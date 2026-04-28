#!/usr/bin/env python3
"""
News Pipeline v2 — Alle Quellen → news_events DB
================================================
Quellen:
  - Bloomberg RSS (markets, energy, politics, technology)
  - Finnhub (Portfolio-Ticker)
  - Google News RSS (Portfolio-Themen)
  - Maritime Executive (Tanker/Geopolitik)
  - Liveuamap (Geopolitik-Regionen)

Schreibt in: data/trading.db → news_events
Feld-Mapping: headline, url, source, published_at, tickers, sector, sentiment_score
"""
import sqlite3, json, hashlib, urllib.request, xml.etree.ElementTree as ET
import sys
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
import re

import os as _os
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.news_pipeline import normalize_published_at  # noqa: E402
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'

PORTFOLIO_TICKERS = ['OXY','EQNR','NVDA','MSFT','PLTR','RIO.L','BHP.L','BAYN.DE','LHA.DE','FRO','AG','ASML.AS']
SECTOR_KEYWORDS = {
    'Energy':   ['oil','brent','crude','opec','iran','gas','energy','barrel','tanker'],
    'Defense':  ['defense','nato','weapons','rheinmetall','army','war','military'],
    'Tech':     ['nvidia','ai','semiconductor','palantir','microsoft','chip'],
    'Materials':['copper','iron','mining','rio tinto','bhp','metals'],
    'Shipping': ['tanker','maritime','shipping','freight','vessel'],
}

def fetch_url(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; NewsFetcher/1.0)'
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None

def parse_rss(xml_text, source_name):
    items = []
    try:
        root = ET.fromstring(xml_text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        # Standard RSS
        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            link  = item.findtext('link', '').strip()
            pubdate = item.findtext('pubDate', item.findtext('{http://purl.org/dc/elements/1.1/}date', '')).strip()
            if title:
                items.append({'headline': title, 'url': link, 'source': source_name, 'published_at': pubdate[:16]})
        # Atom feed
        if not items:
            for entry in root.findall('atom:entry', ns) or root.findall('{http://www.w3.org/2005/Atom}entry'):
                title_el = entry.find('{http://www.w3.org/2005/Atom}title')
                link_el  = entry.find('{http://www.w3.org/2005/Atom}link')
                date_el  = entry.find('{http://www.w3.org/2005/Atom}updated')
                if title_el is not None:
                    items.append({
                        'headline': title_el.text or '',
                        'url': link_el.get('href', '') if link_el is not None else '',
                        'source': source_name,
                        'published_at': (date_el.text or '')[:16]
                    })
    except:
        pass
    return items

def bloomberg_rss():
    feeds = {
        'bloomberg_markets':   'https://feeds.bloomberg.com/markets/news.rss',
        'bloomberg_energy':    'https://feeds.bloomberg.com/energy/news.rss',
        'bloomberg_politics':  'https://feeds.bloomberg.com/politics/news.rss',
        'bloomberg_tech':      'https://feeds.bloomberg.com/technology/news.rss',
    }
    items = []
    for name, url in feeds.items():
        xml = fetch_url(url)
        if xml:
            items.extend(parse_rss(xml, name)[:5])
    return items

def google_news_rss(queries):
    items = []
    for q in queries:
        q_enc = urllib.request.quote(q)
        url = f'https://news.google.com/rss/search?q={q_enc}&hl=en&gl=US&ceid=US:en'
        xml = fetch_url(url)
        if xml:
            parsed = parse_rss(xml, 'google_news')[:3]
            items.extend(parsed)
    return items

def finnhub_rss(tickers):
    """Finnhub via Yahoo RSS als Fallback (kein API-Key nötig)"""
    items = []
    for ticker in tickers[:6]:  # Rate limit
        clean = ticker.replace('.DE','').replace('.AS','').replace('.L','').replace('.OL','')
        url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={clean}&region=US&lang=en-US'
        xml = fetch_url(url)
        if xml:
            parsed = parse_rss(xml, f'yahoo_{ticker}')[:2]
            items.extend(parsed)
    return items

def maritime_executive():
    xml = fetch_url('https://maritime-executive.com/rss/articles')
    if xml:
        return parse_rss(xml, 'maritime_executive')[:5]
    # Fallback: web_fetch Titel extrahieren
    html = fetch_url('https://maritime-executive.com/')
    items = []
    if html:
        titles = re.findall(r'<h[23][^>]*><a[^>]+href="([^"]+)"[^>]*>([^<]{20,120})<', html)
        for url_path, title in titles[:5]:
            full_url = url_path if url_path.startswith('http') else f'https://maritime-executive.com{url_path}'
            items.append({'headline': title.strip(), 'url': full_url, 'source': 'maritime_executive', 'published_at': date.today().isoformat()})
    return items

def liveuamap_headlines(regions=None):
    if regions is None:
        regions = ['iranpalestine', 'iran', 'russia']
    items = []
    for region in regions:
        html = fetch_url(f'https://{region}.liveuamap.com/', timeout=8)
        if not html:
            continue
        # Titel aus Event-Cards extrahieren
        titles = re.findall(r'class="[^"]*title[^"]*"[^>]*>([^<]{20,200})<', html)
        for t in titles[:3]:
            t = t.strip()
            if len(t) > 20:
                items.append({
                    'headline': t,
                    'url': f'https://{region}.liveuamap.com/',
                    'source': f'liveuamap_{region}',
                    'published_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
                })
    return items

def detect_tickers(headline):
    found = []
    h = headline.upper()
    ticker_map = {
        'OXY': ['OXY','OCCIDENTAL'], 'EQNR': ['EQUINOR','EQNR'],
        'NVDA': ['NVIDIA','NVDA'], 'PLTR': ['PALANTIR','PLTR'],
        'MSFT': ['MICROSOFT','MSFT'], 'FRO': ['FRONTLINE','FRO'],
        'LHA.DE': ['LUFTHANSA','LHA'], 'BAYN.DE': ['BAYER','BAYN'],
        'AG': ['FIRST MAJESTIC','SILVER'], 'ASML.AS': ['ASML'],
    }
    for ticker, kws in ticker_map.items():
        if any(k in h for k in kws):
            found.append(ticker)
    return found

def detect_sector(headline):
    h = headline.lower()
    for sector, kws in SECTOR_KEYWORDS.items():
        if any(k in h for k in kws):
            return sector
    return None

def simple_sentiment(headline):
    h = headline.lower()
    pos = ['rise','surge','gain','jump','beat','strong','rally','bullish','up','higher','growth']
    neg = ['fall','drop','slump','miss','weak','decline','crash','bearish','down','lower','loss','war','attack','sanction']
    score = sum(0.3 for w in pos if w in h) - sum(0.3 for w in neg if w in h)
    label = 'bullish' if score > 0.2 else 'bearish' if score < -0.2 else 'neutral'
    return round(min(max(score, -1), 1), 2), label

_STOPWORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','with',
    'by','from','as','is','was','are','were','be','been','being','have','has',
    'had','do','does','did','will','would','could','should','may','might','can',
    'this','that','these','those','it','its','they','them','their','i','you',
    'he','she','we','him','her','us','my','your','our','their','der','die','das',
    'den','dem','des','und','oder','aber','in','an','auf','zu','für','von','mit',
    'bei','ist','war','sind','waren','sein','wird','würde','könnte','sollte',
    'kann','dies','jenes','sie','er','wir','ihn','ihm','ihr','mein','dein','sein',
    "'s","says","reports","report","new","news",
}

def _normalize_for_dedup(text: str) -> set:
    """Token-Set für semantischen Dedup (lowercase, stopwords entfernt)."""
    import re as _re
    text = (text or '').lower()
    # Punctuation raus, splitten
    tokens = _re.findall(r"[a-zäöüß]{3,}", text)
    return {t for t in tokens if t not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_semantic_duplicate(db, headline: str, threshold: float = 0.7,
                              hours_back: int = 24) -> bool:
    """Phase 42b: Vergleicht headline gegen jüngste 200 News, Jaccard > threshold = dup."""
    try:
        rows = db.execute(
            "SELECT headline FROM news_events "
            "WHERE created_at >= datetime('now', '-' || ? || ' hours') "
            "ORDER BY id DESC LIMIT 200",
            (hours_back,),
        ).fetchall()
    except Exception:
        return False
    new_tokens = _normalize_for_dedup(headline)
    if len(new_tokens) < 4:
        return False  # Zu wenig Tokens für sichere Aussage
    for (existing,) in rows:
        existing_tokens = _normalize_for_dedup(existing)
        if _jaccard(new_tokens, existing_tokens) >= threshold:
            return True
    return False


def save_to_db(items):
    db = sqlite3.connect(DB)
    new_count = 0
    skipped_semantic = 0
    for item in items:
        headline = item.get('headline', '').strip()
        if not headline or len(headline) < 10:
            continue
        url = item.get('url', '')
        h = hashlib.md5((headline + url).encode()).hexdigest()[:16]
        # Duplikat-Check Layer 1: exact url-hash
        exists = db.execute('SELECT 1 FROM news_events WHERE url_hash=?', (h,)).fetchone()
        if exists:
            continue
        # Phase 42b — Layer 2: semantic dedup via token-set Jaccard
        if _is_semantic_duplicate(db, headline):
            skipped_semantic += 1
            continue
        tickers = detect_tickers(headline)
        sector = detect_sector(headline)
        sentiment, label = simple_sentiment(headline)
        relevance = 1.0 if tickers else (0.6 if sector else 0.2)
        db.execute('''INSERT INTO news_events
            (url_hash, headline, url, source, published_at, tickers, sector,
             sentiment_score, sentiment_label, relevance_score, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,datetime("now"))''',
            (h, headline, url, item['source'], normalize_published_at(item.get('published_at','')),
             json.dumps(tickers) if tickers else None, sector,
             sentiment, label, relevance))
        new_count += 1
    db.commit()
    db.close()
    return new_count

def ingest_articles(articles: list, source_key: str) -> dict:
    """Konvertiert extra_news-Format zu news_events-Format und speichert in DB."""
    items = []
    for a in articles:
        items.append({
            'headline':     a.get('title', ''),
            'url':          a.get('url', ''),
            'source':       source_key,
            'published_at': a.get('date', '')[:16],
        })
    new = save_to_db(items)
    return {'inserted': new, 'total': len(items)}


def run(verbose=True):
    all_items = []
    sources = [
        ('Bloomberg RSS',     bloomberg_rss),
        ('Google News',       lambda: google_news_rss(['Iran oil Brent', 'Nvidia AI chips', 'Equinor oil Norway', 'copper mining', 'Palantir defense', 'OPEC Saudi Arabia', 'Federal Reserve rate', 'Trump tariff China'])),
        ('Yahoo/Finnhub',     lambda: finnhub_rss(['OXY','EQNR','NVDA','PLTR','FRO'])),
        # Maritime Executive entfernt (Phase 42b: alle URLs 404)
        ('Liveuamap',         lambda: liveuamap_headlines(['iran', 'israelpalestine', 'russia'])),
    ]
    for name, fn in sources:
        try:
            items = fn()
            all_items.extend(items)
            if verbose: print(f'  {name:25} {len(items):2} Items')
        except Exception as e:
            if verbose: print(f'  {name:25} FEHLER: {e}')

    new = save_to_db(all_items)
    if verbose: print(f'\n  Gesamt: {len(all_items)} Items, {new} neu in DB gespeichert')

    # Extra Sources (AP, CNBC, BBC, Al Jazeera, etc.)
    try:
        from news_fetcher import extra_news
        total = {'inserted': 0}
        extra_sources = ['ap_topnews', 'ap_business', 'ap_world', 'cnbc_top',
                         'bbc_business', 'aljazeera', 'marketwatch']
        for source_key in extra_sources:
            articles = extra_news(sources=[source_key], n=8)
            result = ingest_articles(articles, source_key)
            total['inserted'] += result['inserted']
        if verbose: print(f'  {"Extra Sources (AP/CNBC/BBC/AlJ/MW)":25} {total["inserted"]} neu')

        # International (Handelsblatt, Nikkei Asia, FT)
        intl_total = {'inserted': 0}
        intl_sources = ['handelsblatt', 'nikkei_asia', 'ft_markets']
        for source_key in intl_sources:
            articles = extra_news(sources=[source_key], n=5)
            result = ingest_articles(articles, source_key)
            intl_total['inserted'] += result['inserted']
        if verbose: print(f'  {"International (HB/Nikkei/FT)":25} {intl_total["inserted"]} neu')

        # Phase 42b — Energy/Commodities
        energy_sources = ['oilprice', 'rigzone', 'kitco_metals', 'mining_com']
        e_total = {'inserted': 0}
        for source_key in energy_sources:
            articles = extra_news(sources=[source_key], n=6, max_age_hours=12)
            e_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Energy/Commodities":25} {e_total["inserted"]} neu')

        # Phase 42b — Geopolitik/Breaking
        geo_sources = ['reuters_world', 'bbc_business', 'cnbc_world', 'cnbc_economy', 'cnbc_finance']
        g_total = {'inserted': 0}
        for source_key in geo_sources:
            articles = extra_news(sources=[source_key], n=8, max_age_hours=8)
            g_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Geopolitik/Breaking":25} {g_total["inserted"]} neu')

        # Phase 42b — Central Banks
        cb_sources = ['fed_press', 'ecb_news', 'imf_news']
        c_total = {'inserted': 0}
        for source_key in cb_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=24)
            c_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Central Banks (Fed/ECB/IMF)":25} {c_total["inserted"]} neu')

        # Phase 42b — Tech / Crypto
        tech_sources = ['techcrunch', 'theverge', 'arstechnica', 'coindesk']
        t_total = {'inserted': 0}
        for source_key in tech_sources:
            articles = extra_news(sources=[source_key], n=5, max_age_hours=8)
            t_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Tech/Crypto":25} {t_total["inserted"]} neu')

        # Phase 42b — Asia broader
        asia_sources = ['scmp_business', 'reuters_china']
        a_total = {'inserted': 0}
        for source_key in asia_sources:
            articles = extra_news(sources=[source_key], n=5, max_age_hours=12)
            a_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Asia (SCMP/Reuters CN)":25} {a_total["inserted"]} neu')

        # Phase 42b — Defense / Military
        def_sources = ['defense_news', 'janes']
        d_total = {'inserted': 0}
        for source_key in def_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=24)
            d_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Defense (DefNews/Janes)":25} {d_total["inserted"]} neu')

        # Phase 42b — German extra
        de_sources = ['spiegel_wirt', 'tagesschau_wt', 'manager_mag']
        de_total = {'inserted': 0}
        for source_key in de_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=12)
            de_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"German (Spiegel/TS/Manager)":25} {de_total["inserted"]} neu')

        # ╔════════════════════════════════════════════════════════════════════╗
        # ║ Phase 42b — RESEARCHED ADDITIONS                                  ║
        # ╚════════════════════════════════════════════════════════════════════╝

        # Mainstream Finance
        mf_sources = ['nasdaq_markets','benzinga','yahoo_finance','seeking_alpha',
                       'reuters_business','reuters_top','forbes_business','fox_business',
                       'guardian_business','wapo_business','nbcnews_business']
        mf_total = {'inserted': 0}
        for source_key in mf_sources:
            articles = extra_news(sources=[source_key], n=6, max_age_hours=8)
            mf_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Mainstream-Finance (11)":25} {mf_total["inserted"]} neu')

        # Alt-Finance / Contrarian
        ac_sources = ['zerohedge','naked_capitalism','moneyweek','wolfstreet','mish_talk']
        ac_total = {'inserted': 0}
        for source_key in ac_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=12)
            ac_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Alt-Finance/Contrarian":25} {ac_total["inserted"]} neu')

        # Energy zusätzlich (Phase 42b: iea_news/energyvoice entfernt — 403)
        en_sources = ['naturalgasintel','worldoil']
        en_total = {'inserted': 0}
        for source_key in en_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=24)
            en_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Energy zusätzl. (IEA+)":25} {en_total["inserted"]} neu')

        # SEC EDGAR — kritisch für 8-K Material Events
        sec_sources = ['sec_8k','sec_form4']
        sec_total = {'inserted': 0}
        for source_key in sec_sources:
            articles = extra_news(sources=[source_key], n=10, max_age_hours=4)
            sec_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"SEC EDGAR (8-K + Form4)":25} {sec_total["inserted"]} neu')

        # Central Banks zusätzlich
        cb2_sources = ['boe_news','boj_news','snb_news']
        cb2_total = {'inserted': 0}
        for source_key in cb2_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=24)
            cb2_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Central Banks zusätzl.":25} {cb2_total["inserted"]} neu')

        # Crypto zusätzlich
        cr_sources = ['cointelegraph','decrypt','the_block']
        cr_total = {'inserted': 0}
        for source_key in cr_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=8)
            cr_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Crypto zusätzl.":25} {cr_total["inserted"]} neu')

        # Politik / Policy
        pol_sources = ['politico','foreign_policy','cfr_news','thehill','axios_business']
        pol_total = {'inserted': 0}
        for source_key in pol_sources:
            articles = extra_news(sources=[source_key], n=5, max_age_hours=12)
            pol_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Politik/Policy (5)":25} {pol_total["inserted"]} neu')

        # Russia / Ukraine — entfernt (Phase 42b: rferl 11-byte empty, kyiv 404)
        # Ersatz: Liveuamap (iran/israel/russia) bereits in Hauptpipeline, plus
        # Google-News query 'OPEC Saudi Arabia' schon dazu

        # Emerging Markets
        em_sources = ['economic_times','livemint']
        em_total = {'inserted': 0}
        for source_key in em_sources:
            articles = extra_news(sources=[source_key], n=4, max_age_hours=12)
            em_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"India/EM":25} {em_total["inserted"]} neu')

        # Auto / EV
        auto_sources = ['electrek','autocar']
        auto_total = {'inserted': 0}
        for source_key in auto_sources:
            articles = extra_news(sources=[source_key], n=3, max_age_hours=24)
            auto_total['inserted'] += ingest_articles(articles, source_key)['inserted']
        if verbose: print(f'  {"Auto/EV":25} {auto_total["inserted"]} neu')
    except Exception as e:
        if verbose: print(f'  Extra Sources FEHLER: {e}')

    # Alte News löschen (>14 Tage)
    db = sqlite3.connect(DB)
    deleted = db.execute("DELETE FROM news_events WHERE created_at < datetime('now', '-14 days')").rowcount
    db.commit()
    db.close()
    if deleted and verbose: print(f'  {deleted} alte Einträge gelöscht')

    return new

if __name__ == '__main__':
    print(f'News Pipeline v2 — {datetime.now(_BERLIN).strftime("%Y-%m-%d %H:%M")}')
    run()
