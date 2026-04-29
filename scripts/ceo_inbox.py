#!/usr/bin/env python3
"""
ceo_inbox.py — Phase 43e: Internes Event-Feed für den CEO.

Architektur-Prinzip: Jeder System-Event wird IMMER hier festgehalten
(damit CEO den Überblick behält), aber nur User-relevante Events landen
zusätzlich auf Discord.

  Vorher: send_alert() → Discord (Victor wird gepingt) ODER nichts
  Nachher: send_alert() → ceo_inbox.jsonl (immer) + Discord (nur wenn whitelist)

CEO-Daemon liest bei jedem Cold-Cycle die seit-letztem Run unread Events
und kann darauf reagieren (Re-Eval, Position-Health-Check, etc.).

Usage:
  from ceo_inbox import write_event
  write_event('scheduler.recovered', 'Heartbeat zurück nach 601s', severity='info')

  from ceo_inbox import read_unread
  events = read_unread(consumer='ceo_daemon')  # markiert als read
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))

INBOX_FILE = WS / 'data' / 'ceo_inbox.jsonl'
CONSUMER_STATE = WS / 'data' / 'ceo_inbox_consumers.json'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_event(event_type: str, message: str,
                  severity: str = 'info',
                  category: str = 'general',
                  user_pinged: bool = False,
                  payload: dict | None = None) -> bool:
    """Schreibt Event ins CEO-Inbox-Feed.

    Args:
      event_type: kurzer Identifier wie 'scheduler.recovered', 'trade.executed'
      message: human-readable Beschreibung
      severity: info | warning | critical
      category: trade | thesis | macro | system | health | discovery | ...
      user_pinged: True wenn parallel auch Discord-Push ging
      payload: optional structured data
    """
    INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        'ts':          _now_iso(),
        'event_type':  event_type,
        'message':     message[:500],
        'severity':    severity,
        'category':    category,
        'user_pinged': user_pinged,
    }
    if payload and isinstance(payload, dict):
        entry['payload'] = {k: v for k, v in payload.items()
                             if isinstance(v, (str, int, float, bool, list, dict))}
    try:
        with open(INBOX_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True
    except Exception:
        return False


def read_unread(consumer: str = 'ceo_daemon',
                  max_events: int = 100,
                  mark_read: bool = True) -> list[dict]:
    """Lese alle Events seit letztem read durch diesen Consumer."""
    if not INBOX_FILE.exists():
        return []

    # Last-read-marker für consumer
    state = {}
    if CONSUMER_STATE.exists():
        try:
            state = json.loads(CONSUMER_STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {}
    last_ts = state.get(consumer, '1970-01-01T00:00:00Z')

    events = []
    new_last_ts = last_ts
    try:
        with open(INBOX_FILE, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get('ts', '') <= last_ts:
                    continue
                events.append(e)
                if e.get('ts', '') > new_last_ts:
                    new_last_ts = e['ts']
                if len(events) >= max_events:
                    break
    except Exception:
        pass

    if mark_read and events:
        state[consumer] = new_last_ts
        try:
            CONSUMER_STATE.write_text(json.dumps(state, indent=2),
                                       encoding='utf-8')
        except Exception:
            pass

    return events


def summarize_unread(consumer: str = 'ceo_daemon',
                       hours: int = 24) -> dict:
    """Statistik der letzten Events ohne mark-as-read (für Briefings)."""
    from collections import Counter
    if not INBOX_FILE.exists():
        return {'total': 0}
    cutoff = (datetime.now(timezone.utc).timestamp()
                - hours * 3600)
    by_severity = Counter()
    by_category = Counter()
    by_event_type = Counter()
    user_pinged = 0
    total = 0
    try:
        with open(INBOX_FILE, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts_s = e.get('ts', '')
                    ts_dt = datetime.fromisoformat(ts_s.replace('Z', '+00:00'))
                    if ts_dt.timestamp() < cutoff:
                        continue
                except Exception:
                    continue
                total += 1
                by_severity[e.get('severity', 'info')] += 1
                by_category[e.get('category', 'general')] += 1
                by_event_type[e.get('event_type', '?')] += 1
                if e.get('user_pinged'):
                    user_pinged += 1
    except Exception:
        pass
    return {
        'total': total,
        'window_hours': hours,
        'by_severity': dict(by_severity),
        'by_category': dict(by_category.most_common(10)),
        'top_event_types': dict(by_event_type.most_common(10)),
        'user_pinged': user_pinged,
        'silenced': total - user_pinged,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary', action='store_true', help='Show 24h summary')
    ap.add_argument('--unread', action='store_true', help='Show unread + mark')
    ap.add_argument('--consumer', default='cli')
    ap.add_argument('--hours', type=int, default=24)
    args = ap.parse_args()

    if args.summary:
        s = summarize_unread(hours=args.hours)
        print(json.dumps(s, indent=2))
    elif args.unread:
        events = read_unread(consumer=args.consumer)
        print(f'Unread events for {args.consumer}: {len(events)}')
        for e in events[-20:]:
            ping = '🔔' if e.get('user_pinged') else '🔕'
            print(f"  {ping} {e['ts'][:16]} [{e['severity']:<8}] "
                  f"[{e['category']:<10}] {e['event_type']:<30} {e['message'][:80]}")
    else:
        s = summarize_unread()
        print(f'Inbox last 24h: {s["total"]} events, {s["user_pinged"]} pinged, '
              f'{s["silenced"]} silenced')
    return 0


if __name__ == '__main__':
    sys.exit(main())
