#!/usr/bin/env python3
"""
stock_screener.py — Multi-Faktor Stock Screener
Paper Trading System Phase 1.2

Scoring (max 100):
  F1: RSI-Zone (0-20)
  F2: Trend SMA50/200 (0-20)
  F3: Relative Stärke vs S&P500 (0-20)
  F4: Abstand zu SMA50 (0-20)
  F5: Volumen-Trend (0-20)
"""

import sys
import json
import argparse
from pathlib import Path

# Import from price_db
sys.path.insert(0, str(Path(__file__).parent))
from price_db import (
    get_closes, get_sma, get_rsi, get_relative_strength, get_volume_ratio,
    STRATEGY_MAP, ALL_TICKERS, init_tables
)

# Exclude indices/FX from screening
SCREEN_EXCLUDE = {"^GSPC", "^VIX", "^GDAXI", "CL=F", "GC=F", "EURUSD=X", "EURGBP=X", "EURNOK=X"}
SCREENABLE = [t for t in ALL_TICKERS if t not in SCREEN_EXCLUDE]


def score_rsi(rsi_val):
    """F1: RSI Zone scoring."""
    if rsi_val is None:
        return 10, "RSI n/a"
    if rsi_val < 30:
        return 20, f"RSI {rsi_val:.0f} überverkauft ⬇"
    elif rsi_val <= 70:
        return 10, f"RSI {rsi_val:.0f} neutral"
    else:
        return 0, f"RSI {rsi_val:.0f} überkauft ⬆"


def score_trend(price, sma50, sma200):
    """F2: Trend scoring."""
    if price is None or sma50 is None:
        return 0, "Trend n/a"
    if sma200 is not None and price > sma50 > sma200:
        return 20, "Kurs > SMA50 > SMA200 ✅"
    elif price > sma50:
        return 10, "Kurs > SMA50"
    else:
        return 0, "Kurs < SMA50 ❌"


def score_relative_strength(rs_val, all_rs):
    """F3: Relative Stärke vs S&P500."""
    if rs_val is None:
        return 5, "RS n/a"
    valid = sorted([v for v in all_rs if v is not None])
    if not valid:
        return 5, "RS n/a"
    rank_pct = sum(1 for v in valid if v <= rs_val) / len(valid)
    if rank_pct >= 0.75:
        return 20, f"RS {rs_val:+.1f}% Top-Quartil 🔥"
    elif rank_pct >= 0.50:
        return 15, f"RS {rs_val:+.1f}% 2. Quartil"
    elif rank_pct >= 0.25:
        return 5, f"RS {rs_val:+.1f}% 3. Quartil"
    else:
        return 0, f"RS {rs_val:+.1f}% Bottom ❌"


def score_sma_distance(price, sma50):
    """F4: Abstand zu SMA50."""
    if price is None or sma50 is None or sma50 == 0:
        return 5, "SMA50-Abstand n/a"
    dist_pct = abs(price - sma50) / sma50 * 100
    if dist_pct < 3:
        return 20, f"{dist_pct:.1f}% nahe Support 🎯"
    elif dist_pct <= 8:
        return 10, f"{dist_pct:.1f}% moderate Distanz"
    else:
        return 5, f"{dist_pct:.1f}% weit entfernt"


def score_volume(vol_ratio):
    """F5: Volumen-Trend."""
    if vol_ratio is None:
        return 10, "Volumen n/a"
    if vol_ratio > 1.1:
        return 20, f"Vol 5d/20d: {vol_ratio:.2f}x steigend 📈"
    elif vol_ratio >= 0.9:
        return 10, f"Vol 5d/20d: {vol_ratio:.2f}x stabil"
    else:
        return 0, f"Vol 5d/20d: {vol_ratio:.2f}x fallend 📉"


def screen_ticker(ticker, all_rs_values):
    """Score a single ticker."""
    closes = get_closes(ticker)
    if not closes or len(closes) < 50:
        return None

    price = closes[-1]
    sma50 = get_sma(ticker, 50)
    sma200 = get_sma(ticker, 200)
    rsi = get_rsi(ticker)
    rs = get_relative_strength(ticker)
    vol_ratio = get_volume_ratio(ticker)

    f1_score, f1_reason = score_rsi(rsi)
    f2_score, f2_reason = score_trend(price, sma50, sma200)
    f3_score, f3_reason = score_relative_strength(rs, all_rs_values)
    f4_score, f4_reason = score_sma_distance(price, sma50)
    f5_score, f5_reason = score_volume(vol_ratio)

    total = f1_score + f2_score + f3_score + f4_score + f5_score

    # Strategy assignment
    strategies = [s for s, tickers in STRATEGY_MAP.items() if ticker in tickers]

    return {
        "ticker": ticker,
        "price": round(price, 2),
        "score": total,
        "strategies": strategies,
        "factors": {
            "F1_RSI": {"score": f1_score, "reason": f1_reason},
            "F2_Trend": {"score": f2_score, "reason": f2_reason},
            "F3_RelStärke": {"score": f3_score, "reason": f3_reason},
            "F4_SMA50Dist": {"score": f4_score, "reason": f4_reason},
            "F5_Volumen": {"score": f5_score, "reason": f5_reason},
        }
    }


def run_screener(tickers=None, strategy=None, top_n=20):
    """Run full screening."""
    init_tables()

    if strategy:
        strategy = strategy.upper()
        if strategy not in STRATEGY_MAP:
            print(f"❌ Unbekannte Strategie: {strategy}. Verfügbar: {', '.join(STRATEGY_MAP.keys())}")
            return []
        tickers = STRATEGY_MAP[strategy]
        print(f"📊 Screener für Strategie {strategy} ({len(tickers)} Ticker)")
    else:
        tickers = tickers or SCREENABLE
        print(f"📊 Screener für {len(tickers)} Ticker")

    # Pre-compute all relative strengths for quartile ranking
    all_rs = []
    for t in SCREENABLE:
        rs = get_relative_strength(t)
        all_rs.append(rs)

    results = []
    for ticker in tickers:
        if ticker in SCREEN_EXCLUDE:
            continue
        result = screen_ticker(ticker, all_rs)
        if result:
            results.append(result)

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Print human-readable
    print(f"\n{'='*70}")
    print(f"{'Rank':>4} {'Ticker':<10} {'Preis':>10} {'Score':>6} {'Strategie':<10} Faktoren")
    print(f"{'='*70}")

    for i, r in enumerate(results[:top_n], 1):
        strats = ",".join(r["strategies"]) if r["strategies"] else "-"
        factors_short = " | ".join([
            f"{v['reason']}" for v in r["factors"].values()
        ])
        print(f"{i:>4}. {r['ticker']:<10} {r['price']:>10.2f} {r['score']:>5}/100 {strats:<10}")
        # Detail line
        for fname, fdata in r["factors"].items():
            print(f"       {fname}: {fdata['score']:>2}pts — {fdata['reason']}")
        print()

    # JSON output
    json_path = Path("/data/.openclaw/workspace/data/screener_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n💾 JSON gespeichert: {json_path}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Screener")
    parser.add_argument("--strategy", "-s", help="Filter by strategy (PS1-PS5)")
    parser.add_argument("--top", "-n", type=int, default=20, help="Top N results")
    parser.add_argument("--json", action="store_true", help="JSON-only output")
    args = parser.parse_args()

    results = run_screener(strategy=args.strategy, top_n=args.top)
