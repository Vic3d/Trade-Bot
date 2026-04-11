#!/usr/bin/env python3
"""
backtest_engine_v2.py — Backtester für das neue Dual-Gate System
=================================================================
Testet den neuen Scanner (THESIS_ENTRY_CRITERIA + ATR-Stops) gegen
2 Jahre historische Kursdaten via yfinance.

Speichert Ergebnisse in data/backtest_v2_results.json und trading.db

Albert | TradeMind v2 | 2026-04-10
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data' / 'trading.db'
RESULTS_JSON = WS / 'data' / 'backtest_v2_results.json'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'execution'))

# Import UNIVERSE und THESIS_ENTRY_CRITERIA aus dem Scanner
from autonomous_scanner import UNIVERSE, THESIS_ENTRY_CRITERIA, _ema, _rsi, _atr


# ─── DB Setup ────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            ticker TEXT,
            strategy TEXT,
            entry_date TEXT,
            exit_date TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl_pct REAL,
            exit_reason TEXT,
            hold_days INTEGER
        )
    """)
    conn.commit()
    conn.close()


# ─── Daten-Download via yfinance ─────────────────────────────────────────────

def download_history(ticker: str) -> list[dict] | None:
    """
    Lädt 2 Jahre tägliche OHLCV-Daten via yfinance.
    Gibt sortierte Liste von Dicts zurück: {date, open, high, low, close, volume}
    """
    try:
        import yfinance as yf
        df = yf.download(ticker, period='2y', interval='1d', progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 50:
            return None

        rows = []
        for idx, row in df.iterrows():
            date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
            # yfinance kann MultiIndex-Columns haben
            def _val(col):
                try:
                    v = row[col]
                    if hasattr(v, 'item'):
                        v = v.item()
                    return float(v) if v is not None else None
                except Exception:
                    return None

            c = _val('Close')
            if c is None or c <= 0:
                continue

            rows.append({
                'date':   date_str,
                'open':   _val('Open')   or c,
                'high':   _val('High')   or c,
                'low':    _val('Low')    or c,
                'close':  c,
                'volume': _val('Volume') or 0,
            })

        return rows if len(rows) >= 50 else None

    except Exception as e:
        print(f"  Fehler beim Download {ticker}: {e}")
        return None


# ─── Indikator-Berechnung ─────────────────────────────────────────────────────

def calc_indicators(rows: list[dict]) -> list[dict]:
    """
    Berechnet EMA20, EMA50, RSI(14), vol_ratio, ATR(14) für alle Bars.
    Gibt erweiterte Rows zurück.
    """
    closes  = [r['close']  for r in rows]
    highs   = [r['high']   for r in rows]
    lows    = [r['low']    for r in rows]
    volumes = [r['volume'] for r in rows]

    ema20_series = _ema(closes, 20)
    ema50_series = _ema(closes, 50)

    # Offset: ema20 startet bei Index 19, ema50 bei Index 49
    ema20_offset = 19
    ema50_offset = 49

    result = []
    for i, row in enumerate(rows):
        ema20_val = ema20_series[i - ema20_offset] if i >= ema20_offset and (i - ema20_offset) < len(ema20_series) else None
        ema50_val = ema50_series[i - ema50_offset] if i >= ema50_offset and (i - ema50_offset) < len(ema50_series) else None

        rsi_window = closes[max(0, i - 14):i + 1]
        rsi_val    = _rsi(rsi_window, 14) if len(rsi_window) >= 15 else None

        avg_vol = sum(volumes[max(0, i - 20):i]) / min(i, 20) if i > 0 else 0
        vol_ratio = row['volume'] / avg_vol if avg_vol > 0 else 1.0

        atr_closes = closes[max(0, i - 15):i + 1]
        atr_highs  = highs[max(0, i - 15):i + 1]
        atr_lows   = lows[max(0, i - 15):i + 1]
        atr_val    = _atr(atr_closes, atr_highs, atr_lows) if len(atr_closes) >= 5 else row['close'] * 0.03

        result.append({
            **row,
            'ema20':     ema20_val,
            'ema50':     ema50_val,
            'rsi':       rsi_val,
            'vol_ratio': vol_ratio,
            'atr':       atr_val,
            'price':     row['close'],
        })

    return result


# ─── Entry-Simulation ─────────────────────────────────────────────────────────

def check_entry(bar: dict, strategy: str) -> dict | None:
    """
    Prüft Entry-Kriterien für einen Bar (identisch mit evaluate_setup).
    Gibt Setup-Dict zurück oder None.
    """
    if bar.get('ema20') is None or bar.get('ema50') is None:
        return None

    criteria = THESIS_ENTRY_CRITERIA.get(strategy, THESIS_ENTRY_CRITERIA['DEFAULT'])

    if not criteria['trend'](bar):
        return None
    if not criteria['momentum'](bar):
        return None
    if not criteria['volume'](bar):
        return None

    atr  = bar.get('atr', bar['close'] * 0.03)
    stop = bar['close'] - criteria['stop_atr'] * atr
    stop = max(stop, bar['close'] * 0.70)

    risk = bar['close'] - stop
    if risk <= 0:
        return None

    target = bar['close'] + criteria['target_r'] * risk
    crv    = (target - bar['close']) / risk
    if crv < 2.0:
        return None

    return {
        'entry':      bar['close'],
        'stop':       stop,
        'target':     target,
        'crv':        round(crv, 2),
        'atr':        atr,
        'hold_days':  criteria['hold_days'],
    }


# ─── Exit-Simulation ─────────────────────────────────────────────────────────

def simulate_exit(entry_bar_idx: int, bars: list[dict], setup: dict) -> dict:
    """
    Simuliert Exits:
    - Stop Loss: low <= stop
    - Partial +5% (1/3), +10% (1/3), trailing letztes Drittel
    - Target: entry + target_r * risk (CRV)
    - Max Hold: 45 Tage
    """
    entry_price = setup['entry']
    stop        = setup['stop']
    target      = setup['target']
    max_hold    = 45

    partial1_triggered = False   # +5%
    partial2_triggered = False   # +10%
    partial1_price = entry_price * 1.05
    partial2_price = entry_price * 1.10

    trailing_stop   = stop
    trailing_active = False
    highest_close   = entry_price

    weighted_exit = 0.0
    remaining_size = 1.0

    for i in range(entry_bar_idx + 1, min(entry_bar_idx + max_hold + 1, len(bars))):
        bar  = bars[i]
        high = bar['high']
        low  = bar['low']
        close = bar['close']
        hold_days = i - entry_bar_idx

        # Stop-Loss prüfen (intraday low)
        if low <= (trailing_stop if trailing_active else stop):
            exit_price = trailing_stop if trailing_active else stop
            weighted_exit += exit_price * remaining_size
            pnl = (weighted_exit / entry_price - 1) * 100 if entry_price > 0 else 0
            return {
                'exit_date':   bar['date'],
                'exit_price':  round(weighted_exit, 4),
                'pnl_pct':     round(pnl, 3),
                'exit_reason': 'STOP',
                'hold_days':   hold_days,
            }

        # Partial 1: +5% (1/3 Position)
        if not partial1_triggered and high >= partial1_price:
            partial1_triggered = True
            weighted_exit  += partial1_price * (1/3)
            remaining_size -= 1/3
            trailing_active = True
            trailing_stop   = entry_price  # Break-Even nach Partial 1

        # Partial 2: +10% (weiteres Drittel)
        if not partial2_triggered and high >= partial2_price:
            partial2_triggered = True
            weighted_exit  += partial2_price * (1/3)
            remaining_size -= 1/3

        # Trailing Stop für letztes Drittel (ATR-basiert)
        if trailing_active and close > highest_close:
            highest_close = close
            new_trail = highest_close - setup['atr'] * 1.5
            if new_trail > trailing_stop:
                trailing_stop = new_trail

        # Full Target erreicht
        if high >= target:
            weighted_exit += target * remaining_size
            pnl = (weighted_exit / entry_price - 1) * 100 if entry_price > 0 else 0
            return {
                'exit_date':   bar['date'],
                'exit_price':  round(weighted_exit, 4),
                'pnl_pct':     round(pnl, 3),
                'exit_reason': 'TARGET',
                'hold_days':   hold_days,
            }

    # Max Hold abgelaufen
    last_bar   = bars[min(entry_bar_idx + max_hold, len(bars) - 1)]
    exit_price = last_bar['close']
    weighted_exit += exit_price * remaining_size
    pnl = (weighted_exit / entry_price - 1) * 100 if entry_price > 0 else 0
    return {
        'exit_date':   last_bar['date'],
        'exit_price':  round(weighted_exit, 4),
        'pnl_pct':     round(pnl, 3),
        'exit_reason': 'MAX_HOLD',
        'hold_days':   max_hold,
    }


# ─── Backtest pro Ticker ──────────────────────────────────────────────────────

def backtest_ticker(ticker: str, strategy: str) -> list[dict]:
    """
    Führt Backtest für einen Ticker durch.
    Gibt Liste von Trade-Dicts zurück.
    """
    rows = download_history(ticker)
    if rows is None:
        print(f"  {ticker}: keine Daten")
        return []

    bars   = calc_indicators(rows)
    trades = []
    i      = 0

    while i < len(bars) - 1:
        bar = bars[i]
        # Mindestens EMA50 brauchen wir
        if bar.get('ema50') is None:
            i += 1
            continue

        setup = check_entry(bar, strategy)
        if setup is None:
            i += 1
            continue

        # Entry gefunden — Exit simulieren
        exit_info = simulate_exit(i, bars, setup)

        trade = {
            'ticker':       ticker,
            'strategy':     strategy,
            'entry_date':   bar['date'],
            'entry_price':  round(setup['entry'], 4),
            'stop_price':   round(setup['stop'], 4),
            'target_price': round(setup['target'], 4),
            'crv':          setup['crv'],
            **exit_info,
        }
        trades.append(trade)

        # Nächsten Entry erst nach Exit suchen (kein Overlap)
        exit_idx = i + exit_info['hold_days']
        i = exit_idx + 1

    return trades


# ─── Metriken ─────────────────────────────────────────────────────────────────

def calc_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {}

    pnls    = [t['pnl_pct'] for t in trades]
    wins    = [p for p in pnls if p > 0]
    losses  = [p for p in pnls if p <= 0]
    n       = len(trades)

    win_rate   = len(wins) / n * 100 if n > 0 else 0
    avg_win    = sum(wins) / len(wins) if wins else 0
    avg_loss   = sum(losses) / len(losses) if losses else 0
    avg_pnl    = sum(pnls) / n if n > 0 else 0

    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    pf         = gross_win / gross_loss if gross_loss > 0 else float('inf')

    exits = {}
    for t in trades:
        r = t.get('exit_reason', 'UNKNOWN')
        exits[r] = exits.get(r, 0) + 1

    return {
        'n_trades':     n,
        'win_rate':     round(win_rate, 1),
        'avg_win_pct':  round(avg_win, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'avg_pnl_pct':  round(avg_pnl, 2),
        'profit_factor': round(pf, 2) if pf != float('inf') else 'inf',
        'exits':        exits,
    }


def best_worst(trades_by_ticker: dict, key: str) -> tuple[str, str]:
    """Bester/schlechtester Ticker nach avg_pnl."""
    scores = {}
    for ticker, trades in trades_by_ticker.items():
        if not trades:
            continue
        scores[ticker] = sum(t['pnl_pct'] for t in trades) / len(trades)
    if not scores:
        return ('n/a', 'n/a')
    best = max(scores, key=scores.get)
    worst = min(scores, key=scores.get)
    return (best, worst)


# ─── Discord Summary ──────────────────────────────────────────────────────────

def send_discord_summary(summary: dict):
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        metrics = summary.get('overall', {})
        n       = metrics.get('n_trades', 0)
        wr      = metrics.get('win_rate', 0)
        avg_pnl = metrics.get('avg_pnl_pct', 0)
        pf      = metrics.get('profit_factor', 0)
        best_t  = summary.get('best_ticker', 'n/a')
        worst_t = summary.get('worst_ticker', 'n/a')
        n_tickers = summary.get('n_tickers_tested', 0)

        msg = (
            f"**Backtest v2 abgeschlossen** ({summary.get('run_date', '')})\n"
            f"Tickers getestet: {n_tickers} | Trades gesamt: {n}\n"
            f"Win-Rate: {wr:.1f}% | Avg P&L: {avg_pnl:+.2f}% | Profit Factor: {pf}\n"
            f"Bester Ticker: {best_t} | Schlechtester: {worst_t}\n"
            f"Ergebnisse: data/backtest_v2_results.json"
        )
        send(msg)
    except Exception as e:
        print(f"Discord-Fehler: {e}")


# ─── Haupt-Funktion ───────────────────────────────────────────────────────────

def run_backtest():
    """
    Führt Backtest für alle Ticker in UNIVERSE durch.
    Speichert Ergebnisse in JSON und DB.
    """
    print("=== Backtest Engine v2 ===")
    print(f"Tickers: {len(UNIVERSE)} | Zeitraum: 2 Jahre")
    ensure_table()

    run_date    = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    all_trades  = []
    by_ticker   = {}
    by_strategy = {}

    for ticker, strategy, description in UNIVERSE:
        print(f"  {ticker:12} ({strategy})...", end=' ', flush=True)
        trades = backtest_ticker(ticker, strategy)
        print(f"{len(trades)} Trades")

        all_trades.extend(trades)
        by_ticker[ticker]       = trades
        by_strategy[strategy]   = by_strategy.get(strategy, []) + trades

        time.sleep(0.5)  # Rate-Limit

    # Metriken
    overall   = calc_metrics(all_trades)
    strat_met = {s: calc_metrics(t) for s, t in by_strategy.items()}
    best_s    = max(strat_met, key=lambda s: strat_met[s].get('avg_pnl_pct', -999)) if strat_met else 'n/a'
    worst_s   = min(strat_met, key=lambda s: strat_met[s].get('avg_pnl_pct', 999)) if strat_met else 'n/a'
    best_tk, worst_tk = best_worst(by_ticker, 'avg_pnl_pct')

    summary = {
        'run_date':          run_date,
        'n_tickers_tested':  len(UNIVERSE),
        'n_trades':          len(all_trades),
        'overall':           overall,
        'by_strategy':       strat_met,
        'by_ticker':         {t: calc_metrics(trades) for t, trades in by_ticker.items()},
        'best_strategy':     best_s,
        'worst_strategy':    worst_s,
        'best_ticker':       best_tk,
        'worst_ticker':      worst_tk,
    }

    # JSON speichern
    RESULTS_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nJSON gespeichert: {RESULTS_JSON}")

    # DB speichern
    conn = get_db()
    for trade in all_trades:
        conn.execute("""
            INSERT INTO backtest_results_v2
            (run_date, ticker, strategy, entry_date, exit_date,
             entry_price, exit_price, pnl_pct, exit_reason, hold_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_date,
            trade['ticker'],
            trade['strategy'],
            trade['entry_date'],
            trade.get('exit_date', ''),
            trade['entry_price'],
            trade.get('exit_price', trade['entry_price']),
            trade.get('pnl_pct', 0),
            trade.get('exit_reason', 'UNKNOWN'),
            trade.get('hold_days', 0),
        ))
    conn.commit()
    conn.close()
    print(f"DB gespeichert: {len(all_trades)} Trades in backtest_results_v2")

    # Summary ausgeben
    print(f"\n=== Ergebnisse ===")
    print(f"  Trades gesamt  : {overall.get('n_trades', 0)}")
    print(f"  Win-Rate       : {overall.get('win_rate', 0):.1f}%")
    print(f"  Avg Win        : {overall.get('avg_win_pct', 0):+.2f}%")
    print(f"  Avg Loss       : {overall.get('avg_loss_pct', 0):+.2f}%")
    print(f"  Avg P&L        : {overall.get('avg_pnl_pct', 0):+.2f}%")
    print(f"  Profit Factor  : {overall.get('profit_factor', 0)}")
    print(f"  Bester Ticker  : {best_tk}")
    print(f"  Schlechtester  : {worst_tk}")
    print(f"  Beste Strategie: {best_s}")

    print(f"\n  Strategie-Übersicht:")
    for s, m in sorted(strat_met.items()):
        print(
            f"    {s:8} Trades={m.get('n_trades',0):3d} "
            f"WR={m.get('win_rate',0):.0f}% "
            f"AvgPnL={m.get('avg_pnl_pct',0):+.1f}% "
            f"PF={m.get('profit_factor',0)}"
        )

    # Discord
    send_discord_summary(summary)

    return summary


if __name__ == '__main__':
    run_backtest()
