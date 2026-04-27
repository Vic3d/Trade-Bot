#!/usr/bin/env python3
"""
risk_based_sizing.py — Erichsen-Formel: Position aus EUR-Risiko ableiten.

Formel (Rendite-Spezialisten 17/2026, S.10):
    position_eur = portfolio_value * risk_pct / (entry - stop) * entry

Statt fixed-EUR-Cap (1500€) wird die Position so berechnet, dass der
maximale EUR-Verlust bei Stop-Out konstant ist (z.B. 1% des Funds).

Vorteil:
  - Enger Stop → größere Position (mehr Hebel auf saubere Setups)
  - Weiter Stop → kleinere Position (weniger Risiko bei volatilen Setups)
  - EUR-Risiko pro Trade ist immer berechenbar, nicht zufällig

Risiko-Klassen (per Strategie-Typ konfigurierbar):
  PS_*, PT (Thesis):     1.0% Risiko
  PM      (Momentum):    0.5%
  S*      (Setups):      0.5%
  Standard:              1.0%

Hard-Caps bleiben:
  - Position max 15% vom Fund (Guard 6b)
  - Min 5 Shares (sonst nicht sinnvoll)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
SIZING_CONFIG = WS / 'data' / 'sizing_config.json'

DEFAULT_CONFIG = {
    'risk_pct_by_prefix': {
        'PS_': 1.0,
        'PT':  1.0,
        'S':   0.5,
        'PM':  0.5,
    },
    'default_risk_pct': 1.0,
    'min_shares': 5,
    'max_position_pct': 15.0,  # Hard cap als % vom Portfolio
    'absolute_min_eur': 100.0,  # Unter 100€ macht kein Sinn (Fees)
}


def _load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if SIZING_CONFIG.exists():
        try:
            cfg.update(json.loads(SIZING_CONFIG.read_text(encoding='utf-8')))
        except Exception:
            pass
    # Phase 31b: max_position_pct kann durch autonomy_config überschrieben werden
    try:
        autonomy_path = WS / 'data' / 'autonomy_config.json'
        if autonomy_path.exists():
            ac = json.loads(autonomy_path.read_text(encoding='utf-8'))
            if 'max_position_pct' in ac:
                cfg['max_position_pct'] = float(ac['max_position_pct'])
    except Exception:
        pass
    return cfg


def _get_risk_pct(strategy: str, cfg: dict) -> float:
    """Findet Risk-% für Strategie via Prefix-Match."""
    prefix_map = cfg.get('risk_pct_by_prefix', {})
    # Längster Match gewinnt (PS_ vor S)
    best_match = None
    best_len = -1
    for prefix, pct in prefix_map.items():
        if strategy.startswith(prefix) and len(prefix) > best_len:
            best_match = pct
            best_len = len(prefix)
    return best_match if best_match is not None else cfg.get('default_risk_pct', 1.0)


def size_position_risk_based(
    strategy: str,
    portfolio_value_eur: float,
    entry_price: float,
    stop_price: float,
) -> dict:
    """
    Returns:
        {
            'shares': int,
            'position_eur': float,
            'risk_eur': float,
            'risk_pct': float,
            'reason': str,
            'skip': bool (if True: caller should fall back to other sizer)
        }
    """
    cfg = _load_config()

    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return {
            'shares': 0, 'position_eur': 0, 'risk_eur': 0, 'risk_pct': 0,
            'reason': f'invalid_prices (entry={entry_price}, stop={stop_price})',
            'skip': True,
        }

    risk_pct = _get_risk_pct(strategy, cfg)
    risk_per_share = entry_price - stop_price
    target_risk_eur = portfolio_value_eur * (risk_pct / 100.0)

    raw_shares = target_risk_eur / risk_per_share
    shares = int(raw_shares)

    # Min-shares check
    if shares < cfg.get('min_shares', 5):
        return {
            'shares': 0, 'position_eur': 0, 'risk_eur': 0, 'risk_pct': risk_pct,
            'reason': f'below_min_shares (raw={raw_shares:.1f} < min={cfg["min_shares"]})',
            'skip': True,
        }

    position_eur = shares * entry_price
    actual_risk_eur = shares * risk_per_share

    # Hard cap: max % vom Portfolio
    max_pos_eur = portfolio_value_eur * (cfg.get('max_position_pct', 15.0) / 100.0)
    if position_eur > max_pos_eur:
        shares = int(max_pos_eur / entry_price)
        position_eur = shares * entry_price
        actual_risk_eur = shares * risk_per_share

    # Min EUR check
    if position_eur < cfg.get('absolute_min_eur', 100.0):
        return {
            'shares': 0, 'position_eur': position_eur, 'risk_eur': 0, 'risk_pct': risk_pct,
            'reason': f'below_min_eur ({position_eur:.0f} < {cfg["absolute_min_eur"]})',
            'skip': True,
        }

    return {
        'shares': shares,
        'position_eur': round(position_eur, 2),
        'risk_eur': round(actual_risk_eur, 2),
        'risk_pct': risk_pct,
        'reason': f'erichsen-formula: {risk_pct}% von {portfolio_value_eur:.0f}€ = {actual_risk_eur:.0f}€ Risiko',
        'skip': False,
    }


if __name__ == '__main__':
    # Smoke test
    print('--- Test 1: PS_NVDA, enger Stop ---')
    r = size_position_risk_based('PS_NVDA', 25000, 100.0, 95.0)
    print(json.dumps(r, indent=2))
    # Expect: ~50 shares (250€ Risiko / 5€ pro Share)

    print('\n--- Test 2: PM_AAPL, weiter Stop ---')
    r = size_position_risk_based('PM_AAPL', 25000, 200.0, 180.0)
    print(json.dumps(r, indent=2))
    # Expect: ~6 shares (125€ Risiko / 20€ pro Share)

    print('\n--- Test 3: invalid (stop >= entry) ---')
    r = size_position_risk_based('PS_X', 25000, 50, 55)
    print(json.dumps(r, indent=2))

    print('\n--- Test 4: max-position-pct cap ---')
    r = size_position_risk_based('PS_LOW', 25000, 1.0, 0.99)  # winziger Stop → max-cap
    print(json.dumps(r, indent=2))
