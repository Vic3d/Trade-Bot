#!/usr/bin/env python3
"""
magnitude_estimator.py — Schätzt erwartete Preisbewegung für ein Event.

Phase 1: Nutzt impact_magnitude_history (historische Daten)
Phase 2: Wird durch Feedback-Loop mit eigenen Messungen ergänzt (auto)

Lookup-Hierarchie:
  1. Exakter Match auf event_type
  2. Fuzzy Match (LIKE '%keyword%') auf event_type
  3. Direction-only Fallback (alle Events mit gleicher impact_direction)
  4. Kein Match → leere Antwort
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'

# Ticker → lesbarer Name für Formatierungen
TICKER_NAMES = {
    "BZ=F":      "Brent",
    "CL=F":      "WTI",
    "QQQ":       "Nasdaq/QQQ",
    "NVDA":      "Nvidia",
    "GC=F":      "Gold",
    "SI=F":      "Silber",
    "HG=F":      "Kupfer",
    "FRO":       "Frontline (FRO)",
    "^STOXX50E": "Euro Stoxx 50",
    "^VIX":      "VIX",
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _lookup_exact(conn: sqlite3.Connection, event_type: str) -> dict | None:
    """Exakter Match auf event_type."""
    row = conn.execute("""
        SELECT * FROM magnitude_estimates WHERE event_type = ?
    """, (event_type,)).fetchone()
    return _row_to_dict(row)


def _lookup_fuzzy(conn: sqlite3.Connection, event_type: str) -> dict | None:
    """Fuzzy-Match: zerlegt event_type in Keywords, sucht ähnliche Events."""
    # Zerlege event_type in Keywords (iran_military_action → iran, military, action)
    keywords = [kw for kw in event_type.replace('-', '_').split('_') if len(kw) > 3]
    if not keywords:
        return None

    for kw in keywords:
        row = conn.execute("""
            SELECT * FROM magnitude_estimates
            WHERE event_type LIKE ?
            ORDER BY n_events DESC
            LIMIT 1
        """, (f'%{kw}%',)).fetchone()
        if row:
            return _row_to_dict(row)
    return None


def _lookup_direction_fallback(conn: sqlite3.Connection, impact_direction: str) -> dict | None:
    """Fallback: aggregiert ALLE Events mit gleicher impact_direction."""
    rows = conn.execute("""
        SELECT avg_pct_24h, avg_pct_1week, min_pct, max_pct, std_dev, n_events, confidence,
               proxy_ticker, strategy, impact_direction
        FROM magnitude_estimates
        WHERE impact_direction = ?
    """, (impact_direction,)).fetchall()

    if not rows:
        return None

    # Gewichteter Durchschnitt (gewichtet nach n_events)
    total_n = sum(r['n_events'] for r in rows)
    if total_n == 0:
        return None

    avg_24h = sum(r['avg_pct_24h'] * r['n_events'] for r in rows) / total_n
    avg_1w_vals = [(r['avg_pct_1week'], r['n_events']) for r in rows if r['avg_pct_1week'] is not None]
    avg_1w = sum(v * n for v, n in avg_1w_vals) / sum(n for _, n in avg_1w_vals) if avg_1w_vals else None
    min_pct = min(r['min_pct'] for r in rows)
    max_pct = max(r['max_pct'] for r in rows)

    # Konfidenz reduzieren für Fallback
    base_conf = min(0.95, 0.5 + total_n * 0.03)
    confidence = round(base_conf * 0.75, 3)  # 25% Abschlag für Fallback

    # Häufigster Ticker
    ticker_counts = {}
    for r in rows:
        ticker_counts[r['proxy_ticker']] = ticker_counts.get(r['proxy_ticker'], 0) + r['n_events']
    best_ticker = max(ticker_counts, key=ticker_counts.get)

    return {
        "event_type": f"direction_fallback_{impact_direction}",
        "strategy": rows[0]['strategy'],
        "impact_direction": impact_direction,
        "proxy_ticker": best_ticker,
        "avg_pct_24h": round(avg_24h, 4),
        "avg_pct_1week": round(avg_1w, 4) if avg_1w is not None else None,
        "min_pct": round(min_pct, 4),
        "max_pct": round(max_pct, 4),
        "std_dev": None,
        "n_events": total_n,
        "confidence": confidence,
        "last_updated": datetime.now().isoformat(),
    }


def _format_result(data: dict, match_type: str) -> dict:
    """Formatiert einen DB-Row in das Rückgabe-Dict."""
    avg_24h = data.get('avg_pct_24h')
    avg_1w = data.get('avg_pct_1week')
    min_pct = data.get('min_pct', 0)
    max_pct = data.get('max_pct', 0)
    n = data.get('n_events', 0)
    conf = data.get('confidence', 0.5)
    ticker = data.get('proxy_ticker', '')
    direction = data.get('impact_direction', '')

    # Lesbarer Ticker-Name
    ticker_name = TICKER_NAMES.get(ticker, ticker)

    # Range-String
    sign_min = "+" if min_pct >= 0 else ""
    sign_max = "+" if max_pct >= 0 else ""
    range_str = f"{sign_min}{min_pct:.1f}–{sign_max}{max_pct:.1f}%"

    # Richtungsindikator für Formatierung
    if avg_24h is not None:
        sign = "+" if avg_24h >= 0 else ""
        trend_arrow = "↑" if avg_24h > 0 else "↓"
    else:
        sign, trend_arrow = "", "→"

    # 1-Woche String
    week_str = ""
    if avg_1w is not None:
        w_sign = "+" if avg_1w >= 0 else ""
        week_str = f", +1W: {w_sign}{avg_1w:.1f}%"

    # Basis-Beschreibung
    basis_map = {
        "exact": "historische Daten (exakter Match)",
        "fuzzy": "historische Daten (ähnlicher Event-Typ)",
        "direction": "historische Daten (Direction-Durchschnitt)",
    }
    basis = basis_map.get(match_type, "historische Daten")

    # Formatierter String fürs Briefing
    if avg_24h is not None:
        formatted = (
            f"{ticker_name} {sign}{avg_24h:.1f}% erwartet "
            f"(Range: {range_str}{week_str}, n={n}, Konf. {int(conf*100)}%)"
        )
    else:
        formatted = f"{ticker_name} — keine Schätzung verfügbar"

    return {
        "event_type": data.get('event_type', ''),
        "impact_direction": direction,
        "proxy_ticker": ticker,
        "ticker_name": ticker_name,
        "expected_pct_24h": round(avg_24h, 2) if avg_24h is not None else None,
        "expected_pct_1week": round(avg_1w, 2) if avg_1w is not None else None,
        "range_24h": range_str,
        "confidence": round(conf, 3),
        "n_events": n,
        "match_type": match_type,
        "basis": basis,
        "formatted": formatted,
    }


def estimate_magnitude(
    event_type: str,
    strategy: str = "",
    impact_direction: str = "",
    proxy_ticker: str = ""
) -> dict:
    """
    Schätzt die erwartete Preisbewegung für ein Event.

    Args:
        event_type: Event-Typ (z.B. 'iran_military_action', 'opec_surprise_cut')
        strategy: Strategie (z.B. 'S1', 'S3') — optional, verbessert Treffer
        impact_direction: Richtung (z.B. 'bullish_oil') — für Fallback
        proxy_ticker: Ticker (z.B. 'BZ=F') — optional

    Returns:
        Dict mit expected_pct_24h, confidence, formatted-String etc.
    """
    empty_result = {
        "event_type": event_type,
        "impact_direction": impact_direction,
        "proxy_ticker": proxy_ticker,
        "ticker_name": TICKER_NAMES.get(proxy_ticker, proxy_ticker),
        "expected_pct_24h": None,
        "expected_pct_1week": None,
        "range_24h": "N/A",
        "confidence": 0.0,
        "n_events": 0,
        "match_type": "none",
        "basis": "keine historischen Daten",
        "formatted": "Keine historische Datenbasis verfügbar",
    }

    try:
        conn = _get_conn()

        # 1. Exakter Match
        data = _lookup_exact(conn, event_type)
        if data:
            conn.close()
            return _format_result(data, "exact")

        # 2. Fuzzy Match
        data = _lookup_fuzzy(conn, event_type)
        if data:
            conn.close()
            return _format_result(data, "fuzzy")

        # 3. Direction Fallback
        if impact_direction:
            data = _lookup_direction_fallback(conn, impact_direction)
            if data:
                conn.close()
                return _format_result(data, "direction")

        conn.close()
        return empty_result

    except Exception as e:
        return {**empty_result, "basis": f"Fehler: {e}"}


def format_magnitude_for_briefing(events_list: list) -> str:
    """
    Formatiert Magnitude-Schätzungen für das Morning Briefing.

    Input: Liste von overnight_events Dicts (mit 'impact_direction', 'strategies_affected' etc.)
    Output: Formatierter String pro Event

    Beispiel Output:
        ↳ Brent +3.2% erwartet (∅ historisch bei iran_military_action, n=8, Konf. 72%)
    """
    lines = []
    seen_directions = set()

    for event in events_list:
        direction = event.get('impact_direction', '')
        strategies = event.get('strategies_affected', [])
        if isinstance(strategies, str):
            try:
                strategies = json.loads(strategies)
            except Exception:
                strategies = []

        # Dedupliziere pro Direction (nicht jeden Event einzeln)
        if direction in seen_directions or direction in ('neutral', 'watchlist', 'watchlist_S9', ''):
            continue

        # Event-Type aus entities oder direction ableiten
        entities = event.get('entities', {})
        if isinstance(entities, str):
            try:
                entities = json.loads(entities)
            except Exception:
                entities = {}
        event_type = entities.get('event_type', direction)

        strategy = strategies[0] if strategies else ""

        mag = estimate_magnitude(event_type, strategy, direction, "")

        if mag['expected_pct_24h'] is not None:
            lines.append(f"  ↳ {mag['formatted']}")
            seen_directions.add(direction)

    return '\n'.join(lines) if lines else ""


def format_trend_magnitude(trend: dict) -> str:
    """
    Formatiert Magnitude-Info für einen Trend (aus trend_detector).

    Input: {'impact_direction': 'bullish_oil', 'count': 7, 'strength': 'STRONG', ...}
    Output: '→ Brent +2-4% erwartet (∅ historisch: +3.1%, n=12, Konf. 72%)'
    """
    direction = trend.get('impact_direction', '')
    if not direction:
        return ""

    mag = estimate_magnitude("", "", direction, "")
    if mag['expected_pct_24h'] is None:
        return ""

    ticker_name = mag['ticker_name']
    avg = mag['expected_pct_24h']
    rng = mag['range_24h']
    n = mag['n_events']
    conf = int(mag['confidence'] * 100)
    sign = "+" if avg >= 0 else ""

    return f"   → {ticker_name} {sign}{avg:.1f}% erwartet (∅ historisch: {rng}, n={n}, Konf. {conf}%)"


# ─── CLI Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🧪 magnitude_estimator.py — Selbsttest\n")

    test_cases = [
        # (event_type, strategy, direction, ticker, beschreibung)
        ("iran_military_action",     "S1", "bullish_oil",  "BZ=F", "Iran Militäraktion → Brent"),
        ("opec_surprise_cut",        "S1", "bullish_oil",  "BZ=F", "OPEC Überraschungskürzung → Brent"),
        ("gulf_infrastructure_strike","S1","bullish_oil",  "BZ=F", "Infrastrukturangriff Gulf → Brent"),
        ("ai_competitive_shock",     "S3", "bearish_tech", "NVDA", "DeepSeek-Schock → NVDA"),
        ("nvidia_earnings_beat",     "S3", "bullish_tech", "NVDA", "Nvidia Earnings Beat → NVDA"),
        ("banking_crisis_safe_haven","S4", "bullish_metals","GC=F","Banking Crisis → Gold"),
        ("fed_pivot_signal",         "S3", "bullish_tech", "QQQ",  "Fed Pivot → QQQ"),
        ("opec_production_cut",      "S1", "bullish_oil",  "BZ=F", "OPEC Förderkürzung → Brent"),
        # Fuzzy Match Test
        ("iran_strike_new",          "S1", "bullish_oil",  "BZ=F", "Neuer Iran Strike (fuzzy)"),
        # Direction Fallback Test
        ("unknown_oil_event",        "S1", "bullish_oil",  "BZ=F", "Unbekanntes Öl-Event (fallback)"),
        # Kein Match
        ("completely_unknown_event", "",   "",             "",     "Komplett unbekannt (leer)"),
    ]

    print(f"{'Event-Type':<35} {'Match':<10} {'Ergebnis'}")
    print("─" * 90)

    for event_type, strategy, direction, ticker, desc in test_cases:
        result = estimate_magnitude(event_type, strategy, direction, ticker)
        match = result['match_type']
        formatted = result['formatted']
        print(f"{event_type:<35} [{match:<8}] {formatted}")

    print("\n─── Trend-Format Test ───")
    trend_test = {
        "impact_direction": "bullish_oil",
        "count": 7,
        "strength": "STRONG",
        "strategies": ["S1"]
    }
    print(format_trend_magnitude(trend_test))

    print("\n─── Briefing-Format Test ───")
    events_test = [
        {"impact_direction": "bullish_oil", "strategies_affected": ["S1"],
         "entities": {"event_type": "iran_military_action"}},
        {"impact_direction": "bearish_tech", "strategies_affected": ["S3"],
         "entities": {"event_type": "chip_export_controls"}},
    ]
    print(format_magnitude_for_briefing(events_test))

    print("\n✅ Selbsttest abgeschlossen.")
