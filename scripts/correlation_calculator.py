#!/usr/bin/env python3
"""
Korrelations-Rechner für Trading-Paare
Berechnet Pearson-Korrelation + lineare Regression auf täglichen Returns (%)
Nutzt Yahoo Finance API — kein pandas, kein numpy, nur stdlib
"""

import math
import json
import re
import urllib.request
import urllib.error
import statistics
from datetime import datetime, date, timedelta
from typing import Optional

WORKSPACE = "/data/.openclaw/workspace"

# Asset-Paare: (ticker_a, ticker_b, label_a, label_b)
ASSET_PAIRS = [
    ("DR0.DE",  "CL=F",   "DR0.DE",        "WTI (CL=F)"),
    ("EQNR.OL", "BZ=F",   "Equinor (EQNR.OL)", "Brent (BZ=F)"),
    ("RIO.L",   "HG=F",   "Rio Tinto (RIO.L)", "Kupfer (HG=F)"),
    ("PLTR",    "^VIX",   "Palantir (PLTR)", "VIX (^VIX)"),
]

# Für Portfolio ↔ VIX nutzen wir einen Portfolio-Proxy (DR0 + EQNR + RIO + PLTR)
PORTFOLIO_TICKERS = ["DR0.DE", "EQNR.OL", "RIO.L", "PLTR"]


# ─────────────────────────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────────────────────────

def fetch_daily_closes(ticker: str, days: int = 180) -> list[tuple[str, float]]:
    """
    Yahoo Finance daily closes.
    Returns [(date_str, close), ...] sorted ascending.
    """
    range_map = {30: "1mo", 60: "3mo", 90: "3mo", 180: "6mo", 365: "1y"}
    # pick smallest range >= days
    yf_range = "6mo"
    for d, r in sorted(range_map.items()):
        if days <= d:
            yf_range = r
            break

    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range={yf_range}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  [WARN] HTTP {e.code} für {ticker}: {e.reason}")
        return []
    except Exception as e:
        print(f"  [WARN] Fetch-Fehler für {ticker}: {e}")
        return []

    try:
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]

        cutoff = (datetime.utcnow() - timedelta(days=days)).timestamp()
        pairs = []
        for ts, c in zip(timestamps, closes):
            if c is None:
                continue
            if ts < cutoff:
                continue
            date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            pairs.append((date_str, float(c)))

        pairs.sort(key=lambda x: x[0])
        return pairs

    except (KeyError, IndexError, TypeError) as e:
        print(f"  [WARN] Parse-Fehler für {ticker}: {e}")
        return []


def fetch_current_price(ticker: str) -> Optional[float]:
    """Holt den letzten verfügbaren Schlusskurs."""
    closes = fetch_daily_closes(ticker, days=5)
    if closes:
        return closes[-1][1]
    return None


# ─────────────────────────────────────────────────────────────────
# MATH HELPERS
# ─────────────────────────────────────────────────────────────────

def pct_changes(closes: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Berechnet tägliche prozentuale Veränderungen (returns)."""
    result = []
    for i in range(1, len(closes)):
        prev = closes[i - 1][1]
        curr = closes[i][1]
        if prev != 0:
            chg = (curr - prev) / prev * 100.0
            result.append((closes[i][0], chg))
    return result


def align_series(
    series_a: list[tuple[str, float]],
    series_b: list[tuple[str, float]]
) -> tuple[list[float], list[float]]:
    """Gibt nur Datenpunkte zurück, die in BEIDEN Serien vorhanden sind (nach Datum)."""
    dict_a = dict(series_a)
    dict_b = dict(series_b)
    common_dates = sorted(set(dict_a.keys()) & set(dict_b.keys()))
    vals_a = [dict_a[d] for d in common_dates]
    vals_b = [dict_b[d] for d in common_dates]
    return vals_a, vals_b


def calculate_correlation(pair_a: list[float], pair_b: list[float]) -> dict:
    """
    Pearson-Korrelation + lineare Regression (OLS) auf den übergebenen Werten.
    Returns: {correlation, r_squared, slope, intercept, std_error, n_days}
    """
    n = len(pair_a)
    if n < 5:
        return {"error": f"Zu wenig Datenpunkte: {n}"}

    mean_a = sum(pair_a) / n
    mean_b = sum(pair_b) / n

    # Kovarianzen / Varianzen
    cov_ab = sum((a - mean_a) * (b - mean_b) for a, b in zip(pair_a, pair_b)) / n
    var_a  = sum((a - mean_a) ** 2 for a in pair_a) / n
    var_b  = sum((b - mean_b) ** 2 for b in pair_b) / n

    std_a = math.sqrt(var_a) if var_a > 0 else 0
    std_b = math.sqrt(var_b) if var_b > 0 else 0

    # Pearson r
    if std_a == 0 or std_b == 0:
        corr = 0.0
    else:
        corr = cov_ab / (std_a * std_b)
    corr = max(-1.0, min(1.0, corr))  # clamp float noise

    # OLS: b_hat = Cov(X,Y)/Var(X), a_hat = mean_Y - b_hat*mean_X
    # Hier: A = X (Rohpreis-Basis, z.B. WTI returns), B = Y (DR0 returns)
    if var_a == 0:
        slope = 0.0
        intercept = mean_b
    else:
        slope = cov_ab / var_a
        intercept = mean_b - slope * mean_a

    # Standard Error of Estimate (Residuen)
    residuals = [(b - (slope * a + intercept)) ** 2 for a, b in zip(pair_a, pair_b)]
    mse = sum(residuals) / n
    std_error = math.sqrt(mse)

    r_squared = corr ** 2

    return {
        "correlation": round(corr, 4),
        "r_squared": round(r_squared, 4),
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
        "std_error": round(std_error, 6),
        "n_days": n,
    }


def predict_price(ticker_a_price: float, pair_stats: dict) -> dict:
    """
    Gibt Preisvorhersage für B, gegeben Preis A.
    Hinweis: Bei Return-basierter Regression ist die Vorhersage in % Return B,
    d.h. wir nutzen das Modell für Szenario-Szenarien relativ.
    Für absoluten Preis-Predict: separate Regression auf Preis-Levels nötig.
    """
    expected = pair_stats["slope"] * ticker_a_price + pair_stats["intercept"]
    std_err  = pair_stats["std_error"]
    return {
        "expected": round(expected, 4),
        "low_1std":  round(expected - std_err, 4),
        "high_1std": round(expected + std_err, 4),
    }


# ─────────────────────────────────────────────────────────────────
# LEVEL-BASED REGRESSION (für Preis-Szenarien)
# ─────────────────────────────────────────────────────────────────

def level_regression(
    closes_a: list[tuple[str, float]],
    closes_b: list[tuple[str, float]]
) -> dict:
    """
    OLS auf Preis-Levels (nicht Returns) für Szenario-Preis-Vorhersagen.
    X = A-Preise, Y = B-Preise (aligned by date).
    """
    vals_a, vals_b = align_series(closes_a, closes_b)
    return calculate_correlation(vals_a, vals_b)


# ─────────────────────────────────────────────────────────────────
# REPORT GENERATOR
# ─────────────────────────────────────────────────────────────────

def _format_pair_section(
    label_a: str,
    label_b: str,
    ticker_a: str,
    ticker_b: str,
    stats_30: dict,
    stats_90: dict,
    stats_180: dict,
    level_stats: dict,
    current_a: Optional[float],
    current_b: Optional[float],
    scenarios_a: list[float],
    currency_a: str = "",
    currency_b: str = "",
) -> str:
    lines = [f"## {label_a} ↔ {label_b}\n"]

    def fmt_stats(stats: dict, label: str) -> str:
        if "error" in stats:
            return f"- **{label}:** ⚠️ {stats['error']}"
        return (
            f"- **Korrelation ({label}):** {stats['correlation']:+.3f} "
            f"| **R²:** {stats['r_squared']:.3f} "
            f"| **n:** {stats['n_days']} Tage"
        )

    lines.append(fmt_stats(stats_30,  "30T"))
    lines.append(fmt_stats(stats_90,  "90T"))
    lines.append(fmt_stats(stats_180, "180T"))

    # Formel auf Level-Regression (für Preis-Szenarien)
    if "error" not in level_stats:
        s = level_stats["slope"]
        i = level_stats["intercept"]
        sign = "+" if i >= 0 else "-"
        name_a_short = ticker_a.split(".")[0]
        name_b_short = ticker_b.split(".")[0].replace("^", "").replace("=F", "")
        lines.append(
            f"- **Preis-Formel:** {name_b_short} = {s:.4f} × {name_a_short} {sign} {abs(i):.2f}"
        )

        if current_a is not None:
            pred = level_stats["slope"] * current_a + level_stats["intercept"]
            err  = level_stats["std_error"]
            lines.append(
                f"- **Aktuell:** {label_b.split('(')[0].strip()} "
                f"{currency_a}{current_a:.2f} → "
                f"{label_a.split('(')[0].strip()} erwartet: "
                f"{currency_b}{pred:.2f} (±{err:.2f})"
            )

        for sc_a in scenarios_a:
            pred = level_stats["slope"] * sc_a + level_stats["intercept"]
            err  = level_stats["std_error"]
            lines.append(
                f"- **Wenn {ticker_b} {currency_a}{sc_a:.0f}:** "
                f"{ticker_a} erwartet: {currency_b}{pred:.2f} (±{err:.2f})"
            )
    else:
        lines.append(f"- **Preis-Formel:** ⚠️ {level_stats['error']}")

    lines.append("")
    return "\n".join(lines)


def generate_report() -> str:
    today = date.today().strftime("%Y-%m-%d")
    print(f"\n📊 Starte Korrelations-Report für {today}...")

    report_lines = [
        f"# Korrelations-Report — {today}",
        "",
        "> Alle Korrelationen auf **täglichen Returns (%)** berechnet.",
        "> Preis-Szenarien nutzen separate Level-Regression.",
        "",
    ]

    # ── 1. DR0.DE ↔ WTI ──────────────────────────────────────────
    print("\n[1/5] DR0.DE ↔ WTI (CL=F)")
    cl_30  = fetch_daily_closes("CL=F",  30)
    cl_90  = fetch_daily_closes("CL=F",  90)
    cl_180 = fetch_daily_closes("CL=F", 180)
    dr_30  = fetch_daily_closes("DR0.DE",  30)
    dr_90  = fetch_daily_closes("DR0.DE",  90)
    dr_180 = fetch_daily_closes("DR0.DE", 180)

    def corr_returns(a_closes, b_closes):
        ra = pct_changes(a_closes)
        rb = pct_changes(b_closes)
        va, vb = align_series(ra, rb)
        return calculate_correlation(va, vb)

    stats_30  = corr_returns(cl_30, dr_30)
    stats_90  = corr_returns(cl_90, dr_90)
    stats_180 = corr_returns(cl_180, dr_180)

    # Level-Regression: X=WTI (USD), Y=DR0 (EUR) — auf gemeinsame Daten
    va_lv, vb_lv = align_series(cl_180, dr_180)
    lv_stats = calculate_correlation(va_lv, vb_lv) if va_lv else {"error": "Keine Daten"}

    cur_cl = fetch_current_price("CL=F")
    cur_dr = fetch_current_price("DR0.DE")
    scenarios_wti = []
    if cur_cl:
        scenarios_wti = [round(cur_cl * f, 0) for f in [1.05, 1.10, 0.95]]

    report_lines.append(
        _format_pair_section(
            "DR0.DE", "WTI (CL=F)", "DR0.DE", "CL=F",
            stats_30, stats_90, stats_180, lv_stats,
            cur_cl, cur_dr,
            scenarios_wti,
            currency_a="$", currency_b="€",
        )
    )

    # ── 2. EQNR.OL ↔ Brent ───────────────────────────────────────
    print("[2/5] EQNR.OL ↔ Brent (BZ=F)")
    bz_30  = fetch_daily_closes("BZ=F",     30)
    bz_90  = fetch_daily_closes("BZ=F",     90)
    bz_180 = fetch_daily_closes("BZ=F",    180)
    eq_30  = fetch_daily_closes("EQNR.OL",  30)
    eq_90  = fetch_daily_closes("EQNR.OL",  90)
    eq_180 = fetch_daily_closes("EQNR.OL", 180)

    stats_30  = corr_returns(bz_30, eq_30)
    stats_90  = corr_returns(bz_90, eq_90)
    stats_180 = corr_returns(bz_180, eq_180)
    va_lv, vb_lv = align_series(bz_180, eq_180)
    lv_stats_eq = calculate_correlation(va_lv, vb_lv) if va_lv else {"error": "Keine Daten"}

    cur_bz = fetch_current_price("BZ=F")
    cur_eq = fetch_current_price("EQNR.OL")
    scenarios_bz = []
    if cur_bz:
        scenarios_bz = [round(cur_bz * f, 0) for f in [1.05, 1.10, 0.95]]

    report_lines.append(
        _format_pair_section(
            "Equinor (EQNR.OL)", "Brent (BZ=F)", "EQNR.OL", "BZ=F",
            stats_30, stats_90, stats_180, lv_stats_eq,
            cur_bz, cur_eq,
            scenarios_bz,
            currency_a="$", currency_b="NOK ",
        )
    )

    # ── 3. RIO.L ↔ Kupfer ────────────────────────────────────────
    print("[3/5] RIO.L ↔ Kupfer (HG=F)")
    hg_30  = fetch_daily_closes("HG=F",  30)
    hg_90  = fetch_daily_closes("HG=F",  90)
    hg_180 = fetch_daily_closes("HG=F", 180)
    ri_30  = fetch_daily_closes("RIO.L",  30)
    ri_90  = fetch_daily_closes("RIO.L",  90)
    ri_180 = fetch_daily_closes("RIO.L", 180)

    stats_30  = corr_returns(hg_30, ri_30)
    stats_90  = corr_returns(hg_90, ri_90)
    stats_180 = corr_returns(hg_180, ri_180)
    va_lv, vb_lv = align_series(hg_180, ri_180)
    lv_stats_rio = calculate_correlation(va_lv, vb_lv) if va_lv else {"error": "Keine Daten"}

    cur_hg = fetch_current_price("HG=F")
    cur_ri = fetch_current_price("RIO.L")
    scenarios_hg = []
    if cur_hg:
        scenarios_hg = [round(cur_hg * f, 2) for f in [1.05, 1.10, 0.95]]

    report_lines.append(
        _format_pair_section(
            "Rio Tinto (RIO.L)", "Kupfer (HG=F)", "RIO.L", "HG=F",
            stats_30, stats_90, stats_180, lv_stats_rio,
            cur_hg, cur_ri,
            scenarios_hg,
            currency_a="$", currency_b="GBp ",
        )
    )

    # ── 4. PLTR ↔ VIX ────────────────────────────────────────────
    print("[4/5] PLTR ↔ VIX (^VIX)")
    vix_30  = fetch_daily_closes("^VIX",  30)
    vix_90  = fetch_daily_closes("^VIX",  90)
    vix_180 = fetch_daily_closes("^VIX", 180)
    pl_30   = fetch_daily_closes("PLTR",  30)
    pl_90   = fetch_daily_closes("PLTR",  90)
    pl_180  = fetch_daily_closes("PLTR", 180)

    stats_30  = corr_returns(vix_30, pl_30)
    stats_90  = corr_returns(vix_90, pl_90)
    stats_180 = corr_returns(vix_180, pl_180)
    va_lv, vb_lv = align_series(vix_180, pl_180)
    lv_stats_pltr = calculate_correlation(va_lv, vb_lv) if va_lv else {"error": "Keine Daten"}

    cur_vix  = fetch_current_price("^VIX")
    cur_pltr = fetch_current_price("PLTR")
    scenarios_vix = []
    if cur_vix:
        scenarios_vix = [round(cur_vix * f, 0) for f in [0.8, 1.2, 1.5]]

    report_lines.append(
        _format_pair_section(
            "Palantir (PLTR)", "VIX (^VIX)", "PLTR", "^VIX",
            stats_30, stats_90, stats_180, lv_stats_pltr,
            cur_vix, cur_pltr,
            scenarios_vix,
            currency_a="", currency_b="$",
        )
    )

    # ── 5. Portfolio ↔ VIX ───────────────────────────────────────
    print("[5/5] Portfolio ↔ VIX (^VIX)")
    # Portfolio = gleichgewichteter Return-Index
    portfolio_returns_180: dict[str, list[tuple[str, float]]] = {}
    for tkr in PORTFOLIO_TICKERS:
        cl = fetch_daily_closes(tkr, 180)
        if cl:
            portfolio_returns_180[tkr] = pct_changes(cl)

    # Aggregate: für jeden Datum den Durchschnitts-Return
    all_dates: set[str] = set()
    for rets in portfolio_returns_180.values():
        for d, _ in rets:
            all_dates.add(d)

    port_agg: list[tuple[str, float]] = []
    for d in sorted(all_dates):
        vals = []
        for rets in portfolio_returns_180.values():
            dmap = dict(rets)
            if d in dmap:
                vals.append(dmap[d])
        if len(vals) >= 2:
            port_agg.append((d, sum(vals) / len(vals)))

    vix_ret_180 = pct_changes(vix_180)
    vp_a, vp_b = align_series(vix_ret_180, port_agg)
    stats_port_180 = calculate_correlation(vp_a, vp_b) if vp_a else {"error": "Keine Daten"}

    vix_ret_90 = pct_changes(vix_90)
    port_90 = [(d, v) for d, v in port_agg if d >= (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")]
    vp90_a, vp90_b = align_series(vix_ret_90, port_90)
    stats_port_90 = calculate_correlation(vp90_a, vp90_b) if vp90_a else {"error": "Keine Daten"}

    vix_ret_30 = pct_changes(vix_30)
    port_30 = [(d, v) for d, v in port_agg if d >= (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")]
    vp30_a, vp30_b = align_series(vix_ret_30, port_30)
    stats_port_30 = calculate_correlation(vp30_a, vp30_b) if vp30_a else {"error": "Keine Daten"}

    def fmt_stats_port(stats, label):
        if "error" in stats:
            return f"- **{label}:** ⚠️ {stats['error']}"
        return (
            f"- **Korrelation ({label}):** {stats['correlation']:+.3f} "
            f"| **R²:** {stats['r_squared']:.3f} | **n:** {stats['n_days']} Tage"
        )

    port_section = "## Portfolio gesamt ↔ VIX (^VIX)\n\n"
    port_section += fmt_stats_port(stats_port_30, "30T") + "\n"
    port_section += fmt_stats_port(stats_port_90, "90T") + "\n"
    port_section += fmt_stats_port(stats_port_180, "180T") + "\n"
    if "error" not in stats_port_180:
        note = "inverse" if stats_port_180["correlation"] < 0 else "positiv"
        port_section += f"- **Charakter:** Korrelation ist **{note}** (VIX steigt → Portfolio {'fällt' if note == 'inverse' else 'steigt'})\n"
    if cur_vix:
        port_section += f"- **Aktueller VIX:** {cur_vix:.2f}\n"
    port_section += "\n"

    report_lines.append(port_section)

    # ── Footer ───────────────────────────────────────────────────
    report_lines += [
        "---",
        f"*Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Quelle: Yahoo Finance*",
        "",
    ]

    return "\n".join(report_lines)


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    report = generate_report()

    out_path = f"{WORKSPACE}/memory/correlation-report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n✅ Report gespeichert: {out_path}")
    print("\n" + "=" * 60)
    print(report[:2000])
    if len(report) > 2000:
        print(f"... [{len(report) - 2000} weitere Zeichen]")
