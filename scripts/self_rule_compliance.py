#!/usr/bin/env python3
"""
self_rule_compliance.py — Phase 45aw (Victor 2026-05-13).

Zwingt Albert die eigenen Selbst-Regeln einzuhalten — nicht nur zu zitieren.

Mechanik:
  1. Vor jedem LLM-Call: Self-Rules werden als PFLICHT-Block in Prompt injiziert
  2. Nach Output: Compliance-Check via Haiku
  3. Bei Verstoß: Re-Call mit explizitem Reminder, max 3 Retries
  4. Compliance-Rate wird geloggt — sichtbar im Friday-Briefing

API:
  from self_rule_compliance import enforce_compliance

  text, meta = enforce_compliance(
      prompt='...',
      model_hint='sonnet',
      max_tokens=500,
      context='brain_tick'  # für Logging
  )
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
RULES_FILE = WS / 'memory' / 'albert_self_rules.md'
LOG = WS / 'data' / 'compliance_log.jsonl'

MAX_RETRIES = 3


def _load_active_rules() -> list[str]:
    """Extrahiere aktive Regeln aus self_rules.md.
    Sucht nach Pattern '**Regel N (Name):**' oder '**Regel N:**' im Text.
    """
    if not RULES_FILE.exists(): return []
    try:
        txt = RULES_FILE.read_text(encoding='utf-8')
    except Exception:
        return []
    # Extrahiere alle Regel-Blöcke (bis nächste Leerzeile oder Header)
    rules = []
    # Pattern: **Regel N ... :** Text ...
    pattern = r'\*\*Regel\s+\d+[^\*]*?:\*\*\s*([^\*\n][^\n]{20,400})'
    for m in re.finditer(pattern, txt):
        rule_text = m.group(0).strip()
        # Nur wenn Regel nicht in einem "rauswerfen"-Block ist
        # Schauen wir 200 chars davor für "fliegt raus" oder "rauswerfen"
        start = max(0, m.start() - 200)
        before = txt[start:m.start()].lower()
        if 'fliegt raus' in before or 'rauswerfen' in before:
            continue
        rules.append(rule_text[:300])
    return rules[:10]  # max 10 Regeln pro Prompt


def _build_rule_block(rules: list[str]) -> str:
    if not rules:
        return ''
    return (
        '\n\n═══ DEINE PFLICHT-REGELN (Phase 45aw — diese musst du EINHALTEN, nicht zitieren) ═══\n'
        + '\n'.join(f'- {r}' for r in rules)
        + '\n\nWenn du gegen eine dieser Regeln verstößt, wird dein Output verworfen und du bekommst eine Korrektur-Chance.\n'
    )


def _check_compliance(output: str, rules: list[str]) -> tuple[bool, list[str]]:
    """Compliance-Check via Haiku.
    Returns: (compliant, list_of_violations).
    """
    if not rules:
        return True, []
    try:
        sys.path.insert(0, str(WS / 'scripts' / 'core'))
        from llm_client import call_llm
    except Exception:
        return True, []  # ohne LLM → kein Check

    check_prompt = f"""Du bist ein strenger Compliance-Prüfer. Albert hat folgende Selbst-Regeln:

{chr(10).join(f'- {r}' for r in rules)}

Sein Output:
\"\"\"
{output[:2500]}
\"\"\"

Analysiere: Verstößt der Output gegen mind. EINE dieser Regeln? Sei streng.

Beispiele für Verstoss:
- Regel sagt "kein Verbal-Tic", Output zitiert wiederholt eine Floskel
- Regel sagt "Truth-Block vor Verdict lesen", Output urteilt ohne Quellenangabe
- Regel sagt "Bei Blocker-Auflösung sofort Action", Output beschreibt nur

Antworte EXAKT in diesem Format:
COMPLIANT: yes|no
VIOLATIONS: <wenn no, kurze Liste der Verstöße, max 3 Items, jeweils 1-Satz>
"""
    try:
        text, _ = call_llm(check_prompt, model_hint='haiku', max_tokens=300)
    except Exception:
        return True, []

    compliant = 'COMPLIANT: yes' in text or 'compliant: yes' in text.lower()
    if compliant:
        return True, []
    # Extrahiere Violations
    violations = []
    if 'VIOLATIONS:' in text:
        viol_part = text.split('VIOLATIONS:', 1)[1].strip()
        for line in viol_part.split('\n')[:5]:
            line = line.strip(' -*')
            if len(line) > 10:
                violations.append(line[:200])
    return False, violations[:3]


def enforce_compliance(prompt: str, model_hint: str = 'sonnet',
                        max_tokens: int = 500, context: str = 'unknown') -> tuple[str, dict]:
    """
    Haupt-API. Generiert Output, prüft Compliance, retry'd bis OK oder max_retries.

    Returns: (final_output, meta_dict)
      meta_dict: {compliant, retries, violations_per_attempt, ...}
    """
    try:
        sys.path.insert(0, str(WS / 'scripts' / 'core'))
        from llm_client import call_llm
    except Exception as e:
        return '', {'error': f'llm_client_missing: {e}'}

    rules = _load_active_rules()
    rule_block = _build_rule_block(rules)
    effective_prompt = prompt + rule_block

    meta = {
        'context': context,
        'n_rules': len(rules),
        'retries': 0,
        'violations_per_attempt': [],
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }

    output = ''
    for attempt in range(MAX_RETRIES + 1):
        try:
            output, _ = call_llm(effective_prompt, model_hint=model_hint, max_tokens=max_tokens)
        except Exception as e:
            meta['error'] = str(e)
            break

        compliant, violations = _check_compliance(output, rules)
        meta['violations_per_attempt'].append({
            'attempt': attempt,
            'compliant': compliant,
            'violations': violations,
        })

        if compliant:
            meta['compliant'] = True
            meta['retries'] = attempt
            break

        meta['retries'] = attempt + 1
        if attempt >= MAX_RETRIES:
            meta['compliant'] = False
            meta['final_status'] = 'gave_up_after_max_retries'
            break

        # Re-Call mit Reminder
        reminder = (
            f"\n\n═══ KORREKTUR ERFORDERLICH (Versuch {attempt+1}/{MAX_RETRIES}) ═══\n"
            f"Dein vorheriger Output verletzte folgende Regeln:\n"
            + '\n'.join(f'- {v}' for v in violations)
            + "\n\nBitte mache deine Antwort NEU und beachte diese Regeln. "
              "Nicht zitieren — EINHALTEN. Schreibe konkret und ohne Verbal-Tics.\n"
        )
        effective_prompt = prompt + rule_block + reminder

    # Logging
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(meta, ensure_ascii=False, default=str) + '\n')
    except Exception: pass

    return output, meta


def main() -> int:
    """CLI: zeigt aktive Regeln + letzte 5 Compliance-Events."""
    print('=== Aktive Self-Rules ===')
    for r in _load_active_rules():
        print(f'  · {r}')
    print()
    print('=== Letzte 5 Compliance-Events ===')
    if LOG.exists():
        lines = LOG.read_text(encoding='utf-8').strip().splitlines()
        for line in lines[-5:]:
            try:
                e = json.loads(line)
                print(f"  {e['ts'][:16]} {e.get('context','?'):15} "
                      f"retries={e.get('retries',0)} "
                      f"compliant={e.get('compliant','?')}")
            except Exception: pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
