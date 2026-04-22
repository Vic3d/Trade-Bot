#!/usr/bin/env python3
"""
News Pipeline — Dedupliziert, Ticker-getagged, DB-gespeichert
=============================================================
Ersetzt JSON-basiertes Caching durch SQLite news_events Tabelle.
Baut auf news_fetcher.py auf, fügt Deduplikation + Ticker-Tagging hinzu.

TRA-5 | Sprint 1 | TradeMind Bauplan
"""

import hashlib, json, sqlite3, re
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import sys

# ─── Freshness-Konstante ─────────────────────────────────────────────────────
# Artikel älter als X Stunden werden beim Ingest NICHT in die DB übernommen.
# In volatilen Marktphasen (Iran-Krieg, Flash-Crash etc.) relevant:
# alte News = falsche Signale. Kann per Env-Variable überschrieben werden.
MAX_NEWS_AGE_HOURS = int(__import__('os').getenv('MAX_NEWS_AGE_HOURS', '4'))

# news_fetcher importieren (bestehender Code)
sys.path.insert(0, str(Path(__file__).parent.parent))
import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))

from news_fetcher import (
    bloomberg, google_news, finnhub_company as finnhub_company_news, polygon_company as polygon_news
)

DB_PATH = WS / 'data/trading.db'

# ─── Ticker-Alias Map ─────────────────────────────────────────────────
TICKER_ALIASES = {
    # Company names → Ticker
    'nvidia': 'NVDA', 'nvda': 'NVDA',
    'microsoft': 'MSFT', 'msft': 'MSFT',
    'palantir': 'PLTR', 'pltr': 'PLTR',
    'equinor': 'EQNR.OL', 'eqnr': 'EQNR.OL',
    'bayer': 'BAYN.DE', 'bayn': 'BAYN.DE',
    'rheinmetall': 'RHM.DE', 'rhm': 'RHM.DE',
    'rio tinto': 'RIO.L', 'rio': 'RIO.L',
    'asml': 'ASML.AS',
    'novo nordisk': 'NOVO-B.CO', 'novo': 'NOVO-B.CO',
    'totalenergies': 'TTE.PA', 'total': 'TTE.PA',
    'thales': 'HO.PA',
    'glencore': 'GLEN.L',
    'first majestic': 'AG', 'majestic silver': 'AG',
    'occidental': 'OXY', 'oxy': 'OXY',
    'frontline': 'FRO', 'fro': 'FRO',
    'mosaic': 'MOS', 'mos': 'MOS',
    # Sektor-Keywords → Sektor-Tag
    'opec': '_SECTOR:OIL', 'iran': '_SECTOR:OIL', 'hormuz': '_SECTOR:OIL',
    'brent': '_SECTOR:OIL', 'crude oil': '_SECTOR:OIL',
    'nato': '_SECTOR:DEFENSE', 'defense': '_SECTOR:DEFENSE', 'rüstung': '_SECTOR:DEFENSE',
    'gold': '_SECTOR:PRECIOUS', 'silver': '_SECTOR:PRECIOUS', 'silber': '_SECTOR:PRECIOUS',
    'copper': '_SECTOR:COPPER', 'kupfer': '_SECTOR:COPPER',
    'fed': '_SECTOR:MACRO', 'federal reserve': '_SECTOR:MACRO', 'zins': '_SECTOR:MACRO',
}


def url_hash(url):
    """SHA256 Hash der URL für Deduplikation."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def normalize_published_at(published_str) -> str | None:
    """
    Normalisiert ein Datum-String → ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SS+00:00`).
    Garantiert dass SQLite-Datums-Funktionen wie date('now', '-7 days') funktionieren.
    Akzeptiert: RFC 2822 ("Wed, 22 Apr 2026 14:49:00 +0000"), ISO 8601, YYYY-MM-DD.
    Bei Parse-Fehler → aktuelle UTC-Zeit als Fallback (lieber jetzt als NULL).
    """
    if published_str:
        s = str(published_str).strip()
        # RFC 2822
        try:
            dt = parsedate_to_datetime(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        # ISO 8601
        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        # Date only YYYY-MM-DD
        try:
            dt = datetime.strptime(s[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
    # Fallback
    return datetime.now(timezone.utc).isoformat()


def parse_article_age_hours(published_str) -> float | None:
    """
    Parst ein Datum-String und gibt das Alter in Stunden zurück.
    Unterstützt: RFC 2822 (RSS pubDate), ISO 8601, YYYY-MM-DD.
    Gibt None zurück wenn das Datum nicht parsebar ist.
    """
    if not published_str:
        return None
    try:
        # RFC 2822 (RSS standard): "Sun, 05 Apr 2026 10:00:00 +0000"
        dt = parsedate_to_datetime(str(published_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return round(age, 2)
    except Exception:
        pass
    try:
        # ISO 8601: "2026-04-05T10:00:00Z" oder "2026-04-05T10:00:00+00:00"
        s = str(published_str).replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return round(age, 2)
    except Exception:
        pass
    try:
        # Nur Datum: "2026-04-05" → Mitternacht UTC
        dt = datetime.strptime(str(published_str)[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return round(age, 2)
    except Exception:
        return None


def headline_similar(headline, existing_headlines, threshold=0.80):
    """Prüft ob eine ähnliche Headline schon existiert."""
    hl = headline.lower().strip()
    for existing in existing_headlines:
        if SequenceMatcher(None, hl, existing.lower()).ratio() > threshold:
            return True
    return False


def extract_tickers(text):
    """Extrahiert Ticker und Sektoren aus Text."""
    tickers = set()
    sectors = set()
    text_lower = text.lower()
    
    for keyword, ticker in TICKER_ALIASES.items():
        if keyword in text_lower:
            if ticker.startswith('_SECTOR:'):
                sectors.add(ticker.replace('_SECTOR:', ''))
            else:
                tickers.add(ticker)
    
    # Direkte Ticker-Matches (Großbuchstaben, 2-5 Zeichen)
    for match in re.findall(r'\b([A-Z]{2,5})\b', text):
        if match in ('NVDA', 'MSFT', 'PLTR', 'EQNR', 'ASML', 'OXY', 'FRO', 'MOS', 'KTOS'):
            tickers.add(match)
    
    return list(tickers), list(sectors)


def simple_sentiment(headline):
    """
    Sentiment-Score mit Magnitude-Gewichtung (-1 bis +1).
    
    3 Stärke-Level:
      Strong (±0.5): vows, strikes, threatens, seizes, collapses, bans
      Medium (±0.3): rises, gains, beats, falls, warns, cuts
      Weak   (±0.1): hints, suggests, considers, slightly
    
    Magnitude verhindert False Positives: "Ölpreis steigt leicht" ≠ "Iran schließt Hormuz"
    """
    hl = headline.lower()
    
    # Strong bullish (0.5 Punkte) — klare, unmittelbare positive Wirkung
    strong_bullish = [
        'vows to', 'sanctions lifted', 'ceasefire', 'deal signed', 'acquisition',
        'beats estimates', 'record earnings', 'buyback', 'dividend increase',
        'nato expands', 'breakthrough', 'major contract', 'massive deal',
        'surge', 'soar', 'skyrocket', 'explode higher', 'rally hard',
        'hormuz opens', 'oil flows', 'production restored',
    ]
    # Medium bullish (0.3 Punkte)
    medium_bullish = [
        'rise', 'gain', 'rally', 'beat', 'boost', 'increase', 'grow',
        'positive', 'upgrade', 'strong', 'above forecast', 'exceeds',
        'steigt', 'anstieg', 'rallye', 'gewinn', 'rekord', 'zuwachs',
    ]
    # Weak bullish (0.1 Punkte)
    weak_bullish = [
        'hints', 'considers', 'slightly higher', 'modest gain', 'edges up',
        'leicht gestiegen', 'wenig verändert',
    ]
    
    # Strong bearish (-0.5 Punkte)
    strong_bearish = [
        'crash', 'collapse', 'plunge', 'seize', 'seized', 'sanctions imposed',
        'war declared', 'blockade', 'hormuz closed', 'hormuz blocked',
        'missile strike', 'invasion', 'explosion', 'attack kills', 'shutdown',
        'absturz', 'zusammenbruch', 'blockade', 'sanktionen verhängt', 'krieg erklärt',
        'bankruptcy', 'defaults', 'fraud', 'scandal', 'arrested',
    ]
    # Medium bearish (-0.3 Punkte)
    medium_bearish = [
        'drop', 'fall', 'decline', 'miss', 'below', 'cut', 'reduce', 'warn',
        'fear', 'crisis', 'risk', 'concern', 'tension', 'uncertainty',
        'fällt', 'rückgang', 'krise', 'sorgen', 'abschwung', 'verlust', 'einbruch',
    ]
    # Weak bearish (-0.1 Punkte)
    weak_bearish = [
        'slightly lower', 'edges down', 'modest loss', 'cautious',
        'leicht gefallen', 'kaum verändert',
    ]
    
    score = 0.0
    for phrase in strong_bullish:
        if phrase in hl: score += 0.5
    for phrase in medium_bullish:
        if phrase in hl: score += 0.3
    for phrase in weak_bullish:
        if phrase in hl: score += 0.1
    for phrase in strong_bearish:
        if phrase in hl: score -= 0.5
    for phrase in medium_bearish:
        if phrase in hl: score -= 0.3
    for phrase in weak_bearish:
        if phrase in hl: score -= 0.1
    
    return max(-1.0, min(1.0, round(score, 2)))


def ingest_articles(articles, source_name='unknown', max_age_hours=None):
    """
    Speichert Artikel in news_events mit Deduplikation + Freshness-Check.
    
    max_age_hours: Maximales Alter in Stunden (Standard: MAX_NEWS_AGE_HOURS=4).
                   Artikel die älter sind werden übersprungen.
                   None = Env-Default nutzen.
    """
    if max_age_hours is None:
        max_age_hours = MAX_NEWS_AGE_HOURS

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # Existierende Headlines der letzten 48h laden für Similarity-Check
    existing = c.execute("""
        SELECT headline FROM news_events 
        WHERE created_at > datetime('now', '-48 hours')
    """).fetchall()
    existing_headlines = [r[0] for r in existing]
    
    inserted = 0
    skipped_url = 0
    skipped_similar = 0
    skipped_stale = 0
    
    for article in articles:
        headline = article.get('title', '').strip()
        url = article.get('url', article.get('link', ''))
        published = article.get('published', article.get('date', article.get('datetime', '')))
        
        if not headline:
            continue

        # Freshness-Check: Artikel älter als max_age_hours → überspringen
        age_h = parse_article_age_hours(published)
        if age_h is not None and age_h > max_age_hours:
            skipped_stale += 1
            continue
        # Kein Datum vorhanden: trotzdem aufnehmen (lieber false positive als miss)
        
        # Dedup 1: URL-Hash
        uhash = url_hash(url) if url else url_hash(headline)
        existing_url = c.execute("SELECT id FROM news_events WHERE url_hash = ?", (uhash,)).fetchone()
        if existing_url:
            skipped_url += 1
            continue
        
        # Dedup 2: Headline-Similarity
        if headline_similar(headline, existing_headlines):
            skipped_similar += 1
            continue
        
        # Ticker-Tagging
        tickers, sectors = extract_tickers(headline)
        
        # Sentiment
        sentiment = simple_sentiment(headline)
        sentiment_label = 'bullish' if sentiment > 0.1 else ('bearish' if sentiment < -0.1 else 'neutral')
        
        try:
            c.execute("""
                INSERT INTO news_events (url_hash, headline, source, published_at, tickers, sector, 
                                        sentiment_score, sentiment_label, relevance_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uhash, headline, source_name, normalize_published_at(published),
                json.dumps(tickers) if tickers else None,
                json.dumps(sectors) if sectors else None,
                sentiment, sentiment_label,
                1.0 if tickers else (0.5 if sectors else 0.2)
            ))
            inserted += 1
            existing_headlines.append(headline)
        except Exception as e:
            pass
    
    conn.commit()
    conn.close()
    
    return {'inserted': inserted, 'skipped_url': skipped_url, 'skipped_similar': skipped_similar, 'skipped_stale': skipped_stale}


def run_full_pipeline():
    """Führt komplette News-Pipeline aus: alle Quellen → Dedup → DB."""
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] News Pipeline läuft...")
    
    total = {'inserted': 0, 'skipped_url': 0, 'skipped_similar': 0, 'skipped_stale': 0}
    
    # Bloomberg RSS
    for cat in ['markets', 'energy', 'technology', 'politics']:
        articles = bloomberg(categories=[cat], n=10)
        result = ingest_articles(articles, f'bloomberg_{cat}')
        for k in total: total[k] += result[k]
        print(f"  Bloomberg/{cat}: +{result['inserted']} (skip: {result['skipped_url']} url, {result['skipped_similar']} similar)")
    
    # Google News (Portfolio-relevante Queries)
    for query in ['Ölpreis OPEC Iran', 'Nvidia NVDA', 'Palantir PLTR', 'Gold Silber Aktien',
                   'NATO Rüstung Europa', 'Federal Reserve Zinsen']:
        articles = google_news(query, n=5)
        result = ingest_articles(articles, 'google_news')
        for k in total: total[k] += result[k]
    print(f"  Google News: +{total['inserted']} gesamt")
    
    # Finnhub (Company News für aktive Positionen)
    for ticker in ['EQNR', 'PLTR', 'OXY']:
        articles = finnhub_company_news(ticker, days_back=2, n=5)
        result = ingest_articles(articles, f'finnhub_{ticker}')
        for k in total: total[k] += result[k]
    
    # Stats
    conn = sqlite3.connect(str(DB_PATH))
    total_events = conn.execute("SELECT COUNT(*) FROM news_events").fetchone()[0]
    today_events = conn.execute("SELECT COUNT(*) FROM news_events WHERE created_at > date('now')").fetchone()[0]
    conn.close()
    
    print(f"\n  ═══ Pipeline komplett ═══")
    print(f"  Neu: {total['inserted']} | Skip URL: {total['skipped_url']} | Skip Similar: {total['skipped_similar']} | Skip Stale (>{MAX_NEWS_AGE_HOURS}h): {total.get('skipped_stale', 0)}")
    print(f"  DB gesamt: {total_events} Events | Heute: {today_events}")
    
    return total


if __name__ == '__main__':
    run_full_pipeline()
