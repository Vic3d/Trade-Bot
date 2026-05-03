#!/usr/bin/env python3
"""
ceo_active_loop.py — Phase 44ad: Albert arbeitet kontinuierlich (alle 10min).

User-Direktive (Victor 03.05): 'CEO soll immer arbeiten, nicht zu festen Zeiten.'

Statt 1x/Tag Capability-Audit + 1x/Tag Action-Log: Mini-Cycle alle 10min.
Albert wacht alle 10min auf, macht eine kleine Reflexion + Aktion, schlaeft
wieder ein. Diskret aber 144x/Tag = Pseudo-Continuous.

Pro Cycle:
1. Truth-Refresh (current_truth)
2. Halluzinations-Quick-Scan (letzte LLM-Outputs der letzten 60min)
3. Mini-Decision: was hat sich seit letztem Cycle geaendert?
   - Neue News? -> news-reactor-trigger fuer offene positions
   - Position-Move? -> already triggered by price_monitor
   - Strategy-Anomalie? -> log
4. Diskrete Output:
   - data/ceo_active_loop.jsonl (Audit)
   - SILENT-Discord (in ceo_inbox, nicht im Channel)
   - Bei HIGH-Severity: Discord-Push (CRITICAL-Whitelist)

Costs: ~144 LLM-Calls/Tag bei 10min Frequenz. Sonnet ~$2-3/Tag.

Run: python3 scripts/ceo_active_loop.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'ceo_active_loop.jsonl'
LAST_STATE = WS / 'data' / 'ceo_active_loop_state.json'


SYSTEM = """Du bist Albert. Du arbeitest 24/7. Mini-Cycle: alle 10min wachst du
kurz auf, schaust was sich geaendert hat, machst eine Mini-Aktion oder eine
Mini-Notiz.

Sei knapp. Max 5 Saetze pro Antwort. Format als JSON:
{
  "observation": "was hat sich seit letztem Cycle geaendert (1-2 Saetze)",
  "action": "was du jetzt tust (kann auch 'nichts, alles ruhig' sein)",
  "severity": "low|med|high",
  "concerns": ["max 3 spezifische Concerns die du JETZT siehst"]
}

Severity-Regeln:
- LOW: alles ruhig, Routine-Beobachtung
- MED: etwas auffaellig (Move > 1%, neue News, Anomalie)
- HIGH: Position-Risk, These-Bruch, System-Bug

REGEL: keine Halluzinationen. Wenn du eine Position erwaehnst MUSS sie im
verbindlichen Truth-Header oben stehen. Sonst: 'unbekannt' / generisch."""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if LAST_STATE.exists():
        try: return json.loads(LAST_STATE.read_text(encoding='utf-8'))
        except Exception: pass
    return {'last_run': None, 'cumulative_runs': 0,
            'last_open_positions': [], 'last_news_count': 0}


def _save_state(s: dict) -> None:
    LAST_STATE.parent.mkdir(parents=True, exist_ok=True)
    LAST_STATE.write_text(json.dumps(s, indent=2), encoding='utf-8')


def _gather_delta(state: dict) -> dict:
    """Was hat sich seit letztem Run geaendert? (DB-basiert, kein LLM)"""
    delta = {}
    if not DB.exists(): return delta

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Open positions vs last run
    opens = c.execute(
        "SELECT id, ticker, strategy, entry_price, stop_price FROM paper_portfolio "
        "WHERE status='OPEN'"
    ).fetchall()
    current_open_ids = sorted([r['id'] for r in opens])
    last_open_ids = sorted(state.get('last_open_positions', []))
    delta['positions_changed'] = current_open_ids != last_open_ids
    delta['open_positions'] = [dict(r) for r in opens]

    # News-Count letzte 10min
    try:
        n_news = c.execute(
            "SELECT COUNT(*) FROM news_events WHERE created_at >= datetime('now','-10 minutes')"
        ).fetchone()[0]
        delta['news_last_10min'] = n_news
    except Exception:
        delta['news_last_10min'] = 0

    # Macro-Events letzte 10min
    try:
        n_macro = c.execute(
            "SELECT COUNT(*) FROM macro_events WHERE detected_at >= datetime('now','-10 minutes')"
        ).fetchone()[0]
        delta['macro_last_10min'] = n_macro
    except Exception:
        delta['macro_last_10min'] = 0

    c.close()
    return delta


def run() -> dict:
    state = _load_state()
    delta = _gather_delta(state)

    # Wenn nichts passiert + nicht erste run + keine alarms → SKIP LLM (cost saving)
    no_change = (not delta.get('positions_changed') and
                 delta.get('news_last_10min', 0) == 0 and
                 delta.get('macro_last_10min', 0) == 0)
    if no_change and state.get('last_run'):
        # Nur cycle-counter erhoehen, kein LLM
        state['last_run'] = _now()
        state['cumulative_runs'] = state.get('cumulative_runs', 0) + 1
        state['last_open_positions'] = sorted([p['id'] for p in delta.get('open_positions', [])])
        _save_state(state)
        return {'ts': _now(), 'note': 'no_change_skip_llm',
                'cycle': state['cumulative_runs']}

    # Es gibt was zu denken → LLM-Mini-Cycle
    prompt = (
        f"Letzter Cycle: {state.get('last_run','(erster Run)')}\n"
        f"Aktueller Cycle: #{state.get('cumulative_runs',0)+1}\n\n"
        f"Delta seit letztem Run:\n{json.dumps(delta, indent=2, default=str, ensure_ascii=False)[:2500]}\n\n"
        f"Mini-Cycle: was beobachtest du, was tust du JETZT?"
    )

    obs = {}
    try:
        from core.llm_client import call_llm
        text, usage = call_llm(prompt, model_hint='sonnet', max_tokens=400,
                                system=SYSTEM, audit_context='active_loop')
        import re
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            obs = json.loads(m.group(0))
        obs['_audit'] = usage.get('fact_audit', {})
    except Exception as e:
        obs = {'observation': f'LLM-fail: {e}', 'action': 'skip',
                'severity': 'low', 'concerns': []}

    # Persist
    state['last_run'] = _now()
    state['cumulative_runs'] = state.get('cumulative_runs', 0) + 1
    state['last_open_positions'] = sorted([p['id'] for p in delta.get('open_positions', [])])
    _save_state(state)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), 'cycle': state['cumulative_runs'],
                              'delta': {k: v for k, v in delta.items()
                                        if k != 'open_positions'},  # zu lang
                              'obs': obs}, ensure_ascii=False) + '\n')

    # Discord nur bei HIGH-Severity (CRITICAL-Whitelist)
    if obs.get('severity') == 'high':
        try:
            from discord_dispatcher import send_alert, TIER_HIGH
            msg = (f"🤖 **CEO-Loop #{state['cumulative_runs']}** ({obs['severity'].upper()})\n"
                   f"👁 {obs.get('observation','')}\n"
                   f"⚡ {obs.get('action','')}\n"
                   + (f"⚠️ Concerns: {', '.join(obs.get('concerns',[])[:3])}"
                      if obs.get('concerns') else ''))
            send_alert(msg[:1900], tier=TIER_HIGH, category='crash_safety',
                        dedupe_key=f"ceo_loop_high_{datetime.now().strftime('%Y%m%d_%H')}")
        except Exception: pass

    return {'ts': _now(), 'cycle': state['cumulative_runs'],
            'severity': obs.get('severity'), 'action': obs.get('action','')[:80]}


def main() -> int:
    r = run()
    print(f'CEO-Loop #{r.get("cycle","?")} @ {r["ts"][:16]}: '
          f'sev={r.get("severity","?")} action={r.get("action","")[:80]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
