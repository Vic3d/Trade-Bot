#!/usr/bin/env python3.13
"""
db_migrate_v2.py — TradeMind v2 Schema-Migration
=================================================
Fügt neue Tabellen hinzu (falls nicht vorhanden):
  - trade_tranches   : Tranche-Tracking für Teilverkäufe
  - thesis_status    : Thesen-Status-Tracking
  - thesis_checks    : Thesen-Monitoring-Log

Sicher: CREATE TABLE IF NOT EXISTS — keine Daten werden gelöscht.

Aufruf:
  python3.13 scripts/db_migrate_v2.py
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'execution'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

DB = WS / 'data' / 'trading.db'

MIGRATIONS = [
    # ── Tranche-Tracking für Teilverkäufe ─────────────────────────
    """
    CREATE TABLE IF NOT EXISTS trade_tranches (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id    INTEGER NOT NULL,
        tranche_nr  INTEGER NOT NULL,
        shares      REAL    NOT NULL,
        entry_price REAL    NOT NULL,
        exit_price  REAL,
        exit_date   TEXT,
        exit_reason TEXT,
        pnl_eur     REAL,
        status      TEXT DEFAULT 'OPEN'
    )
    """,

    # ── Thesen-Status-Tracking ─────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS thesis_status (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        thesis_id           TEXT NOT NULL,
        status              TEXT NOT NULL,
        health_score        INTEGER DEFAULT 100,
        kill_trigger_fired  INTEGER DEFAULT 0,
        last_checked        TEXT,
        last_news_bullish   TEXT,
        last_news_bearish   TEXT,
        notes               TEXT,
        updated_at          TEXT
    )
    """,

    # ── Thesen-Monitoring-Log ──────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS thesis_checks (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        thesis_id           TEXT,
        checked_at          TEXT,
        news_headline       TEXT,
        direction           TEXT,
        kill_trigger_match  INTEGER DEFAULT 0,
        action_taken        TEXT
    )
    """,
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_trade_tranches_trade_id ON trade_tranches(trade_id)",
    "CREATE INDEX IF NOT EXISTS idx_trade_tranches_status ON trade_tranches(status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_thesis_status_id ON thesis_status(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_thesis_checks_thesis_id ON thesis_checks(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_thesis_checks_at ON thesis_checks(checked_at)",
]


def run_migration():
    """Führt alle Migrations-Statements aus."""
    if not DB.exists():
        print(f"FEHLER: DB nicht gefunden: {DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    created = []
    errors = []

    for stmt in MIGRATIONS:
        table_name = None
        try:
            # Tabellennamen aus Statement extrahieren (für Logging)
            for token in stmt.split():
                if token.upper() == 'EXISTS':
                    continue
            words = stmt.strip().split()
            for i, w in enumerate(words):
                if w.upper() == 'EXISTS' and i + 1 < len(words):
                    table_name = words[i + 1].strip('(')
                    break

            conn.execute(stmt)
            conn.commit()
            created.append(table_name or 'unknown')
        except Exception as e:
            errors.append((table_name or 'unknown', str(e)))

    for stmt in INDEX_STATEMENTS:
        try:
            conn.execute(stmt)
            conn.commit()
        except Exception as e:
            errors.append(('index', str(e)))

    conn.close()

    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{ts}] TradeMind v2 Migration abgeschlossen")
    print(f"  Tabellen verarbeitet : {len(created)}")
    if created:
        for t in created:
            print(f"    OK: {t}")
    if errors:
        print(f"  Fehler ({len(errors)}):")
        for t, e in errors:
            print(f"    FEHLER [{t}]: {e}")
        sys.exit(1)
    else:
        print("  Alle Statements erfolgreich.")


def verify_tables():
    """Prüft ob alle erwarteten Tabellen existieren."""
    expected = ['trade_tranches', 'thesis_status', 'thesis_checks']
    conn = sqlite3.connect(str(DB))
    existing = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    missing = [t for t in expected if t not in existing]
    if missing:
        print(f"FEHLER: Tabellen fehlen noch: {missing}")
        return False
    print(f"  Verifikation OK: {expected}")
    return True


if __name__ == '__main__':
    run_migration()
    verify_tables()
