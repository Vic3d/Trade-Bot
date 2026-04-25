#!/usr/bin/env python3
"""
inject_albert_context.py — UserPromptSubmit Hook für Claude Code.

Wird vor jedem User-Prompt automatisch ausgeführt (siehe .claude/settings.json).
Holt Alberts letzte Discord-Aktivität vom Server und injiziert sie als
zusätzlichen Kontext, damit Claude Code (ich) weiß, was Victor mit Albert
besprochen hat — ohne dass Victor "sync" sagen muss.

Mechanik:
  1. Cache-Check: data/.albert_sync_cache.json — wenn jünger als 60s, nutze Cache
  2. Sonst: SSH zum Server, hole tail -n 30 von conversation_log.jsonl
  3. Output (stdout) wird via Claude-Hook-Protokoll als additionalContext
     Claude in den Prompt injiziert

Output-Format (JSON für UserPromptSubmit-Hook):
    {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "## Alberts letzte Discord-Aktivität\n..."
    }}

Bei Fehler (SSH down, Server unreachable etc.): silent exit 0 ohne Output
→ Claude bekommt kein extra Context aber Prompt geht durch.

Performance-Budget: max 3s, sonst skip (User soll nicht warten).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
CACHE_FILE = WS / 'data' / '.albert_sync_cache.json'
CACHE_TTL_SECONDS = 60
SSH_TIMEOUT = 3
SERVER = 'root@178.104.152.135'
REMOTE_LOG = '/opt/trademind/data/conversation_log.jsonl'
TAIL_N = 25
MAX_AGE_HOURS = 12  # Nur Einträge der letzten 12h zeigen


def _load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        if time.time() - data.get('cached_at', 0) < CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def _save_cache(entries: list[dict], context_text: str) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            'cached_at': time.time(),
            'entries': entries,
            'context_text': context_text,
        }, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _fetch_remote_log() -> list[dict]:
    """SSH zum Server, lese letzte TAIL_N Zeilen aus conversation_log.jsonl."""
    cmd = [
        'ssh',
        '-o', f'ConnectTimeout={SSH_TIMEOUT}',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'BatchMode=yes',  # Kein Passwort-Prompt → fail fast
        SERVER,
        f'tail -n {TAIL_N} {REMOTE_LOG} 2>/dev/null',
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=SSH_TIMEOUT + 2, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []
    entries = []
    for line in (result.stdout or '').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def _format_context(entries: list[dict]) -> str:
    """Formatiert Einträge als kompakter Markdown-Block."""
    if not entries:
        return ''

    # Filter auf MAX_AGE_HOURS
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(hours=MAX_AGE_HOURS)
    recent = []
    for e in entries:
        ts = e.get('ts', '')
        try:
            if datetime.fromisoformat(ts[:19]) >= cutoff:
                recent.append(e)
        except Exception:
            recent.append(e)  # Bei Parse-Fehler trotzdem mitnehmen

    if not recent:
        return ''

    # Discord/Albert-Einträge sind interessanter als CLI-Marker (eigene)
    lines = ['## Alberts Discord-Aktivität (letzte 12h, automatisch via Hook)']
    lines.append('_Was Victor mit Albert besprochen hat seit unserer letzten Interaktion._\n')

    for e in recent:
        ts = (e.get('ts') or '')[11:16]  # HH:MM
        src = e.get('source', '?')
        spk = e.get('speaker', '?')
        content = (e.get('content') or '').replace('\n', ' ').strip()
        if len(content) > 280:
            content = content[:280] + '…'
        # Markiere CLI/claude_code Marker visuell unterschiedlich
        if src == 'cli':
            lines.append(f'  · `{ts}` [CLI: {spk}] {content}')
        else:
            lines.append(f'  · `{ts}` **{spk}**: {content}')

    lines.append('\n_(Wenn relevant für Victors aktuelle Anfrage: berücksichtigen.)_')
    return '\n'.join(lines)


def main() -> int:
    # 1. Cache prüfen
    cached = _load_cache()
    if cached:
        ctx = cached.get('context_text', '')
        if ctx:
            _emit(ctx)
        return 0

    # 2. Remote fetch
    entries = _fetch_remote_log()
    if not entries:
        # Cache leeres Ergebnis kurz — vermeidet SSH-Spam wenn Server down
        _save_cache([], '')
        return 0

    ctx = _format_context(entries)
    _save_cache(entries, ctx)
    if ctx:
        _emit(ctx)
    return 0


def _emit(context: str) -> None:
    """Schreibt das Hook-Protokoll JSON nach stdout."""
    payload = {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': context,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        # Hook darf NIEMALS den User-Prompt blockieren
        print(f'[hook inject_albert_context] error: {e}', file=sys.stderr)
        sys.exit(0)
