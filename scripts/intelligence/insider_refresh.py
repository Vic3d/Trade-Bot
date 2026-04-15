#!/usr/bin/env python3
"""
Insider Signal Refresh — Phase 10

Täglicher Batch-Refresh für alle aktiven Portfolio-Ticker + Watchlist.
Ziel: Cache frisch halten, damit conviction_scorer ohne Latenz arbeitet.

Läuft 1x täglich am Morgen (07:30 CET), bevor der erste Scan beginnt.
"""
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))

from intelligence.sec_edgar import insider_signal  # noqa: E402

DB = WS / 'data' / 'trading.db'
STRATS = WS / 'data' / 'strategies.json'

log = logging.getLogger('insider_refresh')


def _tickers_from_portfolio() -> set[str]:
    out: set[str] = set()
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute("SELECT DISTINCT ticker FROM trades WHERE status='OPEN'").fetchall()
        for r in rows:
            if r[0]:
                out.add(r[0].upper())
        c.close()
    except Exception as e:
        log.warning(f'portfolio fetch failed: {e}')
    return out


def _tickers_from_strategies() -> set[str]:
    out: set[str] = set()
    try:
        raw = json.loads(STRATS.read_text(encoding='utf-8'))
        for sid, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            t = cfg.get('ticker')
            if t:
                out.add(str(t).upper())
    except Exception as e:
        log.warning(f'strategies fetch failed: {e}')
    return out


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    tickers = _tickers_from_portfolio() | _tickers_from_strategies()
    # Strip .DE / .PA etc. (SEC hat nur US-Tickers)
    us_tickers = {t for t in tickers if '.' not in t and '-' not in t}
    non_us = tickers - us_tickers

    print(f'Insider Refresh: {len(us_tickers)} US tickers, {len(non_us)} non-US skipped')
    if non_us:
        print(f'  skipped: {", ".join(sorted(non_us))}')

    stats = {'BULLISH': 0, 'BEARISH': 0, 'NEUTRAL': 0, 'error': 0}
    for t in sorted(us_tickers):
        try:
            sig = insider_signal(t, days=30, use_cache=False)
            bias = sig.get('bias', 'NEUTRAL')
            stats[bias] = stats.get(bias, 0) + 1
            marker = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '⚪'}[bias]
            print(f'  {marker} {t:6} score={sig["score"]:+4d}  {sig["reason"][:60]}')
        except Exception as e:
            stats['error'] += 1
            print(f'  ❌ {t}: {e}')

    print(f'\nSummary: 🟢 {stats["BULLISH"]} | 🔴 {stats["BEARISH"]} | '
          f'⚪ {stats["NEUTRAL"]} | err {stats["error"]}')


if __name__ == '__main__':
    main()
