#!/usr/bin/env python3
"""
overnight_collector.py — Nacht-Research-Collector
Läuft 00:00, 02:00, 04:00, 06:00 MEZ
1. Feedback-Loop: Preis-Checks + Kalibrierung
2. Führt news_pipeline.py aus (frische News in news_events)
3. Liest news_events der letzten 30min
4. Keyword-Matching + Source-Ranking + Impact-Detection
5. Semantische Dedup (statt SHA256)
6. Entity Extraction via Haiku (nur für hochwertige neue Events)
7. INSERT in overnight_events
8. Trend-Detection nach Ingestion
"""
import subprocess
import sqlite3
import json
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
RULES_FILE = WS / 'data/night_relevance_rules.json'
NEWS_PIPELINE = WS / 'scripts/news_pipeline.py'

# ── IMPACT RULES ────────────────────────────────────────────────────────────
# Format: (pos_keywords, neg_keywords, strategies, impact_direction, base_novelty)
IMPACT_RULES = [
    (["Iran", "attack", "strike", "missile"], ["ceasefire", "deal"],   ["S1"],       "bullish_oil",            0.85),
    (["Iran", "ceasefire", "deal", "peace"],  [],                       ["S1"],       "bearish_oil",            0.80),
    (["Hormuz", "blocked", "mines"],          [],                       ["S1"],       "bullish_oil",            0.90),
    (["tanker", "Tanker"],                    [],                       ["S1", "S8"], "watchlist",              0.65),
    (["Cuba", "Kuba"],                        [],                       ["S9"],       "watchlist_S9",           0.80),
    (["Trump", "sanction"],                   [],                       ["S1", "S9"], "geopolitical_watchlist", 0.60),
    (["NATO", "defense", "Rüstung"],          [],                       ["S2"],       "bullish_defense",        0.70),
    (["Fed", "cut", "Zinssenkung"],           [],                       ["S3"],       "bullish_tech",           0.75),
    (["silver", "Silber"],                    [],                       ["S4"],       "bullish_metals",         0.70),
    (["oil", "kerosin"],                      [],                       ["S10", "S11"], "bearish_airlines",     0.70),
]


def load_relevance_rules():
    try:
        with open(RULES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Relevanz-Regeln nicht geladen: {e}")
        return {}


def rank_source(source: str) -> int:
    """Source-Tier: 1=Primär, 2=Finanz, 3=Andere"""
    try:
        from source_ranker import rank_source as _rank
        return _rank(source)
    except ImportError:
        pass
    if not source:
        return 3
    s = source.lower()
    tier1 = ["liveuamap", "reuters", "apnews", "dpa", "bbc", "gov", "centcom", "pentagon"]
    tier2 = ["bloomberg", "ft.com", "wsj", "google", "finnhub", "polygon", "marketwatch", "yahoo"]
    for kw in tier1:
        if kw in s:
            return 1
    for kw in tier2:
        if kw in s:
            return 2
    return 3


def make_event_id(headline: str) -> str:
    return hashlib.sha256(headline[:60].encode()).hexdigest()[:16]


def match_impact_rules(headline: str) -> tuple[list, str, float]:
    """
    Gibt (strategies_affected, impact_direction, base_novelty) zurück.
    Leere Liste wenn kein Match.
    """
    import re
    def kw_in(kw, text):
        kl, tl = kw.lower(), text.lower()
        if len(kl) <= 3:
            return bool(re.search(r'\b' + re.escape(kl) + r'\b', tl))
        return kl in tl

    for pos_kws, neg_kws, strategies, direction, novelty in IMPACT_RULES:
        # Check negative keywords (disqualify)
        if neg_kws and any(kw_in(nk, headline) for nk in neg_kws):
            continue
        # Check positive keywords (at least one must match)
        if any(kw_in(pk, headline) for pk in pos_kws):
            return strategies, direction, novelty
    return [], "neutral", 0.0


def _kw_match(keyword: str, text: str) -> bool:
    """Keyword-Match mit Word-Boundary für kurze Keywords (≤3 Zeichen)."""
    import re
    kl = keyword.lower()
    tl = text.lower()
    if len(kl) <= 3:
        # Word boundary match für kurze Keywords (AI, Fed, VIX etc.)
        return bool(re.search(r'\b' + re.escape(kl) + r'\b', tl))
    return kl in tl


def match_tier2_keywords(headline: str, rules: dict) -> list[str]:
    """Matcht Tier-2 Strategy-Keywords, gibt Liste betroffener Strategien zurück."""
    matched = []
    tier2 = rules.get("tier2_strategy_keywords", {})
    for strategy, keywords in tier2.items():
        if any(_kw_match(kw, headline) for kw in keywords):
            matched.append(strategy)
    return matched


def match_tier3_meta(headline: str, rules: dict) -> bool:
    """Prüft ob ein Tier-3 Meta-Keyword matcht (immer flag)."""
    tier3 = rules.get("tier3_meta_always_flag", [])
    return any(kw.lower() in headline.lower() for kw in tier3)


def run_news_pipeline():
    """Führt news_pipeline.py aus um frische News zu laden."""
    try:
        result = subprocess.run(
            [sys.executable, str(NEWS_PIPELINE)],
            capture_output=True, text=True, timeout=120
        )
        if result.stdout:
            print(f"📡 Pipeline: {result.stdout.strip()[:200]}")
        if result.returncode != 0 and result.stderr:
            print(f"⚠️  Pipeline Fehler: {result.stderr.strip()[:200]}")
    except subprocess.TimeoutExpired:
        print("⚠️  news_pipeline.py Timeout nach 120s")
    except Exception as e:
        print(f"⚠️  Pipeline nicht ausführbar: {e}")


def collect():
    print(f"🌙 overnight_collector.py — {datetime.now().strftime('%Y-%m-%d %H:%M')} MEZ")

    # 0. Feedback-Loop: ausstehende Preis-Checks + Kalibrierung
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from feedback_loop import run_feedback_loop
        run_feedback_loop()
    except Exception as e:
        print(f"⚠️  Feedback-Loop Fehler: {e}")

    # 1. News Pipeline ausführen
    run_news_pipeline()

    conn = sqlite3.connect(str(DB))
    rules = load_relevance_rules()

    # 2. Bestimme welche Tabellen vorhanden sind
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    # Finde News-Tabelle
    news_table = None
    for candidate in ["news_events", "articles", "news_articles", "events"]:
        if candidate in tables:
            news_table = candidate
            break

    if not news_table:
        print(f"❌ Keine News-Tabelle gefunden! Tabellen: {tables}")
        conn.close()
        return 0

    print(f"📋 News-Tabelle: {news_table}")

    # 3. Lese Artikel der letzten 30 Minuten
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    today = datetime.now().strftime('%Y-%m-%d')

    # Adaptive column detection
    cols = {r[1]: r[0] for r in conn.execute(f"PRAGMA table_info({news_table})").fetchall()}

    # Map column names
    headline_col = next((c for c in ["headline", "title"] if c in cols), None)
    source_col = next((c for c in ["source", "source_name"] if c in cols), None)
    time_col = next((c for c in ["created_at", "published_at", "ts"] if c in cols), None)

    if not headline_col:
        print(f"❌ Kein Headline-Spalte in {news_table}")
        conn.close()
        return 0

    select_cols = [headline_col]
    if source_col:
        select_cols.append(source_col)
    if time_col:
        select_cols.append(time_col)

    query = f"SELECT {', '.join(select_cols)} FROM {news_table}"
    if time_col:
        query += f" WHERE {time_col} >= ?"
        articles = conn.execute(query, (cutoff,)).fetchall()
    else:
        # Fallback: take last 50 rows
        query += f" ORDER BY id DESC LIMIT 50"
        articles = conn.execute(query).fetchall()

    print(f"📰 {len(articles)} Artikel aus den letzten 30min")

    # 4. Prüfe existierende event_ids der letzten 24h (für schnellen Pre-Check)
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    existing_ids = set(
        r[0] for r in conn.execute(
            "SELECT event_id FROM overnight_events WHERE timestamp >= ?",
            (cutoff_24h,)
        ).fetchall()
    )

    # Semantische Dedup importieren
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from dedup_checker import is_duplicate as semantic_is_duplicate, get_duplicate_novelty_score
        USE_SEMANTIC_DEDUP = True
        print("  🧠 Semantische Dedup aktiv")
    except Exception as e:
        USE_SEMANTIC_DEDUP = False
        print(f"  ⚠️  Semantische Dedup nicht verfügbar: {e}")

    # 5. Entity Extractor (lazy import)
    def try_extract_entities(headline, source_tier, strategies):
        """Nur bei novelty=1.0, tier<=2, mindestens 1 Strategie via Keywords"""
        if source_tier > 2 or not strategies:
            return None
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from entity_extractor import extract_entities
            return extract_entities(headline)
        except Exception as e:
            print(f"   ⚠️  Entity extraction fehler: {e}")
            return None

    # 6. Verarbeite Artikel
    MAX_PER_SOURCE_PER_RUN = 15  # Verhindert Bloomberg-Flood (3 Feeds × 25+ = 77)
    source_counts = {}
    new_count = 0
    for row in articles:
        headline = row[0].strip() if row[0] else ""
        source = row[1].strip() if len(row) > 1 and row[1] else "unknown"
        timestamp = row[2] if len(row) > 2 and row[2] else datetime.now().isoformat()

        if not headline:
            continue

        # Source-Limit: max N Events pro Quelle pro Run
        source_base = source.split('_')[0] if '_' in source else source  # bloomberg_markets → bloomberg
        source_counts[source_base] = source_counts.get(source_base, 0) + 1
        if source_counts[source_base] > MAX_PER_SOURCE_PER_RUN:
            continue

        # event_id
        event_id = make_event_id(headline)

        # Schnell-Check: exaktes SHA256-Duplikat
        if event_id in existing_ids:
            continue  # Exakt bekannt in letzten 24h

        # Semantischer Duplikat-Check (ersetzt primitiven SHA256-only Check)
        dup_novelty_override = None
        already_known_since = None
        if USE_SEMANTIC_DEDUP:
            try:
                is_sem_dup, orig_event_id, sim_score = semantic_is_duplicate(headline, conn)
                if is_sem_dup:
                    # >80% Ähnlichkeit → komplett droppen (echtes Duplikat)
                    if sim_score >= 0.80:
                        continue
                    dup_novelty_override = get_duplicate_novelty_score(sim_score)
                    # Hole timestamp des Originals
                    orig_ts = conn.execute(
                        "SELECT timestamp FROM overnight_events WHERE event_id = ?",
                        (orig_event_id,)
                    ).fetchone()
                    already_known_since = orig_ts[0] if orig_ts else None
            except Exception as e:
                pass  # Dedup-Fehler → trotzdem verarbeiten

        # Source Tier
        source_tier = rank_source(source)

        # Impact Rules
        strategies, impact_direction, base_novelty = match_impact_rules(headline)

        # Tier 2 Keyword Matching (ergänzend)
        tier2_strategies = match_tier2_keywords(headline, rules)
        for s in tier2_strategies:
            if s not in strategies:
                strategies.append(s)

        # Tier 3 Meta Check
        tier3_hit = match_tier3_meta(headline, rules)

        # Nur relevante Events speichern
        if not strategies and not tier3_hit:
            continue

        # Novelty Score (Basis aus Impact Rules oder 0.5 für Tier3-only)
        novelty_score = base_novelty if base_novelty > 0 else (0.5 if tier3_hit else 0.5)

        # Semantische Dedup: novelty_score deckeln wenn Duplikat
        if dup_novelty_override is not None:
            novelty_score = min(novelty_score, dup_novelty_override)

        # Entity Extraction (Haiku) — nur bei top Events
        entities_data = None
        if novelty_score == 1.0 and strategies:
            entities_data = try_extract_entities(headline, source_tier, strategies)

        if entities_data:
            # Enriche mit Haiku-Daten
            impact_direction = entities_data.get("impact_direction", impact_direction)
            haiku_strategies = entities_data.get("strategies_affected", [])
            for s in haiku_strategies:
                if s not in strategies:
                    strategies.append(s)

        # INSERT
        try:
            conn.execute("""
                INSERT OR IGNORE INTO overnight_events
                (event_id, timestamp, headline, source, source_tier, entities,
                 strategies_affected, impact_direction, novelty_score,
                 already_known_since, briefing_date, included_in_briefing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                event_id,
                str(timestamp),
                headline,
                source,
                source_tier,
                json.dumps(entities_data or {}, ensure_ascii=False),
                json.dumps(strategies, ensure_ascii=False),
                impact_direction,
                novelty_score,
                already_known_since,
                today
            ))

            # Neue Zeile? → price_at_flag setzen + magnitude_estimate
            row_id = conn.execute(
                "SELECT id FROM overnight_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row_id and strategies:
                try:
                    from feedback_loop import set_price_at_flag
                    set_price_at_flag(conn, row_id[0], strategies, str(timestamp))
                except Exception:
                    pass

                # Magnitude Estimate berechnen und speichern
                try:
                    from magnitude_estimator import estimate_magnitude
                    # event_type aus entities oder impact_direction ableiten
                    ent = entities_data or {}
                    ev_type = ent.get('event_type', impact_direction)
                    strategy_key = strategies[0] if strategies else ""
                    mag = estimate_magnitude(ev_type, strategy_key, impact_direction, "")
                    if mag.get('expected_pct_24h') is not None:
                        conn.execute(
                            "UPDATE overnight_events SET magnitude_estimate=? WHERE event_id=?",
                            (json.dumps(mag, ensure_ascii=False), event_id)
                        )
                except Exception as _mag_err:
                    pass  # Magnitude-Fehler sind nicht kritisch

            # VIX-Kontext für Magnitude-Estimate ergänzen
            try:
                from vix_context import get_vix_percentile, get_vix_term_structure
                vix_ctx = get_vix_percentile()
                # Kontext im Event speichern (falls magnitude_estimate Spalte vorhanden)
                if vix_ctx.get('n_observations', 0) > 0:
                    vix_info = {
                        'vix_percentile': vix_ctx.get('vix_percentile'),
                        'vix_label': vix_ctx.get('context_label'),
                        'vix_current': vix_ctx.get('vix_current'),
                    }
                    # In magnitude_estimate einbetten wenn vorhanden
                    mag_row = conn.execute(
                        "SELECT magnitude_estimate FROM overnight_events WHERE event_id = ?",
                        (event_id,)
                    ).fetchone()
                    if mag_row and mag_row[0]:
                        try:
                            existing_mag = json.loads(mag_row[0])
                            existing_mag['vix_context'] = vix_info
                            conn.execute(
                                "UPDATE overnight_events SET magnitude_estimate=? WHERE event_id=?",
                                (json.dumps(existing_mag, ensure_ascii=False), event_id)
                            )
                        except Exception:
                            pass
            except Exception:
                pass  # VIX-Kontext ist optional — kein Crash

            new_count += 1
            existing_ids.add(event_id)  # Prevent duplicates within same run
        except Exception as e:
            print(f"   ⚠️  Insert fehler: {e}")

    conn.commit()
    conn.close()

    print(f"✅ {new_count} neue Events in overnight_events gespeichert")

    # Trend-Detection nach Ingestion
    try:
        from trend_detector import detect_trends, log_strong_trends_to_geo_log
        trends = detect_trends(window_hours=3)
        if trends:
            strong = [t for t in trends if t["strength"] == "STRONG"]
            moderate = [t for t in trends if t["strength"] == "MODERATE"]
            print(f"📈 Trends erkannt: {len(strong)} STRONG, {len(moderate)} MODERATE")
            log_strong_trends_to_geo_log(trends)
        else:
            print("📈 Keine Trends erkannt")
    except Exception as e:
        print(f"⚠️  Trend-Detection Fehler: {e}")

    return new_count


if __name__ == "__main__":
    n = collect()
    if n == 0:
        print("KEIN_SIGNAL")
    else:
        print(f"OVERNIGHT_EVENTS: {n} neue Events")
