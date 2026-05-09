#!/usr/bin/env python3
"""
albert_strategist.py — Phase 45ak (Victor 2026-05-09).

Albert's täglicher Strategie-Slot. 06:30 Mo-Fr mit OPUS — er liest
ALLES (Methodik, Deep-Dive-Doktrin, alle Strategien, News, eigenes Tagebuch
+ accumulated Self-Actions) und proposiert konkret:

  - Neue Strategien (mit Tickers + Trigger + Stop-Logik)
  - Strategien zu killen (mit Begründung)
  - Fokus-Rotationen (Sektor-Shifts)
  - Markt-Phase-Diagnose (was ist gerade dran?)

Output:
  data/albert_strategist_proposals.jsonl  — strukturiert für Review
  data/albert_strategist_latest.md         — wird in Morgen-Briefing eingebunden
  ceo_inbox event                          — health/strategy

Run: täglich 06:30 (vor Morgen-Briefing 08:00).
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

PROPOSALS = WS / 'data' / 'albert_strategist_proposals.jsonl'
OUT_MD    = WS / 'data' / 'albert_strategist_latest.md'

METHODIK   = WS / 'memory' / 'tradermacher-methodik.md'
DEEPDIVE   = WS / 'memory' / 'deepdive-protokoll.md'
STRATEGIEN = WS / 'memory' / 'strategien.md'
DIARY      = WS / 'memory' / 'albert_diary.md'
RULES      = WS / 'memory' / 'albert_self_rules.md'
GOALS      = WS / 'data' / 'albert_goals.json'
ACTIONS    = WS / 'data' / 'albert_self_actions.jsonl'
DIRECTIVE  = WS / 'data' / 'ceo_directive.json'
REGIME     = WS / 'data' / 'current_regime.json'
STRATS     = WS / 'data' / 'strategies.json'
LIFECYCLE  = WS / 'data' / 'strategy_lifecycle.json'
DB         = WS / 'data' / 'trading.db'


def _read(p: Path, max_chars: int = 8000) -> str:
    if not p.exists(): return ''
    try:
        t = p.read_text(encoding='utf-8')
        return t[-max_chars:] if len(t) > max_chars else t
    except Exception: return ''


def _read_json(p: Path) -> dict:
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return {}


def _gather_open_strategies() -> list[dict]:
    s = _read_json(STRATS)
    out = []
    for sid, meta in s.items():
        if not isinstance(meta, dict): continue
        if meta.get('status') != 'active': continue
        out.append({
            'id': sid,
            'tickers': meta.get('tickers') or meta.get('ticker_universe', []),
            'thesis': (meta.get('thesis') or meta.get('description', ''))[:120],
        })
    return out[:60]


def _gather_recent_actions(days: int = 1) -> list[dict]:
    """Letzte Self-Actions aus Brain-Tick als Hintergrund."""
    if not ACTIONS.exists(): return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    try:
        with open(ACTIONS, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('ts', '') >= cutoff:
                        out.append(e)
                except Exception: pass
    except Exception: pass
    return out[-30:]


def _trade_perf_summary(days: int = 30) -> dict:
    if not DB.exists(): return {}
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT strategy, pnl_eur, exit_type, status FROM paper_portfolio "
        "WHERE close_date >= ?", (cutoff,)
    ).fetchall()
    db.close()
    by_strat = {}
    for r in rows:
        s = r['strategy'] or '?'
        d = by_strat.setdefault(s, {'n': 0, 'wins': 0, 'pnl': 0.0, 'bugs': 0})
        d['n'] += 1
        if (r['exit_type'] or '').startswith('BUG_'):
            d['bugs'] += 1
        else:
            if (r['pnl_eur'] or 0) > 0: d['wins'] += 1
            d['pnl'] += (r['pnl_eur'] or 0)
    return {k: v for k, v in by_strat.items() if v['n'] > 0}


def run() -> dict:
    now = datetime.now(timezone.utc)

    methodik     = _read(METHODIK, 4000)
    deepdive     = _read(DEEPDIVE, 2000)
    strategien   = _read(STRATEGIEN, 3000)
    diary_tail   = _read(DIARY, 3000)
    rules        = _read(RULES, 1500)
    goals        = _read_json(GOALS)
    directive    = _read_json(DIRECTIVE)
    regime       = _read_json(REGIME)
    lifecycle    = _read_json(LIFECYCLE)

    open_strats  = _gather_open_strategies()
    recent_acts  = _gather_recent_actions()
    perf         = _trade_perf_summary(30)

    prompt = f"""Du bist Albert, AI-CEO und Trader. Heute Morgen 06:30 ist DEIN
strategischer Slot — der Moment, in dem du als CEO wirklich denkst:
"Was machen wir heute? Welche Strategien funktionieren? Was muss raus?
Welche neue Idee ist reif?"

Du hast Zeit. Du hast OPUS-Power. Sei präzise, ehrlich, aktiv.

═══ HEUTE ═══
{now.strftime('%a %d.%m.%Y %H:%M')} CEST

═══ DEINE ZIELE ═══
{json.dumps(goals, ensure_ascii=False, indent=2)}

═══ MARKT-LAGE ═══
CEO-Directive: {directive.get('mode','?')} ({directive.get('reason','')[:200]})
Regime: {regime.get('regime','?')} VIX={regime.get('vix','?')}
Lifecycle-Status: {lifecycle.get('counts', {})}

═══ AKTIVE STRATEGIEN ({len(open_strats)}) ═══
{json.dumps(open_strats, ensure_ascii=False, indent=2)}

═══ STRATEGIE-PERFORMANCE 30d ═══
{json.dumps(perf, ensure_ascii=False, indent=2)}

═══ TRADERMACHER-METHODIK (Lernung von Dirk 7H) ═══
{methodik}

═══ DEEPDIVE-DOKTRIN (Pflicht-Protokoll vor Entry) ═══
{deepdive}

═══ STRATEGIEN-FRAMEWORK (PS1-PS11, S1-S11 dokumentiert) ═══
{strategien}

═══ DEINE LETZTEN GEDANKEN (Brain-Tick-Tagebuch) ═══
{diary_tail}

═══ DEINE EIGENEN REGELN ═══
{rules}

═══ SELF-ACTIONS DIE BRAIN-TICK GEQUEUED HAT ═══
{json.dumps([{{'a': a.get('action'), 'r': a.get('reason','')[:80]}} for a in recent_acts], ensure_ascii=False, indent=2)}

═══ DEINE AUFGABE ═══

Heute morgen, als CEO, sollst du DREI Dinge liefern. Sei konkret, kurz,
nicht-generisch. Beziehe dich auf konkrete Tickers/Strategien/Daten.

## 1. MARKT-PHASEN-DIAGNOSE (max 100 Wörter)
In welcher Phase sind wir? Risk-On/Off? Welche Sektoren laufen?
Welche fundamentalen Treiber sind aktuell wichtig (Fed, Geo, Earnings)?
Was würde Dirk-Tradermacher heute tun?

## 2. STRATEGIE-VORSCHLÄGE (max 5 Items, JSON)
Konkrete Aktionen die heute/diese Woche umgesetzt werden sollen.
Format pro Item:
{{
  "action": "create_strategy" | "kill_strategy" | "pause_strategy" | "rotate_focus",
  "target": "PS_NEUE_ID oder bestehende ID oder Sektor-Name",
  "tickers": ["TICK1","TICK2"],   // nur bei create
  "thesis": "warum diese Strategie? Was ist der Edge?",
  "trigger": "wann triggert sie? (konkrete Bedingung)",
  "stop_logic": "wo ist der Stop?",
  "priority": "high|med|low",
  "rationale": "in 1 Satz: warum jetzt?"
}}

## 3. WAS WÜRDE ALBERT HEUTE PERSÖNLICH TRADEN? (max 80 Wörter)
Wenn der Markt heute öffnet, welche 1-2 konkreten Setups würdest du nehmen?
Welche aktuell offene Strategie ist reif für ein Entry-Signal?
Sei spezifisch: Ticker + warum + wo Entry + wo Stop.

ANTWORT-FORMAT: Markdown mit ## Headers für die 3 Sektionen.
Sektion 2 muss valides JSON enthalten in einem ```json codeblock.
"""

    try:
        from llm_client import call_llm
        text, meta = call_llm(prompt, model_hint='opus', max_tokens=3000)
    except Exception as e:
        return {'error': f'llm_fail: {e}'}

    # Parse JSON proposals if present
    import re
    proposals_parsed = []
    m = re.search(r'```json\s*(\[.*?\])\s*```', text, re.S)
    if m:
        try:
            proposals_parsed = json.loads(m.group(1))
        except Exception: pass

    # Save MD
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    md = (f"# Albert-Strategist — {now.strftime('%Y-%m-%d %H:%M')} CEST\n\n"
          f"_Täglicher strategischer Slot. Opus-Reflexion über Markt-Phase, "
          f"Strategien, heutige Setups._\n\n"
          f"---\n\n{text}\n")
    OUT_MD.write_text(md, encoding='utf-8')

    # Save JSONL log
    PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROPOSALS, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': now.isoformat(timespec='seconds'),
            'n_proposals': len(proposals_parsed),
            'proposals': proposals_parsed,
            'full_text': text,
        }, ensure_ascii=False, default=str) + '\n')

    # CEO-Inbox event
    try:
        from ceo_inbox import write_event
        write_event(
            event_type='strategist.morning_proposals',
            message=f'Albert-Strategist: {len(proposals_parsed)} Proposals heute',
            severity='info', category='health', user_pinged=False,
            payload={'n_proposals': len(proposals_parsed)},
        )
    except Exception: pass

    return {'ok': True, 'n_proposals': len(proposals_parsed), 'chars': len(text)}


def main() -> int:
    r = run()
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
