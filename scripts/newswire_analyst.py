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

import sqlite3, json, time, os, re
from datetime import datetime, timezone

DB_PATH      = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
DB_TRADING   = os.path.join(os.path.dirname(__file__), "..", "data", "trading.db")
ANALYSIS_OUT = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire-analysis.md")

# ── P1.4 — Sentiment-Magnitude ────────────────────────────────────────────────

# Stärke 3 — starke Handlungsworte / Extremereignisse
MAGNITUDE_STRONG = {
    "threatens", "strikes", "vows", "sanctions", "closes", "attacks",
    "invades", "bans", "seizes", "declares", "war", "crisis", "shock",
    "crash", "collapse",
}

# Stärke 2 — moderate Signale
MAGNITUDE_MEDIUM = {
    "warns", "considers", "tensions", "rising", "escalates", "concerns",
    "risks", "disputes", "protests",
}

# Stärke 1 — schwache / vage Signale (alles andere landet hier als Default)
MAGNITUDE_WEAK = {
    "suggests", "hints", "slightly", "minor", "modest", "gradual",
    "possible", "could",
}


def calculate_magnitude(headline: str) -> int:
    """
    Berechnet Sentiment-Magnitude (1–3) aus Schlüsselwörtern.

    Returns:
        3 = Strong (Extremereignis, sofortige Marktreaktion wahrscheinlich)
        2 = Medium (moderates Signal, Watchlist)
        1 = Weak (Rauschen, vage Formulierung)
    """
    words = set(re.findall(r'\b\w+\b', headline.lower()))
    if words & MAGNITUDE_STRONG:
        return 3
    if words & MAGNITUDE_MEDIUM:
        return 2
    return 1


def ensure_magnitude_column_trading_db():
    """
    Fügt magnitude-Spalte in overnight_events hinzu falls nicht vorhanden.
    Idempotent (ALTER TABLE schlägt fehl wenn Spalte existiert → ignorieren).
    """
    try:
        conn = sqlite3.connect(DB_TRADING)
        try:
            conn.execute("ALTER TABLE overnight_events ADD COLUMN magnitude INTEGER DEFAULT 1")
            conn.commit()
            print("[magnitude] Spalte 'magnitude' zu overnight_events hinzugefügt")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        conn.close()
    except Exception as e:
        print(f"[magnitude] DB-Migration Fehler: {e}")


def ensure_magnitude_column_newswire_db():
    """
    Fügt magnitude-Spalte in events (newswire.db) hinzu falls nicht vorhanden.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("ALTER TABLE events ADD COLUMN magnitude INTEGER DEFAULT 1")
            conn.commit()
            print("[magnitude] Spalte 'magnitude' zu newswire.events hinzugefügt")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        conn.close()
    except Exception as e:
        print(f"[magnitude] newswire DB-Migration Fehler: {e}")

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
    "LHA.DE": {
        "name": "Lufthansa AG",
        "keywords": [
            "lufthansa", "lha.de", "lufthansa aktie", "lufthansa earnings",
            "lufthansa ergebnis", "lufthansa quartal", "lufthansa dividende",
            "lufthansa cargo", "lufthansa strike", "lufthansa streik",
            "lufthansa pilot", "lufthansa kapitalerhöhung",
        ],
        "strategy_keywords": [
            # Peace/De-escalation triggers (BUY signal for S10)
            "iran waffenstillstand", "iran ceasefire", "iran peace deal",
            "iran nuclear deal", "hormuz reopened", "iran de-escalation",
            "middle east ceasefire", "iran sanctions lifted",
            "iran airspace", "iran flight routes",
            # Oil price drop (BUY signal)
            "brent falls", "oil price drop", "crude oil decline",
            "brent unter 75", "brent below 75",
            # Airline sector recovery
            "airline recovery", "flight demand", "aviation rebound",
            "kerosene price", "jet fuel price drop",
        ],
        "strategy": 10,
    },
}

def load_recent_events(minutes=35):
    """
    Lade Events der letzten N Minuten mit score >= 2. Inkl. magnitude.
    
    'minutes' bezieht sich auf den Ingest-Zeitpunkt (ts = wann Albert die News
    gesehen hat). In news_pipeline.py wird zusätzlich das Publikations-Alter
    gefiltert (MAX_NEWS_AGE_HOURS). Beide Checks greifen zusammen.
    """
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - (minutes * 60)

    # Prüfe ob magnitude-Spalte existiert
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    mag_col = "magnitude" if "magnitude" in cols else "1 AS magnitude"

    rows = conn.execute(
        f"""SELECT id, source, ticker, strategy_id, direction, headline, score, {mag_col}
           FROM events
           WHERE ts > ? AND score >= 2
           ORDER BY score DESC, ts DESC
           LIMIT 50""",
        (cutoff,)
    ).fetchall()
    conn.close()

    if rows:
        print(f"[analyst] {len(rows)} Events aus den letzten {minutes} Min geladen")
    else:
        print(f"[analyst] Keine Events in den letzten {minutes} Min (cutoff={cutoff})")

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
    # P1.4 DB-Migration: magnitude-Spalten sicherstellen
    ensure_magnitude_column_newswire_db()
    ensure_magnitude_column_trading_db()

    # Phase 3: News-Pipeline mit Dedup vor jedem Analyst-Run ausführen
    # Schreibt frische News in trading.db:news_events (für Conviction Scorer)
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))
        from news_pipeline import run_full_pipeline
        pipeline_result = run_full_pipeline()
        print(f"[pipeline] +{pipeline_result['inserted']} neue Events, {pipeline_result['skipped_similar']} Duplikate gefiltert")
    except Exception as e:
        print(f"[pipeline] Warnung: {e}")

    events = load_recent_events(minutes=35)

    if not events:
        print("KEIN_SIGNAL — keine relevanten Events in den letzten 35 Min")
        return

    # Per-Aktie gruppieren
    events_by_stock = {}
    for row in events:
        eid, source, ticker, strategy_id, direction, headline, score = row[:7]
        mag_raw = row[7] if len(row) > 7 else None

        # P1.4: Magnitude berechnen (aus DB oder neu berechnen)
        if mag_raw is None or mag_raw == 1:
            magnitude = calculate_magnitude(headline)
            # Magnitude in DB zurückschreiben falls Spalte vorhanden
            try:
                upd_conn = sqlite3.connect(DB_PATH)
                upd_conn.execute(
                    "UPDATE events SET magnitude = ? WHERE id = ?",
                    (magnitude, eid)
                )
                upd_conn.commit()
                upd_conn.close()
            except Exception:
                pass
        else:
            magnitude = int(mag_raw)

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
                "magnitude": magnitude,
            })

    if not events_by_stock:
        print("KEIN_SIGNAL — keine Tier-2-Matches gefunden")
        return

    # Output für den Cron-Job
    print(f"ANALYSE_REQUIRED: {len(events_by_stock)} Aktien betroffen")
    for ticker, data in events_by_stock.items():
        bearish_count = sum(1 for h in data["headlines"] if h["direction"] == "bearish")
        direct_count  = sum(1 for h in data["headlines"] if h["match_type"] == "direct")
        strong_count  = sum(1 for h in data["headlines"] if h.get("magnitude", 1) >= 3)
        print(f"  {ticker} ({data['name']}): {len(data['headlines'])} Events, "
              f"{bearish_count} bearish, {direct_count} direkt, {strong_count} STRONG")
        for h in data["headlines"]:
            mag = h.get("magnitude", 1)
            mag_label = {3: "💥STRONG", 2: "⚡MED", 1: "·weak"}[mag]
            print(f"    [{h['direction']:8}] [{h['match_type']:8}] score={h['score']} mag={mag_label} | {h['headline'][:75]}")

    # Prompt für Sonnet ausgeben (der Cron-Job gibt das an Sonnet weiter)
    print("\n=== SONNET_PROMPT_START ===")
    print(build_analysis_prompt(events_by_stock))
    print("=== SONNET_PROMPT_END ===")

if __name__ == "__main__":
    run()
