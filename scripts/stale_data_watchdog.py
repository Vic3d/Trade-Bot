#!/usr/bin/env python3
"""
Stale Data Watchdog — Phase 4.3
================================
Prüft ob Preis-Daten für ACTIVE Tickers (offene Positionen + aktive Strategien
+ deep-dive-verdicts) aktuell sind. Sendet Discord-Alert wenn:
  - Open position: Preis > 2 Tage alt → KRITISCH (Stop-Loss blind)
  - Active strategy ticker: Preis > 3 Tage alt → WARNUNG
  - Watchlist ticker: Preis > 5 Tage alt → INFO

Warum:
  Am 04.04. wurde BA.L mit exit_type=MANUAL_STALE_DATA geschlossen — Victor
  musste manuell eingreifen weil der Stop-Loss wegen veralteter Preise nicht
  triggern konnte. Das darf nicht nochmal passieren.

Läuft alle 2h während Handelszeit (09-22h CET).

Usage:
  python3 scripts/stale_data_watchdog.py
  python3 scripts/stale_data_watchdog.py --no-alert
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB = DATA / 'trading.db'

# Thresholds in days
THRESH_OPEN     = 2   # offene Position — stop-loss-relevant
THRESH_STRATEGY = 3   # aktive strategy mit tickers
THRESH_WATCHLIST = 5  # watchlist only


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _latest_price_date(conn: sqlite3.Connection, ticker: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(date) FROM prices WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    return row[0] if row and row[0] else None


def _age_days(date_str: str) -> int | None:
    try:
        d = datetime.fromisoformat(date_str[:10]).date()
        return (datetime.now(_BERLIN).date() - d).days
    except Exception:
        return None


def run(alert: bool = True) -> dict:
    conn = sqlite3.connect(str(DB))

    # 1. Open positions
    open_tickers = [row[0] for row in conn.execute(
        "SELECT DISTINCT ticker FROM paper_portfolio WHERE UPPER(status) = 'OPEN'"
    )]

    # 2. Active strategies → tickers
    strategies = _load_json(DATA / 'strategies.json', {})
    strategy_tickers = set()
    for sid, s in strategies.items():
        if not isinstance(s, dict):
            continue
        if str(s.get('status', 'active')).lower() in ('inactive', 'blocked', 'suspended'):
            continue
        for t in s.get('tickers', []):
            strategy_tickers.add(str(t).upper())

    # 3. Verdicts → tickers
    verdicts = _load_json(DATA / 'deep_dive_verdicts.json', {})
    verdict_tickers = set(verdicts.keys())

    open_set = set(t.upper() for t in open_tickers)
    strategy_only = strategy_tickers - open_set
    watchlist_only = verdict_tickers - open_set - strategy_tickers

    results = {
        'critical':  [],  # open positions stale
        'warning':   [],  # strategy tickers stale
        'info':      [],  # watchlist stale
        'checked_n': 0,
    }

    for ticker in sorted(open_set):
        results['checked_n'] += 1
        date = _latest_price_date(conn, ticker)
        age = _age_days(date) if date else 999
        if age is None or age > THRESH_OPEN:
            results['critical'].append({'ticker': ticker, 'date': date, 'age': age})

    for ticker in sorted(strategy_only):
        results['checked_n'] += 1
        date = _latest_price_date(conn, ticker)
        age = _age_days(date) if date else 999
        if age is None or age > THRESH_STRATEGY:
            results['warning'].append({'ticker': ticker, 'date': date, 'age': age})

    for ticker in sorted(watchlist_only):
        results['checked_n'] += 1
        date = _latest_price_date(conn, ticker)
        age = _age_days(date) if date else 999
        if age is None or age > THRESH_WATCHLIST:
            results['info'].append({'ticker': ticker, 'date': date, 'age': age})

    conn.close()

    # Report
    print(f'=== Stale Data Watchdog ({results["checked_n"]} Tickers geprüft) ===')
    print(f'  Critical (open positions): {len(results["critical"])}')
    for x in results['critical']:
        print(f"    🚨 {x['ticker']:12s} letzter Preis: {x['date']} ({x['age']}d alt)")
    print(f'  Warning (strategy):        {len(results["warning"])}')
    for x in results['warning'][:5]:
        print(f"    ⚠️  {x['ticker']:12s} letzter Preis: {x['date']} ({x['age']}d alt)")
    if len(results['warning']) > 5:
        print(f'    ... +{len(results["warning"]) - 5} mehr')
    print(f'  Info (watchlist):          {len(results["info"])}')

    # Alert nur bei critical + warning
    if alert and (results['critical'] or results['warning']):
        _send_alert(results)

    # Write flag file wenn critical — paper_trade_engine kann das lesen & blocken
    flag_file = DATA / 'stale_data_flag.json'
    flag_data = {
        'ts': datetime.now(_BERLIN).isoformat(timespec='seconds'),
        'critical_tickers': [x['ticker'] for x in results['critical']],
        'warning_tickers':  [x['ticker'] for x in results['warning']],
    }
    try:
        flag_file.write_text(json.dumps(flag_data, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'flag-write failed: {e}')

    return results


def _send_alert(r: dict) -> None:
    try:
        from discord_sender import send
        lines = []
        if r['critical']:
            lines.append('🚨 **STALE DATA — Kritisch (offene Positionen)**')
            for x in r['critical']:
                lines.append(f"  {x['ticker']}: letzter Preis {x['date']} ({x['age']}d alt)")
            lines.append('⚠️  Stop-Loss kann nicht greifen!')
        if r['warning']:
            lines.append('')
            lines.append('⚠️ **Stale Data — Warning (active strategies)**')
            for x in r['warning'][:8]:
                lines.append(f"  {x['ticker']}: {x['date']} ({x['age']}d)")
        if lines:
            send('\n'.join(lines))
    except Exception as e:
        print(f'Discord alert failed: {e}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-alert', action='store_true')
    args = ap.parse_args()
    run(alert=not args.no_alert)


if __name__ == '__main__':
    main()
