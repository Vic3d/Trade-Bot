#!/usr/bin/env python3
"""
weekly_sector_scan.py — Breiter Markt-Scan über ~400 Stocks

Läuft jeden Sonntag 08:00 CET.
Scannt data/universe.json komplett durch, filtert auf echte Setups.
Ausgabe: Top 10-15 Kandidaten mit Regime-Filter + Begründung.

Filter-Logik:
  1. Preis holen (Yahoo Finance, batch)
  2. Technisches Signal: RSI-Zone + MA-Beziehung + Volume
  3. Regime-Filter: welche Sektoren sind erlaubt?
  4. Ranking nach Setup-Qualität
  5. Top-Kandidaten mit Entry/Stop/CRV ausgeben
"""
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE   = Path(__file__).parent.parent
UNIVERSE    = WORKSPACE / 'data' / 'universe.json'
REGIME_FILE = WORKSPACE / 'memory' / 'market-regime.json'
CONFIG_PATH = WORKSPACE / 'trading_config.json'
OUTPUT_FILE = WORKSPACE / 'memory' / 'weekly-scan-latest.md'

# Regime → erlaubte Sektoren
REGIME_SECTORS = {
    'TREND_UP':   ['energy','materials_metals','industrials_defense','technology','healthcare',
                   'financials','consumer','real_estate_utilities','emerging_markets','commodities_agri'],
    'RANGE':      ['energy','materials_metals','healthcare','financials','commodities_agri','industrials_defense'],
    'TREND_DOWN': ['energy','materials_metals','industrials_defense','healthcare','commodities_agri'],
    'CRASH':      ['healthcare','real_estate_utilities','commodities_agri'],
    'UNKNOWN':    ['energy','materials_metals','healthcare','commodities_agri'],
}

MAX_TICKERS_PER_BATCH = 20   # Yahoo rate limit
BATCH_SLEEP           = 1.2  # Sekunden zwischen Batches


def yahoo_fetch_batch(tickers):
    """Holt Kursdaten für mehrere Ticker auf einmal (Yahoo Chart API)."""
    results = {}
    for ticker in tickers:
        try:
            url = (f'https://query1.finance.yahoo.com/v8/finance/chart/'
                   f'{urllib.parse.quote(ticker)}?interval=1d&range=60d')
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Accept': 'application/json',
            })
            data = json.loads(urllib.request.urlopen(req, timeout=6).read())
            result = data['chart']['result'][0]
            meta   = result['meta']
            closes = [c for c in result['indicators']['quote'][0].get('close', []) if c]
            volumes= [v for v in result['indicators']['quote'][0].get('volume', []) if v]

            if len(closes) < 20:
                continue

            price = meta.get('regularMarketPrice') or closes[-1]
            prev  = meta.get('chartPreviousClose') or closes[-2]
            currency = meta.get('currency', 'USD')
            chg_pct  = round((price - prev) / prev * 100, 2) if prev else 0

            # Einfache Indikatoren
            ma20  = sum(closes[-20:]) / 20
            ma50  = sum(closes[-50:]) / min(50, len(closes))
            ma200 = sum(closes[-200:]) / min(200, len(closes)) if len(closes) >= 50 else ma50

            # RSI-14
            gains  = [max(closes[i]-closes[i-1],0) for i in range(-14,0)]
            losses = [max(closes[i-1]-closes[i],0) for i in range(-14,0)]
            avg_g  = sum(gains)  / 14
            avg_l  = sum(losses) / 14
            rsi    = 100 - (100 / (1 + avg_g/avg_l)) if avg_l > 0 else 50

            # Volumen (5d vs 20d Durchschnitt)
            vol_5d_avg  = sum(volumes[-5:])  / 5  if len(volumes) >= 5  else 0
            vol_20d_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
            vol_ratio   = vol_5d_avg / vol_20d_avg if vol_20d_avg > 0 else 1.0

            # 52-Wochen-High/Low
            w52_high = max(closes[-min(252, len(closes)):])
            w52_low  = min(closes[-min(252, len(closes)):])
            from_high_pct = round((price - w52_high) / w52_high * 100, 1)
            from_low_pct  = round((price - w52_low)  / w52_low  * 100, 1)

            results[ticker] = {
                'price':       round(price, 2),
                'prev':        round(prev, 2),
                'currency':    currency,
                'chg_pct':     chg_pct,
                'ma20':        round(ma20, 2),
                'ma50':        round(ma50, 2),
                'ma200':       round(ma200, 2),
                'rsi':         round(rsi, 1),
                'vol_ratio':   round(vol_ratio, 2),
                'from_high':   from_high_pct,
                'from_low':    from_low_pct,
                'closes':      closes[-20:],
            }
        except Exception as e:
            pass  # Ticker übersprungen — kein Fehler ausgeben

        time.sleep(0.15)  # Mini-Pause zwischen Requests
    return results


def score_setup(d, sector):
    """
    Bewertet Setup-Qualität 0-100.
    Hoher Score = gutes Setup für aktuelles Regime.
    """
    score  = 0
    reason = []
    price  = d['price']
    rsi    = d['rsi']

    # 1. RSI-Zone (30-50 = Kaufzone nach Korrektur)
    if 28 <= rsi <= 45:
        score += 25
        reason.append(f'RSI {rsi:.0f} (Kaufzone)')
    elif 45 < rsi <= 60:
        score += 12
        reason.append(f'RSI {rsi:.0f} (neutral)')
    elif rsi < 28:
        score += 10
        reason.append(f'RSI {rsi:.0f} (überverkauft)')

    # 2. Preis vs. MA-Struktur
    if price > d['ma50'] > d['ma200']:
        score += 20
        reason.append('Über MA50+MA200 (Uptrend)')
    elif d['ma200'] > price > d['ma50']:
        score += 15
        reason.append('Zwischen MA50/MA200 (Support-Test)')
    elif price > d['ma200'] and price < d['ma50']:
        score += 10
        reason.append('Pullback an MA50')
    elif price < d['ma200']:
        # Nur positiv wenn starke Erholung (mean-reversion)
        if d['from_low'] < 10:
            score += 8
            reason.append('Nahe 52W-Low (Bounce?)')

    # 3. Volumen-Bestätigung
    if d['vol_ratio'] > 1.3:
        score += 15
        reason.append(f'Vol +{round(d["vol_ratio"]*100-100)}% ggü. Ø (Interesse)')
    elif d['vol_ratio'] > 1.0:
        score += 5

    # 4. Nahe 52W-High (Breakout-Potenzial) vs. Nahe Low (Bounce)
    if -5 <= d['from_high'] <= 0:
        score += 15
        reason.append('Nahe 52W-High (Breakout)')
    elif d['from_low'] < 15:
        score += 10
        reason.append('Nahe 52W-Low (Reversal)')

    # 5. Sektoren-Bonus (in aktuellem Regime besonders interessant)
    priority_sectors = ['energy', 'materials_metals', 'healthcare', 'commodities_agri']
    if sector in priority_sectors:
        score += 5

    return score, ' | '.join(reason) if reason else 'Kein klares Signal'


def suggest_levels(d):
    """Schlägt Entry/Stop/Ziel basierend auf MA-Struktur vor."""
    price = d['price']
    ma20  = d['ma20']
    ma50  = d['ma50']
    rsi   = d['rsi']

    # Entry: aktueller Kurs oder leicht darunter
    entry = round(price * 0.99, 2)

    # Stop: unter MA50 oder 7% unter Entry (je nachdem was enger ist)
    stop_ma = round(min(ma50, ma20) * 0.97, 2)
    stop_pct = round(entry * 0.93, 2)
    stop = max(stop_ma, stop_pct)  # Den weiteren Stop wählen

    # Ziel: 52W-High oder +15% (je nachdem was realistischer)
    w52_high  = price / (1 + d['from_high'] / 100) if d['from_high'] < 0 else price * 1.1
    target_15 = round(entry * 1.15, 2)
    target    = round(min(w52_high * 0.98, target_15), 2)

    risk   = abs(entry - stop)
    reward = abs(target - entry)
    crv    = round(reward / risk, 1) if risk > 0 else 0

    return entry, stop, target, crv


def main():
    now    = datetime.now(timezone.utc)
    kw     = now.isocalendar()[1]
    date_s = now.strftime('%d.%m.%Y')

    # Regime laden
    regime     = 'UNKNOWN'
    vix        = '?'
    wti        = '?'
    sp500_ma   = '?'
    if REGIME_FILE.exists():
        try:
            rm = json.loads(REGIME_FILE.read_text())
            regime   = rm.get('regime', 'UNKNOWN')
            factors  = rm.get('factors', {})
            vix      = factors.get('vix', '?')
            wti      = factors.get('wti', '?')
            sp500_ma = factors.get('sp500_vs_ma200', '?')
        except:
            pass

    allowed_sectors = REGIME_SECTORS.get(regime, REGIME_SECTORS['UNKNOWN'])
    universe        = json.loads(UNIVERSE.read_text())

    print(f"🌍 Wöchentlicher Sektor-Scan KW{kw} — Regime: {regime} | VIX: {vix}")
    print(f"   Erlaubte Sektoren: {', '.join(allowed_sectors)}")
    print()

    # Alle Ticker sammeln (nur erlaubte Sektoren)
    all_tickers = []
    ticker_sector = {}
    for sector_key, sector_data in universe.get('sectors', {}).items():
        if sector_key not in allowed_sectors:
            continue
        for t in sector_data.get('tickers', []):
            all_tickers.append(t)
            ticker_sector[t] = sector_key

    # ETFs immer scannen (Regime-Check)
    for t in universe.get('etfs_for_regime_check', {}).get('tickers', []):
        all_tickers.append(t)
        ticker_sector[t] = 'etf'

    print(f"   Scanne {len(all_tickers)} Ticker...")

    # Batch-Fetch
    market_data = {}
    batches = [all_tickers[i:i+MAX_TICKERS_PER_BATCH]
               for i in range(0, len(all_tickers), MAX_TICKERS_PER_BATCH)]

    for i, batch in enumerate(batches):
        print(f"   Batch {i+1}/{len(batches)} ({len(batch)} Ticker)...", end='\r')
        batch_data = yahoo_fetch_batch(batch)
        market_data.update(batch_data)
        if i < len(batches) - 1:
            time.sleep(BATCH_SLEEP)

    fetched = len(market_data)
    print(f"\n   {fetched}/{len(all_tickers)} Ticker erfolgreich geladen")

    # Setup-Scoring
    scored = []
    for ticker, d in market_data.items():
        sector = ticker_sector.get(ticker, 'unknown')
        if sector == 'etf':
            continue
        score, reason = score_setup(d, sector)
        if score >= 30:  # Nur Kandidaten mit echtem Setup
            entry, stop, target, crv = suggest_levels(d)
            scored.append({
                'ticker':   ticker,
                'sector':   sector,
                'score':    score,
                'reason':   reason,
                'price':    d['price'],
                'currency': d['currency'],
                'chg':      d['chg_pct'],
                'rsi':      d['rsi'],
                'vol_ratio':d['vol_ratio'],
                'from_high':d['from_high'],
                'from_low': d['from_low'],
                'entry':    entry,
                'stop':     stop,
                'target':   target,
                'crv':      crv,
                'ma50':     d['ma50'],
                'ma200':    d['ma200'],
            })

    # Sortiert nach Score
    scored.sort(key=lambda x: -x['score'])
    top = scored[:15]

    # ── Output ────────────────────────────────────────────────────────────────
    lines = []
    lines.append(f'# 🌍 Wöchentlicher Sektor-Scan — KW{kw} ({date_s})')
    lines.append(f'**Regime:** {regime} | **VIX:** {vix} | **WTI:** {wti}')
    lines.append(f'**Gescannt:** {fetched} Ticker | **Setups gefunden:** {len(scored)} | **Top 15 gezeigt**')
    lines.append('')

    # ETF Sektor-Rotation
    etf_data = [(t, market_data[t]) for t in universe.get('etfs_for_regime_check', {}).get('tickers', [])
                if t in market_data and t.startswith('X')]
    if etf_data:
        etf_data.sort(key=lambda x: -x[1]['chg_pct'])
        lines.append('## 📊 Sektor-Rotation (Wochenperformance)')
        for t, d in etf_data[:5]:
            chg = d['chg_pct']
            icon = '🟢' if chg > 0 else '🔴'
            lines.append(f'  {icon} `{t}`: {chg:+.1f}%')
        lines.append('')

    # Top Kandidaten nach Sektor gruppiert
    by_sector = {}
    for c in top:
        s = c['sector']
        if s not in by_sector:
            by_sector[s] = []
        by_sector[s].append(c)

    lines.append('## 🏆 Top Setups diese Woche')
    lines.append('')

    sector_labels = {s: universe['sectors'][s]['label'] for s in universe.get('sectors', {})}

    for sector, candidates in by_sector.items():
        label = sector_labels.get(sector, sector)
        lines.append(f'### {label}')
        for c in candidates:
            chg_str = f'({c["chg"]:+.1f}%)' if c['chg'] is not None else ''
            lines.append(
                f'**{c["ticker"]}** — Score: {c["score"]} | '
                f'Kurs: {c["price"]} {c["currency"]} {chg_str} | '
                f'RSI: {c["rsi"]:.0f} | Vol: {c["vol_ratio"]:.1f}x'
            )
            lines.append(
                f'  Entry: ~{c["entry"]} | Stop: {c["stop"]} | '
                f'Ziel: {c["target"]} | CRV: {c["crv"]}:1'
            )
            lines.append(f'  _{c["reason"]}_')
            lines.append('')

    lines.append('---')
    lines.append(f'*Generiert: {now.strftime("%Y-%m-%d %H:%M UTC")} | '
                 f'Erlaubte Sektoren: {", ".join(allowed_sectors)}*')

    output = '\n'.join(lines)

    # In Datei speichern (Markdown für Cron-Report)
    OUTPUT_FILE.write_text(output, encoding='utf-8')

    # Auch als JSON für Dashboard
    json_out = WORKSPACE / 'data' / 'scan-latest.json'
    scan_json = {
        '_generated': now.isoformat(),
        'kw': kw,
        'date': date_s,
        'regime': regime,
        'vix': vix,
        'wti': wti,
        'fetched': fetched,
        'setups_found': len(scored),
        'top': scored[:20],
        'etf_rotation': [
            {'ticker': t, **market_data[t]}
            for t in universe.get('etfs_for_regime_check', {}).get('tickers', [])
            if t in market_data and t.startswith('X')
        ]
    }
    json_out.write_text(json.dumps(scan_json, default=str), encoding='utf-8')

    print(f'\n✅ Scan gespeichert: {OUTPUT_FILE}')
    print(f'   JSON: {json_out}')
    print(f'   {len(scored)} Setups gefunden, Top 15 ausgegeben')

    return output


if __name__ == '__main__':
    main()
