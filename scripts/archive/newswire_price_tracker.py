#!/usr/bin/env python3
"""
NewsWire Price Tracker — schreibt Kurse zu Events nach.
Läuft als Cron: alle 30 Min während Handelszeit.

Für jedes Event mit score >= 2 und ticker != None:
  - price_at_event: wenn noch nicht gesetzt, hole aktuellen Kurs
  - price_4h_later: wenn ts + 4h vergangen, hole Kurs nach
  - price_1d_later: wenn ts + 24h vergangen, hole Kurs nach

Damit entsteht eine Datenbank: News → Kurs-Reaktion.
"""

import sqlite3, json, time, urllib.request, re, os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")

# Ticker → Yahoo Finance Symbol
YAHOO_MAP = {
    "NVDA":    "NVDA",
    "MSFT":    "MSFT",
    "PLTR":    "PLTR",
    "EQNR":    "EQNR.OL",    # NOK, später durch EURNOK dividieren
    "AG":      "AG",
    "BAYN.DE": "BAYN.DE",
    "RHM.DE":  "RHM.DE",
    "DR0.DE":  "DR0.DE",
    "RIO.L":   "RIO.L",
    "ISPA.DE": "ISPA.DE",
}

# Für FX-Umrechnung
FX_PAIRS = ["EURUSD=X", "EURNOK=X", "GBPEUR=X"]

_fx_cache = {}
_price_cache = {}
_cache_ts = 0

def refresh_cache():
    global _cache_ts
    now = time.time()
    if now - _cache_ts < 120:  # Max alle 2 Min neu holen
        return
    _cache_ts = now

    # FX
    for pair in FX_PAIRS:
        try:
            price = yahoo_price(pair)
            if price:
                _fx_cache[pair] = price
        except:
            pass

def yahoo_price(ticker: str) -> float | None:
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        return d["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        return None

def onvista_price(isin_url: str) -> float | None:
    try:
        req = urllib.request.Request(isin_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")
        prices = re.findall(r'"last":([0-9.]+)', html)
        return float(prices[0]) if prices else None
    except:
        return None

ONVISTA_URLS = {
    "BAYN.DE": "https://www.onvista.de/aktien/Bayer-Aktie-DE000BAY0017",
    "RHM.DE":  "https://www.onvista.de/aktien/Rheinmetall-AG-Aktie-DE0007030009",
    "DR0.DE":  "https://www.onvista.de/aktien/Deutsche-Rohstoff-Aktie-DE000A0XYG76",
}

def get_price_eur(ticker: str) -> float | None:
    """Holt Kurs in EUR. Konvertiert NOK/GBp automatisch."""
    refresh_cache()

    # DE-Aktien via Onvista (genauer)
    if ticker in ONVISTA_URLS:
        return onvista_price(ONVISTA_URLS[ticker])

    yahoo_sym = YAHOO_MAP.get(ticker, ticker)
    price = yahoo_price(yahoo_sym)
    if price is None:
        return None

    # EQNR.OL → NOK ÷ EURNOK
    if ticker == "EQNR":
        eurnok = _fx_cache.get("EURNOK=X", 11.8)
        return price / eurnok

    # RIO.L → GBp ÷ 100 × GBPEUR
    if ticker == "RIO.L":
        gbpeur = _fx_cache.get("GBPEUR=X", 1.17)
        return (price / 100) * gbpeur

    # US-Aktien → USD ÷ EURUSD
    if ticker in ["NVDA", "MSFT", "PLTR", "AG"]:
        eurusd = _fx_cache.get("EURUSD=X", 1.08)
        return price / eurusd

    return price  # Bereits in EUR (ISPA.DE etc.)


def fetch_macro_context() -> dict:
    """Holt VIX + DXY + Brent für Regime-Awareness."""
    ctx = {}
    pairs = {"vix": "^VIX", "dxy": "DX-Y.NYB", "brent": "BZ=F"}
    for key, sym in pairs.items():
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.load(r)
            ctx[key] = d["chart"]["result"][0]["meta"]["regularMarketPrice"]
        except:
            ctx[key] = None
    # VIX Regime: green/yellow/orange/red
    vix = ctx.get("vix")
    if vix:
        ctx["regime"] = "green" if vix < 20 else "yellow" if vix < 25 else "orange" if vix < 30 else "red"
        ctx["regime_score"] = 1 if vix < 20 else 0 if vix < 25 else -1 if vix < 30 else -2
    return ctx


def save_macro_context(ctx: dict):
    """Speichert Makro-Kontext in macro_context-Tabelle."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_context (
            ts INTEGER PRIMARY KEY,
            vix REAL, dxy REAL, brent REAL,
            regime TEXT, regime_score INTEGER
        )
    """)
    conn.execute("""
        INSERT OR REPLACE INTO macro_context (ts, vix, dxy, brent, regime, regime_score)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (int(time.time()), ctx.get("vix"), ctx.get("dxy"), ctx.get("brent"),
          ctx.get("regime"), ctx.get("regime_score")))
    conn.commit()
    conn.close()


def run():
    # Makro-Kontext immer mitschreiben
    ctx = fetch_macro_context()
    save_macro_context(ctx)
    vix_str = f"VIX {ctx.get('vix', '?')} ({ctx.get('regime', '?')})"
    print(f"Makro: {vix_str} | DXY {ctx.get('dxy', '?')} | Brent {ctx.get('brent', '?')}")

    conn = sqlite3.connect(DB_PATH)
    now = int(time.time())
    updated = 0
    checked = 0

    # Events mit score >= 2, bekanntem Ticker, noch nicht vollständig geprüft
    rows = conn.execute("""
        SELECT id, ts, ticker, price_at_event, price_4h_later, price_1d_later
        FROM events
        WHERE score >= 2
          AND ticker IS NOT NULL
          AND ticker != ''
          AND price_checked = 0
        ORDER BY ts DESC
        LIMIT 100
    """).fetchall()

    for eid, ts, ticker_raw, price_at, price_4h, price_1d in rows:
        # Ticker ggf. kommagetrennt (wenn mehrere) → ersten nehmen
        ticker = ticker_raw.split(",")[0].strip()
        if ticker not in YAHOO_MAP and ticker not in ONVISTA_URLS:
            continue

        checked += 1
        needs_update = False
        age = now - ts

        # price_at_event: sofort setzen wenn noch leer
        if price_at is None and age < 3600:  # Nur wenn Event < 1h alt
            p = get_price_eur(ticker)
            if p:
                conn.execute("UPDATE events SET price_at_event=? WHERE id=?", (round(p, 3), eid))
                needs_update = True

        # price_4h_later: wenn Event > 4h alt und noch nicht gesetzt
        if price_4h is None and age >= 14400:  # 4h = 14400s
            p = get_price_eur(ticker)
            if p:
                conn.execute("UPDATE events SET price_4h_later=? WHERE id=?", (round(p, 3), eid))
                needs_update = True

        # price_1d_later: wenn Event > 24h alt
        if price_1d is None and age >= 86400:
            p = get_price_eur(ticker)
            if p:
                conn.execute("UPDATE events SET price_1d_later=?, price_checked=1 WHERE id=?",
                             (round(p, 3), eid))
                needs_update = True
        elif price_4h is not None and price_1d is not None:
            conn.execute("UPDATE events SET price_checked=1 WHERE id=?", (eid,))

        # outcome berechnen sobald 4h-Preis da ist
        if price_at is not None and price_4h is not None:
            # Vorhersage vs. tatsächliche Bewegung
            actual_move = (price_4h - price_at) / price_at  # z.B. +0.023 = +2.3%
            row_dir = conn.execute("SELECT direction FROM events WHERE id=?", (eid,)).fetchone()
            if row_dir:
                direction = row_dir[0]
                if direction == "bullish" and actual_move > 0.005:    # >+0.5%
                    conn.execute("UPDATE events SET outcome=1 WHERE id=?", (eid,))
                elif direction == "bearish" and actual_move < -0.005:  # <-0.5%
                    conn.execute("UPDATE events SET outcome=1 WHERE id=?", (eid,))
                elif direction in ("bullish", "bearish"):
                    conn.execute("UPDATE events SET outcome=0 WHERE id=?", (eid,))
            needs_update = True

        if needs_update:
            updated += 1

    conn.commit()
    conn.close()

    print(f"Price Tracker: {checked} Events geprüft, {updated} Kurse aktualisiert")

    # Zeige Qualität der bisherigen Daten
    conn = sqlite3.connect(DB_PATH)
    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN price_at_event IS NOT NULL THEN 1 ELSE 0 END) as has_entry,
            SUM(CASE WHEN price_4h_later IS NOT NULL THEN 1 ELSE 0 END) as has_4h,
            SUM(CASE WHEN price_1d_later IS NOT NULL THEN 1 ELSE 0 END) as has_1d
        FROM events WHERE score >= 2 AND ticker IS NOT NULL AND ticker != ''
    """).fetchone()
    conn.close()
    print(f"DB-Qualität: {stats[0]} Events | entry-Preis: {stats[1]} | 4h-Preis: {stats[2]} | 1d-Preis: {stats[3]}")


if __name__ == "__main__":
    run()
