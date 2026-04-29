#!/usr/bin/env python3
"""
Heartbeat Monitor — Phase 7.6
==============================
Externer Watchdog für trademind-scheduler Service.

Wird alle 5 Minuten via Cron aufgerufen. Prueft:
  1) scheduler_heartbeat.txt Age (max 180s alt)
  2) systemd unit status ('active (running)')

Bei Fehler:
  - Sendet EINEN Discord-Alert (mit Cooldown: 1 Alert pro Stunde)
  - Versucht 'systemctl restart trademind-scheduler' (als root via sudo)

Cron-Install (als root):
  */5 * * * * /opt/trademind/venv/bin/python3 /opt/trademind/scripts/heartbeat_monitor.py >> /opt/trademind/data/heartbeat_monitor.log 2>&1

Idempotent. Schreibt nur bei Alert/Recovery neue Log-Zeilen.

Usage:
  python3 scripts/heartbeat_monitor.py            # normaler Run
  python3 scripts/heartbeat_monitor.py --test     # Force Alert zum testen
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
HEARTBEAT_FILE = WS / 'data' / 'scheduler_heartbeat.txt'
LAST_ALERT_FILE = WS / 'data' / 'heartbeat_monitor_last_alert.txt'
STATE_FILE = WS / 'data' / 'heartbeat_monitor_state.txt'  # HEALTHY oder UNHEALTHY

# Schwellen
HEARTBEAT_MAX_AGE_SEC = 600  # 10 Minuten (2026-04-21: erhoeht da LLM-Jobs >5min legitim)
ALERT_COOLDOWN_MIN = 60      # max 1 Alert pro Stunde
SERVICE_NAME = 'trademind-scheduler'
# Fix #3 (2026-04-21): Cron-Lock - verhindert dass zwei parallele Aufrufe
# (z.B. doppelter Cron-Eintrag oder verzoegerte Cron-Runs) BEIDE Restart triggern.
import fcntl
LOCK_FILE = WS / 'data' / 'heartbeat_monitor.lock'

def _acquire_lock():
    """Non-blocking flock. Gibt File-Handle zurueck oder None wenn schon gehalten."""
    try:
        fh = open(LOCK_FILE, 'w')
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except (IOError, OSError):
        return None


sys.path.insert(0, str(WS / 'scripts'))


def _check_heartbeat() -> tuple[bool, str]:
    """(ok, reason)"""
    try:
        if not HEARTBEAT_FILE.exists():
            return False, 'Heartbeat-File fehlt'
        raw = HEARTBEAT_FILE.read_text().strip()
        last = datetime.fromisoformat(raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - last).total_seconds()
        if age > HEARTBEAT_MAX_AGE_SEC:
            return False, f'Heartbeat {age:.0f}s alt (> {HEARTBEAT_MAX_AGE_SEC}s)'
        return True, f'frisch ({age:.0f}s)'
    except Exception as e:
        return False, f'Heartbeat-Read-Fehler: {e}'


def _check_systemd() -> tuple[bool, str]:
    """(ok, status)"""
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', SERVICE_NAME],
            capture_output=True, text=True, timeout=10,
        )
        status = r.stdout.strip()
        return status == 'active', status
    except Exception as e:
        return False, f'systemctl error: {e}'


def _last_alert_ago_min() -> float:
    """Minuten seit letztem Alert (oder inf)."""
    try:
        if not LAST_ALERT_FILE.exists():
            return 9999.0
        last = datetime.fromisoformat(LAST_ALERT_FILE.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds() / 60
    except Exception:
        return 9999.0


def _send_discord(msg: str, silent: bool = False) -> bool:
    """Phase 43e: silent=True → nur ceo_inbox, kein Discord-Push.
    Default silent=False bleibt für echte Crashes erhalten."""
    # Immer in ceo_inbox loggen (CEO-Sicht)
    try:
        from ceo_inbox import write_event
        is_recovery = '✅' in msg or 'recovered' in msg.lower()
        is_crash = '🚨' in msg or 'crash' in msg.lower()
        write_event(
            event_type='scheduler.recovered' if is_recovery
                        else 'scheduler.crash' if is_crash
                        else 'heartbeat.event',
            message=msg[:300],
            severity='info' if is_recovery else 'critical' if is_crash else 'warning',
            category='health',
            user_pinged=(not silent),
        )
    except Exception:
        pass

    if silent:
        return True  # nur Inbox, kein Discord

    try:
        from discord_sender import send
        send(msg)
        return True
    except Exception as e:
        print(f'Discord fail: {e}', file=sys.stderr)
        return False


def _try_restart() -> tuple[bool, str]:
    """Versucht 'sudo systemctl restart'. Nur erfolgreich wenn sudoers-Regel gesetzt."""
    try:
        r = subprocess.run(
            ['sudo', '-n', 'systemctl', 'restart', SERVICE_NAME],
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0, (r.stderr or r.stdout).strip()[:200]
    except Exception as e:
        return False, str(e)[:200]


def _read_prev_state() -> str:
    try:
        return STATE_FILE.read_text().strip() if STATE_FILE.exists() else 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'


def _write_state(state: str) -> None:
    try:
        STATE_FILE.write_text(state)
    except Exception:
        pass


def run(test: bool = False) -> int:
    hb_ok, hb_msg = _check_heartbeat()
    sd_ok, sd_msg = _check_systemd()

    all_ok = hb_ok and sd_ok and not test
    prev_state = _read_prev_state()
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    if all_ok:
        if prev_state == 'UNHEALTHY':
            # Recovery — Phase 43e: nur Inbox, kein Discord-Spam
            _send_discord(
                f'✅ **Scheduler recovered**\nHeartbeat: {hb_msg}\nSystemd: {sd_msg}',
                silent=True,
            )
            print(f'[{ts}] RECOVERED heartbeat={hb_msg} systemd={sd_msg}')
        _write_state('HEALTHY')
        return 0

    # UNHEALTHY path
    _write_state('UNHEALTHY')
    problem = (
        f'Heartbeat: {"✅" if hb_ok else "❌"} {hb_msg}\n'
        f'Systemd:   {"✅" if sd_ok else "❌"} {sd_msg}'
    )
    print(f'[{ts}] UNHEALTHY\n{problem}')

    # Restart versuchen
    restart_ok, restart_msg = _try_restart()
    print(f'[{ts}] Restart-Versuch: ok={restart_ok} msg={restart_msg}')

    # Alert mit Cooldown
    # Phase 43e: nur echte länger-anhaltende Crashes pingen User.
    # Auto-restart gelang? → silent (kein Spam)
    ago = _last_alert_ago_min()
    alert = (
        f'🚨 **Scheduler-Crash erkannt**\n'
        f'{problem}\n'
        f'Auto-Restart: {"✅ erfolgreich" if restart_ok else f"❌ {restart_msg}"}\n'
        f'Cooldown: {ALERT_COOLDOWN_MIN}min bis nächster Alert'
    )
    silent_for_user = restart_ok  # Wenn Auto-Restart klappt → kein User-Ping
    if ago >= ALERT_COOLDOWN_MIN or test:
        if _send_discord(alert, silent=silent_for_user):
            try:
                LAST_ALERT_FILE.write_text(ts)
            except Exception:
                pass
    else:
        print(f'[{ts}] Alert suppressed (last alert {ago:.0f}min ago)')

    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--test', action='store_true', help='Force UNHEALTHY flow for testing')
    args = ap.parse_args()
    # Fix #3: nur EIN Aufruf darf gleichzeitig laufen
    lock_fh = _acquire_lock()
    if lock_fh is None:
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        print(f'[{ts}] SKIP - anderer heartbeat_monitor Lauf aktiv (lock busy)')
        sys.exit(0)
    try:
        sys.exit(run(test=args.test))
    finally:
        try:
            import fcntl as _f
            _f.flock(lock_fh.fileno(), _f.LOCK_UN)
            lock_fh.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
