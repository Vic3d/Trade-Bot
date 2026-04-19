#!/usr/bin/env python3
"""
Clean-Slate Reset fuer den 30d-Autonomous-Run.
====================================================
1. ALTER TABLE: archived_pre_reset INTEGER DEFAULT 0
2. Markiere alle existierenden Trades als archived_pre_reset=1
3. Reset paper_fund.current_cash auf 25000
4. Setze paper_fund.total_realized_pnl auf 0
5. Schreibe data/run_start.txt = 2026-04-17
6. Die 2 offenen Positionen (MUV2.DE, OXY) bleiben OPEN aber archived=1
   → sie werden NICHT im 30d-Score gezaehlt, aber Trailing-Stops laufen weiter
"""
import sqlite3
import json
from pathlib import Path
from datetime import date

DB = "/opt/trademind/data/trading.db"
WS = Path("/opt/trademind")

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

# 1. Column hinzufuegen
cols = [r[1] for r in c.execute("PRAGMA table_info(paper_portfolio)").fetchall()]
if "archived_pre_reset" not in cols:
    c.execute("ALTER TABLE paper_portfolio ADD COLUMN archived_pre_reset INTEGER DEFAULT 0")
    print("[1] archived_pre_reset column added")
else:
    print("[1] archived_pre_reset column already exists")

# 2. Snapshot BEFORE
before = c.execute("SELECT COUNT(*), SUM(pnl_eur) FROM paper_portfolio").fetchone()
print(f"[2] BEFORE: {before[0]} trades, P&L Summe {before[1] or 0:+.0f}E")

# 3. Alle existierenden als archived markieren
cur = c.execute("UPDATE paper_portfolio SET archived_pre_reset=1 WHERE archived_pre_reset=0")
n = cur.rowcount
print(f"[3] Markiert {n} trades als archived_pre_reset=1")

# 4. Fund Reset
old_cash = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()[0]
old_pnl = c.execute("SELECT value FROM paper_fund WHERE key='total_realized_pnl'").fetchone()[0]
c.execute("UPDATE paper_fund SET value=25000.0 WHERE key='current_cash'")
c.execute("UPDATE paper_fund SET value=0.0 WHERE key='total_realized_pnl'")
print(f"[4] Fund reset: cash {old_cash:.2f}E -> 25000E, pnl {old_pnl:.2f}E -> 0E")

# 5. Open positions check
open_rows = c.execute(
    "SELECT ticker, strategy, entry_price, shares, entry_date, archived_pre_reset "
    "FROM paper_portfolio WHERE status='OPEN'"
).fetchall()
print(f"\n[5] Offene Positionen (bleiben OPEN, archived=1):")
for r in open_rows:
    print(f"    {r['ticker']:10} {r['strategy']:12} entry={r['entry_price']} shares={r['shares']} archived={r['archived_pre_reset']}")

c.commit()
c.close()

# 6. Run-Start-Marker auf heute
(WS / 'data' / 'run_start.txt').write_text('2026-04-17')
print(f"[6] run_start.txt = 2026-04-17")

# 7. Verify
c2 = sqlite3.connect(DB)
n_arch = c2.execute("SELECT COUNT(*) FROM paper_portfolio WHERE archived_pre_reset=1").fetchone()[0]
n_new = c2.execute("SELECT COUNT(*) FROM paper_portfolio WHERE archived_pre_reset=0").fetchone()[0]
cash_new = c2.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()[0]
pnl_new = c2.execute("SELECT value FROM paper_fund WHERE key='total_realized_pnl'").fetchone()[0]
c2.close()
print(f"\n[7] VERIFY: archived={n_arch}, new={n_new}, cash={cash_new}, realized_pnl={pnl_new}")
print("\nCLEAN SLATE READY. Tag 1 des 30d-Autonomous-Runs startet jetzt.")
