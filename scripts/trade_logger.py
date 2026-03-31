#!/usr/bin/env python3
"""
trade_logger.py — Victor's Trade Journal Auto-Logger
=====================================================
Nimmt Victors natürliche Trade-Strings und loggt sie in trading.db.

Usage:
  python3 trade_logger.py "EQNR long 28.40 Stop 27 S1"
  python3 trade_logger.py "PLTR exit 124.50 Stop hit"
  python3 trade_logger.py "BAYN.DE long 39.95 Stop 38 S3"
  python3 trade_logger.py --list         → letzte 10 Einträge anzeigen

Parser erkennt:
  - Ticker: 1–5 Großbuchstaben + optional .DE/.OL/.L/.AS/.PA
  - Direction: long / short / exit / sell / close
  - Preis: erste Zahl nach Direction
  - Stop: Zahl nach "Stop" (wenn numerisch, sonst None)
  - Strategie: S1–S10 oder PS_xyz

Verknüpft außerdem die letzten 5 overnight_events für diesen Ticker
und schreibt sie als JSON in das notes-Feld.
"""

import re
import sys
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'


# ── DB-Setup ─────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_table(conn: sqlite3.Connection):
    """Tabelle anlegen falls nicht vorhanden."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT,
            direction   TEXT,
            price       REAL,
            stop_price  REAL,
            strategy    TEXT,
            logged_at   TEXT DEFAULT (datetime('now')),
            notes       TEXT,
            raw_input   TEXT
        )
    """)
    conn.commit()


# ── Parser ────────────────────────────────────────────────────────────────────

# Ticker: 1–5 Großbuchstaben + optionale Exchange-Suffix
TICKER_PATTERN = re.compile(
    r'\b([A-Z]{1,5}(?:\.(?:DE|OL|L|AS|PA))?)\b'
)

DIRECTION_WORDS = {
    'long': 'long',
    'short': 'short',
    'exit': 'exit',
    'sell': 'sell',
    'close': 'close',
    'buy': 'long',   # Alias
}

# Strategie: S1–S10 oder PS_anything
STRATEGY_PATTERN = re.compile(
    r'\b(S(?:[1-9]|10)|PS_[A-Za-z0-9_]+)\b'
)

# Preis: numerisch (z.B. 28.40, 1234, 0.55)
PRICE_PATTERN = re.compile(r'\b(\d+(?:[.,]\d+)?)\b')

# Stop: nach dem Wort "Stop" oder "stop"
STOP_PATTERN = re.compile(r'[Ss]top\s+(\d+(?:[.,]\d+)?)')


def parse_trade_string(raw: str) -> dict:
    """
    Parsed Victors Trade-String in strukturierte Felder.

    Returns:
        dict mit ticker, direction, price, stop_price, strategy
        (fehlende Felder = None)
    """
    result = {
        'ticker': None,
        'direction': None,
        'price': None,
        'stop_price': None,
        'strategy': None,
        '_parse_notes': [],
    }

    # Wir arbeiten case-insensitiv für Keywords, aber Ticker bleibt als-is
    raw_upper = raw.upper()
    raw_lower = raw.lower()

    # 1. Direction suchen
    for word, normalized in DIRECTION_WORDS.items():
        if re.search(r'\b' + word + r'\b', raw_lower):
            result['direction'] = normalized
            break

    # 2. Ticker: erstes CAPS-Token VOR der Direction
    # Suche Ticker vor dem Direction-Wort
    dir_match = None
    if result['direction']:
        # Finde Position des Direction-Words im Originalstring
        dir_word = next(
            (w for w in DIRECTION_WORDS if re.search(r'\b' + w + r'\b', raw_lower)),
            None
        )
        if dir_word:
            dir_pos = raw_lower.find(dir_word)
            before_dir = raw[:dir_pos].strip()
            ticker_candidates = TICKER_PATTERN.findall(before_dir.upper())
            if ticker_candidates:
                result['ticker'] = ticker_candidates[-1]  # Letztes CAPS-Token vor Direction
                result['_parse_notes'].append(f"Ticker aus '{before_dir}'")

    # Fallback: erstes CAPS-Token im String
    if not result['ticker']:
        all_caps = TICKER_PATTERN.findall(raw)
        # Filter: kein Keyword (STOP, LONG, etc.)
        skip_words = {'STOP', 'LONG', 'SHORT', 'EXIT', 'SELL', 'CLOSE', 'BUY', 'HIT'}
        for t in all_caps:
            if t.upper() not in skip_words:
                result['ticker'] = t
                break

    # 3. Stop-Preis (VOR dem Haupt-Preis suchen, damit wir nicht verwirrt werden)
    stop_match = STOP_PATTERN.search(raw)
    if stop_match:
        stop_str = stop_match.group(1).replace(',', '.')
        try:
            result['stop_price'] = float(stop_str)
        except ValueError:
            pass  # "Stop hit" o.ä. → kein numerischer Stop

    # 4. Preis: erste Zahl NACH Direction und NICHT die Stop-Zahl
    if result['direction']:
        dir_word = next(
            (w for w in DIRECTION_WORDS if re.search(r'\b' + w + r'\b', raw_lower)),
            None
        )
        if dir_word:
            dir_end = raw_lower.find(dir_word) + len(dir_word)
            after_dir = raw[dir_end:]
            # Entferne Stop-Bereich aus der Suche
            stop_area = STOP_PATTERN.sub('', after_dir)
            prices_found = PRICE_PATTERN.findall(stop_area)
            if prices_found:
                try:
                    result['price'] = float(prices_found[0].replace(',', '.'))
                except ValueError:
                    pass

    # 5. Strategie
    strat_match = STRATEGY_PATTERN.search(raw)
    if strat_match:
        result['strategy'] = strat_match.group(1)

    return result


# ── News-Verknüpfung ─────────────────────────────────────────────────────────

def fetch_recent_news(conn: sqlite3.Connection, ticker: str, limit: int = 5) -> list[dict]:
    """
    Holt die letzten N overnight_events für diesen Ticker.
    Matching: Ticker-Name im Headline-Text (case-insensitive).
    """
    # Ticker ohne Exchange-Suffix für Suche
    base_ticker = ticker.split('.')[0]

    rows = conn.execute("""
        SELECT event_id, timestamp, headline, source, impact_direction, novelty_score
        FROM overnight_events
        WHERE LOWER(headline) LIKE ?
           OR LOWER(headline) LIKE ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (
        f'%{base_ticker.lower()}%',
        f'%{ticker.lower()}%',
        limit
    )).fetchall()

    return [dict(r) for r in rows]


def format_news_summary(news_items: list[dict]) -> str:
    """Kurze Zusammenfassung der verknüpften News für Konsolen-Output."""
    if not news_items:
        return "Keine verwandten NewsWire-Events gefunden."
    lines = [f"  → {n['timestamp'][:16]} [{n['impact_direction']}] {n['headline'][:80]}"
             for n in news_items]
    return "\n".join(lines)


# ── Hauptlogik ────────────────────────────────────────────────────────────────

def log_trade(raw_input: str) -> dict:
    """
    Parsed, verknüpft News und schreibt in DB.

    Returns:
        dict mit id und geparsten Feldern
    """
    parsed = parse_trade_string(raw_input)

    conn = get_conn()
    init_table(conn)

    # News-Verknüpfung
    news_items = []
    if parsed['ticker']:
        news_items = fetch_recent_news(conn, parsed['ticker'])

    notes_json = json.dumps(news_items, ensure_ascii=False) if news_items else None

    # In DB schreiben
    logged_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("""
        INSERT INTO trade_journal (ticker, direction, price, stop_price, strategy, logged_at, notes, raw_input)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        parsed['ticker'],
        parsed['direction'],
        parsed['price'],
        parsed['stop_price'],
        parsed['strategy'],
        logged_at,
        notes_json,
        raw_input,
    ))
    conn.commit()
    trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    parsed['id'] = trade_id
    parsed['logged_at'] = logged_at
    parsed['news_count'] = len(news_items)
    parsed['news_items'] = news_items

    return parsed


def print_result(parsed: dict, raw: str):
    """Gibt Bestätigung + News-Zusammenfassung aus."""
    print(f"\n✅ Trade #{parsed['id']} geloggt — {parsed['logged_at']}")
    print(f"   Input:     {raw}")
    print(f"   Ticker:    {parsed['ticker'] or '⚠️ nicht erkannt'}")
    print(f"   Direction: {parsed['direction'] or '⚠️ nicht erkannt'}")
    print(f"   Preis:     {parsed['price'] or '⚠️ nicht erkannt'}")
    print(f"   Stop:      {parsed['stop_price'] or '—'}")
    print(f"   Strategie: {parsed['strategy'] or '—'}")

    if parsed['news_count'] > 0:
        print(f"\n📰 Verknüpfte NewsWire-Events ({parsed['news_count']}):")
        print(format_news_summary(parsed['news_items']))
    else:
        print(f"\n📰 Keine verwandten NewsWire-Events für {parsed['ticker']} gefunden.")


def list_recent(n: int = 10):
    """Zeigt letzte N Einträge aus trade_journal."""
    conn = get_conn()
    init_table(conn)
    rows = conn.execute(
        "SELECT id, ticker, direction, price, stop_price, strategy, logged_at, raw_input "
        "FROM trade_journal ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()

    if not rows:
        print("📋 Keine Einträge in trade_journal")
        return

    print(f"📋 Letzte {len(rows)} Trade-Journal-Einträge:")
    print(f"{'ID':>4}  {'Ticker':<12} {'Dir':<8} {'Preis':>8} {'Stop':>8} {'Strat':<8} Geloggt")
    print("─" * 75)
    for r in rows:
        print(f"{r['id']:>4}  {(r['ticker'] or '?'):<12} {(r['direction'] or '?'):<8} "
              f"{r['price'] or 0:>8.2f} {r['stop_price'] or 0:>8.2f} "
              f"{(r['strategy'] or '—'):<8} {r['logged_at'][:16]}")
        print(f"       {r['raw_input']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print('  python3 trade_logger.py "EQNR long 28.40 Stop 27 S1"')
        print('  python3 trade_logger.py "PLTR exit 124.50 Stop hit"')
        print('  python3 trade_logger.py --list')
        sys.exit(1)

    if sys.argv[1] == '--list':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        list_recent(n)
    else:
        raw = " ".join(sys.argv[1:])
        result = log_trade(raw)
        print_result(result, raw)
