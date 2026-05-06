#!/usr/bin/env python3
"""
strategy_throttle.py — Phase 45u (Victor 2026-05-06).

Zentraler MAX_ACTIVE-Throttle fuer alle Discovery-Pfade.

Problem (06.05.2026): Der Throttle in fast_discovery_trigger.py (50) griff
nicht — andere Pfade (thesis_discovery.py, strategy_discovery.py,
discovery_pipeline.py, hunter_research_mode) haben Strategien ohne Check
angelegt. Wachstum 40 → 60 in 24h trotz Cap.

Loesung: Eine zentrale Funktion can_create_new_strategy() die ueberall
VOR `strats[sid] = ...` gerufen wird. Wenn False → caller skipt + loggt.

Wird genutzt von:
  - scripts/discovery/discovery_pipeline.py
  - scripts/strategy_discovery.py
  - scripts/intelligence/thesis_discovery.py
  - scripts/fast_discovery_trigger.py (auch — dann konsistent)
"""
from __future__ import annotations
import json, os
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
STRATS_FILE = WS / 'data' / 'strategies.json'

MAX_ACTIVE_STRATEGIES = 50
DEAD_STATUSES = {'paused', 'retired', 'auto_deprecated', 'ARCHIVED', 'DRAFT'}


def count_active(strats: dict | None = None) -> int:
    """Zaehlt 'lebende' Strategien (alles ausser DEAD_STATUSES)."""
    if strats is None:
        if not STRATS_FILE.exists(): return 0
        try:
            strats = json.loads(STRATS_FILE.read_text(encoding='utf-8'))
        except Exception:
            return 0
    n = 0
    for sid, v in (strats or {}).items():
        if not isinstance(v, dict): continue
        if v.get('status') in DEAD_STATUSES: continue
        n += 1
    return n


def can_create_new_strategy(strats: dict | None = None) -> tuple[bool, str]:
    """Returns (allowed, reason). Vor jedem strats[sid] = ... aufrufen."""
    n = count_active(strats)
    if n >= MAX_ACTIVE_STRATEGIES:
        return False, (f'STRATEGY_THROTTLE: {n} active >= '
                       f'{MAX_ACTIVE_STRATEGIES} max — auto-deprecate '
                       f'(taeglich 23:00) muss erst aufraumen')
    return True, f'OK ({n}/{MAX_ACTIVE_STRATEGIES} active)'


def log_throttle_block(source: str, sid_attempted: str = '?') -> None:
    """Audit-Log wenn ein Pfad blockiert wurde."""
    try:
        from datetime import datetime, timezone
        log = WS / 'data' / 'strategy_throttle_log.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'source': source,
                'sid_attempted': sid_attempted,
                'n_active': count_active(),
                'cap': MAX_ACTIVE_STRATEGIES,
            }) + '\n')
    except Exception:
        pass
