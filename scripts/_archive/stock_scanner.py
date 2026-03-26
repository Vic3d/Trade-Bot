#!/usr/bin/env python3
"""
Stock Scanner — Dynamisches Aktien-Universum für Day Trader v2
================================================================
Scannt ~120 Aktien aus DAX, FTSE, CAC, Oslo, S&P 500.
Findet die Top-Mover (größte Veränderung + Volumen-Spikes).
Gibt ein dynamisches Universum zurück das der Day Trader nutzt.

Alles in EUR umgerechnet.
Läuft 3x am Tag: 09:15 (EU-Open), 15:45 (US-Open), 18:00 (Midday).
Ergebnis: data/dynamic_universe.json
"""

import json, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path('/data/.openclaw/workspace')
OUTPUT = WORKSPACE / 'data' / 'dynamic_universe.json'

# ── KOMPLETT-UNIVERSUM: ~120 Aktien über 5 Börsen ──

# DAX 40 (alle)
DAX = [
    'SAP.DE', 'SIE.DE', 'ALV.DE', 'DTE.DE', 'MBG.DE', 'BMW.DE', 'BAS.DE',
    'BAYN.DE', 'IFX.DE', 'ADS.DE', 'MUV2.DE', 'RHM.DE', 'VOW3.DE', 'HEN3.DE',
    'SHL.DE', 'DBK.DE', 'RWE.DE', 'DPW.DE', 'FRE.DE', 'MTX.DE', 'MRK.DE',
    'HEI.DE', 'BEI.DE', 'CON.DE', 'ENR.DE', 'SRT3.DE', 'QIA.DE', 'P911.DE',
    'ZAL.DE', 'HFG.DE', 'PUM.DE', 'AIR.DE', 'SY1.DE', 'DTG.DE', 'VNA.DE',
    '1COV.DE', 'FME.DE', 'PAH3.DE', 'TKA.DE', 'LEO.DE',
]

# FTSE 100 (Top 30)
FTSE = [
    'SHEL.L', 'BP.L', 'AZN.L', 'HSBA.L', 'RIO.L', 'GLEN.L', 'ULVR.L',
    'GSK.L', 'REL.L', 'DGE.L', 'LSEG.L', 'BA.L', 'NG.L', 'VOD.L',
    'LLOY.L', 'BARC.L', 'AAL.L', 'BATS.L', 'IMB.L', 'NWG.L',
    'CRH.L', 'RKT.L', 'PRU.L', 'EXPN.L', 'CPG.L', 'ABF.L',
    'ANTO.L', 'BHP.L', 'FRES.L', 'MNDI.L',
]

# CAC 40 (Top 15)
CAC = [
    'TTE.PA', 'MC.PA', 'SAN.PA', 'OR.PA', 'AI.PA', 'BNP.PA', 'SU.PA',
    'AIR.PA', 'CS.PA', 'SAF.PA', 'RI.PA', 'EL.PA', 'DSY.PA', 'SGO.PA',
    'KER.PA',
]

# AEX / Euronext
AEX = ['ASML.AS', 'PHIA.AS', 'UNA.AS', 'INGA.AS', 'AD.AS']

# Oslo (Energie + Fischerei)
OSLO = ['EQNR.OL', 'DNB.OL', 'MOWI.OL', 'TEL.OL', 'ORK.OL', 'AKRBP.OL']

# S&P 500 (Top 50 nach Marktgewicht)
SP500 = [
    'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'TSLA', 'BRK-B',
    'JPM', 'V', 'UNH', 'XOM', 'MA', 'JNJ', 'PG', 'HD', 'COST', 'ABBV',
    'BAC', 'CRM', 'NFLX', 'AMD', 'MRK', 'LLY', 'PLTR', 'CVX', 'KO',
    'AVGO', 'PEP', 'TMO', 'WMT', 'CSCO', 'ABT', 'ACN', 'DHR', 'MCD',
    'NEE', 'INTC', 'DIS', 'TXN', 'PM', 'ORCL', 'GS', 'CAT', 'BA',
    'OXY', 'HAL', 'FCX', 'NEM', 'GOLD',
]

# Markt-Zuordnung mit Handelszeiten (CET)
MARKET_CONFIG = {
    'DE': {'tickers': DAX,  'open_h': 9, 'close_h': 17, 'label': '🇩🇪 Xetra'},
    'UK': {'tickers': FTSE, 'open_h': 9, 'close_h': 17, 'label': '🇬🇧 London'},
    'FR': {'tickers': CAC,  'open_h': 9, 'close_h': 17, 'label': '🇫🇷 Paris'},
    'NL': {'tickers': AEX,  'open_h': 9, 'close_h': 17, 'label': '🇳🇱 Amsterdam'},
    'NO': {'tickers': OSLO, 'open_h': 9, 'close_h': 16, 'label': '🇳🇴 Oslo'},
    'US': {'tickers': SP500, 'open_h': 15, 'close_h': 22, 'label': '🇺🇸 NYSE/NASDAQ'},
}


def yahoo_quick(ticker):
    """Schneller Kurs via v8 chart API."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=6).read())
        meta = d['chart']['result'][0]['meta']
        price = meta['regularMarketPrice']
        prev = meta.get('chartPreviousClose', price)
        chg = ((price / prev) - 1) * 100 if prev else 0
        currency = meta.get('currency', 'USD')

        quotes = d['chart']['result'][0]['indicators']['quote'][0]
        volumes = [v for v in quotes.get('volume', []) if v]
        vol = volumes[-1] if volumes else 0
        avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1) if len(volumes) > 1 else 1

        return {
            'ticker': ticker,
            'name': meta.get('shortName', ticker)[:30],
            'price': price,
            'change_pct': round(chg, 2),
            'volume': vol,
            'vol_ratio': round(vol / max(avg_vol, 1), 1),
            'currency': currency,
            'price_eur': to_eur(price, currency),
        }
    except:
        return None


# FX Cache um API-Calls zu sparen
_fx_cache = {}

def to_eur(price, currency):
    if currency == 'EUR':
        return round(price, 4)
    if currency == 'GBp':
        price = price / 100
        currency = 'GBP'
    if currency in _fx_cache:
        return round(price / _fx_cache[currency], 4)
    try:
        pair = f"EUR{currency}=X"
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{pair}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=6).read())
        fx = d['chart']['result'][0]['meta']['regularMarketPrice']
        _fx_cache[currency] = fx
        return round(price / fx, 4) if fx else price
    except:
        fallbacks = {'USD': 1.08, 'GBP': 0.86, 'NOK': 11.5, 'CHF': 0.97, 'DKK': 7.46, 'SEK': 11.2}
        if currency in fallbacks:
            _fx_cache[currency] = fallbacks[currency]
            return round(price / fallbacks[currency], 4)
        return price


def scan_market(market_id, config, max_per_market=10):
    """Scannt einen Markt und gibt die Top-Mover zurück."""
    results = []
    for ticker in config['tickers']:
        r = yahoo_quick(ticker)
        if r:
            r['market'] = market_id
            r['open_h'] = config['open_h']
            r['close_h'] = config['close_h']
            results.append(r)

    # Sortiere nach Interessantheit: abs(change) + vol_ratio
    for r in results:
        r['score'] = abs(r['change_pct']) * 0.6 + min(r['vol_ratio'], 5) * 0.4

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:max_per_market]


def main():
    now = datetime.now(ZoneInfo('Europe/Berlin'))
    hour = now.hour
    print(f"[{now.strftime('%H:%M CET')}] Stock Scanner — Dynamisches Universum")

    # Welche Märkte sind gerade offen?
    active_markets = {}
    upcoming_markets = {}
    for mid, cfg in MARKET_CONFIG.items():
        if cfg['open_h'] <= hour < cfg['close_h']:
            active_markets[mid] = cfg
        elif hour < cfg['open_h'] and cfg['open_h'] - hour <= 2:
            upcoming_markets[mid] = cfg

    # Scanne aktive Märkte (mehr Aktien) + kommende (weniger)
    universe = []
    total_scanned = 0

    for mid, cfg in active_markets.items():
        print(f"\n  {cfg['label']} — {len(cfg['tickers'])} Aktien scannen...")
        movers = scan_market(mid, cfg, max_per_market=15)
        total_scanned += len(cfg['tickers'])
        universe.extend(movers)
        top3 = ', '.join(f"{m['ticker']} ({m['change_pct']:+.1f}%)" for m in movers[:3])
        print(f"    Top 3: {top3}")

    for mid, cfg in upcoming_markets.items():
        print(f"\n  {cfg['label']} (öffnet bald) — Pre-Scan...")
        movers = scan_market(mid, cfg, max_per_market=8)
        total_scanned += len(cfg['tickers'])
        universe.extend(movers)

    # Dedupliziere und sortiere
    seen = set()
    unique = []
    for u in universe:
        if u['ticker'] not in seen:
            seen.add(u['ticker'])
            unique.append(u)
    universe = sorted(unique, key=lambda x: x['score'], reverse=True)

    # Konvertiere in Day Trader Format
    dt_universe = []
    for u in universe:
        dt_universe.append({
            'ticker': u['ticker'],
            'name': u['name'],
            'market': u['market'],
            'open_h': u['open_h'],
            'close_h': u['close_h'],
            'price_eur': u['price_eur'],
            'change_pct': u['change_pct'],
            'vol_ratio': u['vol_ratio'],
            'score': round(u['score'], 2),
        })

    # Speichern
    output = {
        'updated': now.isoformat(),
        'scanned': total_scanned,
        'selected': len(dt_universe),
        'markets_active': list(active_markets.keys()),
        'universe': dt_universe,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"\n{'=' * 50}")
    print(f"Gescannt: {total_scanned} Aktien")
    print(f"Ausgewählt: {len(dt_universe)} Top-Mover")
    print(f"Märkte aktiv: {', '.join(active_markets.keys()) or 'keine (Wochenende)'}")
    print(f"Gespeichert: {OUTPUT}")

    # Top 10 anzeigen
    print(f"\n  Top 10 Mover (sortiert nach Score):")
    for i, u in enumerate(dt_universe[:10], 1):
        print(f"  {i:2d}. {u['ticker']:10s} {u['name']:25s} {u['change_pct']:+6.1f}% | Vol {u['vol_ratio']:.1f}x | {u['price_eur']:.2f}€ | Score {u['score']:.1f}")

    return output


if __name__ == '__main__':
    main()
