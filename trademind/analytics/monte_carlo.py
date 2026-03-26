"""
trademind/analytics/monte_carlo.py — Monte Carlo Simulation

Resampling aus historischen Trade-Returns.
10.000 Szenarien mit je N zukünftigen Trades.

Zeigt: Verteilung möglicher Ergebnisse, Worst-Case, Wahrscheinlichkeit profitabel.
"""
import random
import math


def monte_carlo_simulation(
    trades: list[dict],
    num_simulations: int = 10000,
    future_trades: int = 100,
) -> dict:
    """
    Monte Carlo Simulation basierend auf historischen Trade-Returns.
    
    Input: Liste von Trades mit pnl_eur
    num_simulations: Anzahl Szenarien (default: 10.000)
    future_trades: Trades pro Szenario (default: 100)
    
    Returns:
        {
            'median_pnl': float,
            'mean_pnl': float,
            'worst_5pct': float,        # 5th percentile
            'best_5pct': float,         # 95th percentile
            'prob_profitable': float,   # Anteil Szenarien mit positivem Ergebnis
            'median_max_dd': float,     # Median Max Drawdown (EUR)
            'worst_max_dd': float,      # 5th percentile Max DD (EUR)
            'distribution': list,       # Histogram-Buckets für Dashboard
            'n_source_trades': int,
            'num_simulations': int,
            'future_trades': int,
        }
    """
    if not trades:
        return _empty_mc(num_simulations, future_trades)

    # Daten extrahieren
    returns = []
    for t in trades:
        pnl = t.get('pnl_eur') or 0.0
        returns.append(float(pnl))

    if len(returns) < 2:
        return _empty_mc(num_simulations, future_trades)

    rng = random.Random(42)  # Reproduzierbar

    final_pnls = []
    max_dds = []

    for _ in range(num_simulations):
        # Zufälliges Resample aus historischen Returns
        scenario = [rng.choice(returns) for _ in range(future_trades)]

        # Equity Curve aufbauen
        equity = 0.0
        curve = [0.0]
        for r in scenario:
            equity += r
            curve.append(equity)

        final_pnls.append(curve[-1])

        # Max Drawdown für dieses Szenario
        max_dd = _calc_max_dd_eur(curve)
        max_dds.append(max_dd)

    # Sortieren für Perzentile
    final_pnls.sort()
    max_dds.sort()

    n = len(final_pnls)
    p5_idx  = max(0, int(0.05 * n))
    p50_idx = max(0, int(0.50 * n))
    p95_idx = min(n - 1, int(0.95 * n))

    median_pnl    = final_pnls[p50_idx]
    mean_pnl      = sum(final_pnls) / n
    worst_5pct    = final_pnls[p5_idx]
    best_5pct     = final_pnls[p95_idx]
    prob_profit   = sum(1 for p in final_pnls if p > 0) / n

    median_max_dd = max_dds[p50_idx]
    worst_max_dd  = max_dds[p5_idx]

    # Histogram für Dashboard (20 Buckets)
    distribution = _build_histogram(final_pnls, n_buckets=20)

    return {
        'median_pnl':       round(median_pnl, 2),
        'mean_pnl':         round(mean_pnl, 2),
        'worst_5pct':       round(worst_5pct, 2),
        'best_5pct':        round(best_5pct, 2),
        'prob_profitable':  round(prob_profit, 4),
        'median_max_dd':    round(median_max_dd, 2),
        'worst_max_dd':     round(worst_max_dd, 2),
        'distribution':     distribution,
        'n_source_trades':  len(returns),
        'num_simulations':  num_simulations,
        'future_trades':    future_trades,
    }


def format_monte_carlo_report(strategy: str, mc: dict) -> str:
    """Formatiert das Monte Carlo Ergebnis als lesbaren String."""
    if not mc or mc.get('n_source_trades', 0) < 2:
        return f"  {strategy}: Zu wenig Daten für Monte Carlo"

    lines = [
        f"\n  📊 MONTE CARLO — {strategy}",
        f"  {'─'*50}",
        f"  Basis: {mc['n_source_trades']} historische Trades → {mc['num_simulations']:,} Szenarien à {mc['future_trades']} Trades",
        f"",
        f"  Ergebnis nach {mc['future_trades']} Trades:",
        f"    Median:        {mc['median_pnl']:>+9,.0f}€",
        f"    Mittelwert:    {mc['mean_pnl']:>+9,.0f}€",
        f"    Worst  5%:     {mc['worst_5pct']:>+9,.0f}€",
        f"    Best   5%:     {mc['best_5pct']:>+9,.0f}€",
        f"    Prob. Gewinn:  {mc['prob_profitable']*100:>8.1f}%",
        f"",
        f"  Max Drawdown (simuliert):",
        f"    Median Max DD: {mc['median_max_dd']:>+9,.0f}€",
        f"    Worst  5% DD:  {mc['worst_max_dd']:>+9,.0f}€",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def _calc_max_dd_eur(curve: list[float]) -> float:
    """Max Drawdown in EUR aus einer Equity-Kurve."""
    if len(curve) < 2:
        return 0.0
    peak = curve[0]
    max_dd = 0.0
    for val in curve:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _build_histogram(data: list[float], n_buckets: int = 20) -> list[dict]:
    """
    Erstellt Histogram-Buckets für das Dashboard.
    
    Returns: Liste von {min, max, count, label}
    """
    if not data:
        return []

    min_val = min(data)
    max_val = max(data)
    
    if min_val == max_val:
        return [{'min': min_val, 'max': max_val, 'count': len(data), 'label': f'{min_val:.0f}€'}]

    bucket_size = (max_val - min_val) / n_buckets
    buckets = [0] * n_buckets

    for val in data:
        idx = int((val - min_val) / bucket_size)
        idx = min(idx, n_buckets - 1)
        buckets[idx] += 1

    result = []
    for i, count in enumerate(buckets):
        b_min = min_val + i * bucket_size
        b_max = b_min + bucket_size
        result.append({
            'min':   round(b_min, 0),
            'max':   round(b_max, 0),
            'count': count,
            'label': f'{b_min:+.0f}€',
        })

    return result


def _empty_mc(num_simulations: int, future_trades: int) -> dict:
    return {
        'median_pnl':       0.0,
        'mean_pnl':         0.0,
        'worst_5pct':       0.0,
        'best_5pct':        0.0,
        'prob_profitable':  0.0,
        'median_max_dd':    0.0,
        'worst_max_dd':     0.0,
        'distribution':     [],
        'n_source_trades':  0,
        'num_simulations':  num_simulations,
        'future_trades':    future_trades,
    }
