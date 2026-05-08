#!/usr/bin/env python3
"""
data_janitor.py — Phase 45ag

Löscht stale + offensichtlich obsolete Files in data/.
Konservative Whitelist-basierte Logik: löscht NUR wenn Pattern + Alter passen.

Patterns (Auto-Delete wenn älter als TTL):
- *.bak.*           : 30d
- *_seen.json       : 30d
- *.tmp / *.swp     : 1d
- discord_dedupe.json archive: 7d (wird live geschrieben, kein Problem)

Whitelist (NIE löschen, egal wie alt):
- strategies.json, trading.db, trading_learnings.json, paper_fund.json
- ceo_directive.json, ceo_inbox.jsonl, current_truth.json
- alle dirs (subfolders bleiben unangetastet)

Run: 1x/Woche (Sonntag 02:00) via Scheduler.
CLI: --dry-run für Preview.
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DATA = WS / 'data'
LOG = WS / 'data' / 'janitor_log.jsonl'

# Pattern → max_age_days
PATTERNS = [
    ('.bak.', 14),  # Phase 45ag: 30d→14d für Auto-Backups
    ('_seen.json', 14),
    ('.tmp', 1),
    ('.swp', 1),
    ('test_mode.json', 14),
    ('broad_scanner_', 14),
    ('discord_queue_low.jsonl.archive', 7),
    ('alternative_data.json', 30),  # 418h alt, nichts mehr
    ('midterm_bias.json', 30),       # 379h alt
]

# Hard-Whitelist (nie löschen)
WHITELIST_NAMES = {
    'strategies.json', 'trading.db', 'trading_learnings.json',
    'paper_fund.json', 'ceo_directive.json', 'ceo_inbox.jsonl',
    'current_truth.json', 'deep_dive_verdicts.json',
    'proposals.json', 'correlations.json',
}


def _pattern_match(name: str, pat: str) -> bool:
    return pat in name


def sweep(dry_run: bool = False) -> dict:
    if not DATA.exists():
        return {'error': 'no_data_dir'}

    now = time.time()
    candidates = []
    for f in DATA.iterdir():
        if not f.is_file():
            continue
        if f.name in WHITELIST_NAMES:
            continue
        age_d = (now - f.stat().st_mtime) / 86400
        for pat, max_age in PATTERNS:
            if _pattern_match(f.name, pat) and age_d > max_age:
                candidates.append({
                    'name': f.name,
                    'age_days': round(age_d, 1),
                    'matched_pattern': pat,
                    'size_kb': round(f.stat().st_size / 1024, 1),
                })
                break

    if not dry_run:
        for c in candidates:
            try:
                (DATA / c['name']).unlink()
                c['deleted'] = True
            except Exception as e:
                c['deleted'] = False
                c['error'] = str(e)
        if candidates:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'action': 'janitor_sweep',
                    'deleted_count': sum(1 for c in candidates if c.get('deleted')),
                    'total_size_freed_kb': sum(c['size_kb'] for c in candidates if c.get('deleted')),
                    'items': candidates,
                }) + '\n')

    return {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'dry_run': dry_run,
        'candidates': len(candidates),
        'total_size_kb': sum(c['size_kb'] for c in candidates),
        'items': candidates,
    }


def main() -> int:
    dry = '--dry-run' in sys.argv
    r = sweep(dry_run=dry)
    print(json.dumps(r, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
