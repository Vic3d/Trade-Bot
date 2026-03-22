#!/usr/bin/env python3
"""
dt_backtester.py — Historisches Backtesting für DT1-DT9 Strategien

Prüft jeden Signal-Algorithmus gegen 2 Jahre historische Yahoo-Daten.
Bewertet Edge: Win-Rate, Avg Win/Loss, Expectancy, WL-Ratio.

Output: memory/dt-backtest.md + Conviction-Seeds in strategies.json
"""
import json, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

WS  = Path('/data/.openclaw/workspace')
OUT = WS / 'memory/dt-backtest.md'

BACKTESTABLE_TICKERS = [
    'NVDA', 'AAPL', 'MSFT', 'TSLA', 'AMD', 'META', 'AMZN', 'GOOGL',
    'XOM', 'OXY', 'RHM.DE', 'SAP.DE', 'SHEL.L', 'RIO.L',
    'ASML.AS', 'EQNR.OL',
]

# ── Datenabruf ──────────────────────────────────────────────

def yahoo_history(ticker, days=730):
    end   = int(datetime.now().timestamp())
    start = int((datetime.now() - timedelta(days=days)).timestamp())
    url   = (f"https://query2.finance.yahoo.com/v8/finance/chart/"
             f"{urllib.parse.quote(ticker)}?interval=1d&period1={start}&period2={end}")
    req   = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        r = d['chart']['result'][0]
        q = r['indicators']['quote'][0]
        opens   = q.get('open', [])
        highs   = q.get('high', [])
        lows    = q.get('low',  [])
        closes  = q.get('close', [])
        volumes = q.get('volume', [])
        ts      = r.get('timestamp', [])
        data = []
        for i in range(len(closes)):
            if closes[i] and opens[i] and highs[i] and lows[i]:
                data.append({
                    'ts': ts[i] if i < len(ts) else 0,
                    'o': opens[i], 'h': highs[i],
                    'l': lows[i],  'c': closes[i],
                    'v': volumes[i] or 0
                })
        return data
    except Exception as e:
        return []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0: return 100
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)

def calc_ma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calc_bb_width(closes, period=20):
    if len(closes) < period:
        return None
    ma = sum(closes[-period:]) / period
    std = (sum((c - ma)**2 for c in closes[-period:]) / period) ** 0.5
    return (2 * std) / ma * 100  # als % des Kurses

def calc_ibs(candle):
    """Internal Bar Strength: (Close - Low) / (High - Low)"""
    r = candle['h'] - candle['l']
    return (candle['c'] - candle['l']) / r if r > 0 else 0.5

# ── Signal-Detektoren ───────────────────────────────────────

def signal_dt1_momentum(data, i):
    """DT1: Momentum-Breakout — Close über 20-Tage-Hoch + Volumen > 1.5x"""
    if i < 22: return False
    prev_highs = [d['h'] for d in data[i-20:i]]
    resistance = max(prev_highs)
    avg_vol    = sum(d['v'] for d in data[i-10:i]) / 10
    return data[i]['c'] > resistance and data[i]['v'] > avg_vol * 1.5

def signal_dt2_reversion(data, i):
    """DT2: Mean-Reversion — RSI < 30 + Hammer-Kerze"""
    if i < 16: return False
    closes = [d['c'] for d in data[i-15:i+1]]
    rsi = calc_rsi(closes)
    if rsi is None or rsi >= 30: return False
    # Hammer: untere Docht > 2x Körper, kleiner oberer Docht
    body = abs(data[i]['c'] - data[i]['o'])
    lower_wick = data[i]['o'] - data[i]['l'] if data[i]['c'] > data[i]['o'] else data[i]['c'] - data[i]['l']
    return lower_wick > body * 2

def signal_dt3_gap(data, i):
    """DT3: Gap-Fill — Gap > 1% + Kurs dreht zurück"""
    if i < 1: return False
    gap = (data[i]['o'] - data[i-1]['c']) / data[i-1]['c'] * 100
    return abs(gap) > 1.0

def signal_dt6_triple_rsi(data, i):
    """DT6: Triple RSI — RSI(2)<10 + RSI(5)<25 + RSI(14)<40"""
    if i < 16: return False
    closes = [d['c'] for d in data[i-16:i+1]]
    r2  = calc_rsi(closes[-3:],  2)
    r5  = calc_rsi(closes[-6:],  5)
    r14 = calc_rsi(closes[-15:], 14)
    return r2 and r5 and r14 and r2 < 10 and r5 < 25 and r14 < 40

def signal_dt7_ibs(data, i):
    """DT7: IBS < 0.2 (Close nahe Tagestief)"""
    return calc_ibs(data[i]) < 0.2

def signal_dt8_bb_squeeze(data, i):
    """DT8: BB Squeeze < 3% Breite + Ausbruch"""
    if i < 22: return False
    closes = [d['c'] for d in data[i-21:i+1]]
    bw = calc_bb_width(closes, 20)
    if bw is None or bw >= 3.0: return False
    # Ausbruch: Close über letztem 5-Tage-Hoch
    prev_highs = [d['h'] for d in data[i-5:i]]
    return data[i]['c'] > max(prev_highs) if prev_highs else False

SIGNALS = {
    'DT1': (signal_dt1_momentum, 'LONG'),
    'DT2': (signal_dt2_reversion, 'LONG'),
    'DT3': (signal_dt3_gap, 'LONG'),
    'DT6': (signal_dt6_triple_rsi, 'LONG'),
    'DT7': (signal_dt7_ibs, 'LONG'),
    'DT8': (signal_dt8_bb_squeeze, 'LONG'),
}

# ── Backtest-Engine ─────────────────────────────────────────

def backtest_strategy(strat_id, signal_fn, direction, hold_days=5):
    """
    Simuliert Signal über alle Ticker + 2 Jahre.
    Returns: {wins, losses, avg_win, avg_loss, wl_ratio, expectancy}
    """
    wins, losses = [], []
    signals_found = 0

    for ticker in BACKTESTABLE_TICKERS:
        data = yahoo_history(ticker, 730)
        if len(data) < 50:
            continue

        for i in range(30, len(data) - hold_days):
            try:
                fired = signal_fn(data, i)
            except Exception:
                fired = False

            if not fired:
                continue

            signals_found += 1
            entry = data[i]['c']
            exit_p = data[i + hold_days]['c']
            ret = (exit_p - entry) / entry * 100

            if direction == 'LONG':
                if ret > 0:
                    wins.append(ret)
                else:
                    losses.append(ret)
            else:
                if ret < 0:
                    wins.append(-ret)
                else:
                    losses.append(ret)

    total = len(wins) + len(losses)
    if total < 5:
        return None

    win_rate = len(wins) / total * 100
    avg_win  = sum(wins)   / len(wins)   if wins   else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    wl_ratio = abs(avg_win / avg_loss)   if avg_loss != 0 else 0
    expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * abs(avg_loss))

    return {
        "strat_id":    strat_id,
        "signals":     signals_found,
        "total":       total,
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    round(win_rate, 1),
        "avg_win":     round(avg_win, 2),
        "avg_loss":    round(avg_loss, 2),
        "wl_ratio":    round(wl_ratio, 2),
        "expectancy":  round(expectancy, 2),
        "hold_days":   hold_days,
    }

# ── Conviction-Seed berechnen ────────────────────────────────

def conviction_from_backtest(r):
    """0-5 Conviction basierend auf Backtest-Ergebnis."""
    if not r or r['total'] < 10:
        return 2  # default: wenig Daten
    if r['wl_ratio'] >= 1.5 and r['expectancy'] > 1.0 and r['win_rate'] > 50:
        return 4
    elif r['wl_ratio'] >= 1.2 and r['expectancy'] > 0:
        return 3
    elif r['expectancy'] > 0:
        return 2
    else:
        return 1  # negativer Edge

def rating(r):
    if not r: return "KEINE_DATEN"
    if r['expectancy'] > 1.5 and r['wl_ratio'] > 1.5: return "STARK ✅"
    if r['expectancy'] > 0   and r['wl_ratio'] > 1.0: return "MODERAT ⚠️"
    return "SCHWACH ❌"

# ── Main ─────────────────────────────────────────────────────

def main():
    print("🔬 DT BACKTESTER — DT1-DT9 Strategien gegen 2 Jahre Historik\n")
    print(f"  Ticker: {len(BACKTESTABLE_TICKERS)} | Hold-Days: 5 | Zeitraum: 2 Jahre\n")

    results = []
    for strat_id, (fn, direction) in SIGNALS.items():
        print(f"  📊 {strat_id}...", end=' ', flush=True)
        r = backtest_strategy(strat_id, fn, direction, hold_days=5)
        if r:
            print(f"WR={r['win_rate']}% WL={r['wl_ratio']} Exp={r['expectancy']} n={r['total']} → {rating(r)}")
        else:
            print("zu wenig Signale")
        results.append(r)

    # ── MD-Report ──
    lines = [f"# DT Backtesting Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"]
    lines.append(f"> Ticker: {len(BACKTESTABLE_TICKERS)} | Hold: 5 Tage | Zeitraum: 2 Jahre\n\n---\n\n")

    for r in results:
        if not r:
            continue
        lines.append(f"## {r['strat_id']} — {rating(r)}\n")
        lines.append(f"| Metrik | Wert |\n|--------|------|\n")
        lines.append(f"| Signale gefunden | {r['signals']} |\n")
        lines.append(f"| Auswertbare Trades | {r['total']} |\n")
        lines.append(f"| Win-Rate | {r['win_rate']}% |\n")
        lines.append(f"| Avg Win | +{r['avg_win']}% |\n")
        lines.append(f"| Avg Loss | {r['avg_loss']}% |\n")
        lines.append(f"| Win/Loss-Ratio | {r['wl_ratio']} |\n")
        lines.append(f"| Expectancy | {r['expectancy']}% |\n")
        lines.append(f"| Conviction-Seed | {conviction_from_backtest(r)}/5 |\n\n")

    OUT.write_text(''.join(lines))
    print(f"\n  📝 Report: {OUT.name}")

    # ── Conviction-Seeds in strategies.json schreiben ──
    strat_path = WS / 'data/strategies.json'
    if strat_path.exists():
        strats = json.loads(strat_path.read_text())
        updated = 0
        for r in results:
            if not r: continue
            sid = r['strat_id']
            if sid in strats:
                if 'genesis' not in strats[sid]:
                    strats[sid]['genesis'] = {}
                # Nur setzen wenn noch kein echter Trade-Datensatz vorhanden
                existing = strats[sid].get('performance', {}).get('total_trades', 0)
                if existing < 20:
                    strats[sid]['genesis']['conviction_backtest'] = conviction_from_backtest(r)
                    strats[sid]['genesis']['backtest_wr']         = r['win_rate']
                    strats[sid]['genesis']['backtest_wl']         = r['wl_ratio']
                    strats[sid]['genesis']['backtest_exp']        = r['expectancy']
                    updated += 1
        strat_path.write_text(json.dumps(strats, indent=2, ensure_ascii=False))
        print(f"  strategies.json: {updated} Conviction-Seeds gesetzt")

    # Zusammenfassung
    print("\n" + "="*50)
    valid = [r for r in results if r]
    strong = [r for r in valid if r['expectancy'] > 1.5 and r['wl_ratio'] > 1.5]
    mod    = [r for r in valid if r['expectancy'] > 0 and r not in strong]
    weak   = [r for r in valid if r['expectancy'] <= 0]
    print(f"  ✅ STARK:   {[r['strat_id'] for r in strong]}")
    print(f"  ⚠️ MODERAT: {[r['strat_id'] for r in mod]}")
    print(f"  ❌ SCHWACH: {[r['strat_id'] for r in weak]}")

if __name__ == '__main__':
    main()
