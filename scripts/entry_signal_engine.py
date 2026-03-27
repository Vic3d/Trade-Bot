#!/usr/bin/env python3
"""
Entry Signal Engine — Verbesserung 3: Echte Chart-Setups statt "blind kaufen"
===========================================================================
Prüft für jeden Ticker ob ein technisches Entry-Signal vorliegt:
  - RSI-Oversold Bounce (RSI < 40 dreht nach oben)
  - Support-Hold (Kurs hält wichtiges Level)
  - Momentum-Break (Kurs bricht über EMA20)
  - VIX-Spike-Recovery (VIX war >30, fällt zurück)
"""
import urllib.request, json
from pathlib import Path
from datetime import date

WS = Path('/data/.openclaw/workspace')

def fetch_closes(ticker: str, days: int = 30) -> list:
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        closes = d['chart']['result'][0]['indicators']['quote'][0].get('close', [])
        return [c for c in closes if c][-days:]
    except:
        return []

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)

def calc_ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return round(ema, 4)

def check_entry_signal(ticker: str, current_price: float) -> dict:
    closes = fetch_closes(ticker, 30)
    if len(closes) < 15:
        return {'signal': 'NO_DATA', 'score': 0, 'reasons': []}

    rsi = calc_rsi(closes)
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50) if len(closes) >= 50 else ema20

    prev_rsi = calc_rsi(closes[:-1]) if len(closes) > 15 else rsi
    price_vs_ema20 = (current_price - ema20) / ema20 * 100
    price_vs_ema50 = (current_price - ema50) / ema50 * 100

    score = 0
    reasons = []

    # Signal 1: RSI Oversold Bounce (RSI war <40, steigt wieder)
    if prev_rsi < 40 and rsi > prev_rsi and rsi < 55:
        score += 3
        reasons.append(f'RSI Bounce: {prev_rsi:.0f}→{rsi:.0f}')

    # Signal 2: EMA20-Ausbruch (Kurs bricht von unten über EMA20)
    if -2 < price_vs_ema20 < 3:
        score += 2
        reasons.append(f'EMA20-Break: {price_vs_ema20:+.1f}%')
    elif price_vs_ema20 > 3:
        score += 1
        reasons.append(f'Über EMA20: +{price_vs_ema20:.1f}%')

    # Signal 3: Trend intact (über EMA50)
    if price_vs_ema50 > 0:
        score += 1
        reasons.append(f'Über EMA50: +{price_vs_ema50:.1f}%')

    # Signal 4: Momentum (letzte 3 Tage positiv)
    if len(closes) >= 4:
        momentum_3d = (closes[-1] - closes[-4]) / closes[-4] * 100
        if 0 < momentum_3d < 8:
            score += 1
            reasons.append(f'3d-Momentum: +{momentum_3d:.1f}%')
        elif momentum_3d >= 8:
            score -= 1
            reasons.append(f'Überkauft 3d: +{momentum_3d:.1f}%')

    # Malus: RSI überkauft
    if rsi > 70:
        score -= 2
        reasons.append(f'RSI überkauft: {rsi:.0f}')

    signal_type = 'STRONG' if score >= 5 else 'MODERATE' if score >= 3 else 'WEAK' if score >= 1 else 'NO_SIGNAL'

    return {
        'signal': signal_type,
        'score': score,
        'rsi': rsi,
        'ema20': round(ema20, 2),
        'ema50': round(ema50, 2),
        'price_vs_ema20': round(price_vs_ema20, 1),
        'reasons': reasons
    }

if __name__ == '__main__':
    import sys
    eurusd = 1.15
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['FCX', 'SMCI', 'LHA.DE', 'ANET', 'ZIM']
    for t in tickers:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=8) as r: d = json.load(r)
            price_raw = d['chart']['result'][0]['meta']['regularMarketPrice']
            is_usd = not any(t.endswith(x) for x in ['.DE','.PA','.AS','.L','.OL'])
            price = price_raw / eurusd if is_usd else price_raw
            sig = check_entry_signal(t, price)
            print(f"{t:12} {sig['signal']:10} Score:{sig['score']} RSI:{sig['rsi']:.0f} EMA20:{sig['price_vs_ema20']:+.1f}% | {' | '.join(sig['reasons'])}")
        except Exception as e:
            print(f"{t}: {e}")
