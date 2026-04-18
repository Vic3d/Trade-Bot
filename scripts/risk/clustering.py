"""Cluster Detection — Hierarchical + HRP (López de Prado).

Phase 21 Pro. Nutzt scipy fuer Linkage, fcluster.

Public API:
    correlation_distance(corr)            -> distance matrix
    hierarchical_cluster(corr, tickers)   -> cluster assignment dict
    find_dangerous_clusters(...)          -> list of risk clusters
    hrp_weights(corr, vols, tickers)      -> dict {ticker: weight}
"""
from __future__ import annotations

from typing import Optional

import numpy as np

try:
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


# ─── Distance ────────────────────────────────────────────────────────────────
def correlation_distance(corr_matrix: np.ndarray) -> np.ndarray:
    """d_ij = sqrt(0.5 * (1 - rho_ij))  — Lopez de Prado-Formel.

    Garantiert echte Distanz-Metrik (Dreiecksungleichung erfuellt).
    Range: [0, 1] — 0 = identisch, 1 = perfekt anti-korreliert.
    """
    # Clip fuer Numerik-Sicherheit
    c = np.clip(corr_matrix, -1.0, 1.0)
    d = np.sqrt(0.5 * (1.0 - c))
    np.fill_diagonal(d, 0.0)
    return d


# ─── Hierarchical Clustering ─────────────────────────────────────────────────
def hierarchical_cluster(
    corr_matrix: np.ndarray,
    tickers: list[str],
    linkage_method: str = 'ward',
    distance_threshold: float = 0.5,
) -> dict:
    """Hierarchical Clustering ueber Korrelations-Distanz.

    distance_threshold=0.5 entspricht ~ Korrelation 0.5
    (bei Lopez de Prado distance: d=0.5 -> rho=0.5).

    Args:
        corr_matrix: NxN correlation matrix
        tickers: column/row labels
        linkage_method: 'ward', 'average', 'complete'
        distance_threshold: cut-off fuer Cluster-Bildung

    Returns: {
        'cluster_assignment': {ticker: cluster_id},
        'n_clusters': int,
        'linkage_matrix': scipy linkage matrix,  (None falls scipy fehlt)
        'method': str,
    }
    """
    n = len(tickers)
    if n < 2:
        return {
            'cluster_assignment': {tickers[0]: 1} if n == 1 else {},
            'n_clusters': n,
            'linkage_matrix': None,
            'method': linkage_method,
        }

    if not SCIPY_AVAILABLE:
        # Fallback: jeder Ticker eigener Cluster
        return {
            'cluster_assignment': {t: i + 1 for i, t in enumerate(tickers)},
            'n_clusters': n,
            'linkage_matrix': None,
            'method': 'fallback_no_scipy',
        }

    dist = correlation_distance(corr_matrix)
    # scipy braucht condensed (1D) distance vector
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method=linkage_method)
    labels = fcluster(Z, t=distance_threshold, criterion='distance')

    assignment = {tickers[i]: int(labels[i]) for i in range(n)}
    return {
        'cluster_assignment': assignment,
        'n_clusters': int(labels.max()),
        'linkage_matrix': Z,
        'method': linkage_method,
    }


# ─── Dangerous Cluster Detection ─────────────────────────────────────────────
def find_dangerous_clusters(
    cluster_assignment: dict[str, int],
    open_positions: list[dict],
    corr_matrix: Optional[np.ndarray] = None,
    tickers: Optional[list[str]] = None,
    fund_total: float = 25000.0,
    min_cluster_size: int = 3,
    min_pct_exposure: float = 0.40,
) -> list[dict]:
    """Findet Cluster mit zuviel Risk-Konzentration.

    Triggers:
    - Cluster mit >= min_cluster_size offenen Positionen
    - ODER Cluster mit >= min_pct_exposure des Funds

    Args:
        cluster_assignment: {ticker: cluster_id} aus hierarchical_cluster
        open_positions: [{ticker, value_eur}, ...] mit aktuellen EUR-Werten
        corr_matrix, tickers: optional, fuer avg-corr-Berechnung im Cluster

    Returns: [
        {
            'cluster_id': int,
            'tickers': [str, ...],
            'n_positions': int,
            'total_exposure_eur': float,
            'pct_of_fund': float,
            'avg_corr': float | None,
            'reason': str,
        },
        ...
    ]
    """
    # Group by cluster
    clusters = {}
    for pos in open_positions:
        tk = pos['ticker'].upper()
        cid = cluster_assignment.get(tk)
        if cid is None:
            continue
        clusters.setdefault(cid, []).append(pos)

    dangerous = []
    for cid, positions in clusters.items():
        tickers_in_cluster = [p['ticker'].upper() for p in positions]
        total = sum(p.get('value_eur', 0.0) for p in positions)
        pct = total / fund_total if fund_total > 0 else 0.0
        n_pos = len(positions)

        triggers = []
        if n_pos >= min_cluster_size:
            triggers.append(f'{n_pos} Positionen >={min_cluster_size}')
        if pct >= min_pct_exposure:
            triggers.append(f'{pct*100:.0f}% Fund >={min_pct_exposure*100:.0f}%')

        if not triggers:
            continue

        # Avg-Korrelation im Cluster
        avg_corr = None
        if corr_matrix is not None and tickers is not None and n_pos >= 2:
            indices = [tickers.index(t) for t in tickers_in_cluster if t in tickers]
            if len(indices) >= 2:
                sub = corr_matrix[np.ix_(indices, indices)]
                mask = ~np.eye(len(indices), dtype=bool)
                avg_corr = float(sub[mask].mean())

        dangerous.append({
            'cluster_id': cid,
            'tickers': tickers_in_cluster,
            'n_positions': n_pos,
            'total_exposure_eur': float(total),
            'pct_of_fund': float(pct),
            'avg_corr': avg_corr,
            'reason': ' + '.join(triggers),
        })

    # Sortiere nach Exposure-Pct absteigend (gefaehrlichster zuerst)
    dangerous.sort(key=lambda c: c['pct_of_fund'], reverse=True)
    return dangerous


# ─── Hierarchical Risk Parity (Lopez de Prado 2016) ──────────────────────────
def _get_quasi_diag(linkage_matrix: np.ndarray) -> list[int]:
    """Sortiert Original-Indices entsprechend des Hierarchischen Trees.

    Korrelierte Assets landen nebeneinander -> diagonale Block-Struktur
    in der reorderten Korrelations-Matrix.
    """
    link = linkage_matrix.astype(int)
    n = link.shape[0] + 1  # original number of items
    sort_ix = [int(link[-1, 0]), int(link[-1, 1])]

    # Recursively expand cluster IDs >= n into their components
    while max(sort_ix) >= n:
        new = []
        for i in sort_ix:
            if i < n:
                new.append(i)
            else:
                # Cluster >= n: expand
                row = i - n
                new.append(int(link[row, 0]))
                new.append(int(link[row, 1]))
        sort_ix = new
    return sort_ix


def _get_cluster_var(cov: np.ndarray, items: list[int]) -> float:
    """Inverse-Variance Portfolio Variance fuer einen Cluster."""
    sub = cov[np.ix_(items, items)]
    inv_diag = 1.0 / np.diag(sub)
    w = inv_diag / inv_diag.sum()
    return float(w @ sub @ w)


def hrp_weights(
    corr_matrix: np.ndarray,
    vols: np.ndarray,
    tickers: list[str],
) -> dict[str, float]:
    """Hierarchical Risk Parity (Lopez de Prado 2016).

    Liefert Risk-Parity-Gewichte ohne Inverse-Cov zu rechnen
    (numerisch stabiler bei wenig Daten).

    Wird im Phase 21 NICHT als Sizing-Vorschlag genutzt — nur informativ
    im Dashboard zeigen.

    Returns: {ticker: weight}, summiert zu 1.0
    """
    n = len(tickers)
    if n == 0:
        return {}
    if n == 1:
        return {tickers[0]: 1.0}
    if not SCIPY_AVAILABLE:
        # Fallback: gleichgewichtet
        return {t: 1.0 / n for t in tickers}

    cov = corr_matrix * np.outer(vols, vols)

    # 1. Hierarchical Tree Clustering
    dist = correlation_distance(corr_matrix)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method='single')

    # 2. Quasi-Diagonalization
    sort_ix = _get_quasi_diag(link)

    # 3. Recursive Bisection
    weights = np.ones(n)
    clusters = [list(range(n))]
    # Re-map sort_ix to original ordering
    sorted_clusters = [[sort_ix[i] for i in range(n)]]

    while sorted_clusters:
        cluster = sorted_clusters.pop(0)
        if len(cluster) <= 1:
            continue
        # Split in 2 halves
        mid = len(cluster) // 2
        left = cluster[:mid]
        right = cluster[mid:]

        var_left = _get_cluster_var(cov, left)
        var_right = _get_cluster_var(cov, right)
        alpha = 1.0 - var_left / (var_left + var_right)

        # Skaliere die Gewichte der jeweiligen Cluster-Items
        for idx in left:
            weights[idx] *= alpha
        for idx in right:
            weights[idx] *= (1.0 - alpha)

        sorted_clusters.append(left)
        sorted_clusters.append(right)

    # Normalize
    weights = weights / weights.sum()
    return {tickers[i]: float(weights[i]) for i in range(n)}


# ─── Self-Test ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not SCIPY_AVAILABLE:
        print('scipy not available — limited test')

    np.random.seed(42)

    # 6 Assets mit 3-Cluster-Struktur
    # Cluster A (Energy): EQNR, BNO, USO  -> hoch korreliert
    # Cluster B (Tech):   NVDA, TSM        -> hoch korreliert
    # Cluster C (Single): GOLD             -> isoliert
    corr = np.array([
        [1.00, 0.85, 0.80, 0.10, 0.12, 0.05],
        [0.85, 1.00, 0.82, 0.08, 0.10, 0.04],
        [0.80, 0.82, 1.00, 0.05, 0.07, 0.02],
        [0.10, 0.08, 0.05, 1.00, 0.78, -0.05],
        [0.12, 0.10, 0.07, 0.78, 1.00, -0.03],
        [0.05, 0.04, 0.02, -0.05, -0.03, 1.00],
    ])
    tickers = ['EQNR', 'BNO', 'USO', 'NVDA', 'TSM', 'GOLD']

    print('=== Hierarchical Clustering ===')
    result = hierarchical_cluster(corr, tickers, linkage_method='ward', distance_threshold=0.5)
    print(f'Cluster assignment: {result["cluster_assignment"]}')
    print(f'N clusters: {result["n_clusters"]}')
    print()

    print('=== Dangerous Clusters ===')
    open_pos = [
        {'ticker': 'EQNR', 'value_eur': 1500},
        {'ticker': 'BNO', 'value_eur': 1500},
        {'ticker': 'USO', 'value_eur': 1500},
        {'ticker': 'NVDA', 'value_eur': 2000},
    ]
    danger = find_dangerous_clusters(
        result['cluster_assignment'], open_pos,
        corr_matrix=corr, tickers=tickers, fund_total=25000,
    )
    for d in danger:
        ac = f'{d["avg_corr"]:.2f}' if d["avg_corr"] is not None else 'n/a'
        print(f'  Cluster {d["cluster_id"]}: {d["tickers"]} '
              f'-> {d["total_exposure_eur"]:.0f} EUR ({d["pct_of_fund"]*100:.0f}%) '
              f'avg_corr={ac} | {d["reason"]}')
    print()

    print('=== HRP Weights ===')
    vols = np.array([0.02, 0.025, 0.022, 0.035, 0.038, 0.015])
    hrp = hrp_weights(corr, vols, tickers)
    for t, w in sorted(hrp.items(), key=lambda x: -x[1]):
        print(f'  {t}: {w*100:.1f}%')
    print(f'  Sum: {sum(hrp.values()):.4f}')
