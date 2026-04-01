#!/usr/bin/env python3
"""
scheduler.py — Leichtgewichtiger Cron-Ersatz für Docker-Container
==================================================================
Läuft als Hintergrundprozess, führt Scripts nach Schedule aus.
Schreibt Alerts in pending_alerts.txt für den OpenClaw Alert Dispatcher.
Verbraucht 0 AI-Tokens.

Start: python3 scheduler.py &
Stop:  kill $(cat /tmp/scheduler.pid)
"""

import subprocess
import time
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
RUNNER = str(WS / 'scripts/cron_runner.sh')
LOG = WS / 'data/scheduler.log'
PID_FILE = Path('/tmp/scheduler.pid')

# ═══ SCHEDULE DEFINITION ═══
# Format: (minute_pattern, hour_pattern, weekday_pattern, command)
# Patterns: '*' = every, '*/N' = every N, 'N' = exact, 'N-M' = range, 'N,M' = list
SCHEDULE = [
    # NACHT — Overnight Collector (0,2,4,6h jeden Tag)
    ('0', '0,2,4,6', '*', [RUNNER, str(WS/'scripts/overnight_collector.py')]),
    
    # MORGEN — Data-Prep für CEO (7h Mo-Fr)
    ('0', '7', '1-5', ['python3', str(WS/'scripts/news_pipeline.py')]),
    ('5', '7', '1-5', ['python3', str(WS/'scripts/ceo.py'), '--live']),
    ('10', '7', '1-5', ['python3', str(WS/'scripts/daily_snapshot.py')]),
    
    # GEO-WATCH — Iran + Trump (stündlich 6-23h jeden Tag)
    ('0', '6-23', '*', [RUNNER, str(WS/'scripts/iran_peace_watch.py')]),
    ('2', '6-23', '*', [RUNNER, str(WS/'scripts/trump_watch.py')]),
    
    # TRADING MONITOR (stündlich 8-22h Mo-Fr)
    ('10', '8-22', '1-5', [RUNNER, str(WS/'scripts/trading_monitor.py')]),
    
    # SIGNAL TRACKER (stündlich 8-22h Mo-Fr)
    ('5', '8-22', '1-5', [RUNNER, str(WS/'scripts/signal_tracker.py')]),
    
    # PIFS (stündlich 14-21h Mo-Fr)
    ('15', '14-21', '1-5', [RUNNER, str(WS/'scripts/political_flow_scanner.py')]),
    
    # PAPER EXIT (alle 2h 9-21h Mo-Fr)
    ('10', '9,11,13,15,17,19,21', '1-5', [RUNNER, str(WS/'scripts/paper_exit_manager.py')]),
    
    # S10 LUFTHANSA (3x täglich)
    ('20', '9,14,20', '*', [RUNNER, str(WS/'scripts/s10_lufthansa_monitor.py')]),
    
    # STRATEGY MONITOR (2x Mo-Fr)
    ('40', '8,20', '1-5', [RUNNER, str(WS/'scripts/strategy_monitor.py')]),
    
    # NEWS PIPELINE (4x Mo-Fr)
    ('0', '11,15,19', '1-5', ['python3', str(WS/'scripts/news_pipeline.py')]),
    
    # AUTONOMOUS SCANNER (1x Mo-Fr)
    ('15', '9', '1-5', ['python3', str(WS/'scripts/execution/autonomous_scanner.py'), '6']),
    
    # OPTIONS FLOW (1x Mo-Fr abends)
    ('0', '22', '1-5', [RUNNER, str(WS/'scripts/options_flow_validator.py')]),
    
    # DASHBOARD HEALTHCHECK (alle 15 Min)
    ('*/15', '*', '*', ['bash', str(WS/'scripts/dashboard_healthcheck.sh')]),
    
    # GIT BACKUPS
    ('0', '13', '*', ['bash', '-c', f'cd {WS} && git add -A && git diff --cached --quiet || git commit -m "Midday backup $(date +%Y-%m-%d)" && git push origin master']),
    ('0', '23', '*', ['bash', '-c', f'cd {WS} && git add -A && git diff --cached --quiet || git commit -m "Daily backup $(date +%Y-%m-%d)" && git push origin master']),
]


def matches_pattern(value: int, pattern: str) -> bool:
    """Prüft ob ein Wert zu einem Cron-Pattern passt."""
    if pattern == '*':
        return True
    
    for part in pattern.split(','):
        part = part.strip()
        
        # */N — every N
        if part.startswith('*/'):
            n = int(part[2:])
            if value % n == 0:
                return True
        # N-M — range
        elif '-' in part:
            lo, hi = part.split('-')
            if int(lo) <= value <= int(hi):
                return True
        # exact
        else:
            if value == int(part):
                return True
    
    return False


def should_run(minute_pat: str, hour_pat: str, weekday_pat: str, now: datetime) -> bool:
    """Prüft ob ein Job jetzt laufen soll."""
    return (
        matches_pattern(now.minute, minute_pat) and
        matches_pattern(now.hour, hour_pat) and
        matches_pattern(now.isoweekday(), weekday_pat)  # 1=Mo, 7=So
    )


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}\n'
    try:
        with open(LOG, 'a') as f:
            f.write(line)
        # Log rotieren wenn > 100KB
        if LOG.stat().st_size > 100_000:
            lines = LOG.read_text().splitlines()[-200:]
            LOG.write_text('\n'.join(lines) + '\n')
    except:
        pass


def run_job(cmd: list):
    """Führt einen Job aus (non-blocking, max 120s)."""
    name = Path(cmd[-1]).stem if cmd else '?'
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(WS)
        )
        if result.returncode != 0:
            log(f'ERROR {name}: exit {result.returncode} — {result.stderr[:200]}')
        elif 'DISCORD_ALERT' in result.stdout or 'PEACE_SIGNAL' in result.stdout:
            log(f'ALERT {name}: {result.stdout[:200]}')
        # Kein Log bei KEIN_SIGNAL (spart Disk)
    except subprocess.TimeoutExpired:
        log(f'TIMEOUT {name}')
    except Exception as e:
        log(f'EXCEPTION {name}: {e}')


def shutdown(signum, frame):
    log('Scheduler gestoppt.')
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)


def main():
    # PID schreiben
    PID_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    log(f'Scheduler gestartet (PID {os.getpid()}, {len(SCHEDULE)} Jobs)')
    
    last_run_minute = -1
    
    while True:
        now = datetime.now()
        current_minute = now.hour * 60 + now.minute
        
        # Nur einmal pro Minute laufen
        if current_minute != last_run_minute:
            last_run_minute = current_minute
            
            for minute_pat, hour_pat, weekday_pat, cmd in SCHEDULE:
                if should_run(minute_pat, hour_pat, weekday_pat, now):
                    # Job in eigenem Prozess starten (non-blocking)
                    try:
                        subprocess.Popen(
                            cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            cwd=str(WS)
                        )
                    except Exception as e:
                        log(f'SPAWN ERROR: {e}')
        
        # 30s schlafen, dann nächste Minute prüfen
        time.sleep(30)


if __name__ == '__main__':
    main()
