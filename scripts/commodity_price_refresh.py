#!/usr/bin/env python3
"""
commodity_price_refresh.py — Phase 44k: Commodity-Cache fuer Korrelations-Awareness.

Problem: Hunter und Discord-Bot konnten Commodity-Underlying-Preise (Brent, Gold,
Copper, VIX etc.) nicht zuverlaessig abrufen. Albert sagte mehrfach "Sandbox-
Permission gescheitert".

Loesung: Ein Job zieht alle 15min die wichtigsten Underlyings via yfinance und
schreibt sie in data/commodity_prices.json. Hunter, CEO-Brain, Discord-Bot lesen
nur noch diesen Cache (keine eigenen yfinance-Calls).

Format:
{
  "ts": "2026-04-30T15:30:00+00:00",
  "prices": {
    "BZ=F":   {"name": "Brent", "spot": 104.45, "ccy": "USD", "chg_24h_pct": -0.07, "chg_7d_pct": +2.1},
    "CL=F":   {"name": "WTI",   "spot": 105.30, ...},
    ...
  }
}

Run:
  python3 scripts/commodity_price_refresh.py            # einmal
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
OUT = WS / 'data' / 'commodity_prices.json'

# Symbol → (Display Name, Currency, Sector-Tag)
UNDERLYINGS = {
    'BZ=F':       ('Brent Crude',     'USD', 'energy'),
    'CL=F':       ('WTI Crude',       'USD', 'energy'),
    'NG=F':       ('Natural Gas',     'USD', 'energy'),
    'GC=F':       ('Gold',            'USD', 'metals'),
    'SI=F':       ('Silver',          'USD', 'metals'),
    'HG=F':       ('Copper',          'USD', 'metals'),
    'PL=F':       ('Platinum',        'USD', 'metals'),
    'ZW=F':       ('Wheat',           'USD', 'agri'),
    'ZC=F':       ('Corn',            'USD', 'agri'),
    'ZS=F':       ('Soybeans',        'USD', 'agri'),
    '^VIX':       ('VIX',             'pts', 'volatility'),
    '^TNX':       ('US 10Y Yield',    'pct', 'rates'),
    'DX-Y.NYB':   ('Dollar Index',    'pts', 'fx'),
    'EURUSD=X':   ('EUR/USD',         'fx',  'fx'),
    'EURNOK=X':   ('EUR/NOK',         'fx',  'fx'),
    'BTC-USD':    ('Bitcoin',         'USD', 'crypto'),
    'ETH-USD':    ('Ethereum',        'USD', 'crypto'),
    '^GSPC':      ('S&P 500',         'pts', 'equity'),
    '^IXIC':      ('Nasdaq Comp',     'pts', 'equity'),
    '^GDAXI':     ('DAX',             'pts', 'equity'),
    '^STOXX50E':  ('Euro Stoxx 50',   'pts', 'equity'),
    'XLE':        ('Energy ETF',      'USD', 'sector_etf'),
    'XLF':        ('Financial ETF',   'USD', 'sector_etf'),
    'XLK':        ('Tech ETF',        'USD', 'sector_etf'),
    'GDX':        ('Gold Miners ETF', 'USD', 'sector_etf'),
    'ITA':        ('Defense ETF',     'USD', 'sector_etf'),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_one(symbol: str) -> dict | None:
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period='14d', interval='1d')
        if h.empty:
            return None
        last = float(h['Close'].iloc[-1])
        # 24h-Change (gestern Close → heute)
        prev_24h = float(h['Close'].iloc[-2]) if len(h) >= 2 else last
        chg_24h = (last - prev_24h) / prev_24h * 100 if prev_24h else 0.0
        # 7d-Change
        prev_7d = float(h['Close'].iloc[-min(8, len(h))])
        chg_7d = (last - prev_7d) / prev_7d * 100 if prev_7d else 0.0
        # 14d-Change
        prev_14d = float(h['Close'].iloc[0])
        chg_14d = (last - prev_14d) / prev_14d * 100 if prev_14d else 0.0
        # 14d-Range
        hi = float(h['High'].max())
        lo = float(h['Low'].min())
        return {
            'spot': round(last, 4),
            'chg_24h_pct': round(chg_24h, 2),
            'chg_7d_pct': round(chg_7d, 2),
            'chg_14d_pct': round(chg_14d, 2),
            'range_14d_low': round(lo, 4),
            'range_14d_high': round(hi, 4),
            'as_of': h.index[-1].strftime('%Y-%m-%d'),
        }
    except Exception as e:
        return {'error': str(e)[:80]}


def refresh() -> dict:
    out = {'ts': _now(), 'prices': {}}
    for sym, (name, ccy, sector) in UNDERLYINGS.items():
        d = fetch_one(sym)
        if not d:
            continue
        out['prices'][sym] = {'name': name, 'ccy': ccy, 'sector': sector, **d}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding='utf-8')
    return out


def get_price(symbol_or_name: str) -> dict | None:
    """Public-API: liefert aktuellen Cache-Eintrag fuer ein Symbol oder Display-Namen."""
    if not OUT.exists():
        return None
    data = json.loads(OUT.read_text(encoding='utf-8'))
    prices = data.get('prices', {})
    if symbol_or_name in prices:
        return prices[symbol_or_name]
    # Fuzzy by name (case-insensitive)
    needle = symbol_or_name.lower()
    for sym, p in prices.items():
        if needle in p.get('name', '').lower() or needle == sym.lower():
            return {'symbol': sym, **p}
    return None


def get_snapshot_str(top_n: int = 20) -> str:
    """Format Brent / VIX / Gold / DXY als kompakte Zeile fuer LLM-Prompts."""
    if not OUT.exists():
        return '(commodity cache empty)'
    data = json.loads(OUT.read_text(encoding='utf-8'))
    prices = data.get('prices', {})
    ts = data.get('ts', '')[:16]
    lines = [f'(Cache @ {ts} UTC)']
    for sym, p in list(prices.items())[:top_n]:
        if 'spot' not in p:
            continue
        chg24 = p.get('chg_24h_pct', 0)
        chg7 = p.get('chg_7d_pct', 0)
        arr_24 = '↑' if chg24 > 0.3 else '↓' if chg24 < -0.3 else '→'
        lines.append(
            f'  {p["name"]:<18} {p["spot"]:>10.2f} {p["ccy"]:<3} '
            f'{arr_24} 24h {chg24:+.2f}% | 7d {chg7:+.2f}%'
        )
    return '\n'.join(lines)


def main() -> int:
    r = refresh()
    print(f'Commodity-Cache @ {r["ts"][:16]}')
    print(f'  {len(r["prices"])} symbols cached')
    print()
    print(get_snapshot_str(top_n=30))
    return 0


if __name__ == '__main__':
    sys.exit(main())
