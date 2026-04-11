#!/usr/bin/env python3.14
import subprocess
from pathlib import Path

pid_file = Path('/data/.openclaw/workspace/data/scheduler.pid')
if pid_file.exists():
    pid = int(pid_file.read_text().strip())
    try:
        import os
        os.kill(pid, 0)
        print('KEIN_SIGNAL')
    except ProcessLookupError:
        subprocess.Popen(['python3.14', '/data/.openclaw/workspace/scripts/scheduler_daemon.py'], start_new_session=True)
        print('Daemon neugestartet')
else:
    subprocess.Popen(['python3.14', '/data/.openclaw/workspace/scripts/scheduler_daemon.py'], start_new_session=True)
    print('Daemon gestartet (kein PID gefunden)')
