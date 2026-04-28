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

WAKE_MARKET     = 5 * 60      # 5min in Marktstunden
WAKE_OFFHOURS   = 30 * 60     # 30min off-hours
EVENT_POLL_SEC  = 30          # Event-Queue alle 30s checken
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
    """EOD-Reflection."""
    _log('💭 REFLECTING — EOD-Review')
    try:
        from ceo_self_assessment import run_self_assessment
        r = run_self_assessment()
        _log(f'  self-assessment: {str(r)[:200]}')
    except Exception as e:
        _log(f'  self_assessment err: {e}')
    state['last_reflect_ts'] = _now_iso()
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

    # 3. Pending proposals
    if _count_pending_proposals() > 0:
        return 'DECIDING'

    # 4. Active Hunting in Marktstunden
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

    # 6. EOD Reflection
    last_refl = (state.get('last_reflect_ts') or '')[:10]
    if 22 <= hour < 23 and last_refl != today and now_cet.weekday() < 5:
        return 'REFLECTING'

    return 'IDLE'


STATE_HANDLERS = {
    'RECONNAIS':  state_RECONNAIS,
    'HUNTING':    state_HUNTING,
    'DECIDING':   state_DECIDING,
    'MONITORING': state_MONITORING,
    'REFLECTING': state_REFLECTING,
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


def main_loop() -> int:
    """Endlos-Loop bis SIGTERM."""
    _log(f'🚀 CEO-Daemon started (pid={os.getpid()})')

    def _shutdown(*_args):
        global _running
        _running = False
        _log('⏹ shutdown signal received')
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    last_full_cycle = 0.0
    while _running:
        _heartbeat()
        try:
            now = time.time()
            wake_interval = WAKE_MARKET if _is_market_hours() else WAKE_OFFHOURS
            do_cycle = (now - last_full_cycle) >= wake_interval

            # Event-poll inzwischen
            events = []
            if EVENT_QUEUE.exists():
                events = _drain_event_queue()
                if events:
                    do_cycle = True
                    # Re-write events in queue so the cycle picks them up
                    EVENT_QUEUE.write_text(json.dumps(events), encoding='utf-8')

            if do_cycle:
                last_full_cycle = now
                # Run states bis IDLE
                for _ in range(5):  # max 5 Transitions pro Wake-Cycle
                    next_st = run_once()
                    if next_st == 'IDLE':
                        break
        except Exception as e:
            _log(f'❌ loop error: {e}')
            traceback.print_exc(file=sys.stderr)

        # Schlafe in kleinen Chunks für responsive shutdown
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
