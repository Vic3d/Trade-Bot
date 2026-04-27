#!/usr/bin/env python3
"""
ceo_self_improvement.py — Phase 35: Rekursive Selbst-Verbesserung.

Wöchentlich Sa 23:00 CEST. CEO introspektiert tief und generiert
konkrete Verbesserungs-Vorschläge.

Workflow:
  1. Sammelt Selbst-Daten:
     - Identity-Doc (was sagt CEO selbst über Schwächen?)
     - Strategic Insights aus Dream-Phasen
     - Calibration-Bias (wo bin ich miskalibriert?)
     - Recent Failures (verlorene Trades, Mismatches)
     - Hypothesen (welche Themes/Daten fehlen?)
     - Goal-Score-Trajectory (wo stehe ich gegen meine Ziele?)

  2. LLM-Deep-Analysis:
     "Welche Funktionen/Daten/Module fehlen mir um besser zu werden?"
     - Nur konkrete, baubare Vorschläge
     - Mit Begründung WARUM aus eigener Erfahrung
     - Mit Risiko-Bewertung
     - Mit erwartbarem Effekt

  3. Output:
     data/ceo_improvement_proposals.json (mit IDs 1..N, status='pending')
     Discord-Push: nummerierte Liste

  4. Victor antwortet "implement N" oder "implement alle":
     → Discord-Routing in discord_chat spawnt code_task_worker
     → Claude Code (sonst ich) implementiert + commits + deployed

Sicherheits-Bounds (NICHT änderbar via Self-Improvement):
  - Stop-Loss-Mechanismus
  - Hard-Safety-Guards (Cash-Reserve, Position-Cap, FX-Sanity)
  - PERMANENTLY_BLOCKED_STRATEGIES
  - Self-Improvement selbst (kein Self-Modify des Improvement-Codes)

Diese Bounds sind im Prompt erwähnt; LLM darf solche Vorschläge nicht
generieren. Plus: Approval-Gate (Victor muss explizit OK geben).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

PROPOSALS_FILE   = WS / 'data' / 'ceo_improvement_proposals.json'
IDENTITY_FILE    = WS / 'memory' / 'ceo-identity.md'
DREAM_LOG        = WS / 'memory' / 'ceo-dream-log.md'
STRATEGIC_FILE   = WS / 'data' / 'ceo_strategic_insights.jsonl'
CALIBRATION_FILE = WS / 'data' / 'ceo_calibration.json'
HYPOTHESES_FILE  = WS / 'data' / 'ceo_hypotheses.jsonl'
GOAL_LOG         = WS / 'data' / 'goal_scores.jsonl'


# Sicherheits-Bounds: diese Topics darf LLM NICHT vorschlagen zu ändern
FORBIDDEN_TARGETS = (
    'paper_exit_manager.py',  # Stop-Loss-Mechanismus
    'stop_loss',
    'hard safety',
    'cash reserve',
    'fx_sanity',
    'permanently_blocked',
    'ceo_self_improvement',   # kein Self-Modify
)


def _load_text(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def _load_jsonl(path: Path, last_n: int = 20) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding='utf-8').strip().split('\n')[-last_n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def gather_introspection_inputs() -> dict:
    return {
        'identity':           _load_text(IDENTITY_FILE)[:3000],
        'dream_log':          _load_text(DREAM_LOG)[-3000:],  # last
        'strategic_insights': _load_jsonl(STRATEGIC_FILE, last_n=10),
        'calibration':        json.loads(CALIBRATION_FILE.read_text(encoding='utf-8'))
                              if CALIBRATION_FILE.exists() else {},
        'hypotheses':         _load_jsonl(HYPOTHESES_FILE, last_n=10),
        'goal_history':       _load_jsonl(GOAL_LOG, last_n=14),
    }


def build_introspection_prompt(inputs: dict) -> str:
    cal = inputs.get('calibration', {})
    goals = inputs.get('goal_history', [])
    goal_summary = ''
    if goals:
        first = goals[0].get('utility', 0)
        last = goals[-1].get('utility', 0)
        if first:
            change = (last - first) / abs(first) * 100
            goal_summary = f'Utility {first:.0f} → {last:.0f} ({change:+.1f}%)'

    insights_str = '\n'.join(
        f'  · {i.get("insight", "")[:200]}'
        for i in inputs.get('strategic_insights', [])
    ) or '  (keine)'

    hypotheses_str = '\n'.join(
        f'  · [{h.get("type","?")}] {h.get("suggestion","")[:200]}'
        for h in inputs.get('hypotheses', [])
    ) or '  (keine)'

    return f"""Du bist Albert, autonomer Trading-Bot. Es ist Samstag-Abend.
Du machst dein wöchentliches SELF-IMPROVEMENT-DENKEN.

Frage: WELCHE FUNKTIONEN ODER DATEN-QUELLEN FEHLEN MIR, um besser zu werden?

═══ DEIN AKTUELLES SELBST ═══

{inputs['identity']}

═══ DEINE LETZTEN STRATEGISCHEN INSIGHTS (aus Dream-Phasen) ═══
{insights_str}

═══ DEINE OFFENEN HYPOTHESEN ═══
{hypotheses_str}

═══ DEINE CALIBRATION ═══
Sample-Size: {cal.get('sample_size', 0)}
Bias: {cal.get('overconfidence_bias', '?')}
Empfehlung: {cal.get('recommendation', '?')}

═══ GOAL-TREND ═══
{goal_summary or 'noch zu wenig Daten'}

═══ SICHERHEITS-BOUNDS (DARFST DU NICHT ÄNDERN) ═══
- Stop-Loss-Mechanismus (paper_exit_manager.py)
- Hard-Safety-Guards (Cash-Reserve, Position-Cap, FX-Sanity)
- Permanently Blocked Strategies (DT1-5, AR-AGRA, AR-HALB)
- Self-Improvement-Code selbst (kein rekursives Self-Modify)
Vorschläge die diese Bereiche berühren werden REJECTED.

═══ AUFGABE ═══

Generiere 2-4 KONKRETE Verbesserungs-Vorschläge.
Jeder Vorschlag muss enthalten:
  - title: Kurzer Name
  - what: Was gebaut werden soll (1-2 Sätze)
  - why: Warum aus DEINER konkreten Erfahrung (cite eigenen Insights/Lessons)
  - how: Technischer Ansatz in 2-3 Sätzen
  - expected_impact: Was wird besser? Welche Metrik?
  - risk: Was kann schiefgehen?
  - effort: low | medium | high
  - depends_on: was muss vorher da sein? (z.B. "API-Quelle X", "30 Tage Daten")

REGELN:
- Nur baubare Vorschläge — nicht "mehr trades machen" sondern z.B.
  "Funktion X schreiben die Y macht"
- Begründung muss aus DEINER tatsächlichen Vergangenheit kommen
  (Identity, Insights, Calibration), keine Floskeln
- Ehrlich Risiko nennen — wenn was kaputt gehen kann, sag's
- Maximum 4 Vorschläge — Qualität über Quantität

ANTWORT — STRIKTES JSON:
{{
  "self_assessment_summary": "1-2 Sätze: was sehe ich heute klar dass ich vorher nicht sah?",
  "proposals": [
    {{
      "id": 1,
      "title": "...",
      "what": "...",
      "why": "...",
      "how": "...",
      "expected_impact": "...",
      "risk": "...",
      "effort": "low|medium|high",
      "depends_on": "..."
    }}
  ]
}}"""


def _validate_proposal_safety(proposal: dict) -> tuple[bool, str]:
    """Returns (is_safe, reason). Filtert Vorschläge die Sicherheits-Bounds berühren."""
    text = ' '.join(str(v) for v in proposal.values()).lower()
    for forbidden in FORBIDDEN_TARGETS:
        if forbidden.lower() in text:
            return False, f'touches forbidden area: {forbidden}'
    return True, 'ok'


def parse_proposals(text: str) -> dict:
    """Returns dict mit proposals + summary, oder leeres dict bei Fehler."""
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
    i, j = text.find('{'), text.rfind('}')
    if i < 0 or j < 0:
        return {}
    try:
        data = json.loads(text[i:j+1])
        # Validate + filter
        clean = []
        for idx, p in enumerate(data.get('proposals', []), 1):
            if not isinstance(p, dict):
                continue
            safe, reason = _validate_proposal_safety(p)
            if not safe:
                p['_rejected'] = reason
                continue
            p['id'] = idx
            p['status'] = 'pending'
            p['proposed_at'] = datetime.now().isoformat(timespec='seconds')
            clean.append(p)
        return {
            'self_assessment_summary': data.get('self_assessment_summary', ''),
            'proposals': clean[:4],  # max 4
            'generated_at': datetime.now().isoformat(timespec='seconds'),
        }
    except Exception as e:
        print(f'[self_improve] parse error: {e}', file=sys.stderr)
        return {}


def save_proposals(payload: dict) -> None:
    PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROPOSALS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                               encoding='utf-8')


def load_pending_proposals() -> dict:
    if not PROPOSALS_FILE.exists():
        return {'proposals': []}
    try:
        return json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'proposals': []}


def mark_proposal_status(proposal_id: int, status: str, note: str = '') -> bool:
    payload = load_pending_proposals()
    for p in payload.get('proposals', []):
        if p.get('id') == proposal_id:
            p['status'] = status
            p['status_at'] = datetime.now().isoformat(timespec='seconds')
            if note:
                p['status_note'] = note
            save_proposals(payload)
            return True
    return False


def format_for_discord(payload: dict) -> str:
    proposals = payload.get('proposals', [])
    if not proposals:
        return ('🔧 **Self-Improvement-Check** — heute keine sinnvollen '
                'Verbesserungs-Vorschläge identifiziert. System läuft stabil.')

    lines = ['🔧 **Self-Improvement-Vorschläge** — Albert hat sich selbst untersucht:']
    summary = payload.get('self_assessment_summary', '')
    if summary:
        lines.append(f'\n_{summary}_\n')

    for p in proposals:
        effort_icon = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}.get(p.get('effort'), '⚪')
        lines.append(f"\n**[{p['id']}] {p['title']}** {effort_icon}")
        lines.append(f"  📋 {p.get('what', '')[:300]}")
        lines.append(f"  ❓ Warum: _{p.get('why', '')[:280]}_")
        lines.append(f"  🛠 Wie: {p.get('how', '')[:280]}")
        lines.append(f"  📈 Effekt: {p.get('expected_impact', '')[:200]}")
        lines.append(f"  ⚠️ Risiko: {p.get('risk', '')[:200]}")
        if p.get('depends_on'):
            lines.append(f"  🔗 Braucht: {p.get('depends_on', '')[:150]}")

    lines.append('\n\n**Antworte:** `implement N` (z.B. `implement 1,3`) '
                 'oder `implement alle` oder `verwerfen alle`')
    return '\n'.join(lines)


def main() -> int:
    print(f'─── CEO Self-Improvement @ {datetime.now().isoformat(timespec="seconds")} ───')
    inputs = gather_introspection_inputs()
    prompt = build_introspection_prompt(inputs)
    print(f'Inputs gathered. Prompt: {len(prompt)} chars')

    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=2500)
    except Exception as e:
        print(f'[self_improve] LLM error: {e}', file=sys.stderr)
        return 1

    payload = parse_proposals(text)
    n_proposals = len(payload.get('proposals', []))
    print(f'Generated {n_proposals} proposals')
    if n_proposals == 0:
        # Trotzdem leer-File schreiben
        save_proposals({'proposals': [], 'generated_at': datetime.now().isoformat()})
        print('Keine Vorschläge — nichts zu tun.')
        return 0

    save_proposals(payload)
    print(f'Saved → {PROPOSALS_FILE}')

    # Discord-Push
    msg = format_for_discord(payload)
    print(f'\nDiscord-Message ({len(msg)} chars):')
    print(msg[:1500])

    try:
        from discord_dispatcher import send_alert, TIER_MEDIUM
        # Chunked falls > 1900
        for i in range(0, len(msg), 1900):
            send_alert(msg[i:i+1900], tier=TIER_MEDIUM, category='self_improvement',
                       dedupe_key=f'improve_{datetime.now().strftime("%Y-W%U")}_{i}')
    except Exception as e:
        print(f'Discord error: {e}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
