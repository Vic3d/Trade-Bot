#!/usr/bin/env python3
"""
backtest_validator.py — Phase 40b: Statistical Validation.

3 Methoden für robustere Strategy-Bewertung:
  1. Monte Carlo Simulation: shuffle historische PnL-Sequenz N-mal,
     berechne Verteilung von Final-PnL, Max-Drawdown, Sharpe.
     → "Mit 95% confidence: Sharpe 1.2-2.4 für PS14"
  2. Bootstrap Confidence Intervals: 1000 Resamples mit Replacement,
     CI für jede Metrik.
  3. Walk-Forward Validation: Strategy trained auf t=[0..N], tested auf
     t=[N..N+1]. Verhindert Overfitting auf einer Periode.

CLI:
  python3 scripts/backtest_validator.py PS14 --mc 1000
  python3 scripts/backtest_validator.py PS14 --walkforward 4
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, stdev, median

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'


def _fetch_strategy_pnls(strategy: str, days: int = 90) -> list[float]:
    """Pnl_pct-Sequenz der Strategy (chronologisch)."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    c = sqlite3.connect(str(DB))
    rows = c.execute("""
        SELECT pnl_pct, COALESCE(close_date, entry_date) as d
        FROM paper_portfolio
        WHERE strategy = ? AND status IN ('WIN','LOSS','CLOSED')
          AND COALESCE(close_date, entry_date) >= ?
          AND pnl_pct IS NOT NULL
        ORDER BY d
    """, (strategy, cutoff)).fetchall()
    c.close()
    return [r[0] for r in rows if r[0] is not None]


def _compute_metrics(pnls: list[float]) -> dict:
    if not pnls:
        return {'n': 0}
    wins = sum(1 for p in pnls if p > 0)
    cum = []
    running = 0
    for p in pnls:
        running += p
        cum.append(running)
    peak = cum[0]
    max_dd = 0
    for v in cum:
        if v > peak:
            peak = v
        if peak > 0:
            dd = peak - v
            if dd > max_dd:
                max_dd = dd
    sharpe = (mean(pnls) / stdev(pnls)) * (252**0.5) if len(pnls) > 1 and stdev(pnls) > 0 else 0
    return {
        'n': len(pnls),
        'win_rate': round(wins / len(pnls) * 100, 1),
        'mean_pnl_pct': round(mean(pnls), 2),
        'median_pnl_pct': round(median(pnls), 2),
        'std_pnl_pct': round(stdev(pnls), 2) if len(pnls) > 1 else 0,
        'sum_pnl_pct': round(sum(pnls), 1),
        'max_drawdown_pct': round(max_dd, 2),
        'sharpe_annualized': round(sharpe, 2),
    }


def monte_carlo_sim(strategy: str, n_simulations: int = 1000,
                     days: int = 90) -> dict:
    """Monte-Carlo: shuffle historic pnls N-mal, berechne Distribution."""
    pnls = _fetch_strategy_pnls(strategy, days=days)
    if len(pnls) < 5:
        return {'error': 'insufficient_data', 'n_trades': len(pnls)}

    base_metrics = _compute_metrics(pnls)
    shuffled_results = {'sharpe': [], 'sum_pnl': [], 'max_dd': []}

    for _ in range(n_simulations):
        shuffled = pnls.copy()
        random.shuffle(shuffled)
        m = _compute_metrics(shuffled)
        shuffled_results['sharpe'].append(m['sharpe_annualized'])
        shuffled_results['sum_pnl'].append(m['sum_pnl_pct'])
        shuffled_results['max_dd'].append(m['max_drawdown_pct'])

    def _percentile(data: list, p: float) -> float:
        s = sorted(data)
        return s[max(0, min(len(s)-1, int(p * len(s))))]

    return {
        'strategy': strategy,
        'n_simulations': n_simulations,
        'base_metrics': base_metrics,
        'sharpe_p5_p50_p95': [
            round(_percentile(shuffled_results['sharpe'], 0.05), 2),
            round(_percentile(shuffled_results['sharpe'], 0.50), 2),
            round(_percentile(shuffled_results['sharpe'], 0.95), 2),
        ],
        'sum_pnl_p5_p50_p95': [
            round(_percentile(shuffled_results['sum_pnl'], 0.05), 1),
            round(_percentile(shuffled_results['sum_pnl'], 0.50), 1),
            round(_percentile(shuffled_results['sum_pnl'], 0.95), 1),
        ],
        'max_dd_p5_p50_p95': [
            round(_percentile(shuffled_results['max_dd'], 0.05), 2),
            round(_percentile(shuffled_results['max_dd'], 0.50), 2),
            round(_percentile(shuffled_results['max_dd'], 0.95), 2),
        ],
        'interpretation': _interpret_mc(base_metrics, shuffled_results),
    }


def _interpret_mc(base: dict, results: dict) -> str:
    sharpe_p50 = sorted(results['sharpe'])[len(results['sharpe'])//2]
    sharpe_p5 = sorted(results['sharpe'])[len(results['sharpe'])//20]
    actual = base['sharpe_annualized']
    pct_better = sum(1 for s in results['sharpe'] if s < actual) / len(results['sharpe']) * 100
    if pct_better > 90:
        verdict = 'real edge'
    elif pct_better > 70:
        verdict = 'likely edge'
    elif pct_better > 30:
        verdict = 'mixed signal'
    else:
        verdict = 'no edge — random shuffle does better'
    return (f'Actual Sharpe {actual} better than {pct_better:.0f}% of random shuffles '
            f'→ {verdict}')


def bootstrap_ci(strategy: str, n_resamples: int = 1000,
                  days: int = 90) -> dict:
    """Bootstrap: 1000 Resamples mit Replacement, 95% CI."""
    pnls = _fetch_strategy_pnls(strategy, days=days)
    if len(pnls) < 5:
        return {'error': 'insufficient_data', 'n_trades': len(pnls)}

    means = []
    sharpes = []
    win_rates = []
    for _ in range(n_resamples):
        sample = random.choices(pnls, k=len(pnls))
        if len(sample) > 1 and stdev(sample) > 0:
            sharpes.append((mean(sample) / stdev(sample)) * (252**0.5))
        means.append(mean(sample))
        win_rates.append(sum(1 for p in sample if p > 0) / len(sample) * 100)

    def _ci(data, alpha=0.95):
        s = sorted(data)
        lo = int((1 - alpha) / 2 * len(s))
        hi = int((1 + alpha) / 2 * len(s)) - 1
        return [round(s[lo], 2), round(s[hi], 2)]

    return {
        'strategy': strategy,
        'n_resamples': n_resamples,
        'n_trades_per_sample': len(pnls),
        'mean_pnl_pct_95ci': _ci(means),
        'sharpe_95ci': _ci(sharpes) if sharpes else [0, 0],
        'win_rate_95ci': _ci(win_rates),
    }


def walk_forward(strategy: str, n_folds: int = 4, days: int = 120) -> dict:
    """Walk-Forward: Sequence in N Folds. Train auf [0..N-1], Test auf N.
    Hier vereinfacht: berechnet metrics für jeden Fold separat."""
    pnls = _fetch_strategy_pnls(strategy, days=days)
    if len(pnls) < n_folds * 3:
        return {'error': 'insufficient_data', 'n_trades': len(pnls)}

    fold_size = len(pnls) // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else len(pnls)
        fold_pnls = pnls[start:end]
        m = _compute_metrics(fold_pnls)
        folds.append({
            'fold': i + 1,
            'period': f'{start}-{end}',
            **m,
        })

    sharpes = [f['sharpe_annualized'] for f in folds if f.get('n', 0) > 1]
    consistency = (max(sharpes) - min(sharpes)) if sharpes else 0
    return {
        'strategy': strategy,
        'n_folds': n_folds,
        'folds': folds,
        'sharpe_consistency_range': round(consistency, 2),
        'consistent': consistency < 1.5,  # arbitrary threshold
    }


def validate_strategy(strategy: str) -> dict:
    """Komplette Validation: MC + Bootstrap + Walk-Forward."""
    return {
        'strategy': strategy,
        'computed_at': datetime.now().isoformat(timespec='seconds'),
        'monte_carlo': monte_carlo_sim(strategy, n_simulations=500),
        'bootstrap': bootstrap_ci(strategy, n_resamples=500),
        'walk_forward': walk_forward(strategy, n_folds=4),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: backtest_validator.py <STRATEGY> [--mc N] [--walkforward N]')
        return 1
    strategy = sys.argv[1]
    if '--mc' in sys.argv:
        n = int(sys.argv[sys.argv.index('--mc') + 1])
        result = monte_carlo_sim(strategy, n_simulations=n)
    elif '--walkforward' in sys.argv:
        n = int(sys.argv[sys.argv.index('--walkforward') + 1])
        result = walk_forward(strategy, n_folds=n)
    elif '--bootstrap' in sys.argv:
        result = bootstrap_ci(strategy)
    else:
        result = validate_strategy(strategy)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
