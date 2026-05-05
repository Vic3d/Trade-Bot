#!/usr/bin/env python3
"""
tool_usage_tracker.py — Phase 45m: Tool-Inventur ueber 30 Tage.

User-Direktive Victor 2026-05-05: "Schau in den naechsten 30 Tagen welche
Tools benutzt werden und welche nicht."

Mechanik:
  - Einmal taeglich (Scheduler 23:50) wird jedes Skript in scripts/*.py
    inventarisiert: wann wurde es zuletzt invoked? (via systemd-Journal,
    process-listing, log-mtime).
  - Output: data/tool_usage_inventory.jsonl — eine Zeile pro Tag mit
    pro-Skript-Status (used_in_24h, last_invoked_at, last_log_modified).
  - Am 30.-Tage-Termin (04.06) liefert summarize() einen Bericht:
    * top-10 used scripts
    * scripts mit 0 invocations in 30d → Kandidaten fuer Archiv

Quellen pro Skript:
  1. journalctl --user -u trademind-scheduler | grep <script>
  2. data/scheduler.log (text-grep)
  3. zugehoerige Log/Output-Datei mtime (data/<script-prefix>*.json/jsonl)

Defensiv: bei Fehler einzelner Quellen wird die naechste probiert.
Skript ohne klare Spur landet als 'unknown'.

CLI:
  python3 scripts/tool_usage_tracker.py            # Run inventory now
  python3 scripts/tool_usage_tracker.py --report   # 30d-Summary
"""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
SCRIPTS = WS / 'scripts'
INVENTORY = WS / 'data' / 'tool_usage_inventory.jsonl'
SCHEDULER_LOG = WS / 'data' / 'scheduler.log'


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _list_scripts() -> list[str]:
    """Alle .py in scripts/ (rekursiv, ohne _archive, ohne hooks)."""
    out = []
    for p in SCRIPTS.rglob('*.py'):
        rel = p.relative_to(SCRIPTS).as_posix()
        if rel.startswith('_archive/'): continue
        if rel.startswith('hooks/'): continue
        if rel.startswith('__pycache__'): continue
        out.append(rel)
    return sorted(out)


def _grep_scheduler_log(script_name: str, since_hours: int = 24) -> str | None:
    """Sucht im scheduler.log nach Zeilen die das Skript erwaehnen."""
    if not SCHEDULER_LOG.exists(): return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    last_line = None
    try:
        with open(SCHEDULER_LOG, encoding='utf-8', errors='replace') as f:
            for line in f:
                if script_name in line:
                    last_line = line.strip()
        return last_line
    except Exception:
        return None


def _journal_check(script_name: str, since_hours: int = 24) -> str | None:
    """journalctl scan (Linux only)."""
    try:
        proc = subprocess.run(
            ['journalctl', '-u', 'trademind-scheduler',
             f'--since={since_hours} hours ago', '--no-pager', '-q'],
            capture_output=True, text=True, timeout=8,
        )
        for line in proc.stdout.splitlines()[::-1]:
            if script_name in line:
                return line.strip()[:200]
    except Exception:
        return None
    return None


def _related_log_mtime(script_rel: str) -> str | None:
    """Suche eine zugehoerige Log/JSON-Datei und nutze deren mtime."""
    base = Path(script_rel).stem
    candidates = [
        WS / 'data' / f'{base}.log',
        WS / 'data' / f'{base}.json',
        WS / 'data' / f'{base}.jsonl',
        WS / 'data' / f'{base}_log.jsonl',
        WS / 'data' / f'{base}_results.json',
    ]
    for c in candidates:
        if c.exists():
            try:
                mt = datetime.fromtimestamp(c.stat().st_mtime, timezone.utc)
                return mt.isoformat(timespec='seconds')
            except Exception:
                continue
    return None


def inventory() -> dict:
    """Heutiger Snapshot: pro Skript Status-Eintrag."""
    scripts = _list_scripts()
    snap = {
        'ts': _now_utc(),
        'date': datetime.now(timezone.utc).date().isoformat(),
        'n_scripts_total': len(scripts),
        'scripts': {},
    }
    used_24h = 0
    for s in scripts:
        name = Path(s).name
        log_hit = _grep_scheduler_log(name, 24)
        journal_hit = _journal_check(name, 24)
        log_mtime = _related_log_mtime(s)
        used = bool(log_hit or journal_hit)
        if used: used_24h += 1
        snap['scripts'][s] = {
            'used_24h': used,
            'last_log_line': log_hit[:140] if log_hit else None,
            'journal_hit_excerpt': journal_hit[:140] if journal_hit else None,
            'related_log_mtime': log_mtime,
        }
    snap['n_scripts_used_24h'] = used_24h
    snap['pct_used'] = round(100.0 * used_24h / max(len(scripts), 1), 1)
    return snap


def append_snapshot(snap: dict) -> None:
    INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(INVENTORY, 'a', encoding='utf-8') as f:
        f.write(json.dumps(snap, ensure_ascii=False, default=str) + '\n')


def summarize_30d() -> dict:
    """Aggregiert die letzten 30 Snapshots."""
    if not INVENTORY.exists():
        return {'error': 'no inventory yet'}
    rows = []
    with open(INVENTORY, encoding='utf-8') as f:
        for line in f:
            try: rows.append(json.loads(line))
            except Exception: continue
    rows = rows[-30:]
    if not rows:
        return {'error': 'no rows'}

    # Per-script: in wie vielen der letzten 30 Tage benutzt?
    usage_count: dict[str, int] = {}
    for r in rows:
        for s, info in (r.get('scripts') or {}).items():
            if info.get('used_24h'):
                usage_count[s] = usage_count.get(s, 0) + 1

    all_scripts = set()
    for r in rows:
        all_scripts.update((r.get('scripts') or {}).keys())

    never_used = [s for s in all_scripts if usage_count.get(s, 0) == 0]
    daily_used = [s for s in all_scripts if usage_count.get(s, 0) >= len(rows) * 0.8]

    top = sorted(usage_count.items(), key=lambda x: -x[1])[:15]

    return {
        'days_analyzed': len(rows),
        'first_day': rows[0].get('date'),
        'last_day': rows[-1].get('date'),
        'n_scripts_total': len(all_scripts),
        'never_used_30d': sorted(never_used),
        'daily_used': sorted(daily_used),
        'top_15_used': top,
    }


def main() -> int:
    if '--report' in sys.argv:
        rep = summarize_30d()
        print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
        return 0
    snap = inventory()
    append_snapshot(snap)
    print(f"[{snap['date']}] {snap['n_scripts_used_24h']}/{snap['n_scripts_total']} "
          f"scripts used in last 24h ({snap['pct_used']}%)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
