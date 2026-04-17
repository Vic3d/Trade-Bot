#!/usr/bin/env python3
"""
Portfolio Circuit Breaker — Phase 22.1
=========================================
Hard-Halt fuer neue Entries wenn Tages-Portfolio-DD zu hoch wird.

Regeln:
  - DAY_DD_HALT  : wenn Tages-DD < -5%  → alle neuen Entries blockieren
  - WEEK_DD_WARN : wenn Woche < -8%     → Discord-Alert, aber nicht blocken
  - MONTH_DD_HALT: wenn Monat < -12%    → alle neuen Entries blockieren

State: data/portfolio_snapshot_daily.json (wird von performance_tracker um 21:30 geschrieben)

CLI:
  python3 scripts/portfolio_circuit_breaker.py          # Status-Check
  python3 scripts/portfolio_circuit_breaker.py --check  # Exit-Code 0 (ok) oder 2 (halt)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
SNAPSHOT = WS / 'data' / 'portfolio_snapshot_daily.json'

DAY_DD_HALT_PCT = -5.0
WEEK_DD_WARN_PCT = -8.0
MONTH_DD_HALT_PCT = -12.0


def _get_current_equity(conn) -> float:
    """Cash + Market-Value aller offenen Positionen (grob zu aktuellem Kurs)."""
    try:
        cash_row = conn.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash'"
        ).fetchone()
        cash = float(cash_row[0]) if cash_row else 0.0
    except Exception:
        cash = 0.0

    # Offene Positionen bewertet zum letzten Preis
    try:
        rows = conn.execute("""
            SELECT p.ticker, p.quantity, p.entry_price
            FROM paper_portfolio p
            WHERE p.status='OPEN'
        """).fetchall()
    except Exception:
        rows = []

    positions_value = 0.0
    for r in rows:
        ticker, qty, entry = r[0], float(r[1] or 0), float(r[2] or 0)
        try:
            last = conn.execute(
                "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            px = float(last[0]) if last else entry
        except Exception:
            px = entry
        positions_value += qty * px

    return round(cash + positions_value, 2)


def _load_snapshot() -> dict:
    if not SNAPSHOT.exists():
        return {}
    try:
        return json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_snapshot(data: dict):
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def record_daily_close(conn) -> float:
    """Fuer performance_tracker 21:30 — schreibt Tages-Closing-Equity."""
    equity = _get_current_equity(conn)
    snap = _load_snapshot()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    snap.setdefault('history', {})[today] = equity
    snap['last_close'] = equity
    snap['last_close_date'] = today
    _save_snapshot(snap)
    return equity


def compute_drawdowns(conn) -> dict:
    """Berechnet DD fuer Tag, Woche, Monat."""
    equity_now = _get_current_equity(conn)
    snap = _load_snapshot()
    history = snap.get('history', {})

    def _dd(days: int) -> float | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        prior = [(d, v) for d, v in history.items() if d <= cutoff]
        if not prior:
            return None
        prior.sort()
        ref = prior[-1][1]
        if ref <= 0:
            return None
        return round((equity_now / ref - 1) * 100, 2)

    return {
        'equity_now': equity_now,
        'day_dd_pct': _dd(1),
        'week_dd_pct': _dd(7),
        'month_dd_pct': _dd(30),
    }


def check() -> dict:
    """Return status={ok|halt|warn} + reason."""
    if not DB.exists():
        return {'status': 'ok', 'reason': 'DB fehlt, skip'}
    conn = sqlite3.connect(str(DB))
    try:
        dd = compute_drawdowns(conn)
    finally:
        conn.close()

    reasons = []
    status = 'ok'

    if dd['day_dd_pct'] is not None and dd['day_dd_pct'] < DAY_DD_HALT_PCT:
        reasons.append(f"Tages-DD {dd['day_dd_pct']}% < {DAY_DD_HALT_PCT}% → HALT")
        status = 'halt'

    if dd['month_dd_pct'] is not None and dd['month_dd_pct'] < MONTH_DD_HALT_PCT:
        reasons.append(f"Monats-DD {dd['month_dd_pct']}% < {MONTH_DD_HALT_PCT}% → HALT")
        status = 'halt'

    if status != 'halt' and dd['week_dd_pct'] is not None and dd['week_dd_pct'] < WEEK_DD_WARN_PCT:
        reasons.append(f"Wochen-DD {dd['week_dd_pct']}% < {WEEK_DD_WARN_PCT}% → WARN")
        status = 'warn'

    return {
        'status': status,
        'drawdowns': dd,
        'reasons': reasons,
        'limits': {
            'day': DAY_DD_HALT_PCT,
            'week': WEEK_DD_WARN_PCT,
            'month': MONTH_DD_HALT_PCT,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='Exit-Code 2 wenn halt')
    ap.add_argument('--record-close', action='store_true', help='Tages-Snapshot schreiben')
    args = ap.parse_args()

    if args.record_close:
        conn = sqlite3.connect(str(DB))
        try:
            eq = record_daily_close(conn)
            print(f"[circuit-breaker] Tages-Close: {eq} EUR")
        finally:
            conn.close()
        return

    r = check()
    print(json.dumps(r, indent=2, ensure_ascii=False))
    if args.check:
        sys.exit(2 if r['status'] == 'halt' else 0)


if __name__ == '__main__':
    main()
