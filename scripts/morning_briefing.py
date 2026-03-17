#!/usr/bin/env python3
"""
morning_briefing.py — Morgen-Report (ersetzt 2 separate Cron-Prompts)

Holt: Portfolio, Live-Kurse, News, Makro
Gibt formatierten Discord-Report aus.

USAGE: python3 morning_briefing.py
Output → wird vom Cron-Agent an Victor geschickt
"""

import json, sys, time, urllib.request, re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

WS = Path('/data/.openclaw/workspace')


def yahoo(ticker, timeout=8):
    """Yahoo Finance Kurs + Tagesveränderung."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        meta = d['chart']['result'][0]['meta']
        p = meta['regularMarketPrice']
        prev = meta.get('chartPreviousClose', p)
        chg = ((p - prev) / prev * 100) if prev else 0
        ccy = meta.get('currency', 'USD')
        return p, round(chg, 2), ccy
    except:
        return None, 0, 'USD'


def onvista(url):
    """Onvista Kurs für DE-Aktien."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode('utf-8')
        matches = re.findall(r'"last":([0-9.]+)', html)
        return float(matches[0]) if matches else None
    except:
        return None


def to_eur(price, ccy, fx):
    """Konvertiert Preis nach EUR."""
    if price is None:
        return None
    if ccy == 'EUR':
        return price
    elif ccy == 'USD':
        return price / fx.get('EURUSD', 1.15)
    elif ccy == 'NOK':
        return price / fx.get('EURNOK', 11.0)
    elif ccy in ('GBp', 'GBX'):
        return (price / 100) / fx.get('EURGBP', 0.86)
    elif ccy == 'GBP':
        return price / fx.get('EURGBP', 0.86)
    return price


def main():
    now = datetime.now().strftime('%H:%M')
    lines = []

    # 1. Portfolio laden
    from portfolio import Portfolio
    p = Portfolio()
    real = p.real_positions()
    paper = p.paper_positions()

    # 2. FX Rates
    fx = {}
    for pair in ['EURUSD=X', 'EURNOK=X', 'EURGBP=X']:
        rate, _, _ = yahoo(pair)
        key = pair.replace('=X', '')
        fx[key] = rate or 1.0
        time.sleep(0.15)

    # 3. Makro
    vix, vix_chg, _ = yahoo('^VIX')
    wti, wti_chg, _ = yahoo('CL=F')

    lines.append(f"📊 **MORGEN-BRIEFING {now} CET**\n")
    lines.append(f"🌍 **MAKRO**")
    lines.append(f"• VIX: {vix:.1f} ({vix_chg:+.1f}%) | WTI: ${wti:.2f} ({wti_chg:+.1f}%) | EUR/USD: {fx.get('EURUSD', 0):.4f}")

    regime = "⚠️ ELEVATED" if vix and vix > 25 else ("🟢 CALM" if vix and vix < 18 else "🟡 NORMAL")
    lines.append(f"• Regime: {regime}\n")

    # 4. Echtes Portfolio
    lines.append(f"📈 **ECHTES PORTFOLIO** ({len(real)} Positionen)")
    
    for pos in real:
        yahoo_t = pos.yahoo or pos.ticker
        
        # Onvista für DE-Aktien
        onvista_map = {
            'BAYN.DE': 'https://www.onvista.de/aktien/Bayer-Aktie-DE000BAY0017',
        }
        
        if pos.ticker in onvista_map:
            price_eur = onvista(onvista_map[pos.ticker])
            chg = 0
        else:
            price_raw, chg, ccy = yahoo(yahoo_t)
            price_eur = to_eur(price_raw, ccy, fx)
            time.sleep(0.15)

        if price_eur and pos.entry_eur:
            pnl = ((price_eur - pos.entry_eur) / pos.entry_eur) * 100
            pnl_icon = "📈" if pnl >= 0 else "📉"

            # Stop-Abstand
            if pos.stop_eur:
                stop_dist = ((price_eur - pos.stop_eur) / price_eur) * 100
                stop_str = f"Stop {pos.stop_eur}€ ({stop_dist:.1f}% weg)"
                if stop_dist < 3:
                    stop_str = f"⚠️ Stop {pos.stop_eur}€ ({stop_dist:.1f}% weg) — KRITISCH!"
            else:
                stop_str = "⚠️ KEIN STOP"

            lines.append(f"• {pos.name} ({pos.ticker}): {price_eur:.2f}€ ({chg:+.1f}%) | Entry {pos.entry_eur}€ | {pnl_icon} {pnl:+.1f}% | {stop_str}")
        else:
            lines.append(f"• {pos.name} ({pos.ticker}): Kurs nicht verfügbar")

    # 5. Paper Fund
    if paper:
        lines.append(f"\n🧪 **PAPER FUND** ({len(paper)} Positionen)")
        
        try:
            from auto_trader import get_portfolio_status
            status = get_portfolio_status()
            lines.append(f"• Wert: ~{status['portfolio_value']:.0f}€ ({status['performance_pct']:+.1f}%) | Cash: {status['cash']:.0f}€ | Unrealized: {status['unrealized_pnl']:+.1f}€")
        except:
            lines.append(f"• {len(paper)} aktive Paper-Positionen")

    # 6. News
    lines.append(f"\n📰 **NEWS**")
    try:
        from news_cache import get_portfolio_news, format_news_compact
        news = get_portfolio_news()
        lines.append(format_news_compact(news, max_items=5))
    except Exception as e:
        lines.append(f"  News-Fehler: {e}")

    # 7. Fokus
    lines.append(f"\n⚡ **HEUTE IM FOKUS**")
    
    # Automatische Fokus-Punkte
    focus = []
    for pos in real:
        if pos.stop_eur:
            yahoo_t = pos.yahoo or pos.ticker
            price_raw, _, ccy = yahoo(yahoo_t)
            price_eur = to_eur(price_raw, ccy, fx)
            if price_eur:
                stop_dist = ((price_eur - pos.stop_eur) / price_eur) * 100
                if stop_dist < 3:
                    focus.append(f"🔴 {pos.name} ({pos.ticker}): Stop nur {stop_dist:.1f}% weg!")
                elif ((price_eur - pos.entry_eur) / pos.entry_eur * 100) > 5:
                    focus.append(f"🟢 {pos.name} ({pos.ticker}): +{((price_eur - pos.entry_eur) / pos.entry_eur * 100):.1f}% → Trailing-Stop prüfen")

    if not focus:
        focus.append("Keine kritischen Positionen — normaler Handelstag")
    
    for f in focus[:3]:
        lines.append(f"• {f}")

    report = "\n".join(lines)
    print(report)
    return report


if __name__ == "__main__":
    main()
