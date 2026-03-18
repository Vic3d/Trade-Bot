#!/usr/bin/env python3
"""
price_db.py — SQLite Preis-Datenbank mit Yahoo Finance
Paper Trading System Phase 1.1
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

DB_PATH = Path("/data/.openclaw/workspace/data/trading.db")
STRATEGIES_PATH = Path("/data/.openclaw/workspace/data/strategies.json")

# All tickers organized by region
TICKERS = {
    "US": ["NVDA", "MSFT", "PLTR", "OXY", "FRO", "DHT", "KTOS", "HII", "HL", "PAAS",
            "MOS", "CF", "HAL", "SLB", "GOLD", "WPM", "CLF", "ENPH", "PLUG", "MP", "UUUU", "EXK"],
    "EU": ["RHM.DE", "BAYN.DE", "HAG.DE", "AIR.PA", "TTE.PA", "ENI.MI", "BAS.DE"],
    "UK": ["RIO.L", "BHP.L", "BA.L", "SHEL.L", "GLEN.L", "AAL.L"],
    "NO": ["EQNR.OL", "YARA.OL"],
    "Index": ["^GSPC", "^VIX", "^GDAXI", "CL=F", "GC=F", "EURUSD=X", "EURGBP=X", "EURNOK=X"],
}

ALL_TICKERS = [t for group in TICKERS.values() for t in group]


def _load_strategy_map():
    """
    Lädt STRATEGY_MAP aus data/strategies.json (Single Source of Truth).
    Fallback auf leeres dict wenn Datei fehlt.
    Returns: dict {strategy_id: [ticker, ...]}
    """
    if not STRATEGIES_PATH.exists():
        return {}
    try:
        data = json.loads(STRATEGIES_PATH.read_text())
        strategy_map = {}
        for strat_id, strat in data.items():
            if strat_id == "emerging_themes":
                continue
            tickers = list(strat.get("tickers") or [])
            tickers += list(strat.get("watchlist_tickers") or [])
            tickers += list(strat.get("closed_tickers") or [])
            if tickers:
                strategy_map[strat_id] = list(dict.fromkeys(tickers))  # dedupliziert, Reihenfolge erhalten
        return strategy_map
    except Exception as e:
        print(f"⚠ price_db: Fehler beim Laden von strategies.json: {e}")
        return {}


# STRATEGY_MAP wird lazy aus strategies.json geladen
# Für Rückwärtskompatibilität bleibt STRATEGY_MAP als Modul-Level-Variable,
# wird aber aus JSON gebaut statt hardcoded.
STRATEGY_MAP = _load_strategy_map()


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_tables():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prices (
            ticker TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        );
        CREATE TABLE IF NOT EXISTS ticker_meta (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            exchange TEXT,
            currency TEXT,
            sector TEXT,
            strategy TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
        CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
    """)
    conn.commit()
    conn.close()


def fetch_history(ticker, years=2):
    """Fetch daily OHLCV data from Yahoo Finance for given years."""
    try:
        t = yf.Ticker(ticker)
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        df = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), auto_adjust=True)
        if df.empty:
            print(f"  ⚠ {ticker}: Keine Daten erhalten")
            return None
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as e:
        print(f"  ❌ {ticker}: {e}")
        return None


def store_prices(ticker, df):
    """Store price DataFrame into SQLite."""
    if df is None or df.empty:
        return 0
    conn = get_db()
    rows = []
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        rows.append((ticker, date_str, row.get("Open"), row.get("High"),
                     row.get("Low"), row.get("Close"), int(row.get("Volume", 0))))
    conn.executemany(
        "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()
    return len(rows)


def store_meta(ticker):
    """Fetch and store ticker metadata."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        name = info.get("shortName") or info.get("longName") or ticker
        exchange = info.get("exchange", "")
        currency = info.get("currency", "")
        sector = info.get("sector", "")
        # Find strategy
        strategy = ",".join([s for s, tickers in STRATEGY_MAP.items() if ticker in tickers])
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO ticker_meta (ticker, name, exchange, currency, sector, strategy) VALUES (?,?,?,?,?,?)",
            (ticker, name, exchange, currency, sector, strategy)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  ⚠ Meta für {ticker}: {e}")


def update_daily(tickers):
    """Only fetch missing days for each ticker."""
    conn = get_db()
    for ticker in tickers:
        # Find last date in DB
        row = conn.execute(
            "SELECT MAX(date) FROM prices WHERE ticker = ?", (ticker,)
        ).fetchone()
        last_date = row[0] if row[0] else None

        if last_date:
            start = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            if start >= today:
                print(f"  ✓ {ticker}: aktuell")
                continue
            try:
                t = yf.Ticker(ticker)
                df = t.history(start=start, end=today, auto_adjust=True)
                if df is not None and not df.empty:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    n = store_prices(ticker, df)
                    print(f"  + {ticker}: {n} neue Tage")
                else:
                    print(f"  ✓ {ticker}: keine neuen Daten")
            except Exception as e:
                print(f"  ❌ {ticker}: {e}")
        else:
            print(f"  ⚠ {ticker}: nicht in DB — bitte 'init' ausführen")
        time.sleep(0.3)
    conn.close()


def get_prices(ticker, days=None):
    """Get price history from DB."""
    conn = get_db()
    if days:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT ?",
            (ticker, days)
        ).fetchall()
        rows.reverse()
    else:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            (ticker,)
        ).fetchall()
    conn.close()
    return rows


def get_closes(ticker, days=None):
    """Get closing prices as list."""
    rows = get_prices(ticker, days)
    return [r[4] for r in rows if r[4] is not None]


def get_sma(ticker, period):
    """Simple Moving Average over last `period` trading days."""
    closes = get_closes(ticker, period + 10)  # buffer
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def get_rsi(ticker, period=14):
    """Relative Strength Index."""
    closes = get_closes(ticker, period + 50)  # need enough data
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    # Use Wilder's smoothing (exponential)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_relative_strength(ticker, benchmark="^GSPC", days=20):
    """Relative performance vs benchmark over N days."""
    ticker_closes = get_closes(ticker, days + 5)
    bench_closes = get_closes(benchmark, days + 5)
    if len(ticker_closes) < days or len(bench_closes) < days:
        return None
    ticker_ret = (ticker_closes[-1] / ticker_closes[-days] - 1) * 100
    bench_ret = (bench_closes[-1] / bench_closes[-days] - 1) * 100
    return ticker_ret - bench_ret


def get_volume_ratio(ticker, short=5, long=20):
    """Ratio of short-term avg volume to long-term avg volume."""
    rows = get_prices(ticker, long + 5)
    if len(rows) < long:
        return None
    volumes = [r[5] for r in rows if r[5] is not None and r[5] > 0]
    if len(volumes) < long:
        return None
    short_avg = sum(volumes[-short:]) / short
    long_avg = sum(volumes[-long:]) / long
    if long_avg == 0:
        return None
    return short_avg / long_avg


def cmd_init():
    """Initialize DB and fetch 2 years of history for all tickers."""
    init_tables()
    total = len(ALL_TICKERS)
    print(f"📊 Initialisierung: {total} Ticker laden...")
    for i, ticker in enumerate(ALL_TICKERS, 1):
        print(f"[{i}/{total}] {ticker}...", end=" ", flush=True)
        df = fetch_history(ticker, years=2)
        if df is not None:
            n = store_prices(ticker, df)
            print(f"✓ {n} Tage")
        else:
            print("übersprungen")
        store_meta(ticker)
        time.sleep(0.3)
    # Summary
    conn = get_db()
    count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
    total_rows = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    conn.close()
    print(f"\n✅ Fertig: {count} Ticker, {total_rows} Preisdatensätze in DB")


def cmd_update():
    """Update only missing days."""
    init_tables()
    print("📊 Update: Fehlende Tage nachfüllen...")
    update_daily(ALL_TICKERS)
    print("✅ Update fertig")


def cmd_info(ticker):
    """Show info for a ticker."""
    init_tables()
    closes = get_closes(ticker)
    if not closes:
        print(f"❌ Keine Daten für {ticker}")
        return
    sma50 = get_sma(ticker, 50)
    sma200 = get_sma(ticker, 200)
    rsi = get_rsi(ticker)
    rs = get_relative_strength(ticker)
    print(f"📊 {ticker}")
    print(f"  Letzter Kurs: {closes[-1]:.2f}")
    print(f"  SMA50: {sma50:.2f}" if sma50 else "  SMA50: n/a")
    print(f"  SMA200: {sma200:.2f}" if sma200 else "  SMA200: n/a")
    print(f"  RSI(14): {rsi:.1f}" if rsi else "  RSI(14): n/a")
    print(f"  Rel. Stärke vs S&P500 (20d): {rs:+.1f}%" if rs else "  Rel. Stärke: n/a")
    print(f"  Datenpunkte: {len(closes)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 price_db.py [init|update|info TICKER]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "init":
        cmd_init()
    elif cmd == "update":
        cmd_update()
    elif cmd == "info" and len(sys.argv) >= 3:
        cmd_info(sys.argv[2])
    else:
        print("Usage: python3 price_db.py [init|update|info TICKER]")
        sys.exit(1)
