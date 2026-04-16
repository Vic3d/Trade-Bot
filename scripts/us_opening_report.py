#!/usr/bin/env python3
"""
us_opening_report.py — US Opening Check (16:30 MEZ)
Frische Intraday-Kurse für US-Ticker + Stop-Warnung
"""
import json, time, urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
def yahoo(ticker, timeout=8):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        meta = d['chart']['result'][0]['meta']
        price = meta['regularMarketPrice']
        prev  = meta.get('chartPreviousClose', price)
        chg   = ((price - prev) / prev * 100) if prev else 0
        ccy   = meta.get('currency', 'USD')
        return price, round(chg, 2), ccy
    except:
        return None, 0, 'USD'

def main():
    # FX
    eurusd, _, _ = yahoo('EURUSD=X')
    eurusd = eurusd or 1.15
    vix,    _, _ = yahoo('^VIX')
    vix    = vix or 25.0
    time.sleep(0.2)

    # Portfolio laden
    try:
        from portfolio import Portfolio
        positions = Portfolio().real_positions()
    except Exception as e:
        print(f'Portfolio-Fehler: {e}')
        return

    # Für US-Ticker frische Kurse holen
    lines = []
    warnings = []
    for pos in positions:
        ticker = pos.ticker
        is_us  = not any(ticker.endswith(x) for x in ['.DE','.PA','.AS','.L','.OL','.ST','.CO'])
        if not is_us:
            continue

        price, chg, ccy = yahoo(ticker)
        time.sleep(0.15)
        if price is None:
            continue

        price_eur = price / eurusd if ccy == 'USD' else price
        stop      = pos.stop_eur
        name      = pos.name or ticker

        stop_dist = ''
        warn = ''
        if stop and stop > 0 and price_eur:
            dist_pct = (price_eur - stop) / price_eur * 100
            stop_dist = f' | Stop {stop:.2f}€ → {dist_pct:.1f}% weg'
            if dist_pct < 3:
                warn = ' ⚠️'
                warnings.append(f'{name} ({ticker}): Stop nur {dist_pct:.1f}% entfernt!')

        arrow = '▲' if chg >= 0 else '▼'
        lines.append(f'• {name} ({ticker}): ${price:.2f} = {price_eur:.2f}€ ({arrow}{abs(chg):.1f}%){stop_dist}{warn}')

    # CEO Direktive
    ceo = {}
    try:
        ceo = json.loads((WS/'data/ceo_directive.json').read_text(encoding="utf-8"))
    except:
        pass

    print(f"=== US OPENING REPORT {datetime.now(_BERLIN).strftime('%d.%m.%Y')} ===")
    print(f"VIX: {vix:.1f} | EURUSD: {eurusd:.4f} | Mode: {ceo.get('mode','?')} | Regime: {ceo.get('regime','?')}")
    print()
    for l in lines:
        print(l)
    if warnings:
        print()
        print("STOP-WARNINGS:")
        for w in warnings:
            print(f"  ⚠️ {w}")

if __name__ == '__main__':
    main()
