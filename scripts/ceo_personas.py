#!/usr/bin/env python3
"""
ceo_personas.py — Phase 41c: Investor-Persona-Sanity-Checks.

Integriert 11 berühmte Investor-Frameworks (Buffett, Graham, Lynch, Munger,
Klarman, Marks, Greenblatt, Einhorn, Miller, Eveillard, Whitman) als
optionale Sanity-Check-Layer für High-Conviction-Trades.

Quelle: Fincept-Terminal (AGPL-3.0) — agent_definitions.json kopiert
nach data/personas/investor_agents.json.

Nutzung:
  from ceo_personas import get_relevant_personas, run_persona_check

  personas = get_relevant_personas(strategy='PS_NVDA', position_eur=1500)
  # → ['warren_buffett_agent', 'howard_marks_agent']

  result = run_persona_check(persona_id='warren_buffett_agent', proposal=p)
  # → {'signal': 'bullish'|'neutral'|'bearish', 'confidence': 0.0-1.0,
  #    'reasoning': '...', 'risks': [...]}

Wann gefeuert:
  - High-Conviction (Position > 1500€ ODER Strategy in {PS_*, PT, S*})
  - Optional: bei Cold-Start als Fallback statt "kein Edge"-WATCH
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

PERSONAS_FILE = WS / 'data' / 'personas' / 'investor_agents.json'

# Strategy → relevant Personas (Mapping Albert→Investoren)
STRATEGY_PERSONA_MAP = {
    # Thesis-Plays (7-30d): Moat + Cycles + Margin of Safety
    'PS_': ['warren_buffett_agent', 'howard_marks_agent', 'seth_klarman_agent'],
    # Thesis-Swing
    'PT': ['peter_lynch_agent', 'joel_greenblatt_agent'],
    # Momentum (2-7d): Catalyst-Driven
    'PM': ['david_einhorn_agent', 'bill_miller_agent'],
    # Long-term winners
    'S':  ['warren_buffett_agent', 'charlie_munger_agent'],
    # Cold-Start: strict-value fallback
    '_COLD_START': ['benjamin_graham_agent', 'jean_marie_eveillard_agent'],
}

_PERSONAS_CACHE: dict | None = None


def load_personas() -> dict:
    """Lade alle 11 Personas aus JSON (cached)."""
    global _PERSONAS_CACHE
    if _PERSONAS_CACHE is not None:
        return _PERSONAS_CACHE
    if not PERSONAS_FILE.exists():
        _PERSONAS_CACHE = {}
        return {}
    data = json.loads(PERSONAS_FILE.read_text(encoding='utf-8'))
    _PERSONAS_CACHE = {a['id']: a for a in data.get('agents', [])}
    return _PERSONAS_CACHE


def get_relevant_personas(strategy: str = '', position_eur: float = 0,
                            cold_start: bool = False) -> list[str]:
    """Liefere passende Persona-IDs für einen Trade-Vorschlag.

    Trigger-Regeln:
      - Position > 1500€ → mindestens 1 Persona
      - Strategy startet mit PS_/PT/PM/S → mapping nutzen
      - cold_start=True → Graham/Eveillard fallback
    """
    personas: list[str] = []
    strategy = (strategy or '').upper()

    # Prefix-Matching
    for prefix, ids in STRATEGY_PERSONA_MAP.items():
        if prefix == '_COLD_START':
            continue
        if strategy.startswith(prefix):
            personas.extend(ids[:2])  # max 2 pro Strategie
            break

    if cold_start:
        personas.extend(STRATEGY_PERSONA_MAP['_COLD_START'][:1])

    # Default für High-Conviction ohne Match
    if not personas and position_eur >= 1500:
        personas = ['warren_buffett_agent']

    return list(dict.fromkeys(personas))[:3]  # max 3, dedupliziert


def get_persona_prompt(persona_id: str, proposal: dict,
                         pre_data: dict | None = None) -> str:
    """Bau den finalen Prompt für eine Persona zu einem Proposal."""
    p = load_personas().get(persona_id)
    if not p:
        return ''
    instr = p.get('config', {}).get('instructions', '')

    pre_str = ''
    if pre_data:
        pre_str = f"\n\nPRE-FETCHED DATA:\n{json.dumps(pre_data, default=str)[:1500]}"

    return f"""{instr}

═══ PROPOSAL ═══
Ticker: {proposal.get('ticker','?')}
Strategy: {proposal.get('strategy','?')}
Entry: {proposal.get('entry_price','?')} | Stop: {proposal.get('stop','?')} | Target: {proposal.get('target_1','?')}
Sector: {proposal.get('sector','?')}
Thesis: {(proposal.get('thesis','') or '')[:300]}
{pre_str}

═══ TASK ═══
Folge deinem Framework strikt. Antworte NUR mit JSON:
{{
  "signal": "bullish|neutral|bearish",
  "confidence": 0.0-1.0,
  "key_metric": "EIN konkretes Argument (Zahl/Faktum)",
  "verdict": "1-2 Sätze",
  "risks": ["risk1", "risk2"]
}}"""


def run_persona_check(persona_id: str, proposal: dict,
                        pre_data: dict | None = None) -> dict:
    """Rufe LLM mit Persona-Prompt, parse JSON, return strukturiert.

    Bei Fehler: {'signal': 'neutral', 'confidence': 0.0, 'error': '...'}
    """
    prompt = get_persona_prompt(persona_id, proposal, pre_data)
    if not prompt:
        return {'signal': 'neutral', 'confidence': 0.0,
                'error': f'persona {persona_id} not found'}

    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=600)
    except Exception as e:
        return {'signal': 'neutral', 'confidence': 0.0,
                'error': f'llm_error: {e}'}

    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]

    i, j = text.find('{'), text.rfind('}')
    if i < 0 or j < 0:
        return {'signal': 'neutral', 'confidence': 0.0,
                'error': 'no_json', 'raw': text[:200]}
    try:
        data = json.loads(text[i:j+1])
        return {
            'persona': persona_id,
            'signal': str(data.get('signal', 'neutral')).lower(),
            'confidence': float(data.get('confidence', 0.0)),
            'key_metric': str(data.get('key_metric', ''))[:200],
            'verdict': str(data.get('verdict', ''))[:300],
            'risks': data.get('risks', [])[:3],
        }
    except Exception as e:
        return {'signal': 'neutral', 'confidence': 0.0,
                'error': f'parse: {e}', 'raw': text[:200]}


def aggregate_persona_signals(checks: list[dict]) -> dict:
    """Aggregiere mehrere Persona-Checks zu einem Konsens-Signal.

    Returns:
      {'consensus': 'bullish|neutral|bearish',
       'avg_confidence': float,
       'agreement_pct': float,  # wie einig sind die Personas?
       'votes': {'bullish': n, 'neutral': n, 'bearish': n}}
    """
    if not checks:
        return {'consensus': 'neutral', 'avg_confidence': 0.0,
                'agreement_pct': 0.0, 'votes': {}}

    votes = {'bullish': 0, 'neutral': 0, 'bearish': 0}
    confs: list[float] = []
    for c in checks:
        sig = c.get('signal', 'neutral')
        if sig in votes:
            votes[sig] += 1
        confs.append(float(c.get('confidence', 0)))

    consensus = max(votes, key=votes.get)
    agreement = votes[consensus] / len(checks) * 100
    return {
        'consensus': consensus,
        'avg_confidence': round(sum(confs) / len(confs), 2),
        'agreement_pct': round(agreement, 1),
        'votes': votes,
        'n_personas': len(checks),
    }


def main() -> int:
    """CLI: list personas oder run check."""
    args = sys.argv[1:]
    if not args or args[0] == 'list':
        for pid, p in load_personas().items():
            print(f"  {pid:<35} {p.get('description','')[:90]}")
        return 0

    if args[0] == 'test' and len(args) >= 2:
        pid = args[1]
        test_proposal = {
            'ticker': 'NVDA', 'strategy': 'PS_AI', 'entry_price': 850,
            'stop': 780, 'target_1': 1000, 'sector': 'tech',
            'thesis': 'AI infrastructure leader, GPU monopoly',
        }
        result = run_persona_check(pid, test_proposal)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print('Usage: ceo_personas.py [list|test PERSONA_ID]')
    return 1


if __name__ == '__main__':
    sys.exit(main())
