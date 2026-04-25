#!/usr/bin/env python3
"""
conversation_log.py — Geteiltes Bewusstsein zwischen Albert (Discord)
und Claude Code (CLI).

Beide Instanzen schreiben in dieselbe Datei `data/conversation_log.jsonl`.
- Albert appendet jeden DM-Austausch (victor → albert → victor → ...)
- Claude Code appendet Session-Marker (chapter starts, important deploys)
Beide lesen die letzten N Einträge als Kontext bei jeder Antwort/Session-Start.

Format pro Zeile:
    {"ts": ISO8601, "source": "discord"|"cli", "role": "user"|"agent"|"system",
     "speaker": "victor"|"albert"|"claude_code", "content": "...",
     "meta": {...}}

Garantien:
- Append-only (kein Datenverlust durch Race Conditions)
- Atomic Writes via O_APPEND (POSIX-Garantie für Lines < PIPE_BUF=4096)
- Defensive: Fehler beim Loggen werfen NIE (silent fallback to print)

Public API:
    append(source, role, speaker, content, meta=None)
    tail(n=20) -> list[dict]
    format_for_context(n=15, max_chars=2000) -> str
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
LOG_FILE = WS / 'data' / 'conversation_log.jsonl'
MAX_LINE_BYTES = 3500  # Sicher unter PIPE_BUF=4096 für atomic append


def append(
    source: str,         # 'discord' | 'cli' | 'system'
    role: str,           # 'user' | 'agent' | 'system'
    speaker: str,        # 'victor' | 'albert' | 'claude_code' | 'scheduler' ...
    content: str,
    meta: dict | None = None,
) -> bool:
    """Hängt einen Eintrag an das gemeinsame Log an. Niemals raise."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'source': source,
            'role': role,
            'speaker': speaker,
            'content': (content or '')[:8000],  # Hard cap pro Eintrag
            'meta': meta or {},
        }
        line = json.dumps(entry, ensure_ascii=False)
        # Truncate falls über PIPE_BUF (atomic-append nicht garantiert sonst)
        if len(line.encode('utf-8')) > MAX_LINE_BYTES:
            entry['content'] = entry['content'][:1500] + '…[truncated]'
            line = json.dumps(entry, ensure_ascii=False)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        return True
    except Exception as e:
        print(f'[conversation_log] append failed: {e}', file=sys.stderr)
        return False


def tail(n: int = 20) -> list[dict]:
    """Liest die letzten N Einträge. Leere Liste wenn Datei fehlt/leer."""
    if not LOG_FILE.exists():
        return []
    try:
        # Effizient für große Files: read all + slice (bei N<200 ok bis MB-Bereich)
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception as e:
        print(f'[conversation_log] tail failed: {e}', file=sys.stderr)
        return []


def format_for_context(n: int = 15, max_chars: int = 2000) -> str:
    """Formatiert die letzten N Einträge als Kontext-Block für LLM-Prompts.

    Beispiel-Output:
        ## Letzte Konversationen (geteiltes Bewusstsein)
        [10:42 discord/victor] Wie sieht das Risk-Dashboard aus?
        [10:42 discord/albert] VaR 95%: 276 EUR (1.12% Fund) ...
        [11:15 cli/claude_code] Phase 21 deployed (commit 320b0d02)
    """
    entries = tail(n)
    if not entries:
        return ''
    lines = ['## Letzte Konversationen (geteiltes Bewusstsein Albert↔CLI)']
    for e in entries:
        ts = (e.get('ts') or '')[11:16]  # HH:MM
        src = e.get('source', '?')
        spk = e.get('speaker', '?')
        content = (e.get('content') or '').replace('\n', ' ')[:200]
        lines.append(f'[{ts} {src}/{spk}] {content}')
    text = '\n'.join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + '…[truncated]'
    return text


# CLI-Modus: zeige die letzten Einträge (für Debugging + sync_with_albert.py)
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Geteiltes Conversation-Log lesen')
    ap.add_argument('-n', type=int, default=20, help='Anzahl letzte Einträge')
    ap.add_argument('--format', choices=['raw', 'pretty', 'context'],
                    default='pretty')
    args = ap.parse_args()

    entries = tail(args.n)
    if not entries:
        print('(Log leer)')
        sys.exit(0)

    if args.format == 'raw':
        for e in entries:
            print(json.dumps(e, ensure_ascii=False))
    elif args.format == 'context':
        print(format_for_context(args.n))
    else:  # pretty
        for e in entries:
            ts = (e.get('ts') or '')[:19]
            src = e.get('source', '?')
            spk = e.get('speaker', '?')
            print(f'\n[{ts}] {src}/{spk}')
            print(f'  {(e.get("content") or "").strip()[:400]}')
