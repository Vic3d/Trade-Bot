"""Fetch historische Stress-Daten via yfinance — EINMAL ausfuehren.

Phase 21 Pro. Bundle-Builder.

Laedt fuer jedes Szenario in stress_test.SCENARIOS die Close-Preise
fuer ein Universum von ~50 relevanten Tickern + Sektor-ETFs.

Output: data/stress_history/<scenario>.json (committed im Repo)

Usage:
    python3 scripts/risk/_fetch_stress_history.py            # alle Szenarien
    python3 scripts/risk/_fetch_stress_history.py covid_2020 # einzeln

Hinweis: Braucht yfinance + Internet. Auf Server-Deploy einmal laufen lassen,
JSONs committen, danach nicht mehr nötig.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE / 'scripts'))

from risk.stress_test import SCENARIOS, BUNDLE_DIR, SECTOR_PROXY


# ─── Universum: Was wir tatsaechlich tracken / handeln ──────────────────────
# US-Mega-Caps + Sektor-ETFs + Internationale Top-Stocks unseres Universums
STRESS_UNIVERSE = [
    # US Tech
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AMZN', 'AVGO', 'TSM', 'AMD',
    # US Energy
    'XOM', 'CVX', 'OXY', 'COP', 'EOG',
    # US Defense
    'LMT', 'RTX', 'NOC', 'GD', 'BA',
    # US Financials
    'JPM', 'BAC', 'GS', 'MS',
    # US Healthcare/Consumer
    'JNJ', 'PFE', 'UNH', 'WMT', 'KO', 'PG',
    # EU Stocks (limited 2008-Coverage, mostly OK from 2010+)
    'ASML.AS', 'SAP.DE', 'SIE.DE', 'BMW.DE', 'RHM.DE', 'MUV2.DE',
    'EQNR.OL', 'NOVO-B.CO', 'BAS.DE', 'BAYN.DE',
    # Sektor-ETFs (Proxies fuer fehlende Tickers)
    'XLK', 'XLE', 'XLF', 'XLV', 'XLI', 'XLB', 'XLY', 'XLU', 'ITA', 'XLP',
    # Macro Indices
    'SPY', 'QQQ', 'GLD', 'TLT', 'UUP',
]


def fetch_scenario(scenario: str, tickers: list[str]) -> dict:
    """Zieht Close-Preise via yfinance fuer Szenario-Window + 5 Tage Puffer."""
    try:
        import yfinance as yf
    except ImportError:
        print('ERROR: yfinance nicht installiert. pip install yfinance')
        sys.exit(1)

    cfg = SCENARIOS[scenario]
    start = datetime.fromisoformat(cfg['start']) - timedelta(days=10)
    end = datetime.fromisoformat(cfg['end']) + timedelta(days=5)

    print(f'\n=== {cfg["name"]} ({cfg["start"]} → {cfg["end"]}) ===')
    out = {
        'scenario': scenario,
        'name': cfg['name'],
        'start': cfg['start'],
        'end': cfg['end'],
        'fetched_at': datetime.now().isoformat(),
        'tickers': {},
    }

    for ticker in tickers:
        try:
            data = yf.download(
                ticker,
                start=start.strftime('%Y-%m-%d'),
                end=end.strftime('%Y-%m-%d'),
                progress=False,
                auto_adjust=True,
            )
            if data.empty or 'Close' not in data:
                print(f'  [skip] {ticker}: no data')
                continue
            close_obj = data['Close'].dropna()
            # yfinance 1.3+: kann DataFrame (multi-ticker shape) sein selbst bei single ticker
            try:
                close_obj = close_obj.squeeze()
            except Exception:
                pass
            if hasattr(close_obj, 'values'):
                closes = list(close_obj.values.flatten())
            else:
                closes = list(close_obj)
            if len(closes) >= 3:
                out['tickers'][ticker] = [float(c) for c in closes]
                print(f'  [OK] {ticker}: {len(closes)} closes')
            time.sleep(0.3)  # rate limit politeness
        except Exception as e:
            print(f'  [ERROR] {ticker}: {e}')

    return out


def save_bundle(scenario: str, data: dict) -> Path:
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    path = BUNDLE_DIR / f'{scenario}.json'
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return path


def main():
    if len(sys.argv) > 1:
        scenarios = sys.argv[1:]
    else:
        scenarios = list(SCENARIOS.keys())

    for scenario in scenarios:
        if scenario not in SCENARIOS:
            print(f'Unknown scenario: {scenario}')
            continue
        data = fetch_scenario(scenario, STRESS_UNIVERSE)
        path = save_bundle(scenario, data)
        n = len(data['tickers'])
        size = path.stat().st_size / 1024
        print(f'  → Saved {n} tickers to {path.name} ({size:.0f} KB)')

    print(f'\nBundle in: {BUNDLE_DIR}')


if __name__ == '__main__':
    main()
