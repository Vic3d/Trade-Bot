#!/usr/bin/env python3
"""
Anti-Cyclical Opportunity Screener
Läuft autonom — findet Aktien die unter temporären Makro-Stressoren leiden
und berechnet Entry-Bedingungen selbst.
"""

import sqlite3, json, urllib.request, datetime, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

STRESSORS = {
    "OIL_HIGH": {
        "name": "Hoher Ölpreis (Brent >$90)",
        "victims": [
            ("LHA.DE", "Lufthansa", "airline"),
            ("RYA.IR", "Ryanair", "airline"),
            ("IAG.L", "IAG", "airline"),
            ("AF.PA", "Air France-KLM", "airline"),
            ("CCL", "Carnival Cruises", "cruise"),
            ("DLTR", "Dollar Tree", "consumer"),
        ],
        "trigger_ticker": "BZ=F",  # Brent Futures
        "reversal_condition": "brent_3day_pct < -4",
    },
    "ROUTE_DISRUPTION": {
        "name": "Suez/Rotes Meer gesperrt",
        "victims": [
            ("HLAG.DE", "Hapag-Lloyd", "container"),
            ("MAERSK-B.CO", "Maersk", "container"),
            ("ZIM", "ZIM Shipping", "container"),
        ],
        "trigger_ticker": None,
        "reversal_condition": "iran_de_escalation OR suez_reopen",
    },
    "VIX_HIGH": {
        "name": "VIX >25 (Konsumangst)",
        "victims": [
            ("BMW.DE", "BMW", "auto"),
            ("VOW3.DE", "Volkswagen", "auto"),
            ("MBG.DE", "Mercedes-Benz", "auto"),
            ("SBUX", "Starbucks", "consumer"),
            ("MCD", "McDonald's", "consumer"),
            ("NKE", "Nike", "consumer"),
        ],
        "trigger_ticker": "^VIX",
        "reversal_condition": "vix_3day_avg < 22",
    },
    "STRONG_EUR": {
        "name": "EUR/USD stark (>1.10) schadet Exporteuren",
        "victims": [
            ("SAP.DE", "SAP", "tech"),
            ("SIE.DE", "Siemens", "industrial"),
            ("ASML.AS", "ASML", "tech"),
            ("AIR.PA", "Airbus", "industrial"),
        ],
        "trigger_ticker": "EURUSD=X",
        "reversal_condition": "eurusd_trend < -0.02",
    }
}

# Entry-Scoring: je mehr Punkte, desto überzeugender der Entry
def score_entry(ticker, cur_price, high52, low52, stressor_key, closes):
    score = 0
    reasons = []

    if not cur_price or not high52 or not low52:
        return 0, []

    # 1. Abstand vom 52W-High (je tiefer, desto mehr Punkte — bis max 40%)
    from_high_pct = (cur_price / high52 - 1) * 100
    if from_high_pct < -30:
        score += 30
        reasons.append(f"Tief: {from_high_pct:.1f}% unter 52W-High (+30 Pkt)")
    elif from_high_pct < -20:
        score += 20
        reasons.append(f"Abschlag: {from_high_pct:.1f}% unter 52W-High (+20 Pkt)")
    elif from_high_pct < -10:
        score += 10
        reasons.append(f"Moderat: {from_high_pct:.1f}% unter 52W-High (+10 Pkt)")

    # 2. Abstand vom 52W-Low (nicht zu nah — Gefahr weiterer Verluste)
    from_low_pct = (cur_price / low52 - 1) * 100
    if from_low_pct > 15:
        score += 15
        reasons.append(f"Sicherheitsabstand zum 52W-Low: +{from_low_pct:.1f}% (+15 Pkt)")
    elif from_low_pct > 5:
        score += 5
        reasons.append(f"Knapp über 52W-Low: +{from_low_pct:.1f}% (+5 Pkt)")

    # 3. Momentum: Stabilisierung? (letzten 3 Wochen weniger Verlust als vorher)
    if len(closes) >= 8:
        recent_3 = closes[-3:]
        prev_3 = closes[-6:-3]
        recent_avg = sum(recent_3) / 3
        prev_avg = sum(prev_3) / 3
        if recent_avg > prev_avg * 0.99:  # Stabilisierung oder leichte Erholung
            score += 15
            reasons.append("Momentum stabilisiert sich (+15 Pkt)")
        elif recent_avg < prev_avg * 0.95:  # Noch im Abwärtstrend
            score -= 10
            reasons.append("Noch im Abwärtstrend (–10 Pkt)")

    # 4. Stressor-Spezifisch
    if stressor_key == "OIL_HIGH":
        score += 10  # Öl-Trigger ist konkret und historisch belegt
        reasons.append("Öl-Inverse bekannt und messbar (+10 Pkt)")
    elif stressor_key == "ROUTE_DISRUPTION":
        score += 15  # Route-Öffnung = sofortiger Impact
        reasons.append("Route-Trigger: direkter, schneller Impact (+15 Pkt)")

    return score, reasons

def get_price(ticker):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1wk&range=6mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        result = data['chart']['result'][0]
        closes = [c for c in result['indicators']['quote'][0]['close'] if c]
        meta = result['meta']
        return (
            meta.get('regularMarketPrice', closes[-1] if closes else None),
            meta.get('fiftyTwoWeekHigh'),
            meta.get('fiftyTwoWeekLow'),
            closes
        )
    except:
        return None, None, None, []

def run_scan():
    results = []
    print(f"\n{'='*70}")
    print(f"ANTI-ZYKLISCHER SCANNER — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    for stressor_key, stressor in STRESSORS.items():
        print(f"\n🔴 STRESSOR: {stressor['name']}")
        print(f"{'Ticker':12s} | {'Score':5s} | {'Kurs':8s} | {'v.52W-H':8s} | Begründung")
        print("-" * 80)

        for ticker, name, sector in stressor['victims']:
            cur, h52, l52, closes = get_price(ticker)
            if not cur:
                print(f"{ticker:12s} | -     | KEIN KURS")
                continue

            score, reasons = score_entry(ticker, cur, h52, l52, stressor_key, closes)
            from_high = (cur/h52-1)*100 if h52 else 0

            entry_signal = "🟢 ENTRY" if score >= 50 else "🟡 WATCH" if score >= 30 else "⚪ WARTEN"
            print(f"{ticker:12s} | {score:5d} | {cur:8.2f} | {from_high:+7.1f}% | {entry_signal}")
            if reasons:
                for r in reasons[:2]:
                    print(f"              |       |         |          |   → {r}")

            results.append({
                "ticker": ticker,
                "name": name,
                "stressor": stressor_key,
                "score": score,
                "current_price": cur,
                "high52": h52,
                "low52": l52,
                "from_high_pct": round((cur/h52-1)*100, 1) if h52 else None,
                "entry_signal": entry_signal,
                "reasons": reasons,
                "scanned_at": datetime.datetime.now().isoformat()
            })

    # Top Opportunities
    top = sorted([r for r in results if r['score'] >= 40], key=lambda x: x['score'], reverse=True)[:5]
    print(f"\n{'='*70}")
    print("TOP ANTI-ZYKLISCHE OPPORTUNITIES (Score ≥ 40):")
    for r in top:
        print(f"  {r['score']:3d}/100 | {r['ticker']:12s} | {r['name']:20s} | {r['from_high_pct']:+.1f}% | {r['entry_signal']}")

    # In DB speichern
    try:
        conn = sqlite3.connect('data/trading.db')
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS anticyclical_scan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, name TEXT, stressor TEXT, score INTEGER,
            current_price REAL, high52 REAL, low52 REAL,
            from_high_pct REAL, entry_signal TEXT, reasons TEXT,
            scanned_at TEXT
        )""")
        for r in results:
            c.execute("""INSERT INTO anticyclical_scan 
                (ticker, name, stressor, score, current_price, high52, low52, from_high_pct, entry_signal, reasons, scanned_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r['ticker'], r['name'], r['stressor'], r['score'], r['current_price'],
                 r['high52'], r['low52'], r['from_high_pct'], r['entry_signal'],
                 json.dumps(r['reasons']), r['scanned_at']))
        conn.commit()
        conn.close()
        print(f"\n✅ {len(results)} Kandidaten in DB gespeichert (anticyclical_scan)")
    except Exception as e:
        print(f"DB-Fehler: {e}")

    return top

if __name__ == '__main__':
    top = run_scan()
