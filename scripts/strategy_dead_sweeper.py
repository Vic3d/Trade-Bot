#!/usr/bin/env python3
"""
strategy_dead_sweeper.py — Phase 45ag

Liest strategy_lifecycle.json. Strategien in Stage 'DEAD' (keine Tickers,
keine Code-Referenz) werden auf status='archived' gesetzt nach 14d Karenz.

Reversibel: archived ≠ deleted. Reaktivierung möglich.
Idempotent: wenn schon archived, kein Change.

Run: täglich 23:55 via Scheduler.
CLI: --dry-run für Preview.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
STRATEGIES = WS / 'data' / 'strategies.json'
LIFECYCLE = WS / 'data' / 'strategy_lifecycle.json'
LOG = WS / 'data' / 'strategy_archive_log.jsonl'

GRACE_DAYS = 14


def sweep(dry_run: bool = False) -> dict:
    if not LIFECYCLE.exists():
        return {'error': 'run_strategy_lifecycle_audit_first'}
    lc = json.loads(LIFECYCLE.read_text(encoding='utf-8'))
    dead_ids = [it['id'] for it in lc.get('by_stage', {}).get('DEAD', [])]

    if not STRATEGIES.exists():
        return {'error': 'no_strategies_file'}
    strategies = json.loads(STRATEGIES.read_text(encoding='utf-8'))

    now = datetime.now(timezone.utc)
    archived: list[str] = []
    skipped: list[dict] = []

    for sid in dead_ids:
        meta = strategies.get(sid)
        if not isinstance(meta, dict):
            continue
        if meta.get('status') != 'active':
            continue

        # Grace: created_at oder genesis_date prüfen
        created_str = meta.get('created_at') or meta.get('genesis_date') or ''
        try:
            created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
        except Exception:
            created = now - timedelta(days=GRACE_DAYS + 1)  # zähle als alt genug

        age_d = (now - created).days
        if age_d < GRACE_DAYS:
            skipped.append({'id': sid, 'reason': f'grace_period age={age_d}d'})
            continue

        if dry_run:
            archived.append(sid)
            continue

        meta['status'] = 'archived'
        meta['archived_at'] = now.isoformat(timespec='seconds')
        meta['archived_reason'] = 'lifecycle_dead_no_tickers_no_code_ref'
        archived.append(sid)

    if not dry_run and archived:
        STRATEGIES.write_text(json.dumps(strategies, indent=2), encoding='utf-8')
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': now.isoformat(timespec='seconds'),
                'action': 'archive_dead',
                'archived': archived,
                'count': len(archived),
            }) + '\n')

    return {
        'ts': now.isoformat(timespec='seconds'),
        'dry_run': dry_run,
        'dead_total': len(dead_ids),
        'archived': archived,
        'skipped': skipped,
        'archived_count': len(archived),
    }


def main() -> int:
    dry = '--dry-run' in sys.argv
    r = sweep(dry_run=dry)
    print(json.dumps(r, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
