#!/usr/bin/env python3
"""
NewsWire v2 — Strategie-bewusster Echtzeit News-Listener
Finnhub WebSocket (Push) + Bloomberg/Google RSS (5-Min-Polling)
Kennt das aktive Portfolio + Strategien → erkennt Chancen und Gefahren
"""

import asyncio
import websockets
import json
import sqlite3
import time
import urllib.request
import re
import os
import logging
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────

FINNHUB_KEY    = os.environ.get("FINNHUB_KEY",    "d6o6lm1r01qu09ciaj3gd6o6lm1r01qu09ciaj40")
DISCORD_WEBHOOK = os.environ.get("NEWSWIRE_WEBHOOK", "https://discord.com/api/webhooks/1481903416035770460/4FkmKMpoPVgoU1NcclX43FFhzKbDinXVXOMVFMuCk9lo8PUpe4Ycu_m9N25UCoJ_tAEZ")
DB_PATH        = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
LOG_PATH       = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.log")

# Finnhub WebSocket — nur US/Nasdaq-Ticker (EU nicht supportet)
WS_TICKERS = ["PLTR", "NVDA", "MSFT", "EQNR", "AG", "SHEL", "BAH", "AMD"]

RSS_INTERVAL   = 300   # 5 Minuten Bloomberg-Polling
RECONNECT_DELAY = 10

# ── Aktives Portfolio ──────────────────────────────────────────────────────────
# Format: ticker → { name, stop, entry, strategy }
PORTFOLIO = {
    "NVDA":    {"name": "Nvidia",              "stop": None,  "entry": 167.88, "strategy": 3},
    "MSFT":    {"name": "Microsoft",           "stop": 338.0, "entry": 351.85, "strategy": 3},
    "PLTR":    {"name": "Palantir",            "stop": 127.0, "entry": 132.11, "strategy": 3},
    "EQNR":    {"name": "Equinor ASA",         "stop": 27.0,  "entry": 27.04,  "strategy": 1},
    "BAYN.DE": {"name": "Bayer AG",            "stop": 38.0,  "entry": 39.95,  "strategy": None},
    "RIO.L":   {"name": "Rio Tinto",           "stop": 73.0,  "entry": 76.92,  "strategy": 5},
    "RHM.DE":  {"name": "Rheinmetall AG",      "stop": None,  "entry": None,   "strategy": 2},
    "DR0.DE":  {"name": "Deutsche Rohstoff AG","stop": None,  "entry": None,   "strategy": 1},
    "AG":      {"name": "First Majestic Silver","stop": 20.5, "entry": None,   "strategy": 4},
    "ISPA.DE": {"name": "Silber ETC",          "stop": None,  "entry": None,   "strategy": 4},
    # ── Leading Indicators (keine Positionen — nur für Korrelationsanalyse) ──
    "SHEL":    {"name": "Shell",               "stop": None,  "entry": None,   "strategy": 1},   # EQNR-Leader
    "BAH":     {"name": "Booz Allen Hamilton", "stop": None,  "entry": None,   "strategy": 3},   # PLTR-Leader
    "AMD":     {"name": "AMD",                 "stop": None,  "entry": None,   "strategy": 3},   # NVDA-Leader
    "ASML":    {"name": "ASML Holding",        "stop": None,  "entry": None,   "strategy": 3},   # Chip-Supply-Leader
    # ── Makro-Barometer (keine Positionen — Kontext) ──
    "GC=F":    {"name": "Gold Futures",        "stop": None,  "entry": None,   "strategy": 4},   # Safe Haven
    "CL=F":    {"name": "WTI Crude Oil",       "stop": None,  "entry": None,   "strategy": 1},   # Öl direkt
}

# ── Strategie-Map ──────────────────────────────────────────────────────────────
# Jede Strategie hat: bullish-keywords (Thesis stärkt) + bearish-keywords (Thesis schwächt)
STRATEGIES = {
    1: {
        "name": "Iran-Konflikt → Öl & Silber",
        "tickers": ["EQNR", "DR0.DE"],
        "bullish": [
            "hormuz", "strait of hormuz", "iran attack", "oil supply disruption",
            "iran strikes", "tanker attack", "gulf escalation", "brent surges",
            "oil hits", "iran missile", "iran drone", "hezbollah", "iran war",
            "oil supply cut", "iran blockade", "khamenei", "irgc",
        ],
        "bearish": [
            "iran ceasefire", "hormuz open", "iran deal", "iran negotiations",
            "iran peace", "oil supply restored", "trump iran deal",
            "waffenstillstand iran", "macron iran", "iran deescalation",
            "strategic reserve release", "iea release", "opec increase",
            "russia oil", "venezuela oil",
        ],
        "neutral": ["iran", "hormuz", "brent", "crude oil", "opec"],
    },
    2: {
        "name": "Europäische Aufrüstung → Rüstung",
        "tickers": ["RHM.DE"],
        "bullish": [
            "rheinmetall", "defense spending", "nato budget", "military spending",
            "rüstung", "aufrüstung", "ukraine weapons", "defense contract",
            "nato 3%", "bundeswehr", "european defense", "rearmament",
        ],
        "bearish": [
            "ceasefire ukraine", "peace ukraine", "nato spending cut",
            "defense budget cut", "waffenstillstand ukraine",
        ],
        "neutral": ["rheinmetall", "defense", "nato", "military"],
    },
    3: {
        "name": "KI-Infrastruktur → Halbleiter",
        "tickers": ["NVDA", "MSFT", "PLTR"],
        "bullish": [
            "nvidia earnings", "datacenter expansion", "ai spending",
            "palantir contract", "microsoft ai", "chip demand",
            "vix below 20", "ai infrastructure", "gpu demand",
            "palantir pentagon", "pltr contract", "nvda beat",
        ],
        "bearish": [
            "nvidia export ban", "chip ban china", "vix above 30",
            "pentagon ai ban", "palantir investigation", "nvda miss",
            "ai spending cut", "helium supply", "chip shortage supply",
            "microsoft layoffs", "burry short palantir", "pltr doge",
        ],
        "neutral": ["nvidia", "palantir", "microsoft", "semiconductor", "ai chip"],
    },
    4: {
        "name": "Geopolitik → Silber/Gold",
        "tickers": ["AG", "ISPA.DE"],
        "bullish": [
            "silver surges", "gold surges", "precious metals rally",
            "silver demand", "solar silver", "silver supply",
            "safe haven", "inflation spike", "first majestic beats",
        ],
        "bearish": [
            "silver falls", "gold drops", "usd strengthens",
            "fed rate hike", "silver supply glut", "precious metals sell",
        ],
        "neutral": ["silver", "gold", "first majestic", "precious metal"],
    },
    5: {
        "name": "Rohstoff-Superzyklus → Basismetalle",
        "tickers": ["RIO.L"],
        "bullish": [
            "copper surge", "rio tinto copper", "lithium demand",
            "ev demand", "copper supply", "rio tinto discovery",
            "bhp copper", "mining boom",
        ],
        "bearish": [
            "china iron ore", "rio tinto dividend cut", "copper falls",
            "china demand weak", "bhp restrictions", "iron ore falls",
        ],
        "neutral": ["rio tinto", "bhp", "copper", "lithium", "iron ore"],
    },
}

# Generelle Makro-Gefahren (portfolioübergreifend)
MACRO_DANGERS = [
    ("vix above 30", "⚠️ VIX-Alarm", "Tech-Positionen unter Druck"),
    ("vix surges", "⚠️ VIX-Alarm", "Markt-Panik"),
    ("fed rate hike", "⚠️ Fed-Alarm", "Zinserhöhung — alle Aktien unter Druck"),
    ("bank run", "🚨 Systemrisiko", "Bankenkrise"),
    ("market crash", "🚨 Crash-Alarm", "Breiter Markteinbruch"),
    ("circuit breaker", "🚨 Handelsstopp", "Börse ausgesetzt"),
    ("recession confirmed", "⚠️ Rezession", "Wirtschaftliche Abschwächung"),
    ("trump tariffs", "⚠️ Zölle", "Handelskonflikt-Eskalation"),
]

# Bloomberg RSS Feeds
BLOOMBERG_FEEDS = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://feeds.bloomberg.com/technology/news.rss",
    "https://feeds.bloomberg.com/politics/news.rss",
]

# Google News für DE/EU-Aktien
GOOGLE_NEWS_QUERIES = [
    ("Rheinmetall Aktie", "rheinmetall aktie"),
    ("Bayer Aktie", "bayer aktie"),
    ("Iran Hormuz Ölpreis", "iran hormuz ölpreis"),
]

# ── Logging ────────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
logging.getLogger().handlers = list({type(h): h for h in logging.getLogger().handlers}.values())
log = logging.getLogger("newswire")

# ── SQLite ─────────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            source TEXT,
            ticker TEXT,
            strategy_id INTEGER,
            direction TEXT,
            headline TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            alerted INTEGER DEFAULT 0,
            raw TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ticker ON events(ticker)")
    conn.commit()
    conn.close()

def db_seen(headline, window_s=3600):
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - window_s
    row = conn.execute(
        "SELECT id FROM events WHERE headline=? AND ts>?", (headline, cutoff)
    ).fetchone()
    if row:
        conn.close()
        return True
    # Fuzzy-Dedup: >80% Ähnlichkeit mit einem Headline der letzten 2h
    import difflib
    recent = conn.execute(
        "SELECT headline FROM events WHERE ts>?", (cutoff,)
    ).fetchall()
    conn.close()
    for (existing,) in recent:
        ratio = difflib.SequenceMatcher(None, headline[:120], existing[:120]).ratio()
        if ratio > 0.80:
            return True
    return False

def db_insert(source, headline, ticker=None, strategy_id=None, direction=None,
              score=0, alerted=0, raw=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO events (ts,source,ticker,strategy_id,direction,headline,score,alerted,raw) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (int(time.time()), source, ticker, strategy_id, direction,
         headline, score, alerted, json.dumps(raw) if raw else None)
    )
    conn.commit()
    conn.close()

# ── Strategie-Analyse ──────────────────────────────────────────────────────────

def analyse(headline: str) -> dict:
    """
    Gibt zurück:
      strategy_id, direction (bullish/bearish/neutral/macro),
      affected_tickers, score, label, reason
    """
    low = headline.lower()

    # Makro-Check zuerst
    for kw, label, reason in MACRO_DANGERS:
        if kw in low:
            return {
                "strategy_id": None,
                "direction": "macro",
                "affected_tickers": list(PORTFOLIO.keys()),
                "score": 3,
                "label": label,
                "reason": reason,
            }

    best = None
    best_score = 0

    for sid, strat in STRATEGIES.items():
        score = 0
        direction = None

        for kw in strat["bullish"]:
            if kw in low:
                score += 2
                direction = "bullish"
                break

        if not direction:
            for kw in strat["bearish"]:
                if kw in low:
                    score += 2
                    direction = "bearish"
                    break

        if not direction:
            for kw in strat["neutral"]:
                if kw in low:
                    score += 1
                    direction = "neutral"
                    break

        # Ticker-Direkttreffer
        for t in strat["tickers"]:
            if t.lower().replace(".de", "").replace(".l", "") in low:
                score += 1

        if score > best_score:
            best_score = score
            best = {
                "strategy_id": sid,
                "direction": direction or "neutral",
                "affected_tickers": strat["tickers"],
                "score": score,
                "label": strat["name"],
                "reason": None,
            }

    if best and best_score >= 1:
        return best

    return {"strategy_id": None, "direction": None, "score": 0,
            "affected_tickers": [], "label": None, "reason": None}

# ── Discord ────────────────────────────────────────────────────────────────────

_last_discord_send = 0

def discord_alert(headline: str, source: str, result: dict):
    global _last_discord_send
    gap = time.time() - _last_discord_send
    if gap < 2.0:
        time.sleep(2.0 - gap)

    direction = result.get("direction")
    score     = result.get("score", 0)
    label     = result.get("label", "")
    tickers   = result.get("affected_tickers", [])
    reason    = result.get("reason", "")

    # Emoji nach Richtung + Score
    if direction == "macro":
        emoji = "🚨"
    elif direction == "bearish":
        emoji = "🔴" if score >= 3 else "⚠️"
    elif direction == "bullish":
        emoji = "🟢" if score >= 3 else "📈"
    else:
        emoji = "📰"

    # Strategie-Tag
    strat_tag = f"**{label}**" if label else ""
    ticker_str = " ".join(f"`{t}`" for t in tickers) if tickers else ""
    dir_str = {"bullish": "✅ Thesis stärkt", "bearish": "❌ Thesis gefährdet",
               "neutral": "➡️ Neutral", "macro": "⚠️ Makro-Risiko"}.get(direction or "", "")

    lines = [f"{emoji} {strat_tag} {ticker_str}"]
    lines.append(f"**{headline}**")
    if dir_str:
        lines.append(dir_str)
    if reason:
        lines.append(f"_{reason}_")
    lines.append(f"*{source} — {datetime.now(timezone.utc).strftime('%H:%M UTC')}*")

    content = "\n".join(lines)

    try:
        data = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=data,
            headers={"Content-Type": "application/json",
                     "User-Agent": "DiscordBot (newswire, 2.0)"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=8)
        _last_discord_send = time.time()
        log.info(f"[{direction}] Discord sent: {headline[:70]}")
    except Exception as e:
        log.error(f"Discord error: {e}")

# ── RSS Poller ─────────────────────────────────────────────────────────────────

def fetch_rss_titles(url: str) -> list[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
        r = urllib.request.urlopen(req, timeout=10)
        content = r.read().decode("utf-8", errors="ignore")
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]>", content)
        if not titles:
            titles = re.findall(r"<title>(.*?)</title>", content)[1:]
        return [t.strip() for t in titles[:20] if t.strip()]
    except Exception as e:
        log.warning(f"RSS fetch error ({url}): {e}")
        return []

def fetch_google_news(query: str) -> list[str]:
    try:
        encoded = urllib.request.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=de&gl=DE&ceid=DE:de"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
        r = urllib.request.urlopen(req, timeout=10)
        content = r.read().decode("utf-8", errors="ignore")
        titles = re.findall(r"<title>(.*?)</title>", content)[1:8]
        return [t.strip() for t in titles if t.strip()]
    except Exception as e:
        log.warning(f"Google News error ({query}): {e}")
        return []

async def rss_poller():
    log.info("RSS Poller gestartet (Bloomberg + Google News)")
    while True:
        all_headlines = []

        for feed_url in BLOOMBERG_FEEDS:
            for title in fetch_rss_titles(feed_url):
                all_headlines.append((title, "Bloomberg RSS"))

        for label, query in GOOGLE_NEWS_QUERIES:
            for title in fetch_google_news(query):
                all_headlines.append((title, f"Google/{label}"))

        for headline, source in all_headlines:
            if db_seen(headline):
                continue
            result = analyse(headline)
            alerted = 0
            # Kein Discord-Push — nur DB-Log. Albert liest und entscheidet.
            db_insert(
                source=source,
                headline=headline,
                ticker=",".join(result["affected_tickers"]) if result["affected_tickers"] else None,
                strategy_id=result["strategy_id"],
                direction=result["direction"],
                score=result["score"],
                alerted=alerted,
            )

        log.info(f"RSS-Cycle: {len(all_headlines)} headlines verarbeitet")
        await asyncio.sleep(RSS_INTERVAL)

# ── Finnhub WebSocket ──────────────────────────────────────────────────────────

async def finnhub_ws():
    uri = f"wss://ws.finnhub.io?token={FINNHUB_KEY}"
    while True:
        try:
            log.info("Finnhub WebSocket: verbinde...")
            async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                for ticker in WS_TICKERS:
                    await ws.send(json.dumps({"type": "subscribe", "symbol": ticker}))
                    log.info(f"  subscribed: {ticker}")
                log.info("Finnhub WebSocket: verbunden ✅")

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        if msg.get("type") == "news":
                            for item in msg.get("data", []):
                                headline = item.get("headline", "").strip()
                                if not headline or db_seen(headline):
                                    continue
                                result = analyse(headline)
                                alerted = 0
                                # Kein Discord-Push — nur DB-Log. Albert liest und entscheidet.
                                db_insert(
                                    source="finnhub_ws",
                                    headline=headline,
                                    ticker=item.get("related"),
                                    strategy_id=result["strategy_id"],
                                    direction=result["direction"],
                                    score=result["score"],
                                    alerted=alerted,
                                    raw=item,
                                )
                        elif msg.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                    except Exception as e:
                        log.warning(f"Msg parse error: {e}")

        except Exception as e:
            delay = 60 if "429" in str(e) else RECONNECT_DELAY
            log.error(f"WS error: {e} — reconnect in {delay}s")
            await asyncio.sleep(delay)

# ── Startup-Summary ────────────────────────────────────────────────────────────

def send_startup_summary():
    """Kurze Bestätigung beim Start."""
    pos = [f"`{t}` {v['name']}" for t, v in PORTFOLIO.items() if v.get("entry")]
    watch = [f"`{t}` {v['name']}" for t, v in PORTFOLIO.items() if not v.get("entry")]
    lines = [
        "🔌 **NewsWire v2 gestartet**",
        f"📊 Positionen: {', '.join(pos)}",
        f"👁 Watchlist: {', '.join(watch)}",
        "🔴 bearish = Thesis gefährdet | 🟢 bullish = Thesis stärkt | ⚠️ Makro = alle",
    ]
    try:
        data = json.dumps({"content": "\n".join(lines)}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=data,
            headers={"Content-Type": "application/json",
                     "User-Agent": "DiscordBot (newswire, 2.0)"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        log.error(f"Startup summary error: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    log.info("🔌 NewsWire v2 starting — DB-only mode (kein Discord-Push)")
    init_db()
    # send_startup_summary() — deaktiviert, kein Discord-Spam
    await asyncio.gather(finnhub_ws(), rss_poller())

if __name__ == "__main__":
    asyncio.run(main())
