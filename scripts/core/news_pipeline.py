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
from datetime import datetime, timezone
from pathlib import Path
import sys

# news_fetcher importieren (bestehender Code)
sys.path.insert(0, str(Path(__file__).parent.parent))
from news_fetcher import (
    bloomberg, google_news, finnhub_company as finnhub_company_news, polygon_company as polygon_news
)

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')

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
    """Einfacher regelbasierter Sentiment-Score (-1 bis +1)."""
    hl = headline.lower()
    
    bullish = ['surge', 'soar', 'rally', 'gain', 'rise', 'boost', 'record', 'beat',
               'steigt', 'anstieg', 'rallye', 'gewinn', 'rekord']
    bearish = ['crash', 'plunge', 'drop', 'fall', 'decline', 'fear', 'war', 'crisis',
               'fällt', 'absturz', 'krise', 'krieg', 'einbruch', 'verlust']
    
    score = 0
    for word in bullish:
        if word in hl: score += 0.3
    for word in bearish:
        if word in hl: score -= 0.3
    
    return max(-1.0, min(1.0, round(score, 2)))


def ingest_articles(articles, source_name='unknown'):
    """Speichert Artikel in news_events mit Deduplikation."""
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
    
    for article in articles:
        headline = article.get('title', '').strip()
        url = article.get('url', article.get('link', ''))
        published = article.get('published', article.get('datetime', ''))
        
        if not headline:
            continue
        
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
                uhash, headline, source_name, published,
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
    
    return {'inserted': inserted, 'skipped_url': skipped_url, 'skipped_similar': skipped_similar}


def run_full_pipeline():
    """Führt komplette News-Pipeline aus: alle Quellen → Dedup → DB."""
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] News Pipeline läuft...")
    
    total = {'inserted': 0, 'skipped_url': 0, 'skipped_similar': 0}
    
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
    print(f"  Neu: {total['inserted']} | Skip URL: {total['skipped_url']} | Skip Similar: {total['skipped_similar']}")
    print(f"  DB gesamt: {total_events} Events | Heute: {today_events}")
    
    return total


if __name__ == '__main__':
    run_full_pipeline()
