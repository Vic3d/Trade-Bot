#!/usr/bin/env python3
"""
Vol-Target Position Sizing — Phase 19b
========================================

Replaces the fixed 1.500€ position size with volatility-adjusted sizing.

**Principle:** Each position should contribute the same RISK to the
portfolio, not the same nominal value. A high-vol tech stock with 40%
annualized vol should be sized smaller than a low-vol utility at 15%.

**Method:** ATR-based risk parity.
  1. Compute 20-day ATR (Average True Range)
  2. Dollar-risk-per-trade = portfolio_value * risk_pct (default 1%)
  3. Shares = dollar_risk / (atr_multiplier * ATR)
  4. Cap at max_position_pct of portfolio (default 15%)

**Conviction Scaling:** High-conviction trades get 1.5x base risk,
low-conviction get 0.5x. Based on Phase 3 conviction_scorer output.

Usage:
    from execution.position_sizing import size_position

    sizing = size_position(
        ticker='NVDA',
        entry_price=850,
        stop_price=820,
        portfolio_value_eur=25000,
        conviction_score=65,          # from Phase 3 scorer
        fx_rate=0.93,                 # USD → EUR
    )
    # → {'shares': ..., 'position_eur': ..., 'risk_eur': ...,
    #    'risk_pct': ..., 'method': ..., 'size_reason': ...}
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class SizingConfig:
    base_risk_pct: float = 0.010       # 1% of portfolio per trade
    max_position_pct: float = 0.15     # 15% of portfolio max single position
    min_position_eur: float = 500      # don't size below this
    atr_multiplier_stop: float = 2.0   # ATR → implicit stop distance
    conviction_low: int = 45           # below: scale down
    conviction_high: int = 60          # above: scale up
    low_scale: float = 0.5
    high_scale: float = 1.5


DEFAULT = SizingConfig()


# ── ATR Computation ───────────────────────────────────────────────────────────

def _compute_atr(ticker: str, period: int = 20) -> float | None:
    """Classic Wilder ATR from prices table."""
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute("""
            SELECT high, low, close FROM prices
            WHERE ticker = ?
            ORDER BY date DESC LIMIT ?
        """, (ticker, period + 1)).fetchall()
        conn.close()
    except Exception:
        return None

    if len(rows) < period:
        return None

    # rows are newest-first → reverse for chronological
    rows = list(reversed(rows))
    true_ranges = []
    prev_close = rows[0][2]
    for h, l, c in rows[1:]:
        if h is None or l is None or c is None:
            continue
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        true_ranges.append(tr)
        prev_close = c

    if not true_ranges:
        return None
    return sum(true_ranges) / len(true_ranges)


def _conviction_scale(conviction: int | None, cfg: SizingConfig) -> float:
    """Returns risk multiplier based on conviction score (0-100)."""
    if conviction is None:
        return 1.0
    if conviction < cfg.conviction_low:
        return cfg.low_scale
    if conviction >= cfg.conviction_high:
        return cfg.high_scale
    # Linear interpolation between
    span = cfg.conviction_high - cfg.conviction_low
    t = (conviction - cfg.conviction_low) / span
    return cfg.low_scale + t * (cfg.high_scale - cfg.low_scale)


# ── Main Sizing Function ──────────────────────────────────────────────────────

def size_position(
    ticker: str,
    entry_price: float,
    stop_price: float | None = None,
    portfolio_value_eur: float = 25000,
    conviction_score: int | None = None,
    fx_rate: float = 1.0,            # local currency → EUR
    cfg: SizingConfig | None = None,
) -> dict:
    """
    Volatility-targeted position sizing.

    Args:
        ticker:              Symbol
        entry_price:         Entry price (local currency)
        stop_price:          Stop price (local currency). If None, uses ATR-based.
        portfolio_value_eur: Total portfolio value for risk calculation
        conviction_score:    Phase 3 conviction (0-100). Scales risk.
        fx_rate:             Local → EUR conversion rate
        cfg:                 Optional SizingConfig override

    Returns dict with shares, position_eur, risk_eur, method, reasoning.
    """
    cfg = cfg or DEFAULT

    if entry_price <= 0:
        return {'error': 'invalid entry price', 'shares': 0, 'position_eur': 0}

    # ── Step 1: determine stop distance ────────────────────────────────
    atr = _compute_atr(ticker)
    stop_distance_local: float
    stop_source: str

    if stop_price and stop_price < entry_price:
        stop_distance_local = entry_price - stop_price
        stop_source = 'explicit_stop'
    elif atr:
        stop_distance_local = atr * cfg.atr_multiplier_stop
        stop_source = f'atr*{cfg.atr_multiplier_stop}'
    else:
        # Fallback: fixed 5% stop
        stop_distance_local = entry_price * 0.05
        stop_source = 'fallback_5pct'

    stop_distance_eur = stop_distance_local * fx_rate

    # ── Step 2: compute risk budget in EUR ─────────────────────────────
    scale = _conviction_scale(conviction_score, cfg)
    risk_budget_eur = portfolio_value_eur * cfg.base_risk_pct * scale

    # ── Step 3: size by risk / per-share risk ──────────────────────────
    if stop_distance_eur <= 0:
        return {'error': 'zero stop distance', 'shares': 0, 'position_eur': 0}

    shares_risk = risk_budget_eur / stop_distance_eur
    position_eur_risk = shares_risk * entry_price * fx_rate

    # ── Step 4: enforce max position cap ───────────────────────────────
    max_position_eur = portfolio_value_eur * cfg.max_position_pct
    capped = False
    if position_eur_risk > max_position_eur:
        position_eur = max_position_eur
        shares = position_eur / (entry_price * fx_rate)
        capped = True
        actual_risk_eur = shares * stop_distance_eur
    else:
        position_eur = position_eur_risk
        shares = shares_risk
        actual_risk_eur = risk_budget_eur

    # ── Step 5: enforce min position ───────────────────────────────────
    skip = False
    if position_eur < cfg.min_position_eur:
        skip = True

    # Round shares to whole numbers (broker reality)
    shares_int = int(shares)
    if shares_int <= 0:
        skip = True

    # Recompute final values with integer shares
    final_position_eur = shares_int * entry_price * fx_rate
    final_risk_eur = shares_int * stop_distance_eur

    reason_parts = [
        f'stop={stop_source}',
        f'stop_dist={stop_distance_local:.2f}',
        f'risk_budget={risk_budget_eur:.0f}€',
    ]
    if conviction_score is not None:
        reason_parts.append(f'conviction={conviction_score}→{scale:.1f}x')
    if capped:
        reason_parts.append(f'capped_at_{cfg.max_position_pct*100:.0f}%')
    if skip:
        reason_parts.append('BELOW_MIN_SKIP')

    return {
        'ticker': ticker,
        'shares': shares_int,
        'position_eur': round(final_position_eur, 2),
        'risk_eur': round(final_risk_eur, 2),
        'risk_pct_of_portfolio': round(final_risk_eur / portfolio_value_eur * 100, 2),
        'stop_distance_local': round(stop_distance_local, 4),
        'stop_distance_eur': round(stop_distance_eur, 4),
        'atr': round(atr, 4) if atr else None,
        'scale': round(scale, 2),
        'capped': capped,
        'skip': skip,
        'method': 'vol_target',
        'reason': ' | '.join(reason_parts),
    }


# ── Batch sizing for portfolio-level review ───────────────────────────────────

def portfolio_vol_check(positions: list[dict], portfolio_value_eur: float) -> dict:
    """
    Given currently-open positions, computes aggregate risk exposure.

    positions: list of dicts with keys: ticker, entry_price, stop_price,
               shares, fx_rate (optional)

    Returns dict with total_risk_eur, total_risk_pct, per_position breakdown.
    """
    total_risk = 0.0
    details = []

    for p in positions:
        ticker = p.get('ticker', '')
        entry = p.get('entry_price', 0)
        stop = p.get('stop_price') or p.get('stop', 0)
        shares = p.get('shares', 0)
        fx = p.get('fx_rate', 1.0)

        if entry and stop and shares and entry > stop:
            risk_per_share = (entry - stop) * fx
            position_risk = risk_per_share * shares
            total_risk += position_risk
            details.append({
                'ticker': ticker,
                'risk_eur': round(position_risk, 2),
                'risk_pct': round(position_risk / portfolio_value_eur * 100, 2),
            })

    return {
        'portfolio_value_eur': portfolio_value_eur,
        'total_risk_eur': round(total_risk, 2),
        'total_risk_pct': round(total_risk / portfolio_value_eur * 100, 2),
        'n_positions': len(details),
        'positions': details,
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

def _self_test():
    import json

    print('── Position Sizing Self-Test ──\n')

    cases = [
        ('NVDA', 850.0, 820.0, 65, 0.93, 'High-conviction US'),
        ('NVDA', 850.0, 820.0, 30, 0.93, 'Low-conviction US'),
        ('NVDA', 850.0, None, 50, 0.93, 'No stop → ATR-based'),
        ('RHM.DE', 500.0, 480.0, 55, 1.00, 'EU mid-cap'),
        ('EQNR.OL', 35.0, 33.0, 60, 0.087, 'NOK position'),
    ]

    for ticker, entry, stop, conv, fx, label in cases:
        print(f'── {label}: {ticker} ──')
        result = size_position(
            ticker=ticker,
            entry_price=entry,
            stop_price=stop,
            portfolio_value_eur=25000,
            conviction_score=conv,
            fx_rate=fx,
        )
        print(json.dumps(result, indent=2))
        print()


if __name__ == '__main__':
    _self_test()
