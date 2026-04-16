#!/usr/bin/env python3
"""
TradeMind CEO — Das zentrale Gehirn des Systems
================================================
Liest alle Datenquellen, berechnet den System-Zustand,
schreibt den täglichen Marschbefehl (ceo_directive.json)
und generiert einen Bericht für Victor.

Verwendung:
  python3 scripts/ceo.py              # Direktive schreiben + Report ausgeben
  python3 scripts/ceo.py --health     # Nur System-Health-Check
  python3 scripts/ceo.py --report     # Nur Report, keine Direktive
  python3 scripts/ceo.py --live       # Mit Live-Marktdaten von Yahoo Finance
  python3 scripts/ceo.py --live --report  # Live-Report ohne Direktive zu schreiben
  python3 scripts/ceo.py --backtest      # Detaillierte Backtest-Ergebnisse anzeigen

Autor: Albert 🎩 | v3.0 Adaptive Intelligence + Backtest | 31.03.2026
"""

import sqlite3
import json
import sys
import argparse
import math
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

WS = Path('/data/.openclaw/workspace')


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def safe_read_json(path: Path, default=None):
    """JSON-Datei lesen — gibt default zurück wenn Datei fehlt oder kaputt ist."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def safe_read_text(path: Path, default: str = '') -> str:
    """Textdatei lesen — gibt default zurück wenn Datei fehlt."""
    try:
        if path.exists():
            return path.read_text()
    except Exception:
        pass
    return default


def get_db():
    """SQLite-Verbindung öffnen."""
    db_path = WS / 'data/trading.db'
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


# ─── P2.A — Live-Daten-Integration ────────────────────────────────────────────

MARKET_CACHE_PATH = WS / 'data/market_cache.json'
MARKET_CACHE_TTL = 300  # 5 Minuten

YAHOO_TICKERS = {
    'vix': '%5EVIX',
    'spy': '%5EGSPC',
    'nasdaq': '%5EIXIC',
    'eurusd': 'EURUSD%3DX',
    'xle': 'XLE',
    'xlk': 'XLK',
    'xlf': 'XLF',
    'xli': 'XLI',
    'xlb': 'XLB',
    'xlv': 'XLV',
}

SECTOR_ETF_NAMES = {
    'xle': 'energy',
    'xlk': 'tech',
    'xlf': 'financials',
    'xli': 'industrials',
    'xlb': 'materials',
    'xlv': 'healthcare',
}


def _fetch_yahoo_chart(ticker_encoded: str) -> dict | None:
    """Holt Chart-Daten von Yahoo Finance für einen Ticker.
    Returns dict mit price, ma50, ma200, change_pct oder None bei Fehler."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker_encoded}?interval=1d&range=6mo'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        result = data['chart']['result'][0]
        meta = result['meta']
        price = meta.get('regularMarketPrice', 0.0)
        prev_close = meta.get('chartPreviousClose', meta.get('previousClose', price))

        # Closing prices for MA calculation
        closes_raw = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
        # Filter None values
        closes = [c for c in closes_raw if c is not None]

        ma50 = sum(closes[-50:]) / len(closes[-50:]) if len(closes) >= 50 else None
        ma200 = sum(closes[-200:]) / len(closes[-200:]) if len(closes) >= 200 else None

        # If we don't have 200 days, use what we have (6mo ≈ 126 trading days)
        if ma200 is None and len(closes) >= 100:
            ma200 = sum(closes) / len(closes)  # Best approximation with available data

        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        # 52-week high approximation from available data
        high_prices = result.get('indicators', {}).get('quote', [{}])[0].get('high', [])
        high_prices = [h for h in high_prices if h is not None]
        period_high = max(high_prices) if high_prices else price

        return {
            'price': round(price, 4),
            'prev_close': round(prev_close, 4),
            'change_pct': round(change_pct, 2),
            'ma50': round(ma50, 4) if ma50 else None,
            'ma200': round(ma200, 4) if ma200 else None,
            'period_high': round(period_high, 4),
            'data_points': len(closes),
        }
    except Exception as e:
        print(f'⚠️ Yahoo Finance Fehler für {ticker_encoded}: {e}', file=sys.stderr)
        return None


def fetch_live_market_data() -> dict:
    """Holt aktuelle Marktdaten von Yahoo Finance.
    Returns dict mit vix, spy, sector_etfs, eurusd, etc.
    Cached in data/market_cache.json (TTL: 5 Min)."""

    # Check cache
    try:
        if MARKET_CACHE_PATH.exists():
            cache = json.loads(MARKET_CACHE_PATH.read_text())
            cache_ts = cache.get('_timestamp', 0)
            if (time.time() - cache_ts) < MARKET_CACHE_TTL:
                print('📦 Market-Cache verwendet (< 5 Min alt)')
                return cache
    except Exception:
        pass

    print('🌐 Lade Live-Marktdaten von Yahoo Finance...')
    market_data = {
        '_timestamp': time.time(),
        '_fetched_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        '_source': 'yahoo_finance',
    }

    # Fetch all tickers
    for key, ticker_enc in YAHOO_TICKERS.items():
        result = _fetch_yahoo_chart(ticker_enc)
        if result:
            market_data[key] = result
        else:
            market_data[key] = {'price': 0.0, 'error': True}
        # Small delay to be nice to Yahoo
        time.sleep(0.2)

    # Save cache
    try:
        MARKET_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MARKET_CACHE_PATH, 'w') as f:
            json.dump(market_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ Cache-Schreibfehler: {e}', file=sys.stderr)

    fetched_count = sum(1 for k in YAHOO_TICKERS if not market_data.get(k, {}).get('error'))
    print(f'✅ {fetched_count}/{len(YAHOO_TICKERS)} Ticker geladen')
    return market_data


# ─── P2.B — Enhanced Regime-Klassifikator ─────────────────────────────────────

def classify_regime(market_data: dict) -> dict:
    """Klassifiziert Marktregime aus Live-Daten.
    Returns dict mit overall regime, VIX, SPY metrics, sector regimes."""

    result = {
        'overall': 'RANGE_BOUND',
        'vix': 0.0,
        'spy_vs_ma200': 0.0,
        'spy_vs_ma50': 0.0,
        'spy_trend': 'FLAT',
        'sectors': {},
        'sector_leaders': [],
        'sector_laggards': [],
        'nasdaq_vs_ma200': 0.0,
        'eurusd': 0.0,
    }

    try:
        # VIX
        vix_data = market_data.get('vix', {})
        vix = vix_data.get('price', 25.0)
        result['vix'] = round(vix, 2)

        # SPY (S&P 500)
        spy_data = market_data.get('spy', {})
        spy_price = spy_data.get('price', 0)
        spy_ma50 = spy_data.get('ma50')
        spy_ma200 = spy_data.get('ma200')
        spy_high = spy_data.get('period_high', spy_price)

        # EUR/USD
        eurusd_data = market_data.get('eurusd', {})
        result['eurusd'] = eurusd_data.get('price', 0.0)

        # Nasdaq
        nasdaq_data = market_data.get('nasdaq', {})
        nasdaq_price = nasdaq_data.get('price', 0)
        nasdaq_ma200 = nasdaq_data.get('ma200')
        if nasdaq_price and nasdaq_ma200 and nasdaq_ma200 > 0:
            result['nasdaq_vs_ma200'] = round((nasdaq_price / nasdaq_ma200 - 1) * 100, 2)

        # SPY vs MAs
        if spy_price and spy_ma200 and spy_ma200 > 0:
            result['spy_vs_ma200'] = round((spy_price / spy_ma200 - 1) * 100, 2)
        if spy_price and spy_ma50 and spy_ma50 > 0:
            result['spy_vs_ma50'] = round((spy_price / spy_ma50 - 1) * 100, 2)

        # SPY Trend
        if spy_ma50 and spy_ma200:
            if spy_ma50 > spy_ma200 * 1.01:
                result['spy_trend'] = 'UP'
            elif spy_ma50 < spy_ma200 * 0.99:
                result['spy_trend'] = 'DOWN'
            else:
                result['spy_trend'] = 'FLAT'

        # Drop from period high (ATH approximation)
        drop_from_high = 0.0
        if spy_high > 0 and spy_price > 0:
            drop_from_high = (1 - spy_price / spy_high) * 100  # positive = below high

        # ── Overall Regime Classification ──
        spy_above_ma200 = result['spy_vs_ma200'] > 0
        spy_near_ma200 = abs(result['spy_vs_ma200']) <= 5
        ma50_above_ma200 = spy_ma50 > spy_ma200 if (spy_ma50 and spy_ma200) else False

        if drop_from_high > 20 or vix > 40:
            result['overall'] = 'CRASH'
        elif drop_from_high > 10 and 25 <= vix <= 35:
            result['overall'] = 'CORRECTION'
        elif not spy_above_ma200 and not ma50_above_ma200 and vix > 25:
            result['overall'] = 'BEAR_TREND'
        elif spy_near_ma200 and not (ma50_above_ma200 and vix < 20):
            result['overall'] = 'RANGE_BOUND'
        elif spy_above_ma200 and 20 <= vix <= 30:
            result['overall'] = 'BULL_VOLATILE'
        elif spy_above_ma200 and ma50_above_ma200 and vix < 20:
            result['overall'] = 'BULL_TREND'
        else:
            # Fallback: use strongest signals
            if spy_above_ma200:
                result['overall'] = 'BULL_VOLATILE'
            elif vix > 30:
                result['overall'] = 'BEAR_TREND'
            else:
                result['overall'] = 'RANGE_BOUND'

        # ── Sector Regimes ──
        leaders = []
        laggards = []

        for etf_key, sector_name in SECTOR_ETF_NAMES.items():
            etf_data = market_data.get(etf_key, {})
            if etf_data.get('error'):
                result['sectors'][sector_name] = 'UNKNOWN'
                continue

            etf_price = etf_data.get('price', 0)
            etf_ma50 = etf_data.get('ma50')
            etf_ma200 = etf_data.get('ma200')

            if not etf_price or not etf_ma200 or etf_ma200 == 0:
                result['sectors'][sector_name] = 'UNKNOWN'
                continue

            vs_ma200 = (etf_price / etf_ma200 - 1) * 100
            vs_ma50 = (etf_price / etf_ma50 - 1) * 100 if etf_ma50 and etf_ma50 > 0 else 0
            ma50_up = etf_ma50 > etf_ma200 if (etf_ma50 and etf_ma200) else False

            # Sector regime classification
            if vs_ma200 > 0 and ma50_up:
                sector_regime = 'BULL'
                leaders.append(sector_name)
            elif vs_ma200 > 0:
                sector_regime = 'BULL_VOLATILE'
            elif abs(vs_ma200) <= 5:
                sector_regime = 'RANGE_BOUND'
            elif vs_ma200 < -10:
                sector_regime = 'CORRECTION'
                laggards.append(sector_name)
            else:
                sector_regime = 'BEAR'
                laggards.append(sector_name)

            result['sectors'][sector_name] = sector_regime

        result['sector_leaders'] = sorted(leaders)
        result['sector_laggards'] = sorted(laggards)

    except Exception as e:
        print(f'⚠️ Regime-Klassifikation Fehler: {e}', file=sys.stderr)
        result['overall'] = 'RANGE_BOUND'
        result['_error'] = str(e)

    return result


# ─── CEO Direktive laden ─────────────────────────────────────────────────────

def load_ceo_directive() -> dict | None:
    """
    Lädt die aktuelle CEO-Direktive.
    Returns None wenn nicht vorhanden oder älter als 24h.
    """
    path = WS / 'data/ceo_directive.json'
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        ts = datetime.fromisoformat(d['timestamp'])
        if (datetime.now() - ts).total_seconds() < 86400:
            return d
    except Exception:
        pass
    return None


# ─── Datenquellen laden ───────────────────────────────────────────────────────

def load_all_sources() -> dict:
    """Alle externen Datenquellen einlesen."""
    return {
        'strategies': safe_read_json(WS / 'data/strategies.json'),
        'regime': safe_read_json(WS / 'memory/market-regime.json'),
        'dna': safe_read_json(WS / 'data/dna.json'),
        'benchmark': safe_read_json(WS / 'data/benchmark.json'),
        'paper_config': safe_read_json(WS / 'data/paper_config.json'),
        'signals': safe_read_json(WS / 'data/signals.json', default=[]),
        'accuracy': safe_read_text(WS / 'memory/albert-accuracy.md'),
        'strategien': safe_read_text(WS / 'memory/strategien.md'),
        'state_snapshot': safe_read_text(WS / 'memory/state-snapshot.md'),
        'strategy_changelog': safe_read_text(WS / 'memory/strategy-changelog.md'),
    }


# ─── Historische Performance aus DB ─────────────────────────────────────────

def load_historical_data(conn) -> dict:
    """
    Berechnet alle relevanten Metriken aus der trading.db.
    Robust: kein Crash bei fehlenden Spalten oder leerer DB.
    """
    result = {
        'total_closed_trades': 0,
        'overall_win_rate': 0.0,
        'avg_pnl_per_trade': 0.0,
        'best_strategy': 'N/A',
        'worst_strategy': 'N/A',
        'open_positions': 0,
        'portfolio_drawdown': 0.0,
        'paper_benchmark_gap': 0.0,
        'recent_win_rate_7d': 0.5,
        'recent_win_rate_30d': 0.5,
        'strategy_performance': {},
        'consecutive_loss_days': 0,
        'total_realized_pnl': 0.0,
        'starting_capital': 25000.0,
        'current_cash': 0.0,
    }

    if conn is None:
        return result

    try:
        # Gesamtperformance (geschlossene Trades)
        row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END), AVG(pnl_eur) "
            "FROM paper_portfolio WHERE status != 'OPEN' AND pnl_eur IS NOT NULL"
        ).fetchone()
        if row and row[0]:
            total = int(row[0])
            wins = int(row[1]) if row[1] else 0
            result['total_closed_trades'] = total
            result['overall_win_rate'] = wins / total if total > 0 else 0.0
            result['avg_pnl_per_trade'] = float(row[2]) if row[2] else 0.0
    except Exception:
        pass

    try:
        # Strategie-Performance
        rows = conn.execute(
            "SELECT strategy, COUNT(*), "
            "SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END), AVG(pnl_eur) "
            "FROM paper_portfolio WHERE status != 'OPEN' AND strategy IS NOT NULL "
            "GROUP BY strategy"
        ).fetchall()
        strat_perf = {}
        for r in rows:
            strat = r[0]
            n = int(r[1])
            wins = int(r[2]) if r[2] else 0
            avg_pnl = float(r[3]) if r[3] else 0.0
            wr = wins / n if n > 0 else 0.0
            strat_perf[strat] = {'trades': n, 'wins': wins, 'win_rate': wr, 'avg_pnl': avg_pnl}

        result['strategy_performance'] = strat_perf

        # Beste und schlechteste Strategie (min 2 Trades)
        eligible = {k: v for k, v in strat_perf.items() if v['trades'] >= 2}
        if eligible:
            best = max(eligible.items(), key=lambda x: x[1]['win_rate'])
            worst = min(eligible.items(), key=lambda x: x[1]['win_rate'])
            result['best_strategy'] = best[0]
            result['worst_strategy'] = worst[0]
    except Exception:
        pass

    try:
        # Offene Positionen
        count = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchone()
        result['open_positions'] = int(count[0]) if count else 0
    except Exception:
        pass

    try:
        # Win-Rate letzte 7 und 30 Tage
        cutoff_7d = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        cutoff_30d = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        for days, cutoff, key in [(7, cutoff_7d, 'recent_win_rate_7d'),
                                    (30, cutoff_30d, 'recent_win_rate_30d')]:
            row = conn.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) "
                f"FROM paper_portfolio WHERE status != 'OPEN' AND close_date >= '{cutoff}'"
            ).fetchone()
            if row and row[0] and int(row[0]) > 0:
                result[key] = int(row[1] or 0) / int(row[0])
    except Exception:
        pass

    try:
        # Paper-Fund Daten
        fund_rows = conn.execute("SELECT key, value FROM paper_fund").fetchall()
        fund = {r[0]: r[1] for r in fund_rows}
        starting = float(fund.get('starting_capital', 25000))
        cash = float(fund.get('current_cash', 0))
        realized_pnl = float(fund.get('total_realized_pnl', 0))
        result['starting_capital'] = starting
        result['current_cash'] = cash
        result['total_realized_pnl'] = realized_pnl

        # Investiertes Kapital in offenen Positionen
        invested_row = conn.execute(
            "SELECT SUM(entry_price * shares) FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchone()
        invested = float(invested_row[0]) if invested_row and invested_row[0] else 0.0

        # Portfolio-Gesamtwert (Cash + Invested zu Entry-Preisen als Proxy)
        # Korrekte Annäherung: Cash + Invested = gesamtes eingesetztes Kapital
        total_value = cash + invested

        # Drawdown = wie weit sind wir vom Höchststand entfernt?
        # Aus paper_performance holen falls verfügbar
        try:
            pp_row = conn.execute(
                "SELECT max_drawdown, total_value FROM paper_performance ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if pp_row:
                max_dd = pp_row[0]
                if max_dd is not None:
                    result['portfolio_drawdown'] = abs(float(max_dd))
                else:
                    # Fallback: Aktueller Wert vs. Starting Capital
                    pnl_ratio = (total_value - starting) / starting if starting > 0 else 0
                    result['portfolio_drawdown'] = max(0.0, -pnl_ratio)
            else:
                pnl_ratio = (total_value - starting) / starting if starting > 0 else 0
                result['portfolio_drawdown'] = max(0.0, -pnl_ratio)
        except Exception:
            # Letzter Fallback: Nur realisierter P&L
            pnl_ratio = realized_pnl / starting if starting > 0 else 0
            result['portfolio_drawdown'] = max(0.0, -pnl_ratio)

    except Exception:
        pass

    try:
        # Aufeinanderfolgende Verlust-Tage berechnen
        rows = conn.execute(
            "SELECT DATE(close_date) as day, "
            "SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins, "
            "COUNT(*) as total "
            "FROM paper_portfolio WHERE status != 'OPEN' AND close_date IS NOT NULL "
            "GROUP BY day ORDER BY day DESC LIMIT 14"
        ).fetchall()
        consecutive_losses = 0
        for r in rows:
            day_wins = int(r[1] or 0)
            day_total = int(r[2] or 0)
            if day_total > 0 and day_wins == 0:
                consecutive_losses += 1
            else:
                break
        result['consecutive_loss_days'] = consecutive_losses
    except Exception:
        pass

    try:
        # Benchmark-Gap (Albert vs. SPY)
        bench = safe_read_json(WS / 'data/benchmark.json')
        if bench and 'benchmarks' in bench:
            spy_perf = bench['benchmarks'].get('SPY', {}).get('performance_pct', 0)
            paper_perf = bench.get('paper_fund', {}).get('performance_pct', 0)
            result['paper_benchmark_gap'] = paper_perf - spy_perf
    except Exception:
        pass

    # ── Signal Tracker Intelligence ──────────────────────────────────
    try:
        sig_stats = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses,
                   SUM(CASE WHEN outcome='PENDING' THEN 1 ELSE 0 END) as pending
            FROM signals
        """).fetchone()
        if sig_stats and sig_stats['total']:
            resolved = (sig_stats['wins'] or 0) + (sig_stats['losses'] or 0)
            result['signal_tracker'] = {
                'total': sig_stats['total'],
                'wins': sig_stats['wins'] or 0,
                'losses': sig_stats['losses'] or 0,
                'pending': sig_stats['pending'] or 0,
                'accuracy': round((sig_stats['wins'] or 0) / resolved * 100, 1) if resolved > 0 else None,
            }
            # Per-pair accuracy for top pairs
            pair_rows = conn.execute("""
                SELECT pair_id, lead_name, lag_name,
                       COUNT(*) as total,
                       SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses
                FROM signals WHERE outcome IN ('WIN', 'LOSS')
                GROUP BY pair_id ORDER BY total DESC LIMIT 5
            """).fetchall()
            result['signal_tracker']['top_pairs'] = [
                {
                    'pair_id': r['pair_id'],
                    'lead': r['lead_name'],
                    'lag': r['lag_name'],
                    'accuracy': round(r['wins'] / (r['wins'] + r['losses']) * 100, 1) if (r['wins'] + r['losses']) > 0 else 0,
                    'samples': r['total'],
                }
                for r in pair_rows
            ]
    except Exception:
        pass

    return result


# ─── P1.A — Risk-Adjusted Metrics ─────────────────────────────────────────────

def calculate_risk_metrics(conn) -> dict:
    """
    Berechnet Risk-Adjusted Metrics aus paper_portfolio.
    Returns dict mit Gesamt- und Pro-Strategie-Metriken.
    Metriken: Sharpe, Sortino, Calmar, Profit Factor, CRV, Expectancy.
    """
    RISK_FREE_ANNUAL = 0.045  # 4.5% US 10Y Treasury
    TRADING_DAYS = 252

    default = {
        'overall': {
            'sharpe_ratio': 0.0, 'sortino_ratio': 0.0, 'calmar_ratio': 0.0,
            'profit_factor': 0.0, 'crv': 0.0, 'expectancy': 0.0,
            'total_trades': 0,
        },
        'by_strategy': {},
    }

    if conn is None:
        return default

    try:
        rows = conn.execute(
            "SELECT strategy, pnl_eur, entry_price, shares "
            "FROM paper_portfolio WHERE status != 'OPEN' AND pnl_eur IS NOT NULL"
        ).fetchall()
    except Exception:
        return default

    if not rows:
        return default

    def _calc_metrics(trades_pnl: list, trades_invested: list) -> dict:
        """Calculate metrics from list of (pnl, invested_capital) tuples."""
        n = len(trades_pnl)
        if n == 0:
            return {'sharpe_ratio': 0.0, 'sortino_ratio': 0.0, 'calmar_ratio': 0.0,
                    'profit_factor': 0.0, 'crv': 0.0, 'expectancy': 0.0, 'total_trades': 0}

        # Return per trade (as fraction of invested capital)
        returns = []
        for pnl, invested in zip(trades_pnl, trades_invested):
            if invested > 0:
                returns.append(pnl / invested)
            else:
                returns.append(0.0)

        mean_ret = sum(returns) / n if n > 0 else 0.0
        daily_rf = RISK_FREE_ANNUAL / TRADING_DAYS

        # StdDev
        if n > 1:
            variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
            std_dev = math.sqrt(variance) if variance > 0 else 0.001
        else:
            std_dev = 0.001

        # Sharpe Ratio (annualized)
        sharpe = ((mean_ret - daily_rf) / std_dev) * math.sqrt(TRADING_DAYS) if std_dev > 0 else 0.0

        # Downside Deviation (only negative returns)
        neg_returns = [r for r in returns if r < daily_rf]
        if len(neg_returns) > 1:
            dd_var = sum((r - daily_rf) ** 2 for r in neg_returns) / (len(neg_returns) - 1)
            downside_dev = math.sqrt(dd_var) if dd_var > 0 else 0.001
        elif len(neg_returns) == 1:
            downside_dev = abs(neg_returns[0] - daily_rf) if neg_returns[0] != daily_rf else 0.001
        else:
            downside_dev = 0.001

        # Sortino Ratio (annualized)
        sortino = ((mean_ret - daily_rf) / downside_dev) * math.sqrt(TRADING_DAYS)

        # Max Drawdown (cumulative returns)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        # Calmar Ratio
        annualized_return = mean_ret * TRADING_DAYS
        calmar = annualized_return / max_dd if max_dd > 0 else 0.0

        # Profit Factor
        gross_profit = sum(p for p in trades_pnl if p > 0)
        gross_loss = abs(sum(p for p in trades_pnl if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # Win/Loss stats
        wins = [p for p in trades_pnl if p > 0]
        losses = [abs(p) for p in trades_pnl if p <= 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.001
        crv = avg_win / avg_loss if avg_loss > 0 else 0.0

        # Expectancy
        win_rate = len(wins) / n if n > 0 else 0.0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        return {
            'sharpe_ratio': round(sharpe, 3),
            'sortino_ratio': round(sortino, 3),
            'calmar_ratio': round(calmar, 3),
            'profit_factor': round(profit_factor, 3),
            'crv': round(crv, 3),
            'expectancy': round(expectancy, 2),
            'total_trades': n,
        }

    # Group by strategy
    by_strategy = defaultdict(lambda: {'pnl': [], 'invested': []})
    all_pnl = []
    all_invested = []

    for row in rows:
        strat = row[0] or 'unknown'
        pnl = float(row[1])
        entry_price = float(row[2]) if row[2] else 0.0
        shares = float(row[3]) if row[3] else 0.0
        invested = entry_price * shares

        by_strategy[strat]['pnl'].append(pnl)
        by_strategy[strat]['invested'].append(invested)
        all_pnl.append(pnl)
        all_invested.append(invested)

    overall = _calc_metrics(all_pnl, all_invested)

    strat_metrics = {}
    for strat, data in by_strategy.items():
        strat_metrics[strat] = _calc_metrics(data['pnl'], data['invested'])

    return {
        'overall': overall,
        'by_strategy': strat_metrics,
    }


# ─── P1.B — Portfolio Concentration (HHI) ────────────────────────────────────

def calculate_portfolio_concentration(conn, strategies: dict) -> dict:
    """
    Berechnet Sektor-Gewichtung und HHI für offene Positionen.
    Returns: dict mit sector_weights, hhi, warnings, blocked_sectors.
    """
    default = {
        'sector_weights': {},
        'hhi': 0.0,
        'hhi_label': 'N/A',
        'warnings': [],
        'blocked_sectors': [],
        'total_invested': 0.0,
    }

    if conn is None:
        return default

    try:
        rows = conn.execute(
            "SELECT strategy, ticker, entry_price, shares "
            "FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchall()
    except Exception:
        return default

    if not rows:
        return default

    # Map strategy -> sector from strategies.json
    sector_invested = defaultdict(float)
    total_invested = 0.0

    for row in rows:
        strat_id = row[0] or 'unknown'
        ticker = row[1] or 'UNKNOWN'
        # row = (strategy, ticker, entry_price, shares)
        entry_price = float(row[2]) if row[2] else 0.0
        shares = float(row[3]) if row[3] else 0.0
        invested = entry_price * shares

        # Get sector from strategies.json, then normalize via _classify_sector
        strat_data = strategies.get(strat_id, {})
        raw_sector = strat_data.get('sector', '')
        sector = _classify_sector(raw_sector or '', ticker, strat_id)
        if not sector or sector == 'other':
            sector = 'other'

        sector_invested[sector] += invested
        total_invested += invested

    if total_invested <= 0:
        return default

    # Calculate weights
    sector_weights = {}
    for sector, inv in sector_invested.items():
        sector_weights[sector] = round(inv / total_invested, 4)

    # HHI = sum of squared weights
    hhi = sum(w ** 2 for w in sector_weights.values())
    hhi = round(hhi, 4)

    # Classify
    if hhi > 0.50:
        hhi_label = 'DANGEROUS'
    elif hhi > 0.25:
        hhi_label = 'CONCENTRATED'
    else:
        hhi_label = 'DIVERSIFIED'

    # Warnings and blocked sectors
    warnings = []
    blocked_sectors = []

    for sector, weight in sorted(sector_weights.items(), key=lambda x: -x[1]):
        pct = weight * 100
        if weight > 0.50:
            warnings.append(f'⚠️ {sector}: {pct:.0f}% — gefährlich konzentriert! Keine neuen Positionen.')
            blocked_sectors.append(sector)
        elif weight > 0.25:
            warnings.append(f'⚠️ {sector}: {pct:.0f}% — konzentriert. Max 1 neue Position.')

    if hhi > 0.50:
        warnings.insert(0, f'🚨 HHI {hhi:.2f} — Portfolio gefährlich konzentriert!')
    elif hhi > 0.25:
        warnings.insert(0, f'⚠️ HHI {hhi:.2f} — Portfolio konzentriert.')

    return {
        'sector_weights': sector_weights,
        'hhi': hhi,
        'hhi_label': hhi_label,
        'warnings': warnings,
        'blocked_sectors': blocked_sectors,
        'total_invested': round(total_invested, 2),
    }


# ─── P1.C — Kelly Position Sizing ────────────────────────────────────────────

def calculate_kelly_size(strategy_id: str, portfolio_value: float, vix: float,
                         strat_perf: dict, mode: str = 'NORMAL') -> dict:
    """
    Berechnet optimale Positionsgröße nach Half-Kelly Criterion.
    Returns: dict mit kelly_pct, recommended_size_eur, reason.
    """
    MIN_POSITION = 200.0  # €200 minimum (TR fees)
    MAX_PCT_NORMAL = 0.15  # 15% max
    MAX_PCT_DEFENSIVE = 0.10  # 10% max in defensive

    max_pct = MAX_PCT_DEFENSIVE if mode == 'DEFENSIVE' else MAX_PCT_NORMAL

    perf = strat_perf.get(strategy_id, {})
    n_trades = perf.get('trades', 0)
    win_rate = perf.get('win_rate', 0.0)

    # Need minimum trades for Kelly to be meaningful
    if n_trades < 3:
        # Default conservative sizing
        default_size = min(portfolio_value * 0.05, 2000.0)  # 5% or €2000
        default_size = max(default_size, MIN_POSITION)
        return {
            'kelly_pct': 0.0,
            'half_kelly_pct': 0.0,
            'vix_adjusted_pct': 0.0,
            'recommended_size_eur': round(default_size, 0),
            'reason': f'Zu wenige Trades ({n_trades}) — Default 5%',
            'tradeable': True,
        }

    avg_pnl = perf.get('avg_pnl', 0.0)
    # Calculate CRV from the performance data
    # We need avg_win and avg_loss; approximate from available data
    wins = perf.get('wins', 0)
    losses = n_trades - wins

    # If we have win_rate and avg_pnl, we can estimate
    # Better: query DB directly if we have it, but use perf data
    if wins > 0 and losses > 0:
        # avg_pnl = WR * avg_win - (1-WR) * avg_loss
        # We need more data; use a simple CRV estimate
        # From build context: perf has 'avg_pnl' which is overall average
        # Let's compute CRV = 1.5 as fallback if we can't determine
        crv = perf.get('crv', 1.5)
    elif wins > 0:
        crv = 999.0  # All winners
    else:
        crv = 0.0  # All losers

    if crv <= 0:
        return {
            'kelly_pct': 0.0,
            'half_kelly_pct': 0.0,
            'vix_adjusted_pct': 0.0,
            'recommended_size_eur': 0.0,
            'reason': 'CRV ≤ 0 — KEIN TRADE',
            'tradeable': False,
        }

    # Kelly% = (WR × CRV - (1 - WR)) / CRV
    kelly_pct = (win_rate * crv - (1 - win_rate)) / crv

    if kelly_pct <= 0:
        return {
            'kelly_pct': round(kelly_pct, 4),
            'half_kelly_pct': 0.0,
            'vix_adjusted_pct': 0.0,
            'recommended_size_eur': 0.0,
            'reason': f'Kelly {kelly_pct:.1%} negativ — KEIN TRADE (negativer Erwartungswert)',
            'tradeable': False,
        }

    # Half Kelly for safety
    half_kelly = kelly_pct * 0.5

    # VIX adjustment
    if vix < 20:
        vix_mult = 1.0
    elif vix <= 28:
        vix_mult = 0.75
    elif vix <= 35:
        vix_mult = 0.50
    else:
        vix_mult = 0.25

    adjusted_pct = half_kelly * vix_mult

    # Cap at max_pct
    final_pct = min(adjusted_pct, max_pct)

    # Calculate EUR amount
    size_eur = portfolio_value * final_pct

    # Min/Max checks
    if size_eur < MIN_POSITION:
        if portfolio_value * max_pct >= MIN_POSITION:
            size_eur = MIN_POSITION
            reason = f'Kelly-Minimum → €{MIN_POSITION:.0f}'
        else:
            return {
                'kelly_pct': round(kelly_pct, 4),
                'half_kelly_pct': round(half_kelly, 4),
                'vix_adjusted_pct': round(adjusted_pct, 4),
                'recommended_size_eur': 0.0,
                'reason': 'Portfolio zu klein für Min-Position',
                'tradeable': False,
            }
    else:
        reason = f'Half-Kelly {half_kelly:.1%} × VIX-Adj {vix_mult:.2f} = {final_pct:.1%}'

    return {
        'kelly_pct': round(kelly_pct, 4),
        'half_kelly_pct': round(half_kelly, 4),
        'vix_adjusted_pct': round(adjusted_pct, 4),
        'recommended_size_eur': round(size_eur, 0),
        'reason': reason,
        'tradeable': True,
    }


def calculate_all_kelly_sizes(strategies: dict, strat_perf: dict, portfolio_value: float,
                                vix: float, mode: str, conn=None) -> dict:
    """Berechnet Kelly-Sizes für alle aktiven Strategien."""
    result = {
        'method': 'half_kelly',
        'portfolio_value': portfolio_value,
        'vix': vix,
        'mode': mode,
        'default_sizes': {},
    }

    # Enrich strat_perf with CRV from DB if available
    if conn is not None:
        try:
            for strat_id in strat_perf:
                rows = conn.execute(
                    "SELECT pnl_eur FROM paper_portfolio "
                    "WHERE strategy = ? AND status != 'OPEN' AND pnl_eur IS NOT NULL",
                    (strat_id,)
                ).fetchall()
                wins_pnl = [float(r[0]) for r in rows if float(r[0]) > 0]
                losses_pnl = [abs(float(r[0])) for r in rows if float(r[0]) <= 0]
                avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0.0
                avg_loss = sum(losses_pnl) / len(losses_pnl) if losses_pnl else 0.001
                strat_perf[strat_id]['crv'] = avg_win / avg_loss if avg_loss > 0 else 0.0
        except Exception:
            pass

    for strat_id, strat_data in strategies.items():
        if strat_id.startswith('_') or strat_id == 'emerging_themes':
            continue
        if strat_data.get('locked', False):
            continue
        if strat_data.get('status') not in ('active', 'watchlist', 'watching', None):
            continue

        sizing = calculate_kelly_size(strat_id, portfolio_value, vix, strat_perf, mode)
        result['default_sizes'][strat_id] = sizing

    return result


# ─── P4.A — Adaptive VIX Thresholds ──────────────────────────────────────────

VIX_HISTORY_PATH = WS / 'data/vix_history.json'
VIX_HISTORY_MAX = 200


def _load_vix_history() -> list:
    """Loads VIX history from JSON file. Returns list of {'date': str, 'vix': float}."""
    try:
        if VIX_HISTORY_PATH.exists():
            data = json.loads(VIX_HISTORY_PATH.read_text())
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_vix_history(history: list):
    """Saves VIX history, capped at VIX_HISTORY_MAX entries."""
    try:
        VIX_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Keep only last VIX_HISTORY_MAX entries
        trimmed = history[-VIX_HISTORY_MAX:]
        with open(VIX_HISTORY_PATH, 'w') as f:
            json.dump(trimmed, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ VIX-History Schreibfehler: {e}', file=sys.stderr)


def calculate_adaptive_thresholds(conn, current_vix: float = None,
                                   market_data: dict = None) -> dict:
    """Lernt optimale VIX-Schwellen aus historischer Performance.

    Uses VIX history (from vix_history.json and/or DB directives) to calculate
    adaptive defensive/shutdown thresholds instead of fixed 28/40.

    Returns: {
        'vix_defensive_threshold': float,
        'vix_shutdown_threshold': float,
        'vix_30d_avg': float,
        'vix_30d_std': float,
        'current_vix_zscore': float,
        'regime_context': str,  # GEOPOLITICAL_ELEVATED | NORMAL | PANIC
        'adaptive_reason': str,
        'static_defensive': float,  # original fixed threshold for comparison
        'static_shutdown': float,
        'performance_adjusted': bool,
    }"""
    import statistics as _stats

    STATIC_DEFENSIVE = 28.0
    STATIC_SHUTDOWN = 40.0

    default = {
        'vix_defensive_threshold': STATIC_DEFENSIVE,
        'vix_shutdown_threshold': STATIC_SHUTDOWN,
        'vix_30d_avg': 0.0,
        'vix_30d_std': 0.0,
        'current_vix_zscore': 0.0,
        'regime_context': 'NORMAL',
        'adaptive_reason': 'Keine VIX-History — statische Schwellen verwendet',
        'static_defensive': STATIC_DEFENSIVE,
        'static_shutdown': STATIC_SHUTDOWN,
        'performance_adjusted': False,
    }

    # Determine current VIX — aus DB, nie hardcoded
    if current_vix is None:
        if market_data and not market_data.get('vix', {}).get('error'):
            current_vix = market_data['vix'].get('price')
        if current_vix is None:
            # Fallback: aus trading.db holen
            try:
                import sqlite3 as _sq
                _c = _sq.connect('/data/.openclaw/workspace/data/trading.db')
                _row = _c.execute(
                    "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
                ).fetchone()
                _c.close()
                current_vix = _row[0] if _row else None
            except Exception:
                current_vix = None  # None statt hardcoded 25 — lieber kein Trade als falscher VIX

    # ── 1. Collect VIX history ────────────────────────────────────────────
    vix_values = []

    # Source A: vix_history.json
    history = _load_vix_history()
    for entry in history:
        v = entry.get('vix')
        if v is not None and isinstance(v, (int, float)) and v > 0:
            vix_values.append(float(v))

    # Source B: DB regime_history table (has VIX column)
    if len(vix_values) < 10 and conn is not None:
        try:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='regime_history'"
            ).fetchone()
            if tbl:
                rows = conn.execute(
                    "SELECT vix FROM regime_history WHERE vix IS NOT NULL "
                    "ORDER BY date DESC LIMIT 30"
                ).fetchall()
                for r in rows:
                    v = r[0]
                    if v is not None and float(v) > 0:
                        vix_values.append(float(v))
        except Exception:
            pass

    # Source C: trades table (vix_at_entry)
    if len(vix_values) < 10 and conn is not None:
        try:
            rows = conn.execute(
                "SELECT vix_at_entry FROM trades WHERE vix_at_entry IS NOT NULL "
                "ORDER BY entry_date DESC LIMIT 30"
            ).fetchall()
            for r in rows:
                v = r[0]
                if v is not None and float(v) > 0:
                    vix_values.append(float(v))
        except Exception:
            pass

    # Append current VIX to history file (dedup by date)
    today_str = datetime.now().strftime('%Y-%m-%d')
    already_today = any(e.get('date') == today_str for e in history)
    if not already_today and current_vix > 0:
        history.append({'date': today_str, 'vix': round(current_vix, 2)})
        _save_vix_history(history)

    # If still not enough data, use static defaults
    if len(vix_values) < 5:
        default['adaptive_reason'] = f'Nur {len(vix_values)} VIX-Datenpunkte — statische Schwellen (min 5 nötig)'
        return default

    # ── 2. Calculate 30-day VIX statistics ────────────────────────────────
    # Use last 30 values (or all if less)
    recent_vix = vix_values[-30:]
    vix_avg = _stats.mean(recent_vix)
    vix_std = _stats.stdev(recent_vix) if len(recent_vix) >= 2 else 1.0

    # Z-score: how abnormal is current VIX?
    z_score = (current_vix - vix_avg) / vix_std if vix_std > 0 else 0.0

    # ── 3. Adaptive thresholds ────────────────────────────────────────────
    defensive_threshold = max(25.0, vix_avg + 0.5 * vix_std)
    shutdown_threshold = max(35.0, vix_avg + 2.0 * vix_std)

    # Regime context
    if vix_avg > 35:
        regime_context = 'PANIC'
    elif vix_avg > 25:
        regime_context = 'GEOPOLITICAL_ELEVATED'
    else:
        regime_context = 'NORMAL'

    # ── 4. Performance feedback ───────────────────────────────────────────
    performance_adjusted = False
    perf_reason = ''

    if conn is not None:
        try:
            # Group closed trades by VIX range at entry
            # Use regime_at_entry or approximate from trade date
            rows = conn.execute(
                "SELECT pnl_eur, regime_at_entry FROM paper_portfolio "
                "WHERE status != 'OPEN' AND pnl_eur IS NOT NULL"
            ).fetchall()

            # Also try to get VIX at entry from trade dates
            vix_range_trades = {'low': [], 'mid': [], 'high': []}  # <25, 25-32, >32

            # Build date→VIX lookup from history
            date_vix = {}
            for entry in history:
                d = entry.get('date', '')
                v = entry.get('vix')
                if d and v:
                    date_vix[d] = float(v)

            # Get trades with entry dates
            try:
                trade_rows = conn.execute(
                    "SELECT pnl_eur, entry_date FROM paper_portfolio "
                    "WHERE status != 'OPEN' AND pnl_eur IS NOT NULL AND entry_date IS NOT NULL"
                ).fetchall()
                for tr in trade_rows:
                    pnl = float(tr[0])
                    entry_date = (tr[1] or '')[:10]
                    # Find closest VIX
                    entry_vix = date_vix.get(entry_date)
                    if entry_vix is None:
                        # Try nearby dates
                        for delta in range(1, 4):
                            for sign in (-1, 1):
                                try:
                                    d = datetime.strptime(entry_date, '%Y-%m-%d') + timedelta(days=delta * sign)
                                    entry_vix = date_vix.get(d.strftime('%Y-%m-%d'))
                                    if entry_vix:
                                        break
                                except Exception:
                                    continue
                            if entry_vix:
                                break

                    if entry_vix is not None:
                        if entry_vix < 25:
                            vix_range_trades['low'].append(pnl)
                        elif entry_vix <= 32:
                            vix_range_trades['mid'].append(pnl)
                        else:
                            vix_range_trades['high'].append(pnl)
            except Exception:
                pass

            # Evaluate mid-range (VIX 25-32) performance
            mid_trades = vix_range_trades['mid']
            if len(mid_trades) >= 3:
                mid_wins = sum(1 for p in mid_trades if p > 0)
                mid_wr = mid_wins / len(mid_trades)

                if mid_wr > 0.45:
                    # Trades at VIX 25-32 are profitable → raise threshold
                    defensive_threshold = max(defensive_threshold, 32.0)
                    performance_adjusted = True
                    perf_reason = f'VIX 25-32 Trades profitabel (WR {mid_wr:.0%}, n={len(mid_trades)}) → Schwelle hoch'
                elif mid_wr < 0.30:
                    # Trades at VIX 25-32 are unprofitable → keep/lower threshold
                    defensive_threshold = min(defensive_threshold, 28.0)
                    performance_adjusted = True
                    perf_reason = f'VIX 25-32 Trades unprofitabel (WR {mid_wr:.0%}, n={len(mid_trades)}) → Schwelle konservativ'
        except Exception:
            pass

    # Ensure shutdown > defensive + buffer
    shutdown_threshold = max(shutdown_threshold, defensive_threshold + 5.0)

    # Build reason string
    reason_parts = [f'VIX 30d Ø{vix_avg:.1f} ±{vix_std:.1f}']
    reason_parts.append(f'Z-Score: {z_score:+.2f}')
    reason_parts.append(f'Regime: {regime_context}')
    if performance_adjusted:
        reason_parts.append(perf_reason)

    return {
        'vix_defensive_threshold': round(defensive_threshold, 1),
        'vix_shutdown_threshold': round(shutdown_threshold, 1),
        'vix_30d_avg': round(vix_avg, 2),
        'vix_30d_std': round(vix_std, 2),
        'current_vix_zscore': round(z_score, 2),
        'regime_context': regime_context,
        'adaptive_reason': ' | '.join(reason_parts),
        'static_defensive': STATIC_DEFENSIVE,
        'static_shutdown': STATIC_SHUTDOWN,
        'performance_adjusted': performance_adjusted,
    }


# ─── P4.B — Multi-Timeframe Integration ──────────────────────────────────────

def analyze_multi_timeframe(market_data: dict = None) -> dict:
    """Analysiert mehrere Timeframes für SPY und Sektor-ETFs.

    Uses existing MA data (MA50, MA200, price) to approximate:
    - Daily signal: Price vs MA50
    - Weekly signal: MA50 vs MA200 (Golden/Death Cross proxy)
    - Monthly signal: Price vs MA200 ±5%

    Returns: {
        'spy': {
            'daily': 'BULL'|'BEAR'|'NEUTRAL',
            'weekly': 'BULL'|'BEAR'|'NEUTRAL',
            'monthly': 'BULL'|'BEAR'|'NEUTRAL',
            'alignment': 'ALIGNED_BULL'|'ALIGNED_BEAR'|'MIXED',
            'interpretation': str,
        },
        'sectors': { 'energy': { ... }, ... },
        'trading_bias': 'LONG_ONLY'|'CAUTIOUS_LONG'|'NEUTRAL'|'CAUTIOUS_SHORT',
        'confidence': float (0-1),
    }"""

    default_tf = {
        'daily': 'NEUTRAL', 'weekly': 'NEUTRAL', 'monthly': 'NEUTRAL',
        'alignment': 'MIXED', 'interpretation': 'Keine Daten verfügbar.',
    }
    default = {
        'spy': dict(default_tf),
        'sectors': {},
        'trading_bias': 'NEUTRAL',
        'confidence': 0.0,
    }

    if not market_data or not isinstance(market_data, dict):
        return default

    def _analyze_ticker(ticker_data: dict, label: str = '') -> dict:
        """Analyze a single ticker's timeframe signals."""
        result = {
            'daily': 'NEUTRAL', 'weekly': 'NEUTRAL', 'monthly': 'NEUTRAL',
            'alignment': 'MIXED', 'interpretation': '',
        }

        if not ticker_data or ticker_data.get('error'):
            result['interpretation'] = f'{label}: Keine Daten.'
            return result

        price = ticker_data.get('price', 0)
        ma50 = ticker_data.get('ma50')
        ma200 = ticker_data.get('ma200')

        if not price or price <= 0:
            result['interpretation'] = f'{label}: Kein Preis verfügbar.'
            return result

        # ── Daily Signal: Price vs MA50 ───────────────────────────────
        if ma50 and ma50 > 0:
            pct_from_ma50 = (price - ma50) / ma50
            if pct_from_ma50 > 0.01:
                result['daily'] = 'BULL'
            elif pct_from_ma50 < -0.01:
                result['daily'] = 'BEAR'
            else:
                result['daily'] = 'NEUTRAL'
        # If no MA50, leave as NEUTRAL

        # ── Weekly Signal: MA50 vs MA200 (Golden/Death Cross proxy) ───
        if ma50 and ma200 and ma200 > 0:
            ma_ratio = (ma50 - ma200) / ma200
            if ma_ratio > 0.02:
                result['weekly'] = 'BULL'
            elif ma_ratio < -0.02:
                result['weekly'] = 'BEAR'
            else:
                result['weekly'] = 'NEUTRAL'

        # ── Monthly Signal: Price vs MA200 ±3% ───────────────────────
        if ma200 and ma200 > 0:
            pct_from_ma200 = (price - ma200) / ma200
            if pct_from_ma200 > 0.03:
                result['monthly'] = 'BULL'
            elif pct_from_ma200 < -0.03:
                result['monthly'] = 'BEAR'
            else:
                result['monthly'] = 'NEUTRAL'

        # ── Alignment ─────────────────────────────────────────────────
        signals = [result['daily'], result['weekly'], result['monthly']]
        if all(s == 'BULL' for s in signals):
            result['alignment'] = 'ALIGNED_BULL'
        elif all(s == 'BEAR' for s in signals):
            result['alignment'] = 'ALIGNED_BEAR'
        else:
            result['alignment'] = 'MIXED'

        # ── Interpretation ────────────────────────────────────────────
        d, w, m = result['daily'], result['weekly'], result['monthly']
        name = label or 'Ticker'

        if result['alignment'] == 'ALIGNED_BULL':
            result['interpretation'] = f'{name}: Aligned BULL → Volle Kraft voraus. Alle Timeframes bestätigen Aufwärtstrend.'
        elif result['alignment'] == 'ALIGNED_BEAR':
            result['interpretation'] = f'{name}: Aligned BEAR → Alle Timeframes bearish. Nur Hedging-Positionen.'
        elif d == 'BULL' and w == 'BEAR':
            result['interpretation'] = f'{name}: Daily BULL in Weekly BEAR → Bear Market Rally. Nur schnelle Trades, kein Buy & Hold.'
        elif d == 'BEAR' and w == 'BULL':
            result['interpretation'] = f'{name}: Daily BEAR in Weekly BULL → Pullback im Aufwärtstrend. Kaufgelegenheit bei Support.'
        elif d == 'BULL' and m == 'BEAR':
            result['interpretation'] = f'{name}: Daily BULL aber Monthly BEAR → Kurzfristiges Rally, übergeordnet bärisch. Vorsicht.'
        elif d == 'BEAR' and m == 'BULL':
            result['interpretation'] = f'{name}: Daily BEAR in Monthly BULL → Kurzfristige Schwäche im Langfrist-Aufwärtstrend.'
        else:
            result['interpretation'] = f'{name}: Mixed Signals (D:{d} W:{w} M:{m}) → Abwarten oder reduzierte Positionsgrößen.'

        return result

    # ── SPY Analysis ──────────────────────────────────────────────────────
    spy_data = market_data.get('spy', {})
    spy_result = _analyze_ticker(spy_data, 'SPY')

    # ── Sector Analysis ───────────────────────────────────────────────────
    sector_results = {}
    sector_map = {
        'xle': 'energy', 'xlk': 'tech', 'xlf': 'financials',
        'xli': 'industrials', 'xlb': 'materials', 'xlv': 'healthcare',
    }
    for etf_key, sector_name in sector_map.items():
        etf_data = market_data.get(etf_key, {})
        sector_results[sector_name] = _analyze_ticker(etf_data, sector_name.title())

    # ── Trading Bias ──────────────────────────────────────────────────────
    spy_align = spy_result['alignment']
    spy_daily = spy_result['daily']
    spy_weekly = spy_result['weekly']

    if spy_align == 'ALIGNED_BULL':
        trading_bias = 'LONG_ONLY'
    elif spy_align == 'ALIGNED_BEAR':
        trading_bias = 'NEUTRAL'  # We don't short
    elif spy_daily == 'BULL' and spy_weekly == 'BEAR':
        trading_bias = 'CAUTIOUS_LONG'
    elif spy_daily == 'BEAR' and spy_weekly == 'BULL':
        trading_bias = 'CAUTIOUS_LONG'
    elif spy_daily == 'BULL':
        trading_bias = 'CAUTIOUS_LONG'
    else:
        trading_bias = 'NEUTRAL'

    # ── Confidence ────────────────────────────────────────────────────────
    # Based on alignment strength across SPY and sectors
    aligned_count = 0
    total_count = 0
    all_results = [spy_result] + list(sector_results.values())
    for r in all_results:
        if r['alignment'] in ('ALIGNED_BULL', 'ALIGNED_BEAR'):
            aligned_count += 1
        total_count += 1

    confidence = aligned_count / total_count if total_count > 0 else 0.0

    # Boost confidence if SPY is aligned
    if spy_align in ('ALIGNED_BULL', 'ALIGNED_BEAR'):
        confidence = min(1.0, confidence + 0.2)

    return {
        'spy': spy_result,
        'sectors': sector_results,
        'trading_bias': trading_bias,
        'confidence': round(confidence, 2),
    }


# ─── Trading-Mode Entscheidung ────────────────────────────────────────────────

def determine_trading_mode(vix: float, geo_score: float, win_rate_7d: float,
                            drawdown: float, consecutive_loss_days: int,
                            risk_metrics: dict = None,
                            regime_detail: dict = None,
                            anomaly_result: dict = None,
                            adaptive_thresholds: dict = None,
                            multi_timeframe: dict = None) -> tuple[str, str]:
    """
    Bestimmt den Trading-Modus basierend auf Marktbedingungen.
    V3.0: Nutzt adaptive VIX-Schwellen + Multi-Timeframe + Sharpe + Enhanced Regime.

    Returns: (mode, reason)
    mode: AGGRESSIVE | NORMAL | DEFENSIVE | SHUTDOWN
    """
    reasons = []

    # P4.A: Use adaptive thresholds if available, otherwise static
    if adaptive_thresholds:
        vix_shutdown = adaptive_thresholds.get('vix_shutdown_threshold', 40.0)
        vix_defensive = adaptive_thresholds.get('vix_defensive_threshold', 28.0)
    else:
        vix_shutdown = 40.0
        vix_defensive = 28.0

    # SHUTDOWN: VIX > shutdown_threshold ODER Drawdown > 20% ODER 3+ Verlust-Tage in Folge
    if vix > vix_shutdown:
        reasons.append(f'VIX {vix:.1f} > {vix_shutdown:.0f} (adaptive SHUTDOWN)')
    if drawdown > 0.20:
        reasons.append(f'Drawdown {drawdown:.1%} > 20%')
    if consecutive_loss_days >= 3:
        reasons.append(f'{consecutive_loss_days} Verlust-Tage in Folge')

    # P1.A SHUTDOWN-Trigger: Sharpe < -1.0 ODER Expectancy < 0 über 30+ Trades
    if risk_metrics:
        overall = risk_metrics.get('overall', {})
        sharpe = overall.get('sharpe_ratio', 0.0)
        expectancy = overall.get('expectancy', 0.0)
        total_trades = overall.get('total_trades', 0)

        if total_trades >= 30:
            if sharpe < -1.0:
                reasons.append(f'Sharpe {sharpe:.2f} < -1.0 (30+ Trades)')
            if expectancy < 0:
                reasons.append(f'Expectancy €{expectancy:.2f} < 0 (30+ Trades)')

    # P2.B: Enhanced regime triggers
    if regime_detail:
        overall_regime = regime_detail.get('overall', '')
        if overall_regime == 'CRASH':
            reasons.append(f'Regime: CRASH')
        spy_vs = regime_detail.get('spy_vs_ma200', 0)
        if spy_vs < -20:
            reasons.append(f'SPY {spy_vs:.1f}% unter MA200')

    # P3.C: ≥3 HIGH anomalies → SHUTDOWN
    if anomaly_result:
        high_count = anomaly_result.get('high_count', 0)
        if high_count >= 3:
            reasons.append(f'{high_count} HIGH Anomalien')

    if reasons:
        return 'SHUTDOWN', ' + '.join(reasons)

    # DEFENSIVE: VIX > adaptive threshold ODER Geopolitik HIGH ODER Win-Rate < 25%
    def_reasons = []
    if vix > vix_defensive:
        def_reasons.append(f'VIX {vix:.1f} > {vix_defensive:.0f} (adaptive DEFENSIVE)')
    if geo_score > 50:
        def_reasons.append(f'Geo-Score {geo_score:.0f} > 50')
    if win_rate_7d < 0.25:
        def_reasons.append(f'WR 7d {win_rate_7d:.0%} < 25%')

    # P1.A: Low Sharpe → DEFENSIVE
    if risk_metrics:
        overall = risk_metrics.get('overall', {})
        sharpe = overall.get('sharpe_ratio', 0.0)
        total_trades = overall.get('total_trades', 0)
        if total_trades >= 15 and sharpe < -0.5:
            def_reasons.append(f'Sharpe {sharpe:.2f} < -0.5')

    # P2.B: Enhanced regime → DEFENSIVE
    if regime_detail:
        overall_regime = regime_detail.get('overall', '')
        if overall_regime in ('BEAR_TREND', 'CORRECTION'):
            def_reasons.append(f'Regime: {overall_regime}')

    # P3.C: ≥2 HIGH anomalies → mindestens DEFENSIVE
    if anomaly_result:
        high_count = anomaly_result.get('high_count', 0)
        if high_count >= 2:
            def_reasons.append(f'{high_count} HIGH Anomalien')

    # P4.B: ALIGNED_BEAR → mindestens DEFENSIVE
    if multi_timeframe:
        spy_tf = multi_timeframe.get('spy', {})
        if spy_tf.get('alignment') == 'ALIGNED_BEAR':
            def_reasons.append('Multi-TF: SPY ALIGNED_BEAR')

    if def_reasons:
        return 'DEFENSIVE', ' + '.join(def_reasons)

    # AGGRESSIVE: VIX < 20 UND Win-Rate > 50% letzte 7d UND Sharpe > 0.5
    sharpe_ok = True
    if risk_metrics:
        overall = risk_metrics.get('overall', {})
        sharpe = overall.get('sharpe_ratio', 0.0)
        if overall.get('total_trades', 0) >= 10 and sharpe < 0.5:
            sharpe_ok = False

    if vix < 20 and win_rate_7d > 0.50 and sharpe_ok:
        return 'AGGRESSIVE', 'Niedrige Volatilität, starke Performance'

    # NORMAL: alles andere
    return 'NORMAL', 'Standardbetrieb'


# ─── Trading-Rules je Modus ───────────────────────────────────────────────────

def build_trading_rules(mode: str, vix: float, strat_perf: dict, strategies: dict,
                        concentration: dict = None, multi_timeframe: dict = None,
                        regime_detail: dict = None) -> dict:
    """Baut die konkreten Handelsregeln basierend auf Modus und Performance."""

    # Basis-Regeln nach Modus
    mode_configs = {
        'SHUTDOWN': {
            'max_new_positions_today': 0,
            'max_position_size_eur': 0,
            'stop_tightening_factor': 1.5,
            'vix_conviction_adjustment': -3,
        },
        'DEFENSIVE': {
            'max_new_positions_today': 2,
            'max_position_size_eur': 1500,
            'stop_tightening_factor': 1.3,
            'vix_conviction_adjustment': -2,
        },
        'NORMAL': {
            'max_new_positions_today': 4,
            'max_position_size_eur': 2000,
            'stop_tightening_factor': 1.0,
            'vix_conviction_adjustment': 0,
        },
        'AGGRESSIVE': {
            'max_new_positions_today': 6,
            'max_position_size_eur': 2500,
            'stop_tightening_factor': 0.9,
            'vix_conviction_adjustment': +1,
        },
    }

    rules = mode_configs.get(mode, mode_configs['NORMAL']).copy()

    # Strategien nach Performance klassifizieren
    # Locked/gesperrte Strategien
    blocked = []
    allowed = []

    # Sektoren die bei DEFENSIVE/SHUTDOWN geblockt werden
    risky_sectors = {'technology', 'day_trade'}
    safe_sectors = {'energy', 'metals', 'fertilizer', 'materials'}

    for strat_id, strat_data in strategies.items():
        if strat_id.startswith('_') or strat_id == 'emerging_themes':
            continue

        # Explizit gesperrt?
        if strat_data.get('locked', False):
            blocked.append(strat_id)
            continue

        # Typ = day_trade? Im Defensive/SHUTDOWN immer blockieren
        strat_type = strat_data.get('type', '')
        if strat_type == 'day_trade' and mode in ('DEFENSIVE', 'SHUTDOWN'):
            blocked.append(strat_id)
            continue

        # Sektor prüfen
        sector = strat_data.get('sector', '')
        health = strat_data.get('health', 'yellow')

        if mode == 'SHUTDOWN':
            blocked.append(strat_id)
        elif mode == 'DEFENSIVE':
            if sector in risky_sectors or health == 'red':
                blocked.append(strat_id)
            else:
                allowed.append(strat_id)
        else:
            if health != 'red':
                allowed.append(strat_id)
            else:
                blocked.append(strat_id)

    # Performance-basiertes Blockieren (VERSCHÄRFT für Sharpe-Optimierung)
    for strat_id, perf in strat_perf.items():
        should_block = False
        block_reason = ''

        # Gate 1: 0% WR nach 3+ Trades → sofort tot
        if perf['trades'] >= 3 and perf['win_rate'] == 0.0:
            should_block = True
            block_reason = f'0% WR nach {perf["trades"]} Trades'

        # Gate 2: Negativer Erwartungswert nach 3+ Trades → tot
        # Expectancy = WR × Avg_Win - (1-WR) × Avg_Loss
        if perf['trades'] >= 3 and not should_block:
            avg_win = perf.get('avg_win', 0) or 0
            avg_loss = abs(perf.get('avg_loss', 0) or 0)
            wr = perf['win_rate']
            expectancy = (wr * avg_win) - ((1 - wr) * avg_loss)
            if expectancy < 0:
                should_block = True
                block_reason = f'Neg. Expectancy €{expectancy:.1f}/Trade nach {perf["trades"]} Trades'

        # Gate 3: CRV < 0.5 nach 5+ Trades → zu schlechtes Risikoprofil
        if perf['trades'] >= 5 and not should_block:
            avg_win = abs(perf.get('avg_win', 0) or 0)
            avg_loss = abs(perf.get('avg_loss', 0) or 0)
            crv = avg_win / avg_loss if avg_loss > 0 else 999
            if crv < 0.5:
                should_block = True
                block_reason = f'CRV {crv:.2f} < 0.5 nach {perf["trades"]} Trades'

        # Gate 4: Mehr als €500 Verlust und WR < 40% → Kapitalschutz
        if perf['trades'] >= 3 and not should_block:
            total_pnl = perf.get('avg_pnl', 0) * perf['trades']
            if total_pnl < -500 and perf['win_rate'] < 0.40:
                should_block = True
                block_reason = f'€{total_pnl:.0f} Verlust + WR {perf["win_rate"]:.0%}'

        if should_block:
            if strat_id not in blocked:
                blocked.append(strat_id)
            if strat_id in allowed:
                allowed.remove(strat_id)

    # P1.B: Block strategies in over-concentrated sectors
    if concentration:
        blocked_sectors = concentration.get('blocked_sectors', [])
        if blocked_sectors:
            for strat_id, strat_data in strategies.items():
                if strat_id.startswith('_') or strat_id == 'emerging_themes':
                    continue
                sector = strat_data.get('sector', '')
                if sector in blocked_sectors:
                    if strat_id not in blocked:
                        blocked.append(strat_id)
                    if strat_id in allowed:
                        allowed.remove(strat_id)

    rules['allowed_strategies'] = sorted(set(allowed))
    rules['blocked_strategies'] = sorted(set(blocked))

    # ── Regime-Filter: Strategien in BEAR-Sektoren blockieren ──────────
    sector_regimes = (regime_detail or {}).get('sectors', {})
    regime_blocked = []
    
    # Mapping: Strategy sector → Market sector
    sector_aliases = {
        'tech': ['tech', 'technology'],
        'financials': ['financials'],
        'energy': ['energy'],
        'materials': ['materials'],
        'industrials': ['industrials'],
        'healthcare': ['healthcare'],
    }
    
    if mode in ('DEFENSIVE', 'SHUTDOWN'):
        for strat_id in list(allowed):
            strat_data = strategies.get(strat_id, {})
            strat_sector = strat_data.get('sector', '')
            
            # Finde das Markt-Regime für diesen Sektor
            market_regime = None
            for market_sec, aliases in sector_aliases.items():
                if strat_sector in aliases or strat_sector == market_sec:
                    market_regime = sector_regimes.get(market_sec, '')
                    break
            
            # BEAR-Sektor + DEFENSIVE mode → blockieren (Paper Lab darf trotzdem)
            if market_regime and 'BEAR' in market_regime and mode == 'DEFENSIVE':
                regime_blocked.append(strat_id)
            # Jedes Regime außer BULL im SHUTDOWN → blockieren
            elif mode == 'SHUTDOWN' and market_regime and 'BULL' not in market_regime:
                regime_blocked.append(strat_id)
    
    for strat_id in regime_blocked:
        if strat_id not in blocked:
            blocked.append(strat_id)
        if strat_id in allowed:
            allowed.remove(strat_id)
    
    if regime_blocked:
        rules['regime_blocked'] = sorted(regime_blocked)

    # ── DNA Auto-Apply: Stop/TP-Empfehlungen in Regeln übernehmen ─────
    dna_data = safe_read_json(WS / 'data/strategy_dna.json', {})
    dna_overrides = {}
    for strat_id, evo in dna_data.get('evolutions', {}).items():
        rec = evo.get('recommended_params', {})
        recommendation = evo.get('recommendation', '')
        confidence = evo.get('confidence', 'LOW')
        trades = evo.get('trades_analyzed', 0)

        # KILL-Empfehlung → blockieren
        if recommendation == 'KILL' and strat_id not in blocked:
            blocked.append(strat_id)
            if strat_id in allowed:
                allowed.remove(strat_id)

        # Nur anwenden wenn: mindestens 5 Trades UND Confidence nicht LOW
        if trades < 5 or confidence == 'LOW':
            continue

        override = {}
        opt_stop = rec.get('optimal_stop_pct')
        opt_tp = rec.get('optimal_tp_pct')
        opt_hold = rec.get('optimal_holding_range')

        if opt_stop and opt_stop > 0:
            override['stop_pct'] = round(opt_stop, 1)
        if opt_tp and opt_tp > 0:
            override['tp_pct'] = round(opt_tp, 1)
        if opt_hold:
            override['holding_range'] = opt_hold

        if override:
            dna_overrides[strat_id] = override

    if dna_overrides:
        rules['dna_overrides'] = dna_overrides

    rules['allowed_strategies'] = sorted(set(allowed))
    rules['blocked_strategies'] = sorted(set(blocked))

    # P4.B: Multi-Timeframe → max_holding_days for CAUTIOUS_LONG
    if multi_timeframe:
        trading_bias = multi_timeframe.get('trading_bias', 'NEUTRAL')
        if trading_bias == 'CAUTIOUS_LONG':
            rules['max_holding_days'] = 10
            rules['mtf_note'] = 'CAUTIOUS_LONG: Nur schnelle Trades, keine Langfrist-Positionen'
        elif trading_bias == 'NEUTRAL':
            rules['max_holding_days'] = 15
            rules['mtf_note'] = 'MTF NEUTRAL: Reduzierte Haltedauer'
        elif trading_bias == 'LONG_ONLY':
            rules['mtf_note'] = 'MTF LONG_ONLY: Alle Timeframes bullish — volle Freiheit'

    return rules


# ─── System-Health berechnen ──────────────────────────────────────────────────

def calculate_system_health(hist: dict, sources: dict) -> dict:
    """
    Berechnet den System-Health-Score (0–100).
    100 = alles perfekt, 0 = System komplett kaputt.
    """
    score = 100
    errors = []
    warnings = []

    # Trade Journal Qualität
    journal_entries = 0
    db = get_db()
    if db:
        try:
            row = db.execute("SELECT COUNT(*) FROM trade_journal").fetchone()
            journal_entries = int(row[0]) if row else 0
            db.close()
        except Exception:
            pass

    if journal_entries < 5:
        score -= 15
        warnings.append(f'P1.3 Trade Journal: nur {journal_entries} Einträge — mehr Daten nötig')
    elif journal_entries < 20:
        score -= 5
        warnings.append(f'Trade Journal: {journal_entries} Einträge (Ziel: 30+ für statistische Signifikanz)')

    # Datenbasis zu klein
    if hist['total_closed_trades'] < 20:
        score -= 10
        warnings.append(f'Nur {hist["total_closed_trades"]} geschlossene Trades — zu wenig für valide Aussagen')

    # Win-Rate sehr niedrig
    if hist['overall_win_rate'] < 0.30:
        score -= 20
        warnings.append(f'Win-Rate {hist["overall_win_rate"]:.0%} — unter 30% (Ziel: >45%)')
    elif hist['overall_win_rate'] < 0.40:
        score -= 10
        warnings.append(f'Win-Rate {hist["overall_win_rate"]:.0%} — verbesserungswürdig')

    # Drawdown
    if hist['portfolio_drawdown'] > 0.15:
        score -= 25
        errors.append(f'Drawdown {hist["portfolio_drawdown"]:.1%} — kritisch! Limit 20%')
    elif hist['portfolio_drawdown'] > 0.10:
        score -= 15
        warnings.append(f'Drawdown {hist["portfolio_drawdown"]:.1%} — erhöht')

    # Aufeinanderfolgende Verlust-Tage
    if hist['consecutive_loss_days'] >= 3:
        score -= 20
        errors.append(f'{hist["consecutive_loss_days"]} aufeinanderfolgende Verlust-Tage — SHUTDOWN-Trigger!')
    elif hist['consecutive_loss_days'] == 2:
        score -= 10
        warnings.append(f'{hist["consecutive_loss_days"]} Verlust-Tage in Folge — beobachten')

    # Datenquellen verfügbar?
    if not sources.get('regime'):
        score -= 5
        warnings.append('market-regime.json nicht verfügbar')

    if not sources.get('strategies'):
        score -= 10
        errors.append('strategies.json nicht verfügbar!')

    # P1.x Features Status
    p1_features = []
    lernplan = sources.get('accuracy', '') + sources.get('state_snapshot', '')
    if 'P1.1' in lernplan or 'dedup' in lernplan.lower():
        p1_features.append('P1.1')
    if 'P1.2' in lernplan or 'VIX' in lernplan:
        p1_features.append('P1.2')
    if 'P1.3' in lernplan or 'trade_journal' in lernplan.lower():
        p1_features.append('P1.3')
    if 'P1.4' in lernplan or 'magnitude' in lernplan.lower():
        p1_features.append('P1.4')

    score = max(0, min(100, score))

    return {
        'score': score,
        'errors': errors,
        'warnings': warnings,
        'journal_entries': journal_entries,
        'p1_features_active': len(p1_features) >= 3,
        'p1_features_list': p1_features,
    }


# ─── Geopolitik-Score (Legacy) ────────────────────────────────────────────────

def estimate_geo_score(regime, strategies: dict) -> float:
    """Legacy wrapper — benutzt calculate_geo_intel() intern."""
    # Kept for backward compatibility; build_directive uses calculate_geo_intel directly
    score = 0
    if isinstance(regime, str):
        regime_type = regime
    elif isinstance(regime, dict):
        regime_type = regime.get('regime', 'NORMAL')
    else:
        regime_type = 'NORMAL'
    if 'DOWN' in regime_type or 'CRASH' in regime_type:
        score += 30
    elif 'RANGE' in regime_type:
        score += 15
    geo_strategies = ['S1', 'S9', 'PS1', 'PS2']
    for s in geo_strategies:
        if s in strategies and strategies[s].get('status') == 'active':
            score += 10
    s1 = strategies.get('S1', {})
    if s1.get('health') in ('green_hot', 'green'):
        score += 20
    return min(100, score)


# ─── P2.C — Erweiterte Geo-Intel-Integration ─────────────────────────────────

def calculate_geo_intel(sources: dict, conn) -> dict:
    """
    Berechnet Geo-Score aus ECHTEN Datenquellen.
    Returns: {
        'geo_score': int (0-100),
        'geo_trend': 'ESCALATING'|'STABLE'|'DEESCALATING'|'CRITICAL',
        'geo_hotspots': ['Iran/Hormuz', ...],
        'geo_trades_affected': ['EQNR', 'OXY', ...],
        'trump_signal': 'PEACE'|'ESCALATION'|'NEUTRAL',
        'pifs_alert': bool,
        'detail': { ... }
    }
    """
    score = 0
    hotspots = []
    trades_affected = set()
    trump_signal = 'NEUTRAL'
    pifs_alert = False
    detail = {
        'overnight_events_score': 0,
        'trump_watch_score': 0,
        'pifs_score': 0,
        'strategy_score': 0,
        'events_24h': 0,
    }

    # ── 1. Overnight Events DB ────────────────────────────────────────────
    try:
        if conn is not None:
            # Check if table exists
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='overnight_events'"
            ).fetchone()
            if tbl:
                rows = conn.execute(
                    "SELECT headline, magnitude, strategies_affected, impact_direction "
                    "FROM overnight_events WHERE timestamp > datetime('now', '-24 hours')"
                ).fetchall()
                detail['events_24h'] = len(rows)
                if len(rows) > 100:
                    detail['dedup_warning'] = True
                    print(f'⚠️ Geo-Intel: {len(rows)} Events in 24h — mögliche Duplikate! dedup_warning=true', file=sys.stderr)
                events_score = 0
                for row in rows:
                    headline = (row[0] or '').lower()
                    mag = int(row[1] or 0)
                    strats = row[2] or '[]'
                    direction = (row[3] or '').lower()

                    # Magnitude scoring: 1=+5, 2=+10, 3=+20
                    if mag >= 3:
                        events_score += 20
                    elif mag >= 2:
                        events_score += 10
                    elif mag >= 1:
                        events_score += 5

                    # Hotspot detection from headlines
                    if any(k in headline for k in ('iran', 'hormuz', 'tehran', 'persian gulf')):
                        if 'Iran/Hormuz' not in hotspots:
                            hotspots.append('Iran/Hormuz')
                    if any(k in headline for k in ('ukraine', 'kyiv', 'russia', 'moscow', 'donbas')):
                        if 'Ukraine/Russia' not in hotspots:
                            hotspots.append('Ukraine/Russia')
                    if any(k in headline for k in ('taiwan', 'china', 'beijing', 'strait')):
                        if 'Taiwan Strait' not in hotspots:
                            hotspots.append('Taiwan Strait')

                    # Extract affected tickers from strategies
                    try:
                        affected = json.loads(strats) if isinstance(strats, str) else strats
                        if isinstance(affected, list):
                            for s in affected:
                                if 'S1' in str(s) or 'oil' in str(s).lower():
                                    trades_affected.update(['EQNR', 'OXY'])
                                if 'LHA' in str(s) or 'airline' in str(s).lower():
                                    trades_affected.add('LHA')
                    except Exception:
                        pass

                # Cap events score contribution
                events_score = min(events_score, 40)
                detail['overnight_events_score'] = events_score
                score += events_score
    except Exception:
        pass

    # ── 2. Trump Watch State ──────────────────────────────────────────────
    try:
        trump_state = safe_read_json(WS / 'data/trump_watch_state.json')
        if trump_state:
            alert_count = trump_state.get('alert_count', 0)
            last_check_str = trump_state.get('last_check', '')

            # Check if alerts are recent (< 24h)
            alerts_recent = False
            if last_check_str:
                try:
                    # Handle timezone-aware ISO strings
                    lc = last_check_str.replace('+00:00', '').replace('Z', '')
                    last_check = datetime.fromisoformat(lc)
                    if (datetime.now() - last_check).total_seconds() < 86400:
                        alerts_recent = True
                except Exception:
                    alerts_recent = True  # Assume recent if we can't parse

            if alert_count > 0 and alerts_recent:
                score += 15
                detail['trump_watch_score'] = 15

        # Read trump-watch-log.md (last 500 bytes) for signals
        trump_log_path = WS / 'memory/trump-watch-log.md'
        if trump_log_path.exists():
            try:
                with open(trump_log_path, 'rb') as f:
                    f.seek(0, 2)  # End of file
                    size = f.tell()
                    f.seek(max(0, size - 500))
                    tail = f.read().decode('utf-8', errors='ignore')

                peace_count = tail.count('PEACE_SIGNAL')
                esc_count = tail.count('ESCALATION_SIGNAL') + tail.count('ESCALATION_WATCH')

                if peace_count > esc_count:
                    trump_signal = 'PEACE'
                elif esc_count > peace_count:
                    trump_signal = 'ESCALATION'
                    score += 10  # Escalation adds to geo score
                    detail['trump_watch_score'] += 10
                # PEACE signal doesn't add to score (de-escalation handled via PIFS)
            except Exception:
                pass
    except Exception:
        pass

    # ── 3. PIFS Flow Scanner ─────────────────────────────────────────────
    try:
        flow_data = safe_read_json(WS / 'memory/flow-scanner-data.json')
        if flow_data:
            sectors = flow_data.get('sectors', {})

            # Iran Peace Cross Signal
            iran_peace = sectors.get('iran_peace_basket', {})
            iran_inverse = sectors.get('iran_peace_inverse', {})
            # Cross signal: peace basket bullish AND inverse bearish (or strong peace activity)
            if (iran_peace.get('direction') == 'BULLISH' or
                    iran_peace.get('signal_count', 0) > 3):
                score -= 20  # De-escalation!
                pifs_alert = True
                detail['pifs_score'] = -20

            # Energy sector signals
            energy = sectors.get('energy', {})
            energy_dir = energy.get('direction', 'NEUTRAL')
            if energy_dir in ('BULLISH', 'BULLISH_STRONG'):
                score += 15
                detail['pifs_score'] += 15
                trades_affected.update(['EQNR', 'OXY'])

            # Congressional tickers — check for oil/defense
            congressional = flow_data.get('congressional_tickers', [])
            oil_defense_tickers = {'XOM', 'OXY', 'CVX', 'EQNR', 'COP', 'SLB',
                                   'LMT', 'RTX', 'NOC', 'GD', 'BA', 'HII',
                                   'RHM', 'HAG', 'SAAB'}
            # Also check for state abbreviations that might indicate defense spending
            if isinstance(congressional, list):
                cong_set = set(str(t).upper() for t in congressional)
                if cong_set & oil_defense_tickers:
                    score += 10
                    detail['pifs_score'] += 10
    except Exception:
        pass

    # ── 4. Aktive Strategien ──────────────────────────────────────────────
    try:
        strategies = sources.get('strategies', {})
        geo_relevant = ['S1', 'S9', 'PS1', 'PS_LHA']
        strat_score = 0
        for sid in geo_relevant:
            strat = strategies.get(sid, {})
            if strat.get('status') in ('active', 'watchlist', 'watching'):
                strat_score += 5
                # Add associated tickers to affected list
                for t in strat.get('tickers', []):
                    trades_affected.add(t)
        detail['strategy_score'] = strat_score
        score += strat_score
    except Exception:
        pass

    # ── Score clamping + Trend ────────────────────────────────────────────
    score = max(0, min(100, score))

    # Override trend for PIFS peace signal
    if pifs_alert:
        geo_trend = 'DEESCALATING'
    elif score >= 75:
        geo_trend = 'CRITICAL'
    elif score >= 50:
        geo_trend = 'ESCALATING'
    elif score >= 25:
        geo_trend = 'STABLE'
    else:
        geo_trend = 'DEESCALATING'

    return {
        'geo_score': score,
        'geo_trend': geo_trend,
        'geo_hotspots': hotspots,
        'geo_trades_affected': sorted(trades_affected),
        'trump_signal': trump_signal,
        'pifs_alert': pifs_alert,
        'detail': detail,
    }


# ─── P2.D — Stress-Testing / Scenario Analysis ──────────────────────────────

def run_stress_tests(conn, vix: float, strategies: dict) -> dict:
    """
    Berechnet Stress-Szenarien für das Portfolio.
    Returns: {
        'max_portfolio_loss_all_stops': float,
        'scenarios': { ... },
        'risk_rating': 'LOW'|'MEDIUM'|'HIGH'|'CRITICAL',
        'portfolio_value': float,
    }
    """
    default = {
        'max_portfolio_loss_all_stops': 0.0,
        'scenarios': {},
        'risk_rating': 'LOW',
        'portfolio_value': 0.0,
    }

    if conn is None:
        return default

    # ── Load open positions ───────────────────────────────────────────────
    try:
        rows = conn.execute(
            "SELECT ticker, strategy, entry_price, shares, stop_price, "
            "target_price, sector FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchall()
    except Exception:
        return default

    if not rows:
        return default

    positions = []
    for r in rows:
        entry = float(r[2]) if r[2] else 0.0
        shares = float(r[3]) if r[3] else 0.0
        stop = float(r[4]) if r[4] else 0.0
        target = float(r[5]) if r[5] else 0.0
        sector = (r[6] or '').lower()
        ticker = r[0] or 'UNKNOWN'
        strategy = r[1] or 'unknown'

        # Determine sector category for stress scenarios
        sector_cat = _classify_sector(sector, ticker, strategy)

        positions.append({
            'ticker': ticker,
            'strategy': strategy,
            'entry_price': entry,
            'shares': shares,
            'stop_price': stop,
            'target_price': target,
            'sector_raw': sector,
            'sector_cat': sector_cat,
            'invested': entry * shares,
        })

    # Get portfolio value
    try:
        fund_rows = conn.execute("SELECT key, value FROM paper_fund").fetchall()
        fund = {r[0]: r[1] for r in fund_rows}
        cash = float(fund.get('current_cash', 0))
        starting = float(fund.get('starting_capital', 25000))
        realized_pnl = float(fund.get('total_realized_pnl', 0))
    except Exception:
        cash = 0.0
        starting = 25000.0
        realized_pnl = 0.0

    total_invested = sum(p['invested'] for p in positions)
    portfolio_value = cash + total_invested

    # ── 1. Max Portfolio Loss (All Stops) ─────────────────────────────────
    max_loss = 0.0
    for p in positions:
        if p['stop_price'] > 0 and p['entry_price'] > 0:
            # Loss per position if stop triggers
            loss = (p['entry_price'] - p['stop_price']) * p['shares']
            # For short-type setups (stop above entry, e.g. NOVO-B.CO with higher stop)
            if p['stop_price'] > p['entry_price']:
                loss = (p['stop_price'] - p['entry_price']) * p['shares']
            max_loss += abs(loss)

    max_loss_pct = (max_loss / portfolio_value * 100) if portfolio_value > 0 else 0

    # ── 2. VIX Spike (+50%) ───────────────────────────────────────────────
    vix_impact_map = {
        'tech': -0.08, 'energy': -0.03, 'materials': -0.05,
        'healthcare': -0.02, 'biotech': -0.04, 'defense': -0.04,
        'industrials': -0.05, 'other': -0.05,
    }
    vix_spike = _calc_scenario_impact(positions, vix_impact_map, portfolio_value)

    # ── 3. Sector Crash (-10% per sector) ─────────────────────────────────
    sectors_in_portfolio = set(p['sector_cat'] for p in positions)
    sector_crash_details = {}
    worst_sector_impact = 0.0
    for sec in sectors_in_portfolio:
        impact_map = {s: 0.0 for s in vix_impact_map}
        impact_map[sec] = -0.10
        result = _calc_scenario_impact(positions, impact_map, portfolio_value)
        sector_crash_details[sec] = result
        if result['impact_eur'] < worst_sector_impact:
            worst_sector_impact = result['impact_eur']

    sector_crash = {
        'description': 'Worst sector -10%',
        'impact_eur': round(worst_sector_impact, 2),
        'details_by_sector': sector_crash_details,
        'positions_at_risk': [],
    }

    # ── 4. Iran Peace Deal ────────────────────────────────────────────────
    iran_peace_impacts = {
        'energy': -0.10, 'defense': -0.05, 'other': -0.03,
        'tech': 0.02, 'healthcare': 0.01, 'biotech': 0.01,
        'materials': -0.02, 'industrials': 0.03,
    }
    # Special overrides for known tickers
    iran_peace = _calc_scenario_impact(positions, iran_peace_impacts, portfolio_value,
                                        ticker_overrides={
                                            'EQNR.OL': -0.10, 'OXY': -0.10,
                                            'XOM': -0.08, 'CVX': -0.08,
                                            'LHA.DE': 0.20,  # Airlines benefit
                                            'BA.L': -0.08,   # Defense company, mixed
                                        })

    # ── 5. Liberation Day (Trump Zölle) ───────────────────────────────────
    liberation_impacts = {
        'tech': -0.06, 'energy': 0.0, 'materials': -0.04,
        'industrials': -0.05, 'defense': -0.02, 'healthcare': -0.02,
        'biotech': -0.03, 'other': -0.03,
    }
    liberation_day = _calc_scenario_impact(positions, liberation_impacts, portfolio_value)

    # ── 6. Flash Crash (SPY -5%) ──────────────────────────────────────────
    flash_impacts = {s: -0.05 for s in vix_impact_map}
    flash_crash = _calc_scenario_impact(positions, flash_impacts, portfolio_value,
                                         slippage_factor=1.02)

    # ── Risk Rating ───────────────────────────────────────────────────────
    if max_loss_pct > 15:
        risk_rating = 'CRITICAL'
    elif max_loss_pct > 10:
        risk_rating = 'HIGH'
    elif max_loss_pct > 5:
        risk_rating = 'MEDIUM'
    else:
        risk_rating = 'LOW'

    return {
        'max_portfolio_loss_all_stops': round(max_loss, 2),
        'max_portfolio_loss_pct': round(max_loss_pct, 1),
        'portfolio_value': round(portfolio_value, 2),
        'open_positions_count': len(positions),
        'scenarios': {
            'vix_spike': vix_spike,
            'sector_crash': sector_crash,
            'iran_peace_deal': iran_peace,
            'liberation_day': liberation_day,
            'flash_crash': flash_crash,
        },
        'risk_rating': risk_rating,
    }


TICKER_SECTOR_MAP = {
    'EQNR': 'energy', 'EQNR.OL': 'energy', 'OXY': 'energy', 'XOM': 'energy',
    'TTE.PA': 'energy', 'CVX': 'energy', 'XLE': 'energy',
    'NVDA': 'tech', 'PLTR': 'tech', 'MSFT': 'tech', 'ASML': 'tech', 'ASML.AS': 'tech',
    'RHM.DE': 'defense', 'LMT': 'defense', 'RTX': 'defense', 'NOC': 'defense', 'BA': 'defense',
    'BAYN.DE': 'healthcare', 'NVO': 'healthcare', 'NOVO-B.CO': 'healthcare',
    'RIO.L': 'materials', 'BHP.L': 'materials', 'VALE': 'materials', 'FCX': 'materials',
    'GOLD': 'materials', 'NEM': 'materials', 'AG': 'materials', 'ISPA.DE': 'materials',
    'STLD': 'materials', 'NUE': 'materials', 'CLF': 'materials',
    'LHA.DE': 'industrials', 'SIE.DE': 'industrials',
    'A3D42Y': 'energy',  # VanEck Oil Services ETF
    'A2DWAW': 'healthcare',  # iShares Biotech ETF
    'BA.L': 'defense',  # BAE Systems
    'DHT': 'energy', 'FRO': 'energy', 'STNG': 'energy',
    'DAL': 'industrials', 'UAL': 'industrials', 'AAL': 'industrials',
    'MAR': 'consumer', 'HLT': 'consumer', 'BKNG': 'consumer',
    'SAP.DE': 'tech', 'MOS': 'materials', 'ADM': 'consumer',
}


def _classify_sector(sector: str, ticker: str, strategy: str) -> str:
    """Classifies a position into a standard sector category for stress testing."""
    # Priority 1: Known ticker mapping
    ticker_upper = (ticker or '').upper()
    mapped = TICKER_SECTOR_MAP.get(ticker_upper)
    if mapped:
        return mapped

    sector_lower = (sector or '').lower()
    strategy_upper = (strategy or '').upper()

    # Direct sector matches (order matters: check biotech BEFORE tech to avoid 'tech' matching 'biotech')
    if any(k in sector_lower for k in ('biotech', 'bio')):
        return 'biotech'
    if any(k in sector_lower for k in ('tech', 'halbleiter', 'semiconductor', 'ki', 'ai')):
        return 'tech'
    if any(k in sector_lower for k in ('energy', 'oil', 'öl', 'gas', 'nuclear', 'uranium')):
        return 'energy'
    if any(k in sector_lower for k in ('defense', 'defence', 'rüstung', 'military')):
        return 'defense'
    if any(k in sector_lower for k in ('health', 'pharma', 'medical')):
        return 'healthcare'
    if any(k in sector_lower for k in ('material', 'metals', 'mining', 'fertilizer')):
        return 'materials'
    if any(k in sector_lower for k in ('industrial',)):
        return 'industrials'

    # Ticker-based fallback
    energy_tickers = {'EQNR.OL', 'OXY', 'XOM', 'CVX', 'COP', 'SLB'}
    defense_tickers = {'RHM.DE', 'BA.L', 'LMT', 'RTX', 'NOC', 'HAG.DE'}
    tech_tickers = {'SIE.DE', 'NVDA', 'PLTR', 'MSFT', 'META', 'GOOG'}
    biotech_tickers = {'NOVO-B.CO', 'NVO', 'ABBV', 'AMGN'}

    if ticker_upper in energy_tickers:
        return 'energy'
    if ticker_upper in defense_tickers:
        return 'defense'
    if ticker_upper in tech_tickers:
        return 'tech'
    if ticker_upper in biotech_tickers:
        return 'biotech'

    # Strategy-based fallback
    if 'S1' in strategy_upper or 'PS1' in strategy_upper:
        return 'energy'
    if 'S11' in strategy_upper or 'PS11' in strategy_upper:
        return 'defense'

    return 'other'


def _calc_scenario_impact(positions: list, impact_map: dict, portfolio_value: float,
                           ticker_overrides: dict = None, slippage_factor: float = 1.0) -> dict:
    """
    Calculates scenario impact across all positions.
    impact_map: {sector_cat: pct_impact} e.g. {'tech': -0.08}
    ticker_overrides: {ticker: pct_impact} for specific stocks
    Returns: { description, impact_eur, positions_at_risk: [...] }
    """
    total_impact = 0.0
    at_risk = []
    position_impacts = []

    for p in positions:
        # Check ticker override first
        if ticker_overrides and p['ticker'] in ticker_overrides:
            pct = ticker_overrides[p['ticker']]
        else:
            pct = impact_map.get(p['sector_cat'], impact_map.get('other', -0.03))

        impact = p['invested'] * pct * slippage_factor
        total_impact += impact

        position_impacts.append({
            'ticker': p['ticker'],
            'impact_eur': round(impact, 2),
            'impact_pct': round(pct * 100, 1),
        })

        # Would this breach the stop?
        if pct < 0 and p['stop_price'] > 0 and p['entry_price'] > 0:
            new_price = p['entry_price'] * (1 + pct)
            if new_price <= p['stop_price']:
                at_risk.append(p['ticker'])

    impact_pct = (total_impact / portfolio_value * 100) if portfolio_value > 0 else 0

    return {
        'description': f'Impact: €{total_impact:+,.0f} ({impact_pct:+.1f}%)',
        'impact_eur': round(total_impact, 2),
        'impact_pct': round(impact_pct, 1),
        'positions_at_risk': at_risk,
        'position_details': position_impacts,
    }


# ─── P3.C — Anomaly Detection ─────────────────────────────────────────────────

def detect_anomalies(conn, market_data: dict = None) -> dict:
    """Erkennt ungewöhnliche Muster in Marktdaten und Portfolio.

    Returns: {
        'anomaly_count': int,
        'anomalies': [
            {
                'type': str,          # VOLUME_SPIKE|STREAK|CONCENTRATION|PNL_OUTLIER|STOP_DISTANCE|STALE_POSITION
                'severity': str,      # LOW|MEDIUM|HIGH
                'ticker': str,
                'description': str,
                'action_suggested': str,
            }
        ],
        'portfolio_anomalies': [...],
        'market_anomalies': [...],
        'high_count': int,
        'medium_count': int,
        'low_count': int,
    }"""
    import statistics as stats
    from datetime import datetime, timedelta

    anomalies = []
    portfolio_anomalies = []
    market_anomalies = []

    # ── 1. Volume Anomalies (from market_data if available) ───────────────
    try:
        if market_data and isinstance(market_data, dict):
            # Collect tickers from open positions + watchlist
            portfolio_tickers = set()
            if conn is not None:
                try:
                    rows = conn.execute(
                        "SELECT DISTINCT ticker FROM paper_portfolio WHERE status = 'OPEN'"
                    ).fetchall()
                    for r in rows:
                        portfolio_tickers.add(r[0])
                except Exception:
                    pass

            # Check sector ETFs for volume anomalies
            for etf_key in ('xle', 'xlk', 'xlf', 'xli', 'xlb', 'xlv'):
                etf_data = market_data.get(etf_key, {})
                if etf_data.get('error') or not etf_data:
                    continue
                # Yahoo chart data includes volume in the raw response
                # but our _fetch_yahoo_chart doesn't return it yet.
                # Check if volume data is present in the market_data dict
                volume = etf_data.get('volume')
                avg_volume = etf_data.get('avg_volume')
                if volume and avg_volume and avg_volume > 0:
                    ratio = volume / avg_volume
                    sector_name = {'xle': 'Energy', 'xlk': 'Tech', 'xlf': 'Financials',
                                   'xli': 'Industrials', 'xlb': 'Materials', 'xlv': 'Healthcare'}.get(etf_key, etf_key)
                    if ratio >= 3.0:
                        a = {
                            'type': 'VOLUME_SPIKE', 'severity': 'HIGH',
                            'ticker': etf_key.upper(),
                            'description': f'{sector_name} ETF Volumen {ratio:.1f}× Durchschnitt — Sektor-Rotation?',
                            'action_suggested': f'{sector_name}-Positionen prüfen',
                        }
                        market_anomalies.append(a)
                        anomalies.append(a)
                    elif ratio >= 2.0:
                        a = {
                            'type': 'VOLUME_SPIKE', 'severity': 'MEDIUM',
                            'ticker': etf_key.upper(),
                            'description': f'{sector_name} ETF Volumen {ratio:.1f}× Durchschnitt — ungewöhnlich',
                            'action_suggested': f'{sector_name}-Sektor beobachten',
                        }
                        market_anomalies.append(a)
                        anomalies.append(a)
    except Exception:
        pass

    # ── 2. Streak Detection (from closed trades) ─────────────────────────
    try:
        if conn is not None:
            rows = conn.execute(
                "SELECT pnl_eur, ticker, strategy FROM paper_portfolio "
                "WHERE status IN ('CLOSED','STOPPED','TP_HIT','WIN','LOSS') "
                "AND pnl_eur IS NOT NULL "
                "ORDER BY close_date DESC LIMIT 20"
            ).fetchall()
            if rows:
                # Count current streak
                streak_type = None  # 'win' or 'loss'
                streak_count = 0
                streak_tickers = []
                for r in rows:
                    pnl = float(r[0])
                    ticker = r[1] or '?'
                    if streak_type is None:
                        streak_type = 'win' if pnl > 0 else 'loss'
                        streak_count = 1
                        streak_tickers.append(ticker)
                    elif (pnl > 0 and streak_type == 'win') or (pnl <= 0 and streak_type == 'loss'):
                        streak_count += 1
                        streak_tickers.append(ticker)
                    else:
                        break

                if streak_type == 'loss' and streak_count >= 5:
                    a = {
                        'type': 'STREAK', 'severity': 'HIGH',
                        'ticker': ', '.join(streak_tickers[:5]),
                        'description': f'Schwere Verlustserie: {streak_count} Verluste in Folge ({", ".join(streak_tickers[:5])})',
                        'action_suggested': 'SHUTDOWN prüfen — Exposure sofort reduzieren',
                    }
                    portfolio_anomalies.append(a)
                    anomalies.append(a)
                elif streak_type == 'loss' and streak_count >= 3:
                    a = {
                        'type': 'STREAK', 'severity': 'MEDIUM',
                        'ticker': ', '.join(streak_tickers[:5]),
                        'description': f'Losing streak: {streak_count} Verluste in Folge ({", ".join(streak_tickers[:5])})',
                        'action_suggested': 'CEO sollte Exposure reduzieren',
                    }
                    portfolio_anomalies.append(a)
                    anomalies.append(a)
                elif streak_type == 'win' and streak_count >= 3:
                    a = {
                        'type': 'STREAK', 'severity': 'LOW',
                        'ticker': ', '.join(streak_tickers[:5]),
                        'description': f'Winning streak: {streak_count} Gewinne in Folge — aber Overconfidence vermeiden',
                        'action_suggested': 'Position Sizing nicht erhöhen — Disziplin halten',
                    }
                    portfolio_anomalies.append(a)
                    anomalies.append(a)
    except Exception:
        pass

    # ── 3. Concentration Anomaly (sector exposure) ───────────────────────
    try:
        if conn is not None:
            rows = conn.execute(
                "SELECT ticker, strategy, entry_price, shares, sector "
                "FROM paper_portfolio WHERE status = 'OPEN'"
            ).fetchall()
            if rows:
                sector_invested = defaultdict(float)
                total_invested = 0.0
                for r in rows:
                    entry = float(r[2]) if r[2] else 0.0
                    shares = float(r[3]) if r[3] else 0.0
                    invested = entry * shares
                    sector = (r[4] or 'Other').strip()
                    if not sector:
                        sector = 'Other'
                    sector_invested[sector] += invested
                    total_invested += invested

                if total_invested > 0:
                    for sector, inv in sector_invested.items():
                        pct = inv / total_invested * 100
                        if pct > 60:
                            a = {
                                'type': 'CONCENTRATION', 'severity': 'HIGH',
                                'ticker': sector,
                                'description': f'Klumpenrisiko: {sector} = {pct:.0f}% des Portfolios!',
                                'action_suggested': f'Keine neuen {sector}-Positionen — Diversifizieren',
                            }
                            portfolio_anomalies.append(a)
                            anomalies.append(a)
                        elif pct > 40:
                            a = {
                                'type': 'CONCENTRATION', 'severity': 'MEDIUM',
                                'ticker': sector,
                                'description': f'Sektor-Konzentration: {sector} = {pct:.0f}% des Portfolios',
                                'action_suggested': f'Neue {sector}-Positionen nur mit starkem Signal',
                            }
                            portfolio_anomalies.append(a)
                            anomalies.append(a)
    except Exception:
        pass

    # ── 4. PnL Anomaly (Outlier Detection) ───────────────────────────────
    try:
        if conn is not None:
            # Get StdDev of closed trade PnLs
            closed_rows = conn.execute(
                "SELECT pnl_eur FROM paper_portfolio "
                "WHERE status IN ('CLOSED','STOPPED','TP_HIT','WIN','LOSS') "
                "AND pnl_eur IS NOT NULL"
            ).fetchall()
            closed_pnls = [float(r[0]) for r in closed_rows]

            if len(closed_pnls) >= 5:
                mean_pnl = stats.mean(closed_pnls)
                stdev_pnl = stats.stdev(closed_pnls)

                if stdev_pnl > 0:
                    # Check open positions' unrealized PnL
                    open_rows = conn.execute(
                        "SELECT ticker, entry_price, shares, stop_price, target_price "
                        "FROM paper_portfolio WHERE status = 'OPEN'"
                    ).fetchall()
                    for r in open_rows:
                        ticker = r[0] or '?'
                        entry = float(r[1]) if r[1] else 0.0
                        shares = float(r[2]) if r[2] else 0.0
                        stop = float(r[3]) if r[3] else 0.0
                        target = float(r[4]) if r[4] else 0.0

                        # Estimate current unrealized PnL using stop as worst case
                        # and entry as current (conservative — we don't have live prices here)
                        # If market_data has ticker prices, use those
                        current_price = entry  # fallback
                        if market_data and isinstance(market_data, dict):
                            # Try to find ticker in market_data
                            for key, val in market_data.items():
                                if isinstance(val, dict) and val.get('price') and key.upper() == ticker.upper():
                                    current_price = val['price']
                                    break

                        unrealized_pnl = (current_price - entry) * shares

                        # Check if outlier loss
                        if stdev_pnl > 0 and unrealized_pnl < (mean_pnl - 2 * stdev_pnl):
                            a = {
                                'type': 'PNL_OUTLIER', 'severity': 'HIGH',
                                'ticker': ticker,
                                'description': f'{ticker} unrealisierter Verlust €{unrealized_pnl:.0f} > 2σ unter Durchschnitt — Outlier-Verlust',
                                'action_suggested': 'Exit prüfen — überdurchschnittlicher Verlust',
                            }
                            portfolio_anomalies.append(a)
                            anomalies.append(a)
                        elif stdev_pnl > 0 and unrealized_pnl > (mean_pnl + 2 * stdev_pnl):
                            a = {
                                'type': 'PNL_OUTLIER', 'severity': 'MEDIUM',
                                'ticker': ticker,
                                'description': f'{ticker} unrealisierter Gewinn €{unrealized_pnl:.0f} > 2σ über Durchschnitt — Trailing Stop empfohlen',
                                'action_suggested': 'Trailing Stop setzen — Gewinne sichern',
                            }
                            portfolio_anomalies.append(a)
                            anomalies.append(a)
    except Exception:
        pass

    # ── 5. Stop-Distance Anomaly ─────────────────────────────────────────
    try:
        if conn is not None:
            rows = conn.execute(
                "SELECT ticker, entry_price, stop_price "
                "FROM paper_portfolio WHERE status = 'OPEN' "
                "AND stop_price IS NOT NULL AND stop_price > 0 "
                "AND entry_price IS NOT NULL AND entry_price > 0"
            ).fetchall()
            for r in rows:
                ticker = r[0] or '?'
                entry = float(r[1])
                stop = float(r[2])

                # Use live price if available, else entry as proxy
                current_price = entry
                if market_data and isinstance(market_data, dict):
                    for key, val in market_data.items():
                        if isinstance(val, dict) and val.get('price') and key.upper() == ticker.upper():
                            current_price = val['price']
                            break

                if current_price > 0:
                    distance_pct = abs(current_price - stop) / current_price * 100

                    if distance_pct < 1.0:
                        a = {
                            'type': 'STOP_DISTANCE', 'severity': 'HIGH',
                            'ticker': ticker,
                            'description': f'{ticker} Stop nur {distance_pct:.1f}% entfernt — Whipsaw-Risiko!',
                            'action_suggested': 'Sofort-Aktion: Stop prüfen oder Position schließen',
                        }
                        portfolio_anomalies.append(a)
                        anomalies.append(a)
                    elif distance_pct > 20.0:
                        a = {
                            'type': 'STOP_DISTANCE', 'severity': 'MEDIUM',
                            'ticker': ticker,
                            'description': f'{ticker} Stop {distance_pct:.1f}% entfernt — sehr weit weg',
                            'action_suggested': 'Stop enger nachziehen — sinnvoll?',
                        }
                        portfolio_anomalies.append(a)
                        anomalies.append(a)
    except Exception:
        pass

    # ── 6. Stale Position Detection ──────────────────────────────────────
    try:
        if conn is not None:
            cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT ticker, entry_price, entry_date, shares "
                "FROM paper_portfolio WHERE status = 'OPEN' "
                "AND entry_date IS NOT NULL AND entry_date < ?",
                (cutoff,)
            ).fetchall()
            for r in rows:
                ticker = r[0] or '?'
                entry = float(r[1]) if r[1] else 0.0
                entry_date = r[2] or ''
                shares = float(r[3]) if r[3] else 0.0

                # Approximate current price
                current_price = entry
                if market_data and isinstance(market_data, dict):
                    for key, val in market_data.items():
                        if isinstance(val, dict) and val.get('price') and key.upper() == ticker.upper():
                            current_price = val['price']
                            break

                if entry > 0:
                    pnl_pct = (current_price - entry) / entry * 100
                    if abs(pnl_pct) <= 2.0:
                        # Calculate days held
                        try:
                            entry_dt = datetime.strptime(entry_date[:10], '%Y-%m-%d')
                            days_held = (datetime.now() - entry_dt).days
                        except Exception:
                            days_held = 31

                        a = {
                            'type': 'STALE_POSITION', 'severity': 'MEDIUM',
                            'ticker': ticker,
                            'description': f'{ticker} seit {days_held} Tagen offen, PnL ≈ {pnl_pct:+.1f}% — Dead Money',
                            'action_suggested': 'Kapital ist gebunden ohne Return — Exit prüfen',
                        }
                        portfolio_anomalies.append(a)
                        anomalies.append(a)
    except Exception:
        pass

    # ── Compile result ───────────────────────────────────────────────────
    high_count = sum(1 for a in anomalies if a['severity'] == 'HIGH')
    medium_count = sum(1 for a in anomalies if a['severity'] == 'MEDIUM')
    low_count = sum(1 for a in anomalies if a['severity'] == 'LOW')

    return {
        'anomaly_count': len(anomalies),
        'anomalies': anomalies,
        'portfolio_anomalies': portfolio_anomalies,
        'market_anomalies': market_anomalies,
        'high_count': high_count,
        'medium_count': medium_count,
        'low_count': low_count,
    }


# ─── Top Opportunities identifizieren ────────────────────────────────────────

def find_top_opportunities(mode: str, strategies: dict, strat_perf: dict) -> list:
    """Findet die 3 besten Opportunitäten basierend auf Modus und Performance."""
    if mode in ('SHUTDOWN',):
        return []

    opps = []

    for strat_id, strat in strategies.items():
        if strat_id.startswith('_') or strat_id == 'emerging_themes':
            continue
        if strat.get('locked', False):
            continue
        if strat.get('status') not in ('active', 'watchlist', 'watching'):
            continue

        health = strat.get('health', 'red')
        if health not in ('green', 'green_hot', 'yellow'):
            continue

        perf = strat_perf.get(strat_id, {})
        wr = perf.get('win_rate', 0)
        n = perf.get('trades', 0)

        # Score: Health + Win-Rate + Conviction
        opp_score = 0
        if health == 'green_hot':
            opp_score += 40
        elif health == 'green':
            opp_score += 30
        elif health == 'yellow':
            opp_score += 10

        if n >= 2:
            opp_score += int(wr * 30)

        # DEFENSIVE: nur sichere Sektoren
        if mode == 'DEFENSIVE' and strat.get('sector') in ('technology',):
            continue

        name = strat.get('name', strat_id)
        tickers = strat.get('tickers', [])
        opps.append({
            'strategy': strat_id,
            'name': name,
            'tickers': tickers[:3],
            'health': health,
            'score': opp_score,
            'win_rate': wr,
            'trades': n,
        })

    opps.sort(key=lambda x: x['score'], reverse=True)
    return opps[:3]


# ─── P3.A — Post-Mortem Analyzer ─────────────────────────────────────────────

def analyze_trade_postmortems(conn) -> dict:
    """Analysiert JEDEN geschlossenen Trade und extrahiert Lern-Insights.

    Returns: {
        'total_analyzed': int,
        'avg_entry_quality': float (0-10),
        'avg_exit_quality': float (0-10),
        'disposition_effect': float (-1 to 1, positiv = Gewinner zu früh verkauft),
        'optimal_holding_days': { 'strategy_id': float, ... },
        'regime_performance': { 'REGIME': {'wr': float, 'avg_pnl': float, 'trades': int}, ... },
        'insights': [str, ...],
        'trade_details': [ { ... }, ... ]
    }"""

    default = {
        'total_analyzed': 0,
        'avg_entry_quality': 0.0,
        'avg_exit_quality': 0.0,
        'disposition_effect': 0.0,
        'optimal_holding_days': {},
        'regime_performance': {},
        'insights': ['Keine geschlossenen Trades für Analyse vorhanden.'],
        'trade_details': [],
    }

    if conn is None:
        return default

    # --- Load strategies for health info ---
    strategies = safe_read_json(WS / 'data/strategies.json', {})

    # --- Fetch closed trades (all non-OPEN statuses) ---
    try:
        rows = conn.execute(
            "SELECT * FROM paper_portfolio WHERE status != 'OPEN' ORDER BY close_date DESC"
        ).fetchall()
    except Exception:
        return default

    if not rows:
        return default

    # --- Get column names for safe access ---
    try:
        col_names = [desc[0] for desc in conn.execute("SELECT * FROM paper_portfolio LIMIT 0").description]
    except Exception:
        col_names = []

    def _safe_get(row, col, default_val=None):
        """Safely get column from Row, handling missing columns."""
        try:
            return row[col]
        except (IndexError, KeyError):
            return default_val

    # --- Pre-compute strategy avg wins/losses for exit quality scoring ---
    strat_stats = {}
    try:
        strat_rows = conn.execute(
            "SELECT strategy, "
            "AVG(CASE WHEN pnl_eur > 0 THEN pnl_eur END) as avg_win, "
            "AVG(CASE WHEN pnl_eur <= 0 THEN pnl_eur END) as avg_loss "
            "FROM paper_portfolio WHERE status != 'OPEN' AND pnl_eur IS NOT NULL "
            "GROUP BY strategy"
        ).fetchall()
        for sr in strat_rows:
            strat_stats[sr[0]] = {
                'avg_win': float(sr[1]) if sr[1] is not None else 0.0,
                'avg_loss': float(sr[2]) if sr[2] is not None else 0.0,
            }
    except Exception:
        pass

    # --- Analyze each trade ---
    trade_details = []
    entry_qualities = []
    exit_qualities = []

    # For holding period analysis: {strategy: {'win_days': [], 'loss_days': []}}
    holding_by_strat = defaultdict(lambda: {'win_days': [], 'loss_days': []})

    # For regime performance: {regime: {'wins': 0, 'losses': 0, 'pnls': []}}
    regime_perf = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnls': []})

    for row in rows:
        ticker = _safe_get(row, 'ticker', '?')
        strategy = _safe_get(row, 'strategy', 'unknown')
        pnl_eur = _safe_get(row, 'pnl_eur')
        pnl_pct = _safe_get(row, 'pnl_pct')
        conviction = _safe_get(row, 'conviction', 0) or 0
        regime = _safe_get(row, 'regime_at_entry')
        exit_type = _safe_get(row, 'exit_type')
        status = _safe_get(row, 'status', 'CLOSED')
        entry_date_str = _safe_get(row, 'entry_date')
        close_date_str = _safe_get(row, 'close_date')
        entry_price = _safe_get(row, 'entry_price', 0) or 0
        close_price = _safe_get(row, 'close_price', 0) or 0
        trade_id = _safe_get(row, 'id', 0)

        if pnl_eur is None:
            pnl_eur = 0.0
        else:
            pnl_eur = float(pnl_eur)

        is_winner = pnl_eur > 0

        # ── 1. Entry-Qualität (0-10) ──
        entry_score_raw = 5  # Base score

        # Conviction adjustment
        if conviction > 7:
            entry_score_raw += 3
        elif conviction >= 4:
            entry_score_raw += 1
        elif conviction > 0 and conviction < 4:
            entry_score_raw -= 1
        # conviction == 0 means not set → no adjustment

        # Regime adjustment
        regime_str = str(regime).upper() if regime else 'UNKNOWN'
        if regime_str in ('BULL', 'BULL_TREND', 'BULL_VOLATILE', 'NEUTRAL', 'NORMAL'):
            entry_score_raw += 2
        elif regime_str in ('RISK_OFF',):
            entry_score_raw -= 1
        elif regime_str in ('CRASH', 'BEAR', 'BEAR_TREND'):
            entry_score_raw -= 3
        # PAPER_LEARN, UNKNOWN, None → no adjustment

        # Strategy health adjustment
        strat_health = strategies.get(strategy, {}).get('health', 'unknown')
        if strat_health == 'green':
            entry_score_raw += 2
        elif strat_health == 'yellow':
            entry_score_raw += 1
        elif strat_health == 'red':
            entry_score_raw -= 2

        # Normalize to 0-10
        entry_quality = max(0.0, min(10.0, float(entry_score_raw)))

        # ── 2. Exit-Qualität (0-10) ──
        # Determine exit category
        if exit_type == 'TARGET_HIT' or status == 'TP_HIT' or status == 'WIN':
            exit_base = 8
        elif status == 'STOPPED' or exit_type == 'STOP_HIT':
            exit_base = 3
        elif is_winner:
            exit_base = 6  # Manual close in profit
        else:
            exit_base = 4  # Manual close at loss

        # Bonus/Malus vs strategy avg
        ss = strat_stats.get(strategy, {})
        avg_win = ss.get('avg_win', 0)
        avg_loss = ss.get('avg_loss', 0)

        if is_winner and avg_win > 0 and pnl_eur > avg_win:
            exit_base += 2
        elif not is_winner and avg_loss < 0 and pnl_eur < avg_loss:
            exit_base -= 2

        exit_quality = max(0.0, min(10.0, float(exit_base)))

        # ── 3. Holding Period ──
        holding_days = None
        if entry_date_str and close_date_str:
            try:
                # Handle various date formats
                for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
                    try:
                        entry_dt = datetime.strptime(entry_date_str[:19] if 'T' in entry_date_str else entry_date_str[:10], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    entry_dt = None

                for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
                    try:
                        close_dt = datetime.strptime(close_date_str[:26] if '.' in close_date_str else close_date_str[:19] if 'T' in close_date_str else close_date_str[:10], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    close_dt = None

                if entry_dt and close_dt:
                    holding_days = max(0, (close_dt - entry_dt).days)
                    if is_winner:
                        holding_by_strat[strategy]['win_days'].append(holding_days)
                    else:
                        holding_by_strat[strategy]['loss_days'].append(holding_days)
            except Exception:
                pass

        # ── 4. Regime Performance tracking ──
        if regime_str not in ('UNKNOWN', 'NONE'):
            if is_winner:
                regime_perf[regime_str]['wins'] += 1
            else:
                regime_perf[regime_str]['losses'] += 1
            regime_perf[regime_str]['pnls'].append(pnl_eur)

        # ── Build lesson ──
        lesson = ''
        if entry_quality >= 7 and exit_quality >= 7:
            lesson = 'Solider Trade — Entry + Exit gut.'
        elif entry_quality >= 7 and exit_quality < 5:
            lesson = 'Guter Entry, schlechter Exit — Exit-Regeln überprüfen.'
        elif entry_quality < 4 and is_winner:
            lesson = 'Glückstreffer — trotz schwachem Entry Gewinn. Nicht replizierbar.'
        elif entry_quality < 4 and not is_winner:
            lesson = 'Vorhersehbarer Verlust — schwacher Entry, schwacher Ausgang.'
        elif not is_winner and holding_days and holding_days > 7:
            lesson = 'Verlierer zu lange gehalten.'
        elif is_winner and pnl_eur < 5:
            lesson = 'Minimal-Gewinn — Position sizing oder Haltedauer prüfen.'
        else:
            lesson = 'Standard-Trade ohne besondere Auffälligkeiten.'

        entry_qualities.append(entry_quality)
        exit_qualities.append(exit_quality)

        trade_details.append({
            'id': trade_id,
            'ticker': ticker,
            'strategy': strategy,
            'entry_quality': round(entry_quality, 1),
            'exit_quality': round(exit_quality, 1),
            'holding_days': holding_days,
            'regime': regime_str,
            'pnl': round(pnl_eur, 2),
            'lesson': lesson,
        })

    # --- Aggregate metrics ---
    total = len(trade_details)
    avg_entry = sum(entry_qualities) / total if total > 0 else 0.0
    avg_exit = sum(exit_qualities) / total if total > 0 else 0.0

    # --- Disposition Effect ---
    # Global: avg holding days for winners vs losers
    all_win_days = []
    all_loss_days = []
    for strat, hd in holding_by_strat.items():
        all_win_days.extend(hd['win_days'])
        all_loss_days.extend(hd['loss_days'])

    avg_win_holding = sum(all_win_days) / len(all_win_days) if all_win_days else 0
    avg_loss_holding = sum(all_loss_days) / len(all_loss_days) if all_loss_days else 0

    # Disposition effect: positive means winners sold too early relative to losers
    # Scale: (loss_holding - win_holding) / max(loss_holding, win_holding) → -1 to 1
    if avg_win_holding > 0 or avg_loss_holding > 0:
        max_hold = max(avg_win_holding, avg_loss_holding, 1)
        disposition_effect = (avg_loss_holding - avg_win_holding) / max_hold
        disposition_effect = max(-1.0, min(1.0, disposition_effect))
    else:
        disposition_effect = 0.0

    # --- Optimal holding days per strategy ---
    optimal_holding = {}
    for strat, hd in holding_by_strat.items():
        if hd['win_days']:
            optimal_holding[strat] = round(sum(hd['win_days']) / len(hd['win_days']), 1)

    # --- Regime Performance ---
    regime_result = {}
    for regime_name, rp in regime_perf.items():
        total_r = rp['wins'] + rp['losses']
        wr = rp['wins'] / total_r if total_r > 0 else 0
        avg_pnl = sum(rp['pnls']) / len(rp['pnls']) if rp['pnls'] else 0
        regime_result[regime_name] = {
            'wr': round(wr, 3),
            'avg_pnl': round(avg_pnl, 2),
            'trades': total_r,
        }

    # --- Generate Insights ---
    insights = []

    # Insight 1: Disposition Effect
    if avg_win_holding > 0 and avg_loss_holding > 0:
        if disposition_effect > 0.15:
            insights.append(
                f'Disposition Effect: Gewinner werden nach Ø {avg_win_holding:.1f} Tagen verkauft, '
                f'Verlierer nach Ø {avg_loss_holding:.1f} Tagen. Gewinner länger halten!'
            )
        elif disposition_effect < -0.15:
            insights.append(
                f'Anti-Disposition: Verlierer werden schneller geschlossen ({avg_loss_holding:.1f}d) '
                f'als Gewinner gehalten ({avg_win_holding:.1f}d). Gute Disziplin!'
            )
        else:
            insights.append(
                f'Haltedauer ausgeglichen: Gewinner Ø {avg_win_holding:.1f}d, Verlierer Ø {avg_loss_holding:.1f}d.'
            )

    # Insight 2: Strategy with low sample size
    for strat, hd in holding_by_strat.items():
        n_trades = len(hd['win_days']) + len(hd['loss_days'])
        wr = len(hd['win_days']) / n_trades if n_trades > 0 else 0
        if n_trades <= 3 and wr >= 0.66:
            insights.append(f'{strat} hat {wr:.0%} WR — aber nur {n_trades} Trades. Mehr Daten nötig.')
            break  # Only one such insight

    # Insight 3: Best and worst regime
    if regime_result:
        best_regime = max(regime_result.items(), key=lambda x: x[1]['wr']) if regime_result else None
        worst_regime = min(regime_result.items(), key=lambda x: x[1]['wr']) if regime_result else None
        if best_regime and worst_regime and best_regime[0] != worst_regime[0]:
            insights.append(
                f'Bestes Regime: {best_regime[0]} ({best_regime[1]["wr"]:.0%} WR, {best_regime[1]["trades"]} Trades) | '
                f'Schlechtestes: {worst_regime[0]} ({worst_regime[1]["wr"]:.0%} WR, {worst_regime[1]["trades"]} Trades)'
            )

    # Insight 4: Regime-independent strategies
    strat_regimes = defaultdict(lambda: defaultdict(lambda: {'wins': 0, 'total': 0}))
    for td in trade_details:
        r = td['regime']
        s = td['strategy']
        strat_regimes[s][r]['total'] += 1
        if td['pnl'] > 0:
            strat_regimes[s][r]['wins'] += 1

    for strat, regimes in strat_regimes.items():
        if len(regimes) >= 2:
            regime_wrs = []
            for rname, rv in regimes.items():
                if rv['total'] >= 1:
                    regime_wrs.append(rv['wins'] / rv['total'])
            if regime_wrs and min(regime_wrs) > 0.3 and len(regime_wrs) >= 2:
                insights.append(f'{strat} funktioniert regime-übergreifend — mögliche Allwetter-Strategie.')
                break

    # Insight 5: Entry quality vs outcomes
    high_entry_wins = sum(1 for td in trade_details if td['entry_quality'] >= 7 and td['pnl'] > 0)
    high_entry_total = sum(1 for td in trade_details if td['entry_quality'] >= 7)
    low_entry_wins = sum(1 for td in trade_details if td['entry_quality'] < 4 and td['pnl'] > 0)
    low_entry_total = sum(1 for td in trade_details if td['entry_quality'] < 4)
    if high_entry_total >= 3 and low_entry_total >= 3:
        high_wr = high_entry_wins / high_entry_total
        low_wr = low_entry_wins / low_entry_total
        if high_wr > low_wr + 0.15:
            insights.append(
                f'Hohe Entry-Qualität (≥7) hat {high_wr:.0%} WR vs. niedrige (<4) mit {low_wr:.0%} WR. '
                f'Entry-Disziplin zahlt sich aus!'
            )

    # Ensure at least one insight
    if not insights:
        insights.append(f'{total} Trades analysiert. Noch zu wenig Daten für starke Muster.')

    # --- Save to file ---
    result = {
        'total_analyzed': total,
        'avg_entry_quality': round(avg_entry, 1),
        'avg_exit_quality': round(avg_exit, 1),
        'disposition_effect': round(disposition_effect, 3),
        'optimal_holding_days': optimal_holding,
        'regime_performance': regime_result,
        'insights': insights,
        'trade_details': trade_details,
        'analysis_timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'avg_win_holding_days': round(avg_win_holding, 1),
        'avg_loss_holding_days': round(avg_loss_holding, 1),
    }

    # Save full results to JSON
    try:
        postmortem_path = WS / 'data/trade_postmortems.json'
        postmortem_path.parent.mkdir(parents=True, exist_ok=True)
        with open(postmortem_path, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ Post-Mortem JSON konnte nicht gespeichert werden: {e}', file=sys.stderr)

    return result


# ─── P4.D — Backtesting Engine ────────────────────────────────────────────────

def run_backtest(conn, strategies: dict) -> dict:
    """Testet Strategie-Parameter gegen historische Trade-Daten.
    Simuliert: 'Was wäre wenn wir andere Stops/TPs/Regime-Filter gehabt hätten?'
    Returns dict mit strategies_tested, results, system_wide."""

    MIN_TRADES = 5
    result = {
        'strategies_tested': 0,
        'results': {},
        'system_wide': {
            'original_pnl': 0.0,
            'optimized_pnl': 0.0,
            'improvement_pct': 0.0,
            'recommendation': '',
        },
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    }

    if conn is None:
        result['system_wide']['recommendation'] = 'Keine DB-Verbindung — Backtest übersprungen.'
        return result

    # ── Load all closed trades ────────────────────────────────────────────
    try:
        rows = conn.execute(
            "SELECT id, ticker, strategy, entry_price, close_price, stop_price, "
            "target_price, pnl_eur, shares, entry_date, close_date, "
            "regime_at_entry, conviction, sector, status "
            "FROM paper_portfolio "
            "WHERE status IN ('CLOSED', 'WIN', 'STOPPED', 'TP_HIT') "
            "AND pnl_eur IS NOT NULL AND strategy IS NOT NULL "
            "ORDER BY entry_date"
        ).fetchall()
    except Exception as e:
        print(f'⚠️ Backtest: DB-Fehler: {e}', file=sys.stderr)
        result['system_wide']['recommendation'] = f'DB-Fehler: {e}'
        return result

    if not rows:
        result['system_wide']['recommendation'] = 'Keine geschlossenen Trades — Backtest nicht möglich.'
        return result

    # ── Group trades by strategy ──────────────────────────────────────────
    trades_by_strat = defaultdict(list)
    for row in rows:
        trade = {
            'id': row[0], 'ticker': row[1], 'strategy': row[2],
            'entry_price': float(row[3]) if row[3] else 0.0,
            'close_price': float(row[4]) if row[4] else 0.0,
            'stop_price': float(row[5]) if row[5] else 0.0,
            'target_price': float(row[6]) if row[6] else 0.0,
            'pnl_eur': float(row[7]) if row[7] else 0.0,
            'shares': float(row[8]) if row[8] else 0.0,
            'entry_date': row[9] or '',
            'close_date': row[10] or '',
            'regime_at_entry': row[11] or 'UNKNOWN',
            'conviction': int(row[12]) if row[12] else 0,
            'sector': row[13] or '',
            'status': row[14] or '',
        }
        trades_by_strat[trade['strategy']].append(trade)

    # ── Load strategy DNA for regime filters (optional) ───────────────────
    dna_path = WS / 'data/strategy_dna.json'
    strategy_dna = safe_read_json(dna_path, {})

    # ── Track system-wide totals ──────────────────────────────────────────
    total_original_pnl = 0.0
    total_best_pnl = 0.0
    best_single_improvement = 0.0
    best_single_recommendation = ''

    for strat_id, trades in sorted(trades_by_strat.items()):
        if len(trades) < MIN_TRADES:
            continue

        result['strategies_tested'] += 1

        # ── Original performance ──────────────────────────────────────────
        winners = [t for t in trades if t['pnl_eur'] > 0]
        losers = [t for t in trades if t['pnl_eur'] <= 0]
        original_pnl = sum(t['pnl_eur'] for t in trades)
        original_wr = len(winners) / len(trades) if trades else 0.0
        avg_win = sum(t['pnl_eur'] for t in winners) / len(winners) if winners else 0.0

        strat_result = {
            'original': {
                'wr': round(original_wr, 3),
                'pnl': round(original_pnl, 2),
                'trades': len(trades),
            },
            'optimized_stop': {'wr': 0.0, 'pnl': 0.0, 'improvement_pct': 0.0},
            'optimized_tp': {'wr': 0.0, 'pnl': 0.0, 'improvement_pct': 0.0},
            'regime_filtered': {'wr': 0.0, 'pnl': 0.0, 'trades_skipped': 0},
            'best_variant': 'original',
            'best_improvement_pct': 0.0,
        }

        # ── Variant 1: Optimized Stop (-20% weiter) ──────────────────────
        # Neuer Stop = entry_price - (entry_price - stop_price) * 1.2
        # For stopped-out trades with wider stop:
        #   40% chance recovery → pnl = avg_win
        #   60% chance bigger loss → pnl = original_loss * 1.3
        opt_stop_pnl = 0.0
        opt_stop_wins = 0
        for t in trades:
            ep = t['entry_price']
            sp = t['stop_price']
            if ep <= 0 or sp <= 0:
                # Can't compute — keep original
                opt_stop_pnl += t['pnl_eur']
                if t['pnl_eur'] > 0:
                    opt_stop_wins += 1
                continue

            new_stop = ep - (ep - sp) * 1.2
            was_stopped = t['pnl_eur'] <= 0 and t['close_price'] <= sp * 1.02  # close near stop

            if was_stopped and new_stop < sp:
                # Wider stop — would this trade have survived?
                # Simplified simulation:
                # 40% chance recovery → pnl = avg_win of strategy
                # 60% chance bigger loss → pnl = original_loss * 1.3
                recovery_pnl = avg_win if avg_win > 0 else 5.0  # fallback
                worse_pnl = t['pnl_eur'] * 1.3

                simulated_pnl = 0.4 * recovery_pnl + 0.6 * worse_pnl
                opt_stop_pnl += simulated_pnl
                if simulated_pnl > 0:
                    opt_stop_wins += 1
            else:
                # Trade was not stopped out at original level — keep result
                opt_stop_pnl += t['pnl_eur']
                if t['pnl_eur'] > 0:
                    opt_stop_wins += 1

        opt_stop_wr = opt_stop_wins / len(trades) if trades else 0.0
        opt_stop_improvement = ((opt_stop_pnl - original_pnl) / abs(original_pnl) * 100) if original_pnl != 0 else 0.0

        strat_result['optimized_stop'] = {
            'wr': round(opt_stop_wr, 3),
            'pnl': round(opt_stop_pnl, 2),
            'improvement_pct': round(opt_stop_improvement, 1),
        }

        # ── Variant 2: Optimized TP (+20% höher) ─────────────────────────
        # For TP-hit trades (winners that hit target):
        #   50% chance runs further → pnl = original_pnl * 1.15
        #   50% chance reverses → pnl = original_pnl * 0.7
        opt_tp_pnl = 0.0
        opt_tp_wins = 0
        for t in trades:
            ep = t['entry_price']
            tp = t['target_price']

            if t['pnl_eur'] > 0 and tp > 0 and ep > 0:
                # Check if this was a TP hit (close_price near target)
                tp_hit = abs(t['close_price'] - tp) / tp < 0.03 if tp > 0 else False

                if tp_hit:
                    # Simulate higher TP
                    simulated_pnl = 0.5 * (t['pnl_eur'] * 1.15) + 0.5 * (t['pnl_eur'] * 0.7)
                    opt_tp_pnl += simulated_pnl
                    if simulated_pnl > 0:
                        opt_tp_wins += 1
                else:
                    # Winner but not at TP — keep as is
                    opt_tp_pnl += t['pnl_eur']
                    opt_tp_wins += 1
            else:
                # Loser — TP optimization doesn't help
                opt_tp_pnl += t['pnl_eur']
                if t['pnl_eur'] > 0:
                    opt_tp_wins += 1

        opt_tp_wr = opt_tp_wins / len(trades) if trades else 0.0
        opt_tp_improvement = ((opt_tp_pnl - original_pnl) / abs(original_pnl) * 100) if original_pnl != 0 else 0.0

        strat_result['optimized_tp'] = {
            'wr': round(opt_tp_wr, 3),
            'pnl': round(opt_tp_pnl, 2),
            'improvement_pct': round(opt_tp_improvement, 1),
        }

        # ── Variant 3: Regime-Filtered ────────────────────────────────────
        # Filter out trades in worst-performing regimes
        regime_perf = defaultdict(lambda: {'wins': 0, 'total': 0, 'pnl': 0.0})
        for t in trades:
            r = t['regime_at_entry']
            regime_perf[r]['total'] += 1
            regime_perf[r]['pnl'] += t['pnl_eur']
            if t['pnl_eur'] > 0:
                regime_perf[r]['wins'] += 1

        # Calculate WR per regime
        for r in regime_perf:
            rp = regime_perf[r]
            rp['wr'] = rp['wins'] / rp['total'] if rp['total'] > 0 else 0.0

        # Check strategy_dna for regime filters
        dna_filter = strategy_dna.get('regime_filters', {}).get(strat_id, {})
        worst_regimes = set()

        if dna_filter and dna_filter.get('worst_regime'):
            worst_regimes.add(dna_filter['worst_regime'])
        else:
            # Find bottom 20% WR regimes (at least 1 regime if multiple exist)
            if len(regime_perf) >= 2:
                sorted_regimes = sorted(regime_perf.items(), key=lambda x: x[1]['wr'])
                n_worst = max(1, len(sorted_regimes) // 5)  # bottom 20%
                worst_regimes = {r[0] for r in sorted_regimes[:n_worst]}

        # Filter trades
        filtered_trades = [t for t in trades if t['regime_at_entry'] not in worst_regimes]
        skipped = len(trades) - len(filtered_trades)

        if filtered_trades:
            regime_pnl = sum(t['pnl_eur'] for t in filtered_trades)
            regime_wins = sum(1 for t in filtered_trades if t['pnl_eur'] > 0)
            regime_wr = regime_wins / len(filtered_trades)
        else:
            regime_pnl = 0.0
            regime_wr = 0.0

        strat_result['regime_filtered'] = {
            'wr': round(regime_wr, 3),
            'pnl': round(regime_pnl, 2),
            'trades_skipped': skipped,
            'worst_regimes': list(worst_regimes),
        }

        # ── Determine best variant ────────────────────────────────────────
        variants = {
            'optimized_stop': opt_stop_pnl,
            'optimized_tp': opt_tp_pnl,
            'regime_filtered': regime_pnl,
        }
        best_var = max(variants, key=variants.get)
        best_pnl = variants[best_var]
        best_improvement = ((best_pnl - original_pnl) / abs(original_pnl) * 100) if original_pnl != 0 else 0.0

        if best_pnl <= original_pnl:
            strat_result['best_variant'] = 'original'
            strat_result['best_improvement_pct'] = 0.0
            best_pnl_for_system = original_pnl
        else:
            strat_result['best_variant'] = best_var
            strat_result['best_improvement_pct'] = round(best_improvement, 1)
            best_pnl_for_system = best_pnl

        result['results'][strat_id] = strat_result

        # ── System-wide tracking ──────────────────────────────────────────
        total_original_pnl += original_pnl
        total_best_pnl += best_pnl_for_system

        # Track best single improvement for recommendation
        improvement_eur = best_pnl_for_system - original_pnl
        if improvement_eur > best_single_improvement:
            best_single_improvement = improvement_eur
            strat_name = strategies.get(strat_id, {}).get('name', strat_id)
            variant_labels = {
                'optimized_stop': 'Stop 20% weiter',
                'optimized_tp': 'TP 20% höher',
                'regime_filtered': 'Regime-Filter',
                'original': 'Keine Änderung',
            }
            best_single_recommendation = (
                f'{strat_name} ({strat_id}): {variant_labels.get(best_var, best_var)} '
                f'→ +€{improvement_eur:.0f} Verbesserung'
            )

    # ── System-wide summary ───────────────────────────────────────────────
    sys_improvement = ((total_best_pnl - total_original_pnl) / abs(total_original_pnl) * 100
                       if total_original_pnl != 0 else 0.0)

    result['system_wide'] = {
        'original_pnl': round(total_original_pnl, 2),
        'optimized_pnl': round(total_best_pnl, 2),
        'improvement_pct': round(sys_improvement, 1),
        'recommendation': best_single_recommendation or 'Keine signifikanten Verbesserungen gefunden.',
    }

    # ── Save to file ──────────────────────────────────────────────────────
    try:
        backtest_path = WS / 'data/backtest_results.json'
        with open(backtest_path, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ Backtest-Ergebnisse konnten nicht gespeichert werden: {e}', file=sys.stderr)

    return result


# ─── P3.B — Strategy DNA Evolution ───────────────────────────────────────────

def evolve_strategy_dna(conn, strategies: dict) -> dict:
    """Optimiert Strategie-Parameter basierend auf historischer Performance.
    Nur für Strategien mit 5+ geschlossenen Trades.
    Returns: {
        'strategies_analyzed': int,
        'strategies_evolved': int,
        'evolutions': {
            'strategy_id': {
                'trades_analyzed': int,
                'current_params': {...},
                'recommended_params': {...},
                'expected_improvement': str,
                'confidence': 'HIGH'|'MEDIUM'|'LOW',
            }
        },
        'regime_filters': {
            'strategy_id': {
                'best_regime': str,
                'worst_regime': str,
                'recommended_filter': str,
            }
        }
    }"""

    MIN_TRADES = 5
    result = {
        'strategies_analyzed': 0,
        'strategies_evolved': 0,
        'evolutions': {},
        'regime_filters': {},
        'insufficient_data': [],
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    }

    if conn is None:
        return result

    # ── Load all closed trades grouped by strategy ────────────────────────
    try:
        rows = conn.execute(
            "SELECT id, ticker, strategy, entry_price, entry_date, shares, "
            "stop_price, target_price, close_price, close_date, pnl_eur, pnl_pct, "
            "regime_at_entry, exit_type "
            "FROM paper_portfolio WHERE status != 'OPEN' AND pnl_eur IS NOT NULL "
            "AND strategy IS NOT NULL"
        ).fetchall()
    except Exception as e:
        print(f'⚠️ Strategy DNA: DB-Fehler: {e}', file=sys.stderr)
        return result

    # Group trades by strategy
    trades_by_strat = defaultdict(list)
    for row in rows:
        trade = {
            'id': row[0], 'ticker': row[1], 'strategy': row[2],
            'entry_price': float(row[3]) if row[3] else 0.0,
            'entry_date': row[4] or '',
            'shares': float(row[5]) if row[5] else 0.0,
            'stop_price': float(row[6]) if row[6] else 0.0,
            'target_price': float(row[7]) if row[7] else 0.0,
            'close_price': float(row[8]) if row[8] else 0.0,
            'close_date': row[9] or '',
            'pnl_eur': float(row[10]) if row[10] else 0.0,
            'pnl_pct': float(row[11]) if row[11] else 0.0,
            'regime_at_entry': row[12] or 'UNKNOWN',
            'exit_type': row[13] or 'UNKNOWN',
        }
        trades_by_strat[trade['strategy']].append(trade)

    # ── Analyze each strategy with enough trades ─────────────────────────
    all_strat_ids = set(trades_by_strat.keys()) | set(strategies.keys())

    for strat_id in sorted(all_strat_ids):
        trades = trades_by_strat.get(strat_id, [])
        if len(trades) < MIN_TRADES:
            result['insufficient_data'].append(strat_id)
            continue

        result['strategies_analyzed'] += 1
        winners = [t for t in trades if t['pnl_eur'] > 0]
        losers = [t for t in trades if t['pnl_eur'] <= 0]
        win_rate = len(winners) / len(trades) if trades else 0.0

        strat_cfg = strategies.get(strat_id, {})
        evolution = {
            'trades_analyzed': len(trades),
            'wins': len(winners),
            'losses': len(losers),
            'win_rate': round(win_rate, 3),
            'current_params': {},
            'recommended_params': {},
            'findings': [],
            'expected_improvement': '',
            'confidence': 'LOW',
        }

        # ── 1. Optimaler Stop-Abstand ────────────────────────────────────
        winner_stops = []
        loser_stops = []
        for t in trades:
            if t['entry_price'] > 0 and t['stop_price'] > 0:
                stop_dist_pct = abs(t['entry_price'] - t['stop_price']) / t['entry_price'] * 100
                if t['pnl_eur'] > 0:
                    winner_stops.append(stop_dist_pct)
                else:
                    loser_stops.append(stop_dist_pct)

        current_avg_stop = 0.0
        recommended_stop = 0.0
        if winner_stops or loser_stops:
            all_stops = winner_stops + loser_stops
            current_avg_stop = sum(all_stops) / len(all_stops)
            evolution['current_params']['avg_stop_distance_pct'] = round(current_avg_stop, 2)

        if winner_stops:
            # Median of winner stops
            sorted_ws = sorted(winner_stops)
            mid = len(sorted_ws) // 2
            median_winner_stop = sorted_ws[mid] if len(sorted_ws) % 2 == 1 else (sorted_ws[mid-1] + sorted_ws[mid]) / 2
            # Add 1 ATR-buffer (approximate: +1.5% as proxy since we don't have ATR)
            atr_buffer = 1.5
            recommended_stop = median_winner_stop + atr_buffer
            evolution['recommended_params']['optimal_stop_pct'] = round(recommended_stop, 2)

            if loser_stops:
                avg_loser_stop = sum(loser_stops) / len(loser_stops)
                avg_winner_stop = sum(winner_stops) / len(winner_stops)
                if avg_loser_stop < avg_winner_stop * 0.85:
                    evolution['findings'].append(
                        f'Verlierer-Stops Ø {avg_loser_stop:.1f}% vs. Gewinner Ø {avg_winner_stop:.1f}% — Stops bei Verlierern zu eng!'
                    )
                elif avg_loser_stop > avg_winner_stop * 1.3:
                    evolution['findings'].append(
                        f'Verlierer-Stops Ø {avg_loser_stop:.1f}% vs. Gewinner Ø {avg_winner_stop:.1f}% — Verlierer-Stops zu weit'
                    )

        # ── 2. Optimaler Take-Profit ─────────────────────────────────────
        winner_gains = []
        for t in winners:
            if t['pnl_pct'] and t['pnl_pct'] > 0:
                winner_gains.append(t['pnl_pct'])

        if winner_gains:
            avg_win = sum(winner_gains) / len(winner_gains)
            max_gain_approx = max(winner_gains)  # Best proxy for max gain without intraday data
            evolution['current_params']['avg_win_pct'] = round(avg_win, 2)
            evolution['current_params']['max_win_pct'] = round(max_gain_approx, 2)

            # Recommended TP = avg of top gains × 0.8
            # Use top 50% of winners as "typical max gain"
            sorted_gains = sorted(winner_gains, reverse=True)
            top_half = sorted_gains[:max(1, len(sorted_gains) // 2)]
            avg_max_gain = sum(top_half) / len(top_half)

            recommended_tp = avg_max_gain * 0.8
            evolution['recommended_params']['optimal_tp_pct'] = round(recommended_tp, 2)

            if avg_win < avg_max_gain * 0.6:
                evolution['findings'].append(
                    f'Avg Win {avg_win:.1f}% ist nur {avg_win/avg_max_gain*100:.0f}% des Maximallaufs ({avg_max_gain:.1f}%) — Gewinne werden zu früh mitgenommen!'
                )

        # ── 3. Optimale Holding Period ────────────────────────────────────
        holding_days_profit = []
        holding_days_loss = []
        for t in trades:
            try:
                entry_dt = datetime.fromisoformat(t['entry_date'][:10])
                close_dt = datetime.fromisoformat(t['close_date'][:10])
                hd = (close_dt - entry_dt).days
                if hd < 0:
                    hd = 0
                if t['pnl_eur'] > 0:
                    holding_days_profit.append(hd)
                else:
                    holding_days_loss.append(hd)
            except (ValueError, TypeError):
                continue

        all_holding = holding_days_profit + holding_days_loss
        if all_holding:
            avg_holding = sum(all_holding) / len(all_holding)
            evolution['current_params']['avg_holding_days'] = round(avg_holding, 1)

        if holding_days_profit:
            avg_hold_win = sum(holding_days_profit) / len(holding_days_profit)
            evolution['current_params']['avg_holding_days_winners'] = round(avg_hold_win, 1)

            # Find sweet spot: group by holding period ranges
            # Ranges: 0-2d, 3-5d, 6-10d, 11-20d, 21+d
            ranges = [(0, 2), (3, 5), (6, 10), (11, 20), (21, 999)]
            range_perf = {}
            for rmin, rmax in ranges:
                range_trades = [t for t in trades if _holding_days(t) is not None and rmin <= _holding_days(t) <= rmax]
                if len(range_trades) >= 2:
                    range_wins = sum(1 for t in range_trades if t['pnl_eur'] > 0)
                    range_wr = range_wins / len(range_trades)
                    range_avg_pnl = sum(t['pnl_pct'] for t in range_trades if t['pnl_pct'] is not None) / len(range_trades)
                    label = f'{rmin}-{rmax}d' if rmax < 999 else f'{rmin}d+'
                    range_perf[label] = {'wr': round(range_wr, 3), 'avg_pnl': round(range_avg_pnl, 2), 'n': len(range_trades)}

            if range_perf:
                best_range = max(range_perf.items(), key=lambda x: x[1]['avg_pnl'])
                evolution['recommended_params']['optimal_holding_range'] = best_range[0]
                evolution['recommended_params']['holding_range_detail'] = range_perf
                evolution['findings'].append(
                    f'Sweet Spot Haltedauer: {best_range[0]} (Avg PnL: {best_range[1]["avg_pnl"]:+.1f}%, WR: {best_range[1]["wr"]:.0%}, n={best_range[1]["n"]})'
                )

        if holding_days_loss:
            avg_hold_loss = sum(holding_days_loss) / len(holding_days_loss)
            evolution['current_params']['avg_holding_days_losers'] = round(avg_hold_loss, 1)

        # ── 4. Regime-Filter ─────────────────────────────────────────────
        regime_perf = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'count': 0})
        for t in trades:
            r = t['regime_at_entry']
            regime_perf[r]['count'] += 1
            regime_perf[r]['total_pnl'] += t['pnl_pct'] if t['pnl_pct'] else 0.0
            if t['pnl_eur'] > 0:
                regime_perf[r]['wins'] += 1
            else:
                regime_perf[r]['losses'] += 1

        regime_filter = {}
        if regime_perf:
            for r, rp in regime_perf.items():
                rp['wr'] = rp['wins'] / rp['count'] if rp['count'] > 0 else 0.0
                rp['avg_pnl'] = rp['total_pnl'] / rp['count'] if rp['count'] > 0 else 0.0

            # Find best and worst regime (by win rate, min 2 trades)
            eligible_regimes = {k: v for k, v in regime_perf.items() if v['count'] >= 2}
            if eligible_regimes:
                best_r = max(eligible_regimes.items(), key=lambda x: x[1]['wr'])
                worst_r = min(eligible_regimes.items(), key=lambda x: x[1]['wr'])
                regime_filter = {
                    'best_regime': best_r[0],
                    'best_regime_wr': round(best_r[1]['wr'], 3),
                    'best_regime_trades': best_r[1]['count'],
                    'worst_regime': worst_r[0],
                    'worst_regime_wr': round(worst_r[1]['wr'], 3),
                    'worst_regime_trades': worst_r[1]['count'],
                    'regime_detail': {k: {'wr': round(v['wr'], 3), 'avg_pnl': round(v['avg_pnl'], 2), 'n': v['count']} for k, v in regime_perf.items()},
                }

                # Recommendations
                recommendations = []
                for r, rp in regime_perf.items():
                    if rp['count'] >= 2 and rp['wr'] < 0.20:
                        recommendations.append(f'NICHT traden in {r} (WR {rp["wr"]:.0%})')
                        evolution['findings'].append(f'⛔ Regime {r}: WR {rp["wr"]:.0%} bei {rp["count"]} Trades — vermeiden!')
                    elif rp['count'] >= 2 and rp['wr'] > 0.60:
                        recommendations.append(f'Optimal in {r} (WR {rp["wr"]:.0%})')
                        evolution['findings'].append(f'✅ Regime {r}: WR {rp["wr"]:.0%} bei {rp["count"]} Trades — ideal!')

                if recommendations:
                    regime_filter['recommended_filter'] = '; '.join(recommendations)
                else:
                    # Check if performance is regime-independent
                    wrs = [v['wr'] for v in eligible_regimes.values()]
                    if wrs and max(wrs) - min(wrs) < 0.20:
                        regime_filter['recommended_filter'] = 'Regime-unabhängig — "Allwetter"-Strategie'
                        evolution['findings'].append('🌤️ Regime-unabhängig — performt in allen Marktphasen ähnlich')
                    else:
                        regime_filter['recommended_filter'] = 'Keine klare Regime-Präferenz'

            result['regime_filters'][strat_id] = regime_filter

        # ── Confidence & Expected Improvement ─────────────────────────────
        n_trades = len(trades)
        if n_trades >= 15:
            evolution['confidence'] = 'HIGH'
        elif n_trades >= 8:
            evolution['confidence'] = 'MEDIUM'
        else:
            evolution['confidence'] = 'LOW'

        # Expected improvement summary
        improvements = []
        if evolution['recommended_params'].get('optimal_stop_pct') and current_avg_stop > 0:
            diff = recommended_stop - current_avg_stop
            if abs(diff) > 0.5:
                direction = 'weiter' if diff > 0 else 'enger'
                improvements.append(f'Stop {direction} ({current_avg_stop:.1f}% → {recommended_stop:.1f}%)')

        if evolution['recommended_params'].get('optimal_tp_pct'):
            improvements.append(f'TP bei {evolution["recommended_params"]["optimal_tp_pct"]:.1f}%')

        if evolution['recommended_params'].get('optimal_holding_range'):
            improvements.append(f'Haltedauer {evolution["recommended_params"]["optimal_holding_range"]}')

        evolution['expected_improvement'] = ' | '.join(improvements) if improvements else 'Keine konkreten Anpassungen empfohlen'

        # ── Kill recommendation for hopeless strategies ───────────────────
        if win_rate == 0.0 and n_trades >= 5:
            evolution['findings'].append(f'💀 DNA sagt KILL — 0% WR nach {n_trades} Trades')
            evolution['recommendation'] = 'KILL'
        elif win_rate < 0.20 and n_trades >= 5:
            evolution['findings'].append(f'⚠️ Kritisch — nur {win_rate:.0%} WR nach {n_trades} Trades')
            evolution['recommendation'] = 'REVIEW'
        elif win_rate > 0.50:
            evolution['recommendation'] = 'HEALTHY'
        else:
            evolution['recommendation'] = 'MONITOR'

        result['evolutions'][strat_id] = evolution
        result['strategies_evolved'] += 1

    # ── Save strategy_dna.json ────────────────────────────────────────────
    try:
        dna_path = WS / 'data/strategy_dna.json'
        dna_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dna_path, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f'✅ Strategy DNA geschrieben: {dna_path}')
    except Exception as e:
        print(f'⚠️ Strategy DNA Schreibfehler: {e}', file=sys.stderr)

    return result


def _holding_days(trade: dict):
    """Helper: Berechnet Haltedauer in Tagen. Returns None bei Fehler."""
    try:
        entry_dt = datetime.fromisoformat(trade['entry_date'][:10])
        close_dt = datetime.fromisoformat(trade['close_date'][:10])
        hd = (close_dt - entry_dt).days
        return max(0, hd)
    except (ValueError, TypeError, AttributeError):
        return None


# ─── P4.C — Portfolio Optimization (Mean-Variance / ERC) ─────────────────────

# Default sector return/risk assumptions (annualized)
_SECTOR_DEFAULTS = {
    'energy':      {'expected_return': 0.08, 'std_return': 0.15},
    'tech':        {'expected_return': 0.12, 'std_return': 0.25},
    'materials':   {'expected_return': 0.06, 'std_return': 0.18},
    'healthcare':  {'expected_return': 0.10, 'std_return': 0.12},
    'defense':     {'expected_return': 0.09, 'std_return': 0.14},
    'biotech':     {'expected_return': 0.11, 'std_return': 0.22},
    'industrials': {'expected_return': 0.07, 'std_return': 0.16},
    'financials':  {'expected_return': 0.07, 'std_return': 0.20},
    'other':       {'expected_return': 0.06, 'std_return': 0.18},
}

# Rough inter-sector correlation hints (negative = natural hedge)
_SECTOR_CORRELATION_BONUS = {
    frozenset({'energy', 'tech'}): -0.03,
    frozenset({'energy', 'healthcare'}): -0.02,
    frozenset({'defense', 'tech'}): -0.02,
    frozenset({'biotech', 'energy'}): -0.01,
}


def optimize_portfolio(conn, strategies: dict, market_data: dict = None) -> dict:
    """Markowitz-inspirierte Portfolio-Optimierung (ERC-Ansatz).

    Berechnet aktuelle vs. optimale Sektor-Allokation,
    generiert Rebalance-Vorschläge und einen Diversifikations-Score.
    Alles in reinem Python — kein numpy/scipy.

    Returns: {
        'current_allocation': { sector: pct, ... },
        'optimal_allocation': { sector: pct, ... },
        'rebalance_suggestions': [ { action, ticker/sector, reason, target_pct } ],
        'diversification_score': float (0-1),
        'optimal_diversification_score': float (0-1),
        'expected_portfolio_return': float,
        'expected_portfolio_risk': float,
        'sharpe_optimal': float,
    }
    """
    import statistics as _stats

    default = {
        'current_allocation': {},
        'optimal_allocation': {},
        'rebalance_suggestions': [],
        'diversification_score': 0.0,
        'optimal_diversification_score': 0.0,
        'expected_portfolio_return': 0.0,
        'expected_portfolio_risk': 0.0,
        'sharpe_optimal': 0.0,
    }

    if conn is None:
        default['error'] = 'Keine DB-Verbindung'
        return default

    # ── 1. Aktuelle Allokation (offene Positionen) ────────────────────────
    try:
        open_rows = conn.execute(
            "SELECT ticker, strategy, entry_price, shares, sector "
            "FROM paper_portfolio WHERE status = 'OPEN'"
        ).fetchall()
    except Exception as e:
        default['error'] = f'DB-Fehler (open): {e}'
        return default

    if not open_rows:
        default['error'] = 'Keine offenen Positionen'
        return default

    # Build current allocation by normalized sector
    sector_invested = defaultdict(float)
    ticker_sector_map = {}  # ticker -> normalized sector
    total_invested = 0.0

    for row in open_rows:
        ticker = row[0] or 'UNKNOWN'
        strategy = row[1] or ''
        entry_price = float(row[2]) if row[2] else 0.0
        shares = float(row[3]) if row[3] else 0.0
        raw_sector = row[4] or ''

        invested = entry_price * shares
        if invested <= 0:
            continue

        # Normalize sector using existing helper + strategies.json
        strat_data = strategies.get(strategy, {})
        strat_sector = strat_data.get('sector', '')
        norm_sector = _classify_sector(raw_sector or strat_sector, ticker, strategy)

        sector_invested[norm_sector] += invested
        ticker_sector_map[ticker] = norm_sector
        total_invested += invested

    if total_invested <= 0:
        default['error'] = 'Investiertes Volumen = 0'
        return default

    current_allocation = {}
    for sector, inv in sector_invested.items():
        current_allocation[sector] = round(inv / total_invested, 4)

    # ── 2. Historische Returns pro Sektor (aus geschlossenen Trades) ──────
    sector_returns = defaultdict(list)  # sector -> [pnl_pct, ...]
    try:
        closed_rows = conn.execute(
            "SELECT ticker, strategy, sector, pnl_pct "
            "FROM paper_portfolio WHERE status = 'CLOSED' AND pnl_pct IS NOT NULL"
        ).fetchall()
    except Exception:
        closed_rows = []

    for row in closed_rows:
        ticker = row[0] or ''
        strategy = row[1] or ''
        raw_sector = row[2] or ''
        pnl_pct = float(row[3]) if row[3] is not None else 0.0

        strat_data = strategies.get(strategy, {})
        strat_sector = strat_data.get('sector', '')
        norm_sector = _classify_sector(raw_sector or strat_sector, ticker, strategy)
        sector_returns[norm_sector].append(pnl_pct / 100.0)  # convert to decimal

    # Build sector stats: use real data if >= 5 trades, else defaults
    sector_stats = {}
    all_sectors = set(current_allocation.keys())
    # Also include sectors with historical data (potential ADD candidates)
    for s in sector_returns:
        all_sectors.add(s)
    # Always include standard sectors so optimizer can suggest ADDs
    for s in ('energy', 'tech', 'materials', 'healthcare', 'defense'):
        all_sectors.add(s)
    all_sectors.discard('other')
    all_sectors.discard('unknown')

    uses_defaults = False
    for sector in all_sectors:
        returns = sector_returns.get(sector, [])
        if len(returns) >= 5:
            avg_r = sum(returns) / len(returns)
            # Annualize: assume avg trade ~ 10 days → ~25 trades/year
            annual_return = avg_r * 25
            if len(returns) > 1:
                std_r = _stats.stdev(returns)
                annual_std = std_r * math.sqrt(25)
            else:
                annual_std = _SECTOR_DEFAULTS.get(sector, _SECTOR_DEFAULTS['other'])['std_return']
            sector_stats[sector] = {
                'expected_return': round(annual_return, 4),
                'std_return': round(max(annual_std, 0.01), 4),  # floor at 1%
                'data_source': 'historical',
                'trade_count': len(returns),
            }
        else:
            uses_defaults = True
            defaults = _SECTOR_DEFAULTS.get(sector, _SECTOR_DEFAULTS['other'])
            sector_stats[sector] = {
                'expected_return': defaults['expected_return'],
                'std_return': defaults['std_return'],
                'data_source': 'default',
                'trade_count': len(returns),
            }

    # ── 3. Equal Risk Contribution (ERC) Optimization ─────────────────────
    # Goal: each sector contributes equal risk (weight × std_return = const)
    # Iterative algorithm without numpy

    opt_sectors = list(sector_stats.keys())
    n = len(opt_sectors)

    if n == 0:
        default['current_allocation'] = current_allocation
        default['diversification_score'] = _calc_hhi_score(current_allocation)
        default['error'] = 'Keine Sektoren für Optimierung'
        return default

    # Start with equal weights
    weights = {s: 1.0 / n for s in opt_sectors}

    # Iterative ERC
    for _iteration in range(30):
        # Calculate risk contributions
        risk_contributions = {}
        total_risk = 0.0
        for s in opt_sectors:
            rc = weights[s] * sector_stats[s]['std_return']
            risk_contributions[s] = rc
            total_risk += rc

        if total_risk <= 0:
            break

        target_rc = total_risk / n

        # Adjust weights
        new_weights = {}
        for s in opt_sectors:
            rc = risk_contributions[s]
            std = sector_stats[s]['std_return']
            if std <= 0:
                new_weights[s] = weights[s]
                continue

            # Move weight toward target risk contribution
            # target_rc = new_weight * std → new_weight = target_rc / std
            ideal_weight = target_rc / std
            # Damped update (0.3 learning rate for stability)
            new_weights[s] = weights[s] * 0.7 + ideal_weight * 0.3

        # Normalize to sum = 1
        total_w = sum(new_weights.values())
        if total_w > 0:
            weights = {s: w / total_w for s, w in new_weights.items()}

    # Apply return-based tilt: boost high-return sectors slightly
    # This bridges ERC (pure risk parity) toward mean-variance
    avg_expected = sum(sector_stats[s]['expected_return'] for s in opt_sectors) / n if n > 0 else 0
    for s in opt_sectors:
        excess = sector_stats[s]['expected_return'] - avg_expected
        # Tilt up to ±20% of weight based on return advantage
        tilt = excess * 0.5  # moderate tilt
        weights[s] = max(0.02, weights[s] * (1 + tilt))

    # Re-normalize
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {s: round(w / total_w, 4) for s, w in weights.items()}

    # Filter out tiny allocations (< 3%) and redistribute
    significant = {s: w for s, w in weights.items() if w >= 0.03}
    if significant:
        total_sig = sum(significant.values())
        optimal_allocation = {s: round(w / total_sig, 4) for s, w in significant.items()}
    else:
        optimal_allocation = weights

    # ── 4. Expected portfolio return and risk ─────────────────────────────
    exp_return = sum(
        optimal_allocation.get(s, 0) * sector_stats[s]['expected_return']
        for s in optimal_allocation
    )
    # Simplified portfolio risk (assuming low correlation ≈ 0.3 between sectors)
    avg_corr = 0.3
    port_variance = 0.0
    opt_list = list(optimal_allocation.items())
    for i, (s1, w1) in enumerate(opt_list):
        std1 = sector_stats.get(s1, {}).get('std_return', 0.15)
        port_variance += (w1 * std1) ** 2
        for j in range(i + 1, len(opt_list)):
            s2, w2 = opt_list[j]
            std2 = sector_stats.get(s2, {}).get('std_return', 0.15)
            # Check for specific correlation adjustments
            pair = frozenset({s1, s2})
            corr = avg_corr + _SECTOR_CORRELATION_BONUS.get(pair, 0)
            port_variance += 2 * w1 * w2 * std1 * std2 * corr

    port_risk = math.sqrt(max(port_variance, 0))
    risk_free = 0.045  # 4.5% US 10Y
    sharpe_optimal = (exp_return - risk_free) / port_risk if port_risk > 0 else 0

    # Current portfolio metrics for comparison
    cur_return = sum(
        current_allocation.get(s, 0) * sector_stats.get(s, _SECTOR_DEFAULTS.get(s, _SECTOR_DEFAULTS['other']))['expected_return']
        for s in current_allocation
    )
    cur_variance = 0.0
    cur_list = list(current_allocation.items())
    for i, (s1, w1) in enumerate(cur_list):
        std1 = sector_stats.get(s1, {}).get('std_return', 0.15)
        cur_variance += (w1 * std1) ** 2
        for j in range(i + 1, len(cur_list)):
            s2, w2 = cur_list[j]
            std2 = sector_stats.get(s2, {}).get('std_return', 0.15)
            pair = frozenset({s1, s2})
            corr = avg_corr + _SECTOR_CORRELATION_BONUS.get(pair, 0)
            cur_variance += 2 * w1 * w2 * std1 * std2 * corr
    cur_risk = math.sqrt(max(cur_variance, 0))
    sharpe_current = (cur_return - risk_free) / cur_risk if cur_risk > 0 else 0

    # ── 5. Diversification Score (HHI-based) ──────────────────────────────
    div_score_current = _calc_hhi_score(current_allocation)
    div_score_optimal = _calc_hhi_score(optimal_allocation)

    # Correlation bonus: pairs of sectors that hedge each other
    corr_bonus = 0.0
    cur_sectors = set(current_allocation.keys())
    for pair, bonus in _SECTOR_CORRELATION_BONUS.items():
        if pair.issubset(cur_sectors) and bonus < 0:
            corr_bonus += abs(bonus) * 2  # small bonus for natural hedges
    div_score_current = min(1.0, round(div_score_current + corr_bonus, 4))

    opt_sectors_set = set(optimal_allocation.keys())
    corr_bonus_opt = 0.0
    for pair, bonus in _SECTOR_CORRELATION_BONUS.items():
        if pair.issubset(opt_sectors_set) and bonus < 0:
            corr_bonus_opt += abs(bonus) * 2
    div_score_optimal = min(1.0, round(div_score_optimal + corr_bonus_opt, 4))

    # ── 6. Rebalance Suggestions ──────────────────────────────────────────
    suggestions = []
    all_rebalance_sectors = set(current_allocation.keys()) | set(optimal_allocation.keys())

    for sector in sorted(all_rebalance_sectors):
        cur_pct = current_allocation.get(sector, 0)
        opt_pct = optimal_allocation.get(sector, 0)
        diff = opt_pct - cur_pct

        if abs(diff) < 0.05:
            continue  # Less than 5% difference — skip

        if cur_pct == 0 and opt_pct > 0:
            action = 'ADD'
            reason = f'aktuell 0%, optimal {opt_pct:.0%} — unterrepräsentiert'
        elif opt_pct == 0 and cur_pct > 0:
            action = 'REMOVE'
            reason = f'aktuell {cur_pct:.0%}, nicht im optimalen Portfolio'
        elif diff > 0:
            action = 'INCREASE'
            reason = f'{cur_pct:.0%} → {opt_pct:.0%}'
            # Add context
            stats = sector_stats.get(sector, {})
            if stats.get('expected_return', 0) > avg_expected:
                reason += f' (überdurchschnittliche Rendite: {stats["expected_return"]:.0%})'
            elif cur_pct > 0.40:
                reason += ' (Risiko-Diversifikation)'
        else:  # diff < 0
            action = 'DECREASE'
            reason = f'{cur_pct:.0%} → {opt_pct:.0%}'
            if cur_pct > 0.40:
                reason += ' (Klumpenrisiko!)'
            elif cur_pct > 0.25:
                reason += ' (konzentriert)'

        suggestions.append({
            'action': action,
            'sector': sector,
            'reason': reason,
            'current_pct': round(cur_pct, 4),
            'target_pct': round(opt_pct, 4),
        })

    # Sort: DECREASE/REMOVE first, then INCREASE/ADD
    action_order = {'DECREASE': 0, 'REMOVE': 1, 'INCREASE': 2, 'ADD': 3}
    suggestions.sort(key=lambda x: action_order.get(x['action'], 4))

    result = {
        'current_allocation': current_allocation,
        'optimal_allocation': optimal_allocation,
        'rebalance_suggestions': suggestions,
        'diversification_score': div_score_current,
        'diversification_score_current': div_score_current,
        'optimal_diversification_score': div_score_optimal,
        'diversification_score_optimal': div_score_optimal,
        'expected_portfolio_return': round(exp_return, 4),
        'expected_return_pct': round(exp_return * 100, 2),
        'expected_portfolio_risk': round(port_risk, 4),
        'expected_risk_pct': round(port_risk * 100, 2),
        'sharpe_current': round(sharpe_current, 2),
        'sharpe_optimal': round(sharpe_optimal, 2),
        'sector_stats': sector_stats,
    }

    # BUG 4: Warn if optimal Sharpe < current (due to default returns)
    if sharpe_optimal < sharpe_current and uses_defaults:
        result['sharpe_note'] = (
            'Optimierung basiert teilweise auf Default-Returns — '
            'mehr Trade-Daten nötig für verlässliche Optimierung'
        )

    return result


def _calc_hhi_score(allocation: dict) -> float:
    """HHI-based diversification score. 0 = concentrated, 1 = perfect."""
    if not allocation:
        return 0.0
    hhi = sum(w ** 2 for w in allocation.values())
    return round(1 - hhi, 4)


def _enrich_position_sizing(position_sizing: dict) -> dict:
    """Adds 'actionable' field: only strategies with real Kelly data (tradeable=True, not Default)."""
    if not position_sizing or not position_sizing.get('default_sizes'):
        return position_sizing
    actionable = {}
    for strat_id, sizing in position_sizing.get('default_sizes', {}).items():
        reason = sizing.get('reason', '')
        if sizing.get('tradeable', False) and 'Default' not in reason and 'Zu wenige' not in reason:
            actionable[strat_id] = sizing
    position_sizing['actionable'] = actionable
    return position_sizing


# ─── CEO-Direktive zusammenbauen ─────────────────────────────────────────────

def build_directive(sources: dict, hist: dict, health: dict,
                    risk_metrics: dict = None, concentration: dict = None,
                    position_sizing: dict = None,
                    live_market_data: dict = None, conn=None) -> dict:
    """Baut die vollständige CEO-Direktive."""

    regime = sources.get('regime', {})
    strategies = sources.get('strategies', {})

    # VIX und Regime: Live-Daten haben Vorrang
    regime_detail = None
    if live_market_data and not live_market_data.get('vix', {}).get('error'):
        regime_detail = classify_regime(live_market_data)
        vix = regime_detail['vix']
        regime_type = regime_detail['overall']
    else:
        vix = regime.get('indicators', {}).get('vix', 25.0)
        regime_type = regime.get('regime', 'TREND_DOWN')

    # P2.C: Erweiterte Geo-Intel (ersetzt estimate_geo_score)
    geo_intel = calculate_geo_intel(sources, conn)
    geo_score = geo_intel['geo_score']

    # P2.D: Stress-Tests
    stress_tests = run_stress_tests(conn, vix, strategies)

    # P3.A: Post-Mortem Analyzer
    postmortem = analyze_trade_postmortems(conn)

    # P3.B: Strategy DNA Evolution
    strategy_dna = evolve_strategy_dna(conn, strategies)

    # P4.D: Backtesting Engine
    backtest_results = run_backtest(conn, strategies)

    # P4.C: Portfolio Optimization
    portfolio_opt = optimize_portfolio(conn, strategies, market_data=live_market_data)

    # P3.C: Anomaly Detection
    anomaly_result = detect_anomalies(conn, market_data=live_market_data)

    # P4.A: Adaptive VIX Thresholds
    adaptive_thresholds = calculate_adaptive_thresholds(
        conn, current_vix=vix, market_data=live_market_data)

    # P4.B: Multi-Timeframe Analysis
    multi_timeframe = analyze_multi_timeframe(market_data=live_market_data)

    # Trading-Mode bestimmen (P1.A + P2.B + P4.A + P4.B)
    mode, mode_reason = determine_trading_mode(
        vix=vix,
        geo_score=geo_score,
        win_rate_7d=hist['recent_win_rate_7d'],
        drawdown=hist['portfolio_drawdown'],
        consecutive_loss_days=hist['consecutive_loss_days'],
        risk_metrics=risk_metrics,
        regime_detail=regime_detail,
        anomaly_result=anomaly_result,
        adaptive_thresholds=adaptive_thresholds,
        multi_timeframe=multi_timeframe,
    )

    # Trading-Rules (P1.B + P4.B: mit concentration + multi_timeframe)
    rules = build_trading_rules(mode, vix, hist['strategy_performance'], strategies,
                                concentration=concentration,
                                multi_timeframe=multi_timeframe,
                                regime_detail=regime_detail)

    # Top-Opportunitäten
    top_opps = find_top_opportunities(mode, strategies, hist['strategy_performance'])

    # CEO-Notizen generieren
    ceo_notes = _generate_ceo_notes(mode, vix, hist, regime_type)

    # Direktive zusammenbauen
    directive = {
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'mode': mode,
        'mode_reason': mode_reason,
        'vix': round(vix, 1),
        'regime': regime_type,
        'geo_alert_level': 'HIGH' if geo_score > 60 else 'MEDIUM' if geo_score > 30 else 'LOW',
        'geo_score': round(geo_score, 0),

        # REAL TRADING — bleibt konservativ (CEO-Regeln gelten)
        'trading_rules': rules,

        # PAPER LAB — volle Freiheit, Experimental Mode
        'paper_lab': {
            'mode': 'EXPERIMENTAL',
            'description': 'Paper Lab testet alles — auch schwache Setups und hohes Risiko',
            'max_new_positions_per_run': 15,
            'min_conviction_score': 1,        # Auch Score 1-2 wird getestet (statt 4+)
            'ignore_vix_limit': True,          # Tradet auch bei VIX 40+
            'ignore_regime': True,             # Tradet auch in CRASH
            'blocked_strategies': [],          # Nichts geblockt
            'max_position_size_eur': 3000,     # Höhere Einzelpositionsgröße
            'stop_factor': 1.0,                # Normaler Stop (nicht enger)
            'risk_mode': 'HIGH',               # Explizit: hohes Risiko erlaubt
            'experimental_strategies': True,   # Auch Strategien mit health='testing'
        },

        'system_health': {
            'score': health['score'],
            'errors': health['errors'],
            'warnings': health['warnings'],
        },

        'learning_status': {
            'overall_win_rate': round(hist['overall_win_rate'], 3),
            'win_rate_7d': round(hist['recent_win_rate_7d'], 3),
            'win_rate_30d': round(hist['recent_win_rate_30d'], 3),
            'best_strategy': hist['best_strategy'],
            'worst_strategy': hist['worst_strategy'],
            'total_closed_trades': hist['total_closed_trades'],
            'open_positions': hist['open_positions'],
            'portfolio_drawdown': round(hist['portfolio_drawdown'], 3),
            'p1_features_active': health['p1_features_active'],
            'data_quality_score': _calc_data_quality(hist, health),
        },

        'top_opportunities': top_opps,

        'ceo_notes': ceo_notes,

        # P1.A — Risk-Adjusted Metrics
        'risk_metrics': risk_metrics if risk_metrics else {},

        # P1.B — Portfolio Concentration
        'portfolio_concentration': concentration if concentration else {},

        # P1.C — Position Sizing (with actionable filter for report)
        'position_sizing': _enrich_position_sizing(position_sizing) if position_sizing else {},

        # P2.A/B — Live Market Data & Regime Detail
        'regime_detail': regime_detail if regime_detail else {},
        'live_data_available': live_market_data is not None and not live_market_data.get('vix', {}).get('error'),

        # P2.C — Geo-Intel (erweitert)
        'geo_intel': geo_intel,

        # P2.D — Stress-Tests
        'stress_tests': stress_tests,

        # P3.C — Anomaly Detection
        'anomalies': anomaly_result,

        # P3.A — Post-Mortem Summary
        'postmortem_summary': {
            'total_analyzed': postmortem.get('total_analyzed', 0),
            'avg_entry_quality': postmortem.get('avg_entry_quality', 0),
            'avg_exit_quality': postmortem.get('avg_exit_quality', 0),
            'disposition_effect': postmortem.get('disposition_effect', 0),
            'avg_win_holding_days': postmortem.get('avg_win_holding_days', 0),
            'avg_loss_holding_days': postmortem.get('avg_loss_holding_days', 0),
            'regime_performance': postmortem.get('regime_performance', {}),
            'top_insights': postmortem.get('insights', [])[:3],
        },

        # P3.B — Strategy DNA Evolution
        'strategy_dna': strategy_dna,

        # P4.D — Backtesting Engine
        'backtest_summary': {
            'strategies_tested': backtest_results.get('strategies_tested', 0),
            'results': backtest_results.get('results', {}),
            'system_wide': backtest_results.get('system_wide', {}),
            'timestamp': backtest_results.get('timestamp', ''),
        },

        # P4.C — Portfolio Optimization
        'portfolio_optimization': portfolio_opt,

        # P4.A — Adaptive VIX Thresholds
        'adaptive_thresholds': adaptive_thresholds,

        # P4.B — Multi-Timeframe Analysis
        'multi_timeframe': multi_timeframe,

        # Signal Tracker Intelligence
        'signal_tracker': hist.get('signal_tracker'),
    }

    return directive


def _generate_ceo_notes(mode: str, vix: float, hist: dict, regime: str) -> str:
    """Generiert situative CEO-Notizen."""
    notes = []

    if mode == 'SHUTDOWN':
        notes.append('System im SHUTDOWN-Modus. Keine neuen Positionen öffnen.')
    elif mode == 'DEFENSIVE':
        notes.append(f'VIX {vix:.1f} — erhöhte Volatilität. Stops erweitern.')
        if vix > 28:
            notes.append('Tech-Positionen (NVDA, PLTR, MSFT) nur halten, nicht ausbauen.')
    elif mode == 'AGGRESSIVE':
        notes.append('Niedrige Volatilität + starke Performance — Chance nutzen.')

    if hist['consecutive_loss_days'] >= 2:
        notes.append(f'⚠️ {hist["consecutive_loss_days"]} Verlust-Tage in Folge — Position Sizing reduzieren.')

    if hist['total_closed_trades'] < 30:
        notes.append(f'Datenbasis noch klein ({hist["total_closed_trades"]} Trades) — keine statistischen Garantien.')

    if 'TREND_DOWN' in regime or 'CRASH' in regime:
        notes.append('Abwärtstrend aktiv — S&P unter MA200 = kein Growth-Long.')

    # Kontext-bewusste Notizen
    from datetime import datetime
    from zoneinfo import ZoneInfo as _ZI
    now = datetime.now(_ZI('Europe/Berlin'))
    weekday = now.weekday()  # 0=Mo
    
    # Wochenende
    if weekday == 4:  # Freitag
        notes.append('Freitag — Wochenend-Risiko prüfen. RSI >75 + Wochenende = Gefahr.')

    return ' | '.join(notes) if notes else 'Standardbetrieb.'


def _calc_data_quality(hist: dict, health: dict) -> int:
    """Berechnet einen Data-Quality-Score (0–100)."""
    score = 100
    if hist['total_closed_trades'] < 10: score -= 30
    elif hist['total_closed_trades'] < 30: score -= 15
    if health['journal_entries'] < 5: score -= 20
    elif health['journal_entries'] < 20: score -= 10
    if not health['p1_features_active']: score -= 15
    return max(0, min(100, score))


# ─── Discord-Report generieren (kompakt, <1900 Zeichen) ──────────────────────

def generate_report(directive: dict, hist: dict) -> str:
    """Generiert den kompakten Discord-Tagesbriefing-Text für Victor (<1900 Zeichen)."""

    mode = directive['mode']
    vix = directive['vix']
    regime = directive['regime']

    mode_labels = {
        'AGGRESSIVE': 'AGGRESSIV',
        'NORMAL': 'NORMAL',
        'DEFENSIVE': 'DEFENSIV',
        'SHUTDOWN': 'SHUTDOWN',
    }
    mode_label = mode_labels.get(mode, mode)

    # Performance data
    wr_overall = directive['learning_status']['overall_win_rate']
    total_trades = directive['learning_status']['total_closed_trades']
    open_pos = directive['learning_status']['open_positions']
    drawdown = directive['learning_status']['portfolio_drawdown']

    rm = directive.get('risk_metrics', {}).get('overall', {})
    sharpe = rm.get('sharpe_ratio', 0)
    pf = rm.get('profit_factor', 0)
    crv = rm.get('crv', 0)
    expectancy = rm.get('expectancy', 0)

    # Regime detail
    regime_detail = directive.get('regime_detail', {})
    spy_vs = regime_detail.get('spy_vs_ma200', 0)
    leaders = regime_detail.get('sector_leaders', [])
    laggards = regime_detail.get('sector_laggards', [])

    # Rules
    rules = directive['trading_rules']
    max_pos = rules.get('max_new_positions_today', 0)
    max_size = rules.get('max_position_size_eur', 0)
    allowed = rules.get('allowed_strategies', [])
    blocked = rules.get('blocked_strategies', [])

    # Stress tests
    st = directive.get('stress_tests', {})
    risk_rating = st.get('risk_rating', 'N/A')

    # Build compact sections (order = priority, cut from bottom if too long)
    sections = []

    # 1. Header
    sections.append('🎩 **TradeMind CEO — Tagesbriefing**')

    # 2. Status block
    leaders_str = ', '.join(s.title() for s in leaders[:3]) if leaders else 'N/A'
    laggards_str = ', '.join(s.title() for s in laggards[:3]) if laggards else 'N/A'
    sections.append(
        f'📊 {mode_label} | VIX {vix:.1f} | {regime} | SPY {spy_vs:+.1f}% vs MA200\n'
        f'🟢 Leaders: {leaders_str} | 🔴 Laggards: {laggards_str}\n'
        f'📈 WR {wr_overall:.0%} | Sharpe {sharpe:.2f} | PF {pf:.2f} | CRV {crv:.2f} | €{expectancy:.0f}/Trade\n'
        f'📦 {open_pos} offen | {total_trades} geschl. | DD {drawdown:.1%} | Risk: {risk_rating}'
    )

    # 3. Directive
    top_opps = directive.get('top_opportunities', [])
    top_str = ' | '.join(
        f'{o["strategy"]} {o["name"][:15]} ({o["win_rate"]:.0%} WR)' for o in top_opps[:2]
    ) if top_opps else 'N/A'
    sections.append(
        f'**Direktive:** Max {max_pos} neu (€{max_size:,.0f}) | {len(allowed)} erlaubt, {len(blocked)} geblockt\n'
        f'**Top:** {top_str}'
    )

    # 4. Kelly (only actionable, no defaults)
    ps = directive.get('position_sizing', {})
    actionable = ps.get('actionable', {})
    if actionable:
        kelly_parts = []
        for strat_id, sizing in sorted(actionable.items()):
            size = sizing.get('recommended_size_eur', 0)
            pct = sizing.get('vix_adjusted_pct', 0) or sizing.get('half_kelly_pct', 0)
            kelly_parts.append(f'{strat_id} €{size:,.0f} ({pct:.1%})')
        # Also show negative Kelly strategies (tradeable=False, kelly negative)
        all_sizes = ps.get('default_sizes', {})
        for strat_id, sizing in sorted(all_sizes.items()):
            if not sizing.get('tradeable', True) and sizing.get('kelly_pct', 0) < 0:
                kelly_parts.append(f'{strat_id} ❌ neg.')
        if kelly_parts:
            sections.append(f'📐 **Kelly:** {" | ".join(kelly_parts[:4])}')

    # 5. Compact sections
    # Portfolio concentration
    pc = directive.get('portfolio_concentration', {})
    if pc and pc.get('sector_weights'):
        top_sectors = sorted(pc['sector_weights'].items(), key=lambda x: -x[1])[:3]
        sec_parts = [f'{s.title()} {w:.0%}' + (' ⚠️' if w > 0.40 else '') for s, w in top_sectors]
        sections.append(f'⚖️ HHI {pc.get("hhi", 0):.2f} | {" | ".join(sec_parts)}')

    # Geo-Intel
    gi = directive.get('geo_intel', {})
    if gi and gi.get('geo_score') is not None:
        hotspots = '/'.join(gi.get('geo_hotspots', [])[:2]) or 'Keine'
        trump = gi.get('trump_signal', 'NEUTRAL')
        trend = gi.get('geo_trend', 'STABLE')
        sections.append(f'🌍 Geo {gi["geo_score"]:.0f} {trend} | {hotspots} | Trump: {trump}')

    # Stress tests
    if st and st.get('open_positions_count', 0) > 0:
        max_loss = st.get('max_portfolio_loss_all_stops', 0)
        max_loss_pct = st.get('max_portfolio_loss_pct', 0)
        scenarios = st.get('scenarios', {})
        iran = scenarios.get('iran_peace_deal', {})
        iran_str = f' | Iran Deal €{iran.get("impact_eur", 0):+,.0f}' if iran else ''
        sections.append(f'🔥 Stress: Max -€{max_loss:,.0f} ({max_loss_pct:.1f}%){iran_str}')

    # Anomalies
    anom = directive.get('anomalies', {})
    if anom and anom.get('anomaly_count', 0) > 0:
        anom_parts = []
        for a in sorted(anom.get('anomalies', []), key=lambda x: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}.get(x.get('severity', 'LOW'), 3))[:3]:
            desc = a.get('description', '')
            # Shorten description
            if len(desc) > 40:
                desc = desc[:55] + '...'
            anom_parts.append(desc)
        sections.append(f'🔍 Anomalien: {" | ".join(anom_parts[:2])}')

    # Post-Mortem
    pm = directive.get('postmortem_summary', {})
    if pm and pm.get('total_analyzed', 0) > 0:
        disp = pm.get('disposition_effect', 0)
        disp_label = 'Anti-Disposition ✅' if disp < -0.15 else ('Disposition ⚠️' if disp > 0.15 else 'Ausgeglichen')
        sections.append(f'🔬 Post-Mortem: Entry {pm["avg_entry_quality"]:.1f} | Exit {pm["avg_exit_quality"]:.1f} | {disp_label}')

    # Strategy DNA
    dna = directive.get('strategy_dna', {})
    if dna and dna.get('evolutions'):
        dna_parts = []
        for strat_id, evo in sorted(dna.get('evolutions', {}).items()):
            rec = evo.get('recommendation', 'MONITOR')
            opt_stop = evo.get('recommended_params', {}).get('optimal_stop_pct')
            if rec == 'KILL':
                dna_parts.append(f'{strat_id} KILL')
            elif opt_stop:
                dna_parts.append(f'{strat_id} Stop→{opt_stop:.1f}%')
        if dna_parts:
            sections.append(f'🧬 DNA: {" | ".join(dna_parts[:3])}')

    # Backtest (lower priority — will be cut first)
    bt = directive.get('backtest_summary', {})
    if bt and bt.get('strategies_tested', 0) > 0:
        sw = bt.get('system_wide', {})
        imp = sw.get('improvement_pct', 0)
        rec = sw.get('recommendation', '')
        rec_short = rec.split('→')[0].strip()[-30:] if '→' in rec else rec[:30]
        sections.append(f'🔄 Backtest: {imp:+.0f}% PnL möglich | {rec_short}')

    # MTF (lower priority)
    mtf = directive.get('multi_timeframe', {})
    if mtf and mtf.get('spy', {}).get('alignment', 'MIXED') != 'MIXED':
        spy_tf = mtf.get('spy', {})
        bias = mtf.get('trading_bias', 'NEUTRAL')
        # Find sector highlights
        sec_highlights = []
        for sec_name, sec_data in sorted(mtf.get('sectors', {}).items()):
            sa = sec_data.get('alignment', 'MIXED')
            if sa == 'ALIGNED_BULL':
                sec_highlights.append(f'{sec_name.title()} BULL ✅')
            elif sa == 'ALIGNED_BEAR':
                sec_highlights.append(f'{sec_name.title()} BEAR ❌')
        sec_str = ' | '.join(sec_highlights[:2]) if sec_highlights else ''
        parts = [f'SPY {spy_tf.get("alignment", "MIXED")}']
        if sec_str:
            parts.append(sec_str)
        parts.append(f'Bias {bias}')
        sections.append(f'📊 MTF: {" | ".join(parts)}')

    # Adaptive VIX (lowest priority)
    at = directive.get('adaptive_thresholds', {})
    if at and at.get('vix_30d_avg', 0) > 0:
        z_score = at.get('current_vix_zscore', 0)
        avg_30d = at.get('vix_30d_avg', 0)
        def_thresh = at.get('vix_defensive_threshold', 28)
        sections.append(f'🎯 VIX adaptiv: DEF ab {def_thresh:.1f} | Z {z_score:+.1f} | 30d Ø{avg_30d:.1f}')

    # Signal Tracker
    sig_tracker = hist.get('signal_tracker')
    if sig_tracker and sig_tracker.get('total', 0) > 0:
        st = sig_tracker
        acc_str = f"{st['accuracy']:.0f}%" if st.get('accuracy') is not None else '?'
        sections.append(f"📡 Signals: {st['total']} total | ⏳{st['pending']} | ✅{st['wins']}/{st['wins']+st['losses']} ({acc_str})")

    # CEO note
    ceo_notes = directive.get('ceo_notes', '')
    if ceo_notes and ceo_notes != 'Standardbetrieb.':
        sections.append(f'📝 {ceo_notes}')

    # Assemble report, cutting from bottom if too long
    report = '\n'.join(sections)
    while len(report) > 1900 and len(sections) > 5:
        # Remove second-to-last section (keep CEO note at end)
        sections.pop(-2)
        report = '\n'.join(sections)

    assert len(report) <= 1900, f"Report zu lang: {len(report)}"
    return report


def generate_report_full(directive: dict, hist: dict) -> str:
    """Generiert den vollständigen Discord-Tagesbriefing-Text (für --full Flag)."""

    mode = directive['mode']
    vix = directive['vix']
    regime = directive['regime']
    health_score = directive['system_health']['score']

    # Mode-Label mit Emoji
    mode_labels = {
        'AGGRESSIVE': '🚀 AGGRESSIV',
        'NORMAL': '🟢 NORMAL',
        'DEFENSIVE': '🛡️ DEFENSIV',
        'SHUTDOWN': '🔴 SHUTDOWN',
    }
    mode_label = mode_labels.get(mode, mode)

    # Performance-Zahlen
    wr_overall = directive['learning_status']['overall_win_rate']
    wr_7d = directive['learning_status']['win_rate_7d']
    drawdown = directive['learning_status']['portfolio_drawdown']
    best_strat = directive['learning_status']['best_strategy']
    worst_strat = directive['learning_status']['worst_strategy']
    total_trades = directive['learning_status']['total_closed_trades']
    open_pos = directive['learning_status']['open_positions']

    best_perf = hist['strategy_performance'].get(best_strat, {})
    worst_perf = hist['strategy_performance'].get(worst_strat, {})
    best_wr = best_perf.get('win_rate', 0)
    worst_wr = worst_perf.get('win_rate', 0)

    # Benchmark-Gap
    bench_gap = hist.get('paper_benchmark_gap', 0)
    bench_str = f'{bench_gap:+.1f}% vs SPY' if bench_gap != 0 else 'vs SPY N/A'

    # Direktive-Details
    rules = directive['trading_rules']
    max_pos = rules.get('max_new_positions_today', 0)
    max_size = rules.get('max_position_size_eur', 0)
    stop_factor = rules.get('stop_tightening_factor', 1.0)
    allowed = rules.get('allowed_strategies', [])
    blocked = rules.get('blocked_strategies', [])

    # Allowed/Blocked kurzfassen
    allowed_str = ', '.join(allowed[:5]) if allowed else 'Keine'
    blocked_str = ', '.join(blocked[:5]) if blocked else 'Keine'
    if len(blocked) > 5:
        blocked_str += f' +{len(blocked)-5} weitere'

    # Warnungen
    warnings = directive['system_health']['warnings']
    errors = directive['system_health']['errors']

    # P1-Features
    p1_active = directive['learning_status']['p1_features_active']
    p1_str = '✅' if p1_active else '⏸️'

    # Top Opportunities
    opps = directive.get('top_opportunities', [])
    opp_lines = []
    for opp in opps:
        tickers_str = ', '.join(opp['tickers']) if opp['tickers'] else 'N/A'
        opp_lines.append(f"  • {opp['name']} ({opp['strategy']}) — {tickers_str} | WR: {opp['win_rate']:.0%}")

    # CEO-Notizen
    ceo_notes = directive.get('ceo_notes', '')

    # P2.B — Regime Detail
    regime_detail = directive.get('regime_detail', {})
    live_data = directive.get('live_data_available', False)

    regime_line = f'📊 **System-Status:** {mode_label} (VIX {vix:.1f} | Regime: {regime})'
    if regime_detail and live_data:
        spy_vs = regime_detail.get('spy_vs_ma200', 0)
        spy_dir = '+' if spy_vs >= 0 else ''
        leaders = regime_detail.get('sector_leaders', [])
        laggards = regime_detail.get('sector_laggards', [])
        regime_line += f'\n📡 **Live-Regime:** {regime} (SPY {spy_dir}{spy_vs:.1f}% vs MA200 | Trend: {regime_detail.get("spy_trend", "?")})'
        if leaders:
            regime_line += f'\n🟢 **Sector Leaders:** {", ".join(leaders).title()}'
        if laggards:
            regime_line += f'\n🔴 **Sector Laggards:** {", ".join(laggards).title()}'

    report_lines = [
        '🎩 **TradeMind CEO — Tagesbriefing**',
        '',
        regime_line,
        f'📈 **Performance:** Win-Rate {wr_overall:.0%} (7d: {wr_7d:.0%}) | {bench_str}',
        f'🏆 **Beste Strategie:** {best_strat} ({best_wr:.0%} WR) | ⚠️ Schwächste: {worst_strat} ({worst_wr:.0%} WR)',
        f'📦 **Positionen:** {open_pos} offen | {total_trades} Trades geschlossen | Drawdown: {drawdown:.1%}',
        '',
        '**Heutige Direktive:**',
        f'- Max {max_pos} neue Positionen (Größe: €{max_size:,.0f})',
        f'- Stop-Faktor ×{stop_factor:.1f}' + (' (breiter bei VIX > 28)' if vix > 28 else ''),
        f'- Erlaubt: {allowed_str[:60]}',
        f'- Geblockt: {blocked_str[:80]}',
    ]

    if opp_lines:
        report_lines.append('')
        report_lines.append('**Top Opportunities:**')
        report_lines.extend(opp_lines)

    # ── Pending Setups (warte auf Trigger) ──────────────────────────
    try:
        pending = conn.execute('''
            SELECT ticker, strategy, conviction, entry_trigger, current_price,
                   stop_suggestion, target_suggestion, notes, created_at
            FROM pending_setups WHERE status='WATCHING'
            ORDER BY conviction DESC LIMIT 5
        ''').fetchall()
        if pending:
            report_lines.append('')
            report_lines.append(f'**⏳ Watchlist — warte auf Entry ({len(pending)} Setups):**')
            for p in pending:
                crv = ''
                if p['stop_suggestion'] and p['target_suggestion'] and p['entry_trigger']:
                    risk = p['entry_trigger'] - p['stop_suggestion']
                    reward = p['target_suggestion'] - p['entry_trigger']
                    if risk > 0:
                        crv = f" CRV {reward/risk:.1f}:1"
                curr = p['current_price'] or 0
                dist = ((curr - p['entry_trigger']) / p['entry_trigger'] * 100) if p['entry_trigger'] else 0
                report_lines.append(
                    f"  • {p['ticker']} ({p['strategy']}) | Trigger: {p['entry_trigger']:.2f}€"
                    f" | Kurs jetzt: {curr:.2f}€ ({dist:+.1f}%){crv}"
                )
    except Exception:
        pass

    report_lines.append('')
    report_lines.append(f'**System-Gesundheit:** {health_score}/100')

    if errors:
        for e in errors:
            report_lines.append(f'🚨 {e}')

    if warnings:
        for w in warnings[:3]:
            report_lines.append(f'⚠️ {w}')

    # P1.A — Risk-Adjusted Metrics
    rm = directive.get('risk_metrics', {}).get('overall', {})
    if rm and rm.get('total_trades', 0) > 0:
        report_lines.append('')
        report_lines.append('**📐 Risk-Adjusted Metrics:**')
        report_lines.append(f'- Sharpe Ratio: {rm.get("sharpe_ratio", 0):.2f} (Ziel: >1.0)')
        report_lines.append(f'- Sortino Ratio: {rm.get("sortino_ratio", 0):.2f} (Ziel: >1.5)')
        report_lines.append(f'- Calmar Ratio: {rm.get("calmar_ratio", 0):.2f} (Ziel: >1.0)')
        report_lines.append(f'- Profit Factor: {rm.get("profit_factor", 0):.2f} (Ziel: >1.5)')
        report_lines.append(f'- CRV: {rm.get("crv", 0):.2f} (Ziel: >1.5)')
        report_lines.append(f'- Expectancy: €{rm.get("expectancy", 0):.2f}/Trade')

    # P1.B — Portfolio Concentration
    pc = directive.get('portfolio_concentration', {})
    if pc and pc.get('sector_weights'):
        report_lines.append('')
        report_lines.append(f'**⚖️ Portfolio-Balance:** (HHI: {pc.get("hhi", 0):.2f} — {pc.get("hhi_label", "N/A")})')
        for sector, weight in sorted(pc['sector_weights'].items(), key=lambda x: -x[1]):
            bar = '█' * int(weight * 20)
            report_lines.append(f'  {sector}: {weight:.0%} {bar}')
        for w in pc.get('warnings', []):
            report_lines.append(f'  {w}')

    # P1.C — Position Sizing
    ps = directive.get('position_sizing', {})
    if ps and ps.get('default_sizes'):
        report_lines.append('')
        report_lines.append(f'**💰 Kelly Position Sizing** (VIX {ps.get("vix", 0):.1f} | {ps.get("mode", "?")}):')
        for strat_id, sizing in sorted(ps['default_sizes'].items()):
            if sizing.get('tradeable', False):
                report_lines.append(f'  {strat_id}: €{sizing["recommended_size_eur"]:,.0f} ({sizing["reason"]})')
            else:
                report_lines.append(f'  {strat_id}: ❌ {sizing["reason"]}')

    # P2.B — Sector Regime Detail
    if regime_detail and regime_detail.get('sectors'):
        report_lines.append('')
        report_lines.append('**🌍 Sektor-Regime (Live):**')
        sector_icons = {'BULL': '🟢', 'BULL_VOLATILE': '🟡', 'RANGE_BOUND': '⚪',
                        'CORRECTION': '🟠', 'BEAR': '🔴', 'UNKNOWN': '❓'}
        for sector, sr in sorted(regime_detail['sectors'].items()):
            icon = sector_icons.get(sr, '❓')
            report_lines.append(f'  {icon} {sector.title()}: {sr}')
        eurusd = regime_detail.get('eurusd', 0)
        if eurusd:
            report_lines.append(f'  💱 EUR/USD: {eurusd:.4f}')
        nasdaq_vs = regime_detail.get('nasdaq_vs_ma200', 0)
        if nasdaq_vs:
            report_lines.append(f'  📈 Nasdaq vs MA200: {nasdaq_vs:+.1f}%')

    # P2.C — Geo-Intel
    gi = directive.get('geo_intel', {})
    if gi and gi.get('geo_score') is not None:
        hotspots_str = ', '.join(gi.get('geo_hotspots', [])) or 'Keine'
        affected_str = ', '.join(gi.get('geo_trades_affected', [])[:5]) or 'Keine'
        trump_str = gi.get('trump_signal', 'NEUTRAL')
        pifs_str = '🚨 PIFS ALERT' if gi.get('pifs_alert') else ''
        trend = gi.get('geo_trend', 'STABLE')
        trend_icons = {'CRITICAL': '🔴', 'ESCALATING': '🟠', 'STABLE': '🟡', 'DEESCALATING': '🟢'}
        trend_icon = trend_icons.get(trend, '⚪')
        report_lines.append('')
        report_lines.append(f'**🌍 Geo-Intel:** Score {gi["geo_score"]} ({trend_icon} {trend}) | Hotspots: {hotspots_str} | Trump: {trump_str} {pifs_str}')
        if gi.get('geo_trades_affected'):
            report_lines.append(f'  Betroffene Trades: {affected_str}')
        detail = gi.get('detail', {})
        if detail.get('events_24h', 0) > 0:
            report_lines.append(f'  Events 24h: {detail["events_24h"]} | Event-Score: {detail.get("overnight_events_score", 0)}')

    # P2.D — Stress-Tests
    st = directive.get('stress_tests', {})
    if st and st.get('open_positions_count', 0) > 0:
        report_lines.append('')
        report_lines.append('**🔥 Stress-Tests:**')
        report_lines.append(f'- Max Loss (alle Stops): -€{st["max_portfolio_loss_all_stops"]:,.0f} (-{st.get("max_portfolio_loss_pct", 0):.1f}%)')

        scenarios = st.get('scenarios', {})
        iran = scenarios.get('iran_peace_deal', {})
        if iran:
            report_lines.append(f'- Iran Peace Deal: €{iran.get("impact_eur", 0):+,.0f} ({iran.get("impact_pct", 0):+.1f}%)')
        lib = scenarios.get('liberation_day', {})
        if lib:
            report_lines.append(f'- Liberation Day: €{lib.get("impact_eur", 0):+,.0f} ({lib.get("impact_pct", 0):+.1f}%)')
        flash = scenarios.get('flash_crash', {})
        if flash:
            report_lines.append(f'- Flash Crash (SPY -5%): €{flash.get("impact_eur", 0):+,.0f} ({flash.get("impact_pct", 0):+.1f}%)')
        vix_s = scenarios.get('vix_spike', {})
        if vix_s:
            at_risk = vix_s.get('positions_at_risk', [])
            risk_str = f' | At risk: {", ".join(at_risk)}' if at_risk else ''
            report_lines.append(f'- VIX Spike (+50%): €{vix_s.get("impact_eur", 0):+,.0f}{risk_str}')

        report_lines.append(f'- **Risiko-Rating: {st.get("risk_rating", "N/A")}**')

    # P3.C — Anomaly Detection
    anom = directive.get('anomalies', {})
    if anom and anom.get('anomaly_count', 0) > 0:
        report_lines.append('')
        report_lines.append(f'**🔍 Anomalie-Erkennung:** {anom["anomaly_count"]} Anomalien erkannt')
        severity_icons = {'HIGH': '🚨', 'MEDIUM': '⚠️', 'LOW': 'ℹ️'}
        # Sort: HIGH first, then MEDIUM, then LOW
        severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        sorted_anomalies = sorted(anom.get('anomalies', []),
                                   key=lambda a: severity_order.get(a.get('severity', 'LOW'), 3))
        for a in sorted_anomalies:
            icon = severity_icons.get(a.get('severity', 'LOW'), '❓')
            report_lines.append(f'  {icon} {a["severity"]}: {a["description"]}')

    # P3.A — Post-Mortem Analyse
    pm = directive.get('postmortem_summary', {})
    if pm and pm.get('total_analyzed', 0) > 0:
        report_lines.append('')
        report_lines.append(f'**🔬 Post-Mortem Analyse ({pm["total_analyzed"]} Trades):**')
        report_lines.append(f'- Entry-Qualität: Ø {pm["avg_entry_quality"]:.1f}/10')
        report_lines.append(f'- Exit-Qualität: Ø {pm["avg_exit_quality"]:.1f}/10')

        disp = pm.get('disposition_effect', 0)
        if disp > 0.15:
            disp_label = 'Gewinner zu früh verkauft'
        elif disp < -0.15:
            disp_label = 'Gute Disziplin — Verlierer schnell geschlossen'
        else:
            disp_label = 'Ausgeglichen'
        report_lines.append(f'- Disposition Effect: {disp:+.2f} ({disp_label})')

        avg_w_days = pm.get('avg_win_holding_days', 0)
        avg_l_days = pm.get('avg_loss_holding_days', 0)
        if avg_w_days > 0 or avg_l_days > 0:
            report_lines.append(f'- Haltedauer: Gewinner Ø {avg_w_days:.1f}d | Verlierer Ø {avg_l_days:.1f}d')

        # Best/worst regime
        rp = pm.get('regime_performance', {})
        if rp:
            best_r = max(rp.items(), key=lambda x: x[1].get('wr', 0))
            worst_r = min(rp.items(), key=lambda x: x[1].get('wr', 0))
            if best_r[0] != worst_r[0]:
                report_lines.append(f'- Beste Regime: {best_r[0]} ({best_r[1]["wr"]:.0%} WR) | Schlechteste: {worst_r[0]} ({worst_r[1]["wr"]:.0%} WR)')

        # Top insight
        top_insights = pm.get('top_insights', [])
        if top_insights:
            report_lines.append(f'- 💡 Top Insight: "{top_insights[0]}"')

    # P3.B — Strategy DNA Evolution
    dna = directive.get('strategy_dna', {})
    if dna and dna.get('strategies_analyzed', 0) > 0:
        total_strats = dna.get('strategies_analyzed', 0) + len(dna.get('insufficient_data', []))
        report_lines.append('')
        report_lines.append(f'**🧬 Strategy DNA Evolution:**')
        report_lines.append(f'- {dna["strategies_analyzed"]} von {total_strats} Strategien analysierbar (5+ Trades)')

        for strat_id, evo in sorted(dna.get('evolutions', {}).items()):
            findings = evo.get('findings', [])
            rec = evo.get('recommendation', 'MONITOR')
            wr = evo.get('win_rate', 0)
            n = evo.get('trades_analyzed', 0)
            conf = evo.get('confidence', 'LOW')

            # Build compact line
            parts = [f'{strat_id}:']

            # Kill/Review recommendation
            if rec == 'KILL':
                parts.append(f'DNA sagt KILL — {wr:.0%} WR in {n} Trades')
            elif rec == 'REVIEW':
                parts.append(f'⚠️ Review nötig — {wr:.0%} WR')
            elif rec == 'HEALTHY':
                parts.append(f'✅ Gesund — {wr:.0%} WR')
            else:
                parts.append(f'{wr:.0%} WR ({n} Trades)')

            # Stop recommendation
            opt_stop = evo.get('recommended_params', {}).get('optimal_stop_pct')
            cur_stop = evo.get('current_params', {}).get('avg_stop_distance_pct')
            if opt_stop and cur_stop:
                parts.append(f'Stop empfohlen -{opt_stop:.1f}% (aktuell: -{cur_stop:.1f}%)')

            # Holding period
            opt_hold = evo.get('recommended_params', {}).get('optimal_holding_range')
            avg_hold = evo.get('current_params', {}).get('avg_holding_days')
            if opt_hold:
                hold_info = f'Optimale Haltedauer {opt_hold}'
                if avg_hold:
                    hold_info += f' (aktuell: Ø {avg_hold:.1f} Tage)'
                parts.append(hold_info)

            # Regime info from regime_filters
            rf = dna.get('regime_filters', {}).get(strat_id, {})
            rec_filter = rf.get('recommended_filter', '')
            if 'Allwetter' in rec_filter:
                parts.append('"Allwetter" ✅')
            elif 'NICHT' in rec_filter:
                parts.append(rec_filter.split(';')[0].strip())

            report_lines.append(f'- {" | ".join(parts)}')

    # P4.D — Backtest-Ergebnisse
    bt = directive.get('backtest_summary', {})
    if bt and bt.get('strategies_tested', 0) > 0:
        report_lines.append('')
        report_lines.append(f'**🔄 Backtest-Ergebnisse ({bt["strategies_tested"]} Strategien mit 5+ Trades):**')

        bt_results = bt.get('results', {})
        for sid, sr in sorted(bt_results.items()):
            orig = sr.get('original', {})
            stop_imp = sr.get('optimized_stop', {}).get('improvement_pct', 0)
            tp_imp = sr.get('optimized_tp', {}).get('improvement_pct', 0)
            regime_info = sr.get('regime_filtered', {})
            regime_skipped = regime_info.get('trades_skipped', 0)
            best_var = sr.get('best_variant', 'original')
            best_imp = sr.get('best_improvement_pct', 0)

            parts = [f'{sid} ({orig.get("trades", 0)}T, {orig.get("wr", 0):.0%} WR):']
            parts.append(f'Stop weiter → {stop_imp:+.0f}%')
            parts.append(f'TP höher → {tp_imp:+.0f}%')
            parts.append(f'Regime-Filter → {regime_skipped} übersprungen')
            if best_var != 'original' and best_imp > 0:
                parts.append(f'← BEST: {best_var} ({best_imp:+.0f}%)')
            report_lines.append(f'- {" | ".join(parts)}')

        sys_w = bt.get('system_wide', {})
        orig_pnl = sys_w.get('original_pnl', 0)
        opt_pnl = sys_w.get('optimized_pnl', 0)
        sys_imp = sys_w.get('improvement_pct', 0)
        rec = sys_w.get('recommendation', '')
        report_lines.append(f'- System-Gesamt: €{orig_pnl:,.0f} → €{opt_pnl:,.0f} ({sys_imp:+.1f}% möglich)')
        if rec:
            report_lines.append(f'- 💡 Top-Empfehlung: "{rec}"')

    # P4.C — Portfolio-Optimierung
    po = directive.get('portfolio_optimization', {})
    if po and not po.get('error') and po.get('current_allocation'):
        div_cur = po.get('diversification_score', 0)
        div_opt = po.get('optimal_diversification_score', 0)
        sharpe_cur = po.get('sharpe_current', 0)
        sharpe_opt = po.get('sharpe_optimal', 0)
        exp_ret = po.get('expected_portfolio_return', 0)
        exp_risk = po.get('expected_portfolio_risk', 0)

        report_lines.append('')
        report_lines.append(f'**📊 Portfolio-Optimierung:**')
        report_lines.append(f'- Diversifikation: {div_cur:.2f}/1.0 (aktuell) → {div_opt:.2f} (optimal)')

        suggestions = po.get('rebalance_suggestions', [])
        if suggestions:
            report_lines.append('- Rebalance:')
            action_icons = {'DECREASE': '↘️', 'REMOVE': '❌', 'INCREASE': '↗️', 'ADD': '➕'}
            for s in suggestions:
                icon = action_icons.get(s['action'], '•')
                report_lines.append(f'  {icon} {s["sector"].title()}: {s["reason"]}')

        report_lines.append(f'- Erwartete Sharpe (optimal): {sharpe_opt:.1f} (aktuell: {sharpe_cur:.1f})')
        report_lines.append(f'- Erwartete Rendite: {exp_ret:.1%} p.a. | Risiko: {exp_risk:.1%} p.a.')

    # P4.A — Adaptive VIX Thresholds
    at = directive.get('adaptive_thresholds', {})
    if at and at.get('vix_30d_avg', 0) > 0:
        report_lines.append('')
        z_score = at.get('current_vix_zscore', 0)
        z_label = 'normal' if abs(z_score) < 1.0 else ('erhöht' if z_score > 0 else 'niedrig')
        regime_ctx = at.get('regime_context', 'NORMAL')
        ctx_icons = {'NORMAL': '🟢', 'GEOPOLITICAL_ELEVATED': '🟠', 'PANIC': '🔴'}
        ctx_icon = ctx_icons.get(regime_ctx, '⚪')
        report_lines.append(f'**🎯 Adaptive VIX-Schwellen:**')
        report_lines.append(
            f'  VIX {vix:.1f} (Z-Score: {z_score:+.1f} — {z_label} für aktuelle Lage) | '
            f'30d Ø{at["vix_30d_avg"]:.1f} ±{at["vix_30d_std"]:.1f}'
        )
        report_lines.append(
            f'  {ctx_icon} Regime: {regime_ctx} | '
            f'Adaptive: DEFENSIVE ab {at["vix_defensive_threshold"]:.0f} '
            f'(fix: {at["static_defensive"]:.0f}), '
            f'SHUTDOWN ab {at["vix_shutdown_threshold"]:.0f} '
            f'(fix: {at["static_shutdown"]:.0f})'
        )
        if at.get('performance_adjusted'):
            report_lines.append(f'  📊 Performance-Feedback aktiv')

    # P4.B — Multi-Timeframe
    mtf = directive.get('multi_timeframe', {})
    if mtf and mtf.get('spy', {}).get('daily') != 'NEUTRAL':
        report_lines.append('')
        report_lines.append('**📊 Multi-Timeframe:**')

        # SPY
        spy_tf = mtf.get('spy', {})
        d, w, m = spy_tf.get('daily', '?'), spy_tf.get('weekly', '?'), spy_tf.get('monthly', '?')
        align = spy_tf.get('alignment', 'MIXED')
        align_icons = {'ALIGNED_BULL': '✅', 'ALIGNED_BEAR': '❌', 'MIXED': '⚠️'}
        report_lines.append(
            f'  SPY: Daily {d} | Weekly {w} | Monthly {m} → {align} {align_icons.get(align, "")}'
        )
        interp = spy_tf.get('interpretation', '')
        if interp:
            report_lines.append(f'  → "{interp.split(": ", 1)[-1] if ": " in interp else interp}"')

        # Sectors
        sectors = mtf.get('sectors', {})
        for sec_name, sec_data in sorted(sectors.items()):
            sd = sec_data.get('daily', '?')
            sw = sec_data.get('weekly', '?')
            sa = sec_data.get('alignment', 'MIXED')
            sec_icon = align_icons.get(sa, '⚠️')
            report_lines.append(f'  {sec_name.title()}: Daily {sd} | Weekly {sw} → {sa} {sec_icon}')

        # Trading Bias
        bias = mtf.get('trading_bias', 'NEUTRAL')
        conf = mtf.get('confidence', 0)
        bias_icons = {'LONG_ONLY': '🚀', 'CAUTIOUS_LONG': '⚠️', 'NEUTRAL': '⏸️'}
        report_lines.append(f'  Trading Bias: {bias} {bias_icons.get(bias, "")} (Confidence: {conf:.1f})')

        # MTF note from trading rules
        mtf_note = directive.get('trading_rules', {}).get('mtf_note', '')
        if mtf_note:
            report_lines.append(f'  💡 {mtf_note}')
        max_hold = directive.get('trading_rules', {}).get('max_holding_days')
        if max_hold:
            report_lines.append(f'  ⏱️ Max Haltedauer: {max_hold} Tage')

    report_lines.extend([
        '',
        f'**Lernfortschritt:** P1.1–P1.4 {p1_str} | Trades gesamt: {total_trades} | Nächste Review: +{max(0, 30-total_trades)} Trades',
    ])

    if ceo_notes and ceo_notes != 'Standardbetrieb.':
        report_lines.extend([
            '',
            f'📝 **CEO-Notiz:** {ceo_notes}',
        ])

    return '\n'.join(report_lines)


# ─── Health-Only Report ────────────────────────────────────────────────────────

def generate_health_report(health: dict, hist: dict) -> str:
    """Kurzreport für --health Flag."""
    lines = [
        '🏥 **TradeMind System-Health**',
        f'Score: {health["score"]}/100',
        f'Trade Journal: {health["journal_entries"]} Einträge',
        f'Closed Trades: {hist["total_closed_trades"]}',
        f'Win-Rate: {hist["overall_win_rate"]:.0%}',
        f'Drawdown: {hist["portfolio_drawdown"]:.1%}',
        f'P1-Features: {", ".join(health["p1_features_list"]) or "Keine"}',
    ]
    for e in health['errors']:
        lines.append(f'🚨 ERROR: {e}')
    for w in health['warnings']:
        lines.append(f'⚠️ WARN: {w}')
    return '\n'.join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='TradeMind CEO')
    parser.add_argument('--health', action='store_true', help='Nur System-Health-Check')
    parser.add_argument('--report', action='store_true', help='Nur Report, keine Direktive schreiben')
    parser.add_argument('--live', action='store_true', help='Live-Marktdaten von Yahoo Finance laden')
    parser.add_argument('--backtest', action='store_true', help='Detaillierte Backtest-Ergebnisse anzeigen')
    parser.add_argument('--full', action='store_true', help='Vollständiger Report (kein Discord-Limit)')
    args = parser.parse_args()

    # ── Schritt 1: Alle Quellen laden ────────────────────────────────────────
    sources = load_all_sources()

    # ── Schritt 2: DB-Daten laden ─────────────────────────────────────────────
    conn = get_db()
    hist = load_historical_data(conn)

    # ── Schritt 2b: P1.A — Risk-Adjusted Metrics ─────────────────────────────
    risk_metrics = calculate_risk_metrics(conn)

    # ── Schritt 2c: P1.B — Portfolio Concentration ────────────────────────────
    concentration = calculate_portfolio_concentration(conn, sources.get('strategies', {}))

    # ── Schritt 2d: P2.A — Live Market Data (optional) ───────────────────────
    live_market_data = None
    if args.live:
        try:
            live_market_data = fetch_live_market_data()
        except Exception as e:
            print(f'⚠️ Live-Daten konnten nicht geladen werden: {e}', file=sys.stderr)
            live_market_data = None

    # ── Schritt 2e: P1.C — Kelly Position Sizing ─────────────────────────────
    regime = sources.get('regime', {})

    # VIX: Live-Daten haben Vorrang
    if live_market_data and not live_market_data.get('vix', {}).get('error'):
        vix = live_market_data['vix'].get('price', 25.0)
    else:
        vix = regime.get('indicators', {}).get('vix', 25.0)
    portfolio_value = hist.get('starting_capital', 25000.0) + hist.get('total_realized_pnl', 0.0)
    # Pre-determine mode for Kelly (simplified — will be recalculated in build_directive)
    pre_mode = 'NORMAL'
    if vix > 28 or hist['recent_win_rate_7d'] < 0.25:
        pre_mode = 'DEFENSIVE'
    if vix > 40 or hist['portfolio_drawdown'] > 0.20:
        pre_mode = 'SHUTDOWN'

    position_sizing = calculate_all_kelly_sizes(
        sources.get('strategies', {}),
        hist['strategy_performance'],
        portfolio_value, vix, pre_mode, conn
    )

    # ── Schritt 3: System-Health berechnen ────────────────────────────────────
    health = calculate_system_health(hist, sources)

    # ── Health-Only Modus ─────────────────────────────────────────────────────
    if args.health:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        print(generate_health_report(health, hist))
        return

    # ── Schritt 4: Direktive bauen (P1.A/B/C + P2.A/B/C/D integriert) ───────
    directive = build_directive(sources, hist, health,
                                risk_metrics=risk_metrics,
                                concentration=concentration,
                                position_sizing=position_sizing,
                                live_market_data=live_market_data,
                                conn=conn)

    # DB schließen nach build_directive (P2.C/D brauchen die Verbindung)
    if conn:
        try:
            conn.close()
        except Exception:
            pass

    # ── Schritt 5: Report generieren ──────────────────────────────────────────
    if args.full:
        report = generate_report_full(directive, hist)
    else:
        report = generate_report(directive, hist)

    # ── Schritt 6: Direktive schreiben (wenn nicht --report) ──────────────────
    if not args.report:
        directive_path = WS / 'data/ceo_directive.json'
        try:
            with open(directive_path, 'w') as f:
                json.dump(directive, f, indent=2, ensure_ascii=False)
            print(f'✅ CEO-Direktive geschrieben: {directive_path}')
        except Exception as e:
            print(f'❌ Fehler beim Schreiben der Direktive: {e}', file=sys.stderr)

    # ── Schritt 7: Report ausgeben ────────────────────────────────────────────
    print()
    print(report)

    # ── Schritt 8: Detaillierter Backtest (wenn --backtest) ───────────────────
    if args.backtest:
        bt = directive.get('backtest_summary', {})
        if bt and bt.get('strategies_tested', 0) > 0:
            print('\n' + '=' * 60)
            print('🔄 DETAILLIERTER BACKTEST-REPORT')
            print('=' * 60)
            print(f'Strategien getestet: {bt["strategies_tested"]}')
            print(f'Zeitstempel: {bt.get("timestamp", "N/A")}')

            for sid, sr in sorted(bt.get('results', {}).items()):
                orig = sr.get('original', {})
                print(f'\n── {sid} ({orig.get("trades", 0)} Trades, WR: {orig.get("wr", 0):.0%}, PnL: €{orig.get("pnl", 0):,.2f}) ──')

                # Optimized Stop
                os = sr.get('optimized_stop', {})
                print(f'  Stop 20% weiter:  WR {os.get("wr", 0):.0%} | PnL €{os.get("pnl", 0):,.2f} | Δ {os.get("improvement_pct", 0):+.1f}%')

                # Optimized TP
                ot = sr.get('optimized_tp', {})
                print(f'  TP 20% höher:     WR {ot.get("wr", 0):.0%} | PnL €{ot.get("pnl", 0):,.2f} | Δ {ot.get("improvement_pct", 0):+.1f}%')

                # Regime-Filtered
                rf = sr.get('regime_filtered', {})
                worst = rf.get('worst_regimes', [])
                worst_str = f' (gefiltert: {", ".join(worst)})' if worst else ''
                print(f'  Regime-Filter:    WR {rf.get("wr", 0):.0%} | PnL €{rf.get("pnl", 0):,.2f} | {rf.get("trades_skipped", 0)} übersprungen{worst_str}')

                # Best variant
                bv = sr.get('best_variant', 'original')
                bi = sr.get('best_improvement_pct', 0)
                if bv != 'original':
                    print(f'  ✅ Beste Variante: {bv} ({bi:+.1f}% Verbesserung)')
                else:
                    print(f'  ℹ️ Original ist optimal — keine Variante besser')

            # System-wide
            sw = bt.get('system_wide', {})
            print(f'\n{"=" * 60}')
            print(f'SYSTEM-GESAMT:')
            print(f'  Original PnL:   €{sw.get("original_pnl", 0):,.2f}')
            print(f'  Optimiert PnL:   €{sw.get("optimized_pnl", 0):,.2f}')
            print(f'  Verbesserung:    {sw.get("improvement_pct", 0):+.1f}%')
            print(f'  Empfehlung:      {sw.get("recommendation", "N/A")}')
            print('=' * 60)
        else:
            print('\n⚠️ Keine Backtest-Ergebnisse — nicht genug Trades (min. 5 pro Strategie).')

    return report


if __name__ == '__main__':
    main()
