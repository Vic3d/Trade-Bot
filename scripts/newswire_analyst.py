#!/usr/bin/env python3
"""
NewsWire Analyst — liest DB, klassifiziert mit Haiku, analysiert mit Sonnet.
Wird von einem OpenClaw-Cron aufgerufen (alle 30 Min).
Output → memory/newswire-analysis.md (für Albert, nicht für Victor)

Tier-System:
  Tier 1: NewsWire Keyword-Match (bereits in DB)
  Tier 2: Dieses Script — per-Aktie Relevanz-Check (Haiku)
  Tier 3: Sonnet Impact-Analyse (nur bei echtem Treffer)
"""

import sqlite3, json, time, os
from datetime import datetime, timezone

DB_PATH      = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
ANALYSIS_OUT = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire-analysis.md")

# ── Per-Aktie Keyword-Sets (präzise, Tier-2-Filter) ───────────────────────────
# Diese Keywords sind spezifischer als die breiten Strategie-Keywords im Daemon.
# Nur wenn mindestens eines matcht → relevant für diese Aktie.

STOCK_KEYWORDS = {
    "EQNR": {
        "name": "Equinor ASA",
        "keywords": [
            "equinor", "eqnr", "norwegian oil", "north sea production",
            "snorre", "barents sea", "johan sverdrup", "equinor dividend",
            "equinor earnings", "equinor buyback",
        ],
        "strategy_keywords": [  # Indirekt relevant (Strategie-Level)
            "brent crude", "hormuz", "iran oil", "oil supply cut",
            "tanker seized", "opec cut", "iran blockade",
        ],
        "strategy": 1,
    },
    "DR0.DE": {
        "name": "Deutsche Rohstoff AG",
        "keywords": [
            "deutsche rohstoff", "dr0", "caza oil", "hammer metals",
            "wrl energy", "bright mountain",
        ],
        "strategy_keywords": [
            "brent crude", "wti crude", "hormuz", "oil supply cut",
            "iran oil", "opec",
        ],
        "strategy": 1,
    },
    "PLTR": {
        "name": "Palantir Technologies",
        "keywords": [
            "palantir", "pltr", "alex karp", "gotham platform",
            "foundry platform", "palantir contract", "palantir revenue",
            "palantir army", "palantir pentagon", "palantir doge",
            "palantir earnings", "palantir ai",
        ],
        "strategy_keywords": [
            "pentagon ai", "government software", "defense ai",
            "doge cuts defense", "michael burry palantir",
        ],
        "strategy": 3,
    },
    "NVDA": {
        "name": "Nvidia",
        "keywords": [
            "nvidia", "nvda", "jensen huang", "blackwell chip",
            "h100", "h200", "b200", "nvidia gpu", "nvidia earnings",
            "nvidia export", "cuda", "nvidia data center",
        ],
        "strategy_keywords": [
            "chip export ban", "ai chip ban", "china semiconductor",
            "helium supply chip", "tsmc nvidia", "us chip restriction",
        ],
        "strategy": 3,
    },
    "MSFT": {
        "name": "Microsoft",
        "keywords": [
            "microsoft", "msft", "azure", "satya nadella",
            "microsoft copilot", "microsoft openai", "azure revenue",
            "microsoft earnings", "microsoft layoffs", "microsoft ai",
        ],
        "strategy_keywords": [
            "openai", "cloud computing", "enterprise ai",
        ],
        "strategy": 3,
    },
    "BAYN.DE": {
        "name": "Bayer AG",
        "keywords": [
            "bayer ag", "bayn", "roundup verdict", "glyphosate",
            "monsanto", "bayer pharma", "bayer crop science",
            "bayer leverkusen aktie", "bayer earnings", "bayer lawsuit",
            "bayer dividend",
        ],
        "strategy_keywords": [],
        "strategy": None,
    },
    "RHM.DE": {
        "name": "Rheinmetall AG",
        "keywords": [
            "rheinmetall", "rhm.de", "panther tank",
            "lynx infantry", "rheinmetall order", "rheinmetall earnings",
            "rheinmetall contract", "rheinmetall dividend",
        ],
        "strategy_keywords": [
            "nato defense spending", "european rearmament",
            "bundeswehr", "ukraine weapons", "nato 3 percent",
            "waffenstillstand ukraine",
        ],
        "strategy": 2,
    },
    "RIO.L": {
        "name": "Rio Tinto",
        "keywords": [
            "rio tinto", "oyu tolgoi", "pilbara iron",
            "rio tinto copper", "rio tinto earnings", "rio tinto dividend",
            "rio tinto lithium",
        ],
        "strategy_keywords": [
            "copper demand", "iron ore china", "lithium demand",
            "ev battery metals", "china steel",
        ],
        "strategy": 5,
    },
    "AG": {
        "name": "First Majestic Silver",
        "keywords": [
            "first majestic silver", "first majestic", "santa elena mine",
            "jerritt canyon", "first majestic earnings",
        ],
        "strategy_keywords": [
            "silver price", "silver demand", "silver supply",
            "precious metals", "safe haven silver",
        ],
        "strategy": 4,
    },
    "ISPA.DE": {
        "name": "iShares Physical Silver ETC",
        "keywords": [
            "ispa.de", "physical silver", "silver etf", "silver etc",
        ],
        "strategy_keywords": [
            "silver price", "silver rally", "silver falls",
            "safe haven", "precious metals",
        ],
        "strategy": 4,
    },
}

def load_recent_events(minutes=35):
    """Lade Events der letzten N Minuten mit score >= 2."""
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - (minutes * 60)
    rows = conn.execute(
        """SELECT id, source, ticker, strategy_id, direction, headline, score
           FROM events
           WHERE ts > ? AND score >= 2
           ORDER BY score DESC, ts DESC
           LIMIT 50""",
        (cutoff,)
    ).fetchall()
    conn.close()
    return rows

def match_stock(headline: str) -> list[dict]:
    """
    Prüft ob die Headline direkt oder indirekt einer Aktie zuzuordnen ist.
    Gibt Liste von gematchten Aktien mit Match-Typ zurück.
    """
    low = headline.lower()
    matches = []
    for ticker, info in STOCK_KEYWORDS.items():
        direct = any(kw in low for kw in info["keywords"])
        indirect = any(kw in low for kw in info["strategy_keywords"])
        if direct or indirect:
            matches.append({
                "ticker": ticker,
                "name": info["name"],
                "strategy": info["strategy"],
                "match_type": "direct" if direct else "indirect",
            })
    return matches

def build_analysis_prompt(events_by_stock: dict) -> str:
    """Baut den Prompt für die Sonnet-Analyse."""
    lines = []
    lines.append("Du bist Albert, Trading-Analyst. Analysiere folgende News-Events kurz und präzise.")
    lines.append("Für jede Aktie: 2-3 Sätze — was bedeutet das für die Position/Strategie?")
    lines.append("Format: **[Aktie]**: [Analyse] | Impact: bullish/bearish/neutral | Handlung: [konkret oder 'beobachten']\n")

    for ticker, data in events_by_stock.items():
        lines.append(f"## {data['name']} ({ticker}) — Strategie {data['strategy']}")
        for h in data["headlines"]:
            lines.append(f"- [{h['direction']}] {h['headline']}")
        lines.append("")

    return "\n".join(lines)

def write_analysis(analysis: str, events_by_stock: dict):
    """Schreibt Analyse in die Analysis-Datei."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entry = f"\n## {ts}\n\n"
    entry += analysis + "\n"
    entry += "\n---\n"

    # Append zur Datei
    if not os.path.exists(ANALYSIS_OUT):
        with open(ANALYSIS_OUT, "w") as f:
            f.write("# NewsWire Analysis Log\n*Automatisch generiert — nur für Albert*\n\n")

    with open(ANALYSIS_OUT, "a") as f:
        f.write(entry)

def run():
    """Hauptlogik: DB lesen → per-Aktie matchen → Output für Cron-Analyse."""
    events = load_recent_events(minutes=35)

    if not events:
        print("KEIN_SIGNAL — keine relevanten Events in den letzten 35 Min")
        return

    # Per-Aktie gruppieren
    events_by_stock = {}
    for eid, source, ticker, strategy_id, direction, headline, score in events:
        matches = match_stock(headline)
        if not matches:
            # Kein direkter Match — ignorieren in Tier-2
            continue
        for m in matches:
            t = m["ticker"]
            if t not in events_by_stock:
                events_by_stock[t] = {
                    "name": m["name"],
                    "strategy": m["strategy"],
                    "headlines": [],
                }
            events_by_stock[t]["headlines"].append({
                "headline": headline,
                "direction": direction or "neutral",
                "score": score,
                "source": source,
                "match_type": m["match_type"],
            })

    if not events_by_stock:
        print("KEIN_SIGNAL — keine Tier-2-Matches gefunden")
        return

    # Output für den Cron-Job
    print(f"ANALYSE_REQUIRED: {len(events_by_stock)} Aktien betroffen")
    for ticker, data in events_by_stock.items():
        bearish_count = sum(1 for h in data["headlines"] if h["direction"] == "bearish")
        direct_count  = sum(1 for h in data["headlines"] if h["match_type"] == "direct")
        print(f"  {ticker} ({data['name']}): {len(data['headlines'])} Events, "
              f"{bearish_count} bearish, {direct_count} direkt")
        for h in data["headlines"]:
            print(f"    [{h['direction']:8}] [{h['match_type']:8}] score={h['score']} | {h['headline'][:80]}")

    # Prompt für Sonnet ausgeben (der Cron-Job gibt das an Sonnet weiter)
    print("\n=== SONNET_PROMPT_START ===")
    print(build_analysis_prompt(events_by_stock))
    print("=== SONNET_PROMPT_END ===")

if __name__ == "__main__":
    run()
