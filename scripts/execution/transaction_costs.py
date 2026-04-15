#!/usr/bin/env python3
"""
Transaction Cost Model — Phase 19a
====================================

Models realistic trading frictions that Paper-Trading ignores:

  1. **Spread**       — Bid/Ask gap (wider for EU mid-caps, tight for US large-caps)
  2. **Slippage**     — Market impact on top of mid-price for retail orders
  3. **FX conversion** — Trade Republic / IBKR spread on non-EUR currencies
  4. **Commission**   — Fixed broker fee per trade

Cost estimates are intentionally CONSERVATIVE (pessimistic) because
underestimating real-world costs is the #1 cause of paper-to-real
performance collapse.

Usage:
    from execution.transaction_costs import estimate_trade_cost

    cost = estimate_trade_cost(
        ticker='NVDA',
        direction='entry',    # 'entry' or 'exit'
        price=850.0,
        shares=10,
        broker='trade_republic',
    )
    # → {'spread_eur': ..., 'slippage_eur': ..., 'fx_eur': ...,
    #    'commission_eur': ..., 'total_eur': ..., 'total_bps': ...}

    # Net PnL calculation for a full round-trip:
    net = net_pnl(
        ticker='NVDA',
        entry_price=850, exit_price=920,
        shares=10, currency='USD',
    )
    # → {'gross_pnl_eur': ..., 'total_costs_eur': ..., 'net_pnl_eur': ...}
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Per-market cost profiles (bps = basis points = 0.01%) ─────────────────────
# Based on empirical retail-broker spreads observed on TR/IBKR/DeGiro 2024-2025.

@dataclass
class MarketProfile:
    name: str
    spread_bps: float          # half-spread (each direction)
    slippage_bps: float        # additional slippage per trade
    min_commission_eur: float  # per-trade fixed fee
    fx_spread_bps: float       # currency conversion (one-way)
    currency: str


# Classification: we look at the ticker suffix and known symbols.
# Large-cap US (tight): SPY, NVDA, AAPL, MSFT, etc.
# EU mid-cap (wide):    most .DE / .PA / .MI / .AS tickers
# Small-cap:            anything in the penny range

_PROFILES: dict[str, MarketProfile] = {
    'us_large': MarketProfile(
        name='US Large Cap',
        spread_bps=5,        # 0.05% each side → 0.10% round-trip
        slippage_bps=5,      # 0.05%
        min_commission_eur=1.0,
        fx_spread_bps=25,    # 0.25% each FX conversion
        currency='USD',
    ),
    'us_mid': MarketProfile(
        name='US Mid Cap',
        spread_bps=10,
        slippage_bps=10,
        min_commission_eur=1.0,
        fx_spread_bps=25,
        currency='USD',
    ),
    'eu_large': MarketProfile(
        name='EU Large Cap',
        spread_bps=8,
        slippage_bps=8,
        min_commission_eur=1.0,
        fx_spread_bps=0,
        currency='EUR',
    ),
    'eu_mid': MarketProfile(
        name='EU Mid Cap',
        spread_bps=20,       # 0.20% each side → 0.40% round-trip
        slippage_bps=15,
        min_commission_eur=1.0,
        fx_spread_bps=0,
        currency='EUR',
    ),
    'small_cap': MarketProfile(
        name='Small Cap / Illiquid',
        spread_bps=50,       # 0.50% each side → 1.00% round-trip
        slippage_bps=30,
        min_commission_eur=1.0,
        fx_spread_bps=0,
        currency='EUR',
    ),
    'uk': MarketProfile(
        name='UK Large Cap',
        spread_bps=10,
        slippage_bps=10,
        min_commission_eur=1.0,
        fx_spread_bps=25,
        currency='GBP',
    ),
    'no_oil': MarketProfile(  # Norwegian oil/energy
        name='Norway',
        spread_bps=15,
        slippage_bps=10,
        min_commission_eur=1.0,
        fx_spread_bps=30,    # NOK-EUR wider
        currency='NOK',
    ),
}


# US large-cap tickers (expandable list — everything else is "us_mid" default)
_US_LARGE_CAPS = {
    'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'TSLA',
    'JPM', 'V', 'MA', 'JNJ', 'UNH', 'XOM', 'CVX', 'PG', 'HD', 'KO',
    'PEP', 'BAC', 'WMT', 'DIS', 'NFLX', 'ADBE', 'CRM', 'ORCL', 'AVGO',
    'SPY', 'QQQ', 'VOO', 'VTI', 'IWM', 'EEM', 'TLT', 'GLD', 'SLV',
    'PLTR', 'AMD', 'INTC', 'CSCO', 'IBM', 'PFE', 'LLY', 'NKE', 'COST',
}


def classify_market(ticker: str) -> str:
    """Returns the market profile key for a ticker."""
    t = ticker.upper()

    # EU suffixes
    if '.DE' in t or '.F' in t:
        return 'eu_mid' if t.split('.')[0] not in {'SAP', 'SIE', 'ALV', 'BAS', 'DTE'} else 'eu_large'
    if '.PA' in t:
        return 'eu_mid' if t.split('.')[0] not in {'MC', 'TTE', 'LVMH', 'SAN'} else 'eu_large'
    if '.MI' in t or '.AS' in t or '.BR' in t or '.MC' in t or '.LS' in t:
        return 'eu_mid'
    if '.L' in t:
        return 'uk'
    if '.OL' in t:
        return 'no_oil'
    if '.CO' in t or '.ST' in t or '.HE' in t:
        return 'eu_mid'

    # German WKN (6 chars alphanumeric, starts with A or 5/6/7/8/9)
    if len(t) == 6 and t[0] in 'A56789':
        return 'eu_mid'

    # US — check large-cap set first
    if t in _US_LARGE_CAPS:
        return 'us_large'

    # Default to US mid-cap (most common case for unknown US tickers)
    return 'us_mid'


def get_profile(ticker: str) -> MarketProfile:
    key = classify_market(ticker)
    return _PROFILES.get(key, _PROFILES['us_mid'])


def estimate_trade_cost(
    ticker: str,
    direction: str,             # 'entry' | 'exit'
    price: float,
    shares: float,
    broker: str = 'trade_republic',
) -> dict:
    """
    Estimates all frictional costs for ONE side of a trade (entry OR exit).

    Returns absolute EUR amounts per category + total.
    """
    profile = get_profile(ticker)
    notional_local = price * shares
    # Rough FX-free conversion assumption — caller should convert if needed.
    # For sizing we estimate in local currency EUR-equivalent by just using
    # price*shares as a proxy; real conversion happens in net_pnl().

    spread_cost = notional_local * (profile.spread_bps / 10_000)
    slippage_cost = notional_local * (profile.slippage_bps / 10_000)
    fx_cost = 0.0
    if profile.currency != 'EUR':
        fx_cost = notional_local * (profile.fx_spread_bps / 10_000)

    commission = profile.min_commission_eur
    # IBKR uses per-share; TR is flat 1€. We default to flat.
    if broker == 'ibkr':
        commission = max(1.0, shares * 0.005)  # $0.005/share, min $1

    total = spread_cost + slippage_cost + fx_cost + commission

    return {
        'market': profile.name,
        'currency': profile.currency,
        'notional_local': round(notional_local, 2),
        'spread_local': round(spread_cost, 2),
        'slippage_local': round(slippage_cost, 2),
        'fx_local': round(fx_cost, 2),
        'commission_eur': round(commission, 2),
        'total_local': round(total, 2),
        'total_bps': round(total / notional_local * 10_000, 1) if notional_local else 0,
    }


def net_pnl(
    ticker: str,
    entry_price: float,
    exit_price: float,
    shares: float,
    fx_rate: float = 1.0,        # local currency → EUR
    broker: str = 'trade_republic',
) -> dict:
    """
    Computes realistic NET PnL in EUR for a full round-trip trade
    after all frictions.

    Returns dict with gross_pnl_eur, total_costs_eur, net_pnl_eur, net_pnl_pct
    """
    entry_cost = estimate_trade_cost(ticker, 'entry', entry_price, shares, broker)
    exit_cost = estimate_trade_cost(ticker, 'exit', exit_price, shares, broker)

    gross_local = (exit_price - entry_price) * shares
    total_costs_local = entry_cost['total_local'] + exit_cost['total_local']

    gross_eur = gross_local * fx_rate
    # commission is already in EUR, deduct separately
    commission_eur = entry_cost['commission_eur'] + exit_cost['commission_eur']
    frictions_local = total_costs_local - commission_eur
    frictions_eur = frictions_local * fx_rate

    total_costs_eur = frictions_eur + commission_eur
    net_eur = gross_eur - total_costs_eur

    # Percentage relative to notional entry
    entry_notional_eur = entry_price * shares * fx_rate
    net_pct = (net_eur / entry_notional_eur * 100) if entry_notional_eur > 0 else 0
    gross_pct = (gross_eur / entry_notional_eur * 100) if entry_notional_eur > 0 else 0

    return {
        'market': entry_cost['market'],
        'currency': entry_cost['currency'],
        'fx_rate': fx_rate,
        'gross_pnl_eur': round(gross_eur, 2),
        'total_costs_eur': round(total_costs_eur, 2),
        'net_pnl_eur': round(net_eur, 2),
        'gross_pnl_pct': round(gross_pct, 2),
        'net_pnl_pct': round(net_pct, 2),
        'cost_drag_pct': round(gross_pct - net_pct, 2),
        'entry_costs_local': entry_cost['total_local'],
        'exit_costs_local': exit_cost['total_local'],
    }


def annualized_cost_drag(
    avg_trade_eur: float = 1500,
    avg_holding_days: int = 10,
    trades_per_year: int = 100,
    sample_ticker: str = 'NVDA',
) -> dict:
    """
    Rough estimate: how much edge does the cost model eat per year?

    Useful for calibrating minimum expected-value thresholds.
    """
    shares = avg_trade_eur / 100  # dummy price 100
    cost_per_side = estimate_trade_cost(sample_ticker, 'entry', 100, shares)
    round_trip = 2 * cost_per_side['total_bps']  # bps
    annual_bps = round_trip * trades_per_year
    return {
        'sample_ticker': sample_ticker,
        'round_trip_bps': round(round_trip, 1),
        'trades_per_year': trades_per_year,
        'annual_cost_bps': round(annual_bps, 1),
        'annual_cost_pct': round(annual_bps / 100, 2),
        'min_edge_per_trade_bps': round(round_trip * 1.5, 1),
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

def _self_test():
    import json

    print('── Transaction Cost Model Self-Test ──\n')

    samples = [
        ('NVDA', 850.0, 10, 'us_large'),
        ('PLTR', 25.0, 200, 'us_large'),
        ('RHM.DE', 500.0, 5, 'eu_mid'),
        ('EQNR.OL', 35.0, 100, 'no_oil'),
        ('AAPL', 180.0, 20, 'us_large'),
    ]

    for ticker, price, shares, expected in samples:
        profile_key = classify_market(ticker)
        cost = estimate_trade_cost(ticker, 'entry', price, shares)
        print(f'{ticker:10} price={price:8.2f} shares={shares:4}')
        print(f'   profile: {profile_key} ({cost["market"]})')
        print(f'   cost:    {cost["total_local"]:.2f} {cost["currency"]} '
              f'({cost["total_bps"]:.1f} bps)')
        print()

    print('── Round-Trip Example: NVDA 850 → 920, 10 shares, FX 0.93 ──')
    rt = net_pnl('NVDA', 850, 920, 10, fx_rate=0.93)
    print(json.dumps(rt, indent=2))

    print('\n── Annual Cost Drag (100 trades/year, 1500€ avg) ──')
    drag = annualized_cost_drag()
    print(json.dumps(drag, indent=2))


if __name__ == '__main__':
    _self_test()
