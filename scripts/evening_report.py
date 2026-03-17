#!/usr/bin/env python3
"""
evening_report.py — Abend-Report (nach US-Schluss)

Portfolio-Übersicht, Overnight-Risiko, Trailing-Review, Geopolitik.
Schreibt Overnight-Kontext für Morgen-Briefing.

USAGE: python3 evening_report.py
"""

import json, sys, time, urllib.request, re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

WS = Path('/data/.openclaw/workspace')


def yahoo(ticker, timeout=8):
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


def to_eur(price, ccy, fx):
    if price is None: return None
    if ccy == 'EUR': return price
    elif ccy == 'USD': return price / fx.get('EURUSD', 1.15)
    elif ccy == 'NOK': return price / fx.get('EURNOK', 11.0)
    elif ccy in ('GBp', 'GBX'): return (price / 100) / fx.get('EURGBP', 0.86)
    elif ccy == 'GBP': return price / fx.get('EURGBP', 0.86)
    return price


def main():
    now = datetime.now().strftime('%H:%M')
    lines = []

    from portfolio import Portfolio
    p = Portfolio()
    real = p.real_positions()
    paper = p.paper_positions()

    # FX
    fx = {}
    for pair in ['EURUSD=X', 'EURNOK=X', 'EURGBP=X']:
        rate, _, _ = yahoo(pair)
        fx[pair.replace('=X', '')] = rate or 1.0
        time.sleep(0.15)

    vix, vix_chg, _ = yahoo('^VIX')
    wti, wti_chg, _ = yahoo('CL=F')

    lines.append(f"🌙 **ABEND-REPORT {now} CET**\n")
    lines.append(f"🌍 **TAGESSCHLUSS**")
    lines.append(f"• VIX: {vix:.1f} ({vix_chg:+.1f}%) | WTI: ${wti:.2f} ({wti_chg:+.1f}%) | EUR/USD: {fx.get('EURUSD', 0):.4f}\n")

    # Portfolio
    lines.append(f"📈 **ECHTES PORTFOLIO**")
    overnight_risks = []
    trailing_candidates = []
    prices_export = {}

    for pos in real:
        yahoo_t = pos.yahoo or pos.ticker
        price_raw, chg, ccy = yahoo(yahoo_t)
        price_eur = to_eur(price_raw, ccy, fx)
        time.sleep(0.15)

        if price_eur and pos.entry_eur:
            pnl = ((price_eur - pos.entry_eur) / pos.entry_eur) * 100
            pnl_icon = "📈" if pnl >= 0 else "📉"
            prices_export[pos.ticker] = {'price_eur': round(price_eur, 2), 'pnl_pct': round(pnl, 1)}

            stop_info = ""
            if pos.stop_eur:
                stop_dist = ((price_eur - pos.stop_eur) / price_eur) * 100
                stop_info = f"Stop {pos.stop_eur}€ ({stop_dist:.1f}%)"
                if stop_dist < 5:
                    overnight_risks.append(f"{pos.name} ({pos.ticker}): Stop nur {stop_dist:.1f}% weg")
            else:
                stop_info = "⚠️ KEIN STOP"
                overnight_risks.append(f"{pos.name} ({pos.ticker}): KEIN STOP gesetzt!")

            if pnl > 10:
                trailing_candidates.append(f"{pos.name} ({pos.ticker}): +{pnl:.1f}% → Gewinn sichern (Stop auf +5%)")
            elif pnl > 5:
                trailing_candidates.append(f"{pos.name} ({pos.ticker}): +{pnl:.1f}% → Stop auf Breakeven")

            lines.append(f"• {pos.name} ({pos.ticker}): {price_eur:.2f}€ ({chg:+.1f}%) | {pnl_icon} {pnl:+.1f}% | {stop_info}")

    # Paper Fund
    lines.append(f"\n🧪 **PAPER FUND**")
    try:
        from auto_trader import get_portfolio_status
        status = get_portfolio_status()
        lines.append(f"• Wert: ~{status['portfolio_value']:.0f}€ ({status['performance_pct']:+.1f}%) | Win-Rate: {status['win_rate']:.0f}%")
    except:
        lines.append(f"• {len(paper)} aktive Positionen")

    # Overnight Risiko
    if overnight_risks:
        lines.append(f"\n⚠️ **OVERNIGHT-RISIKO**")
        for r in overnight_risks:
            lines.append(f"• {r}")

    # Trailing
    if trailing_candidates:
        lines.append(f"\n🎯 **TRAILING-STOP REVIEW**")
        for t in trailing_candidates:
            lines.append(f"• {t}")

    # Overnight-Kontext speichern
    overnight = {
        'generated': datetime.utcnow().isoformat(),
        'prices': prices_export,
        'vix': vix,
        'wti': wti,
        'risks': overnight_risks,
    }
    overnight_path = WS / 'memory' / 'overnight-context.json'
    overnight_path.write_text(json.dumps(overnight, indent=2, ensure_ascii=False))

    report = "\n".join(lines)
    print(report)
    return report


if __name__ == "__main__":
    main()
