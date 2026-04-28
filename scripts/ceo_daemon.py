#!/usr/bin/env python3
"""
ceo_daemon.py — Phase 43 Pillar 1: Active CEO als Long-Running Daemon.

Statt 30min-Cron läuft Albert kontinuierlich mit State-Machine.

States:
  IDLE        — wartet auf nächsten Wake-Cycle
  RECONNAIS   — pre-market: P&L review, news scan, position health
  HUNTING     — keine Proposals → ceo_active_hunter aufrufen
  DECIDING    — pending Proposals → ceo_brain.decide_llm
  EXECUTING   — Decisions → paper_trade_engine
  MONITORING  — alle Open-Positions stress-testen
  REFLECTING  — EOD: Reflection + Lessons schreiben

Wake-Cycle:
  Marktstunden (CET 09-22) Mo-Fr: alle 5min
  Off-hours: alle 30min
  Event-Triggered: Macro-Event-Push weckt sofort

Usage:
  python3 scripts/ceo_daemon.py                # foreground
  python3 scripts/ceo_daemon.py --once         # single cycle, dann exit
  python3 scripts/ceo_daemon.py --state HUNTING --once  # specific state, single cycle
  systemctl start trademind-ceo-daemon         # production
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
PROPOSALS_FILE  = WS / 'data' / 'proposals.json'
DAEMON_STATE    = WS / 'data' / 'ceo_daemon_state.json'
HEARTBEAT_FILE  = WS / 'data' / 'ceo_daemon_heartbeat'
EVENT_QUEUE     = WS / 'data' / 'ceo_event_queue.json'
DAEMON_LOG      = WS / 'data' / 'ceo_daemon.log'

CET = ZoneInfo('Europe/Berlin')

# Phase 43 Pillar A-Voll: Multi-Tier-Loops
HOT_INTERVAL    = 30          # 30s — Event-Queue + Stop/Tranche-Check (regelbasiert)
WARM_INTERVAL   = 3 * 60      # 3min — Position-Health (selektiv LLM)
COLD_MARKET     = 15 * 60     # 15min in Marktstunden — HUNTING/DECIDING (LLM)
COLD_OFFHOURS   = 30 * 60     # 30min off-hours
WAKE_MARKET     = HOT_INTERVAL  # legacy alias
WAKE_OFFHOURS   = HOT_INTERVAL
EVENT_POLL_SEC  = 5           # 5s sleep-chunks (responsive)
MIN_HUNT_GAP    = 15 * 60     # max 1 Hunt pro 15min

_running = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_cet() -> datetime:
    return datetime.now(CET)


def _log(msg: str) -> None:
    """Schreibt in stdout + ceo_daemon.log mit Timestamp."""
    ts = _now_cet().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(DAEMON_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _is_market_hours() -> bool:
    """Mo-Fr 09:00-22:00 CET = Marktstunden (XETR + NYSE-Overlap)."""
    now = _now_cet()
    if now.weekday() >= 5:  # Sa, So
        return False
    return 9 <= now.hour < 22


def _load_state() -> dict:
    if DAEMON_STATE.exists():
        try:
            return json.loads(DAEMON_STATE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'state': 'IDLE',
        'last_state_change': _now_iso(),
        'cycle_count': 0,
        'last_hunt_ts': None,
        'last_decide_ts': None,
        'last_monitor_ts': None,
        'last_reconnais_ts': None,
        'last_reflect_ts': None,
        'pid': os.getpid(),
        'started_at': _now_iso(),
    }


def _save_state(state: dict) -> None:
    state['last_save'] = _now_iso()
    DAEMON_STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def _heartbeat() -> None:
    """Update heartbeat-File (für Watchdog)."""
    try:
        HEARTBEAT_FILE.write_text(_now_iso())
    except Exception:
        pass


def _drain_event_queue() -> list[dict]:
    """Lese + leere die Event-Queue."""
    if not EVENT_QUEUE.exists():
        return []
    try:
        events = json.loads(EVENT_QUEUE.read_text(encoding='utf-8'))
        if not isinstance(events, list):
            events = []
        EVENT_QUEUE.write_text('[]', encoding='utf-8')
        return events
    except Exception:
        return []


def _count_pending_proposals() -> int:
    """Phase 43: zählt nur status='pending'/'active'/None (NICHT 'watching'/'rejected')."""
    if not PROPOSALS_FILE.exists():
        return 0
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data = data.get('proposals', [])
        if not isinstance(data, list):
            return 0
        return sum(1 for p in data if isinstance(p, dict)
                   and p.get('status') in ('pending', 'active', None))
    except Exception:
        return 0


def _expire_stale_proposals() -> int:
    """Phase 43 Pillar A: Expire pending proposals älter als 4h."""
    if not PROPOSALS_FILE.exists():
        return 0
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            meta = {k: v for k, v in data.items() if k != 'proposals'}
            props = data.get('proposals', [])
        else:
            meta = {}
            props = data if isinstance(data, list) else []
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        expired = 0
        for p in props:
            if not isinstance(p, dict):
                continue
            if (p.get('status') in ('pending', 'active', None)
                    and (p.get('created_at') or '') < cutoff):
                p['status'] = 'expired'
                p['status_changed_at'] = datetime.now(timezone.utc).isoformat()
                expired += 1
        if expired:
            out = {**meta, 'proposals': props} if meta else props
            PROPOSALS_FILE.write_text(
                json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8'
            )
        return expired
    except Exception:
        return 0


def _count_watching_proposals_due_for_reeval() -> int:
    """Phase 43 Pillar A: Watching-Proposals die re-eval brauchen.
    Trigger: 60min seit letztem Decide UND (neue Macro-Events ODER Preis±2%)."""
    if not PROPOSALS_FILE.exists():
        return 0
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data = data.get('proposals', [])
        if not isinstance(data, list):
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        return sum(1 for p in data if isinstance(p, dict)
                   and p.get('status') == 'watching'
                   and (p.get('status_changed_at') or '') < cutoff)
    except Exception:
        return 0


def _promote_watching_to_pending() -> int:
    """Phase 43 Pillar A: stale watching-Proposals zurück auf pending für Re-Eval."""
    if not PROPOSALS_FILE.exists():
        return 0
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            meta = {k: v for k, v in data.items() if k != 'proposals'}
            props = data.get('proposals', [])
        else:
            meta = {}
            props = data if isinstance(data, list) else []
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        promoted = 0
        for p in props:
            if not isinstance(p, dict):
                continue
            if (p.get('status') == 'watching'
                    and (p.get('status_changed_at') or '') < cutoff):
                p['status'] = 'pending'
                p['status_changed_at'] = datetime.now(timezone.utc).isoformat()
                p.setdefault('decision_history', []).append({
                    'ts': p['status_changed_at'],
                    'new_status': 'pending',
                    'reason': 'auto_reeval_60min',
                })
                promoted += 1
        if promoted:
            out = {**meta, 'proposals': props} if meta else props
            PROPOSALS_FILE.write_text(
                json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8'
            )
        return promoted
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# State-Handler
# ═══════════════════════════════════════════════════════════════════════════

def state_RECONNAIS(state: dict) -> str:
    """Pre-Market-Briefing — sammle aktuellen Markt-State."""
    _log('🌅 RECONNAIS — Pre-Market-Briefing')
    try:
        # Aktualisiere directive
        from ceo_intelligence import update_directive
        result = update_directive()
        _log(f'  directive: mode={result.get("mode", "?")} regime={result.get("regime", "?")}')
    except Exception as e:
        _log(f'  directive err: {e}')

    # Macro-Detector frisch laufen lassen
    try:
        from macro_event_detector import run as macro_run
        m = macro_run(hours=2)
        _log(f'  macro: {m["matches"]} matches, {m["critical_high"]} crit/high, '
             f'pushed={m["pushed_to_discord"]}')
    except Exception as e:
        _log(f'  macro err: {e}')

    state['last_reconnais_ts'] = _now_iso()
    return 'IDLE'


def state_HUNTING(state: dict) -> str:
    """Aktiv neue Setups generieren."""
    last_hunt = state.get('last_hunt_ts')
    if last_hunt:
        try:
            last_dt = datetime.fromisoformat(last_hunt.replace('Z', '+00:00'))
            gap = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if gap < MIN_HUNT_GAP:
                _log(f'⏸ HUNT skip — last hunt {gap/60:.1f}min ago (<{MIN_HUNT_GAP/60}min cooldown)')
                return 'IDLE'
        except Exception:
            pass

    _log('🎯 HUNTING — active setup search')
    try:
        from ceo_active_hunter import hunt_for_setups
        result = hunt_for_setups(max_new=3)
        _log(f'  context: {result["context_summary"]}')
        _log(f'  thinking: {result["thinking"][:160]}')
        _log(f'  setups proposed: {result["setups_proposed"]}, '
             f'written: {result["proposals_written"]}')
        for s in result.get('setups', [])[:5]:
            _log(f'    · {s.get("ticker", "?"):<8} {s.get("strategy", "?")} '
                 f'conf={s.get("confidence", "?")} trigger={s.get("trigger", "?")}')
        state['last_hunt_ts'] = _now_iso()
        if result['proposals_written'] > 0:
            return 'DECIDING'  # gleich entscheiden
    except Exception as e:
        _log(f'❌ HUNTING failed: {e}')
        traceback.print_exc(file=sys.stderr)
    return 'IDLE'


def state_DECIDING(state: dict) -> str:
    """Pending Proposals durch CEO-Brain durchwürgen."""
    n = _count_pending_proposals()
    if n == 0:
        _log('⏸ DECIDING skip — 0 pending proposals')
        return 'IDLE'
    _log(f'🧠 DECIDING — {n} pending proposals')
    try:
        from ceo_brain import gather_inputs, decide_llm, execute_decisions
        inp = gather_inputs()
        decisions = decide_llm(inp)
        if not decisions:
            from ceo_brain import decide_rules
            decisions = decide_rules(inp)
            _log(f'  fallback rules: {len(decisions)} decisions')
        else:
            _log(f'  LLM: {len(decisions)} decisions')

        summary = execute_decisions(decisions)
        _log(f'  ✅ executed: {summary["success"]}, '
             f'❌ blocked: {summary["failed"]}, '
             f'SKIP: {summary["skip"]}, WATCH: {summary["watch"]}')
        state['last_decide_ts'] = _now_iso()
        if summary['success'] > 0:
            return 'MONITORING'
    except Exception as e:
        _log(f'❌ DECIDING failed: {e}')
        traceback.print_exc(file=sys.stderr)
    return 'IDLE'


def state_MONITORING(state: dict) -> str:
    """Alle Open-Positions kurz checken."""
    _log('👀 MONITORING — open positions check')
    try:
        c = sqlite3.connect(str(DB))
        opens = c.execute(
            "SELECT id, ticker, strategy, entry_price, stop_price, "
            "       target_price, entry_date FROM paper_portfolio "
            "WHERE status='OPEN'"
        ).fetchall()
        c.close()
        _log(f'  open positions: {len(opens)}')

        # Trigger Thesis-Engine (Kill-Trigger)
        try:
            from core.thesis_engine import monitor_all_open
            r = monitor_all_open()
            if r:
                _log(f'  thesis_engine: {r}')
        except Exception as e:
            _log(f'  thesis_engine err: {e}')

        # Trigger Exit-Manager (Tranchen + Stops)
        try:
            from paper_exit_manager import process_all_open
            r = process_all_open()
            if r:
                _log(f'  exit_manager: closed/trail={r}')
        except Exception:
            pass  # process_all_open existiert evtl. nicht; ignore

        state['last_monitor_ts'] = _now_iso()
    except Exception as e:
        _log(f'❌ MONITORING failed: {e}')
    return 'IDLE'


def state_REFLECTING(state: dict) -> str:
    """EOD-Reflection — self-assessment + Phase 43 Pillar C self-reflection."""
    _log('💭 REFLECTING — EOD-Review')
    try:
        from ceo_self_assessment import run_self_assessment
        r = run_self_assessment()
        _log(f'  self-assessment: {str(r)[:200]}')
    except Exception as e:
        _log(f'  self_assessment err: {e}')

    # Phase 43 Pillar C: Self-Reflection (war ich zu vorsichtig?)
    try:
        from ceo_self_reflection import reflect
        r = reflect(days=30)
        _log(f'  self-reflection: missed=+{r["missed_wins_eur"]:.0f}€ '
             f'avoided=-{r["avoided_losses_eur"]:.0f}€ '
             f'net_bias={r["net_bias_cost_eur"]:+.0f}€')
        _log(f'  recommendation: {r["recommendation"][:150]}')
    except Exception as e:
        _log(f'  self_reflection err: {e}')

    state['last_reflect_ts'] = _now_iso()
    return 'IDLE'


def state_INITIATIVE(state: dict) -> str:
    """Phase 43 Pillar D: Eigeninitiative — CEO darf Tickers ergänzen."""
    _log('💡 INITIATIVE — strategy ticker proposals')
    try:
        from ceo_initiative import propose_initiatives
        r = propose_initiatives()
        if r.get('error'):
            _log(f'  err: {r["error"]}')
        else:
            _log(f'  thinking: {r.get("thinking", "")[:160]}')
            ar = r.get('apply_result', {})
            _log(f'  applied: {ar.get("applied", 0)} / {ar.get("attempted", 0)}')
    except Exception as e:
        _log(f'  initiative err: {e}')
    state['last_initiative_ts'] = _now_iso()
    return 'IDLE'


# ═══════════════════════════════════════════════════════════════════════════
# Main Loop
# ═══════════════════════════════════════════════════════════════════════════

def _decide_next_state(state: dict, events: list[dict]) -> str:
    """Welcher State sollte als nächstes laufen? Priorität:
       1. Macro-Event in queue → MONITORING (Re-Eval) + DECIDING
       2. Pre-Market-Zeit (07-09 CET) und nicht heute schon gemacht → RECONNAIS
       3. Pending Proposals > 0 → DECIDING
       4. Last hunt > 15min UND Marktstunden → HUNTING
       5. Marktstunden UND last monitor > 15min → MONITORING
       6. EOD (22-23 CET) und nicht heute schon → REFLECTING
       7. sonst IDLE
    """
    now_cet = _now_cet()
    today = now_cet.strftime('%Y-%m-%d')
    hour = now_cet.hour

    # 0. Lifecycle: expire pending älter 4h, promote watching älter 60min
    n_expired = _expire_stale_proposals()
    n_promoted = _promote_watching_to_pending()
    if n_expired or n_promoted:
        _log(f'  ↻ lifecycle: expired={n_expired} watching→pending={n_promoted}')

    # 1. Events
    if events:
        for ev in events:
            if ev.get('type') in ('macro_event', 'critical_news'):
                _log(f'⚡ Event-Trigger: {ev.get("type")} → MONITORING + DECIDING')
                return 'MONITORING'

    # 2. Pre-Market-Briefing einmal pro Tag
    last_recon = (state.get('last_reconnais_ts') or '')[:10]
    if 7 <= hour < 9 and last_recon != today and now_cet.weekday() < 5:
        return 'RECONNAIS'

    # 3. HUNTING-Priorität wenn lange nicht gehunt UND Marktstunden
    # (Phase 43 Pillar A: vor DECIDING, sonst hunger nach neuen Setups)
    if _is_market_hours():
        last_hunt = state.get('last_hunt_ts')
        if not last_hunt:
            return 'HUNTING'
        try:
            last_dt = datetime.fromisoformat(last_hunt.replace('Z', '+00:00'))
            gap_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            if gap_min >= 15:
                return 'HUNTING'
        except Exception:
            return 'HUNTING'

    # 4. Pending proposals (nach Hunt-Prio)
    if _count_pending_proposals() > 0:
        return 'DECIDING'

    # 5. Position Monitoring alle 15min in Marktstunden
    if _is_market_hours():
        last_mon = state.get('last_monitor_ts')
        if not last_mon:
            return 'MONITORING'
        try:
            last_dt = datetime.fromisoformat(last_mon.replace('Z', '+00:00'))
            gap_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            if gap_min >= 15:
                return 'MONITORING'
        except Exception:
            pass

    # 6. EOD Reflection (22-23 CET)
    last_refl = (state.get('last_reflect_ts') or '')[:10]
    if 22 <= hour < 23 and last_refl != today and now_cet.weekday() < 5:
        return 'REFLECTING'

    # 7. Phase 43 Pillar D: Initiative (1x/Tag um 09-10 CET nach Reconnais)
    last_init = (state.get('last_initiative_ts') or '')[:10]
    if 9 <= hour < 10 and last_init != today and now_cet.weekday() < 5:
        return 'INITIATIVE'

    return 'IDLE'


STATE_HANDLERS = {
    'RECONNAIS':  state_RECONNAIS,
    'HUNTING':    state_HUNTING,
    'DECIDING':   state_DECIDING,
    'MONITORING': state_MONITORING,
    'REFLECTING': state_REFLECTING,
    'INITIATIVE': state_INITIATIVE,
}


def run_once(force_state: str | None = None) -> str:
    """Einmal durch die State-Machine. Returns finalen State."""
    state = _load_state()
    state['cycle_count'] = state.get('cycle_count', 0) + 1
    state['pid'] = os.getpid()

    events = _drain_event_queue()
    if events:
        _log(f'⚡ {len(events)} events in queue')

    next_state = force_state or _decide_next_state(state, events)
    if next_state == 'IDLE':
        state['state'] = 'IDLE'
        _save_state(state)
        return 'IDLE'

    handler = STATE_HANDLERS.get(next_state)
    if not handler:
        _log(f'⚠ unknown state: {next_state}')
        state['state'] = 'IDLE'
        _save_state(state)
        return 'IDLE'

    state['state'] = next_state
    state['last_state_change'] = _now_iso()
    _save_state(state)
    try:
        result_state = handler(state)
    except Exception as e:
        _log(f'❌ handler {next_state} crashed: {e}')
        traceback.print_exc(file=sys.stderr)
        result_state = 'IDLE'
    state['state'] = result_state
    _save_state(state)
    return result_state


def run_hot_tick() -> dict:
    """Phase 43 Pillar A-Voll: Hot-Loop (30s).
    Regelbasiert, KEIN LLM. Aufgaben:
      · Event-Queue drain → wake cold-loop wenn macro_event
      · Pro Open-Position: Stop-Price >= Live-Preis → emergency exit
      · Tranche-Trigger: Live >= tranche_trigger_price → partial close
    """
    result = {'events': 0, 'stops_hit': 0, 'tranches_fired': 0}

    # 1. Events sind in queue, werden vom cold-loop geholt — wir checken nur Anwesenheit
    if EVENT_QUEUE.exists():
        try:
            events = json.loads(EVENT_QUEUE.read_text(encoding='utf-8'))
            if isinstance(events, list):
                result['events'] = len(events)
        except Exception:
            pass

    # 2. Stop-Hit-Check pro Open-Position (rules-based, schnell)
    try:
        c = sqlite3.connect(str(DB))
        opens = c.execute(
            "SELECT id, ticker, strategy, entry_price, stop_price, shares "
            "FROM paper_portfolio WHERE status='OPEN' AND stop_price IS NOT NULL"
        ).fetchall()
        c.close()
        for trade_id, ticker, strategy, entry, stop, shares in opens:
            try:
                # Live-Preis aus prices-Tabelle (täglich) oder live_data
                from ceo_active_hunter import _resolve_live_price
                live = _resolve_live_price(ticker)
                if live <= 0 or not stop:
                    continue
                if live <= float(stop):
                    # Stop hit! Emergency exit
                    _log(f'  🚨 STOP-HIT: {ticker} live={live:.2f} <= stop={stop} '
                         f'(trade {trade_id}) → emergency close')
                    try:
                        from paper_exit_manager import close_position
                        r = close_position(trade_id, exit_reason='STOP_HIT_HOT')
                        if r:
                            result['stops_hit'] += 1
                    except Exception as e:
                        _log(f'    close_position failed: {e}')
            except Exception:
                continue
    except Exception as e:
        _log(f'  hot stop-check err: {e}')

    # 3. Tranche-Trigger (Phase 43: nur Logging, vollständige Logik in paper_exit_manager)
    try:
        from paper_exit_manager import check_tranche_triggers
        r = check_tranche_triggers()
        if r:
            result['tranches_fired'] = r.get('triggered', 0) if isinstance(r, dict) else 0
    except Exception:
        pass  # Funktion existiert evtl. nicht

    return result


def run_warm_tick() -> dict:
    """Phase 43 Pillar A-Voll: Warm-Loop (3min).
    Selektiv LLM. Aufgaben:
      · Pro Open-Position: Thesis-Health-Check (rules + News-Match)
      · Bei 3+ Yellow-Flags: re-eval flag setzen
      · News auf Open-Ticker letzte 3min → mark for next cold cycle
    """
    result = {'positions_checked': 0, 'yellow_flags': 0, 'news_alerts': 0}

    try:
        c = sqlite3.connect(str(DB))
        opens = c.execute(
            "SELECT id, ticker, strategy, entry_price, stop_price, "
            "       target_price, sector, entry_date "
            "FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()

        cutoff = (datetime.utcnow() - timedelta(minutes=3)).strftime('%Y-%m-%d %H:%M:%S')
        for trade_id, ticker, strategy, entry, stop, target, sector, entry_date in opens:
            result['positions_checked'] += 1
            yellow = 0
            from ceo_active_hunter import _resolve_live_price
            live = _resolve_live_price(ticker)
            # Yellow-Flag 1: Stop-Distance < 2%
            if live > 0 and stop and (live - float(stop)) / live < 0.02:
                yellow += 1
            # Yellow-Flag 2: Position underwater > 4%
            if live > 0 and entry and (live - float(entry)) / float(entry) < -0.04:
                yellow += 1
            # Yellow-Flag 3: Recent news mit bearish sentiment
            try:
                rows = c.execute(
                    "SELECT COUNT(*) FROM news_events "
                    "WHERE created_at >= ? AND sentiment_label='bearish' "
                    "AND (tickers LIKE ? OR sector=?)",
                    (cutoff, f'%{ticker}%', sector or '')
                ).fetchone()
                if rows and rows[0] > 0:
                    yellow += 1
                    result['news_alerts'] += 1
            except Exception:
                pass
            if yellow >= 2:
                result['yellow_flags'] += 1
                _log(f'  ⚠ {ticker} ({strategy}): {yellow} yellow flags '
                     f'(live={live:.2f}, entry={entry}, stop={stop})')
                # Mark for cold-cycle reeval (write to event-queue)
                try:
                    qf = WS / 'data' / 'ceo_event_queue.json'
                    q = []
                    if qf.exists():
                        q = json.loads(qf.read_text())
                    q.append({
                        'type':       'position_health_alert',
                        'pushed_at':  _now_iso(),
                        'payload':    {'ticker': ticker, 'strategy': strategy,
                                        'trade_id': trade_id, 'yellow_count': yellow},
                    })
                    qf.write_text(json.dumps(q[-50:], indent=2))
                except Exception:
                    pass
        c.close()
    except Exception as e:
        _log(f'  warm err: {e}')

    return result


def main_loop() -> int:
    """Phase 43 Pillar A-Voll: Multi-Tier-Loop.
    HOT (30s)  → regelbasiert, Stop-Hits + Event-Queue
    WARM (3min)→ Position-Health + News-Match
    COLD (15min)→ Full state-machine (HUNTING/DECIDING/MONITORING)
    """
    _log(f'🚀 CEO-Daemon started (pid={os.getpid()}) — multi-tier mode')

    def _shutdown(*_args):
        global _running
        _running = False
        _log('⏹ shutdown signal received')
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    last_hot  = 0.0
    last_warm = 0.0
    last_cold = 0.0
    cold_log_skip = 0

    while _running:
        _heartbeat()
        try:
            now = time.time()

            # HOT LOOP (30s)
            if now - last_hot >= HOT_INTERVAL:
                last_hot = now
                hot = run_hot_tick()
                if hot['events'] or hot['stops_hit'] or hot['tranches_fired']:
                    _log(f'🔥 HOT: events={hot["events"]} stops={hot["stops_hit"]} '
                         f'tranches={hot["tranches_fired"]}')

            # WARM LOOP (3min, nur in Marktstunden)
            if _is_market_hours() and now - last_warm >= WARM_INTERVAL:
                last_warm = now
                warm = run_warm_tick()
                if warm['positions_checked'] > 0:
                    _log(f'🌡 WARM: checked={warm["positions_checked"]} '
                         f'yellow_flags={warm["yellow_flags"]} '
                         f'news_alerts={warm["news_alerts"]}')

            # COLD LOOP (15min in Marktstunden, 30min off-hours)
            cold_interval = COLD_MARKET if _is_market_hours() else COLD_OFFHOURS
            event_present = EVENT_QUEUE.exists() and EVENT_QUEUE.stat().st_size > 5
            should_cold = (now - last_cold >= cold_interval) or event_present
            if should_cold:
                last_cold = now
                # Run states bis IDLE
                for _ in range(5):
                    next_st = run_once()
                    if next_st == 'IDLE':
                        break

        except Exception as e:
            _log(f'❌ loop error: {e}')
            traceback.print_exc(file=sys.stderr)

        # Schlafe in kleinen Chunks für responsive shutdown (5s)
        for _ in range(EVENT_POLL_SEC):
            if not _running:
                break
            time.sleep(1)

    _log('💤 CEO-Daemon stopped')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true',
                     help='Single cycle, dann exit')
    ap.add_argument('--state', choices=list(STATE_HANDLERS.keys()),
                     help='Specific state forcieren (mit --once)')
    args = ap.parse_args()

    if args.once:
        result = run_once(force_state=args.state)
        _log(f'final state: {result}')
        return 0

    return main_loop()


if __name__ == '__main__':
    sys.exit(main())
