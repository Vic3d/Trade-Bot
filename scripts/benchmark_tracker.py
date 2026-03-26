#!/usr/bin/env python3
"""
Benchmark Tracker (Verbesserung 2)
====================================
Speichert täglich SPY + DAX Close-Kurs + Portfolio-Wert in
data/benchmark_history.json.

Format:
{
  "2026-03-26": {
    "spy": 520.5,
    "dax": 22150.0,
    "portfolio_value": 25155.0
  },
  ...
}

Läuft als Teil des Tagesabschlusses (oder standalone via cron).
"""

import json, sqlite3, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
DB_PATH   = WORKSPACE / 'data/trading.db'
BENCH_PATH = WORKSPACE / 'data/benchmark_history.json'


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_yahoo_price(ticker: str) -> float | None:
    """Holt aktuellen Kurs von Yahoo Finance."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        meta = d['chart']['result'][0]['meta']
        return meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
    except Exception as e:
        print(f"  ⚠️ Yahoo {ticker} Fehler: {e}")
        return None


def get_portfolio_value() -> float:
    """Berechne aktuellen Portfolio-Wert: Fund-Cash + offene Positionen (entry_price * shares)."""
    conn = get_db()
    try:
        # Fund-Cash
        cash_row = conn.execute("SELECT value FROM paper_fund WHERE key='cash'").fetchone()
        cash = float(cash_row[0]) if cash_row else 25000.0

        # Offene Day Trades (entry_price × shares als Proxy wenn kein Kurszugriff)
        open_trades = conn.execute("""
            SELECT entry_price, shares FROM trades
            WHERE trade_type='day_trade' AND status='OPEN'
            AND entry_price IS NOT NULL AND shares IS NOT NULL
        """).fetchall()
        trade_value = sum(float(r[0]) * float(r[1]) for r in open_trades)

        # Swing Portfolio
        swing_open = conn.execute("""
            SELECT entry_price, shares FROM paper_portfolio
            WHERE status='OPEN'
            AND entry_price IS NOT NULL AND shares IS NOT NULL
        """).fetchall()
        swing_value = sum(float(r[0]) * float(r[1]) for r in swing_open)

        total = cash + trade_value + swing_value
        return round(total, 2)
    except Exception as e:
        print(f"  ⚠️ Portfolio-Wert Fehler: {e}")
        return 25000.0
    finally:
        conn.close()


def load_history() -> dict:
    if BENCH_PATH.exists():
        try:
            return json.loads(BENCH_PATH.read_text())
        except Exception:
            pass
    return {}


def save_history(history: dict):
    BENCH_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def run():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f"[Benchmark Tracker] {today}")

    spy_price = fetch_yahoo_price('SPY')
    dax_price = fetch_yahoo_price('^GDAXI')
    portfolio_value = get_portfolio_value()

    history = load_history()

    entry = {}
    if spy_price:
        entry['spy'] = round(spy_price, 4)
        print(f"  SPY:       {spy_price:.2f}")
    if dax_price:
        entry['dax'] = round(dax_price, 2)
        print(f"  DAX:       {dax_price:.2f}")
    entry['portfolio_value'] = portfolio_value
    print(f"  Portfolio: {portfolio_value:.2f}€")

    history[today] = entry
    save_history(history)
    print(f"  ✅ Benchmark gespeichert → {BENCH_PATH.name} ({len(history)} Einträge)")
    return entry


if __name__ == '__main__':
    run()
