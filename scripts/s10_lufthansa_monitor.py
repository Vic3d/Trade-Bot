#!/usr/bin/env python3
"""
S10 Lufthansa Post-War Recovery — Trigger & Risiko Monitor
============================================================
Überwacht 3 Entry-Trigger für S10:
  1. Iran De-Eskalation / Waffenstillstand (News-Signal)
  2. Brent Crude < 75$/Barrel (Preis-Signal)
  3. LHA.DE über EMA20 (Technisches Signal)

Output: JSON mit trigger_status, risk_reward, alert
"""

import urllib.request
import json
import re
import time
from datetime import datetime
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')

# ── Konfiguration ───────────────────────────────────────────────────────────
S10 = {
    'ticker':       'LHA.DE',
    'name':         'Lufthansa AG',
    'entry_min':    7.00,
    'entry_max':    8.50,
    'stop':         5.80,
    'target1':      11.50,
    'target2':      14.00,
    'brent_max':    75.0,    # Trigger: Brent unter diesem Niveau
    'size_eur':     2000.0,  # Planned position size
}

PEACE_KEYWORDS = [
    'iran ceasefire', 'iran waffenstillstand', 'iran peace deal',
    'iran nuclear deal', 'hormuz reopened', 'iran de-escalation',
    'iran agreement', 'middle east ceasefire', 'iran talks',
    'iran sanctions lifted', 'iran airspace open',
]

RISK_KEYWORDS = [
    'iran escalation', 'iran attack', 'hormuz blocked',
    'lufthansa strike', 'lufthansa streik', 'lufthansa kapitalerhöhung',
    'oil price surge', 'brent above 90',
]


def yahoo_price(ticker: str) -> float | None:
    """Aktuellen Kurs von Yahoo Finance holen."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        meta = d['chart']['result'][0]['meta']
        return meta.get('regularMarketPrice') or meta.get('previousClose')
    except Exception as e:
        print(f'  Yahoo {ticker}: {e}')
        return None


def get_ema(prices: list, period: int = 20) -> float | None:
    """EMA berechnen."""
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def get_lha_with_ema() -> dict:
    """LHA.DE Kurs + EMA20 aus Yahoo Finance."""
    url = 'https://query2.finance.yahoo.com/v8/finance/chart/LHA.DE?interval=1d&range=60d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        result = d['chart']['result'][0]
        closes = result['indicators']['quote'][0].get('close', [])
        closes = [c for c in closes if c is not None]
        current = result['meta'].get('regularMarketPrice') or closes[-1]
        ema20 = get_ema(closes, 20)
        ema50 = get_ema(closes, 50)
        week_low = min(closes[-5:]) if len(closes) >= 5 else None
        week_high = max(closes[-5:]) if len(closes) >= 5 else None
        return {
            'price': current,
            'ema20': ema20,
            'ema50': ema50,
            'above_ema20': current > ema20 if ema20 else None,
            'above_ema50': current > ema50 if ema50 else None,
            'week_low': week_low,
            'week_high': week_high,
        }
    except Exception as e:
        print(f'  LHA EMA error: {e}')
        return {'price': None, 'ema20': None, 'ema50': None, 'above_ema20': None}


def check_news_triggers() -> dict:
    """Google News auf Peace- und Risk-Keywords scannen."""
    import urllib.parse
    peace_hits = []
    risk_hits = []

    queries = [
        'Iran ceasefire peace deal 2026',
        'Iran Waffenstillstand 2026',
        'Hormuz strait reopened',
        'Lufthansa Aktie 2026',
    ]

    for query in queries:
        try:
            q = urllib.parse.quote(query)
            url = f'https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                content = r.read().decode('utf-8', errors='replace')

            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', content)[1:6]
            for title in titles:
                low = title.lower()
                if any(kw in low for kw in PEACE_KEYWORDS):
                    peace_hits.append(title)
                if any(kw in low for kw in RISK_KEYWORDS):
                    risk_hits.append(title)
        except Exception:
            pass

    return {
        'peace_signals': list(set(peace_hits)),
        'risk_signals': list(set(risk_hits)),
        'peace_trigger': len(peace_hits) >= 2,  # Mind. 2 Peace-News = Trigger
    }


def calculate_risk_reward(lha_price: float) -> dict:
    """Risiko-Rendite-Analyse für verschiedene Entry-Szenarien."""
    cfg = S10
    if not lha_price:
        return {}

    results = {}
    for label, entry in [('Jetzt', lha_price),
                          ('Entry Min', cfg['entry_min']),
                          ('Entry Max', cfg['entry_max'])]:
        risk = entry - cfg['stop']
        reward1 = cfg['target1'] - entry
        reward2 = cfg['target2'] - entry
        crv1 = reward1 / risk if risk > 0 else 0
        crv2 = reward2 / risk if risk > 0 else 0

        # In EUR bei 2000€ Position
        shares = cfg['size_eur'] / entry
        max_loss = shares * risk
        gain_t1 = shares * reward1
        gain_t2 = shares * reward2

        results[label] = {
            'entry':    round(entry, 2),
            'stop':     cfg['stop'],
            'target1':  cfg['target1'],
            'target2':  cfg['target2'],
            'risk_pct': round(risk / entry * 100, 1),
            'gain_pct_t1': round(reward1 / entry * 100, 1),
            'gain_pct_t2': round(reward2 / entry * 100, 1),
            'crv_t1':   round(crv1, 2),
            'crv_t2':   round(crv2, 2),
            'max_loss_eur': round(max_loss, 0),
            'gain_t1_eur':  round(gain_t1, 0),
            'gain_t2_eur':  round(gain_t2, 0),
        }
    return results


def run_monitor() -> dict:
    """Vollständiger S10 Monitor-Lauf."""
    print(f'S10 Lufthansa Monitor — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('─' * 50)

    # 1. LHA.DE Kurs + EMA
    print('1. LHA.DE Kurs & Technik...')
    lha = get_lha_with_ema()
    lha_price = lha.get('price')
    ema20 = lha.get('ema20')
    ema50 = lha.get('ema50')
    print(f'   Kurs: {lha_price:.2f}€' if lha_price else '   Kurs: N/A')
    print(f'   EMA20: {ema20:.2f}€' if ema20 else '   EMA20: N/A')
    print(f'   EMA50: {ema50:.2f}€' if ema50 else '   EMA50: N/A')

    # 2. Brent Crude
    print('2. Brent Crude...')
    brent = yahoo_price('BZ=F')
    if not brent:
        brent = yahoo_price('CL=F')  # WTI als Fallback
    print(f'   Brent: ${brent:.2f}' if brent else '   Brent: N/A')

    # 3. News-Trigger
    print('3. News-Scan (Peace-Signale)...')
    news = check_news_triggers()
    print(f'   Peace-Signale: {len(news["peace_signals"])}')
    print(f'   Risk-Signale: {len(news["risk_signals"])}')

    # 4. Trigger-Auswertung
    trigger_brent = brent is not None and brent < S10['brent_max']
    trigger_tech = lha.get('above_ema20') is True
    trigger_peace = news['peace_trigger']

    triggers_met = sum([trigger_brent, trigger_tech, trigger_peace])

    # Entry-Check: Kurs in Entry-Zone?
    in_entry_zone = (lha_price is not None and
                     S10['entry_min'] <= lha_price <= S10['entry_max'])

    # 5. Risiko-Rendite
    rr = calculate_risk_reward(lha_price) if lha_price else {}

    # 6. Alert-Level
    if triggers_met >= 2 and in_entry_zone:
        alert_level = 'ENTRY_SIGNAL'
        alert_msg = f'🚨 S10 ENTRY-SIGNAL! {triggers_met}/3 Trigger erfüllt, Kurs in Entry-Zone ({lha_price:.2f}€)'
    elif triggers_met >= 2:
        alert_level = 'WATCH_CLOSELY'
        alert_msg = f'⚡ S10 fast bereit: {triggers_met}/3 Trigger, aber Kurs außerhalb Entry-Zone'
    elif triggers_met == 1:
        alert_level = 'WARMING_UP'
        alert_msg = f'👀 S10 erwacht: 1/3 Trigger aktiv'
    else:
        alert_level = 'STANDBY'
        alert_msg = f'😴 S10 Standby: 0/3 Trigger aktiv'

    result = {
        'timestamp': datetime.now().isoformat(),
        'lha': lha,
        'brent_price': brent,
        'triggers': {
            'brent_below_75': trigger_brent,
            'above_ema20': trigger_tech,
            'peace_signal': trigger_peace,
            'total_met': triggers_met,
        },
        'in_entry_zone': in_entry_zone,
        'alert_level': alert_level,
        'alert_msg': alert_msg,
        'risk_reward': rr,
        'news': news,
    }

    # 7. Output
    print()
    print('─' * 50)
    print(f'TRIGGER STATUS ({triggers_met}/3):')
    print(f'  🛢️  Brent < 75$:      {"✅" if trigger_brent else "❌"} ({f"${brent:.2f}" if brent else "N/A"})')
    print(f'  📈 LHA über EMA20:  {"✅" if trigger_tech else "❌"} ({f"{lha_price:.2f}€ vs {ema20:.2f}€ EMA" if lha_price and ema20 else "N/A"})')
    print(f'  ☮️  Peace-Signal:     {"✅" if trigger_peace else "❌"}')
    print()
    print(f'ENTRY-ZONE (7,00–8,50€): {"✅ JA" if in_entry_zone else "❌ NEIN"}')
    print(f'ALERT: {alert_msg}')
    print()

    if rr.get('Jetzt'):
        r = rr['Jetzt']
        print('RISIKO-RENDITE (bei Jetzt-Einstieg):')
        print(f'  Entry: {r["entry"]}€ | Stop: {r["stop"]}€ (-{r["risk_pct"]}%)')
        print(f'  Ziel 1: {r["target1"]}€ (+{r["gain_pct_t1"]}%) | CRV: {r["crv_t1"]}:1 | +{r["gain_t1_eur"]}€')
        print(f'  Ziel 2: {r["target2"]}€ (+{r["gain_pct_t2"]}%) | CRV: {r["crv_t2"]}:1 | +{r["gain_t2_eur"]}€')
        print(f'  Max. Verlust: -{r["max_loss_eur"]}€ bei 2.000€ Position')

    if news['peace_signals']:
        print()
        print('PEACE-SIGNALE in News:')
        for h in news['peace_signals'][:3]:
            print(f'  • {h}')

    if news['risk_signals']:
        print()
        print('⚠️ RISK-SIGNALE in News:')
        for h in news['risk_signals'][:3]:
            print(f'  • {h}')

    # Ergebnis speichern
    out = WORKSPACE / 'data/s10_status.json'
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f'\nGespeichert: {out}')

    return result


if __name__ == '__main__':
    result = run_monitor()
    # Discord-Alert nur bei ENTRY_SIGNAL oder WATCH_CLOSELY
    if result['alert_level'] in ('ENTRY_SIGNAL', 'WATCH_CLOSELY'):
        print(f'\nDISCORD_ALERT: {result["alert_msg"]}')
