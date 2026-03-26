"""
trademind/dashboard/generate_data.py — Dashboard Data Generator

Sammelt alle Daten für das Dashboard in einer JSON-Datei.
Wird per Cron nach Börsenschluss generiert.
Output: trademind/dashboard/data.json
"""
from __future__ import annotations

import json
import sqlite3
import os
import random
import math
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = '/data/.openclaw/workspace/data/trading.db'
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'data.json')


# ══════════════════════════════════════════════════════════════════════════════
# DB Helper
# ══════════════════════════════════════════════════════════════════════════════

def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio Data
# ══════════════════════════════════════════════════════════════════════════════

def _collect_portfolio(db) -> dict:
    """Tab 1: Portfolio — offene Positionen + P&L Summary."""

    # Offene Positionen aus trades
    open_rows = db.execute("""
        SELECT ticker, strategy, entry_price, shares, stop, target,
               entry_date, position_size_eur, pnl_eur, geo_theme, setup_type
        FROM trades WHERE status='OPEN'
        ORDER BY entry_date ASC
    """).fetchall()

    positions = []
    total_invested = 0.0
    for r in open_rows:
        entry = r['entry_price'] or 0.0
        shares = r['shares'] or 0.0
        pos_size = r['position_size_eur'] or (entry * shares) or 0.0
        pnl_eur  = r['pnl_eur'] or 0.0
        pnl_pct  = (pnl_eur / pos_size * 100) if pos_size else 0.0

        # Days held
        try:
            ed = datetime.fromisoformat(r['entry_date'][:10])
            days_held = (datetime.now() - ed).days
        except Exception:
            days_held = 0

        positions.append({
            'ticker':     r['ticker'],
            'strategy':   r['strategy'] or '?',
            'entry':      round(entry, 2),
            'current':    round(entry + (pnl_eur / shares) if shares else entry, 2),
            'pnl_eur':    round(pnl_eur, 2),
            'pnl_pct':    round(pnl_pct, 2),
            'stop':       round(r['stop'] or 0.0, 2),
            'target':     round(r['target'] or 0.0, 2),
            'days_held':  days_held,
            'geo_theme':  r['geo_theme'] or '',
            'setup_type': r['setup_type'] or '',
        })
        total_invested += pos_size

    # Closed trades P&L
    closed = db.execute("""
        SELECT COALESCE(SUM(pnl_eur), 0) AS total,
               COUNT(*) as cnt
        FROM trades
        WHERE status IN ('WIN','LOSS','CLOSED','STOPPED')
    """).fetchone()

    closed_pnl = closed['total'] or 0.0

    # Open unrealized P&L
    open_unrealized = sum(p['pnl_eur'] for p in positions)

    # Cash from paper_fund if exists
    try:
        fund_row = db.execute("SELECT cash FROM paper_fund ORDER BY rowid DESC LIMIT 1").fetchone()
        cash = fund_row['cash'] if fund_row else 25_000.0
    except Exception:
        cash = 25_000.0

    return {
        'positions':        positions,
        'total_invested':   round(total_invested, 2),
        'open_unrealized':  round(open_unrealized, 2),
        'closed_pnl':       round(closed_pnl, 2),
        'total_pnl':        round(open_unrealized + closed_pnl, 2),
        'cash':             round(cash, 2),
        'position_count':   len(positions),
        'last_updated':     datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Risk Data
# ══════════════════════════════════════════════════════════════════════════════

def _collect_risk(db) -> dict:
    """Tab 2: Risk — Circuit Breakers, Exposure, Stress Tests, Korrelation."""

    # Circuit Breaker status
    try:
        from trademind.risk.circuit_breaker import check_circuit_breakers
        cb = check_circuit_breakers(db)
        circuit_breaker = {
            'trading_allowed': cb.get('trading_allowed', True),
            'triggered':       cb.get('triggered', []),
            'warnings':        cb.get('warnings', []),
        }
    except Exception as e:
        circuit_breaker = {
            'trading_allowed': True,
            'triggered': [],
            'warnings': [f'Nicht verfügbar: {e}'],
        }

    # Portfolio Exposure
    open_rows = db.execute("""
        SELECT ticker, strategy, position_size_eur, shares, entry_price, geo_theme, setup_type
        FROM trades WHERE status='OPEN'
    """).fetchall()

    positions = []
    for r in open_rows:
        entry = r['entry_price'] or 0.0
        shares = r['shares'] or 0.0
        pos_size = r['position_size_eur'] or (entry * shares) or 5000.0
        positions.append({
            'ticker': r['ticker'],
            'strategy': r['strategy'] or 'UNK',
            'position_size_eur': pos_size,
            'geo_theme': r['geo_theme'] or 'Unknown',
        })

    try:
        from trademind.risk.portfolio import get_portfolio_exposure
        exp = get_portfolio_exposure(positions)
    except Exception:
        exp = {
            'total_exposure': sum(p['position_size_eur'] for p in positions),
            'by_sector': {},
            'by_region': {},
            'by_theme': {},
            'violations': [],
        }

    # Sektor + Region für Charts (serializable)
    sector_data = {}
    for sector, data in exp.get('by_sector', {}).items():
        sector_data[sector] = {'pct': data.get('pct', 0), 'value': data.get('value', 0)}

    region_data = {}
    for region, data in exp.get('by_region', {}).items():
        region_data[region] = {'pct': data.get('pct', 0), 'value': data.get('value', 0)}

    # Stress Tests
    try:
        from trademind.risk.stress_test import run_stress_tests
        stress_raw = run_stress_tests(positions)
        stress = []
        for s in stress_raw[:3]:  # top 3
            stress.append({
                'name':        s.get('name', '?'),
                'total_loss':  s.get('total_loss', 0),
                'severity':    s.get('severity', 'low'),
                'description': s.get('description', ''),
            })
    except Exception as e:
        stress = [{'name': 'Nicht verfügbar', 'total_loss': 0, 'severity': 'low', 'description': str(e)}]

    # Korrelations-Heatmap (einfach: aus prices-Tabelle)
    correlation_matrix = _calc_correlation_matrix(db, [p['ticker'] for p in positions])

    return {
        'circuit_breaker':  circuit_breaker,
        'exposure': {
            'total':    round(exp.get('total_exposure', 0), 2),
            'sector':   sector_data,
            'region':   region_data,
            'violations': exp.get('violations', []),
        },
        'stress_tests':     stress,
        'correlation':      correlation_matrix,
    }


def _calc_correlation_matrix(db, tickers: list[str]) -> dict:
    """Berechne Korrelationsmatrix für offene Positionen (30 Tage)."""
    if not tickers:
        return {'tickers': [], 'matrix': []}

    # Hole letzte 30 Preistage für alle Tickers
    price_data = {}
    for ticker in tickers:
        rows = db.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 30",
            (ticker,)
        ).fetchall()
        if rows:
            prices = [r['close'] for r in reversed(rows)]
            if len(prices) > 1:
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                price_data[ticker] = returns

    valid_tickers = list(price_data.keys())
    n = len(valid_tickers)
    if n == 0:
        return {'tickers': [], 'matrix': []}

    import numpy as np
    matrix = []
    for t1 in valid_tickers:
        row = []
        for t2 in valid_tickers:
            r1 = price_data[t1]
            r2 = price_data[t2]
            min_len = min(len(r1), len(r2))
            if min_len < 5:
                row.append(0.0)
            else:
                try:
                    corr = float(np.corrcoef(r1[:min_len], r2[:min_len])[0, 1])
                    row.append(round(corr, 3) if not math.isnan(corr) else 0.0)
                except Exception:
                    row.append(0.0)
        matrix.append(row)

    return {'tickers': valid_tickers, 'matrix': matrix}


# ══════════════════════════════════════════════════════════════════════════════
# Performance Data
# ══════════════════════════════════════════════════════════════════════════════

def _collect_performance(db) -> dict:
    """Tab 3: Performance — Equity Curve, Strategy Comparison, Best/Worst, Monthly."""

    # Geschlossene Trades, chronologisch
    closed_trades = db.execute("""
        SELECT ticker, strategy, exit_date, pnl_eur, pnl_pct, exit_type, entry_date
        FROM trades
        WHERE status IN ('WIN','LOSS','CLOSED','STOPPED')
          AND exit_date IS NOT NULL
        ORDER BY exit_date ASC
    """).fetchall()

    trades_list = [dict(r) for r in closed_trades]

    # Equity Curve (kumuliertes P&L)
    equity_curve = []
    cumulative = 0.0
    for t in trades_list:
        pnl = t['pnl_eur'] or 0.0
        cumulative += pnl
        equity_curve.append({
            'date': t['exit_date'][:10] if t['exit_date'] else '',
            'cumulative_pnl': round(cumulative, 2),
            'pnl': round(pnl, 2),
        })

    # Strategy Comparison
    strat_stats = {}
    for t in trades_list:
        s = t['strategy'] or 'UNK'
        if s not in strat_stats:
            strat_stats[s] = {'pnls': [], 'trades': 0, 'wins': 0}
        pnl = t['pnl_eur'] or 0.0
        strat_stats[s]['pnls'].append(pnl)
        strat_stats[s]['trades'] += 1
        if pnl > 0:
            strat_stats[s]['wins'] += 1

    strategy_comparison = []
    for s, data in strat_stats.items():
        pnls = data['pnls']
        n = data['trades']
        wins = data['wins']
        total_pnl = sum(pnls)
        wr = wins / n if n else 0
        sharpe = _compute_sharpe(pnls)
        pf = _compute_profit_factor(pnls)
        verdict = 'Strong' if sharpe > 0.5 and wr > 0.5 else ('Weak' if sharpe < 0 else 'Neutral')
        strategy_comparison.append({
            'strategy': s,
            'trades':   n,
            'win_rate': round(wr, 3),
            'total_pnl': round(total_pnl, 2),
            'sharpe':   round(sharpe, 3),
            'profit_factor': round(pf, 3),
            'verdict':  verdict,
        })

    strategy_comparison.sort(key=lambda x: x['total_pnl'], reverse=True)

    # Best & Worst Trades
    sorted_by_pnl = sorted(trades_list, key=lambda x: x.get('pnl_eur') or 0, reverse=True)
    best_trades  = [_fmt_trade(t) for t in sorted_by_pnl[:3]]
    worst_trades = [_fmt_trade(t) for t in sorted_by_pnl[-3:]]

    # Monthly P&L Heatmap
    monthly_pnl = {}
    for t in trades_list:
        try:
            d = t['exit_date'][:7]  # YYYY-MM
            monthly_pnl[d] = monthly_pnl.get(d, 0.0) + (t['pnl_eur'] or 0.0)
        except Exception:
            pass
    monthly_data = sorted(
        [{'month': k, 'pnl': round(v, 2)} for k, v in monthly_pnl.items()],
        key=lambda x: x['month']
    )

    return {
        'equity_curve':         equity_curve,
        'strategy_comparison':  strategy_comparison,
        'best_trades':          best_trades,
        'worst_trades':         worst_trades,
        'monthly_pnl':          monthly_data,
        'total_closed_trades':  len(trades_list),
        'total_closed_pnl':     round(sum(t.get('pnl_eur') or 0 for t in trades_list), 2),
    }


def _fmt_trade(t: dict) -> dict:
    return {
        'ticker':   t.get('ticker', '?'),
        'strategy': t.get('strategy', '?'),
        'pnl_eur':  round(t.get('pnl_eur') or 0, 2),
        'pnl_pct':  round((t.get('pnl_pct') or 0) * 100, 2),
        'exit_date': (t.get('exit_date') or '')[:10],
    }


def _compute_sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    import numpy as np
    arr = np.array(pnls, dtype=float)
    std = np.std(arr, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(arr) / std * math.sqrt(252))


def _compute_profit_factor(pnls: list[float]) -> float:
    wins = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    if losses == 0:
        return float('inf') if wins > 0 else 0.0
    return wins / losses


# ══════════════════════════════════════════════════════════════════════════════
# Learning Data
# ══════════════════════════════════════════════════════════════════════════════

def _collect_learning(db) -> dict:
    """Tab 4: Learning — Trefferquote, Setup, Theme, VIX, Lektionen."""

    closed = db.execute("""
        SELECT ticker, strategy, pnl_eur, pnl_pct, vix_at_entry, regime_at_entry,
               setup_type, geo_theme, lessons, exit_date, thesis_alive, result
        FROM trades
        WHERE status IN ('WIN','LOSS','CLOSED','STOPPED')
        ORDER BY exit_date ASC
    """).fetchall()

    trades = [dict(r) for r in closed]

    # These-Trefferquote (thesis_alive)
    with_thesis = [t for t in trades if t.get('thesis_alive') is not None]
    if with_thesis:
        hits = sum(1 for t in with_thesis if t.get('thesis_alive') == 1 and (t.get('pnl_eur') or 0) > 0)
        thesis_accuracy = round(hits / len(with_thesis), 3)
    else:
        thesis_accuracy = 0.5  # Default wenn keine Daten

    # Setup-Performance
    setup_perf = {}
    for t in trades:
        s = t.get('setup_type') or 'unknown'
        if s not in setup_perf:
            setup_perf[s] = {'pnls': [], 'wins': 0, 'total': 0}
        pnl = t.get('pnl_eur') or 0
        setup_perf[s]['pnls'].append(pnl)
        setup_perf[s]['total'] += 1
        if pnl > 0:
            setup_perf[s]['wins'] += 1

    setup_data = []
    for name, data in setup_perf.items():
        n = data['total']
        wr = data['wins'] / n if n else 0
        avg_pnl = sum(data['pnls']) / n if n else 0
        setup_data.append({
            'setup': name,
            'trades': n,
            'win_rate': round(wr, 3),
            'avg_pnl': round(avg_pnl, 2),
        })
    setup_data.sort(key=lambda x: x['avg_pnl'], reverse=True)

    # Theme-Performance
    theme_perf = {}
    for t in trades:
        th = t.get('geo_theme') or 'untagged'
        if th not in theme_perf:
            theme_perf[th] = {'pnls': [], 'wins': 0, 'total': 0}
        pnl = t.get('pnl_eur') or 0
        theme_perf[th]['pnls'].append(pnl)
        theme_perf[th]['total'] += 1
        if pnl > 0:
            theme_perf[th]['wins'] += 1

    theme_data = []
    for name, data in theme_perf.items():
        n = data['total']
        wr = data['wins'] / n if n else 0
        total_pnl = sum(data['pnls'])
        theme_data.append({
            'theme': name,
            'trades': n,
            'win_rate': round(wr, 3),
            'total_pnl': round(total_pnl, 2),
        })
    theme_data.sort(key=lambda x: x['total_pnl'], reverse=True)

    # VIX-Zone Performance
    def vix_zone(v):
        if v is None: return 'unknown'
        if v < 15: return 'calm (<15)'
        if v < 20: return 'normal (15-20)'
        if v < 30: return 'elevated (20-30)'
        return 'fear (>30)'

    vix_perf = {}
    for t in trades:
        zone = vix_zone(t.get('vix_at_entry'))
        if zone not in vix_perf:
            vix_perf[zone] = {'pnls': [], 'wins': 0, 'total': 0}
        pnl = t.get('pnl_eur') or 0
        vix_perf[zone]['pnls'].append(pnl)
        vix_perf[zone]['total'] += 1
        if pnl > 0:
            vix_perf[zone]['wins'] += 1

    vix_data = []
    for zone, data in vix_perf.items():
        n = data['total']
        wr = data['wins'] / n if n else 0
        avg_pnl = sum(data['pnls']) / n if n else 0
        vix_data.append({
            'zone': zone,
            'trades': n,
            'win_rate': round(wr, 3),
            'avg_pnl': round(avg_pnl, 2),
        })

    # Letzte 10 Lektionen
    lessons_rows = db.execute("""
        SELECT ticker, strategy, lessons, exit_date, pnl_eur
        FROM trades
        WHERE status IN ('WIN','LOSS','CLOSED','STOPPED')
          AND lessons IS NOT NULL
          AND lessons != ''
        ORDER BY exit_date DESC
        LIMIT 10
    """).fetchall()

    lessons = []
    for r in lessons_rows:
        lessons.append({
            'ticker':   r['ticker'],
            'strategy': r['strategy'],
            'lesson':   r['lessons'],
            'date':     (r['exit_date'] or '')[:10],
            'pnl':      round(r['pnl_eur'] or 0, 2),
        })

    return {
        'thesis_accuracy':  thesis_accuracy,
        'setup_performance': setup_data,
        'theme_performance': theme_data,
        'vix_performance':  vix_data,
        'lessons':          lessons,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Backtest Data
# ══════════════════════════════════════════════════════════════════════════════

def _collect_backtest(db) -> dict:
    """Tab 5: Backtest — Walk-Forward Ergebnisse."""
    try:
        from trademind.analytics.backtester import WalkForwardBacktester

        # Hol alle Tickers aus der DB die genug Daten haben
        rows = db.execute("""
            SELECT ticker, COUNT(*) as cnt
            FROM prices
            GROUP BY ticker
            HAVING cnt >= 150
            ORDER BY cnt DESC
            LIMIT 5
        """).fetchall()

        tickers = [r['ticker'] for r in rows if not r['ticker'].startswith('^')]
        # Filtere FX-Ticker raus
        tickers = [t for t in tickers if '=' not in t][:5]

        if not tickers:
            tickers = ['OXY', 'FRO', 'AG']

        bt = WalkForwardBacktester()

        # Momentum
        mom = bt.backtest_momentum(tickers[:3], train_days=120, test_days=20)
        # Mean Reversion
        mr  = bt.backtest_mean_reversion(tickers[:3], train_days=120, test_days=20)

        return {
            'tickers_used': tickers[:3],
            'momentum': {
                'aggregate': mom['aggregate'],
                'oos_valid': mom['out_of_sample_valid'],
                'benchmark': mom['benchmark'],
                'windows':   mom['windows'][-10:],  # letzte 10 Fenster
            },
            'mean_reversion': {
                'aggregate': mr['aggregate'],
                'oos_valid': mr['out_of_sample_valid'],
                'benchmark': mr['benchmark'],
                'windows':   mr['windows'][-10:],
            },
            'generated_at': datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            'tickers_used': [],
            'momentum': {'aggregate': {}, 'oos_valid': False, 'benchmark': {}, 'windows': []},
            'mean_reversion': {'aggregate': {}, 'oos_valid': False, 'benchmark': {}, 'windows': []},
            'error': str(e),
            'generated_at': datetime.now().isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Main Generator
# ══════════════════════════════════════════════════════════════════════════════

def generate_dashboard_data(db_path: str = None) -> dict:
    """
    Sammelt alle Daten für das Dashboard in einer JSON-Datei.
    Wird per Cron nach Börsenschluss generiert.
    Output: trademind/dashboard/data.json
    """
    db_path = db_path or DB_PATH
    db = _get_db(db_path)

    print("📊 Sammle Portfolio-Daten...")
    portfolio = _collect_portfolio(db)

    print("⚡ Sammle Risk-Daten...")
    risk = _collect_risk(db)

    print("📈 Sammle Performance-Daten...")
    performance = _collect_performance(db)

    print("🧠 Sammle Learning-Daten...")
    learning = _collect_learning(db)

    print("🔬 Sammle Backtest-Daten (kann 30s dauern)...")
    backtest = _collect_backtest(db)

    db.close()

    data = {
        'meta': {
            'generated_at': datetime.now().isoformat(),
            'version': '1.0',
            'db_path': db_path,
        },
        'portfolio':   portfolio,
        'risk':        risk,
        'performance': performance,
        'learning':    learning,
        'backtest':    backtest,
    }

    # Write output
    out_path = OUTPUT_PATH
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ Dashboard-Daten gespeichert: {out_path}")
    print(f"   Portfolio: {portfolio['position_count']} offene Positionen, P&L: {portfolio['total_pnl']:.2f}€")
    print(f"   Performance: {performance['total_closed_trades']} geschlossene Trades")
    print(f"   Backtest: Momentum OOS={'✅' if backtest['momentum']['oos_valid'] else '❌'}, "
          f"MeanRev OOS={'✅' if backtest['mean_reversion']['oos_valid'] else '❌'}")

    return data


if __name__ == '__main__':
    generate_dashboard_data()
