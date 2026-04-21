#!/usr/bin/env python3
"""
Commodity Refresh — Phase 22
============================
Holt taeglich Spot/Futures-Preise fuer die Fundamental-Treiber unserer Thesen.

Quellen:
  - yfinance (Futures: BZ=F Brent, HG=F Copper, GC=F Gold, CL=F WTI, SI=F Silver)
  - yfinance (DXY Index ^DXY, VIX ^VIX)
  - Yahoo Finance via urllib fuer Uranium ETF (URNM) als Uranium-Proxy
  - Finnhub/FRED optional (API-Key in env)
  - Manueller Seed fuer HRC_STEEL (kein freies API — aus News-Parse)

Schreibt in commodity_prices-Tabelle:
  commodity, date, price, unit, source, notes

Aufgerufen:
  Scheduler taeglich 07:00 CET (vor Handelsstart)
  CLI: python3 scripts/commodity_refresh.py

Kill-Trigger-Logik:
  2-Tage-Bestaetigung. Wenn Schwellwert an 2 aufeinanderfolgenden Tagen ueberschritten,
  wird das in `commodity_kill_events` geloggt — thesis_monitor liest von dort.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'commodity_refresh.log'

# Mapping: unser interner Name → Yahoo-Symbol + Unit
COMMODITY_SYMBOLS = {
    'BRENT_OIL':       {'symbol': 'BZ=F',  'unit': '$/bbl',   'source': 'yahoo_futures'},
    'WTI_OIL':         {'symbol': 'CL=F',  'unit': '$/bbl',   'source': 'yahoo_futures'},
    'COPPER':          {'symbol': 'HG=F',  'unit': '$/lb',    'source': 'yahoo_futures'},
    'GOLD':            {'symbol': 'GC=F',  'unit': '$/oz',    'source': 'yahoo_futures'},
    'SILVER':          {'symbol': 'SI=F',  'unit': '$/oz',    'source': 'yahoo_futures'},
    'NATGAS':          {'symbol': 'NG=F',  'unit': '$/MMBtu', 'source': 'yahoo_futures'},
    'DXY':             {'symbol': 'DX-Y.NYB', 'unit': 'index', 'source': 'yahoo_index'},
    'VIX':             {'symbol': '^VIX',  'unit': 'index',   'source': 'yahoo_index'},
    # Uranium: URNM-ETF als Proxy (kein freies Spot-API)
    'URANIUM_PROXY':   {'symbol': 'URNM',  'unit': '$/share', 'source': 'yahoo_etf'},
    # Stahl: SLX-ETF als Proxy fuer HRC (freies Spot-HRC nur via Platts $$$)
    'STEEL_PROXY':     {'symbol': 'SLX',   'unit': '$/share', 'source': 'yahoo_etf'},
}

# Kill-Trigger Schwellwerte (aus strategies.json catalyst-Feldern aggregiert)
# Format: (commodity, direction, threshold, strategy_hint)
DEFAULT_KILL_THRESHOLDS = [
    ('BRENT_OIL',    'below', 75.0, 'PS1 Oel-These kill'),
    ('BRENT_OIL',    'above', 140.0, 'PS_LHA invalidation'),
    ('STEEL_PROXY',  'below', 55.0, 'PS_STLD HRC-Proxy kill'),
    ('URANIUM_PROXY','below', 45.0, 'PS_CCJ Nuclear kill'),
    ('COPPER',       'below', 3.80, 'Industrial-Demand kill'),
]


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec='seconds')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS commodity_prices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            commodity  TEXT NOT NULL,
            date       TEXT NOT NULL,
            price      REAL NOT NULL,
            unit       TEXT,
            source     TEXT,
            notes      TEXT,
            UNIQUE(commodity, date, source)
        );
        CREATE INDEX IF NOT EXISTS idx_commodity_date
            ON commodity_prices(commodity, date DESC);

        CREATE TABLE IF NOT EXISTS commodity_kill_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            commodity    TEXT NOT NULL,
            direction    TEXT NOT NULL,
            threshold    REAL NOT NULL,
            fired_date   TEXT NOT NULL,
            price_at_fire REAL,
            confirmed    INTEGER DEFAULT 0,
            notified     INTEGER DEFAULT 0,
            hint         TEXT,
            UNIQUE(commodity, direction, threshold, fired_date)
        );
    ''')
    conn.commit()


def _fetch_yahoo_quote(symbol: str) -> tuple[float | None, str]:
    """Fetch last close via Yahoo Finance v8 chart API (kein key noetig)."""
    url = (
        f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        f'?interval=1d&range=5d'
    )
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (TradeMind/1.0)',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        result = data.get('chart', {}).get('result', [])
        if not result:
            return None, 'no_result'
        quote = result[0]
        closes = quote.get('indicators', {}).get('quote', [{}])[0].get('close', [])
        timestamps = quote.get('timestamp', [])
        # last non-None close
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                return float(closes[i]), ''
        return None, 'all_close_null'
    except urllib.error.HTTPError as e:
        return None, f'http_{e.code}'
    except Exception as e:
        return None, f'err_{type(e).__name__}'


def refresh_all() -> dict:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB))
    _ensure_schema(conn)

    today = date.today().isoformat()
    stats = {'fetched': 0, 'failed': 0, 'new_rows': 0, 'kill_fires': 0}

    for name, cfg in COMMODITY_SYMBOLS.items():
        price, err = _fetch_yahoo_quote(cfg['symbol'])
        if price is None:
            _log(f'FAIL {name} ({cfg["symbol"]}): {err}')
            stats['failed'] += 1
            continue

        before = conn.total_changes
        conn.execute('''
            INSERT OR IGNORE INTO commodity_prices
            (commodity, date, price, unit, source, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, today, price, cfg['unit'], cfg['source'],
              f'auto-refresh {datetime.now().isoformat(timespec="minutes")}'))
        if conn.total_changes > before:
            stats['new_rows'] += 1
        stats['fetched'] += 1
        _log(f'OK {name:16} {price:>10.2f} {cfg["unit"]}')

    conn.commit()

    # Kill-Trigger-Check mit 2-Tage-Bestaetigung
    stats['kill_fires'] = _check_kill_triggers(conn, today)

    conn.close()
    _log(f'STATS {stats}')
    return stats


def _check_kill_triggers(conn: sqlite3.Connection, today: str) -> int:
    """
    Checkt alle Standard-Schwellwerte.
    Kill feuert nur wenn Bedingung an HEUTE UND GESTERN wahr war.
    """
    fires = 0
    for commodity, direction, threshold, hint in DEFAULT_KILL_THRESHOLDS:
        # Letzte 2 Schlusskurse
        rows = conn.execute('''
            SELECT date, price FROM commodity_prices
            WHERE commodity=?
            ORDER BY date DESC LIMIT 2
        ''', (commodity,)).fetchall()
        if len(rows) < 2:
            continue
        p_today, p_prev = rows[0][1], rows[1][1]

        breached_today = (direction == 'below' and p_today < threshold) or \
                         (direction == 'above' and p_today > threshold)
        breached_prev = (direction == 'below' and p_prev < threshold) or \
                        (direction == 'above' and p_prev > threshold)

        if breached_today and breached_prev:
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO commodity_kill_events
                    (commodity, direction, threshold, fired_date, price_at_fire, confirmed, hint)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                ''', (commodity, direction, threshold, today, p_today, hint))
                if conn.total_changes:
                    fires += 1
                    _log(f'KILL_FIRE {commodity} {direction} {threshold} '
                         f'(heute={p_today}, gestern={p_prev}) → {hint}')
            except Exception as e:
                _log(f'kill insert err: {e}')
    conn.commit()
    return fires


def get_latest(commodity: str) -> dict | None:
    """Helper fuer andere Module — letzter Preis eines Commodities."""
    if not DB.exists():
        return None
    conn = sqlite3.connect(str(DB))
    r = conn.execute('''
        SELECT commodity, date, price, unit FROM commodity_prices
        WHERE commodity=? ORDER BY date DESC LIMIT 1
    ''', (commodity,)).fetchone()
    conn.close()
    if not r:
        return None
    return {'commodity': r[0], 'date': r[1], 'price': r[2], 'unit': r[3]}


if __name__ == '__main__':
    s = refresh_all()
    print('\n── Commodity Refresh Summary ──')
    for k, v in s.items():
        print(f'  {k:12} {v}')
