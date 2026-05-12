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

    # Phase 45ao: Markt-Puls + News-Correlation als Pflicht-Kontext
    market_pulse_str = '(market_pulse_latest.json nicht gefunden)'
    try:
        mp_file = WS / 'data' / 'market_pulse_latest.json'
        if mp_file.exists():
            mp = json.loads(mp_file.read_text(encoding='utf-8'))
            market_pulse_str = (
                f"TOP-5 OUT-PERFORMER (5d): "
                + ', '.join(f"{e['ticker']}({e['sector']}, {e['chg_5d']:+}%)" for e in mp.get('top_5d', [])[:5])
                + "\nTOP-5 BESCHLEUNIGER: "
                + ', '.join(f"{e['ticker']}({e['chg_5d']:+}%/{e['chg_30d']:+}%)" for e in mp.get('accelerating', [])[:5])
                + "\nDRILLDOWN Top-3: "
                + '; '.join(
                    f"{etf}: " + ', '.join(c['ticker'] + f"({c['trend']})" for c in comps[:4])
                    for etf, comps in list(mp.get('drilldowns', {}).items())[:3]
                  )
            )
    except Exception as _e:
        market_pulse_str = f'(market_pulse parse-err: {_e})'

    news_corr_str = '(sector_news_correlation.json nicht gefunden)'
    try:
        nc_file = WS / 'data' / 'sector_news_correlation.json'
        if nc_file.exists():
            nc = json.loads(nc_file.read_text(encoding='utf-8'))
            hc = nc.get('high_conviction', [])
            structural = nc.get('structural', [])
            traps = nc.get('traps', [])
            news_corr_str = (
                f"HIGH_CONVICTION (Markt+News): " + ', '.join(c['ticker'] for c in hc[:5])
                + f"\nSTRUCTURAL (Markt ohne News): " + ', '.join(c['ticker'] for c in structural[:5])
                + f"\nTRAPS (vermeiden!): " + ', '.join(c['ticker'] for c in traps[:5])
            )
    except Exception: pass

    genesis_str = '(noch keine Genesis-Proposals heute)'
    try:
        gen_file = WS / 'data' / 'strategy_genesis_log.jsonl'
        if gen_file.exists():
            lines = gen_file.read_text(encoding='utf-8').strip().splitlines()
            if lines:
                last = json.loads(lines[-1])
                today_str = datetime.now().strftime('%Y-%m-%d')
                if last.get('ts', '').startswith(today_str):
                    props = last.get('proposals', [])
                    genesis_str = f"{len(props)} Genesis-Proposals heute: " + json.dumps(
                        [{'action': p.get('action'), 'target': p.get('target'),
                          'tickers': p.get('tickers'), 'thesis': p.get('thesis','')[:100]}
                         for p in props[:4]], ensure_ascii=False, indent=2)
    except Exception: pass

    # Pre-compute Strings für f-string (vermeidet Escape-Hell)
    recent_acts_summary = json.dumps(
        [{'a': a.get('action'), 'r': (a.get('reason') or '')[:80]} for a in recent_acts],
        ensure_ascii=False, indent=2
    )

    # Track-Record: letzte 10 Entscheidungen mit Verdict (wenn vorhanden)
    verdicts_file = WS / 'data' / 'albert_decision_verdicts.jsonl'
    track_record = []
    if verdicts_file.exists():
        try:
            with open(verdicts_file, encoding='utf-8') as f:
                for line in f:
                    try: track_record.append(json.loads(line))
                    except Exception: pass
        except Exception: pass
    track_record_summary = json.dumps(
        [{'date': v.get('reviewed_at', '')[:10],
          'action': v.get('proposal', {}).get('action'),
          'target': v.get('proposal', {}).get('target'),
          'verdict': v.get('verdict'),
          'lesson': (v.get('lesson') or '')[:120]}
         for v in track_record[-10:]],
        ensure_ascii=False, indent=2
    ) if track_record else '(noch kein Track-Record — erste Reviews ab morgen)'

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
{recent_acts_summary}

═══ DEINE LETZTEN ENTSCHEIDUNGEN (Track-Record, max 10) ═══
{track_record_summary}

═══ MARKT-PULS (Phase 45ao Layer 1+2 — heute 06:00) ═══
{market_pulse_str}

═══ NEWS-CROSS (Phase 45ao Layer 3 — Markt + News kombiniert) ═══
{news_corr_str}

═══ GENESIS-PROPOSALS (Phase 45ao Layer 4 — automatische Gap-Vorschläge) ═══
{genesis_str}

WICHTIG: Wenn HIGH_CONVICTION oder STRUCTURAL Sektoren aktiv sind, MUSST du
sie in deinen Vorschlägen berücksichtigen. Wenn du KEINE Strategie für einen
Top-5d-Sektor hast (siehe Genesis), proposiere create_strategy.

═══ AKTUELLER MODUS ═══

LERN-MODUS (Phase 45au, Victor 2026-05-12). Cash auf der Seitenlinie ist
Lernverlust. Wir testen aktiv verschiedene Entry-Patterns (Breakout, Pullback,
Range-Break, Climax-Reversal, Gap-Followthrough) und Exit-Strategien (Tranche,
Hard-Target, Time-Stop, ATR-Trail) in verschiedenen Sektoren. **Paper-Trades:
Verluste sind Datenpunkte, nicht Drama.** Ziel: lernen WANN Entry funktioniert
und WANN Exit. Aggressive Sizing erlaubt (Risk 1.5%, Kelly 7%, max 3k EUR).

═══ DEINE AUFGABE ═══

Heute morgen, als CEO, sollst du DREI Dinge liefern. Sei konkret, kurz,
nicht-generisch. Beziehe dich auf konkrete Tickers/Strategien/Daten.

WICHTIG: Wenn Cash-Quote der jüngsten Kohorte > 50% nach 7+ Tagen, MUSST du
aggressiver proposieren. Cash auf Konto = ungelernte Lektion. Lieber 3 Trades
mit -5% Verlust als 0 Trades und keine Erkenntnis. **Diversifiziere Sektoren
und Entry-Pattern-Typen aktiv über die Trades.**

## 1. MARKT-PHASEN-DIAGNOSE (max 100 Wörter)
In welcher Phase sind wir? Risk-On/Off? Welche Sektoren laufen?
Welche fundamentalen Treiber sind aktuell wichtig (Fed, Geo, Earnings)?
Was würde Dirk-Tradermacher heute tun?
**Plus:** Welches Entry-Pattern (Breakout/Pullback/Range/Climax/Gap) passt heute am besten zur Marktlage?

## 2. STRATEGIE-VORSCHLÄGE (max 5 Items, JSON)
Konkrete Aktionen die heute/diese Woche umgesetzt werden sollen.
WICHTIG: Jede Proposal MUSS einen messbaren expected_outcome haben damit
du später retrospektiv beurteilen kannst ob die Entscheidung richtig war.
Format pro Item:
{{
  "action": "create_strategy" | "kill_strategy" | "pause_strategy" | "rotate_focus",
  "target": "PS_NEUE_ID oder bestehende ID oder Sektor-Name",
  "tickers": ["TICK1","TICK2"],
  "thesis": "warum diese Strategie? Was ist der Edge?",
  "trigger": "wann triggert sie? (konkrete Bedingung)",
  "stop_logic": "wo ist der Stop?",
  "priority": "high|med|low",
  "rationale": "in 1 Satz: warum jetzt?",
  "expected_outcome": "WAS messbares erwartest du? z.B. 'PS_HLAG +5% binnen 14d nach Suez-Reopening' oder 'PS1-Pause spart -50€/Woche Hallu-Schaden'",
  "evaluate_after_days": 1   // ← WÄHLE PASSEND: 1=taktisch (Cleanup, Pause), 3=Setup-Test, 7=Strategy-Pivot, 14=Thesis-Play
}}

WICHTIG: kurze Fenster wenn möglich. Lieber 1-Tag-Reviews die schnell Feedback geben,
als 7-Tage-Reviews die zu spät kommen. Strategische Entscheidungen brauchen längere
Fenster, taktische (Cleanup, Pause, Sweep) reichen 1-2 Tage. Du musst SO SCHNELL
WIE MÖGLICH lernen ob deine Decisions richtig waren.

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
