#!/usr/bin/env python3
"""Catalyst-aware helpers. Wird von ceo.py / entry_gate.py / strategy_validator.py importiert.

Logik: Ein 'locked: true' wird UEBERSTEUERT wenn:
  - Der Katalysator noch NICHT gefeuert hat (date > today) → These hatte keine Chance
  - Der Katalysator INNERHALB 14 Tagen gefeuert hat → These gerade erst aktiv
  - Ein sekundaerer Katalysator noch bevorsteht (z.B. Earnings)

Das verhindert, dass Strategien wie PS_STLD gelockt werden, BEVOR ihr Hauptkatalysator gefeuert hat.
"""
from __future__ import annotations
from datetime import datetime, timedelta, date


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def catalyst_status(strategy: dict) -> dict:
    """
    Returns: {
        'has_catalyst': bool,
        'state': 'PENDING' | 'FRESH' | 'MATURE' | 'STALE' | 'NONE',
        'days_since_fire': int | None,
        'days_until_fire': int | None,
        'lock_override': bool,   # True => ignoriere 'locked' flag
        'reason': str,
    }
    """
    cat = strategy.get('catalyst') or {}
    secondary = cat.get('secondary') or {}
    today = datetime.now().date()

    if not cat:
        return {
            'has_catalyst': False, 'state': 'NONE',
            'days_since_fire': None, 'days_until_fire': None,
            'lock_override': False,
            'reason': 'Kein Katalysator-Feld in Strategie',
        }

    # Primary catalyst
    cat_date = _parse_date(cat.get('date'))
    fired = cat.get('fired', False)
    fired_date = _parse_date(cat.get('fired_date')) or cat_date
    horizon_days = int(cat.get('horizon_days', 60))

    # Secondary: z.B. Earnings nach Liberation Day
    sec_date = _parse_date(secondary.get('date'))
    sec_fired = secondary.get('fired', False)

    # Pending primary?
    if cat_date and not fired:
        days_until = (cat_date - today).days
        if days_until > 0:
            return {
                'has_catalyst': True, 'state': 'PENDING',
                'days_since_fire': None, 'days_until_fire': days_until,
                'lock_override': True,
                'reason': f'Katalysator "{cat.get("event", "?")}" feuert erst in {days_until} Tagen',
            }

    # Secondary pending?
    if sec_date and not sec_fired:
        days_until_sec = (sec_date - today).days
        if 0 <= days_until_sec <= 14:
            return {
                'has_catalyst': True, 'state': 'PENDING_SECONDARY',
                'days_since_fire': (today - fired_date).days if fired_date else None,
                'days_until_fire': days_until_sec,
                'lock_override': True,
                'reason': f'Sekundaerer Katalysator "{secondary.get("event", "?")}" in {days_until_sec}d',
            }

    # Fired but fresh (within 14 days)?
    if fired_date:
        days_since = (today - fired_date).days
        if 0 <= days_since <= 14:
            return {
                'has_catalyst': True, 'state': 'FRESH',
                'days_since_fire': days_since, 'days_until_fire': None,
                'lock_override': True,
                'reason': f'Katalysator feuerte vor {days_since}d, These braucht Zeit',
            }
        if days_since <= horizon_days:
            return {
                'has_catalyst': True, 'state': 'MATURE',
                'days_since_fire': days_since, 'days_until_fire': None,
                'lock_override': False,
                'reason': f'Katalysator-Fenster aktiv ({days_since}/{horizon_days}d)',
            }
        return {
            'has_catalyst': True, 'state': 'STALE',
            'days_since_fire': days_since, 'days_until_fire': None,
            'lock_override': False,
            'reason': f'Katalysator veraltet ({days_since}d > {horizon_days}d horizon)',
        }

    return {
        'has_catalyst': True, 'state': 'UNKNOWN',
        'days_since_fire': None, 'days_until_fire': None,
        'lock_override': False,
        'reason': 'Katalysator-Feld unvollstaendig',
    }


def is_effectively_locked(strategy: dict) -> tuple[bool, str]:
    """
    Kern-API: Ersetzt das direkte 'strategy.get("locked", False)' Check.

    Returns (locked, reason):
      locked=True   → Strategie wirklich blockiert
      locked=False  → Strategie handelbar (entweder nicht gelockt ODER Katalysator-Override)
    """
    raw_locked = bool(strategy.get('locked', False))
    if not raw_locked:
        return False, ''

    cat = catalyst_status(strategy)
    if cat['lock_override']:
        return False, f'LOCK_OVERRIDE: {cat["reason"]}'

    return True, strategy.get('lock_reason', 'locked')


def needs_reeval(strategy: dict, reeval_after_days: int = 7) -> tuple[bool, str]:
    """Returns True wenn Strategie >N Tage nach Katalysator-Fire neu bewertet werden sollte."""
    cat = catalyst_status(strategy)
    if cat['state'] != 'FRESH' and cat['state'] != 'MATURE':
        return False, cat['reason']

    days_since = cat['days_since_fire'] or 0
    # Trigger einmalig bei days_since == reeval_after_days ± 1
    if reeval_after_days <= days_since <= reeval_after_days + 2:
        last_reeval = strategy.get('last_catalyst_reeval', '')
        today_str = datetime.now().date().isoformat()
        if last_reeval != today_str:
            return True, f'Post-Catalyst Re-Eval faellig ({days_since}d seit Fire)'

    return False, ''
