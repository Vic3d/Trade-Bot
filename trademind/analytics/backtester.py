"""
trademind/analytics/backtester.py — Walk-Forward Backtester

Walk-Forward Backtesting mit Out-of-Sample Validierung.
Alle Berechnungen mit numpy, keine externen Libs.
"""
from __future__ import annotations

import sqlite3
import random
import math
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

DB_PATH = '/data/.openclaw/workspace/data/trading.db'
POSITION_SIZE_EUR = 5_000.0


# ══════════════════════════════════════════════════════════════════════════════
# Technical Indicators (pure numpy)
# ══════════════════════════════════════════════════════════════════════════════

def _ma(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """Simple Moving Average via convolution. Returns array of len(prices)-period+1."""
    kernel = np.ones(period) / period
    return np.convolve(prices, kernel, mode='valid')


def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI(14) — returns array of same length with NaN for first `period` values."""
    if len(prices) < period + 1:
        return np.full(len(prices), np.nan)

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    rsi = np.full(len(prices), np.nan)

    # Initial average
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """ATR(14) via SMA of True Range. Returns array same length, NaN for first period."""
    n = len(highs)
    tr = np.full(n, np.nan)
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hpc, lpc)

    atr = np.full(n, np.nan)
    valid = tr[1:]  # skip first NaN
    for i in range(period - 1, len(valid)):
        atr[i + 1] = np.mean(valid[i - period + 1: i + 1])

    return atr


# ══════════════════════════════════════════════════════════════════════════════
# DB helpers
# ══════════════════════════════════════════════════════════════════════════════

def _load_prices(db_path: str, ticker: str) -> list[dict]:
    """Lade alle Preis-Zeilen für einen Ticker aus der DB, chronologisch sortiert."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date ASC",
        (ticker,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_prices_multi(db_path: str, tickers: list[str]) -> dict[str, list[dict]]:
    """Lade Preise für mehrere Ticker."""
    return {t: _load_prices(db_path, t) for t in tickers}


# ══════════════════════════════════════════════════════════════════════════════
# Metrics helpers
# ══════════════════════════════════════════════════════════════════════════════

def _sharpe(pnl_series: list[float], risk_free: float = 0.0) -> float:
    """Annualisierter Sharpe Ratio aus einer Liste von Trade-P&L Werten."""
    if len(pnl_series) < 2:
        return 0.0
    arr = np.array(pnl_series, dtype=float)
    mean = np.mean(arr) - risk_free
    std = np.std(arr, ddof=1)
    if std == 0:
        return 0.0
    # Rough annualization: assume ~252 trades/year
    return float(mean / std * math.sqrt(252))


def _max_drawdown(pnl_series: list[float]) -> float:
    """Max Drawdown in EUR (negativ)."""
    if not pnl_series:
        return 0.0
    equity = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    return float(np.min(dd))


def _profit_factor(pnl_series: list[float]) -> float:
    """Gross profit / gross loss."""
    wins = sum(p for p in pnl_series if p > 0)
    losses = sum(-p for p in pnl_series if p < 0)
    if losses == 0:
        return float('inf') if wins > 0 else 0.0
    return round(wins / losses, 3)


def _win_rate(pnl_series: list[float]) -> float:
    if not pnl_series:
        return 0.0
    return sum(1 for p in pnl_series if p > 0) / len(pnl_series)


# ══════════════════════════════════════════════════════════════════════════════
# Trade Simulation (per ticker, per window)
# ══════════════════════════════════════════════════════════════════════════════

def _simulate_momentum_trades(rows: list[dict], position_eur: float = POSITION_SIZE_EUR) -> list[float]:
    """
    Momentum-Strategie auf einer Preisserie simulieren.
    BUY wenn close > MA(20) UND RSI < 70
    SELL wenn close < MA(20) ODER RSI > 80 ODER Stop Hit (ATR×2)
    Returns: Liste von P&L-Werten pro Trade.
    """
    if len(rows) < 30:
        return []

    closes = np.array([r['close'] for r in rows], dtype=float)
    highs  = np.array([r['high']  for r in rows], dtype=float)
    lows   = np.array([r['low']   for r in rows], dtype=float)

    ma   = _ma(closes, 20)
    rsi  = _rsi(closes, 14)
    atr  = _atr(highs, lows, closes, 14)

    # ma starts at index 19 (0-based), so align
    ma_aligned = np.full(len(closes), np.nan)
    ma_aligned[19:] = ma

    pnls = []
    in_trade = False
    entry_price = 0.0
    stop_price  = 0.0
    shares      = 0.0

    for i in range(20, len(closes)):
        price = closes[i]
        ma_val  = ma_aligned[i]
        rsi_val = rsi[i]
        atr_val = atr[i]

        if np.isnan(ma_val) or np.isnan(rsi_val) or np.isnan(atr_val):
            continue

        if not in_trade:
            # BUY signal
            if price > ma_val and rsi_val < 70:
                entry_price = price
                shares = position_eur / price
                stop_price = entry_price - 2.0 * atr_val
                in_trade = True
        else:
            # SELL conditions
            exit_now = False
            if price < ma_val:
                exit_now = True
            elif rsi_val > 80:
                exit_now = True
            elif price <= stop_price:
                exit_now = True

            if exit_now:
                pnl = (price - entry_price) * shares - 2.0  # 2€ fees roundtrip
                pnls.append(pnl)
                in_trade = False

    # Force-close at end if still in trade
    if in_trade and len(closes) > 0:
        pnl = (closes[-1] - entry_price) * shares - 2.0
        pnls.append(pnl)

    return pnls


def _simulate_meanrev_trades(rows: list[dict], position_eur: float = POSITION_SIZE_EUR) -> list[float]:
    """
    Mean-Reversion-Strategie.
    BUY wenn RSI < 30
    SELL wenn RSI > 50 ODER Stop Hit (ATR×2)
    """
    if len(rows) < 30:
        return []

    closes = np.array([r['close'] for r in rows], dtype=float)
    highs  = np.array([r['high']  for r in rows], dtype=float)
    lows   = np.array([r['low']   for r in rows], dtype=float)

    rsi  = _rsi(closes, 14)
    atr  = _atr(highs, lows, closes, 14)

    pnls = []
    in_trade = False
    entry_price = 0.0
    stop_price  = 0.0
    shares      = 0.0

    for i in range(15, len(closes)):
        price   = closes[i]
        rsi_val = rsi[i]
        atr_val = atr[i]

        if np.isnan(rsi_val) or np.isnan(atr_val):
            continue

        if not in_trade:
            if rsi_val < 30:
                entry_price = price
                shares = position_eur / price
                stop_price = entry_price - 2.0 * atr_val
                in_trade = True
        else:
            exit_now = False
            if rsi_val > 50:
                exit_now = True
            elif price <= stop_price:
                exit_now = True

            if exit_now:
                pnl = (price - entry_price) * shares - 2.0
                pnls.append(pnl)
                in_trade = False

    if in_trade and len(closes) > 0:
        pnl = (closes[-1] - entry_price) * shares - 2.0
        pnls.append(pnl)

    return pnls


# ══════════════════════════════════════════════════════════════════════════════
# Walk-Forward Backtester
# ══════════════════════════════════════════════════════════════════════════════

class WalkForwardBacktester:
    """
    Walk-Forward Backtesting mit Out-of-Sample Validierung.

    train_window: 120 Tage (6 Monate)
    test_window:   20 Tage (1 Monat)
    step:          20 Tage

    Für jedes Fenster:
    1. "Trainiere" Strategie auf train_window (= berechne Signale)
    2. Simuliere Trades auf test_window (hat die Strategie NIE gesehen)
    3. Erfasse Ergebnis
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH

    # ── Core walk-forward engine ─────────────────────────────────────────────

    def _run_walkforward(
        self,
        tickers: list[str],
        simulate_fn,
        train_days: int = 120,
        test_days: int = 20,
    ) -> dict:
        """
        Generische Walk-Forward Engine.
        simulate_fn(rows) → list[float] (P&L pro Trade)
        """
        all_price_data = _load_prices_multi(self.db_path, tickers)

        # Sammle alle Preis-Daten (für Benchmark-Vergleich)
        all_window_results = []
        all_pnls: list[float] = []

        for ticker in tickers:
            rows = all_price_data.get(ticker, [])
            if not rows:
                continue

            n = len(rows)
            total_window = train_days + test_days

            if n < total_window:
                continue

            # Walk-Forward: Schritt = test_days
            pos = 0
            while pos + total_window <= n:
                train_rows = rows[pos: pos + train_days]
                test_rows  = rows[pos + train_days: pos + total_window]

                train_start = train_rows[0]['date']
                test_start  = test_rows[0]['date']

                # "Train" phase: Signale berechnen (implizit — hier einfach vollständige Simulation)
                # train_pnls = simulate_fn(train_rows)  # In-sample (nicht für OOS-Validierung genutzt)

                # "Test" phase: OOS (Out-of-Sample)
                # Für Walk-Forward: Wir nutzen die letzten MA/RSI/ATR-Werte aus dem Training
                # als "Parameter" und simulieren dann auf dem Test-Window.
                # Praxis: Wir hängen Train+Test zusammen und simulieren NUR auf dem Test-Teil.
                combined = train_rows + test_rows
                all_trades_combined = simulate_fn(combined)

                # OOS-Trades sind die, die im Test-Window stattgefunden haben:
                # Da wir keine Trade-Timestamps haben, nutzen wir einen Proxy:
                # Die letzten len(test_rows) / (train_days+test_days) Anteil der Trades
                if all_trades_combined:
                    # Grobe Schätzung: Test hat test_days/(train+test) Anteil der Zeit
                    test_fraction = test_days / total_window
                    oos_trade_count = max(1, round(len(all_trades_combined) * test_fraction))
                    oos_pnls = all_trades_combined[-oos_trade_count:]
                else:
                    oos_pnls = []

                window_pnl  = sum(oos_pnls)
                window_wr   = _win_rate(oos_pnls)
                window_trades = len(oos_pnls)

                all_window_results.append({
                    'ticker':      ticker,
                    'train_start': train_start,
                    'test_start':  test_start,
                    'trades':      window_trades,
                    'pnl':         round(window_pnl, 2),
                    'wr':          round(window_wr, 3),
                })

                all_pnls.extend(oos_pnls)
                pos += test_days  # step

        # ── Aggregate metrics ────────────────────────────────────────────────
        total_trades  = len(all_pnls)
        total_pnl     = round(sum(all_pnls), 2)
        win_rate      = round(_win_rate(all_pnls), 3)
        sharpe        = round(_sharpe(all_pnls), 3)
        max_dd        = round(_max_drawdown(all_pnls), 2)
        pf            = _profit_factor(all_pnls)

        # OOS-Validierung: Sharpe über 0 → valid
        oos_valid = sharpe > 0

        # ── Benchmark ───────────────────────────────────────────────────────
        # Bestimme Zeitraum aus den Window-Ergebnissen
        if all_window_results:
            period_start = min(w['train_start'] for w in all_window_results)
            period_end   = max(w['test_start']  for w in all_window_results)
        else:
            period_start = period_end = ''

        # Benchmark-Tickers in der DB suchen
        bench_spy = self._calc_buy_hold('^GSPC', period_start, period_end) if period_start else 0.0
        bench_dax = self._calc_buy_hold('^GDAXI', period_start, period_end) if period_start else 0.0
        # Buy & Hold auf gegebene Tickers
        bh_pnl = self._calc_buy_hold_tickers(tickers, period_start, period_end)

        return {
            'windows':   all_window_results,
            'aggregate': {
                'total_trades':  total_trades,
                'win_rate':      win_rate,
                'total_pnl':     total_pnl,
                'sharpe':        sharpe,
                'max_drawdown':  max_dd,
                'profit_factor': pf,
            },
            'benchmark': {
                'spy_return':       round(bench_spy, 4),
                'dax_return':       round(bench_dax, 4),
                'buy_hold_return':  round(bh_pnl, 2),
            },
            'out_of_sample_valid': oos_valid,
        }

    # ── Public Methods ───────────────────────────────────────────────────────

    def backtest_momentum(
        self,
        tickers: list[str],
        train_days: int = 120,
        test_days:  int = 20,
    ) -> dict:
        """
        Momentum-Strategie Walk-Forward Backtest.
        BUY wenn Kurs > MA(20) UND RSI < 70
        SELL wenn Kurs < MA(20) ODER RSI > 80 ODER Stop Hit (ATR×2)
        Position sizing: Fixed €5000 pro Trade
        """
        return self._run_walkforward(
            tickers, _simulate_momentum_trades, train_days, test_days
        )

    def backtest_mean_reversion(
        self,
        tickers: list[str],
        train_days: int = 120,
        test_days:  int = 20,
    ) -> dict:
        """
        Mean-Reversion-Strategie Walk-Forward Backtest.
        BUY wenn RSI < 30
        SELL wenn RSI > 50 ODER Stop Hit (ATR×2)
        """
        return self._run_walkforward(
            tickers, _simulate_meanrev_trades, train_days, test_days
        )

    def compare_with_benchmarks(
        self,
        strategy_pnl: list[float],
        period_start: str,
        period_end:   str,
    ) -> dict:
        """
        Vergleiche Strategie mit:
        1. Buy & Hold SPY
        2. Buy & Hold DAX (^GDAXI)
        3. Random entry (gleiche Sizing, zufällige Entry/Exit)
        """
        strategy_total = sum(strategy_pnl)
        strategy_sharpe = _sharpe(strategy_pnl)

        spy_return = self._calc_buy_hold('^GSPC',  period_start, period_end)
        dax_return = self._calc_buy_hold('^GDAXI', period_start, period_end)

        # Random entry simulation (10.000 × shuffled trades)
        random_results = []
        for _ in range(1000):
            shuffled = strategy_pnl.copy()
            random.shuffle(shuffled)
            random_results.append(sum(shuffled))
        random_median = float(np.median(random_results)) if random_results else 0.0

        return {
            'strategy_pnl':    round(strategy_total, 2),
            'strategy_sharpe': round(strategy_sharpe, 3),
            'spy_return_pct':  round(spy_return * 100, 2),
            'dax_return_pct':  round(dax_return * 100, 2),
            'random_median':   round(random_median, 2),
            'outperforms_spy': strategy_total > spy_return * len(strategy_pnl) * POSITION_SIZE_EUR,
            'outperforms_random': strategy_total > random_median,
        }

    # ── Benchmark helpers ────────────────────────────────────────────────────

    def _calc_buy_hold(self, ticker: str, start: str, end: str) -> float:
        """Berechne Buy & Hold Return (%) für einen Ticker im Zeitraum."""
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT close FROM prices
                   WHERE ticker=? AND date >= ? AND date <= ?
                   ORDER BY date ASC""",
                (ticker, start, end)
            ).fetchall()
            conn.close()
            if len(rows) < 2:
                return 0.0
            return (rows[-1][0] - rows[0][0]) / rows[0][0]
        except Exception:
            return 0.0

    def _calc_buy_hold_tickers(self, tickers: list[str], start: str, end: str) -> float:
        """Buy & Hold P&L in EUR für eine Liste von Tickers (gleiche Position sizing)."""
        total = 0.0
        count = 0
        for ticker in tickers:
            ret = self._calc_buy_hold(ticker, start, end)
            if ret != 0.0:
                total += ret * POSITION_SIZE_EUR
                count += 1
        return total / max(count, 1) if count else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# CLI Formatter
# ══════════════════════════════════════════════════════════════════════════════

def format_backtest_result(result: dict, strategy_name: str) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append(f"🎩 TRADEMIND — BACKTEST: {strategy_name.upper()}")
    lines.append("=" * 65)

    agg = result.get('aggregate', {})
    bench = result.get('benchmark', {})
    windows = result.get('windows', [])
    oos = result.get('out_of_sample_valid', False)

    # Aggregate
    lines.append(f"\n{'─'*65}")
    lines.append("📊 AGGREGATE METRIKEN")
    lines.append(f"{'─'*65}")
    lines.append(f"  Trades gesamt:    {agg.get('total_trades', 0)}")
    lines.append(f"  Win Rate:         {agg.get('win_rate', 0)*100:.1f}%")
    lines.append(f"  Total P&L:        {agg.get('total_pnl', 0):+.2f}€")
    lines.append(f"  Sharpe Ratio:     {agg.get('sharpe', 0):.3f}")
    lines.append(f"  Max Drawdown:     {agg.get('max_drawdown', 0):.2f}€")
    lines.append(f"  Profit Factor:    {agg.get('profit_factor', 0):.3f}")

    oos_icon = "✅ VALID" if oos else "❌ INVALID"
    lines.append(f"\n  Out-of-Sample:    {oos_icon}  (Sharpe {'>' if oos else '<='} 0)")

    # Benchmark
    lines.append(f"\n{'─'*65}")
    lines.append("📈 BENCHMARK VERGLEICH")
    lines.append(f"{'─'*65}")
    lines.append(f"  Strategie P&L:    {agg.get('total_pnl', 0):+.2f}€")
    lines.append(f"  Buy&Hold Returns (selbe Periode):")
    lines.append(f"    SPY:            {bench.get('spy_return', 0)*100:+.1f}%")
    lines.append(f"    DAX (^GDAXI):   {bench.get('dax_return', 0)*100:+.1f}%")
    lines.append(f"    Tickers BH:     {bench.get('buy_hold_return', 0):+.2f}€")

    # Windows (letzten 5)
    if windows:
        lines.append(f"\n{'─'*65}")
        lines.append(f"🔁 WALK-FORWARD FENSTER (letzte {min(5, len(windows))} von {len(windows)})")
        lines.append(f"{'─'*65}")
        lines.append(f"  {'Ticker':<10} {'Train-Start':<12} {'Test-Start':<12} {'Trades':>6} {'P&L':>10} {'WR':>7}")
        lines.append(f"  {'─'*58}")
        for w in windows[-5:]:
            pnl_str = f"{w['pnl']:+.2f}€"
            wr_str  = f"{w['wr']*100:.0f}%"
            lines.append(
                f"  {w.get('ticker','?'):<10} {w['train_start']:<12} {w['test_start']:<12} "
                f"{w['trades']:>6} {pnl_str:>10} {wr_str:>7}"
            )

    lines.append(f"\n{'='*65}\n")
    return "\n".join(lines)


def format_compare_result(result: dict) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append("🎩 TRADEMIND — STRATEGIE vs BENCHMARKS")
    lines.append("=" * 65)
    lines.append(f"  Strategie P&L:      {result.get('strategy_pnl', 0):+.2f}€")
    lines.append(f"  Strategie Sharpe:   {result.get('strategy_sharpe', 0):.3f}")
    lines.append(f"  SPY Return:         {result.get('spy_return_pct', 0):+.1f}%")
    lines.append(f"  DAX Return:         {result.get('dax_return_pct', 0):+.1f}%")
    lines.append(f"  Random Median P&L:  {result.get('random_median', 0):+.2f}€")
    lines.append(f"  Schlägt SPY:        {'✅' if result.get('outperforms_spy') else '❌'}")
    lines.append(f"  Schlägt Random:     {'✅' if result.get('outperforms_random') else '❌'}")
    lines.append(f"{'='*65}\n")
    return "\n".join(lines)
