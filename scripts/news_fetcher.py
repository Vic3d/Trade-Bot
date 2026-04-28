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
    """General market news from Finnhub, filtered by keywords."""
    if keywords is None:
        keywords = ['oil','iran','hormuz','nvidia','palantir','rheinmetall','rio tinto','bayer','equinor','silver','gold','copper']
    url = f'https://finnhub.io/api/v1/news?category=general&token={FINNHUB}'
    raw = _get(url)
    if not raw: return []
    try:
        data = json.loads(raw)
        results = []
        for a in data:
            text = (a.get('headline','') + ' ' + a.get('summary','')).lower()
            if any(k in text for k in keywords):
                results.append({'source': a.get('source','Finnhub'), 'title': a.get('headline',''), 'date': ''})
                if len(results) >= n: break
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

# ── Additional Breaking News Sources ─────────────────────────────────────────

EXTRA_FEEDS = {
    # ── Getestet & funktional auf Hetzner VPS ────────────────────────────────
    'wsj_markets':   'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',         # Wall Street Journal
    'nyt_business':  'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',  # NYT Business
    'skynews_world': 'https://feeds.skynews.com/feeds/rss/world.xml',          # Sky News World (geopolitik)
    'investing_news':'https://www.investing.com/rss/news.rss',                 # Investing.com (breit)
    'fortune':       'https://fortune.com/feed/',                               # Fortune
    'aljazeera':     'https://www.aljazeera.com/xml/rss/all.xml',              # Al Jazeera (Nahost)
    'marketwatch':   'https://feeds.content.dowjones.io/public/rss/mw_topstories',  # MarketWatch
    'handelsblatt':  'https://www.handelsblatt.com/contentexport/feed/top-themen',  # Handelsblatt (DE)
    'nikkei_asia':   'https://asia.nikkei.com/rss/feed/nar',                   # Nikkei Asia (JP/Asia)
    'ft_markets':    'https://www.ft.com/rss/home/uk',                         # Financial Times
    # ── Phase 42b — Energy / Commodities ─────────────────────────────────────
    'oilprice':      'https://oilprice.com/rss/main',                          # OilPrice.com (OPEC, crude)
    'rigzone':       'https://www.rigzone.com/news/rss/rigzone_latest.aspx',   # Oil/Gas industry
    'kitco_metals':  'https://www.kitco.com/rss/KitcoNews.xml',                # Gold/Silver/Metals
    'mining_com':    'https://www.mining.com/feed/',                           # Mining sector
    # ── Phase 42b — Geopolitik / Breaking ────────────────────────────────────
    'reuters_world': 'https://feeds.reuters.com/Reuters/worldNews',            # Reuters World
    'bbc_business':  'https://feeds.bbci.co.uk/news/business/rss.xml',         # BBC Business
    'ap_topnews':    'https://feeds.apnews.com/rss/apf-topnews',               # AP Top News
    'ap_business':   'https://feeds.apnews.com/rss/apf-business',              # AP Business
    'ap_world':      'https://feeds.apnews.com/rss/apf-worldnews',             # AP World
    'cnbc_top':      'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114',  # CNBC Top
    'cnbc_world':    'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362',  # CNBC World
    'cnbc_economy':  'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258',   # CNBC Economy
    'cnbc_finance':  'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664',   # CNBC Finance
    # ── Phase 42b — Central Banks / Macro ────────────────────────────────────
    'fed_press':     'https://www.federalreserve.gov/feeds/press_all.xml',     # Fed press releases
    'ecb_news':      'https://www.ecb.europa.eu/rss/press.html',               # ECB press
    'imf_news':      'https://www.imf.org/en/News/RSS?Language=ENG',           # IMF news
    # ── Phase 42b — Crypto/Risk-on Indicators ────────────────────────────────
    'coindesk':      'https://www.coindesk.com/arc/outboundfeeds/rss/',        # Coindesk
    # ── Phase 42b — Tech ─────────────────────────────────────────────────────
    'techcrunch':    'https://techcrunch.com/feed/',                           # TechCrunch
    'theverge':      'https://www.theverge.com/rss/index.xml',                 # The Verge
    'arstechnica':   'https://feeds.arstechnica.com/arstechnica/index',        # Ars Technica
    # ── Phase 42b — Asia broader ─────────────────────────────────────────────
    'scmp_business': 'https://www.scmp.com/rss/2/feed',                        # South China Morning Post Business
    'reuters_china': 'https://feeds.reuters.com/reuters/CNTopNews',            # Reuters China
    # ── Phase 42b — Defense / Military ───────────────────────────────────────
    'defense_news':  'https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml',  # Defense News
    'janes':         'https://www.janes.com/feeds/news',                       # Janes Defence
    # ── Phase 42b — German extra ─────────────────────────────────────────────
    'spiegel_wirt':  'https://www.spiegel.de/wirtschaft/index.rss',            # Spiegel Wirtschaft
    'tagesschau_wt': 'https://www.tagesschau.de/wirtschaft/index~rss2.xml',    # Tagesschau Wirtschaft
    'manager_mag':   'https://www.manager-magazin.de/wirtschaft/index.rss',    # Manager Magazin

    # ╔════════════════════════════════════════════════════════════════════════╗
    # ║ Phase 42b — RESEARCHED ADDITIONS (Web-Search 2026-04-28)              ║
    # ╚════════════════════════════════════════════════════════════════════════╝

    # ── Mainstream Finance ───────────────────────────────────────────────────
    'nasdaq_markets':  'https://www.nasdaq.com/feed/rssoutbound?category=Markets',
    'benzinga':        'https://feeds.benzinga.com/benzinga',
    'yahoo_finance':   'https://finance.yahoo.com/news/rssindex',
    'seeking_alpha':   'https://seekingalpha.com/feed.xml',
    'reuters_business':'https://feeds.reuters.com/reuters/businessNews',
    'reuters_top':     'https://feeds.reuters.com/reuters/topNews',
    'forbes_business': 'https://www.forbes.com/business/feed/',
    'fox_business':    'https://feeds.foxbusiness.com/foxbusiness/latest',
    'guardian_business':'https://www.theguardian.com/business/rss',
    'wapo_business':   'https://feeds.washingtonpost.com/rss/business',
    'nbcnews_business':'https://feeds.nbcnews.com/nbcnews/public/business',

    # ── Alt-Finance / Contrarian ─────────────────────────────────────────────
    'zerohedge':       'https://feeds.feedburner.com/zerohedge/feed',
    'naked_capitalism':'https://www.nakedcapitalism.com/feed',
    'moneyweek':       'https://moneyweek.com/feed/all',
    'wolfstreet':      'https://wolfstreet.com/feed/',                          # Wolf Richter
    'mish_talk':       'https://mishtalk.com/feed/',                            # Mish Shedlock

    # ── Energy / Oil specific (zusätzlich) ───────────────────────────────────
    'iea_news':        'https://www.iea.org/api/news/rss',                     # International Energy Agency
    'naturalgasintel': 'https://www.naturalgasintel.com/category/news/feed/',  # NatGas Intelligence
    'energyvoice':     'https://www.energyvoice.com/feed/',                    # Energy Voice (UK)
    'worldoil':        'https://www.worldoil.com/rss',                         # World Oil

    # ── SEC EDGAR Filings ────────────────────────────────────────────────────
    'sec_8k':          'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom',  # Material Events
    'sec_form4':       'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&output=atom',    # Insider Trades

    # ── Central Banks (zusätzlich) ───────────────────────────────────────────
    'boe_news':        'https://www.bankofengland.co.uk/rss/news',             # Bank of England
    'boj_news':        'https://www.boj.or.jp/en/rss/whatsnew.xml',            # Bank of Japan
    'snb_news':        'https://www.snb.ch/en/rss/news',                       # Swiss National Bank

    # ── Crypto (zusätzlich) ──────────────────────────────────────────────────
    'cointelegraph':   'https://cointelegraph.com/rss',
    'decrypt':         'https://decrypt.co/feed',
    'the_block':       'https://www.theblock.co/rss.xml',

    # ── Politik / Policy ─────────────────────────────────────────────────────
    'politico':        'https://rss.politico.com/politics-news.xml',
    'foreign_policy':  'https://foreignpolicy.com/feed/',                      # Foreign Policy Mag
    'cfr_news':        'https://www.cfr.org/rss-feeds/all',                    # Council on Foreign Relations

    # ── Russia / Eastern Europe ──────────────────────────────────────────────
    'rferl':           'https://www.rferl.org/api/zoqveiqyiqe',                # Radio Free Europe (Russia/EE)
    'kyiv_independent':'https://kyivindependent.com/feed/',                    # Kyiv Independent

    # ── Indien / Emerging Markets ────────────────────────────────────────────
    'economic_times':  'https://economictimes.indiatimes.com/rssfeedstopstories.cms',  # India biggest
    'livemint':        'https://www.livemint.com/rss/markets',                 # India Markets

    # ── Auto / EV / Tech-Industrie ───────────────────────────────────────────
    'electrek':        'https://electrek.co/feed/',                            # EV/Tesla
    'autocar':         'https://www.autocar.co.uk/rss',                        # UK auto industry

    # ── Trump-spezifisch / US-Politik (relevant für PS_*-Strategien) ─────────
    'thehill':         'https://thehill.com/feed/',                            # The Hill (US Politics)
    'axios_business':  'https://api.axios.com/feed/business',                  # Axios Business
}

def extra_news(sources=None, n=5, max_age_hours=4):
    """
    Fetches from additional RSS sources (AP, CNBC, BBC, Al Jazeera, etc.).
    sources: list of keys from EXTRA_FEEDS, or None for all.
    Returns list of {source, title, date}.
    """
    if sources is None:
        sources = list(EXTRA_FEEDS.keys())
    results = []
    for key in sources:
        url = EXTRA_FEEDS.get(key)
        if not url:
            continue
        raw = _get(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
            count = 0
            for item in root.findall('.//item'):
                if count >= n:
                    break
                title = item.findtext('title', '').strip()
                pub   = item.findtext('pubDate', '')
                link  = item.findtext('link', '')
                if not title:
                    continue
                age = _age_hours(pub)
                if age is not None and age > max_age_hours:
                    continue
                results.append({
                    'source': key,
                    'title':  title,
                    'date':   pub[:22],
                    'url':    link,
                })
                count += 1
        except Exception:
            pass
    return results


def breaking_news(max_age_hours=1, n=10):
    """
    Fast-path: only the quickest-updating sources for breaking news.
    AP Top, CNBC, BBC Business. max_age_hours=1 for truly fresh news.
    """
    return extra_news(
        sources=['ap_topnews', 'ap_world', 'cnbc_top', 'bbc_business'],
        n=n,
        max_age_hours=max_age_hours,
    )


if __name__ == '__main__':
    news = news_for_portfolio()
    print(format_news(news))
