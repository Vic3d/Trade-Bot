#!/usr/bin/env python3
"""
Meta-Health Watchdog — Sub-8 #2
================================
Wer überwacht die Watchdogs? Dieser Job checkt dass die anderen Health-
Komponenten selbst noch leben:

  1) heartbeat_monitor.py — letzter Run via cron (Log-Mtime < 15 Min)
  2) alert_dispatcher.py  — letzter Run (Log-Mtime < 30 Min)
  3) discord_sender       — Webhook erreichbar (HTTP HEAD, 5s Timeout)
  4) trading_monitor.py   — letzter Run (Log-Mtime < 30 Min)
  5) Disk Space           — /opt/trademind > 500MB frei
  6) DB-Größe Spike       — trading.db wachst nicht > 100MB/Tag

Bei Problemen: 1 Discord-Alert pro Befund mit 6h Cooldown.
Schreibt selbst in `data/meta_health_last_run.txt` damit Daily Health
Digest sieht dass Meta-Watchdog läuft.

USAGE:
    python3 scripts/meta_health_watchdog.py [--quiet] [--test]
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DATA = WS / 'data'
DB = DATA / 'trading.db'
LAST_RUN = DATA / 'meta_health_last_run.txt'
LAST_ALERT = DATA / 'meta_health_last_alert.txt'
COOLDOWN_HOURS = 6

# (komponente, log-pfad relativ, max-alter-min)
# Sub-8 Bugfix: alert_dispatcher.log + trading_monitor.log existieren auf VPS
# nicht (Scripts laufen via anderem Mechanismus). Stattdessen aktive Logs.
LOG_CHECKS = [
    ('scheduler',          'scheduler.log',             5),
    ('heartbeat_monitor',  'heartbeat_monitor.log',     15),
    ('price_monitor',      'price_monitor.log',         60),
    ('observation_mode',   'observation_mode.log',      90),
    ('watchdog',           'watchdog.log',              180),
]


def _file_age_min(p: Path) -> float | None:
    if not p.exists():
        return None
    age = (datetime.now().timestamp() - p.stat().st_mtime) / 60
    return age


def _try_restart(name: str) -> str | None:
    """Sub-8 V2 (C): Auto-Heal für bekannte Daemons.
    Versucht price_monitor und heartbeat_monitor systemd-restart oder Direct-Start.
    Gibt Status-Suffix zurück oder None.
    """
    import subprocess
    # systemd-Service-Mapping (Linux/VPS)
    svc_map = {
        'price_monitor': 'trademind-price-monitor',
        'heartbeat_monitor': 'trademind-heartbeat',
        'scheduler': 'trademind-scheduler',
    }
    svc = svc_map.get(name)
    if not svc:
        return None
    try:
        r = subprocess.run(
            ['systemctl', 'restart', svc],
            timeout=15, capture_output=True, text=True
        )
        if r.returncode == 0:
            return f' → AUTO-HEAL: systemctl restart {svc} OK'
        # Fallback: Direct-Start im Hintergrund
        script_map = {
            'price_monitor': WS / 'scripts' / 'price_monitor.py',
        }
        script = script_map.get(name)
        if script and script.exists():
            log = DATA / f'{name}.log'
            subprocess.Popen(
                [sys.executable, str(script)],
                stdout=open(log, 'a'), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return f' → AUTO-HEAL: direct-start {script.name} (PID detached)'
        return f' → AUTO-HEAL FAIL: systemctl rc={r.returncode}'
    except Exception as e:
        return f' → AUTO-HEAL CRASH: {e}'


def _check_logs() -> list[str]:
    issues = []
    for name, fname, max_age in LOG_CHECKS:
        p = DATA / fname
        age = _file_age_min(p)
        if age is None:
            msg = f'{name}: Log-File fehlt ({fname})'
            heal = _try_restart(name)
            if heal:
                msg += heal
            issues.append(msg)
        elif age > max_age:
            msg = f'{name}: Log {age:.0f}min alt (max {max_age}min)'
            heal = _try_restart(name)
            if heal:
                msg += heal
            issues.append(msg)
    return issues


def _check_discord_webhook() -> list[str]:
    """Probiert verschiedene Discord-Setups (Webhook ODER Bot-Token)."""
    issues = []
    sys.path.insert(0, str(WS / 'scripts'))

    # Variante 1: Bot-Token (TradeMind nutzt Bot, kein Webhook)
    if os.getenv('DISCORD_BOT_TOKEN') or os.getenv('TRADEMIND_DISCORD_TOKEN'):
        return []  # Bot-Setup → discord_sender wird selbst checken

    # Variante 2: Klassischer Webhook
    url = os.getenv('DISCORD_WEBHOOK_URL') or os.getenv('TRADEMIND_DISCORD_WEBHOOK')
    if not url:
        try:
            from discord_sender import WEBHOOK_URL  # type: ignore
            url = WEBHOOK_URL
        except Exception:
            try:
                from discord_sender import BOT_TOKEN  # type: ignore
                if BOT_TOKEN:
                    return []  # Bot-Mode
            except Exception:
                pass
            issues.append('Weder Discord-Webhook noch Bot-Token konfiguriert')
            return issues
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status not in (200, 405):
                issues.append(f'Discord-Webhook HTTP {r.status}')
    except Exception as e:
        issues.append(f'Discord-Webhook unreachable: {e}')
    return issues


def _check_disk_space() -> list[str]:
    issues = []
    try:
        usage = shutil.disk_usage(str(WS))
        free_mb = usage.free / 1024 / 1024
        if free_mb < 500:
            issues.append(f'Disk: nur {free_mb:.0f}MB frei (< 500MB)')
    except Exception as e:
        issues.append(f'Disk-Check fail: {e}')
    return issues


def _check_db_size_spike() -> list[str]:
    issues = []
    if not DB.exists():
        return ['trading.db fehlt']
    size_mb = DB.stat().st_size / 1024 / 1024
    history = DATA / 'db_size_history.csv'
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday_size = None
    if history.exists():
        try:
            for line in history.read_text().splitlines()[-7:]:
                d, s = line.split(',')
                if d != today:
                    yesterday_size = float(s)
        except Exception:
            pass
    # Append today's size
    try:
        with history.open('a') as f:
            f.write(f'{today},{size_mb:.2f}\n')
    except Exception:
        pass
    if yesterday_size and (size_mb - yesterday_size) > 100:
        issues.append(f'DB Spike: +{size_mb - yesterday_size:.0f}MB seit gestern')
    return issues


def _alert_cooldown_ok() -> bool:
    if not LAST_ALERT.exists():
        return True
    try:
        last = datetime.fromisoformat(LAST_ALERT.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return age_h >= COOLDOWN_HOURS
    except Exception:
        return True


def _send_alert(msg: str) -> None:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        send(msg)
        LAST_ALERT.write_text(datetime.now(timezone.utc).isoformat(timespec='seconds'))
    except Exception as e:
        print(f'Discord-Alert failed: {e}', file=sys.stderr)


def run(quiet: bool = False, test: bool = False) -> int:
    issues: list[str] = []
    for fn in (_check_logs, _check_discord_webhook, _check_disk_space, _check_db_size_spike):
        try:
            issues.extend(fn())
        except Exception as e:
            issues.append(f'{fn.__name__} CRASHED: {e}')

    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    LAST_RUN.write_text(ts)

    if not issues and not test:
        if not quiet:
            print(f'[{ts}] Meta-Health ✅')
        return 0

    msg = f'[{ts}] Meta-Health Issues ({len(issues)}):\n' + '\n'.join(f'  - {i}' for i in issues)
    if test:
        msg += '\n  - (TEST mode)'
    print(msg)

    if _alert_cooldown_ok():
        _send_alert(f'⚠️ **Meta-Health Watchdog**\n```\n{msg[:1500]}\n```')
    else:
        print(f'[{ts}] Alert suppressed (cooldown)')
    return 1


def main():
    sys.exit(run(quiet='--quiet' in sys.argv, test='--test' in sys.argv))


if __name__ == '__main__':
    main()
