"""
trademind/risk/portfolio.py — Portfolio Exposure & Limits

Analysiert Sektor-, Regions- und Ticker-Konzentration des Portfolios.

Limits:
    Sektor:     Max 40% des Portfolios
    Region:     Max 60% des Portfolios
    Einzelticker: Max 20% des Portfolios
"""

from trademind.core.db import get_db

# ── Mapping ───────────────────────────────────────────────────────────────────

SECTOR_MAP: dict[str, str] = {
    "OXY": "Energy",
    "FRO": "Energy",
    "EQNR": "Energy",
    "EQNR.OL": "Energy",
    "DHT": "Energy",
    "TTE": "Energy",
    "TTE.PA": "Energy",
    "SHEL": "Energy",
    "SHEL.L": "Energy",
    "PSX": "Energy",
    "DINO": "Energy",
    "NVDA": "Technology",
    "MSFT": "Technology",
    "PLTR": "Technology",
    "AG": "Mining",
    "PAAS": "Mining",
    "WPM": "Mining",
    "HL": "Mining",
    "EXK": "Mining",
    "RIO": "Mining",
    "RIO.L": "Mining",
    "BHP": "Mining",
    "BHP.L": "Mining",
    "DR0.DE": "Mining",
    "S.TO": "Mining",
    "BAYN.DE": "Healthcare",
    "RHM.DE": "Defense",
    "CCL": "Consumer",
    "9988.HK": "Technology",
    "0700.HK": "Technology",
    "BABA": "Technology",
    "KWEB": "Technology",
}

REGION_MAP: dict[str, str] = {
    "OXY": "US",
    "FRO": "US",
    "NVDA": "US",
    "MSFT": "US",
    "PLTR": "US",
    "AG": "US",
    "PSX": "US",
    "DINO": "US",
    "DHT": "US",
    "PAAS": "US",
    "WPM": "US",
    "HL": "US",
    "EXK": "US",
    "BABA": "US",
    "KWEB": "US",
    "CCL": "US",
    "EQNR": "Europe",
    "EQNR.OL": "Europe",
    "TTE": "Europe",
    "TTE.PA": "Europe",
    "SHEL": "Europe",
    "SHEL.L": "Europe",
    "RHM.DE": "Europe",
    "BAYN.DE": "Europe",
    "DR0.DE": "Europe",
    "RIO.L": "Europe",
    "BHP.L": "Europe",
    "9988.HK": "Asia",
    "0700.HK": "Asia",
    "S.TO": "Americas",
}

THEME_MAP: dict[str, str] = {
    "OXY": "iran_hormuz",
    "FRO": "iran_hormuz",
    "EQNR": "iran_hormuz",
    "EQNR.OL": "iran_hormuz",
    "DHT": "iran_hormuz",
    "TTE": "iran_hormuz",
    "TTE.PA": "iran_hormuz",
    "SHEL": "iran_hormuz",
    "SHEL.L": "iran_hormuz",
    "AG": "silver_correction",
    "PAAS": "silver_correction",
    "WPM": "silver_correction",
    "HL": "silver_correction",
    "EXK": "silver_correction",
    "DR0.DE": "silver_correction",
    "NVDA": "tech_ai",
    "MSFT": "tech_ai",
    "PLTR": "tech_ai",
    "RHM.DE": "rearmament",
    "BAYN.DE": "healthcare_recovery",
}

# ── Limits ────────────────────────────────────────────────────────────────────

SECTOR_LIMIT_PCT = 0.40   # 40%
REGION_LIMIT_PCT = 0.60   # 60%
TICKER_LIMIT_PCT = 0.20   # 20%


def _get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker.upper(), SECTOR_MAP.get(ticker, "Other"))


def _get_region(ticker: str) -> str:
    return REGION_MAP.get(ticker.upper(), REGION_MAP.get(ticker, "Other"))


def _get_theme(ticker: str) -> str:
    return THEME_MAP.get(ticker.upper(), THEME_MAP.get(ticker, "other"))


def _position_value(pos: dict) -> float:
    """Berechnet EUR-Wert einer Position."""
    val = pos.get("position_size_eur") or 0.0
    if not val and pos.get("entry_price") and pos.get("shares"):
        val = float(pos["entry_price"]) * float(pos["shares"])
    return float(val)


# ── Public API ────────────────────────────────────────────────────────────────

def get_portfolio_exposure(open_positions: list[dict]) -> dict:
    """
    Analysiert Sektor-, Regions- und Theme-Konzentration des Portfolios.

    Args:
        open_positions: Liste von Dicts mit Feldern:
            ticker, position_size_eur (oder entry_price + shares)

    Returns:
        {
            'by_sector': {'Energy': {'count': 2, 'value': 26000, 'pct': 45.2}, ...},
            'by_region': {'US': {'count': 3, 'value': 30000, 'pct': 52.1}, ...},
            'by_theme':  {'iran_hormuz': {'count': 2, 'value': 26000, 'pct': 45.2}, ...},
            'by_ticker': {'OXY': {'value': 15000, 'pct': 26.1}, ...},
            'violations': ['Energy > 40% Limit (45.2%)', ...],
            'total_exposure': 57500,
        }
    """
    if not open_positions:
        return {
            "by_sector": {},
            "by_region": {},
            "by_theme": {},
            "by_ticker": {},
            "violations": [],
            "total_exposure": 0.0,
        }

    # Filter TESTOK und ähnliche Test-Ticker raus
    real_positions = [p for p in open_positions if p.get("ticker", "").upper() not in ("TESTOK",)]

    total = sum(_position_value(p) for p in real_positions)
    if total <= 0:
        total = 1  # Division-by-zero vermeiden

    by_sector: dict[str, dict] = {}
    by_region: dict[str, dict] = {}
    by_theme: dict[str, dict] = {}
    by_ticker: dict[str, dict] = {}

    for pos in real_positions:
        ticker = pos.get("ticker", "UNKNOWN")
        val = _position_value(pos)
        pct = (val / total) * 100

        sector = _get_sector(ticker)
        region = _get_region(ticker)
        theme = _get_theme(ticker)

        # by_sector
        if sector not in by_sector:
            by_sector[sector] = {"count": 0, "value": 0.0, "pct": 0.0, "tickers": []}
        by_sector[sector]["count"] += 1
        by_sector[sector]["value"] += val
        by_sector[sector]["pct"] += pct
        by_sector[sector]["tickers"].append(ticker)

        # by_region
        if region not in by_region:
            by_region[region] = {"count": 0, "value": 0.0, "pct": 0.0, "tickers": []}
        by_region[region]["count"] += 1
        by_region[region]["value"] += val
        by_region[region]["pct"] += pct
        by_region[region]["tickers"].append(ticker)

        # by_theme
        if theme not in by_theme:
            by_theme[theme] = {"count": 0, "value": 0.0, "pct": 0.0, "tickers": []}
        by_theme[theme]["count"] += 1
        by_theme[theme]["value"] += val
        by_theme[theme]["pct"] += pct
        by_theme[theme]["tickers"].append(ticker)

        # by_ticker
        by_ticker[ticker] = {"value": round(val, 2), "pct": round(pct, 1)}

    # Runde Werte
    for d in [by_sector, by_region, by_theme]:
        for k in d:
            d[k]["value"] = round(d[k]["value"], 2)
            d[k]["pct"] = round(d[k]["pct"], 1)

    # Violations prüfen
    violations = []

    for sector, data in by_sector.items():
        if data["pct"] / 100 > SECTOR_LIMIT_PCT:
            violations.append(
                f"Sektor {sector} > {SECTOR_LIMIT_PCT:.0%} Limit ({data['pct']:.1f}%)"
            )

    for region, data in by_region.items():
        if data["pct"] / 100 > REGION_LIMIT_PCT:
            violations.append(
                f"Region {region} > {REGION_LIMIT_PCT:.0%} Limit ({data['pct']:.1f}%)"
            )

    for ticker, data in by_ticker.items():
        if data["pct"] / 100 > TICKER_LIMIT_PCT:
            violations.append(
                f"Ticker {ticker} > {TICKER_LIMIT_PCT:.0%} Limit ({data['pct']:.1f}%)"
            )

    return {
        "by_sector": by_sector,
        "by_region": by_region,
        "by_theme": by_theme,
        "by_ticker": by_ticker,
        "violations": violations,
        "total_exposure": round(total, 2),
    }


def check_new_position_exposure(
    new_ticker: str,
    new_value: float,
    open_positions: list[dict],
) -> dict:
    """
    Prüft ob ein neuer Trade die Exposure-Limits verletzen würde.

    Returns:
        {
            'approved': bool,
            'violations': [...],
            'reason': str,
        }
    """
    # Simulierte neue Position einfügen
    simulated = list(open_positions) + [
        {"ticker": new_ticker, "position_size_eur": new_value}
    ]
    exposure = get_portfolio_exposure(simulated)

    if exposure["violations"]:
        return {
            "approved": False,
            "violations": exposure["violations"],
            "reason": f"Würde Limits verletzen: {'; '.join(exposure['violations'])}",
        }

    return {
        "approved": True,
        "violations": [],
        "reason": "Exposure-Limits eingehalten",
    }
