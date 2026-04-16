#!/usr/bin/env python3
"""
DB Backup — Phase 7.8
======================
Täglicher Backup von trading.db mit SQLite .backup command (safe
während gleichzeitiger Writes vom Scheduler).

  - Ziel: /opt/trademind/backups/trading-YYYY-MM-DD.db
  - Retention: 14 Tage (ältere werden gelöscht)
  - Integrity-Check nach Backup (PRAGMA integrity_check)
  - Discord-Alert bei Fehler

Cron (als trademind user): täglich 02:15 CET
  15 2 * * * /opt/trademind/venv/bin/python3 /opt/trademind/scripts/db_backup.py >> /opt/trademind/data/db_backup.log 2>&1

Usage:
  python3 scripts/db_backup.py
  python3 scripts/db_backup.py --verify   # auch bestehende Backups checken
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
BACKUP_DIR = WS / 'backups'
RETENTION_DAYS = 14

sys.path.insert(0, str(WS / 'scripts'))


def _discord(msg: str) -> None:
    try:
        from discord_sender import send
        send(msg)
    except Exception as e:
        print(f'Discord fail: {e}', file=sys.stderr)


def _integrity_check(db_path: Path) -> tuple[bool, str]:
    try:
        c = sqlite3.connect(str(db_path))
        r = c.execute('PRAGMA integrity_check').fetchone()
        c.close()
        ok = bool(r and r[0] == 'ok')
        return ok, r[0] if r else 'empty'
    except Exception as e:
        return False, str(e)[:200]


def _copy_via_backup_api(src: Path, dst: Path) -> None:
    """Nutzt sqlite3 .backup — safe während Writes."""
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _rotate(retention_days: int) -> list[str]:
    """Löscht Backups älter als retention_days. Gibt Namen zurück."""
    cutoff = date.today() - timedelta(days=retention_days)
    removed = []
    for p in BACKUP_DIR.glob('trading-*.db'):
        try:
            # Filename trading-YYYY-MM-DD.db
            stem = p.stem  # trading-YYYY-MM-DD
            d_str = stem.split('trading-', 1)[1]
            d = datetime.strptime(d_str, '%Y-%m-%d').date()
            if d < cutoff:
                p.unlink()
                removed.append(p.name)
        except Exception:
            # Unbekanntes Format — lassen
            continue
    return removed


def run(verify: bool = False) -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    target = BACKUP_DIR / f'trading-{today}.db'

    # 1) Backup erstellen
    print(f'[{datetime.now().isoformat(timespec="seconds")}] Backup: {DB} → {target}')
    try:
        if target.exists():
            target.unlink()  # Idempotent: gleiches Datum überschreibt
        _copy_via_backup_api(DB, target)
    except Exception as e:
        msg = f'🚨 **DB-Backup fehlgeschlagen**: {e}'
        print(msg)
        _discord(msg)
        return 1

    size_mb = target.stat().st_size / 1024 / 1024

    # 2) Integrity-Check
    ok, details = _integrity_check(target)
    if not ok:
        msg = f'🚨 **DB-Backup corrupt**: {target.name} — {details}'
        print(msg)
        _discord(msg)
        target.unlink(missing_ok=True)
        return 1

    # 3) Rotation
    removed = _rotate(RETENTION_DAYS)

    # 4) Optional: Alle Backups verifizieren
    verify_results = []
    if verify:
        for p in sorted(BACKUP_DIR.glob('trading-*.db')):
            vok, vdet = _integrity_check(p)
            verify_results.append((p.name, vok, vdet))
            mark = '✅' if vok else '❌'
            print(f'  {mark} {p.name} — {vdet}')

    current_backups = sorted(BACKUP_DIR.glob('trading-*.db'))
    print(f'✅ Backup OK: {size_mb:.1f} MB')
    print(f'   Removed (retention {RETENTION_DAYS}d): {len(removed)} files')
    print(f'   Total backups: {len(current_backups)}')

    if verify and any(not v[1] for v in verify_results):
        _discord(f'⚠️ {sum(1 for v in verify_results if not v[1])} corrupt backup(s) gefunden')
        return 2

    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='Alle Backups integrity-checken')
    args = ap.parse_args()
    sys.exit(run(verify=args.verify))


if __name__ == '__main__':
    main()
