#!/usr/bin/env python3
"""
sector_rotation.py — Sektor-Rotation-Modell
Analysiert Sektor-Momentum und identifiziert Rotationen.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from price_db import get_closes, get_rsi, init_tables

DATA_DIR = Path("/data/.openclaw/workspace/data")

SECTORS = {
    'Energy': ['OXY', 'TTE.PA', 'EQNR.OL', 'SHEL.L', 'ENI.MI'],
    'Defense': ['KTOS', 'HII', 'HAG.DE', 'BA.L', 'RHM.DE'],
    'Metals': ['HL', 'PAAS', 'GOLD', 'WPM', 'CLF', 'AAL.L'],
    'Tech': ['NVDA', 'MSFT', 'PLTR'],
    'Mining': ['RIO.L', 'BHP.L', 'GLEN.L', 'MP', 'UUUU'],
    'Fertilizer': ['MOS', 'CF'],
    'Tanker': ['FRO', 'DHT'],
    'Pharma': ['BAYN.DE', 'BAS.DE'],
    'Solar': ['ENPH', 'PLUG'],
}


def calc_performance(ticker, days):
    """Calculate performance over N trading days."""
    closes = get_closes(ticker, days + 10)
    if not closes or len(closes) < days:
        return None
    return ((closes[-1] / closes[-days]) - 1) * 100


def analyze_sector(sector_name, tickers):
    """Analyze a single sector."""
    perfs_1w = []
    perfs_1m = []
    perfs_3m = []
    rsis = []
    valid_tickers = []

    for ticker in tickers:
        p1w = calc_performance(ticker, 5)
        p1m = calc_performance(ticker, 21)
        p3m = calc_performance(ticker, 63)
        rsi = get_rsi(ticker)

        if p1w is not None and p1m is not None:
            perfs_1w.append(p1w)
            perfs_1m.append(p1m)
            if p3m is not None:
                perfs_3m.append(p3m)
            if rsi is not None:
                rsis.append(rsi)
            valid_tickers.append(ticker)

    if not perfs_1w:
        return None

    avg_1w = sum(perfs_1w) / len(perfs_1w)
    avg_1m = sum(perfs_1m) / len(perfs_1m)
    avg_3m = sum(perfs_3m) / len(perfs_3m) if perfs_3m else 0
    avg_rsi = sum(rsis) / len(rsis) if rsis else 50

    # Momentum score: weighted average
    momentum = avg_1w * 0.5 + avg_1m * 0.3 + avg_3m * 0.2

    # Signal classification
    if avg_3m < -5 and avg_1w > 2:
        signal = '🟡 POSSIBLE ROTATION'
    elif momentum > 5:
        signal = '🟢 STRONG TREND'
    elif momentum > 2:
        signal = '🟢 MODERATE'
    elif momentum > 0:
        signal = '🟡 STABLE'
    elif momentum > -2:
        signal = '🟡 LAGGING'
    elif momentum > -5:
        signal = '🔴 WEAKENING'
    else:
        signal = '🔴 AVOID'

    # Check for weak sectors
    if avg_1m < -5 and avg_3m < -10:
        signal = '🔴 WEAK'

    return {
        'sector': sector_name,
        'tickers': valid_tickers,
        'perf_1w': round(avg_1w, 2),
        'perf_1m': round(avg_1m, 2),
        'perf_3m': round(avg_3m, 2),
        'avg_rsi': round(avg_rsi, 1),
        'momentum': round(momentum, 2),
        'signal': signal,
    }


def run_analysis():
    """Run full sector rotation analysis."""
    init_tables()
    today = datetime.now().strftime('%d.%m.%Y')

    results = []
    for sector_name, tickers in SECTORS.items():
        result = analyze_sector(sector_name, tickers)
        if result:
            results.append(result)

    # Sort by momentum
    results.sort(key=lambda x: x['momentum'], reverse=True)

    # Print
    print(f"\n=== SEKTOR-ROTATION — {today} ===\n")
    print(f"{'Rank':>4} | {'Sektor':<12} | {'1W':>7} | {'1M':>7} | {'3M':>7} | {'RSI':>5} | {'Mom':>6} | Signal")
    print(f"{'─'*85}")

    for i, r in enumerate(results, 1):
        print(f"  {i:>2} | {r['sector']:<12} | {r['perf_1w']:>+6.1f}% | {r['perf_1m']:>+6.1f}% | "
              f"{r['perf_3m']:>+6.1f}% | {r['avg_rsi']:>5.1f} | {r['momentum']:>+5.1f} | {r['signal']}")

    # Recommendations
    strong = [r for r in results if '🟢 STRONG' in r['signal']]
    weak = [r for r in results if '🔴' in r['signal'] and 'AVOID' in r['signal'] or 'WEAK' in r['signal']]
    rotating = [r for r in results if 'ROTATION' in r['signal']]

    print(f"\n💡 EMPFEHLUNG:")
    if strong:
        names = ', '.join(r['sector'] for r in strong)
        print(f"  - Übergewichten: {names} (starker Trend + Momentum)")
    if weak:
        names = ', '.join(r['sector'] for r in weak)
        print(f"  - Untergewichten: {names} (schwach)")
    if rotating:
        names = ', '.join(r['sector'] for r in rotating)
        print(f"  - Beobachten: {names} (mögl. Rotation von schwach auf stark)")
    if not strong and not weak and not rotating:
        print(f"  - Keine klaren Signale — Markt in Transition")

    # Save JSON
    output = {
        'timestamp': datetime.now().isoformat(),
        'date': today,
        'sectors': results,
        'recommendations': {
            'overweight': [r['sector'] for r in strong],
            'underweight': [r['sector'] for r in weak],
            'watch': [r['sector'] for r in rotating],
        },
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / "sector_rotation.json"
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Gespeichert: {json_path}")

    return results


if __name__ == '__main__':
    run_analysis()
