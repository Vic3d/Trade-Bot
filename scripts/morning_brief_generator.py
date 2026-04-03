#!/usr/bin/env python3
"""
morning_brief_generator.py — 🌅 Nacht-Briefing Generator
Läuft täglich 07:00 MEZ
Generiert strukturiertes Briefing aus overnight_events + Marktdaten + State Snapshot
"""
import sqlite3
import json
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'

# Strategy → Emoji Mapping
STRATEGY_EMOJIS = {
    "S1": "🛢️",
    "S1_Iran_Oil": "🛢️",
    "S2": "🛡️",
    "S2_Rüstung": "🛡️",
    "S3": "🤖",
    "S3_KI": "🤖",
    "S4": "🥈",
    "S4_Silber": "🥈",
    "S5": "⛏️",
    "S5_Rohstoffe": "⛏️",
    "S8": "🚢",
    "S8_Tanker_Lag": "🚢",
    "S9": "🌴",
    "S9_Kuba": "🌴",
    "S10": "✈️",
    "S10_Lufthansa": "✈️",
    "S11": "🪨",
    "S11_Edelmetall_Minen": "🪨",
}

IMPACT_EMOJI = {
    "bullish_oil": "🟢 Öl↑",
    "bearish_oil": "🔴 Öl↓",
    "bullish_defense": "🟢 Rüstung↑",
    "bullish_tech": "🟢 Tech↑",
    "bullish_metals": "🟢 Metalle↑",
    "bearish_airlines": "🔴 Airlines↓",
    "geopolitical_watchlist": "⚠️ Geo",
    "watchlist": "👁️ Watch",
    "watchlist_S9": "👁️ Kuba",
    "neutral": "〰️",
}


def fetch_market_data() -> dict:
    """Holt Brent (BZ=F), VIX (^VIX), EUR/USD (EURUSD=X) via Yahoo Finance.
    TRA-178: safe_price verhindert Futures-Rollover-Artefakte bei =F Symbolen."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from core.fetch_price import safe_price
    tickers = {"BZ=F": "Brent", "^VIX": "VIX", "EURUSD=X": "EUR/USD"}
    results = {}
    for ticker, label in tickers.items():
        d = safe_price(ticker, timeout=10)
        if d:
            results[label] = round(d['price'], 2)
            results[f"{label}_chg"] = round(d['change_pct'], 2)
        else:
            results[label] = "N/A"
    return results


def read_state_snapshot() -> str:
    """Liest state-snapshot.md und extrahiert Alerts + Positionen."""
    path = WS / 'memory/state-snapshot.md'
    if not path.exists():
        return "Kein State Snapshot vorhanden."
    try:
        content = path.read_text()
        # Extrahiere relevante Abschnitte
        lines = content.split('\n')
        relevant = []
        in_portfolio = False
        in_alerts = False
        in_watchlist = False
        for line in lines:
            if '## Portfolio' in line or '## Positionen' in line:
                in_portfolio = True
                relevant.append(line)
            elif '## Alert' in line:
                in_alerts = True
                relevant.append(line)
            elif '## Watchlist' in line:
                in_watchlist = True
                relevant.append(line)
            elif line.startswith('## ') and (in_portfolio or in_alerts or in_watchlist):
                in_portfolio = in_alerts = in_watchlist = False
            elif in_portfolio or in_alerts or in_watchlist:
                if line.strip():
                    relevant.append(line)
        return '\n'.join(relevant[:40]) if relevant else content[:600]
    except Exception as e:
        return f"State Snapshot Lesefehler: {e}"


def read_night_geo_log() -> str:
    """Liest night-geo-log.md falls vorhanden."""
    path = WS / 'memory/night-geo-log.md'
    if not path.exists():
        return ""
    try:
        content = path.read_text().strip()
        # Letzte 20 Zeilen
        lines = content.split('\n')
        recent = '\n'.join(lines[-20:])
        return recent if recent else ""
    except Exception:
        return ""


def get_overnight_events(today: str) -> list[dict]:
    """Liest overnight_events für heute mit novelty_score >= 0.5."""
    conn = sqlite3.connect(str(DB))

    # Prüfe ob magnitude_estimate Spalte vorhanden
    cols = [r[1] for r in conn.execute("PRAGMA table_info(overnight_events)").fetchall()]
    mag_col = ", magnitude_estimate" if "magnitude_estimate" in cols else ""

    rows = conn.execute(f"""
        SELECT id, event_id, timestamp, headline, source, source_tier,
               entities, strategies_affected, impact_direction, novelty_score{mag_col}
        FROM overnight_events
        WHERE briefing_date = ?
          AND novelty_score >= 0.5
        ORDER BY source_tier ASC, id DESC
    """, (today,)).fetchall()
    conn.close()

    has_mag = "magnitude_estimate" in cols
    events = []
    for row in rows:
        ev = {
            "id": row[0],
            "event_id": row[1],
            "timestamp": row[2],
            "headline": row[3],
            "source": row[4],
            "source_tier": row[5],
            "entities": json.loads(row[6] or "{}"),
            "strategies_affected": json.loads(row[7] or "[]"),
            "impact_direction": row[8],
            "novelty_score": row[9],
        }
        if has_mag:
            ev["magnitude_estimate"] = row[10]
        events.append(ev)
    return events


def format_time(ts_str: str) -> str:
    """Formatiert Timestamp zu lesbarer Zeit."""
    try:
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
            try:
                dt = datetime.strptime(ts_str[:19], fmt[:len(ts_str[:19])])
                return dt.strftime("%H:%M")
            except ValueError:
                continue
        return ts_str[:5]
    except Exception:
        return "??"


def format_event_line(event: dict) -> str:
    """Formatiert ein einzelnes Event als Bullet Point inkl. Magnitude-Schätzung."""
    headline = event["headline"]
    source = event["source"]
    time_str = format_time(event["timestamp"])
    impact = IMPACT_EMOJI.get(event["impact_direction"], "〰️")
    why = event["entities"].get("why", "")

    line = f"  • {impact} {headline}"
    if why and why not in ("parse error", "extraction failed"):
        line += f"\n    → {why}"
    line += f"\n    ({source}, {time_str})"

    # Magnitude-Schätzung anhängen (aus DB oder frisch berechnet)
    mag_str = _get_magnitude_line(event)
    if mag_str:
        line += f"\n    {mag_str}"

    return line


def _get_magnitude_line(event: dict) -> str:
    """Holt die Magnitude-Schätzung für ein Event (gecacht oder live)."""
    # Erst aus preberechneter magnitude_estimate Spalte
    mag_json = event.get("magnitude_estimate")
    if mag_json:
        try:
            mag = json.loads(mag_json) if isinstance(mag_json, str) else mag_json
            if mag.get("expected_pct_24h") is not None:
                return f"↳ {mag['formatted']}"
        except Exception:
            pass

    # Fallback: live berechnen
    try:
        import sys
        sys.path.insert(0, str(WS / 'scripts'))
        from magnitude_estimator import estimate_magnitude
        direction = event.get("impact_direction", "")
        strategies = event.get("strategies_affected", [])
        if isinstance(strategies, str):
            strategies = json.loads(strategies) if strategies else []
        entities = event.get("entities", {})
        ev_type = entities.get("event_type", direction) if isinstance(entities, dict) else direction
        strategy = strategies[0] if strategies else ""
        mag = estimate_magnitude(ev_type, strategy, direction, "")
        if mag.get("expected_pct_24h") is not None:
            return f"↳ {mag['formatted']}"
    except Exception:
        pass

    return ""


def get_trend_section() -> str:
    """Holt Trend-Signale von trend_detector — inkl. Magnitude-Schätzung."""
    try:
        import sys
        sys.path.insert(0, str(WS / 'scripts'))
        from trend_detector import detect_trends, format_trends_for_briefing
        trends = detect_trends(window_hours=8)  # Letzte 8h für Morgen-Briefing
        if not trends:
            return ""

        base_text = format_trends_for_briefing(trends)

        # Magnitude-Zeilen für jeden Trend anhängen
        try:
            from magnitude_estimator import format_trend_magnitude
            mag_lines = []
            for trend in trends:
                mag_line = format_trend_magnitude(trend)
                if mag_line:
                    mag_lines.append(mag_line)
            if mag_lines:
                base_text = base_text.rstrip() + "\n" + "\n".join(mag_lines)
        except Exception:
            pass  # Magnitude ist optional

        return base_text
    except Exception as e:
        return f"⚠️ Trend-Detection Fehler: {e}"


def get_calibration_section() -> str:
    """Holt Signal-Kalibrierungs-Report von feedback_loop."""
    try:
        import sys
        sys.path.insert(0, str(WS / 'scripts'))
        from feedback_loop import run_feedback_loop
        return run_feedback_loop()
    except Exception as e:
        return f"⚠️ Feedback-Loop Fehler: {e}"


def generate_briefing() -> str:
    """Hauptfunktion: generiert den vollständigen Briefing-Text."""
    today = date.today().isoformat()
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y")

    # Events laden — Graceful Degradation: kein Crash wenn DB/Tabelle fehlt
    try:
        events = get_overnight_events(today)
    except Exception as e:
        events = []
        print(f"⚠️  overnight_events nicht verfügbar: {e}")

    if not events:
        # Trotzdem ein Briefing liefern — nur ohne Events
        market = fetch_market_data()
        brent_str = f"${market.get('Brent', 'N/A')}"
        vix_str = str(market.get('VIX', 'N/A'))
        eurusd_str = str(market.get('EUR/USD', 'N/A'))
        return (
            f"📰 **Nacht-Briefing {date_str} — Keine neuen Overnight-Events**\n\n"
            f"VIX: {vix_str} | Brent: {brent_str} | EUR/USD: {eurusd_str}\n\n"
            f"Nacht war ruhig — keine relevanten geopolitischen Events (novelty_score ≥ 0.5).\n"
            f"_Xetra-Briefing: 08:30_"
        )

    # Marktdaten
    market = fetch_market_data()
    brent_str = f"${market.get('Brent', 'N/A')}"
    vix_str = str(market.get('VIX', 'N/A'))
    eurusd_str = str(market.get('EUR/USD', 'N/A'))

    # State Snapshot
    snapshot = read_state_snapshot()

    # Night Geo Log
    geo_log = read_night_geo_log()

    # ── Executive Summary (Top 3, Tier 1 zuerst) ────────────────────────────
    exec_events = [e for e in events if e["source_tier"] == 1][:3]
    if len(exec_events) < 3:
        exec_events += [e for e in events if e["source_tier"] == 2][:3 - len(exec_events)]
    if len(exec_events) < 3:
        exec_events += [e for e in events if e not in exec_events][:3 - len(exec_events)]

    exec_lines = []
    for e in exec_events[:3]:
        impact = IMPACT_EMOJI.get(e["impact_direction"], "〰️")
        exec_lines.append(f"• {impact} {e['headline']}")

    if not exec_lines:
        exec_lines = ["• Keine hochpriorisierten Events in der Nacht"]

    # ── Events gruppiert nach Strategie ─────────────────────────────────────
    strategy_groups = {}
    for event in events:
        strategies = event.get("strategies_affected", [])
        if not strategies:
            strategies = ["Allgemein"]
        for strategy in strategies:
            if strategy not in strategy_groups:
                strategy_groups[strategy] = []
            if event not in strategy_groups[strategy]:
                strategy_groups[strategy].append(event)

    # Normalisiere Strategie-Keys: S1_Iran_Oil → S1, etc.
    def normalize_strategy(s: str) -> str:
        """Normalisiert zu kurzem Key: S1_Iran_Oil → S1"""
        import re
        m = re.match(r'^(S\d+)', s)
        return m.group(1) if m else s

    # Re-gruppe mit normalisierten Keys
    norm_groups: dict = {}
    for strategy, evts in strategy_groups.items():
        norm_key = normalize_strategy(strategy)
        if norm_key not in norm_groups:
            norm_groups[norm_key] = {"events": [], "raw_key": strategy}
        for e in evts:
            if e not in norm_groups[norm_key]["events"]:
                norm_groups[norm_key]["events"].append(e)

    strategy_section_lines = []
    if norm_groups:
        for norm_key, data in sorted(norm_groups.items()):
            evts = data["events"]
            raw_key = data["raw_key"]
            emoji = STRATEGY_EMOJIS.get(norm_key, STRATEGY_EMOJIS.get(raw_key, "📌"))
            # Lesbarer Name
            strategy_labels = {
                "S1": "Öl/Iran/Hormuz", "S2": "Rüstung/NATO", "S3": "KI/Tech",
                "S4": "Silber/Gold", "S5": "Rohstoffe", "S8": "Tanker",
                "S9": "Kuba/Karibik", "S10": "Airlines", "S11": "Edelmetall-Minen",
                "Allgemein": "Allgemein"
            }
            label = strategy_labels.get(norm_key, norm_key)
            strategy_section_lines.append(f"\n{emoji} **{label}**")
            for e in evts[:3]:  # Max 3 pro Strategie
                strategy_section_lines.append(format_event_line(e))
    else:
        strategy_section_lines.append("  Keine neuen Overnight-Events.")

    # ── Alerts aus State Snapshot ────────────────────────────────────────────
    alerts_lines = []
    if snapshot:
        for line in snapshot.split('\n'):
            stripped = line.strip()
            # Skip: table headers, empty lines, section headers, separator lines
            if not stripped or stripped.startswith('#') or stripped.startswith('---'):
                continue
            if stripped.startswith('|') and ('Aktie' in stripped or '---' in stripped or 'Kurs' in stripped and 'Entry' in stripped):
                continue
            # Include: lines with actual alert/signal data
            if any(kw in stripped for kw in ['🔴', '🟢', '🟡', '⚠️', 'Stop:', 'Entry:', 'Alert:', 'PLTR', 'A3D42Y', 'A2DWAW', 'BAYN', 'LHA']):
                alerts_lines.append(f"  {stripped}")
            elif '|' in stripped and any(kw in stripped for kw in ['PLTR', 'A3D42Y', 'A2DWAW', 'BAYN', 'LHA', 'Palantir', 'Equinor', 'Bayer', 'Lufthansa']):
                # Parse position table row nicely
                parts = [p.strip() for p in stripped.split('|') if p.strip()]
                if len(parts) >= 4:
                    alerts_lines.append(f"  → {' | '.join(parts[:5])}")
    if not alerts_lines:
        alerts_lines = ["  Keine aktiven Alerts aus State Snapshot"]

    # ── Geo Log Ergänzung ────────────────────────────────────────────────────
    geo_section = ""
    if geo_log:
        geo_section = f"\n━━ GEO-LOG NACHT ━━\n{geo_log[:400]}\n"

    # ── Trend-Signale ─────────────────────────────────────────────────────────
    trend_section = get_trend_section()

    # ── Signal-Kalibrierung ───────────────────────────────────────────────────
    calibration_section = get_calibration_section()

    # ── Briefing zusammenbauen ────────────────────────────────────────────────
    event_count = len(events)
    tier1_count = sum(1 for e in events if e["source_tier"] == 1)

    # ── Trend-Sektion (nur wenn Trends vorhanden) ─────────────────────────────
    trend_block = f"\n{trend_section}\n" if trend_section else ""

    # ── Kalibrierungs-Sektion ─────────────────────────────────────────────────
    cal_block = f"\n━━ SIGNAL-KALIBRIERUNG ━━\n{calibration_section}\n" if calibration_section else ""

    briefing = f"""🌅 Nacht-Briefing {date_str} — 07:00 MEZ
({event_count} neue Events, davon {tier1_count} Tier-1)

━━ EXECUTIVE SUMMARY ━━
{chr(10).join(exec_lines)}

━━ NEU SEIT 19:00 GESTERN ━━
{chr(10).join(strategy_section_lines)}
{geo_section}{trend_block}
━━ MARKTKONTEXT ━━
Brent: {brent_str} | VIX: {vix_str} | EUR/USD: {eurusd_str}

━━ HEUTE BEOBACHTEN ━━
{chr(10).join(alerts_lines[:8])}
{cal_block}
_Xetra-Briefing: 08:30_"""

    return briefing


if __name__ == "__main__":
    print(generate_briefing())
