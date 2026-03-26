"""
trademind/execution/gap_model.py — Overnight Gap Risk Model

Berechnet historische Overnight-Gaps aus 1-Jahres-Kursdaten (yfinance).
Gibt Risikobewertung inkl. VaR-95 und Empfehlung zurück.

Empfehlungs-Logik:
  gap_gt_3pct_frequency > 5%  → 'DANGEROUS'
  gap_gt_3pct_frequency > 2%  → 'CAUTION'
  else                        → 'OK'
"""
from __future__ import annotations

import numpy as np


def estimate_gap_risk(ticker: str, position_value: float) -> dict:
    """Berechnet Overnight-Gap-Risiko für einen Ticker.

    Nutzt yfinance (1 Jahr, Daily OHLCV) um Overnight-Gaps zu messen.
    Ein Gap = |Open(t) - Close(t-1)| / Close(t-1).

    Args:
        ticker:         Ticker-Symbol (z.B. 'OXY').
        position_value: Positionswert in EUR.

    Returns:
        {
            'ticker':                str,
            'avg_gap_pct':           float,   # Durchschnittl. Gap (%)
            'gap_gt_1pct_frequency': float,   # Anteil Tage mit >1% Gap (0–100)
            'gap_gt_3pct_frequency': float,   # Anteil Tage mit >3% Gap (0–100)
            'worst_gap_pct':         float,   # Schlimmster historischer Gap (%)
            'worst_gap_eur':         float,   # worst_gap * position_value
            'var_95_gap_eur':        float,   # 95th Percentile Gap in EUR
            'recommendation':        str,     # 'OK', 'CAUTION', 'DANGEROUS'
            'data_days':             int,     # Anzahl Handelstage analysiert
            'error':                 str|None # Fehlermeldung falls nötig
        }
    """
    try:
        import yfinance as yf
    except ImportError:
        return _error_result(ticker, position_value, "yfinance nicht installiert (pip install yfinance)")

    try:
        hist = yf.download(ticker, period="1y", interval="1d",
                           auto_adjust=True, progress=False)
    except Exception as e:
        return _error_result(ticker, position_value, f"yfinance Download fehlgeschlagen: {e}")

    if hist is None or len(hist) < 20:
        return _error_result(ticker, position_value,
                             f"Zu wenig Daten ({len(hist) if hist is not None else 0} Tage)")

    try:
        # Flatten MultiIndex columns if present
        if isinstance(hist.columns, type(hist.columns)) and hasattr(hist.columns, 'levels'):
            try:
                hist.columns = hist.columns.get_level_values(0)
            except Exception:
                pass

        closes = hist['Close'].values.flatten().astype(float)
        opens  = hist['Open'].values.flatten().astype(float)

        # Overnight gap: Open(t) vs Close(t-1)
        prev_closes = closes[:-1]
        curr_opens  = opens[1:]

        # Filtere NaN/Inf raus
        mask = (
            np.isfinite(prev_closes) & np.isfinite(curr_opens) &
            (prev_closes > 0) & (curr_opens > 0)
        )
        prev_closes = prev_closes[mask]
        curr_opens  = curr_opens[mask]

        if len(prev_closes) < 5:
            return _error_result(ticker, position_value, "Zu wenig valide Datenpunkte")

        # Gap = abs(Open - Close_prev) / Close_prev * 100
        gaps_pct = np.abs(curr_opens - prev_closes) / prev_closes * 100.0

        avg_gap_pct          = float(np.mean(gaps_pct))
        gap_gt_1pct_freq     = float(np.mean(gaps_pct > 1.0) * 100.0)
        gap_gt_3pct_freq     = float(np.mean(gaps_pct > 3.0) * 100.0)
        worst_gap_pct        = float(np.max(gaps_pct))
        var_95_gap_pct       = float(np.percentile(gaps_pct, 95))

        worst_gap_eur        = round(position_value * worst_gap_pct / 100.0, 2)
        var_95_gap_eur       = round(position_value * var_95_gap_pct / 100.0, 2)

        # Empfehlung
        if gap_gt_3pct_freq > 5.0:
            recommendation = 'DANGEROUS'
        elif gap_gt_3pct_freq > 2.0:
            recommendation = 'CAUTION'
        else:
            recommendation = 'OK'

        return {
            'ticker':                ticker,
            'avg_gap_pct':           round(avg_gap_pct, 3),
            'gap_gt_1pct_frequency': round(gap_gt_1pct_freq, 1),
            'gap_gt_3pct_frequency': round(gap_gt_3pct_freq, 1),
            'worst_gap_pct':         round(worst_gap_pct, 2),
            'worst_gap_eur':         worst_gap_eur,
            'var_95_gap_eur':        var_95_gap_eur,
            'recommendation':        recommendation,
            'data_days':             len(gaps_pct),
            'error':                 None,
        }

    except Exception as e:
        return _error_result(ticker, position_value, f"Berechnungsfehler: {e}")


def _error_result(ticker: str, position_value: float, msg: str) -> dict:
    """Gibt ein Fehler-Result mit sicheren Default-Werten zurück."""
    return {
        'ticker':                ticker,
        'avg_gap_pct':           0.0,
        'gap_gt_1pct_frequency': 0.0,
        'gap_gt_3pct_frequency': 0.0,
        'worst_gap_pct':         0.0,
        'worst_gap_eur':         0.0,
        'var_95_gap_eur':        0.0,
        'recommendation':        'UNKNOWN',
        'data_days':             0,
        'error':                 msg,
    }


def format_gap_report(gap: dict) -> str:
    """Gibt einen lesbaren Gap-Risk-Report zurück."""
    rec_icons = {'OK': '✅', 'CAUTION': '⚠️', 'DANGEROUS': '🚨', 'UNKNOWN': '❓'}
    icon = rec_icons.get(gap['recommendation'], '❓')

    lines = [
        f"\n🌙 OVERNIGHT GAP RISK: {gap['ticker']}",
        f"   Daten: {gap['data_days']} Handelstage (1 Jahr)",
    ]

    if gap['error']:
        lines.append(f"   ❌ Fehler: {gap['error']}")
        return '\n'.join(lines)

    lines += [
        f"",
        f"   Ø Gap:        {gap['avg_gap_pct']:.3f}%",
        f"   >1% Gap:      {gap['gap_gt_1pct_frequency']:.1f}% der Tage",
        f"   >3% Gap:      {gap['gap_gt_3pct_frequency']:.1f}% der Tage",
        f"   Schlimmster:  {gap['worst_gap_pct']:.2f}%  →  {gap['worst_gap_eur']:+.0f}€ auf Position",
        f"   VaR-95:       {gap['var_95_gap_eur']:+.0f}€ (95th Percentile)",
        f"",
        f"   {icon} Empfehlung: {gap['recommendation']}",
    ]
    return '\n'.join(lines)
