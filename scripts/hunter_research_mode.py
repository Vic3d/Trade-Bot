#!/usr/bin/env python3
"""
hunter_research_mode.py — Phase 44y: Hunter ohne Trade-Execution.

User-Korrektur (Victor 03.05): Hunter sollte auch am Wochenende laufen —
Thesen suchen + verifizieren ist kein Markt-abhaengiger Vorgang. Nur
TRADE-EXECUTION braucht offene Boersen.

Dieser Job ruft den bestehenden ceo_active_hunter im RESEARCH-MODE:
  - Generiert Setup-Vorschlaege wie immer (LLM + News + Macro)
  - Schreibt sie aber NICHT in proposals.json (= keine Trade-Pipeline)
  - Schreibt sie in memory/ceo-thesis-pipeline/YYYY-MM-DD.md
  - Output: 'Heute identifizierte Setup-Kandidaten — fuer Mo-Verifikation'
  - Discord SILENT (kein Spam — User sieht es im naechsten Self-Research)

Mo-Morgen kann der Executor diese Pipeline lesen und entscheiden welche
Setups noch valide sind (Tape-Move ueberpruefen, dann Entry).

Run: python3 scripts/hunter_research_mode.py
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

PIPELINE_DIR = WS / 'memory' / 'ceo-thesis-pipeline'
LOG = WS / 'data' / 'hunter_research_log.jsonl'


def _now() -> str: return datetime.now(timezone.utc).isoformat()


RESEARCH_SYSTEM = """Du bist Albert im RESEARCH-MODE. Es ist Wochenende oder
ausserhalb Trading-Window. KEINE Trades werden platziert — du suchst nur Thesen
fuer den NAECHSTEN Trading-Tag.

WICHTIG: Markt-Status ist IRRELEVANT. Du sollst TROTZDEM Setups generieren,
auch wenn Boersen geschlossen sind. Sie werden am naechsten Trading-Tag
verifiziert + ggf. ausgefuehrt.

Generiere 3-5 Setup-Kandidaten basierend auf:
- aktuellen Macro-Events
- News der letzten 6h
- Active-Strategies (welche koennten Mo Morgen feuern?)
- Externen Research-Thesen (von Victor eingebracht)
- Open-Positions (was koennte sie Mo bewegen?)

Pro Setup: ticker, strategy, why-now, was muss Mo-Morgen passieren damit Trade
gerechtfertigt ist (Falsifikations-Check), conf 0.0-1.0.

Antwort als JSON:
{
  "thinking": "max 400 chars analysis",
  "setups": [
    {"ticker": "...", "strategy": "...", "thesis": "...",
     "monday_check": "was Mo verifizieren", "confidence": 0.7,
     "trigger": "macro_event|news|strategy_match|catalyst"}
  ]
}"""


def run() -> dict:
    # Eigener Prompt-Build, nutze ceo_active_hunter als context-Provider
    try:
        from ceo_active_hunter import gather_hunting_context, _build_hunter_prompt
        from core.llm_client import call_llm
    except Exception as e:
        return {'error': f'import_fail: {e}'}

    try:
        ctx = gather_hunting_context()
        # Bauen wir den Standard-Prompt fuer Context, aber ueberschreiben System
        base_prompt = _build_hunter_prompt(ctx, max_new=5)
    except Exception as e:
        return {'error': f'context_fail: {e}'}

    # Direct LLM call mit Research-System
    try:
        text, usage = call_llm(
            base_prompt + "\n\nWICHTIG: RESEARCH-MODE. Markt-Status ist egal. "
            "Generiere Setups fuer naechsten Trading-Tag.",
            model_hint='sonnet', max_tokens=2000,
            system=RESEARCH_SYSTEM, audit_context='hunter_research'
        )
    except Exception as e:
        return {'error': f'llm_fail: {e}'}

    # Parse JSON
    setups = []
    thinking = ''
    try:
        import re
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            j = json.loads(m.group(0))
            setups = j.get('setups', [])
            thinking = j.get('thinking', '')
    except Exception as e:
        thinking = f'(JSON-parse-fail: {e})'
    today = datetime.now().strftime('%Y-%m-%d')
    weekday = datetime.now().strftime('%A')

    # Pipeline-File schreiben
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    f = PIPELINE_DIR / f'{today}.md'
    lines = [
        f'# Thesen-Pipeline {today} ({weekday})',
        '',
        '*Hunter im RESEARCH-MODE. Keine Trades platziert — nur Setup-Kandidaten '
        'fuer den naechsten Trading-Tag identifiziert.*',
        '',
        f'## Hunter-Thinking',
        f'{thinking[:1200] if thinking else "(kein Thinking-Output)"}',
        '',
        f'## Setup-Kandidaten ({len(setups)})',
    ]
    if setups:
        for s in setups:
            lines.append(f"- **{s.get('ticker','?')}** ({s.get('strategy','?')}) "
                          f"conf={s.get('confidence','?')} trigger={s.get('trigger','?')}")
            if s.get('thesis'):
                lines.append(f"  Thesis: {s['thesis'][:200]}")
            if s.get('entry') and s.get('stop'):
                lines.append(f"  Entry: {s.get('entry')} | Stop: {s.get('stop')} | "
                              f"Target: {s.get('target','?')}")
    else:
        lines.append('  (keine Setups generiert)')
    lines.append('')
    lines.append(f'## Folge-Aufgabe Mo-Morgen')
    lines.append('1. Tape-Check: hat sich seit jetzt etwas relevantes bewegt?')
    lines.append('2. Re-Verify These: News/Catalysts seitdem?')
    lines.append('3. Wenn These intakt → execute_paper_entry mit aktuellem Live-Preis')
    f.write_text('\n'.join(lines), encoding='utf-8')

    # Audit-Log
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': _now(), 'date': today,
                              'n_setups': len(setups),
                              'setups': [{'ticker': s.get('ticker'),
                                          'strategy': s.get('strategy'),
                                          'confidence': s.get('confidence')}
                                         for s in setups]},
                             ensure_ascii=False) + '\n')

    return {'ts': _now(), 'date': today,
            'n_setups': len(setups), 'file': str(f)}


def main() -> int:
    r = run()
    if 'error' in r:
        print(f'Error: {r["error"]}'); return 1
    print(f'═══ Hunter Research-Mode @ {r["ts"][:16]} ═══')
    print(f'  Setups identifiziert: {r["n_setups"]}')
    print(f'  Pipeline-File: {r["file"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
