"""
news_fetcher.py — Zentraler News-Aggregator für Albert
Quellen: Bloomberg RSS, Finnhub, Polygon, Google News RSS
Verwendung: exec('open(str(WS / 'scripts/news_fetcher.py')).read()')
oder: exec(open(str(WS / 'scripts/news_fetcher.py')).read())
"""
import urllib.request, json, xml.etree.ElementTree as ET, urllib.parse, os, time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from pathlib import Path
import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


def _age_hours(date_str) -> float | None:
    """Alter eines Datums-Strings in Stunden. None wenn nicht parsebar."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return None

POLYGON  = os.getenv('POLYGON_KEY',  'UratMpPH0sxlZeDYcSaiXsK_g6C1_7ml')
FINNHUB  = os.getenv('FINNHUB_KEY',  'd6o6lm1r01qu09ciaj3gd6o6lm1r01qu09ciaj40')

def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        return None

# ── Bloomberg RSS ──────────────────────────────────────────────────────────────
BLOOMBERG_FEEDS = {
    'markets':    'https://feeds.bloomberg.com/markets/news.rss',
    'energy':     'https://feeds.bloomberg.com/energy/news.rss',
    'technology': 'https://feeds.bloomberg.com/technology/news.rss',
    'politics':   'https://feeds.bloomberg.com/politics/news.rss',
}

# ── Reuters RSS ────────────────────────────────────────────────────────────────
REUTERS_FEEDS = {
    'markets':    'https://feeds.reuters.com/markets/',
    'energy':     'https://feeds.reuters.com/energy/',
    'mining':     'https://feeds.reuters.com/business/mining/',
    'metals':     'https://feeds.reuters.com/metals/',
}

def bloomberg(categories=None, n=3, max_age_hours=6):
    """Fetch Bloomberg RSS. Filtert Artikel älter als max_age_hours."""
    if categories is None:
        categories = ['markets', 'energy']
    results = []
    for cat in categories:
        url = BLOOMBERG_FEEDS.get(cat)
        if not url: continue
        raw = _get(url)
        if not raw: continue
        try:
            root = ET.fromstring(raw)
            count = 0
            for item in root.findall('.//item'):
                if count >= n: break
                title = item.findtext('title', '')
                pub   = item.findtext('pubDate', '')
                age   = _age_hours(pub)
                if age is not None and age > max_age_hours:
                    continue  # zu alt
                results.append({'source': f'Bloomberg/{cat}', 'title': title, 'date': pub[:22]})
                count += 1
        except: pass
    return results

def reuters(categories=None, n=3, max_age_hours=6):
    """Fetch Reuters RSS. Filtert Artikel älter als max_age_hours."""
    if categories is None:
        categories = ['markets', 'energy']
    results = []
    for cat in categories:
        url = REUTERS_FEEDS.get(cat)
        if not url: continue
        raw = _get(url)
        if not raw: continue
        try:
            root = ET.fromstring(raw)
            count = 0
            for item in root.findall('.//item'):
                if count >= n: break
                title = item.findtext('title', '')
                pub   = item.findtext('pubDate', '')
                age   = _age_hours(pub)
                if age is not None and age > max_age_hours:
                    continue  # zu alt
                results.append({'source': f'Reuters/{cat}', 'title': title, 'date': pub[:22]})
                count += 1
        except: pass
    return results

# ── Charttechnik: Umkehrkerze-Detektor ────────────────────────────────────────
def detect_reversal_candle(ticker, interval_minutes=5, lookback=20):
    """
    Erkennt bullische Umkehrkerzen (Hammer, Engulfing, Morning Star etc.)
    Gibt (pattern_name, confidence) oder (None, 0) zurück
    """
    import json, urllib.request
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval_minutes}m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        candles = data['chart']['result'][0]['indicators']['quote'][0]
        opens = candles.get('open', [])
        closes = candles.get('close', [])
        highs = candles.get('high', [])
        lows = candles.get('low', [])
        
        # Letzten lookback Kerzen filtern (nur gültige)
        valid_candles = []
        for i in range(len(opens)):
            if all(v is not None for v in [opens[i], closes[i], highs[i], lows[i]]):
                valid_candles.append((opens[i], closes[i], highs[i], lows[i]))
        valid_candles = valid_candles[-lookback:]
        
        if len(valid_candles) < 2:
            return None, 0
        
        # Letzter Kerze
        o, c, h, l = valid_candles[-1]
        body = abs(c - o)
        wick_lower = min(o, c) - l
        wick_upper = h - max(o, c)
        range_total = h - l
        
        if range_total == 0:
            return None, 0
        
        # Pattern-Erkennung
        # 1. HAMMER: kleiner Body, großer unterer Docht, wenig oben
        if wick_lower > body * 2 and wick_upper < body:
            return 'HAMMER', 0.85
        
        # 2. INVERTED HAMMER: kleiner Body, großer oberer Docht
        if wick_upper > body * 2 and wick_lower < body:
            return 'INVERTED_HAMMER', 0.70
        
        # 3. BULLISH ENGULFING: aktuelle Kerze schließt über vorherige auf, öffnet unter
        if len(valid_candles) >= 2:
            o_prev, c_prev, _, _ = valid_candles[-2]
            if c > c_prev and o < o_prev and c > o:
                return 'BULLISH_ENGULFING', 0.80
        
        # 4. MORNING STAR: 3-Kerzen-Pattern
        if len(valid_candles) >= 3:
            o1, c1, _, l1 = valid_candles[-3]
            o2, c2, _, l2 = valid_candles[-2]
            o3, c3, _, _ = valid_candles[-1]
            if c1 > o1 and c2 < max(o1, c1) and l2 < l1 and c3 > c2:
                return 'MORNING_STAR', 0.75
        
        return None, 0
    except:
        return None, 0

# ── Finnhub ────────────────────────────────────────────────────────────────────
def finnhub_company(symbol, days_back=2, n=3):
    """Company news from Finnhub."""
    from_dt = time.strftime('%Y-%m-%d', time.gmtime(time.time() - days_back*86400))
    to_dt   = time.strftime('%Y-%m-%d', time.gmtime())
    url = f'https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_dt}&to={to_dt}&token={FINNHUB}'
    raw = _get(url)
    if not raw: return []
    try:
        data = json.loads(raw)
        return [{'source': a.get('source','Finnhub'), 'title': a.get('headline',''), 'date': time.strftime('%Y-%m-%d', time.gmtime(a.get('datetime',0)))} for a in data[:n]]
    except: return []

def finnhub_market(keywords=None, n=5):
    """
    General market news from Finnhub.
    keywords=None → ALLE News (ungefiltert, für Firehose-Ansatz).
    keywords=[...] → nur Headlines die mindestens ein Keyword enthalten.
    """
    url = f'https://finnhub.io/api/v1/news?category=general&token={FINNHUB}'
    raw = _get(url)
    if not raw: return []
    try:
        data = json.loads(raw)
        results = []
        for a in data:
            if keywords is not None:
                text = (a.get('headline','') + ' ' + a.get('summary','')).lower()
                if not any(k in text for k in keywords):
                    continue
            results.append({
                'source': a.get('source','Finnhub'),
                'title': a.get('headline',''),
                'date': '',
                'url': a.get('url', ''),
            })
            if len(results) >= n:
                break
        return results
    except: return []

# ── Polygon ────────────────────────────────────────────────────────────────────
def polygon_company(ticker, n=3):
    """Company news from Polygon.io."""
    url = f'https://api.polygon.io/v2/reference/news?ticker={ticker}&limit={n}&order=desc&sort=published_utc&apiKey={POLYGON}'
    raw = _get(url)
    if not raw: return []
    try:
        data = json.loads(raw)
        return [{'source': a.get('publisher',{}).get('name','Polygon'), 'title': a.get('title',''), 'date': a.get('published_utc','')[:10]} for a in data.get('results',[])]
    except: return []

# ── Google News RSS ────────────────────────────────────────────────────────────
def google_news(query, lang='de', n=3, max_age_hours=6):
    """Google News RSS — filtert Artikel älter als max_age_hours."""
    q = urllib.parse.quote(query)
    url = f'https://news.google.com/rss/search?q={q}&hl={lang}&gl=DE&ceid=DE:{lang}'
    raw = _get(url)
    if not raw: return []
    try:
        root = ET.fromstring(raw)
        results = []
        for item in root.findall('.//item'):
            if len(results) >= n: break
            pub = item.findtext('pubDate', '')
            age = _age_hours(pub)
            if age is not None and age > max_age_hours:
                continue  # zu alt
            results.append({
                'source': item.findtext('source', 'Google'),
                'title':  item.findtext('title', ''),
                'date':   pub[:16],
            })
        return results
    except: return []

# ── Kostenlose RSS-Feeds (kein API-Key nötig) ────────────────────────────────
# Alle komplett gratis, keine Registrierung, keine Limits
FREE_RSS_FEEDS = {
    # Englisch — Nachrichten & Geopolitik
    'AP_Top':         'https://feeds.apnews.com/rss/apf-topnews',
    'AP_World':       'https://feeds.apnews.com/rss/apf-intlnews',
    'AP_Politics':    'https://feeds.apnews.com/rss/apf-politics',
    'BBC_Top':        'http://feeds.bbci.co.uk/news/rss.xml',
    'BBC_World':      'http://feeds.bbci.co.uk/news/world/rss.xml',
    'BBC_Business':   'http://feeds.bbci.co.uk/news/business/rss.xml',
    'AlJazeera':      'https://www.aljazeera.com/xml/rss/all.xml',
    'CNBC_World':     'https://www.cnbc.com/id/100003114/device/rss/rss.html',
    'CNBC_Finance':   'https://www.cnbc.com/id/10000664/device/rss/rss.html',
    'Guardian_World': 'https://www.theguardian.com/world/rss',
    'Guardian_Biz':   'https://www.theguardian.com/business/rss',
    'NPR_World':      'https://feeds.npr.org/1004/rss.xml',
    # Deutsch — für DE-Markt Signale
    'Spiegel':        'https://www.spiegel.de/schlagzeilen/tops/index.rss',
    'Tagesschau':     'https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml',
    'Zeit_Politik':   'https://newsfeed.zeit.de/politik/index',
    # Finanz-spezifisch
    'MarketWatch':    'https://feeds.marketwatch.com/marketwatch/topstories/',
    'Seeking_Alpha':  'https://seekingalpha.com/market_currents.xml',
    'Yahoo_Finance':  'https://finance.yahoo.com/news/rssindex',
}

def free_rss(feeds=None, n_per_feed=8, max_age_hours=12):
    """
    Holt Nachrichten aus kostenlosen RSS-Feeds — kein API-Key benötigt.
    feeds=None → alle FREE_RSS_FEEDS nutzen.
    Gibt alle Artikel zurück, KEINE Keyword-Vorfilterung.
    """
    if feeds is None:
        feeds = FREE_RSS_FEEDS
    results = []
    for name, url in feeds.items():
        raw = _get(url, timeout=8)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
            count = 0
            for item in root.findall('.//item'):
                if count >= n_per_feed:
                    break
                title = item.findtext('title', '').strip()
                if not title:
                    continue
                pub = item.findtext('pubDate', '')
                age = _age_hours(pub)
                if age is not None and age > max_age_hours:
                    continue
                link = item.findtext('link', '')
                results.append({
                    'source': name,
                    'title': title,
                    'date': pub[:16] if pub else '',
                    'url': link,
                })
                count += 1
        except Exception:
            continue
    return results


# ── Google News Top Headlines (kein Keyword nötig) ────────────────────────────
def google_news_top(lang='en', geo='US', n=20, max_age_hours=12):
    """
    Google News RSS Top-Stories — ALLE Schlagzeilen, ungefiltert.
    Das ist der 'Firehose-Light' Ansatz: Erst alles holen, dann LLM filtert.
    """
    url = f'https://news.google.com/rss?hl={lang}&gl={geo}&ceid={geo}:{lang}'
    raw = _get(url, timeout=10)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
        results = []
        for item in root.findall('.//item'):
            if len(results) >= n:
                break
            pub = item.findtext('pubDate', '')
            age = _age_hours(pub)
            if age is not None and age > max_age_hours:
                continue
            results.append({
                'source': item.findtext('source', 'Google'),
                'title': item.findtext('title', ''),
                'date': pub[:16] if pub else '',
            })
        return results
    except Exception:
        return []


# ── Kombiniert: alle Quellen für ein Ticker-Set ────────────────────────────────
def news_for_portfolio(us_tickers=None, extra_queries=None, bloomberg_cats=None):
    """
    Sammelt News für US-Tickers (Polygon+Finnhub) + Queries (Google) + Bloomberg.
    Returns: dict mit source → list of {source, title, date}
    """
    if us_tickers is None:
        us_tickers = ['NVDA', 'MSFT', 'PLTR', 'EQNR', 'RIO']
    if extra_queries is None:
        extra_queries = ['Rheinmetall Aktie', 'Bayer Aktie', 'Iran Hormuz Ölpreis']
    if bloomberg_cats is None:
        bloomberg_cats = ['markets', 'energy', 'technology']

    out = {}

    # Bloomberg (breit)
    bl = bloomberg(bloomberg_cats, n=4)
    if bl:
        out['Bloomberg'] = bl

    # Finnhub Market (gefiltert)
    fm = finnhub_market(n=6)
    if fm:
        out['Finnhub-Market'] = fm

    # Pro Ticker: Polygon + Finnhub
    for t in us_tickers:
        news = polygon_company(t, n=2) + finnhub_company(t, n=2)
        # Deduplizieren nach Titel
        seen = set()
        deduped = []
        for a in news:
            if a['title'] not in seen:
                seen.add(a['title'])
                deduped.append(a)
        if deduped:
            out[t] = deduped

    # Google News für DE-Aktien + Geopolitik
    for q in extra_queries:
        news = google_news(q, n=2)
        if news:
            out[f'Google:{q[:20]}'] = news

    return out

def format_news(news_dict, max_per_source=2):
    """Formatiert News-Dict für Discord-Ausgabe."""
    lines = []
    for source, items in news_dict.items():
        lines.append(f'**{source}:**')
        for item in items[:max_per_source]:
            date = f" ({item['date']})" if item.get('date') else ''
            lines.append(f"  · {item['title']}{date}")
    return '\n'.join(lines)

if __name__ == '__main__':
    news = news_for_portfolio()
    print(format_news(news))
