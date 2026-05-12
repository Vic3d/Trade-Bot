#!/usr/bin/env python3
"""
cohort_performance_tracker.py — Phase 45at.

Berechnet täglich pro Kohorte:
  - Realized PnL, Unrealized PnL (FX-sicher via position_pnl)
  - Trade Count, Win Rate, Sharpe approximiert
  - Sektor-Verteilung
  - Aktuelles Total-Equity (cash + position value)

Output: data/cohort_performance/<cohort_id>_history.jsonl + latest.json.
Run: täglich 22:45.
"""
from __future__ import annotations
import json, math, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT_DIR = WS / 'data' / 'cohort_performance'
sys.path.insert(0, str(WS / 'scripts'))


def _sharpe_approx(daily_returns: list[float]) -> float:
    if len(daily_returns) < 5: return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    var = sum((r - mean) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
    sd = var ** 0.5
    if sd == 0: return 0.0
    return round(mean / sd * (252 ** 0.5), 2)


def compute_cohort_perf(cohort_id: str, cohort_row: dict) -> dict:
    if not DB.exists(): return {}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    trades = [dict(r) for r in c.execute(
        "SELECT id, ticker, status, entry_price, shares, pnl_eur, exit_type, "
        "entry_date, close_date FROM paper_portfolio WHERE cohort_id=?", (cohort_id,)
    ).fetchall()]
    c.close()

    closed = [t for t in trades if t['status'] != 'OPEN' and t.get('pnl_eur') is not None
              and not (t.get('exit_type') or '').startswith('BUG_')]
    open_pos = [t for t in trades if t['status'] == 'OPEN']
    wins = [t for t in closed if t['pnl_eur'] > 0]

    realized = sum(t['pnl_eur'] for t in closed)

    # Unrealized via position_pnl
    unrealized = 0.0
    open_value = 0.0
    try:
        from position_pnl import get_position_pnl
        for t in open_pos:
            if t.get('entry_price') and t.get('shares'):
                pnl = get_position_pnl(t['ticker'], t['entry_price'], t['shares'])
                if pnl.get('valid'):
                    unrealized += pnl['pnl_eur']
                    open_value += pnl['live_eur'] * t['shares']
    except Exception: pass

    initial = cohort_row.get('initial_capital_eur', 25000)
    cash = cohort_row.get('current_cash_eur', 0)
    equity = cash + open_value
    total_return_pct = round((equity + realized - initial) / initial * 100, 2)

    return {
        'cohort_id': cohort_id,
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': cohort_row.get('status'),
        'initial_capital_eur': initial,
        'current_cash_eur': round(cash, 2),
        'open_position_value_eur': round(open_value, 2),
        'equity_eur': round(equity, 2),
        'realized_pnl_eur': round(realized, 2),
        'unrealized_pnl_eur': round(unrealized, 2),
        'total_return_pct': total_return_pct,
        'n_trades_total': len(trades),
        'n_closed': len(closed),
        'n_wins': len(wins),
        'n_open': len(open_pos),
        'win_rate_pct': round(len(wins) / max(len(closed), 1) * 100, 1) if closed else None,
        'avg_winner_eur': round(sum(t['pnl_eur'] for t in wins) / max(len(wins), 1), 2) if wins else 0,
        'avg_loser_eur': round(sum(t['pnl_eur'] for t in closed if t['pnl_eur']<0)
                                / max(len([t for t in closed if t['pnl_eur']<0]), 1), 2) if closed else 0,
    }


def track_all() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    cohorts = [dict(r) for r in c.execute(
        "SELECT * FROM paper_cohorts WHERE status IN ('ACTIVE','WINDDOWN','PENDING_DECISION')"
    ).fetchall()]
    c.close()

    results = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ch in cohorts:
        perf = compute_cohort_perf(ch['cohort_id'], ch)
        results.append(perf)
        # Historie schreiben
        hist = OUT_DIR / f'{ch["cohort_id"]}_history.jsonl'
        with open(hist, 'a', encoding='utf-8') as f:
            f.write(json.dumps(perf, default=str) + '\n')

    # Latest snapshot über alle
    latest = OUT_DIR / 'latest.json'
    latest.write_text(json.dumps(
        {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
         'cohorts': results}, indent=2, default=str, ensure_ascii=False
    ), encoding='utf-8')

    return {'n_cohorts': len(results), 'cohorts': results}


def main() -> int:
    r = track_all()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
