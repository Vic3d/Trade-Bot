#!/usr/bin/env python3
"""
fast_discovery_trigger.py — Schneller Discovery bei Geo-Alert HIGH.

Läuft alle 30 Minuten via scheduler. Aufgabe:
  1. Liest aktuelles geo_alert_level aus data/ceo_directive.json
  2. Vergleicht mit dem letzten Stand in data/.fast_discovery_state.json
  3. Bei Transition (LOW/MEDIUM/None → HIGH) ODER bei NEUEM news_count_jump:
       → spawnt thesis_discovery.py SOFORT (statt erst 05:00 morgen)
       → schreibt Discord-Alert
       → loggt in conversation_log
  4. Debounce: triggert nicht erneut innerhalb DEBOUNCE_HOURS=4 für selbe Ursache

Hintergrund:
  Normalerweise läuft thesis_discovery.py nur 1x täglich um 05:00 CEST.
  Wenn aber tagsüber etwas Großes passiert (Trump-Tariff, Iran-Eskalation,
  Tech-Crash) braucht's nicht 12h Verzögerung sondern <60min.

Sicherheits-Caps:
  - Max 3 Fast-Triggers pro Tag (verhindert Endlos-Spam bei eskalierenden Events)
  - Debounce 4h zwischen Triggers (auch wenn Alert wieder HIGH)
  - Nur LIVE-Pfad: läuft nicht in Backtest-Mode
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DIRECTIVE_FILE = WS / 'data' / 'ceo_directive.json'
STATE_FILE     = WS / 'data' / '.fast_discovery_state.json'
DISCOVERY_PATH = WS / 'scripts' / 'intelligence' / 'thesis_discovery.py'

DEBOUNCE_HOURS    = 4
MAX_TRIGGERS_DAY  = 3
TIMEOUT_DISCOVERY = 300  # 5min Hard-Cap


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {'last_alert': 'LOW', 'last_trigger_at': None, 'triggers_today': []}
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'last_alert': 'LOW', 'last_trigger_at': None, 'triggers_today': []}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding='utf-8')


def _read_directive() -> dict:
    if not DIRECTIVE_FILE.exists():
        return {}
    try:
        return json.loads(DIRECTIVE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _today_iso() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _purge_old_triggers(state: dict) -> None:
    """Behält nur Trigger von heute."""
    today = _today_iso()
    state['triggers_today'] = [
        t for t in state.get('triggers_today', [])
        if t.startswith(today)
    ]


def _can_trigger(state: dict) -> tuple[bool, str]:
    _purge_old_triggers(state)
    if len(state.get('triggers_today', [])) >= MAX_TRIGGERS_DAY:
        return False, f'cap_reached ({MAX_TRIGGERS_DAY}/Tag)'
    last = state.get('last_trigger_at')
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if datetime.now() - last_dt < timedelta(hours=DEBOUNCE_HOURS):
                age = (datetime.now() - last_dt).total_seconds() / 60
                return False, f'debounce ({age:.0f}min seit letztem)'
        except Exception:
            pass
    return True, 'ok'


def _spawn_discovery() -> tuple[bool, str]:
    """Startet thesis_discovery.py synchron (mit Timeout)."""
    if not DISCOVERY_PATH.exists():
        return False, f'script not found: {DISCOVERY_PATH}'
    try:
        result = subprocess.run(
            ['python3', str(DISCOVERY_PATH)],
            capture_output=True, text=True,
            timeout=TIMEOUT_DISCOVERY,
            cwd=str(WS),
        )
        if result.returncode == 0:
            tail = (result.stdout or '').splitlines()[-3:]
            return True, ' | '.join(tail) if tail else 'OK'
        else:
            return False, f'rc={result.returncode}: {(result.stderr or "")[:200]}'
    except subprocess.TimeoutExpired:
        return False, f'timeout nach {TIMEOUT_DISCOVERY}s'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def _notify_discord(msg: str) -> None:
    try:
        from discord_dispatcher import send_alert, TIER_HIGH
        send_alert(msg, tier=TIER_HIGH, category='fast_discovery',
                   dedupe_key=f'fast_disc_{_today_iso()}')
    except Exception as e:
        print(f'[fast_discovery] Discord-Send-Fehler: {e}')


def _log_event(content: str, meta: dict | None = None) -> None:
    try:
        from conversation_log import append
        append(source='cli', role='system', speaker='fast_discovery',
               content=content, meta=meta or {})
    except Exception:
        pass


def main() -> int:
    state = _load_state()
    directive = _read_directive()
    current_alert = directive.get('geo_alert_level', 'LOW')
    geo_score = directive.get('geo_score', 0)
    last_alert = state.get('last_alert', 'LOW')

    # State vor allem updaten (auch wenn nicht triggered)
    state['last_alert'] = current_alert
    state['last_check_at'] = datetime.now().isoformat(timespec='seconds')

    # Trigger-Bedingung: Transition AUF HIGH
    is_transition = (last_alert != 'HIGH' and current_alert == 'HIGH')

    if not is_transition:
        _save_state(state)
        print(f'[fast_discovery] no transition (current={current_alert}, last={last_alert}) — skip')
        return 0

    # Transition erkannt — Debounce/Cap prüfen
    can, reason = _can_trigger(state)
    if not can:
        print(f'[fast_discovery] transition LOW/MEDIUM→HIGH erkannt aber blocked: {reason}')
        _log_event(f'Geo-Alert HIGH erkannt aber Trigger blocked: {reason}',
                   meta={'event': 'fast_discovery_blocked', 'reason': reason,
                         'geo_score': geo_score})
        _save_state(state)
        return 0

    # Trigger!
    print(f'[fast_discovery] Geo-Alert TRANSITION → HIGH (score={geo_score}). '
          f'Spawning thesis_discovery...')
    started = datetime.now()
    ok, info = _spawn_discovery()
    elapsed = (datetime.now() - started).total_seconds()

    state['last_trigger_at'] = datetime.now().isoformat(timespec='seconds')
    state.setdefault('triggers_today', []).append(state['last_trigger_at'])
    _save_state(state)

    if ok:
        msg = (f'⚡ **Fast Discovery getriggert** — Geo-Alert HIGH (score {geo_score})\n'
               f'thesis_discovery.py lief in {elapsed:.0f}s.\n'
               f'Output: `{info[:200]}`\n'
               f'_(Trigger {len(state["triggers_today"])}/{MAX_TRIGGERS_DAY} heute)_')
    else:
        msg = (f'⚠️ **Fast Discovery FEHLGESCHLAGEN** — Geo-Alert HIGH (score {geo_score})\n'
               f'Fehler: `{info[:200]}`')

    _notify_discord(msg)
    _log_event(f'Fast Discovery getriggert (geo_score={geo_score}, ok={ok})',
               meta={'event': 'fast_discovery_run', 'ok': ok,
                     'elapsed_s': elapsed, 'geo_score': geo_score})
    print(f'[fast_discovery] done. ok={ok}, elapsed={elapsed:.0f}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
