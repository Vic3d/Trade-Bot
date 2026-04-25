#!/usr/bin/env python3
"""
init_shared_session.py — Stage 3: Volle Fusion.

Initialisiert eine geteilte Claude-Session-ID zwischen:
  - Albert (Discord-Bot, ruft `claude -p --resume <ID>`)
  - Claude Code CLI (Victor läuft `claude --resume <ID>` lokal)

Workflow:
  1. python3 scripts/init_shared_session.py        # erzeugt + speichert ID
  2. ID landet in data/shared_session_id.txt
  3. ENV LLM_SHARED_SESSION_ID wird in deploy/.env gesetzt
  4. systemctl restart trademind-scheduler         # Albert nutzt ab jetzt --resume
  5. Lokal: claude --resume $(cat data/shared_session_id.txt)
     → ich sehe Alberts History, er sieht meine

Sicherheitshinweis:
  - Concurrent writes auf dieselbe Session sind nicht 100% sicher (claude CLI
    hat keinen Lock-Mechanismus für Session-Files). In der Praxis kollidieren
    Albert (alle 30s polling) und CLI (interaktiv) selten.
  - Bei Problemen: ENV LLM_SHARED_SESSION_ID leeren → fallback auf
    --no-session-persistence (jede Antwort isoliert, garantiert sicher).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
SESSION_FILE = WS / 'data' / 'shared_session_id.txt'
ENV_FILE = WS / 'deploy' / '.env'


def get_or_create_session_id() -> str:
    if SESSION_FILE.exists():
        sid = SESSION_FILE.read_text(encoding='utf-8').strip()
        if sid:
            return sid
    # Neue UUID — Claude CLI akzeptiert beliebige Strings als Session-ID
    sid = str(uuid.uuid4())
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(sid, encoding='utf-8')
    return sid


def update_env_file(sid: str) -> bool:
    """Setzt LLM_SHARED_SESSION_ID=<sid> in deploy/.env (idempotent)."""
    if not ENV_FILE.exists():
        print(f'[warn] {ENV_FILE} fehlt — manuell setzen!')
        return False

    lines = ENV_FILE.read_text(encoding='utf-8').splitlines()
    out_lines = []
    found = False
    for ln in lines:
        if ln.startswith('LLM_SHARED_SESSION_ID='):
            out_lines.append(f'LLM_SHARED_SESSION_ID={sid}')
            found = True
        else:
            out_lines.append(ln)
    if not found:
        out_lines.append(f'LLM_SHARED_SESSION_ID={sid}')
    ENV_FILE.write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
    return True


def main():
    sid = get_or_create_session_id()
    print(f'Shared Session ID: {sid}')
    print(f'Datei: {SESSION_FILE}')

    if update_env_file(sid):
        print(f'.env aktualisiert: {ENV_FILE}')

    print()
    print('Nächste Schritte:')
    print('  1. systemctl restart trademind-scheduler')
    print(f'  2. Lokal/manuell: claude --resume {sid}')
    print('  3. Verifizieren: in Discord etwas an Albert schreiben,')
    print('     dann in der CLI-Session sollte die History sichtbar sein.')


if __name__ == '__main__':
    main()
