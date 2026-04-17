#!/usr/bin/env python3
"""
Regime Cache Refresh — Prerequisite fuer regime_detector.py
=============================================================
Laedt ^GSPC / ^VIX / ^TNX in data/price_cache/ wenn
  (a) die Files fehlen ODER
  (b) aelter als 20h sind.

Wird im Scheduler ~10min vor regime_detector ausgefuehrt.
Behebt den "S&P 500 Daten nicht gefunden"-Crash wenn die price_cache
zwischen Backtest-Laeufen (So+Mi) stale wird.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
CACHE = WS / 'data' / 'price_cache'
MAX_AGE_HOURS = 20

TICKERS = [('^GSPC', 'IXGSPC'), ('^VIX', 'IXVIX'), ('^TNX', 'IXTNX')]


def needs_refresh(dst: str) -> bool:
    f = CACHE / f'{dst}.json'
    if not f.exists():
        return True
    age_h = (datetime.now().timestamp() - f.stat().st_mtime) / 3600
    return age_h >= MAX_AGE_HOURS


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(WS / 'scripts'))
    from backtest_engine import download_data

    refreshed = 0
    for src, dst in TICKERS:
        if not needs_refresh(dst):
            print(f'[regime-cache] {dst}: frisch, skip')
            continue
        bars = download_data(src, years=5)
        if bars:
            (CACHE / f'{dst}.json').write_text(json.dumps(bars))
            print(f'[regime-cache] {src} -> {dst}.json: {len(bars)} Bars')
            refreshed += 1
        else:
            print(f'[regime-cache] {src}: FAIL')

    print(f'[regime-cache] {refreshed}/{len(TICKERS)} refreshed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
