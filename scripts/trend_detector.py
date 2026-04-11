#!/usr/bin/env python3
"""
trend_detector.py — Trend-Erkennung für overnight_events
Erkennt wenn mehrere Events in kurzer Zeit dieselbe Impact-Direction signalisieren.

Schwellenwerte:
  3-4 Events = MODERATE Trend 🟡
  5+ Events  = STRONG Trend 🔴

Verwendung:
  python3 trend_detector.py          → Trends der letzten 3h ausgeben
  python3 trend_detector.py --hours 6  → Zeitfenster überschreiben
"""
import sqlite3
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
GEO_LOG = WS / 'memory/night-geo-log.md'

STRATEGY_LABELS = {
    "S1": "Öl/Iran/Hormuz",
    "S2": "Rüstung/NATO",
    "S3": "KI/Tech",
    "S4": "Silber/Gold",
    "S5": "Rohstoffe",
    "S8": "Tanker",
    "S9": "Kuba/Karibik",
    "S10": "Airlines",
    "S11": "Edelmetall-Minen",
}


def normalize_strategy(s: str) -> str:
    """S1_Iran_Oil → S1"""
    import re
    m = re.match(r'^(S\d+)', s)
    return m.group(1) if m else s


def detect_trends(window_hours: float = 3, min_events: int = 3) -> list[dict]:
    """
    Schaut in overnight_events der letzten window_hours.
    Gruppiert nach (strategy, impact_direction).
    Wenn eine Gruppe >= min_events hat → Trend erkannt.

    Returns Liste von Trend-Dicts mit:
      strategy, direction, count, strength, headlines, sources
    """
    conn = sqlite3.connect(str(DB))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime(
        '%Y-%m-%d %H:%M:%S'
    )

    rows = conn.execute("""
        SELECT id, headline, source, strategies_affected, impact_direction,
               novelty_score, timestamp
        FROM overnight_events
        WHERE timestamp >= ?
          AND novelty_score >= 0.5
          AND impact_direction != 'neutral'
        ORDER BY timestamp DESC
    """, (cutoff,)).fetchall()
    conn.close()

    if not rows:
        return []

    # Gruppieren nach (strategy, direction)
    groups = defaultdict(list)
    for ev_id, headline, source, strategies_json, direction, novelty, ts in rows:
        try:
            strategies = json.loads(strategies_json or "[]")
        except Exception:
            strategies = []

        for s in strategies:
            norm = normalize_strategy(s)
            key = (norm, direction)
            groups[key].append({
                "id": ev_id,
                "headline": headline,
                "source": source,
                "novelty": novelty,
                "timestamp": ts,
            })

    trends = []
    for (strategy, direction), events in groups.items():
        count = len(events)
        if count < min_events:
            continue

        strength = "STRONG" if count >= 5 else "MODERATE"

        # Top 3 Headlines (nach novelty)
        sorted_events = sorted(events, key=lambda e: e["novelty"], reverse=True)
        headlines = [e["headline"] for e in sorted_events[:3]]
        sources = list({e["source"] for e in events if e["source"]})[:3]

        trends.append({
            "strategy": strategy,
            "direction": direction,
            "count": count,
            "strength": strength,
            "headlines": headlines,
            "sources": sources,
            "label": STRATEGY_LABELS.get(strategy, strategy),
        })

    # Stärkste Trends zuerst
    trends.sort(key=lambda t: t["count"], reverse=True)
    return trends


def format_trends_for_briefing(trends: list[dict],
                                calibration_report: str = "") -> str:
    """Formatiert Trends für das Morning Briefing."""
    if not trends:
        return ""

    lines = ["━━ TREND-SIGNALE ━━"]
    for t in trends:
        emoji = "🔴" if t["strength"] == "STRONG" else "🟡"
        label = t["label"]
        direction = t["direction"]
        count = t["count"]
        window = "3h"

        lines.append(f"\n{emoji} {t['strength']}: {t['strategy']} {direction} — {count} Events in {window}")
        lines.append(f"   Thema: {label}")

        for i, h in enumerate(t["headlines"][:3]):
            lines.append(f"   – {h}")

        # Kalibrierungs-Trefferquote wenn verfügbar
        if calibration_report and direction in calibration_report:
            for cal_line in calibration_report.split("\n"):
                if direction in cal_line and "%" in cal_line:
                    pct_part = cal_line.strip()
                    lines.append(f"   → {pct_part}")
                    break

    return "\n".join(lines)


def log_strong_trends_to_geo_log(trends: list[dict]):
    """Schreibt STRONG Trends in night-geo-log.md."""
    strong = [t for t in trends if t["strength"] == "STRONG"]
    if not strong:
        return

    GEO_LOG.parent.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines_to_add = []
    for t in strong:
        lines_to_add.append(
            f"[TREND] {now_str} — 🔴 STRONG: {t['strategy']} {t['direction']} "
            f"({t['count']} Events in 3h): {t['headlines'][0] if t['headlines'] else ''}"
        )

    existing = GEO_LOG.read_text(encoding="utf-8") if GEO_LOG.exists() else ""
    with open(GEO_LOG, 'w') as f:
        f.write(existing)
        f.write("\n".join(lines_to_add) + "\n")

    print(f"  📝 {len(lines_to_add)} STRONG-Trend(s) in night-geo-log.md eingetragen")


def format_trends_for_terminal(trends: list[dict]) -> str:
    """Lesbarer Output für CLI."""
    if not trends:
        return "✅ Keine Trends erkannt (mind. 3 gleichgerichtete Events in 3h nötig)."

    lines = []
    for t in trends:
        emoji = "🔴" if t["strength"] == "STRONG" else "🟡"
        lines.append(
            f"\n{emoji} {t['strength']}: {t['strategy']} ({t['label']}) "
            f"→ {t['direction']} | {t['count']} Events in 3h"
        )
        for h in t["headlines"]:
            lines.append(f"   • {h}")
        if t["sources"]:
            lines.append(f"   Quellen: {', '.join(t['sources'])}")

    return "\n".join(lines)


if __name__ == "__main__":
    # CLI-Parameter für Zeitfenster
    hours = 3
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--hours" and i + 1 < len(sys.argv[1:]):
            try:
                hours = float(sys.argv[i + 2])
            except ValueError:
                pass

    print(f"🔍 Trend-Analyse — letzten {hours}h\n")
    trends = detect_trends(window_hours=hours)

    if trends:
        print(format_trends_for_terminal(trends))
        log_strong_trends_to_geo_log(trends)
    else:
        print("✅ Keine Trends erkannt")
