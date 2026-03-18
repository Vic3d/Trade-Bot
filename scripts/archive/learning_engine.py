#!/usr/bin/env python3
"""
learning_engine.py — Cross-Learning Engine
Analysiert Trade-Journal-Daten für Strategie-Gewichte, Fehlermuster und Wochen-Insights.
"""

import sys
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trade_journal import get_db, init_tables, get_closed_trades

DATA_DIR = Path("/data/.openclaw/workspace/data")
WEIGHTS_PATH = DATA_DIR / "strategy_weights.json"
INSIGHTS_PATH = DATA_DIR / "weekly_insights.json"
DB_PATH = Path("/data/.openclaw/workspace/data/trading.db")


def update_strategy_weights():
    """
    Berechnet Win-Rate pro Strategie und schreibt Gewichte.
    Weight = win_rate * avg_win / abs(avg_loss)
    Default 1.0 für Strategien mit <5 Trades.
    """
    init_tables()
    conn = get_db()
    trades = conn.execute("SELECT * FROM trades WHERE status IN ('WIN','LOSS')").fetchall()
    conn.close()

    # Group by strategy
    by_strategy = {}
    for t in trades:
        strat = t["strategy"] or "UNKNOWN"
        by_strategy.setdefault(strat, []).append(t)

    weights = {}
    for strat, strat_trades in sorted(by_strategy.items()):
        wins = [t for t in strat_trades if t["status"] == "WIN"]
        losses = [t for t in strat_trades if t["status"] == "LOSS"]
        total = len(strat_trades)
        win_rate = len(wins) / total if total > 0 else 0

        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

        # Weight calculation
        if total < 5:
            weight = 1.0  # Default — zu wenig Daten
        elif avg_loss == 0:
            weight = win_rate * avg_win if avg_win > 0 else 1.0
        else:
            weight = round(win_rate * avg_win / abs(avg_loss), 3)

        # Paper vs Real breakdown
        paper_trades = [t for t in strat_trades if (t["trade_type"] or "paper") == "paper"]
        real_trades = [t for t in strat_trades if (t["trade_type"] or "paper") == "real"]
        paper_wins = [t for t in paper_trades if t["status"] == "WIN"]
        real_wins = [t for t in real_trades if t["status"] == "WIN"]

        weights[strat] = {
            "trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 3),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "weight": weight,
            "paper_trades": len(paper_trades),
            "paper_win_rate": round(len(paper_wins) / len(paper_trades), 3) if paper_trades else 0,
            "real_trades": len(real_trades),
            "real_win_rate": round(len(real_wins) / len(real_trades), 3) if real_trades else 0,
        }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(weights, f, indent=2, ensure_ascii=False)

    return weights


def print_weights():
    """Display strategy weights."""
    weights = update_strategy_weights()
    if not weights:
        print("📊 Keine geschlossenen Trades — keine Gewichte berechenbar")
        return

    print("📊 Strategie-Gewichte:")
    print(f"{'Strat':<8} {'Trades':>6} {'W/L':>8} {'WR':>7} {'AvgW':>7} {'AvgL':>7} {'Weight':>8} {'Paper WR':>10} {'Real WR':>10}")
    print("-" * 85)
    for strat, w in sorted(weights.items(), key=lambda x: x[1]["weight"], reverse=True):
        wr_str = f"{w['win_rate']*100:.1f}%"
        pw = f"{w['paper_win_rate']*100:.0f}% ({w['paper_trades']}T)" if w['paper_trades'] > 0 else "—"
        rw = f"{w['real_win_rate']*100:.0f}% ({w['real_trades']}T)" if w['real_trades'] > 0 else "—"
        note = " ⚠️<5T" if w["trades"] < 5 else ""
        print(f"{strat:<8} {w['trades']:>6} {w['wins']}W/{w['losses']}L  {wr_str:>6} {w['avg_win']:>+7.2f} {w['avg_loss']:>+7.2f} {w['weight']:>8.3f} {pw:>10} {rw:>10}{note}")


def check_error_patterns(ticker, strategy, entry_price):
    """
    Prüft ob ähnliche Trades in der Vergangenheit gescheitert sind.
    Returns: Liste von Warnungen.
    """
    init_tables()
    conn = get_db()
    warnings = []

    # 1. Check losses in same strategy
    strat_losses = conn.execute(
        "SELECT * FROM trades WHERE strategy = ? AND status = 'LOSS' ORDER BY exit_date DESC",
        (strategy.upper(),)
    ).fetchall()

    if strat_losses:
        last_loss = strat_losses[0]
        total_strat = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE strategy = ? AND status IN ('WIN','LOSS')",
            (strategy.upper(),)
        ).fetchone()[0]
        loss_rate = len(strat_losses) / total_strat * 100 if total_strat > 0 else 0

        if loss_rate > 60:
            warnings.append(
                f"⚠️ {strategy} hat {loss_rate:.0f}% Verlustquote ({len(strat_losses)}/{total_strat} Trades). Erhöhtes Risiko!"
            )
        warnings.append(
            f"ℹ️ Letzter {strategy}-Verlust: {last_loss['ticker']} "
            f"({last_loss['entry_price']:.2f} → {last_loss['exit_price']:.2f}, "
            f"{last_loss['pnl_pct']:+.1f}%) am {last_loss['exit_date']}"
            + (f". Lektion: {last_loss['lessons']}" if last_loss['lessons'] else "")
        )

    # 2. Check losses with same ticker
    ticker_losses = conn.execute(
        "SELECT * FROM trades WHERE ticker = ? AND status = 'LOSS' ORDER BY exit_date DESC",
        (ticker.upper(),)
    ).fetchall()

    if ticker_losses:
        last = ticker_losses[0]
        warnings.append(
            f"⚠️ {ticker} hatte bereits {len(ticker_losses)} Verlust-Trade(s). "
            f"Letzter: {last['pnl_pct']:+.1f}% am {last['exit_date']}"
            + (f". Lektion: {last['lessons']}" if last['lessons'] else "")
        )

    # 3. Check same-sector losses (via strategy mapping)
    try:
        from price_db import STRATEGY_MAP
        # Find which strategies this ticker belongs to
        ticker_strategies = [s for s, tickers in STRATEGY_MAP.items() if ticker.upper() in tickers]
        for ts in ticker_strategies:
            if ts == strategy.upper():
                continue
            sector_losses = conn.execute(
                "SELECT * FROM trades WHERE strategy = ? AND status = 'LOSS' ORDER BY exit_date DESC LIMIT 3",
                (ts,)
            ).fetchall()
            if sector_losses:
                tickers_lost = ", ".join(set(t["ticker"] for t in sector_losses))
                warnings.append(
                    f"ℹ️ Verwandte Strategie {ts} hatte Verluste bei: {tickers_lost}"
                )
    except ImportError:
        pass

    # 4. Check overall recent losing streak
    recent = conn.execute(
        "SELECT * FROM trades WHERE status IN ('WIN','LOSS') ORDER BY exit_date DESC LIMIT 5"
    ).fetchall()
    if len(recent) >= 3:
        last_3 = recent[:3]
        if all(t["status"] == "LOSS" for t in last_3):
            warnings.append("🔴 Achtung: 3 Verluste in Folge! Risiko reduzieren oder pausieren.")

    conn.close()

    if not warnings:
        warnings.append(f"✅ Keine bekannten Fehlermuster für {ticker} / {strategy}")

    return warnings


def generate_weekly_insights():
    """
    Analysiert Trades der letzten 7 Tage und generiert Insights.
    """
    init_tables()
    conn = get_db()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    trades = conn.execute(
        "SELECT * FROM trades WHERE exit_date >= ? AND status IN ('WIN','LOSS') ORDER BY exit_date",
        (week_ago,)
    ).fetchall()

    # Also get opened trades this week
    opened = conn.execute(
        "SELECT * FROM trades WHERE entry_date >= ? ORDER BY entry_date",
        (week_ago,)
    ).fetchall()

    conn.close()

    insights = {
        "period": f"{week_ago} bis {datetime.now().strftime('%Y-%m-%d')}",
        "generated": datetime.now().isoformat(),
        "closed_trades": len(trades),
        "opened_trades": len(opened),
        "strategies": {},
        "summary": "",
        "lessons": [],
    }

    if not trades:
        insights["summary"] = "Keine geschlossenen Trades in den letzten 7 Tagen."
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(INSIGHTS_PATH, "w") as f:
            json.dump(insights, f, indent=2, ensure_ascii=False)
        return insights

    # Analyze by strategy
    by_strat = {}
    for t in trades:
        strat = t["strategy"] or "UNKNOWN"
        by_strat.setdefault(strat, []).append(t)

    best_strat = None
    best_wr = -1
    worst_strat = None
    worst_wr = 101

    for strat, strat_trades in by_strat.items():
        wins = [t for t in strat_trades if t["status"] == "WIN"]
        losses = [t for t in strat_trades if t["status"] == "LOSS"]
        total = len(strat_trades)
        wr = len(wins) / total * 100 if total > 0 else 0
        total_pnl = sum(t["pnl_eur"] or 0 for t in strat_trades)

        insights["strategies"][strat] = {
            "trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(wr, 1),
            "total_pnl": round(total_pnl, 2),
        }

        if wr > best_wr or (wr == best_wr and total > (len(by_strat.get(best_strat, [])) if best_strat else 0)):
            best_wr = wr
            best_strat = strat
        if wr < worst_wr or (wr == worst_wr and len(losses) > 0):
            worst_wr = wr
            worst_strat = strat

    # Build summary
    wins_total = [t for t in trades if t["status"] == "WIN"]
    losses_total = [t for t in trades if t["status"] == "LOSS"]
    total_pnl = sum(t["pnl_eur"] or 0 for t in trades)

    parts = [
        f"{len(trades)} Trades geschlossen ({len(wins_total)}W/{len(losses_total)}L), P&L: {total_pnl:+.2f}€."
    ]
    if best_strat:
        bs = insights["strategies"][best_strat]
        parts.append(f"Beste Strategie: {best_strat} ({bs['wins']} Wins).")
    if worst_strat and worst_strat != best_strat:
        ws = insights["strategies"][worst_strat]
        parts.append(f"Schlechteste: {worst_strat} ({ws['losses']} Losses).")

    insights["summary"] = " ".join(parts)

    # Extract lessons from trades
    for t in trades:
        if t["lessons"]:
            insights["lessons"].append(f"{t['ticker']} ({t['strategy']}): {t['lessons']}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(INSIGHTS_PATH, "w") as f:
        json.dump(insights, f, indent=2, ensure_ascii=False)

    return insights


def print_weekly():
    """Display weekly insights."""
    insights = generate_weekly_insights()

    print("📊 Wochen-Insights")
    print(f"   Zeitraum: {insights['period']}")
    print(f"   {insights['summary']}")

    if insights["strategies"]:
        print("\n   Nach Strategie:")
        for strat, s in sorted(insights["strategies"].items()):
            emoji = "🟢" if s["win_rate"] >= 50 else "🔴"
            print(f"   {emoji} {strat}: {s['trades']}T ({s['wins']}W/{s['losses']}L) "
                  f"WR {s['win_rate']}% | P&L {s['total_pnl']:+.2f}€")

    if insights["lessons"]:
        print("\n   📝 Lektionen:")
        for lesson in insights["lessons"]:
            print(f"   - {lesson}")

    print(f"\n💾 Gespeichert: {INSIGHTS_PATH}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 learning_engine.py weights           — Strategie-Gewichte anzeigen")
        print("  python3 learning_engine.py check TICKER STRATEGY PRICE — Pre-Trade Warnung")
        print("  python3 learning_engine.py weekly             — Wochen-Insights")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "weights":
        print_weights()

    elif cmd == "check":
        if len(sys.argv) < 5:
            print("Usage: python3 learning_engine.py check TICKER STRATEGY PRICE")
            sys.exit(1)
        ticker = sys.argv[2].upper()
        strategy = sys.argv[3].upper()
        price = float(sys.argv[4])
        warnings = check_error_patterns(ticker, strategy, price)
        print(f"🔍 Pre-Trade Check: {ticker} / {strategy} @ {price:.2f}")
        for w in warnings:
            print(f"   {w}")

    elif cmd == "weekly":
        print_weekly()

    else:
        print(f"Unbekannter Befehl: {cmd}")
        sys.exit(1)
