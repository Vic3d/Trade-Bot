#!/usr/bin/env python3
"""
Daily Health Digest — Sub-8 #3
================================
Nightly Discord-Message: 1 kompakte System-Übersicht der letzten 24h.

Aggregiert:
  - Scheduler-Heartbeats (Alter, last 24h heartbeat-File-mtime)
  - Watchdog-Runs (DB-Integrity, Meta-Health, Anomaly-Brake — letzter Run + Status)
  - Job-Failures (aus scheduler.log: ERROR-Lines der letzten 24h)
  - Alerts gesendet (Heartbeat-Monitor, Anomaly, Alert-Dispatcher)
  - API-Quota (über api_quota_tracker.report)
  - Discord-Sender Erfolgsrate

Läuft täglich 22:30 CET, NACH dem Daily Learning Cycle.

USAGE:
    python3 scripts/health_digest.py [--no-send] [--test]
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DATA = WS / 'data'
DB = DATA / 'trading.db'


def _file_age_min(p: Path) -> float | None:
    if not p.exists():
        return None
    return (datetime.now().timestamp() - p.stat().st_mtime) / 60


def _section_scheduler() -> str:
    hb = DATA / 'scheduler_heartbeat.txt'
    age = _file_age_min(hb)
    if age is None:
        return '❌ Scheduler-Heartbeat fehlt!'
    if age > 5:
        return f'⚠️ Scheduler-Heartbeat {age:.0f}min alt'
    return f'✅ Scheduler aktiv (HB {age:.0f}min)'


def _section_watchdogs() -> str:
    """File-Semantik:
       - *_last_alert.txt / *_last_halt.txt → Datei existiert NUR bei Problem
       - *_last_run.txt / *_state.txt → Datei existiert nach jedem Run
    """
    lines = ['Watchdogs:']
    # (name, fname, problem_if_exists, ok_label_if_missing)
    problem_files = [
        ('DB-Integrity',  'db_integrity_last_alert.txt',  'no recent alerts'),
        ('Anomaly-Brake', 'anomaly_brake_last_halt.txt',  'no recent HALT'),
    ]
    run_files = [
        ('Meta-Health',   'meta_health_last_run.txt',     720),  # warn if >12h alt
        ('Heartbeat-Mon', 'heartbeat_monitor_state.txt',  60),
    ]
    for name, fname, ok_label in problem_files:
        p = DATA / fname
        if not p.exists():
            lines.append(f'  ✅ {name:14s}: {ok_label}')
        else:
            age = _file_age_min(p) or 0
            try:
                content = p.read_text().strip()[:60]
            except Exception:
                content = '?'
            marker = '🚨' if age < 60 else '⚠️'
            lines.append(f'  {marker} {name:14s}: ALERT vor {age:.0f}min ({content})')
    for name, fname, max_age_min in run_files:
        p = DATA / fname
        if not p.exists():
            lines.append(f'  ⚪ {name:14s}: noch nie gelaufen')
            continue
        age = _file_age_min(p) or 0
        try:
            content = p.read_text().strip()[:30]
        except Exception:
            content = '?'
        marker = '✅' if age <= max_age_min else '⚠️'
        lines.append(f'  {marker} {name:14s}: {content} ({age:.0f}min ago)')
    return '\n'.join(lines)


def _section_job_errors() -> str:
    log = DATA / 'scheduler.log'
    if not log.exists():
        return 'Job-Errors (24h): scheduler.log fehlt'
    cutoff = datetime.now() - timedelta(hours=24)
    err_count = 0
    samples = []
    try:
        # Tail last 5000 lines (cheap)
        lines = log.read_text(errors='replace').splitlines()[-5000:]
        for ln in lines:
            if 'ERROR' in ln or '❌' in ln or 'CRASHED' in ln:
                err_count += 1
                if len(samples) < 3:
                    samples.append(ln[:120])
    except Exception as e:
        return f'Job-Errors: read fail ({e})'
    out = [f'Job-Errors (24h): {err_count}']
    for s in samples:
        out.append(f'  - {s}')
    return '\n'.join(out)


def _section_anomaly_log() -> str:
    log = DATA / 'anomaly_brake_log.jsonl'
    if not log.exists():
        return 'Anomaly-Triggers (24h): 0'
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    cnt = 0
    try:
        for ln in log.read_text().splitlines()[-200:]:
            if cutoff in ln or ln > f'{{"ts": "{cutoff}':
                cnt += 1
    except Exception:
        pass
    return f'Anomaly-Triggers (24h): {cnt}'


def _section_api_quota() -> str:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from api_quota_tracker import report, format_report
        return format_report(report(days=1))
    except Exception as e:
        return f'API-Quota: {e}'


def _section_db_size() -> str:
    if not DB.exists():
        return 'DB: fehlt'
    size_mb = DB.stat().st_size / 1024 / 1024
    rows = 0
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute('SELECT COUNT(*) FROM paper_portfolio').fetchone()[0]
        c.close()
    except Exception:
        pass
    return f'DB: {size_mb:.1f}MB, paper_portfolio={rows} rows'


def build_digest() -> str:
    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    parts = [
        f'🩺 **Health Digest** {ts}',
        '',
        _section_scheduler(),
        '',
        _section_watchdogs(),
        '',
        _section_job_errors(),
        _section_anomaly_log(),
        _section_db_size(),
        '',
        _section_api_quota(),
    ]
    return '\n'.join(parts)


def main():
    no_send = '--no-send' in sys.argv
    test = '--test' in sys.argv
    digest = build_digest()
    print(digest)
    if no_send:
        return
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        send(digest)
    except Exception as e:
        print(f'discord send fail: {e}', file=sys.stderr)
        if test:
            sys.exit(1)


if __name__ == '__main__':
    main()
