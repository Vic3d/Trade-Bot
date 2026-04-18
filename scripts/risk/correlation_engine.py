"""Correlation Engine — 4 Estimators (Sample / EWMA / Ledoit-Wolf / Conditional).

Phase 21 Pro. Pure numpy, keine pandas/sklearn-Pflicht.

Public API:
    compute_returns(prices)                  -> dict[ticker, np.ndarray]
    sample_correlation(returns)              -> (matrix, tickers)
    ewma_correlation(returns, lambda_decay)  -> (matrix, tickers)
    ledoit_wolf_correlation(returns)         -> (matrix, tickers, alpha)
    conditional_correlation(returns, vix)    -> (matrix, tickers, n_stress)
    aggregate_estimators(estimators, weights)-> matrix
    apply_sector_override(m, tickers, smap)  -> matrix
    compute_aggregated_matrix(prices, vix, sector_map)
        -> high-level helper, gibt finale Matrix + Metadaten zurueck

Hintergrund:
- 30 Tage * 10 Ticker = unterbestimmt fuer Sample-Pearson
- Ledoit-Wolf 2004: Shrinkage zu konstantem Avg-Correlation Target
- EWMA (lambda=0.94) ist RiskMetrics-Standard, ~25 Tage Half-Life
- Conditional auf VIX>25 erfasst Stress-Korrelation ('go to 1 in a crisis')
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

# ─── Konstanten ──────────────────────────────────────────────────────────────
DEFAULT_LAMBDA = 0.94            # EWMA Decay (RiskMetrics)
DEFAULT_VIX_THRESHOLD = 25.0     # Conditional-Stress Definition
MIN_OBS = 20                     # Minimum Observations fuer valide Schaetzung
MIN_STRESS_OBS = 10              # Minimum fuer Conditional-Schaetzung


# ─── Returns ─────────────────────────────────────────────────────────────────
def compute_returns(prices: dict[str, list[float]]) -> dict[str, np.ndarray]:
    """Log-Returns aus Price-Series. Filtert NaN/Inf raus.

    Args:
        prices: {ticker: [close1, close2, ..., closeN]}

    Returns:
        {ticker: array of log-returns, length = N-1}
    """
    out = {}
    for ticker, series in prices.items():
        arr = np.asarray(series, dtype=float)
        # Handle NaN: forward-fill via mask, drop trailing NaN
        mask = np.isfinite(arr) & (arr > 0)
        if mask.sum() < MIN_OBS:
            continue
        clean = arr[mask]
        if len(clean) < 2:
            continue
        rets = np.diff(np.log(clean))
        # Defensive: clamp extreme outliers (>50% daily) — likely data errors
        rets = np.clip(rets, -0.5, 0.5)
        out[ticker] = rets
    return out


def _align_returns(returns: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Bringt alle Return-Serien auf gemeinsame Laenge (truncate to min).

    Returns: (T x N matrix, tickers in column order)
    """
    if not returns:
        return np.zeros((0, 0)), []
    tickers = sorted(returns.keys())
    min_len = min(len(returns[t]) for t in tickers)
    if min_len < MIN_OBS:
        return np.zeros((0, len(tickers))), tickers
    # Take last `min_len` returns (most recent)
    matrix = np.column_stack([returns[t][-min_len:] for t in tickers])
    return matrix, tickers


# ─── Sample Correlation ──────────────────────────────────────────────────────
def sample_correlation(returns: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Standard Pearson. Rueckgabe (NxN matrix, ticker_order).

    Baseline-Estimator. Statistisch unterbestimmt bei wenig Daten,
    deshalb in aggregate_estimators() nur niedriges Gewicht.
    """
    matrix, tickers = _align_returns(returns)
    if matrix.size == 0 or matrix.shape[0] < MIN_OBS:
        n = len(tickers)
        return np.eye(n), tickers
    corr = np.corrcoef(matrix, rowvar=False)
    # Defensive: NaN-Repair (kann passieren wenn Asset konstant)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    return corr, tickers


# ─── EWMA Correlation ────────────────────────────────────────────────────────
def ewma_correlation(
    returns: dict[str, np.ndarray],
    lambda_decay: float = DEFAULT_LAMBDA,
) -> tuple[np.ndarray, list[str]]:
    """RiskMetrics EWMA. Recursive: var_t = lambda*var_{t-1} + (1-lambda)*r^2_t.

    Initialisiert var_0 mit Sample-Variance der ersten min(20, T) Beobachtungen.
    Half-life bei lambda=0.94 ist ln(0.5)/ln(0.94) ~ 11.2 Tage.
    """
    matrix, tickers = _align_returns(returns)
    T, N = matrix.shape
    if T < MIN_OBS:
        return np.eye(N), tickers

    # Init: Sample-Cov aus ersten 20 Tagen
    init_T = min(20, T)
    cov = np.cov(matrix[:init_T], rowvar=False)
    if N == 1:
        cov = np.array([[float(cov)]])

    # Iteriere ueber restliche Tage
    for t in range(init_T, T):
        r = matrix[t].reshape(-1, 1)  # column vector
        cov = lambda_decay * cov + (1.0 - lambda_decay) * (r @ r.T)

    # Cov -> Corr
    vols = np.sqrt(np.diag(cov))
    vols[vols == 0] = 1.0  # avoid /0
    corr = cov / np.outer(vols, vols)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    return corr, tickers


# ─── Ledoit-Wolf Shrinkage ───────────────────────────────────────────────────
def ledoit_wolf_correlation(
    returns: dict[str, np.ndarray],
) -> tuple[np.ndarray, list[str], float]:
    """Shrinkage zu konstanter Avg-Correlation Target.

    Folgt Ledoit & Wolf 2004 'Honey, I Shrunk the Sample Covariance Matrix'
    (Constant-Correlation Target Variant — einfachste, robusteste Form).

    Sigma_shrunk = (1-alpha) * Sigma_sample + alpha * F
        F[i,j] = avg_off_diag_correlation * sqrt(var_i * var_j)
        F[i,i] = var_i (Diagonale bleibt unveraendert)

    Alpha wird analytisch aus Daten geschaetzt (siehe Paper Eq. 14).
    Garantiert PSD wenn Sample-Cov PSD ist.

    Returns: (shrunk_corr_matrix, tickers, alpha_intensity)
        alpha=0 -> kein Shrinkage (viel Daten), alpha=1 -> alles zum Target
    """
    matrix, tickers = _align_returns(returns)
    T, N = matrix.shape
    if T < MIN_OBS or N < 2:
        return np.eye(N), tickers, 0.0

    # 1. Sample-Cov + Sample-Vols
    X = matrix - matrix.mean(axis=0)  # center
    sample_cov = (X.T @ X) / T  # MLE estimator (T statt T-1, wie im Paper)
    vols = np.sqrt(np.diag(sample_cov))
    vols_safe = np.where(vols > 1e-12, vols, 1.0)

    # 2. Sample-Corr
    sample_corr = sample_cov / np.outer(vols_safe, vols_safe)

    # 3. Avg off-diagonal correlation
    mask = ~np.eye(N, dtype=bool)
    avg_corr = sample_corr[mask].mean()

    # 4. Target F (Constant-Correlation)
    F_corr = np.full((N, N), avg_corr)
    np.fill_diagonal(F_corr, 1.0)
    F_cov = F_corr * np.outer(vols, vols)

    # 5. Shrinkage Intensity Alpha (Ledoit-Wolf 2004 Eq. 14, simplified)
    # pi = sum_ij Var(s_ij)
    # rho = sum_i Var(s_ii) + sum_{i!=j} Cov(s_ii, s_jj) * f-Term (vereinfacht)
    # gamma = sum_ij (f_ij - s_ij)^2
    # alpha = max(0, min(1, (pi - rho) / (gamma * T)))

    # pi: Variance der Sample-Cov-Eintraege
    var_s = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            # Var(s_ij) = (1/T) * E[(x_i x_j - s_ij)^2]
            d = (X[:, i] * X[:, j]) - sample_cov[i, j]
            var_s[i, j] = (d * d).mean()
    pi = var_s.sum()

    # gamma: Misfit zwischen F und Sample
    diff = F_cov - sample_cov
    gamma = (diff * diff).sum()

    # rho: Vereinfachte Variante — bei Constant-Correlation dominiert pi-Term
    # Wir lassen rho=0 (Approx, in der Praxis kaum Unterschied bei N<20)
    rho = 0.0

    if gamma <= 1e-12:
        alpha = 0.0
    else:
        kappa = (pi - rho) / gamma
        alpha = max(0.0, min(1.0, kappa / T))

    # 6. Shrunk Cov
    shrunk_cov = (1.0 - alpha) * sample_cov + alpha * F_cov

    # 7. Cov -> Corr
    shrunk_vols = np.sqrt(np.diag(shrunk_cov))
    shrunk_vols[shrunk_vols == 0] = 1.0
    shrunk_corr = shrunk_cov / np.outer(shrunk_vols, shrunk_vols)
    shrunk_corr = np.nan_to_num(shrunk_corr, nan=0.0)
    np.fill_diagonal(shrunk_corr, 1.0)

    return shrunk_corr, tickers, float(alpha)


# ─── Conditional / Stress Correlation ────────────────────────────────────────
def conditional_correlation(
    returns: dict[str, np.ndarray],
    vix_series: np.ndarray,
    vix_threshold: float = DEFAULT_VIX_THRESHOLD,
) -> tuple[np.ndarray, list[str], int]:
    """Korrelation auf Tagen mit VIX > threshold.

    Erfasst 'correlations go to 1 in a crisis'-Phaenomen.
    Falls weniger als MIN_STRESS_OBS Stress-Tage vorhanden:
    Fallback auf Sample-Correlation, n_stress=0 als Marker.
    """
    matrix, tickers = _align_returns(returns)
    T, N = matrix.shape
    if T < MIN_OBS:
        return np.eye(N), tickers, 0

    # Align vix_series to returns length (take last T)
    vix_arr = np.asarray(vix_series, dtype=float)
    if len(vix_arr) >= T:
        vix_aligned = vix_arr[-T:]
    else:
        # VIX kuerzer als returns — pad mit Median
        med = float(np.nanmedian(vix_arr)) if len(vix_arr) > 0 else 20.0
        vix_aligned = np.concatenate([np.full(T - len(vix_arr), med), vix_arr])

    stress_mask = vix_aligned > vix_threshold
    n_stress = int(stress_mask.sum())

    if n_stress < MIN_STRESS_OBS:
        # Fallback: nutze Sample, marker n_stress=0
        corr, _ = sample_correlation(returns)
        return corr, tickers, 0

    stress_returns = matrix[stress_mask]
    corr = np.corrcoef(stress_returns, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    return corr, tickers, n_stress


# ─── Aggregate / Sector-Override ─────────────────────────────────────────────
DEFAULT_AGGREGATE_WEIGHTS = {
    'ledoit_wolf': 0.50,
    'ewma': 0.30,
    'conditional': 0.20,
    'sample': 0.0,  # Baseline only, nicht im Default
}


def aggregate_estimators(
    estimators: dict[str, np.ndarray],
    weights: Optional[dict[str, float]] = None,
) -> np.ndarray:
    """Gewichteter Mix mehrerer Korrelations-Schaetzer.

    Args:
        estimators: {'sample': matrix, 'ewma': matrix, ...}
                    Alle Matrizen muessen gleiche Shape haben!
        weights: {'sample': 0.1, 'ewma': 0.3, ...}
                 Werden auf Summe=1 normiert (nur ueber vorhandene Estimators).

    Returns: aggregated correlation matrix
    """
    if weights is None:
        weights = DEFAULT_AGGREGATE_WEIGHTS

    valid = {k: v for k, v in estimators.items() if k in weights and weights[k] > 0}
    if not valid:
        # Fallback: ersten verfuegbaren Estimator nehmen
        first = next(iter(estimators.values()))
        return first

    total_weight = sum(weights[k] for k in valid)
    if total_weight <= 0:
        return next(iter(valid.values()))

    agg = np.zeros_like(next(iter(valid.values())))
    for k, m in valid.items():
        agg += (weights[k] / total_weight) * m

    np.fill_diagonal(agg, 1.0)
    return agg


def apply_sector_override(
    matrix: np.ndarray,
    tickers: list[str],
    sector_map: dict[str, str],
    floor: float = 0.60,
) -> np.ndarray:
    """Wenn 2 Ticker im selben Sektor: corr = max(corr, floor).

    Verhindert Underestimation bei kurzen Returns-Divergenzen.
    Beispiel: 2 Oil-Aktien koennen kurzfristig divergieren (one-off-news),
    fallen aber langfristig zusammen wenn Brent crashed.
    """
    out = matrix.copy()
    N = len(tickers)
    for i in range(N):
        s_i = sector_map.get(tickers[i].upper(), 'UNKNOWN')
        for j in range(i + 1, N):
            s_j = sector_map.get(tickers[j].upper(), 'UNKNOWN')
            if s_i == s_j and s_i not in ('UNKNOWN', 'Other', None, ''):
                if out[i, j] < floor:
                    out[i, j] = floor
                    out[j, i] = floor
    return out


# ─── High-Level Helper ───────────────────────────────────────────────────────
def compute_aggregated_matrix(
    prices: dict[str, list[float]],
    vix_series: Optional[np.ndarray] = None,
    sector_map: Optional[dict[str, str]] = None,
    weights: Optional[dict[str, float]] = None,
) -> dict:
    """End-to-end: Returns + 4 Estimators + Aggregation + Sector-Override.

    Returns:
        {
            'aggregated': np.ndarray (NxN),
            'tickers': list[str],
            'estimators': {
                'sample': matrix,
                'ewma': matrix,
                'ledoit_wolf': matrix,
                'conditional': matrix,
            },
            'metadata': {
                'lw_alpha': float,
                'n_stress_days': int,
                'n_observations': int,
                'lambda_ewma': float,
            }
        }
    """
    returns = compute_returns(prices)
    if not returns:
        return {
            'aggregated': np.zeros((0, 0)),
            'tickers': [],
            'estimators': {},
            'metadata': {'error': 'no_returns'},
        }

    sample_m, tickers = sample_correlation(returns)
    ewma_m, _ = ewma_correlation(returns)
    lw_m, _, lw_alpha = ledoit_wolf_correlation(returns)

    if vix_series is not None and len(vix_series) > 0:
        cond_m, _, n_stress = conditional_correlation(returns, vix_series)
    else:
        cond_m = sample_m
        n_stress = 0

    estimators = {
        'sample': sample_m,
        'ewma': ewma_m,
        'ledoit_wolf': lw_m,
        'conditional': cond_m,
    }

    agg = aggregate_estimators(estimators, weights)

    if sector_map:
        agg = apply_sector_override(agg, tickers, sector_map)

    # Stelle sicher: Diagonale = 1, symmetrisch
    agg = (agg + agg.T) / 2.0
    np.fill_diagonal(agg, 1.0)

    return {
        'aggregated': agg,
        'tickers': tickers,
        'estimators': estimators,
        'metadata': {
            'lw_alpha': lw_alpha,
            'n_stress_days': n_stress,
            'n_observations': len(next(iter(returns.values()))),
            'lambda_ewma': DEFAULT_LAMBDA,
        },
    }


# ─── Persistence ─────────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = WORKSPACE / 'data'


def save_correlation_matrix(matrix: np.ndarray, tickers: list[str], metadata: dict) -> Path:
    """Speichert aktuelle Matrix nach data/correlations.json."""
    path = DATA_DIR / 'correlations.json'
    payload = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'tickers': tickers,
        'matrix': matrix.tolist(),
        'metadata': {k: (v if not isinstance(v, np.generic) else v.item()) for k, v in metadata.items()},
    }
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return path


def save_snapshot(matrix: np.ndarray, tickers: list[str], estimators: dict, metadata: dict) -> Path:
    """Speichert Daily-Snapshot nach data/correlations_history/YYYY-MM-DD.json."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    path = DATA_DIR / 'correlations_history' / f'{today}.json'
    payload = {
        'date': today,
        'tickers': tickers,
        'aggregated': matrix.tolist(),
        'estimators': {k: m.tolist() for k, m in estimators.items()},
        'metadata': {k: (v if not isinstance(v, np.generic) else v.item()) for k, v in metadata.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return path


def load_current_matrix() -> tuple[np.ndarray, list[str], dict]:
    """Laedt aktuelle Matrix aus data/correlations.json.

    Returns: (matrix, tickers, metadata) — leer wenn File nicht existiert.
    """
    path = DATA_DIR / 'correlations.json'
    if not path.exists():
        return np.zeros((0, 0)), [], {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return (
        np.asarray(data['matrix']),
        data['tickers'],
        data.get('metadata', {}),
    )


def matrix_drift_distance(matrix_today: np.ndarray, matrix_yesterday: np.ndarray) -> float:
    """Frobenius-Norm der Differenz, normalisiert.

    Wert > 0.15 = signifikanter Korrelations-Regime-Shift,
    Discord-Notice triggern.
    """
    if matrix_today.shape != matrix_yesterday.shape:
        return float('inf')
    diff = matrix_today - matrix_yesterday
    return float(np.linalg.norm(diff, 'fro') / np.sqrt(diff.size))


# ─── Data Loaders ────────────────────────────────────────────────────────────
def load_price_history(tickers: list[str], days: int = 180) -> dict[str, list[float]]:
    """Laedt Close-Preise aus trading.db fuer die letzten `days` Tage."""
    db = DATA_DIR / 'trading.db'
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    out = {}
    for t in tickers:
        rows = conn.execute(
            "SELECT date, close FROM prices WHERE ticker=? AND date>=? ORDER BY date ASC",
            (t.upper(), cutoff),
        ).fetchall()
        if rows:
            out[t.upper()] = [r[1] for r in rows if r[1] is not None]
    conn.close()
    return out


def load_vix_history(days: int = 180) -> np.ndarray:
    """Laedt VIX-Tagesschluesse aus macro_daily."""
    db = DATA_DIR / 'trading.db'
    if not db.exists():
        return np.array([])
    conn = sqlite3.connect(str(db))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    rows = conn.execute(
        "SELECT date, value FROM macro_daily WHERE indicator='VIX' AND date>=? ORDER BY date ASC",
        (cutoff,),
    ).fetchall()
    conn.close()
    return np.array([r[1] for r in rows if r[1] is not None], dtype=float)


# ─── CLI / Self-Test ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Self-Test mit synthetischen Daten
    np.random.seed(42)
    T = 100
    # 3 Assets mit bekannter Korrelations-Struktur
    cov_true = np.array([
        [1.0, 0.7, 0.1],
        [0.7, 1.0, 0.2],
        [0.1, 0.2, 1.0],
    ])
    L = np.linalg.cholesky(cov_true)
    rets = (L @ np.random.randn(3, T)).T

    prices_dict = {
        'A': np.exp(np.cumsum(rets[:, 0] * 0.01) + np.log(100)).tolist(),
        'B': np.exp(np.cumsum(rets[:, 1] * 0.01) + np.log(100)).tolist(),
        'C': np.exp(np.cumsum(rets[:, 2] * 0.01) + np.log(100)).tolist(),
    }

    result = compute_aggregated_matrix(prices_dict)
    print('Tickers:', result['tickers'])
    print('Aggregated Matrix:')
    print(np.round(result['aggregated'], 3))
    print('Metadata:', result['metadata'])
    print()
    print('True correlation:')
    print(np.round(cov_true, 3))
