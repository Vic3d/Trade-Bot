"""
trademind/execution — Realistische Execution-Simulation.

Exports:
    simulate_fill(price, side, ticker, vix) → dict
    estimate_gap_risk(ticker, position_value) → dict
"""
from trademind.execution.simulator import simulate_fill, LIQUIDITY, get_liquidity_class
from trademind.execution.gap_model import estimate_gap_risk

__all__ = ["simulate_fill", "estimate_gap_risk", "LIQUIDITY", "get_liquidity_class"]
