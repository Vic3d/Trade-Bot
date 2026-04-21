#!/usr/bin/env python3
"""Catalyst Re-Eval Job
=====================
Taeglich 08:00 CET im Scheduler.

Logik:
  1. Scanne alle Strategien in strategies.json
  2. Wenn catalyst.date <= today AND catalyst.fired == False:
     → setze fired=True, fired_date=today (auto-fire)
  3. Wenn catalyst.fired_date + 7-9 Tage == today:
     → queue Ticker fuer LLM Deep Dive (re-evaluation)
  4. Wenn catalyst.fired_date + horizon_days + 7 < today:
     → mark catalyst.state = EXPIRED, Discord-Alert

Usage:
  python3 scripts/intelligence/catalyst_reeval.py
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
STRATS = WS / 'data' / 'strategies.json'
QUEUE = WS / 'data' / 'deepdive_queue.json'
LOG = WS / 'data' / 'catalyst_reeval.log'

sys.path.insert(0, str(WS / 'scripts'))
try:
    from intelligence.catalyst_utils import catalyst_status, needs_reeval
except Exception as e:
    print(f'FATAL import catalyst_utils: {e}')
    sys.exit(1)


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec='seconds')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    try:
        return json.loads(QUEUE.read_text(encoding='utf-8'))
    except Exception:
        return []


def _save_queue(q: list[dict]) -> None:
    QUEUE.write_text(json.dumps(q, indent=2, ensure_ascii=False), encoding='utf-8')


def run() -> dict:
    if not STRATS.exists():
        _log('FATAL strategies.json fehlt')
        return {'error': 'no_strategies'}

    strats = json.loads(STRATS.read_text(encoding='utf-8'))
    today = date.today()
    today_str = today.isoformat()

    stats = {
        'scanned': 0, 'auto_fired': 0, 'queued_reeval': 0,
        'expired': 0, 'pending': 0, 'fresh': 0, 'mature': 0
    }
    queue = _load_queue()
    changed = False

    for sid, cfg in strats.items():
        if not isinstance(cfg, dict):
            continue
        if sid.startswith('_') or sid == 'emerging_themes':
            continue
        cat = cfg.get('catalyst')
        if not cat:
            continue
        stats['scanned'] += 1

        # 1) Auto-Fire wenn Datum erreicht
        cat_date_s = cat.get('date')
        if cat_date_s and not cat.get('fired'):
            try:
                cat_date = datetime.fromisoformat(str(cat_date_s)[:10]).date()
                if cat_date <= today:
                    cfg['catalyst']['fired'] = True
                    cfg['catalyst']['fired_date'] = today_str
                    stats['auto_fired'] += 1
                    changed = True
                    _log(f'AUTO_FIRE {sid}: "{cat.get("event", "?")[:60]}"')
            except Exception:
                pass

        # Secondary auto-fire
        sec = cat.get('secondary')
        if sec and sec.get('date') and not sec.get('fired'):
            try:
                sec_date = datetime.fromisoformat(str(sec['date'])[:10]).date()
                if sec_date <= today:
                    cfg['catalyst']['secondary']['fired'] = True
                    cfg['catalyst']['secondary']['fired_date'] = today_str
                    stats['auto_fired'] += 1
                    changed = True
                    _log(f'AUTO_FIRE_SEC {sid}: "{sec.get("event", "?")[:60]}"')
            except Exception:
                pass

        # 2) Re-Eval faellig?
        needs, reason = needs_reeval(cfg, reeval_after_days=7)
        if needs:
            tickers = cfg.get('tickers') or ([cfg.get('ticker')] if cfg.get('ticker') else [])
            for tk in tickers:
                if not tk:
                    continue
                queue.append({
                    'ticker': tk,
                    'strategy': sid,
                    'queued_at': datetime.now().isoformat(timespec='seconds'),
                    'reason': f'catalyst_reeval: {reason}',
                    'priority': 'high',
                })
                stats['queued_reeval'] += 1
                _log(f'QUEUE_REEVAL {tk} (strat={sid}): {reason}')
            cfg['last_catalyst_reeval'] = today_str
            changed = True

        # Status-Stats
        cs = catalyst_status(cfg)
        if cs['state'] == 'PENDING':
            stats['pending'] += 1
        elif cs['state'] == 'FRESH':
            stats['fresh'] += 1
        elif cs['state'] == 'MATURE':
            stats['mature'] += 1
        elif cs['state'] == 'STALE':
            stats['expired'] += 1

    if changed:
        STRATS.write_text(json.dumps(strats, indent=2, ensure_ascii=False), encoding='utf-8')
        _log('strategies.json aktualisiert')

    if stats['queued_reeval']:
        _save_queue(queue)
        _log(f'deepdive_queue.json: {len(queue)} Eintraege')

    _log(f'STATS {stats}')
    return stats


if __name__ == '__main__':
    stats = run()
    print('\n── Catalyst Re-Eval Summary ──')
    for k, v in stats.items():
        print(f'  {k:15} {v}')
