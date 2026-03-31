#!/usr/bin/env python3
"""
Opportunity Scanner — Broad Market Anti-Cyclical Search
Findet Aktien die an 52W-Tiefs sind, analysiert WARUM (via News),
bewertet ob der Grund temporär oder strukturell ist.
Keine vordefinierten Stressoren — der Scanner findet selbst.
"""

import sqlite3, json, urllib.request, datetime, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Breites Universum — verschiedene Sektoren, nicht nur bekannte Namen
UNIVERSE = {
    "airlines":     ["LHA.DE", "RYA.IR", "IAG.L", "AF.PA", "DAL", "UAL", "WIZZ.L"],
    "container":    ["HLAG.DE", "MAERSK-B.CO", "ZIM", "CMRE"],
    "tanker":       ["FRO", "DHT", "STNG", "TNK"],
    "energy_cons":  ["BAS.DE", "WCH.DE", "LIN", "APD"],       # Chemie — Energie-Input
    "auto":         ["BMW.DE", "VOW3.DE", "MBG.DE", "STLAM.MI", "F", "GM"],
    "retail":       ["DLTR", "DG", "KSS", "M"],               # Konsumgüter/Discount
    "cruise":       ["CCL", "RCL", "NCLH"],
    "real_estate":  ["VNQ", "LAND.L", "WDP.BR"],              # REIT — Zinssensitiv
    "biotech":      ["BIIB", "MRNA", "BNTX", "REGN"],
    "solar":        ["ENPH", "SEDG", "RUN", "FSLR"],
    "semi":         ["ASML.AS", "INTC", "MRVL", "ON"],        # Chips außer NVDA
    "banks_eu":     ["CBK.DE", "DBK.DE", "BNP.PA", "CABK.MC"],
    "steel":        ["MT", "STLD", "NUE", "TKAMY"],
    "miners_base":  ["FCX", "TECK", "HBM"],                   # Kupfer/Zink
    "agri":         ["MOS", "NTR", "CF", "UAN"],
    "defense":      ["RHM.DE", "LDO.MI", "HO.PA", "BA"],
}

TEMPORAERE_FAKTOREN = [
    # Schlüsselwörter die auf temporäre Probleme hinweisen
    ("krieg", "konflikt", "sanktionen", "embargo"),
    ("zins", "rate hike", "fed", "ezb"),
    ("vix", "volatility", "uncertainty", "angst"),
    ("kerosin", "fuel", "oil", "brent", "crude"),
    ("suez", "hormuz", "rotes meer", "route", "shipping lane"),
    ("china", "taiwan", "geopolit"),
    ("earnings miss", "gewinnwarnung", "guidance cut"),
    ("recall", "rückruf", "regulierung", "klage"),
    ("covid", "lockdown", "pandemie"),
]

STRUKTURELLE_FAKTOREN = [
    # Schlüsselwörter die auf strukturelle Probleme hinweisen (→ kein antizyklischer Kauf)
    ("disruption", "disrupted", "obsolet"),
    ("marktanteil verloren", "market share loss"),
    ("insolvenz", "bankruptcy", "chapter 11"),
    ("fraud", "betrug", "bilanzskandal"),
    ("strukturell", "langfristig rückläufig", "secular decline"),
]

def get_price(ticker):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1wk&range=6mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        r = data['chart']['result'][0]
        closes = [c for c in r['indicators']['quote'][0]['close'] if c]
        m = r['meta']
        return m.get('regularMarketPrice'), m.get('fiftyTwoWeekHigh'), m.get('fiftyTwoWeekLow'), closes
    except:
        return None, None, None, []

def get_news_for_ticker(ticker):
    """Google News RSS für Ticker"""
    try:
        name = ticker.split('.')[0]
        url = f'https://news.google.com/rss/search?q={name}+stock+aktie&hl=en&gl=US&ceid=US:en'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        xml = urllib.request.urlopen(req, timeout=6).read().decode('utf-8', errors='ignore')
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', xml)[1:6]
        return titles
    except:
        return []

def classify_reason(news_titles):
    """Klassifiziert ob Grund temporär oder strukturell ist"""
    text = ' '.join(news_titles).lower()
    temp_score = 0
    struct_score = 0

    for keywords in TEMPORAERE_FAKTOREN:
        if any(k in text for k in keywords):
            temp_score += 1

    for keywords in STRUKTURELLE_FAKTOREN:
        if any(k in text for k in keywords):
            struct_score += 2  # Strukturell gewichtet schwerer

    if struct_score > temp_score:
        return "STRUKTURELL", struct_score, temp_score
    elif temp_score > 0:
        return "TEMPORAER", temp_score, struct_score
    else:
        return "UNKLAR", 0, 0

def run_scan():
    opportunities = []
    print(f"\n{'='*65}")
    print(f"BROAD OPPORTUNITY SCANNER — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")
    print("Scanne " + str(sum(len(v) for v in UNIVERSE.values())) + " Aktien in " + str(len(UNIVERSE)) + " Sektoren...")

    for sector, tickers in UNIVERSE.items():
        sector_results = []
        for ticker in tickers:
            cur, h52, l52, closes = get_price(ticker)
            if not cur or not h52 or not l52:
                continue

            from_high = (cur/h52-1)*100

            # Nur interessant wenn >15% unter 52W-High
            if from_high > -15:
                continue

            # Momentum: fällt noch oder stabilisiert?
            trend = "stabil" if len(closes) >= 4 and closes[-1] >= closes[-4]*0.97 else "fallend"

            # News abrufen für Grund-Analyse
            news = get_news_for_ticker(ticker)
            reason_type, temp_s, struct_s = classify_reason(news)

            # Score berechnen
            score = 0
            if from_high < -30: score += 30
            elif from_high < -20: score += 20
            else: score += 10

            from_low = (cur/l52-1)*100
            if from_low > 20: score += 15
            elif from_low > 10: score += 8

            if trend == "stabil": score += 15
            if reason_type == "TEMPORAER": score += 20
            elif reason_type == "STRUKTURELL": score -= 20

            sector_results.append({
                "ticker": ticker,
                "sector": sector,
                "current": cur,
                "high52": h52,
                "low52": l52,
                "from_high": round(from_high, 1),
                "from_low": round(from_low, 1),
                "trend": trend,
                "reason_type": reason_type,
                "news": news[:2],
                "score": max(0, score),
                "scanned_at": datetime.datetime.now().isoformat()
            })

        # Top pro Sektor
        if sector_results:
            best = max(sector_results, key=lambda x: x['score'])
            if best['score'] >= 25:
                opportunities.append(best)

    # Sortiert nach Score
    opportunities.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n{'Ticker':12s} | {'Score':5s} | {'v.High':7s} | {'Grund':12s} | {'Trend':8s} | Letzte News")
    print("-" * 90)
    for o in opportunities[:15]:
        icon = "🟢" if o['score'] >= 50 else "🟡" if o['score'] >= 35 else "⚪"
        news_preview = o['news'][0][:45] if o['news'] else "—"
        print(f"{icon} {o['ticker']:10s} | {o['score']:5d} | {o['from_high']:+6.1f}% | {o['reason_type']:12s} | {o['trend']:8s} | {news_preview}")

    # In DB
    conn = sqlite3.connect('data/trading.db')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS opportunity_scan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT, sector TEXT, current_price REAL,
        high52 REAL, low52 REAL, from_high_pct REAL, from_low_pct REAL,
        trend TEXT, reason_type TEXT, news TEXT, score INTEGER, scanned_at TEXT
    )""")
    for o in opportunities:
        c.execute("""INSERT INTO opportunity_scan
            (ticker, sector, current_price, high52, low52, from_high_pct, from_low_pct,
             trend, reason_type, news, score, scanned_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (o['ticker'], o['sector'], o['current'], o['high52'], o['low52'],
             o['from_high'], o['from_low'], o['trend'], o['reason_type'],
             json.dumps(o['news']), o['score'], o['scanned_at']))
    conn.commit()
    conn.close()

    top = [o for o in opportunities if o['score'] >= 50]
    print(f"\n✅ {len(opportunities)} Kandidaten gefunden, {len(top)} mit Score ≥50 (potenzielle Entries)")
    return opportunities

if __name__ == '__main__':
    run_scan()
