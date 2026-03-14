#!/usr/bin/env python3
"""
Stop-Loss Monitor — alle 15 Min
Liest offene Stops aus DB, holt aktuelle Kurse, prüft auf Stop-Trigger
"""
import sys, json, urllib.request, sqlite3, time, re, os
from datetime import datetime

sys.path.insert(0, '/data/.openclaw/workspace/scripts')

# FX-Kurse holen
def yahoo(ticker):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        return d['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        return None

# Kurs für einen Ticker abrufen (mit Konvertierung wenn nötig)
def get_price_eur(ticker, eurusd, eurnok, gbpeur):
    if ticker == 'BAYN.DE':
        try:
            req = urllib.request.Request('https://www.onvista.de/aktien/Bayer-Aktie-DE000BAY0017', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode('utf-8', errors='ignore')
            match = re.findall(r'"last":([0-9.]+)', html)
            return float(match[0]) if match else None
        except:
            return None
    elif ticker.endswith('.OL'):  # Oslo (NOK)
        price = yahoo(ticker)
        return price / eurnok if price else None
    elif ticker.endswith('.L'):  # London (GBP, × 100 = pence)
        price = yahoo(ticker)
        return price / 100 * gbpeur if price else None
    else:  # US (USD)
        price = yahoo(ticker)
        return price / eurusd if price else None

# DB laden
conn = sqlite3.connect('/data/.openclaw/workspace/memory/newswire.db')
stops_data = conn.execute('SELECT ticker, stop_price FROM trades WHERE outcome="open" AND stop_price IS NOT NULL').fetchall()
conn.close()

if not stops_data:
    print('KEIN_SIGNAL — keine offenen Trades mit Stop-Loss in DB')
    sys.exit(0)

# FX-Kurse
eurusd = yahoo('EURUSD=X')
eurnok = yahoo('EURNOK=X')
gbpeur = yahoo('GBPEUR=X')

if not eurusd or not eurnok or not gbpeur:
    print(f'ERROR: FX-Kurse konnten nicht geladen werden')
    sys.exit(1)

# Alle Stops prüfen
alerts = []
for ticker, stop in stops_data:
    price = get_price_eur(ticker, eurusd, eurnok, gbpeur)
    if price is None:
        continue
    
    margin_pct = (price - stop) / stop * 100
    
    if price <= stop:
        alerts.append(f'🔴 **STOP GETROFFEN** {ticker} @ {price:.2f}€ | Stop: {stop}€')
    elif margin_pct < 2.0:
        alerts.append(f'🟡 **STOP-NÄHE** {ticker} @ {price:.2f}€ | Stop: {stop}€ | Margin: {margin_pct:.1f}%')

# Webhook senden wenn Alerts
if alerts:
    webhook_url = os.getenv('DISCORD_WEBHOOK_STOP_LOSS', '')
    if not webhook_url:
        print(f'ERROR: DISCORD_WEBHOOK_STOP_LOSS nicht in .env')
        sys.exit(1)
    
    msg = '⚠️ **STOP-LOSS ALERT** <@452053147620343808>\n' + '\n'.join(alerts)
    data = json.dumps({'content': msg}).encode()
    req = urllib.request.Request(webhook_url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        urllib.request.urlopen(req, timeout=8)
        print(f'✅ ALERT GESENDET ({len(alerts)} Signal(e))')
    except Exception as e:
        print(f'ERROR Discord: {e}')
else:
    print('KEIN_SIGNAL — alle Stops sicher')
