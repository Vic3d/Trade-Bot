#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))


pid_file = WS / 'data/scheduler.pid'

if pid_file.exists():
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    try:
        os.kill(pid, 0)
        print('KEIN_SIGNAL')
    except (ProcessLookupError, OSError):
        subprocess.Popen([sys.executable, str(WS / 'scripts/scheduler_daemon.py')], start_new_session=True)
        print('Daemon neugestartet')
else:
    subprocess.Popen([sys.executable, str(WS / 'scripts/scheduler_daemon.py')], start_new_session=True)
    print('Daemon gestartet (kein PID gefunden)')
