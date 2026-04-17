#!/usr/bin/env python3
"""
Price Backfill fuer Discovery-Kandidaten — Phase 7.15 Fix
============================================================
Auto-DD braucht >=60 Tage Preis-Historie aus der prices-Tabelle.
Frisch discovered Kandidaten haben 0 Zeilen -> Auto-DD wirft ERROR.

Diese Script:
  1. Liest candidate_tickers.json (status=pending)
  2. Prueft fuer jeden Ticker: SELECT COUNT FROM prices WHERE ticker=?
  3. Wenn <60 Zeilen: yfinance fetch 1y OHLCV + INSERT OR REPLACE in prices

Laeuft im Scheduler zwischen Discovery-Jobs (06:00-06:30) und Auto-DD (07:30).

CLI:
  python3 scripts/discovery/price_backfill.py
  python3 scripts/discovery/price_backfill.py --min-rows 60 --years 1
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))

from candidates import load_candidates  # noqa: E402


def count_prices(conn: sqlite3.Connection, ticker: str) -> int:
    r = conn.execute('SELECT COUNT(*) FROM prices WHERE ticker=?', (ticker,)).fetchone()
    return int(r[0]) if r else 0


def backfill_ticker(conn: sqlite3.Connection, ticker: str, years: int) -> int:
    """Fetcht OHLCV via yfinance und schreibt in prices. Return Anzahl geschrieben."""
    try:
        import yfinance as yf
    except ImportError:
        print('[backfill] yfinance fehlt')
        return 0

    try:
        df = yf.download(
            tickers=ticker, period=f'{years}y', interval='1d',
            auto_adjust=True, progress=False, threads=False,
        )
    except Exception as e:
        print(f'[backfill] {ticker}: download-error {e}')
        return 0

    if df is None or df.empty:
        return 0

    rows = []
    for dt, row in df.dropna().iterrows():
        try:
            o = float(row['Open'].iloc[0]) if hasattr(row['Open'], 'iloc') else float(row['Open'])
            h = float(row['High'].iloc[0]) if hasattr(row['High'], 'iloc') else float(row['High'])
            l = float(row['Low'].iloc[0]) if hasattr(row['Low'], 'iloc') else float(row['Low'])
            c = float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
            v = row['Volume'].iloc[0] if hasattr(row['Volume'], 'iloc') else row['Volume']
            v = int(v) if v == v else 0  # NaN-check
            rows.append((ticker, dt.strftime('%Y-%m-%d'), o, h, l, c, v))
        except Exception:
            continue

    if not rows:
        return 0

    conn.executemany(
        'INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        rows,
    )
    conn.commit()
    return len(rows)


def run(min_rows: int = 60, years: int = 1) -> dict:
    candidates = load_candidates()
    pending = [t for t, e in candidates.items() if e.get('status') == 'pending']
    print(f'[backfill] {len(pending)} pending Kandidaten')

    conn = sqlite3.connect(str(DB))
    try:
        backfilled = 0
        skipped = 0
        failed = 0
        for ticker in pending:
            existing = count_prices(conn, ticker)
            if existing >= min_rows:
                skipped += 1
                continue
            n = backfill_ticker(conn, ticker, years)
            if n > 0:
                backfilled += 1
                print(f'  + {ticker}: {n} Zeilen ({existing} -> {existing + n})')
            else:
                failed += 1
                print(f'  ! {ticker}: FAIL (keine Daten)')
    finally:
        conn.close()

    print(f'[backfill] backfilled={backfilled} skipped={skipped} failed={failed}')
    return {'status': 'ok', 'backfilled': backfilled, 'skipped': skipped, 'failed': failed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-rows', type=int, default=60)
    ap.add_argument('--years', type=int, default=1)
    args = ap.parse_args()
    result = run(min_rows=args.min_rows, years=args.years)
    sys.exit(0 if result.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
