#!/usr/bin/env python3
"""
Observation Mode — Phase 7.10 (Pre-Flight vor 30d Autonomous Run)
==================================================================
Pollt alle 5 Minuten kritische System-Signale und schreibt sie
als JSONL in data/observation_log.jsonl (append-only).

Ziel:
  48h durchlaufen lassen → `--summary` auswerten → grünes Licht
  geben bevor der 30-Tage-Run gestartet wird.

Signale pro Snapshot:
  - fund_value_eur, cash_eur, open_positions
  - heartbeat_age_sec (scheduler_heartbeat.txt)
  - systemd_active (is-active trademind-scheduler)
  - disk_free_gb (/opt partition)
  - db_size_mb (trading.db)
  - null_exit_count (CLOSED/WIN/LOSS mit exit_type IS NULL)
  - last_trade_age_min (jüngster OPEN oder CLOSED)
  - ceo_halt (trading_halt Flag)
  - price_freshness_min (neuester prices.date)
  - errors in scheduler.log der letzten 5 Minuten

Anomalien (werden im Log mit "flags" Liste markiert):
  - heartbeat_stale (> 180s)
  - systemd_inactive
  - disk_low (< 2 GB frei)
  - null_exit_new (neuer NULL-exit aufgetaucht)
  - scheduler_errors (≥3 ERROR-Lines in 5min)
  - ceo_halt_unexpected (HALT ohne menschlichen Grund)

Usage:
  python3 scripts/observation_mode.py               # 1 Snapshot
  python3 scripts/observation_mode.py --summary     # 48h-Rollup
  python3 scripts/observation_mode.py --summary 24  # letzte 24h

Cron-Install (als trademind):
  */5 * * * * /opt/trademind/venv/bin/python3 /opt/trademind/scripts/observation_mode.py >> /opt/trademind/data/observation_mode.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
HEARTBEAT = WS / 'data' / 'scheduler_heartbeat.txt'
CEO = WS / 'data' / 'ceo_directive.json'
SCHED_LOG = WS / 'data' / 'scheduler.log'
OBS_LOG = WS / 'data' / 'observation_log.jsonl'

sys.path.insert(0, str(WS / 'scripts'))

HEARTBEAT_MAX_AGE_SEC = 180
DISK_MIN_GB = 2.0
SCHEDULER_ERROR_THRESHOLD = 3  # pro 5min

SERVICE = 'trademind-scheduler'


# ────────────────────────────────────────────────────────────────────────────
# Signal Collectors
# ────────────────────────────────────────────────────────────────────────────

def _db_snapshot() -> dict:
    """fund_value, cash, open_positions, null_exits, last_trade_age, price_freshness."""
    out = {
        'fund_value_eur': None, 'cash_eur': None, 'open_positions': None,
        'null_exit_count': None, 'last_trade_age_min': None,
        'price_freshness_min': None, 'db_size_mb': None,
    }
    try:
        out['db_size_mb'] = round(DB.stat().st_size / 1024 / 1024, 2)
    except Exception:
        pass
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        # Cash
        r = c.execute(
            "SELECT value FROM paper_fund WHERE key IN ('current_cash','cash') "
            "ORDER BY CASE key WHEN 'current_cash' THEN 0 ELSE 1 END LIMIT 1"
        ).fetchone()
        cash = float(r[0]) if r else 0.0
        # Offene Positionen + Wert
        rows = c.execute(
            "SELECT shares, entry_price FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        open_pos_value = sum(float(r[0] or 0) * float(r[1] or 0) for r in rows)
        out['cash_eur'] = round(cash, 2)
        out['open_positions'] = len(rows)
        out['fund_value_eur'] = round(cash + open_pos_value, 2)
        # NULL exits (CLOSED/WIN/LOSS ohne exit_type)
        r = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio "
            "WHERE status IN ('CLOSED','WIN','LOSS') AND exit_type IS NULL"
        ).fetchone()
        out['null_exit_count'] = int(r[0]) if r else 0
        # Letzter Trade
        r = c.execute(
            "SELECT MAX(COALESCE(exit_date, entry_date)) FROM paper_portfolio"
        ).fetchone()
        if r and r[0]:
            try:
                last = datetime.fromisoformat(r[0])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last).total_seconds() / 60
                out['last_trade_age_min'] = round(age, 1)
            except Exception:
                pass
        # Preis-Aktualität
        r = c.execute("SELECT MAX(date) FROM prices").fetchone()
        if r and r[0]:
            try:
                last = datetime.fromisoformat(r[0])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last).total_seconds() / 60
                out['price_freshness_min'] = round(age, 1)
            except Exception:
                pass
        c.close()
    except Exception as e:
        out['db_error'] = str(e)[:200]
    return out


def _heartbeat_age() -> float | None:
    try:
        raw = HEARTBEAT.read_text().strip()
        last = datetime.fromisoformat(raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - last).total_seconds(), 1)
    except Exception:
        return None


def _systemd_active() -> bool | None:
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', SERVICE],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() == 'active'
    except Exception:
        return None


def _disk_free_gb(path: Path = WS) -> float | None:
    try:
        total, used, free = shutil.disk_usage(str(path))
        return round(free / 1024 / 1024 / 1024, 2)
    except Exception:
        return None


def _ceo_halt() -> bool | None:
    try:
        d = json.loads(CEO.read_text(encoding='utf-8'))
        return bool(d.get('trading_halt', False))
    except Exception:
        return None


def _scheduler_errors_5min() -> int:
    """Zählt ERROR-Lines in scheduler.log der letzten 5 Minuten."""
    if not SCHED_LOG.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    count = 0
    try:
        # Nur die letzten ~500 Zeilen sampeln (schnell)
        with open(SCHED_LOG, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            tail = f.read().decode('utf-8', errors='replace').splitlines()
        iso_re = re.compile(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})')
        for line in tail[-500:]:
            if 'ERROR' not in line and 'CRITICAL' not in line:
                continue
            m = iso_re.search(line)
            if not m:
                continue
            try:
                ts = datetime.fromisoformat(m.group(1).replace(' ', 'T'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    count += 1
            except Exception:
                continue
    except Exception:
        pass
    return count


# ────────────────────────────────────────────────────────────────────────────
# Snapshot + Anomalie-Erkennung
# ────────────────────────────────────────────────────────────────────────────

def snapshot() -> dict:
    now = datetime.now(timezone.utc)
    snap = {
        'ts': now.isoformat(timespec='seconds'),
        'heartbeat_age_sec': _heartbeat_age(),
        'systemd_active': _systemd_active(),
        'disk_free_gb': _disk_free_gb(),
        'ceo_halt': _ceo_halt(),
        'scheduler_errors_5min': _scheduler_errors_5min(),
    }
    snap.update(_db_snapshot())

    flags = []
    hb = snap.get('heartbeat_age_sec')
    if hb is not None and hb > HEARTBEAT_MAX_AGE_SEC:
        flags.append('heartbeat_stale')
    if snap.get('systemd_active') is False:
        flags.append('systemd_inactive')
    if snap.get('disk_free_gb') is not None and snap['disk_free_gb'] < DISK_MIN_GB:
        flags.append('disk_low')
    if snap.get('scheduler_errors_5min', 0) >= SCHEDULER_ERROR_THRESHOLD:
        flags.append('scheduler_errors')
    if snap.get('ceo_halt') is True:
        flags.append('ceo_halt_active')
    nx = snap.get('null_exit_count')
    if nx is not None and nx > 0:
        flags.append('null_exits_present')
    snap['flags'] = flags
    return snap


def write_snapshot(snap: dict) -> None:
    OBS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(OBS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(snap, ensure_ascii=False) + '\n')


# ────────────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────────────

def summary(hours: int = 48) -> int:
    if not OBS_LOG.exists():
        print(f'Kein Log: {OBS_LOG}')
        return 1
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    with open(OBS_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                o = json.loads(line)
                ts = datetime.fromisoformat(o['ts'])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    rows.append(o)
            except Exception:
                continue
    if not rows:
        print(f'Keine Snapshots in den letzten {hours}h')
        return 1

    first, last = rows[0], rows[-1]
    n = len(rows)

    # Flag-Histogramm
    flag_counts: dict[str, int] = {}
    for r in rows:
        for f in r.get('flags', []):
            flag_counts[f] = flag_counts.get(f, 0) + 1

    # Heartbeat-Health
    hb_stale = sum(1 for r in rows if 'heartbeat_stale' in r.get('flags', []))
    sys_inactive = sum(1 for r in rows if 'systemd_inactive' in r.get('flags', []))

    # Fund-Werte
    fv_values = [r.get('fund_value_eur') for r in rows if r.get('fund_value_eur') is not None]
    fv_start = fv_values[0] if fv_values else None
    fv_end = fv_values[-1] if fv_values else None
    fv_min = min(fv_values) if fv_values else None
    fv_max = max(fv_values) if fv_values else None

    print(f'━━━ Observation Summary (last {hours}h) ━━━')
    print(f'Von {first["ts"]} bis {last["ts"]}')
    print(f'Snapshots: {n} (erwartet ~{hours * 12})')
    print()
    print(f'Fund-Value  start: {fv_start}€  end: {fv_end}€')
    print(f'            min:   {fv_min}€  max: {fv_max}€')
    print(f'Cash:       {last.get("cash_eur")}€')
    print(f'Positionen: {last.get("open_positions")}')
    print(f'DB:         {last.get("db_size_mb")} MB')
    print(f'Disk frei:  {last.get("disk_free_gb")} GB')
    print()
    print('── Health ──')
    print(f'Heartbeat stale:   {hb_stale}/{n}  ({hb_stale / n * 100:.1f}%)')
    print(f'Systemd inactive:  {sys_inactive}/{n}  ({sys_inactive / n * 100:.1f}%)')
    print(f'NULL-exits (last): {last.get("null_exit_count")}')
    print(f'Scheduler-Errors letzte 5min (last): {last.get("scheduler_errors_5min")}')
    print()
    if flag_counts:
        print('── Flags (Häufigkeit) ──')
        for f, c in sorted(flag_counts.items(), key=lambda x: -x[1]):
            print(f'  {f:30} {c:>4}')
    else:
        print('✅ Keine Flags — System sauber')
    print()

    # Gate-Entscheidung
    critical = ['heartbeat_stale', 'systemd_inactive', 'disk_low', 'scheduler_errors']
    criticals_hit = sum(flag_counts.get(f, 0) for f in critical)
    ratio = criticals_hit / max(1, n)
    print(f'── Pre-Flight Gate ──')
    print(f'Kritische Flags / Snapshots: {criticals_hit}/{n}  ({ratio * 100:.2f}%)')
    if ratio > 0.02:
        print('❌ NICHT BEREIT — > 2% kritische Flags')
        return 2
    if hb_stale > n * 0.05:
        print('❌ NICHT BEREIT — Heartbeat zu oft stale (>5%)')
        return 2
    print('✅ GRÜNES LICHT für 30d Autonomous Run')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary', nargs='?', type=int, const=48,
                    help='Auswertung der letzten N Stunden (Default 48)')
    args = ap.parse_args()

    if args.summary is not None:
        sys.exit(summary(args.summary))

    snap = snapshot()
    write_snapshot(snap)
    flags = snap.get('flags', [])
    marker = '⚠️ ' + ','.join(flags) if flags else '✅'
    print(f'[{snap["ts"]}] {marker}  fund={snap.get("fund_value_eur")}€  '
          f'open={snap.get("open_positions")}  hb={snap.get("heartbeat_age_sec")}s')


if __name__ == '__main__':
    main()
