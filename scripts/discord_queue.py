#!/usr/bin/env python3
"""
Discord Queue — Nachrichten-Buffer für tages-gebündelte Alerts
===============================================================

Nicht-kritische Events werden in data/discord_queue.json gesammelt.
Nur CRITICAL-Events (Hard-Exit, Circuit-Breaker) werden sofort gesendet.
Alles andere erscheint einmal täglich im Daily Digest (08:30 + 20:00 CET).

API:
    from discord_queue import queue_event, flush_and_send

    queue_event('info', 'Titel', 'Details...')
    queue_event('critical', 'STOP HIT', 'PLTR stop hit ...')  # → sofort
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
QUEUE_FILE = WS / 'data' / 'discord_queue.json'
SEND_IMMEDIATELY = {'critical', 'emergency'}


def _load_queue() -> list[dict]:
    try:
        if QUEUE_FILE.exists():
            return json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return []


def _save_queue(q: list[dict]) -> None:
    try:
        QUEUE_FILE.write_text(json.dumps(q, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'discord_queue save failed: {e}')


def _send_direct(msg: str) -> None:
    try:
        import sys
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        send(msg[:1900])
    except Exception as e:
        print(f'discord_queue direct send failed: {e}')


def queue_event(
    priority: str,  # 'critical'|'warning'|'info'|'success'
    title: str,
    body: str,
    source: str = '',
) -> None:
    """
    Queues an event for the daily digest.
    priority='critical' → sends immediately (hard exits, stop hits).
    """
    icons = {'critical': '🚨', 'warning': '⚠️', 'info': '📋', 'success': '✅'}
    icon = icons.get(priority, '📌')

    if priority in SEND_IMMEDIATELY:
        _send_direct(f'{icon} **{title}**\n{body}')
        return

    entry = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'priority': priority,
        'icon': icon,
        'title': title,
        'body': body,
        'source': source,
    }
    q = _load_queue()
    q.append(entry)
    _save_queue(q)


def flush_and_send(header: str = '', clear: bool = True) -> int:
    """
    Builds a consolidated digest from the queue and sends it to Discord.
    Returns number of events included. Clears queue unless clear=False.
    """
    q = _load_queue()
    if not q:
        return 0

    # Sort by priority (critical first, then info)
    order = {'critical': 0, 'warning': 1, 'success': 2, 'info': 3}
    q.sort(key=lambda e: order.get(e.get('priority', 'info'), 9))

    lines: list[str] = []
    if header:
        lines.append(header)

    prev_source = None
    for e in q:
        # Group by source with separator
        if e.get('source') and e['source'] != prev_source:
            lines.append(f"\n**— {e['source']} —**")
            prev_source = e['source']
        lines.append(f"{e['icon']} **{e['title']}** {e['body']}")

    # Discord 2000-char limit — if too long, summarize
    msg = '\n'.join(lines)
    if len(msg) > 1800:
        # Send header + count summary
        top = '\n'.join(lines[:15])
        rest = len(lines) - 15
        msg = top + f'\n_...und {rest} weitere Events. Vollständig in data/discord_queue.json._'

    _send_direct(msg)

    if clear:
        _save_queue([])

    return len(q)


def queue_size() -> int:
    return len(_load_queue())
