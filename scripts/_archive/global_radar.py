#!/usr/bin/env python3
"""
Global Radar — News-First Opportunity Detection
Ansatz: ERST News, DANN Aktien — nicht umgekehrt.
Scannt globale Nachrichten, identifiziert Markt-relevante Ereignisse,
findet den dazugehörigen Trade — weltweit, alle Asset-Klassen.
"""

import urllib.request, json, re, datetime, sqlite3, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# News-Feeds: wirklich global
FEEDS = {
    # Rohstoffe & Energie
    "commodities": [
        "https://news.google.com/rss/search?q=commodity+mining+lithium+copper+cobalt+rare+earth&hl=en",
        "https://news.google.com/rss/search?q=oil+gas+LNG+pipeline+refinery&hl=en",
        "https://news.google.com/rss/search?q=wheat+corn+soy+coffee+cocoa+agriculture&hl=en",
    ],
    # Geopolitik global (nicht nur Naher Osten)
    "geopolitics": [
        "https://news.google.com/rss/search?q=sanctions+embargo+trade+war+tariff&hl=en",
        "https://news.google.com/rss/search?q=coup+election+protest+revolution+government&hl=en",
        "https://news.google.com/rss/search?q=latin+america+africa+southeast+asia+economy&hl=en",
    ],
    # Zentralbanken & Währungen
    "macro": [
        "https://news.google.com/rss/search?q=central+bank+interest+rate+inflation+recession&hl=en",
        "https://news.google.com/rss/search?q=currency+crisis+devaluation+forex+dollar+yuan&hl=en",
        "https://news.google.com/rss/search?q=IMF+World+Bank+debt+crisis+default&hl=en",
    ],
    # Technologie & Disruption
    "tech": [
        "https://news.google.com/rss/search?q=AI+semiconductor+chip+quantum+breakthrough&hl=en",
        "https://news.google.com/rss/search?q=FDA+approval+drug+biotech+clinical+trial&hl=en",
        "https://news.google.com/rss/search?q=antitrust+regulation+ban+fine+tech&hl=en",
    ],
    # Shipping & Logistik global
    "shipping": [
        "https://news.google.com/rss/search?q=shipping+port+canal+strait+blockade+tanker&hl=en",
        "https://news.google.com/rss/search?q=Panama+Suez+Malacca+Bosphorus+strait&hl=en",
    ],
    # Naturkatastrophen & Klimaereignisse
    "events": [
        "https://news.google.com/rss/search?q=earthquake+hurricane+drought+flood+disaster+crop&hl=en",
        "https://news.google.com/rss/search?q=strike+labor+union+supply+chain+shortage&hl=en",
    ],
}

# Mapping: Keywords → Tradeable Assets + Richtung
SIGNAL_MAP = [
    # Rohstoffe
    {"keywords": ["lithium", "lithium mine", "lithium supply"],
     "tickers": ["ALB", "SQM", "LTHM", "PLL"],
     "sector": "Lithium/EV",
     "direction_up": ["shortage", "strike", "mine closure", "demand surge", "EV"],
     "direction_down": ["oversupply", "new mine", "demand falls"]},

    {"keywords": ["copper", "kupfer", "mine strike", "chile mine"],
     "tickers": ["FCX", "TECK", "HBM", "SCCO"],
     "sector": "Kupfer",
     "direction_up": ["strike", "shortage", "mine close", "flood"],
     "direction_down": ["oversupply", "china demand falls"]},

    {"keywords": ["wheat", "weizen", "grain", "drought", "harvest"],
     "tickers": ["WEAT", "MOS", "NTR", "CF", "ADM"],
     "sector": "Agrar",
     "direction_up": ["drought", "dürre", "shortage", "export ban", "flood"],
     "direction_down": ["record harvest", "oversupply"]},

    {"keywords": ["coffee", "kakao", "cocoa", "palm oil"],
     "tickers": ["JO", "NIB", "PALM"],
     "sector": "Soft Commodities",
     "direction_up": ["drought", "disease", "frost", "shortage"],
     "direction_down": ["record crop", "oversupply"]},

    {"keywords": ["rare earth", "seltene erden", "neodymium", "cobalt"],
     "tickers": ["MP", "LITE", "LYEL"],
     "sector": "Seltene Erden",
     "direction_up": ["china export ban", "shortage", "defense demand"],
     "direction_down": ["new mine", "alternative found"]},

    {"keywords": ["lng", "natural gas", "flüssiggas", "pipeline"],
     "tickers": ["LNG", "TELL", "GLNG", "TTF"],
     "sector": "LNG/Erdgas",
     "direction_up": ["pipeline attack", "cold wave", "shortage", "export ban"],
     "direction_down": ["warm winter", "new supply", "discovery"]},

    {"keywords": ["semiconductor", "chip", "wafer", "TSMC", "halbleiter"],
     "tickers": ["TSM", "ASML.AS", "AMAT", "LRCX", "KLAC"],
     "sector": "Halbleiter",
     "direction_up": ["shortage", "new fab", "AI demand", "defense order"],
     "direction_down": ["oversupply", "export ban", "China risk"]},

    {"keywords": ["FDA", "approval", "drug", "clinical trial", "EMA"],
     "tickers": ["depends_on_company"],
     "sector": "Biotech/Pharma",
     "direction_up": ["FDA approval", "positive trial", "breakthrough"],
     "direction_down": ["trial failure", "FDA rejection", "recall"]},

    {"keywords": ["argentina", "brazil", "chile", "latin america", "latam"],
     "tickers": ["EWZ", "ECH", "ARGT", "GXG"],
     "sector": "Lateinamerika ETFs",
     "direction_up": ["reform", "trade deal", "commodity boom"],
     "direction_down": ["default", "devaluation", "political crisis"]},

    {"keywords": ["nigeria", "ghana", "angola", "africa", "DRC", "congo"],
     "tickers": ["AFK", "GAF", "EGPT"],
     "sector": "Afrika (Rohstoffe/ETFs)",
     "direction_up": ["oil discovery", "reform", "FDI"],
     "direction_down": ["coup", "sanctions", "civil war"]},

    {"keywords": ["vietnam", "indonesia", "philippines", "bangladesh", "manufacturing"],
     "tickers": ["VNM", "EIDO", "EPHE"],
     "sector": "SE-Asien Produktion",
     "direction_up": ["factory relocation", "trade deal", "US tariff China"],
     "direction_down": ["flood", "political crisis", "labor unrest"]},

    {"keywords": ["strike", "streik", "labor", "union", "port blockade"],
     "tickers": ["depends_on_sector"],
     "sector": "Supply Chain",
     "direction_up": ["supply disruption"],
     "direction_down": ["deal reached", "strike ends"]},

    {"keywords": ["interest rate", "zinsen", "fed hike", "ECB cut", "rate decision"],
     "tickers": ["TLT", "IEF", "GLD", "VNQ", "XLU"],
     "sector": "Zinssensitive Assets",
     "direction_up": ["rate cut", "pivot", "pause"],
     "direction_down": ["rate hike", "hawkish", "inflation"]},

    {"keywords": ["yuan", "renminbi", "CNY", "dollar", "currency crisis", "devaluation"],
     "tickers": ["FXI", "MCHI", "EWY", "EWT"],
     "sector": "EM Währung/Aktien",
     "direction_up": ["yuan strong", "dollar weak"],
     "direction_down": ["devaluation", "capital flight", "yuan weak"]},
]

def fetch_rss(url, max_items=8):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        xml = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
        items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)[:max_items]
        results = []
        for item in items:
            title = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item)
            if not title:
                title = re.search(r'<title>(.*?)</title>', item)
            link = re.search(r'<link>(.*?)</link>', item)
            pub = re.search(r'<pubDate>(.*?)</pubDate>', item)
            if title:
                results.append({
                    'title': title.group(1).strip(),
                    'link': link.group(1).strip() if link else '',
                    'date': pub.group(1)[:16] if pub else '',
                })
        return results
    except Exception as e:
        return []

def match_signals(news_items):
    """Matched News-Headlines gegen Signal-Map"""
    hits = []
    for news in news_items:
        title_lower = news['title'].lower()
        for sig in SIGNAL_MAP:
            if any(kw in title_lower for kw in sig['keywords']):
                direction = "UP"
                confidence = "mittel"
                if any(d in title_lower for d in sig['direction_up']):
                    direction = "↑ BULLISCH"
                    confidence = "hoch"
                elif any(d in title_lower for d in sig['direction_down']):
                    direction = "↓ BEARISCH"
                    confidence = "hoch"

                hits.append({
                    'headline': news['title'],
                    'sector': sig['sector'],
                    'tickers': [t for t in sig['tickers'] if t != 'depends_on_company' and t != 'depends_on_sector'],
                    'direction': direction,
                    'confidence': confidence,
                    'date': news['date'],
                })
                break
    return hits

def run_global_radar():
    all_news = []
    print(f"\n{'='*65}")
    print(f"🌍 GLOBAL RADAR — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    for category, urls in FEEDS.items():
        for url in urls:
            items = fetch_rss(url)
            all_news.extend(items)

    print(f"Gescannte News: {len(all_news)} Headlines aus {sum(len(v) for v in FEEDS.values())} Feeds")

    # Signal-Matching
    signals = match_signals(all_news)
    unique = {s['headline']: s for s in signals}.values()  # Deduplizieren

    print(f"\n📡 ERKANNTE MARKT-SIGNALE ({len(list(unique))} Treffer):")
    print(f"{'Sektor':20s} | {'Richtung':12s} | {'Tickers':20s} | Headline")
    print("-" * 90)
    for s in sorted(unique, key=lambda x: x['confidence'], reverse=True):
        tickers_str = ', '.join(s['tickers'][:3]) if s['tickers'] else '(manuell prüfen)'
        print(f"{s['sector']:20s} | {s['direction']:12s} | {tickers_str:20s} | {s['headline'][:50]}")

    # In DB speichern
    conn = sqlite3.connect('data/trading.db')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS global_radar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        headline TEXT, sector TEXT, tickers TEXT,
        direction TEXT, confidence TEXT, scanned_at TEXT
    )""")
    for s in unique:
        c.execute("INSERT INTO global_radar (headline, sector, tickers, direction, confidence, scanned_at) VALUES (?,?,?,?,?,?)",
            (s['headline'], s['sector'], json.dumps(s['tickers']), s['direction'],
             s['confidence'], datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

    return list(unique)

if __name__ == '__main__':
    run_global_radar()
