#!/usr/bin/env python3
"""
news_ingestor.py — Feeds fresh Google News RSS + Bloomberg RSS into newswire.db
Läuft vor newswire_analyst.py (oder standalone)
"""
import sqlite3, urllib.request, xml.etree.ElementTree as ET
import urllib.parse, hashlib, time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path('/data/.openclaw/workspace/memory/newswire.db')

# Portfolio-relevante Suchanfragen + Ticker-Mapping
QUERIES = [
    ('Equinor Ölpreis Nordsee',   'EQNR', 1),
    ('Palantir AI Defense',        'PLTR', 3),
    ('Bayer Aktie',                'BAYN.DE', 7),
    ('Iran Hormuz Ölpreis',        'EQNR,DR0.DE', 1),
    ('Nvidia KI Chips',            'NVDA', 3),
    ('Solar Energie ETF',          'A2QQ9R', 6),
    ('Öl Tanker Rohstoffe',        'A3D42Y', 1),
    ('Cyber Security Aktie',       'A14WU5', None),
    ('Biotech Pharma',             'A2DWAW', 7),
    ('DAX VIX Volatilität',        None, None),
    ('NATO Rüstung Europa',        None, 2),
    ('Fed Zinsen Markt',           None, None),
]

# Bloomberg RSS Feeds — kein API-Key, ~30 Min Lag
# Ticker/Strategy-Mapping: None = kein direkter Ticker, wird über Keywords gematcht
BLOOMBERG_FEEDS = [
    ('https://feeds.bloomberg.com/markets/news.rss',   None,          None, 'Bloomberg Markets'),
    ('https://feeds.bloomberg.com/energy/news.rss',    'EQNR,DR0.DE', 1,   'Bloomberg Energy'),
    ('https://feeds.bloomberg.com/technology/news.rss','NVDA,PLTR',   3,   'Bloomberg Tech'),
    ('https://feeds.bloomberg.com/politics/news.rss',  None,          None, 'Bloomberg Politics'),
]

def bloomberg_rss(url, source_name, n=6):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.findall('.//item')[:n]:
            title = item.findtext('title', '')
            pub = item.findtext('pubDate', '')
            link = item.findtext('link', '') or item.findtext('guid', '')
            items.append({'title': title, 'pub': pub, 'link': link, 'source': source_name})
        return items
    except Exception:
        return []

def google_news_rss(query, n=4):
    enc = urllib.parse.quote(query)
    url = f'https://news.google.com/rss/search?q={enc}&hl=de&gl=DE&ceid=DE:de'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.findall('.//item')[:n]:
            title = item.findtext('title', '')
            pub = item.findtext('pubDate', '')
            link = item.findtext('link', '') or item.findtext('guid', '')
            source = item.find('source')
            source_name = source.text if source is not None else 'Google News'
            items.append({'title': title, 'pub': pub, 'link': link, 'source': source_name})
        return items
    except Exception as e:
        return []

def score_article(title, ticker):
    """Simple relevance score 0-10"""
    title_lower = title.lower()
    # Negative keywords
    neg = ['unrelated', 'sport', 'celebrity', 'weather']
    if any(n in title_lower for n in neg):
        return 0
    return 6  # default medium relevance

def ingest():
    conn = sqlite3.connect(str(DB_PATH))

    # Existing URLs to avoid duplicates (use headline hash)
    existing = set(row[0] for row in conn.execute('SELECT headline FROM events').fetchall())

    inserted = 0

    # --- Bloomberg RSS ---
    for feed_url, ticker, strategy_id, source_name in BLOOMBERG_FEEDS:
        articles = bloomberg_rss(feed_url, source_name)
        for art in articles:
            title = art['title'].strip()
            if not title or title in existing:
                continue
            existing.add(title)

            ts = int(time.time())
            if art['pub']:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = int(parsedate_to_datetime(art['pub']).timestamp())
                except:
                    pass

            if time.time() - ts > 48 * 3600:
                continue

            score = score_article(title, ticker or '')
            conn.execute('''
                INSERT INTO events (ts, source, ticker, strategy_id, direction, headline, score, alerted, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (ts, source_name, ticker, strategy_id, 'NEUTRAL', title, score, '{}'))
            inserted += 1

        time.sleep(0.5)

    # --- Google News RSS ---
    for query, ticker, strategy_id in QUERIES:
        articles = google_news_rss(query)
        for art in articles:
            title = art['title'].strip()
            if not title or title in existing:
                continue
            existing.add(title)

            # Parse timestamp
            ts = int(time.time())
            if art['pub']:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = int(parsedate_to_datetime(art['pub']).timestamp())
                except:
                    pass

            # Skip articles older than 48h
            if time.time() - ts > 48 * 3600:
                continue

            score = score_article(title, ticker)

            conn.execute('''
                INSERT INTO events (ts, source, ticker, strategy_id, direction, headline, score, alerted, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''', (ts, art['source'], ticker, strategy_id, 'NEUTRAL', title, score, '{}'))
            inserted += 1

        time.sleep(0.3)  # Rate limit

    conn.commit()
    conn.close()
    print(f'news_ingestor: {inserted} neue Artikel in newswire.db')
    return inserted

if __name__ == '__main__':
    n = ingest()
    if n == 0:
        print('KEIN_SIGNAL')
    else:
        print(f'ANALYSE_REQUIRED: {n} neue Artikel')
