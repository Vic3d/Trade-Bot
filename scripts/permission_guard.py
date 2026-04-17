#!/usr/bin/env python3
"""
Permission Guard — Phase 22.1
================================
Verhindert Permission-Drift: Wenn ein Script als root oder anderer User
Dateien in data/ oder memory/ erzeugt, gehoeren sie dem falschen Owner und
spaetere Scheduler-Jobs (die als `trademind` laufen) crashen mit EACCES.

Dieser Guard chownt alle Files in data/ und memory/ auf trademind:trademind,
falls sie einem anderen User gehoeren. Laeuft nur auf Linux/VPS. Auf Windows
ist er ein No-Op.

Aufruf aus Scheduler alle 15 Minuten oder bei Bedarf manuell:
  sudo python3 scripts/permission_guard.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
TARGETS = [WS / 'data', WS / 'memory']

EXPECTED_USER = 'trademind'
EXPECTED_GROUP = 'trademind'


def main() -> int:
    if sys.platform == 'win32':
        print('[perm-guard] Windows → No-Op')
        return 0
    try:
        import pwd
        import grp
    except ImportError:
        print('[perm-guard] pwd/grp nicht verfuegbar')
        return 0

    try:
        uid = pwd.getpwnam(EXPECTED_USER).pw_uid
        gid = grp.getgrnam(EXPECTED_GROUP).gr_gid
    except KeyError:
        print(f'[perm-guard] User {EXPECTED_USER} nicht gefunden — skip')
        return 0

    fixed = 0
    scanned = 0
    for root in TARGETS:
        if not root.exists():
            continue
        for p in root.rglob('*'):
            # Git-Interna ueberspringen
            if '.git' in p.parts:
                continue
            try:
                st = p.stat()
                scanned += 1
                if st.st_uid != uid or st.st_gid != gid:
                    try:
                        os.chown(p, uid, gid)
                        fixed += 1
                    except PermissionError:
                        # Wenn wir selbst nicht root sind, geht es nicht
                        pass
            except (FileNotFoundError, OSError):
                continue

    print(f'[perm-guard] scanned={scanned} fixed={fixed}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
