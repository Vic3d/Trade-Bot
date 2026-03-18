#!/usr/bin/env python3
"""
trade_journal.py — Paper & Real Trade Journal (SQLite)
Paper Trading System Phase 1.3 + Cross-Learning

⚠️  DEPRECATED: Dieses Script wird noch von unified_scorer importiert.
    Neue Trades bitte über learning_system.py sync verwalten.
    Direkte Nutzung weiterhin möglich, aber learning_system.py ist der bevorzugte Weg.
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/data/.openclaw/workspace/data/trading.db")


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            strategy TEXT,
            direction TEXT DEFAULT 'LONG',
            entry_price REAL,
            entry_date TEXT,
            exit_price REAL,
            exit_date TEXT,
            stop REAL,
            target REAL,
            shares REAL,
            pnl_eur REAL,
            pnl_pct REAL,
            status TEXT DEFAULT 'OPEN',
            thesis TEXT,
            result TEXT,
            lessons TEXT,
            trade_type TEXT DEFAULT 'paper'
        )
    """)
    conn.commit()
    # Migration: add trade_type column if missing
    _migrate_trade_type(conn)
    conn.close()


def _migrate_trade_type(conn):
    """Add trade_type column to existing DB if it doesn't exist."""
    cursor = conn.execute("PRAGMA table_info(trades)")
    columns = [row[1] for row in cursor.fetchall()]
    if "trade_type" not in columns:
        conn.execute("ALTER TABLE trades ADD COLUMN trade_type TEXT DEFAULT 'paper'")
        conn.commit()
        print("🔄 Migration: trade_type Spalte hinzugefügt (Default: 'paper')")


def open_trade(ticker, strategy, direction, entry_price, stop, target, shares, thesis, trade_type="paper"):
    """Open a new paper or real trade."""
    if trade_type not in ("paper", "real"):
        print(f"❌ Ungültiger trade_type: {trade_type}. Erlaubt: 'paper', 'real'")
        return None
    init_tables()
    conn = get_db()
    entry_date = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO trades (ticker, strategy, direction, entry_price, entry_date, 
           stop, target, shares, status, thesis, trade_type) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (ticker.upper(), strategy.upper(), direction.upper(), entry_price, entry_date,
         stop, target, shares, "OPEN", thesis, trade_type)
    )
    conn.commit()
    trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    risk = abs(entry_price - stop) * shares
    reward = abs(target - entry_price) * shares
    crv = reward / risk if risk > 0 else 0

    type_label = "📝 PAPER" if trade_type == "paper" else "💰 REAL"
    print(f"✅ Trade #{trade_id} eröffnet ({type_label}):")
    print(f"   {direction} {shares}x {ticker} @ {entry_price:.2f}")
    print(f"   Stop: {stop:.2f} | Target: {target:.2f}")
    print(f"   Risiko: {risk:.2f} | Chance: {reward:.2f} | CRV: {crv:.1f}:1")
    print(f"   Strategie: {strategy} | These: {thesis}")
    return trade_id


def close_trade(trade_id, exit_price, result="", lessons=""):
    """Close an existing trade."""
    init_tables()
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade:
        print(f"❌ Trade #{trade_id} nicht gefunden")
        return

    if trade["status"] != "OPEN":
        print(f"⚠ Trade #{trade_id} ist bereits {trade['status']}")
        return

    entry = trade["entry_price"]
    shares = trade["shares"]
    direction = trade["direction"]

    if direction == "LONG":
        pnl = (exit_price - entry) * shares
        pnl_pct = (exit_price / entry - 1) * 100
    else:
        pnl = (entry - exit_price) * shares
        pnl_pct = (1 - exit_price / entry) * 100

    exit_date = datetime.now().strftime("%Y-%m-%d")
    status = "WIN" if pnl > 0 else "LOSS"

    conn.execute(
        """UPDATE trades SET exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?, 
           status=?, result=?, lessons=? WHERE id=?""",
        (exit_price, exit_date, round(pnl, 2), round(pnl_pct, 2), status, result, lessons, trade_id)
    )
    conn.commit()
    conn.close()

    trade_type = trade["trade_type"] or "paper"
    type_label = "📝 PAPER" if trade_type == "paper" else "💰 REAL"
    emoji = "🟢" if pnl > 0 else "🔴"
    print(f"{emoji} Trade #{trade_id} geschlossen ({type_label}):")
    print(f"   {trade['ticker']} {direction}: {entry:.2f} → {exit_price:.2f}")
    print(f"   P&L: {pnl:+.2f} EUR ({pnl_pct:+.1f}%)")
    print(f"   Ergebnis: {result}")
    if lessons:
        print(f"   Lektion: {lessons}")


def get_open_trades():
    """List all open trades."""
    init_tables()
    conn = get_db()
    trades = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY entry_date").fetchall()
    conn.close()
    return trades


def _build_stats(trades):
    """Compute stats from a list of closed trade rows."""
    if not trades:
        return {"total": 0, "message": "Keine geschlossenen Trades"}

    wins = [t for t in trades if t["status"] == "WIN"]
    losses = [t for t in trades if t["status"] == "LOSS"]

    total = len(trades)
    win_rate = len(wins) / total * 100 if total > 0 else 0
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t["pnl_eur"] for t in trades)
    avg_crv = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "total_pnl_eur": round(total_pnl, 2),
        "realized_crv": round(avg_crv, 2),
    }


def get_stats(trade_type="all"):
    """Overall trading statistics, filterable by trade_type ('paper', 'real', 'all')."""
    init_tables()
    conn = get_db()
    if trade_type == "all":
        closed = conn.execute("SELECT * FROM trades WHERE status IN ('WIN','LOSS')").fetchall()
    else:
        closed = conn.execute(
            "SELECT * FROM trades WHERE status IN ('WIN','LOSS') AND trade_type = ?",
            (trade_type,)
        ).fetchall()
    conn.close()
    return _build_stats(closed)


def get_stats_by_strategy(trade_type="all"):
    """Stats broken down by strategy, with paper/real comparison."""
    init_tables()
    conn = get_db()
    strategies = conn.execute("SELECT DISTINCT strategy FROM trades WHERE status IN ('WIN','LOSS')").fetchall()
    result = {}

    for s in strategies:
        strat = s["strategy"]

        if trade_type == "all":
            trades = conn.execute(
                "SELECT * FROM trades WHERE strategy = ? AND status IN ('WIN','LOSS')", (strat,)
            ).fetchall()
        else:
            trades = conn.execute(
                "SELECT * FROM trades WHERE strategy = ? AND status IN ('WIN','LOSS') AND trade_type = ?",
                (strat, trade_type)
            ).fetchall()

        if not trades:
            continue

        # Always compute paper vs real breakdown
        paper_trades = [t for t in trades if (t["trade_type"] or "paper") == "paper"]
        real_trades = [t for t in trades if (t["trade_type"] or "paper") == "real"]

        wins = [t for t in trades if t["status"] == "WIN"]
        losses = [t for t in trades if t["status"] == "LOSS"]
        total = len(trades)
        win_rate = len(wins) / total * 100 if total > 0 else 0
        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
        total_pnl = sum(t["pnl_eur"] for t in trades)

        paper_wins = [t for t in paper_trades if t["status"] == "WIN"]
        paper_wr = len(paper_wins) / len(paper_trades) * 100 if paper_trades else 0
        real_wins = [t for t in real_trades if t["status"] == "WIN"]
        real_wr = len(real_wins) / len(real_trades) * 100 if real_trades else 0

        result[strat] = {
            "total": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "total_pnl_eur": round(total_pnl, 2),
            "paper_trades": len(paper_trades),
            "paper_win_rate": round(paper_wr, 1),
            "real_trades": len(real_trades),
            "real_win_rate": round(real_wr, 1),
        }

    conn.close()
    return result


def get_closed_trades(trade_type="all"):
    """Get all closed trades, optionally filtered by type."""
    init_tables()
    conn = get_db()
    if trade_type == "all":
        trades = conn.execute("SELECT * FROM trades WHERE status IN ('WIN','LOSS') ORDER BY exit_date").fetchall()
    else:
        trades = conn.execute(
            "SELECT * FROM trades WHERE status IN ('WIN','LOSS') AND trade_type = ? ORDER BY exit_date",
            (trade_type,)
        ).fetchall()
    conn.close()
    return trades


def print_open_trades():
    trades = get_open_trades()
    if not trades:
        print("📋 Keine offenen Trades")
        return
    print(f"📋 {len(trades)} offene Trades:")
    print(f"{'ID':>4} {'Typ':<6} {'Ticker':<10} {'Dir':<5} {'Entry':>8} {'Stop':>8} {'Target':>8} {'Shares':>7} {'Strat':<6} Datum")
    print("-" * 90)
    for t in trades:
        tt = (t['trade_type'] or 'paper').upper()[:5]
        print(f"{t['id']:>4} {tt:<6} {t['ticker']:<10} {t['direction']:<5} {t['entry_price']:>8.2f} "
              f"{t['stop']:>8.2f} {t['target']:>8.2f} {t['shares']:>7.2f} {t['strategy']:<6} {t['entry_date']}")
        if t['thesis']:
            print(f"     These: {t['thesis']}")


def print_stats(trade_type="all"):
    if trade_type == "all":
        # Show paper, real, and combined
        for tt, label in [("paper", "📝 Paper"), ("real", "💰 Real"), ("all", "📊 Gesamt")]:
            stats = get_stats(tt)
            if stats.get("total", 0) == 0:
                if tt != "all":
                    continue
                print(f"{label}: Noch keine geschlossenen Trades")
                return
            print(f"\n{label} Trading-Statistik:")
            print(f"   Trades: {stats['total']} ({stats['wins']}W / {stats['losses']}L)")
            print(f"   Win-Rate: {stats['win_rate']}%")
            print(f"   Avg Win: {stats['avg_win_pct']:+.2f}%")
            print(f"   Avg Loss: {stats['avg_loss_pct']:+.2f}%")
            print(f"   CRV realisiert: {stats['realized_crv']:.2f}:1")
            print(f"   Total P&L: {stats['total_pnl_eur']:+.2f} EUR")
    else:
        stats = get_stats(trade_type)
        if stats.get("total", 0) == 0:
            label = "📝 Paper" if trade_type == "paper" else "💰 Real"
            print(f"{label}: Noch keine geschlossenen Trades")
            return
        label = "📝 Paper" if trade_type == "paper" else "💰 Real"
        print(f"\n{label} Trading-Statistik:")
        print(f"   Trades: {stats['total']} ({stats['wins']}W / {stats['losses']}L)")
        print(f"   Win-Rate: {stats['win_rate']}%")
        print(f"   Avg Win: {stats['avg_win_pct']:+.2f}%")
        print(f"   Avg Loss: {stats['avg_loss_pct']:+.2f}%")
        print(f"   CRV realisiert: {stats['realized_crv']:.2f}:1")
        print(f"   Total P&L: {stats['total_pnl_eur']:+.2f} EUR")

    by_strat = get_stats_by_strategy(trade_type)
    if by_strat:
        print("\n📊 Nach Strategie (Paper vs Real):")
        for strat, s in sorted(by_strat.items()):
            paper_info = f"Paper: {s['paper_trades']}T WR {s['paper_win_rate']}%" if s['paper_trades'] > 0 else "Paper: —"
            real_info = f"Real: {s['real_trades']}T WR {s['real_win_rate']}%" if s['real_trades'] > 0 else "Real: —"
            print(f"   {strat}: {s['total']}T ({s['wins']}W/{s['losses']}L) "
                  f"WR {s['win_rate']}% | P&L {s['total_pnl_eur']:+.2f}€ | {paper_info} | {real_info}")


def print_all_trades():
    """List all trades (open + closed)."""
    init_tables()
    conn = get_db()
    trades = conn.execute("SELECT * FROM trades ORDER BY entry_date DESC").fetchall()
    conn.close()

    if not trades:
        print("📋 Keine Trades vorhanden")
        return

    print(f"📋 Alle Trades ({len(trades)}):")
    print(f"{'ID':>4} {'Typ':<6} {'Status':<6} {'Ticker':<10} {'Dir':<5} {'Entry':>8} {'Exit':>8} {'P&L%':>8} {'P&L€':>10} {'Strat':<5}")
    print("-" * 85)
    for t in trades:
        exit_p = f"{t['exit_price']:.2f}" if t['exit_price'] else "—"
        pnl_pct = f"{t['pnl_pct']:+.1f}%" if t['pnl_pct'] is not None else "—"
        pnl_eur = f"{t['pnl_eur']:+.2f}" if t['pnl_eur'] is not None else "—"
        status_emoji = {"OPEN": "🔵", "WIN": "🟢", "LOSS": "🔴"}.get(t['status'], "⚪")
        tt = (t['trade_type'] or 'paper').upper()[:5]
        print(f"{t['id']:>4} {tt:<6} {status_emoji}{t['status']:<5} {t['ticker']:<10} {t['direction']:<5} "
              f"{t['entry_price']:>8.2f} {exit_p:>8} {pnl_pct:>8} {pnl_eur:>10} {t['strategy']:<5}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 trade_journal.py open TICKER STRATEGY DIR ENTRY STOP TARGET SHARES \"THESIS\" [--type paper|real]")
        print("  python3 trade_journal.py close ID EXIT_PRICE \"RESULT\" \"LESSONS\"")
        print("  python3 trade_journal.py list")
        print("  python3 trade_journal.py stats [--type paper|real|all]")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    # Parse --type flag from anywhere in args
    trade_type_filter = "all"
    remaining_args = []
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--type" and i + 1 < len(sys.argv):
            trade_type_filter = sys.argv[i + 1].lower()
            i += 2
        else:
            remaining_args.append(sys.argv[i])
            i += 1

    if cmd == "open":
        if len(remaining_args) < 7:
            print("Usage: python3 trade_journal.py open TICKER STRATEGY DIR ENTRY STOP TARGET SHARES [THESIS] [--type paper|real]")
            sys.exit(1)
        ticker = remaining_args[0]
        strategy = remaining_args[1]
        direction = remaining_args[2]
        entry = float(remaining_args[3])
        stop = float(remaining_args[4])
        target = float(remaining_args[5])
        shares = float(remaining_args[6])
        thesis = remaining_args[7] if len(remaining_args) > 7 else ""
        tt = trade_type_filter if trade_type_filter != "all" else "paper"
        open_trade(ticker, strategy, direction, entry, stop, target, shares, thesis, trade_type=tt)

    elif cmd == "close":
        if len(remaining_args) < 2:
            print("Usage: python3 trade_journal.py close ID EXIT_PRICE [RESULT] [LESSONS]")
            sys.exit(1)
        trade_id = int(remaining_args[0])
        exit_price = float(remaining_args[1])
        result = remaining_args[2] if len(remaining_args) > 2 else ""
        lessons = remaining_args[3] if len(remaining_args) > 3 else ""
        close_trade(trade_id, exit_price, result, lessons)

    elif cmd == "list":
        print_all_trades()

    elif cmd == "stats":
        print_stats(trade_type_filter)

    elif cmd == "open-list":
        print_open_trades()

    else:
        print(f"Unbekannter Befehl: {cmd}")
        sys.exit(1)
