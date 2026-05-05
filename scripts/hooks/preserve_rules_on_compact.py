#!/usr/bin/env python3
"""
preserve_rules_on_compact.py — PreCompact-Hook fuer Claude Code.

Phase 45l (Victor 2026-05-05): Layer 7 der Anti-Halluzinations-Defense.

Gap: Bei Auto-Compact wird die Konversation gekuerzt. Faktische Aussagen
wie "PS5 retired (Sharpe -3.14)" landen im Summary und werden nach der
Compaction NICHT mehr gegen die DB verifiziert. Genau so ist der PS5-
Halluzinations-Bug heute morgen entstanden.

Mechanik:
  1. PreCompact-Hook feuert bevor die Compaction laeuft
  2. Holt frische current_truth via SSH (live DB-State)
  3. Injiziert sie als additionalContext, damit der Compaction-Prozess
     UND alle nachfolgenden Antworten weiterhin den Truth-Block sehen
  4. Erinnert Claude explizit daran: "Aussagen aus dem Pre-Compact-
     Summary sind potentiell veraltet. Bei Konflikt gewinnt der unten
     stehende Truth-Block."

Performance: max 6s.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
SSH_TIMEOUT = 5
SERVER = 'root@178.104.152.135'
REMOTE_CMD = 'cd /opt/trademind && /usr/bin/python3 scripts/current_truth.py 2>/dev/null'


def _fetch_truth() -> str | None:
    try:
        proc = subprocess.run(
            ['ssh', '-o', f'ConnectTimeout={SSH_TIMEOUT}',
             '-o', 'StrictHostKeyChecking=no', SERVER, REMOTE_CMD],
            capture_output=True, text=True, timeout=SSH_TIMEOUT + 3,
            encoding='utf-8', errors='replace',
        )
        if proc.returncode != 0:
            return None
        out = proc.stdout
        sep = '--- raw JSON ---'
        if sep in out:
            out = out.split(sep, 1)[0].rstrip()
        return out.strip() or None
    except Exception:
        return None


def main() -> int:
    truth = _fetch_truth()
    if not truth:
        return 0

    payload = {
        'hookSpecificOutput': {
            'hookEventName': 'PreCompact',
            'additionalContext': (
                '## ⚠ COMPACTION-WARNUNG: Truth-Reinjection\n\n'
                'Das gleich entstehende Compaction-Summary kann veraltete '
                'oder halluzinierte Fakten enthalten. Beispiel-Bug am '
                '05.05.2026: Summary enthielt "PS5 retired" obwohl '
                'strategies.json "active" sagte.\n\n'
                'REGEL nach Compaction: Bei JEDER Aussage ueber Position/'
                'Strategie/PnL ZUERST den unten stehenden Live-Truth-Block '
                'pruefen. Summary-Eintraege NIE als Quelle nehmen.\n\n'
                f'```\n{truth}\n```\n'
            ),
        }
    }
    print(json.dumps(payload), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
