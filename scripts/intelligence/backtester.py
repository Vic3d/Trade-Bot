#!/usr/bin/env python3
"""
Backtester v2 — Walk-Forward mit Regime-Filter
================================================
- Walk-Forward statt nur In-Sample
- Slippage (0.1%) + Gebühren (1€ TR) + Spread (0.05%)
- Regime-Filter: "Teste Strategie nur in bestimmtem Regime"
- Metrics: Sharpe, Max Drawdown, Profit Factor, Win Rate, Expectancy

Sprint 3 | TradeMind Bauplan
"""

import sqlite3, json, math
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH = WS / 'data/trading.db'
RESULTS_PATH = WS / 'data/backtest_results.json'

# Trade Republic Kosten
FEES_PER_TRADE = 1.0  # EUR
SLIPPAGE_PCT = 0.001  # 0.1%
SPREAD_PCT = 0.0005   # 0.05%


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_price_series(ticker, start_date=None, end_date=None):
    """Holt Kursdaten für Ticker."""
    conn = get_db()
    query = "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=?"
    params = [ticker]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_regime_for_date(date, regime_cache={}):
    """Holt Regime für ein Datum (gecacht)."""
    if date in regime_cache:
        return regime_cache[date]
    conn = get_db()
    r = conn.execute(
        "SELECT regime FROM regime_history WHERE date<=? ORDER BY date DESC LIMIT 1",
        (date,)
    ).fetchone()
    conn.close()
    regime = r['regime'] if r else 'NEUTRAL'
    regime_cache[date] = regime
    return regime


def calculate_ema(closes, period):
    """Berechnet EMA."""
    if len(closes) < period:
        return [None] * len(closes)
    ema = [sum(closes[:period]) / period]
    mult = 2 / (period + 1)
    for i in range(period, len(closes)):
        ema.append(closes[i] * mult + ema[-1] * (1 - mult))
    return [None] * (period - 1) + ema


# ─── Strategie-Definitionen ────────────────────────────────
def strategy_ema_crossover(prices, short=10, long=50, stop_pct=0.05, target_pct=0.10):
    """EMA Crossover Strategie."""
    closes = [p['close'] for p in prices]
    ema_s = calculate_ema(closes, short)
    ema_l = calculate_ema(closes, long)
    
    trades = []
    position = None
    
    for i in range(1, len(prices)):
        if ema_s[i] is None or ema_l[i] is None:
            continue
        
        # Entry: Golden Cross
        if not position and ema_s[i] is not None and ema_l[i] is not None and ema_s[i-1] is not None and ema_l[i-1] is not None and ema_s[i] > ema_l[i] and ema_s[i-1] <= ema_l[i-1]:
            entry_price = closes[i] * (1 + SLIPPAGE_PCT + SPREAD_PCT)
            position = {
                'entry_date': prices[i]['date'],
                'entry_price': entry_price,
                'stop': entry_price * (1 - stop_pct),
                'target': entry_price * (1 + target_pct),
            }
        
        # Exit
        if position:
            current = closes[i]
            exit_type = None
            
            if current <= position['stop']:
                exit_type = 'STOP_HIT'
                exit_price = position['stop'] * (1 - SLIPPAGE_PCT)
            elif current >= position['target']:
                exit_type = 'TARGET'
                exit_price = position['target'] * (1 - SLIPPAGE_PCT)
            elif ema_s[i] is not None and ema_l[i] is not None and ema_s[i-1] is not None and ema_l[i-1] is not None and ema_s[i] < ema_l[i] and ema_s[i-1] >= ema_l[i-1]:
                exit_type = 'DEATH_CROSS'
                exit_price = current * (1 - SLIPPAGE_PCT - SPREAD_PCT)
            
            if exit_type:
                pnl = exit_price - position['entry_price'] - (2 * FEES_PER_TRADE)
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                trades.append({
                    'entry_date': position['entry_date'],
                    'exit_date': prices[i]['date'],
                    'entry_price': round(position['entry_price'], 4),
                    'exit_price': round(exit_price, 4),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'exit_type': exit_type,
                    'regime': get_regime_for_date(position['entry_date'])
                })
                position = None
    
    return trades


def strategy_mean_reversion(prices, bb_period=20, bb_std=2.0, stop_pct=0.03, target_pct=0.05):
    """Bollinger Band Mean Reversion."""
    closes = [p['close'] for p in prices]
    trades = []
    position = None
    
    for i in range(bb_period, len(prices)):
        window = closes[i-bb_period:i]
        mean = sum(window) / bb_period
        std = math.sqrt(sum((x - mean)**2 for x in window) / bb_period)
        lower_band = mean - bb_std * std
        upper_band = mean + bb_std * std
        
        # Entry: Preis unter Lower Band → Long
        if not position and closes[i] < lower_band:
            entry_price = closes[i] * (1 + SLIPPAGE_PCT + SPREAD_PCT)
            position = {
                'entry_date': prices[i]['date'],
                'entry_price': entry_price,
                'stop': entry_price * (1 - stop_pct),
                'target': mean,  # Mean als Target
            }
        
        if position:
            current = closes[i]
            exit_type = None
            
            if current <= position['stop']:
                exit_type = 'STOP_HIT'
                exit_price = position['stop'] * (1 - SLIPPAGE_PCT)
            elif current >= position['target']:
                exit_type = 'MEAN_REVERT'
                exit_price = current * (1 - SLIPPAGE_PCT - SPREAD_PCT)
            
            if exit_type:
                pnl = exit_price - position['entry_price'] - (2 * FEES_PER_TRADE)
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                trades.append({
                    'entry_date': position['entry_date'],
                    'exit_date': prices[i]['date'],
                    'entry_price': round(position['entry_price'], 4),
                    'exit_price': round(exit_price, 4),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'exit_type': exit_type,
                    'regime': get_regime_for_date(position['entry_date'])
                })
                position = None
    
    return trades


STRATEGIES = {
    'ema_cross_10_50': lambda p: strategy_ema_crossover(p, 10, 50),
    'ema_cross_20_100': lambda p: strategy_ema_crossover(p, 20, 100),
    'mean_reversion_20': lambda p: strategy_mean_reversion(p),
    'mean_reversion_tight': lambda p: strategy_mean_reversion(p, stop_pct=0.02, target_pct=0.03),
}


# ─── Metrics ────────────────────────────────────────────────

def calculate_metrics(trades):
    """Berechnet Performance-Metriken."""
    if not trades:
        return {'total': 0, 'win_rate': 0, 'sharpe': 0, 'max_drawdown': 0}
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in trades)
    returns = [t['pnl_pct'] for t in trades]
    avg_return = sum(returns) / len(returns) if returns else 0
    
    # Sharpe (annualisiert, ~252 Trading-Tage)
    if len(returns) > 1:
        std = math.sqrt(sum((r - avg_return)**2 for r in returns) / (len(returns) - 1))
        sharpe = (avg_return / std * math.sqrt(252)) if std > 0 else 0
    else:
        sharpe = 0
    
    # Max Drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
    
    # Profit Factor
    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    # Win Rate
    wr = len(wins) / len(trades) * 100 if trades else 0
    
    # Expectancy
    avg_win = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
    expectancy = avg_win * wr/100 + avg_loss * (1 - wr/100)
    
    # Per-Regime
    regime_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
    for t in trades:
        r = t.get('regime', 'UNKNOWN')
        regime_stats[r]['trades'] += 1
        regime_stats[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            regime_stats[r]['wins'] += 1
    
    return {
        'total': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(wr, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_return': round(avg_return, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'expectancy': round(expectancy, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_dd, 2),
        'profit_factor': round(profit_factor, 2),
        'regime_breakdown': dict(regime_stats),
    }


def walk_forward_backtest(ticker, strategy_name, train_pct=0.70):
    """
    Walk-Forward Backtest:
    - 70% In-Sample (Training)
    - 30% Out-of-Sample (Validation)
    """
    prices = get_price_series(ticker)
    if len(prices) < 100:
        return None
    
    split = int(len(prices) * train_pct)
    train_prices = prices[:split]
    test_prices = prices[split:]
    
    strategy_fn = STRATEGIES.get(strategy_name)
    if not strategy_fn:
        return None
    
    train_trades = strategy_fn(train_prices)
    test_trades = strategy_fn(test_prices)
    
    train_metrics = calculate_metrics(train_trades)
    test_metrics = calculate_metrics(test_trades)
    
    # Robustness: wie ähnlich sind In-Sample und Out-of-Sample?
    wr_diff = abs(train_metrics['win_rate'] - test_metrics['win_rate'])
    robust = wr_diff < 15  # <15% Unterschied = robust
    
    return {
        'ticker': ticker,
        'strategy': strategy_name,
        'train_period': f"{train_prices[0]['date']} → {train_prices[-1]['date']}",
        'test_period': f"{test_prices[0]['date']} → {test_prices[-1]['date']}",
        'train': train_metrics,
        'test': test_metrics,
        'robust': robust,
        'wr_diff': round(wr_diff, 1),
    }


def run_full_backtest(tickers=None, strategies=None):
    """Führt Backtests für alle Ticker × Strategien aus."""
    conn = get_db()
    if not tickers:
        tickers = [r['ticker'] for r in conn.execute(
            "SELECT DISTINCT ticker FROM prices WHERE ticker NOT LIKE '^%' AND ticker NOT LIKE '%=%'"
        ).fetchall()]
    conn.close()
    
    if not strategies:
        strategies = list(STRATEGIES.keys())
    
    results = {}
    for strategy in strategies:
        results[strategy] = {}
        for ticker in tickers:
            result = walk_forward_backtest(ticker, strategy)
            if result and result['test']['total'] > 0:
                results[strategy][ticker] = result
    
    # Speichern
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    return results


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 2:
        ticker, strategy = sys.argv[1], sys.argv[2]
        result = walk_forward_backtest(ticker, strategy)
        if result:
            print(f"═══ Backtest: {ticker} × {strategy} ═══")
            print(f"  Train ({result['train_period']}):")
            print(f"    Trades: {result['train']['total']} | WR: {result['train']['win_rate']}% | Sharpe: {result['train']['sharpe']}")
            print(f"  Test ({result['test_period']}):")
            print(f"    Trades: {result['test']['total']} | WR: {result['test']['win_rate']}% | Sharpe: {result['test']['sharpe']}")
            print(f"  Robust: {'✅' if result['robust'] else '❌'} (WR Diff: {result['wr_diff']}%)")
    
    elif len(sys.argv) > 1 and sys.argv[1] == 'full':
        print("═══ Full Walk-Forward Backtest ═══")
        results = run_full_backtest()
        for strat, tickers in results.items():
            print(f"\n  Strategy: {strat}")
            for ticker, r in sorted(tickers.items(), key=lambda x: x[1]['test']['win_rate'], reverse=True)[:5]:
                emoji = '✅' if r['robust'] else '⚠️'
                print(f"    {emoji} {ticker:12} Train WR={r['train']['win_rate']}% → Test WR={r['test']['win_rate']}% | Sharpe={r['test']['sharpe']} | PF={r['test']['profit_factor']}")
    
    else:
        print("Usage: backtester.py TICKER STRATEGY | backtester.py full")
        print(f"Strategies: {list(STRATEGIES.keys())}")
