#!/usr/bin/env python3
"""
newswire_poll.py — läuft einmalig, holt News, speichert in DB, gibt neue Danger-Events zurück.
Kein LLM, kein Discord. Ressourcenschonend — für Cron-Aufruf alle 5 Min.
Output (JSON) wird von OpenClaw Haiku-Cron gelesen.
"""

import json, sqlite3, time, urllib.request, re, os, sys

DB_PATH      = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
FINNHUB_KEY  = os.environ.get("FINNHUB_KEY", "d6o6lm1r01qu09ciaj3gd6o6lm1r01qu09ciaj40")
POLYGON_KEY  = os.environ.get("POLYGON_KEY", "UratMpPH0sxlZeDYcSaiXsK_g6C1_7ml")

# ── Portfolio ──────────────────────────────────────────────────────────────────
PORTFOLIO = {
    "NVDA":    {"name": "Nvidia",               "stop": None,  "entry": 167.88, "strategy": 3},
    "MSFT":    {"name": "Microsoft",            "stop": 338.0, "entry": 351.85, "strategy": 3},
    "PLTR":    {"name": "Palantir",             "stop": 127.0, "entry": 132.11, "strategy": 3},
    "EQNR":    {"name": "Equinor ASA",          "stop": 27.0,  "entry": 27.04,  "strategy": 1},
    "BAYN.DE": {"name": "Bayer AG",             "stop": 38.0,  "entry": 39.95,  "strategy": None},
    "RIO.L":   {"name": "Rio Tinto",            "stop": 73.0,  "entry": 76.92,  "strategy": 5},
    "RHM.DE":  {"name": "Rheinmetall AG",       "stop": None,  "entry": None,   "strategy": 2},
    "DR0.DE":  {"name": "Deutsche Rohstoff AG", "stop": 74.0,  "entry": None,   "strategy": 1},
    "AG":      {"name": "First Majestic Silver","stop": 20.5,  "entry": None,   "strategy": 4},
    "ISPA.DE": {"name": "Silber ETC",           "stop": None,  "entry": None,   "strategy": 4},
}

# ── Strategie-Keywords ─────────────────────────────────────────────────────────
STRATEGIES = {
    1: {"name": "Iran → Öl",       "tickers": ["EQNR","DR0.DE"],
        "bullish": ["hormuz","iran attack","oil supply disruption","iran strikes","tanker attack",
                    "gulf escalation","brent surges","oil hits","iran missile","iran drone",
                    "hezbollah","iran blockade","khamenei","irgc","strait of hormuz"],
        "bearish": ["iran ceasefire","hormuz open","iran deal","iran negotiations","iran peace",
                    "oil supply restored","waffenstillstand iran","strategic reserve release",
                    "iea release","russia oil waiver","opec increase output","de-escalat"]},
    2: {"name": "Aufrüstung → RHM","tickers": ["RHM.DE"],
        "bullish": ["rheinmetall","defense spending","nato budget","military spending","rearmament",
                    "bundeswehr","european defense","ukraine weapons","nato 3%"],
        "bearish": ["ceasefire ukraine","peace ukraine","defense budget cut","nato withdrawal"]},
    3: {"name": "KI → Halbleiter", "tickers": ["NVDA","MSFT","PLTR"],
        "bullish": ["nvidia earnings","datacenter expansion","ai spending","chip demand",
                    "palantir contract","microsoft ai","gpu demand","nvda beat","ai investment"],
        "bearish": ["nvidia export ban","chip ban china","vix above 30","pentagon ai ban",
                    "palantir investigation","nvda miss","helium supply chip","helium shortage",
                    "burry short palantir","pltr doge"]},
    4: {"name": "Silber/Gold",     "tickers": ["AG","ISPA.DE"],
        "bullish": ["silver surges","gold surges","precious metals rally","safe haven",
                    "silver demand","solar silver","first majestic beats"],
        "bearish": ["silver falls","gold drops","usd strengthens","fed rate hike","silver supply glut"]},
    5: {"name": "Kupfer/Rohstoff", "tickers": ["RIO.L"],
        "bullish": ["copper surge","lithium demand","ev demand","rio tinto copper","mining boom"],
        "bearish": ["china iron ore","rio tinto dividend cut","copper falls","china demand weak"]},
}

MACRO_SIGNALS = [
    ("vix above 30", "VIX > 30 — Tech unter Druck"),
    ("vix surges",   "VIX steigt — Markt-Panik"),
    ("fed rate hike","Fed Zinserhöhung — alle Positionen unter Druck"),
    ("bank collapse","Bankenkrise — Systemrisiko"),
    ("market crash", "Breiter Markteinbruch"),
    ("circuit breaker","Handelsstopp ausgelöst"),
    ("trump tariffs","Neue Zölle — Handelskonflikt"),
    ("nuclear",      "Nuklear-Eskalation"),
]

BLOOMBERG_FEEDS = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://feeds.bloomberg.com/technology/news.rss",
    "https://feeds.bloomberg.com/politics/news.rss",
]
GOOGLE_QUERIES = [
    "Rheinmetall Aktie", "Bayer Aktie", "Iran Hormuz Ölpreis",
    "Equinor Aktie", "Palantir stock", "Nvidia stock news",
]

# ── DB ─────────────────────────────────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL, source TEXT, ticker TEXT,
        strategy_id INTEGER, direction TEXT,
        headline TEXT NOT NULL UNIQUE,
        score INTEGER DEFAULT 0, alerted INTEGER DEFAULT 0, raw TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)")
    conn.commit(); conn.close()

def db_seen(headline):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM events WHERE headline=?", (headline,)).fetchone()
    conn.close(); return row is not None

def db_insert(source, headline, ticker=None, sid=None, direction=None, score=0):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO events (ts,source,ticker,strategy_id,direction,headline,score) VALUES (?,?,?,?,?,?,?)",
            (int(time.time()), source, ticker, sid, direction, headline, score))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Duplikat
    conn.close()

# ── Analyse ────────────────────────────────────────────────────────────────────
def analyse(headline):
    low = headline.lower()
    for kw, reason in MACRO_SIGNALS:
        if kw in low:
            return {"sid": None, "direction": "macro", "tickers": [], "score": 4, "reason": reason}
    best = None; best_score = 0
    for sid, strat in STRATEGIES.items():
        score = 0; direction = None
        for kw in strat["bullish"]:
            if kw in low: score += 2; direction = "bullish"; break
        if not direction:
            for kw in strat["bearish"]:
                if kw in low: score += 3; direction = "bearish"; break  # bearish höher gewichtet
        if score > best_score:
            best_score = score
            best = {"sid": sid, "direction": direction, "tickers": strat["tickers"],
                    "score": score, "reason": strat["name"]}
    return best if best and best_score >= 2 else {"sid": None, "direction": None, "score": 0, "tickers": [], "reason": None}

# ── Fetch ──────────────────────────────────────────────────────────────────────
def fetch_rss(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
        r = urllib.request.urlopen(req, timeout=8)
        html = r.read().decode("utf-8", errors="ignore")
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]>", html)
        if not titles: titles = re.findall(r"<title>(.*?)</title>", html)[1:]
        return [t.strip() for t in titles[:20] if t.strip()]
    except: return []

def fetch_google(query):
    try:
        enc = urllib.request.quote(query)
        url = f"https://news.google.com/rss/search?q={enc}&hl=de&gl=DE&ceid=DE:de"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
        r = urllib.request.urlopen(req, timeout=8)
        html = r.read().decode("utf-8", errors="ignore")
        return [t.strip() for t in re.findall(r"<title>(.*?)</title>", html)[1:8] if t.strip()]
    except: return []

def fetch_finnhub_news():
    headlines = []
    for ticker in ["NVDA","MSFT","PLTR","EQNR","AG"]:
        try:
            url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from=2026-03-12&to=2026-03-13&token={FINNHUB_KEY}"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
            r = urllib.request.urlopen(req, timeout=8)
            items = json.loads(r.read())
            for item in items[:5]:
                hl = item.get("headline","").strip()
                if hl: headlines.append((hl, f"Finnhub/{ticker}"))
        except: pass
    return headlines

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    init_db()
    all_headlines = []

    for feed in BLOOMBERG_FEEDS:
        for t in fetch_rss(feed): all_headlines.append((t, "Bloomberg"))
    for q in GOOGLE_QUERIES:
        for t in fetch_google(q): all_headlines.append((t, f"Google/{q[:15]}"))
    for t, src in fetch_finnhub_news(): all_headlines.append((t, src))

    new_events = []
    danger_events = []

    for headline, source in all_headlines:
        if db_seen(headline): continue
        r = analyse(headline)
        db_insert(source, headline, ticker=",".join(r["tickers"]) if r["tickers"] else None,
                  sid=r["sid"], direction=r["direction"], score=r["score"])
        if r["score"] >= 2:
            new_events.append({"headline": headline, "source": source, **r})
            if r["direction"] in ("bearish", "macro"):
                danger_events.append({"headline": headline, "source": source, **r})

    # Output für Cron-Agent
    result = {
        "ts": int(time.time()),
        "new_total": len(new_events),
        "danger_count": len(danger_events),
        "danger": danger_events[:5],   # max 5 für Haiku
        "bullish": [e for e in new_events if e["direction"] == "bullish"][:5],
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
