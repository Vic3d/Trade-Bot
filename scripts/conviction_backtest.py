#!/usr/bin/env python3
"""
Conviction Score Backtest — Phase 7.2
=======================================
Analysiert historische Trades nach Conviction Score Buckets.

Fragt: "Welcher Entry-Threshold hätte die besten Ergebnisse geliefert?"
  - Bucket <45:   Trades die geblockt worden wären (Threshold-Check)
  - Bucket 45-55: Grenzfälle
  - Bucket 55+:   High-Conviction

Output:
  - data/conviction_backtest.json
  - Empfehlung für optimalen Threshold (maximiere avg P&L * WR)

Usage:
  python3 scripts/conviction_backtest.py
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
OUT_FILE = WS / 'data' / 'conviction_backtest.json'

BUCKETS = [
    ('0 (legacy)',   0,   0),   # exakt 0
    ('1-44',         1,   44),  # unterhalb Threshold
    ('45-54',        45,  54),  # am Threshold
    ('55-64',        55,  64),
    ('65-74',        65,  74),
    ('75+',          75,  999),
]


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {'n': 0}
    n = len(trades)
    wins = sum(1 for t in trades if (t['pnl'] or 0) > 0)
    losses = n - wins
    sum_pnl = sum((t['pnl'] or 0) for t in trades)
    winners_pnl = sum((t['pnl'] or 0) for t in trades if (t['pnl'] or 0) > 0)
    losers_pnl = abs(sum((t['pnl'] or 0) for t in trades if (t['pnl'] or 0) < 0))
    return {
        'n':            n,
        'wins':         wins,
        'losses':       losses,
        'wr':           round(wins / n * 100, 1),
        'sum_pnl':      round(sum_pnl, 2),
        'avg_pnl':      round(sum_pnl / n, 2),
        'avg_winner':   round(winners_pnl / wins, 2) if wins else 0,
        'avg_loser':    round(-losers_pnl / losses, 2) if losses else 0,
        'profit_factor': round(winners_pnl / losers_pnl, 2) if losers_pnl > 0 else float('inf'),
        'expectancy':   round((wins/n * (winners_pnl/wins if wins else 0)) +
                              (losses/n * -(losers_pnl/losses if losses else 0)), 2),
    }


def _threshold_simulation(trades: list[dict], threshold: int) -> dict:
    """Simuliert: Wenn Threshold=X gegolten hätte, welche Trades wären durchgekommen?"""
    passed = [t for t in trades if (t['conviction'] or 0) >= threshold]
    blocked = [t for t in trades if (t['conviction'] or 0) < threshold]
    return {
        'threshold':   threshold,
        'passed':      _stats(passed),
        'blocked':     _stats(blocked),
        'would_save':  round(-sum((t['pnl'] or 0) for t in blocked), 2),
    }


def run() -> dict:
    conn = sqlite3.connect(str(DB))
    # score_source filter: nur Trades vom echten CONVICTION_V3-Scorer auswerten.
    # OPPORTUNITY_TIER nutzt eine 1-10-Skala und mischt die Semantik sonst.
    # Column existiert seit Phase 7.3 — Fallback wenn Schema alt ist.
    has_source_col = bool(conn.execute(
        "SELECT 1 FROM pragma_table_info('paper_portfolio') WHERE name='score_source'"
    ).fetchone())

    if has_source_col:
        rows = conn.execute("""
            SELECT ticker, strategy, conviction, pnl_eur, pnl_pct, entry_date, close_date,
                   COALESCE(score_source, 'LEGACY_NONE') AS src
            FROM paper_portfolio
            WHERE UPPER(status) IN ('CLOSED','WIN','LOSS')
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT ticker, strategy, conviction, pnl_eur, pnl_pct, entry_date, close_date,
                   'LEGACY_NONE' AS src
            FROM paper_portfolio
            WHERE UPPER(status) IN ('CLOSED','WIN','LOSS')
        """).fetchall()
    conn.close()

    all_trades = [{
        'ticker': r[0], 'strategy': r[1], 'conviction': r[2] or 0,
        'pnl': r[3] or 0, 'pnl_pct': r[4] or 0,
        'entry': r[5], 'close': r[6],
        'source': r[7] or 'LEGACY_NONE',
    } for r in rows]

    # Nur CONVICTION_V3-Trades für Threshold-Backtest verwenden.
    # OPPORTUNITY_TIER (1-10) und LEGACY_NONE (0) würden die 0-100-Analyse verzerren.
    trades = [t for t in all_trades if t['source'] == 'CONVICTION_V3']

    if not trades:
        return {'error': 'no_closed_trades'}

    # 1) Per-Bucket stats
    bucket_stats = []
    for name, lo, hi in BUCKETS:
        if lo == 0 and hi == 0:
            sub = [t for t in trades if (t['conviction'] or 0) == 0]
        else:
            sub = [t for t in trades if lo <= (t['conviction'] or 0) <= hi]
        bucket_stats.append({'bucket': name, 'range': f'{lo}-{hi}', **_stats(sub)})

    # 2) Threshold-Simulation (nur für trades mit conviction > 0 sinnvoll)
    scored_trades = [t for t in trades if (t['conviction'] or 0) > 0]
    thresholds = [35, 40, 45, 50, 55, 60, 65] if scored_trades else []
    sims = [_threshold_simulation(scored_trades, t) for t in thresholds]

    # 3) Optimum finden: max(passed.expectancy * sqrt(passed.n))
    import math
    def score(sim):
        p = sim['passed']
        if p['n'] < 2:
            return -9999
        return p['expectancy'] * math.sqrt(p['n'])
    optimum = max(sims, key=score) if sims else None

    # Zähle die gefilterten Sources für Transparenz
    source_counts = {}
    for t in all_trades:
        source_counts[t['source']] = source_counts.get(t['source'], 0) + 1

    result = {
        'generated_at': datetime.now(_BERLIN).isoformat(timespec='seconds'),
        'total_trades': len(trades),
        'scored_trades': len(scored_trades),
        'filter':       'score_source = CONVICTION_V3 only',
        'source_counts': source_counts,
        'trades_filtered_out': len(all_trades) - len(trades),
        'by_bucket': bucket_stats,
        'threshold_sims': sims,
        'recommended_threshold': optimum['threshold'] if optimum else None,
        'current_threshold': 45,  # aus conviction_scorer.py
        'warning': 'Zu wenig scored-trades — Empfehlung unsicher'
                   if len(scored_trades) < 15 else None,
    }

    OUT_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    # Report
    print('═' * 70)
    print(f'  Conviction Score Backtest — {len(trades)} Closed Trades')
    print('═' * 70)
    print(f'  {"Bucket":15} {"n":>3}  {"WR":>6}  {"ΣPnL":>9}  {"AvgPnL":>8}  {"Exp":>8}')
    print('  ' + '─' * 60)
    for b in bucket_stats:
        if b['n'] == 0:
            print(f'  {b["bucket"]:15} -')
            continue
        print(f'  {b["bucket"]:15} {b["n"]:>3}  {b["wr"]:>5.1f}%  '
              f'{b["sum_pnl"]:>+9.2f}  {b["avg_pnl"]:>+8.2f}  {b["expectancy"]:>+8.2f}')

    if sims:
        print()
        print(f'  Threshold-Simulation (nur {len(scored_trades)} scored trades):')
        print(f'  {"Thresh":>6}  {"Passed-n":>8}  {"Passed-WR":>9}  {"Passed-ΣPnL":>11}  {"Saved":>8}')
        print('  ' + '─' * 55)
        for s in sims:
            p = s['passed']
            if p['n'] == 0:
                print(f'  {s["threshold"]:>6}  (alle geblockt)')
                continue
            print(f'  {s["threshold"]:>6}  {p["n"]:>8}  {p["wr"]:>8.1f}%  '
                  f'{p["sum_pnl"]:>+11.2f}  {s["would_save"]:>+8.2f}')
        if optimum:
            print()
            print(f'  → Empfohlener Threshold: {optimum["threshold"]}')
            print(f'     (aktuell: {result["current_threshold"]})')

    if result.get('warning'):
        print()
        print(f'  ⚠️  {result["warning"]}')
    print('═' * 70)

    return result


def main():
    ap = argparse.ArgumentParser()
    args = ap.parse_args()
    run()


if __name__ == '__main__':
    main()
