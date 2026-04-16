#!/usr/bin/env python3
"""
Fund Reconciliation — Phase 4.1
================================
Berechnet den WAHREN Fund-Status aus paper_portfolio (Single Source of Truth)
und vergleicht mit paper_fund.current_cash. Meldet Diskrepanzen > 50€ an
Discord und schreibt einen täglichen Snapshot in paper_fund_history.

Läuft tägl. 23:10 CET (nach State Sync).

Warum das Tool existiert:
  paper_fund ist eine key-value-Tabelle die von paper_trade_engine.py bei
  jedem Trade mutiert wird. Über 3 Wochen ist sie ~8000€ von der Realität
  abgewichen (doppelte Trade-Einträge, Migrations-Bugs, nicht-abgeschlossene
  Legs). Das Reconciliation-Tool ist die Kontrollinstanz.

Ground Truth:
  current_cash = starting_capital
               + SUM(pnl_eur für CLOSED trades)
               - SUM(fees für CLOSED trades)
               - SUM(shares * entry_price für OPEN positions)   # gebundenes Cash

Usage:
  python3 scripts/fund_reconciliation.py              # Report + Snapshot
  python3 scripts/fund_reconciliation.py --fix        # Setzt paper_fund auf Wahrheit
  python3 scripts/fund_reconciliation.py --no-alert   # Kein Discord
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB = DATA / 'trading.db'

ALERT_THRESHOLD_EUR = 50.0  # Diskrepanz > 50€ → Discord-Alert

sys.path.insert(0, str(WS / 'scripts'))


def _ensure_history_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_fund_history (
            ts                TEXT PRIMARY KEY,
            reported_cash     REAL NOT NULL,
            reported_realized REAL NOT NULL,
            truth_cash        REAL NOT NULL,
            truth_realized    REAL NOT NULL,
            open_positions_n  INTEGER NOT NULL,
            open_positions_val REAL NOT NULL,
            closed_trades_n   INTEGER NOT NULL,
            fees_total        REAL NOT NULL,
            cash_discrepancy  REAL NOT NULL,
            was_fixed         INTEGER DEFAULT 0
        )
    """)
    conn.commit()


def compute_truth(conn: sqlite3.Connection) -> dict:
    """Wahrer Fund-Status aus paper_portfolio."""
    # Starting capital aus paper_fund (key fix point, ändert sich nie)
    row = conn.execute("SELECT value FROM paper_fund WHERE key='starting_capital'").fetchone()
    starting = float(row[0]) if row else 25000.0

    # Realized P&L (schon fees-adjusted, aber wir validieren)
    row = conn.execute("""
        SELECT COUNT(*), COALESCE(SUM(pnl_eur), 0), COALESCE(SUM(fees), 0)
        FROM paper_portfolio
        WHERE UPPER(status) = 'CLOSED'
    """).fetchone()
    closed_n, closed_pnl, closed_fees = row[0], float(row[1]), float(row[2])

    # Open positions (gebundenes Cash)
    row = conn.execute("""
        SELECT COUNT(*),
               COALESCE(SUM(shares * entry_price), 0),
               COALESCE(SUM(fees), 0)
        FROM paper_portfolio
        WHERE UPPER(status) = 'OPEN'
    """).fetchone()
    open_n, open_val, open_fees = row[0], float(row[1]), float(row[2])

    # Annahme: pnl_eur ist GROSS (ohne fees), daher fees separat abziehen
    # Falls pnl_eur schon net ist, wären die fees doppelt gezählt — zur Sicherheit
    # checken wir beide Varianten und nehmen die plausiblere.
    truth_cash_net = starting + closed_pnl - open_val - open_fees
    truth_cash_gross = starting + closed_pnl - closed_fees - open_val - open_fees

    return {
        'starting':        starting,
        'closed_n':        closed_n,
        'closed_pnl':      closed_pnl,
        'closed_fees':     closed_fees,
        'open_n':          open_n,
        'open_val':        open_val,
        'open_fees':       open_fees,
        'truth_cash_net':  truth_cash_net,
        'truth_cash_gross': truth_cash_gross,
        # Wir nehmen gross als offizielle Wahrheit: paper_trade_engine.py
        # bucht Fees separat (siehe paper_fund.current_cash -= fees bei OPEN)
        'truth_cash':      truth_cash_gross,
        'truth_realized':  closed_pnl - closed_fees,
    }


def get_reported(conn: sqlite3.Connection) -> dict:
    rows = dict(conn.execute("SELECT key, value FROM paper_fund").fetchall())
    return {
        'starting_capital':    float(rows.get('starting_capital', 25000.0)),
        'current_cash':        float(rows.get('current_cash', 0.0)),
        'total_realized_pnl':  float(rows.get('total_realized_pnl', 0.0)),
    }


def reconcile(fix: bool = False, alert: bool = True) -> dict:
    conn = sqlite3.connect(str(DB))
    _ensure_history_table(conn)

    truth = compute_truth(conn)
    reported = get_reported(conn)

    cash_diff = reported['current_cash'] - truth['truth_cash']
    pnl_diff  = reported['total_realized_pnl'] - truth['truth_realized']

    ts = datetime.now(_BERLIN).isoformat(timespec='seconds')

    result = {
        'ts':                   ts,
        'reported_cash':        reported['current_cash'],
        'reported_realized':    reported['total_realized_pnl'],
        'truth_cash':           truth['truth_cash'],
        'truth_realized':       truth['truth_realized'],
        'cash_discrepancy':     cash_diff,
        'pnl_discrepancy':      pnl_diff,
        'open_positions_n':     truth['open_n'],
        'open_positions_val':   truth['open_val'],
        'closed_trades_n':      truth['closed_n'],
        'fees_total':           truth['closed_fees'] + truth['open_fees'],
        'was_fixed':            False,
    }

    # Fix?
    if fix and abs(cash_diff) >= 0.01:
        conn.execute("UPDATE paper_fund SET value = ? WHERE key = 'current_cash'",
                     (truth['truth_cash'],))
        conn.execute("UPDATE paper_fund SET value = ? WHERE key = 'total_realized_pnl'",
                     (truth['truth_realized'],))
        conn.commit()
        result['was_fixed'] = True
        print(f'✅ FIX angewendet: current_cash {reported["current_cash"]:.2f}€ → {truth["truth_cash"]:.2f}€')

    # Snapshot in history
    conn.execute("""
        INSERT OR REPLACE INTO paper_fund_history
        (ts, reported_cash, reported_realized, truth_cash, truth_realized,
         open_positions_n, open_positions_val, closed_trades_n, fees_total,
         cash_discrepancy, was_fixed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (ts,
          reported['current_cash'], reported['total_realized_pnl'],
          truth['truth_cash'], truth['truth_realized'],
          truth['open_n'], truth['open_val'],
          truth['closed_n'], truth['closed_fees'] + truth['open_fees'],
          cash_diff, 1 if result['was_fixed'] else 0))
    conn.commit()
    conn.close()

    # Alert bei Diskrepanz
    if alert and abs(cash_diff) >= ALERT_THRESHOLD_EUR and not result['was_fixed']:
        _send_alert(result)

    return result


def _send_alert(r: dict) -> None:
    """Discord-Alert bei signifikanter Diskrepanz."""
    try:
        from discord_sender import send
        emoji = '🚨' if abs(r['cash_discrepancy']) > 500 else '⚠️'
        msg = (
            f"{emoji} **Fund-Reconciliation Diskrepanz**\n"
            f"Reported Cash: **{r['reported_cash']:.2f}€** | "
            f"Truth: **{r['truth_cash']:.2f}€**\n"
            f"→ Diskrepanz: **{r['cash_discrepancy']:+.2f}€**\n"
            f"Trades closed: {r['closed_trades_n']} | open: {r['open_positions_n']} "
            f"(gebunden: {r['open_positions_val']:.0f}€)\n"
            f"Realized P&L reported: {r['reported_realized']:+.2f}€ | "
            f"truth: {r['truth_realized']:+.2f}€"
        )
        send(msg)
    except Exception as e:
        print(f'Discord-Alert fehlgeschlagen: {e}')


def print_report(r: dict) -> None:
    print()
    print('═' * 70)
    print(f'  Fund Reconciliation — {r["ts"]}')
    print('═' * 70)
    print(f'  Reported cash:     {r["reported_cash"]:>12.2f}€')
    print(f'  Truth cash:        {r["truth_cash"]:>12.2f}€')
    print(f'  → Diskrepanz:      {r["cash_discrepancy"]:>+12.2f}€')
    print()
    print(f'  Reported realized: {r["reported_realized"]:>+12.2f}€')
    print(f'  Truth realized:    {r["truth_realized"]:>+12.2f}€')
    print(f'  → Diskrepanz:      {r["pnl_discrepancy"]:>+12.2f}€')
    print()
    print(f'  Closed trades:     {r["closed_trades_n"]}')
    print(f'  Open positions:    {r["open_positions_n"]} (gebunden: {r["open_positions_val"]:.2f}€)')
    print(f'  Fees total:        {r["fees_total"]:.2f}€')
    if r.get('was_fixed'):
        print()
        print('  ✅ paper_fund wurde GEFIXT auf truth-values')
    elif abs(r['cash_discrepancy']) >= ALERT_THRESHOLD_EUR:
        print()
        print(f'  ⚠️  Diskrepanz > {ALERT_THRESHOLD_EUR}€ — Discord-Alert gesendet')
    print('═' * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fix', action='store_true',
                    help='Setzt paper_fund auf truth-values')
    ap.add_argument('--no-alert', action='store_true',
                    help='Kein Discord-Alert bei Diskrepanz')
    args = ap.parse_args()

    r = reconcile(fix=args.fix, alert=not args.no_alert)
    print_report(r)
    return r


if __name__ == '__main__':
    main()
