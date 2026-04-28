#!/usr/bin/env python3
"""
ceo_brain.py — Phase 28a: Zentrale autonome Trade-Entscheidung.

Läuft alle 30min im Trading-Fenster (10:00–22:00 CEST).
Statt 10 unabhängige Guards die jeweils blocken können, ist hier EINE
Stimme die alles sieht und entscheidet.

Mechanik:
  1. Sammelt Inputs:
     - Pending Proposals (data/proposals.json + pending_setups DB)
     - Open Positions + Cash
     - CEO Directive (mode, themes, max_positions)
     - Market State (VIX, Regime, Geo-Score)
     - Recent Performance (letzte 5 closed Trades)
     - Verdict-Map (deep_dive_verdicts.json)
     - Korrelations-Matrix Status
     - Sektor-Exposure aktuell

  2. Pro Proposal: ENTSCHEIDUNG via LLM (claude_cli) ODER Fallback-Rules:
       EXECUTE  — sofort ausführen
       SKIP     — heute nicht, Begründung
       WATCH    — gut aber Trigger noch nicht (lass im Pending)

  3. EXECUTE → ruft execute_paper_entry() (existierende Hard-Safety-Guards
     bleiben aktiv: Stop<Entry, Cash-Reserve, Position-Cap, FX-Sanity).
  4. SKIP    → Proposal als 'skipped' markieren mit reason in
     ceo_decisions.jsonl + skipped_reasons-Counter.
  5. WATCH   → Proposal bleibt pending, wird beim nächsten Run neu evaluiert.

  6. Decision-Log: data/ceo_decisions.jsonl (append-only)
  7. Daily Discord-Report 22:00: was hat CEO heute entschieden, warum,
     was hat funktioniert vs nicht.

LLM-Fallback (bei API-Outage):
  Regelbasiert + konservativ. EXECUTE nur wenn:
    - Verdict KAUFEN < 14d
    - CRV >= 2.0
    - Kein Currency-Mismatch
    - Sektor-Exposure < 25%
    - Keine 2+ offenen Trades in derselben Strategy
  Sonst: SKIP mit Begründung.

Hard-Safety (NIEMALS überschrieben — auch nicht von CEO-LLM):
  - Stop < Entry
  - Cash-Reserve > 10%
  - Position < 15% Fund
  - Hard Stop -8%
  - FX-Mismatch Block (Guard 0e)
  - Permanently blocked Strategies (DT1-5, AR-AGRA)
  - 24h Quarantäne nach Thesis-Kill
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
PROPOSALS_FILE  = WS / 'data' / 'proposals.json'
DIRECTIVE_FILE  = WS / 'data' / 'ceo_directive.json'
VERDICTS_FILE   = WS / 'data' / 'deep_dive_verdicts.json'
DECISIONS_LOG   = WS / 'data' / 'ceo_decisions.jsonl'

VERDICT_MAX_AGE_DAYS = 14
LLM_DECISION_TIMEOUT = 120  # Sekunden pro LLM-Call


# ─── Helpers ──────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _log_decision(entry: dict) -> None:
    """Append-only log."""
    try:
        DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry.setdefault('ts', _now_iso())
        with open(DECISIONS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'[ceo_brain] decision log error: {e}', file=sys.stderr)


# ─── Inputs sammeln ───────────────────────────────────────────────────────

def gather_inputs() -> dict:
    """Sammelt alle Daten die der CEO für seine Entscheidung braucht."""
    state = {
        'ts': _now_iso(),
        'proposals_pending': [],
        'open_positions': [],
        'cash_eur': 0.0,
        'fund_value': 25000,
        'directive': {},
        'verdicts': {},
        'recent_trades': [],
        'sector_exposure': {},
    }

    # 1. Proposals
    proposals = _load_json(PROPOSALS_FILE, [])
    if isinstance(proposals, dict) and 'proposals' in proposals:
        proposals = proposals['proposals']
    # Filter active proposals only
    active = [p for p in proposals if isinstance(p, dict)
              and p.get('status') in ('active', 'pending', None)]
    state['proposals_pending'] = active

    # 2. Open Positions + Cash
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        opens = c.execute("""
            SELECT ticker, strategy, entry_price, shares, stop_price, target_price,
                   entry_date, sector
            FROM paper_portfolio WHERE status='OPEN'
        """).fetchall()
        for r in opens:
            d = dict(r)
            d['position_eur'] = (d['entry_price'] or 0) * (d['shares'] or 0)
            state['open_positions'].append(d)

        cash_row = c.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash'"
        ).fetchone()
        if cash_row:
            state['cash_eur'] = float(cash_row[0])

        # Recent trades
        recent = c.execute("""
            SELECT ticker, strategy, pnl_eur, pnl_pct, exit_type,
                   COALESCE(close_date, entry_date) as date
            FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED')
            ORDER BY COALESCE(close_date, entry_date) DESC LIMIT 5
        """).fetchall()
        state['recent_trades'] = [dict(r) for r in recent]
        c.close()
    except Exception as e:
        print(f'[ceo_brain] DB error: {e}', file=sys.stderr)

    # 3. Directive
    state['directive'] = _load_json(DIRECTIVE_FILE, {})

    # 4. Verdicts
    state['verdicts'] = _load_json(VERDICTS_FILE, {})

    # 5. Sektor-Exposure
    try:
        from portfolio_risk import get_exposure_breakdown
        b = get_exposure_breakdown()
        state['sector_exposure'] = b.get('by_sector', {})
    except Exception:
        pass

    return state


# ─── LLM-basierte Entscheidung ────────────────────────────────────────────

def decide_llm(state: dict) -> list[dict]:
    """
    Phase 32: Smart-Mode mit Memory + Lessons + Multi-Agent.
    Returns: [{ticker, strategy, action, reason, confidence, ...}, ...]
    """
    proposals = state['proposals_pending']
    if not proposals:
        return []

    proposals = proposals[:30]

    # Phase 32+37: Lade Memory + Lessons (Tools werden on-demand vom LLM gerufen)
    try:
        from ceo_intelligence import (
            load_decision_memory, load_lessons,
            synthesize_decisions, synthesize_decisions_with_tools,
        )
    except Exception as e:
        print(f'[ceo_brain] Smart-Mode nicht verfuegbar ({e}) — fallback altes Prompt')
        return _decide_legacy(state, proposals)

    memory = load_decision_memory(n=20)
    lessons = load_lessons(max_age_days=60, limit=30)

    # Phase 37: Versuche Tool-Loop zuerst
    decisions = synthesize_decisions_with_tools(state, proposals, memory, lessons)
    if decisions:
        print(f'[ceo_brain] Tool-Loop OK ({len(decisions)} decisions)')
    else:
        # Fallback Multi-Agent (Phase 32e)
        from ceo_intelligence import gather_tool_data
        tickers = [p.get('ticker', '') for p in proposals]
        tool_data = gather_tool_data(tickers)
        use_multi = len(proposals) >= 3
        decisions = synthesize_decisions(
            state, proposals, memory, lessons, tool_data,
            multi_agent=use_multi,
        )
        print(f'[ceo_brain] Tool-Loop empty → Multi-Agent fallback ({len(decisions)} decisions)')

    # Phase 33+38b: Consciousness + Pattern-Enforcement-Layer
    try:
        from ceo_consciousness import (
            adjust_confidence, select_optimal_subset, detect_mood,
        )
        # Phase 38b: Pattern-Enforcement (Anti-Pattern Hard-Block + Heatmap-Sizing)
        from ceo_pattern_learning import (
            check_proposal_against_patterns, get_hour_multiplier,
        )

        # 33a: Calibration auf jede Decision anwenden
        for d in decisions:
            if d.get('_meta'):
                continue
            raw_conf = d.get('confidence', 0.5)
            d['confidence'] = adjust_confidence(raw_conf)
            d['_raw_confidence'] = raw_conf

            # Phase 43 Pillar B: Confidence-Boosts für High-Quality-Triggers
            boosts = []
            try:
                # Boost 1: aktives Macro-Event letzte 6h (HIGH/CRITICAL severity)
                import sqlite3 as _sql
                _conn = _sql.connect(str(DB))
                cnt = _conn.execute(
                    "SELECT COUNT(*) FROM macro_events "
                    "WHERE detected_at >= datetime('now','-6 hours') "
                    "AND severity >= 0.9"
                ).fetchone()[0]
                _conn.close()
                if cnt > 0:
                    d['confidence'] = min(0.99, d['confidence'] + 0.10)
                    boosts.append(f'macro+0.10 (n={cnt})')
            except Exception:
                pass
            try:
                # Boost 2: Cold-Start ohne Anti-Pattern (strategy n_trades < 5)
                _strat = d.get('strategy', '')
                from ceo_tools import _strategy_n_trades
                _stats = _strategy_n_trades(_strat)
                if _stats['cold_start'] and not d.get('_pattern_matches'):
                    d['confidence'] = min(0.99, d['confidence'] + 0.05)
                    boosts.append(f'cold-start+0.05 (n={_stats["n_trades"]})')
            except Exception:
                pass
            try:
                # Boost 3: Strategy hat aktuell positive expectancy + n>=5
                from ceo_tools import _strategy_n_trades as _ns
                _strat = d.get('strategy', '')
                _stats = _ns(_strat)
                if not _stats['cold_start']:
                    _wr = _stats.get('win_rate') or 0
                    if _wr >= 60:
                        d['confidence'] = min(0.99, d['confidence'] + 0.05)
                        boosts.append(f'high-WR+0.05 ({_wr}%)')
            except Exception:
                pass
            if boosts:
                d['_conf_boosts'] = boosts
                d['reason'] = (d.get('reason', '') + f' | boosts: {", ".join(boosts)}')

            # Re-apply confidence-filter (jetzt nach Boosts)
            if d.get('action') == 'EXECUTE' and d['confidence'] < 0.5:
                d['action'] = 'WATCH'
                d['reason'] = (d.get('reason', '') +
                               f' | DEMOTED: calibrated conf {d["confidence"]} < 0.5')

            # Phase 43 Pillar B: PROMOTE WATCH→EXECUTE wenn nach Boost stark genug
            if (d.get('action') == 'WATCH' and d['confidence'] >= 0.55
                    and not d.get('_pattern_blocked')
                    and not d.get('_lifecycle_blocked')):
                d['action'] = 'EXECUTE'
                d['reason'] = (d.get('reason', '') +
                               f' | PROMOTED WATCH→EXECUTE: conf {d["confidence"]:.2f} >= 0.55 (Phase 43b)')
                d['_promoted'] = True

            # === Phase 38b: Anti-Pattern Hard-Enforcement ===
            try:
                proposal_for_check = {
                    'strategy': d.get('strategy'),
                    'sector': d.get('sector', ''),
                }
                pattern_matches = check_proposal_against_patterns(proposal_for_check)
                d['_pattern_matches'] = pattern_matches
                if pattern_matches and d.get('action') == 'EXECUTE':
                    has_critical = any(p.get('severity') == 'critical' for p in pattern_matches)
                    if has_critical:
                        d['action'] = 'WATCH'
                        d['reason'] = (d.get('reason', '') +
                                      f' | ANTI-PATTERN BLOCK: {len(pattern_matches)} critical match(es)')
                        d['_pattern_blocked'] = True
                    else:
                        # Warning-Pattern → confidence reduzieren
                        d['confidence'] = max(0, d['confidence'] - 0.15)
                        d['reason'] = (d.get('reason', '') +
                                      f' | conf -0.15 wegen anti-pattern warning')
                        if d['confidence'] < 0.5:
                            d['action'] = 'WATCH'
            except Exception as _pe:
                print(f'[pattern-enforce] error: {_pe}', file=sys.stderr)

            # === Phase 38b: Heatmap-basiertes Sizing ===
            try:
                hour_mult = get_hour_multiplier(d.get('strategy', ''))
                # Combined mit existing _mood_multiplier
                existing = d.get('_mood_multiplier', 1.0)
                combined = existing * hour_mult.get('multiplier', 1.0)
                d['_hour_multiplier'] = hour_mult.get('multiplier', 1.0)
                d['_mood_multiplier'] = combined
                if hour_mult.get('multiplier', 1.0) != 1.0:
                    d['reason'] = (d.get('reason', '') +
                                  f' | heatmap: {hour_mult["reason"]} → ×{hour_mult["multiplier"]}')
            except Exception as _he:
                print(f'[heatmap-sizing] error: {_he}', file=sys.stderr)

            # === Phase 39: Strategy-Lifecycle (Probation/Suspended-Check) ===
            try:
                from strategy_lifecycle import get_size_multiplier as _lc_mult
                lc_mult = _lc_mult(d.get('strategy', ''))
                if lc_mult == 0.0:
                    # SUSPENDED oder RETIRED → Hard-Block
                    d['action'] = 'WATCH'
                    d['reason'] = (d.get('reason', '') +
                                  f' | LIFECYCLE BLOCK: strategy in SUSPENDED/RETIRED')
                    d['_lifecycle_blocked'] = True
                elif lc_mult < 1.0:
                    # PROBATION → Halbierte Größe
                    existing = d.get('_mood_multiplier', 1.0)
                    d['_mood_multiplier'] = existing * lc_mult
                    d['_lifecycle_multiplier'] = lc_mult
                    d['reason'] = (d.get('reason', '') +
                                  f' | PROBATION × {lc_mult}')
            except Exception as _lce:
                print(f'[lifecycle-sizing] error: {_lce}', file=sys.stderr)

        # 33e: Mood-Multiplier auf alle EXECUTE
        mood = detect_mood(window_trades=10)
        if mood.get('mood') in ('tilt', 'caution'):
            for d in decisions:
                if d.get('action') == 'EXECUTE':
                    existing = d.get('_mood_multiplier', 1.0)
                    d['_mood_multiplier'] = existing * mood['size_multiplier']
                    d['reason'] = (d.get('reason', '') +
                                  f' | mood={mood["mood"]} → ×{mood["size_multiplier"]}')

        # 33b: Portfolio-Level Selection (nur Top-N gleichzeitig)
        cash = state.get('cash_eur', 0)
        decisions = select_optimal_subset(
            decisions, cash_available=cash, max_positions=3,
        )
    except Exception as e:
        print(f'[ceo_brain] Consciousness layer error: {e}', file=sys.stderr)

    # _meta-Eintrag rausfiltern für return
    meta_entries = [d for d in decisions if d.get('_meta')]
    real_decisions = [d for d in decisions if not d.get('_meta')]

    if meta_entries:
        m = meta_entries[0]
        print(f'[ceo_brain] Market: {m.get("market_assessment","")[:150]}')
        print(f'[ceo_brain] Portfolio: {m.get("portfolio_assessment","")[:150]}')

    if not real_decisions:
        print('[ceo_brain] Smart-Decisions leer — fallback Rules')
        return decide_rules(state)

    return real_decisions


def _decide_legacy(state: dict, proposals: list[dict]) -> list[dict]:
    """Alter prompt-flow als notfall fallback."""
    prompt = _build_prompt(state, proposals)
    try:
        from core.llm_client import call_llm
        text, _usage = call_llm(prompt, model_hint='sonnet', max_tokens=3000)
    except Exception as e:
        print(f'[ceo_brain] legacy LLM error: {e} — Rules fallback')
        return decide_rules(state)
    decisions = _parse_llm_response(text, proposals)
    return decisions or decide_rules(state)


def _build_prompt(state: dict, proposals: list[dict]) -> str:
    directive = state['directive']
    cash_pct = state['cash_eur'] / state['fund_value'] * 100 if state['fund_value'] else 0

    open_pos_str = '\n'.join(
        f"  · {p['ticker']} ({p['strategy']}) {p['position_eur']:.0f}EUR seit {str(p['entry_date'])[:10]}"
        for p in state['open_positions']
    ) or '  (keine)'

    sector_str = '\n'.join(
        f"  · {sec}: {data.get('eur', 0):.0f}EUR ({data.get('pct', 0)*100:.0f}%)"
        for sec, data in state['sector_exposure'].items()
    ) or '  (leer)'

    recent_str = '\n'.join(
        f"  · {t['ticker']} ({t['strategy']}) {t['pnl_eur']:+.0f}EUR"
        for t in state['recent_trades']
    ) or '  (keine)'

    verdicts_summary = {
        k: v.get('verdict') if isinstance(v, dict) else v
        for k, v in (state['verdicts'] or {}).items()
        if isinstance(v, dict)
    }

    proposals_str = ''
    for i, p in enumerate(proposals, 1):
        tk = p.get('ticker', '?')
        verdict = verdicts_summary.get(tk, '?')
        proposals_str += (
            f"\n[{i}] {tk} | {p.get('strategy','?')} | "
            f"entry={p.get('entry_price','?')} stop={p.get('stop','?')} "
            f"target={p.get('target_1') or p.get('target','?')} | "
            f"verdict={verdict} | thesis: {(p.get('thesis','') or '')[:120]}"
        )

    return f"""Du bist Albert, autonomer CEO eines Paper-Trading-Bots (TradeMind).
Du musst pro Proposal entscheiden: EXECUTE / SKIP / WATCH.

═══ AKTUELLER STATE ═══
Mode: {directive.get('mode','?')} | Regime: {directive.get('regime','?')} | VIX: {directive.get('vix','?')}
Geo-Alert: {directive.get('geo_alert_level','?')} (Score {directive.get('geo_score','?')})
Cash: {state['cash_eur']:.0f}EUR ({cash_pct:.1f}% vom Fund)
Open Positions: {len(state['open_positions'])} (max sinnvoll ~6-8)
{open_pos_str}

Sektor-Exposure:
{sector_str}

Letzte 5 Trades:
{recent_str}

═══ PROPOSALS ZU ENTSCHEIDEN ({len(proposals)}) ═══
{proposals_str}

═══ ENTSCHEIDUNGSREGELN ═══
• EXECUTE: KAUFEN-Verdict < 14d, CRV >= 2.0, Sektor < 25%, kein Duplikat zur Strategie offen
• SKIP: WARTEN/NICHT_KAUFEN-Verdict, oder Sektor-Cluster-Risiko, oder Cash zu knapp (<15%)
• WATCH: gutes Setup aber Markt nicht-ideal (z.B. RSI > 85, Falling Knife, Mode DEFENSIVE bei nicht-Thesis)
• Mode DEFENSIVE: nur PS_*/PT-Strategien EXECUTE, sonst SKIP
• Mode BULLISH: liberaler, auch PM/Setups
• Wenn 5+ Open Positions schon: nur EXECUTE wenn Setup deutlich überlegen
• COLD-START (Phase 41b): Strategien mit <5 historischen Trades NICHT mit "kein Edge" skippen.
  Falls Setup technisch ok + kein Anti-Pattern: EXECUTE wenn Verdict frisch, sonst WATCH.

ANTWORT-FORMAT — STRIKT JSON, SONST NICHTS:
{{
  "decisions": [
    {{"index": 1, "ticker": "...", "action": "EXECUTE|SKIP|WATCH", "reason": "1-2 Sätze"}},
    ...
  ]
}}"""


def _parse_llm_response(text: str, proposals: list[dict]) -> list[dict]:
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
            out.append({
                'ticker': p.get('ticker'),
                'strategy': p.get('strategy'),
                'entry': float(p.get('entry_price') or 0),
                'stop': float(p.get('stop') or 0),
                'target': float(p.get('target_1') or p.get('target') or 0),
                'thesis': p.get('thesis', ''),
                'action': (d.get('action') or 'SKIP').upper(),
                'reason': (d.get('reason') or '')[:300],
                'source': 'llm',
            })
        return out
    except Exception as e:
        print(f'[ceo_brain] parse error: {e}', file=sys.stderr)
        return []


# ─── Regel-basierte Fallback-Entscheidung ─────────────────────────────────

def decide_rules(state: dict) -> list[dict]:
    """Konservativer Rule-Engine wenn LLM nicht verfügbar."""
    decisions = []
    open_strategies = {p['strategy'] for p in state['open_positions']}
    cash_pct = state['cash_eur'] / state['fund_value'] if state['fund_value'] else 0
    mode = (state['directive'] or {}).get('mode', 'NEUTRAL')

    for p in state['proposals_pending'][:30]:
        ticker = p.get('ticker', '')
        strategy = p.get('strategy', '')
        entry = float(p.get('entry_price') or 0)
        stop = float(p.get('stop') or 0)
        target = float(p.get('target_1') or p.get('target') or 0)

        # Verdict check
        v = state['verdicts'].get(ticker, {})
        verdict = (v.get('verdict') if isinstance(v, dict) else v) or '?'
        v_date = v.get('date', '') if isinstance(v, dict) else ''
        try:
            v_age = (datetime.now() - datetime.fromisoformat(v_date[:19])).days
        except Exception:
            v_age = 999

        # Decisions
        action = 'SKIP'
        reason = ''

        if verdict in ('NICHT_KAUFEN', 'VERKAUFEN_GESTAFFELT'):
            action, reason = 'SKIP', f'Verdict {verdict}'
        elif verdict == 'WARTEN':
            action, reason = 'WATCH', 'Verdict WARTEN — re-evaluate later'
        elif v_age > VERDICT_MAX_AGE_DAYS:
            action, reason = 'WATCH', f'Verdict zu alt ({v_age}d > {VERDICT_MAX_AGE_DAYS})'
        elif strategy in open_strategies:
            action, reason = 'SKIP', f'Strategy {strategy} bereits OPEN'
        elif cash_pct < 0.15:
            action, reason = 'SKIP', f'Cash zu knapp ({cash_pct*100:.0f}% < 15%)'
        elif entry <= 0 or stop <= 0 or stop >= entry:
            action, reason = 'SKIP', 'Invalid prices (stop>=entry)'
        elif (target - entry) / max(entry - stop, 0.01) < 2.0:
            action, reason = 'SKIP', f'CRV < 2.0'
        elif mode == 'DEFENSIVE' and not strategy.startswith(('PS_', 'PT')):
            action, reason = 'SKIP', f'DEFENSIVE-Mode: nur PS_/PT, kein {strategy}'
        elif verdict == 'KAUFEN':
            action, reason = 'EXECUTE', f'KAUFEN-Verdict ({v_age}d alt), CRV ok'
        else:
            action, reason = 'SKIP', f'No green light (verdict={verdict})'

        decisions.append({
            'ticker': ticker, 'strategy': strategy,
            'entry': entry, 'stop': stop, 'target': target,
            'thesis': p.get('thesis', ''),
            'action': action, 'reason': reason,
            'source': 'rules',
        })
    return decisions


# ─── Ausführen ────────────────────────────────────────────────────────────

def _update_proposal_status(ticker: str, strategy: str, new_status: str,
                             extra: dict | None = None) -> None:
    """Phase 43 Pillar A: Lifecycle. Setzt Proposal-Status.
    pending → watching | rejected | executed | expired
    """
    if not PROPOSALS_FILE.exists():
        return
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            meta = {k: v for k, v in data.items() if k != 'proposals'}
            props = data.get('proposals', [])
        else:
            meta = {}
            props = data if isinstance(data, list) else []
        now = datetime.now(timezone.utc).isoformat()
        updated = 0
        for p in props:
            if not isinstance(p, dict):
                continue
            if (p.get('ticker') == ticker and p.get('strategy') == strategy
                    and p.get('status') in ('pending', 'active', None)):
                p['status'] = new_status
                p['status_changed_at'] = now
                p.setdefault('decision_history', []).append({
                    'ts': now, 'new_status': new_status,
                    **({k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float, bool))})
                })
                updated += 1
        if updated:
            out = {**meta, 'proposals': props} if meta else props
            PROPOSALS_FILE.write_text(
                json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8'
            )
    except Exception as e:
        print(f'[lifecycle] update_proposal_status err: {e}', file=sys.stderr)


def execute_decisions(decisions: list[dict]) -> dict:
    """Setzt EXECUTE-Entscheidungen um. Hard-Safety-Guards bleiben aktiv.
    Phase 43 Pillar A: nach Decision wird Proposal-Status aktualisiert
    (pending → watching/rejected/executed) damit kein DECIDING-Loop entsteht."""
    summary = {'execute': 0, 'skip': 0, 'watch': 0, 'failed': 0,
               'success': 0, 'blocked_by': {}}

    for d in decisions:
        action = d['action']
        ticker = d.get('ticker', '')
        strategy = d.get('strategy', '')
        if action == 'WATCH':
            summary['watch'] += 1
            _log_decision({**d, 'event': 'watch'})
            # Phase 43 Pillar A: WATCH → Proposal-Status auf "watching"
            _update_proposal_status(ticker, strategy, 'watching',
                                     {'confidence': d.get('confidence'),
                                      'reason': str(d.get('reason', ''))[:120]})
            continue
        if action == 'SKIP':
            summary['skip'] += 1
            _log_decision({**d, 'event': 'skip'})
            _update_proposal_status(ticker, strategy, 'rejected',
                                     {'confidence': d.get('confidence'),
                                      'reason': str(d.get('reason', ''))[:120]})
            continue
        if action != 'EXECUTE':
            summary['failed'] += 1
            continue

        # EXECUTE
        summary['execute'] += 1
        try:
            from execution.paper_trade_engine import execute_paper_entry
            # Phase 33e: Mood-Multiplier wirkt sich aufs Sizing aus.
            # Wir können via thesis-string Hinweis weitergeben, paper_trade_engine
            # könnte ihn lesen. Für jetzt: Multiplier-Info in thesis loggen.
            mood_mult = d.get('_mood_multiplier', 1.0)
            mood_str = f' | mood_size_mult={mood_mult}' if mood_mult != 1.0 else ''
            result = execute_paper_entry(
                ticker=d['ticker'],
                strategy=d['strategy'],
                entry_price=d['entry'],
                stop_price=d['stop'],
                target_price=d['target'],
                thesis=f'[CEO-Brain] conf={d.get("confidence",0):.2f}{mood_str} | '
                       f'{d.get("reason","")[:150]} | {d.get("thesis","")[:150]}',
                source='ceo_brain',
            )
            success = bool(result.get('success'))
            if success:
                summary['success'] += 1
            else:
                summary['failed'] += 1
                blocker = result.get('blocked_by', 'unknown')
                summary['blocked_by'][blocker] = summary['blocked_by'].get(blocker, 0) + 1
            _log_decision({
                **d, 'event': 'execute',
                'success': success, 'trade_id': result.get('trade_id'),
                'message': (result.get('message') or '')[:300],
                'blocked_by': result.get('blocked_by'),
            })
            # Phase 43 Pillar A: EXECUTE → 'executed' oder 'execute_blocked'
            new_status = 'executed' if success else 'execute_blocked'
            _update_proposal_status(ticker, strategy, new_status,
                                     {'success': success,
                                      'blocked_by': str(result.get('blocked_by') or ''),
                                      'trade_id': result.get('trade_id')})
        except Exception as e:
            summary['failed'] += 1
            print(f'[ceo_brain] execute crashed for {d["ticker"]}: {e}', file=sys.stderr)
            _log_decision({**d, 'event': 'crash', 'error': str(e)[:200]})

    return summary


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print(f'─── CEO-Brain Run @ {_now_iso()} ───')
    started = datetime.now()

    state = gather_inputs()
    n_pending = len(state['proposals_pending'])
    print(f'Inputs: {n_pending} pending, {len(state["open_positions"])} open, '
          f'cash {state["cash_eur"]:.0f}EUR, mode {state["directive"].get("mode","?")}')

    if n_pending == 0:
        # Phase 43: Active CEO — bei 0 Proposals nicht mehr exit, sondern hunten.
        print('Keine pending Proposals — Active-Hunter starten...')
        try:
            from ceo_active_hunter import hunt_for_setups
            r = hunt_for_setups(max_new=3)
            print(f'  Hunter: {r["setups_proposed"]} setups, '
                  f'{r["proposals_written"]} written ({r.get("thinking", "")[:120]})')
            # Re-load state mit neuen Proposals
            state = gather_inputs()
            n_pending = len(state['proposals_pending'])
            if n_pending == 0:
                print('  Hunter brachte keine neuen Setups — fertig.')
                return 0
            print(f'  Hunter brachte {n_pending} neue Proposals → weiter mit decide.')
        except Exception as e:
            print(f'  Hunter failed: {e} — exit.', file=sys.stderr)
            return 0

    # Try LLM first, fallback to rules
    # Phase 29: Health-Monitor setzt .llm_fallback_active wenn LLM down
    _fallback_flag = WS / 'data' / '.llm_fallback_active'
    if _fallback_flag.exists():
        # Wenn Flag älter als 60min → ignorieren (LLM könnte wieder laufen)
        try:
            _age_min = (datetime.now().timestamp() - _fallback_flag.stat().st_mtime) / 60
            if _age_min > 60:
                _fallback_flag.unlink()
                print(f'[ceo_brain] LLM-Fallback-Flag {_age_min:.0f}min alt → entfernt')
            else:
                print(f'[ceo_brain] LLM-Fallback aktiv (Health-Monitor) → Rules')
                decisions = decide_rules(state)
                summary = execute_decisions(decisions)
                print(f'\nRules-Mode Summary: {summary}')
                return 0
        except Exception:
            pass

    try:
        decisions = decide_llm(state)
        if decisions:
            print(f'LLM-Entscheidung: {len(decisions)} decisions')
        else:
            decisions = decide_rules(state)
            print(f'Fallback Rules: {len(decisions)} decisions')
    except Exception as e:
        print(f'Decide failed: {e} — Rules fallback')
        decisions = decide_rules(state)

    summary = execute_decisions(decisions)
    elapsed = (datetime.now() - started).total_seconds()

    print(f'\n=== Summary ({elapsed:.1f}s) ===')
    print(f'  EXECUTE attempted: {summary["execute"]}')
    print(f'    ✅ Success:      {summary["success"]}')
    print(f'    ❌ Blocked:      {summary["failed"]}')
    if summary['blocked_by']:
        for k, v in summary['blocked_by'].items():
            print(f'         {k}: {v}x')
    print(f'  SKIP:              {summary["skip"]}')
    print(f'  WATCH:             {summary["watch"]}')

    # Daily Discord-Push (only one time per day, around 22:00)
    if datetime.now().hour == 22 and datetime.now().minute < 30:
        try:
            from discord_dispatcher import send_alert, TIER_MEDIUM
            msg = (
                f'🧠 **CEO-Brain Daily Report**\n'
                f'Pending: {n_pending} | Open: {len(state["open_positions"])} | '
                f'Cash: {state["cash_eur"]:.0f}€\n'
                f'Heute: ✅ {summary["success"]} executed, ❌ {summary["failed"]} blocked, '
                f'⏸ {summary["skip"]} skipped, 👀 {summary["watch"]} watching\n'
                f'Mode: {state["directive"].get("mode","?")} | '
                f'VIX: {state["directive"].get("vix","?")} | '
                f'Geo: {state["directive"].get("geo_alert_level","?")}'
            )
            send_alert(msg, tier=TIER_MEDIUM, category='ceo_brain_daily',
                       dedupe_key=f'ceo_brain_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f'[ceo_brain] FATAL: {e}', file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
