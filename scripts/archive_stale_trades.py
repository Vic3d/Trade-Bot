#!/usr/bin/env python3
"""
Archive Stale Trades — Phase 5.6
=================================
Verschiebt historische Trades von NICHT MEHR AKTIVEN Strategien in eine
Archiv-Tabelle, damit sie Stats (Win-Rate, Strategy-Scores, Learning) nicht
mehr verfälschen.

Zielgruppe:
  - AR-AGRA, AR-HALB (permanent geblockt seit CLAUDE.md)
  - DT1-DT5 (Day-Trade Strategien, alle suspended)
  - PS_STLD, S4 (historische Bulk-Trade-Bugs, nicht mehr aktiv)
  - S10-TEST (Test-Runs, pnl_eur=0)

Archiv bleibt queryable aber wird von learning/stats excluded.

Idempotent. Fügt archived_at Timestamp an Original an.

Usage:
  python3 scripts/archive_stale_trades.py             # Run
  python3 scripts/archive_stale_trades.py --dry-run   # Zeigen
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'

# Permanent-geblockte oder explizit-historische Strategien
STALE_STRATEGIES = {
    # Auto-Rotation (permanent geblockt)
    'AR-AGRA', 'AR-HALB', 'AR-',
    # Day Trades (permanent suspended — siehe CLAUDE.md)
    'DT1', 'DT2', 'DT3', 'DT4', 'DT5', 'DT6', 'DT7', 'DT8', 'DT9',
    # Historische Bulk-Trade-Bugs (nicht mehr aktiv — alle exit_type=NULL)
    'PS_STLD', 'S4',
    # Test-Runs
    'S10-TEST', 'new',
}


def _matches_stale(strategy: str | None) -> bool:
    if not strategy:
        return False
    s = strategy.upper().strip()
    if s in STALE_STRATEGIES:
        return True
    # Prefix-Match für AR-* und DT* variants
    if s.startswith('AR-') or s.startswith('DT'):
        return True
    return False


def setup_archive_table(conn: sqlite3.Connection) -> None:
    """Klone paper_portfolio-Schema für Archiv."""
    cols = conn.execute('PRAGMA table_info(paper_portfolio)').fetchall()
    col_defs = []
    for c in cols:
        # c = (cid, name, type, notnull, default, pk)
        d = f'{c[1]} {c[2]}'
        if c[3]:
            d += ' NOT NULL'
        if c[4] is not None:
            d += f' DEFAULT {c[4]}'
        if c[5]:
            d += ' PRIMARY KEY'
        col_defs.append(d)
    col_defs.append('archived_at TEXT')
    col_defs.append('archive_reason TEXT')
    ddl = f"CREATE TABLE IF NOT EXISTS paper_portfolio_archive ({', '.join(col_defs)})"
    conn.execute(ddl)
    conn.commit()


def _is_bulk_bug_trade(row) -> bool:
    """
    Erkennt Bulk-Bug-Trades aus der Anfangsphase:
      - exit_type IS NULL (kein normaler Exit-Pfad)
      - entry_date zwischen 07:00 und 07:30 UTC (bulk-entry direkt vor US-Pre-Market)
      - close_date innerhalb von 2h nach entry (bulk-closure)
    Das sind die pre-Morgen-Block-Trades die von Guard 0a nicht erfasst wurden.
    """
    id_, ticker, strat, status, pnl, entry_date, close_date, exit_type = row
    if exit_type is not None and exit_type != '':
        return False
    if str(status).upper() != 'CLOSED':
        return False
    if not entry_date:
        return False
    # Entry-Zeit-Check: 07:00-07:30 UTC (09:00-09:30 CET = Morgen-Block)
    ed = str(entry_date)
    # Format kann '2026-04-02T07:15:46' oder '2026-04-02 07:15:46' sein
    if 'T' in ed:
        time_part = ed.split('T', 1)[1][:5]
    elif ' ' in ed:
        time_part = ed.split(' ', 1)[1][:5]
    else:
        return False
    try:
        hh, mm = time_part.split(':')
        h, m = int(hh), int(mm)
    except Exception:
        return False
    return h == 7 and 0 <= m <= 30  # 07:00-07:30 UTC bulk window


def run(dry_run: bool = False) -> dict:
    conn = sqlite3.connect(str(DB))
    setup_archive_table(conn)

    # Kandidaten identifizieren (stale strategy OR bulk-bug)
    rows = conn.execute(
        "SELECT id, ticker, strategy, status, pnl_eur, entry_date, close_date, exit_type "
        "FROM paper_portfolio"
    ).fetchall()

    to_archive = []
    for r in rows:
        id_, ticker, strat, status, pnl, entry_date, close_date, exit_type = r
        is_stale = _matches_stale(strat)
        is_bulk = _is_bulk_bug_trade(r)
        if is_stale or is_bulk:
            to_archive.append({
                'id': id_, 'ticker': ticker, 'strategy': strat,
                'status': status, 'pnl': pnl or 0,
                'reason': 'stale_strategy' if is_stale else 'bulk_bug_morning',
            })

    stats = {
        'total_candidates': len(to_archive),
        'closed_archived':  sum(1 for x in to_archive if str(x['status']).upper()=='CLOSED'),
        'open_skipped':     sum(1 for x in to_archive if str(x['status']).upper()=='OPEN'),
        'pnl_removed':      sum(x['pnl'] for x in to_archive
                                if str(x['status']).upper()=='CLOSED'),
    }

    # Nur CLOSED archivieren — offene Trades nicht anfassen
    closed_ids = [x['id'] for x in to_archive if str(x['status']).upper()=='CLOSED']

    print('=== Archive Stale Trades ===')
    print(f'Kandidaten total:   {stats["total_candidates"]}')
    print(f'  → CLOSED (archive): {stats["closed_archived"]}')
    print(f'  → OPEN (skip):      {stats["open_skipped"]}')
    print(f'P&L removed from stats: {stats["pnl_removed"]:+.2f}€')

    # Aufsplittung nach Grund
    by_reason = {}
    for x in to_archive:
        by_reason.setdefault(x['reason'], []).append(x)
    print('\nBy reason:')
    for k, items in sorted(by_reason.items()):
        closed = sum(1 for i in items if str(i['status']).upper()=='CLOSED')
        pnl_sum = sum(i['pnl'] for i in items if str(i['status']).upper()=='CLOSED')
        print(f'  {k:25} {closed:2d} closed, P&L: {pnl_sum:+8.2f}€')

    by_strat = {}
    for x in to_archive:
        k = x['strategy']
        by_strat.setdefault(k, []).append(x)
    print('\nBy strategy:')
    for k, items in sorted(by_strat.items()):
        closed = sum(1 for i in items if str(i['status']).upper()=='CLOSED')
        pnl_sum = sum(i['pnl'] for i in items if str(i['status']).upper()=='CLOSED')
        print(f'  {k:15} {closed:2d} closed, P&L: {pnl_sum:+8.2f}€')

    if dry_run:
        print('\n[DRY-RUN]')
        conn.close()
        return stats

    if not closed_ids:
        print('\nNichts zu archivieren.')
        conn.close()
        return stats

    # Copy to archive
    ts = datetime.now(_BERLIN).isoformat(timespec='seconds')
    placeholders = ','.join('?' * len(closed_ids))
    reason = 'stale strategy (permanently blocked or test data)'

    cols = [c[1] for c in conn.execute('PRAGMA table_info(paper_portfolio)')]
    col_list = ', '.join(cols)
    conn.execute(f"""
        INSERT INTO paper_portfolio_archive ({col_list}, archived_at, archive_reason)
        SELECT {col_list}, ?, ? FROM paper_portfolio WHERE id IN ({placeholders})
    """, (ts, reason, *closed_ids))

    conn.execute(
        f"DELETE FROM paper_portfolio WHERE id IN ({placeholders})",
        closed_ids,
    )
    conn.commit()

    # Verify
    after = conn.execute("SELECT COUNT(*) FROM paper_portfolio").fetchone()[0]
    archived = conn.execute("SELECT COUNT(*) FROM paper_portfolio_archive").fetchone()[0]
    print(f'\n✅ {len(closed_ids)} Trades archiviert')
    print(f'   paper_portfolio:         {after} trades remaining')
    print(f'   paper_portfolio_archive: {archived} trades archived')

    conn.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
