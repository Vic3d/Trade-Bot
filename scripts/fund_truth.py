#!/usr/bin/env python3
"""
Fund Truth — Phase 5.5
=======================
Single Source of Truth für Fund-Status. Berechnet IMMER aus paper_portfolio
(die eigentliche Trade-Historie), nie aus paper_fund (key-value cache).

Verwendung statt `SELECT value FROM paper_fund WHERE key='current_cash'`:

    from fund_truth import get_truth
    t = get_truth()
    cash = t['cash']
    realized = t['realized_pnl']
    open_val = t['open_positions_val']
    total_equity = t['total_equity']  # cash + mark-to-market offene Positionen

Liest auch das letzte Mark-to-Market wenn verfügbar (prices table).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB))


def _latest_price_map(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    qmarks = ','.join('?' * len(tickers))
    rows = conn.execute(
        f"""SELECT ticker, close FROM prices WHERE (ticker, date) IN
            (SELECT ticker, MAX(date) FROM prices WHERE ticker IN ({qmarks}) GROUP BY ticker)""",
        tickers,
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def get_truth() -> dict:
    """Wahrer Fund-Status live berechnet."""
    conn = _conn()

    row = conn.execute("SELECT value FROM paper_fund WHERE key='starting_capital'").fetchone()
    starting = float(row[0]) if row else 25000.0

    # Closed trades — realized P&L
    row = conn.execute("""
        SELECT COALESCE(SUM(pnl_eur),0), COALESCE(SUM(fees),0), COUNT(*)
        FROM paper_portfolio WHERE UPPER(status) IN ('CLOSED','WIN','LOSS')
    """).fetchone()
    realized, closed_fees, closed_n = float(row[0]), float(row[1]), row[2]

    # Open positions
    open_rows = conn.execute("""
        SELECT ticker, shares, entry_price, stop_price, target_price, strategy,
               COALESCE(fees, 0) as fees
        FROM paper_portfolio WHERE UPPER(status)='OPEN'
    """).fetchall()

    tickers = [r[0] for r in open_rows]
    prices = _latest_price_map(conn, tickers)

    open_entry_val = 0.0   # cash gebunden (Einstiegswert)
    open_mtm_val = 0.0     # mark-to-market aktueller Wert
    open_fees = 0.0
    open_list = []
    for ticker, shares, entry, stop, target, strat, fees in open_rows:
        shares = float(shares or 0)
        entry = float(entry or 0)
        fees = float(fees or 0)
        cur_price = prices.get(ticker, entry)
        entry_val = shares * entry
        mtm_val = shares * cur_price
        open_entry_val += entry_val
        open_mtm_val += mtm_val
        open_fees += fees
        open_list.append({
            'ticker': ticker, 'strategy': strat, 'shares': shares,
            'entry': entry, 'stop': stop, 'target': target, 'current': cur_price,
            'entry_val': entry_val, 'mtm_val': mtm_val,
            'unrealized_pnl': mtm_val - entry_val,
            'unrealized_pct': ((cur_price - entry) / entry * 100) if entry else 0,
        })

    cash = starting + realized - closed_fees - open_entry_val - open_fees
    total_equity = cash + open_mtm_val

    conn.close()
    return {
        'starting_capital':     starting,
        'cash':                 cash,
        'realized_pnl':         realized - closed_fees,
        'closed_trades':        closed_n,
        'open_positions':       len(open_list),
        'open_positions_entry_val': open_entry_val,
        'open_positions_mtm_val':   open_mtm_val,
        'open_positions_unrealized_pnl': open_mtm_val - open_entry_val,
        'total_equity':         total_equity,
        'total_return_eur':     total_equity - starting,
        'total_return_pct':     (total_equity - starting) / starting * 100 if starting else 0,
        'positions':            open_list,
    }


def print_summary():
    t = get_truth()
    print('═' * 60)
    print(f'  Fund Truth (aus paper_portfolio berechnet)')
    print('═' * 60)
    print(f'  Starting Capital:  {t["starting_capital"]:>12.2f}€')
    print(f'  Realized P&L:      {t["realized_pnl"]:>+12.2f}€ ({t["closed_trades"]} trades)')
    print(f'  Cash:              {t["cash"]:>12.2f}€')
    print(f'  Open Positions:    {t["open_positions"]}')
    print(f'    Entry-Wert:      {t["open_positions_entry_val"]:>12.2f}€')
    print(f'    MTM-Wert:        {t["open_positions_mtm_val"]:>12.2f}€')
    print(f'    Unrealized P&L:  {t["open_positions_unrealized_pnl"]:>+12.2f}€')
    print(f'  ─────────────────────────────')
    print(f'  Total Equity:      {t["total_equity"]:>12.2f}€')
    print(f'  Return:            {t["total_return_eur"]:>+12.2f}€ ({t["total_return_pct"]:+.2f}%)')
    print('═' * 60)
    for p in t['positions']:
        print(f'  {p["ticker"]:10} {p["strategy"]:10} '
              f'{p["shares"]:>5.1f}×{p["entry"]:>7.2f}→{p["current"]:>7.2f} '
              f'{p["unrealized_pnl"]:>+7.2f}€ ({p["unrealized_pct"]:+.1f}%)')


if __name__ == '__main__':
    print_summary()
