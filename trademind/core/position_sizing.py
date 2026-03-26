"""
trademind/core/position_sizing.py — ATR-basierte, VIX-adaptive Position Sizing

Usage:
    from trademind.core.position_sizing import calculate_position

    pos = calculate_position(
        portfolio_size=100_000,
        vix_zone='medium',
        price=45.20,           # in EUR
        atr=1.35               # in EUR
    )
    # pos = {
    #   'shares': 83,
    #   'position_value': 3751.60,
    #   'risk_eur': 225.0,
    #   'stop_price': 42.50,
    #   'stop_distance': 2.70,
    #   'risk_pct': 0.015,
    # }
"""
from trademind.core.config import (
    RISK_PCT,
    ATR_STOP_MULTIPLIER,
    MIN_CASH_PCT,
    DEFAULT_PORTFOLIO_SIZE,
)


def calculate_position(
    portfolio_size: float,
    vix_zone: str,
    price: float,
    atr: float,
) -> dict | None:
    """
    Berechnet Positionsgröße basierend auf ATR-Stop und VIX-Zone.

    Args:
        portfolio_size:  Gesamtportfolio in EUR
        vix_zone:        'low' | 'medium' | 'high' | 'extreme'
        price:           Einstiegspreis in EUR
        atr:             ATR(14) in EUR

    Returns:
        dict mit Positionsdetails oder None wenn nicht berechenbar
    """
    # Normalisierung: albert_strategy nutzt andere Zonen-Namen
    zone_map = {"normal": "medium", "elevated": "medium"}
    zone = zone_map.get(vix_zone, vix_zone)

    risk_pct = RISK_PCT.get(zone, RISK_PCT["medium"])
    risk_budget = portfolio_size * risk_pct

    stop_distance = atr * ATR_STOP_MULTIPLIER
    if stop_distance <= 0 or price <= 0:
        return None

    shares = int(risk_budget / stop_distance)
    if shares <= 0:
        return None

    position_value = shares * price

    # Max-Position: immer mindestens MIN_CASH_PCT in Cash halten
    max_position = portfolio_size * (1 - MIN_CASH_PCT)
    if position_value > max_position:
        shares = int(max_position / price)
        position_value = shares * price

    stop_price = price - stop_distance

    return {
        "shares":         shares,
        "position_value": round(position_value, 2),
        "risk_eur":       round(shares * stop_distance, 2),
        "stop_price":     round(stop_price, 2),
        "stop_distance":  round(stop_distance, 2),
        "risk_pct":       risk_pct,
    }
