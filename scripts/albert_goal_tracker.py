#!/usr/bin/env python3
"""
albert_goal_tracker.py — Phase 45aj.

Misst wöchentlich: bewegt sich Albert auf seine Goals zu?
Output: data/albert_goal_progress.jsonl + Update goals.json wenn Goal erreicht.

Run: täglich 23:00 (vor Self-Audit Sonntag).
"""
from __future__ import annotations
import json, os, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
GOALS = WS / 'data' / 'albert_goals.json'
LOG = WS / 'data' / 'albert_goal_progress.jsonl'
DB = WS / 'data' / 'trading.db'


def measure() -> dict:
    now = datetime.now(timezone.utc)
    goals = json.loads(GOALS.read_text(encoding='utf-8')) if GOALS.exists() else {}

    # 7d Trade-Metrics
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row
    cutoff = (now - timedelta(days=7)).isoformat()
    trades = db.execute(
        "SELECT pnl_eur, exit_type, status FROM paper_portfolio "
        "WHERE close_date >= ?", (cutoff,)
    ).fetchall()
    db.close()

    n_trades = len(trades)
    n_bug = sum(1 for r in trades if (r['exit_type'] or '').startswith('BUG_'))
    n_clean = n_trades - n_bug
    n_wins = sum(1 for r in trades
                 if (r['pnl_eur'] or 0) > 0 and not (r['exit_type'] or '').startswith('BUG_'))
    wr_pct = round(100 * n_wins / n_clean, 1) if n_clean > 0 else None

    progress = {
        'ts': now.isoformat(timespec='seconds'),
        'weekly_goal': goals.get('weekly', '?'),
        'metrics_7d': {
            'trades_total': n_trades,
            'trades_clean': n_clean,
            'trades_bug_rollback': n_bug,
            'wr_pct_clean': wr_pct,
        },
        'on_track': bool(n_clean >= 3 and (wr_pct or 0) >= 40),
        'cleanliness_score': round(100 * n_clean / max(n_trades, 1), 0),
    }

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(progress, ensure_ascii=False) + '\n')
    return progress


def main() -> int:
    r = measure()
    print(json.dumps(r, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
