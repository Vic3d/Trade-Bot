#!/usr/bin/env python3
"""
ceo_intelligence.py — Phase 32: Smart-CEO Helper-Modul.

Bundle aus:
  32a Decision-Memory   — load_decision_memory()
  32b Chain-of-Thought  — build_cot_prompt()
  32c Lessons-DB        — load_lessons() / append_lesson()
  32d Tool-Use          — gather_tool_data() (pre-computed Context-Bundle)
  32e Multi-Agent       — run_persona() + synthesize()

Wird von ceo_brain.py importiert. Eigenständig nicht ausführbar.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB             = WS / 'data' / 'trading.db'
DECISIONS_LOG  = WS / 'data' / 'ceo_decisions.jsonl'
LESSONS_LOG    = WS / 'data' / 'ceo_lessons.jsonl'


# ═══════════════════════════════════════════════════════════════════════════
# 32a — Decision-Memory
# ═══════════════════════════════════════════════════════════════════════════

def load_decision_memory(n: int = 20) -> list[dict]:
    """Letzte N CEO-Decisions mit Outcome (PnL falls Trade closed)."""
    if not DECISIONS_LOG.exists():
        return []
    lines = DECISIONS_LOG.read_text(encoding='utf-8').strip().split('\n')[-n*3:]  # buffer
    decisions = []
    for ln in lines:
        try:
            d = json.loads(ln)
            if d.get('event') in ('execute', 'skip', 'watch'):
                decisions.append(d)
        except Exception:
            continue
    decisions = decisions[-n:]  # final last N

    # Enrich mit Trade-Outcomes (falls trade_id existiert + Trade closed ist)
    if not decisions:
        return []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        for d in decisions:
            tid = d.get('trade_id')
            if not tid:
                continue
            row = c.execute(
                "SELECT status, pnl_eur, pnl_pct, exit_type FROM paper_portfolio WHERE id=?",
                (tid,)
            ).fetchone()
            if row:
                d['_outcome'] = {
                    'status': row['status'],
                    'pnl_eur': row['pnl_eur'],
                    'pnl_pct': row['pnl_pct'],
                    'exit_type': row['exit_type'],
                }
        c.close()
    except Exception as e:
        print(f'[ceo_intel] memory enrich error: {e}', file=sys.stderr)
    return decisions


def find_similar_past_trades(ticker: str, strategy: str, n: int = 5) -> list[dict]:
    """Pattern-Match: ähnliche historische Trades (selbe Strategie ODER selber Sektor)."""
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT ticker, strategy, pnl_eur, pnl_pct, exit_type, entry_date
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND (strategy = ? OR ticker = ?)
            ORDER BY entry_date DESC LIMIT ?
        """, (strategy, ticker, n)).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
# 32c — Lessons-DB
# ═══════════════════════════════════════════════════════════════════════════

def load_lessons(max_age_days: int = 60, limit: int = 30) -> list[dict]:
    """Liest letzte Lessons aus ceo_lessons.jsonl (Filter: nicht zu alt)."""
    if not LESSONS_LOG.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
    lessons = []
    for ln in LESSONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
        try:
            d = json.loads(ln)
            if d.get('ts', '') >= cutoff:
                lessons.append(d)
        except Exception:
            continue
    return lessons[-limit:]


def append_lesson(lesson: str, source_trade_id: int | None = None,
                  category: str = 'general', meta: dict | None = None) -> None:
    """Append-only lesson logging."""
    try:
        LESSONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'lesson': lesson[:500],
            'source_trade_id': source_trade_id,
            'category': category,
            'meta': meta or {},
        }
        with open(LESSONS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'[ceo_intel] lesson log error: {e}', file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════
# 32d — Tool-Use (Pre-Computed Context-Bundle)
# ═══════════════════════════════════════════════════════════════════════════

def gather_tool_data(tickers: list[str]) -> dict:
    """
    Sammelt für alle Pipeline-Tickers: Korrelationen, Sektor-Momentum,
    Recent News, RSI/MA-Distanz. Wird einmalig pro Run berechnet und in
    den LLM-Prompt eingebaut. Spart pro-Call Tool-Roundtrips.
    """
    bundle = {}
    if not tickers:
        return bundle

    # Korrelationen mit OPEN-Positions
    try:
        from portfolio_risk import _get_open_positions, _get_price_series, _pct_returns, _pearson, get_sector
        opens = _get_open_positions()
        for tk in tickers[:20]:  # Cap auf 20 für Performance
            entry = {'sector': get_sector(tk)}
            try:
                tk_series = _get_price_series(tk, days=30)
                tk_ret = _pct_returns(tk_series) if tk_series else []
                # Korrelationen mit jeder OPEN-Position
                corr_map = {}
                for op in opens[:5]:
                    op_series = _get_price_series(op['ticker'], days=30)
                    op_ret = _pct_returns(op_series) if op_series else []
                    if tk_ret and op_ret and len(tk_ret) >= 10 and len(op_ret) >= 10:
                        c = _pearson(tk_ret, op_ret)
                        if c is not None:
                            corr_map[op['ticker']] = round(c, 2)
                if corr_map:
                    entry['corr_with_open'] = corr_map
                    entry['max_corr'] = max(corr_map.values())
            except Exception:
                pass
            bundle[tk] = entry
    except Exception as e:
        print(f'[ceo_intel] tool_data error: {e}', file=sys.stderr)

    return bundle


# ═══════════════════════════════════════════════════════════════════════════
# 32b — Chain-of-Thought Prompt-Builder
# ═══════════════════════════════════════════════════════════════════════════

def build_smart_prompt(state: dict, proposals: list[dict],
                        memory: list[dict], lessons: list[dict],
                        tool_data: dict, persona: str = 'ceo') -> str:
    """Strukturierter CoT-Prompt mit allem Kontext."""
    directive = state.get('directive', {})
    cash_pct = state['cash_eur'] / state['fund_value'] * 100 if state['fund_value'] else 0

    open_pos_str = '\n'.join(
        f"  · {p['ticker']} ({p['strategy']}) {p['position_eur']:.0f}EUR seit {str(p['entry_date'])[:10]}"
        for p in state['open_positions']
    ) or '  (keine)'

    # Memory: letzte 20 Decisions, davon mit Outcome
    mem_lines = []
    for d in memory[-15:]:
        outcome = d.get('_outcome', {})
        if outcome and outcome.get('pnl_eur') is not None:
            icon = '✅' if outcome['pnl_eur'] > 0 else '❌'
            mem_lines.append(
                f"  {icon} {d.get('ts','')[:10]} {d.get('ticker','?')} "
                f"{d.get('strategy','?')} {d.get('action','?')} → "
                f"PnL {outcome['pnl_eur']:+.0f}EUR ({outcome.get('pnl_pct',0):+.1f}%) "
                f"exit={outcome.get('exit_type','?')}"
            )
        else:
            mem_lines.append(
                f"  · {d.get('ts','')[:10]} {d.get('ticker','?')} "
                f"{d.get('action','?')} (offen) — {d.get('reason','')[:60]}"
            )
    memory_str = '\n'.join(mem_lines) or '  (keine bisherigen Decisions)'

    # Lessons
    if lessons:
        lessons_str = '\n'.join(
            f"  • [{l.get('category','?')}] {l.get('lesson','')}"
            for l in lessons[-15:]
        )
    else:
        lessons_str = '  (noch keine Lessons gesammelt)'

    # Proposals mit angereichertem Kontext
    proposals_str = ''
    for i, p in enumerate(proposals, 1):
        tk = p.get('ticker', '?')
        td = tool_data.get(tk, {})
        sector = td.get('sector', '?')
        max_corr = td.get('max_corr')
        corr_str = f" | max_corr_with_open={max_corr:.2f}" if max_corr is not None else ''

        verdict = state['verdicts'].get(tk, {})
        v_text = verdict.get('verdict', '?') if isinstance(verdict, dict) else str(verdict)

        # Similar past trades
        similar = find_similar_past_trades(tk, p.get('strategy', ''), n=3)
        similar_str = ''
        if similar:
            similar_str = ' | history: ' + ', '.join(
                f"{s['ticker']}({s['pnl_eur']:+.0f}€)" for s in similar
            )

        proposals_str += (
            f"\n[{i}] {tk} ({sector}) | {p.get('strategy','?')} | "
            f"entry={p.get('entry_price','?')} stop={p.get('stop','?')} "
            f"target={p.get('target_1') or p.get('target','?')}{corr_str}\n"
            f"     verdict={v_text}{similar_str}\n"
            f"     thesis: {(p.get('thesis','') or '')[:150]}"
        )

    # Persona-spezifische Instructions
    persona_instr = {
        'bull': "Du bist BULL-AGENT. Nur Pro-EXECUTE-Argumente, beste Szenarien.",
        'bear': "Du bist BEAR-AGENT. Nur Risiken, was kann schiefgehen, worst-case.",
        'risk': "Du bist RISK-AGENT. Nur Portfolio-Effekt: Konzentration, Korrelation, Drawdown-Beitrag.",
        'ceo':  "Du bist CEO-SYNTHESIZER. Wäge alle Inputs, entscheide pragmatisch.",
    }
    role = persona_instr.get(persona, persona_instr['ceo'])

    # Phase 36: Calendar/Markt-Status — damit CEO nie raten muss welcher Tag ist
    calendar_block = ''
    try:
        from calendar_service import format_for_prompt as _cal_prompt
        calendar_block = '\n' + _cal_prompt() + '\n'
    except Exception:
        pass

    # Phase 40z: Capabilities-Awareness — CEO weiß welche Tools/Phasen er hat
    capabilities_summary = ''
    try:
        cap_file = WS / 'memory' / 'ceo-capabilities.md'
        if cap_file.exists():
            cap_text = cap_file.read_text(encoding='utf-8')
            # Take only "Übersicht" + "Decision-Pfade" + "Sizing-Stack" sections
            # Compact summary statt full doc
            capabilities_summary = ('\n═══ DEINE FÄHIGKEITEN (du hast Zugriff auf) ═══\n'
                + cap_text[:2000] + '\n')
    except Exception:
        pass

    # Phase 34a: Identity-Anchor in jeden Prompt
    identity_anchor = ''
    try:
        from ceo_narrative_self import get_identity_for_prompt
        ident = get_identity_for_prompt()
        if ident:
            identity_anchor = f"\n═══ DEINE IDENTITÄT (wer du bist) ═══\n{ident[:1500]}\n"
    except Exception:
        pass

    # Strategic Insights aus Dream-Phase
    strategic_str = ''
    try:
        from pathlib import Path as _P
        si_file = _P(WS) / 'data' / 'ceo_strategic_insights.jsonl'
        if si_file.exists():
            insights = []
            for ln in si_file.read_text(encoding='utf-8').strip().split('\n')[-10:]:
                try:
                    insights.append(json.loads(ln).get('insight', ''))
                except Exception:
                    continue
            if insights:
                strategic_str = '\n═══ STRATEGISCHE INSIGHTS (aus Dream-Phasen) ═══\n' + \
                               '\n'.join(f'  💡 {i}' for i in insights[-5:]) + '\n'
    except Exception:
        pass

    return f"""{role}
{calendar_block}{capabilities_summary}{identity_anchor}{strategic_str}

═══ AKTUELLER MARKT-STATE ═══
Mode: {directive.get('mode','?')} | Regime: {directive.get('regime','?')} | VIX: {directive.get('vix','?')}
Geo: {directive.get('geo_alert_level','?')} ({directive.get('geo_score','?')})
Cash: {state['cash_eur']:.0f}EUR ({cash_pct:.1f}%)

═══ PORTFOLIO ═══
Open Positions: {len(state['open_positions'])}
{open_pos_str}

═══ DEINE LETZTEN ENTSCHEIDUNGEN (mit Outcomes wo bekannt) ═══
{memory_str}

═══ AKKUMULIERTE LESSONS ═══
{lessons_str}

═══ PROPOSALS ZU ENTSCHEIDEN ═══
{proposals_str}

═══ AUFGABE ═══
Pro Proposal: bull_case (1 Satz), bear_case (1 Satz), decision (EXECUTE|SKIP|WATCH),
confidence (0.0-1.0), expected_outcome_pct (Best-Schätzung in 14d %).

Confidence < 0.5 → WATCH (zu unsicher).
Beziehe Memory + Lessons explizit ein wenn relevant.

ANTWORT-FORMAT — STRIKT JSON:
{{
  "market_assessment": "1-2 Sätze über aktuelle Lage",
  "portfolio_assessment": "1-2 Sätze über Portfolio-Risk",
  "decisions": [
    {{
      "index": 1, "ticker": "...",
      "bull_case": "...",
      "bear_case": "...",
      "decision": "EXECUTE|SKIP|WATCH",
      "confidence": 0.72,
      "expected_outcome_pct": 8.5,
      "reasoning": "1-2 Sätze warum diese Decision",
      "memory_reference": "z.B. 'siehe Lesson XY' oder leer"
    }}
  ]
}}"""


# ═══════════════════════════════════════════════════════════════════════════
# 32e — Multi-Agent (Bull / Bear / Risk → CEO Synthesizer)
# ═══════════════════════════════════════════════════════════════════════════

def run_persona(state: dict, proposals: list[dict],
                memory: list[dict], lessons: list[dict],
                tool_data: dict, persona: str) -> str:
    """Single LLM-Call mit persona-spezifischem Prompt."""
    prompt = build_smart_prompt(state, proposals, memory, lessons, tool_data, persona)
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=2500)
        return text or ''
    except Exception as e:
        print(f'[ceo_intel] persona {persona} error: {e}', file=sys.stderr)
        return ''


def synthesize_decisions_with_tools(state: dict, proposals: list[dict],
                                       memory: list[dict], lessons: list[dict]) -> list[dict]:
    """
    Phase 37: Tool-Loop-Variante. CEO bekommt Tools statt pre-computed bundle.
    LLM kann iterativ get_correlation, get_recent_news, web_search etc. aufrufen
    bis er final_decision liefert. Pydantic-validiert.
    """
    if not proposals:
        return []
    try:
        from ceo_tools import (
            get_tool_definitions_for_prompt, run_tool_loop,
            validate_decision, auto_pre_tool_calls,
        )
    except Exception as e:
        print(f'[ceo_intel] Tool-Loop nicht verfügbar ({e}) — fallback', file=sys.stderr)
        return []

    # Phase 37 Fix: pre-fetch wichtige Tools bevor LLM dran ist (damit es nicht
    # "ich brauche Daten" als Ausrede für fehlendes Schema nutzt)
    pre_tool_data = auto_pre_tool_calls(proposals)

    # Build initial prompt (slimmer than build_smart_prompt — Tools liefern Details)
    directive = state.get('directive', {})
    cash_pct = state['cash_eur'] / state['fund_value'] * 100 if state['fund_value'] else 0
    open_pos = '\n'.join(
        f"  · {p['ticker']} ({p['strategy']}) {p['position_eur']:.0f}EUR"
        for p in state.get('open_positions', [])
    ) or '  (keine)'

    proposals_str = ''
    for i, p in enumerate(proposals[:30], 1):
        proposals_str += (
            f"\n[{i}] {p.get('ticker','?')} | {p.get('strategy','?')} | "
            f"entry={p.get('entry_price','?')} stop={p.get('stop','?')} "
            f"target={p.get('target_1') or p.get('target','?')} | "
            f"thesis: {(p.get('thesis','') or '')[:120]}"
        )

    lessons_str = '\n'.join(f'  · {l.get("lesson","")[:200]}' for l in lessons[-8:]) \
                    or '  (keine)'

    # Calendar
    cal_block = ''
    try:
        from calendar_service import format_for_prompt as _cal
        cal_block = '\n' + _cal()
    except Exception:
        pass

    pre_data_str = json.dumps(pre_tool_data, default=str)[:3000]

    initial_prompt = f"""Du bist CEO-Brain (Smart-Mode mit Tools, Phase 37).
{cal_block}

═══ PORTFOLIO ═══
Mode: {directive.get('mode','?')} | VIX: {directive.get('vix','?')} | Geo: {directive.get('geo_alert_level','?')}
Cash: {state['cash_eur']:.0f}EUR ({cash_pct:.0f}%)
{open_pos}

═══ DEINE LESSONS (letzte) ═══
{lessons_str}

═══ PROPOSALS ZU ENTSCHEIDEN ═══{proposals_str}

═══ PRE-FETCHED CONTEXT (du hast diese Daten schon — du musst sie nicht abrufen) ═══
{pre_data_str}

{get_tool_definitions_for_prompt()}

═══ AUFGABE ═══
Pro Proposal: EXECUTE / SKIP / WATCH mit confidence (0.0-1.0).
Confidence < 0.5 → automatisch WATCH.

Du hast schon viel Pre-Data oben. Tools nur wenn DRINGEND (z.B. spezifische
Korrelation zwischen 2 Tickern fehlt, oder web_search bei Eilmeldung).

═══ COLD-START-REGEL (Phase 41b) ═══
Wenn 'strategy_stats' für eine Strategie cold_start=true zeigt (n<5 Trades),
ist FEHLENDE HISTORIE KEIN SKIP-GRUND. Verlasse dich dann auf:
  • Conviction-Score (technical+thesis+R:R+market)
  • Anti-Pattern-Check (falls vorhanden → ja, dann skippen)
  • Aktuelle Setup-Qualität (Stop unter Entry, gutes CRV, Sektor-OK)
Default bei Cold-Start ohne Anti-Pattern: WATCH bei conf<0.55, EXECUTE bei conf>=0.55.
Begründe NICHT mit "kein historisches Edge" — das ist bei Cold-Start zirkulär.

Du KANNST direkt mit final_decision antworten wenn Pre-Data ausreicht.
WICHTIG: STRIKT das Schema oben einhalten."""

    result = run_tool_loop(initial_prompt, max_iterations=6, model_hint='sonnet',
                            max_tokens=2500)

    if 'error' in result:
        print(f'[ceo_intel] Tool-Loop error: {result["error"]}', file=sys.stderr)
        return []

    final = result.get('final_decision', {})
    if not isinstance(final, dict):
        return []

    # Pydantic-validate
    is_valid, validated = validate_decision(final)
    if not is_valid:
        print(f'[ceo_intel] Pydantic validation failed: {validated}', file=sys.stderr)
        # Try to use raw anyway if it has decisions
        if 'decisions' in final:
            validated = final
        else:
            return []

    # Convert to expected format
    out = []
    if validated.get('market_assessment') or validated.get('portfolio_assessment'):
        out.append({
            '_meta': True,
            'market_assessment': validated.get('market_assessment', '')[:400],
            'portfolio_assessment': validated.get('portfolio_assessment', '')[:400],
            'tool_calls_used': validated.get('tool_calls_used', []),
            'tool_iterations': result.get('tool_calls_made', 0),
        })

    for idx, d in enumerate(validated.get('decisions', [])):
        if not isinstance(d, dict):
            continue
        # Find matching proposal
        tk = d.get('ticker')
        matched = next((p for p in proposals if p.get('ticker') == tk), None)
        if not matched:
            continue
        action = d.get('action', 'SKIP').upper()
        conf = float(d.get('confidence', 0.5))
        if action == 'EXECUTE' and conf < 0.5:
            action = 'WATCH'
        out.append({
            'ticker': tk,
            'strategy': matched.get('strategy', d.get('strategy')),
            'entry': float(matched.get('entry_price', 0)),
            'stop': float(matched.get('stop', 0)),
            'target': float(matched.get('target_1') or matched.get('target', 0)),
            'thesis': matched.get('thesis', ''),
            'action': action,
            'confidence': conf,
            'reason': d.get('reasoning', '')[:300],
            'bull_case': d.get('bull_case', '')[:200],
            'bear_case': d.get('bear_case', '')[:200],
            'expected_pct': float(d.get('expected_outcome_pct', 0)),
            'memory_ref': d.get('memory_reference', '')[:200],
            'source': 'tool_loop',
        })

    return out


def synthesize_decisions(state: dict, proposals: list[dict],
                          memory: list[dict], lessons: list[dict],
                          tool_data: dict, multi_agent: bool = True) -> list[dict]:
    """
    Returns parsed decisions. Bei multi_agent=True: 3 Personas + Synthesizer.
    Bei False: Single CEO-Call (default smart).
    """
    if not proposals:
        return []

    if not multi_agent:
        # Single-Pass smart prompt
        text = run_persona(state, proposals, memory, lessons, tool_data, 'ceo')
        return _parse_decisions(text, proposals)

    # Multi-Agent
    bull_text = run_persona(state, proposals, memory, lessons, tool_data, 'bull')
    bear_text = run_persona(state, proposals, memory, lessons, tool_data, 'bear')
    risk_text = run_persona(state, proposals, memory, lessons, tool_data, 'risk')

    # Synthesizer-Prompt
    synth_prompt = f"""Du bist CEO-SYNTHESIZER. Drei Berater haben sich pro Proposal geäußert:

═══ BULL-AGENT (pro EXECUTE) ═══
{bull_text[:3000]}

═══ BEAR-AGENT (contra EXECUTE) ═══
{bear_text[:3000]}

═══ RISK-AGENT (Portfolio-Effekt) ═══
{risk_text[:3000]}

Synthetisiere für jeden Proposal die finale Decision.
Confidence < 0.5 → WATCH. Beachte Risk-Agent's Portfolio-Bedenken besonders.

ANTWORT — STRIKT JSON wie zuvor:
{{"market_assessment":"...","portfolio_assessment":"...",
  "decisions":[{{"index":N,"ticker":"...","bull_case":"...","bear_case":"...",
                 "decision":"EXECUTE|SKIP|WATCH","confidence":0.X,
                 "expected_outcome_pct":N,"reasoning":"...",
                 "memory_reference":""}}]}}"""

    try:
        from core.llm_client import call_llm
        text, _ = call_llm(synth_prompt, model_hint='sonnet', max_tokens=2500)
        return _parse_decisions(text, proposals)
    except Exception as e:
        print(f'[ceo_intel] synthesizer error: {e}', file=sys.stderr)
        return []


def _parse_decisions(text: str, proposals: list[dict]) -> list[dict]:
    """JSON-Parse mit Confidence-Filter (>= 0.5 = action gilt, sonst WATCH)."""
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
    i, j = text.find('{'), text.rfind('}')
    if i < 0 or j < 0:
        return []
    try:
        data = json.loads(text[i:j+1])
        out = []
        for d in data.get('decisions', []):
            idx = d.get('index')
            if not isinstance(idx, int) or idx < 1 or idx > len(proposals):
                continue
            p = proposals[idx - 1]
            confidence = float(d.get('confidence', 0.5))
            action = (d.get('decision') or 'SKIP').upper()
            # Confidence-Filter
            if action == 'EXECUTE' and confidence < 0.5:
                action = 'WATCH'
            out.append({
                'ticker': p.get('ticker'),
                'strategy': p.get('strategy'),
                'entry': float(p.get('entry_price') or 0),
                'stop': float(p.get('stop') or 0),
                'target': float(p.get('target_1') or p.get('target') or 0),
                'thesis': p.get('thesis', ''),
                'action': action,
                'confidence': confidence,
                'reason': d.get('reasoning', '')[:300],
                'bull_case': d.get('bull_case', '')[:200],
                'bear_case': d.get('bear_case', '')[:200],
                'expected_pct': float(d.get('expected_outcome_pct', 0)),
                'memory_ref': d.get('memory_reference', '')[:200],
                'source': 'multi_agent_synth',
            })
        # Auch market+portfolio assessment global
        if data.get('market_assessment') or data.get('portfolio_assessment'):
            out.insert(0, {
                '_meta': True,
                'market_assessment': data.get('market_assessment', '')[:400],
                'portfolio_assessment': data.get('portfolio_assessment', '')[:400],
            })
        return out
    except Exception as e:
        print(f'[ceo_intel] parse error: {e}', file=sys.stderr)
        return []
