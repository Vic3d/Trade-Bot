#!/usr/bin/env python3
"""
run_backtests.py — Systematischer Backtest aller Paper-Strategien
Testet jede PS1-PS5 Strategie mit Default + 3 Varianten.
Ergebnisse werden als JSON gespeichert.
"""

import sys
import json
import math
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from price_db import get_prices, init_tables
from backtester import backtest, analyze_trades

# Paper-Strategien wie im Verbesserungsplan definiert
PAPER_STRATEGIES = {
    'PS1': {
        'name': 'Iran/Öl',
        'tickers': ['OXY', 'TTE.PA'],
        'default': {'rsi_buy': 40, 'sma': 50, 'stop': 10, 'target': 15, 'trailing': 5},
    },
    'PS2': {
        'name': 'Tanker-Lag',
        'tickers': ['FRO', 'DHT'],
        'default': {'rsi_buy': 45, 'sma': 20, 'stop': 10, 'target': 12, 'trailing': 4},
    },
    'PS3': {
        'name': 'NATO/Defense',
        'tickers': ['KTOS', 'HII', 'HAG.DE', 'BA.L'],
        'default': {'rsi_buy': 40, 'sma': 50, 'stop': 8, 'target': 15, 'trailing': 5},
    },
    'PS4': {
        'name': 'Edelmetalle/Miner',
        'tickers': ['HL', 'PAAS', 'GOLD', 'WPM'],
        'default': {'rsi_buy': 35, 'sma': 50, 'stop': 12, 'target': 20, 'trailing': 6},
    },
    'PS5': {
        'name': 'Dünger/Agrar',
        'tickers': ['MOS', 'CF'],
        'default': {'rsi_buy': 40, 'sma': 50, 'stop': 10, 'target': 18, 'trailing': 5},
    },
}

# Alternative Parameter-Varianten
VARIANTS = {
    'Tight': {'stop': 5, 'target': 10, 'trailing': 3},
    'Wide': {'stop': 14, 'target': 22, 'trailing': 7},
    'TrailOnly': {'stop': 15, 'target': 999, 'trailing': 5},  # 999% target = effektiv kein Target
    'RSI50_SMA20': {'rsi_buy': 50, 'sma': 20, 'stop': 8, 'target': 15, 'trailing': 5},
    'RSI55_SMA50': {'rsi_buy': 55, 'sma': 50, 'stop': 10, 'target': 15, 'trailing': 5},
}


def run_all_backtests():
    """Run backtests for all strategies with all variants."""
    init_tables()
    
    all_results = {}
    strategy_summaries = []
    
    for ps_id, ps_config in PAPER_STRATEGIES.items():
        ps_name = ps_config['name']
        tickers = ps_config['tickers']
        default_params = ps_config['default']
        
        print(f"\n{'='*80}")
        print(f"=== {ps_id}: {ps_name} ===")
        print(f"{'='*80}")
        
        # Header
        print(f"\n{'Ticker':<10} {'Variante':<12} {'Trades':>6} {'Win%':>6} {'Total P&L':>10} {'Max DD':>8} {'Avg Win':>8} {'Avg Loss':>9} {'Sharpe':>7}")
        print('-' * 80)
        
        ps_results = []
        best_variant = {}  # ticker -> best variant info
        
        for ticker in tickers:
            ticker_results = []
            
            # Build all variants to test
            variants_to_test = {'Default': default_params.copy()}
            for var_name, var_overrides in VARIANTS.items():
                v = default_params.copy()
                v.update(var_overrides)
                variants_to_test[var_name] = v
            
            for var_name, params in variants_to_test.items():
                trades = backtest(
                    ticker,
                    rsi_buy=params['rsi_buy'],
                    sma_period=params['sma'],
                    stop_pct=params['stop'],
                    target_pct=params['target'],
                    trailing_pct=params['trailing']
                )
                
                if trades is None:
                    print(f"{ticker:<10} {var_name:<12} {'N/A - Nicht genug Daten':>50}")
                    continue
                
                stats = analyze_trades(trades, ticker)
                
                if stats.get('trades', 0) == 0 or 'win_rate' not in stats:
                    print(f"{ticker:<10} {var_name:<12} {'Keine Trades / nur offene Pos.':>50}")
                    ticker_results.append({
                        'ticker': ticker, 'variant': var_name, 'params': params,
                        'trades': 0, 'win_rate': 0, 'total_pnl': 0, 'max_dd': 0,
                        'avg_win': 0, 'avg_loss': 0, 'sharpe': 0
                    })
                    continue
                
                result = {
                    'ticker': ticker,
                    'variant': var_name,
                    'params': params,
                    'trades': stats['trades'],
                    'win_rate': stats['win_rate'],
                    'total_pnl': stats['total_pnl_pct'],
                    'max_dd': stats['max_drawdown_pct'],
                    'avg_win': stats['avg_win_pct'],
                    'avg_loss': stats['avg_loss_pct'],
                    'sharpe': stats['sharpe_ratio'],
                    'crv': stats.get('crv_realized', 0),
                    'exit_reasons': stats.get('exit_reasons', {}),
                }
                ticker_results.append(result)
                
                pnl_str = f"{result['total_pnl']:+.1f}%"
                dd_str = f"-{result['max_dd']:.1f}%"
                print(f"{ticker:<10} {var_name:<12} {result['trades']:>6} {result['win_rate']:>5.1f}% {pnl_str:>10} {dd_str:>8} {result['avg_win']:>+7.1f}% {result['avg_loss']:>+8.1f}% {result['sharpe']:>7.2f}")
            
            # Find best variant for this ticker
            profitable = [r for r in ticker_results if r.get('total_pnl', 0) > 0 and r.get('trades', 0) >= 3]
            if profitable:
                best = max(profitable, key=lambda x: x['total_pnl'])
                best_variant[ticker] = best
            
            ps_results.extend(ticker_results)
        
        # Strategy recommendation
        all_defaults = [r for r in ps_results if r['variant'] == 'Default' and r.get('trades', 0) > 0]
        profitable_defaults = [r for r in all_defaults if r.get('total_pnl', 0) > 0]
        
        avg_pnl = sum(r['total_pnl'] for r in all_defaults) / len(all_defaults) if all_defaults else 0
        avg_wr = sum(r['win_rate'] for r in all_defaults) / len(all_defaults) if all_defaults else 0
        
        print(f"\n📊 EMPFEHLUNG {ps_id} ({ps_name}):")
        if len(profitable_defaults) == len(all_defaults) and all_defaults:
            print(f"   ✅ PROFITABEL — Alle {len(all_defaults)} Ticker profitabel mit Default-Params (Ø P&L: {avg_pnl:+.1f}%, Ø Win-Rate: {avg_wr:.0f}%)")
            verdict = 'PROFITABEL'
        elif len(profitable_defaults) > 0:
            losers = [r['ticker'] for r in all_defaults if r['total_pnl'] <= 0]
            print(f"   🟡 GEMISCHT — {len(profitable_defaults)}/{len(all_defaults)} Ticker profitabel. Verluste: {', '.join(losers)}")
            if best_variant:
                for t, bv in best_variant.items():
                    if t in losers:
                        print(f"      → {t}: Bessere Variante '{bv['variant']}' mit {bv['total_pnl']:+.1f}% P&L")
            verdict = 'GEMISCHT'
        else:
            print(f"   ❌ UNPROFITABEL — Kein Ticker profitabel mit Default-Params (Ø P&L: {avg_pnl:+.1f}%)")
            if best_variant:
                for t, bv in best_variant.items():
                    print(f"      → {t}: Einzige profitable Variante '{bv['variant']}' mit {bv['total_pnl']:+.1f}% P&L")
            verdict = 'UNPROFITABEL'
        
        strategy_summaries.append({
            'strategy': ps_id,
            'name': ps_name,
            'verdict': verdict,
            'avg_pnl_default': round(avg_pnl, 2),
            'avg_winrate_default': round(avg_wr, 1),
            'tickers_profitable': len(profitable_defaults),
            'tickers_total': len(all_defaults),
        })
        
        all_results[ps_id] = {
            'name': ps_name,
            'tickers': tickers,
            'default_params': default_params,
            'results': ps_results,
            'best_variants': {t: v for t, v in best_variant.items()},
            'verdict': verdict,
        }
    
    # Final summary
    print(f"\n{'='*80}")
    print(f"=== GESAMTÜBERSICHT ===")
    print(f"{'='*80}")
    print(f"\n{'Strategie':<12} {'Name':<20} {'Verdict':<14} {'Ø P&L':>8} {'Ø Win%':>8} {'Profitabel':>12}")
    print('-' * 74)
    
    for s in strategy_summaries:
        icon = '✅' if s['verdict'] == 'PROFITABEL' else ('🟡' if s['verdict'] == 'GEMISCHT' else '❌')
        print(f"{s['strategy']:<12} {s['name']:<20} {icon} {s['verdict']:<11} {s['avg_pnl_default']:>+7.1f}% {s['avg_winrate_default']:>7.1f}% {s['tickers_profitable']}/{s['tickers_total']:>8}")
    
    # Save to JSON
    output = {
        'timestamp': datetime.now().isoformat(),
        'strategy_summaries': strategy_summaries,
        'detailed_results': {}
    }
    
    for ps_id, data in all_results.items():
        output['detailed_results'][ps_id] = {
            'name': data['name'],
            'tickers': data['tickers'],
            'default_params': data['default_params'],
            'verdict': data['verdict'],
            'results': [
                {k: v for k, v in r.items() if k != 'params'}
                for r in data['results']
            ],
            'best_variants': {
                t: {'variant': v['variant'], 'total_pnl': v['total_pnl'], 'win_rate': v['win_rate']}
                for t, v in data['best_variants'].items()
            }
        }
    
    json_path = Path("/data/.openclaw/workspace/data/backtest_results.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n💾 Ergebnisse gespeichert in: {json_path}")


if __name__ == '__main__':
    run_all_backtests()
