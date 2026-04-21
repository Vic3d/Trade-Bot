#!/usr/bin/env python3
"""
Catalyst-aware State Machine — Phase 22
========================================
Wird von ceo.py / entry_gate.py / strategy_validator.py / thesis_monitor importiert.

States:
  PENDING              — catalyst.date > today, noch nicht gefeuert
  PENDING_SECONDARY    — Sekundaer-Event (z.B. Earnings) in <14d
  FRESH                — gefeuert vor <=14 Tagen
  MATURE               — 14 < days_since <= horizon_days
  STALE                — days_since > horizon_days
  NONE                 — kein Katalysator-Feld

Lock-Override: raw_locked=True wird uebersteuert wenn lock_override=True
(PENDING / PENDING_SECONDARY / FRESH).
"""
from __future__ import annotations
from datetime import datetime, date


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def catalyst_status(strategy: dict) -> dict:
    """
    Returns dict mit: has_catalyst, state, days_since_fire, days_until_fire,
    lock_override, reason.
    """
    cat = strategy.get('catalyst') or {}
    secondary = cat.get('secondary') or {}
    today = datetime.now().date()

    if not cat:
        return {
            'has_catalyst': False, 'state': 'NONE',
            'days_since_fire': None, 'days_until_fire': None,
            'lock_override': False,
            'reason': 'Kein Katalysator-Feld',
        }

    cat_date = _parse_date(cat.get('date'))
    fired = cat.get('fired', False)
    fired_date = _parse_date(cat.get('fired_date')) or cat_date
    horizon_days = int(cat.get('horizon_days', 60))

    sec_date = _parse_date(secondary.get('date'))
    sec_fired = secondary.get('fired', False)

    # PENDING primary
    if cat_date and not fired:
        days_until = (cat_date - today).days
        if days_until > 0:
            return {
                'has_catalyst': True, 'state': 'PENDING',
                'days_since_fire': None, 'days_until_fire': days_until,
                'lock_override': True,
                'reason': f'Katalysator "{cat.get("event", "?")}" in {days_until}d',
            }

    # PENDING secondary (in <=14d)
    if sec_date and not sec_fired:
        days_until_sec = (sec_date - today).days
        if 0 <= days_until_sec <= 14:
            return {
                'has_catalyst': True, 'state': 'PENDING_SECONDARY',
                'days_since_fire': (today - fired_date).days if fired_date else None,
                'days_until_fire': days_until_sec,
                'lock_override': True,
                'reason': f'Sec-Event "{secondary.get("event", "?")}" in {days_until_sec}d',
            }

    # FRESH / MATURE / STALE
    if fired_date:
        days_since = (today - fired_date).days
        if 0 <= days_since <= 14:
            return {
                'has_catalyst': True, 'state': 'FRESH',
                'days_since_fire': days_since, 'days_until_fire': None,
                'lock_override': True,
                'reason': f'Katalysator feuerte vor {days_since}d',
            }
        if days_since <= horizon_days:
            return {
                'has_catalyst': True, 'state': 'MATURE',
                'days_since_fire': days_since, 'days_until_fire': None,
                'lock_override': False,
                'reason': f'Fenster aktiv ({days_since}/{horizon_days}d)',
            }
        return {
            'has_catalyst': True, 'state': 'STALE',
            'days_since_fire': days_since, 'days_until_fire': None,
            'lock_override': False,
            'reason': f'Veraltet ({days_since}d > {horizon_days}d)',
        }

    return {
        'has_catalyst': True, 'state': 'UNKNOWN',
        'days_since_fire': None, 'days_until_fire': None,
        'lock_override': False,
        'reason': 'Katalysator-Feld unvollstaendig',
    }


def is_effectively_locked(strategy: dict) -> tuple[bool, str]:
    """Kern-API: ersetzt strategy.get('locked', False)."""
    raw_locked = bool(strategy.get('locked', False))
    if not raw_locked:
        return False, ''
    cat = catalyst_status(strategy)
    if cat['lock_override']:
        return False, f'LOCK_OVERRIDE: {cat["reason"]}'
    return True, strategy.get('lock_reason', 'locked')


def needs_reeval(strategy: dict, reeval_after_days: int = 7) -> tuple[bool, str]:
    """True wenn Strategie N Tage nach Fire neu bewertet werden sollte."""
    cat = catalyst_status(strategy)
    if cat['state'] not in ('FRESH', 'MATURE'):
        return False, cat['reason']
    days_since = cat['days_since_fire'] or 0
    if reeval_after_days <= days_since <= reeval_after_days + 2:
        last_reeval = strategy.get('last_catalyst_reeval', '')
        today_str = datetime.now().date().isoformat()
        if last_reeval != today_str:
            return True, f'Post-Catalyst Re-Eval faellig ({days_since}d seit Fire)'
    return False, ''
