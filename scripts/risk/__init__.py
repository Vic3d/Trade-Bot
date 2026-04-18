"""TradeMind Risk Package — Phase 21 Pro.

Modular Risk-Engine fuer Korrelationen, VaR, Cluster, Stress-Tests.

Entry-Points fuer andere Skripte:
    from risk.correlation_engine import compute_aggregated_matrix
    from risk.var_calculator import marginal_var, parametric_var
    from risk.clustering import find_dangerous_clusters
    from risk.stress_test import run_all_scenarios
"""

__version__ = '21.0.0'
