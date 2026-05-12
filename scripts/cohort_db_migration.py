#!/usr/bin/env python3
"""
cohort_db_migration.py — Phase 45at (Victor 2026-05-12).

Einmaliges Migration-Script für Parallel-Kohorten-Trading.
  1. Erstellt Tabelle paper_cohorts
  2. Fügt cohort_id-Spalte zu paper_portfolio hinzu
  3. Backfillt Mai-2026-Kohorte (alle existing OPEN trades + aktueller Cash)
  4. Aggression-Profil Mai = aktuelle Defaults (Risk 1%, Kelly 5%)

Idempotent: kann mehrfach laufen ohne zu beschädigen.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
FUND_FILE = WS / 'data' / 'paper_fund.json'


def migrate() -> dict:
    if not DB.exists():
        return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    changes = []

    # 1. paper_cohorts Tabelle erstellen
    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_cohorts (
            cohort_id TEXT PRIMARY KEY,
            started_at TIMESTAMP NOT NULL,
            initial_capital_eur REAL NOT NULL,
            current_cash_eur REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            aggression_profile TEXT NOT NULL,
            sector_cap_pct REAL NOT NULL DEFAULT 0.35,
            parent_cohort_id TEXT,
            min_lifetime_until DATE,
            notes TEXT
        )
    """)
    changes.append('table_paper_cohorts_created')

    # 2. cohort_id zu paper_portfolio
    cols = [row[1] for row in c.execute("PRAGMA table_info(paper_portfolio)").fetchall()]
    if 'cohort_id' not in cols:
        c.execute("ALTER TABLE paper_portfolio ADD COLUMN cohort_id TEXT")
        changes.append('cohort_id_column_added')

    # 3. Mai-Kohorte backfillen
    mai = c.execute("SELECT cohort_id FROM paper_cohorts WHERE cohort_id='2026-05'").fetchone()
    if not mai:
        cash = 25000.0
        if FUND_FILE.exists():
            try:
                f = json.loads(FUND_FILE.read_text(encoding='utf-8'))
                cash = float(f.get('cash', 25000))
            except Exception: pass

        # Mai-Profil = aktuelle Defaults
        profile = {
            'risk_per_trade': 0.01,
            'kelly_cap': 0.05,
            'max_absolute_eur': 2500,
            'max_trades_per_week': 7,
        }
        # Ende 2026-04 als virtueller "Start" für Mai
        from datetime import datetime as _dt
        started = '2026-05-01T00:00:00+02:00'
        min_lifetime = '2027-05-01'  # 1 Jahr Mindest-Lifetime
        c.execute("""
            INSERT INTO paper_cohorts
            (cohort_id, started_at, initial_capital_eur, current_cash_eur,
             status, aggression_profile, sector_cap_pct, parent_cohort_id,
             min_lifetime_until, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('2026-05', started, 25000.0, cash, 'ACTIVE',
              json.dumps(profile), 0.35, None, min_lifetime,
              'Mai-Kohorte: erste Kohorte (backfilled). Migrations-Generation.'))
        changes.append(f'cohort_2026-05_created_cash_{cash:.0f}')

    # 4. Alle bestehenden OPEN trades → Mai-Kohorte
    affected = c.execute(
        "UPDATE paper_portfolio SET cohort_id='2026-05' "
        "WHERE cohort_id IS NULL"
    ).rowcount
    changes.append(f'backfill_trades_to_mai_{affected}')

    c.commit()

    # Verify
    summary = {
        'changes': changes,
        'cohorts': [dict(r) for r in c.execute("SELECT * FROM paper_cohorts").fetchall()],
        'trades_per_cohort': dict(c.execute(
            "SELECT cohort_id, COUNT(*) FROM paper_portfolio "
            "WHERE status='OPEN' GROUP BY cohort_id"
        ).fetchall()),
    }
    c.close()
    return summary


def main() -> int:
    r = migrate()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
