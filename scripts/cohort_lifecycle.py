#!/usr/bin/env python3
"""
cohort_lifecycle.py — Phase 45at.

Tägliches Lifecycle-Management:
  - ACTIVE → WINDDOWN: nach min_lifetime_until + (Victor-Entscheidung pending)
  - WINDDOWN → CLOSED: wenn alle Positionen geschlossen
  - 1-Jahr-Anniversary: erzeugt Auto-Summary für Victor und fragt
    ob diese Kohorte einstellen oder weiterlaufen lassen

Run: täglich 23:00.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, date
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
SUMMARIES_DIR = WS / 'data' / 'cohort_summaries'


def _cohort_anniversary_summary(cohort_id: str) -> dict:
    """Erstelle 1-Jahr-Bilanz einer Kohorte (für Victor-Entscheidung)."""
    if not DB.exists(): return {}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    trades = [dict(r) for r in c.execute(
        "SELECT * FROM paper_portfolio WHERE cohort_id=? ORDER BY entry_date",
        (cohort_id,)
    ).fetchall()]
    cohort = c.execute("SELECT * FROM paper_cohorts WHERE cohort_id=?",
                       (cohort_id,)).fetchone()
    c.close()
    if not cohort: return {}
    cohort = dict(cohort)

    closed = [t for t in trades if t['status'] != 'OPEN'
              and not (t.get('exit_type') or '').startswith('BUG_')]
    open_pos = [t for t in trades if t['status'] == 'OPEN']
    wins = [t for t in closed if (t.get('pnl_eur') or 0) > 0]
    losses = [t for t in closed if (t.get('pnl_eur') or 0) < 0]
    total_pnl = sum((t.get('pnl_eur') or 0) for t in closed)
    unrealized = 0  # would need live price calc

    return {
        'cohort_id': cohort_id,
        'started_at': cohort['started_at'],
        'initial_capital_eur': cohort['initial_capital_eur'],
        'current_cash_eur': cohort['current_cash_eur'],
        'n_trades_total': len(trades),
        'n_closed': len(closed),
        'n_wins': len(wins),
        'n_losses': len(losses),
        'win_rate': round(len(wins) / max(len(closed), 1) * 100, 1),
        'realized_pnl_eur': round(total_pnl, 2),
        'realized_pnl_pct': round(total_pnl / cohort['initial_capital_eur'] * 100, 2),
        'n_open_positions': len(open_pos),
        'best_trade_eur': max((t.get('pnl_eur') or 0) for t in closed) if closed else 0,
        'worst_trade_eur': min((t.get('pnl_eur') or 0) for t in closed) if closed else 0,
        'aggression_profile': cohort.get('aggression_profile'),
    }


def manage_lifecycle() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    now = datetime.now(timezone.utc)
    today = now.date()
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    cohorts = [dict(r) for r in c.execute("SELECT * FROM paper_cohorts").fetchall()]

    transitions = []
    anniversaries = []

    for cohort in cohorts:
        cid = cohort['cohort_id']
        status = cohort['status']

        # 1-Jahr-Anniversary Check
        try:
            min_lifetime = date.fromisoformat(cohort['min_lifetime_until'])
            if today >= min_lifetime and status == 'ACTIVE':
                # Anniversary erreicht → Summary erstellen
                summary = _cohort_anniversary_summary(cid)
                SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
                f = SUMMARIES_DIR / f'{cid}_anniversary.json'
                if not f.exists():
                    f.write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
                    anniversaries.append(cid)
                    # Markiere als PENDING_VICTOR_DECISION
                    c.execute("UPDATE paper_cohorts SET status='PENDING_DECISION', "
                              "notes=notes || ? WHERE cohort_id=?",
                              (f' [Anniversary {today} — Summary erstellt, Victor-Entscheidung pending]', cid))
                    transitions.append({'cohort_id': cid, 'from': 'ACTIVE',
                                        'to': 'PENDING_DECISION',
                                        'reason': '1-year anniversary'})
                    # CEO-Inbox + Discord-fähig
                    try:
                        sys.path.insert(0, str(WS / 'scripts'))
                        from ceo_inbox import write_event
                        write_event(
                            event_type='cohort.anniversary',
                            message=f'Kohorte {cid} hat 1 Jahr erreicht. PnL: {summary.get("realized_pnl_pct","?")}%, WR: {summary.get("win_rate","?")}%. Victor-Entscheidung pending: einstellen oder weiterlaufen?',
                            severity='warning', category='health',
                            user_pinged=True,  # Anniversary: Victor MUSS sehen
                            payload=summary,
                        )
                    except Exception: pass
        except Exception: pass

        # WINDDOWN → CLOSED: alle Positionen zu?
        if status == 'WINDDOWN':
            n_open = c.execute(
                "SELECT COUNT(*) FROM paper_portfolio "
                "WHERE cohort_id=? AND status='OPEN'", (cid,)
            ).fetchone()[0]
            if n_open == 0:
                c.execute("UPDATE paper_cohorts SET status='CLOSED' WHERE cohort_id=?", (cid,))
                transitions.append({'cohort_id': cid, 'from': 'WINDDOWN',
                                    'to': 'CLOSED', 'reason': 'all_positions_closed'})

    c.commit()
    c.close()
    return {
        'ts': now.isoformat(timespec='seconds'),
        'transitions': transitions,
        'anniversaries': anniversaries,
    }


def main() -> int:
    r = manage_lifecycle()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
