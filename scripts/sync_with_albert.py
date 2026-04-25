#!/usr/bin/env python3
"""
sync_with_albert.py — CLI-Helfer für Claude Code, um Alberts (Discord-Bot)
letzte Aktivität zu lesen.

Aufruf am Session-Start (oder zwischendurch):
    python3 scripts/sync_with_albert.py            # letzte 20 Discord-Turns
    python3 scripts/sync_with_albert.py -n 50      # mehr
    python3 scripts/sync_with_albert.py --since 2h # nur letzte 2h

Schreibt zusätzlich einen "claude_code"-System-Marker ins Shared Log,
damit Albert weiß, dass eine CLI-Session aktiv ist.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from conversation_log import tail, append


def _parse_since(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.match(r'^(\d+)\s*([hmdHMD])$', s.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == 'h':
        return datetime.now() - timedelta(hours=n)
    if unit == 'm':
        return datetime.now() - timedelta(minutes=n)
    if unit == 'd':
        return datetime.now() - timedelta(days=n)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-n', type=int, default=20)
    ap.add_argument('--since', type=str, help='Filter z.B. "2h" "30m" "1d"')
    ap.add_argument('--no-marker', action='store_true',
                    help='Keinen "CLI active"-Marker schreiben')
    ap.add_argument('--summary', type=str,
                    help='Optional: Zusammenfassung was diese CLI-Session gemacht hat')
    args = ap.parse_args()

    cutoff = _parse_since(args.since)
    entries = tail(args.n)

    if cutoff:
        entries = [
            e for e in entries
            if e.get('ts') and datetime.fromisoformat(e['ts'][:19]) >= cutoff
        ]

    print(f'─── Albert-Sync: {len(entries)} Einträge '
          f'{"(seit " + args.since + ")" if args.since else ""} ───')
    if not entries:
        print('  (keine Einträge — Albert war ruhig)')
    else:
        for e in entries:
            ts = (e.get('ts') or '')[11:19]
            src = e.get('source', '?')
            spk = e.get('speaker', '?')
            content = (e.get('content') or '').strip().replace('\n', ' ')
            if len(content) > 280:
                content = content[:280] + '…'
            print(f'  [{ts} {src:7s}/{spk:11s}] {content}')

    # Marker setzen — Albert sieht beim nächsten DM, dass eine CLI-Session lief
    if not args.no_marker:
        msg = args.summary or 'Claude Code CLI session aktiv'
        append(source='cli', role='system', speaker='claude_code',
               content=msg, meta={'event': 'session_sync'})
        print(f'\n[ok] Marker im Shared Log gesetzt: "{msg[:80]}"')


if __name__ == '__main__':
    main()
