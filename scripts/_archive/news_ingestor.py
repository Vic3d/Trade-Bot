#!/usr/bin/env python3
"""
news_ingestor.py — News-Ingestion mit semantischer Deduplication
================================================================
Liest frische News aus news_events (befüllt von news_pipeline.py),
prüft Duplikate via dedup_checker.py (>60% Ähnlichkeit in letzten 6h),
und schreibt saubere Events in overnight_events.

Dedup-Fenster: 6h (enger als der 24h-Scan in dedup_checker, weil hier
  nur echte neue Ingest-Runs berücksichtigt werden)
Threshold: 0.60 (wie in dedup_checker.DUPLICATE_THRESHOLD definiert)

Usage:
  python3 scripts/news_ingestor.py
  python3 scripts/news_ingestor.py --dry-run   (keine DB-Schreiboperationen)
"""

import sqlite3
import json
import hashlib
import sys
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'

# Dedup-Fenster für den Ingest-Run (kürzer als täglicher Scan)
DEDUP_WINDOW_HOURS = 6
DEDUP_THRESHOLD    = 0.60  # >60% Match → Duplikat


# ── Impact Rules (aus overnight_collector.py übernommen) ─────────────────────

IMPACT_RULES = [
    (["Iran", "attack", "strike", "missile"], ["ceasefire", "deal"],    ["S1"],         "bullish_oil",            0.85),
    (["Iran", "ceasefire", "deal", "peace"],  [],                        ["S1"],         "bearish_oil",            0.80),
    (["Hormuz", "blocked", "mines"],          [],                        ["S1"],         "bullish_oil",            0.90),
    (["tanker", "Tanker"],                    [],                        ["S1", "S8"],   "watchlist",              0.65),
    (["Cuba", "Kuba"],                        [],                        ["S9"],         "watchlist_S9",           0.80),
    (["Trump", "sanction"],                   [],                        ["S1", "S9"],   "geopolitical_watchlist", 0.60),
    (["NATO", "defense", "Rüstung"],          [],                        ["S2"],         "bullish_defense",        0.70),
    (["Fed", "cut", "Zinssenkung"],           [],                        ["S3"],         "bullish_tech",           0.75),
    (["silver", "Silber"],                    [],                        ["S4"],         "bullish_metals",         0.70),
    (["oil", "kerosin"],                      [],                        ["S10", "S11"], "bearish_airlines",       0.70),
]


def rank_source(source: str) -> int:
    """Source-Tier 1=Primär, 2=Finanz, 3=Andere."""
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


def match_impact_rules(headline: str) -> tuple:
    """Gibt (strategies, impact_direction, base_novelty) zurück."""
    def kw_in(kw, text):
        kl, tl = kw.lower(), text.lower()
        if len(kl) <= 3:
            return bool(re.search(r'\b' + re.escape(kl) + r'\b', tl))
        return kl in tl

    for pos_kws, neg_kws, strategies, direction, novelty in IMPACT_RULES:
        if neg_kws and any(kw_in(nk, headline) for nk in neg_kws):
            continue
        if any(kw_in(pk, headline) for pk in pos_kws):
            return strategies, direction, novelty
    return [], "neutral", 0.0


# ── Dedup-Logik ──────────────────────────────────────────────────────────────

def setup_dedup(conn):
    """Importiere und konfiguriere dedup_checker."""
    sys.path.insert(0, str(WS / 'scripts'))
    from dedup_checker import is_duplicate, get_duplicate_novelty_score
    return is_duplicate, get_duplicate_novelty_score


def log_dedup_run(conn, run_ts: str, inserted: int, skipped: int, total_checked: int):
    """Schreibt Dedup-Statistiken in entry_gate_log (kein Discord, nur DB)."""
    try:
        conn.execute("""
            INSERT INTO entry_gate_log (timestamp, ticker, strategy, gate_triggered, reason, news_headline)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            run_ts,
            "INGESTOR",
            "DEDUP",
            0,
            f"Run complete: {inserted} inserted, {skipped} duplicates filtered of {total_checked} checked",
            f"dedup_window={DEDUP_WINDOW_HOURS}h threshold={DEDUP_THRESHOLD}"
        ))
        conn.commit()
    except Exception as e:
        print(f"  ⚠️  Log-Eintrag fehlgeschlagen: {e}")


# ── Haupt-Ingest ─────────────────────────────────────────────────────────────

def ingest(dry_run: bool = False) -> dict:
    """
    Hauptfunktion: News-Ingest mit Dedup.

    Returns:
        dict mit inserted, skipped_duplicates, total_checked
    """
    run_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f"📡 news_ingestor.py — {run_ts}")

    conn = sqlite3.connect(str(DB))

    # Dedup-Modul laden
    try:
        is_duplicate, get_duplicate_novelty_score = setup_dedup(conn)
        USE_DEDUP = True
        print(f"  🧠 Dedup aktiv (Fenster: {DEDUP_WINDOW_HOURS}h, Threshold: {DEDUP_THRESHOLD:.0%})")
    except Exception as e:
        USE_DEDUP = False
        print(f"  ⚠️  Dedup nicht verfügbar: {e}")

    # News-Quelle: news_events (letzten 60 Minuten)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')

    # Adaptive column detection für news_events
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news_events)").fetchall()}
    headline_col = "headline" if "headline" in cols else "title"
    time_col = next((c for c in ["created_at", "published_at"] if c in cols), None)

    if time_col:
        articles = conn.execute(
            f"SELECT {headline_col}, source, {time_col} FROM news_events WHERE {time_col} >= ? ORDER BY {time_col} DESC",
            (cutoff,)
        ).fetchall()
    else:
        articles = conn.execute(
            f"SELECT {headline_col}, source, NULL FROM news_events ORDER BY id DESC LIMIT 100"
        ).fetchall()

    print(f"  📰 {len(articles)} Artikel aus den letzten 60min")

    # Existierende event_ids für schnellen SHA-Check
    existing_ids = set(
        r[0] for r in conn.execute(
            "SELECT event_id FROM overnight_events WHERE timestamp >= ?",
            ((datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),)
        ).fetchall()
    )

    inserted = 0
    skipped_dup = 0
    total_checked = 0

    today = datetime.now().strftime('%Y-%m-%d')

    for row in articles:
        headline = (row[0] or "").strip()
        source   = (row[1] or "unknown").strip()
        timestamp = row[2] if row[2] else run_ts

        if not headline:
            continue

        total_checked += 1
        event_id = make_event_id(headline)

        # Schritt 1: SHA-Schnellcheck (exaktes Duplikat)
        if event_id in existing_ids:
            skipped_dup += 1
            continue

        # Schritt 2: Semantischer Dedup-Check (>60% in letzten 6h)
        if USE_DEDUP:
            try:
                is_dup, orig_id, sim_score = is_duplicate(
                    headline, conn, window_hours=DEDUP_WINDOW_HOURS
                )
                if is_dup and sim_score > DEDUP_THRESHOLD:
                    skipped_dup += 1
                    # Kein DB-Eintrag, kein Discord — nur Counter
                    continue
            except Exception as e:
                pass  # Dedup-Fehler → weiter verarbeiten

        # Kein Duplikat → Impact bestimmen und eintragen
        strategies, direction, novelty = match_impact_rules(headline)
        source_tier = rank_source(source)

        # Nur relevante Events (mit Impact-Match ODER hoher Source-Tier) speichern
        if not strategies and source_tier > 2:
            continue  # Kein Match, schlechte Quelle → überspringen

        if not dry_run:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO overnight_events
                        (event_id, timestamp, headline, source, source_tier,
                         strategies_affected, impact_direction, novelty_score, briefing_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event_id,
                    timestamp,
                    headline,
                    source,
                    source_tier,
                    json.dumps(strategies),
                    direction,
                    novelty,
                    today,
                ))
                conn.commit()
                existing_ids.add(event_id)
                inserted += 1
            except Exception as e:
                print(f"  ⚠️  Insert-Fehler: {e} | {headline[:60]}")
        else:
            inserted += 1  # Dry-run: zähle trotzdem

    # Ergebnis loggen (nur in DB, kein Discord)
    if not dry_run:
        log_dedup_run(conn, run_ts, inserted, skipped_dup, total_checked)

    conn.close()

    result = {
        "inserted": inserted,
        "skipped_duplicates": skipped_dup,
        "total_checked": total_checked,
        "dedup_rate": round(skipped_dup / total_checked * 100, 1) if total_checked > 0 else 0,
    }

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"  {prefix}✅ Fertig: {inserted} neu | {skipped_dup} Duplikate gefiltert "
          f"({result['dedup_rate']}% von {total_checked})")

    return result


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("⚠️  DRY-RUN — keine DB-Schreiboperationen")
    result = ingest(dry_run=dry_run)
    sys.exit(0)
