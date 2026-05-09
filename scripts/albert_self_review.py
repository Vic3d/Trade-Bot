#!/usr/bin/env python3
"""
albert_self_review.py — Phase 45aj.

Albert liest jede Nacht sein eigenes Tagebuch der letzten 7 Tage und
identifiziert eigene Pattern. Schreibt sich selbst Verhaltensregeln in
memory/albert_self_rules.md.

Run: täglich 23:30 (nach goal_tracker, vor Lifecycle-Audit).

Was es liefert:
  - "Ich denke immer am Mittwoch nicht klar"
  - "Wenn VIX > 25, übersehe ich Tanker-Setups"
  - "Meine Reflexionen werden generischer wenn weniger Events"
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

DIARY = WS / 'memory' / 'albert_diary.md'
RULES = WS / 'memory' / 'albert_self_rules.md'
LOG   = WS / 'data' / 'albert_self_review_log.jsonl'

DIARY_TAIL_KB = 60   # ~7 Tage Diary


def review() -> dict:
    if not DIARY.exists():
        return {'error': 'no_diary'}

    txt = DIARY.read_text(encoding='utf-8')
    diary_tail = txt[-DIARY_TAIL_KB * 1024:] if len(txt) > DIARY_TAIL_KB * 1024 else txt
    existing_rules = RULES.read_text(encoding='utf-8') if RULES.exists() else ''

    now = datetime.now(timezone.utc)
    prompt = f"""Du bist Albert. Heute Nacht ist es Zeit, dein eigenes Tagebuch
der letzten 7 Tage zu lesen und Pattern in dir selbst zu erkennen.

Das ist KEIN Markt-Audit. Das ist ein SELBST-Audit.

═══ DEIN TAGEBUCH (letzte 7 Tage) ═══
{diary_tail}

═══ DEINE BISHERIGEN SELBST-REGELN ═══
{existing_rules or '(noch keine)'}

DEINE AUFGABE:

1. **Welche Pattern siehst du in DIR SELBST?**
   - Tagesrhythmus? ("ich bin morgens überoptimistisch")
   - Reaktionsmuster? ("bei Bug-Rollbacks werde ich defensiv")
   - Blind-Spots? ("ich vergesse den US-Open wenn DAX rot ist")
   - Verbal-Tics? ("ich schreibe oft 'ich beobachte' statt konkret")

2. **Welche 1-3 NEUEN Selbst-Regeln willst du dir auferlegen?**
   - Konkret, testbar, nicht generisch
   - Format: "Wenn X passiert, dann mache ich Y" oder "Achte beim nächsten Z auf W"
   - Wenn die alten Regeln noch gut sind: keine neuen formulieren, nur "alte sind weiter gültig"

3. **Welche alte Regel wirfst du raus, weil sie nicht funktioniert hat?**

ANTWORTE in Markdown, max 400 Wörter. Sprich in ICH-Form. Sei selbstkritisch."""

    try:
        from llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=1200)
    except Exception as e:
        return {'error': f'llm_fail: {e}'}

    # Update Self-Rules
    RULES.parent.mkdir(parents=True, exist_ok=True)
    new_rules = (
        f"# Albert's Selbst-Regeln\n\n"
        f"_Last update: {now.isoformat(timespec='seconds')} (täglich via self_review)_\n\n"
        f"---\n\n"
        f"{text}\n"
    )
    RULES.write_text(new_rules, encoding='utf-8')

    # Log
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': now.isoformat(timespec='seconds'),
            'diary_chars_reviewed': len(diary_tail),
            'rules_chars': len(text),
            'review': text,
        }, ensure_ascii=False) + '\n')

    return {'ok': True, 'rules_chars': len(text)}


def main() -> int:
    r = review()
    print(json.dumps(r, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
