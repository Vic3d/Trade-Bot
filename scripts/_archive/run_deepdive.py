#!/usr/bin/env python3
"""
run_deepdive.py — Deep Dive Analyse für einen Ticker

Wird aufgerufen wenn Victor auf "Deep Dive" im Dashboard klickt.
Analysiert: Technicals + News + Fundamental + Thesis
Speichert in: data/research/TICKER.json
"""
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE     = Path(__file__).parent.parent
RESEARCH_DIR  = WORKSPACE / 'data' / 'research'
QUEUE_FILE    = WORKSPACE / 'data' / 'research-queue.json'
CONFIG_PATH   = WORKSPACE / 'trading_config.json'


def yahoo_full(ticker):
    """Holt vollständige Kursdaten inkl. 1-Jahres-History."""
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/'
           f'{urllib.parse.quote(ticker)}?interval=1d&range=1y')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
    data = json.loads(urllib.request.urlopen(req, timeout=8).read())
    result = data['chart']['result'][0]
    meta   = result['meta']
    closes = [c for c in result['indicators']['quote'][0].get('close', []) if c]
    volumes= [v for v in result['indicators']['quote'][0].get('volume', []) if v]
    timestamps = result.get('timestamp', [])

    if not closes:
        raise ValueError(f'Keine Kursdaten für {ticker}')

    price    = meta.get('regularMarketPrice') or closes[-1]
    prev     = meta.get('chartPreviousClose') or closes[-2]
    currency = meta.get('currency', 'USD')
    mktcap   = meta.get('marketCap')

    # Indikatoren
    ma20  = sum(closes[-20:])  / min(20, len(closes))
    ma50  = sum(closes[-50:])  / min(50, len(closes))
    ma200 = sum(closes[-200:]) / min(200, len(closes))

    # RSI-14
    gains  = [max(closes[i]-closes[i-1],0) for i in range(-14,0)]
    losses = [max(closes[i-1]-closes[i],0) for i in range(-14,0)]
    ag, al = sum(gains)/14, sum(losses)/14
    rsi    = round(100 - (100/(1+ag/al)) if al > 0 else 50, 1)

    # Volumen
    vol_5  = sum(volumes[-5:])  / 5  if len(volumes) >= 5  else 0
    vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
    vol_ratio = round(vol_5 / vol_20, 2) if vol_20 > 0 else 1.0

    # 52W
    closes_52 = closes[-min(252, len(closes)):]
    w52h = max(closes_52)
    w52l = min(closes_52)

    # Trend (Richtung der letzten 5 Wochen)
    trend = 'UP' if closes[-1] > closes[-5] else 'DOWN'
    trend_strength = round(abs(closes[-1] - closes[-5]) / closes[-5] * 100, 1)

    # Equity Curve (letzte 90 Tage)
    equity = []
    for i, c in enumerate(closes[-90:]):
        ts = timestamps[max(0, len(timestamps)-90+i)] if timestamps else 0
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d') if ts else ''
        equity.append({'date': date, 'price': round(c, 2)})

    return {
        'price':      round(price, 2),
        'prev':       round(prev, 2),
        'currency':   currency,
        'mkt_cap':    mktcap,
        'chg_pct':    round((price - prev) / prev * 100, 2) if prev else 0,
        'ma20':       round(ma20, 2),
        'ma50':       round(ma50, 2),
        'ma200':      round(ma200, 2),
        'rsi':        rsi,
        'vol_ratio':  vol_ratio,
        'w52_high':   round(w52h, 2),
        'w52_low':    round(w52l, 2),
        'from_high':  round((price - w52h) / w52h * 100, 1),
        'from_low':   round((price - w52l) / w52l * 100, 1),
        'trend':      trend,
        'trend_pct':  trend_strength,
        'equity':     equity,
    }


def fetch_news(ticker):
    """Holt News der letzten 7 Tage via Finnhub."""
    try:
        import os
        key = os.environ.get('FINNHUB_KEY', '')
        if not key:
            try:
                env = (WORKSPACE / '.env').read_text()
                for line in env.splitlines():
                    if line.startswith('FINNHUB_KEY='):
                        key = line.split('=',1)[1].strip()
            except:
                pass
        if not key:
            return []

        from_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        # 7 Tage zurück
        import datetime as dt
        to_dt   = dt.date.today()
        from_dt = to_dt - dt.timedelta(days=7)

        url = (f'https://finnhub.io/api/v1/company-news?symbol={urllib.parse.quote(ticker)}'
               f'&from={from_dt}&to={to_dt}&token={key}')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        news = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return [{'headline': n.get('headline',''), 'source': n.get('source',''),
                 'datetime': n.get('datetime',0), 'url': n.get('url','')}
                for n in (news or [])[:10]]
    except Exception as e:
        return [{'headline': f'News-Fehler: {e}', 'source': '', 'datetime': 0, 'url': ''}]


def technical_verdict(d):
    """Generiert technisches Urteil aus den Daten."""
    verdicts = []
    signals  = []

    rsi = d['rsi']
    if rsi < 30:
        verdicts.append('🟢 RSI stark überverkauft — historisches Reversal-Signal')
        signals.append('RSI_OVERSOLD_STRONG')
    elif rsi < 45:
        verdicts.append('🟡 RSI in Kaufzone (30–45)')
        signals.append('RSI_BUY_ZONE')
    elif rsi > 70:
        verdicts.append('🔴 RSI überkauft — Vorsicht bei neuem Entry')
        signals.append('RSI_OVERBOUGHT')

    p = d['price']
    if p > d['ma50'] > d['ma200']:
        verdicts.append('🟢 Kurs über MA50 + MA200 — Uptrend intakt')
        signals.append('TREND_UP')
    elif p < d['ma50'] < d['ma200']:
        verdicts.append('🔴 Kurs unter MA50 + MA200 — Abwärtstrend')
        signals.append('TREND_DOWN')
    elif d['ma200'] > p > d['ma50']:
        verdicts.append('🟡 Kurs zwischen MA50/MA200 — Support-Test')
        signals.append('MA_SUPPORT')

    if d['from_high'] < -40:
        verdicts.append(f'⚠️ {abs(d["from_high"]):.0f}% unter 52W-High — massiver Abverkauf')
        signals.append('DEEP_CORRECTION')
    elif d['from_high'] > -5:
        verdicts.append('🚀 Nahe 52W-High — Ausbruchspotenzial')
        signals.append('NEAR_HIGH')

    if d['vol_ratio'] > 1.5:
        verdicts.append(f'📈 Volumen +{round(d["vol_ratio"]*100-100)}% über Ø — erhöhtes Interesse')
        signals.append('HIGH_VOLUME')

    return verdicts, signals


def suggest_setup(d):
    """Entry/Stop/Ziel Vorschlag."""
    price = d['price']
    ma50  = d['ma50']
    ma200 = d['ma200']
    w52h  = d['w52_high']

    # Entry: leicht unter aktuellem Kurs (Limit)
    entry = round(price * 0.99, 2)

    # Stop: unter dem letzten signifikanten Support
    support = min(ma50, ma200) * 0.96
    stop    = round(max(support, entry * 0.92), 2)

    # Ziel: nächster Widerstand (MA200 wenn darunter, sonst 52W-High)
    if price < ma200:
        target = round(ma200 * 0.98, 2)
    else:
        target = round(min(w52h * 0.95, price * 1.20), 2)

    risk   = abs(entry - stop)
    reward = abs(target - entry)
    crv    = round(reward / risk, 1) if risk > 0 else 0

    return {
        'entry':  entry,
        'stop':   stop,
        'target': target,
        'crv':    crv,
        'risk_pct':   round(risk / entry * 100, 1),
        'reward_pct': round(reward / entry * 100, 1),
    }


def run_deepdive(ticker):
    """Führt vollständige Deep-Dive-Analyse durch."""
    now = datetime.now(timezone.utc)
    print(f'🔬 Deep Dive: {ticker}')

    # 1. Kursdaten
    print('  → Kursdaten...')
    try:
        market = yahoo_full(ticker)
    except Exception as e:
        return {'error': str(e), 'ticker': ticker, '_generated': now.isoformat()}

    # 2. News
    print('  → News...')
    news = fetch_news(ticker)
    time.sleep(0.5)

    # 3. Technische Analyse
    verdicts, signals = technical_verdict(market)
    setup = suggest_setup(market)

    # 4. Watchlist-Infos falls vorhanden
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    watchlist_entry = next(
        (w for w in cfg.get('watchlist', []) if w.get('ticker') == ticker), None
    )

    # 5. Resultat zusammenbauen
    result = {
        'ticker':      ticker,
        '_generated':  now.isoformat(),
        '_version':    1,
        'market':      market,
        'technicals': {
            'verdicts': verdicts,
            'signals':  signals,
        },
        'setup':       setup,
        'news':        news,
        'watchlist':   watchlist_entry,
        'notes':       [],   # Manuelle Notizen (Victor oder Albert)
        'history': [{
            'date':     now.isoformat(),
            'action':   'deep_dive',
            'summary':  f'Automatische Analyse: RSI {market["rsi"]}, Kurs {market["price"]} {market["currency"]}'
        }]
    }

    # 6. Speichern
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    safe_ticker = ticker.replace('/', '_').replace('.', '_')
    out_path = RESEARCH_DIR / f'{safe_ticker}.json'

    # Bestehende History erhalten
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text())
            result['notes']   = old.get('notes', [])
            result['history'] = old.get('history', []) + result['history']
        except:
            pass

    out_path.write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2))
    print(f'  ✅ Gespeichert: {out_path}')
    print(f'  RSI: {market["rsi"]} | Kurs: {market["price"]} {market["currency"]} | CRV: {setup["crv"]}:1')
    print(f'  Technicals: {" | ".join(verdicts[:2])}')

    return result


def process_queue():
    """Verarbeitet alle Ticker in der Research-Queue."""
    if not QUEUE_FILE.exists():
        print('Queue leer.')
        return

    try:
        queue = json.loads(QUEUE_FILE.read_text())
    except:
        queue = []

    if not queue:
        print('Queue leer.')
        return

    pending = [q for q in queue if q.get('status') == 'pending']
    print(f'{len(pending)} Ticker in Queue...')

    for item in pending:
        ticker = item.get('ticker', '')
        if not ticker:
            continue
        try:
            run_deepdive(ticker)
            item['status'] = 'done'
            item['done_at'] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            item['status'] = 'error'
            item['error']  = str(e)
            print(f'  ❌ {ticker}: {e}')

    QUEUE_FILE.write_text(json.dumps(queue, indent=2))
    print('Queue verarbeitet.')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Direkt-Aufruf: python3 run_deepdive.py TICKER
        ticker = sys.argv[1].upper()
        result = run_deepdive(ticker)
    else:
        # Queue abarbeiten
        process_queue()
