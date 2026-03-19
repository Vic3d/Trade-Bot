#!/usr/bin/env python3
"""
NewsWire Learner — berechnet Keyword-Trefferquoten aus historischen Daten.
Läuft 1x pro Woche (Sonntag 20:00) oder auf Anfrage.

Logik: Wenn direction=bullish und price_4h_later > price_at_event → richtig
       Wenn direction=bearish und price_4h_later < price_at_event → richtig

Output: keyword_accuracy.json — welche Keywords sind valide Signale?
"""

import sqlite3, json, os, re
from collections import defaultdict

DB_PATH  = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "keyword_accuracy.json")

# Mindest-Datenpunkte für statistisch valide Aussage
MIN_SAMPLES = 5
# Schwellwert: ab welchem % Kursveränderung gilt eine News als "relevant"
PRICE_MOVE_THRESHOLD = 0.005  # 0.5%

def load_completed_events():
    """Events mit Einstieg UND 4h-Preis."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT ticker, strategy_id, direction, headline, score,
               price_at_event, price_4h_later, price_1d_later
        FROM events
        WHERE price_at_event IS NOT NULL
          AND price_4h_later IS NOT NULL
          AND direction IS NOT NULL
          AND direction != 'neutral'
        ORDER BY ts DESC
    """).fetchall()
    conn.close()
    return rows

def extract_keywords(headline: str) -> list[str]:
    """Extrahiert Schlüsselwörter aus Headline (einfache Wort-Tokenisierung)."""
    # Stopwords raus
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
                 "to", "for", "of", "and", "or", "but", "as", "by", "with",
                 "from", "that", "this", "it", "be", "has", "have", "had",
                 "not", "no", "up", "down", "–", "-", "|", ":", "der", "die",
                 "das", "ein", "eine", "und", "oder", "ist", "sind", "des"}
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b', headline.lower())
    return [w for w in words if w not in stopwords]

def run():
    events = load_completed_events()

    if len(events) < MIN_SAMPLES:
        print(f"Zu wenig Daten: {len(events)} Events mit 4h-Preis. Mindestens {MIN_SAMPLES} benötigt.")
        return

    print(f"Analysiere {len(events)} abgeschlossene Events...")

    # Per-Ticker Statistiken
    ticker_stats = defaultdict(lambda: {"correct": 0, "wrong": 0, "total": 0, "avg_move_pct": []})
    keyword_stats = defaultdict(lambda: {"correct": 0, "wrong": 0, "total": 0})
    strategy_stats = defaultdict(lambda: {"correct": 0, "wrong": 0, "total": 0})

    for ticker, strategy_id, direction, headline, score, p_entry, p_4h, p_1d in events:
        if not ticker or not p_entry or p_entry == 0:
            continue

        move_pct = (p_4h - p_entry) / p_entry

        # War die Vorhersage richtig?
        if direction == "bullish":
            correct = move_pct > PRICE_MOVE_THRESHOLD
        elif direction == "bearish":
            correct = move_pct < -PRICE_MOVE_THRESHOLD
        else:
            continue

        # Ticker-Stats
        t = ticker.split(",")[0]
        ticker_stats[t]["total"] += 1
        ticker_stats[t]["avg_move_pct"].append(move_pct * 100)
        if correct:
            ticker_stats[t]["correct"] += 1
        else:
            ticker_stats[t]["wrong"] += 1

        # Strategie-Stats
        if strategy_id:
            strategy_stats[strategy_id]["total"] += 1
            if correct:
                strategy_stats[strategy_id]["correct"] += 1
            else:
                strategy_stats[strategy_id]["wrong"] += 1

        # Keyword-Stats
        for kw in extract_keywords(headline):
            keyword_stats[kw]["total"] += 1
            if correct:
                keyword_stats[kw]["correct"] += 1
            else:
                keyword_stats[kw]["wrong"] += 1

    # Keywords mit genug Daten filtern + sortieren
    valid_keywords = {
        kw: {
            "accuracy": round(s["correct"] / s["total"] * 100, 1),
            "correct": s["correct"],
            "wrong": s["wrong"],
            "total": s["total"],
            "signal_strength": "strong" if s["correct"]/s["total"] >= 0.7 else
                               "moderate" if s["correct"]/s["total"] >= 0.55 else "noise"
        }
        for kw, s in keyword_stats.items()
        if s["total"] >= MIN_SAMPLES
    }

    # Ticker-Stats aufbereiten
    ticker_summary = {}
    for t, s in ticker_stats.items():
        if s["total"] >= 3:
            acc = round(s["correct"] / s["total"] * 100, 1)
            avg_move = round(sum(s["avg_move_pct"]) / len(s["avg_move_pct"]), 2)
            ticker_summary[t] = {
                "accuracy": acc,
                "avg_move_4h_pct": avg_move,
                "total": s["total"],
            }

    result = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
        "total_events_analyzed": len(events),
        "ticker_accuracy": ticker_summary,
        "strategy_accuracy": {str(k): v for k, v in strategy_stats.items()},
        "top_keywords_by_accuracy": dict(
            sorted(valid_keywords.items(),
                   key=lambda x: x[1]["accuracy"], reverse=True)[:30]
        ),
        "noise_keywords": [
            kw for kw, d in valid_keywords.items()
            if d["signal_strength"] == "noise"
        ],
    }

    with open(OUT_PATH, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Konsolen-Output
    print(f"\n=== KEYWORD ACCURACY REPORT ===")
    print(f"Analysierte Events: {len(events)}")
    print(f"\nTop Signale (>= {MIN_SAMPLES} Datenpunkte):")
    for kw, d in list(result["top_keywords_by_accuracy"].items())[:15]:
        bar = "█" * int(d["accuracy"] / 10)
        print(f"  {kw:20} {bar:10} {d['accuracy']:5.1f}%  ({d['total']} Events, {d['signal_strength']})")

    if result["noise_keywords"]:
        print(f"\nRauschen (entfernen?): {', '.join(result['noise_keywords'][:10])}")

    print(f"\nGespeichert: {OUT_PATH}")

if __name__ == "__main__":
    run()
