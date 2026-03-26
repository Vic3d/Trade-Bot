"""
trademind/analytics/significance.py — Statistische Signifikanz-Tests

3 Tests:
1. Binomial Test: Win Rate signifikant > 50%?
2. t-Test: Mean Return signifikant > 0?
3. Bootstrap CI: 10.000 Resamplings → 95% Confidence Interval

Minimum 10 Trades für aussagekräftige Tests.
Unter 10 Trades: verdict = 'ZU WENIG DATEN'
"""
import random


def test_strategy_significance(
    trades: list[dict],
    confidence: float = 0.95,
) -> dict:
    """
    Testet ob eine Strategie statistisch signifikant profitabel ist.
    
    Input: Liste von Trades mit pnl_eur und/oder pnl_pct
    confidence: Konfidenz-Niveau (default: 0.95 = 95%)
    
    Returns:
        {
            'binom_p': float,           # Binomial-Test p-value
            't_test_p': float,          # t-Test p-value
            'ci_95_lower': float,       # Bootstrap CI lower bound
            'ci_95_upper': float,       # Bootstrap CI upper bound
            'significant': bool,        # Beide Tests signifikant?
            'verdict': str,             # 'EDGE BESTÄTIGT' | 'KEIN EDGE (Zufall)' | 'ZU WENIG DATEN'
            'n_trades': int,
        }
    """
    MIN_TRADES = 10
    alpha = 1.0 - confidence  # 0.05 bei 95% confidence

    if not trades or len(trades) < MIN_TRADES:
        return {
            'binom_p': 1.0,
            't_test_p': 1.0,
            'ci_95_lower': 0.0,
            'ci_95_upper': 0.0,
            'significant': False,
            'verdict': 'ZU WENIG DATEN',
            'n_trades': len(trades) if trades else 0,
        }

    # Daten aufbereiten
    pnl_list = []
    for t in trades:
        pnl_p = t.get('pnl_pct') or 0.0
        if pnl_p != 0 and abs(pnl_p) < 0.5:
            pnl_p = pnl_p * 100
        pnl_list.append(float(pnl_p))

    n = len(pnl_list)
    wins = sum(1 for r in pnl_list if r > 0)

    # ── 1. Binomial Test (Win Rate > 50%) ─────────────────────────────────
    binom_p = _binomial_test_gt_half(wins, n)

    # ── 2. t-Test (Mean Return > 0) ───────────────────────────────────────
    t_stat, t_p = _one_sample_t_test(pnl_list, mu=0.0)

    # ── 3. Bootstrap Confidence Interval ─────────────────────────────────
    ci_lower, ci_upper = _bootstrap_ci(pnl_list, n_resamples=10000, ci=confidence)

    # ── Verdict ──────────────────────────────────────────────────────────
    significant = (binom_p < alpha) and (t_p < alpha)
    mean_return = sum(pnl_list) / n

    if significant and mean_return > 0:
        verdict = 'EDGE BESTÄTIGT'
    elif binom_p < alpha and mean_return < 0:
        verdict = 'KEIN EDGE (Signifikant NEGATIV — abschalten!)'
    else:
        verdict = 'KEIN EDGE (Zufall)'

    return {
        'binom_p':      round(binom_p, 4),
        't_test_p':     round(t_p, 4),
        'ci_95_lower':  round(ci_lower, 4),
        'ci_95_upper':  round(ci_upper, 4),
        'significant':  significant,
        'verdict':      verdict,
        'n_trades':     n,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hilfs-Funktionen (ohne scipy als Fallback, aber scipy bevorzugt)
# ─────────────────────────────────────────────────────────────────────────────

def _binomial_test_gt_half(k: int, n: int) -> float:
    """
    Einseitiger Binomial-Test: P(X >= k | n, p=0.5)
    Gibt p-value zurück. Kleiner = signifikanter.
    """
    try:
        from scipy.stats import binomtest
        result = binomtest(k, n, 0.5, alternative='greater')
        return float(result.pvalue)
    except ImportError:
        pass

    # Fallback: Normal-Approximation
    import math
    if n == 0:
        return 1.0
    p0 = 0.5
    expected = n * p0
    std = math.sqrt(n * p0 * (1 - p0))
    if std == 0:
        return 1.0 if k <= expected else 0.0
    z = (k - expected - 0.5) / std  # Kontinuitätskorrektur
    # P(Z >= z) einseitig
    return 1.0 - _normal_cdf(z)


def _one_sample_t_test(data: list[float], mu: float = 0.0) -> tuple[float, float]:
    """
    Einseitiger t-Test: Ist der Mittelwert signifikant > mu?
    Gibt (t_statistic, p_value) zurück.
    """
    try:
        from scipy.stats import ttest_1samp
        t_stat, p_two_sided = ttest_1samp(data, mu)
        # Einseitig (greater): p = p_two_sided / 2 wenn t > 0
        p_one_sided = p_two_sided / 2 if t_stat > 0 else 1.0 - p_two_sided / 2
        return float(t_stat), float(p_one_sided)
    except ImportError:
        pass

    # Fallback: Manuelle t-Stat
    import math
    n = len(data)
    if n < 2:
        return 0.0, 1.0
    mean = sum(data) / n
    var = sum((x - mean) ** 2 for x in data) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0, 1.0
    t = (mean - mu) / (std / math.sqrt(n))
    # Approximation p-value mit Normal (gültig für n > 30)
    p = 1.0 - _normal_cdf(t)
    return t, p


def _bootstrap_ci(
    data: list[float],
    n_resamples: int = 10000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """
    Bootstrap Confidence Interval für den Mittelwert.
    10.000 Resamplings mit Zurücklegen.
    """
    import math

    n = len(data)
    if n == 0:
        return 0.0, 0.0

    rng = random.Random(42)  # Reproduzierbar
    means = []
    for _ in range(n_resamples):
        sample = [rng.choice(data) for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    alpha = (1.0 - ci) / 2
    lower_idx = int(alpha * n_resamples)
    upper_idx = int((1 - alpha) * n_resamples)
    
    lower_idx = max(0, min(lower_idx, n_resamples - 1))
    upper_idx = max(0, min(upper_idx, n_resamples - 1))

    return means[lower_idx], means[upper_idx]


def _normal_cdf(x: float) -> float:
    """Standard Normal CDF (Approximation via math.erf)."""
    import math
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
