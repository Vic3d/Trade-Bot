#!/usr/bin/env python3
"""
Equity Curve Snapshot — Phase 7.5 (rewrite)
============================================
Täglicher Portfolio-Equity-Snapshot inkl. MTM der offenen Positionen.
Grundlage für saubere Max-Drawdown-Berechnung.

Schreibt pro Tag EINEN Eintrag:
  - DB-Tabelle `equity_history` (canonical source for DD)
  - data/equity_curve.json (legacy consumer — portfolio_risk.py)

Idempotent: mehrfach pro Tag → überschreibt den Tag.

Nutzt fund_truth.get_truth() als Single Source of Truth.

Scheduler: täglich 22:55 CET (nach Markt-Close, vor Honesty-Report).

Usage:
  python3 scripts/equity_snapshot.py             # normaler Run
  python3 scripts/equity_snapshot.py --dry-run   # nur anzeigen
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
CURVE_JSON = WS / 'data' / 'equity_curve.json'

sys.path.insert(0, str(WS / 'scripts'))


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equity_history (
            snapshot_date    TEXT PRIMARY KEY,
            ts               TEXT NOT NULL,
            cash             REAL NOT NULL,
            open_entry_val   REAL NOT NULL,
            open_mtm_val     REAL NOT NULL,
            unrealized_pnl   REAL NOT NULL,
            total_equity     REAL NOT NULL,
            peak_equity      REAL NOT NULL,
            drawdown_pct     REAL NOT NULL,
            open_positions_n INTEGER NOT NULL,
            closed_trades_n  INTEGER NOT NULL
        )
    """)
    conn.commit()


def _atomic_json_write(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def run(dry_run: bool = False) -> dict:
    from fund_truth import get_truth

    conn = sqlite3.connect(str(DB))
    _ensure_table(conn)

    t = get_truth()
    total_equity = t['total_equity']

    # Peak equity: max von bisherigen snapshots + heute
    row = conn.execute("SELECT MAX(peak_equity) FROM equity_history").fetchone()
    prev_peak = float(row[0]) if row and row[0] is not None else t['starting_capital']
    peak = max(prev_peak, total_equity)
    dd = ((peak - total_equity) / peak * 100) if peak > 0 else 0.0

    today = date.today().isoformat()
    ts = datetime.now(_BERLIN).isoformat(timespec='seconds')

    record = {
        'snapshot_date':    today,
        'ts':               ts,
        'cash':             round(t['cash'], 2),
        'open_entry_val':   round(t['open_positions_entry_val'], 2),
        'open_mtm_val':     round(t['open_positions_mtm_val'], 2),
        'unrealized_pnl':   round(t['open_positions_unrealized_pnl'], 2),
        'total_equity':     round(total_equity, 2),
        'peak_equity':      round(peak, 2),
        'drawdown_pct':     round(dd, 2),
        'open_positions_n': t['open_positions'],
        'closed_trades_n':  t['closed_trades'],
    }

    print('═' * 60)
    print(f'  Equity Snapshot — {today}')
    print('═' * 60)
    print(f'  Cash:               {record["cash"]:>10.2f}€')
    print(f'  Open entry value:   {record["open_entry_val"]:>10.2f}€')
    print(f'  Open MTM value:     {record["open_mtm_val"]:>10.2f}€')
    print(f'  Unrealized P&L:     {record["unrealized_pnl"]:>+10.2f}€')
    print(f'  Total equity:       {record["total_equity"]:>10.2f}€')
    print(f'  Peak equity:        {record["peak_equity"]:>10.2f}€')
    print(f'  Drawdown:           {record["drawdown_pct"]:>10.2f}%')
    print(f'  Open positions:     {record["open_positions_n"]}')
    print(f'  Closed trades:      {record["closed_trades_n"]}')

    if dry_run:
        print('\n[DRY-RUN]')
        conn.close()
        return record

    # 1) DB-Tabelle
    conn.execute("""
        INSERT OR REPLACE INTO equity_history
        (snapshot_date, ts, cash, open_entry_val, open_mtm_val, unrealized_pnl,
         total_equity, peak_equity, drawdown_pct, open_positions_n, closed_trades_n)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, tuple(record.values()))
    conn.commit()

    # 2) Legacy JSON für portfolio_risk.py
    try:
        if CURVE_JSON.exists():
            curve = json.loads(CURVE_JSON.read_text(encoding='utf-8'))
            if not isinstance(curve, list):
                curve = []
        else:
            curve = []
    except Exception:
        curve = []

    curve = [e for e in curve if e.get('date') != today]
    curve.append({
        'date':           today,
        'timestamp':      ts,
        'cash':           record['cash'],
        'positions_entry': record['open_entry_val'],
        'positions_mtm':  record['open_mtm_val'],
        'total_value':    record['total_equity'],
        'unrealized_pnl': record['unrealized_pnl'],
    })
    curve = curve[-180:]  # 6 Monate aufheben
    _atomic_json_write(CURVE_JSON, curve)

    conn.close()
    print('\n✅ Snapshot gespeichert (equity_history + equity_curve.json).')
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
