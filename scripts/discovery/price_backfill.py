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


def _fetch_yfinance(ticker: str, years: int) -> list:
    """Yahoo via Ticker().history — robuster als yf.download fuer single-ticker."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=f'{years}y', interval='1d', auto_adjust=True)
    except Exception as e:
        print(f'[backfill] {ticker}: yf-history-error {e}')
        return []
    if df is None or df.empty:
        return []
    rows = []
    for dt, row in df.dropna().iterrows():
        try:
            rows.append((ticker, dt.strftime('%Y-%m-%d'),
                         float(row['Open']), float(row['High']),
                         float(row['Low']), float(row['Close']),
                         int(row['Volume']) if row['Volume'] == row['Volume'] else 0))
        except Exception:
            continue
    return rows


def _fetch_stooq(ticker: str) -> list:
    """
    Stooq-Fallback fuer deutsche/EU-Ticker die Yahoo nicht hat.
    Beispiele: BMW.DE -> bmw.de, MC.PA -> mc.fr (Stooq-Konvention).
    Gibt leere Liste zurueck wenn Stooq die Boerse nicht kennt.
    """
    import urllib.request
    import urllib.error

    t = ticker.lower().strip()
    # Stooq-Boersen-Mapping
    suffix_map = {
        '.de': '.de', '.pa': '.fr', '.mi': '.it', '.as': '.nl',
        '.l': '.uk', '.ol': '.no', '.st': '.se', '.hk': '.hk',
    }
    stooq_sym = t
    mapped = False
    for suf, stooq_suf in suffix_map.items():
        if t.endswith(suf):
            stooq_sym = t[:-len(suf)] + stooq_suf
            mapped = True
            break
    if not mapped and '.' not in t:
        # US-Ticker ohne Suffix → bereits Yahoo-Domain, Stooq nutzt us-Suffix
        stooq_sym = t + '.us'

    url = f'https://stooq.com/q/d/l/?s={stooq_sym}&i=d'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, TimeoutError) as e:
        print(f'[backfill] {ticker}: stooq-error {e}')
        return []

    lines = text.strip().split('\n')
    if len(lines) < 2 or not lines[0].lower().startswith('date'):
        return []

    rows = []
    for ln in lines[1:]:
        parts = ln.split(',')
        if len(parts) < 6:
            continue
        try:
            d, o, h, l, c = parts[0], float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            v = int(float(parts[5])) if parts[5] else 0
            rows.append((ticker, d, o, h, l, c, v))
        except (ValueError, IndexError):
            continue
    return rows


def backfill_ticker(conn: sqlite3.Connection, ticker: str, years: int) -> int:
    """Yahoo primaer, Stooq-Fallback. Return Anzahl geschriebener Zeilen."""
    rows = _fetch_yfinance(ticker, years)
    source = 'yahoo'
    if not rows:
        rows = _fetch_stooq(ticker)
        source = 'stooq'
    if not rows:
        return 0

    conn.executemany(
        'INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        rows,
    )
    conn.commit()
    print(f'  + {ticker}: {len(rows)} Zeilen via {source}')
    return len(rows)


def _load_active_strategy_tickers() -> list:
    """Ticker aus allen aktiven + watchlist Strategien extrahieren."""
    strat_file = WS / 'data' / 'strategies.json'
    if not strat_file.exists():
        return []
    try:
        import json as _json
        strats = _json.loads(strat_file.read_text(encoding='utf-8'))
    except Exception:
        return []
    active_tickers = set()
    for sid, s in strats.items():
        if not isinstance(s, dict):
            continue
        if s.get('status') in ('active', 'watchlist', 'watching', 'probation'):
            for t in s.get('tickers', []) or []:
                if t:
                    active_tickers.add(str(t).upper())
    return sorted(active_tickers)


def run(min_rows: int = 60, years: int = 1) -> dict:
    candidates = load_candidates()
    pending = [t for t, e in candidates.items() if e.get('status') == 'pending']
    active = _load_active_strategy_tickers()
    # Merge: pending Kandidaten + aktive Strategy-Ticker (dedupe)
    all_targets = list({*pending, *active})
    print(f'[backfill] {len(pending)} pending + {len(active)} active = {len(all_targets)} Ticker')
    pending = all_targets

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
