#!/usr/bin/env python3
"""
Equity Curve Snapshot — Phase 9 Support

Schreibt tägliche Portfolio-Bewertung nach data/equity_curve.json.
Wird vom Drawdown Circuit Breaker (portfolio_risk.py) als Input verwendet.

Läuft 1x täglich am Ende der US-Session (22:00 CET).
"""
import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'equity_curve.json'


def _db():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def _latest_price(conn, ticker: str) -> float | None:
    row = conn.execute(
        "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    return float(row[0]) if row else None


def compute_portfolio_value() -> dict:
    """Aktueller Portfolio-Wert = Cash + MTM aller offenen Positionen."""
    conn = _db()
    cash_row = conn.execute("SELECT value FROM paper_fund WHERE key='cash'").fetchone()
    cash = float(cash_row[0]) if cash_row else 25000.0

    positions = conn.execute(
        "SELECT ticker, shares, entry_price, position_size_eur FROM trades WHERE status='OPEN'"
    ).fetchall()

    mtm_value = 0.0
    entry_value = 0.0
    for p in positions:
        shares = p['shares'] or 0
        entry = p['entry_price'] or 0
        ticker = p['ticker']
        if not shares or not entry or not ticker:
            # Fallback: position_size_eur
            entry_value += (p['position_size_eur'] or 0)
            mtm_value += (p['position_size_eur'] or 0)
            continue
        live = _latest_price(conn, ticker) or entry
        mtm_value += shares * live
        entry_value += shares * entry

    conn.close()
    return {
        'date': date.today().isoformat(),
        'timestamp': datetime.now().isoformat(),
        'cash': round(cash, 2),
        'positions_entry': round(entry_value, 2),
        'positions_mtm': round(mtm_value, 2),
        'total_value': round(cash + mtm_value, 2),
        'unrealized_pnl': round(mtm_value - entry_value, 2),
    }


def update_equity_curve() -> dict:
    """Fügt einen Daten-Punkt zur equity_curve.json hinzu (1 pro Tag)."""
    snap = compute_portfolio_value()

    if OUT.exists():
        try:
            curve = json.loads(OUT.read_text(encoding='utf-8'))
            if not isinstance(curve, list):
                curve = []
        except Exception:
            curve = []
    else:
        curve = []

    # Heutigen Tag überschreiben, falls schon vorhanden (last-write-wins)
    curve = [e for e in curve if e.get('date') != snap['date']]
    curve.append(snap)

    # Nur letzte 90 Tage behalten
    curve = curve[-90:]

    OUT.write_text(json.dumps(curve, indent=2), encoding='utf-8')
    return snap


def run():
    snap = update_equity_curve()
    print(f"Equity Snapshot {snap['date']}: {snap['total_value']:,.0f}€ "
          f"(Cash {snap['cash']:,.0f} + Positions {snap['positions_mtm']:,.0f}, "
          f"uPnL {snap['unrealized_pnl']:+,.0f})")
    return snap


if __name__ == '__main__':
    run()
