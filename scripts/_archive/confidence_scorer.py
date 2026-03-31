#!/usr/bin/env python3
"""
Confidence Scorer — Phase 2
==============================
Berechnet einen Multi-Faktor-Konfidenz-Score (0-10) für Öl/EQNR-Einstiege.

Faktoren:
  +2  Bullisher Options-Flow (Vol/OI >3x auf Öl-Ticker)
  +2  Iran/Hormuz Eskalation (aktuelle Keywords)
  +1  Brent Crude >$100
  +1  EQNR Momentum positiv (Kurs > EMA20)
  +1  Tanker/Lieferketten-News (Hormuz, Rotes Meer etc.)
  +1  Brent-WTI Spread ausweitet (>$5)
  +1  VIX < 20 (ruhiger Markt)

Schwellen:
  3-4 Punkte → 🟡 Watchlist, kein Kauf
  5-6 Punkte → 🟠 Überlegung, halbe Position
  7+  Punkte → 🔴 STARKER EINSTIEG, volle Position
"""

import json
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE   = Path('/data/.openclaw/workspace')
STATE_PATH  = WORKSPACE / 'data/options_flow_state.json'
SCORE_PATH  = WORKSPACE / 'data/confidence_score.json'

IRAN_KEYWORDS    = ["iran", "hormuz", "strait", "persian gulf", "nuclear", "ultimatum",
                    "sanctions", "missiles", "attack", "retaliation"]
TANKER_KEYWORDS  = ["tanker", "shipping", "red sea", "hormuz", "suez", "cargo", "crude shipment",
                    "oil delivery", "lieferkette", "blockade"]


# ── Marktdaten ───────────────────────────────────────────────────────────────

def _yahoo(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=30d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        result = d['chart']['result'][0]
        meta   = result['meta']
        closes = result['indicators']['quote'][0].get('close', [])
        closes = [c for c in closes if c is not None]
        return meta['regularMarketPrice'], closes
    except Exception as e:
        print(f"  ⚠️ Yahoo {ticker}: {e}")
        return None, []

def ema(closes, period=20):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = closes[0]
    for c in closes[1:]:
        val = c * k + val * (1 - k)
    return val

def check_options_flow() -> tuple[int, str]:
    """Gibt Punkte für aktiven bullischen Options-Flow zurück."""
    if not STATE_PATH.exists():
        return 0, "Kein Scanner-State"
    with open(STATE_PATH) as f:
        state = json.load(f)
    alerted = state.get("alerted", {})
    if not alerted:
        return 0, "Kein aktiver Flow"
    
    # Prüfe ob aktuelle Alarme (Volume > 1000)
    high_vol = [(k, v) for k, v in alerted.items() if v >= 1000]
    if high_vol:
        top = sorted(high_vol, key=lambda x: x[1], reverse=True)[0]
        return 2, f"Aktiver Flow: {top[0]} Vol={top[1]:,}"
    return 0, "Kein signifikanter Flow"

def check_iran_news() -> tuple[int, str]:
    """Prüft aktuelle Iran/Hormuz-Nachrichten via Google News RSS."""
    try:
        url = "https://news.google.com/rss/search?q=iran+hormuz+oil&hl=en&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        xml = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
        
        titles = re.findall(r'<title>(.*?)</title>', xml)[2:7]  # erste 2 überspringen (Feed-Titel)
        text   = " ".join(titles).lower()
        
        matches = [kw for kw in IRAN_KEYWORDS if kw in text]
        if len(matches) >= 3:
            return 2, f"Iran-Eskalation: {', '.join(matches[:3])}"
        elif len(matches) >= 1:
            return 1, f"Iran-News: {', '.join(matches[:2])}"
        return 0, "Keine Iran-Eskalation"
    except Exception as e:
        return 0, f"News-Fehler: {e}"

def check_tanker_news() -> tuple[int, str]:
    """Prüft Tanker/Lieferketten-News."""
    try:
        url = "https://news.google.com/rss/search?q=tanker+oil+hormuz+shipping&hl=en&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        xml = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
        
        titles = re.findall(r'<title>(.*?)</title>', xml)[2:7]
        text   = " ".join(titles).lower()
        
        matches = [kw for kw in TANKER_KEYWORDS if kw in text]
        if matches:
            return 1, f"Tanker-News: {', '.join(matches[:2])}"
        return 0, "Keine Tanker-News"
    except Exception as e:
        return 0, f"News-Fehler: {e}"


# ── Score-Berechnung ──────────────────────────────────────────────────────────

def calculate_score() -> dict:
    """Berechnet den Gesamt-Score + Begründungen."""
    print(f"[Confidence Scorer] {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    score    = 0
    factors  = []
    details  = {}

    # Faktor 1: Options-Flow (+2)
    pts, reason = check_options_flow()
    score += pts
    factors.append({"factor": "Options-Flow", "points": pts, "max": 2, "reason": reason})
    details["options_flow"] = pts
    print(f"  Options-Flow:    {pts}/2 — {reason}")

    # Faktor 2: Iran/Hormuz (+2)
    pts, reason = check_iran_news()
    score += pts
    factors.append({"factor": "Iran-Eskalation", "points": pts, "max": 2, "reason": reason})
    details["iran"] = pts
    print(f"  Iran-Eskalation: {pts}/2 — {reason}")

    # Faktor 3: Brent >$100 (+1)
    brent_price, _ = _yahoo("BZ=F")
    if brent_price and brent_price > 100:
        score += 1
        reasons = f"Brent ${brent_price:.2f} > $100"
        factors.append({"factor": "Brent >$100", "points": 1, "max": 1, "reason": reasons})
        details["brent"] = 1
        print(f"  Brent >$100:     1/1 — {reasons}")
    else:
        factors.append({"factor": "Brent >$100", "points": 0, "max": 1, "reason": f"Brent ${brent_price:.2f}" if brent_price else "n/a"})
        details["brent"] = 0
        print(f"  Brent >$100:     0/1 — {brent_price}")

    # Faktor 4: EQNR Momentum (Kurs > EMA20) (+1)
    eqnr_nok, eqnr_closes = _yahoo("EQNR.OL")
    eqnr_ema20 = ema(eqnr_closes, 20)
    if eqnr_nok and eqnr_ema20 and eqnr_nok > eqnr_ema20:
        score += 1
        reason = f"EQNR {eqnr_nok:.1f} > EMA20 {eqnr_ema20:.1f}"
        factors.append({"factor": "EQNR Momentum", "points": 1, "max": 1, "reason": reason})
        details["eqnr_momentum"] = 1
        print(f"  EQNR Momentum:   1/1 — {reason}")
    else:
        factors.append({"factor": "EQNR Momentum", "points": 0, "max": 1,
                        "reason": f"EQNR {eqnr_nok} vs EMA20 {eqnr_ema20:.1f if eqnr_ema20 else 'n/a'}"})
        details["eqnr_momentum"] = 0
        print(f"  EQNR Momentum:   0/1")

    # Faktor 5: Tanker-News (+1)
    pts, reason = check_tanker_news()
    score += pts
    factors.append({"factor": "Tanker-News", "points": pts, "max": 1, "reason": reason})
    details["tanker"] = pts
    print(f"  Tanker-News:     {pts}/1 — {reason}")

    # Faktor 6: Brent-WTI Spread >$5 (+1)
    wti_price, _ = _yahoo("CL=F")
    if brent_price and wti_price:
        spread = brent_price - wti_price
        if spread > 5:
            score += 1
            reason = f"Spread ${spread:.2f} > $5"
            factors.append({"factor": "Brent-WTI Spread", "points": 1, "max": 1, "reason": reason})
            details["brent_wti_spread"] = 1
            print(f"  Brent-WTI Spread: 1/1 — {reason}")
        else:
            factors.append({"factor": "Brent-WTI Spread", "points": 0, "max": 1, "reason": f"Spread ${spread:.2f}"})
            details["brent_wti_spread"] = 0
            print(f"  Brent-WTI Spread: 0/1 — Spread ${spread:.2f} ≤ $5")
    else:
        factors.append({"factor": "Brent-WTI Spread", "points": 0, "max": 1, "reason": "n/a"})
        details["brent_wti_spread"] = 0

    # Faktor 7: VIX < 20 (+1)
    vix, _ = _yahoo("^VIX")
    if vix and vix < 20:
        score += 1
        reason = f"VIX {vix:.1f} < 20"
        factors.append({"factor": "VIX <20", "points": 1, "max": 1, "reason": reason})
        details["vix"] = 1
        print(f"  VIX <20:         1/1 — {reason}")
    else:
        factors.append({"factor": "VIX <20", "points": 0, "max": 1, "reason": f"VIX {vix:.1f}" if vix else "n/a"})
        details["vix"] = 0
        print(f"  VIX <20:         0/1 — VIX {vix}")

    # Gesamt-Bewertung
    if score >= 7:
        label   = "🔴 STARKER EINSTIEG"
        action  = "Volle Position vertretbar"
    elif score >= 5:
        label   = "🟠 ÜBERLEGUNG"
        action  = "Halbe Position, Stop setzen"
    elif score >= 3:
        label   = "🟡 WATCHLIST"
        action  = "Beobachten, kein Kauf"
    else:
        label   = "⚪ KEIN SIGNAL"
        action  = "Kein Handlungsbedarf"

    result = {
        "score":      score,
        "max_score":  10,
        "label":      label,
        "action":     action,
        "factors":    factors,
        "details":    details,
        "brent_usd":  brent_price,
        "wti_usd":    wti_price,
        "eqnr_nok":   eqnr_nok,
        "eqnr_ema20": round(eqnr_ema20, 2) if eqnr_ema20 else None,
        "vix":        vix,
        "updated":    datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }

    print(f"\n  ─────────────────────────────")
    print(f"  SCORE: {score}/10 → {label}")
    print(f"  ACTION: {action}")

    # Speichern
    with open(SCORE_PATH, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"  Gespeichert: data/confidence_score.json")

    return result


if __name__ == "__main__":
    calculate_score()
