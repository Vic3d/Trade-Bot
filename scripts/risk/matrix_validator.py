"""Matrix Validator — PSD-Check + Repair.

Korrelations-Matrizen muessen positiv-semidefinit (PSD) sein, sonst sind
VaR-Berechnungen Muell (negative Varianzen moeglich).

Public API:
    is_psd(matrix)              -> bool
    nearest_psd(matrix)         -> matrix (Higham 2002)
    spectral_filter(matrix, k)  -> matrix (Random-Matrix-Theorie, optional)
    cov_to_corr(cov)            -> corr matrix
    corr_to_cov(corr, vols)     -> cov matrix
"""
from __future__ import annotations

import numpy as np


def is_psd(matrix: np.ndarray, tol: float = 1e-8) -> bool:
    """Eigenwert-Check. Matrix ist PSD wenn alle Eigenwerte >= -tol."""
    if matrix.size == 0:
        return True
    if not np.allclose(matrix, matrix.T, atol=1e-6):
        return False
    eigvals = np.linalg.eigvalsh(matrix)
    return bool(np.all(eigvals >= -tol))


def nearest_psd(matrix: np.ndarray, max_iter: int = 100) -> np.ndarray:
    """Higham 2002 — Nearest Symmetric PSD Matrix.

    Iterativ: Symmetrisieren -> Eigenvalue-Clipping -> Diagonale = 1 erzwingen.
    Konvergenz nach typisch 5-20 Iterationen.

    Falls Matrix bereits PSD: gibt sie unveraendert zurueck.
    """
    if is_psd(matrix):
        return matrix

    n = matrix.shape[0]
    Y = (matrix + matrix.T) / 2.0  # symmetrize

    for _ in range(max_iter):
        # Eigen-Decomposition + Clip negative Eigenwerte auf 0
        eigvals, eigvecs = np.linalg.eigh(Y)
        eigvals_clipped = np.maximum(eigvals, 0)
        Y_psd = eigvecs @ np.diag(eigvals_clipped) @ eigvecs.T
        Y_psd = (Y_psd + Y_psd.T) / 2.0  # re-symmetrize

        # Diagonale auf 1 setzen (Korrelations-Constraint)
        np.fill_diagonal(Y_psd, 1.0)

        if is_psd(Y_psd):
            return Y_psd
        Y = Y_psd

    # Fallback: minimum jitter auf Diagonale
    eigvals, eigvecs = np.linalg.eigh(Y)
    eigvals = np.maximum(eigvals, 1e-6)
    result = eigvecs @ np.diag(eigvals) @ eigvecs.T
    np.fill_diagonal(result, 1.0)
    return (result + result.T) / 2.0


def spectral_filter(matrix: np.ndarray, n_top_factors: int = 3) -> np.ndarray:
    """Marcenko-Pastur spectral cleaning.

    Random-Matrix-Theorie: Eigenwerte unter MP-Threshold sind Noise.
    Wir behalten die top-k Eigenwerte und mitteln den Rest.

    Optional fuer Phase 21c (Elite). Default-Engine nutzt das NICHT.
    """
    if matrix.size == 0:
        return matrix
    n = matrix.shape[0]
    if n_top_factors >= n:
        return matrix

    eigvals, eigvecs = np.linalg.eigh(matrix)
    # eigvals sind aufsteigend sortiert -> top-k am Ende
    bottom_avg = float(eigvals[:-n_top_factors].mean())
    eigvals_clean = eigvals.copy()
    eigvals_clean[:-n_top_factors] = bottom_avg

    cleaned = eigvecs @ np.diag(eigvals_clean) @ eigvecs.T
    np.fill_diagonal(cleaned, 1.0)
    return (cleaned + cleaned.T) / 2.0


def cov_to_corr(cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Kovarianz -> Korrelation. Returns (corr, vols)."""
    if cov.size == 0:
        return cov, np.array([])
    vols = np.sqrt(np.diag(cov))
    vols_safe = np.where(vols > 1e-12, vols, 1.0)
    corr = cov / np.outer(vols_safe, vols_safe)
    np.fill_diagonal(corr, 1.0)
    return corr, vols


def corr_to_cov(corr: np.ndarray, vols: np.ndarray) -> np.ndarray:
    """Korrelation + Volatilitaeten -> Kovarianz."""
    if corr.size == 0:
        return corr
    return corr * np.outer(vols, vols)


# ─── Self-Test ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Konstruiere absichtlich kaputte Matrix (nicht PSD)
    bad = np.array([
        [1.0, 0.9, 0.9],
        [0.9, 1.0, -0.9],  # widerspruechlich
        [0.9, -0.9, 1.0],
    ])
    print('Original PSD?', is_psd(bad))
    print('Eigenvalues:', np.linalg.eigvalsh(bad))

    fixed = nearest_psd(bad)
    print('\nRepaired matrix:')
    print(np.round(fixed, 3))
    print('Repaired PSD?', is_psd(fixed))
    print('Eigenvalues:', np.linalg.eigvalsh(fixed))

    # Test cov<->corr
    cov = np.array([[4.0, 1.0], [1.0, 9.0]])
    corr, vols = cov_to_corr(cov)
    print('\nCov:', cov)
    print('Corr:', corr)
    print('Vols:', vols)
    print('Roundtrip:', corr_to_cov(corr, vols))
