#!/usr/bin/env python3
"""
thesis_validator.py — Historische Überprüfung der Eriksen/Dirk 7H Thesen

Prüft jede These gegen historische Daten und bewertet:
  STARK    (>70% historische Trefferquote)
  MODERAT  (50-70%)
  SCHWACH  (<50% oder zu wenig Daten)

Speichert Ergebnis in memory/thesis-validation.md
"""
import json, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timedelta, date

WS = Path('/data/.openclaw/workspace')
OUT = WS / 'memory/thesis-validation.md'

# ── Datenabruf ──────────────────────────────────────────────

def yahoo_history(ticker, days=365):
    """Holt tägliche OHLCV-Daten der letzten N Tage."""
    end = int(datetime.now().timestamp())
    start = int((datetime.now() - timedelta(days=days)).timestamp())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(ticker)}?interval=1d"
           f"&period1={start}&period2={end}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = d['chart']['result'][0]
        ts = result['timestamp']
        closes = result['indicators']['quote'][0]['close']
        return [(datetime.fromtimestamp(t).date(), c)
                for t, c in zip(ts, closes) if c is not None]
    except Exception as e:
        print(f"  ⚠️ Yahoo Fehler {ticker}: {e}")
        return []

def to_series(data):
    """Liste von (date, price) → dict"""
    return {d: p for d, p in data}

# ── These 1: Brent-WTI Spread > $8 → PS1 bullish ───────────

def validate_brent_wti_spread():
    """
    These: Wenn Brent-WTI Spread > $8, dann Öl-Aktien (EQNR, XOM) outperformen
    in den folgenden 4 Wochen.
    Historisch prüfen: Spread > $8 → EQNR-Rendite nächste 4 Wochen
    """
    print("\n📊 These 1: Brent-WTI Spread > $8 → Öl-Aktien bullish")
    brent = to_series(yahoo_history("BZ=F", 730))
    wti   = to_series(yahoo_history("CL=F", 730))
    eqnr  = to_series(yahoo_history("EQNR.OL", 730))

    if not brent or not wti or not eqnr:
        return {"thesis": "Brent-WTI Spread > $8 → PS1 bullish",
                "result": "KEINE_DATEN", "score": None, "hits": 0, "total": 0}

    dates = sorted(set(brent) & set(wti) & set(eqnr))
    hits, total = 0, 0

    for i, d in enumerate(dates[:-28]):
        spread = brent[d] - wti[d]
        if spread > 8:
            # 4 Wochen später
            future_dates = [dd for dd in dates if dd > d][:28]
            if len(future_dates) >= 20:
                future_price = eqnr.get(future_dates[-1])
                current_price = eqnr[d]
                if future_price and current_price:
                    total += 1
                    if future_price > current_price:
                        hits += 1

    rate = hits / total * 100 if total > 0 else 0
    rating = "STARK" if rate > 70 else ("MODERAT" if rate > 50 else "SCHWACH")
    print(f"  Spread > $8 Ereignisse: {total} | EQNR +4W: {hits}/{total} ({rate:.0f}%) → {rating}")
    return {"thesis": "Brent-WTI Spread > $8 → Öl-Aktien +4W bullish",
            "result": rating, "score": round(rate, 1), "hits": hits, "total": total}

# ── These 2: VIX > 25 → Growth-Aktien underperformen ────────

def validate_vix_growth():
    """
    These (Eriksen): VIX > 25 + Öl > $95 → Growth (NVDA, PLTR) underperformen Markt
    """
    print("\n📊 These 2: VIX > 25 → Growth underperformt")
    vix  = to_series(yahoo_history("^VIX", 730))
    nvda = to_series(yahoo_history("NVDA", 730))
    spy  = to_series(yahoo_history("SPY", 730))

    if not vix or not nvda or not spy:
        return {"thesis": "VIX > 25 → Growth underperformt", "result": "KEINE_DATEN",
                "score": None, "hits": 0, "total": 0}

    dates = sorted(set(vix) & set(nvda) & set(spy))
    hits, total = 0, 0

    for i, d in enumerate(dates[:-14]):
        if vix[d] > 25:
            future = [dd for dd in dates if dd > d][:14]
            if len(future) >= 10:
                nvda_ret = (nvda.get(future[-1], nvda[d]) / nvda[d] - 1) * 100
                spy_ret  = (spy.get(future[-1], spy[d])  / spy[d]  - 1) * 100
                total += 1
                if nvda_ret < spy_ret:  # NVDA schlechter als Markt
                    hits += 1

    rate = hits / total * 100 if total > 0 else 0
    rating = "STARK" if rate > 70 else ("MODERAT" if rate > 50 else "SCHWACH")
    print(f"  VIX > 25 Ereignisse: {total} | NVDA < SPY +2W: {hits}/{total} ({rate:.0f}%) → {rating}")
    return {"thesis": "VIX > 25 → NVDA underperformt SPY +2W",
            "result": rating, "score": round(rate, 1), "hits": hits, "total": total}

# ── These 3: S&P unter 200-MA → weitere Schwäche ────────────

def validate_sp500_200ma():
    """
    These (Eriksen/Klassisch): S&P 500 unter 200-Tage-MA → nächste 4W negativ
    """
    print("\n📊 These 3: S&P500 unter 200-MA → weitere Schwäche")
    spy = yahoo_history("SPY", 800)
    if len(spy) < 200:
        return {"thesis": "S&P unter 200-MA → Schwäche", "result": "KEINE_DATEN",
                "score": None, "hits": 0, "total": 0}

    prices = spy
    hits, total = 0, 0

    for i in range(200, len(prices) - 20):
        d, price = prices[i]
        ma200 = sum(p for _, p in prices[i-200:i]) / 200

        if price < ma200:
            # 4 Wochen später
            future_price = prices[min(i+20, len(prices)-1)][1]
            total += 1
            if future_price < price:
                hits += 1

    rate = hits / total * 100 if total > 0 else 0
    rating = "STARK" if rate > 60 else ("MODERAT" if rate > 45 else "SCHWACH")
    print(f"  Unter 200-MA Ereignisse: {total} | SPY weiter -4W: {hits}/{total} ({rate:.0f}%) → {rating}")
    return {"thesis": "S&P500 unter 200-MA → +4W weiter negativ",
            "result": rating, "score": round(rate, 1), "hits": hits, "total": total}

# ── These 4: Dirk 7H — Hohe Win-Rate ohne Kontowachstum ─────

def validate_winrate_vs_expectancy():
    """
    These (Dirk 7H): Win-Rate allein sagt nichts — Expectancy ist der echte KPI
    Prüfe in unserer eigenen DB: Korrelation Win-Rate vs. P&L pro Strategie
    """
    print("\n📊 These 4: Win-Rate allein ≠ Profitabilität (Dirk 7H)")
    import sqlite3
    db = WS / 'data/trading.db'
    if not db.exists():
        return {"thesis": "Win-Rate ≠ Profitabilität", "result": "KEINE_DATEN",
                "score": None, "hits": 0, "total": 0}

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT strategy, pnl_pct, status FROM trades
        WHERE status IN ('WIN','LOSS') AND pnl_pct IS NOT NULL
    """).fetchall()
    conn.close()

    if len(rows) < 5:
        print(f"  Zu wenig Trades ({len(rows)}) für Auswertung")
        return {"thesis": "Win-Rate ≠ Profitabilität", "result": "ZU_WENIG_DATEN",
                "score": None, "hits": len(rows), "total": len(rows)}

    wins = [r for r in rows if r['status'] == 'WIN']
    losses = [r for r in rows if r['status'] == 'LOSS']
    win_rate = len(wins) / len(rows) * 100
    avg_win = sum(r['pnl_pct'] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r['pnl_pct'] for r in losses) / len(losses) if losses else 0
    expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * abs(avg_loss))
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # These bestätigt wenn: Win-Rate sieht ok aus aber Expectancy negativ
    thesis_confirmed = win_rate > 45 and expectancy < 0
    print(f"  Win-Rate: {win_rate:.0f}% | Avg Win: {avg_win:.1f}% | Avg Loss: {avg_loss:.1f}%")
    print(f"  WL-Ratio: {wl_ratio:.2f} | Expectancy: {expectancy:.2f}")
    print(f"  These bestätigt: {'JA — Win-Rate täuscht!' if thesis_confirmed else 'NEIN — Portfolio gesund'}")

    rating = "STARK" if thesis_confirmed else "MODERAT"
    return {"thesis": "Win-Rate allein ≠ Profitabilität",
            "result": rating, "score": round(win_rate, 1),
            "expectancy": round(expectancy, 2), "wl_ratio": round(wl_ratio, 2),
            "hits": len(rows), "total": len(rows)}

# ── Ergebnisse speichern ────────────────────────────────────

def save_results(results):
    today = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f"# Thesis Validation — {today}\n\n"]
    lines.append("> Automatisch generiert durch thesis_validator.py\n")
    lines.append("> Quellen: Yahoo Finance Historik + eigene Tradingdaten\n\n---\n\n")

    for r in results:
        icon = "✅" if r['result'] == "STARK" else ("⚠️" if r['result'] == "MODERAT" else "❌")
        lines.append(f"## {icon} {r['thesis']}\n")
        lines.append(f"- **Bewertung:** {r['result']}\n")
        if r.get('score') is not None:
            lines.append(f"- **Trefferquote:** {r['score']}%\n")
        if r.get('expectancy') is not None:
            lines.append(f"- **Expectancy:** {r['expectancy']} | WL-Ratio: {r.get('wl_ratio')}\n")
        lines.append(f"- **Datenpunkte:** {r['hits']}/{r['total']}\n\n")

    lines.append("---\n*Nächste Validierung empfohlen: in 30 Tagen oder nach 20+ neuen Trades*\n")
    OUT.write_text(''.join(lines))
    print(f"\n  📝 Ergebnisse gespeichert → {OUT.name}")

# ── Main ────────────────────────────────────────────────────

if __name__ == '__main__':
    print("🔬 THESIS VALIDATOR — Historische Überprüfung der Eriksen/Dirk 7H Thesen\n")
    results = []
    results.append(validate_brent_wti_spread())
    results.append(validate_vix_growth())
    results.append(validate_sp500_200ma())
    results.append(validate_winrate_vs_expectancy())
    save_results(results)

    # Zusammenfassung
    print("\n" + "="*50)
    print("FAZIT:")
    for r in results:
        icon = "✅" if r['result'] == "STARK" else ("⚠️" if r['result'] == "MODERAT" else "❌")
        score = f"{r['score']}%" if r.get('score') else r['result']
        print(f"  {icon} {r['thesis'][:50]}: {score}")
