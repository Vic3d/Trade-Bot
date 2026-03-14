#!/usr/bin/env python3
"""
Portfolio Risk Monitor — P1/P2
  - Korrelations-Matrix (welche Positionen bewegen sich zusammen?)
  - Portfolio-Konzentration (zu viel in einem Sektor?)
  - Max-Drawdown-Schätzung
  - Position-Sizing-Report

Usage:
  python3 portfolio_risk.py            → Voller Report
  python3 portfolio_risk.py matrix     → Nur Korrelationsmatrix
  python3 portfolio_risk.py sizing     → Nur Position-Sizing
"""

import urllib.request, json, os, sys
from datetime import datetime, timezone

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "portfolio-risk.md")

PORTFOLIO = {
    "NVDA":   {"name":"Nvidia",               "yahoo":"NVDA",    "fx":"EURUSD","entry":167.88,"strategy":3},
    "MSFT":   {"name":"Microsoft",            "yahoo":"MSFT",    "fx":"EURUSD","entry":351.85,"strategy":3},
    "PLTR":   {"name":"Palantir",             "yahoo":"PLTR",    "fx":"EURUSD","entry":132.11,"strategy":3},
    "EQNR":   {"name":"Equinor ASA",          "yahoo":"EQNR.OL", "fx":"EURNOK","entry":27.04, "strategy":1},
    "BAYN.DE":{"name":"Bayer AG",             "yahoo":"BAYN.DE", "fx":None,    "entry":39.95, "strategy":None},
    "RIO.L":  {"name":"Rio Tinto",            "yahoo":"RIO.L",   "fx":"GBPEUR","entry":76.92, "strategy":5},
    "A2QQ9R": {"name":"Invesco Solar ETF",    "yahoo":"TAN",     "fx":"EURUSD","entry":22.40, "strategy":6},
    "A3D42Y": {"name":"VanEck Oil Services",  "yahoo":"OIH",     "fx":"EURUSD","entry":27.91, "strategy":1},
    "A14WU5": {"name":"L&G Cyber ETF",        "yahoo":"HACK",    "fx":"EURUSD","entry":28.83, "strategy":3},
    "A2DWAW": {"name":"iShares Biotech ETF",  "yahoo":"IBB",     "fx":"EURUSD","entry":7.00,  "strategy":7},
}

STRATEGY_NAMES = {1:"S1 Öl/Iran",2:"S2 Rüstung",3:"S3 Tech/KI",
                   4:"S4 Silber",5:"S5 Rohstoffe",6:"S6 Solar",7:"S7 Biotech"}
FALLBACK_FX = {"EURUSD":1.09,"EURNOK":11.80,"GBPEUR":1.17}
_fx_cache = {}

def get_fx(pair):
    if pair in _fx_cache: return _fx_cache[pair]
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{pair}=X?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        v = d["chart"]["result"][0]["meta"]["regularMarketPrice"]
        _fx_cache[pair] = v; return v
    except: return FALLBACK_FX.get(pair, 1.0)

def get_returns(ticker, n=30):
    """Holt tägliche Returns der letzten n Tage."""
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0].get("close",[]) if c]
        if len(closes) < 2: return []
        returns = [(closes[i]-closes[i-1])/closes[i-1] for i in range(1, len(closes))]
        return returns[-n:]
    except: return []

def pearson(a, b):
    """Pearson-Korrelation zwischen zwei Listen."""
    n = min(len(a), len(b))
    if n < 5: return None
    a, b = a[-n:], b[-n:]
    mean_a = sum(a)/n; mean_b = sum(b)/n
    num   = sum((a[i]-mean_a)*(b[i]-mean_b) for i in range(n))
    den_a = (sum((x-mean_a)**2 for x in a))**0.5
    den_b = (sum((x-mean_b)**2 for x in b))**0.5
    return round(num/(den_a*den_b), 2) if den_a*den_b > 0 else None

def correlation_matrix() -> dict:
    """Berechnet Korrelationsmatrix aller Portfolio-Positionen."""
    tickers = list(PORTFOLIO.keys())
    returns = {}
    for t in tickers:
        yahoo = PORTFOLIO[t]["yahoo"]
        returns[t] = get_returns(yahoo, n=30)

    matrix = {}
    for i, t1 in enumerate(tickers):
        matrix[t1] = {}
        for j, t2 in enumerate(tickers):
            if i == j:
                matrix[t1][t2] = 1.0
            elif j > i:
                r = pearson(returns[t1], returns[t2])
                matrix[t1][t2] = r
                if t2 not in matrix: matrix[t2] = {}
                matrix[t2][t1] = r
            # j < i bereits gefüllt
    return matrix

def find_high_correlations(matrix: dict, threshold=0.75) -> list:
    """Findet Paare mit zu hoher Korrelation."""
    tickers = list(matrix.keys())
    high = []
    seen = set()
    for t1 in tickers:
        for t2 in tickers:
            if t1 == t2: continue
            pair = tuple(sorted([t1,t2]))
            if pair in seen: continue
            seen.add(pair)
            r = matrix.get(t1,{}).get(t2)
            if r and r >= threshold:
                high.append((t1, t2, r))
    return sorted(high, key=lambda x: -x[2])

def sector_concentration(matrix: dict) -> dict:
    """Zeigt Konzentration pro Strategie."""
    from collections import defaultdict
    sectors = defaultdict(list)
    for t, info in PORTFOLIO.items():
        s = info.get("strategy")
        sectors[s].append(t)

    result = {}
    for s_id, tickers in sectors.items():
        name = STRATEGY_NAMES.get(s_id, f"S{s_id}" if s_id else "Ohne Strategie")
        # Durchschnittliche Intra-Sektor-Korrelation
        pairs = [(t1,t2) for i,t1 in enumerate(tickers) for t2 in tickers[i+1:]]
        if pairs:
            corrs = [matrix.get(t1,{}).get(t2) for t1,t2 in pairs]
            corrs = [c for c in corrs if c is not None]
            avg_corr = round(sum(corrs)/len(corrs),2) if corrs else None
        else:
            avg_corr = None
        result[name] = {"count":len(tickers),"tickers":tickers,"avg_corr":avg_corr}
    return result

def sizing_report(portfolio_eur=10_000, risk_pct=0.02) -> list:
    """P2: Position-Sizing-Empfehlungen für alle Positionen."""
    rows = []
    for ticker, info in PORTFOLIO.items():
        yahoo = info["yahoo"]
        fx = info.get("fx")
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo}?interval=1d&range=1mo"
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.load(r)
            closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0].get("close",[]) if c]
            price  = d["chart"]["result"][0]["meta"]["regularMarketPrice"]

            if fx == "EURUSD":
                f = get_fx("EURUSD"); price = price/f
                closes = [c/f for c in closes]
            elif fx == "EURNOK":
                f = get_fx("EURNOK"); price = price/f
                closes = [c/f for c in closes]
            elif fx == "GBPEUR":
                f = get_fx("GBPEUR"); price = (price/100)*f
                closes = [(c/100)*f for c in closes]

            if len(closes) >= 15:
                tr = [abs(closes[i]-closes[i-1]) for i in range(1,len(closes))]
                atr14 = sum(tr[-14:])/14
                risk_per_unit = 2 * atr14
                max_risk      = portfolio_eur * risk_pct
                units         = round(max_risk / risk_per_unit, 2) if risk_per_unit > 0 else 0
                invest_eur    = round(units * price, 0)
                pct_of_port   = round(invest_eur / portfolio_eur * 100, 1)
                rows.append({
                    "ticker":      ticker,
                    "name":        info["name"],
                    "price":       round(price,2),
                    "atr14":       round(atr14,3),
                    "risk_unit":   round(risk_per_unit,2),
                    "units":       units,
                    "invest_eur":  invest_eur,
                    "pct_port":    pct_of_port,
                })
        except:
            pass
    return rows


def write_report(portfolio_eur=10_000) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Portfolio Risk Report\n*{now}*\n"]

    # Korrelationsmatrix
    print("  Berechne Korrelationsmatrix...")
    matrix = correlation_matrix()

    # Hohe Korrelationen
    high = find_high_correlations(matrix, threshold=0.75)
    lines.append("## ⚠️ Hohe Korrelationen (>0.75)\n")
    if high:
        for t1, t2, r in high:
            n1 = PORTFOLIO[t1]["name"]; n2 = PORTFOLIO[t2]["name"]
            lines.append(f"- **{n1} ↔ {n2}**: {r:.2f} {'⚠️' if r>0.85 else ''}")
    else:
        lines.append("- Keine kritischen Korrelationen gefunden ✅")

    # Sektor-Konzentration
    lines.append("\n## 📊 Sektor-Konzentration\n")
    sectors = sector_concentration(matrix)
    for s_name, data in sorted(sectors.items(), key=lambda x: -x[1]["count"]):
        corr_str = f" | Ø Korr: {data['avg_corr']:.2f}" if data["avg_corr"] else ""
        lines.append(f"- **{s_name}** ({data['count']} Positionen{corr_str}): {', '.join(data['tickers'])}")

    # Korrelationsmatrix (kompakt)
    lines.append("\n## 🔢 Korrelationsmatrix (30 Tage)\n")
    tickers = list(PORTFOLIO.keys())
    header = "| | " + " | ".join(t[:6] for t in tickers) + " |"
    separator = "|---|" + "---|" * len(tickers)
    lines += [header, separator]
    for t1 in tickers:
        row = f"| **{t1[:6]}** |"
        for t2 in tickers:
            r = matrix.get(t1,{}).get(t2)
            if r is None: row += " — |"
            elif t1==t2:  row += " 1.00 |"
            elif r >= 0.75: row += f" **{r:.2f}** |"
            else: row += f" {r:.2f} |"
        lines.append(row)

    # Position Sizing
    lines.append(f"\n## 💡 Position Sizing (2% Risiko | Portfolio {portfolio_eur:,.0f}€)\n")
    print("  Berechne Position Sizing...")
    sizing = sizing_report(portfolio_eur)
    lines.append("| Position | Kurs | ATR14 | 2×ATR Risiko | Empf. Units | Invest | % Portfolio |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in sorted(sizing, key=lambda x: -x["invest_eur"]):
        lines.append(f"| {s['name']} | {s['price']}€ | {s['atr14']}€ | {s['risk_unit']}€ | {s['units']} | {s['invest_eur']:.0f}€ | {s['pct_port']}% |")

    report = "\n".join(lines)
    with open(REPORT_PATH, "w") as f: f.write(report)
    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv)>1 else "full"
    if mode == "matrix":
        matrix = correlation_matrix()
        high = find_high_correlations(matrix)
        for t1,t2,r in high:
            print(f"{t1} ↔ {t2}: {r:.2f}")
    elif mode == "sizing":
        for s in sizing_report():
            print(f"{s['name']:35} {s['price']:8.2f}€ | ATR {s['atr14']:6.3f} | Empf: {s['invest_eur']:.0f}€ ({s['pct_port']}%)")
    else:
        print("Erstelle Portfolio-Risk-Report...")
        report = write_report()
        print(report)
