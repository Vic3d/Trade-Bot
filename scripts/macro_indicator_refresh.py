#!/usr/bin/env python3
"""
Macro Indicator Refresh — Sub-8 V2 Folge-Fix (2026-04-23)
==========================================================
Schreibt SPY, VIX, EURUSD täglich nach macro_daily.

Hintergrund: db_integrity_watchdog._check_macro_stale fand am 2026-04-23
dass SPY seit 2026-03-25 nicht refreshed wurde. Es existierte kein Job
der diese Indikatoren aktiv pflegt — anomaly_brake market-relativer DD-
Check fiel deshalb auf absoluten Fallback zurück.

Datenquelle: Yahoo (period1=heute-7d, period2=heute) für letzten Schluss.
Auch ältere Lücken werden bis zu 30d zurück gefüllt.

USAGE:
    python3 scripts/macro_indicator_refresh.py [--backfill-days N]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

INDICATORS = {
    'SPY':    'SPY',
    'VIX':    '^VIX',
    'EURUSD': 'EURUSD=X',
    'GOLD':   'GC=F',
    'WTI':    'CL=F',
}

# Sub-8 V3 #4: Stooq als Fallback wenn Yahoo down/leer
STOOQ_SYMBOLS = {
    'SPY':    'spy.us',
    'VIX':    '^vix',
    'EURUSD': 'eurusd',
    'GOLD':   'gc.f',
    'WTI':    'cl.f',
}


def _fetch_bars(yahoo_symbol: str, days_back: int = 30) -> list[tuple[str, float]]:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days_back + 5)
    p1 = int(start_dt.timestamp())
    p2 = int(end_dt.timestamp())
    enc = urllib.parse.quote(yahoo_symbol)
    url = (f'https://query2.finance.yahoo.com/v8/finance/chart/{enc}'
           f'?interval=1d&period1={p1}&period2={p2}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (MacroRefresh)'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        closes = result['indicators']['quote'][0].get('close', [])
        out = []
        for ts, c in zip(timestamps, closes):
            if c is None or c <= 0:
                continue
            d = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            out.append((d, float(c)))
        return out
    except Exception as e:
        print(f'  ❌ {yahoo_symbol}: {e}', file=sys.stderr)
        return []


def _fetch_bars_stooq(stooq_symbol: str, days_back: int = 30) -> list[tuple[str, float]]:
    """Sub-8 V3 #4: Stooq Daily-CSV Fallback. Endpoint:
       https://stooq.com/q/d/l/?s=spy.us&i=d
    Liefert ALLE Tage; wir slicen auf days_back."""
    url = f'https://stooq.com/q/d/l/?s={urllib.parse.quote(stooq_symbol)}&i=d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (MacroRefresh)'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode('utf-8', errors='replace')
        lines = [l for l in text.strip().splitlines() if l]
        if len(lines) < 2 or not lines[0].lower().startswith('date'):
            return []
        # Header: Date,Open,High,Low,Close,Volume
        out = []
        cutoff = (datetime.now() - timedelta(days=days_back + 5)).strftime('%Y-%m-%d')
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) < 5:
                continue
            d = parts[0]
            if d < cutoff:
                continue
            try:
                close = float(parts[4])
                if close <= 0:
                    continue
                out.append((d, close))
            except (ValueError, IndexError):
                continue
        return out
    except Exception as e:
        print(f'  ❌ Stooq {stooq_symbol}: {e}', file=sys.stderr)
        return []


def _ensure_schema(conn) -> None:
    cols = {c[1] for c in conn.execute('PRAGMA table_info(macro_daily)').fetchall()}
    if not cols:
        conn.execute("""
            CREATE TABLE macro_daily (
                date TEXT NOT NULL, indicator TEXT NOT NULL,
                value REAL, PRIMARY KEY (date, indicator)
            )
        """)
        conn.commit()


def main():
    backfill_days = 30
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--backfill-days' and i + 1 < len(args):
            backfill_days = int(args[i + 1])

    if not DB.exists():
        print(f'❌ DB fehlt: {DB}', file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB))
    _ensure_schema(conn)

    # API-Quota tracken
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from api_quota_tracker import track as _track
    except Exception:
        _track = lambda *a, **kw: None

    total_inserted = 0
    for ind, ysym in INDICATORS.items():
        bars = _fetch_bars(ysym, days_back=backfill_days)
        _track('yahoo', 'macro', status='ok' if bars else 'fail', note=f'{ind}={ysym}')
        # Sub-8 V3 #4: Stooq-Fallback wenn Yahoo leer
        if not bars and ind in STOOQ_SYMBOLS:
            ssym = STOOQ_SYMBOLS[ind]
            print(f'  ⚠️  Yahoo leer fuer {ind} → Stooq-Fallback ({ssym})')
            bars = _fetch_bars_stooq(ssym, days_back=backfill_days)
            _track('stooq', 'macro_fallback', status='ok' if bars else 'fail',
                   note=f'{ind}={ssym}')
        if not bars:
            continue
        before = conn.execute(
            "SELECT COUNT(*) FROM macro_daily WHERE indicator=?", (ind,)
        ).fetchone()[0]
        for date, value in bars:
            conn.execute(
                "INSERT OR REPLACE INTO macro_daily (date, indicator, value) VALUES (?, ?, ?)",
                (date, ind, value),
            )
        conn.commit()
        after = conn.execute(
            "SELECT COUNT(*) FROM macro_daily WHERE indicator=?", (ind,)
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT date, value FROM macro_daily WHERE indicator=? ORDER BY date DESC LIMIT 1",
            (ind,),
        ).fetchone()
        added = after - before
        total_inserted += added
        print(f'✅ {ind:6s}: +{added:3d} rows (total {after}), latest {latest[0]} = {latest[1]:.2f}')

    print(f'\n📊 Total inserted: {total_inserted} rows across {len(INDICATORS)} indicators')
    conn.close()


if __name__ == '__main__':
    main()
