#!/usr/bin/env python3
"""
Correlation Matrix — misst Portfolio-Korrelation und warnt bei Klumpenrisiko.

Problem: NVDA + MSFT + PLTR + Cyber-ETF = faktisch eine Tech-Wette.
Wenn NDX fällt, fallen alle vier gleichzeitig.

Usage:
  python3 correlation_matrix.py           → Voller Report
  python3 correlation_matrix.py check     → Nur Warnungen
"""

import urllib.request, json, os, sys
from datetime import datetime

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "correlation-report.md")

# Tickers für Korrelationsberechnung (Yahoo-Symbole)
TICKERS = {
    "NVDA":   {"yahoo": "NVDA",    "fx": "EURUSD=X", "sector": "Tech/KI"},
    "MSFT":   {"yahoo": "MSFT",    "fx": "EURUSD=X", "sector": "Tech/KI"},
    "PLTR":   {"yahoo": "PLTR",    "fx": "EURUSD=X", "sector": "Tech/KI"},
    "EQNR":   {"yahoo": "EQNR.OL", "fx": "EURNOK=X", "sector": "Energie/Öl"},
    "RIO.L":  {"yahoo": "RIO.L",   "fx": "GBPEUR=X", "sector": "Rohstoffe"},
    "BAYN":   {"yahoo": "BAYN.DE", "fx": None,        "sector": "Pharma"},
    "Solar":  {"yahoo": "TAN",     "fx": "EURUSD=X",  "sector": "Energie/Solar"},
    "OilSvc": {"yahoo": "OIH",     "fx": "EURUSD=X",  "sector": "Energie/Öl"},
    "Cyber":  {"yahoo": "ISPY.L",  "fx": "GBPEUR=X",  "sector": "Tech/KI"},
    "Biotech":{"yahoo": "IBB",     "fx": "EURUSD=X",  "sector": "Gesundheit"},
}

WARN_THRESHOLD = 0.75   # Korrelation > 0.75 = Klumpenrisiko
CONCERN_THRESHOLD = 0.55  # Korrelation > 0.55 = beobachten


def fetch_returns(yahoo_sym: str, fx_pair: str = None, period: int = 60) -> list:
    """Holt tägliche Returns (%) für die letzten N Handelstage."""
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1d&range=3mo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0].get("close", []) if c]
    except:
        return []

    if not closes or len(closes) < 2:
        return []

    # FX-Konvertierung (vereinfacht — für Korrelation ist es egal, Returns in Lokalwährung reichen)
    returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100
               for i in range(1, len(closes))]
    return returns[-period:]


def pearson_correlation(a: list, b: list) -> float | None:
    """Pearson-Korrelationskoeffizient."""
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num    = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    den_a  = sum((x - mean_a)**2 for x in a) ** 0.5
    den_b  = sum((x - mean_b)**2 for x in b) ** 0.5
    if den_a == 0 or den_b == 0:
        return None
    return round(num / (den_a * den_b), 3)


def build_matrix() -> dict:
    """Berechnet Korrelationsmatrix für alle Portfolio-Positionen."""
    print("Hole Returns für alle Positionen...")
    returns = {}
    for name, info in TICKERS.items():
        r = fetch_returns(info["yahoo"], info.get("fx"))
        returns[name] = r
        status = f"{len(r)} Tage" if r else "FEHLER"
        print(f"  {name}: {status}")

    matrix = {}
    names = list(returns.keys())
    for i, a in enumerate(names):
        matrix[a] = {}
        for b in names:
            if a == b:
                matrix[a][b] = 1.0
            elif b in matrix and a in matrix[b]:
                matrix[a][b] = matrix[b][a]
            else:
                c = pearson_correlation(returns.get(a, []), returns.get(b, []))
                matrix[a][b] = c

    return matrix, returns


def find_warnings(matrix: dict) -> list:
    """Findet hohe Korrelationen = Klumpenrisiko."""
    warnings = []
    names = list(matrix.keys())
    seen = set()
    for a in names:
        for b in names:
            if a == b or (b, a) in seen:
                continue
            seen.add((a, b))
            c = matrix[a].get(b)
            if c is None:
                continue
            if c >= WARN_THRESHOLD:
                sector_a = TICKERS[a]["sector"]
                sector_b = TICKERS[b]["sector"]
                warnings.append({
                    "pair": (a, b),
                    "corr": c,
                    "level": "HIGH",
                    "msg": f"🔴 {a} ↔ {b}: {c:.2f} — KLUMPENRISIKO (beide in {sector_a})"
                           if sector_a == sector_b else
                           f"🔴 {a} ↔ {b}: {c:.2f} — hohe Korrelation (sektorübergreifend)"
                })
            elif c >= CONCERN_THRESHOLD:
                warnings.append({
                    "pair": (a, b),
                    "corr": c,
                    "level": "MEDIUM",
                    "msg": f"🟡 {a} ↔ {b}: {c:.2f} — erhöhte Korrelation, beobachten"
                })
    return sorted(warnings, key=lambda x: -x["corr"])


def sector_exposure(matrix: dict) -> dict:
    """Aggregiert Korrelation nach Sektor."""
    sectors = {}
    for name, info in TICKERS.items():
        s = info["sector"]
        if s not in sectors:
            sectors[s] = []
        sectors[s].append(name)
    return sectors


def write_report(matrix: dict, warnings: list) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    names = list(matrix.keys())

    lines = [
        f"# Portfolio-Korrelationsmatrix\n*{now}*\n",
        "## ⚠️ Warnungen\n",
    ]

    if not warnings:
        lines.append("✅ Keine kritischen Korrelationen gefunden.\n")
    else:
        high = [w for w in warnings if w["level"] == "HIGH"]
        med  = [w for w in warnings if w["level"] == "MEDIUM"]
        for w in high:
            lines.append(w["msg"])
        if med:
            lines.append("\n**Erhöhte Korrelationen:**")
            for w in med[:5]:
                lines.append(w["msg"])

    lines.append("\n## Korrelationsmatrix (60 Handelstage)\n")
    header = "| " + " | ".join([""] + names) + " |"
    sep    = "|" + "|".join([":---:"] * (len(names)+1)) + "|"
    lines.append(header)
    lines.append(sep)
    for a in names:
        row = [a]
        for b in names:
            c = matrix[a].get(b)
            if c is None:
                row.append("—")
            elif a == b:
                row.append("1.00")
            elif c >= WARN_THRESHOLD:
                row.append(f"**{c:.2f}**")
            else:
                row.append(f"{c:.2f}")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("\n## Sektor-Übersicht\n")
    sectors = sector_exposure(matrix)
    for sector, tickers in sectors.items():
        lines.append(f"- **{sector}**: {', '.join(tickers)}")

    report = "\n".join(lines)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    matrix, returns = build_matrix()
    warnings = find_warnings(matrix)

    if mode == "check":
        high = [w for w in warnings if w["level"] == "HIGH"]
        if high:
            print("⚠️ KLUMPENRISIKO ERKANNT:")
            for w in high:
                print(f"  {w['msg']}")
        else:
            print("✅ Keine kritischen Korrelationen.")
    else:
        report = write_report(matrix, warnings)
        print(report)
        print(f"\nReport gespeichert: {REPORT_PATH}")
