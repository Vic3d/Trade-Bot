#!/usr/bin/env python3.13
"""
TradeMind Scheduler Daemon — Phase 8 / Kostenoptimierung
=========================================================
Läuft 24/7 als Hintergrundprozess.
Ersetzt alle OpenClaw agentTurn-Crons durch direkte Python-Aufrufe.
Kein LLM, keine Token-Kosten, kein Overhead.

Starten:  python3.13 scheduler_daemon.py &
Status:   python3.13 scheduler_daemon.py --status
Stoppen:  python3.13 scheduler_daemon.py --stop
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
SCRIPTS = WS / 'scripts'
PID_FILE = WS / 'data/scheduler.pid'
LOG_FILE = WS / 'data/scheduler.log'

# ── Zeitplan ──────────────────────────────────────────────────────────────────
# Format: (name, script, args, stunde, minute, wochentage)
# wochentage: None = täglich, [0,1,2,3,4] = Mo-Fr, [5] = Sa, [6] = So

SCHEDULE = [
    # Täglich
    ('Regime Detector',     'regime_detector.py',     ['--integrate', '--quick'], 7,  0,  None),
    ('Alpha Decay',         'alpha_decay.py',          [],                        21, 0,  None),
    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),
    ('RL Training',         'rl_trainer.py',           ['--train', '200000'],     2,  0,  None),
    # Mo-Fr
    ('Feature Analyzer',    'feature_analyzer.py',     ['--quick'],               11, 30, [5]),   # Sa
    ('Backtest Engine',     'backtest_engine.py',      ['--quick'],               9,  0,  [6]),   # So
    ('Strategy DNA',        'strategy_dna.py',         [],                        12, 0,  [5]),   # Sa
    ('Feature Importance',  'feature_importance.py',   [],                        22, 30, [4]),   # Fr
]


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')
    # Log auf 5000 Zeilen begrenzen
    try:
        lines = LOG_FILE.read_text().splitlines()
        if len(lines) > 5000:
            LOG_FILE.write_text('\n'.join(lines[-4000:]) + '\n')
    except Exception:
        pass


# ── Discord ───────────────────────────────────────────────────────────────────

def notify(msg: str):
    """Sendet Discord-Nachricht direkt (kein LLM)."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from discord_sender import send
        send(msg)
    except Exception as e:
        log(f'Discord-Fehler: {e}')


# ── Job Runner ────────────────────────────────────────────────────────────────

def run_job(name: str, script: str, args: list[str]) -> bool:
    """Führt ein Script aus und gibt True bei Erfolg zurück."""
    script_path = SCRIPTS / script
    if not script_path.exists():
        log(f'⚠️  {name}: Script nicht gefunden — {script}')
        return False

    log(f'▶️  {name}: Start')
    try:
        result = subprocess.run(
            ['python3.13', str(script_path)] + args,
            capture_output=True, text=True, timeout=3600,
            cwd=str(WS)
        )
        if result.returncode == 0:
            log(f'✅ {name}: OK')
            return True
        else:
            log(f'❌ {name}: Fehler (code {result.returncode})')
            log(f'   STDERR: {result.stderr[-300:]}')
            return False
    except subprocess.TimeoutExpired:
        log(f'⏱️  {name}: Timeout')
        return False
    except Exception as e:
        log(f'💥 {name}: Exception — {e}')
        return False


# ── Scheduler Loop ────────────────────────────────────────────────────────────

def should_run(hour: int, minute: int, weekdays) -> bool:
    """Prüft ob ein Job jetzt laufen soll (innerhalb ±30s Fenster)."""
    now = datetime.now()
    if now.hour != hour or abs(now.minute - minute) > 0:
        return False
    if weekdays is not None and now.weekday() not in weekdays:
        return False
    return True


def scheduler_loop():
    """Haupt-Schleife — prüft jede Minute ob Jobs laufen sollen."""
    log('🚀 TradeMind Scheduler Daemon gestartet')
    notify('🤖 **TradeMind Scheduler** gestartet — alle Crons laufen jetzt token-frei')

    last_run = {}  # Verhindert Doppel-Ausführungen

    while True:
        now = datetime.now()
        current_key = f'{now.strftime("%Y-%m-%d %H:%M")}'

        for name, script, args, hour, minute, weekdays in SCHEDULE:
            job_key = f'{name}_{current_key}'
            if job_key in last_run:
                continue

            if should_run(hour, minute, weekdays):
                last_run[job_key] = True
                # Cleanup alter Einträge
                if len(last_run) > 1000:
                    old_keys = list(last_run.keys())[:-500]
                    for k in old_keys:
                        del last_run[k]

                success = run_job(name, script, args)

                # Bestimmte Jobs senden Discord-Notification bei Fehler
                if not success:
                    notify(f'⚠️ **Scheduler:** {name} fehlgeschlagen — Logs: data/scheduler.log')

        # Genau auf nächste Minute warten
        sleep_secs = 60 - datetime.now().second
        time.sleep(max(1, sleep_secs))


# ── PID Management ────────────────────────────────────────────────────────────

def write_pid():
    PID_FILE.write_text(str(os.getpid()))

def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None

def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--status' in args:
        pid = read_pid()
        if pid and is_running(pid):
            print(f'✅ Scheduler läuft (PID {pid})')
            # Letzte Log-Zeilen
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text().splitlines()
                print('\nLetzte 10 Einträge:')
                for l in lines[-10:]:
                    print(f'  {l}')
        else:
            print('❌ Scheduler läuft NICHT')
            print('   Starte mit: python3.13 scheduler_daemon.py &')

    elif '--stop' in args:
        pid = read_pid()
        if pid and is_running(pid):
            os.kill(pid, signal.SIGTERM)
            PID_FILE.unlink(missing_ok=True)
            print(f'✅ Scheduler (PID {pid}) gestoppt')
        else:
            print('Scheduler läuft nicht')

    elif '--run-now' in args:
        # Manuell einen Job ausführen
        job_name = args[args.index('--run-now') + 1] if len(args) > args.index('--run-now') + 1 else None
        for name, script, job_args, *_ in SCHEDULE:
            if job_name is None or job_name.lower() in name.lower():
                print(f'▶️  Manuell: {name}')
                run_job(name, script, job_args)

    elif '--start' in args or len(args) == 0:
        # Prüfen ob bereits läuft
        pid = read_pid()
        if pid and is_running(pid):
            print(f'⚠️  Scheduler läuft bereits (PID {pid})')
            sys.exit(0)

        write_pid()
        try:
            scheduler_loop()
        except KeyboardInterrupt:
            log('Scheduler gestoppt (KeyboardInterrupt)')
            PID_FILE.unlink(missing_ok=True)
        except Exception as e:
            log(f'💥 Daemon Crash: {e}')
            notify(f'🚨 **TradeMind Scheduler CRASH:** {e}\nNeustart nötig!')
            PID_FILE.unlink(missing_ok=True)
            raise
