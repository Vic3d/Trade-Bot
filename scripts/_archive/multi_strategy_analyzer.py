#!/usr/bin/env python3
"""
Multi-Strategy Analyzer v2 — alle P0-P2 Fixes.

Änderungen v2:
  - 1Y Daten → EMA200 jetzt verfügbar
  - Volume-Confirmation für Trend-Signale
  - log_dimension_signals() wird aufgerufen (Lernschleife aktiv)
  - Onvista für ETF-Preise (korrekte EUR), US-Proxies für Technicals
  - Gewichteter Conviction Score (Trend+News höher gewichtet)
  - Earnings-Datum auto-fetch aus Yahoo
  - Klare FX-Konvertierung pro Ticker
"""

import sqlite3, json, os, time, urllib.request, re
from datetime import datetime, timezone, date

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")

# ── Portfolio-Konfiguration ────────────────────────────────────────────────────
# yahoo_tech: Ticker für historische Technicals (RSI/EMA/ATR/Volume)
# yahoo_fx:   FX-Paar um auf EUR zu kommen (None = schon EUR)
# onvista:    URL für aktuellen Kurs wenn yahoo_price nicht stimmt
PORTFOLIO = {
    # Einzelaktien
    "NVDA":    {"name": "Nvidia",               "entry": 167.88, "stop": 153.0,  "strategy": 3,
                "yahoo_tech": "NVDA",    "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "earnings": None},
    "MSFT":    {"name": "Microsoft",            "entry": 351.85, "stop": 338.0,  "strategy": 3,
                "yahoo_tech": "MSFT",    "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "earnings": None},
    "PLTR":    {"name": "Palantir",             "entry": 132.11, "stop": 127.0,  "strategy": 3,
                "yahoo_tech": "PLTR",    "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "earnings": None},
    "EQNR":    {"name": "Equinor ASA",          "entry": 27.04,  "stop": 27.0,   "strategy": 1,
                "yahoo_tech": "EQNR.OL", "yahoo_fx": "EURNOK=X", "fx_mode": "divnok",
                "earnings": None},
    "BAYN.DE": {"name": "Bayer AG",             "entry": 39.95,  "stop": 38.0,   "strategy": None,
                "yahoo_tech": "BAYN.DE", "yahoo_fx": None, "fx_mode": None,
                "onvista": "https://www.onvista.de/aktien/Bayer-Aktie-DE000BAY0017",
                "earnings": None},
    "RIO.L":   {"name": "Rio Tinto",            "entry": 76.92,  "stop": 73.0,   "strategy": 5,
                "yahoo_tech": "RIO.L",   "yahoo_fx": "GBPEUR=X", "fx_mode": "gbp",
                "earnings": None},
    # Watchlist
    "RHM.DE":  {"name": "Rheinmetall AG",       "entry": None,   "stop": None,   "strategy": 2,
                "yahoo_tech": "RHM.DE",  "yahoo_fx": None, "fx_mode": None,
                "earnings": None},
    "AG":      {"name": "First Majestic Silver","entry": None,   "stop": 20.5,   "strategy": 4,
                "yahoo_tech": "AG",      "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "earnings": None},
    # ETFs — Onvista für Preis, US/EU-Proxy für Technicals
    "A2QQ9R":  {"name": "Invesco Solar Energy ETF",   "entry": 22.40, "stop": None,  "strategy": 6,
                "yahoo_tech": "TAN",     "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "onvista_wkn": "A2QQ9R", "earnings": None},
    "A3D42Y":  {"name": "VanEck Oil Services ETF",    "entry": 27.91, "stop": 24.0,  "strategy": 1,
                "yahoo_tech": "OIH",     "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "onvista_wkn": "A3D42Y", "earnings": None},
    "A14WU5":  {"name": "L&G Cyber Security ETF",     "entry": 28.83, "stop": 25.95, "strategy": 3,
                "yahoo_tech": "ISPY.L",  "yahoo_fx": "GBPEUR=X", "fx_mode": "gbp",
                "onvista_wkn": "A14WU5", "earnings": None},
    "A2DWAW":  {"name": "iShares Biotechnology ETF",  "entry": 7.00,  "stop": 6.30,  "strategy": 7,
                "yahoo_tech": "IBB",     "yahoo_fx": "EURUSD=X", "fx_mode": "div",
                "onvista_wkn": "A2DWAW", "earnings": None},
}

# Conviction-Gewichte (empirisch, bis Daten vorliegen)
# Höhere Gewichtung = stärkerer Prädiktor laut Theorie
DIMENSION_WEIGHTS = {
    "trend":         1.5,   # EMA-Struktur — stärkster struktureller Indikator
    "news":          1.5,   # Katalysatoren — schnellster Marktmover
    "macro":         1.0,   # VIX-Regime — wichtig aber langsamer
    "mean_reversion":0.7,   # RSI — oft Gegenwind, schwächerer Prädiktor
    "event":         0.8,   # Earnings — wichtig aber selten
    "risk":          1.0,   # ATR/Stop — Risk-Management, nicht Richtung
    "volume":        1.3,   # Volumen-Bestätigung — NEU in v2
}


# ── Yahoo-Daten-Fetch ──────────────────────────────────────────────────────────
def _yahoo_fetch(ticker: str, range_: str = "1y") -> dict:
    """Holt OHLCV + Meta von Yahoo Finance."""
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={range_}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        res = d["chart"]["result"][0]
        meta = res["meta"]
        q = res.get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in q.get("close", []) if c is not None]
        volumes = [v for v in q.get("volume", []) if v is not None]
        return {
            "price": meta["regularMarketPrice"],
            "prev_close": closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose", meta["regularMarketPrice"]),
            "currency": meta.get("currency", "?"),
            "closes": closes,
            "volumes": volumes,
            "earnings_ts": meta.get("earningsTimestamp"),
        }
    except Exception as e:
        return {"error": str(e)}


def _onvista_price(wkn: str) -> float | None:
    """Holt aktuellen Kurs von Onvista für DE-ETFs."""
    try:
        url = f"https://www.onvista.de/suche/?searchValue={wkn}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")
        prices = re.findall(r'"last":([0-9.]+)', html)
        return float(prices[0]) if prices else None
    except:
        return None


def _get_fx(fx_pair: str) -> float:
    """Holt FX-Kurs von Yahoo."""
    try:
        d = _yahoo_fetch(fx_pair, range_="5d")
        return d.get("price", 1.0)
    except:
        return 1.0


def _to_eur(price: float, fx_mode: str, fx_rate: float) -> float:
    """Konvertiert Preis auf EUR."""
    if fx_mode == "div":     return price / fx_rate          # USD/NOK → EUR
    if fx_mode == "divnok":  return price / fx_rate          # NOK → EUR
    if fx_mode == "gbp":     return (price / 100) * fx_rate  # GBp → EUR (GBPEUR)
    return price  # schon EUR


# ── Technische Indikatoren ─────────────────────────────────────────────────────
def _ema(closes: list, n: int) -> float | None:
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    e = closes[-n]
    for p in closes[-n + 1:]:
        e = p * k + e * (1 - k)
    return round(e, 4)


def _rsi(closes: list, n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    d = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [x for x in d[-n:] if x > 0]
    losses = [-x for x in d[-n:] if x < 0]
    ag = sum(gains) / n if gains else 0
    al = sum(losses) / n if losses else 0.0001
    return round(100 - (100 / (1 + ag / al)), 1)


def _atr(closes: list, n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    tr = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
    return round(sum(tr[-n:]) / n, 4)


def _volume_signal(volumes: list, n: int = 20) -> dict:
    """Vergleicht aktuelles Volumen mit 20T-Durchschnitt."""
    if len(volumes) < n + 1:
        return {"signal": "neutral", "ratio": None, "reason": "Zu wenig Daten"}
    avg_vol = sum(volumes[-n-1:-1]) / n
    curr_vol = volumes[-1]
    ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
    if ratio >= 1.5:
        return {"signal": "bullish", "ratio": round(ratio, 2),
                "reason": f"Volumen {ratio:.1f}× über 20T-Schnitt — Bestätigung ✅"}
    elif ratio <= 0.5:
        return {"signal": "bearish", "ratio": round(ratio, 2),
                "reason": f"Volumen {ratio:.1f}× unter 20T-Schnitt — Schwache Bewegung ⚠️"}
    else:
        return {"signal": "neutral", "ratio": round(ratio, 2),
                "reason": f"Volumen normal ({ratio:.1f}×)"}


# ── DB-Funktionen ──────────────────────────────────────────────────────────────
def _get_vix() -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT vix, regime, regime_score FROM macro_context ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return {"vix": row[0], "regime": row[1], "score": row[2]} if row else {}
    except:
        return {}


def _get_news_signal(ticker: str, lookback_min: int = 240) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        cutoff = int(time.time()) - (lookback_min * 60)
        # Suche nach Ticker UND ETF-WKN
        rows = conn.execute("""
            SELECT direction, score, headline FROM events
            WHERE (ticker LIKE ? OR ticker LIKE ? OR headline LIKE ?)
              AND ts > ? AND score >= 2
            ORDER BY score DESC, ts DESC LIMIT 10
        """, (f"%{ticker}%", f"%{ticker.split('.')[0]}%",
               f"%{ticker.split('.')[0].lower()}%", cutoff)).fetchall()
        conn.close()
        if not rows:
            return {"direction": "neutral", "count": 0, "top": None}
        bull = sum(1 for r in rows if r[0] == "bullish")
        bear = sum(1 for r in rows if r[0] == "bearish")
        dominant = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"
        return {"direction": dominant, "count": len(rows), "bull": bull, "bear": bear,
                "top": rows[0][2][:80] if rows else None}
    except:
        return {"direction": "neutral", "count": 0}


def _log_dimension_signals(ticker: str, strategy_id: int, dimensions: dict, price_eur: float):
    """Speichert alle Dimension-Signale in DB für spätere Accuracy-Auswertung."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dimension_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT, strategy_id INTEGER, ts INTEGER,
                dimension TEXT, signal TEXT,
                price_at_signal REAL, price_4h REAL, price_24h REAL,
                outcome_4h TEXT, outcome_24h TEXT
            )
        """)
        ts = int(time.time())
        for dim_key, dim_data in dimensions.items():
            if dim_key == "volume":
                continue  # Volumen separat tracken
            conn.execute("""
                INSERT INTO dimension_signals
                (ticker, strategy_id, ts, dimension, signal, price_at_signal)
                VALUES (?,?,?,?,?,?)
            """, (ticker, strategy_id, ts, dim_key, dim_data.get("signal", "neutral"), price_eur))
        conn.commit()
        conn.close()
    except Exception as e:
        pass  # Lernschleife darf nie die Analyse blockieren


def _fetch_earnings_date(ticker: str, earnings_ts) -> str | None:
    """Extrahiert Earnings-Datum aus Yahoo-Timestamp."""
    if earnings_ts:
        try:
            d = date.fromtimestamp(earnings_ts)
            if d > date.today():
                return d.isoformat()
        except:
            pass
    return None


# ── Haupt-Analyse ──────────────────────────────────────────────────────────────
def analyze_ticker(ticker: str) -> dict:
    """Vollständige Multi-Strategie-Analyse für einen Ticker."""
    info = PORTFOLIO.get(ticker, {})
    yahoo_tech = info.get("yahoo_tech", ticker)
    fx_pair    = info.get("yahoo_fx")
    fx_mode    = info.get("fx_mode")
    entry      = info.get("entry")
    stop       = info.get("stop")
    strategy   = info.get("strategy")

    # 1Y Daten für EMA200
    data = _yahoo_fetch(yahoo_tech, range_="1y")
    if "error" in data or not data.get("closes"):
        return {"ticker": ticker, "error": data.get("error", "Keine Daten")}

    closes  = data["closes"]
    volumes = data.get("volumes", [])

    # FX-Konvertierung
    fx_rate = _get_fx(fx_pair) if fx_pair else 1.0
    current_eur = None

    # Für ETFs: Onvista-Preis bevorzugen
    wkn = info.get("onvista_wkn")
    if wkn:
        current_eur = _onvista_price(wkn)

    if current_eur is None:
        raw_price = data["price"]
        current_eur = round(_to_eur(raw_price, fx_mode, fx_rate), 2)

    # Technicals (auf Basis der Yahoo-Tech-Daten, skaliert)
    ema20  = _ema(closes, 20)
    ema50  = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    rsi14  = _rsi(closes, 14)
    atr14  = _atr(closes, 14)

    # ATR in EUR umrechnen
    if fx_mode in ("div", "divnok") and fx_rate and atr14:
        atr_eur = round(atr14 / fx_rate, 3)
    elif fx_mode == "gbp" and fx_rate and atr14:
        atr_eur = round((atr14 / 100) * fx_rate, 3)
    else:
        atr_eur = atr14

    # Day-change: letzte zwei Schlusskurse (zuverlässiger als chartPreviousClose bei 1y)
    if len(closes) >= 2:
        prev_raw = closes[-2]
        prev_eur = round(_to_eur(prev_raw, fx_mode, fx_rate), 2)
    else:
        prev_eur = current_eur
    day_change = (current_eur - prev_eur) / prev_eur * 100 if prev_eur else 0

    # Earnings aus Yahoo
    earnings_date = _fetch_earnings_date(ticker, data.get("earnings_ts")) or info.get("earnings")

    dimensions = {}

    # ── 1. TREND FOLLOWING ───────────────────────────────────────────────────
    td = {"name": "Trend Following"}
    if ema200 and ema50:
        if closes[-1] > ema50 > ema200:
            td["signal"] = "bullish"
            td["reason"] = f"Kurs > EMA50 > EMA200 — Aufwärtstrend intakt ✅"
        elif closes[-1] < ema50 < ema200:
            td["signal"] = "bearish"
            td["reason"] = f"Kurs < EMA50 < EMA200 — Abwärtstrend ❌"
        elif closes[-1] > ema200:
            td["signal"] = "neutral"
            td["reason"] = f"Über EMA200 aber unter EMA50 — Konsolidierung"
        else:
            td["signal"] = "bearish"
            td["reason"] = f"Unter EMA200 — strukturell schwach"
    elif ema50:
        td["signal"] = "bullish" if closes[-1] > ema50 else "bearish"
        td["reason"] = f"Kurs {'>' if closes[-1] > ema50 else '<'} EMA50 (EMA200 nicht verfügbar)"
    else:
        td["signal"] = "neutral"
        td["reason"] = "Zu wenig Daten"
    dimensions["trend"] = td

    # ── 2. VOLUMEN-BESTÄTIGUNG (NEU) ─────────────────────────────────────────
    vol_data = _volume_signal(volumes)
    vd = {"name": "Volumen"}
    vd["signal"] = vol_data["signal"]
    vd["reason"] = vol_data["reason"]
    vd["ratio"]  = vol_data.get("ratio")
    # Volumen-Signal verstärkt Trend: wenn Trend bullish + Volumen hoch → extra bullish
    if td["signal"] == "bullish" and vol_data["signal"] == "bullish":
        vd["reason"] += " | Trend + Volumen = starke Bestätigung 💪"
    elif td["signal"] == "bearish" and vol_data["signal"] == "bullish":
        vd["signal"] = "bearish"
        vd["reason"] += " | Sell-Volumen bestätigt Abwärtstrend"
    dimensions["volume"] = vd

    # ── 3. NEWS / CATALYST ───────────────────────────────────────────────────
    news = _get_news_signal(ticker)
    nd = {"name": "News/Catalyst"}
    if news["count"] == 0:
        nd["signal"] = "neutral"
        nd["reason"] = "Keine relevanten Headlines (letzte 4h)"
    else:
        nd["signal"] = news["direction"]
        nd["reason"] = f"{news['count']} Events ({news.get('bull',0)}× bull, {news.get('bear',0)}× bear)"
        if news.get("top"):
            nd["top_headline"] = news["top"]
    dimensions["news"] = nd

    # ── 4. MAKRO-REGIME ──────────────────────────────────────────────────────
    vix = _get_vix()
    md = {"name": "Makro-Regime (VIX)"}
    vix_val = vix.get("vix")
    regime  = vix.get("regime", "unknown")
    if regime == "green":
        md["signal"] = "bullish";   md["reason"] = f"VIX {vix_val:.1f} < 20 — Risk-On ✅"
    elif regime == "yellow":
        md["signal"] = "neutral";   md["reason"] = f"VIX {vix_val:.1f} (20–25) — erhöht ⚠️"
    elif regime == "orange":
        md["signal"] = "bearish";   md["reason"] = f"VIX {vix_val:.1f} (25–30) — Volatil 🟠"
    else:
        md["signal"] = "bearish";   md["reason"] = f"VIX {vix_val if vix_val else '?'} > 30 — Risk-Off 🔴"
    dimensions["macro"] = md

    # ── 5. MEAN REVERSION ────────────────────────────────────────────────────
    rv = {"name": "Mean Reversion (RSI)"}
    if rsi14:
        if rsi14 > 75:
            rv["signal"] = "bearish"; rv["reason"] = f"RSI {rsi14} — stark überkauft ⚠️"
        elif rsi14 > 65:
            rv["signal"] = "neutral"; rv["reason"] = f"RSI {rsi14} — leicht überkauft, Rücksetzer möglich"
        elif rsi14 < 25:
            rv["signal"] = "bullish"; rv["reason"] = f"RSI {rsi14} — stark überverkauft, Erholung möglich ✅"
        elif rsi14 < 35:
            rv["signal"] = "neutral"; rv["reason"] = f"RSI {rsi14} — überverkauft, kein klarer Boden"
        else:
            rv["signal"] = "neutral"; rv["reason"] = f"RSI {rsi14} — neutrales Terrain"
    else:
        rv["signal"] = "neutral"; rv["reason"] = "RSI nicht berechenbar"
    if ema20 and closes:
        dist = (closes[-1] - ema20) / ema20 * 100
        if abs(dist) > 12:
            rv["ema20_dist"] = f"{dist:+.1f}% von EMA20"
            if dist > 12:
                rv["signal"] = "bearish"; rv["reason"] += f" | +{dist:.0f}% über EMA20 — ausgedehnt"
    dimensions["mean_reversion"] = rv

    # ── 6. EVENT-DRIVEN ──────────────────────────────────────────────────────
    ev = {"name": "Event-Driven"}
    if earnings_date:
        try:
            edate = date.fromisoformat(earnings_date)
            days  = (edate - date.today()).days
            if 0 <= days <= 14:
                ev["signal"] = "bullish"; ev["reason"] = f"Earnings in {days}d ({earnings_date}) — Pre-Drift möglich"
            elif 15 <= days <= 45:
                ev["signal"] = "neutral"; ev["reason"] = f"Earnings in {days}d ({earnings_date})"
            elif days < 0:
                ev["signal"] = "neutral"; ev["reason"] = f"Post-Earnings ({-days}d her)"
            else:
                ev["signal"] = "neutral"; ev["reason"] = f"Earnings: {earnings_date} ({days}d)"
        except:
            ev["signal"] = "neutral"; ev["reason"] = f"Earnings: {earnings_date}"
    else:
        ev["signal"] = "neutral"; ev["reason"] = "Kein Earnings-Datum bekannt"
    dimensions["event"] = ev

    # ── 7. RISK / ATR ────────────────────────────────────────────────────────
    rk = {"name": "Risk/ATR"}
    if atr_eur:
        atr_stop_2x = round(current_eur - 2 * atr_eur, 2)
        atr_stop_1x = round(current_eur - 1 * atr_eur, 2)
        rk["atr_eur"]      = round(atr_eur, 2)
        rk["atr_stop_2x"]  = atr_stop_2x
        rk["reason"]       = f"ATR={atr_eur:.2f}€ | Stop-Vorschlag 2×ATR={atr_stop_2x}€"
        if not stop:
            rk["signal"] = "bearish"; rk["reason"] += " | 🔴 KEIN STOP"
        elif stop < atr_stop_2x - atr_eur:
            rk["signal"] = "neutral"; rk["reason"] += f" | Stop {stop}€ zu weit"
        elif stop > current_eur:
            rk["signal"] = "bearish"; rk["reason"] += f" | ⚠️ Stop {stop}€ über Kurs — würde jetzt auslösen!"
        else:
            margin = (current_eur - stop) / stop * 100
            if margin < 2:
                rk["signal"] = "bearish"; rk["reason"] += f" | ⚠️ Stop {stop}€ sehr eng ({margin:.1f}%)"
            else:
                rk["signal"] = "neutral"; rk["reason"] += f" | Stop {stop}€ OK ({margin:.1f}%)"
    else:
        rk["signal"] = "neutral"; rk["reason"] = "ATR nicht berechenbar"
    dimensions["risk"] = rk

    # ── GEWICHTETER CONVICTION SCORE ─────────────────────────────────────────
    signal_map = {"bullish": 1, "neutral": 0, "bearish": -1}
    weighted_score = 0.0
    raw_scores = {}
    for dim_key, dim_data in dimensions.items():
        w = DIMENSION_WEIGHTS.get(dim_key, 1.0)
        s = signal_map.get(dim_data.get("signal", "neutral"), 0)
        weighted_score += s * w
        raw_scores[dim_key] = s

    bull_count = sum(1 for s in raw_scores.values() if s > 0)
    bear_count = sum(1 for s in raw_scores.values() if s < 0)
    max_score  = sum(DIMENSION_WEIGHTS.values())

    if weighted_score >= max_score * 0.5:
        overall = "STRONG LONG"
    elif weighted_score >= max_score * 0.2:
        overall = "LONG"
    elif weighted_score <= -max_score * 0.5:
        overall = "STRONG SHORT/EXIT"
    elif weighted_score <= -max_score * 0.15:
        overall = "VORSICHT/HALTEN"
    else:
        overall = "NEUTRAL/ABWARTEN"

    result = {
        "ticker":          ticker,
        "name":            info.get("name", ticker),
        "current_price":   current_eur,
        "day_change_pct":  round(day_change, 2),
        "entry":           entry,
        "stop":            stop,
        "pnl_pct":         round((current_eur - entry) / entry * 100, 1) if entry else None,
        "dimensions":      dimensions,
        "weighted_score":  round(weighted_score, 2),
        "total_score":     sum(raw_scores.values()),
        "bull_count":      bull_count,
        "bear_count":      bear_count,
        "overall":         overall,
        "earnings":        earnings_date,
        "atr_eur":         atr_eur,
    }

    # Lernschleife: Signals in DB speichern
    _log_dimension_signals(ticker, strategy or 0, dimensions, current_eur)

    return result


def format_analysis(result: dict) -> str:
    """Formatiert Analyse für Discord."""
    if "error" in result:
        return f"**{result['ticker']}**: Fehler — {result['error']}"

    ticker = result["ticker"]
    name   = result["name"]
    price  = result["current_price"]
    chg    = result["day_change_pct"]
    pnl    = result.get("pnl_pct")
    ws     = result["weighted_score"]
    overall= result["overall"]
    bull   = result["bull_count"]
    bear   = result["bear_count"]

    pnl_str = f" | P&L: {pnl:+.1f}%" if pnl is not None else ""
    chg_e   = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"

    lines = [
        f"**{name} ({ticker})** {chg_e} {price:.2f}€ ({chg:+.1f}%){pnl_str}",
        f"→ **{overall}** | Score: {ws:+.1f} | {bull}× bullish / {bear}× bearish",
    ]
    dim_e = {"bullish": "✅", "neutral": "⚪", "bearish": "⚠️"}
    for key, dim in result["dimensions"].items():
        w    = DIMENSION_WEIGHTS.get(key, 1.0)
        e    = dim_e.get(dim["signal"], "—")
        vol_ratio = f" ({dim.get('ratio',''):.1f}×)" if key == "volume" and dim.get("ratio") else ""
        lines.append(f"  {e} **{dim['name']}** (×{w}): {dim['reason']}{vol_ratio}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["EQNR", "NVDA", "BAYN.DE"]
    for t in tickers:
        print(f"\n📊 Analysiere {t}...")
        r = analyze_ticker(t)
        print(format_analysis(r))
        print()
