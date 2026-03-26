"""
trademind/risk/correlation.py — Pairwise Korrelationsanalyse

Berechnet 60-Tage Rolling Korrelation zwischen einem neuen Ticker
und allen aktuell offenen Positionen, um Klumpenrisiken zu erkennen.

Cache: 24h in data/correlation_cache.json
"""
import json
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

from trademind.core.config import DATA_DIR

CACHE_FILE = DATA_DIR / "correlation_cache.json"
CACHE_TTL_HOURS = 24

THRESHOLD_HALF = 0.70   # > 0.70  → half_size empfehlen
THRESHOLD_REJECT = 0.85  # > 0.85 → reject empfehlen


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _cache_key(ticker_a: str, ticker_b: str) -> str:
    """Reihenfolge-unabhängiger Cache-Key."""
    return f"{min(ticker_a, ticker_b)}:{max(ticker_a, ticker_b)}"


def _get_cached(ticker_a: str, ticker_b: str) -> float | None:
    cache = _load_cache()
    key = _cache_key(ticker_a, ticker_b)
    if key not in cache:
        return None
    entry = cache[key]
    age_hours = (time.time() - entry.get("ts", 0)) / 3600
    if age_hours > CACHE_TTL_HOURS:
        return None
    return entry.get("corr")


def _set_cached(ticker_a: str, ticker_b: str, corr: float):
    cache = _load_cache()
    key = _cache_key(ticker_a, ticker_b)
    cache[key] = {"corr": corr, "ts": time.time()}
    _save_cache(cache)


# ── Korrelationsberechnung ───────────────────────────────────────────────────

def _fetch_returns(ticker: str, lookback_days: int) -> "pd.Series | None":
    """Lädt Yahoo Finance History und berechnet Daily Returns."""
    try:
        import yfinance as yf
        import pandas as pd
        end = datetime.now()
        # Extra-Buffer wegen Wochenenden
        start = end - timedelta(days=lookback_days + 20)
        data = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if data is None or len(data) < 10:
            return None
        closes = data["Close"]
        if hasattr(closes, "iloc"):
            if closes.ndim > 1:
                closes = closes.iloc[:, 0]
        returns = closes.pct_change().dropna()
        return returns.tail(lookback_days)
    except Exception as e:
        return None


def _calc_correlation(ticker_a: str, ticker_b: str, lookback_days: int) -> float | None:
    """Berechnet Pearson-Korrelation zwischen zwei Tickern."""
    # Check Cache
    cached = _get_cached(ticker_a, ticker_b)
    if cached is not None:
        return cached

    ret_a = _fetch_returns(ticker_a, lookback_days)
    ret_b = _fetch_returns(ticker_b, lookback_days)

    if ret_a is None or ret_b is None:
        return None

    # Align by index
    import pandas as pd
    aligned = pd.concat([ret_a.rename("a"), ret_b.rename("b")], axis=1).dropna()
    if len(aligned) < 10:
        return None

    corr = float(aligned["a"].corr(aligned["b"]))
    _set_cached(ticker_a, ticker_b, corr)
    return corr


# ── Public API ────────────────────────────────────────────────────────────────

def check_correlation(
    new_ticker: str,
    open_positions: list[str],
    threshold: float = THRESHOLD_HALF,
    lookback_days: int = 60,
) -> dict:
    """
    Berechnet 60-Tage Korrelation zwischen new_ticker und allen offenen Positionen.

    Args:
        new_ticker:     Ticker der neuen Position (z.B. 'OXY')
        open_positions: Liste der offenen Ticker (z.B. ['FRO', 'EQNR.OL'])
        threshold:      Ab wann half_size empfohlen wird (default 0.70)
        lookback_days:  Anzahl Handelstage (default 60)

    Returns:
        {
            'approved': bool,
            'reason': str,
            'correlations': [(ticker, correlation_value), ...],
            'suggested_action': 'full_size' | 'half_size' | 'reject',
            'max_correlation': float,
            'correlated_with': str or None,
        }
    """
    if not open_positions:
        return {
            "approved": True,
            "reason": "Keine offenen Positionen — kein Korrelationsrisiko",
            "correlations": [],
            "suggested_action": "full_size",
            "max_correlation": 0.0,
            "correlated_with": None,
        }

    # Filter: neuer Ticker nicht gegen sich selbst prüfen
    others = [t for t in open_positions if t.upper() != new_ticker.upper()]

    correlations = []
    failed = []

    for pos_ticker in others:
        corr = _calc_correlation(new_ticker, pos_ticker, lookback_days)
        if corr is not None:
            correlations.append((pos_ticker, round(corr, 4)))
        else:
            failed.append(pos_ticker)

    if not correlations:
        reason = "Keine Korrelationsdaten verfügbar"
        if failed:
            reason += f" (Fehler bei: {', '.join(failed)})"
        return {
            "approved": True,
            "reason": reason,
            "correlations": [],
            "suggested_action": "full_size",
            "max_correlation": 0.0,
            "correlated_with": None,
        }

    # Sortiere absteigend nach Absolutkorrelation
    correlations.sort(key=lambda x: abs(x[1]), reverse=True)

    max_corr_ticker, max_corr = correlations[0]
    abs_max = abs(max_corr)

    # Entscheidungslogik
    if abs_max >= THRESHOLD_REJECT:
        action = "reject"
        approved = False
        reason = (
            f"{new_ticker} hat Korrelation {max_corr:+.2f} mit {max_corr_ticker} "
            f"(>{THRESHOLD_REJECT:.0%} → Ablehnung). "
            f"Wäre effektiv eine Verdopplung der {max_corr_ticker}-Position."
        )
    elif abs_max >= THRESHOLD_HALF:
        action = "half_size"
        approved = True
        reason = (
            f"{new_ticker} hat Korrelation {max_corr:+.2f} mit {max_corr_ticker} "
            f"(>{THRESHOLD_HALF:.0%}). Halbe Position empfohlen."
        )
    else:
        action = "full_size"
        approved = True
        reason = (
            f"Max. Korrelation {max_corr:+.2f} mit {max_corr_ticker} — "
            f"unter Schwelle ({THRESHOLD_HALF:.0%}). Volle Position OK."
        )

    return {
        "approved": approved,
        "reason": reason,
        "correlations": correlations,
        "suggested_action": action,
        "max_correlation": max_corr,
        "correlated_with": max_corr_ticker if abs_max >= THRESHOLD_HALF else None,
    }
