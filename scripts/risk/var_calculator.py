"""VaR Calculator — Parametric / Historical / CVaR / Marginal / Component VaR.

Phase 21 Pro. Pure numpy.

Public API:
    parametric_var(weights, cov, conf, horizon)         -> EUR
    historical_var(weights, returns_matrix, conf)       -> EUR
    conditional_var_es(weights, returns_matrix, conf)   -> EUR (Expected Shortfall)
    marginal_var(weights, cov, position_idx, conf)      -> EUR per 1 EUR added
    component_var(weights, cov)                         -> array (Decomposition)
    diversification_ratio(weights, vols, cov)           -> float
    effective_n_bets(weights, cov)                      -> float

Konventionen:
- weights: EUR-Beträge pro Position (Position-Value, NICHT prozentual)
- cov: Tagesvarianz (z.B. var_daily = (return)^2)
- horizon: in Tagen (1-day VaR ist Standard)
- confidence: 0.95 = 95%-VaR (z=1.645), 0.99 (z=2.326)

Alle VaR-Werte sind POSITIV (= Verlust-Höhe).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# ─── Z-Quantile (analytisch fuer Normal-Verteilung) ──────────────────────────
_Z = {
    0.90: 1.282,
    0.95: 1.645,
    0.975: 1.960,
    0.99: 2.326,
    0.995: 2.576,
}


def _z_score(confidence: float) -> float:
    """Liefert Normal-Quantil. Default Linear-Interpolation falls nicht in Tabelle."""
    if confidence in _Z:
        return _Z[confidence]
    # Default: 95%
    return 1.645


# ─── Parametric VaR ──────────────────────────────────────────────────────────
def parametric_var(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> float:
    """Klassische Parametric VaR (Variance-Covariance-Methode).

    sigma_p = sqrt(w^T Sigma w)
    VaR = z_alpha * sigma_p * sqrt(horizon)

    Annahme: Returns sind multivariat-normal-verteilt.
    Schwaeche: unterschaetzt Tail-Risiko bei Fat-Tails (siehe historical_var).

    Args:
        weights: array of EUR amounts per position
        cov_matrix: NxN covariance matrix of DAILY returns
        confidence: 0.95 etc.
        horizon_days: typical 1

    Returns: VaR in EUR (positive value = potential loss)
    """
    w = np.asarray(weights, dtype=float)
    if w.size == 0 or cov_matrix.size == 0:
        return 0.0
    portfolio_var = float(w @ cov_matrix @ w)
    if portfolio_var <= 0:
        return 0.0
    sigma_p = np.sqrt(portfolio_var)
    z = _z_score(confidence)
    return float(z * sigma_p * np.sqrt(horizon_days))


# ─── Historical VaR ──────────────────────────────────────────────────────────
def historical_var(
    weights: np.ndarray,
    returns_matrix: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Empirische VaR — simuliert Portfolio-P&L ueber jeden historischen Tag.

    Robuster gegen Fat-Tails als Parametric, aber sample-size-limited.

    Args:
        weights: EUR amounts per position
        returns_matrix: T x N matrix of historical returns
        confidence: 0.95 = 95% VaR (Verlust den nur 5% der Tage uebersteigen)

    Returns: VaR in EUR (positive)
    """
    w = np.asarray(weights, dtype=float)
    R = np.asarray(returns_matrix, dtype=float)
    if R.size == 0 or w.size == 0 or R.shape[1] != w.size:
        return 0.0
    portfolio_pnl = R @ w  # T-vector of EUR P&L per day
    # VaR = -quantile (Verluste sind negativ -> wir nehmen Negativ)
    quantile = np.quantile(portfolio_pnl, 1.0 - confidence)
    return float(max(0.0, -quantile))


# ─── Conditional VaR (Expected Shortfall) ────────────────────────────────────
def conditional_var_es(
    weights: np.ndarray,
    returns_matrix: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Expected Shortfall = Mittlerer Verlust in den schlimmsten (1-conf)% Tagen.

    Antwort auf 'Wenn der Worst-Case eintritt, wie schlimm wird es im Schnitt?'
    ES >= VaR immer.

    Returns: ES in EUR (positive)
    """
    w = np.asarray(weights, dtype=float)
    R = np.asarray(returns_matrix, dtype=float)
    if R.size == 0 or w.size == 0 or R.shape[1] != w.size:
        return 0.0
    portfolio_pnl = R @ w
    threshold = np.quantile(portfolio_pnl, 1.0 - confidence)
    tail_losses = portfolio_pnl[portfolio_pnl <= threshold]
    if tail_losses.size == 0:
        return 0.0
    return float(max(0.0, -tail_losses.mean()))


# ─── Marginal VaR (KEY FOR PRE-TRADE GUARD 5d) ───────────────────────────────
def marginal_var(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
    position_idx: int,
    confidence: float = 0.95,
) -> float:
    """d(VaR)/d(w_i) — wieviel aendert sich VaR pro 1 EUR mehr in Position i?

    Formel: MVaR_i = z * (Sigma w)_i / sigma_p

    Das ist die KEY-METRIC fuer Pre-Trade-Decision:
    'Wenn ich diese Position um X EUR vergroesere, steigt VaR um X * MVaR_i'

    Args:
        weights: aktuelle Portfolio-Gewichte (EUR), inkl. der zu pruefenden Position
        cov_matrix: NxN Cov-Matrix
        position_idx: Index der zu pruefenden Position in weights/cov

    Returns: MVaR in EUR pro 1 EUR Position-Erhoehung
    """
    w = np.asarray(weights, dtype=float)
    if w.size == 0 or cov_matrix.size == 0 or position_idx >= w.size:
        return 0.0
    portfolio_var = float(w @ cov_matrix @ w)
    if portfolio_var <= 1e-12:
        # Single-Position-Edge-Case: MVaR = z * sigma_i
        sigma_i = np.sqrt(max(0.0, cov_matrix[position_idx, position_idx]))
        return float(_z_score(confidence) * sigma_i)
    sigma_p = np.sqrt(portfolio_var)
    cov_w = cov_matrix @ w
    z = _z_score(confidence)
    return float(z * cov_w[position_idx] / sigma_p)


def component_var(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
    confidence: float = 0.95,
) -> np.ndarray:
    """Zerlegung des Total-VaR in Beitraege pro Position.

    sum(component_var) = parametric_var (per Definition)

    Wichtig fuer Dashboard: 'NVDA stellt 28% des Total-Portfolio-Risk'
    """
    w = np.asarray(weights, dtype=float)
    if w.size == 0 or cov_matrix.size == 0:
        return np.zeros(0)
    portfolio_var = float(w @ cov_matrix @ w)
    if portfolio_var <= 1e-12:
        return np.zeros(w.size)
    sigma_p = np.sqrt(portfolio_var)
    z = _z_score(confidence)
    cov_w = cov_matrix @ w
    # Component_i = w_i * MVaR_i
    return z * w * cov_w / sigma_p


# ─── Diversification Ratio (Choueifaty/Coignard 2008) ────────────────────────
def diversification_ratio(
    weights: np.ndarray,
    vols: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """DR = sum(|w_i| * sigma_i) / sigma_p

    = 1.0 wenn alles perfect korreliert (= keine Diversifikation)
    > 1.0 je besser diversifiziert
    Praktisch: 1.5-2.0 fuer 10-Asset gut diversifiziertes Portfolio
    """
    w = np.asarray(weights, dtype=float)
    v = np.asarray(vols, dtype=float)
    if w.size == 0 or v.size == 0 or w.size != v.size:
        return 1.0
    weighted_vol_sum = float(np.sum(np.abs(w) * v))
    portfolio_var = float(w @ cov_matrix @ w)
    if portfolio_var <= 1e-12 or weighted_vol_sum <= 1e-12:
        return 1.0
    return weighted_vol_sum / np.sqrt(portfolio_var)


# ─── Effective Number of Bets ────────────────────────────────────────────────
def effective_n_bets(weights: np.ndarray, cov_matrix: np.ndarray) -> float:
    """ENB via Entropie der Risk-Contributions.

    'Wieviele unabhaengige Wetten habe ich wirklich?'
    10 Tech-Aktien -> ENB ~1.5
    Diversifiziertes 10er -> ENB ~7

    Formel: ENB = exp(-sum(p_i * log(p_i)))
        wo p_i = component_var_i / total_var
    """
    cv = component_var(weights, cov_matrix)
    if cv.size == 0:
        return 0.0
    total = cv.sum()
    if total <= 1e-12:
        return float(cv.size)  # gleichverteilt
    p = cv / total
    p = p[p > 1e-12]  # filter noise
    if p.size == 0:
        return 0.0
    entropy = -np.sum(p * np.log(p))
    return float(np.exp(entropy))


# ─── Helper: Vols from Returns ───────────────────────────────────────────────
def estimate_vols(returns_matrix: np.ndarray) -> np.ndarray:
    """Sample-Standardabweichung pro Asset (taegliche Vola)."""
    R = np.asarray(returns_matrix, dtype=float)
    if R.size == 0:
        return np.zeros(0)
    return np.std(R, axis=0, ddof=1)


# ─── Self-Test ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    np.random.seed(42)

    # 3-Asset Portfolio: EUR-Beträge
    weights = np.array([5000.0, 3000.0, 2000.0])

    # Tagesreturns simulieren
    T = 252
    rets = np.random.multivariate_normal(
        mean=[0.0005, 0.0003, 0.0002],
        cov=[[0.0004, 0.00012, 0.00008],
             [0.00012, 0.0003, 0.00006],
             [0.00008, 0.00006, 0.0002]],
        size=T,
    )
    cov = np.cov(rets, rowvar=False)
    vols = np.sqrt(np.diag(cov))

    print('=== 3-Asset Portfolio (EUR 5000/3000/2000) ===')
    print(f'Daily Vols: {vols.round(4)}')
    print()
    print('--- VaR Metrics (95%, 1-day) ---')
    var_param = parametric_var(weights, cov, 0.95)
    var_hist = historical_var(weights, rets, 0.95)
    es = conditional_var_es(weights, rets, 0.95)
    print(f'Parametric VaR : EUR {var_param:.2f}')
    print(f'Historical VaR : EUR {var_hist:.2f}')
    print(f'CVaR (ES)      : EUR {es:.2f}')
    print()
    print('--- Marginal VaR per Position ---')
    for i in range(3):
        mvar = marginal_var(weights, cov, i, 0.95)
        print(f'  Position {i} (EUR {weights[i]:.0f}): MVaR = {mvar:.4f} EUR per 1 EUR added')
    print()
    print('--- Component VaR (Decomposition) ---')
    cv = component_var(weights, cov, 0.95)
    print(f'Components: {cv.round(2)}  -> sum: {cv.sum():.2f} (should equal VaR {var_param:.2f})')
    pcts = cv / cv.sum() * 100
    print(f'  Pct of Total Risk: {pcts.round(1)}')
    print()
    print('--- Diversification Metrics ---')
    dr = diversification_ratio(weights, vols, cov)
    enb = effective_n_bets(weights, cov)
    print(f'Diversification Ratio: {dr:.3f} (>1.5 ist gut)')
    print(f'Effective N Bets: {enb:.2f} (von 3 Assets)')
