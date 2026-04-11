#!/usr/bin/env python3
"""
Signal Engine v2 — Multi-Source Signal Detection
=================================================
Vereinigt:
- Lead-Lag Detection (aus signal_tracker.py)
- Technical Pattern Scanner (Candlestick Patterns)
- Volume Anomaly Detection
- Signal Fusion (Confluence Score)

Alle Signale → signals Tabelle + optional Paperclip Issues.

Sprint 2 | TradeMind Bauplan
"""

import sqlite3, json, hashlib, math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH = WS / 'data/trading.db'
LAG_PATH = WS / 'data/lag_knowledge.json'

# ─── Candlestick Pattern Definitions ────────────────────────
BULLISH_PATTERNS = {
    'hammer': 'Unterer Schatten ≥2× Body, kleiner Body oben',
    'bullish_engulfing': 'Grüne Kerze verschlingt vorherige rote komplett',
    'morning_star': '3 Kerzen: rot → kleiner Body → grün (Umkehr)',
    'doji': 'Open ≈ Close (Unentschlossenheit nach Abwärtstrend)',
}

BEARISH_PATTERNS = {
    'shooting_star': 'Oberer Schatten ≥2× Body, kleiner Body unten',
    'bearish_engulfing': 'Rote Kerze verschlingt vorherige grüne komplett',
    'evening_star': '3 Kerzen: grün → kleiner Body → rot (Umkehr)',
}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════
# 1. TECHNICAL PATTERN SCANNER
# ═══════════════════════════════════════════════════════════════

def detect_candlestick_patterns(ticker, lookback=5):
    """Erkennt Candlestick-Patterns für einen Ticker."""
    conn = get_db()
    rows = conn.execute("""
        SELECT date, open, high, low, close, volume 
        FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?
    """, (ticker, lookback)).fetchall()
    conn.close()
    
    if len(rows) < 3:
        return []
    
    patterns = []
    candles = list(reversed(rows))  # chronologisch
    
    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i-1]
        
        o, h, l, cl = c['open'], c['high'], c['low'], c['close']
        if not all([o, h, l, cl]):
            continue
        
        body = abs(cl - o)
        upper_shadow = h - max(o, cl)
        lower_shadow = min(o, cl) - l
        
        # Hammer (bullish)
        if body > 0 and lower_shadow >= 2 * body and upper_shadow < body * 0.3:
            if prev['close'] < prev['open']:  # nach Abwärtstrend
                patterns.append({
                    'pattern': 'hammer',
                    'type': 'bullish',
                    'date': c['date'],
                    'confidence': min(90, int(lower_shadow / body * 20)),
                    'price': cl
                })
        
        # Shooting Star (bearish)
        if body > 0 and upper_shadow >= 2 * body and lower_shadow < body * 0.3:
            if prev['close'] > prev['open']:  # nach Aufwärtstrend
                patterns.append({
                    'pattern': 'shooting_star',
                    'type': 'bearish',
                    'date': c['date'],
                    'confidence': min(90, int(upper_shadow / body * 20)),
                    'price': cl
                })
        
        # Bullish Engulfing
        if i > 0:
            po, pcl = prev['open'], prev['close']
            if po and pcl and pcl < po and cl > o:  # prev red, current green
                if cl > po and o < pcl:  # engulfing
                    patterns.append({
                        'pattern': 'bullish_engulfing',
                        'type': 'bullish',
                        'date': c['date'],
                        'confidence': 75,
                        'price': cl
                    })
        
        # Bearish Engulfing
        if i > 0:
            po, pcl = prev['open'], prev['close']
            if po and pcl and pcl > po and cl < o:  # prev green, current red
                if cl < po and o > pcl:  # engulfing
                    patterns.append({
                        'pattern': 'bearish_engulfing',
                        'type': 'bearish',
                        'date': c['date'],
                        'confidence': 75,
                        'price': cl
                    })
        
        # Doji (nach Trend)
        if body < (h - l) * 0.1 and (h - l) > 0:
            patterns.append({
                'pattern': 'doji',
                'type': 'neutral',
                'date': c['date'],
                'confidence': 50,
                'price': cl
            })
    
    return patterns


# ═══════════════════════════════════════════════════════════════
# 2. VOLUME ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_volume_anomalies(ticker, threshold=2.0, lookback=21):
    """Erkennt Volume > threshold × 20-SMA."""
    conn = get_db()
    rows = conn.execute("""
        SELECT date, close, volume FROM prices 
        WHERE ticker=? ORDER BY date DESC LIMIT ?
    """, (ticker, lookback)).fetchall()
    conn.close()
    
    if len(rows) < 5:
        return []
    
    volumes = [r['volume'] or 0 for r in rows]
    avg_vol = sum(volumes[1:]) / max(len(volumes)-1, 1)
    
    anomalies = []
    if avg_vol > 0 and volumes[0] > avg_vol * threshold:
        ratio = volumes[0] / avg_vol
        anomalies.append({
            'date': rows[0]['date'],
            'ticker': ticker,
            'volume': volumes[0],
            'avg_volume': int(avg_vol),
            'ratio': round(ratio, 1),
            'price': rows[0]['close'],
            'signal': 'VOLUME_SPIKE'
        })
    
    return anomalies


# ═══════════════════════════════════════════════════════════════
# 3. EMA CROSSOVER DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_ema_crossovers(ticker, short=10, long=50):
    """Erkennt EMA-Crossovers."""
    conn = get_db()
    rows = conn.execute("""
        SELECT date, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?
    """, (ticker, long + 5)).fetchall()
    conn.close()
    
    if len(rows) < long + 2:
        return []
    
    closes = [r['close'] for r in reversed(rows)]
    dates = [r['date'] for r in reversed(rows)]
    
    # EMA berechnen
    def ema(data, period):
        result = [data[0]]
        mult = 2 / (period + 1)
        for i in range(1, len(data)):
            result.append(data[i] * mult + result[-1] * (1 - mult))
        return result
    
    ema_short = ema(closes, short)
    ema_long = ema(closes, long)
    
    signals = []
    # Check letzte 3 Tage für Crossover
    for i in range(-3, 0):
        if i-1 < -len(ema_short):
            continue
        if ema_short[i-1] <= ema_long[i-1] and ema_short[i] > ema_long[i]:
            signals.append({
                'pattern': f'ema_golden_cross_{short}_{long}',
                'type': 'bullish',
                'date': dates[i],
                'confidence': 70,
                'price': closes[i]
            })
        elif ema_short[i-1] >= ema_long[i-1] and ema_short[i] < ema_long[i]:
            signals.append({
                'pattern': f'ema_death_cross_{short}_{long}',
                'type': 'bearish',
                'date': dates[i],
                'confidence': 70,
                'price': closes[i]
            })
    
    return signals


# ═══════════════════════════════════════════════════════════════
# 4. SIGNAL FUSION (Confluence)
# ═══════════════════════════════════════════════════════════════

def calculate_confluence(ticker):
    """
    Berechnet Confluence Score: wie viele Signale zeigen in gleiche Richtung?
    Returns: {'bullish': count, 'bearish': count, 'score': -100 bis +100}
    """
    patterns = detect_candlestick_patterns(ticker)
    volumes = detect_volume_anomalies(ticker)
    crossovers = detect_ema_crossovers(ticker)
    
    bullish = sum(1 for p in patterns if p['type'] == 'bullish')
    bearish = sum(1 for p in patterns if p['type'] == 'bearish')
    bullish += len([c for c in crossovers if c['type'] == 'bullish'])
    bearish += len([c for c in crossovers if c['type'] == 'bearish'])
    
    # Volume Spike ist richtungsneutral, aber verstärkt vorhandenes Signal
    if volumes:
        if bullish > bearish:
            bullish += 1
        elif bearish > bullish:
            bearish += 1
    
    total = bullish + bearish
    if total == 0:
        score = 0
    else:
        score = int((bullish - bearish) / total * 100)
    
    return {
        'bullish_signals': bullish,
        'bearish_signals': bearish,
        'confluence_score': score,
        'patterns': patterns,
        'volume_anomalies': volumes,
        'ema_crossovers': crossovers,
    }


def store_signal(pair_id, lead_ticker, lag_ticker, signal_value, 
                 lead_price=None, lag_price=None, paperclip_issue_id=None):
    """Speichert ein Signal in der signals Tabelle."""
    conn = get_db()
    
    # Regime + VIX holen
    regime_row = conn.execute("SELECT regime, vix FROM regime_history ORDER BY date DESC LIMIT 1").fetchone()
    regime = regime_row['regime'] if regime_row else None
    vix = regime_row['vix'] if regime_row else None
    
    conn.execute("""
        INSERT INTO signals (pair_id, lead_ticker, lag_ticker, signal_value,
                           lead_price, lag_price_at_signal, regime_at_signal, vix_at_signal,
                           paperclip_issue_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pair_id, lead_ticker, lag_ticker, signal_value,
          lead_price, lag_price, regime, vix,
          paperclip_issue_id, datetime.now(timezone.utc).isoformat()))
    
    conn.commit()
    signal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return signal_id


def scan_all_tickers():
    """Scannt alle aktiven Ticker auf Signale."""
    conn = get_db()
    tickers = conn.execute("""
        SELECT DISTINCT ticker FROM trades WHERE status='OPEN'
        UNION
        SELECT DISTINCT ticker FROM paper_portfolio WHERE status='OPEN'
    """).fetchall()
    conn.close()
    
    results = {}
    for row in tickers:
        ticker = row['ticker']
        confluence = calculate_confluence(ticker)
        if confluence['bullish_signals'] > 0 or confluence['bearish_signals'] > 0:
            results[ticker] = confluence
    
    return results


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'scan':
        results = scan_all_tickers()
        print(f"═══ Signal Scan — {len(results)} Ticker mit Signalen ═══")
        for ticker, data in sorted(results.items(), key=lambda x: abs(x[1]['confluence_score']), reverse=True):
            score = data['confluence_score']
            emoji = '🟢' if score > 30 else ('🔴' if score < -30 else '⚪')
            print(f"  {emoji} {ticker:12} Confluence: {score:+4d} (↑{data['bullish_signals']} ↓{data['bearish_signals']})")
            for p in data['patterns']:
                print(f"      📊 {p['pattern']} ({p['type']}) @ {p['date']} conf={p['confidence']}%")
            for v in data['volume_anomalies']:
                print(f"      📈 Volume Spike {v['ratio']}× avg")
            for c in data['ema_crossovers']:
                print(f"      ✂️  {c['pattern']} @ {c['date']}")
    
    elif len(sys.argv) > 1:
        ticker = sys.argv[1]
        confluence = calculate_confluence(ticker)
        print(f"═══ {ticker} Signal Analysis ═══")
        print(f"  Confluence: {confluence['confluence_score']:+d}")
        print(f"  Bullish: {confluence['bullish_signals']} | Bearish: {confluence['bearish_signals']}")
        for p in confluence['patterns']:
            print(f"  📊 {p['pattern']} ({p['type']}) @ {p['date']}")
    
    else:
        print("Usage: signal_engine.py scan | signal_engine.py TICKER")
