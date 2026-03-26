"""
trademind/analytics/ — Statistische Validierung & Metriken (Phase 4)

Module:
    metrics.py      — Sharpe, Sortino, Max DD, Calmar, Profit Factor, ...
    significance.py — Binomial-Test, t-Test, Bootstrap CI
    monte_carlo.py  — Monte Carlo Simulation (10.000 Szenarien)
    health.py       — Strategy Health Report (KEEP / REVIEW / KILL)
"""
from .metrics import calculate_strategy_metrics
from .significance import test_strategy_significance
from .monte_carlo import monte_carlo_simulation
from .health import generate_health_report

__all__ = [
    "calculate_strategy_metrics",
    "test_strategy_significance",
    "monte_carlo_simulation",
    "generate_health_report",
]
