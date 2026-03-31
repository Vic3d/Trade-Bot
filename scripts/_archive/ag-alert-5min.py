#!/usr/bin/env python3
"""
AG (First Majestic Silver) - Umkehrkerze-Detektor (5min)
Intraday-Monitoring für Swing-Trade-Einstiege
"""

import urllib.request, json, sys, os
from datetime import datetime

def yahoo_intraday(ticker):
    """Fetch 5-min OHLC data from Yahoo Finance"""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
    except Exception as e:
        print(f'FEHLER: Yahoo Finance API failed: {e}')
        sys.exit(1)
    
    r = d['chart']['result'][0]
    q = r['indicators']['quote'][0]
    
    # Filter out null values
    c = [v for v in q.get('close', []) if v is not None]
    o = [v for v in q.get('open', []) if v is not None]
    h = [v for v in q.get('high', []) if v is not None]
    l = [v for v in q.get('low', []) if v is not None]
    
    if len(c) < 2:
        return None
    
    # Last 2 candles
    k1 = {'o': o[-2], 'c': c[-2], 'h': h[-2], 'l': l[-2]}  # older
    k2 = {'o': o[-1], 'c': c[-1], 'h': h[-1], 'l': l[-1]}  # current
    
    return k1, k2

def detect_patterns(k1, k2):
    """Detect reversal patterns"""
    
    range_k2 = k2['h'] - k2['l']
    if range_k2 < 0.01:
        return None, None, None  # Avoid division by zero
    
    body_k2 = abs(k2['c'] - k2['o'])
    lower_wick_k2 = k2['o'] - k2['l'] if k2['o'] < k2['c'] else k2['c'] - k2['l']
    
    # HAMMER: Lower wick > 2x body, close in upper half
    is_hammer = (
        lower_wick_k2 > body_k2 * 2 and 
        k2['c'] > k2['o'] + (range_k2 * 0.6)
    )
    
    # BULLISH ENGULFING: K2 close > K1 open, K2 open < K1 close
    is_bull_engulf = (
        k2['c'] > k1['o'] and 
        k2['o'] < k1['c'] and
        k2['c'] - k2['o'] > 0  # Green candle
    )
    
    # CLOSE NEAR HIGH: Close >75% of range, above midpoint
    midpoint = (k2['o'] + k2['c']) / 2
    is_close_high = k2['c'] > midpoint and (k2['c'] - k2['l']) / range_k2 > 0.75
    
    return is_hammer, is_bull_engulf, is_close_high

# ===== MAIN =====

kz = yahoo_intraday('AG')
if not kz:
    print('KEIN_SIGNAL — API failed')
    sys.exit(0)

k1, k2 = kz

# Detect
is_hammer, is_bull_engulf, is_close_high = detect_patterns(k1, k2)

signal_type = None
confidence = None

if is_hammer:
    signal_type = 'HAMMER'
    confidence = 'STRONG'
elif is_bull_engulf:
    signal_type = 'BULLISH_ENGULFING'
    confidence = 'STRONG'
elif is_close_high:
    signal_type = 'CLOSE_NEAR_HIGH'
    confidence = 'MEDIUM'
else:
    print('KEIN_SIGNAL — intern geloggt')
    sys.exit(0)

# Format message
msg = f"""🔔 **AG Umkehrkerze erkannt!**
Signal: {signal_type} (Confidence: {confidence})
Kurs: ${k2['c']:.2f}
Range (5m): ${k2['l']:.2f} - ${k2['h']:.2f}
Entry: ${k2['c']:.2f}
Stop: $22.00
Ziel 1: $25.00
Ziel 2: $28.00
⏰ {datetime.utcnow().strftime('%H:%M UTC')}"""

print(msg)

# Send to Discord
import subprocess
cmd = ['openclaw', 'message', 'send', '--channel', 'discord', '--target', '452053147620343808', '--message', msg]
subprocess.run(cmd, check=False)
