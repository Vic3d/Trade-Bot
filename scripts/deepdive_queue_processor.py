#!/usr/bin/env python3
"""
Deep-Dive Queue Processor — Phase 6.7
======================================
Verarbeitet data/deepdive_requests.json ohne LLM-Call:
  - Prüft welche Tickers noch auf Deep Dive warten
  - Triggert `autonomous_ceo.execute_deep_dive()` für Top-N pro Run
  - Queue wird automatisch durch execute_deep_dive geleert

Läuft alle 2h zwischen 08-23h CET (auch außerhalb Marktzeiten, da Deep
Dives jederzeit Sinn machen — News kommen ja auch nach Börsenschluss).

Unterschied zum autonomous_ceo run:
  - autonomous_ceo nur 6x/Tag Mo-Fr, macht full-context LLM
  - Dieser Processor nur für die Queue, läuft öfter, macht nur deep_dive

Max 3 Deep Dives pro Run (Token-Budget + Qualität statt Spam).

Usage:
  python3 scripts/deepdive_queue_processor.py              # Normal
  python3 scripts/deepdive_queue_processor.py --max 5      # Override
  python3 scripts/deepdive_queue_processor.py --dry-run    # Nur zeigen
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
DATA = WS / 'data'
QUEUE_FILE = DATA / 'deepdive_requests.json'
VERDICTS_FILE = DATA / 'deep_dive_verdicts.json'

log = logging.getLogger('dq_processor')


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _has_fresh_verdict(ticker: str) -> bool:
    """Skip wenn Ticker schon frischen KAUFEN-Verdict hat."""
    verdicts = _load(VERDICTS_FILE, {})
    v = verdicts.get(ticker.upper(), {})
    if not v or v.get('verdict') != 'KAUFEN':
        return False
    try:
        age = (datetime.now(_BERLIN) - datetime.fromisoformat(v['date'])).days
        return age <= 14
    except Exception:
        return False


def process_queue(max_n: int = 8, dry_run: bool = False) -> dict:
    queue = _load(QUEUE_FILE, [])
    if not isinstance(queue, list):
        return {'error': 'bad_queue_format'}

    # Sortiere nach Score DESC, dann Age DESC
    cutoff_12h = (datetime.now(_BERLIN) - timedelta(hours=36)).isoformat()  # Phase 24 aggressive: 12→36h
    fresh = [q for q in queue
             if isinstance(q, dict)
             and q.get('ts', '') > cutoff_12h  # 36h Window (Phase 24 aggressive)
             and not _has_fresh_verdict(q.get('ticker', ''))]
    fresh.sort(key=lambda q: (q.get('score', 0), q.get('ts', '')), reverse=True)

    to_process = fresh[:max_n]

    print(f'=== Deep-Dive Queue Processor {"[DRY]" if dry_run else ""} ===')
    print(f'Queue total: {len(queue)} | Fresh (<12h, kein KAUFEN): {len(fresh)}')
    print(f'Verarbeite: {len(to_process)} (max {max_n})')

    if not to_process:
        return {'processed': 0, 'queue_size': len(queue)}

    for q in to_process:
        print(f'  → {q.get("ticker")} (score {q.get("score")}, '
              f'thesis {q.get("thesis_id")}): {q.get("reason", "")[:70]}')

    if dry_run:
        return {'processed': 0, 'dry_run': True, 'would_process': len(to_process)}

    # Execute deep dives
    try:
        from autonomous_ceo import execute_deep_dive
    except Exception as e:
        print(f'❌ Import autonomous_ceo fehlgeschlagen: {e}')
        return {'error': str(e)}

    results = []
    for q in to_process:
        ticker = q.get('ticker', '').upper()
        reason = f"News-Queue: {q.get('reason','')[:100]} (Score {q.get('score')})"
        try:
            verdict = execute_deep_dive(ticker, reason, dry_run=False)
            results.append({'ticker': ticker, 'verdict': verdict})
            print(f'  ✓ {ticker} → {verdict}')
        except Exception as e:
            print(f'  ✗ {ticker} Fehler: {e}')
            results.append({'ticker': ticker, 'error': str(e)})

    return {
        'processed': len(results),
        'results': results,
        'queue_size_before': len(queue),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=8)  # Phase 24 aggressive: 3→8
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    r = process_queue(max_n=args.max, dry_run=args.dry_run)
    print(f'\nResult: {r}')


if __name__ == '__main__':
    main()
