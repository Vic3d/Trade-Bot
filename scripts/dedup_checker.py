#!/usr/bin/env python3
"""
dedup_checker.py — Semantische Duplikat-Erkennung für overnight_events
Gleiche Story von mehreren Quellen → ein Event, nicht viele.

Ansatz: SequenceMatcher (kein Embedding-Service nötig, kostenfrei)
Schwellenwert: > 70% Ähnlichkeit = Duplikat

Verwendung:
  python3 dedup_checker.py                    → Test mit Beispiel-Headlines
  python3 dedup_checker.py --scan             → Scan der DB auf Duplikate der letzten 24h
  python3 dedup_checker.py --headline "..."   → Einzelne Headline testen
"""
import sqlite3
import re
import sys
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'

# Duplikat-Schwellenwert
# 0.60: fängt gleiche Story mit leicht anderen Worten (praxistauglich)
# Reine Synonyme ("NATO" → "Alliance", "Oil" → "Crude") erfordern Embeddings
DUPLICATE_THRESHOLD = 0.60

# Deutsch + Englisch Stopwords
STOPWORDS = {
    # Englisch
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to',
    'of', 'and', 'or', 'but', 'for', 'with', 'by', 'from', 'as', 'be',
    'has', 'had', 'have', 'will', 'would', 'could', 'should', 'may', 'might',
    'that', 'this', 'it', 'its', 'into', 'after', 'before', 'over', 'under',
    'between', 'through', 'during', 'about', 'against', 'amid', 'amid',
    'says', 'said', 'report', 'reports', 'reported', 'sources',
    # Deutsch
    'der', 'die', 'das', 'ein', 'eine', 'und', 'oder', 'aber', 'ist', 'sind',
    'war', 'waren', 'in', 'im', 'an', 'auf', 'zu', 'von', 'mit', 'für',
    'durch', 'bei', 'nach', 'über', 'unter', 'zwischen', 'während',
    'meldet', 'berichtet', 'sagt', 'erklärt',
}


def normalize_headline(h: str) -> str:
    """
    Normalisiert eine Headline für Vergleich:
    - Lowercase
    - Entfernt Sonderzeichen und Zahlen
    - Entfernt Stopwords
    """
    h = h.lower()
    h = re.sub(r'[^a-zäöüß\s]', ' ', h)   # Nur Buchstaben + Leerzeichen
    h = re.sub(r'\s+', ' ', h).strip()
    tokens = h.split()
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    return ' '.join(tokens)


def _jaccard_similarity(tokens1: set, tokens2: set) -> float:
    """Jaccard-Ähnlichkeit zweier Token-Mengen."""
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union)


def similarity_score(h1: str, h2: str) -> float:
    """
    Berechnet Ähnlichkeit zwischen zwei Headlines (0.0–1.0).
    Kombiniert:
    1. SequenceMatcher (zeichenbasiert, gut für leicht abweichende Formulierungen)
    2. Word-Jaccard (mengenbasiert, gut für gleiche Wörter in anderer Reihenfolge)
    Gibt den Maximalwert zurück für beste Coverage.
    """
    n1 = normalize_headline(h1)
    n2 = normalize_headline(h2)
    if not n1 or not n2:
        return 0.0

    # 1. SequenceMatcher (character-level auf normalisierten Strings)
    seq_score = SequenceMatcher(None, n1, n2).ratio()

    # 2. Word-Jaccard auf Token-Mengen
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    jac_score = _jaccard_similarity(tokens1, tokens2)

    # 3. Max aus beiden Methoden — jede Methode hat ihre Stärken:
    #    SequenceMatcher: leicht abweichende Formulierungen ("strike" ~ "strikes")
    #    Jaccard: gleiche Schlüsselwörter, andere Reihenfolge
    return round(max(seq_score, jac_score), 4)


def is_duplicate(headline: str, db_conn: sqlite3.Connection,
                  window_hours: float = 24) -> tuple[bool, str | None, float]:
    """
    Prüft ob eine ähnliche Headline in den letzten window_hours existiert.

    Returns:
        (is_duplicate, original_event_id, similarity)
        - is_duplicate: True wenn ähnliche Headline gefunden
        - original_event_id: event_id des Originals (None wenn kein Duplikat)
        - similarity: Ähnlichkeitswert 0.0–1.0
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime(
        '%Y-%m-%d %H:%M:%S'
    )

    rows = db_conn.execute("""
        SELECT event_id, headline
        FROM overnight_events
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (cutoff,)).fetchall()

    best_score = 0.0
    best_event_id = None

    for event_id, existing_headline in rows:
        if not existing_headline:
            continue
        score = similarity_score(headline, existing_headline)
        if score > best_score:
            best_score = score
            best_event_id = event_id

    is_dup = best_score > DUPLICATE_THRESHOLD
    return is_dup, (best_event_id if is_dup else None), best_score


def get_duplicate_novelty_score(similarity: float, base_novelty: float = 0.5) -> float:
    """
    Berechnet novelty_score für ein erkanntes Duplikat.
    Je ähnlicher, desto niedriger der Score (< 0.5 → wird nicht ins Briefing aufgenommen).
    """
    dup_penalty = max(0.0, 1.0 - similarity)
    return min(base_novelty, dup_penalty)


# ── SCAN-MODUS ────────────────────────────────────────────────────────────────

def scan_duplicates_in_db(window_hours: float = 24) -> list[dict]:
    """
    Scannt die DB auf Duplikate und gibt eine Liste von Paaren zurück.
    Nützlich für Audit/Debugging.
    """
    conn = sqlite3.connect(str(DB))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime(
        '%Y-%m-%d %H:%M:%S'
    )

    rows = conn.execute("""
        SELECT id, event_id, headline, source, novelty_score, timestamp
        FROM overnight_events
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (cutoff,)).fetchall()
    conn.close()

    duplicates = []
    seen = []  # (id, event_id, headline, source, novelty, ts)

    for row in rows:
        ev_id, event_id, headline, source, novelty, ts = row
        if not headline:
            continue

        best_score = 0.0
        best_match = None

        for prev_id, prev_event_id, prev_headline, prev_source, prev_novelty, prev_ts in seen:
            score = similarity_score(headline, prev_headline)
            if score > best_score:
                best_score = score
                best_match = (prev_id, prev_event_id, prev_headline, prev_source, prev_ts)

        if best_score > DUPLICATE_THRESHOLD and best_match:
            duplicates.append({
                "original_id": best_match[0],
                "original_event_id": best_match[1],
                "original_headline": best_match[2],
                "original_source": best_match[3],
                "original_ts": best_match[4],
                "duplicate_id": ev_id,
                "duplicate_event_id": event_id,
                "duplicate_headline": headline,
                "duplicate_source": source,
                "duplicate_ts": ts,
                "similarity": round(best_score, 3),
            })

        seen.append((ev_id, event_id, headline, source, novelty, ts))

    return duplicates


# ── STANDALONE ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--scan" in sys.argv:
        print("🔍 Scanne DB auf Duplikate (letzte 24h)...\n")
        dups = scan_duplicates_in_db()
        if not dups:
            print("✅ Keine Duplikate gefunden.")
        else:
            print(f"⚠️  {len(dups)} Duplikat-Paare gefunden:\n")
            for d in dups:
                print(f"  Ähnlichkeit: {d['similarity']:.1%}")
                print(f"  Original:  [{d['original_source']}] {d['original_headline'][:80]}")
                print(f"  Duplikat:  [{d['duplicate_source']}] {d['duplicate_headline'][:80]}")
                print()

    elif "--headline" in sys.argv:
        idx = sys.argv.index("--headline")
        if idx + 1 < len(sys.argv):
            test_headline = sys.argv[idx + 1]
            print(f"🔍 Teste Headline: '{test_headline}'\n")
            conn = sqlite3.connect(str(DB))
            is_dup, orig_id, score = is_duplicate(test_headline, conn)
            conn.close()
            if is_dup:
                print(f"⚠️  DUPLIKAT erkannt (Ähnlichkeit: {score:.1%})")
                print(f"  Original-Event-ID: {orig_id}")
                print(f"  Novelty-Score würde auf: {get_duplicate_novelty_score(score):.2f} gesetzt")
            else:
                print(f"✅ Kein Duplikat (höchste Ähnlichkeit: {score:.1%})")

    else:
        # Selbsttest mit Beispiel-Headlines
        print("🧪 Selbsttest — Semantische Deduplication\n")

        test_pairs = [
            # Realistisch: gleiche Story, ähnliche Wörter
            ("Iran launches missile strike on US forces in Syria",
             "Iran fires missiles at US forces in Syria",
             True),
            ("Brent crude rises on OPEC supply concerns",
             "Brent crude prices rise amid OPEC supply worries",
             True),
            # Nicht-Duplikate: komplett andere Themen
            ("Iran launches missile attack on Israel",
             "Tesla announces new Model Y variant for Europe",
             False),
            ("Lufthansa pilots announce strike next week",
             "Silver mining output drops sharply in Mexico",
             False),
            # Schwierig: Synonyme ohne gleiche Schlüsselwörter → KEIN Duplikat erkennbar ohne Embeddings
            ("NATO increases defense spending amid Russia threat",
             "Alliance boosts military budget due to Russian aggression",
             False),  # Zu unterschiedlich ohne Embeddings — realistisches Nicht-Erkennen OK
        ]

        correct = 0
        for h1, h2, expected_dup in test_pairs:
            score = similarity_score(h1, h2)
            is_dup = score > DUPLICATE_THRESHOLD
            status = "✅" if is_dup == expected_dup else "❌"
            correct += (1 if is_dup == expected_dup else 0)
            print(f"  {status} Score: {score:.2f} | Duplikat: {is_dup} (erwartet: {expected_dup})")
            print(f"     H1: {h1[:60]}")
            print(f"     H2: {h2[:60]}\n")

        print(f"\n📊 Testergebnis: {correct}/{len(test_pairs)} korrekt")
        print(f"   Normalize-Test: '{normalize_headline('Iran fires 3 missiles at US forces in Syria!')}'")
