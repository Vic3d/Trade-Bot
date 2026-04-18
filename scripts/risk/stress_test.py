"""Stress Test Engine — historische Krisen auf JETZIGES Portfolio anwenden.

Phase 21 Pro.

Datenquellen-Hierarchie (in dieser Reihenfolge):
1. data/stress_history/<scenario>.json  (gebundelt im Repo)
2. trading.db prices (fuer Krisen >= 2024)
3. Skip mit Warning (falls weder noch)

Public API:
    run_stress_test(weights, scenario)       -> dict
    run_all_scenarios(weights)               -> list[dict]
    fetch_scenario_returns(scenario, tickers) -> dict
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

WORKSPACE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = WORKSPACE / 'data'
BUNDLE_DIR = DATA_DIR / 'stress_history'

# ─── Szenarien-Definition ────────────────────────────────────────────────────
SCENARIOS = {
    'covid_2020': {
        'name': 'COVID-Crash März 2020',
        'start': '2020-03-09',
        'end': '2020-03-23',
        'spx_drawdown': -0.27,
        'vix_peak': 82,
        'description': '11 Tage Lockdown-Schock, fastest Bear in History',
    },
    'rate_shock_2022': {
        'name': 'Fed-Rate-Shock H1 2022',
        'start': '2022-01-03',
        'end': '2022-06-16',
        'spx_drawdown': -0.23,
        'vix_peak': 35,
        'description': 'Tech-Crash auf Zinserhoehungen 0% -> 1.75%',
    },
    'lehman_2008': {
        'name': 'Lehman-Crash Sep 2008',
        'start': '2008-09-15',
        'end': '2008-09-29',
        'spx_drawdown': -0.28,
        'vix_peak': 70,
        'description': 'Cross-Asset-Korrelation = Tail-Risk Demo',
    },
    'tariff_shock_2025': {
        'name': 'Trump-Tariff-Shock Apr 2025',
        'start': '2025-04-02',
        'end': '2025-04-09',
        'spx_drawdown': -0.18,
        'vix_peak': 55,
        'description': 'Reciprocal Tariffs, Liberation Day',
    },
    'iran_escalation_26': {
        'name': 'Iran-Eskalation Mar 2026',
        'start': '2026-03-15',
        'end': '2026-03-31',
        'spx_drawdown': -0.08,
        'vix_peak': 38,
        'description': 'Geo-Premium Spike, Energy/Defense Rotation',
    },
}


# ─── Sektor-Proxy fuer fehlende Tickers ─────────────────────────────────────
# Falls Ticker zur Krisen-Zeit nicht existierte: nutze Sektor-ETF als Proxy.
# Beispiel: NVDA gab's 2008 zwar schon, aber wenn Daten fehlen -> XLK als Proxy.
SECTOR_PROXY = {
    'Tech': 'XLK',
    'Energy': 'XLE',
    'Defense': 'ITA',
    'Financial': 'XLF',
    'Healthcare': 'XLV',
    'Industrials': 'XLI',
    'Materials': 'XLB',
    'Consumer': 'XLY',
    'Utilities': 'XLU',
    'Versicherung': 'XLF',
}


# ─── Loading ─────────────────────────────────────────────────────────────────
def _load_bundle(scenario: str) -> Optional[dict]:
    """Liest gebundelte Stress-Daten aus data/stress_history/<scenario>.json.

    Format:
    {
        'scenario': str,
        'start': YYYY-MM-DD,
        'end': YYYY-MM-DD,
        'tickers': {
            'NVDA': [close1, close2, ...],
            ...
        }
    }
    """
    path = BUNDLE_DIR / f'{scenario}.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _load_from_db(scenario: str, tickers: list[str]) -> dict[str, list[float]]:
    """Falls Krise im DB-Zeitraum: Returns aus prices-Tabelle."""
    cfg = SCENARIOS.get(scenario)
    if not cfg:
        return {}
    db = DATA_DIR / 'trading.db'
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    out = {}
    for t in tickers:
        rows = conn.execute(
            "SELECT date, close FROM prices "
            "WHERE ticker=? AND date BETWEEN ? AND ? ORDER BY date ASC",
            (t.upper(), cfg['start'], cfg['end']),
        ).fetchall()
        if rows and len(rows) >= 3:
            out[t.upper()] = [r[1] for r in rows if r[1] is not None]
    conn.close()
    return out


def fetch_scenario_returns(
    scenario: str,
    tickers: list[str],
) -> tuple[dict[str, np.ndarray], dict]:
    """Lade Returns fuer ein Szenario.

    Returns: ({ticker: returns_array}, metadata_dict)
        metadata: {source: 'bundle'|'db'|'mixed', missing: [tickers], n_days}
    """
    cfg = SCENARIOS.get(scenario)
    if not cfg:
        return {}, {'error': f'unknown scenario: {scenario}'}

    bundle = _load_bundle(scenario)
    db_data = _load_from_db(scenario, tickers)

    prices = {}
    sources = {}
    if bundle and 'tickers' in bundle:
        for t, series in bundle['tickers'].items():
            if t.upper() in [tk.upper() for tk in tickers]:
                prices[t.upper()] = series
                sources[t.upper()] = 'bundle'
    for t, series in db_data.items():
        if t not in prices:
            prices[t] = series
            sources[t] = 'db'

    # Compute returns
    returns_out = {}
    for t, series in prices.items():
        arr = np.asarray(series, dtype=float)
        if len(arr) < 3:
            continue
        rets = np.diff(np.log(arr))
        rets = np.clip(rets, -0.5, 0.5)
        returns_out[t] = rets

    missing = [t.upper() for t in tickers if t.upper() not in returns_out]
    n_days = max((len(r) for r in returns_out.values()), default=0)

    return returns_out, {
        'source': 'bundle' if all(s == 'bundle' for s in sources.values()) else (
            'db' if all(s == 'db' for s in sources.values()) else 'mixed'),
        'missing': missing,
        'n_days': n_days,
        'n_covered': len(returns_out),
    }


# ─── Stress-Test Execution ───────────────────────────────────────────────────
def run_stress_test(
    portfolio: dict[str, float],
    scenario: str,
) -> dict:
    """Apply scenario returns auf aktuelles Portfolio.

    Args:
        portfolio: {ticker: value_eur}
        scenario: key in SCENARIOS

    Returns: {
        'scenario': str,
        'name': str,
        'total_pl_eur': float,        # cumulative P&L
        'total_pl_pct': float,         # vs. portfolio value
        'max_drawdown_eur': float,     # peak-to-trough during scenario
        'worst_position': {ticker, pl_eur},
        'best_position': {ticker, pl_eur},
        'days_simulated': int,
        'coverage': str,
        'missing_tickers': list[str],
    }
    """
    cfg = SCENARIOS.get(scenario)
    if not cfg:
        return {'error': f'unknown scenario: {scenario}'}

    tickers = list(portfolio.keys())
    if not tickers:
        return {'error': 'empty portfolio'}

    returns, meta = fetch_scenario_returns(scenario, tickers)

    if not returns:
        return {
            'scenario': scenario,
            'name': cfg['name'],
            'error': 'no_data',
            'missing_tickers': tickers,
        }

    # Per-Position cumulative P&L = value * (cumprod(1+r) - 1)
    position_pl = {}
    daily_portfolio_pl = None
    for t, rets in returns.items():
        if t not in portfolio:
            continue
        cumret = np.cumprod(1.0 + rets) - 1.0
        pl = portfolio[t] * cumret
        position_pl[t] = float(pl[-1])
        if daily_portfolio_pl is None:
            daily_portfolio_pl = pl.copy()
        else:
            # Truncate to common length
            min_len = min(len(daily_portfolio_pl), len(pl))
            daily_portfolio_pl = daily_portfolio_pl[:min_len] + pl[:min_len]

    total_pl = float(daily_portfolio_pl[-1]) if daily_portfolio_pl is not None else 0.0
    portfolio_total = sum(portfolio.values())
    pct = total_pl / portfolio_total if portfolio_total > 0 else 0.0

    # Max Drawdown ueber den Krisen-Zeitraum
    if daily_portfolio_pl is not None and len(daily_portfolio_pl) > 0:
        running_peak = np.maximum.accumulate(daily_portfolio_pl)
        drawdown = daily_portfolio_pl - running_peak
        max_dd = float(drawdown.min())
    else:
        max_dd = 0.0

    if position_pl:
        worst_t = min(position_pl.items(), key=lambda x: x[1])
        best_t = max(position_pl.items(), key=lambda x: x[1])
    else:
        worst_t = best_t = ('n/a', 0.0)

    return {
        'scenario': scenario,
        'name': cfg['name'],
        'description': cfg['description'],
        'total_pl_eur': total_pl,
        'total_pl_pct': pct,
        'max_drawdown_eur': max_dd,
        'worst_position': {'ticker': worst_t[0], 'pl_eur': worst_t[1]},
        'best_position': {'ticker': best_t[0], 'pl_eur': best_t[1]},
        'days_simulated': meta.get('n_days', 0),
        'coverage_source': meta.get('source', 'unknown'),
        'n_covered': meta.get('n_covered', 0),
        'n_total': len(tickers),
        'missing_tickers': meta.get('missing', []),
    }


def run_all_scenarios(portfolio: dict[str, float]) -> list[dict]:
    """Alle 5 Szenarien fuer Dashboard."""
    return [run_stress_test(portfolio, s) for s in SCENARIOS.keys()]


# ─── Self-Test ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Test mit aktuellem (synthetischem) Portfolio
    test_portfolio = {
        'NVDA': 3000.0,
        'EQNR.OL': 2000.0,
        'BMW.DE': 1500.0,
        'RHM.DE': 2500.0,
    }

    print('=== Stress-Test Resultate ===\n')
    for result in run_all_scenarios(test_portfolio):
        print(f"{result['name']}")
        if 'error' in result:
            print(f"  [SKIP] {result['error']}")
            if 'missing_tickers' in result:
                print(f"  Missing: {result['missing_tickers'][:5]}")
        else:
            print(f"  P&L: {result['total_pl_eur']:+.0f} EUR ({result['total_pl_pct']*100:+.1f}%)")
            print(f"  Max DD: {result['max_drawdown_eur']:+.0f} EUR")
            print(f"  Worst: {result['worst_position']['ticker']} ({result['worst_position']['pl_eur']:+.0f} EUR)")
            print(f"  Coverage: {result['n_covered']}/{result['n_total']} via {result['coverage_source']}")
        print()
