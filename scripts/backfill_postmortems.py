#!/usr/bin/env python3
"""
Schicht 1c — Backfill Postmortems
Klassifiziert alle bestehenden CLOSED/WIN/LOSS Trades rückwirkend.
"""
import sqlite3, re, sys, os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'trading.db')

CHINESE_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef\u3000-\u303f]')

GARBAGE_NEWS_MARKERS = [
    'usgs', 'floods and drought', '富途', 'futu', 'futubull',
    'science to keep us safe', 'earthquake magnitude', 'weather forecast',
    'noaa', 'geological survey', 'stocktwits', 'reddit.com'
]


def has_chinese(text):
    return bool(CHINESE_RE.search(text or ''))


def is_garbage_news(notes, strategy):
    n = (notes or '').lower()
    if any(m in n for m in GARBAGE_NEWS_MARKERS):
        return True
    if has_chinese(notes):
        return True
    return False


def auto_lesson(category, ticker, strategy, pnl_eur, slippage_eur=None):
    if category == 'GARBAGE_NEWS':
        return (f"{ticker}/{strategy}: Eröffnung basierend auf nicht-relevanter/unzuverlässiger "
                f"Nachrichtenquelle (USGS, 富途, Reddit etc.). "
                f"Entry Gate hätte diesen Trade verhindert.")
    elif category == 'DUPLICATE':
        return (f"{ticker}/{strategy}: Duplikat-Trade innerhalb kurzer Zeit. "
                f"Gleicher Ticker/Strategie doppelt geöffnet — Entry Gate blockiert das künftig.")
    elif category == 'MARKET_GAP':
        slip = f"{slippage_eur:.2f}€ Slippage" if slippage_eur else "Slippage unbekannt"
        return (f"{ticker}/{strategy}: Stop-Loss durch Gap unterschritten ({slip}). "
                f"Gap-Risiko bei volatilen Titeln vor Events berücksichtigen.")
    elif category == 'REGIME_MISMATCH':
        return (f"{ticker}/{strategy}: AR-Strategie im BEAR-Regime geöffnet. "
                f"Autonomous Radar nur bei NEUTRAL/CORRECTION/BULL aktiv halten.")
    elif category == 'CORRECT_TRADE':
        return (f"{ticker}/{strategy}: Trade korrekt mit P&L +{pnl_eur:.2f}€. "
                f"These validiert und sauber ausgeführt.")
    else:
        return (f"{ticker}/{strategy}: Trade nicht klassifizierbar — manuelle Prüfung empfohlen.")


def schema_setup(conn):
    c = conn.cursor()

    # paper_portfolio neue Spalten
    existing = {r[1] for r in c.execute("PRAGMA table_info(paper_portfolio)").fetchall()}
    new_cols = [
        ("failure_category", "TEXT"),
        ("news_source_tier", "INTEGER"),
        ("slippage_eur", "REAL"),
        ("expected_exit_price", "REAL"),
        ("postmortem_done", "INTEGER DEFAULT 0"),
    ]
    for col, typ in new_cols:
        if col not in existing:
            c.execute(f"ALTER TABLE paper_portfolio ADD COLUMN {col} {typ}")
            print(f"  + Spalte hinzugefügt: {col}")
        else:
            print(f"  ✓ Spalte bereits vorhanden: {col}")

    # trade_postmortems
    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_postmortems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            ticker TEXT,
            strategy TEXT,
            failure_category TEXT,
            root_cause TEXT,
            news_headline TEXT,
            news_source TEXT,
            news_tier INTEGER,
            regime_at_entry TEXT,
            vix_at_entry REAL,
            pnl_eur REAL,
            slippage_eur REAL,
            expected_exit REAL,
            actual_exit REAL,
            lesson TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (trade_id) REFERENCES paper_portfolio(id)
        )
    """)

    # entry_gate_log
    c.execute("""
        CREATE TABLE IF NOT EXISTS entry_gate_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ticker TEXT,
            strategy TEXT,
            gate_triggered TEXT,
            reason TEXT,
            news_headline TEXT,
            news_source TEXT,
            regime TEXT,
            vix REAL
        )
    """)

    conn.commit()
    print("  ✓ Tabellen trade_postmortems + entry_gate_log OK")


def classify_trade(row, all_closed):
    """
    row: (id, ticker, strategy, status, pnl_eur, notes, close_price, stop_price, shares,
          close_date, regime_at_entry, failure_category, postmortem_done)
    """
    (tid, ticker, strategy, status, pnl_eur, notes, close_price,
     stop_price, shares, close_date, regime_at_entry, failure_category, postmortem_done) = row

    notes_str = notes or ''
    strategy_str = strategy or ''
    pnl = pnl_eur or 0.0
    slippage = None

    # 1. GARBAGE_NEWS
    if is_garbage_news(notes_str, strategy_str):
        cat = 'GARBAGE_NEWS'
        # Versuche Source aus notes zu extrahieren
        source = ''
        if ' - ' in notes_str:
            parts = notes_str.split(' - ')
            source = parts[-1].split(' [')[0].strip() if parts else ''
        return cat, slippage, source

    # 2. DUPLICATE: gleicher ticker+strategy, close_date innerhalb 2h
    if close_date:
        try:
            cd = datetime.fromisoformat(str(close_date).replace('Z', ''))
        except Exception:
            cd = None
        if cd:
            for other in all_closed:
                if other[0] == tid:
                    continue
                if other[1] == ticker and other[2] == strategy_str and other[9]:
                    try:
                        ocd = datetime.fromisoformat(str(other[9]).replace('Z', ''))
                        if abs((cd - ocd).total_seconds()) < 7200:
                            return 'DUPLICATE', slippage, ''
                    except Exception:
                        pass

    # 3. MARKET_GAP
    if (close_price is not None and stop_price is not None
            and pnl < 0 and stop_price > 0):
        gap_ratio = (stop_price - close_price) / stop_price
        if gap_ratio > 0.03:
            slip = (close_price - stop_price) * (shares or 1.0)
            return 'MARKET_GAP', slip, ''

    # 4. REGIME_MISMATCH
    if strategy_str.startswith('AR-') and (regime_at_entry or '').upper() == 'BEAR':
        return 'REGIME_MISMATCH', slippage, ''

    # 5. CORRECT_TRADE
    if pnl > 0 or status == 'WIN':
        return 'CORRECT_TRADE', slippage, ''

    return 'UNCLASSIFIED', slippage, ''


def run_backfill(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("\n=== SCHEMA SETUP ===")
    schema_setup(conn)

    print("\n=== BACKFILL POSTMORTEMS ===")

    # Alle closed/win/loss trades laden
    c.execute("""
        SELECT id, ticker, strategy, status, pnl_eur, notes, close_price, stop_price,
               shares, close_date, regime_at_entry, failure_category, postmortem_done
        FROM paper_portfolio
        WHERE status IN ('CLOSED', 'WIN', 'LOSS')
        ORDER BY id
    """)
    all_closed = c.fetchall()
    print(f"Gefundene abgeschlossene Trades: {len(all_closed)}")

    counts = {}
    processed = 0

    for row in all_closed:
        tid = row[0]
        ticker = row[1]
        strategy = row[2] or ''
        pnl_eur = row[4] or 0.0
        notes = row[5] or ''
        close_price = row[6]
        stop_price = row[7]
        shares = row[8]
        regime = row[10]
        postmortem_done = row[12] or 0

        if postmortem_done:
            print(f"  SKIP #{tid} {ticker} — bereits postmortem_done")
            continue

        cat, slippage, source_hint = classify_trade(row, all_closed)
        counts[cat] = counts.get(cat, 0) + 1

        # Slippage in paper_portfolio schreiben
        if slippage is not None:
            c.execute("""
                UPDATE paper_portfolio SET failure_category=?, slippage_eur=?,
                expected_exit_price=?, postmortem_done=1 WHERE id=?
            """, (cat, slippage, stop_price, tid))
        else:
            c.execute("""
                UPDATE paper_portfolio SET failure_category=?, postmortem_done=1 WHERE id=?
            """, (cat, tid))

        # Headline aus notes extrahieren
        headline = ''
        if notes.startswith('AUTO:'):
            headline = notes[5:].split('[EXIT')[0].strip()
            if ' - ' in headline:
                parts = headline.rsplit(' - ', 1)
                headline = parts[0].strip()
                if not source_hint:
                    source_hint = parts[1].strip() if len(parts) > 1 else ''

        lesson = auto_lesson(cat, ticker, strategy, pnl_eur, slippage)

        # Root cause
        root_cause_map = {
            'GARBAGE_NEWS': 'Schlechte News-Quelle (USGS/富途/Reddit) hat Trade ausgelöst',
            'DUPLICATE': 'Gleicher Ticker+Strategy innerhalb 2h doppelt geöffnet',
            'MARKET_GAP': 'Kurs hat Stop per Gap unterschritten — kein sauberer Ausstieg möglich',
            'REGIME_MISMATCH': 'AR-Strategie im BEAR-Markt geöffnet — Regime-Filter fehlte',
            'CORRECT_TRADE': 'Trade korrekt ausgeführt',
            'UNCLASSIFIED': 'Ursache unklar — manuelle Prüfung erforderlich',
        }

        # Prüfen ob Postmortem schon existiert
        c.execute("SELECT id FROM trade_postmortems WHERE trade_id=?", (tid,))
        if c.fetchone():
            processed += 1
            continue

        c.execute("""
            INSERT INTO trade_postmortems
            (trade_id, ticker, strategy, failure_category, root_cause, news_headline,
             news_source, news_tier, regime_at_entry, vix_at_entry, pnl_eur,
             slippage_eur, expected_exit, actual_exit, lesson)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            tid, ticker, strategy, cat,
            root_cause_map.get(cat, ''),
            headline[:200] if headline else '',
            source_hint[:100] if source_hint else '',
            None,  # news_tier — kann später befüllt werden
            regime,
            None,  # vix_at_entry — nicht in DB
            pnl_eur,
            slippage,
            stop_price,   # expected_exit = stop_price
            close_price,  # actual_exit
            lesson
        ))
        processed += 1
        print(f"  #{tid:3d} {ticker:12s} {strategy:12s} → {cat}")

    conn.commit()
    conn.close()

    print(f"\n=== ZUSAMMENFASSUNG ===")
    print(f"Verarbeitete Trades: {processed}")
    print(f"\nKlassifizierung:")
    total = sum(counts.values())
    for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
        pct = 100 * n / total if total else 0
        print(f"  {cat:20s}: {n:3d} ({pct:.0f}%)")

    return counts


if __name__ == '__main__':
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    run_backfill(db)
