#!/usr/bin/env python3
"""
cohort_manager.py — Phase 45at (Victor 2026-05-12).

Erzeugt am 1. jedes Monats eine neue Trading-Kohorte mit:
  - 25.000 EUR Startkapital
  - Aggression-Profil basierend auf Parent-Performance (auto-Skalierung)
  - Learning-Briefing aus Parent-Kohorte
  - 1-Jahr-Mindest-Lifetime

Run: 1. jedes Monats 00:01 via Scheduler.
Idempotent: erzeugt nur wenn diese Kohorte noch nicht existiert.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LEARNINGS_DIR = WS / 'data' / 'cohort_learnings'

INITIAL_CAPITAL = 25000.0
MIN_LIFETIME_DAYS = 365


def _parent_cohort_id(now: datetime) -> str:
    """Letzte Kohorte = aktueller Monat - 1."""
    if now.month == 1:
        return f"{now.year-1}-12"
    return f"{now.year}-{now.month-1:02d}"


def _current_cohort_id(now: datetime) -> str:
    return f"{now.year}-{now.month:02d}"


def _load_parent_performance(parent_id: str) -> dict:
    """Hole Performance-Stats der Parent-Kohorte."""
    if not DB.exists(): return {}
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        trades = c.execute(
            "SELECT pnl_eur, exit_type, status FROM paper_portfolio WHERE cohort_id=?",
            (parent_id,)
        ).fetchall()
        c.close()
        closed = [r for r in trades if r['pnl_eur'] is not None
                  and not (r['exit_type'] or '').startswith('BUG_')]
        n = len(closed)
        if n == 0:
            return {'n_trades': 0, 'has_data': False}
        wins = sum(1 for r in closed if r['pnl_eur'] > 0)
        total_pnl = sum(r['pnl_eur'] for r in closed)
        return {
            'has_data': True,
            'n_trades': n,
            'wins': wins,
            'win_rate': round(wins / n * 100, 1) if n else 0,
            'total_pnl_eur': round(total_pnl, 2),
            'pnl_pct': round(total_pnl / INITIAL_CAPITAL * 100, 2),
        }
    except Exception:
        return {}


def _next_aggression_profile(parent_id: str | None) -> dict:
    """Automatische Eskalation basierend auf Parent-Performance.

    Defaults: konservativ. Steigerung nur bei nachgewiesener positiver Performance.
    """
    base = {
        'risk_per_trade': 0.015,  # Phase 1: schon aggressiver als Mai (1.5%)
        'kelly_cap': 0.07,         # 7% statt 5%
        'max_absolute_eur': 3000,  # leicht höher
        'max_trades_per_week': 7,
    }
    if not parent_id:
        return base
    perf = _load_parent_performance(parent_id)
    if not perf.get('has_data'):
        return base

    # Trigger-basiert eskalieren
    pnl_pct = perf.get('pnl_pct', 0)
    n_trades = perf.get('n_trades', 0)
    win_rate = perf.get('win_rate', 0)

    if n_trades >= 10 and pnl_pct > 5 and win_rate > 50:
        # Parent war erfolgreich → Skalieren
        base['risk_per_trade'] = 0.02
        base['kelly_cap'] = 0.09
        base['max_absolute_eur'] = 4000
    if n_trades >= 15 and pnl_pct > 10 and win_rate > 55:
        # Parent war sehr erfolgreich → noch aggressiver
        base['risk_per_trade'] = 0.025
        base['kelly_cap'] = 0.10
        base['max_absolute_eur'] = 5000

    return base


def _next_sector_cap_pct(parent_id: str | None) -> float:
    """Sektor-Cap pro Kohorte. Default 25% (strenger als global 35%)."""
    return 0.25


def _read_learning_briefing(parent_id: str | None) -> str:
    """Lade Learning-Briefing aus letzter Extraction."""
    if not parent_id: return ''
    f = LEARNINGS_DIR / f'briefing_for_{parent_id}_successor.json'
    if not f.exists(): return ''
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return json.dumps(d, indent=2, ensure_ascii=False)
    except Exception: return ''


def create_new_cohort_if_needed() -> dict:
    if not DB.exists():
        return {'error': 'no_db'}
    now = datetime.now(timezone.utc)
    cohort_id = _current_cohort_id(now)
    parent_id = _parent_cohort_id(now)

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Idempotent: skip wenn schon existiert
    existing = c.execute("SELECT cohort_id FROM paper_cohorts WHERE cohort_id=?",
                         (cohort_id,)).fetchone()
    if existing:
        c.close()
        return {'cohort_id': cohort_id, 'status': 'already_exists', 'parent': parent_id}

    profile = _next_aggression_profile(parent_id)
    sector_cap = _next_sector_cap_pct(parent_id)
    parent_perf = _load_parent_performance(parent_id) if parent_id else {}
    min_lifetime = (now + timedelta(days=MIN_LIFETIME_DAYS)).date().isoformat()

    notes = (
        f"Auto-Created {now.isoformat(timespec='seconds')}. "
        f"Parent: {parent_id} (PnL {parent_perf.get('pnl_pct','n/a')}%, "
        f"WR {parent_perf.get('win_rate','n/a')}%, n={parent_perf.get('n_trades',0)}). "
        f"Aggression: {profile['risk_per_trade']*100:.1f}% risk, "
        f"{profile['kelly_cap']*100:.0f}% kelly-cap."
    )

    c.execute("""
        INSERT INTO paper_cohorts
        (cohort_id, started_at, initial_capital_eur, current_cash_eur,
         status, aggression_profile, sector_cap_pct, parent_cohort_id,
         min_lifetime_until, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (cohort_id, now.isoformat(timespec='seconds'), INITIAL_CAPITAL,
          INITIAL_CAPITAL, 'ACTIVE', json.dumps(profile), sector_cap,
          parent_id, min_lifetime, notes))
    c.commit()
    c.close()

    # CEO-Inbox-Event
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from ceo_inbox import write_event
        write_event(
            event_type='cohort.created',
            message=f'Neue Kohorte {cohort_id} geboren mit 25k EUR. Parent: {parent_id}. '
                    f'Aggression risk={profile["risk_per_trade"]*100:.1f}%.',
            severity='info', category='health',
            user_pinged=False,
            payload={'cohort_id': cohort_id, 'profile': profile,
                     'parent': parent_id, 'parent_perf': parent_perf},
        )
    except Exception: pass

    return {
        'cohort_id': cohort_id,
        'status': 'created',
        'parent': parent_id,
        'parent_perf': parent_perf,
        'profile': profile,
        'sector_cap': sector_cap,
        'min_lifetime_until': min_lifetime,
    }


def main() -> int:
    r = create_new_cohort_if_needed()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
