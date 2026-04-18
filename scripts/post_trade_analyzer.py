#!/usr/bin/env python3
"""
Schicht 3 — Post-Trade Analyzer
Analysiert neue CLOSED Trades, erkennt Patterns, generiert Berichte.
"""
import sqlite3, re, os, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')

DB_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'trading.db')

CHINESE_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef]')

GARBAGE_MARKERS = [
    'usgs', 'floods and drought', '富途', 'futu', 'futubull',
    'science to keep us safe', 'earthquake magnitude', 'weather forecast',
    'noaa', 'geological survey', 'stocktwits', 'reddit.com',
    'samsung union strike', 'union strike vote'
]


def has_chinese(text):
    return bool(CHINESE_RE.search(text or ''))


def is_garbage_news(notes):
    n = (notes or '').lower()
    if any(m in n for m in GARBAGE_MARKERS):
        return True
    if has_chinese(notes):
        return True
    return False


def classify(row, all_closed):
    """
    row: (id, ticker, strategy, status, pnl_eur, notes, close_price, stop_price,
          shares, close_date, regime_at_entry)
    """
    (tid, ticker, strategy, status, pnl_eur, notes, close_price,
     stop_price, shares, close_date, regime) = row

    pnl = pnl_eur or 0.0
    strategy = strategy or ''
    notes_str = notes or ''
    slippage = None

    if is_garbage_news(notes_str):
        return 'GARBAGE_NEWS', slippage

    # Duplicate check
    if close_date:
        try:
            cd = datetime.fromisoformat(str(close_date).replace('Z', ''))
        except Exception:
            cd = None
        if cd:
            for other in all_closed:
                if other[0] == tid:
                    continue
                if other[1] == ticker and (other[2] or '') == strategy and other[9]:
                    try:
                        ocd = datetime.fromisoformat(str(other[9]).replace('Z', ''))
                        if abs((cd - ocd).total_seconds()) < 7200:
                            return 'DUPLICATE', slippage
                    except Exception:
                        pass

    # Market Gap
    if (close_price is not None and stop_price is not None
            and pnl < 0 and stop_price > 0):
        gap = (stop_price - close_price) / stop_price
        if gap > 0.03:
            slip = (close_price - stop_price) * (shares or 1.0)
            return 'MARKET_GAP', slip

    # Regime Mismatch
    if strategy.startswith('AR-') and (regime or '').upper() == 'BEAR':
        return 'REGIME_MISMATCH', slippage

    # Correct Trade
    if pnl > 0 or status == 'WIN':
        return 'CORRECT_TRADE', slippage

    return 'UNCLASSIFIED', slippage


def auto_lesson(category, ticker, strategy, pnl_eur, slippage=None):
    if category == 'GARBAGE_NEWS':
        return (f"{ticker}/{strategy}: Garbage-News-Quelle hat Trade ausgelöst. "
                "Entry Gate blockiert das künftig.")
    elif category == 'DUPLICATE':
        return f"{ticker}/{strategy}: Duplikat innerhalb 2h — Entry Gate verhindert das."
    elif category == 'MARKET_GAP':
        slip = f"{slippage:.2f}€" if slippage else "?"
        return f"{ticker}/{strategy}: Gap-Stop ({slip} Slippage). Gap-Risiko vor Events beachten."
    elif category == 'REGIME_MISMATCH':
        return f"{ticker}/{strategy}: AR-Trade im BEAR-Regime — Regime-Filter jetzt aktiv."
    elif category == 'CORRECT_TRADE':
        return f"{ticker}/{strategy}: Trade korrekt, P&L +{pnl_eur:.2f}€."
    return f"{ticker}/{strategy}: Unklar — manuelle Prüfung."


def analyze_new_closed_trades(db_path=None):
    """Neue CLOSED Trades ohne postmortem_done=1 analysieren."""
    db_path = db_path or DB_DEFAULT
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Ensure columns exist
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

    # Ensure tables exist
    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_postmortems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            ticker TEXT, strategy TEXT, failure_category TEXT,
            root_cause TEXT, news_headline TEXT, news_source TEXT,
            news_tier INTEGER, regime_at_entry TEXT, vix_at_entry REAL,
            pnl_eur REAL, slippage_eur REAL, expected_exit REAL, actual_exit REAL,
            lesson TEXT, created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (trade_id) REFERENCES paper_portfolio(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS entry_gate_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
            ticker TEXT, strategy TEXT, gate_triggered TEXT, reason TEXT,
            news_headline TEXT, news_source TEXT, regime TEXT, vix REAL
        )
    """)
    conn.commit()

    # Load all closed for context (duplicate detection) — deduplicated by ticker+strategy+date
    DEDUP_QUERY = """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY ticker, strategy, DATE(entry_date)
                ORDER BY id
            ) as rn
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
        )
        SELECT id, ticker, strategy, status, pnl_eur, notes, close_price, stop_price,
               shares, close_date, regime_at_entry
        FROM ranked WHERE rn = 1
    """
    c.execute(DEDUP_QUERY)
    all_closed = c.fetchall()

    # Unprocessed trades
    c.execute("""
        SELECT id, ticker, strategy, status, pnl_eur, notes, close_price, stop_price,
               shares, close_date, regime_at_entry
        FROM paper_portfolio
        WHERE status IN ('CLOSED', 'WIN', 'LOSS')
        AND (postmortem_done IS NULL OR postmortem_done = 0)
    """)
    unprocessed = c.fetchall()

    new_postmortems = 0
    for row in unprocessed:
        tid = row[0]
        ticker = row[1]
        strategy = row[2] or ''
        pnl_eur = row[4] or 0.0
        notes = row[5] or ''
        close_price = row[6]
        stop_price = row[7]
        shares = row[8]
        regime = row[10]

        cat, slippage = classify(row, all_closed)

        # Update paper_portfolio
        if slippage is not None:
            c.execute("""
                UPDATE paper_portfolio SET failure_category=?, slippage_eur=?,
                expected_exit_price=?, postmortem_done=1 WHERE id=?
            """, (cat, slippage, stop_price, tid))
        else:
            c.execute("""
                UPDATE paper_portfolio SET failure_category=?, postmortem_done=1 WHERE id=?
            """, (cat, tid))

        # Extract headline/source from notes
        headline = ''
        source = ''
        if notes.startswith('AUTO:'):
            raw = notes[5:].split('[EXIT')[0].strip()
            if ' - ' in raw:
                parts = raw.rsplit(' - ', 1)
                headline = parts[0].strip()
                source = parts[1].strip() if len(parts) > 1 else ''
            else:
                headline = raw

        # Check if postmortem exists
        c.execute("SELECT id FROM trade_postmortems WHERE trade_id=?", (tid,))
        if c.fetchone():
            continue

        root_causes = {
            'GARBAGE_NEWS': 'Schlechte News-Quelle (USGS/富途/Reddit)',
            'DUPLICATE': 'Gleicher Ticker+Strategy doppelt geöffnet',
            'MARKET_GAP': 'Stop per Gap unterschritten',
            'REGIME_MISMATCH': 'AR-Trade im BEAR-Regime',
            'CORRECT_TRADE': 'Korrekt ausgeführt',
            'UNCLASSIFIED': 'Ursache unklar',
        }

        lesson = auto_lesson(cat, ticker, strategy, pnl_eur, slippage)
        c.execute("""
            INSERT INTO trade_postmortems
            (trade_id, ticker, strategy, failure_category, root_cause,
             news_headline, news_source, regime_at_entry, pnl_eur,
             slippage_eur, expected_exit, actual_exit, lesson)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            tid, ticker, strategy, cat, root_causes.get(cat, ''),
            headline[:200], source[:100], regime, pnl_eur,
            slippage, stop_price, close_price, lesson
        ))
        new_postmortems += 1

    conn.commit()
    conn.close()
    print(f"[POSTMORTEM] {new_postmortems} neue Postmortems erstellt.")
    return new_postmortems


def detect_patterns(db_path=None, days=14):
    """Erkennt wiederkehrende Fehler-Patterns."""
    db_path = db_path or DB_DEFAULT
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    cutoff = (datetime.now(_BERLIN) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    patterns = []

    try:
        # GARBAGE_NEWS häufung
        c.execute("""
            SELECT COUNT(*) FROM trade_postmortems
            WHERE failure_category='GARBAGE_NEWS'
            AND created_at > ?
        """, (cutoff,))
        n = c.fetchone()[0]
        if n >= 3:
            patterns.append(f"⚠️ PATTERN: {n}x GARBAGE_NEWS in {days} Tagen — "
                            "Entry Gate schützt jetzt davor.")

        # REGIME_MISMATCH
        c.execute("""
            SELECT COUNT(*) FROM trade_postmortems
            WHERE failure_category='REGIME_MISMATCH'
            AND created_at > ?
        """, (cutoff,))
        n = c.fetchone()[0]
        if n >= 2:
            patterns.append(f"⚠️ PATTERN: {n}x REGIME_MISMATCH in {days} Tagen — "
                            "AR-Strategien im BEAR-Markt nicht aktivieren.")

        # DUPLICATE
        c.execute("""
            SELECT COUNT(*) FROM trade_postmortems
            WHERE failure_category='DUPLICATE'
            AND created_at > ?
        """, (cutoff,))
        n = c.fetchone()[0]
        if n >= 2:
            patterns.append(f"⚠️ PATTERN: {n}x DUPLICATE in {days} Tagen — "
                            "bereits_im_portfolio Check vor jedem Trade.")

        # MARKET_GAP
        c.execute("""
            SELECT COUNT(*) FROM trade_postmortems
            WHERE failure_category='MARKET_GAP'
            AND created_at > ?
        """, (cutoff,))
        n = c.fetchone()[0]
        if n >= 2:
            patterns.append(f"⚠️ PATTERN: {n}x MARKET_GAP in {days} Tagen — "
                            "Gaps bei News-Events einkalkulieren.")

        # Total LOSS rate
        c.execute("""
            SELECT COUNT(*), SUM(pnl_eur) FROM trade_postmortems
            WHERE created_at > ?
        """, (cutoff,))
        row = c.fetchone()
        total, total_pnl = row
        if total and total_pnl is not None and total_pnl < -500:
            patterns.append(f"🔴 HOHER VERLUST: {total_pnl:.0f}€ in {days} Tagen "
                            f"über {total} Trades.")

        # Top failing strategy
        c.execute("""
            SELECT strategy, COUNT(*) as n, SUM(pnl_eur) as pnl
            FROM trade_postmortems
            WHERE failure_category NOT IN ('CORRECT_TRADE')
            AND created_at > ?
            GROUP BY strategy
            ORDER BY pnl ASC
            LIMIT 1
        """, (cutoff,))
        worst = c.fetchone()
        if worst and worst[2] is not None and worst[2] < -200:
            patterns.append(f"📉 SCHLECHTESTE STRATEGIE: {worst[0]} "
                            f"({worst[1]} Miss-Trades, {worst[2]:.0f}€ P&L)")

    except Exception as e:
        patterns.append(f"[Pattern-Erkennung Fehler: {e}]")

    conn.close()
    return patterns


def generate_summary(db_path=None, days=7):
    """Formatierter Discord-kompatibler Wochenbericht."""
    db_path = db_path or DB_DEFAULT
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    cutoff = (datetime.now(_BERLIN) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    today = datetime.now(_BERLIN).strftime('%Y-%m-%d')

    try:
        # Gesamtstatistik
        c.execute("""
            SELECT COUNT(*), SUM(pnl_eur),
                   SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN pnl_eur <= 0 THEN 1 ELSE 0 END)
            FROM trade_postmortems WHERE created_at > ?
        """, (cutoff,))
        row = c.fetchone()
        total, sum_pnl, wins, losses = row
        total = total or 0
        sum_pnl = sum_pnl or 0.0
        wins = wins or 0
        losses = losses or 0

        win_rate = (wins / total * 100) if total else 0

        # Kategorien
        c.execute("""
            SELECT failure_category, COUNT(*), SUM(pnl_eur)
            FROM trade_postmortems WHERE created_at > ?
            GROUP BY failure_category ORDER BY COUNT(*) DESC
        """, (cutoff,))
        cats = c.fetchall()

        # Offene Positionen
        c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'")
        open_pos = c.fetchone()[0]

        # Entry Gate Blocks
        try:
            c.execute("""
                SELECT COUNT(*), gate_triggered
                FROM entry_gate_log
                WHERE timestamp > ?
                GROUP BY gate_triggered ORDER BY COUNT(*) DESC
            """, (cutoff,))
            gate_blocks = c.fetchall()
        except Exception:
            gate_blocks = []

        # Top Winner / Loser
        c.execute("""
            SELECT ticker, strategy, pnl_eur FROM trade_postmortems
            WHERE created_at > ? ORDER BY pnl_eur DESC LIMIT 1
        """, (cutoff,))
        top_winner = c.fetchone()

        c.execute("""
            SELECT ticker, strategy, pnl_eur FROM trade_postmortems
            WHERE created_at > ? ORDER BY pnl_eur ASC LIMIT 1
        """, (cutoff,))
        top_loser = c.fetchone()

    except Exception as e:
        conn.close()
        return f"[FEHLER beim Report: {e}]"

    conn.close()

    # Patterns
    patterns = detect_patterns(db_path, days=days)

    # Report formatieren
    lines = [
        f"📊 **Weekly Miss-Trade Report** — {today}",
        f"Zeitraum: letzte {days} Tage",
        "",
        f"**Gesamt:** {total} Trades | P&L: {sum_pnl:+.0f}€ | WinRate: {win_rate:.0f}%",
        f"Wins: {wins} | Losses: {losses} | Offene Positionen: {open_pos}",
        "",
        "**Klassifizierung:**",
    ]

    cat_emoji = {
        'CORRECT_TRADE': '✅',
        'GARBAGE_NEWS': '🗑️',
        'REGIME_MISMATCH': '⚠️',
        'DUPLICATE': '🔄',
        'MARKET_GAP': '📉',
        'UNCLASSIFIED': '❓',
    }

    for cat, n, pnl in cats:
        emoji = cat_emoji.get(cat, '•')
        pnl_str = f"{pnl:+.0f}€" if pnl is not None else "n/a"
        lines.append(f"  {emoji} {cat}: {n}x ({pnl_str})")

    if top_winner and top_winner[2]:
        lines.append(f"\n🏆 **Bester Trade:** {top_winner[0]} ({top_winner[1]}) +{top_winner[2]:.0f}€")
    if top_loser and top_loser[2]:
        lines.append(f"💀 **Schlechtester:** {top_loser[0]} ({top_loser[1]}) {top_loser[2]:.0f}€")

    if gate_blocks:
        lines.append(f"\n🚦 **Entry Gate Blocks ({days}d):**")
        for n, gate in gate_blocks:
            lines.append(f"  • {gate}: {n}x")

    if patterns:
        lines.append(f"\n**Erkannte Patterns:**")
        for p in patterns:
            lines.append(f"  {p}")
    else:
        lines.append(f"\n✅ Keine kritischen Patterns erkannt.")

    lines.append(f"\n_Generiert: {datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M')} — Albert 🎩_")

    return "\n".join(lines)


if __name__ == '__main__':
    if '--summary' in sys.argv or '--weekly-report' in sys.argv:
        days = 7
        print(generate_summary(DB_DEFAULT, days=days))
    else:
        analyze_new_closed_trades(DB_DEFAULT)
        pats = detect_patterns(DB_DEFAULT)
        if pats:
            print("\n=== PATTERNS ===")
            for p in pats:
                print(p)
        else:
            print("Keine kritischen Patterns erkannt.")
