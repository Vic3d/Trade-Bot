#!/usr/bin/env python3
"""
backtester.py — Simple Rule-Based Backtester v1
Paper Trading System Phase 1.4

Rules:
  BUY when: RSI < threshold AND price > SMA(period)
  SELL when: Stop hit (X%) OR Target hit (Y%) OR Trailing stop (Z%)
"""

import sys
import argparse
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from price_db import get_prices, init_tables, STRATEGY_MAP


# Default parameters per strategy
STRATEGY_PARAMS = {
    "PS1": {"rsi_buy": 35, "sma": 50, "stop": 8, "target": 15, "trailing": 5},
    "PS2": {"rsi_buy": 30, "sma": 50, "stop": 10, "target": 20, "trailing": 6},
    "PS3": {"rsi_buy": 35, "sma": 50, "stop": 8, "target": 15, "trailing": 5},
    "PS4": {"rsi_buy": 30, "sma": 50, "stop": 10, "target": 20, "trailing": 7},
    "PS5": {"rsi_buy": 30, "sma": 50, "stop": 12, "target": 25, "trailing": 8},
}


def compute_rsi(closes, period=14):
    """Compute RSI series from close prices."""
    rsi_series = [None] * len(closes)
    if len(closes) < period + 1:
        return rsi_series

    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_series[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_series[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi_series


def compute_sma(closes, period):
    """Compute SMA series."""
    sma = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        sma[i] = sum(closes[i - period + 1:i + 1]) / period
    return sma


def backtest(ticker, rsi_buy=35, sma_period=50, stop_pct=8, target_pct=15, trailing_pct=5):
    """Run backtest on a single ticker."""
    rows = get_prices(ticker)
    if not rows or len(rows) < sma_period + 20:
        return None

    dates = [r[0] for r in rows]
    closes = [r[4] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]

    # Filter out None values
    if any(c is None for c in closes):
        closes = [c if c is not None else 0 for c in closes]

    rsi_series = compute_rsi(closes)
    sma_series = compute_sma(closes, sma_period)

    trades = []
    position = None  # {entry_price, entry_date, entry_idx, high_since_entry}

    for i in range(sma_period, len(closes)):
        price = closes[i]
        rsi = rsi_series[i]
        sma = sma_series[i]

        if price == 0 or sma is None or rsi is None:
            continue

        if position is None:
            # CHECK BUY
            if rsi < rsi_buy and price > sma:
                position = {
                    "entry_price": price,
                    "entry_date": dates[i],
                    "entry_idx": i,
                    "high_since": price,
                }
        else:
            # Update trailing high
            if price > position["high_since"]:
                position["high_since"] = price

            entry = position["entry_price"]
            pnl_pct = (price / entry - 1) * 100
            trailing_from_high = (1 - price / position["high_since"]) * 100

            exit_reason = None

            # CHECK STOP
            if pnl_pct <= -stop_pct:
                exit_reason = "STOP"
            # CHECK TARGET
            elif pnl_pct >= target_pct:
                exit_reason = "TARGET"
            # CHECK TRAILING (only if we're in profit)
            elif pnl_pct > 0 and trailing_pct > 0 and trailing_from_high >= trailing_pct:
                exit_reason = "TRAILING"

            if exit_reason:
                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date": dates[i],
                    "entry_price": entry,
                    "exit_price": price,
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": exit_reason,
                    "days": i - position["entry_idx"],
                })
                position = None

    # Close open position at last price
    if position:
        entry = position["entry_price"]
        pnl_pct = (closes[-1] / entry - 1) * 100
        trades.append({
            "entry_date": position["entry_date"],
            "exit_date": dates[-1],
            "entry_price": entry,
            "exit_price": closes[-1],
            "pnl_pct": round(pnl_pct, 2),
            "reason": "OPEN",
            "days": len(closes) - 1 - position["entry_idx"],
        })

    return trades


def analyze_trades(trades, ticker=""):
    """Analyze trade results."""
    if not trades:
        return {"ticker": ticker, "trades": 0, "message": "Keine Trades generiert"}

    closed = [t for t in trades if t["reason"] != "OPEN"]
    if not closed:
        return {"ticker": ticker, "trades": len(trades), "message": "Nur offene Positionen"}

    wins = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] <= 0]

    total_pnl = sum(t["pnl_pct"] for t in closed)
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    win_rate = len(wins) / len(closed) * 100

    # Max drawdown (cumulative)
    cum = 0
    peak = 0
    max_dd = 0
    for t in closed:
        cum += t["pnl_pct"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Sharpe Ratio (annualized, simplified)
    returns = [t["pnl_pct"] for t in closed]
    if len(returns) > 1:
        mean_ret = sum(returns) / len(returns)
        var = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var) if var > 0 else 0
        sharpe = (mean_ret / std) * math.sqrt(252 / max(1, sum(t["days"] for t in closed) / len(closed))) if std > 0 else 0
    else:
        sharpe = 0

    avg_days = sum(t["days"] for t in closed) / len(closed)

    # Exit reason breakdown
    reasons = {}
    for t in closed:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    return {
        "ticker": ticker,
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(total_pnl, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "avg_days_held": round(avg_days, 1),
        "exit_reasons": reasons,
        "crv_realized": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0,
    }


def print_results(stats, params, trades=None):
    """Pretty-print backtest results."""
    print(f"\n{'='*60}")
    print(f"📊 Backtest: {stats['ticker']}")
    print(f"   Parameter: RSI<{params['rsi_buy']}, SMA{params['sma']}, "
          f"Stop {params['stop']}%, Target {params['target']}%, Trailing {params['trailing']}%")
    print(f"{'='*60}")

    if stats.get("message"):
        print(f"   {stats['message']}")
        return

    print(f"   Trades: {stats['trades']} ({stats['wins']}W / {stats['losses']}L)")
    print(f"   Win-Rate: {stats['win_rate']}%")
    print(f"   Total P&L: {stats['total_pnl_pct']:+.2f}%")
    print(f"   Avg Win: {stats['avg_win_pct']:+.2f}%")
    print(f"   Avg Loss: {stats['avg_loss_pct']:+.2f}%")
    print(f"   CRV realisiert: {stats['crv_realized']:.2f}:1")
    print(f"   Max Drawdown: {stats['max_drawdown_pct']:.2f}%")
    print(f"   Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
    print(f"   Ø Haltedauer: {stats['avg_days_held']:.0f} Tage")
    print(f"   Exit-Gründe: {stats['exit_reasons']}")

    # Show individual trades
    if trades:
        print(f"\n   {'Entry':<12} {'Exit':<12} {'Buy':>8} {'Sell':>8} {'P&L':>8} {'Reason':<10} {'Days':>4}")
        print(f"   {'-'*68}")
        for t in trades:
            emoji = "🟢" if t["pnl_pct"] > 0 else "🔴"
            print(f"   {t['entry_date']:<12} {t['exit_date']:<12} {t['entry_price']:>8.2f} "
                  f"{t['exit_price']:>8.2f} {emoji}{t['pnl_pct']:>+6.1f}% {t['reason']:<10} {t['days']:>4}")


def run_strategy_backtest(strategy):
    """Backtest all tickers in a strategy."""
    strategy = strategy.upper()
    if strategy not in STRATEGY_MAP:
        print(f"❌ Unbekannte Strategie: {strategy}")
        return

    tickers = STRATEGY_MAP[strategy]
    params = STRATEGY_PARAMS.get(strategy, STRATEGY_PARAMS["PS1"])

    print(f"\n🔬 Strategie-Backtest: {strategy}")
    print(f"   Ticker: {', '.join(tickers)}")
    print(f"   Parameter: RSI<{params['rsi_buy']}, SMA{params['sma']}, "
          f"Stop {params['stop']}%, Target {params['target']}%, Trailing {params['trailing']}%")

    all_stats = []
    for ticker in tickers:
        trades = backtest(ticker, params["rsi_buy"], params["sma"], params["stop"], params["target"], params["trailing"])
        if trades:
            stats = analyze_trades(trades, ticker)
            all_stats.append(stats)
            print_results(stats, params)
        else:
            print(f"\n   ⚠ {ticker}: Nicht genug Daten")

    # Summary
    valid = [s for s in all_stats if s.get("trades", 0) > 0]
    if valid:
        total_trades = sum(s["trades"] for s in valid)
        total_wins = sum(s["wins"] for s in valid)
        avg_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
        avg_pnl = sum(s["total_pnl_pct"] for s in valid) / len(valid)

        print(f"\n{'='*60}")
        print(f"📊 Strategie {strategy} — Zusammenfassung")
        print(f"   Ticker getestet: {len(valid)}")
        print(f"   Gesamt-Trades: {total_trades}")
        print(f"   Gesamt Win-Rate: {avg_wr:.1f}%")
        print(f"   Ø P&L pro Ticker: {avg_pnl:+.2f}%")
        print(f"{'='*60}")


if __name__ == "__main__":
    init_tables()

    parser = argparse.ArgumentParser(description="Backtester v1")
    parser.add_argument("ticker", nargs="?", help="Ticker to backtest")
    parser.add_argument("--strategy", "-s", help="Backtest entire strategy (PS1-PS5)")
    parser.add_argument("--rsi-buy", type=int, default=35, help="RSI buy threshold (default: 35)")
    parser.add_argument("--sma", type=int, default=50, help="SMA period (default: 50)")
    parser.add_argument("--stop", type=float, default=8, help="Stop loss %% (default: 8)")
    parser.add_argument("--target", type=float, default=15, help="Target profit %% (default: 15)")
    parser.add_argument("--trailing", type=float, default=5, help="Trailing stop %% (default: 5)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show individual trades")
    args = parser.parse_args()

    if args.strategy:
        run_strategy_backtest(args.strategy)
    elif args.ticker:
        params = {"rsi_buy": args.rsi_buy, "sma": args.sma, "stop": args.stop,
                  "target": args.target, "trailing": args.trailing}
        trades = backtest(args.ticker, args.rsi_buy, args.sma, args.stop, args.target, args.trailing)
        if trades:
            stats = analyze_trades(trades, args.ticker)
            print_results(stats, params, trades if args.verbose else trades)
        else:
            print(f"❌ Keine Daten oder Trades für {args.ticker}")
    else:
        print("Usage:")
        print("  python3 backtester.py NVDA --rsi-buy 35 --sma 50 --stop 8 --target 15")
        print("  python3 backtester.py --strategy PS3")
        sys.exit(1)
