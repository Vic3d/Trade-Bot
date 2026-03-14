#!/usr/bin/env python3
"""
Position Sizer — ATR-basiertes Position Sizing.

Methoden:
  1. ATR-basiert (Dirk 7H Methode): Risiko pro Trade / ATR = Anzahl Einheiten
  2. Prozentsatz-Risiko: X% des Portfolios riskieren pro Trade
  3. Kelly Criterion (wenn Win-Rate-Daten vorhanden)

Usage:
  from position_sizer import calc_position

  result = calc_position(
      ticker="NVDA",
      entry_eur=160.0,
      stop_eur=153.0,
      portfolio_eur=10000.0,   # Gesamtportfolio in EUR
      risk_pct=1.0,            # Max 1% Risiko pro Trade
      atr_eur=3.22,            # Optional: ATR für ATR-Methode
  )
"""

import sqlite3, os, json

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")

# Risiko-Regeln
DEFAULT_RISK_PCT    = 1.0   # 1% des Portfolios pro Trade
MAX_RISK_PCT        = 2.0   # Niemals mehr als 2% riskieren
MAX_POSITION_PCT    = 15.0  # Niemals mehr als 15% des Portfolios in einer Position
MAX_SECTOR_PCT      = 35.0  # Niemals mehr als 35% in einem Sektor

STRATEGY_SECTORS = {
    1: "Energie",       # S1 Iran/Öl
    2: "Rüstung",       # S2
    3: "Tech/KI",       # S3
    4: "Rohstoffe",     # S4
    5: "Rohstoffe",     # S5
    6: "Energie",       # S6 Solar
    7: "Gesundheit",    # S7 Biotech
}


def calc_position(
    ticker: str,
    entry_eur: float,
    stop_eur: float,
    portfolio_eur: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    atr_eur: float = None,
    conviction_score: float = 0.0,
    method: str = "atr",          # "atr" | "fixed_pct" | "kelly"
) -> dict:
    """
    Berechnet optimale Positionsgröße.

    Args:
        ticker:          Ticker-Symbol
        entry_eur:       Einstiegspreis in EUR
        stop_eur:        Stop-Loss in EUR
        portfolio_eur:   Gesamtportfoliowert in EUR
        risk_pct:        Max. Risiko als % des Portfolios (Standard: 1%)
        atr_eur:         ATR in EUR (für ATR-Methode)
        conviction_score: Gewichteter Score aus multi_strategy_analyzer (-7 bis +7)
        method:          Berechnungsmethode

    Returns:
        dict mit Positionsgröße, Risikoberechnung, Warnungen
    """

    if entry_eur <= 0 or stop_eur <= 0 or portfolio_eur <= 0:
        return {"error": "Ungültige Eingaben"}

    risk_per_unit = abs(entry_eur - stop_eur)
    if risk_per_unit <= 0:
        return {"error": "Entry = Stop — keine sinnvolle Position"}

    # Conviction-Adjustment: höherer Score = mehr riskieren (bis max)
    # Score +5 = 100% des Basis-Risikos, +7 = 150%, negativ = 50%
    conviction_multiplier = max(0.5, min(1.5, 1.0 + conviction_score / 10))
    adjusted_risk_pct = min(risk_pct * conviction_multiplier, MAX_RISK_PCT)

    max_risk_eur = portfolio_eur * (adjusted_risk_pct / 100)

    if method == "atr" and atr_eur:
        # ATR-Methode: Stop = 2×ATR, Positionsgröße so dass 2×ATR = max_risk_eur
        units_by_atr  = max_risk_eur / (2 * atr_eur)
        units_by_stop = max_risk_eur / risk_per_unit
        units = min(units_by_atr, units_by_stop)  # konservativere Schätzung
    else:
        # Prozent-Methode
        units = max_risk_eur / risk_per_unit

    position_eur = units * entry_eur
    position_pct = position_eur / portfolio_eur * 100

    # Sicherheits-Caps
    warnings = []
    if position_pct > MAX_POSITION_PCT:
        capped_units = (portfolio_eur * MAX_POSITION_PCT / 100) / entry_eur
        warnings.append(f"Position auf {MAX_POSITION_PCT}% des Portfolios gekappt ({units:.1f}→{capped_units:.1f} Einheiten)")
        units = capped_units
        position_eur = units * entry_eur
        position_pct = MAX_POSITION_PCT

    actual_risk_eur = units * risk_per_unit
    actual_risk_pct = actual_risk_eur / portfolio_eur * 100

    # CRV prüfen (brauchen Ziel für vollständiges CRV)
    result = {
        "ticker":               ticker,
        "entry_eur":            entry_eur,
        "stop_eur":             stop_eur,
        "risk_per_unit_eur":    round(risk_per_unit, 2),
        "units":                round(units, 4),
        "position_eur":         round(position_eur, 2),
        "position_pct":         round(position_pct, 1),
        "actual_risk_eur":      round(actual_risk_eur, 2),
        "actual_risk_pct":      round(actual_risk_pct, 2),
        "conviction_mult":      round(conviction_multiplier, 2),
        "method":               method,
        "warnings":             warnings,
    }

    return result


def get_portfolio_exposure(portfolio_eur: float) -> dict:
    """Holt aktuelle Sektor-Exposition aus der DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT ticker, strategy_id, entry_price
            FROM trades WHERE outcome='open' AND entry_price IS NOT NULL
        """).fetchall()
        conn.close()
    except:
        return {}

    sectors = {}
    for ticker, s_id, entry in rows:
        sector = STRATEGY_SECTORS.get(s_id, "Sonstige")
        sectors[sector] = sectors.get(sector, 0) + entry

    total = sum(sectors.values())
    return {s: {"eur": round(v, 2), "pct": round(v/portfolio_eur*100, 1)}
            for s, v in sectors.items()}


def format_sizing(result: dict) -> str:
    """Formatiert Sizing-Empfehlung für Discord."""
    if "error" in result:
        return f"❌ Position Sizing Fehler: {result['error']}"

    lines = [
        f"**Position Sizing — {result['ticker']}**",
        f"Entry: {result['entry_eur']}€ | Stop: {result['stop_eur']}€ | Risiko/Einheit: {result['risk_per_unit_eur']}€",
        f"→ **{result['units']:.1f} Einheiten** = {result['position_eur']:.2f}€ ({result['position_pct']:.1f}% Portfolio)",
        f"→ Risiko: {result['actual_risk_eur']:.2f}€ ({result['actual_risk_pct']:.2f}%)",
        f"→ Conviction-Faktor: ×{result['conviction_mult']} (Score-basiert)",
    ]
    if result.get("warnings"):
        for w in result["warnings"]:
            lines.append(f"⚠️ {w}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Beispiel: NVDA
    r = calc_position(
        ticker="NVDA",
        entry_eur=160.0,
        stop_eur=153.0,
        portfolio_eur=5000.0,
        risk_pct=1.0,
        atr_eur=3.22,
        conviction_score=-1.0,
        method="atr"
    )
    print(format_sizing(r))
    print()

    # Beispiel: EQNR
    r2 = calc_position(
        ticker="EQNR",
        entry_eur=27.04,
        stop_eur=27.0,
        portfolio_eur=5000.0,
        risk_pct=1.0,
        atr_eur=0.63,
        conviction_score=2.0,
    )
    print(format_sizing(r2))
