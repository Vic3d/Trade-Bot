#!/usr/bin/env python3
"""
correlation_tracker.py — Portfolio-Korrelations-Tracker
Berechnet Pearson-Korrelationen zwischen Portfolio-Positionen,
erkennt Cluster-Risiken und schlägt Diversifikation vor.
"""

import sys
import json
import math
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from price_db import get_prices, init_tables, ALL_TICKERS

# Default Paper-Fund Positionen
PAPER_FUND = ['OXY', 'FRO', 'DHT', 'KTOS', 'HII', 'HL', 'PAAS', 'MOS', 'HAG.DE', 'TTE.PA']

# Sektor-Labels für Display
SECTOR_LABELS = {
    'OXY': 'Öl', 'TTE.PA': 'Öl', 'EQNR.OL': 'Öl', 'SHEL.L': 'Öl', 'ENI.MI': 'Öl',
    'FRO': 'Tanker', 'DHT': 'Tanker',
    'KTOS': 'Defense', 'HII': 'Defense', 'HAG.DE': 'Defense', 'BA.L': 'Defense', 'RHM.DE': 'Defense', 'AIR.PA': 'Defense',
    'HL': 'Metalle', 'PAAS': 'Metalle', 'GOLD': 'Metalle', 'WPM': 'Metalle', 'CLF': 'Metalle',
    'RIO.L': 'Metalle', 'BHP.L': 'Metalle', 'GLEN.L': 'Metalle', 'AAL.L': 'Metalle',
    'MOS': 'Dünger', 'CF': 'Dünger', 'YARA.OL': 'Dünger',
    'NVDA': 'Tech', 'MSFT': 'Tech', 'PLTR': 'Tech',
    'ENPH': 'Green', 'PLUG': 'Green',
    'BAYN.DE': 'Pharma', 'BAS.DE': 'Chemie',
}


def get_returns(ticker, days=30):
    """Get daily returns for a ticker."""
    rows = get_prices(ticker, days=days + 5)
    if not rows or len(rows) < 10:
        return None, []
    
    closes = [(r[0], r[4]) for r in rows if r[4] is not None and r[4] > 0]
    if len(closes) < 10:
        return None, []
    
    # Use last `days` entries
    closes = closes[-(days+1):]
    
    returns = []
    dates = []
    for i in range(1, len(closes)):
        ret = (closes[i][1] / closes[i-1][1]) - 1
        returns.append(ret)
        dates.append(closes[i][0])
    
    return dates, returns


def pearson_correlation(x, y):
    """Calculate Pearson correlation coefficient."""
    n = min(len(x), len(y))
    if n < 5:
        return None
    
    x, y = x[:n], y[:n]
    
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / (n - 1)
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / (n - 1))
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / (n - 1))
    
    if std_x == 0 or std_y == 0:
        return None
    
    return cov / (std_x * std_y)


def calc_correlation(ticker_a, ticker_b, days=30):
    """Calculate correlation between two tickers."""
    dates_a, returns_a = get_returns(ticker_a, days)
    dates_b, returns_b = get_returns(ticker_b, days)
    
    if returns_a is None or returns_b is None:
        return None
    
    # Align by dates
    if dates_a and dates_b:
        common_dates = set(dates_a) & set(dates_b)
        if len(common_dates) < 10:
            return None
        
        ret_dict_a = dict(zip(dates_a, returns_a))
        ret_dict_b = dict(zip(dates_b, returns_b))
        
        sorted_dates = sorted(common_dates)
        aligned_a = [ret_dict_a[d] for d in sorted_dates]
        aligned_b = [ret_dict_b[d] for d in sorted_dates]
        
        return pearson_correlation(aligned_a, aligned_b)
    
    return pearson_correlation(returns_a, returns_b)


def get_portfolio_correlations(tickers, days=30):
    """Calculate correlation matrix for a portfolio."""
    n = len(tickers)
    matrix = {}
    
    for i in range(n):
        matrix[tickers[i]] = {}
        for j in range(n):
            if i == j:
                matrix[tickers[i]][tickers[j]] = 1.0
            elif j < i:
                matrix[tickers[i]][tickers[j]] = matrix[tickers[j]][tickers[i]]
            else:
                corr = calc_correlation(tickers[i], tickers[j], days)
                matrix[tickers[i]][tickers[j]] = round(corr, 2) if corr is not None else None
    
    return matrix


def check_concentration_risk(tickers, threshold=0.7, matrix=None, days=30):
    """Identify clusters of highly correlated positions."""
    if matrix is None:
        matrix = get_portfolio_correlations(tickers, days)
    
    clusters = []
    seen = set()
    
    for i, t1 in enumerate(tickers):
        if t1 in seen:
            continue
        cluster = [t1]
        for j, t2 in enumerate(tickers):
            if i >= j or t2 in seen:
                continue
            corr = matrix.get(t1, {}).get(t2)
            if corr is not None and corr >= threshold:
                cluster.append(t2)
        if len(cluster) > 1:
            clusters.append({
                'tickers': cluster,
                'sector': SECTOR_LABELS.get(cluster[0], 'Unknown'),
                'max_corr': max(
                    (matrix.get(a, {}).get(b, 0) or 0)
                    for a in cluster for b in cluster if a != b
                ),
                'pct_of_portfolio': len(cluster) / len(tickers) * 100,
            })
            seen.update(cluster)
    
    return clusters


def suggest_diversification(current_tickers, all_tickers=None, days=30):
    """Suggest uncorrelated additions to the portfolio."""
    if all_tickers is None:
        # Use all DB tickers except indices/FX
        all_tickers = [t for t in ALL_TICKERS if not t.startswith('^') and '=' not in t]
    
    candidates = [t for t in all_tickers if t not in current_tickers]
    suggestions = []
    
    for candidate in candidates:
        correlations = []
        for existing in current_tickers:
            corr = calc_correlation(candidate, existing, days)
            if corr is not None:
                correlations.append(abs(corr))
        
        if correlations:
            avg_corr = sum(correlations) / len(correlations)
            max_corr = max(correlations)
            suggestions.append({
                'ticker': candidate,
                'sector': SECTOR_LABELS.get(candidate, 'Other'),
                'avg_abs_correlation': round(avg_corr, 2),
                'max_abs_correlation': round(max_corr, 2),
            })
    
    # Sort by lowest average correlation (most diversifying)
    suggestions.sort(key=lambda x: x['avg_abs_correlation'])
    return suggestions[:10]


def short_name(ticker):
    """Short display name for ticker."""
    return ticker.replace('.DE', '').replace('.PA', '').replace('.L', '').replace('.OL', '').replace('.MI', '')


def print_report(tickers, days=30):
    """Print full correlation report."""
    print(f"\n{'='*80}")
    print(f"=== KORRELATIONS-MATRIX ({days} Tage) ===")
    print(f"{'='*80}")
    
    matrix = get_portfolio_correlations(tickers, days)
    
    # Print matrix header
    names = [short_name(t) for t in tickers]
    max_name = max(len(n) for n in names)
    header = ' ' * (max_name + 2)
    for n in names:
        header += f"{n:>7}"
    print(f"\n{header}")
    
    for t in tickers:
        row = f"{short_name(t):<{max_name+2}}"
        for t2 in tickers:
            val = matrix.get(t, {}).get(t2)
            if val is None:
                row += f"{'N/A':>7}"
            else:
                row += f"{val:>7.2f}"
        print(row)
    
    # Cluster warnings
    clusters = check_concentration_risk(tickers, threshold=0.7, matrix=matrix, days=days)
    
    if clusters:
        print(f"\n⚠️  CLUSTER-WARNUNG:")
        for c in clusters:
            cluster_names = ', '.join(c['tickers'])
            print(f"  {c['sector']}-Cluster (Korrelation >{0.7}): {cluster_names}")
            print(f"  → {len(c['tickers'])} von {len(tickers)} Positionen ({c['pct_of_portfolio']:.0f}% des Funds)")
            print(f"  → Max Korrelation: {c['max_corr']:.2f}")
            print()
    
    # Also check for high-correlation pairs above 0.9
    redundant_pairs = []
    for i, t1 in enumerate(tickers):
        for j, t2 in enumerate(tickers):
            if j <= i:
                continue
            val = matrix.get(t1, {}).get(t2)
            if val is not None and val >= 0.9:
                redundant_pairs.append((t1, t2, val))
    
    if redundant_pairs:
        print(f"  🔴 REDUNDANZ (Korrelation >0.9):")
        for t1, t2, corr in redundant_pairs:
            print(f"    {t1} ↔ {t2}: {corr:.2f} — eine Position reicht!")
    
    # Diversification suggestions
    print(f"\n🟢 DIVERSIFIKATIONS-VORSCHLAG:")
    suggestions = suggest_diversification(tickers, days=days)
    
    if suggestions:
        # Group by sector
        sectors = {}
        for s in suggestions[:8]:
            sec = s['sector']
            if sec not in sectors:
                sectors[sec] = []
            sectors[sec].append(s)
        
        for sector, items in sectors.items():
            ticker_list = ', '.join(f"{s['ticker']}" for s in items[:3])
            avg_corr = sum(s['avg_abs_correlation'] for s in items) / len(items)
            print(f"  {sector}: {ticker_list} — Ø Korrelation zum Portfolio: {avg_corr:.2f}")
    else:
        print("  Keine Vorschläge verfügbar")
    
    return matrix


def save_correlations(tickers, days=30, matrix=None):
    """Save correlation data to JSON."""
    if matrix is None:
        matrix = get_portfolio_correlations(tickers, days)
    
    clusters = check_concentration_risk(tickers, matrix=matrix, days=days)
    suggestions = suggest_diversification(tickers, days=days)
    
    output = {
        'timestamp': datetime.now().isoformat(),
        'days': days,
        'tickers': tickers,
        'correlation_matrix': matrix,
        'clusters': [
            {
                'tickers': c['tickers'],
                'sector': c['sector'],
                'max_correlation': c['max_corr'],
                'pct_of_portfolio': c['pct_of_portfolio'],
            }
            for c in clusters
        ],
        'diversification_suggestions': suggestions[:5],
    }
    
    json_path = Path("/data/.openclaw/workspace/data/correlations.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n💾 Korrelationen gespeichert in: {json_path}")


if __name__ == '__main__':
    init_tables()
    
    parser = argparse.ArgumentParser(description='Portfolio Korrelations-Tracker')
    parser.add_argument('--tickers', type=str, help='Komma-separierte Ticker-Liste')
    parser.add_argument('--days', type=int, default=30, help='Zeitraum in Tagen (default: 30)')
    args = parser.parse_args()
    
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',')]
    else:
        tickers = PAPER_FUND
    
    matrix = print_report(tickers, args.days)
    save_correlations(tickers, args.days, matrix)
