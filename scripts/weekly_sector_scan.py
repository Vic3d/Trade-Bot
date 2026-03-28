#!/usr/bin/env python3
"""
weekly_sector_scan.py — Sonntags-Scan über 5 Regionen/Sektoren

Läuft jeden Sonntag 08:00 CET vor Markteröffnung.
Prüft Watchlist-Kandidaten auf Entry-Zonen + gibt Wochenausblick.

Regionen: USA (ex-Tech), Europa, Asien/EM, Rohstoffe (ex-Öl), Defensiv/Healthcare
"""
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE = Path(__file__).parent.parent
CONFIG_PATH = WORKSPACE / 'trading_config.json'

DISCORD_TOKEN = None
DISCORD_CHANNEL = '1475255728313864413'

# Region-Mapping für Watchlist-Ticker
REGION_MAP = {
    'MOS':       ('🌾 Agrar/USA',        'USD'),
    'VALE':      ('🇧🇷 Brasilien/EM',    'USD'),
    'FCX':       ('🔴 Kupfer/USA',       'USD'),
    'SAP.DE':    ('🇪🇺 Europa-Tech',     'EUR'),
    'NOVO-B.CO': ('🏥 Healthcare/DK',    'DKK'),
    'ASML.AS':   ('🇪🇺 Halbleiter/EU',  'EUR'),
    'BHP.L':     ('🇦🇺 Mining/UK',      'GBp'),
    'RIO.L':     ('🇦🇺 Mining/UK',      'GBp'),
    'AG':        ('🪙 Silber/USA',       'USD'),
    'GOLD':      ('🥇 Gold/USA',         'USD'),
    'NEM':       ('🥇 Gold/USA',         'USD'),
    'BAYN.DE':   ('🇩🇪 Pharma/DE',      'EUR'),
    'LHA.DE':    ('✈️ Aviation/DE',      'EUR'),
    'RHM.DE':    ('🛡️ Rüstung/DE',      'EUR'),
}


def yahoo_price(ticker):
    """Holt aktuellen Preis von Yahoo Finance."""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=5d'
    try:
        import urllib.parse
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        meta = data['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
        prev  = meta.get('chartPreviousClose') or price
        chg   = round((price - prev) / prev * 100, 2) if prev else 0
        return price, chg, meta.get('currency', 'USD')
    except Exception as e:
        return None, None, None


def check_entry_zone(price, entry_min, entry_max):
    """Prüft ob Kurs in Entry-Zone ist."""
    if price is None:
        return '❓'
    if entry_min <= price <= entry_max:
        return '🟢 IN ZONE'
    elif price < entry_min:
        diff_pct = round((entry_min - price) / price * 100, 1)
        return f'🔽 {diff_pct}% unter Zone'
    else:
        diff_pct = round((price - entry_max) / price * 100, 1)
        return f'🔼 {diff_pct}% über Zone'


def send_discord(message):
    """Sendet Nachricht an Victor via Discord."""
    try:
        import os
        token = os.environ.get('DISCORD_BOT_TOKEN', '')
        if not token:
            print("[Discord] Kein Token — Output nur lokal")
            return False
        data = json.dumps({'content': message}).encode()
        req = urllib.request.Request(
            f'https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages',
            data=data,
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json',
            },
            method='POST'
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[Discord] Fehler: {e}")
        return False


def main():
    import urllib.parse

    now = datetime.now(timezone.utc)
    date_str = now.strftime('%d.%m.%Y')
    kw = now.isocalendar()[1]

    cfg = json.loads(CONFIG_PATH.read_text())
    watchlist = cfg.get('watchlist', [])
    regime_data = {}
    regime_path = WORKSPACE / 'memory' / 'market-regime.json'
    if regime_path.exists():
        try:
            regime_data = json.loads(regime_path.read_text())
        except:
            pass

    regime = regime_data.get('regime', 'UNKNOWN')
    vix    = regime_data.get('factors', {}).get('vix', '?')

    lines = []
    lines.append(f'## 🌍 Wöchentlicher Sektor-Scan — KW{kw} ({date_str})')
    lines.append(f'**Regime:** {regime} | **VIX:** {vix}')
    lines.append('')

    # Regionen-Gruppierung
    regions = {}
    for w in watchlist:
        ticker = w.get('ticker', '')
        region_label, _ = REGION_MAP.get(ticker, ('🌐 Sonstige', 'USD'))
        region_key = region_label.split('/')[0].strip()
        if region_key not in regions:
            regions[region_key] = []
        regions[region_key].append(w)

    in_zone = []
    near_zone = []  # within 5%
    far = []

    for w in watchlist:
        ticker = w.get('ticker', '')
        if not ticker:
            continue

        price, chg, currency = yahoo_price(ticker)
        region_label, _ = REGION_MAP.get(ticker, ('🌐', 'USD'))

        entry_min = w.get('entryMin', 0)
        entry_max = w.get('entryMax', entry_min * 1.05)
        stop      = w.get('stop', 0)
        targets   = w.get('targets', [])
        target    = targets[0] if targets else None
        name      = w.get('name', ticker)
        note      = w.get('note', '')[:80]

        zone_status = check_entry_zone(price, entry_min, entry_max)

        crv = '—'
        if price and stop and target and price > stop:
            risk   = abs(price - stop)
            reward = abs(target - price)
            crv    = f'{round(reward/risk, 1)}:1'

        chg_str = f'({chg:+.1f}%)' if chg is not None else ''
        price_str = f'{price:.2f} {currency}' if price else '?'

        entry_info = {
            'ticker': ticker,
            'name': name,
            'region': region_label,
            'price': price_str,
            'chg': chg_str,
            'zone': zone_status,
            'entry': f'{entry_min}–{entry_max} {currency}',
            'stop': f'{stop} {currency}',
            'target': f'{target} {currency}' if target else '—',
            'crv': crv,
            'note': note,
        }

        if '🟢' in zone_status:
            in_zone.append(entry_info)
        elif 'unter' in zone_status:
            try:
                pct = float(zone_status.split('%')[0].replace('🔽 ', ''))
                if pct <= 5:
                    near_zone.append(entry_info)
                else:
                    far.append(entry_info)
            except:
                far.append(entry_info)
        else:
            far.append(entry_info)

    # Output: In-Zone zuerst (Handlungsbedarf)
    if in_zone:
        lines.append('### 🚨 IN ENTRY-ZONE — Handlungsbedarf prüfen')
        for e in in_zone:
            lines.append(f'**{e["ticker"]}** ({e["name"]}) {e["region"]}')
            lines.append(f'  Kurs: {e["price"]} {e["chg"]} | Zone: {e["entry"]} | Stop: {e["stop"]} | Ziel: {e["target"]} | CRV: {e["crv"]}')
            if e["note"]:
                lines.append(f'  _{e["note"]}_')
            lines.append('')

    if near_zone:
        lines.append('### 🟡 NAHE AN ZONE (<5%)')
        for e in near_zone:
            lines.append(f'**{e["ticker"]}** {e["region"]} — {e["price"]} {e["chg"]} → Zone: {e["entry"]} ({e["zone"]})')

    lines.append('')
    lines.append('### 📋 Alle Watchlist-Kandidaten')
    for e in in_zone + near_zone + far:
        lines.append(f'`{e["ticker"]}` {e["region"]} | {e["price"]} {e["chg"]} | {e["zone"]} | Stop: {e["stop"]} | CRV: {e["crv"]}')

    # Wochenausblick basierend auf Regime
    lines.append('')
    lines.append('### 📅 Wochenausblick')
    if 'TREND_DOWN' in regime or 'CRASH' in regime:
        lines.append('⚠️ **Regime TREND_DOWN/CRASH** — Nur Rohstoffe/Energie/Healthcare/Defensiv erlaubt.')
        lines.append('Growth-Longs (Tech, NVDA etc.) bleiben gesperrt bis Drei-Schritt-Bestätigung.')
    elif 'RANGE' in regime:
        lines.append('🟡 **Regime RANGE** — Mean-Reversion Setups bevorzugen. Keine aggressiven Directional Bets.')
    else:
        lines.append('🟢 **Regime TREND_UP/BULL** — Alle Strategien erlaubt. Fokus auf Momentum + Breakouts.')

    output = '\n'.join(lines)
    print(output)

    # Discord senden (via message-Tool, nicht direkt)
    # In Cron-Kontext: announce-Delivery übernimmt das
    return output


if __name__ == '__main__':
    main()
