#!/usr/bin/env python3
"""
Albert Stock Screener v1.0
==========================
Vollständiges Aktien-Bewertungssystem nach aktien-bewertung.md v2

5 Stufen:
1. Top-Down (Makro) — manuell vom Analysten
2. Technische Analyse — Yahoo Finance Chart-Daten
3. Fundamentalanalyse — Finnhub Metriken + FCF
4. Relative Bewertung — Branchenvergleich (Median)
5. Praxis-Check — manuell

Usage:
    python3 stock_screener.py VLO MPC PSX DINO TTE
    python3 stock_screener.py --sector "Raffinerien" VLO MPC PSX DINO PBF TTE
"""

import urllib.request
import json
import sys
import os
import time
from datetime import datetime

# === CONFIG ===
FINNHUB_KEY = None
ENV_PATH = '/data/.openclaw/workspace/.env'
if os.path.exists(ENV_PATH):
    for line in open(ENV_PATH):
        if line.startswith('FINNHUB_KEY='):
            FINNHUB_KEY = line.strip().split('=', 1)[1]

EURUSD = 1.16  # Fallback, wird live geholt

# === API FUNCTIONS ===

def yahoo_chart(ticker, range='6mo'):
    """Holt Chart-Daten von Yahoo Finance (funktioniert ohne Auth)"""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={range}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    result = data['chart']['result'][0]
    meta = result['meta']
    q = result['indicators']['quote'][0]
    closes = [c for c in q['close'] if c is not None]
    volumes = [v for v in q['volume'] if v is not None]
    highs = [h for h in q['high'] if h is not None]
    lows = [l for l in q['low'] if l is not None]
    return {
        'price': meta['regularMarketPrice'],
        'currency': meta.get('currency', 'USD'),
        'closes': closes,
        'volumes': volumes,
        'highs': highs,
        'lows': lows,
    }

def finnhub_metrics(ticker):
    """Holt Fundamental-Metriken von Finnhub"""
    if not FINNHUB_KEY:
        return {}
    url = f'https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={FINNHUB_KEY}'
    try:
        data = json.loads(urllib.request.urlopen(url, timeout=8).read())
        return data.get('metric', {})
    except:
        return {}

# === STUFE 2: TECHNISCHE ANALYSE ===

def technical_analysis(chart_data):
    """Berechnet technische Indikatoren"""
    closes = chart_data['closes']
    volumes = chart_data['volumes']
    price = chart_data['price']
    
    result = {}
    
    # EMAs
    result['ema20'] = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    result['ema50'] = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    result['above_ema20'] = price > result['ema20'] if result['ema20'] else None
    result['above_ema50'] = price > result['ema50'] if result['ema50'] else None
    
    # RSI(14)
    if len(closes) >= 15:
        gains, losses = [], []
        for i in range(-14, 0):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        result['rsi'] = 100 - (100 / (1 + avg_g / max(avg_l, 0.001)))
    
    # Vom 3M-Hoch
    high_3m = max(closes[-65:]) if len(closes) >= 65 else max(closes)
    result['high_3m'] = high_3m
    result['from_high'] = (price - high_3m) / high_3m * 100
    
    # A/D Ratio (10 Tage)
    if len(closes) >= 10 and len(volumes) >= 10:
        up_vol = sum(volumes[-10:][i] for i in range(1, min(10, len(volumes[-10:])))
                     if i < len(closes[-10:]) and closes[-10:][i] > closes[-10:][i-1])
        dn_vol = sum(volumes[-10:][i] for i in range(1, min(10, len(volumes[-10:])))
                     if i < len(closes[-10:]) and closes[-10:][i] <= closes[-10:][i-1])
        result['ad_ratio'] = up_vol / max(dn_vol, 1)
    
    # Abverkaufs-Volumen
    drop_vols = []
    avg_vol = sum(volumes) / len(volumes) if volumes else 1
    for i in range(1, len(closes)):
        if (closes[i] - closes[i-1]) / closes[i-1] < -0.03 and i < len(volumes):
            drop_vols.append(volumes[i])
    result['drop_vol_ratio'] = (sum(drop_vols) / len(drop_vols)) / avg_vol if drop_vols else 0
    result['avg_volume'] = avg_vol
    
    # Performance
    if len(closes) >= 65:
        result['perf_3m'] = (closes[-1] - closes[-65]) / closes[-65] * 100
    if len(closes) >= 22:
        result['perf_1m'] = (closes[-1] - closes[-22]) / closes[-22] * 100
    
    return result

def tech_score(ta):
    """Berechnet technischen Score"""
    score = 0
    details = []
    
    if ta.get('above_ema20'):
        score += 2; details.append("✅ Über EMA20")
    elif ta.get('above_ema20') is not None:
        score -= 2; details.append("❌ Unter EMA20")
    
    if ta.get('above_ema50'):
        score += 1; details.append("✅ Über EMA50")
    elif ta.get('above_ema50') is not None:
        score -= 2; details.append("❌ Unter EMA50")
    
    rsi = ta.get('rsi', 50)
    if rsi < 30:
        score += 1; details.append(f"🟢 RSI {rsi:.0f} überverkauft")
    elif rsi > 70:
        score -= 1; details.append(f"🟡 RSI {rsi:.0f} überkauft")
    else:
        details.append(f"⚪ RSI {rsi:.0f}")
    
    fh = ta.get('from_high', 0)
    if fh > -5:
        score += 2; details.append(f"✅ Nur {fh:+.1f}% vom Hoch")
    elif fh > -10:
        score += 1; details.append(f"🟡 {fh:+.1f}% vom Hoch")
    elif fh > -15:
        score += 0; details.append(f"🟡 {fh:+.1f}% vom Hoch")
    else:
        score -= 2; details.append(f"❌ {fh:+.1f}% vom Hoch")
    
    ad = ta.get('ad_ratio', 1)
    if ad > 1.5:
        score += 2; details.append(f"✅ A/D {ad:.1f}x (Käufer)")
    elif ad > 1.0:
        score += 1; details.append(f"🟡 A/D {ad:.1f}x")
    else:
        score -= 1; details.append(f"❌ A/D {ad:.1f}x (Verkäufer)")
    
    dvr = ta.get('drop_vol_ratio', 0)
    if dvr > 1.5:
        score -= 1; details.append(f"⚠️ Distribution ({dvr:.1f}x Vol bei Drops)")
    else:
        score += 1; details.append(f"✅ Keine Distribution")
    
    return score, details

# === STUFE 3: FUNDAMENTALANALYSE ===

def fundamental_analysis(metrics):
    """Bewertet Fundamental-Metriken"""
    result = {
        'pe': metrics.get('peBasicExclExtraTTM'),
        'pb': metrics.get('pbQuarterly'),
        'ev_ebitda': metrics.get('currentEv/freeCashFlowTTM'),  # EV/FCF als Proxy
        'margin': metrics.get('netProfitMarginTTM'),
        'gross_margin': metrics.get('grossMarginTTM'),
        'op_margin': metrics.get('operatingMarginTTM'),
        'roe': metrics.get('roeTTM'),
        'roa': metrics.get('roaTTM'),
        'debt_eq': metrics.get('totalDebt/totalEquityQuarterly'),
        'current_ratio': metrics.get('currentRatioQuarterly'),
        'div_yield': metrics.get('dividendYieldIndicatedAnnual'),
        'rev_growth': metrics.get('revenueGrowthQuarterlyYoy'),
        'eps_growth': metrics.get('epsGrowthQuarterlyYoy'),
        'fcf_per_share': metrics.get('cashFlowPerShareTTM'),
        'ev_fcf': metrics.get('currentEv/freeCashFlowTTM'),
        'pfcf': metrics.get('pfcfShareTTM'),
        'mcap': metrics.get('marketCapitalization'),
        'ev': metrics.get('enterpriseValue'),
    }
    
    # FCF Yield berechnen
    if result['fcf_per_share'] and result['mcap'] and result['pfcf']:
        result['fcf_yield'] = 100 / result['pfcf'] if result['pfcf'] > 0 else None
    else:
        result['fcf_yield'] = None
    
    return result

def check_disqualification(fa):
    """Prüft auf automatische Disqualifikation"""
    flags = []
    if fa.get('margin') is not None and fa['margin'] < 0:
        flags.append(f"⛔ Negative Margin: {fa['margin']:.1f}%")
    if fa.get('debt_eq') is not None and fa['debt_eq'] > 5:
        flags.append(f"⛔ Debt/Equity: {fa['debt_eq']:.1f}x (>5x)")
    if fa.get('pe') is not None and fa['pe'] > 100:
        flags.append(f"⛔ P/E: {fa['pe']:.0f}x (>100x)")
    return flags

# === STUFE 4: RELATIVE BEWERTUNG ===

def relative_ranking(all_fundamentals):
    """
    Berechnet Rang jeder Aktie relativ zum Branchenmedian.
    
    Bewertungs-Kennzahlen (niedriger = besser): pe, pb, ev_fcf, pfcf
    Qualitäts-Kennzahlen (höher = besser): margin, gross_margin, roe, roa, fcf_yield, div_yield
    Schulden (niedriger = besser): debt_eq
    """
    tickers = list(all_fundamentals.keys())
    if len(tickers) < 2:
        return {t: {'rank': 1, 'percentile': 50} for t in tickers}
    
    # Kennzahlen und ihre Richtung
    metrics_config = {
        'pe': 'lower',
        'pb': 'lower',
        'ev_fcf': 'lower',
        'pfcf': 'lower',
        'margin': 'higher',
        'gross_margin': 'higher',
        'op_margin': 'higher',
        'roe': 'higher',
        'roa': 'higher',
        'fcf_yield': 'higher',
        'div_yield': 'higher',
        'debt_eq': 'lower',
        'current_ratio': 'higher',
    }
    
    # Für jede Metrik: Rang berechnen
    rank_sums = {t: 0 for t in tickers}
    rank_count = {t: 0 for t in tickers}
    
    details = {t: {} for t in tickers}
    medians = {}
    
    for metric, direction in metrics_config.items():
        # Sammle verfügbare Werte
        values = {}
        for t in tickers:
            v = all_fundamentals[t].get(metric)
            if v is not None and v != 0:
                values[t] = v
        
        if len(values) < 2:
            continue
        
        # Median berechnen
        sorted_vals = sorted(values.values())
        mid = len(sorted_vals) // 2
        median = sorted_vals[mid] if len(sorted_vals) % 2 else (sorted_vals[mid-1] + sorted_vals[mid]) / 2
        medians[metric] = median
        
        # Rang vergeben
        if direction == 'lower':
            ranked = sorted(values.items(), key=lambda x: x[1])  # niedrigster = Rang 1
        else:
            ranked = sorted(values.items(), key=lambda x: -x[1])  # höchster = Rang 1
        
        for rank, (t, v) in enumerate(ranked, 1):
            rank_sums[t] += rank
            rank_count[t] += 1
            vs_median = "✅" if (direction == 'lower' and v <= median) or (direction == 'higher' and v >= median) else "❌"
            details[t][metric] = {'value': v, 'rank': rank, 'median': median, 'vs_median': vs_median}
    
    # Durchschnittsrang
    avg_ranks = {}
    for t in tickers:
        if rank_count[t] > 0:
            avg_ranks[t] = rank_sums[t] / rank_count[t]
        else:
            avg_ranks[t] = len(tickers)  # Worst rank if no data
    
    # Sortiere nach Durchschnittsrang
    final_ranking = sorted(avg_ranks.items(), key=lambda x: x[1])
    
    result = {}
    for final_rank, (t, avg_r) in enumerate(final_ranking, 1):
        n = len(tickers)
        percentile = (1 - (final_rank - 1) / max(n - 1, 1)) * 100
        result[t] = {
            'final_rank': final_rank,
            'avg_rank': avg_r,
            'percentile': percentile,
            'details': details[t],
        }
    
    return result, medians

# === HAUPTFUNKTION ===

def screen_stocks(tickers, sector_name="Sektor"):
    """Vollständiges Screening aller Tickers"""
    
    print(f"\n{'='*100}")
    print(f"  📊 ALBERT STOCK SCREENER v1.0 — {sector_name}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(tickers)} Kandidaten")
    print(f"{'='*100}")
    
    all_tech = {}
    all_fund = {}
    all_charts = {}
    errors = []
    
    # === Daten sammeln ===
    print(f"\n  📡 Daten laden...")
    for ticker in tickers:
        try:
            # Chart-Daten
            chart = yahoo_chart(ticker)
            ta = technical_analysis(chart)
            all_tech[ticker] = ta
            all_charts[ticker] = chart
            
            # Fundamental-Daten
            metrics = finnhub_metrics(ticker.split('.')[0])
            fa = fundamental_analysis(metrics)
            all_fund[ticker] = fa
            
            print(f"    ✅ {ticker}")
            time.sleep(0.3)  # Rate limit
        except Exception as e:
            errors.append(f"{ticker}: {e}")
            print(f"    ❌ {ticker}: {e}")
    
    if errors:
        print(f"\n  ⚠️ Fehler bei: {', '.join(errors)}")
    
    # === Peer-Vergleich (Stufe 4) ===
    ranking, medians = relative_ranking(all_fund) if len(all_fund) >= 2 else ({}, {})
    
    # === Ergebnisse ===
    
    # Übersichtstabelle
    print(f"\n{'─'*100}")
    print(f"  {'Ticker':<10} {'Kurs':>8} {'EMA20':>6} {'EMA50':>6} {'RSI':>5} {'vHoch':>7} {'A/D':>5} {'T.Sc':>5} │ {'P/E':>7} {'Margin':>7} {'ROE':>6} {'D/E':>5} {'FCF.Y':>6} {'F.Sc':>5} │ {'Rang':>4}")
    print(f"  {'─'*97}")
    
    results = []
    
    for ticker in tickers:
        if ticker not in all_tech:
            continue
        
        ta = all_tech[ticker]
        fa = all_fund.get(ticker, {})
        chart = all_charts[ticker]
        
        t_score, t_details = tech_score(ta)
        disq = check_disqualification(fa)
        
        # Fundamental Score
        f_score = 0
        if fa.get('pe') and fa['pe'] < medians.get('pe', 20): f_score += 1
        if fa.get('margin') and fa['margin'] > medians.get('margin', 3): f_score += 1
        if fa.get('roe') and fa['roe'] > medians.get('roe', 10): f_score += 1
        if fa.get('debt_eq') and fa['debt_eq'] < medians.get('debt_eq', 1): f_score += 1
        if fa.get('fcf_yield') and fa['fcf_yield'] > 5: f_score += 1
        if fa.get('gross_margin') and fa['gross_margin'] > medians.get('gross_margin', 5): f_score += 1
        
        rank_info = ranking.get(ticker, {})
        final_rank = rank_info.get('final_rank', '?')
        
        e20 = "✅" if ta.get('above_ema20') else "❌"
        e50 = "✅" if ta.get('above_ema50') else "❌"
        
        pe_s = f"{fa['pe']:.1f}" if fa.get('pe') else "N/A"
        margin_s = f"{fa['margin']:.1f}%" if fa.get('margin') is not None else "N/A"
        roe_s = f"{fa['roe']:.1f}" if fa.get('roe') else "N/A"
        de_s = f"{fa['debt_eq']:.1f}" if fa.get('debt_eq') is not None else "N/A"
        fcfy_s = f"{fa['fcf_yield']:.1f}%" if fa.get('fcf_yield') else "N/A"
        
        disq_flag = " ⛔" if disq else ""
        
        print(f"  {ticker:<10} ${chart['price']:>7.2f}   {e20}    {e50}  {ta.get('rsi',0):>4.0f} {ta.get('from_high',0):>+6.1f}% {ta.get('ad_ratio',0):>4.1f}x {t_score:>+4d}  │ {pe_s:>7} {margin_s:>7} {roe_s:>6} {de_s:>5} {fcfy_s:>6} {f_score:>+4d}  │ #{final_rank}{disq_flag}")
        
        results.append({
            'ticker': ticker,
            'price': chart['price'],
            'currency': chart['currency'],
            'tech_score': t_score,
            'tech_details': t_details,
            'fund_score': f_score,
            'fund_data': fa,
            'disqualified': disq,
            'rank': final_rank,
            'rank_info': rank_info,
        })
    
    # === Branchenmediane ===
    if medians:
        print(f"\n  📊 Branchenmediane ({sector_name}):")
        for k, v in sorted(medians.items()):
            print(f"    {k}: {v:.2f}")
    
    # === Detailberichte ===
    print(f"\n{'='*100}")
    print(f"  🏆 DETAIL-ANALYSE (sortiert nach Gesamtrang)")
    print(f"{'='*100}")
    
    results.sort(key=lambda x: (bool(x['disqualified']), -x['tech_score'] - x['fund_score']))
    
    for r in results:
        ticker = r['ticker']
        
        # Gesamt-Urteil
        if r['disqualified']:
            verdict = "🔴 DISQUALIFIZIERT"
        elif r['tech_score'] >= 5 and r['fund_score'] >= 3:
            verdict = "🟢 KAUFBAR"
        elif r['tech_score'] >= 2 and r['fund_score'] >= 2:
            verdict = "🟡 WATCHLIST"
        else:
            verdict = "🔴 MEIDEN"
        
        print(f"\n  {'─'*90}")
        print(f"  {verdict}  {ticker} — Rang #{r['rank']}")
        print(f"  Tech Score: {r['tech_score']:+d} | Fund Score: {r['fund_score']:+d}")
        
        if r['disqualified']:
            for d in r['disqualified']:
                print(f"    {d}")
        
        print(f"  Technik:")
        for d in r['tech_details']:
            print(f"    {d}")
        
        fa = r['fund_data']
        print(f"  Fundamentals:")
        if fa.get('pe'): print(f"    P/E: {fa['pe']:.1f}x (Median: {medians.get('pe','?')})")
        if fa.get('margin') is not None: print(f"    Net Margin: {fa['margin']:.1f}% (Median: {medians.get('margin','?')})")
        if fa.get('gross_margin'): print(f"    Gross Margin: {fa['gross_margin']:.1f}%")
        if fa.get('roe'): print(f"    ROE: {fa['roe']:.1f}%")
        if fa.get('debt_eq') is not None: print(f"    Debt/Eq: {fa['debt_eq']:.1f}x")
        if fa.get('fcf_yield'): print(f"    FCF Yield: {fa['fcf_yield']:.1f}%")
        if fa.get('div_yield'): print(f"    Dividende: {fa['div_yield']:.1f}%")
        if fa.get('rev_growth') is not None: print(f"    Revenue Growth: {fa['rev_growth']:+.1f}%")
        
        # Relative Bewertung
        ri = r.get('rank_info', {})
        if ri.get('details'):
            print(f"  Rel. Bewertung vs. Peers:")
            for metric, info in sorted(ri['details'].items()):
                print(f"    {info['vs_median']} {metric}: {info['value']:.2f} (Median: {info['median']:.2f}, Rang {info['rank']})")
    
    print(f"\n{'='*100}")
    print(f"  ⚠️  Dies ist ein Screening — kein DCF-Gutachten.")
    print(f"  Fehlende Daten (besonders bei EU-Aktien) sind gekennzeichnet.")
    print(f"{'='*100}\n")
    
    return results


# === MAIN ===
if __name__ == '__main__':
    args = sys.argv[1:]
    
    sector = "Sektor"
    tickers = []
    
    i = 0
    while i < len(args):
        if args[i] == '--sector' and i + 1 < len(args):
            sector = args[i + 1]
            i += 2
        else:
            tickers.append(args[i].upper())
            i += 1
    
    if not tickers:
        print("Usage: python3 stock_screener.py [--sector NAME] TICKER1 TICKER2 ...")
        print("Example: python3 stock_screener.py --sector Raffinerien VLO MPC PSX DINO TTE")
        sys.exit(1)
    
    screen_stocks(tickers, sector)
