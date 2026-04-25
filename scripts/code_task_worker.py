#!/usr/bin/env python3
"""
code_task_worker.py — Stage 2: Discord als Universal-Inbox.

Wird von Albert (discord_chat.poll_once) aufgerufen, wenn die Nachricht
als Code-Task klassifiziert wurde (statt Trading-Frage). Spawnt einen
Headless Claude-Code-Prozess via `claude -p`, lässt ihn die Aufgabe
bearbeiten (mit vollem Repo-Zugriff: Read/Write/Bash/Git), und postet
das Ergebnis zurück nach Discord.

Architektur:
    Victor → Discord-DM
        → Albert poll_once
            → classify_message() → 'code'
                → handle_code_task() (dieses Modul)
                    → claude -p --add-dir /opt/trademind --setting-sources project
                    → result → Discord-Reply
                    → conversation_log.append('cli', 'agent', 'claude_code', result)

Wichtig:
- Läuft synchron im Discord-Polling-Thread → Timeout 8min hard
- Nutzt OAuth-Token (Max-Subscription, kein API-Verbrauch)
- Strippt ANTHROPIC_API_KEY aus Subprocess-Env (sonst billing == api)
- Fehler werden ans Discord gemeldet (nie silent crashen)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from conversation_log import append as conv_append

# Trigger-Wörter, die einen Code-Task signalisieren (case-insensitive)
CODE_KEYWORDS = (
    'fix', 'bug', 'error', 'fehler', 'code', 'script', 'skript',
    'deploy', 'commit', 'push', 'pull', 'merge', 'pr ', 'pull request',
    'pfad', 'path', 'cron', 'scheduler', 'systemd', 'service',
    'migration', 'datenbank-schema', 'db-schema',
    'umbauen', 'refaktor', 'refactor', 'rewrite', 'umschreib',
    'guard ', 'gate', 'logik ändern', 'aendern', 'logik ander',
    'baue ', 'implementier', 'erstell mir', 'schreib mir',
    'updaten', 'update das', 'update die', 'updates auf server',
    'zeile ', 'line ', 'in scripts/', 'in scripts\\\\',
    '.py', '.json', '.md', '.sh',
)

# Negative Trigger — diese sind eher Trading/Analyse-Fragen, nicht Code
NEGATIVE_KEYWORDS = (
    'wie sieht', 'was denkst du', 'meinung', 'analyse', 'einschätzung',
    'einschaetzung', 'soll ich kaufen', 'soll ich verkaufen', 'kursziel',
    'thesis', 'these', 'deep dive',
)


def classify_message(content: str) -> str:
    """Returns 'code' | 'chat'.

    Heuristisch (kein LLM-Call, weil das die Latenz verdoppelt):
    - Wenn explizit Code/Deploy/Pfad-Wörter → code
    - Wenn Trading/Analyse-Wörter dominieren → chat
    - Default → chat (sicherer Fallback)
    """
    if not content:
        return 'chat'
    low = content.lower()

    # Negative zuerst (Override): Trading-Fragen sind wichtiger
    neg_hits = sum(1 for kw in NEGATIVE_KEYWORDS if kw in low)
    pos_hits = sum(1 for kw in CODE_KEYWORDS if kw in low)

    # Klar Code: 2+ Hits oder explizite Datei-/Zeilen-Referenz
    if pos_hits >= 2:
        return 'code'
    if pos_hits >= 1 and neg_hits == 0:
        return 'code'
    return 'chat'


def _claude_cli_path() -> str | None:
    """Findet `claude` Binary."""
    p = shutil.which('claude')
    if p:
        return p
    # Server-Standardpfade
    for cand in ('/home/trademind/.local/bin/claude',
                 '/usr/local/bin/claude',
                 '/opt/claude/bin/claude'):
        if Path(cand).exists():
            return cand
    return None


def handle_code_task(victor_message: str, timeout_sec: int = 480) -> str:
    """
    Gibt eine Discord-tauglich formatierte Antwort zurück (max ~1900 Zeichen).
    Loggt selbst ins conversation_log.
    """
    started = datetime.now()
    cli = _claude_cli_path()
    if not cli:
        return ('⚠️ **Code-Task abgelehnt** — `claude` CLI nicht im PATH.\n'
                'Admin: `which claude` auf Server prüfen.')

    # Prompt: gib Claude Code den Auftrag, samt Hinweis dass die Antwort
    # zurück nach Discord gepostet wird (also kurz/prägnant halten).
    prompt = f"""Du bist Claude Code in einer Headless-Session, getriggert durch Victors Discord-DM an Albert.

Repo: /opt/trademind (TradeMind Trading-Bot, siehe CLAUDE.md).
Du hast vollen Filesystem/Bash/Git-Zugriff. Führe die Aufgabe aus.

Wichtig:
- Antwort wird 1:1 nach Discord gepostet → halte sie kurz (max 1500 Zeichen)
- Bei Code-Änderungen: commit + push selbstständig wenn möglich
- Bei Unsicherheit: KEINE destructive Aktion, lieber nachfragen
- Nutze Markdown sparsam (Discord-kompatibel)

Victors Auftrag:
{victor_message}
"""

    # Subprocess-Env: ANTHROPIC_API_KEY raus, OAuth lassen (Max-Subscription)
    env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'

    cmd = [
        cli, '-p',
        '--model', 'sonnet',
        '--output-format', 'json',
        '--add-dir', str(WS),
        '--setting-sources', 'user',
        '--permission-mode', 'acceptEdits',  # Auto-Accept im Headless
    ]
    # Stage 3 — Shared Session (optional)
    _shared_sid = os.getenv('LLM_SHARED_SESSION_ID', '').strip()
    if _shared_sid:
        cmd.extend(['--resume', _shared_sid])

    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout_sec, check=False, env=env, cwd=str(WS),
        )
        # Stage 3 — Shared Session existiert noch nicht? Retry ohne --resume
        # (erste Albert-Antwort erstellt sie implizit nicht — nur interaktive
        # Sessions werden registriert. Daher: ohne resume erneut versuchen.)
        if (result.returncode != 0 and
            'No conversation found' in (result.stderr + result.stdout) and
            '--resume' in cmd):
            print('[code_task] shared session not found → retry without --resume',
                  file=sys.stderr)
            cmd_clean = [c for c in cmd if c != '--resume']
            # auch das Argument nach --resume entfernen
            try:
                idx = cmd.index('--resume')
                cmd_clean = cmd[:idx] + cmd[idx+2:]
            except ValueError:
                pass
            result = subprocess.run(
                cmd_clean, input=prompt, capture_output=True, text=True,
                timeout=timeout_sec, check=False, env=env, cwd=str(WS),
            )
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now() - started).total_seconds()
        msg = f'⏰ **Code-Task Timeout** nach {elapsed:.0f}s. Versuche kleinere Aufgabe.'
        conv_append(source='cli', role='agent', speaker='claude_code',
                    content=f'TIMEOUT: {victor_message[:200]}',
                    meta={'event': 'code_task', 'status': 'timeout'})
        return msg
    except Exception as e:
        return f'⚠️ **Code-Task Fehler** beim Spawnen: {type(e).__name__}: {e}'

    elapsed = (datetime.now() - started).total_seconds()

    if result.returncode != 0:
        err = (result.stderr or 'unknown')[:300]
        conv_append(source='cli', role='agent', speaker='claude_code',
                    content=f'ERROR rc={result.returncode}: {err}',
                    meta={'event': 'code_task', 'status': 'error'})
        return f'⚠️ **Code-Task fehlgeschlagen** (rc={result.returncode}, {elapsed:.0f}s):\n```\n{err}\n```'

    # Parse JSON-Output
    text = ''
    cost = 0.0
    try:
        payload = json.loads(result.stdout or '{}')
        text = payload.get('result') or payload.get('content') or ''
        cost = float(payload.get('total_cost_usd', 0) or 0)
    except Exception:
        text = (result.stdout or '').strip()

    if not text:
        return '⚠️ **Code-Task lieferte leere Antwort.** Vielleicht Tool-Loop ohne Final-Message.'

    # Header für Discord
    header = f'🛠️ **Claude Code** ({elapsed:.0f}s, {"sub" if cost==0 else f"${cost:.3f}"})'

    # Loggen ins Shared Log
    conv_append(source='cli', role='agent', speaker='claude_code',
                content=text[:2000],
                meta={'event': 'code_task', 'elapsed_s': elapsed, 'cost_usd': cost,
                      'triggered_by_discord': True})

    # Discord-Limit 2000 Zeichen → header + content kürzen
    body = text[:1800]
    if len(text) > 1800:
        body += '\n…[gekürzt, voller Output im conversation_log]'
    return f'{header}\n{body}'


# CLI-Modus zum Testen
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('message', nargs='+', help='Test-Auftrag')
    ap.add_argument('--classify-only', action='store_true')
    args = ap.parse_args()
    msg = ' '.join(args.message)

    if args.classify_only:
        print(f'classify({msg!r}) = {classify_message(msg)}')
        sys.exit(0)

    print(f'Classify: {classify_message(msg)}')
    print(f'Result:\n{handle_code_task(msg)}')
