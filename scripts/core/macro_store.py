#!/usr/bin/env python3
"""
Macro Store — Historische + tägliche Makrodaten
================================================
Befüllt macro_daily Tabelle mit VIX, WTI, Brent, DXY, Gold,
US10Y, US2Y, Nikkei, Kupfer, EUR/USD.

Backfill: 5 Jahre via Yahoo Finance
Daily: Cron 22:30 UTC für Tageswerte

TRA-6 | Sprint 1 | TradeMind Bauplan
"""

import json, sqlite3, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH = WS / 'data/trading.db'

MACRO_TICKERS = {
    'VIX':      '^VIX',
    'WTI':      'CL=F',
    'BRENT':    'BZ=F',
    'DXY':      'DX-Y.NYB',
    'GOLD':     'GC=F',
    'US10Y':    '^TNX',
    'US2Y':     '^IRX',
    'NIKKEI':   '^N225',
    'COPPER':   'HG=F',
    'EURUSD':   'EURUSD=X',
    'SP500':    '^GSPC',
    'NASDAQ':   '^IXIC',
}


def yahoo_history(ticker, period='5y', interval='1d'):
    """Holt historische Kurse von Yahoo Finance."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
    url += f"?interval={interval}&range={period}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        quotes = result['indicators']['quote'][0]
        
        rows = []
        for i, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
            close = quotes['close'][i]
            if close is None:
                continue
            rows.append((dt, close))
        return rows
    except Exception as e:
        print(f"  ⚠️ {ticker}: {e}")
        return []


def backfill(conn, indicator, ticker, period='5y'):
    """Backfill für einen Indikator."""
    rows = yahoo_history(ticker, period)
    if not rows:
        return 0
    
    c = conn.cursor()
    inserted = 0
    prev_value = None
    
    for date, value in rows:
        change_pct = None
        if prev_value and prev_value != 0:
            change_pct = round((value - prev_value) / prev_value * 100, 4)
        
        try:
            c.execute("""
                INSERT OR IGNORE INTO macro_daily (date, indicator, value, prev_value, change_pct)
                VALUES (?, ?, ?, ?, ?)
            """, (date, indicator, round(value, 4), prev_value, change_pct))
            if c.rowcount > 0:
                inserted += 1
        except Exception:
            pass
        prev_value = round(value, 4)
    
    conn.commit()
    return inserted


def daily_update(conn):
    """Holt heutige Werte für alle Indikatoren."""
    updated = 0
    for indicator, ticker in MACRO_TICKERS.items():
        rows = yahoo_history(ticker, period='5d', interval='1d')
        if not rows:
            continue
        
        c = conn.cursor()
        for i, (date, value) in enumerate(rows):
            prev_value = rows[i-1][1] if i > 0 else None
            change_pct = None
            if prev_value and prev_value != 0:
                change_pct = round((value - prev_value) / prev_value * 100, 4)
            
            c.execute("""
                INSERT OR REPLACE INTO macro_daily (date, indicator, value, prev_value, change_pct)
                VALUES (?, ?, ?, ?, ?)
            """, (date, indicator, round(value, 4), prev_value, change_pct))
            updated += c.rowcount
        
        conn.commit()
    return updated


def compute_derived(conn):
    """Berechnet abgeleitete Indikatoren (Yield Spread)."""
    c = conn.cursor()
    
    # 2Y-10Y Spread
    rows = c.execute("""
        SELECT a.date, a.value as us10y, b.value as us2y
        FROM macro_daily a
        JOIN macro_daily b ON a.date = b.date AND b.indicator = 'US2Y'
        WHERE a.indicator = 'US10Y'
        AND a.date NOT IN (SELECT date FROM macro_daily WHERE indicator = 'YIELD_SPREAD_2Y10Y')
    """).fetchall()
    
    for date, us10y, us2y in rows:
        spread = round(us10y - us2y, 4)
        c.execute("""
            INSERT OR IGNORE INTO macro_daily (date, indicator, value)
            VALUES (?, 'YIELD_SPREAD_2Y10Y', ?)
        """, (date, spread))
    
    # Brent-WTI Spread
    rows = c.execute("""
        SELECT a.date, a.value as brent, b.value as wti
        FROM macro_daily a
        JOIN macro_daily b ON a.date = b.date AND b.indicator = 'WTI'
        WHERE a.indicator = 'BRENT'
        AND a.date NOT IN (SELECT date FROM macro_daily WHERE indicator = 'BRENT_WTI_SPREAD')
    """).fetchall()
    
    for date, brent, wti in rows:
        spread = round(brent - wti, 4)
        c.execute("""
            INSERT OR IGNORE INTO macro_daily (date, indicator, value)
            VALUES (?, 'BRENT_WTI_SPREAD', ?)
        """, (date, spread))
    
    conn.commit()
    print(f"  📐 Derived: {len(rows)} Brent-WTI Spread + Yield Spread Einträge")


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    
    conn = sqlite3.connect(str(DB_PATH))
    
    if mode == 'backfill':
        print("═══ Macro Store — 5-Jahres Backfill ═══")
        total = 0
        for indicator, ticker in MACRO_TICKERS.items():
            count = backfill(conn, indicator, ticker, period='5y')
            total += count
            print(f"  {indicator:10} ({ticker:12}): {count:5} Tage")
        
        compute_derived(conn)
        
        final = conn.execute("SELECT COUNT(*) FROM macro_daily").fetchone()[0]
        indicators = conn.execute("SELECT COUNT(DISTINCT indicator) FROM macro_daily").fetchone()[0]
        date_range = conn.execute("SELECT MIN(date), MAX(date) FROM macro_daily").fetchone()
        print(f"\n═══ Backfill komplett ═══")
        print(f"  {final} Datenpunkte | {indicators} Indikatoren | {date_range[0]} → {date_range[1]}")
    
    elif mode == 'daily':
        print("═══ Macro Store — Daily Update ═══")
        updated = daily_update(conn)
        compute_derived(conn)
        print(f"  {updated} Werte aktualisiert")
    
    conn.close()


if __name__ == '__main__':
    main()
