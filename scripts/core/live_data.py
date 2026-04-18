#!/usr/bin/env python3
"""
live_data.py — Single Source of Truth für alle Live-Marktdaten
===============================================================

ARCHITEKTUR-REGEL:
  - Nur dieses Modul darf Yahoo Finance / externe Quellen aufrufen
  - Alle anderen Scripts rufen NUR Funktionen aus diesem Modul auf
  - Daten werden IMMER in trading.db geschrieben und von dort gelesen
  - Kein Script speichert Marktdaten in eigenen Variablen oder JSON-Dateien

DATENFLUSS:
  Yahoo Finance → live_data.refresh_*() → trading.db → alle Scripts

VERWENDUNG:
  from scripts.core.live_data import get_price, get_vix, get_eurusd, get_regime
  
  price   = get_price('EQNR.OL')     # EUR, aus DB (max 15min alt)
  vix     = get_vix()                 # aus DB (max 60min alt)
  eurusd  = get_eurusd()              # aus DB (max 60min alt)
  regime  = get_regime()              # aus DB
  fresh   = is_price_fresh('TTE.PA') # True/False
"""

import json
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH  = WS / 'data/trading.db'
GATE_PATH = WS / 'data/news_gate.json'

# Wie alt dürfen Daten maximal sein bevor auto-refresh
MAX_PRICE_AGE_MINUTES = 20    # Preise: 20 Min (Intraday-Modus)
MAX_PRICE_AGE_DAYS    = 3     # Preise: Tage (für is_price_fresh Guard)
MAX_VIX_AGE_MINUTES   = 60    # VIX: 1 Stunde
MAX_FX_AGE_MINUTES    = 60    # EUR/USD: 1 Stunde

# Suffix → Währungscode (Yahoo-Lieferung)
SUFFIX_CURRENCY = {
    '.DE':  'EUR',   # Xetra
    '.PA':  'EUR',   # Euronext Paris
    '.AS':  'EUR',   # Euronext Amsterdam
    '.MI':  'EUR',   # Borsa Italiana
    '.MC':  'EUR',   # BME Madrid
    '.VI':  'EUR',   # Wiener Börse
    '.BR':  'EUR',   # Euronext Brüssel
    '.L':   'GBp',   # London Stock Exchange — PENCE (÷100 für GBP!)
    '.OL':  'NOK',   # Oslo Børs
    '.CO':  'DKK',   # Kopenhagen
    '.ST':  'SEK',   # Stockholm
    '.HE':  'EUR',   # Helsinki
}
# EUR_SUFFIXES für schnellen Check (direkt in EUR, kein Umrechnen nötig)
EUR_SUFFIXES = {s for s, c in SUFFIX_CURRENCY.items() if c == 'EUR'}


def get_fx_factor(ticker: str) -> float:
    """
    Gibt den Multiplikator zurück, um Yahoo-Rohpreise in EUR zu konvertieren.
    Beispiel: EQNR.OL (NOK) → 0.085, AAPL (USD) → 0.91, RHM.DE (EUR) → 1.0
    """
    ticker_upper = ticker.upper()
    suffix = next((s for s in SUFFIX_CURRENCY if ticker_upper.endswith(s.upper())), None)
    currency = SUFFIX_CURRENCY.get(suffix, 'USD') if suffix else 'USD'

    if currency == 'EUR':
        return 1.0

    eurusd = get_eurusd()
    if not eurusd:
        return 1.0  # Fallback: unkonvertiert

    if currency == 'GBp':
        # London: Pence → GBP (÷100), dann GBP→EUR
        gbpusd_data = _yahoo_raw('GBPUSD=X', range_='1d')
        try:
            gbp_rate = gbpusd_data['chart']['result'][0]['meta']['regularMarketPrice']
        except Exception:
            gbp_rate = 1.27  # Notfall-Fallback
        return (1.0 / 100) * gbp_rate / eurusd

    FX_PAIRS = {'NOK': 'NOKUSD=X', 'DKK': 'DKKUSD=X', 'SEK': 'SEKUSD=X'}
    fx_pair = FX_PAIRS.get(currency)
    if fx_pair:
        fx_data = _yahoo_raw(fx_pair, range_='1d')
        try:
            fx_rate = fx_data['chart']['result'][0]['meta']['regularMarketPrice']
            return fx_rate / eurusd
        except Exception:
            pass

    # USD → EUR
    return 1.0 / eurusd


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _yahoo_raw(ticker: str, range_: str = '5d') -> dict | None:
    """Interner Yahoo-Abruf. NUR von diesem Modul aufrufen."""
    url = (f'https://query2.finance.yahoo.com/v8/finance/chart/'
           f'{ticker}?interval=1d&range={range_}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r)
    except Exception:
        return None


# ─── PREISE ──────────────────────────────────────────────────────────────────

def refresh_price(ticker: str) -> float | None:
    """
    Holt aktuellen Kurs von Yahoo, schreibt in trading.db:prices.
    Gibt den Kurs zurück (in Yahoo-Währung — kann USD oder EUR sein).
    """
    data = _yahoo_raw(ticker, range_='30d')
    if not data:
        return None

    try:
        result = data['chart']['result'][0]
        meta = result['meta']
        current_price = meta.get('regularMarketPrice')

        # Historische Kerzen in DB schreiben
        timestamps = result.get('timestamp', [])
        quote = result['indicators']['quote'][0]
        closes  = quote.get('close', [])
        volumes = quote.get('volume', [])
        opens   = quote.get('open', [])
        highs   = quote.get('high', [])
        lows    = quote.get('low', [])

        conn = _get_db()
        inserted = 0
        for i, ts in enumerate(timestamps):
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
            c = closes[i] if i < len(closes) and closes[i] else None
            if not c:
                continue
            v = volumes[i] if i < len(volumes) and volumes[i] else None
            o = opens[i]  if i < len(opens)   and opens[i]   else c
            h = highs[i]  if i < len(highs)   and highs[i]   else c
            l = lows[i]   if i < len(lows)    and lows[i]    else c
            conn.execute(
                'INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (ticker, date_str, o, h, l, c, v)
            )
            inserted += 1
        conn.commit()
        conn.close()
        return current_price
    except Exception:
        return None


def refresh_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    """Refresht mehrere Ticker auf einmal. Gibt {ticker: price} zurück."""
    import time
    results = {}
    for ticker in tickers:
        results[ticker] = refresh_price(ticker)
        time.sleep(0.1)  # Rate limit
    return results


def get_price(ticker: str, max_age_minutes: int = MAX_PRICE_AGE_MINUTES) -> float | None:
    """
    Holt aktuellen Preis aus DB. Auto-refresh wenn älter als max_age_minutes.
    Gibt Preis in der Yahoo-Originalwährung zurück.
    """
    conn = _get_db()
    row = conn.execute(
        'SELECT close, date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1',
        (ticker,)
    ).fetchone()
    conn.close()

    if row:
        last_date = datetime.strptime(row['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - last_date).days
        # Wochenende/Feiertag: Daten von Fr sind Mo noch gültig
        if age_days <= 3:
            return row['close']

    # Daten zu alt oder nicht vorhanden → live holen
    return refresh_price(ticker)


def get_price_eur(ticker: str) -> float | None:
    """
    Wie get_price(), aber konvertiert automatisch in EUR.
    Berücksichtigt NOK, DKK, SEK, GBp (London pence).
    Gibt immer EUR zurück.
    """
    price = get_price(ticker)
    if price is None:
        return None

    ticker_upper = ticker.upper()

    # Suffix → Währung ermitteln
    suffix = next((s for s in SUFFIX_CURRENCY if ticker_upper.endswith(s.upper())), None)
    currency = SUFFIX_CURRENCY.get(suffix, 'USD') if suffix else 'USD'

    if currency == 'EUR':
        return round(price, 4)

    eurusd = get_eurusd()

    if currency == 'GBp':
        # London: Pence → GBP (÷100), dann GBP→EUR
        gbpusd = _yahoo_raw('GBPUSD=X', range_='1d')
        gbp_rate = None
        try:
            gbp_rate = gbpusd['chart']['result'][0]['meta']['regularMarketPrice']
        except Exception:
            gbp_rate = 1.27  # Notfall-Fallback GBP/USD
        gbp_price = price / 100
        return round(gbp_price * gbp_rate / eurusd, 4) if eurusd else round(gbp_price * gbp_rate, 4)

    # FX-Kurse für andere Währungen
    FX_PAIRS = {'NOK': 'NOKUSD=X', 'DKK': 'DKKUSD=X', 'SEK': 'SEKUSD=X'}
    fx_pair = FX_PAIRS.get(currency)
    if fx_pair:
        fx_data = _yahoo_raw(fx_pair, range_='1d')
        try:
            fx_rate = fx_data['chart']['result'][0]['meta']['regularMarketPrice']
        except Exception:
            fx_rate = None
        # SICHERHEIT: Ohne FX-Rate KEIN Fallback — sonst droht Nicht-EUR-Preis
        # als EUR interpretiert zu werden (z.B. SEK 93 → vermeintlich 93€ statt 8€).
        # Das hätte echte TARGET/STOP-Alerts mit falschen Close-Actions zur Folge.
        if fx_rate is None or not eurusd:
            return None
        return round(price * fx_rate / eurusd, 4)

    # US-Ticker oder unbekannt: USD → EUR
    # Ohne EURUSD keine verlässliche Konvertierung → None (kein stumpfer USD-Fallback).
    if not eurusd:
        return None
    return round(price / eurusd, 4)


def is_price_fresh(ticker: str, max_days: int = MAX_PRICE_AGE_DAYS) -> bool:
    """True wenn letzter Kurs in DB nicht älter als max_days Werktage."""
    conn = _get_db()
    row = conn.execute(
        'SELECT date FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1',
        (ticker,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    last = datetime.strptime(row['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).days <= max_days


# ─── VIX ─────────────────────────────────────────────────────────────────────

def refresh_vix() -> float | None:
    """Holt VIX live von Yahoo, schreibt in macro_daily."""
    data = _yahoo_raw('^VIX', range_='1d')
    if not data:
        return None
    try:
        vix = data['chart']['result'][0]['meta'].get('regularMarketPrice')
        if vix:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            conn = _get_db()
            conn.execute(
                'INSERT OR REPLACE INTO macro_daily (date, indicator, value) VALUES (?, ?, ?)',
                (today, 'VIX', round(vix, 2))
            )
            conn.commit()
            conn.close()
        return vix
    except Exception:
        return None


def get_vix(max_age_minutes: int = MAX_VIX_AGE_MINUTES) -> float | None:
    """
    Holt VIX aus DB. Auto-refresh wenn älter als max_age_minutes.
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT value, date FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if row:
        last = datetime.strptime(row['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last).days == 0:
            # Heute schon vorhanden — gut genug für Trading-Entscheidungen
            return row['value']

    # Noch kein VIX heute → live holen
    return refresh_vix()


# ─── EUR/USD ─────────────────────────────────────────────────────────────────

def refresh_eurusd() -> float | None:
    """Holt EUR/USD live von Yahoo, schreibt in macro_daily."""
    data = _yahoo_raw('EURUSD=X', range_='1d')
    if not data:
        return None
    try:
        fx = data['chart']['result'][0]['meta'].get('regularMarketPrice')
        if fx:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            conn = _get_db()
            conn.execute(
                'INSERT OR REPLACE INTO macro_daily (date, indicator, value) VALUES (?, ?, ?)',
                (today, 'EURUSD', round(fx, 6))
            )
            conn.commit()
            conn.close()
        return fx
    except Exception:
        return None


def get_eurusd(max_age_minutes: int = MAX_FX_AGE_MINUTES) -> float:
    """
    Holt EUR/USD aus DB. Auto-refresh wenn nicht aktuell.
    Gibt 1.10 als Notfall-Fallback (nie hardcoded 1.15!).
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT value, date FROM macro_daily WHERE indicator='EURUSD' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if row:
        last = datetime.strptime(row['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last).days <= 3:
            return row['value']

    live = refresh_eurusd()
    return live if live else 1.10  # Notfall-Fallback: 1.10 (realistischer als 1.15)


# ─── REGIME ──────────────────────────────────────────────────────────────────

def get_regime() -> str:
    """Holt aktuelles Markt-Regime aus DB (regime_history)."""
    conn = _get_db()
    row = conn.execute(
        'SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1'
    ).fetchone()
    conn.close()
    return row['regime'] if row else 'NEUTRAL'


# ─── SNAPSHOT (alle Live-Daten auf einmal) ───────────────────────────────────

def get_market_snapshot() -> dict:
    """
    Gibt alle aktuellen Marktdaten in einem Dict zurück.
    Ideal für Reports und Cron-Jobs.
    """
    return {
        'vix':     get_vix(),
        'eurusd':  get_eurusd(),
        'regime':  get_regime(),
        'ts':      datetime.now(timezone.utc).isoformat(),
    }


def refresh_all_live_data(tickers: list[str] | None = None) -> dict:
    """
    Refresht ALLE Live-Daten:
    - VIX
    - EUR/USD
    - Alle übergebenen Ticker (oder komplette Watchlist aus DB)
    
    Gedacht für täglichen Morgen-Refresh (07:00 CET).
    """
    vix    = refresh_vix()
    eurusd = refresh_eurusd()

    if tickers is None:
        # Watchlist = offene Positionen + alle Ticker mit frischem Deep-Dive-Verdict
        # (≤14 Tage) — egal ob KAUFEN/WARTEN, damit Trigger-Preise aktuell bleiben.
        # + Ticker aus aktiven strategies.json Einträgen (primary_ticker).
        conn = _get_db()
        pos = [r[0] for r in conn.execute(
            "SELECT DISTINCT ticker FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()]
        conn.close()

        _ws_root = Path(__file__).resolve().parents[2]
        verdict_tickers: list[str] = []
        try:
            import json as _json
            _vfile = _ws_root / 'data' / 'deep_dive_verdicts.json'
            if _vfile.exists():
                _verdicts = _json.loads(_vfile.read_text(encoding='utf-8'))
                _cutoff = datetime.now(timezone.utc).timestamp() - 14 * 86400
                for _t, _v in _verdicts.items():
                    _ts_str = _v.get('timestamp') or _v.get('date', '')
                    try:
                        if 'T' in _ts_str:
                            _ts = datetime.fromisoformat(_ts_str.replace('Z', '+00:00'))
                        else:
                            _ts = datetime.strptime(_ts_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                        if _ts.timestamp() >= _cutoff:
                            verdict_tickers.append(_t)
                    except Exception:
                        continue
        except Exception:
            pass

        strategy_tickers: list[str] = []
        try:
            import json as _json
            _sfile = _ws_root / 'data' / 'strategies.json'
            if _sfile.exists():
                _strats = _json.loads(_sfile.read_text(encoding='utf-8'))
                for _sid, _s in _strats.items():
                    if not isinstance(_s, dict):
                        continue
                    if _s.get('status') in ('inactive', 'blocked', 'suspended'):
                        continue
                    _pt = _s.get('primary_ticker') or _s.get('ticker')
                    if _pt:
                        strategy_tickers.append(_pt)
        except Exception:
            pass

        tickers = sorted(set(pos) | set(verdict_tickers) | set(strategy_tickers))

    prices = refresh_prices_bulk(tickers)
    n_ok = sum(1 for v in prices.values() if v is not None)

    return {
        'vix':     vix,
        'eurusd':  eurusd,
        'regime':  get_regime(),
        'prices_refreshed': n_ok,
        'prices_total':     len(tickers),
        'ts':      datetime.now(timezone.utc).isoformat(),
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    args = sys.argv[1:]

    if '--snapshot' in args:
        snap = get_market_snapshot()
        print(f"VIX:    {snap['vix']}")
        print(f"EURUSD: {snap['eurusd']}")
        print(f"Regime: {snap['regime']}")
        print(f"Stand:  {snap['ts']}")

    elif '--refresh' in args:
        print("Refreshe alle Live-Daten...")
        result = refresh_all_live_data()
        print(f"VIX:    {result['vix']}")
        print(f"EURUSD: {result['eurusd']}")
        print(f"Preise: {result['prices_refreshed']}/{result['prices_total']} OK")

    elif len(args) == 1:
        ticker = args[0].upper()
        p = get_price(ticker)
        p_eur = get_price_eur(ticker)
        fresh = is_price_fresh(ticker)
        print(f"{ticker}: {p} (EUR: {p_eur}) | Fresh: {fresh}")

    else:
        print("Usage:")
        print("  python3 live_data.py --snapshot     # VIX + EURUSD + Regime")
        print("  python3 live_data.py --refresh      # Alle Daten aktualisieren")
        print("  python3 live_data.py EQNR.OL        # Einzelner Ticker")
