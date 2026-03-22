#!/usr/bin/env python3
"""
market_regime.py — Automatische Marktphasen-Klassifikation

Erkennt täglich den Marktmodus:
  TREND_UP    → DT1, DT4, DT9 bevorzugt
  TREND_DOWN  → Short-Strategien, Cash erhöhen
  RANGE       → DT2, DT5, DT7 bevorzugt
  CRASH       → Alle DT pausieren, nur PS1 aktiv

Methodik:
  - ADX > 25 + Kurs über MA20 → TREND_UP
  - ADX > 25 + Kurs unter MA20 → TREND_DOWN
  - ADX < 20 → RANGE
  - VIX > 35 + S&P unter 200-MA → CRASH

Schreibt nach: memory/market-regime.json
"""
import json, urllib.request, urllib.parse, math
from pathlib import Path
from datetime import datetime, timedelta

WS      = Path('/data/.openclaw/workspace')
OUT     = WS / 'memory/market-regime.json'

# DT-Strategien je Regime
REGIME_STRATEGIES = {
    'TREND_UP':   ['DT1', 'DT4', 'DT9'],
    'TREND_DOWN': ['DT4'],               # Nur News-Catalyst (Short-Setups), kein Momentum-Long
    'RANGE':      ['DT2', 'DT5', 'DT7'],
    'CRASH':      [],                    # Kein Day Trading bei Crash
}

# ── Datenabruf ──────────────────────────────────────────────

def yahoo_history(ticker, days=60):
    end   = int(datetime.now().timestamp())
    start = int((datetime.now() - timedelta(days=days)).timestamp())
    url   = (f"https://query2.finance.yahoo.com/v8/finance/chart/"
             f"{urllib.parse.quote(ticker)}?interval=1d&period1={start}&period2={end}")
    req   = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        r = d['chart']['result'][0]
        closes = [c for c in r['indicators']['quote'][0]['close'] if c]
        highs  = [h for h in r['indicators']['quote'][0].get('high', []) if h]
        lows   = [l for l in r['indicators']['quote'][0].get('low', [])  if l]
        return closes, highs, lows
    except Exception as e:
        print(f"  ⚠️ Yahoo {ticker}: {e}")
        return [], [], []

def yahoo_price(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return d['chart']['result'][0]['meta']['regularMarketPrice']
    except:
        return None

# ── Indikatoren ─────────────────────────────────────────────

def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calc_adx(highs, lows, closes, period=14):
    """Vereinfachter ADX (Average Directional Index)."""
    if len(closes) < period + 1:
        return None
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - highs[i-1], 0) if (h - highs[i-1]) > (lows[i-1] - l) else 0
        mdm = max(lows[i-1] - l, 0) if (lows[i-1] - l) > (h - highs[i-1]) else 0
        tr_list.append(tr); plus_dm.append(pdm); minus_dm.append(mdm)

    def smooth(lst, p):
        s = sum(lst[:p])
        result = [s]
        for v in lst[p:]:
            s = s - s/p + v
            result.append(s)
        return result

    atr   = smooth(tr_list, period)
    pdi   = smooth(plus_dm, period)
    mdi   = smooth(minus_dm, period)
    dx_list = []
    for a, p, m in zip(atr, pdi, mdi):
        if a == 0: continue
        pdi_v = 100 * p / a
        mdi_v = 100 * m / a
        dx = 100 * abs(pdi_v - mdi_v) / (pdi_v + mdi_v) if (pdi_v + mdi_v) > 0 else 0
        dx_list.append(dx)
    if len(dx_list) < period:
        return None
    return sum(dx_list[-period:]) / period

# ── Marktphasen-Klassifikation ──────────────────────────────

def classify_regime():
    print("🧭 MARKTPHASEN-KLASSIFIKATION")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Hauptindex: S&P 500 via SPY
    closes, highs, lows = yahoo_history('SPY', 250)
    vix  = yahoo_price('^VIX')
    spy  = yahoo_price('SPY')

    # Makro-Daten aus learning_system falls verfügbar
    macro_path = WS / 'memory/market-regime.json'
    prev = json.loads(macro_path.read_text()) if macro_path.exists() else {}

    if not closes or len(closes) < 30:
        print("  ⚠️ Zu wenig Daten — behalte letztes Regime")
        return prev.get('regime', 'RANGE')

    ma20  = calc_ma(closes, 20)
    ma200 = calc_ma(closes, 200) if len(closes) >= 200 else None
    adx   = calc_adx(highs, lows, closes, 14) if highs and lows else None
    current_price = closes[-1]

    print(f"  SPY: ${current_price:.1f} | MA20: ${ma20:.1f}" + (f" | MA200: ${ma200:.1f}" if ma200 else ""))
    print(f"  ADX: {adx:.1f}" if adx else "  ADX: N/A")
    print(f"  VIX: {vix:.1f}" if vix else "  VIX: N/A")

    # ── Regime-Entscheidung ──
    regime = 'RANGE'  # Default
    reason = []

    # CRASH: VIX > 35 + S&P unter 200-MA
    if vix and vix > 35 and ma200 and current_price < ma200:
        regime = 'CRASH'
        reason.append(f"VIX {vix:.1f} > 35 + SPY unter 200-MA")

    # TREND_DOWN: ADX > 25 + Kurs unter MA20
    elif adx and adx > 25 and current_price < ma20:
        regime = 'TREND_DOWN'
        reason.append(f"ADX {adx:.1f} > 25 + SPY unter MA20")

    # TREND_UP: ADX > 25 + Kurs über MA20
    elif adx and adx > 25 and current_price > ma20:
        regime = 'TREND_UP'
        reason.append(f"ADX {adx:.1f} > 25 + SPY über MA20")

    # RANGE: ADX < 20
    elif adx and adx < 20:
        regime = 'RANGE'
        reason.append(f"ADX {adx:.1f} < 20 (kein Trend)")

    else:
        reason.append(f"ADX {adx:.1f if adx else 'N/A'} — kein klares Signal")

    # Aktive DT-Strategien für dieses Regime
    active_dt = REGIME_STRATEGIES.get(regime, [])

    # Regime-Change erkennen
    prev_regime = prev.get('regime', 'UNBEKANNT')
    changed = prev_regime != regime

    if changed:
        print(f"  🔄 REGIME-WECHSEL: {prev_regime} → {regime}")
    else:
        print(f"  ✅ Regime bestätigt: {regime}")

    print(f"  Grund: {' | '.join(reason)}")
    print(f"  Aktive DT-Strategien: {active_dt or 'keine (CRASH-Modus)'}")

    result = {
        "regime":      regime,
        "prev_regime": prev_regime,
        "changed":     changed,
        "reason":      ' | '.join(reason),
        "active_dt":   active_dt,
        "indicators": {
            "spy":   round(current_price, 2),
            "ma20":  round(ma20, 2) if ma20 else None,
            "ma200": round(ma200, 2) if ma200 else None,
            "adx":   round(adx, 1) if adx else None,
            "vix":   round(vix, 1) if vix else None,
        },
        "updated": timestamp,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    return regime

if __name__ == '__main__':
    regime = classify_regime()
    print(f"\n  → Regime gespeichert: {regime}")

    # Alert bei Regime-Wechsel
    result = json.loads(OUT.read_text())
    if result.get('changed') and result.get('prev_regime') != 'UNBEKANNT':
        print(f"REGIME_CHANGE: {result['prev_regime']} → {regime}")
