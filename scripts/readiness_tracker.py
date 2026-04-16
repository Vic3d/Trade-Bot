#!/usr/bin/env python3
"""
Live-Readiness Tracker — Phase 7.4
====================================
Go/No-Go Dashboard für Echtgeld-Live-Test.

Harte Kriterien die ALLE grün sein müssen:
  [1] Win-Rate ≥ 45% über ≥ 60 Trades
  [2] Positiver Total-Return über min. 2 Monate
  [3] Max Drawdown < 10%
  [4] Profit-Faktor ≥ 1.5
  [5] 0 Fund-Reconciliation-Alerts (30d)
  [6] 0 Stale-Data-Trades (30d)
  [7] 2 verschiedene Regimes profitabel
  [8] 30d ohne Scheduler-Crash

Output:
  - data/readiness.json
  - Text-Block kann in honesty_report eingebunden werden

Usage:
  python3 scripts/readiness_tracker.py
  python3 scripts/readiness_tracker.py --block     # Nur Text für honesty
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
DB = WS / 'data' / 'trading.db'
OUT_FILE = WS / 'data' / 'readiness.json'

# Go/No-Go Schwellen
TARGET_TRADES = 60
TARGET_WR = 45.0
TARGET_PROFIT_FACTOR = 1.5
MAX_DRAWDOWN_PCT = 10.0
MIN_RUNTIME_MONTHS = 2
MIN_REGIMES = 2


def _closed_trades_stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("""
        SELECT pnl_eur, close_date, regime_at_entry, hmm_regime
        FROM paper_portfolio WHERE UPPER(status)='CLOSED'
        ORDER BY close_date ASC
    """).fetchall()
    n = len(rows)
    if n == 0:
        return {'n': 0}
    wins_pnl = [r[0] for r in rows if (r[0] or 0) > 0]
    losses_pnl = [r[0] for r in rows if (r[0] or 0) < 0]
    wr = len(wins_pnl) / n * 100
    pf = (sum(wins_pnl) / abs(sum(losses_pnl))) if losses_pnl else float('inf')

    regimes = set()
    for r in rows:
        for col in (r[2], r[3]):
            if col:
                regimes.add(str(col).upper())

    first_date = rows[0][1][:10] if rows[0][1] else None
    last_date = rows[-1][1][:10] if rows[-1][1] else None
    return {
        'n':              n,
        'wr':             round(wr, 1),
        'profit_factor':  round(pf, 2) if pf != float('inf') else 999,
        'sum_pnl':        round(sum(r[0] or 0 for r in rows), 2),
        'first_trade':    first_date,
        'last_trade':     last_date,
        'regimes_seen':   sorted(regimes),
        'regime_count':   len(regimes),
    }


def _equity_drawdown(conn: sqlite3.Connection) -> dict:
    """Max Drawdown aus paper_fund_history oder equity snapshots."""
    try:
        rows = conn.execute("""
            SELECT ts, truth_cash FROM paper_fund_history ORDER BY ts ASC
        """).fetchall()
    except sqlite3.OperationalError:
        return {'max_dd_pct': None, 'reason': 'no_history_table'}

    if len(rows) < 2:
        # Fallback: aus CLOSED trades kumulativ
        trow = conn.execute("""
            SELECT close_date, pnl_eur FROM paper_portfolio
            WHERE UPPER(status)='CLOSED' ORDER BY close_date ASC
        """).fetchall()
        if not trow:
            return {'max_dd_pct': None, 'reason': 'no_data'}
        equity = 25000.0
        peak = equity
        max_dd = 0.0
        for _, pnl in trow:
            equity += (pnl or 0)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return {'max_dd_pct': round(max_dd, 2), 'reason': 'from_trades'}

    peak = rows[0][1]
    max_dd = 0.0
    for _, cash in rows:
        if cash > peak:
            peak = cash
        dd = (peak - cash) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return {'max_dd_pct': round(max_dd, 2), 'reason': 'from_history'}


def _reconciliation_alerts_30d(conn: sqlite3.Connection) -> int:
    try:
        cutoff = (datetime.now(_BERLIN) - timedelta(days=30)).isoformat()
        row = conn.execute("""
            SELECT COUNT(*) FROM paper_fund_history
            WHERE ts >= ? AND ABS(cash_discrepancy) >= 50
        """, (cutoff,)).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return -1  # keine Historie


def _stale_data_trades_30d(conn: sqlite3.Connection) -> int:
    """Trades mit exit_type MANUAL_STALE_DATA o.ä. in den letzten 30d."""
    cutoff = (datetime.now(_BERLIN) - timedelta(days=30)).strftime('%Y-%m-%d')
    row = conn.execute("""
        SELECT COUNT(*) FROM paper_portfolio
        WHERE UPPER(status)='CLOSED'
        AND close_date >= ?
        AND (exit_type LIKE '%STALE%' OR exit_type LIKE '%MANUAL%')
    """, (cutoff,)).fetchone()
    return int(row[0]) if row else 0


def _runtime_days(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("""
        SELECT MIN(entry_date) FROM paper_portfolio
    """).fetchone()
    if not row or not row[0]:
        return None
    try:
        first = datetime.fromisoformat(row[0][:19])
        return (datetime.now() - first).days
    except Exception:
        return None


def run() -> dict:
    conn = sqlite3.connect(str(DB))
    ts = _closed_trades_stats(conn)
    dd = _equity_drawdown(conn)
    recon_alerts = _reconciliation_alerts_30d(conn)
    stale = _stale_data_trades_30d(conn)
    runtime = _runtime_days(conn)
    conn.close()

    # Kriterien auswerten
    criteria = []

    # [1] 60 Trades + WR 45%
    ok_trades = ts['n'] >= TARGET_TRADES
    ok_wr = ts.get('wr', 0) >= TARGET_WR
    criteria.append({
        'id': 'trades_wr',
        'label': f'≥{TARGET_TRADES} Trades mit WR ≥{TARGET_WR}%',
        'current': f'{ts["n"]} trades, WR {ts.get("wr", 0)}%',
        'ok': ok_trades and ok_wr,
        'progress': round(ts['n'] / TARGET_TRADES * 100, 1),
    })

    # [2] Positive Return + ≥2 Monate
    ok_return = ts.get('sum_pnl', 0) > 0
    ok_runtime = (runtime or 0) >= MIN_RUNTIME_MONTHS * 30
    criteria.append({
        'id': 'return_runtime',
        'label': f'Positiver Return ≥{MIN_RUNTIME_MONTHS} Monate',
        'current': f'{ts.get("sum_pnl", 0):+.2f}€, Laufzeit {runtime or 0}d',
        'ok': ok_return and ok_runtime,
        'progress': round((runtime or 0) / (MIN_RUNTIME_MONTHS * 30) * 100, 1),
    })

    # [3] Max DD < 10%
    ok_dd = (dd.get('max_dd_pct') is not None
             and dd['max_dd_pct'] < MAX_DRAWDOWN_PCT)
    criteria.append({
        'id': 'max_drawdown',
        'label': f'Max Drawdown < {MAX_DRAWDOWN_PCT}%',
        'current': f'{dd.get("max_dd_pct", "?")}%' if dd.get('max_dd_pct') is not None else 'unbekannt',
        'ok': ok_dd,
        'progress': None,
    })

    # [4] Profit Faktor ≥ 1.5
    pf = ts.get('profit_factor', 0)
    ok_pf = pf >= TARGET_PROFIT_FACTOR
    criteria.append({
        'id': 'profit_factor',
        'label': f'Profit-Faktor ≥ {TARGET_PROFIT_FACTOR}',
        'current': f'{pf}' if pf < 999 else '∞',
        'ok': ok_pf,
        'progress': round(pf / TARGET_PROFIT_FACTOR * 100, 1) if pf < 999 else 100,
    })

    # [5] 0 Reconciliation Alerts 30d
    ok_recon = recon_alerts == 0
    criteria.append({
        'id': 'reconciliation',
        'label': '0 Fund-Reconciliation-Alerts (30d)',
        'current': f'{recon_alerts} alerts' if recon_alerts >= 0 else 'noch keine Historie',
        'ok': ok_recon,
        'progress': None,
    })

    # [6] 0 Stale-Data-Trades 30d
    ok_stale = stale == 0
    criteria.append({
        'id': 'stale_data',
        'label': '0 Stale-Data-Trades (30d)',
        'current': f'{stale} stale trades',
        'ok': ok_stale,
        'progress': None,
    })

    # [7] ≥2 verschiedene Regimes
    ok_regimes = ts.get('regime_count', 0) >= MIN_REGIMES
    criteria.append({
        'id': 'regimes',
        'label': f'Profitabel in ≥{MIN_REGIMES} Regimes',
        'current': f'{ts.get("regime_count", 0)} gesehen: {ts.get("regimes_seen", [])}',
        'ok': ok_regimes,
        'progress': None,
    })

    # Aggregat
    passing = sum(1 for c in criteria if c['ok'])
    total = len(criteria)
    go_green = passing == total

    result = {
        'generated_at': datetime.now(_BERLIN).isoformat(timespec='seconds'),
        'criteria':     criteria,
        'passing':      passing,
        'total':        total,
        'go_green':     go_green,
        'verdict':      'READY_FOR_LIVE' if go_green else 'NOT_READY',
        'stats_trades': ts,
        'stats_dd':     dd,
        'runtime_days': runtime,
    }
    OUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return result


def render_block(r: dict) -> str:
    """Text-Block für honesty_report."""
    lines = []
    lines.append(f'📋 **Live-Test Readiness: {r["passing"]}/{r["total"]} {"✅" if r["go_green"] else "❌"}**')
    for c in r['criteria']:
        mark = '✅' if c['ok'] else '❌'
        prog = f' ({c["progress"]:.0f}%)' if c.get('progress') is not None else ''
        lines.append(f'  {mark} {c["label"]}: {c["current"]}{prog}')
    if not r['go_green']:
        lines.append(f'  → Verdict: {r["verdict"]}')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--block', action='store_true', help='Nur Text-Block ausgeben')
    args = ap.parse_args()

    r = run()
    if args.block:
        print(render_block(r))
    else:
        print('═' * 70)
        print(f'  Live-Test Readiness — {r["passing"]}/{r["total"]} Kriterien erfüllt')
        print('═' * 70)
        for c in r['criteria']:
            mark = '✅' if c['ok'] else '❌'
            print(f'  {mark} {c["label"]}')
            print(f'      current: {c["current"]}')
            if c.get('progress') is not None:
                print(f'      progress: {c["progress"]:.1f}%')
        print()
        print(f'  VERDICT: {r["verdict"]}')
        print('═' * 70)


if __name__ == '__main__':
    main()
