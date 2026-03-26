"""
trademind/risk/stress_test.py — Portfolio Stress-Tests

Simuliert historische Crash-Szenarien und berechnet den erwarteten
Verlust für das aktuelle Portfolio.

Szenarien:
    vix_spike_50:      VIX auf 50 (2020-Crash-Stil)
    oil_crash_20pct:   Öl -20% (Saudi-Russland Preiskrieg 2020)
    tech_crash_15pct:  Tech -15% (2022-Stil)
    black_swan_10pct:  Alles -10% (unspezifischer Crash)
"""

from trademind.risk.portfolio import SECTOR_MAP, _get_sector, _position_value

# ── Szenarien ─────────────────────────────────────────────────────────────────

SCENARIOS: dict[str, dict] = {
    "vix_spike_50": {
        "name": "VIX Spike auf 50",
        "description": "Panik-Verkäufe wie März 2020. Alle riskanten Assets crashen.",
        "shocks": {
            "Energy":     -0.12,
            "Technology": -0.15,
            "Mining":     -0.10,
            "Defense":    -0.05,
            "Healthcare": -0.08,
            "Consumer":   -0.13,
            "Other":      -0.10,
        },
    },
    "oil_crash_20pct": {
        "name": "Öl -20% über Nacht",
        "description": "Saudi-Arabien/Russland Preiskrieg. Öl-Sektor kollabiert.",
        "shocks": {
            "Energy":     -0.20,
            "Mining":     -0.05,
            "Technology": -0.02,
            "Defense":    -0.01,
            "Healthcare": -0.01,
            "Consumer":   -0.03,
            "Other":      -0.03,
        },
    },
    "tech_crash_15pct": {
        "name": "Tech Crash -15%",
        "description": "Zinserhöhungs-Schock wie 2022. Tech-Bewertungen kollabieren.",
        "shocks": {
            "Technology": -0.15,
            "Mining":     -0.03,
            "Energy":     -0.02,
            "Defense":    -0.02,
            "Healthcare": -0.04,
            "Consumer":   -0.05,
            "Other":      -0.05,
        },
    },
    "black_swan_10pct": {
        "name": "Black Swan -10% alles",
        "description": "Unspezifischer Schock — alles fällt gleichzeitig 10%.",
        "shocks": {
            s: -0.10
            for s in set(SECTOR_MAP.values()) | {"Other"}
        },
    },
}


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _calc_scenario_loss(open_positions: list[dict], shocks: dict[str, float]) -> dict:
    """
    Berechnet erwarteten Verlust für ein Szenario.

    Returns:
        {
            'total_loss': -2300.0,
            'by_position': [{'ticker': 'OXY', 'loss': -1200.0, 'shock_pct': -12}, ...],
        }
    """
    total_loss = 0.0
    by_position = []

    for pos in open_positions:
        ticker = pos.get("ticker", "UNKNOWN")
        if ticker.upper() == "TESTOK":
            continue

        val = _position_value(pos)
        sector = _get_sector(ticker)
        shock = shocks.get(sector, shocks.get("Other", -0.05))

        loss = val * shock
        total_loss += loss

        by_position.append({
            "ticker": ticker,
            "sector": sector,
            "value": round(val, 2),
            "shock_pct": round(shock * 100, 1),
            "loss": round(loss, 2),
        })

    # Sortiere nach Verlust (schlimmster zuerst)
    by_position.sort(key=lambda x: x["loss"])

    return {
        "total_loss": round(total_loss, 2),
        "by_position": by_position,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def run_stress_tests(open_positions: list[dict]) -> list[dict]:
    """
    Führt alle definierten Stress-Test-Szenarien durch.

    Args:
        open_positions: Liste von Dicts mit ticker + position_size_eur
                        (oder entry_price + shares)

    Returns:
        [
            {
                'id': 'vix_spike_50',
                'name': 'VIX Spike auf 50',
                'description': '...',
                'total_loss': -2300.0,
                'by_position': [...],
                'severity': 'high' | 'medium' | 'low',
            },
            ...
        ]
    """
    if not open_positions:
        return []

    results = []

    for scenario_id, scenario in SCENARIOS.items():
        calc = _calc_scenario_loss(open_positions, scenario["shocks"])

        total_loss = calc["total_loss"]

        # Severity einschätzen
        abs_loss = abs(total_loss)
        if abs_loss > 3000:
            severity = "critical"
        elif abs_loss > 1500:
            severity = "high"
        elif abs_loss > 500:
            severity = "medium"
        else:
            severity = "low"

        results.append({
            "id": scenario_id,
            "name": scenario["name"],
            "description": scenario["description"],
            "total_loss": total_loss,
            "by_position": calc["by_position"],
            "severity": severity,
            "shocks": scenario["shocks"],
        })

    # Sortiere nach Verlust (schlimmster zuerst)
    results.sort(key=lambda x: x["total_loss"])

    return results


def format_stress_results(results: list[dict], show_positions: bool = False) -> str:
    """Formatiert Stress-Test-Ergebnisse als lesbaren Report."""
    if not results:
        return "  Keine offenen Positionen — kein Stress-Test möglich"

    severity_icon = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢",
    }

    lines = []
    for r in results:
        icon = severity_icon.get(r["severity"], "⚪")
        lines.append(
            f"  {icon} {r['name']:<28} → {r['total_loss']:>+8.0f}€  [{r['severity'].upper()}]"
        )
        if show_positions:
            for pos in r["by_position"][:5]:  # Top 5 biggest losers
                lines.append(
                    f"       {pos['ticker']:<10} {pos['sector']:<12} "
                    f"{pos['shock_pct']:+.0f}%  → {pos['loss']:>+7.0f}€"
                )
            if len(r["by_position"]) > 5:
                lines.append(f"       ... und {len(r['by_position'])-5} weitere Positionen")

    return "\n".join(lines)
