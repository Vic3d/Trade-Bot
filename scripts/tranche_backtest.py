#!/usr/bin/env python3
"""
tranche_backtest.py — Phase 44f
================================

Vergleicht 4 Tranche-Konfigurationen auf den echten geschlossenen Paper-Trades:

  A: +3% / +8%   (Phase 44b — frueher Profit-Lock)
  B: +5% / +10%  (Originaldesign — CLAUDE.md)
  C: Keine Tranchen, Vollposition mit Trail (8% unter HWM nach +5%)
  D: Keine Tranchen, kein Trail — Vollposition bis Stop oder Target

Fuer jeden geschlossenen Trade:
  - Lade Daily OHLC zwischen entry_date und close_date
  - Simuliere Day-by-Day: Stop, Tranche-Exits, Trailing
  - Berechne realisierten P&L pro Config

Usage: python3 scripts/tranche_backtest.py
"""
from __future__ import annotations
import os, sqlite3, sys
from pathlib import Path
from dataclasses import dataclass

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'


@dataclass
class TradeResult:
    pnl_eur: float
    exit_reason: str
    exit_price: float


def _bars(c, ticker, start, end):
    rows = c.execute(
        "SELECT date, open, high, low, close FROM prices "
        "WHERE ticker=? AND date >= ? AND date <= ? ORDER BY date ASC",
        (ticker, start[:10], end[:10])
    ).fetchall()
    return [{'d': r[0], 'o': r[1], 'h': r[2], 'l': r[3], 'c': r[4]} for r in rows]


def _sim_tranches(bars, entry, stop_init, target, shares, t1_pct, t2_pct, fallback_close):
    """3-Tranche Simulation. Returns (pnl_eur, exit_reason)."""
    if not bars or shares <= 0:
        return TradeResult(0.0, 'no_data', entry)

    s_each = shares / 3.0
    t1_done = t2_done = False
    realized = 0.0
    stop = stop_init
    hwm = entry  # high water mark fuer T3-Trail
    t1_target = entry * (1 + t1_pct)
    t2_target = entry * (1 + t2_pct)

    for b in bars:
        # 1. Stop-Hit zuerst pruefen (low <= stop)
        if b['l'] <= stop:
            # Vollausstieg restliche Shares zum Stop
            remaining = shares - (s_each if t1_done else 0) - (s_each if t2_done else 0)
            realized += (stop - entry) * remaining
            return TradeResult(realized, 'STOP@'+f'{stop:.2f}', stop)

        # 2. T1 Hit
        if not t1_done and b['h'] >= t1_target:
            realized += (t1_target - entry) * s_each
            t1_done = True
            # Stop -> Breakeven
            stop = entry

        # 3. T2 Hit (nur wenn T1 schon raus)
        if t1_done and not t2_done and b['h'] >= t2_target:
            realized += (t2_target - entry) * s_each
            t2_done = True
            # Stop -> 8% unter HWM (ATR-Proxy)
            hwm = max(hwm, b['h'])
            new_stop = hwm * 0.92
            if new_stop > stop:
                stop = new_stop

        # 4. T3 Trailing (nach T2)
        if t2_done:
            hwm = max(hwm, b['h'])
            new_stop = hwm * 0.92
            if new_stop > stop:
                stop = new_stop

    # Kein Stop/Target getroffen — Restposition zum letzten close (oder fallback)
    last = bars[-1]['c'] if bars else fallback_close
    remaining = shares - (s_each if t1_done else 0) - (s_each if t2_done else 0)
    realized += (last - entry) * remaining
    reason = 'END@' + f'{last:.2f}'
    if t1_done and not t2_done:
        reason = 'T1+END'
    elif t1_done and t2_done:
        reason = 'T1+T2+END'
    return TradeResult(realized, reason, last)


def _sim_full_with_trail(bars, entry, stop_init, target, shares, fallback_close):
    """Variante C: Vollposition, Trail 8% unter HWM nachdem +5% erreicht."""
    if not bars or shares <= 0:
        return TradeResult(0.0, 'no_data', entry)
    stop = stop_init
    hwm = entry
    trail_active = False
    for b in bars:
        if b['l'] <= stop:
            return TradeResult((stop - entry) * shares, 'STOP@'+f'{stop:.2f}', stop)
        if b['h'] >= entry * 1.05:
            trail_active = True
        if trail_active:
            hwm = max(hwm, b['h'])
            new_stop = hwm * 0.92
            if new_stop > stop:
                stop = new_stop
    last = bars[-1]['c']
    return TradeResult((last - entry) * shares, 'END@'+f'{last:.2f}', last)


def _sim_no_partials(bars, entry, stop_init, target, shares, fallback_close):
    """Variante D: Vollposition, keine Tranchen, kein Trail. Stop oder Target oder End."""
    if not bars or shares <= 0:
        return TradeResult(0.0, 'no_data', entry)
    for b in bars:
        if b['l'] <= stop_init:
            return TradeResult((stop_init - entry) * shares, 'STOP', stop_init)
        if target and b['h'] >= target:
            return TradeResult((target - entry) * shares, 'TARGET', target)
    last = bars[-1]['c']
    return TradeResult((last - entry) * shares, 'END', last)


def run_backtest():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    trades = c.execute(
        "SELECT id, ticker, entry_price, stop_price, target_price, shares, "
        "       entry_date, close_date, close_price, pnl_eur, status "
        "FROM paper_portfolio "
        "WHERE status IN ('CLOSED','WIN','LOSS') "
        "  AND entry_date IS NOT NULL AND close_date IS NOT NULL "
        "  AND entry_price > 0 AND shares > 0"
    ).fetchall()

    print(f'Loaded {len(trades)} closed trades')

    configs = {
        'A_+3/+8'    : ('tranches', 0.03, 0.08),
        'B_+5/+10'   : ('tranches', 0.05, 0.10),
        'C_full+trail': ('full_trail', None, None),
        'D_no_partial': ('no_partial', None, None),
    }
    totals = {k: {'pnl': 0.0, 'wins': 0, 'losses': 0, 'n': 0} for k in configs}
    real_total = 0.0
    real_wins = 0
    real_losses = 0
    skipped_no_bars = 0

    per_trade = []  # Detailrows

    for t in trades:
        bars = _bars(c, t['ticker'], t['entry_date'], t['close_date'])
        if not bars:
            skipped_no_bars += 1
            continue

        entry = t['entry_price']
        stop = t['stop_price'] or entry * 0.95
        target = t['target_price'] or entry * 1.15
        shares = t['shares']
        close_p = t['close_price'] or entry

        row = {'id': t['id'], 'ticker': t['ticker'],
               'real_pnl': t['pnl_eur'] or 0.0}
        real_total += row['real_pnl']
        if row['real_pnl'] > 0: real_wins += 1
        elif row['real_pnl'] < 0: real_losses += 1

        for label, (kind, p1, p2) in configs.items():
            if kind == 'tranches':
                r = _sim_tranches(bars, entry, stop, target, shares, p1, p2, close_p)
            elif kind == 'full_trail':
                r = _sim_full_with_trail(bars, entry, stop, target, shares, close_p)
            else:
                r = _sim_no_partials(bars, entry, stop, target, shares, close_p)
            row[label] = r.pnl_eur
            totals[label]['pnl'] += r.pnl_eur
            totals[label]['n']   += 1
            if r.pnl_eur > 0: totals[label]['wins']   += 1
            elif r.pnl_eur < 0: totals[label]['losses'] += 1
        per_trade.append(row)

    c.close()

    print(f'Skipped (no price history): {skipped_no_bars}')
    print()
    print('═══ AGGREGATE ═══')
    print(f'{"Config":<16} {"N":>4} {"P&L EUR":>12} {"Win":>5} {"Loss":>5} {"WR":>6} {"avg":>9}')
    print('-' * 64)
    n = len(per_trade)
    print(f'{"REAL (history)":<16} {n:>4} {real_total:>+12.0f} '
          f'{real_wins:>5} {real_losses:>5} '
          f'{(100*real_wins/max(n,1)):>5.1f}% {real_total/max(n,1):>+9.0f}')
    for label, s in totals.items():
        wr = 100 * s['wins'] / max(s['n'], 1)
        avg = s['pnl'] / max(s['n'], 1)
        print(f'{label:<16} {s["n"]:>4} {s["pnl"]:>+12.0f} '
              f'{s["wins"]:>5} {s["losses"]:>5} {wr:>5.1f}% {avg:>+9.0f}')

    # Top deltas A vs B
    print()
    print('═══ TOP TRADES wo +5/+10 mehr verdient als +3/+8 ═══')
    deltas = sorted(per_trade, key=lambda x: x.get('B_+5/+10', 0) - x.get('A_+3/+8', 0), reverse=True)[:8]
    for r in deltas:
        d = r['B_+5/+10'] - r['A_+3/+8']
        print(f'  {r["ticker"]:<10} A={r["A_+3/+8"]:>+7.0f}  B={r["B_+5/+10"]:>+7.0f}  '
              f'C={r["C_full+trail"]:>+7.0f}  D={r["D_no_partial"]:>+7.0f}  Δ(B-A)={d:>+6.0f}')

    print()
    print('═══ TOP TRADES wo +3/+8 mehr verdient als +5/+10 ═══')
    deltas = sorted(per_trade, key=lambda x: x.get('A_+3/+8', 0) - x.get('B_+5/+10', 0), reverse=True)[:8]
    for r in deltas:
        d = r['A_+3/+8'] - r['B_+5/+10']
        print(f'  {r["ticker"]:<10} A={r["A_+3/+8"]:>+7.0f}  B={r["B_+5/+10"]:>+7.0f}  '
              f'C={r["C_full+trail"]:>+7.0f}  D={r["D_no_partial"]:>+7.0f}  Δ(A-B)={d:>+6.0f}')


if __name__ == '__main__':
    run_backtest()
