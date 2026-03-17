#!/usr/bin/env python3
"""
auto_trader.py — Auto-Execution Engine
Autonomer Paper-Trader: Kauf/Verkauf basierend auf Unified Score.

Portfolio-State in SQLite (paper_portfolio + paper_fund Tabellen).
Slippage, Gebühren, Trailing Stops, Risiko-Regeln.
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from price_db import get_closes, init_tables as init_price_tables, STRATEGY_MAP, DB_PATH

DATA_DIR = Path("/data/.openclaw/workspace/data")
LAST_RUN_PATH = DATA_DIR / "auto_trader_last_run.json"

STARTING_CAPITAL = 1000.0
MIN_CASH_RESERVE = 100.0  # 10% of starting capital
MIN_POSITION_SIZE = 50.0
MAX_POSITION_PCT = 0.15   # 15% max per position
MAX_NEW_TRADES_PER_WEEK = 2
MAX_CORRELATED_POSITIONS = 3
FEES_ROUND_TRIP = 3.0
SLIPPAGE_PCT = 0.001  # 0.1%


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    """Create paper_portfolio and paper_fund tables."""
    init_price_tables()
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            strategy TEXT,
            entry_price REAL,
            entry_date TEXT,
            shares REAL,
            stop_price REAL,
            target_price REAL,
            status TEXT DEFAULT 'OPEN',
            close_price REAL,
            close_date TEXT,
            pnl_eur REAL,
            pnl_pct REAL,
            fees REAL DEFAULT 3.0,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS paper_fund (
            key TEXT PRIMARY KEY,
            value REAL
        );
    """)
    conn.commit()

    # Initialize fund if empty
    row = conn.execute("SELECT value FROM paper_fund WHERE key='starting_capital'").fetchone()
    if row is None:
        conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('starting_capital', ?)", (STARTING_CAPITAL,))
        conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('current_cash', ?)", (STARTING_CAPITAL,))
        conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('total_realized_pnl', 0)")
        conn.commit()

    conn.close()


def _sync_from_paper_portfolio_md():
    """
    One-time sync: Import positions from paper-portfolio.md into SQLite 
    if paper_portfolio table is empty.
    """
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM paper_portfolio").fetchone()[0]
    if count > 0:
        conn.close()
        return  # Already has data

    pp_path = Path("/data/.openclaw/workspace/memory/paper-portfolio.md")
    if not pp_path.exists():
        conn.close()
        return

    content = pp_path.read_text()
    lines = content.split('\n')

    positions = []
    in_table = False
    for line in lines:
        if '| # |' in line and 'Ticker' in line:
            in_table = True
            continue
        if in_table and line.startswith('|---'):
            continue
        if in_table and '|' in line and 'LONG' in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 11:
                try:
                    ticker = parts[2]
                    entry_str = parts[4].replace('€/St', '').replace('€', '').strip()
                    entry_price = float(entry_str)
                    shares = float(parts[5])
                    stop_str = parts[6].replace('€', '').replace('**', '').strip()
                    stop_price = float(stop_str)
                    target_str = parts[7].replace('€', '').strip()
                    target_price = float(target_str)

                    # Find strategy
                    strategy = 'PS1'
                    for s, t_list in STRATEGY_MAP.items():
                        if ticker in t_list:
                            strategy = s
                            break

                    positions.append((ticker, strategy, entry_price, '2026-03-17', shares, stop_price, target_price))
                except (ValueError, IndexError):
                    continue
        elif in_table and line.strip() == '':
            in_table = False

    if positions:
        for p in positions:
            conn.execute(
                """INSERT INTO paper_portfolio (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN')""", p
            )
        conn.commit()

        # Calculate invested amount and set cash
        total_invested = sum(p[2] * p[4] + FEES_ROUND_TRIP for p in positions)
        # Parse cash from MD if possible
        cash = STARTING_CAPITAL - total_invested
        realized = 0
        for line in lines:
            if 'Realisierte P&L' in line and '€' in line:
                import re
                m = re.search(r'([+-]?\d+[.,]\d+)€', line.replace(',', '.'))
                if m:
                    realized = float(m.group(1))
            if 'Cash' in line and '€' in line:
                import re
                m = re.search(r'(\d+[.,]\d+)€', line.replace(',', '.'))
                if m:
                    cash = float(m.group(1))

        conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('current_cash', ?)", (cash,))
        conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('total_realized_pnl', ?)", (realized,))
        conn.commit()
        print(f"  📥 {len(positions)} Positionen aus paper-portfolio.md importiert")

    conn.close()


def get_fund_value(key, conn=None):
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    row = conn.execute("SELECT value FROM paper_fund WHERE key=?", (key,)).fetchone()
    if own_conn:
        conn.close()
    return row[0] if row else 0


def set_fund_value(key, value, conn=None):
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    if own_conn:
        conn.close()


def get_open_positions():
    conn = get_db()
    rows = conn.execute("SELECT * FROM paper_portfolio WHERE status='OPEN' ORDER BY entry_date").fetchall()
    conn.close()
    return rows


def get_closed_positions(limit=10):
    conn = get_db()
    rows = conn.execute("SELECT * FROM paper_portfolio WHERE status='CLOSED' ORDER BY close_date DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows


def get_current_price(ticker):
    """Get latest price from DB."""
    closes = get_closes(ticker, days=3)
    if closes:
        return closes[-1]
    return None


def count_trades_this_week():
    """Count new entries in the last 7 days."""
    conn = get_db()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    count = conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE entry_date >= ?", (week_ago,)
    ).fetchone()[0]
    conn.close()
    return count


def close_position(pos_id, close_price, reason=""):
    """Close a position and update fund."""
    conn = get_db()
    pos = conn.execute("SELECT * FROM paper_portfolio WHERE id=?", (pos_id,)).fetchone()
    if not pos:
        conn.close()
        return None

    # Apply slippage on exit
    exit_price = close_price * (1 - SLIPPAGE_PCT)

    pnl_eur = (exit_price - pos['entry_price']) * pos['shares'] - pos['fees']
    pnl_pct = ((exit_price / pos['entry_price']) - 1) * 100 if pos['entry_price'] > 0 else 0
    close_date = datetime.now().strftime("%Y-%m-%d")

    conn.execute("""
        UPDATE paper_portfolio SET status='CLOSED', close_price=?, close_date=?,
        pnl_eur=?, pnl_pct=?, notes=? WHERE id=?
    """, (round(exit_price, 2), close_date, round(pnl_eur, 2), round(pnl_pct, 2), reason, pos_id))

    # Update cash — use same connection
    cash = get_fund_value('current_cash', conn)
    position_value = exit_price * pos['shares']
    cash += position_value
    conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('current_cash', ?)", (round(cash, 2),))

    realized = get_fund_value('total_realized_pnl', conn)
    realized += pnl_eur
    conn.execute("INSERT OR REPLACE INTO paper_fund (key, value) VALUES ('total_realized_pnl', ?)", (round(realized, 2),))

    conn.commit()
    conn.close()

    return {
        'ticker': pos['ticker'],
        'entry': pos['entry_price'],
        'exit': round(exit_price, 2),
        'pnl_eur': round(pnl_eur, 2),
        'pnl_pct': round(pnl_pct, 2),
        'reason': reason,
    }


def open_position(ticker, strategy, price, shares, stop_price, target_price):
    """Open a new position."""
    # Apply slippage on entry
    entry_price = price * (1 + SLIPPAGE_PCT)

    cost = entry_price * shares + FEES_ROUND_TRIP
    cash = get_fund_value('current_cash')

    if cash - cost < MIN_CASH_RESERVE:
        return None, f"Nicht genug Cash ({cash:.2f}€, brauche {cost:.2f}€ + {MIN_CASH_RESERVE:.0f}€ Reserve)"

    conn = get_db()
    entry_date = datetime.now().strftime("%Y-%m-%d")
    conn.execute("""
        INSERT INTO paper_portfolio (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price, status, fees)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
    """, (ticker, strategy, round(entry_price, 2), entry_date, round(shares, 4), round(stop_price, 2),
          round(target_price, 2), FEES_ROUND_TRIP))
    conn.commit()
    pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    # Deduct from cash
    set_fund_value('current_cash', round(cash - cost, 2))

    return {
        'id': pos_id,
        'ticker': ticker,
        'strategy': strategy,
        'entry': round(entry_price, 2),
        'shares': round(shares, 4),
        'stop': round(stop_price, 2),
        'target': round(target_price, 2),
        'cost': round(cost, 2),
    }, None


def update_stop(pos_id, new_stop):
    """Update stop price for a position."""
    conn = get_db()
    conn.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (round(new_stop, 2), pos_id))
    conn.commit()
    conn.close()


def check_positions(execute=True):
    """Check all open positions for stop/target/trailing."""
    positions = get_open_positions()
    exits = []
    trailing_updates = []

    for pos in positions:
        price = get_current_price(pos['ticker'])
        if price is None:
            continue

        entry = pos['entry_price']
        stop = pos['stop_price']
        target = pos['target_price']
        pnl_pct = ((price / entry) - 1) * 100 if entry > 0 else 0

        # Check stop hit
        if price <= stop:
            exit_price = price * (1 - SLIPPAGE_PCT)
            pnl_eur = (exit_price - entry) * pos['shares'] - (pos['fees'] or FEES_ROUND_TRIP)
            exit_info = {
                'ticker': pos['ticker'],
                'entry': entry,
                'exit': round(exit_price, 2),
                'pnl_eur': round(pnl_eur, 2),
                'pnl_pct': round(pnl_pct, 1),
                'reason': f"STOP HIT @ {price:.2f}",
            }
            if execute:
                close_position(pos['id'], price, f"STOP HIT @ {price:.2f}")
            exits.append(exit_info)
            continue

        # Check target hit
        if target and price >= target:
            exit_price = price * (1 - SLIPPAGE_PCT)
            pnl_eur = (exit_price - entry) * pos['shares'] - (pos['fees'] or FEES_ROUND_TRIP)
            exit_info = {
                'ticker': pos['ticker'],
                'entry': entry,
                'exit': round(exit_price, 2),
                'pnl_eur': round(pnl_eur, 2),
                'pnl_pct': round(pnl_pct, 1),
                'reason': f"TARGET HIT @ {price:.2f}",
            }
            if execute:
                close_position(pos['id'], price, f"TARGET HIT @ {price:.2f}")
            exits.append(exit_info)
            continue

        # Trailing stop logic
        if pnl_pct > 10:
            new_stop = entry * 1.05
            if new_stop > stop:
                if execute:
                    update_stop(pos['id'], new_stop)
                trailing_updates.append({
                    'ticker': pos['ticker'],
                    'pnl_pct': round(pnl_pct, 1),
                    'old_stop': stop,
                    'new_stop': round(new_stop, 2),
                    'reason': '+10% → Trail auf +5%'
                })
        elif pnl_pct > 5:
            new_stop = entry
            if new_stop > stop:
                if execute:
                    update_stop(pos['id'], new_stop)
                trailing_updates.append({
                    'ticker': pos['ticker'],
                    'pnl_pct': round(pnl_pct, 1),
                    'old_stop': stop,
                    'new_stop': round(new_stop, 2),
                    'reason': '+5% → Stop auf Breakeven'
                })

    return exits, trailing_updates


def check_thesis_broken():
    """Check if any position's unified score dropped below 30."""
    positions = get_open_positions()
    exit_candidates = []

    try:
        from unified_scorer import unified_score
        portfolio_tickers = [p['ticker'] for p in positions]

        for pos in positions:
            other_tickers = [t for t in portfolio_tickers if t != pos['ticker']]
            strategy = pos['strategy'] or 'PS1'
            result = unified_score(pos['ticker'], strategy, other_tickers)
            if result['unified_score'] < 30:
                exit_candidates.append({
                    'ticker': pos['ticker'],
                    'id': pos['id'],
                    'score': result['unified_score'],
                    'verdict': result['verdict'],
                })
    except Exception as e:
        print(f"  ⚠ Thesis-Check Fehler: {e}")

    return exit_candidates


def find_new_entries(max_entries=2):
    """Find new entry candidates via unified scorer."""
    try:
        from unified_scorer import find_best_opportunities
        from regime_detector import get_current_regime

        regime = get_current_regime()
        position_factor = regime.get('position_size_factor', 1.0)

        opportunities = find_best_opportunities(n=10)
        existing_tickers = [p['ticker'] for p in get_open_positions()]

        entries = []
        for opp in opportunities:
            if opp['unified_score'] < 70:
                break
            if opp['ticker'] in existing_tickers:
                continue
            if len(entries) >= max_entries:
                break

            # Calculate position size
            cash = get_fund_value('current_cash')
            portfolio_value = cash + sum(
                (get_current_price(p['ticker']) or p['entry_price']) * p['shares']
                for p in get_open_positions()
            )
            max_pos = portfolio_value * MAX_POSITION_PCT * position_factor
            pos_size = min(max_pos, cash - MIN_CASH_RESERVE)

            if pos_size < MIN_POSITION_SIZE:
                continue

            price = get_current_price(opp['ticker'])
            if price is None or price <= 0:
                continue

            shares = pos_size / price

            # Simple stop/target from backtester params
            stop_pct = 0.10  # 10% default
            target_pct = 0.15  # 15% default
            stop_price = price * (1 - stop_pct)
            target_price = price * (1 + target_pct)

            entries.append({
                'ticker': opp['ticker'],
                'strategy': opp['strategy'],
                'price': price,
                'shares': round(shares, 4),
                'stop': round(stop_price, 2),
                'target': round(target_price, 2),
                'score': opp['unified_score'],
                'position_size': round(pos_size, 2),
            })

        return entries
    except Exception as e:
        print(f"  ⚠ Entry-Suche Fehler: {e}")
        return []


def get_portfolio_status():
    """Calculate full portfolio status."""
    positions = get_open_positions()
    closed = get_closed_positions(limit=100)
    cash = get_fund_value('current_cash')
    realized_pnl = get_fund_value('total_realized_pnl')

    invested = 0
    unrealized = 0

    pos_details = []
    for pos in positions:
        price = get_current_price(pos['ticker'])
        if price is None:
            price = pos['entry_price']

        pos_value = price * pos['shares']
        pos_pnl = (price - pos['entry_price']) * pos['shares'] - pos['fees']
        pos_pnl_pct = ((price / pos['entry_price']) - 1) * 100 if pos['entry_price'] > 0 else 0
        invested += pos['entry_price'] * pos['shares']
        unrealized += pos_pnl

        pos_details.append({
            'id': pos['id'],
            'ticker': pos['ticker'],
            'strategy': pos['strategy'],
            'entry': pos['entry_price'],
            'current': round(price, 2),
            'shares': pos['shares'],
            'stop': pos['stop_price'],
            'target': pos['target_price'],
            'pnl_eur': round(pos_pnl, 2),
            'pnl_pct': round(pos_pnl_pct, 1),
            'value': round(pos_value, 2),
        })

    portfolio_value = cash + sum(p['value'] for p in pos_details)
    performance_pct = ((portfolio_value / STARTING_CAPITAL) - 1) * 100

    # Win rate from closed
    wins = len([c for c in closed if (c['pnl_eur'] or 0) > 0])
    losses = len([c for c in closed if (c['pnl_eur'] or 0) <= 0])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    return {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'unrealized_pnl': round(unrealized, 2),
        'realized_pnl': round(realized_pnl, 2),
        'portfolio_value': round(portfolio_value, 2),
        'performance_pct': round(performance_pct, 1),
        'positions': pos_details,
        'open_count': len(positions),
        'closed_count': len(closed),
        'win_rate': round(win_rate, 1),
        'wins': wins,
        'losses': losses,
    }


def run_daily(execute=True):
    """Full daily run: check positions, find entries, update state."""
    init_tables()
    _sync_from_paper_portfolio_md()

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    output_lines = []

    def log(msg):
        output_lines.append(msg)
        print(msg)

    # Get regime
    try:
        from regime_detector import get_current_regime
        regime = get_current_regime()
        regime_name = regime.get('regime', 'UNKNOWN')
        vix = regime.get('vix', '?')
        pos_factor = regime.get('position_size_factor', 1.0)
    except Exception:
        regime_name = 'UNKNOWN'
        vix = '?'
        pos_factor = 1.0

    log(f"\n=== AUTO-TRADER RUN — {now} ===")
    log(f"📊 REGIME: {regime_name} (VIX {vix}) | Position-Size: {int(pos_factor*100)}%")

    # 1. Check existing positions (stops, targets, trailing)
    exits, trailing = check_positions(execute=execute)

    if exits:
        log(f"\n🔴 EXITS:")
        for e in exits:
            emoji = "🟢" if e['pnl_eur'] > 0 else "🔴"
            log(f"  {emoji} {e['ticker']}: {e['reason']} | Entry {e['entry']:.2f}€ | P&L {e['pnl_pct']:+.1f}% ({e['pnl_eur']:+.2f}€)")
    else:
        log(f"\n✅ Keine Exits")

    if trailing:
        log(f"\n🟢 TRAILING:")
        for t in trailing:
            log(f"  - {t['ticker']}: +{t['pnl_pct']:.1f}% → {t['reason']} (Stop {t['old_stop']:.2f} → {t['new_stop']:.2f})")
    else:
        log(f"\n  Keine Trailing-Updates")

    # 2. Check thesis broken (skip in check-only to avoid slow unified scoring)
    thesis_broken = []
    if execute:
        thesis_broken = check_thesis_broken()
        if thesis_broken:
            log(f"\n⚠️ THESIS GEBROCHEN (Score < 30):")
            for tb in thesis_broken:
                log(f"  - {tb['ticker']}: Score {tb['score']} → EXIT-Kandidat")
                price = get_current_price(tb['ticker'])
                if price:
                    result = close_position(tb['id'], price, f"THESIS BROKEN (Score {tb['score']})")
                    if result:
                        log(f"    → Geschlossen @ {result['exit']:.2f}€ | P&L {result['pnl_pct']:+.1f}%")

    # 3. Find new entries
    trades_this_week = count_trades_this_week()
    remaining_trades = max(0, MAX_NEW_TRADES_PER_WEEK - trades_this_week)

    if remaining_trades > 0 and execute:
        new_entries = find_new_entries(max_entries=remaining_trades)
        if new_entries:
            log(f"\n🆕 NEW ENTRIES:")
            for ne in new_entries:
                result, error = open_position(ne['ticker'], ne['strategy'], ne['price'],
                                               ne['shares'], ne['stop'], ne['target'])
                if result:
                    log(f"  ✅ {result['ticker']} ({ne['strategy']}): {result['shares']}x @ {result['entry']:.2f}€ "
                        f"| Stop {result['stop']:.2f} | Target {result['target']:.2f} | Score {ne['score']}")
                elif error:
                    log(f"  ❌ {ne['ticker']}: {error}")
        else:
            log(f"\n🆕 NEW ENTRIES: [keine — kein Score > 70 oder nicht genug Cash]")
    else:
        log(f"\n🆕 NEW ENTRIES: [keine — {trades_this_week}/{MAX_NEW_TRADES_PER_WEEK} diese Woche]")

    # 4. Portfolio Status
    status = get_portfolio_status()

    log(f"\n💰 FUND STATUS:")
    log(f"  Cash: {status['cash']:.2f}€ | Invested: {status['invested']:.2f}€ | "
        f"Unrealized: {status['unrealized_pnl']:+.2f}€ | Realized: {status['realized_pnl']:+.2f}€")
    log(f"  Portfolio Value: ~{status['portfolio_value']:.0f}€ | Performance: {status['performance_pct']:+.1f}%")

    log(f"\n📋 JOURNAL:")
    log(f"  {status['open_count']} offene Trades | {status['closed_count']} geschlossene | "
        f"Win-Rate: {status['win_rate']:.0f}% ({status['wins']}/{status['wins']+status['losses']})")

    # Save results
    run_result = {
        'timestamp': datetime.now().isoformat(),
        'date': now,
        'regime': regime_name,
        'vix': vix,
        'position_factor': pos_factor,
        'exits': exits,
        'trailing_updates': trailing,
        'thesis_broken': thesis_broken,
        'new_entries': [],
        'status': status,
        'output': '\n'.join(output_lines),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LAST_RUN_PATH, 'w') as f:
        json.dump(run_result, f, indent=2, ensure_ascii=False, default=str)

    log(f"\n💾 Ergebnis gespeichert: {LAST_RUN_PATH}")
    return run_result


def cmd_status():
    """Show portfolio status only."""
    init_tables()
    _sync_from_paper_portfolio_md()
    status = get_portfolio_status()

    print(f"\n=== PAPER PORTFOLIO STATUS — {status['date']} ===")
    print(f"\n💰 Cash: {status['cash']:.2f}€ | Invested: {status['invested']:.2f}€")
    print(f"   Unrealized: {status['unrealized_pnl']:+.2f}€ | Realized: {status['realized_pnl']:+.2f}€")
    print(f"   Portfolio Value: ~{status['portfolio_value']:.0f}€ | Performance: {status['performance_pct']:+.1f}%")

    if status['positions']:
        print(f"\n📈 Positionen ({status['open_count']}):")
        print(f"  {'Ticker':<10} {'Strat':<5} {'Entry':>8} {'Aktuell':>8} {'P&L€':>8} {'P&L%':>7} {'Stop':>8} {'Target':>8}")
        print(f"  {'─'*72}")
        for p in status['positions']:
            emoji = "🟢" if p['pnl_eur'] > 0 else ("🔴" if p['pnl_eur'] < 0 else "⚪")
            print(f"  {p['ticker']:<10} {p['strategy'] or '-':<5} {p['entry']:>8.2f} {p['current']:>8.2f} "
                  f"{emoji}{p['pnl_eur']:>+7.2f} {p['pnl_pct']:>+6.1f}% {p['stop']:>8.2f} {p['target']:>8.2f}")

    print(f"\n📋 Win-Rate: {status['win_rate']:.0f}% ({status['wins']}W / {status['losses']}L)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Auto-Execution Engine')
    parser.add_argument('--check-only', action='store_true', help='Nur prüfen, nicht traden')
    parser.add_argument('--status', action='store_true', help='Nur Portfolio-Status anzeigen')
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.check_only:
        run_daily(execute=False)
    else:
        run_daily(execute=True)
