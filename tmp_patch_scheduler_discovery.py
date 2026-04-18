#!/usr/bin/env python3
"""
Patch-Script C: Candidate Discovery Job in Scheduler hinzufügen
Ziel: /opt/trademind/scripts/scheduler_daemon.py

Fügt vor 'Daily Learning' in der JOBS-Liste ein:
    ('Candidate Discovery', 'core/candidate_discovery.py', [], 8, 15, [0,1,2,3,4,5,6]),  # 08:15 tägl.

Aufruf: python3 /tmp/tmp_patch_scheduler_discovery.py
"""
import sys
import py_compile
import tempfile
import os

TARGET = '/opt/trademind/scripts/scheduler_daemon.py'

# ─── Exakter OLD-String (match anhand des Daily Learning Eintrags) ─────────────

OLD_DAILY_LEARNING = "    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),"

NEW_WITH_DISCOVERY = """    ('Candidate Discovery', 'core/candidate_discovery.py', [], 8, 15, [0,1,2,3,4,5,6]),  # 08:15 tägl.
    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),"""

# Fallback: verschiedene Whitespace-Varianten des Daily Learning Eintrags
DAILY_LEARNING_VARIANTS = [
    "    ('Daily Learning',      'daily_learning_cycle.py', [],                        22, 45, None),",
    "    ('Daily Learning', 'daily_learning_cycle.py', [], 22, 45, None),",
]


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def verify_syntax(path):
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f'SYNTAX ERROR: {e}')
        return False


def main():
    if not os.path.exists(TARGET):
        raise SystemExit(f'FEHLER: Zieldatei nicht gefunden: {TARGET}')

    print(f'Lese {TARGET} ...')
    content = read_file(TARGET)

    # Idempotenz-Check
    sentinel = 'Candidate Discovery'
    if sentinel in content:
        print('SKIP — Candidate Discovery bereits im Scheduler vorhanden (idempotent).')
        sys.exit(0)

    # Exakter Match versuchen
    matched_old = None
    for variant in DAILY_LEARNING_VARIANTS:
        if variant in content:
            matched_old = variant
            break

    if matched_old is None:
        # Fuzzy-Suche: zeige was stattdessen da ist
        for line in content.splitlines():
            if 'Daily Learning' in line:
                print(f'  Gefunden: {repr(line)}')
        raise SystemExit(
            f'FEHLER: "Daily Learning" Zeile nicht in erwarteter Form gefunden in {TARGET}.\n'
            'Bitte obige Ausgabe prüfen und OLD-String anpassen.'
        )

    # Replacement aufbauen: gleiche Whitespace-Struktur wie gefundene Zeile behalten
    discovery_line = "    ('Candidate Discovery', 'core/candidate_discovery.py', [], 8, 15, [0,1,2,3,4,5,6]),  # 08:15 tägl."
    new_block = discovery_line + '\n' + matched_old

    new_content = content.replace(matched_old, new_block, 1)

    # Syntax-Check in temporärer Datei
    with tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8') as tmp:
        tmp.write(new_content)
        tmp_path = tmp.name

    try:
        if not verify_syntax(tmp_path):
            raise SystemExit('[FEHLER] Syntax-Check fehlgeschlagen — Datei NICHT geschrieben!')
    finally:
        os.unlink(tmp_path)

    write_file(TARGET, new_content)
    print(f'OK — {TARGET} erfolgreich gepatcht: Candidate Discovery um 08:15 täglich hinzugefügt.')


if __name__ == '__main__':
    main()
