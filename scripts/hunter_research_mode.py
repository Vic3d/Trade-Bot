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


def run() -> dict:
    try:
        from ceo_active_hunter import hunt_for_setups
    except Exception as e:
        return {'error': f'hunter_import_fail: {e}'}

    # Hunt im dry_run-Mode → generiert Setups, schreibt NICHT in proposals.json
    try:
        result = hunt_for_setups(max_new=5, dry_run=True)
    except Exception as e:
        return {'error': f'hunt_fail: {e}'}

    setups = result.get('setups', []) if isinstance(result, dict) else []
    thinking = result.get('thinking', '') if isinstance(result, dict) else ''
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
