#!/usr/bin/env python3
"""
Day Trading Engine — Intraday Paper Trading
=============================================
25.000€ imaginäres Kapital. Strategien:
- DT1: Momentum Breakout (VWAP + Volume)
- DT2: Mean Reversion (RSI Oversold Bounce)
- DT3: Gap Fill (Opening Gap > 2%)
- DT4: Trend Following (EMA9/EMA21 Cross Intraday)

Regeln:
- Max 5 gleichzeitige Day Trades
- Positionsgröße: 5.000€ (20% vom Pool)
- Risk: 1% pro Trade (250€ max Loss)
- EOD Auto-Close um 21:45 CET (vor US Close)
- Kein Overnight-Hold

Läuft alle 5 Min via Cron (09:00-22:00 CET Mo-Fr).
"""

import sqlite3, json, math, urllib.request, urllib.parse, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
DB_PATH = WORKSPACE / 'data/trading.db'
DT_STATE = WORKSPACE / 'memory/daytrader-state.json'
DNA_JSON = WORKSPACE / 'data/dna.json'

CAPITAL = 25000
POS_SIZE = 5000       # €5k pro Trade (20% vom Pool)
MAX_POSITIONS = 5
RISK_PCT = 0.01       # 1% Risk = 250€
EOD_CLOSE_HOUR = 21   # 21:45 CET → alles schließen
EOD_CLOSE_MIN = 45

# Day Trading Watchlist — liquide Aktien mit gutem Spread
DT_UNIVERSE = [
    # US Large Cap (höchste Liquidität)
    {'ticker': 'NVDA', 'name': 'Nvidia', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'AAPL', 'name': 'Apple', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'MSFT', 'name': 'Microsoft', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'TSLA', 'name': 'Tesla', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'AMD', 'name': 'AMD', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'META', 'name': 'Meta', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'AMZN', 'name': 'Amazon', 'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'PLTR', 'name': 'Palantir', 'market': 'US', 'open_h': 15, 'close_h': 22},
    # DE Xetra
    {'ticker': 'RHM.DE', 'name': 'Rheinmetall', 'market': 'DE', 'open_h': 9, 'close_h': 17},
    {'ticker': 'SAP.DE', 'name': 'SAP', 'market': 'DE', 'open_h': 9, 'close_h': 17},
    {'ticker': 'SIE.DE', 'name': 'Siemens', 'market': 'DE', 'open_h': 9, 'close_h': 17},
    {'ticker': 'BAYN.DE', 'name': 'Bayer', 'market': 'DE', 'open_h': 9, 'close_h': 17},
]


# ─── Yahoo Finance (Intraday) ────────────────────────────────────────

def yahoo_intraday(ticker, interval='5m', range='1d'):
    """Holt Intraday-Daten (5m Kerzen)."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval={interval}&range={range}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = d['chart']['result'][0]
        meta = result['meta']
        price = meta['regularMarketPrice']
        prev_close = meta.get('chartPreviousClose', price)
        currency = meta.get('currency', 'USD')
        
        # Kerzen extrahieren
        timestamps = result.get('timestamp', [])
        quotes = result['indicators']['quote'][0]
        candles = []
        for i in range(len(timestamps)):
            c = {
                'time': timestamps[i],
                'open': quotes['open'][i],
                'high': quotes['high'][i],
                'low': quotes['low'][i],
                'close': quotes['close'][i],
                'volume': quotes['volume'][i],
            }
            if c['close'] is not None:
                candles.append(c)
        
        return {
            'price': price,
            'prev_close': prev_close,
            'currency': currency,
            'candles': candles,
            'gap_pct': (candles[0]['open'] / prev_close - 1) * 100 if candles and prev_close else 0,
        }
    except Exception as e:
        return None


def to_eur(price, currency):
    if not price or currency == 'EUR':
        return price
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        eurusd = d['chart']['result'][0]['meta']['regularMarketPrice']
        if currency == 'USD':
            return round(price / eurusd, 4)
        if currency in ('GBP', 'GBp'):
            if currency == 'GBp':
                price /= 100
            gbpusd_url = f"https://query2.finance.yahoo.com/v8/finance/chart/GBPUSD=X?interval=1d&range=1d"
            req2 = urllib.request.Request(gbpusd_url, headers={"User-Agent": "Mozilla/5.0"})
            d2 = json.loads(urllib.request.urlopen(req2, timeout=8).read())
            gbpusd = d2['chart']['result'][0]['meta']['regularMarketPrice']
            return round(price * gbpusd / eurusd, 4)
    except:
        pass
    return price


# ─── Technische Indikatoren (Intraday) ───────────────────────────────

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema


def calc_vwap(candles):
    """Volume-Weighted Average Price."""
    total_vp = 0
    total_vol = 0
    for c in candles:
        typical = (c['high'] + c['low'] + c['close']) / 3
        vol = c['volume'] or 1
        total_vp += typical * vol
        total_vol += vol
    return total_vp / total_vol if total_vol > 0 else None


# ─── Signal Detection ────────────────────────────────────────────────

def detect_dt_signals(ticker_info, data):
    """Prüft alle Day-Trading Strategien für einen Ticker."""
    signals = []
    candles = data['candles']
    if len(candles) < 20:
        return signals
    
    closes = [c['close'] for c in candles]
    volumes = [c['volume'] or 0 for c in candles]
    price = data['price']
    prev_close = data['prev_close']
    
    # RSI
    rsi = calc_rsi(closes)
    
    # EMAs
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    
    # VWAP
    vwap = calc_vwap(candles)
    
    # Avg Volume
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
    current_vol = volumes[-1] if volumes else 0
    
    # ── DT1: Momentum Breakout ──
    # Price > VWAP + Volume > 2x Average + Trend Up
    if vwap and price > vwap and current_vol > avg_vol * 1.5 and ema9 and ema21 and ema9 > ema21:
        stop_eur = round(vwap * 0.995, 2)  # 0.5% unter VWAP
        target_eur = round(price * 1.01, 2)  # +1% Target
        signals.append({
            'strategy': 'DT1',
            'direction': 'LONG',
            'reason': f'Momentum: Price > VWAP ({vwap:.2f}), Vol {current_vol/avg_vol:.1f}x avg, EMA9>EMA21',
            'stop': stop_eur,
            'target': target_eur,
            'confidence': min(90, 50 + int((current_vol / avg_vol - 1) * 20)),
        })
    
    # ── DT2: Mean Reversion (RSI Oversold) ──
    if rsi and rsi < 30 and price < (vwap or price * 2):
        # RSI oversold + unter VWAP = Bounce-Setup
        stop_eur = round(price * 0.99, 2)   # -1% Stop
        target_eur = round(vwap or price * 1.01, 2)  # Target = VWAP
        signals.append({
            'strategy': 'DT2',
            'direction': 'LONG',
            'reason': f'Mean Reversion: RSI {rsi} (oversold), Price < VWAP',
            'stop': stop_eur,
            'target': target_eur,
            'confidence': min(85, 40 + int((30 - rsi) * 2)),
        })
    
    # ── DT3: Gap Fill ──
    gap = data.get('gap_pct', 0)
    if abs(gap) > 2.0 and len(candles) < 30:  # Nur in erster Stunde
        direction = 'SHORT' if gap > 0 else 'LONG'  # Gap Fill = gegen Gap handeln
        stop_eur = round(price * (1.01 if direction == 'SHORT' else 0.99), 2)
        target_eur = round(prev_close, 2)  # Target = Previous Close (Gap Fill)
        signals.append({
            'strategy': 'DT3',
            'direction': direction,
            'reason': f'Gap Fill: {gap:+.1f}% Gap, Target = Prev Close {prev_close:.2f}',
            'stop': stop_eur,
            'target': target_eur,
            'confidence': min(80, 40 + int(abs(gap) * 5)),
        })
    
    # ── DT4: EMA Cross ──
    if ema9 and ema21 and len(closes) >= 22:
        prev_ema9 = calc_ema(closes[:-1], 9)
        prev_ema21 = calc_ema(closes[:-1], 21)
        if prev_ema9 and prev_ema21:
            # Bullish Cross
            if prev_ema9 <= prev_ema21 and ema9 > ema21:
                stop_eur = round(ema21 * 0.998, 2)
                target_eur = round(price * 1.008, 2)  # +0.8%
                signals.append({
                    'strategy': 'DT4',
                    'direction': 'LONG',
                    'reason': f'EMA Cross: EMA9 ({ema9:.2f}) crossed above EMA21 ({ema21:.2f})',
                    'stop': stop_eur,
                    'target': target_eur,
                    'confidence': 55,
                })
            # Bearish Cross
            elif prev_ema9 >= prev_ema21 and ema9 < ema21:
                stop_eur = round(ema21 * 1.002, 2)
                target_eur = round(price * 0.992, 2)  # -0.8%
                signals.append({
                    'strategy': 'DT4',
                    'direction': 'SHORT',
                    'reason': f'EMA Cross: EMA9 ({ema9:.2f}) crossed below EMA21 ({ema21:.2f})',
                    'stop': stop_eur,
                    'target': target_eur,
                    'confidence': 55,
                })
    
    return signals


# ─── DB Operations ───────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def count_open_dt():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM trades WHERE trade_type='day_trade' AND status='OPEN'").fetchone()[0]
    conn.close()
    return count

def open_dt_trade(ticker, name, strategy, direction, entry_eur, stop, target, reason, currency):
    shares = max(1, math.floor(POS_SIZE / entry_eur))
    risk = abs(entry_eur - stop) * shares
    
    conn = get_db()
    conn.execute("""
        INSERT INTO trades (ticker, strategy, direction, entry_price, entry_date,
            stop, target, shares, status, trade_type, thesis, fees_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 'day_trade', ?, 0)
    """, (
        ticker, strategy, direction, round(entry_eur, 2),
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
        round(stop, 2), round(target, 2), shares, reason
    ))
    conn.commit()
    trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    
    print(f"  🟢 OPEN {direction} {ticker} ({name}) @ {entry_eur:.2f}€ × {shares} = {entry_eur*shares:.0f}€")
    print(f"     Strategy: {strategy} | Stop: {stop:.2f}€ | Target: {target:.2f}€ | Risk: {risk:.0f}€")
    print(f"     Reason: {reason}")
    return trade_id

def close_dt_trade(trade_id, exit_price, reason='EOD'):
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not trade:
        conn.close()
        return
    
    entry = trade['entry_price']
    shares = trade['shares'] or 1
    direction = trade['direction'] or 'LONG'
    
    if direction == 'LONG':
        pnl = (exit_price - entry) * shares
        pnl_pct = (exit_price / entry - 1) * 100
    else:
        pnl = (entry - exit_price) * shares
        pnl_pct = (entry / exit_price - 1) * 100
    
    status = 'WIN' if pnl > 0 else 'LOSS'
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    
    conn.execute("""
        UPDATE trades SET exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?, status=?, holding_days=0
        WHERE id=?
    """, (round(exit_price, 2), now, round(pnl, 2), round(pnl_pct, 2), status, trade_id))
    conn.commit()
    conn.close()
    
    emoji = "✅" if status == 'WIN' else "❌"
    print(f"  {emoji} CLOSE {trade['ticker']}: {entry:.2f} → {exit_price:.2f} ({pnl_pct:+.1f}%) P&L: {pnl:+.1f}€ [{reason}]")
    return pnl


# ─── Main Loop ────────────────────────────────────────────────────────

def load_state():
    if DT_STATE.exists():
        return json.loads(DT_STATE.read_text())
    return {'daily_pnl': 0, 'daily_trades': 0, 'last_date': None, 'signals_today': []}

def save_state(state):
    DT_STATE.write_text(json.dumps(state, indent=2))

def main():
    from zoneinfo import ZoneInfo
    now_cet = datetime.now(ZoneInfo('Europe/Berlin'))
    now_utc = datetime.now(timezone.utc)
    
    print(f"[{now_cet.strftime('%H:%M CET')}] Day Trader läuft...")
    
    state = load_state()
    today = now_cet.strftime('%Y-%m-%d')
    
    # Daily Reset
    if state.get('last_date') != today:
        state = {'daily_pnl': 0, 'daily_trades': 0, 'last_date': today, 'signals_today': []}
    
    conn = get_db()
    open_dts = conn.execute("""
        SELECT id, ticker, direction, entry_price, stop, target, shares, strategy
        FROM trades WHERE trade_type='day_trade' AND status='OPEN'
    """).fetchall()
    conn.close()
    
    print(f"  Offene Day Trades: {len(open_dts)}/{MAX_POSITIONS}")
    
    # ── 1. EOD Auto-Close ──
    if now_cet.hour >= EOD_CLOSE_HOUR and now_cet.minute >= EOD_CLOSE_MIN:
        if open_dts:
            print(f"  🕘 EOD Close — {len(open_dts)} Positionen schließen")
            for dt in open_dts:
                data = yahoo_intraday(dt['ticker'])
                if data:
                    price_eur = to_eur(data['price'], data['currency'])
                    if price_eur:
                        pnl = close_dt_trade(dt['id'], price_eur, 'EOD Auto-Close')
                        state['daily_pnl'] += (pnl or 0)
                        state['daily_trades'] += 1
            save_state(state)
            # DNA regenerieren
            regenerate_dna()
            return
    
    # ── 2. Stop/Target Check für offene Trades ──
    for dt in open_dts:
        data = yahoo_intraday(dt['ticker'])
        if not data:
            continue
        
        price_eur = to_eur(data['price'], data['currency'])
        if not price_eur:
            continue
        
        direction = dt['direction']
        stop = dt['stop']
        target = dt['target']
        
        # Stop Hit
        if stop:
            if (direction == 'LONG' and price_eur <= stop) or (direction == 'SHORT' and price_eur >= stop):
                pnl = close_dt_trade(dt['id'], price_eur, 'Stop Hit')
                state['daily_pnl'] += (pnl or 0)
                state['daily_trades'] += 1
                continue
        
        # Target Hit
        if target:
            if (direction == 'LONG' and price_eur >= target) or (direction == 'SHORT' and price_eur <= target):
                pnl = close_dt_trade(dt['id'], price_eur, 'Target Hit')
                state['daily_pnl'] += (pnl or 0)
                state['daily_trades'] += 1
                continue
        
        # Status
        if direction == 'LONG':
            pnl_pct = (price_eur / dt['entry_price'] - 1) * 100
        else:
            pnl_pct = (dt['entry_price'] / price_eur - 1) * 100
        emoji = "🟢" if pnl_pct > 0 else "🔴"
        print(f"  {emoji} {dt['ticker']:8s} {price_eur:.2f}€ ({pnl_pct:+.1f}%) | S:{stop:.2f} T:{target:.2f}")
    
    # ── 3. Neue Signale scannen ──
    open_count = count_open_dt()
    if open_count >= MAX_POSITIONS:
        print(f"  ⏸️ Max Positionen ({MAX_POSITIONS}) erreicht — kein neuer Scan")
        save_state(state)
        return
    
    # Daily P&L Limit: Stop bei -500€ (2% vom Kapital)
    if state['daily_pnl'] <= -500:
        print(f"  🛑 Daily Loss Limit erreicht: {state['daily_pnl']:.0f}€ — kein neuer Scan")
        save_state(state)
        return
    
    hour = now_cet.hour
    for ticker_info in DT_UNIVERSE:
        if open_count >= MAX_POSITIONS:
            break
        
        ticker = ticker_info['ticker']
        
        # Nur während Marktzeiten scannen
        if hour < ticker_info['open_h'] or hour >= ticker_info['close_h']:
            continue
        
        # Schon heute gehandelt?
        if ticker in state['signals_today']:
            continue
        
        # Schon eine offene Position?
        conn = get_db()
        existing = conn.execute("SELECT id FROM trades WHERE ticker=? AND trade_type='day_trade' AND status='OPEN'", (ticker,)).fetchone()
        conn.close()
        if existing:
            continue
        
        data = yahoo_intraday(ticker)
        if not data:
            continue
        
        signals = detect_dt_signals(ticker_info, data)
        if not signals:
            continue
        
        # Bestes Signal nehmen (höchste Confidence)
        best = max(signals, key=lambda s: s['confidence'])
        
        price_eur = to_eur(data['price'], data['currency'])
        if not price_eur:
            continue
        
        stop_eur = to_eur(best['stop'], data['currency']) or best['stop']
        target_eur = to_eur(best['target'], data['currency']) or best['target']
        
        open_dt_trade(
            ticker, ticker_info['name'], best['strategy'],
            best['direction'], price_eur, stop_eur, target_eur,
            best['reason'], data['currency']
        )
        
        state['signals_today'].append(ticker)
        open_count += 1
    
    save_state(state)
    
    # DNA regenerieren wenn sich was geändert hat
    regenerate_dna()
    
    # Summary
    print(f"\n  📈 Daily P&L: {state['daily_pnl']:+.0f}€ | Trades: {state['daily_trades']} | Open: {open_count}")


def regenerate_dna():
    """DNA Report regenerieren (importiert paper_monitor)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("paper_monitor", str(WORKSPACE / 'scripts/paper_monitor.py'))
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        pm.generate_dna_json()
    except Exception as e:
        print(f"  ⚠️ DNA regeneration failed: {e}")


def push_to_git():
    try:
        subprocess.run(['git', 'add', str(DNA_JSON), str(DT_STATE)], cwd=str(WORKSPACE), capture_output=True, timeout=10)
        result = subprocess.run(
            ['git', 'commit', '-m', f'🏎️ Day Trade update {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} [skip ci]'],
            cwd=str(WORKSPACE), capture_output=True, timeout=10
        )
        if result.returncode == 0:
            subprocess.run(['git', 'push'], cwd=str(WORKSPACE), capture_output=True, timeout=30)
    except:
        pass


if __name__ == '__main__':
    main()
