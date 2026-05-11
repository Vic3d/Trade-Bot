#!/usr/bin/env python3
"""
strategy_genesis_engine.py — Phase 45ao Layer 4 (Victor 2026-05-11).

Liest market_pulse_latest.json + strategies.json + decision_verdicts und
generiert via Opus konkrete Strategy-Proposals:
  - create_strategy: Sektor läuft, keine Strategie dafür → neue PS
  - rotate_tickers: Sektor in Universum, aber falsche/tote Tickers → updaten
  - kill_strategy: Sektor läuft NICHT seit 30d + Strategie hat 0 Trades → kill
  - boost_strategy: Sektor läuft, Strategie ist da, aber INSUFFICIENT → bevorzugt traden

Output landet in albert_strategist_proposals.jsonl (gleicher Channel wie Strategist)
und wird vom 06:30 Strategist-Slot gesehen.

Run: täglich 06:20 (zwischen Market-Pulse 06:00 und Strategist 06:30).
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

PULSE_FILE = WS / 'data' / 'market_pulse_latest.json'
STRATS_FILE = WS / 'data' / 'strategies.json'
PROPOSALS_FILE = WS / 'data' / 'albert_strategist_proposals.jsonl'
GENESIS_LOG = WS / 'data' / 'strategy_genesis_log.jsonl'


def _load_json(p: Path, default=None):
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return default


def _strategy_sector_map(strats: dict) -> dict:
    """Welche Sektoren sind bereits abgedeckt?"""
    sector_map = {}
    for sid, meta in strats.items():
        if not isinstance(meta, dict): continue
        if meta.get('status') != 'active': continue
        sector = meta.get('sector') or 'unknown'
        thesis = (meta.get('thesis') or meta.get('description') or '').lower()
        # Heuristic: derive sector from thesis if not set
        if sector == 'unknown':
            for kw, sec in [('gold', 'GDX'), ('silber', 'SLV'), ('öl', 'XLE'),
                             ('tanker', 'XLE'), ('defense', 'ITA'), ('rüstung', 'ITA'),
                             ('biotech', 'XBI'), ('semi', 'SMH'), ('chip', 'SMH'),
                             ('bank', 'XLF'), ('utilit', 'XLU'), ('dünger', 'XLB'),
                             ('uran', 'URA'), ('lithium', 'LIT'), ('kupfer', 'COPX'),
                             ('solar', 'TAN'), ('staples', 'XLP'), ('healthcare', 'XLV')]:
                if kw in thesis:
                    sector = sec
                    break
        sector_map[sid] = {
            'sector': sector,
            'tickers': meta.get('tickers') or meta.get('ticker_universe', []),
            'status': meta.get('status'),
        }
    return sector_map


def _gap_analysis(pulse: dict, strats: dict) -> dict:
    """Welche Top-Sektoren haben keine Strategie?"""
    sector_map = _strategy_sector_map(strats)
    covered_sectors = set(v['sector'] for v in sector_map.values())
    top_5d = pulse.get('top_5d', [])
    accel = pulse.get('accelerating', [])

    gaps = []
    for e in top_5d[:5] + accel[:5]:
        if e['ticker'] not in covered_sectors and e['chg_5d'] >= 3:
            gaps.append(e)

    # Dedupe
    seen = set()
    gaps_dedup = []
    for g in gaps:
        if g['ticker'] not in seen:
            seen.add(g['ticker'])
            gaps_dedup.append(g)

    return {
        'covered_sectors': sorted(covered_sectors),
        'gaps': gaps_dedup,
        'sector_map': sector_map,
    }


def generate_proposals() -> dict:
    pulse = _load_json(PULSE_FILE, {})
    strats = _load_json(STRATS_FILE, {})
    if not pulse or not strats:
        return {'error': 'missing_input_data', 'pulse_ok': bool(pulse), 'strats_ok': bool(strats)}

    gap = _gap_analysis(pulse, strats)

    # Pulse-Highlights für Prompt
    top_str = '\n'.join([
        f"  {e['ticker']:6} ({e['sector']}): 5d={e['chg_5d']:+}%, 30d={e['chg_30d']:+}%, "
        f"RS-vs-SPY={e['rs_vs_spy_30d']:+}%, trend={e['trend']}"
        for e in pulse.get('top_5d', [])[:5]
    ])
    accel_str = '\n'.join([
        f"  {e['ticker']:6} ({e['sector']}): 5d={e['chg_5d']:+}%, 30d={e['chg_30d']:+}%, trend={e['trend']}"
        for e in pulse.get('accelerating', [])[:5]
    ])
    gaps_str = '\n'.join([
        f"  {g['ticker']} ({g['sector']}): 5d={g['chg_5d']:+}%, trend={g['trend']} → KEINE Strategie!"
        for g in gap['gaps']
    ]) or '  (alle Top-Sektoren sind abgedeckt)'

    # Drilldown der Top-3 als Trade-Kandidaten
    dd_str = ''
    for etf, comps in list(pulse.get('drilldowns', {}).items())[:3]:
        dd_str += f"\n  {etf}: "
        dd_str += ', '.join([f"{c['ticker']} ({c['trend']}, +{c['chg_5d']}%)"
                              for c in comps[:5]])

    prompt = f"""Du bist Albert. Heute morgen 06:20 — bevor du in den Strategist-Slot gehst,
prüfst du den Markt-Puls und entscheidest: welche neuen Strategien BRAUCHST du?

═══ MARKT-PULS (heute 06:00) ═══

TOP-5 OUT-PERFORMER (5d):
{top_str}

TOP-5 BESCHLEUNIGER:
{accel_str}

GAPS (laufen heiß, KEINE Strategie dafür):
{gaps_str}

DRILLDOWN Top-3 Sektoren (Komponenten):
{dd_str}

═══ DEINE BESTEHENDEN AKTIVEN STRATEGIEN ═══
{json.dumps(gap['sector_map'], ensure_ascii=False, indent=2)}

═══ DEINE AUFGABE ═══

Generiere 1-4 KONKRETE Proposals als JSON-Array. Sei selektiv — lieber
2 hochwertige als 5 schwache. Formate:

CREATE — neuer Sektor läuft, keine Strategie:
{{
  "action": "create_strategy",
  "target": "PS_NEUE_ID (z.B. PS_GOLD_RALLY)",
  "tickers": ["GDX", "NEM", "AEM"],
  "thesis": "Konkret WARUM dieser Sektor jetzt — was treibt ihn (Markt-Daten + Hypothese)",
  "trigger": "Konkrete Entry-Bedingung (z.B. Pullback auf EMA10 mit grünem Tag)",
  "stop_logic": "Wo der Stop sitzt — konkret",
  "priority": "high|med|low",
  "rationale": "1-Satz: warum HEUTE, nicht morgen?",
  "expected_outcome": "Messbare Erwartung (z.B. NEM +6% in 7d nach Pullback-Entry)",
  "evaluate_after_days": 7
}}

ROTATE_TICKERS — Strategie da, aber alte/tote Tickers:
{{"action": "rotate_tickers", "target": "PS_BESTEHEND", "old_tickers": [...],
  "new_tickers": [...], "thesis": "warum die alten raus, die neuen rein",
  ...}}

KILL — Sektor down, Strategie da, 0 Trades:
{{"action": "kill_strategy", "target": "PS_X", ...}}

BOOST — Sektor läuft, Strategie da, aber INSUFFICIENT → bevorzugt traden:
{{"action": "boost_strategy", "target": "PS_X", "thesis": "Sektor heiß, lieber jetzt eine Probe-Position",
  ...}}

WICHTIG:
- Beziehe dich auf KONKRETE Daten aus dem Markt-Puls oben — keine erfundenen Zahlen.
- Wenn KEINE überzeugende Gap → lieber leeres Array [] zurück als Müll.
- Nur Setups die EINEN messbaren Trigger haben — keine "schauen wir mal"-Strategien.
- Tickers MÜSSEN aus dem Drilldown oder erkannten Sektoren kommen.

ANTWORTE NUR mit dem JSON-Array, kein Drumherum.
"""

    try:
        from llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='opus', max_tokens=2500)
    except Exception as e:
        return {'error': f'llm_fail: {e}', 'gap_analysis': gap}

    # Parse JSON
    import re
    proposals = []
    m = re.search(r'\[.*\]', text, re.S)
    if m:
        try: proposals = json.loads(m.group(0))
        except Exception: pass

    # Persist
    now = datetime.now(timezone.utc)
    record = {
        'ts': now.isoformat(timespec='seconds'),
        'source': 'genesis_engine',
        'n_proposals': len(proposals),
        'proposals': proposals,
        'gap_analysis': gap,
        'full_text': text,
    }

    GENESIS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(GENESIS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')

    # Auch in albert_strategist_proposals.jsonl damit Strategist es sieht
    if proposals:
        with open(PROPOSALS_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': now.isoformat(timespec='seconds'),
                'source': 'genesis_engine',
                'n_proposals': len(proposals),
                'proposals': proposals,
            }, ensure_ascii=False, default=str) + '\n')

    return {'ok': True, 'n_proposals': len(proposals),
            'gaps_found': len(gap['gaps']),
            'first_proposal_action': proposals[0].get('action') if proposals else None}


def main() -> int:
    r = generate_proposals()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
