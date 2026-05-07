#!/usr/bin/env python3
"""
inject_current_truth.py — UserPromptSubmit Hook fuer Claude Code (CLI).

Phase 45k (Victor 2026-05-05): Schliesst die CLI-Halluzinations-Luecke.

Bisher: current_truth.py wurde nur in LLM-Prompts (Albert via llm_client)
gespritzt. CLI-Claude (mich) sah keinen verbindlichen Truth-Header und
konnte deshalb halluzinieren ("PS5 ist retired" obwohl strategies.json
'active' sagt — passiert am 05.05).

Jetzt: Vor JEDEM User-Prompt im CLI wird current_truth.format_for_llm()
aufgerufen und als additionalContext injiziert. Damit sehen Albert UND
CLI-Claude die identische Single-Source-of-Truth, inkl. Strategy-Verdicts.

Mechanik (analog zu inject_albert_context.py):
  1. SSH zum Server, rufe `python3 scripts/current_truth.py` auf
     (Server hat Live-DB; lokale Worktree nicht zwingend synchron)
  2. Cache 60s in data/.current_truth_cache.json
  3. Output via stdout im Claude-Hook-JSON-Protokoll

Bei Fehler (SSH down): silent exit 0, kein Block.
Performance-Budget: max 4s.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
CACHE_FILE = WS / 'data' / '.current_truth_cache.json'
CACHE_TTL_SECONDS = 15  # Phase 45aa (A8): von 60s auf 15s verkuerzt — frischere Truth
SSH_TIMEOUT = 4
SERVER = 'root@178.104.152.135'
REMOTE_CMD = 'cd /opt/trademind && /usr/bin/python3 scripts/current_truth.py 2>/dev/null'
MAX_OUTPUT_CHARS = 8000  # Verdict-Liste kann lang werden, schneide bei Bedarf


def _load_cache() -> str | None:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        if time.time() - data.get('cached_at', 0) < CACHE_TTL_SECONDS:
            return data.get('text')
    except Exception:
        return None
    return None


def _save_cache(text: str) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            'cached_at': time.time(),
            'text': text,
        }), encoding='utf-8')
    except Exception:
        pass


def _fetch_truth() -> str | None:
    cached = _load_cache()
    if cached:
        return cached

    try:
        proc = subprocess.run(
            ['ssh', '-o', f'ConnectTimeout={SSH_TIMEOUT}',
             '-o', 'StrictHostKeyChecking=no', SERVER, REMOTE_CMD],
            capture_output=True, text=True, timeout=SSH_TIMEOUT + 2,
            encoding='utf-8', errors='replace',
        )
        if proc.returncode != 0:
            return None
        # current_truth.py prints format_for_llm() block + raw JSON dump.
        # Wir wollen nur den ersten Teil (bis '--- raw JSON ---').
        out = proc.stdout
        sep = '--- raw JSON ---'
        if sep in out:
            out = out.split(sep, 1)[0].rstrip()
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + '\n... (truncated)\n'
        if not out.strip():
            return None
        _save_cache(out)
        return out
    except Exception:
        return None


def main() -> int:
    truth = _fetch_truth()
    if not truth:
        # Silent exit — kein additionalContext aber Prompt geht durch
        return 0

    # Hook-Output-Format
    payload = {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': (
                '## TradeMind Current Truth (auto-injiziert via Hook)\n'
                '_Verbindliche As-Of-Now Fakten aus Server-DB. '
                'Bei Strategie-/Position-Aussagen MUSS dieser Block gewinnen._\n\n'
                f'```\n{truth}\n```\n'
            ),
        }
    }
    print(json.dumps(payload), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
