#!/usr/bin/env python3
"""
headline_classifier.py — LLM-basierte Nachrichtenklassifikation
================================================================
Kernstück der neuen News-Architektur (April 2026):

ALT: Keywords → Filter → nur Matches gespeichert → alles andere verworfen
NEU: ALLES reinholen → Haiku klassifiziert JEDE Headline → nichts geht verloren

Warum: Keyword-Systeme fangen nur was du vorhersehen kannst.
       LLM-Klassifikation fängt auch Black Swans und Policy-Signale
       die keine Keywords matchen ("US erwägt neue Maßnahmen" → Öl-relevant).

Kosten: ~100-300 Headlines/Tag × ~0.001€/Call = 0.10-0.30€/Tag
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'

# ── Portfolio-Kontext für den Klassifikator ──────────────────────────────────
PORTFOLIO_CONTEXT = """Du bist ein Finanz-Nachrichtenklassifikator für ein Paper-Trading-Portfolio.

AKTIVE STRATEGIEN:
- S1: Iran/Öl/Hormuz — Ölpreis-Thesis (EQNR, OXY, FRO). Alles was Ölpreis beeinflusst.
- S2: NATO/Rüstung — Europäische Verteidigung (RHM.DE). Alles was Rüstungsausgaben beeinflusst.
- S3: KI/Tech — AI-Boom (NVDA, PLTR, ASML). Alles was Tech/Halbleiter beeinflusst.
- S4: Silber/Gold — Edelmetalle als Safe Haven. Alles was Gold/Silber beeinflusst.
- S5: Kupfer/Rohstoffe — Industrie-Metalle (RIO, BHP). Alles was Industrienachfrage beeinflusst.
- S8: Tanker — Schifffahrt/Frachtraten. Alles was Öl-Transport beeinflusst.
- S9: Kuba — Geopolitische Sondersituation.
- S10: Airlines — Lufthansa. Treibstoffkosten, Luftverkehr.
- PS20: Makro — Rezession, Zinsen, globale Risiken.
- JP: Japan — BOJ, Yen, Nikkei.
- CN: China — PBOC, Yuan, Handelsstreit, Tech-Regulierung.

WATCHLIST-TICKER: EQNR, PLTR, OXY, RHM.DE, NVDA, ASML, RIO, BAYN.DE, FRO, AG

WICHTIG: Bewerte auch INDIREKTE Relevanz. Beispiele:
- "Trump kündigt Gespräche mit Iran an" → S1 (beeinflusst Ölpreis-Erwartung)
- "US Navy entsendet Carrier Group" → S1 + S2 (Hormuz-Risiko + Rüstung)
- "Neues EU-Sanktionspaket" → könnte S1, S5, CN betreffen
- "Rezessionsangst wächst" → PS20 + alle Strategien betroffen
"""

CLASSIFY_PROMPT_TEMPLATE = """Klassifiziere diese Nachrichten-Headlines für unser Trading-Portfolio.

Für JEDE Headline antworte mit JSON:
{{
  "relevant": true/false,
  "relevance_score": 0.0-1.0,
  "strategies": ["S1", "PS20", ...],
  "impact": "bullish|bearish|neutral|mixed",
  "category": "geopolitical|macro|earnings|policy|military|trade|tech|commodity|other",
  "urgency": "high|medium|low",
  "why": "Ein Satz warum relevant/irrelevant"
}}

Antworte NUR mit einem JSON-Array. Ein Objekt pro Headline, gleiche Reihenfolge.

Headlines:
{headlines}"""


def _ensure_table(conn):
    """Erstellt die headline_classifications Tabelle falls nötig."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS headline_classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_event_id INTEGER,
            headline TEXT NOT NULL,
            source TEXT,
            relevant BOOLEAN DEFAULT 0,
            relevance_score REAL DEFAULT 0.0,
            strategies TEXT,
            impact TEXT,
            category TEXT,
            urgency TEXT,
            reasoning TEXT,
            classified_at TEXT DEFAULT (datetime('now')),
            classifier_version TEXT DEFAULT 'v1',
            UNIQUE(headline)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_hc_relevant
        ON headline_classifications(relevant, relevance_score DESC)
    """)
    conn.commit()


def classify_headlines(headlines: list[dict], batch_size: int = 25) -> list[dict]:
    """
    Klassifiziert Headlines per Haiku-LLM.

    Input: [{"id": 123, "headline": "...", "source": "..."}, ...]
    Output: [{"id": 123, "relevant": True, "relevance_score": 0.8, ...}, ...]

    Batched: Max 25 Headlines pro API-Call (Token-Limit Haiku).
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        print("[headline_classifier] ANTHROPIC_API_KEY nicht gesetzt — Fallback auf keyword-only")
        return _keyword_fallback(headlines)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        print("[headline_classifier] anthropic nicht installiert — Fallback")
        return _keyword_fallback(headlines)

    all_results = []

    # Batch processing
    for i in range(0, len(headlines), batch_size):
        batch = headlines[i:i + batch_size]
        headlines_text = "\n".join(
            f'{idx+1}. [{h.get("source", "?")}] {h["headline"]}'
            for idx, h in enumerate(batch)
        )

        prompt = CLASSIFY_PROMPT_TEMPLATE.format(headlines=headlines_text)

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=2000,
                system=PORTFOLIO_CONTEXT,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = msg.content[0].text.strip()

            # Parse JSON (auch mit Markdown Code-Fences)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            classifications = json.loads(raw)

            # Map zurück auf Headline-IDs
            for idx, cls in enumerate(classifications):
                if idx < len(batch):
                    result = {
                        "id": batch[idx].get("id"),
                        "headline": batch[idx]["headline"],
                        "source": batch[idx].get("source", ""),
                        "relevant": cls.get("relevant", False),
                        "relevance_score": cls.get("relevance_score", 0.0),
                        "strategies": cls.get("strategies", []),
                        "impact": cls.get("impact", "neutral"),
                        "category": cls.get("category", "other"),
                        "urgency": cls.get("urgency", "low"),
                        "why": cls.get("why", ""),
                    }
                    all_results.append(result)

            # Rate limiting
            if i + batch_size < len(headlines):
                time.sleep(0.5)

        except json.JSONDecodeError as e:
            print(f"[headline_classifier] JSON-Parse-Fehler: {e}")
            # Fallback für diese Batch
            all_results.extend(_keyword_fallback(batch))
        except Exception as e:
            print(f"[headline_classifier] API-Fehler: {e}")
            all_results.extend(_keyword_fallback(batch))

    return all_results


def classify_and_store(conn=None, lookback_minutes: int = 60, force_reclassify: bool = False):
    """
    Hauptfunktion: Holt unklassifizierte Headlines aus news_events,
    klassifiziert per LLM, speichert in headline_classifications.

    Returns: (total_classified, relevant_count)
    """
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(str(DB))
        close_conn = True

    _ensure_table(conn)

    # Hole unklassifizierte Headlines
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).strftime('%Y-%m-%d %H:%M:%S')

    if force_reclassify:
        query = """
            SELECT id, headline, source FROM news_events
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """
    else:
        query = """
            SELECT ne.id, ne.headline, ne.source FROM news_events ne
            LEFT JOIN headline_classifications hc ON ne.headline = hc.headline
            WHERE ne.created_at >= ? AND hc.id IS NULL
            ORDER BY ne.created_at DESC
        """

    rows = conn.execute(query, (cutoff,)).fetchall()

    if not rows:
        print(f"[headline_classifier] Keine neuen Headlines zu klassifizieren (lookback={lookback_minutes}min)")
        if close_conn:
            conn.close()
        return 0, 0

    print(f"[headline_classifier] {len(rows)} Headlines zu klassifizieren...")

    headlines = [{"id": r[0], "headline": r[1], "source": r[2] or ""} for r in rows]
    results = classify_headlines(headlines)

    # Speichern
    relevant_count = 0
    for r in results:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO headline_classifications
                (news_event_id, headline, source, relevant, relevance_score,
                 strategies, impact, category, urgency, reasoning, classifier_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1')
            """, (
                r.get("id"),
                r["headline"],
                r.get("source", ""),
                1 if r.get("relevant") else 0,
                r.get("relevance_score", 0.0),
                json.dumps(r.get("strategies", []), ensure_ascii=False),
                r.get("impact", "neutral"),
                r.get("category", "other"),
                r.get("urgency", "low"),
                r.get("why", ""),
            ))
            if r.get("relevant"):
                relevant_count += 1
        except Exception as e:
            print(f"[headline_classifier] Store-Fehler: {e}")

    conn.commit()
    print(f"[headline_classifier] ✅ {len(results)} klassifiziert, {relevant_count} relevant")

    if close_conn:
        conn.close()

    return len(results), relevant_count


def get_relevant_headlines(conn=None, min_score: float = 0.3, hours: int = 24,
                           strategies: list = None) -> list[dict]:
    """
    Holt relevante, klassifizierte Headlines.
    Optional gefiltert nach Strategie.
    """
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(str(DB))
        close_conn = True

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

    rows = conn.execute("""
        SELECT headline, source, relevance_score, strategies, impact,
               category, urgency, reasoning, classified_at
        FROM headline_classifications
        WHERE relevant = 1 AND relevance_score >= ? AND classified_at >= ?
        ORDER BY relevance_score DESC, classified_at DESC
    """, (min_score, cutoff)).fetchall()

    results = []
    for r in rows:
        strats = json.loads(r[3]) if r[3] else []
        # Strategie-Filter
        if strategies and not any(s in strats for s in strategies):
            continue
        results.append({
            "headline": r[0], "source": r[1], "score": r[2],
            "strategies": strats, "impact": r[3], "category": r[5],
            "urgency": r[6], "why": r[7], "classified_at": r[8],
        })

    if close_conn:
        conn.close()
    return results


def _keyword_fallback(headlines: list[dict]) -> list[dict]:
    """
    Fallback wenn LLM nicht verfügbar: Keyword-basierte Grundklassifikation.
    Besser als nichts, aber deutlich schlechter als LLM.
    """
    GEOPOLITICAL_KEYWORDS = [
        'trump', 'iran', 'hormuz', 'sanctions', 'tariff', 'trade war',
        'military', 'navy', 'war', 'peace', 'deal', 'blockade', 'attack',
        'missile', 'nuclear', 'china', 'russia', 'nato', 'defense',
        'opec', 'oil', 'fed', 'rate', 'recession', 'crisis',
        'pentagon', 'centcom', 'carrier', 'warship', 'strait',
        'diplomat', 'negotiat', 'ultimatum', 'retaliat', 'escalat',
        'sanktion', 'handelskrieg', 'blockade', 'vergeltung',
        'massnahmen', 'olexport', 'teheran', 'persisch',
        'executive order', 'dekret', 'white house',
    ]
    STRATEGY_MAP = {
        'iran': ['S1'], 'hormuz': ['S1'], 'oil': ['S1'], 'opec': ['S1'],
        'brent': ['S1'], 'tanker': ['S1', 'S8'], 'teheran': ['S1'],
        'olexport': ['S1'], 'persisch': ['S1'], 'strait': ['S1'],
        'nato': ['S2'], 'defense': ['S2'], 'military': ['S2'],
        'pentagon': ['S1', 'S2'], 'centcom': ['S1', 'S2'],
        'carrier': ['S1', 'S2'], 'warship': ['S1', 'S2'],
        'nvidia': ['S3'], 'ai ': ['S3'], 'semiconductor': ['S3'], 'chip': ['S3'],
        'gold': ['S4'], 'silver': ['S4'],
        'copper': ['S5'], 'mining': ['S5'],
        'airline': ['S10'], 'lufthansa': ['S10'],
        'fed': ['PS20'], 'recession': ['PS20'], 'rate': ['PS20'],
        'china': ['CN'], 'japan': ['JP'], 'boj': ['JP'],
        'trump': ['PS20'], 'white house': ['PS20'],
        'executive order': ['PS20'], 'dekret': ['PS20'],
        'handelskrieg': ['PS20', 'CN'], 'trade war': ['PS20', 'CN'],
    }

    results = []
    for h in headlines:
        hl = h["headline"].lower()
        matched_strategies = set()
        keyword_hits = 0

        for kw in GEOPOLITICAL_KEYWORDS:
            if kw in hl:
                keyword_hits += 1
                for strategy in STRATEGY_MAP.get(kw, []):
                    matched_strategies.add(strategy)

        relevant = keyword_hits > 0
        score = min(1.0, keyword_hits * 0.25)

        results.append({
            "id": h.get("id"),
            "headline": h["headline"],
            "source": h.get("source", ""),
            "relevant": relevant,
            "relevance_score": score,
            "strategies": list(matched_strategies),
            "impact": "neutral",
            "category": "other",
            "urgency": "medium" if keyword_hits >= 2 else "low",
            "why": f"keyword fallback ({keyword_hits} hits)",
        })
    return results


if __name__ == '__main__':
    total, relevant = classify_and_store(lookback_minutes=120)
    print(f"\nErgebnis: {total} klassifiziert, {relevant} relevant")
