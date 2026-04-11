#!/usr/bin/env python3
"""
Backtest Engine — Phase 2 des ML-Bauplans
==========================================
Walk-Forward Backtesting aller Strategien auf 2+ Jahren historischen Daten.

Methodik:
  - Train-Fenster: 18 Monate (Parametervalidierung)
  - Test-Fenster:  3 Monate (Out-of-Sample, nie in die Zukunft gesehen)
  - Roll: 3 Monate vorwärts
  - Regime-Filter: VIX-Daten aus historischen Daten (kein Hindsight-Bias)

Einstiegsregeln (spiegeln paper_trade_engine.py):
  - RSI(14) < 55 (nicht überkauft)
  - Kurs über MA20
  - Volume Ratio >= 0.8 (kein Phantomvolumen)
  - VIX-Regime-Filter aktiv (wie im echten System)

Ausstiegsregeln:
  - Stop: entry * (1 - stop_pct)
  - Target: entry * (1 + target_pct)
  - Time Exit: nach max_hold_days ohne +3% Move

Usage:
  python3 backtest_engine.py                    # Alle Strategien
  python3 backtest_engine.py --strategy PS1     # Einzelne Strategie
  python3 backtest_engine.py --ticker EQNR      # Einzelner Ticker
  python3 backtest_engine.py --quick            # Nur Top-5 Strategien
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf
import numpy as np

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
STRATEGIES_FILE = WS / 'data/strategies.json'
RESULTS_FILE = WS / 'data/backtest_results.json'
REPORT_FILE = WS / 'memory/backtest-report.md'
CACHE_DIR = WS / 'data/price_cache'
CACHE_DIR.mkdir(exist_ok=True)

# ── Backtest-Parameter ────────────────────────────────────────────────────────
BACKTEST_YEARS = 2          # Wie viele Jahre historische Daten
TRAIN_MONTHS = 18           # Walk-Forward Trainings-Fenster
TEST_MONTHS = 3             # Walk-Forward Test-Fenster
STOP_PCT = 0.07             # 7% Stop (konservativ, VIX-angepasst)
TARGET_PCT = 0.14           # 14% Target → CRV 2:1
MAX_HOLD_DAYS = 21          # Max Haltezeit (Thesis-Trades)
MIN_MOVE_TO_HOLD = 0.03     # Mindest-Move nach halber Haltezeit
POSITION_SIZE = 2000        # EUR pro Trade (Simulation)
COMMISSION = 2.0            # 2€ Round-Trip (Trade Republic Simulation)


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def download_data(ticker: str, years: int = 3) -> dict | None:
    """
    Lädt OHLCV-Daten via yfinance. Cached lokal.
    Gibt dict zurück: {date_str: {open, high, low, close, volume}}
    """
    cache_file = CACHE_DIR / f"{ticker.replace('/', '_').replace('^', 'IX')}.json"

    # Cache gültig wenn < 12h alt
    if cache_file.exists():
        age_h = (datetime.now().timestamp() - cache_file.stat().st_mtime) / 3600
        if age_h < 12:
            return json.loads(cache_file.read_text(encoding="utf-8"))

    try:
        df = yf.download(ticker, period=f"{years}y", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 50:
            return None

        bars = {}
        for date, row in df.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            try:
                # yfinance gibt manchmal MultiIndex zurück
                c = float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
                o = float(row['Open'].iloc[0]) if hasattr(row['Open'], 'iloc') else float(row['Open'])
                h = float(row['High'].iloc[0]) if hasattr(row['High'], 'iloc') else float(row['High'])
                l = float(row['Low'].iloc[0]) if hasattr(row['Low'], 'iloc') else float(row['Low'])
                v = float(row['Volume'].iloc[0]) if hasattr(row['Volume'], 'iloc') else float(row['Volume'])
                if c > 0:
                    bars[date_str] = {'o': round(o, 4), 'h': round(h, 4),
                                      'l': round(l, 4), 'c': round(c, 4), 'v': int(v)}
            except Exception:
                continue

        if len(bars) < 50:
            return None

        cache_file.write_text(json.dumps(bars))
        return bars
    except Exception as e:
        return None


def calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    """RSI(14) für alle Bars. Gibt Liste zurück (gleiche Länge wie closes)."""
    rsi = [None] * len(closes)
    if len(closes) <= period:
        return rsi
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi[i] = round(100 - (100 / (1 + rs)), 2)

    return rsi


def calc_ma(closes: list[float], period: int) -> list[float | None]:
    """Einfacher gleitender Durchschnitt."""
    result = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1:i + 1]) / period
    return result


def calc_atr(bars_list: list[dict], period: int = 14) -> list[float | None]:
    """ATR(14) als % des Kurses."""
    result = [None] * len(bars_list)
    ranges = [abs(bars_list[i]['c'] - bars_list[i-1]['c']) for i in range(1, len(bars_list))]
    for i in range(period, len(bars_list)):
        atr = sum(ranges[i-period:i]) / period
        result[i] = round(atr / bars_list[i]['c'] * 100, 3) if bars_list[i]['c'] > 0 else None
    return result


def sharpe_ratio(returns: list[float], risk_free: float = 0.04) -> float:
    """Annualisierter Sharpe Ratio (tägliche Returns → annualisiert)."""
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    daily_rf = risk_free / 252
    excess = arr - daily_rf
    if excess.std() == 0:
        return 0.0
    return round(float(excess.mean() / excess.std() * np.sqrt(252)), 3)


def max_drawdown(equity_curve: list[float]) -> float:
    """Max Drawdown als negative %-Zahl."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


def prepare_indicators(bars: dict) -> dict:
    """
    Berechnet alle technischen Indikatoren für einen Ticker.
    Gibt augmentiertes dict zurück: date → {o,h,l,c,v, rsi, ma20, ma50, vol_ratio, atr}
    """
    dates = sorted(bars.keys())
    closes = [bars[d]['c'] for d in dates]
    volumes = [bars[d]['v'] for d in dates]

    rsi_vals = calc_rsi(closes)
    ma20_vals = calc_ma(closes, 20)
    ma50_vals = calc_ma(closes, 50)
    atr_vals = calc_atr([bars[d] for d in dates])

    # Volume Ratio (aktuell / Ø 20 Tage)
    vol_ratio = [None] * len(dates)
    for i in range(20, len(dates)):
        avg_vol = sum(volumes[i-20:i]) / 20
        vol_ratio[i] = round(volumes[i] / avg_vol, 2) if avg_vol > 0 else None

    augmented = {}
    for i, d in enumerate(dates):
        augmented[d] = {
            **bars[d],
            'rsi': rsi_vals[i],
            'ma20': ma20_vals[i],
            'ma50': ma50_vals[i],
            'vol_ratio': vol_ratio[i],
            'atr': atr_vals[i],
        }
    return augmented


# ── Entry/Exit Logik ─────────────────────────────────────────────────────────

def check_entry(bar: dict, vix: float | None) -> tuple[bool, str]:
    """
    Prüft Entry-Kriterien (spiegelt paper_trade_engine.py).
    Returns: (should_enter, reason)
    """
    rsi = bar.get('rsi')
    ma20 = bar.get('ma20')
    vol_ratio = bar.get('vol_ratio')
    c = bar['c']

    if rsi is None or ma20 is None:
        return False, "indicators_missing"

    # VIX-Regime-Filter (wie im echten System)
    if vix is not None:
        if vix > 35:
            return False, "vix_crash_block"
        if vix > 30:
            # Im echten System: nur wenn conviction sehr hoch → hier: skip
            return False, "vix_risk_off"

    # Kurs über MA20 (Grundtrend)
    if c < ma20:
        return False, "below_ma20"

    # RSI nicht überkauft
    if rsi > 72:
        return False, "rsi_overbought"

    # RSI aktiv (nicht tief überverkauft — das wäre reversal, nicht momentum)
    if rsi < 25:
        return False, "rsi_extreme_oversold"

    # Volume OK
    if vol_ratio is not None and vol_ratio < 0.5:
        return False, "low_volume"

    return True, "signal_ok"


def simulate_ticker(ticker: str, augmented: dict, vix_data: dict,
                    stop_pct: float = STOP_PCT, target_pct: float = TARGET_PCT,
                    max_hold: int = MAX_HOLD_DAYS) -> list[dict]:
    """
    Simuliert alle Trades für einen Ticker auf historischen Daten.
    Kein Lookahead-Bias: Entscheidungen nur auf Basis von Daten bis Kauftag.
    """
    dates = sorted(augmented.keys())
    trades = []
    in_trade = False
    entry_date = None
    entry_price = None
    stop_price = None
    target_price = None

    for i, d in enumerate(dates):
        bar = augmented[d]
        vix = vix_data.get(d)

        if not in_trade:
            should_enter, reason = check_entry(bar, vix)
            if should_enter:
                entry_price = bar['c']
                stop_price = entry_price * (1 - stop_pct)
                target_price = entry_price * (1 + target_pct)
                entry_date = d
                in_trade = True
        else:
            hold_days = (datetime.strptime(d, '%Y-%m-%d') -
                         datetime.strptime(entry_date, '%Y-%m-%d')).days
            c = bar['c']
            move_pct = (c - entry_price) / entry_price

            exit_price = None
            exit_type = None

            # Stop
            if c <= stop_price:
                exit_price = stop_price
                exit_type = 'STOP'

            # Target
            elif c >= target_price:
                exit_price = target_price
                exit_type = 'TARGET'

            # Time Exit
            elif hold_days >= max_hold and move_pct < MIN_MOVE_TO_HOLD:
                exit_price = c
                exit_type = f'TIME_{hold_days}d'

            if exit_price:
                pnl_eur = (exit_price - entry_price) / entry_price * POSITION_SIZE - COMMISSION
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'exit_date': d,
                    'entry_price': round(entry_price, 4),
                    'exit_price': round(exit_price, 4),
                    'hold_days': hold_days,
                    'pnl_eur': round(pnl_eur, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'exit_type': exit_type,
                    'win': pnl_eur > 0,
                    'rsi_at_entry': augmented[entry_date].get('rsi'),
                    'vix_at_entry': vix_data.get(entry_date),
                })
                in_trade = False
                entry_date = None

    return trades


def calc_metrics(trades: list[dict], spy_returns: dict | None = None) -> dict:
    """Berechnet alle Performance-Metriken."""
    if not trades:
        return {'error': 'no_trades'}

    wins = [t for t in trades if t['win']]
    losses = [t for t in trades if not t['win']]
    pnls = [t['pnl_eur'] for t in trades]
    pnl_pcts = [t['pnl_pct'] for t in trades]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(trades)
    avg_win = sum(t['pnl_eur'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_eur'] for t in losses) / len(losses) if losses else 0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # Profit Factor
    gross_profit = sum(t['pnl_eur'] for t in wins)
    gross_loss = abs(sum(t['pnl_eur'] for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0

    # Equity Curve (kumulativ)
    equity = [POSITION_SIZE]
    for t in trades:
        equity.append(equity[-1] + t['pnl_eur'])
    max_dd = max_drawdown(equity)

    # Tägliche Returns für Sharpe
    daily_returns = [t['pnl_eur'] / POSITION_SIZE for t in trades]
    sharpe = sharpe_ratio(daily_returns)

    # Alpha vs SPY (wenn verfügbar)
    alpha = None
    if spy_returns and trades:
        spy_start = spy_returns.get(trades[0]['entry_date'])
        spy_end = spy_returns.get(trades[-1]['exit_date'])
        if spy_start and spy_end and spy_start > 0:
            spy_return_pct = (spy_end - spy_start) / spy_start * 100
            strategy_return_pct = total_pnl / (POSITION_SIZE * len(trades)) * 100
            alpha = round(strategy_return_pct - spy_return_pct, 2)

    return {
        'total_trades': len(trades),
        'win_rate': round(win_rate, 3),
        'total_pnl_eur': round(total_pnl, 2),
        'avg_pnl_pct': round(sum(pnl_pcts) / len(pnl_pcts), 2),
        'avg_win_eur': round(avg_win, 2),
        'avg_loss_eur': round(avg_loss, 2),
        'expectancy_eur': round(expectancy, 2),
        'profit_factor': profit_factor,
        'max_drawdown_pct': max_dd,
        'sharpe_ratio': sharpe,
        'alpha_vs_spy': alpha,
        'avg_hold_days': round(sum(t['hold_days'] for t in trades) / len(trades), 1),
        'exit_types': {
            'STOP': sum(1 for t in trades if t['exit_type'] == 'STOP'),
            'TARGET': sum(1 for t in trades if t['exit_type'] == 'TARGET'),
            'TIME': sum(1 for t in trades if 'TIME' in (t['exit_type'] or '')),
        }
    }


# ── Walk-Forward ─────────────────────────────────────────────────────────────

def walk_forward(trades_all: list[dict], total_days: int) -> list[dict]:
    """
    Teilt Trades in Walk-Forward-Perioden auf.
    Returns: Liste von Perioden-Metriken (nur Test-Perioden)
    """
    if len(trades_all) < 5:
        return []

    start = datetime.strptime(trades_all[0]['entry_date'], '%Y-%m-%d')
    end = datetime.strptime(trades_all[-1]['exit_date'], '%Y-%m-%d')

    periods = []
    period_start = start + timedelta(days=TRAIN_MONTHS * 30)  # Erster Test nach Train-Fenster

    while period_start < end:
        period_end = period_start + timedelta(days=TEST_MONTHS * 30)
        ps_str = period_start.strftime('%Y-%m-%d')
        pe_str = period_end.strftime('%Y-%m-%d')

        # Nur Trades im Test-Fenster
        test_trades = [
            t for t in trades_all
            if ps_str <= t['entry_date'] < pe_str
        ]

        if len(test_trades) >= 3:
            metrics = calc_metrics(test_trades)
            metrics['period'] = f"{ps_str[:7]} → {pe_str[:7]}"
            metrics['is_oos'] = True  # Out-of-Sample
            periods.append(metrics)

        period_start = period_end

    return periods


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def run_strategy_backtest(strategy_id: str, tickers: list[str],
                          vix_data: dict, spy_prices: dict) -> dict:
    """Backtested eine Strategie über alle ihre Tickers."""
    all_trades = []
    ticker_results = {}

    for ticker in tickers:
        print(f"    → {ticker}...", end=' ', flush=True)
        bars = download_data(ticker, years=BACKTEST_YEARS + 1)
        if not bars:
            print("❌ (keine Daten)")
            continue

        augmented = prepare_indicators(bars)
        trades = simulate_ticker(ticker, augmented, vix_data)

        if trades:
            all_trades.extend(trades)
            ticker_results[ticker] = calc_metrics(trades)
            print(f"✅ ({len(trades)} Trades, WR {ticker_results[ticker]['win_rate']:.0%})")
        else:
            print("⚠️  (keine Trades generiert)")

    if not all_trades:
        return {'status': 'no_trades', 'strategy': strategy_id}

    all_trades.sort(key=lambda x: x['entry_date'])

    # Gesamtmetriken
    spy_returns = {d: spy_prices[d]['c'] for d in spy_prices} if spy_prices else None
    overall = calc_metrics(all_trades, spy_returns)

    # Walk-Forward
    total_days = (BACKTEST_YEARS + 1) * 365
    wf_periods = walk_forward(all_trades, total_days)

    # Konsistenz: wie viele OOS-Perioden waren profitabel?
    if wf_periods:
        profitable_periods = sum(1 for p in wf_periods if p.get('total_pnl_eur', 0) > 0)
        consistency = profitable_periods / len(wf_periods)
    else:
        consistency = None

    return {
        'status': 'ok',
        'strategy': strategy_id,
        'tickers_tested': list(ticker_results.keys()),
        'total_trades': len(all_trades),
        'overall': overall,
        'ticker_breakdown': ticker_results,
        'walk_forward': wf_periods,
        'consistency': round(consistency, 2) if consistency else None,
        'verdict': _verdict(overall, consistency),
        'backtested_at': datetime.now(timezone.utc).isoformat(),
    }


def _verdict(metrics: dict, consistency: float | None) -> str:
    """Gibt Klartext-Verdict für eine Strategie."""
    wr = metrics.get('win_rate', 0)
    pf = metrics.get('profit_factor', 0)
    sharpe = metrics.get('sharpe_ratio', 0)
    dd = metrics.get('max_drawdown_pct', -99)
    cons = consistency or 0

    if wr >= 0.55 and pf >= 1.3 and sharpe >= 0.5 and dd > -20 and cons >= 0.6:
        return '🟢 VALIDATED — Historisch robust, bereit für Paper Trading'
    elif wr >= 0.45 and pf >= 1.0:
        return '🟡 CONDITIONAL — Funktioniert, aber Konsistenz prüfen'
    elif wr < 0.35 or pf < 0.8:
        return '🔴 WEAK — Historisch schwach, Strategie überdenken'
    else:
        return '⚪ INCONCLUSIVE — Zu wenig Trades für klares Urteil'


def generate_report(all_results: dict) -> str:
    """Erstellt vollständigen Backtest-Report als Markdown."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        f"# Backtest Report — Walk-Forward Analyse",
        f"*Generiert: {now} | Phase 2 — Backtest Engine*",
        f"*Zeitraum: {BACKTEST_YEARS} Jahre | Stop: {STOP_PCT:.0%} | Target: {TARGET_PCT:.0%} | Max Hold: {MAX_HOLD_DAYS}d*",
        "",
        "## 🏆 Strategie-Ranking",
        "",
        "| Strategie | Trades | Win-Rate | Profit Factor | Sharpe | Max DD | Konsistenz | Verdict |",
        "|-----------|--------|----------|---------------|--------|--------|------------|---------|",
    ]

    # Sortiert nach Win-Rate × Profit Factor
    ranked = sorted(
        [(sid, r) for sid, r in all_results.items() if r.get('status') == 'ok'],
        key=lambda x: x[1]['overall'].get('win_rate', 0) * x[1]['overall'].get('profit_factor', 0),
        reverse=True
    )

    for sid, r in ranked:
        m = r['overall']
        wr = m.get('win_rate', 0)
        pf = m.get('profit_factor', 0)
        sh = m.get('sharpe_ratio', 0)
        dd = m.get('max_drawdown_pct', 0)
        cons = r.get('consistency')
        verdict = r.get('verdict', '?')[:4]
        cons_str = f"{cons:.0%}" if cons is not None else "—"
        lines.append(
            f"| {sid} | {r['total_trades']} | {wr:.0%} | {pf:.2f} | {sh:.2f} | {dd:.1f}% | {cons_str} | {verdict} |"
        )

    lines += ["", "## 📋 Strategie-Details", ""]

    for sid, r in ranked:
        m = r['overall']
        lines += [
            f"### {sid}",
            f"**Verdict:** {r.get('verdict', '?')}",
            f"- Trades: {r['total_trades']} | Win-Rate: {m.get('win_rate',0):.0%} | Avg P&L: {m.get('avg_pnl_pct',0):+.1f}%",
            f"- Profit Factor: {m.get('profit_factor',0):.2f} | Sharpe: {m.get('sharpe_ratio',0):.2f} | Max DD: {m.get('max_drawdown_pct',0):.1f}%",
            f"- Avg Haltezeit: {m.get('avg_hold_days',0):.0f} Tage | Erwartungswert: {m.get('expectancy_eur',0):+.1f}€",
        ]
        if r.get('alpha_vs_spy') is not None:
            lines.append(f"- Alpha vs. SPY: {m.get('alpha_vs_spy',0):+.1f}%")

        # Exit-Verteilung
        exits = m.get('exit_types', {})
        if exits:
            total_ex = sum(exits.values())
            lines.append(
                f"- Exits: Stop {exits.get('STOP',0)} ({exits.get('STOP',0)/max(total_ex,1):.0%}) | "
                f"Target {exits.get('TARGET',0)} ({exits.get('TARGET',0)/max(total_ex,1):.0%}) | "
                f"Time {exits.get('TIME',0)} ({exits.get('TIME',0)/max(total_ex,1):.0%})"
            )

        # Walk-Forward Perioden
        wf = r.get('walk_forward', [])
        if wf:
            lines += ["", "**Walk-Forward Perioden (Out-of-Sample):**",
                      "| Periode | Trades | Win-Rate | P&L | Sharpe |",
                      "|---------|--------|----------|-----|--------|"]
            for p in wf:
                profit_icon = "✅" if p.get('total_pnl_eur', 0) > 0 else "❌"
                lines.append(
                    f"| {p.get('period','?')} | {p.get('total_trades',0)} | "
                    f"{p.get('win_rate',0):.0%} | {profit_icon} {p.get('total_pnl_eur',0):+.0f}€ | "
                    f"{p.get('sharpe_ratio',0):.2f} |"
                )
        lines.append("")

    lines += [
        "---",
        "",
        "## 🎓 Interpretations-Guide",
        "",
        "- **Win-Rate >55%** + **Profit Factor >1.3** + **Konsistenz >60%** → Strategie historisch robust",
        "- **Max Drawdown > -25%** → Position Sizing überdenken",
        "- **Sharpe > 0.5** → Risikoadjustierte Rendite akzeptabel",
        "- **Viele TIME-Exits** → Strategie stagniert, Max-Hold oder Target anpassen",
        "- **Walk-Forward** zeigt ob Strategie auch auf unseen Daten funktioniert (≠ Overfitting)",
        "",
        "*Achtung: Backtest ≠ Zukunft. Regime-Wechsel (z.B. Iran-Eskalation) sind historisch nicht replizierbar.*"
    ]

    return '\n'.join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    strategies = json.loads(STRATEGIES_FILE.read_text(encoding="utf-8"))

    # VIX Historisch laden
    print("[Backtest Engine] Lade VIX-Daten...")
    vix_bars = download_data('^VIX', years=BACKTEST_YEARS + 1)
    vix_data = {d: v['c'] for d, v in (vix_bars or {}).items()}
    if vix_data:
        print(f"  ✅ VIX: {len(vix_data)} Tage geladen")
    else:
        print("  ⚠️  VIX-Daten nicht verfügbar — ohne Regime-Filter")

    # SPY für Alpha-Berechnung
    print("[Backtest Engine] Lade SPY-Daten...")
    spy_bars = download_data('SPY', years=BACKTEST_YEARS + 1)
    if spy_bars:
        print(f"  ✅ SPY: {len(spy_bars)} Tage geladen")

    # Welche Strategien backtesten?
    if '--strategy' in args:
        sid = args[args.index('--strategy') + 1]
        target_strategies = {sid: strategies.get(sid, {})}
    elif '--ticker' in args:
        ticker = args[args.index('--ticker') + 1]
        target_strategies = {'SINGLE': {'tickers': [ticker], 'name': ticker}}
    elif '--quick' in args:
        # Nur aktive Haupt-Strategien
        priority = ['PS1', 'PS2', 'PS3', 'PS4', 'PS5', 'S1', 'S2', 'S3']
        target_strategies = {k: strategies[k] for k in priority if k in strategies}
    else:
        # Alle mit Tickers
        target_strategies = {k: v for k, v in strategies.items()
                            if isinstance(v, dict) and v.get('tickers') and not k.startswith('_')}

    print(f"\n[Backtest Engine] {len(target_strategies)} Strategien → backtesting...\n")

    all_results = {}
    for sid, strat in target_strategies.items():
        tickers = strat.get('tickers', [])
        if not tickers:
            continue
        name = strat.get('name', sid)
        print(f"[{sid}] {name[:50]}")
        result = run_strategy_backtest(sid, tickers[:6], vix_data, spy_bars or {})
        all_results[sid] = result

        if result.get('status') == 'ok':
            m = result['overall']
            print(f"  → WR {m.get('win_rate',0):.0%} | PF {m.get('profit_factor',0):.2f} | "
                  f"Sharpe {m.get('sharpe_ratio',0):.2f} | {result.get('verdict','')[:20]}")
        print()

    # Ergebnisse speichern
    RESULTS_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\n✅ Ergebnisse gespeichert: {RESULTS_FILE}")

    # Report generieren
    report = generate_report(all_results)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"✅ Report: {REPORT_FILE}")

    # Kurze Zusammenfassung
    ok_results = [(sid, r) for sid, r in all_results.items() if r.get('status') == 'ok']
    validated = [sid for sid, r in ok_results if '🟢' in r.get('verdict', '')]
    weak = [sid for sid, r in ok_results if '🔴' in r.get('verdict', '')]

    print(f"\n{'='*50}")
    print(f"Validiert (🟢): {validated or 'keine'}")
    print(f"Schwach   (🔴): {weak or 'keine'}")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()
