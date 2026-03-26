#!/usr/bin/env python3
"""
news_cache.py — Zentraler News-Cache (30 Min TTL)

Mehrere Crons pro Tag brauchen News. Statt jeder einzeln fetcht,
cached dieser Service die Ergebnisse für 30 Minuten.

USAGE:
  from news_cache import get_cached_news, get_portfolio_news
  
  # Alle News (gecacht)
  articles = get_cached_news()
  
  # Portfolio-relevante News (gefiltert)
  relevant = get_portfolio_news()
  
  # CLI: python3 news_cache.py [--refresh] [--portfolio] [--json]
"""

import json, time, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

CACHE_PATH = Path("/data/.openclaw/workspace/data/news_cache.json")
CACHE_TTL_SECONDS = 30 * 60  # 30 Minuten


def _fetch_fresh_news():
    """Holt frische News aus allen Quellen."""
    articles = []
    
    try:
        # news_fetcher.py laden
        ns = {}
        exec(open(str(Path(__file__).parent / 'news_fetcher.py')).read(), ns)
        
        # Bloomberg RSS
        for cat in ['markets', 'energy', 'technology', 'politics']:
            try:
                arts = ns['bloomberg'](categories=[cat], n=5)
                for a in arts:
                    a['source'] = f'bloomberg_{cat}'
                articles += arts
            except:
                pass
        
        # Finnhub Market News
        try:
            arts = ns['finnhub_market'](n=5)
            for a in arts:
                a['source'] = 'finnhub_market'
            articles += arts
        except:
            pass
        
        # Google News — Portfolio-relevante Queries
        queries = [
            'Iran Öl Hormuz Geopolitik',
            'Nasdaq DAX Aktien Börse',
            'Rüstung Verteidigung NATO',
            'Gold Silber Rohstoffe',
            'Nvidia NVDA KI Halbleiter',
        ]
        for q in queries:
            try:
                arts = ns['google_news'](query=q, n=3)
                for a in arts:
                    a['source'] = 'google_news'
                    a['query'] = q
                articles += arts
            except:
                pass
    except Exception as e:
        print(f"⚠ News-Fetch Fehler: {e}", file=sys.stderr)
    
    return articles


def _load_cache():
    """Liest Cache wenn vorhanden und frisch."""
    if not CACHE_PATH.exists():
        return None, 0
    
    try:
        data = json.loads(CACHE_PATH.read_text())
        cached_at = data.get('cached_at', 0)
        age = time.time() - cached_at
        if age < CACHE_TTL_SECONDS:
            return data.get('articles', []), age
    except:
        pass
    return None, 0


def _save_cache(articles):
    """Speichert Cache."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'cached_at': time.time(),
        'cached_at_str': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'article_count': len(articles),
        'articles': articles,
    }
    CACHE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_cached_news(force_refresh=False):
    """
    Holt News — aus Cache wenn <30 Min alt, sonst frisch.
    Returns: list of article dicts
    """
    if not force_refresh:
        cached, age = _load_cache()
        if cached is not None:
            mins = int(age / 60)
            print(f"📰 News aus Cache ({mins} Min alt, {len(cached)} Artikel)", file=sys.stderr)
            return cached
    
    print("📰 Hole frische News...", file=sys.stderr)
    articles = _fetch_fresh_news()
    _save_cache(articles)
    print(f"📰 {len(articles)} Artikel gecacht", file=sys.stderr)
    return articles


def get_portfolio_news(tickers=None):
    """
    Portfolio-relevante News filtern.
    Wenn tickers=None, nutzt portfolio.py für aktive Tickers.
    """
    articles = get_cached_news()
    
    if tickers is None:
        try:
            from portfolio import Portfolio
            p = Portfolio()
            tickers = p.all_active_tickers()
        except:
            tickers = []
    
    # Ticker-Keywords erweitern
    keywords = set()
    for t in tickers:
        keywords.add(t.lower())
        # Bekannte Namen
        names = {
            'NVDA': 'nvidia', 'MSFT': 'microsoft', 'PLTR': 'palantir',
            'EQNR': 'equinor', 'BAYN.DE': 'bayer', 'RIO.L': 'rio tinto',
            'OXY': 'occidental', 'FRO': 'frontline', 'DHT': 'dht holdings',
            'KTOS': 'kratos', 'HII': 'huntington ingalls', 'HL': 'hecla',
            'PAAS': 'pan american', 'MOS': 'mosaic', 'HAG.DE': 'hensoldt',
            'TTE.PA': 'totalenergies', 'RHM.DE': 'rheinmetall',
        }
        if t in names:
            keywords.add(names[t])
    
    # Immer relevante Keywords
    keywords.update(['oil', 'öl', 'iran', 'hormuz', 'defense', 'rüstung',
                     'gold', 'silver', 'vix', 'fed', 'nasdaq'])
    
    relevant = []
    for art in articles:
        text = (art.get('title', '') + ' ' + art.get('summary', '')).lower()
        for kw in keywords:
            if kw in text:
                art['matched_keyword'] = kw
                relevant.append(art)
                break
    
    return relevant


def format_news_compact(articles, max_items=8):
    """Kompakte News-Ausgabe für Reports."""
    lines = []
    seen = set()
    for art in articles[:max_items]:
        title = art.get('title', '')[:80]
        if title in seen:
            continue
        seen.add(title)
        source = art.get('source', '?')
        kw = art.get('matched_keyword', '')
        lines.append(f"  • [{source}] {title}" + (f" ({kw})" if kw else ""))
    return "\n".join(lines) if lines else "  Keine relevanten News"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true', help='Cache ignorieren')
    parser.add_argument('--portfolio', action='store_true', help='Nur Portfolio-relevante')
    parser.add_argument('--json', action='store_true', help='JSON-Ausgabe')
    parser.add_argument('--compact', action='store_true', help='Kompakte Ausgabe')
    args = parser.parse_args()
    
    if args.portfolio:
        articles = get_portfolio_news()
    else:
        articles = get_cached_news(force_refresh=args.refresh)
    
    if args.json:
        print(json.dumps(articles, indent=2, ensure_ascii=False))
    elif args.compact:
        print(format_news_compact(articles))
    else:
        print(f"📰 {len(articles)} Artikel")
        for a in articles:
            src = a.get('source', '?')
            title = a.get('title', '?')[:70]
            print(f"  [{src}] {title}")
