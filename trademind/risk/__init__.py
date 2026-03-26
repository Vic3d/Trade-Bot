"""
trademind/risk/ — Portfolio-Level Risikomanagement

Module:
    correlation     → Pairwise Korrelation vor jedem Trade
    portfolio       → Sector/Region/Ticker Exposure-Limits
    circuit_breaker → Daily/Weekly Loss Limits, Max Drawdown, VIX Panic
    stress_test     → Szenario-Simulationen (VIX Spike, Oil Crash, etc.)
"""

from .correlation import check_correlation
from .portfolio import get_portfolio_exposure
from .circuit_breaker import check_circuit_breakers
from .stress_test import run_stress_tests

__all__ = [
    "check_correlation",
    "get_portfolio_exposure",
    "check_circuit_breakers",
    "run_stress_tests",
]
