#!/usr/bin/env python3
"""
ATR Calculator — Verbesserung 1: Ticker-spezifische Stops
=========================================================
Average True Range (14 Tage) → dynamischer Stop statt pauschal 6.5%
"""
import urllib.request, json
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
ATR_CACHE = WS / 'data/atr_cache.json'

def fetch_ohlcv(ticker: str, days: int = 20) -> list:
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        q = d['chart']['result'][0]['indicators']['quote'][0]
        closes = q.get('close', [])
        highs  = q.get('high',  [])
        lows   = q.get('low',   [])
        bars = [(h, l, c) for h, l, c in zip(highs, lows, closes)
                if h and l and c]
        return bars[-days:]
    except:
        return []

def calc_atr(bars: list, period: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, c = bars[i]
        prev_c  = bars[i-1][2]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(len(trs), period)

def get_atr_stop(ticker: str, current_price: float,
                 atr_multiplier: float = 2.0,
                 eurusd: float = 1.15) -> dict:
    """
    Gibt stop_price + target_price basierend auf ATR zurück.
    Multiplier: 2.0 = konservativ, 1.5 = aggressiv (VIX>25)
    """
    # Cache laden
    cache = {}
    if ATR_CACHE.exists():
        try:
            cache = json.load(open(ATR_CACHE))
        except:
            pass

    cache_key = ticker
    from datetime import date
    today = date.today().isoformat()

    if cache_key in cache and cache[cache_key].get('date') == today:
        atr_eur = cache[cache_key]['atr_eur']
        atr_pct = cache[cache_key]['atr_pct']
    else:
        bars = fetch_ohlcv(ticker)
        if not bars:
            # Fallback: pauschal 6.5%
            atr_pct = 0.065
            atr_eur = current_price * atr_pct
        else:
            atr_raw = calc_atr(bars)
            is_usd = not any(ticker.endswith(x) for x in ['.DE','.PA','.AS','.L','.OL','.CO'])
            atr_eur = atr_raw / eurusd if is_usd else atr_raw
            atr_pct = atr_eur / current_price if current_price > 0 else 0.065

        cache[cache_key] = {'atr_eur': round(atr_eur, 4),
                            'atr_pct': round(atr_pct, 4),
                            'date': today}
        with open(ATR_CACHE, 'w') as f:
            json.dump(cache, f, indent=2)

    stop_distance = atr_eur * atr_multiplier
    stop_price    = current_price - stop_distance
    # Ziel = 3× ATR (CRV 1.5:1 minimum nach Kosten)
    target_price  = current_price + (stop_distance * 3.0)
    crv = (target_price - current_price) / (current_price - stop_price)

    return {
        'stop':    round(stop_price, 2),
        'target':  round(target_price, 2),
        'crv':     round(crv, 2),
        'atr_eur': round(atr_eur, 4),
        'atr_pct': round(atr_pct * 100, 2),
        'stop_pct': round(stop_distance / current_price * 100, 2)
    }

if __name__ == '__main__':
    import sys
    eurusd = 1.15
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['NVDA','FCX','LHA.DE','ASML.AS','FRO']
    for t in tickers:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=8) as r: d = json.load(r)
            price_raw = d['chart']['result'][0]['meta']['regularMarketPrice']
            is_usd = not any(t.endswith(x) for x in ['.DE','.PA','.AS','.L','.OL'])
            price = price_raw / eurusd if is_usd else price_raw
            result = get_atr_stop(t, price, eurusd=eurusd)
            print(f"{t:12} Preis: {price:.2f}€ | ATR: {result['atr_pct']:.1f}% | Stop: {result['stop']:.2f}€ (-{result['stop_pct']:.1f}%) | Ziel: {result['target']:.2f}€ | CRV: {result['crv']:.1f}:1")
        except Exception as e:
            print(f"{t}: Fehler — {e}")
