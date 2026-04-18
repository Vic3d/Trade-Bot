#!/usr/bin/env python3
"""
Walk-Forward Backtest — Phase 19c
===================================

Professional backtest with:
  - **Rolling train/test windows** (no look-ahead bias)
  - **Transaction costs** (Phase 19a)
  - **Vol-target sizing** (Phase 19b)
  - **Bootstrap confidence intervals** (statistical significance)
  - **Multiple metrics**: Sharpe, Sortino, Max-DD, Profit-Factor, Win-Rate

**Strategy being tested:** Simple trend-following as proof-of-concept.
  Signal: Price > EMA50 AND EMA20 > EMA50 (golden cross)
  Exit: Price < EMA20 OR stop -5% OR +15% target
  Holding: max 20 days

This is a SKELETON backtester — replace the signal function with actual
TradeMind thesis-generation logic later. The goal is to have a rigorous
framework BEFORE testing strategies.

Output:
  data/walk_forward_results.json  — full stats per fold + aggregate
  data/walk_forward_report.md     — human-readable summary

Run:
  python3 walk_forward_backtest.py --ticker NVDA
  python3 walk_forward_backtest.py --all   # all tickers with enough history
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger('walk_forward')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
DATA = WS / 'data'
DB = DATA / 'trading.db'
OUT_JSON = DATA / 'walk_forward_results.json'
OUT_MD = DATA / 'walk_forward_report.md'


# ── Data Loading ──────────────────────────────────────────────────────────────

@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float


def _load_prices(ticker: str, min_days: int = 500) -> list[Bar]:
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT date, open, high, low, close FROM prices "
            "WHERE ticker = ? ORDER BY date ASC",
            (ticker,),
        ).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f'{ticker}: load failed: {e}')
        return []

    bars: list[Bar] = []
    for r in rows:
        d, o, h, l, c = r
        if None in (o, h, l, c):
            continue
        bars.append(Bar(d, float(o), float(h), float(l), float(c)))

    if len(bars) < min_days:
        return []
    return bars


# ── Technical Indicators ──────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


# ── Strategy (placeholder — replace with TradeMind thesis logic) ──────────────

@dataclass
class Signal:
    direction: str  # 'LONG' or 'FLAT'
    stop_pct: float = 0.05
    target_pct: float = 0.15
    max_hold_days: int = 20


def _trend_signal(bars: list[Bar], idx: int) -> Signal:
    """
    Simple golden-cross trend signal:
      LONG if close > ema50 AND ema20 > ema50
      else FLAT
    """
    if idx < 60:
        return Signal('FLAT')

    closes = [b.close for b in bars[: idx + 1]]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    if not ema20 or not ema50:
        return Signal('FLAT')

    last_close = closes[-1]
    last_e20 = ema20[-1]
    last_e50 = ema50[-1]

    if last_close > last_e50 and last_e20 > last_e50:
        return Signal('LONG', stop_pct=0.05, target_pct=0.15, max_hold_days=20)
    return Signal('FLAT')


# ── Trade Simulation (with transaction costs) ─────────────────────────────────

@dataclass
class ClosedTrade:
    ticker: str
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    shares: int
    gross_pnl_eur: float
    net_pnl_eur: float
    cost_drag_pct: float
    exit_reason: str
    holding_days: int


def _simulate_trade(
    ticker: str,
    bars: list[Bar],
    entry_idx: int,
    signal: Signal,
    portfolio_value_eur: float,
    fx_rate: float,
) -> ClosedTrade | None:
    from execution.transaction_costs import net_pnl
    from execution.position_sizing import size_position

    if entry_idx + 1 >= len(bars):
        return None

    entry_bar = bars[entry_idx + 1]  # enter next open (no look-ahead)
    entry_price = entry_bar.open
    stop_price = entry_price * (1 - signal.stop_pct)
    target_price = entry_price * (1 + signal.target_pct)

    sizing = size_position(
        ticker=ticker,
        entry_price=entry_price,
        stop_price=stop_price,
        portfolio_value_eur=portfolio_value_eur,
        conviction_score=55,  # default mid — caller can override
        fx_rate=fx_rate,
    )
    shares = sizing['shares']
    if shares <= 0 or sizing.get('skip'):
        return None

    # Walk forward until exit
    exit_price = None
    exit_idx = None
    exit_reason = 'time_stop'
    for j in range(entry_idx + 1, min(entry_idx + 1 + signal.max_hold_days, len(bars))):
        bar = bars[j]
        # Intraday check: stop first (conservative)
        if bar.low <= stop_price:
            exit_price = stop_price
            exit_idx = j
            exit_reason = 'stop_loss'
            break
        if bar.high >= target_price:
            exit_price = target_price
            exit_idx = j
            exit_reason = 'take_profit'
            break
        # Trend breakdown exit
        closes_so_far = [b.close for b in bars[: j + 1]]
        ema20 = _ema(closes_so_far, 20)
        if ema20 and bar.close < ema20[-1]:
            exit_price = bar.close
            exit_idx = j
            exit_reason = 'trend_breakdown'
            break

    if exit_price is None:
        last_idx = min(entry_idx + signal.max_hold_days, len(bars) - 1)
        exit_price = bars[last_idx].close
        exit_idx = last_idx
        exit_reason = 'time_stop'

    result = net_pnl(
        ticker=ticker,
        entry_price=entry_price,
        exit_price=exit_price,
        shares=shares,
        fx_rate=fx_rate,
    )

    return ClosedTrade(
        ticker=ticker,
        entry_idx=entry_idx + 1,
        exit_idx=exit_idx,
        entry_price=entry_price,
        exit_price=exit_price,
        shares=shares,
        gross_pnl_eur=result['gross_pnl_eur'],
        net_pnl_eur=result['net_pnl_eur'],
        cost_drag_pct=result['cost_drag_pct'],
        exit_reason=exit_reason,
        holding_days=exit_idx - (entry_idx + 1) + 1,
    )


# ── Fold Execution ────────────────────────────────────────────────────────────

def run_fold(
    ticker: str,
    bars: list[Bar],
    start_idx: int,
    end_idx: int,
    portfolio_value_eur: float = 25000,
    fx_rate: float = 1.0,
) -> list[ClosedTrade]:
    """
    Runs strategy on a contiguous slice [start_idx, end_idx).
    Returns list of closed trades.
    """
    trades: list[ClosedTrade] = []
    i = start_idx
    while i < end_idx:
        sig = _trend_signal(bars, i)
        if sig.direction == 'LONG':
            trade = _simulate_trade(
                ticker, bars, i, sig, portfolio_value_eur, fx_rate
            )
            if trade:
                trades.append(trade)
                i = trade.exit_idx + 1
                continue
        i += 1
    return trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(trades: list[ClosedTrade], portfolio_value_eur: float) -> dict:
    if not trades:
        return {
            'n_trades': 0, 'win_rate': 0, 'avg_pnl_eur': 0,
            'total_pnl_eur': 0, 'sharpe': 0, 'sortino': 0,
            'max_dd_eur': 0, 'profit_factor': 0,
        }

    pnls = [t.net_pnl_eur for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls)
    win_rate = len(wins) / len(pnls) * 100

    # Sharpe (annualized, assume ~252 trading days and naive)
    if len(pnls) > 1:
        std = statistics.stdev(pnls)
        sharpe = (avg_pnl / std * math.sqrt(252)) if std > 0 else 0
    else:
        sharpe = 0

    # Sortino (downside deviation only)
    if losses and len(losses) > 1:
        downside_std = statistics.stdev(losses)
        sortino = (avg_pnl / downside_std * math.sqrt(252)) if downside_std > 0 else 0
    else:
        sortino = 0

    # Max drawdown on cumulative equity curve
    equity = [portfolio_value_eur]
    for p in pnls:
        equity.append(equity[-1] + p)
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    # Profit factor: gross_win / gross_loss
    gross_win = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float('inf') if gross_win > 0 else 0

    return {
        'n_trades': len(trades),
        'win_rate': round(win_rate, 1),
        'avg_pnl_eur': round(avg_pnl, 2),
        'total_pnl_eur': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl / portfolio_value_eur * 100, 2),
        'sharpe': round(sharpe, 2),
        'sortino': round(sortino, 2),
        'max_dd_eur': round(max_dd, 2),
        'max_dd_pct': round(max_dd / portfolio_value_eur * 100, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
        'avg_holding_days': round(
            sum(t.holding_days for t in trades) / len(trades), 1
        ),
        'avg_cost_drag_pct': round(
            sum(t.cost_drag_pct for t in trades) / len(trades), 2
        ),
    }


# ── Bootstrap Confidence Intervals ────────────────────────────────────────────

def bootstrap_ci(
    pnls: list[float],
    n_samples: int = 1000,
    confidence: float = 0.95,
) -> dict:
    """
    Bootstrap resampling for confidence intervals on mean PnL & win-rate.
    """
    if len(pnls) < 10:
        return {'warning': 'insufficient data for bootstrap (<10 trades)'}

    rng = random.Random(42)  # reproducible
    means = []
    win_rates = []
    for _ in range(n_samples):
        sample = [rng.choice(pnls) for _ in range(len(pnls))]
        means.append(sum(sample) / len(sample))
        wins = sum(1 for p in sample if p > 0)
        win_rates.append(wins / len(sample) * 100)

    means.sort()
    win_rates.sort()
    lo_idx = int((1 - confidence) / 2 * n_samples)
    hi_idx = int((1 + confidence) / 2 * n_samples) - 1

    return {
        'n_samples': n_samples,
        'confidence': confidence,
        'mean_pnl_ci': [round(means[lo_idx], 2), round(means[hi_idx], 2)],
        'win_rate_ci': [round(win_rates[lo_idx], 1), round(win_rates[hi_idx], 1)],
        'mean_pnl_median': round(means[n_samples // 2], 2),
    }


# ── Walk-Forward Orchestration ────────────────────────────────────────────────

def walk_forward(
    ticker: str,
    train_days: int = 252,     # 1y train
    test_days: int = 63,       # 3m test
    step_days: int = 63,       # step forward 3m
    portfolio_value_eur: float = 25000,
    fx_rate: float = 1.0,
) -> dict:
    """
    Runs walk-forward analysis on one ticker. For each fold:
      - Uses train_days for (potential) parameter fitting (skipped here — strategy is static)
      - Tests on next test_days
      - Rolls forward by step_days
    """
    bars = _load_prices(ticker)
    if not bars:
        return {'ticker': ticker, 'error': 'no data'}

    folds = []
    all_trades: list[ClosedTrade] = []

    start = train_days
    while start + test_days <= len(bars):
        test_start = start
        test_end = min(start + test_days, len(bars))
        fold_trades = run_fold(
            ticker, bars, test_start, test_end,
            portfolio_value_eur=portfolio_value_eur,
            fx_rate=fx_rate,
        )
        fold_metrics = compute_metrics(fold_trades, portfolio_value_eur)
        folds.append({
            'test_from': bars[test_start].date,
            'test_to': bars[test_end - 1].date,
            'metrics': fold_metrics,
        })
        all_trades.extend(fold_trades)
        start += step_days

    aggregate = compute_metrics(all_trades, portfolio_value_eur)

    all_pnls = [t.net_pnl_eur for t in all_trades]
    ci = bootstrap_ci(all_pnls) if len(all_pnls) >= 10 else None

    return {
        'ticker': ticker,
        'total_bars': len(bars),
        'n_folds': len(folds),
        'folds': folds,
        'aggregate': aggregate,
        'bootstrap_ci': ci,
        'sample_trades': [
            {
                'entry_date': bars[t.entry_idx].date,
                'exit_date': bars[t.exit_idx].date,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'shares': t.shares,
                'gross_pnl_eur': t.gross_pnl_eur,
                'net_pnl_eur': t.net_pnl_eur,
                'exit_reason': t.exit_reason,
                'holding_days': t.holding_days,
            }
            for t in all_trades[:10]
        ],
    }


# ── CLI / Main ────────────────────────────────────────────────────────────────

def _list_backtest_tickers(min_bars: int = 500) -> list[str]:
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute("""
            SELECT ticker, COUNT(*) as n FROM prices
            GROUP BY ticker HAVING n >= ?
            ORDER BY ticker
        """, (min_bars,)).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def run_all(ticker_limit: int | None = None) -> dict:
    tickers = _list_backtest_tickers()
    if ticker_limit:
        tickers = tickers[:ticker_limit]

    log.info(f'Walk-forward: {len(tickers)} tickers')
    results: dict[str, dict] = {}
    for t in tickers:
        log.info(f'  {t}')
        try:
            results[t] = walk_forward(t)
        except Exception as e:
            results[t] = {'error': str(e)}
    return results


def write_report(results: dict) -> None:
    lines = [
        '# Walk-Forward Backtest Report',
        f'_Generated {datetime.now().isoformat(timespec="seconds")}_',
        '',
        'Strategy: **Golden-Cross Trend** (EMA20 > EMA50 && close > EMA50)',
        'Exit: stop -5% / target +15% / trend-breakdown / 20-day max hold',
        'Costs: Phase 19a transaction cost model (spread+slippage+FX+commission)',
        'Sizing: Phase 19b vol-target (1% risk budget, 15% max position)',
        '',
        '## Aggregate per Ticker',
        '',
        '| Ticker | Folds | Trades | WR | Net PnL€ | Net PnL% | Sharpe | Max DD% | PF | Cost Drag |',
        '|---|---|---|---|---|---|---|---|---|---|',
    ]
    for t, r in results.items():
        if r.get('error'):
            lines.append(f'| {t} | — | — | — | — | — | — | — | — | {r["error"]} |')
            continue
        a = r.get('aggregate', {})
        lines.append(
            f'| {t} | {r.get("n_folds", 0)} | {a.get("n_trades", 0)} | '
            f'{a.get("win_rate", 0)}% | {a.get("total_pnl_eur", 0)} | '
            f'{a.get("total_pnl_pct", 0)}% | {a.get("sharpe", 0)} | '
            f'{a.get("max_dd_pct", 0)}% | {a.get("profit_factor", 0)} | '
            f'{a.get("avg_cost_drag_pct", 0)}% |'
        )

    OUT_MD.write_text('\n'.join(lines), encoding='utf-8')


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', type=str, help='Single ticker')
    ap.add_argument('--all', action='store_true', help='All tickers with ≥500 bars')
    ap.add_argument('--limit', type=int, default=None)
    args = ap.parse_args()

    if args.ticker:
        results = {args.ticker: walk_forward(args.ticker)}
    elif args.all:
        results = run_all(ticker_limit=args.limit)
    else:
        # Default: top 5 tickers with most data
        tickers = _list_backtest_tickers()[:5]
        results = {t: walk_forward(t) for t in tickers}

    OUT_JSON.write_text(json.dumps(results, indent=2), encoding='utf-8')
    write_report(results)

    # Console summary
    print('\n── Walk-Forward Summary ──')
    for t, r in results.items():
        if r.get('error'):
            print(f'  {t:10} ERR: {r["error"]}')
            continue
        a = r.get('aggregate', {})
        print(
            f'  {t:10} folds={r.get("n_folds", 0):2} '
            f'trades={a.get("n_trades", 0):3} '
            f'WR={a.get("win_rate", 0):5.1f}% '
            f'net={a.get("total_pnl_eur", 0):+8.0f}€ '
            f'sharpe={a.get("sharpe", 0):+5.2f} '
            f'DD={a.get("max_dd_pct", 0):5.1f}% '
            f'drag={a.get("avg_cost_drag_pct", 0):.2f}%'
        )


if __name__ == '__main__':
    main()
