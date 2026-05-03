#!/usr/bin/env python3
"""
multi_asset_universe.py — Phase 45g (Sprint 6): Multi-Asset-Universe.

Erweitert handelbares Universe ueber Equities hinaus auf:
  - Bonds:       TLT, IEF, HYG, LQD, AGG (US-Treasury + Corporate)
  - Commodities: USO, GLD, DBC, SLV, UNG, DBA (Oil, Gold, Broad, Silver, Gas, Agri)
  - Volatility:  VXX, UVXY (long vol — fuer Hedging)
  - FX-ETFs:     UUP (USD), FXE (EUR), FXY (JPY)
  - Sektor-ETFs: XLE, XLF, XLK, XLV, XLY, XLP, XLI, XLB, XLU, XLRE, XLC

Pro Asset: zugewiesene Macro-Strategy (regime-conditional), z.B.:
  TLT  → 'BOND_RALLY' bei Yields-fallen
  GLD  → 'GOLD_HEDGE' bei VIX > 25
  VXX  → 'VOL_LONG' bei VIX < 15 (anti-crowd)

Output: data/multi_asset_universe.json mit Tickers + Categories + Triggers
Wird vom Hunter als zusaetzliche Setup-Quelle gelesen.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
OUT = WS / 'data' / 'multi_asset_universe.json'

UNIVERSE = {
    'bonds': {
        'TLT':  {'name': '20+ Year Treasury', 'trigger': 'yields_falling',
                  'regimes': ['RISK_OFF', 'CRISIS']},
        'IEF':  {'name': '7-10 Year Treasury', 'trigger': 'yields_stable',
                  'regimes': ['CALM_BULL', 'RISK_OFF']},
        'HYG':  {'name': 'High-Yield Corporate', 'trigger': 'risk_on_credit',
                  'regimes': ['CALM_BULL', 'VOLATILE_BULL']},
        'LQD':  {'name': 'Investment-Grade Corp', 'trigger': 'rate_stability',
                  'regimes': ['CALM_BULL', 'CHOPPY']},
        'AGG':  {'name': 'Aggregate Bond', 'trigger': 'broad_bond',
                  'regimes': ['CHOPPY']},
    },
    'commodities': {
        'USO':  {'name': 'Oil ETF', 'trigger': 'energy_shock',
                  'regimes': ['VOLATILE_BULL', 'RISK_OFF']},
        'GLD':  {'name': 'Gold', 'trigger': 'safe_haven',
                  'regimes': ['RISK_OFF', 'CRISIS']},
        'SLV':  {'name': 'Silver', 'trigger': 'inflation_hedge',
                  'regimes': ['VOLATILE_BULL', 'RISK_OFF']},
        'DBC':  {'name': 'Broad Commodities', 'trigger': 'inflation_broad',
                  'regimes': ['VOLATILE_BULL']},
        'UNG':  {'name': 'Natural Gas', 'trigger': 'energy_shock',
                  'regimes': ['VOLATILE_BULL', 'CRISIS']},
        'DBA':  {'name': 'Agriculture', 'trigger': 'food_disruption',
                  'regimes': ['RISK_OFF']},
        'GDX':  {'name': 'Gold Miners', 'trigger': 'gold_rally',
                  'regimes': ['RISK_OFF', 'CRISIS']},
    },
    'volatility': {
        'VXX':  {'name': 'Short-Term VIX Futures', 'trigger': 'low_vix_anti_crowd',
                  'regimes': ['CALM_BULL']},
        'UVXY': {'name': 'Leveraged VIX', 'trigger': 'crisis_hedge',
                  'regimes': ['CRISIS']},
    },
    'fx_etfs': {
        'UUP':  {'name': 'USD Index ETF', 'trigger': 'dxy_strength',
                  'regimes': ['RISK_OFF']},
        'FXE':  {'name': 'EUR ETF', 'trigger': 'eur_strength',
                  'regimes': ['CALM_BULL']},
        'FXY':  {'name': 'JPY ETF', 'trigger': 'risk_off_safe_haven',
                  'regimes': ['RISK_OFF', 'CRISIS']},
    },
    'sector_etfs': {
        'XLE':  {'name': 'Energy', 'trigger': 'energy_demand',
                  'regimes': ['VOLATILE_BULL']},
        'XLF':  {'name': 'Financials', 'trigger': 'rate_steepening',
                  'regimes': ['CALM_BULL']},
        'XLK':  {'name': 'Tech', 'trigger': 'growth_rotation',
                  'regimes': ['CALM_BULL']},
        'XLV':  {'name': 'Healthcare', 'trigger': 'defensive',
                  'regimes': ['CHOPPY', 'RISK_OFF']},
        'XLY':  {'name': 'Cons Discretionary', 'trigger': 'consumer_strength',
                  'regimes': ['CALM_BULL']},
        'XLP':  {'name': 'Cons Staples', 'trigger': 'defensive',
                  'regimes': ['RISK_OFF']},
        'XLI':  {'name': 'Industrials', 'trigger': 'capex_cycle',
                  'regimes': ['CALM_BULL', 'VOLATILE_BULL']},
        'XLB':  {'name': 'Materials', 'trigger': 'inflation',
                  'regimes': ['VOLATILE_BULL']},
        'XLU':  {'name': 'Utilities', 'trigger': 'rate_falling',
                  'regimes': ['RISK_OFF', 'CRISIS']},
        'XLRE': {'name': 'Real Estate', 'trigger': 'rate_falling',
                  'regimes': ['RISK_OFF']},
        'XLC':  {'name': 'Communications', 'trigger': 'tech_rotation',
                  'regimes': ['CALM_BULL']},
        'ITA':  {'name': 'Defense ETF', 'trigger': 'geopolitical',
                  'regimes': ['VOLATILE_BULL', 'RISK_OFF', 'CRISIS']},
        'KRE':  {'name': 'Regional Banks', 'trigger': 'rate_steep',
                  'regimes': ['CALM_BULL']},
    },
}


def get_universe() -> dict:
    """Liefert vollstaendiges Universe mit Metadaten."""
    flat = []
    for category, assets in UNIVERSE.items():
        for ticker, meta in assets.items():
            flat.append({'ticker': ticker, 'category': category, **meta})
    return {
        'ts': datetime.now(timezone.utc).isoformat(),
        'total_assets': len(flat),
        'by_category': {cat: len(a) for cat, a in UNIVERSE.items()},
        'all_tickers': sorted(set(a['ticker'] for a in flat)),
        'universe': UNIVERSE,
        'flat': flat,
    }


def get_eligible_for_regime(regime: str) -> list[dict]:
    """Liefert alle Assets die fuer aktuelles Regime erlaubt sind."""
    eligible = []
    for category, assets in UNIVERSE.items():
        for ticker, meta in assets.items():
            if regime in meta.get('regimes', []):
                eligible.append({'ticker': ticker, 'category': category, **meta})
    return eligible


def main():
    u = get_universe()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(u, indent=2), encoding='utf-8')
    print(f'═══ Multi-Asset Universe ═══')
    print(f'  Total: {u["total_assets"]} Assets')
    print(f'  By Category: {u["by_category"]}')
    print(f'\nFor current regime (read from market_regime.json):')
    rf = WS / 'data' / 'market_regime.json'
    if rf.exists():
        regime = json.loads(rf.read_text(encoding='utf-8')).get('regime', 'UNKNOWN')
        eligible = get_eligible_for_regime(regime)
        print(f'  Regime: {regime} → {len(eligible)} eligible assets')
        for a in eligible[:10]: print(f"    {a['ticker']:<6} {a['category']:<12} {a['name']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
