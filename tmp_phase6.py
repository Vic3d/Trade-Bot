"""Phase 6: Watchdog (6a) + Discord Error-Alerts (6b) + Health Report (6b-2) + systemd (6a-2)"""
from pathlib import Path
import py_compile, tempfile, subprocess

WS   = Path('/opt/trademind')
SCHED = WS / 'scripts/scheduler_daemon.py'

# ── 6a: Watchdog Heartbeat ────────────────────────────────────────────────────
s = SCHED.read_text(encoding='utf-8')

if 'WATCHDOG_SENTINEL_6a' in s:
    print("6a bereits gepatcht")
else:
    wf = (
        '\n# WATCHDOG_SENTINEL_6a\n'
        'def _watchdog_notify():\n'
        '    """Sendet sd_notify WATCHDOG=1 — verhindert Restart bei haengenden Jobs."""\n'
        '    try:\n'
        '        import systemd.daemon as _sd\n'
        '        _sd.notify("WATCHDOG=1")\n'
        '    except Exception:\n'
        '        try:\n'
        '            (LOG_FILE.parent / "watchdog.txt").write_text(\n'
        '                __import__("datetime").datetime.now().isoformat()\n'
        '            )\n'
        '        except Exception:\n'
        '            pass\n\n'
    )
    tz_marker = 'TZ_BERLIN = ZoneInfo("Europe/Berlin")'
    if tz_marker in s:
        s = s.replace(tz_marker, tz_marker + wf, 1)
    sleep_marker = '        time.sleep(30)'
    if sleep_marker in s:
        s = s.replace(sleep_marker, sleep_marker + '\n        _watchdog_notify()  # Heartbeat', 1)
    tf = tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8')
    tf.write(s); tf.close()
    try:
        py_compile.compile(tf.name, doraise=True)
        SCHED.write_text(s, encoding='utf-8')
        print("6a OK - Watchdog Heartbeat in scheduler_daemon.py")
    except py_compile.PyCompileError as e:
        print("6a FEHLER: " + str(e))
    finally:
        Path(tf.name).unlink(missing_ok=True)

# ── 6b: Discord Error-Alerts ──────────────────────────────────────────────────
s = SCHED.read_text(encoding='utf-8')
if 'ERROR_ALERT_SENTINEL_6b' in s:
    print("6b bereits gepatcht")
else:
    lines = s.splitlines(keepends=True)
    err_idx = next((i for i, l in enumerate(lines) if 'Fehler (code {result.returncode})' in l), None)
    if err_idx is None:
        print("6b WARN: Fehler-Zeile nicht gefunden")
    else:
        ret_idx = next((i for i, l in enumerate(lines) if i > err_idx and '            return False' in l), None)
        if ret_idx is None:
            print("6b WARN: return False nicht gefunden")
        else:
            alert_lines = [
                '            # ERROR_ALERT_SENTINEL_6b\n',
                '            try:\n',
                '                _atf = LOG_FILE.parent / ("alert_" + name.replace(" ", "_") + ".txt")\n',
                '                _now2 = datetime.now()\n',
                '                _do_alert = True\n',
                '                if _atf.exists():\n',
                '                    try:\n',
                '                        _last2 = datetime.fromisoformat(_atf.read_text().strip())\n',
                '                        if (_now2 - _last2).total_seconds() < 3600:\n',
                '                            _do_alert = False\n',
                '                    except Exception:\n',
                '                        pass\n',
                '                if _do_alert:\n',
                '                    _em = (result.stderr or result.stdout or "")[:300]\n',
                '                    _amsg = ("Fehler: " + name + " (code " + str(result.returncode) + ")" +\n',
                '                             chr(10) + _em)\n',
                '                    notify(_amsg)\n',
                '                    _atf.write_text(_now2.isoformat())\n',
                '            except Exception:\n',
                '                pass\n',
            ]
            lines = lines[:ret_idx] + alert_lines + lines[ret_idx:]
            new_s = ''.join(lines)
            tf2 = tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8')
            tf2.write(new_s); tf2.close()
            try:
                py_compile.compile(tf2.name, doraise=True)
                SCHED.write_text(new_s, encoding='utf-8')
                print("6b OK - Discord Error-Alerts in run_job()")
            except py_compile.PyCompileError as e:
                print("6b FEHLER: " + str(e))
            finally:
                Path(tf2.name).unlink(missing_ok=True)

# ── 6b-2: Health Report Job 23:00 ────────────────────────────────────────────
s = SCHED.read_text(encoding='utf-8')
if 'Health Report' not in s:
    lines = s.splitlines(keepends=True)
    dl_idx = next((i for i, l in enumerate(lines) if "('Daily Learning'" in l), None)
    if dl_idx:
        lines.insert(dl_idx + 1,
            "        ('Daily Health Report', 'core/health_report.py', [], 23, 0, [0,1,2,3,4,5,6], True),  # 23:00 CET taegl.\n"
        )
        SCHED.write_text(''.join(lines), encoding='utf-8')
        try:
            py_compile.compile(str(SCHED), doraise=True)
            print("6b-2 OK - Daily Health Report 23:00 in Scheduler")
        except py_compile.PyCompileError as e:
            print("6b-2 FEHLER: " + str(e))
    else:
        print("6b-2 WARN: Daily Learning Marker nicht gefunden")
else:
    print("6b-2 bereits gepatcht")

# ── 6a-2: systemd WatchdogSec ────────────────────────────────────────────────
SERVICE = Path('/etc/systemd/system/trademind-scheduler.service')
svc = SERVICE.read_text(encoding='utf-8')
if 'WatchdogSec' not in svc:
    svc = svc.replace(
        'StartLimitBurst=5\nStartLimitIntervalSec=60',
        'StartLimitBurst=10\nStartLimitIntervalSec=120\nWatchdogSec=180'
    )
    SERVICE.write_text(svc, encoding='utf-8')
    subprocess.run(['systemctl', 'daemon-reload'], check=False)
    print("6a-2 OK - WatchdogSec=180 in systemd service")
else:
    print("6a-2 bereits gepatcht")

print("\nPhase 6a+6b abgeschlossen!")
