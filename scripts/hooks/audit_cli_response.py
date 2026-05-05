#!/usr/bin/env python3
"""
audit_cli_response.py — Stop-Hook fuer Claude Code CLI.

Phase 45l (Victor 2026-05-05): Layer 5 der Anti-Halluzinations-Defense.

Gap: halluzination_detector.py prueft NUR Alberts LLM-Outputs (Discord).
CLI-Claude (mich) kann weiter halluzinieren — siehe PS5-Bug am 05.05
("PS5 Backtest-Retire" obwohl strategies.json 'active' sagte).

Mechanik:
  1. Stop-Hook bekommt von Claude Code transcript_path via stdin
  2. Liest die letzte Assistant-Message aus der JSONL-Transkript-Datei
  3. Ruft den Server-Detector ueber SSH mit dem Text als stdin auf
  4. Wenn Violations gefunden: schreibt nach data/cli_audit_violations.jsonl
     UND printet systemMessage damit Victor es im Terminal sieht
  5. Setzt KEINEN block (kein Force-Rewake) — Halluzinationen-Audit ist
     informativ, nicht erzwingend. Victor entscheidet wie er reagiert.

Performance-Budget: max 8s. Bei Fehler: silent exit 0.

Hook-Config (.claude/settings.json):
  "Stop": [{
    "matcher": "",
    "hooks": [{"type": "command",
               "command": "python scripts/hooks/audit_cli_response.py",
               "timeout": 10}]
  }]
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
LOG = WS / 'data' / 'cli_audit_violations.jsonl'
SSH_TIMEOUT = 6
SERVER = 'root@178.104.152.135'
# Detector liest stdin und gibt JSON aus
REMOTE_CMD = (
    'cd /opt/trademind && '
    '/usr/bin/python3 -c "'
    'import sys, json; sys.path.insert(0, \\"scripts\\"); '
    'from halluzination_detector import check_halluzinations; '
    'r = check_halluzinations(sys.stdin.read(), context=\\"cli_claude\\"); '
    'print(json.dumps({\\"has_violations\\": r.has_violations, '
    '\\"violations\\": r.violations}))"'
)


def _read_last_assistant_message(transcript_path: str) -> str | None:
    """Liest die letzte Assistant-Message aus dem Claude-Code-Transkript."""
    try:
        p = Path(transcript_path)
        if not p.exists():
            return None
        # Backwards search nach letztem assistant-Eintrag
        last_msg = None
        with open(p, encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', {})
                    content = msg.get('content', [])
                    if isinstance(content, list):
                        text = '\n'.join(
                            c.get('text', '') for c in content
                            if isinstance(c, dict) and c.get('type') == 'text'
                        )
                        if text.strip():
                            last_msg = text
                    elif isinstance(content, str):
                        last_msg = content
        return last_msg
    except Exception:
        return None


def _audit_text(text: str) -> dict | None:
    """SSH zum Server, ruft Detector mit text als stdin auf."""
    if not text or len(text.strip()) < 50:
        return None
    try:
        proc = subprocess.run(
            ['ssh', '-o', f'ConnectTimeout={SSH_TIMEOUT}',
             '-o', 'StrictHostKeyChecking=no', SERVER, REMOTE_CMD],
            input=text, capture_output=True, text=True,
            timeout=SSH_TIMEOUT + 3, encoding='utf-8', errors='replace',
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout.strip())
    except Exception:
        return None


def _log_violations(violations: list, text_preview: str) -> None:
    try:
        from datetime import datetime, timezone
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'violations': violations,
                'text_preview': text_preview[:500],
            }, default=str) + '\n')
    except Exception:
        pass


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except Exception:
        return 0

    transcript_path = payload.get('transcript_path')
    if not transcript_path:
        return 0

    text = _read_last_assistant_message(transcript_path)
    if not text:
        return 0

    result = _audit_text(text)
    if not result or not result.get('has_violations'):
        return 0

    violations = result.get('violations', [])
    _log_violations(violations, text)

    # SystemMessage damit Victor es im Terminal sieht
    bullets = []
    for v in violations[:5]:
        if isinstance(v, dict):
            kind = v.get('kind') or v.get('type') or '?'
            claim = v.get('claim') or '?'
            truth = v.get('truth') or v.get('reason') or '?'
            bullets.append(f"  - [{kind}] {claim} | TRUTH: {truth}")
        else:
            bullets.append(f"  - {v}")
    msg = (
        f"⚠ Halluzinations-Audit: {len(violations)} Verstoss(e) in letzter Antwort:\n"
        + '\n'.join(bullets)
        + f"\nFull log: data/cli_audit_violations.jsonl"
    )

    print(json.dumps({
        'systemMessage': msg,
        'continue': True,
    }), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
