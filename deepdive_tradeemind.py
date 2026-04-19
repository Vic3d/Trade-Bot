#!/usr/bin/env python3
"""Deep Dive auf das Trade-Bot-System selbst."""
import sqlite3, json, re
from pathlib import Path
from collections import Counter

c = sqlite3.connect("/opt/trademind/data/trading.db")
c.row_factory = sqlite3.Row

total = c.execute("SELECT COUNT(*) FROM paper_portfolio").fetchone()[0]
closed = c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED')").fetchone()[0]
open_ = c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
wins = c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='WIN'").fetchone()[0]
losses = c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='LOSS'").fetchone()[0]
print(f"Total: {total} | Closed: {closed} (WIN {wins}/LOSS {losses}) | Open: {open_}")

src = c.execute("SELECT COALESCE(score_source,'unknown') s, COUNT(*) FROM paper_portfolio GROUP BY s ORDER BY 2 DESC").fetchall()
print("\nSources:")
for r in src:
    print(f"  {r[0]:30} {r[1]}")

auto = c.execute("SELECT COUNT(*) FROM paper_portfolio WHERE score_source='CONVICTION_V3'").fetchone()[0]
print(f"\nAutonome (CONVICTION_V3): {auto}/{total}")

pnl_total = c.execute("SELECT SUM(pnl_eur) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED')").fetchone()[0] or 0
pnl_30d = c.execute("SELECT SUM(pnl_eur) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED') AND close_date >= date('now','-30 days')").fetchone()[0] or 0
pnl_7d = c.execute("SELECT SUM(pnl_eur) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED') AND close_date >= date('now','-7 days')").fetchone()[0] or 0
print(f"\nP&L total: {pnl_total:+.0f}E | 30d: {pnl_30d:+.0f}E | 7d: {pnl_7d:+.0f}E")

# P&L by source
pnl_by_src = c.execute("SELECT COALESCE(score_source,'unknown'), SUM(pnl_eur), COUNT(*) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED') GROUP BY score_source ORDER BY 2 DESC").fetchall()
print("\nP&L by source:")
for r in pnl_by_src:
    print(f"  {r[0]:30} {r[1] or 0:+9.0f}E ({r[2]} trades)")

# Exit-Type-Distribution
xt = c.execute("SELECT COALESCE(exit_type,'<null>') x, COUNT(*), SUM(pnl_eur) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED') GROUP BY x ORDER BY 2 DESC").fetchall()
print("\nExit-Types:")
for r in xt:
    print(f"  {r[0][:40]:40} {r[1]:>4} {r[2] or 0:+9.0f}E")

try:
    dd = json.loads(Path("/opt/trademind/data/deep_dive_verdicts.json").read_text())
    kaufen = sum(1 for t,v in dd.items() if isinstance(v,dict) and v.get('verdict')=='KAUFEN')
    warten = sum(1 for t,v in dd.items() if isinstance(v,dict) and v.get('verdict')=='WARTEN')
    nichtk = sum(1 for t,v in dd.items() if isinstance(v,dict) and v.get('verdict')=='NICHT_KAUFEN')
    print(f"\nDeep Dive Verdicts: KAUFEN {kaufen} / WARTEN {warten} / NICHT_KAUFEN {nichtk}")
except Exception as e:
    print(f"dd verdicts err: {e}")

try:
    s = json.loads(Path("/opt/trademind/data/strategies.json").read_text())
    active = sum(1 for k,v in s.items() if isinstance(v,dict) and v.get('status')!='SUSPENDED')
    susp = sum(1 for k,v in s.items() if isinstance(v,dict) and v.get('status')=='SUSPENDED')
    print(f"Strategien: {active} aktiv, {susp} suspended")
except Exception as e:
    print(f"strategies err: {e}")

# Guard-Blocks
block_counts = Counter()
try:
    log = Path("/opt/trademind/data/scheduler.log").read_text(errors='replace').split("\n")[-5000:]
    for line in log:
        m = re.search(r"blocked_by['\":= ]+([a-z_0-9]+)", line)
        if m:
            block_counts[m.group(1)] += 1
except Exception as e:
    print(f"logs err: {e}")
print("\nGuard-Blocks (letzte 5000 Log-Zeilen):")
for g, n in block_counts.most_common(15):
    print(f"  {g:35} {n}")

# Scripts Count
scripts = list(Path("/opt/trademind/scripts").rglob("*.py"))
print(f"\nPython-Scripts: {len(scripts)}")
print(f"Data-DB-Size: {Path('/opt/trademind/data/trading.db').stat().st_size/1024/1024:.1f} MB")

# Offene Positionen
pos = c.execute("SELECT ticker, strategy, entry_price, shares, sector, entry_date FROM paper_portfolio WHERE status='OPEN'").fetchall()
print("\nOffene Positionen:")
for p in pos:
    print(f"  {p[0]:10} {p[1]:12} sector={p[4]} entry={p[2]} shares={p[3]} date={p[5]}")

c.close()
