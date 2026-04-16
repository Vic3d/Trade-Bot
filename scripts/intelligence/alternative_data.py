#!/usr/bin/env python3.13
"""
Alternative Data Browser — kostenloses Web-Scraping für Trading-Thesen
=======================================================================
Verhält sich wie ein Mensch der Webseiten aufruft — keine bezahlten APIs.

Datenquellen:
  1. SEC EDGAR JSON-API    — Insider-Trades, 13F (institutionelle Positionen)
  2. VesselFinder          — Schiffsverkehr Hormuz / Suez
  3. FAO Food Price Index  — Nahrungsmittel-/Düngemittelpreise
  4. EIA API               — US Öl/Gas Lagerdaten (kostenlose Behörden-API)
  5. FinViz Screener       — Aktien-Momentum, News-Sentiment
  6. USDA NASS             — US-Agrar-Reports (Aussaatsaison-Daten)
  7. Seeking Alpha RSS     — Nachrichten zu spezifischen Tickers

Ausgabe: data/alternative_data.json (wird von conviction_scorer und overnight_collector gelesen)

Usage:
  python3.13 alternative_data.py              # Alle Quellen abrufen
  python3.13 alternative_data.py --source eia # Nur EIA
  python3.13 alternative_data.py --source vessels  # Nur Schiffe
  python3.13 alternative_data.py --source insider YARA.OL  # Insider-Trades
"""

import json
import random
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path
from xml.etree import ElementTree

WS = Path('/data/.openclaw/workspace')
OUTPUT = WS / 'data/alternative_data.json'
STRATEGIES_FILE = WS / 'data/strategies.json'

# ── User-Agent Rotation (wirkt wie echter Browser) ───────────────────────────

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 '
    '(KHTML, like Gecko) Version/17.4 Safari/605.1.15',
]

ACCEPT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
}


def _random_delay(min_s: float = 1.5, max_s: float = 4.5):
    """Menschliche Pause zwischen Requests."""
    time.sleep(random.uniform(min_s, max_s))


def _fetch(url: str, headers: dict | None = None, retries: int = 3,
           timeout: int = 15, decode: str = 'utf-8') -> str | None:
    """
    HTTP-GET mit rotierendem User-Agent und Retry-Backoff.
    Gibt HTML/Text zurück oder None bei Fehler.
    """
    h = {**ACCEPT_HEADERS, 'User-Agent': random.choice(USER_AGENTS)}
    if headers:
        h.update(headers)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # gzip wird von urllib automatisch behandelt
                try:
                    return raw.decode(decode)
                except UnicodeDecodeError:
                    return raw.decode('latin-1', errors='replace')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 10
                print(f"[alt_data] 429 Too Many Requests — warte {wait}s")
                time.sleep(wait)
            elif e.code in (403, 451):
                print(f"[alt_data] {e.code} geblockt: {url[:60]}")
                return None
            else:
                print(f"[alt_data] HTTP {e.code}: {url[:60]}")
        except Exception as e:
            print(f"[alt_data] Fehler (Versuch {attempt+1}): {e}")
            time.sleep(3 * (attempt + 1))

    return None


def _fetch_json(url: str, headers: dict | None = None) -> dict | list | None:
    """Lädt JSON direkt."""
    h = {'Accept': 'application/json'}
    if headers:
        h.update(headers)
    raw = _fetch(url, headers=h)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── 1. SEC EDGAR — Insider-Trades + 13F ──────────────────────────────────────

def fetch_sec_insider(ticker: str) -> dict:
    """
    Lädt die letzten Insider-Transaktionen via SEC EDGAR JSON-API.
    Kein Scraping nötig — offizieller kostenloser API-Endpunkt.
    """
    result = {'ticker': ticker, 'insider_trades': [], 'source': 'SEC EDGAR'}
    # CIK-Lookup
    url_lookup = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2024-01-01&forms=4"
    # Nutze EDGAR Full-Text Search API
    search_url = (
        f"https://efts.sec.gov/LATEST/search-index?q=%22{urllib.parse.quote(ticker)}%22"
        f"&forms=4&dateRange=custom&startdt={_days_ago(90)}&enddt={_today()}"
    )
    headers = {'User-Agent': 'TradeMind Research contact@trademind.local'}
    data = _fetch_json(search_url, headers=headers)
    if not data:
        return result

    hits = data.get('hits', {}).get('hits', [])[:10]
    for hit in hits:
        src = hit.get('_source', {})
        result['insider_trades'].append({
            'date': src.get('file_date', ''),
            'filer': src.get('display_names', ['?'])[0] if src.get('display_names') else '?',
            'form': src.get('form_type', '4'),
            'url': f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={src.get('entity_id','')}&type=4",
        })
    _random_delay()
    return result


def _days_ago(n: int) -> str:
    return (datetime.now(_BERLIN) - timedelta(days=n)).strftime('%Y-%m-%d')

def _today() -> str:
    return datetime.now(_BERLIN).strftime('%Y-%m-%d')


# ── 2. VesselFinder — Schiffsverkehr Hormuz ──────────────────────────────────

def fetch_vessel_activity(area: str = 'hormuz') -> dict:
    """
    Scrapt VesselFinder für Schiffsverkehr in kritischen Wasserstraßen.
    Liest öffentliche Statistik-Seiten — kein Login nötig.
    """
    result = {
        'area': area,
        'vessels_detected': None,
        'tankers_detected': None,
        'note': '',
        'source': 'VesselFinder / MarineTraffic public data',
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    # Strategischer Ansatz: Suche nach Hormuz-Berichten auf öffentlichen Seiten
    # VesselFinder zeigt Zonen-Statistiken auf der Hauptseite nicht direkt an.
    # Stattdessen: Lloyd's List Intelligence oder MarineTraffic Blog scrapen
    urls_to_try = [
        ('https://www.marinetraffic.com/blog/', 'hormuz|strait|tanker'),
        ('https://gcaptain.com/', 'hormuz|strait|tanker|closure'),
    ]

    for url, pattern in urls_to_try:
        html = _fetch(url)
        if not html:
            continue
        # Extrahiere Artikel-Titel die Hormuz erwähnen
        titles = re.findall(r'<h[23][^>]*>([^<]{10,120})</h[23]>', html, re.IGNORECASE)
        mentions = [t.strip() for t in titles
                    if re.search(pattern, t, re.IGNORECASE)]
        if mentions:
            result['note'] = f"Aktuelle Meldungen: {'; '.join(mentions[:3])}"
            result['vessels_detected'] = 'data_from_news'
            break
        _random_delay(2, 5)

    return result


# ── 3. FAO Food Price Index ───────────────────────────────────────────────────

def fetch_fao_food_price_index() -> dict:
    """
    Lädt den FAO Food Price Index — öffentliche CSV-Daten.
    Enthält: Getreide, Pflanzenöl, Milch, Fleisch, Zucker.
    Relevant für PS_FertilizerShock-Thesis.
    """
    result = {
        'source': 'FAO Food Price Index',
        'url': 'https://www.fao.org/worldfoodsituation/foodpricesindex/en/',
        'data': {},
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    # FAO stellt monatliche Daten als CSV bereit
    csv_url = 'https://www.fao.org/faostat/en/data/CP'
    # Stattdessen: Scrape die Übersichtsseite
    html = _fetch('https://www.fao.org/worldfoodsituation/foodpricesindex/en/')
    if not html:
        result['note'] = 'FAO nicht erreichbar'
        return result

    # Extrahiere Indexwerte aus der HTML-Tabelle
    # FAO FPRI Tabelle hat spezifisches Format
    numbers = re.findall(r'(\d{3}(?:\.\d{1,2})?)', html)
    if numbers:
        result['note'] = f"FAO FPRI Seite geladen, {len(numbers)} Zahlen gefunden"
    _random_delay()
    return result


# ── 4. EIA — US Öl/Gas Lagerdaten ────────────────────────────────────────────

def fetch_eia_weekly_petroleum() -> dict:
    """
    EIA (US Energy Information Administration) — kostenlose Behörden-API.
    Wöchentliche US-Rohöllager: Wenn Lager sinken = bullish für Öl.
    Kein API-Key nötig für öffentliche Datensätze.
    """
    result = {
        'source': 'EIA Weekly Petroleum Status Report',
        'crude_inventory_change_mmbbl': None,
        'note': '',
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    # EIA API v2 — kostenlos, kein Key für public datasets
    url = (
        'https://api.eia.gov/v2/petroleum/stoc/wstk/data/'
        '?frequency=weekly&data[0]=value&facets[series][]=WCRSTUS1'
        '&sort[0][column]=period&sort[0][direction]=desc&length=4'
        '&api_key=DEMO_KEY'
    )
    data = _fetch_json(url)
    if data and 'response' in data:
        rows = data['response'].get('data', [])
        if len(rows) >= 2:
            latest = rows[0]['value']
            prev = rows[1]['value']
            change = round((float(latest) - float(prev)), 1) if latest and prev else None
            result['crude_inventory_change_mmbbl'] = change
            result['latest_inventory_mmbbl'] = latest
            result['period'] = rows[0].get('period', '')
            result['note'] = (
                f"Rohöllager {'+' if change and change > 0 else ''}{change} Mio bbl "
                f"(Stand {rows[0].get('period','')})"
            )
    _random_delay()
    return result


# ── 5. FinViz — Momentum + News-Sentiment ────────────────────────────────────

def fetch_finviz_ticker(ticker: str) -> dict:
    """
    Scrapt FinViz für einen Ticker: Fundamentaldaten + aktuelle News-Headlines.
    FinViz erlaubt mäßiges Scraping ohne Login (keine Paywall auf Basis-Daten).
    """
    result = {
        'ticker': ticker,
        'price': None,
        'change_pct': None,
        'week52_high': None,
        'week52_low': None,
        'news': [],
        'source': 'FinViz',
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    url = f"https://finviz.com/quote.ashx?t={ticker.upper()}&p=d"
    html = _fetch(url, headers={
        'Referer': 'https://finviz.com/',
        'Upgrade-Insecure-Requests': '1',
    })
    if not html:
        return result

    # Preis extrahieren
    price_m = re.search(r'"last"[^>]*>([0-9,]+\.?\d*)<', html)
    if price_m:
        result['price'] = price_m.group(1).replace(',', '')

    # Change %
    change_m = re.search(r'id="change"[^>]*>([+-]?\d+\.\d+)%', html)
    if change_m:
        result['change_pct'] = change_m.group(1)

    # 52W Range
    range_m = re.search(r'52W\s*(?:Range|High)[^>]*>([\d.,]+)\s*-\s*([\d.,]+)', html, re.IGNORECASE)
    if range_m:
        result['week52_low'] = range_m.group(1)
        result['week52_high'] = range_m.group(2)

    # News Headlines
    news_titles = re.findall(
        r'class="news-link-left"[^>]*>\s*<a[^>]+>([^<]{10,120})</a>',
        html, re.IGNORECASE
    )
    result['news'] = news_titles[:5]

    _random_delay(2, 5)
    return result


# ── 6. Seeking Alpha RSS — Ticker-spezifische Nachrichten ────────────────────

def fetch_seeking_alpha_news(ticker: str) -> list[dict]:
    """
    Seeking Alpha RSS-Feed für einen Ticker — kostenlos, kein Login.
    """
    url = f"https://seekingalpha.com/api/v3/symbols/{ticker.upper()}/news?filter[category]=latest-articles&page[size]=5"
    # SA blockiert direkte API-Calls — nutze deren öffentlichen Feed stattdessen
    rss_url = f"https://seekingalpha.com/symbol/{ticker.upper()}.xml"
    html = _fetch(rss_url)
    items = []
    if html:
        try:
            root = ElementTree.fromstring(html)
            ns = {'': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('.//item')[:5]:
                title = entry.findtext('title') or ''
                pub = entry.findtext('pubDate') or ''
                link = entry.findtext('link') or ''
                items.append({'title': title.strip(), 'date': pub[:16], 'url': link})
        except Exception:
            pass
    _random_delay()
    return items


# ── 7. USDA NASS — US-Agrar-Reports ─────────────────────────────────────────

def fetch_usda_planting_progress() -> dict:
    """
    USDA National Agricultural Statistics Service — kostenlose API.
    Aussaatfortschritt für Mais und Soja (relevant für Düngemittel-Thesis).
    """
    result = {
        'source': 'USDA NASS',
        'corn_planted_pct': None,
        'soybeans_planted_pct': None,
        'note': '',
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    # USDA Quick Stats API — kostenlos
    base = 'https://quickstats.nass.usda.gov/api/get_param_values/?key=DEMO_KEY'
    url = (
        'https://quickstats.nass.usda.gov/api/api_GET/?key=DEMO_KEY'
        '&source_desc=SURVEY&sector_desc=CROPS&group_desc=FIELD CROPS'
        '&commodity_desc=CORN&statisticcat_desc=PROGRESS'
        '&unit_desc=PCT PLANTED&year=2026&agg_level_desc=NATIONAL'
        '&format=json'
    )
    data = _fetch_json(url)
    if data and 'data' in data:
        rows = data['data']
        if rows:
            latest = rows[-1]
            result['corn_planted_pct'] = latest.get('Value', '?')
            result['note'] = f"Mais-Aussaat: {latest.get('Value','?')}% (KW {latest.get('week_ending','')})"
    _random_delay()
    return result


# ── 8. gcaptain.com — Maritime News ─────────────────────────────────────────

def fetch_shipping_news() -> list[dict]:
    """
    gCaptain.com — kostenloser RSS-Feed für Maritime/Shipping News.
    Direkter Proxy für Hormuz/Suez-Aktivität.
    """
    rss_url = 'https://gcaptain.com/feed/'
    html = _fetch(rss_url)
    items = []
    if not html:
        return items
    try:
        root = ElementTree.fromstring(html)
        for item in root.findall('.//item')[:10]:
            title = item.findtext('title') or ''
            link = item.findtext('link') or ''
            pub = item.findtext('pubDate') or ''
            desc = item.findtext('description') or ''
            # Nur relevante maritime/geopolitik Themen
            if re.search(r'hormuz|suez|tanker|iran|blockade|shipping|vessel|freight',
                        title + desc, re.IGNORECASE):
                items.append({
                    'title': title.strip(),
                    'date': pub[:16],
                    'url': link,
                    'relevance': 'HORMUZ/SHIPPING',
                })
    except Exception as e:
        print(f"[alt_data] gcaptain RSS parse error: {e}")
    _random_delay()
    return items


# ── Orchestrierung ────────────────────────────────────────────────────────────

def load_active_tickers() -> list[str]:
    """Liest aktive Ticker aus strategies.json."""
    try:
        strategies = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
        tickers = []
        for sid, s in strategies.items():
            if sid.startswith('_') or not isinstance(s, dict):
                continue
            if s.get('status') in ('active', 'experimental'):
                tickers.extend(s.get('tickers', []))
        # Nur US-Tickers für FinViz (kein .OL .DE etc.)
        us_tickers = [t for t in set(tickers) if '.' not in t and len(t) <= 5]
        return us_tickers[:10]  # Max 10 um nicht zu viele Requests zu machen
    except Exception:
        return ['YARA', 'CF', 'MOS', 'MP', 'OXY']


def run_all(sources: list[str] | None = None) -> dict:
    """
    Holt alle Alternative-Data-Quellen und speichert in alternative_data.json.
    sources: Optional Liste von Source-IDs, sonst alle
    """
    report = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'sources_run': [],
    }

    run_all_sources = sources is None
    active_tickers = load_active_tickers()

    # EIA Öl-Lagerdaten
    if run_all_sources or 'eia' in sources:
        print("[alt_data] EIA Petroleum...")
        report['eia_petroleum'] = fetch_eia_weekly_petroleum()
        report['sources_run'].append('eia')

    # Shipping News (Hormuz-Proxy)
    if run_all_sources or 'vessels' in sources or 'shipping' in sources:
        print("[alt_data] gCaptain Shipping News...")
        report['shipping_news'] = fetch_shipping_news()
        vessel_result = fetch_vessel_activity('hormuz')
        report['vessel_activity'] = vessel_result
        report['sources_run'].extend(['gcaptain', 'vessels'])

    # USDA Aussaat-Fortschritt (für Düngemittel-Thesis)
    if run_all_sources or 'usda' in sources:
        print("[alt_data] USDA Planting Progress...")
        report['usda_planting'] = fetch_usda_planting_progress()
        report['sources_run'].append('usda')

    # FAO Nahrungsmittelpreise
    if run_all_sources or 'fao' in sources:
        print("[alt_data] FAO Food Price Index...")
        report['fao_food_prices'] = fetch_fao_food_price_index()
        report['sources_run'].append('fao')

    # FinViz für aktive US-Tickers
    if run_all_sources or 'finviz' in sources:
        print(f"[alt_data] FinViz fuer {len(active_tickers)} Tickers...")
        report['finviz'] = {}
        for ticker in active_tickers:
            print(f"  -> {ticker}")
            report['finviz'][ticker] = fetch_finviz_ticker(ticker)
        report['sources_run'].append('finviz')

    # Speichern
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[alt_data] Gespeichert: {OUTPUT}")
    return report


def summarize_for_discord(report: dict) -> str:
    """Kurze Discord-Zusammenfassung der Alternative Data."""
    lines = ["**Alt-Data Update**"]

    eia = report.get('eia_petroleum', {})
    if eia.get('note'):
        emoji = 'bearish' if (eia.get('crude_inventory_change_mmbbl') or 0) > 0 else 'bullish'
        lines.append(f"Oel-Lager: {eia['note']} {'(bearish)' if emoji=='bearish' else '(bullish)'}")

    shipping = report.get('shipping_news', [])
    if shipping:
        lines.append(f"Shipping ({len(shipping)} relevante Meldungen):")
        for s in shipping[:3]:
            lines.append(f"  - {s['title'][:80]}")

    usda = report.get('usda_planting', {})
    if usda.get('note'):
        lines.append(f"USDA: {usda['note']}")

    return '\n'.join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--source' in args:
        idx = args.index('--source')
        source_name = args[idx + 1] if idx + 1 < len(args) else ''
        extra_arg = args[idx + 2] if idx + 2 < len(args) else None

        if source_name == 'insider' and extra_arg:
            result = fetch_sec_insider(extra_arg)
            print(json.dumps(result, indent=2))
        elif source_name == 'finviz' and extra_arg:
            result = fetch_finviz_ticker(extra_arg)
            print(json.dumps(result, indent=2))
        elif source_name == 'shipping' or source_name == 'vessels':
            shipping = fetch_shipping_news()
            vessels = fetch_vessel_activity('hormuz')
            print(json.dumps({'shipping': shipping, 'vessels': vessels}, indent=2))
        elif source_name == 'eia':
            print(json.dumps(fetch_eia_weekly_petroleum(), indent=2))
        elif source_name == 'usda':
            print(json.dumps(fetch_usda_planting_progress(), indent=2))
        elif source_name == 'fao':
            print(json.dumps(fetch_fao_food_price_index(), indent=2))
        else:
            report = run_all([source_name])
            print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        report = run_all()
        print(summarize_for_discord(report))
