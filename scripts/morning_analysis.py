#!/usr/bin/env python3
"""
morning_analysis.py — Morgen-Analyse für Portfolio + Screener
Kombiniert echtes Portfolio, Screener-Picks und Warnungen.
"""

import sys
import json
from pathlib import Path

# Import from siblings
sys.path.insert(0, str(Path(__file__).parent))
from price_db import (
    get_closes, get_sma, get_rsi, get_relative_strength, get_volume_ratio,
    update_daily, ALL_TICKERS, STRATEGY_MAP, init_tables
)
from stock_screener import screen_ticker, run_screener, SCREENABLE, SCREEN_EXCLUDE

TRADING_CONFIG = Path("/data/.openclaw/workspace/trading_config.json")
DATA_DIR = Path("/data/.openclaw/workspace/data")


def load_portfolio():
    """Load active positions from trading_config.json (status != CLOSED)."""
    if not TRADING_CONFIG.exists():
        print("⚠️ trading_config.json nicht gefunden")
        return {}
    with open(TRADING_CONFIG) as f:
        config = json.load(f)
    positions = config.get("positions", {})
    active = {}
    for key, pos in positions.items():
        if pos.get("status", "").upper() == "CLOSED":
            continue
        active[key] = pos
    return active


def get_macro():
    """Get VIX, WTI, EUR/USD data."""
    macro = {}
    for ticker, label in [("^VIX", "VIX"), ("CL=F", "WTI"), ("EURUSD=X", "EUR/USD")]:
        closes = get_closes(ticker)
        rsi = get_rsi(ticker)
        if closes:
            macro[label] = {"price": round(closes[-1], 2), "rsi": round(rsi, 1) if rsi else None}
        else:
            macro[label] = {"price": None, "rsi": None}
    return macro


def score_label(score):
    """Human-readable label for score."""
    if score >= 70:
        return "STARK 🟢"
    elif score >= 50:
        return "NEUTRAL 🟡"
    else:
        return "SCHWACH 🔴"


def ticker_for_yahoo(key, pos):
    """Get the Yahoo ticker for a position."""
    if "yahoo" in pos:
        return pos["yahoo"]
    # For DE stocks with onvista, the key might be the ticker
    return key


def run_morning_analysis(update_prices=True):
    """Run full morning analysis."""
    init_tables()

    # 1. Update prices
    if update_prices:
        print("📡 Kurse aktualisieren...")
        update_daily(ALL_TICKERS)
        print()

    # 2. Macro
    macro = get_macro()

    print("=" * 60)
    print("=== MORGEN-ANALYSE ===")
    print("=" * 60)

    # Macro section
    print("\n📊 MAKRO")
    parts = []
    vix = macro.get("VIX", {})
    wti = macro.get("WTI", {})
    eurusd = macro.get("EUR/USD", {})
    if vix["price"]:
        rsi_str = f" (RSI: {vix['rsi']:.0f})" if vix["rsi"] else ""
        parts.append(f"VIX: {vix['price']:.1f}{rsi_str}")
    if wti["price"]:
        rsi_str = f" (RSI: {wti['rsi']:.0f})" if wti["rsi"] else ""
        parts.append(f"WTI: ${wti['price']:.2f}{rsi_str}")
    if eurusd["price"]:
        parts.append(f"EUR/USD: {eurusd['price']:.4f}")
    print(" | ".join(parts) if parts else "Keine Makro-Daten")

    # 3. Portfolio scoring
    portfolio = load_portfolio()
    # Pre-compute all RS values for quartile ranking
    all_rs = [get_relative_strength(t) for t in SCREENABLE]

    warnings = []

    if portfolio:
        print(f"\n📈 ECHTES PORTFOLIO — Screener-Bewertung")
        portfolio_scores = []
        for key, pos in portfolio.items():
            yahoo_ticker = ticker_for_yahoo(key, pos)
            result = screen_ticker(yahoo_ticker, all_rs)
            name = pos.get("name", key)
            if result:
                s = result["score"]
                f = result["factors"]
                f1 = f["F1_RSI"]["score"]
                f2 = f["F2_Trend"]["score"]
                f3 = f["F3_RelStärke"]["score"]
                f4 = f["F4_SMA50Dist"]["score"]
                f5 = f["F5_Volumen"]["score"]
                label = score_label(s)
                print(f"  {key} ({name}): Score {s}/100 "
                      f"(Trend {f2}, RSI {f1}, RS {f3}, Support {f4}, Vol {f5}) — {label}")
                portfolio_scores.append((key, name, result))

                # Generate warnings
                rsi_val = get_rsi(yahoo_ticker)
                if s < 50:
                    warnings.append(f"{key} ({name}) Score unter 50 → Position unter Beobachtung")
                if rsi_val and rsi_val > 70:
                    warnings.append(f"{key} ({name}) RSI {rsi_val:.0f} über 70 → überkauft, Trailing prüfen")
                if rsi_val and rsi_val < 30:
                    warnings.append(f"{key} ({name}) RSI {rsi_val:.0f} unter 30 → überverkauft")
            else:
                print(f"  {key} ({name}): Keine Daten verfügbar")

    # 4. Top screener picks
    print(f"\n🔍 TOP SCREENER-PICKS (Paper Fund Kandidaten)")

    # Get portfolio tickers to exclude from picks
    portfolio_tickers = set()
    for key, pos in portfolio.items():
        portfolio_tickers.add(ticker_for_yahoo(key, pos))
        portfolio_tickers.add(key)

    # Screen all tickers
    all_results = []
    for ticker in SCREENABLE:
        if ticker in portfolio_tickers:
            continue
        result = screen_ticker(ticker, all_rs)
        if result:
            all_results.append(result)
    all_results.sort(key=lambda x: x["score"], reverse=True)

    for i, r in enumerate(all_results[:10], 1):
        strats = ",".join(r["strategies"]) if r["strategies"] else "-"
        rsi = get_rsi(r["ticker"])
        sma50 = get_sma(r["ticker"], 50)
        price = r["price"]

        details = []
        if rsi:
            details.append(f"RSI {rsi:.0f}")
        if sma50 and price:
            if price > sma50:
                details.append("über SMA50")
            else:
                details.append("unter SMA50")
        vol_ratio = get_volume_ratio(r["ticker"])
        if vol_ratio and vol_ratio > 1.1:
            details.append("starkes Volumen")

        detail_str = ", ".join(details) if details else ""
        print(f"  {i}. {r['ticker']}: {r['score']}/100 — {strats} | {detail_str}")

        # Warnings for screener picks
        if rsi and rsi > 70:
            warnings.append(f"{r['ticker']} RSI über 70 → überkauft, Einstieg abwarten")

    # 5. Warnings
    if warnings:
        print(f"\n⚠️ WARNUNGEN")
        for w in warnings:
            print(f"  - {w}")
    else:
        print(f"\n✅ Keine Warnungen")

    print()

    # Save results to JSON
    output = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "macro": macro,
        "warnings": warnings,
        "top_picks": [{"ticker": r["ticker"], "score": r["score"], "strategies": r["strategies"]}
                      for r in all_results[:10]],
    }
    output_path = DATA_DIR / "morning_analysis.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"💾 Ergebnis gespeichert: {output_path}")


if __name__ == "__main__":
    skip_update = "--no-update" in sys.argv
    run_morning_analysis(update_prices=not skip_update)
