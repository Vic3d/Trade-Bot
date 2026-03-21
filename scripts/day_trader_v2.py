#!/usr/bin/env python3
"""
Day Trader v2 — Aggressiver Paper Trading für Datensammlung
=============================================================
Ziel: DATEN SAMMELN. Jeder Trade lehrt uns etwas.
Paper Money = kein echtes Risiko. Lieber 10 Trades mit 40% Win-Rate
als 0 Trades mit theoretisch perfektem Setup.

Kapital: 25.000€ | Position: 5.000€ | Max 5 gleichzeitig | 1% Risk
Läuft alle 5 Min via Cron (Mo-Fr 09:00-22:00 CET)
"""

import sqlite3, json, math, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path('/data/.openclaw/workspace')
DB_PATH = WORKSPACE / 'data/trading.db'
DT_STATE = WORKSPACE / 'memory/daytrader-state.json'
LOG_PATH = WORKSPACE / 'memory/daytrader-log.md'

CAPITAL = 25000
POS_SIZE = 5000
MAX_POSITIONS = 5
RISK_PCT = 0.01
EOD_CLOSE_HOUR = 21
EOD_CLOSE_MIN = 45
DYNAMIC_UNIVERSE_PATH = WORKSPACE / 'data' / 'dynamic_universe.json'

# Statisches Fallback-Universum (wird genutzt wenn dynamic_universe.json nicht existiert)
# Im Normalbetrieb: stock_scanner.py liefert 30-50 Top-Mover aus ~120 Aktien
# Xetra 09:00-17:30 | London 09:00-17:30 | Euronext 09:00-17:30 | Oslo 09:00-16:20 | US 15:30-22:00
DT_UNIVERSE = [
    # ── DE Xetra (09:00-17:30 CET) ──
    {'ticker': 'RHM.DE', 'name': 'Rheinmetall',   'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'SAP.DE', 'name': 'SAP',           'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'SIE.DE', 'name': 'Siemens',       'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'DTE.DE', 'name': 'Dt. Telekom',   'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'ALV.DE', 'name': 'Allianz',       'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'MBG.DE', 'name': 'Mercedes-Benz', 'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'BAS.DE', 'name': 'BASF',          'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'IFX.DE', 'name': 'Infineon',      'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'BAYN.DE','name': 'Bayer',          'market': 'DE', 'open_h': 9,  'close_h': 17},
    {'ticker': 'ADS.DE', 'name': 'Adidas',        'market': 'DE', 'open_h': 9,  'close_h': 17},
    # ── UK London (09:00-17:30 CET = 08:00-16:30 GMT) ──
    {'ticker': 'SHEL.L', 'name': 'Shell',         'market': 'UK', 'open_h': 9,  'close_h': 17},
    {'ticker': 'BP.L',   'name': 'BP',            'market': 'UK', 'open_h': 9,  'close_h': 17},
    {'ticker': 'RIO.L',  'name': 'Rio Tinto',     'market': 'UK', 'open_h': 9,  'close_h': 17},
    {'ticker': 'GLEN.L', 'name': 'Glencore',      'market': 'UK', 'open_h': 9,  'close_h': 17},
    {'ticker': 'HSBA.L', 'name': 'HSBC',          'market': 'UK', 'open_h': 9,  'close_h': 17},
    {'ticker': 'AZN.L',  'name': 'AstraZeneca',   'market': 'UK', 'open_h': 9,  'close_h': 17},
    # ── EU Euronext (09:00-17:30 CET) ──
    {'ticker': 'ASML.AS','name': 'ASML',           'market': 'EU', 'open_h': 9,  'close_h': 17},
    {'ticker': 'TTE.PA', 'name': 'TotalEnergies',  'market': 'EU', 'open_h': 9,  'close_h': 17},
    {'ticker': 'MC.PA',  'name': 'LVMH',           'market': 'EU', 'open_h': 9,  'close_h': 17},
    {'ticker': 'SAN.PA', 'name': 'Sanofi',         'market': 'EU', 'open_h': 9,  'close_h': 17},
    # ── Norwegen Oslo (09:00-16:20 CET) ──
    {'ticker': 'EQNR.OL','name': 'Equinor',        'market': 'NO', 'open_h': 9,  'close_h': 16},
    # ── US NYSE/NASDAQ (15:30-22:00 CET) ──
    {'ticker': 'NVDA',   'name': 'Nvidia',         'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'AAPL',   'name': 'Apple',          'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'MSFT',   'name': 'Microsoft',      'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'TSLA',   'name': 'Tesla',          'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'AMD',    'name': 'AMD',            'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'META',   'name': 'Meta',           'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'AMZN',   'name': 'Amazon',         'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'PLTR',   'name': 'Palantir',       'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'GOOGL',  'name': 'Alphabet',       'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'NFLX',   'name': 'Netflix',        'market': 'US', 'open_h': 15, 'close_h': 22},
    # US Energie
    {'ticker': 'XOM',    'name': 'ExxonMobil',     'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'OXY',    'name': 'Occidental',     'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'HAL',    'name': 'Halliburton',    'market': 'US', 'open_h': 15, 'close_h': 22},
    # US Rohstoffe
    {'ticker': 'FCX',    'name': 'Freeport Cu',    'market': 'US', 'open_h': 15, 'close_h': 22},
    {'ticker': 'NEM',    'name': 'Newmont',        'market': 'US', 'open_h': 15, 'close_h': 22},
]

# Sektor-Mapping für DT9 (erweitert auf EU/UK)
SECTOR_MAP = {
    'XLK': ['NVDA','AAPL','MSFT','AMD','META','AMZN','GOOGL','NFLX','PLTR','SAP.DE','ASML.AS','IFX.DE'],
    'XLE': ['XOM','OXY','HAL','SHEL.L','BP.L','TTE.PA','EQNR.OL'],
    'XLF': ['ALV.DE','HSBA.L'],
    'XLV': [],
    'XLI': ['RHM.DE','SIE.DE'],
}


def yahoo_intraday(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=5m&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = d['chart']['result'][0]
        meta = result['meta']
        timestamps = result.get('timestamp', [])
        quotes = result['indicators']['quote'][0]
        candles = []
        for i in range(len(timestamps)):
            if quotes['close'][i] is not None:
                candles.append({
                    'open': quotes['open'][i], 'high': quotes['high'][i],
                    'low': quotes['low'][i], 'close': quotes['close'][i],
                    'volume': quotes['volume'][i] or 0
                })
        prev = meta.get('chartPreviousClose', meta['regularMarketPrice'])
        gap = ((meta['regularMarketPrice'] / prev) - 1) * 100 if prev else 0
        return {
            'price': meta['regularMarketPrice'], 'prev_close': prev,
            'currency': meta.get('currency', 'USD'), 'candles': candles, 'gap_pct': gap
        }
    except:
        return None


def to_eur(price, currency):
    if currency == 'EUR': return price
    # GBp = Pence → erst in GBP umrechnen
    if currency == 'GBp':
        price = price / 100
        currency = 'GBP'
    try:
        # FX-Rate holen (EURGBP, EURUSD, EURNOK etc.)
        pair = f"EUR{currency}=X"
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{pair}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        fx = d['chart']['result'][0]['meta']['regularMarketPrice']
        return round(price / fx, 4) if fx else price
    except:
        # Fallbacks für häufige Währungen
        fallbacks = {'USD': 1.08, 'GBP': 0.86, 'NOK': 11.5, 'CHF': 0.97}
        if currency in fallbacks:
            return round(price / fallbacks[currency], 4)
        return price


def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0: return 100
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def calc_ema(closes, period):
    if len(closes) < period: return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema


def calc_vwap(candles):
    total_vp, total_vol = 0, 0
    for c in candles:
        typical = (c['high'] + c['low'] + c['close']) / 3
        total_vp += typical * c['volume']
        total_vol += c['volume']
    return total_vp / total_vol if total_vol > 0 else None


def detect_signals(ticker_info, data):
    """
    AGGRESSIVERE Signale — wir wollen TRADEN, nicht perfekt sein.
    Jeder Trade = Datenpunkt. Paper Money = kein Risiko.
    """
    signals = []
    candles = data['candles']
    if len(candles) < 10:  # Weniger Kerzen nötig (v1 war 20)
        return signals

    closes = [c['close'] for c in candles]
    volumes = [c['volume'] or 0 for c in candles]
    price = data['price']
    prev_close = data['prev_close']
    gap = data.get('gap_pct', 0)

    rsi = calc_rsi(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21) if len(closes) >= 21 else None
    vwap = calc_vwap(candles)
    avg_vol = sum(volumes[-10:]) / 10 if len(volumes) >= 10 else max(sum(volumes) / max(len(volumes),1), 1)
    cur_vol = volumes[-1] if volumes else 0
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1

    # ── DT1: Momentum — GELOCKERT ──
    # v1: VWAP + Vol 1.5x + EMA9>21 alle gleichzeitig
    # v2: VWAP ODER Vol 1.2x, plus Trend-Bestätigung
    if vwap and price > vwap and ema9:
        bullish = ema21 is None or ema9 > ema21  # Wenn EMA21 nicht berechenbar, zählt EMA9 allein
        vol_ok = vol_ratio > 1.2
        if bullish or vol_ok:
            stop = round(min(vwap, price * 0.99) * 0.998, 2)
            target = round(price * 1.012, 2)
            conf = min(85, 45 + int(vol_ratio * 10) + (10 if bullish else 0))
            signals.append({'strategy': 'DT1', 'direction': 'LONG', 'stop': stop, 'target': target,
                'confidence': conf, 'reason': f'Momentum: >{vwap:.0f} VWAP, Vol {vol_ratio:.1f}x'})

    # ── DT2: Mean Reversion — GELOCKERT ──
    # v1: RSI < 30 (fast nie auf 5min)
    # v2: RSI < 40 ODER Kurs > 1.5% unter VWAP
    vwap_dist = ((price / vwap) - 1) * 100 if vwap else 0
    if (rsi and rsi < 40) or vwap_dist < -1.5:
        stop = round(price * 0.988, 2)
        target = round(vwap or price * 1.01, 2)
        conf = 50
        if rsi and rsi < 30: conf += 15
        if vwap_dist < -2: conf += 10
        signals.append({'strategy': 'DT2', 'direction': 'LONG', 'stop': stop, 'target': target,
            'confidence': conf, 'reason': f'Reversion: RSI={rsi}, VWAP-dist={vwap_dist:+.1f}%'})

    # ── DT3: Gap Play — GELOCKERT ──
    # v1: Gap > 2%, erste 30 Kerzen
    # v2: Gap > 1%, erste 40 Kerzen, ODER Gap > 3% jederzeit
    if (abs(gap) > 1.0 and len(candles) < 40) or abs(gap) > 3.0:
        direction = 'SHORT' if gap > 0 else 'LONG'
        stop = round(price * (1.012 if direction == 'SHORT' else 0.988), 2)
        target = round(prev_close, 2)
        conf = min(75, 35 + int(abs(gap) * 8))
        signals.append({'strategy': 'DT3', 'direction': direction, 'stop': stop, 'target': target,
            'confidence': conf, 'reason': f'Gap {gap:+.1f}% → Fill to {prev_close:.2f}'})

    # ── DT4: Trend Following — GELOCKERT ──
    # v1: Exakter EMA-Cross auf letzter Kerze
    # v2: EMA9 > EMA21 + Kurs über beiden = Trend bestätigt
    if ema9 and ema21:
        if ema9 > ema21 and price > ema9:
            stop = round(ema21 * 0.997, 2)
            target = round(price * 1.008, 2)
            signals.append({'strategy': 'DT4', 'direction': 'LONG', 'stop': stop, 'target': target,
                'confidence': 55, 'reason': f'Trend: EMA9({ema9:.0f})>EMA21({ema21:.0f}), Price above'})
        elif ema9 < ema21 and price < ema9:
            stop = round(ema21 * 1.003, 2)
            target = round(price * 0.992, 2)
            signals.append({'strategy': 'DT4', 'direction': 'SHORT', 'stop': stop, 'target': target,
                'confidence': 55, 'reason': f'Trend: EMA9({ema9:.0f})<EMA21({ema21:.0f}), Price below'})

    # ── DT5: NEU — Intraday Range Breakout ──
    if len(candles) >= 12:
        recent_highs = [c['high'] for c in candles[-12:]]
        recent_lows = [c['low'] for c in candles[-12:]]
        range_high = max(recent_highs)
        range_low = min(recent_lows)
        range_pct = (range_high / range_low - 1) * 100 if range_low > 0 else 0

        if price > range_high and range_pct > 0.5:
            stop = round(range_low + (range_high - range_low) * 0.5, 2)
            target = round(price + (range_high - range_low), 2)
            signals.append({'strategy': 'DT5', 'direction': 'LONG', 'stop': stop, 'target': target,
                'confidence': 60, 'reason': f'Range Breakout: {range_low:.0f}-{range_high:.0f} ({range_pct:.1f}%)'})
        elif price < range_low and range_pct > 0.5:
            stop = round(range_high - (range_high - range_low) * 0.5, 2)
            target = round(price - (range_high - range_low), 2)
            signals.append({'strategy': 'DT5', 'direction': 'SHORT', 'stop': stop, 'target': target,
                'confidence': 60, 'reason': f'Range Breakdown: {range_low:.0f}-{range_high:.0f} ({range_pct:.1f}%)'})


    # ── DT6: Mean Reversion (Triple RSI Variation) ──
    # Backtested seit 1993, 90% Win-Rate auf SPY (QuantifiedStrategies.com)
    # RSI(5) < 35, RSI fallend, Preis > Vortagsclose (Aufwärtstrend-Proxy)
    rsi5 = calc_rsi(closes, 5)
    if rsi5 is not None and len(closes) >= 7:
        rsi5_prev_closes = closes[:-1]
        rsi5_prev = calc_rsi(rsi5_prev_closes, 5)
        uptrend = price > prev_close  # Proxy für SMA(200) bei 5min-Kerzen
        if rsi5 < 35 and rsi5_prev is not None and rsi5 < rsi5_prev and uptrend:
            stop6 = round(price * 0.985, 2)
            target6 = round(vwap if vwap and vwap > price else price * 1.01, 2)
            conf6 = min(90, int(70 + (35 - rsi5) * 2))
            signals.append({'strategy': 'DT6', 'direction': 'LONG', 'stop': stop6, 'target': target6,
                'confidence': conf6, 'reason': f'MeanRev RSI(5)={rsi5:.1f} (prev {rsi5_prev:.1f}), uptrend'})

    # ── DT7: Internal Bar Strength (IBS) ──
    # IBS = (Close - Low) / (High - Low) der letzten Kerze
    if len(candles) >= 20:
        last_c = candles[-1]
        ibs_range = last_c['high'] - last_c['low']
        if ibs_range > 0:
            ibs = (last_c['close'] - last_c['low']) / ibs_range
            # Bollinger Middle Band für Target
            if len(closes) >= 20:
                bb_mid = sum(closes[-20:]) / 20
            else:
                bb_mid = None
            if ibs < 0.2:
                stop7 = round(price * 0.988, 2)
                target7 = round(bb_mid if bb_mid and bb_mid > price else price * 1.008, 2)
                conf7 = 55 + (15 if ibs < 0.1 else 0)
                signals.append({'strategy': 'DT7', 'direction': 'LONG', 'stop': stop7, 'target': target7,
                    'confidence': conf7, 'reason': f'IBS={ibs:.3f} (near low) → bounce expected'})
            elif ibs > 0.8:
                stop7 = round(price * 1.012, 2)
                target7 = round(bb_mid if bb_mid and bb_mid < price else price * 0.992, 2)
                conf7 = 55 + (15 if ibs > 0.9 else 0)
                signals.append({'strategy': 'DT7', 'direction': 'SHORT', 'stop': stop7, 'target': target7,
                    'confidence': conf7, 'reason': f'IBS={ibs:.3f} (near high) → pullback expected'})

    # ── DT8: Bollinger Band Squeeze Breakout ──
    # Volatilitäts-Kompression → Ausbruch mit Volumen
    if len(closes) >= 50:
        bb_period = 20
        bb_sma = sum(closes[-bb_period:]) / bb_period
        bb_std = (sum((c - bb_sma) ** 2 for c in closes[-bb_period:]) / bb_period) ** 0.5
        bb_upper = bb_sma + 2 * bb_std
        bb_lower = bb_sma - 2 * bb_std
        bb_bandwidth = (bb_upper - bb_lower) / bb_sma if bb_sma > 0 else 0
        # Calculate historical bandwidths for squeeze detection
        bandwidths = []
        for j in range(50):
            idx_end = len(closes) - j
            if idx_end < bb_period:
                break
            slice_c = closes[idx_end - bb_period:idx_end]
            s = sum(slice_c) / bb_period
            std_j = (sum((c - s) ** 2 for c in slice_c) / bb_period) ** 0.5
            bw_j = (2 * std_j * 2) / s if s > 0 else 0
            bandwidths.append(bw_j)
        if bandwidths:
            bandwidths_sorted = sorted(bandwidths)
            squeeze_threshold = bandwidths_sorted[max(0, len(bandwidths_sorted) // 4)]
            is_squeeze = bb_bandwidth <= squeeze_threshold
            vol_confirm = vol_ratio > 1.3
            if is_squeeze and vol_confirm:
                if price > bb_upper:
                    stop8 = round(bb_sma, 2)
                    target8 = round(price + (bb_upper - bb_lower), 2)
                    signals.append({'strategy': 'DT8', 'direction': 'LONG', 'stop': stop8, 'target': target8,
                        'confidence': 65, 'reason': f'BB Squeeze Breakout UP: BW={bb_bandwidth:.4f}, Vol {vol_ratio:.1f}x'})
                elif price < bb_lower:
                    stop8 = round(bb_sma, 2)
                    target8 = round(price - (bb_upper - bb_lower), 2)
                    signals.append({'strategy': 'DT8', 'direction': 'SHORT', 'stop': stop8, 'target': target8,
                        'confidence': 65, 'reason': f'BB Squeeze Breakdown: BW={bb_bandwidth:.4f}, Vol {vol_ratio:.1f}x'})

    # ── DT9: Sektor-Momentum (vereinfacht) ──
    # Nur Aktien aus dem stärksten Sektor bekommen Signal
    # sector_momentum wird in main() berechnet und als Attribut übergeben
    _sector_perf = ticker_info.get('_sector_perf')
    _sector_etf = ticker_info.get('_sector_etf')
    if _sector_perf is not None and _sector_etf:
        if _sector_perf > 0.5:
            stop9 = round(price * 0.99, 2)
            target9 = round(price * 1.008, 2)
            conf9 = min(80, 50 + int(abs(_sector_perf) * 20))
            signals.append({'strategy': 'DT9', 'direction': 'LONG', 'stop': stop9, 'target': target9,
                'confidence': conf9, 'reason': f'Sector Momentum: {_sector_etf} +{_sector_perf:.1f}%'})
        elif _sector_perf < -0.5:
            stop9 = round(price * 1.01, 2)
            target9 = round(price * 0.992, 2)
            conf9 = min(80, 50 + int(abs(_sector_perf) * 20))
            signals.append({'strategy': 'DT9', 'direction': 'SHORT', 'stop': stop9, 'target': target9,
                'confidence': conf9, 'reason': f'Sector Momentum: {_sector_etf} {_sector_perf:+.1f}%'})

    return signals


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # Ensure trades table exists
    conn.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, ticker TEXT, strategy TEXT, direction TEXT,
        entry_price REAL, entry_date TEXT, exit_price REAL, exit_date TEXT,
        stop REAL, target REAL, shares INTEGER, pnl_eur REAL, pnl_pct REAL,
        status TEXT, trade_type TEXT, thesis TEXT, fees_eur REAL DEFAULT 0,
        holding_days INTEGER DEFAULT 0
    )""")
    return conn


def get_strategy_conviction(strategy_id):
    """Get conviction from strategies.json. Returns (conviction, position_size)."""
    try:
        strat_path = WORKSPACE / 'data/strategies.json'
        if strat_path.exists():
            with open(strat_path) as f:
                strats = json.load(f)
            if strategy_id in strats and isinstance(strats[strategy_id], dict):
                genesis = strats[strategy_id].get('genesis', {})
                conviction = genesis.get('conviction_current', 3)
                if conviction < 2:
                    return conviction, 0  # suspended
                elif conviction >= 4:
                    return conviction, 7500  # elevated
                else:
                    return conviction, 5000  # normal
    except Exception:
        pass
    return 3, POS_SIZE  # default


def open_trade(ticker, name, strategy, direction, entry_eur, stop, target, reason):
    # Check conviction before opening
    conviction, pos_size = get_strategy_conviction(strategy)
    if pos_size == 0:
        print(f"  ⛔ BLOCKED {ticker} — Strategy {strategy} suspended (conviction={conviction})")
        return None
    if pos_size != POS_SIZE:
        print(f"  📈 {strategy} conviction={conviction} → Position Size {pos_size}€")
    shares = max(1, math.floor(pos_size / entry_eur))
    risk = abs(entry_eur - stop) * shares
    conn = get_db()
    conn.execute("""INSERT INTO trades (ticker, strategy, direction, entry_price, entry_date,
        stop, target, shares, status, trade_type, thesis, fees_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 'day_trade', ?, 0)""",
        (ticker, strategy, direction, round(entry_eur, 2),
         datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
         round(stop, 2), round(target, 2), shares, reason))
    conn.commit()
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    print(f"  🟢 OPEN {direction} {ticker} ({name}) @ {entry_eur:.2f}€ × {shares} | S:{stop:.2f} T:{target:.2f}")
    print(f"     {strategy}: {reason}")
    return tid


def close_trade(trade_id, exit_price, reason='EOD'):
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not trade:
        conn.close()
        return 0
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
    conn.execute("""UPDATE trades SET exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?, status=?, holding_days=0
        WHERE id=?""", (round(exit_price, 2), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        round(pnl, 2), round(pnl_pct, 2), status, trade_id))
    conn.commit()
    conn.close()
    emoji = "✅" if status == 'WIN' else "❌"
    print(f"  {emoji} CLOSE {trade['ticker']}: {entry:.2f} → {exit_price:.2f} ({pnl_pct:+.1f}%) P&L: {pnl:+.1f}€ [{reason}]")
    return pnl


def log_to_file(text):
    """Loggt in daytrader-log.md für Transparenz."""
    now = datetime.now(ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d %H:%M')
    with open(LOG_PATH, 'a') as f:
        f.write(f"[{now}] {text}\n")


def main():
    now_cet = datetime.now(ZoneInfo('Europe/Berlin'))
    print(f"[{now_cet.strftime('%H:%M CET')}] Day Trader v2 läuft...")

    # Load state
    if DT_STATE.exists():
        state = json.loads(DT_STATE.read_text())
    else:
        state = {}
    today = now_cet.strftime('%Y-%m-%d')
    if state.get('last_date') != today:
        state = {'daily_pnl': 0, 'daily_trades': 0, 'last_date': today,
                 'signals_today': [], 'scanned': 0, 'signals_found': 0}

    conn = get_db()
    open_trades = conn.execute(
        "SELECT id, ticker, direction, entry_price, stop, target, shares, strategy "
        "FROM trades WHERE trade_type='day_trade' AND status='OPEN'").fetchall()
    conn.close()

    print(f"  Offen: {len(open_trades)}/{MAX_POSITIONS} | Daily P&L: {state.get('daily_pnl',0):+.0f}€ | Scans: {state.get('scanned',0)}")

    # ── 1. EOD Auto-Close ──
    if now_cet.hour >= EOD_CLOSE_HOUR and now_cet.minute >= EOD_CLOSE_MIN:
        if open_trades:
            print(f"  🕘 EOD Close — {len(open_trades)} Positionen")
            for t in open_trades:
                data = yahoo_intraday(t['ticker'])
                if data:
                    p = to_eur(data['price'], data['currency'])
                    if p:
                        pnl = close_trade(t['id'], p, 'EOD')
                        state['daily_pnl'] += (pnl or 0)
                        state['daily_trades'] += 1
            log_to_file(f"EOD Close: {len(open_trades)} Trades, Daily P&L: {state['daily_pnl']:+.0f}€")
        DT_STATE.write_text(json.dumps(state, indent=2))
        return

    # ── 2. Stop/Target Check ──
    for t in open_trades:
        data = yahoo_intraday(t['ticker'])
        if not data: continue
        p = to_eur(data['price'], data['currency'])
        if not p: continue

        stop, target = t['stop'], t['target']
        direction = t['direction']

        # Stop
        if stop and ((direction == 'LONG' and p <= stop) or (direction == 'SHORT' and p >= stop)):
            pnl = close_trade(t['id'], p, 'Stop')
            state['daily_pnl'] += (pnl or 0)
            state['daily_trades'] += 1
            continue

        # Target
        if target and ((direction == 'LONG' and p >= target) or (direction == 'SHORT' and p <= target)):
            pnl = close_trade(t['id'], p, 'Target')
            state['daily_pnl'] += (pnl or 0)
            state['daily_trades'] += 1
            continue

        # Status
        pnl_pct = ((p / t['entry_price'] - 1) * 100) if direction == 'LONG' else ((t['entry_price'] / p - 1) * 100)
        print(f"  {'🟢' if pnl_pct > 0 else '🔴'} {t['ticker']:8s} {p:.2f}€ ({pnl_pct:+.1f}%)")

    # ── 3. Neue Signale ──
    open_count = len([t for t in open_trades if True])  # recount after closes
    conn = get_db()
    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE trade_type='day_trade' AND status='OPEN'").fetchone()[0]
    conn.close()

    if open_count >= MAX_POSITIONS:
        print(f"  ⏸️ Max Positionen ({MAX_POSITIONS}) — kein Scan")
        DT_STATE.write_text(json.dumps(state, indent=2))
        return

    if state.get('daily_pnl', 0) <= -500:
        print(f"  🛑 Daily Loss Limit: {state['daily_pnl']:.0f}€")
        DT_STATE.write_text(json.dumps(state, indent=2))
        return

    hour = now_cet.hour

    # ── Dynamisches Universum laden (wenn vorhanden) ──
    active_universe = DT_UNIVERSE  # Fallback
    if DYNAMIC_UNIVERSE_PATH.exists():
        try:
            dyn = json.loads(DYNAMIC_UNIVERSE_PATH.read_text())
            dyn_list = dyn.get('universe', [])
            if dyn_list:
                # Konvertiere in DT_UNIVERSE Format
                active_universe = []
                for item in dyn_list:
                    active_universe.append({
                        'ticker': item['ticker'],
                        'name': item.get('name', item['ticker']),
                        'market': item.get('market', 'US'),
                        'open_h': item.get('open_h', 9),
                        'close_h': item.get('close_h', 22),
                    })
                print(f"  🌍 Dynamisches Universum: {len(active_universe)} Aktien aus {', '.join(dyn.get('markets_active', []))}")
        except Exception as e:
            print(f"  ⚠️ Dynamisches Universum Fehler: {e} → Fallback")

    # ── Sektor-Momentum berechnen (für DT9) ──
    sector_perf = {}
    for etf in ['XLK', 'XLE', 'XLF', 'XLV', 'XLI']:
        etf_data = yahoo_intraday(etf)
        if etf_data and etf_data.get('prev_close'):
            perf = ((etf_data['price'] / etf_data['prev_close']) - 1) * 100
            sector_perf[etf] = perf
    best_sector_etf = max(sector_perf, key=lambda k: abs(sector_perf[k])) if sector_perf else None
    best_sector_perf = sector_perf.get(best_sector_etf, 0) if best_sector_etf else 0
    sector_tickers = SECTOR_MAP.get(best_sector_etf, []) if best_sector_etf else []
    if best_sector_etf:
        print(f"  📊 Sektor-Momentum: {best_sector_etf} {best_sector_perf:+.2f}% → {len(sector_tickers)} Ticker")

    new_trades = 0
    for ti in active_universe:
        if open_count >= MAX_POSITIONS: break

        ticker = ti['ticker']
        if hour < ti['open_h'] or hour >= ti['close_h']: continue

        # Maximal 2x pro Ticker pro Tag (v1 war 1x)
        ticker_count = state.get('signals_today', []).count(ticker)
        if ticker_count >= 2: continue

        # Schon offen?
        conn = get_db()
        existing = conn.execute("SELECT id FROM trades WHERE ticker=? AND trade_type='day_trade' AND status='OPEN'",
                               (ticker,)).fetchone()
        conn.close()
        if existing: continue

        data = yahoo_intraday(ticker)
        state['scanned'] = state.get('scanned', 0) + 1
        if not data: continue

        # Inject sector momentum for DT9
        if ti['ticker'] in sector_tickers:
            ti['_sector_perf'] = best_sector_perf
            ti['_sector_etf'] = best_sector_etf
        else:
            ti['_sector_perf'] = None
            ti['_sector_etf'] = None
        signals = detect_signals(ti, data)
        state['signals_found'] = state.get('signals_found', 0) + len(signals)

        if not signals: continue

        # Bestes Signal
        best = max(signals, key=lambda s: s['confidence'])
        p_eur = to_eur(data['price'], data['currency'])
        if not p_eur: continue

        stop_eur = to_eur(best['stop'], data['currency']) or best['stop']
        target_eur = to_eur(best['target'], data['currency']) or best['target']

        open_trade(ticker, ti['name'], best['strategy'], best['direction'],
                   p_eur, stop_eur, target_eur, best['reason'])

        state.setdefault('signals_today', []).append(ticker)
        open_count += 1
        new_trades += 1

    if new_trades:
        log_to_file(f"Neue Trades: {new_trades} | Offen: {open_count}")

    # ── 4. Minimum Trade Garantie ──
    # Wenn es 20:00+ CET ist und heute noch KEIN Trade eröffnet wurde:
    # → Nimm das beste Signal aus dem letzten Scan, auch bei niedriger Confidence
    # Daten > Perfektion. Wir brauchen Trades zum Lernen.
    conn = get_db()
    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE trade_type='day_trade' AND status='OPEN'").fetchone()[0]
    conn.close()
    if hour >= 20 and state.get('daily_trades', 0) == 0 and open_count < MAX_POSITIONS:
        print("  ⚠️ MINIMUM TRADE GARANTIE — Erzwinge mindestens 1 Trade heute")
        # Scanne alle US-Aktien nochmal mit ALLEN Strategien
        best_signal = None
        best_ticker = None
        best_data = None
        for ti in active_universe:
            ticker = ti['ticker']
            conn = get_db()
            existing = conn.execute("SELECT id FROM trades WHERE ticker=? AND trade_type='day_trade' AND status='OPEN'", (ticker,)).fetchone()
            conn.close()
            if existing: continue
            data = yahoo_intraday(ticker)
            if not data: continue
            # Inject sector momentum for DT9
            if ticker in sector_tickers:
                ti['_sector_perf'] = best_sector_perf
                ti['_sector_etf'] = best_sector_etf
            else:
                ti['_sector_perf'] = None
                ti['_sector_etf'] = None
            signals = detect_signals(ti, data)
            for s in signals:
                if best_signal is None or s['confidence'] > best_signal['confidence']:
                    best_signal = s
                    best_ticker = ti
                    best_data = data
        if best_signal and best_data:
            p_eur = to_eur(best_data['price'], best_data['currency'])
            if p_eur:
                stop_eur = to_eur(best_signal['stop'], best_data['currency']) or best_signal['stop']
                target_eur = to_eur(best_signal['target'], best_data['currency']) or best_signal['target']
                open_trade(best_ticker['ticker'], best_ticker['name'], best_signal['strategy'],
                          best_signal['direction'], p_eur, stop_eur, target_eur,
                          f"MIN_TRADE_GARANTIE: {best_signal['reason']}")
                state.setdefault('signals_today', []).append(best_ticker['ticker'])
                log_to_file(f"⚠️ Min Trade Garantie: {best_ticker['ticker']} {best_signal['strategy']}")
        else:
            log_to_file("⚠️ Min Trade Garantie: Kein einziges Signal gefunden!")

    DT_STATE.write_text(json.dumps(state, indent=2))
    print(f"\n  📊 Scans: {state.get('scanned',0)} | Signale: {state.get('signals_found',0)} | Neu: {new_trades} | P&L: {state.get('daily_pnl',0):+.0f}€")


if __name__ == '__main__':
    main()
