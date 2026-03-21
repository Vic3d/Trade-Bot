#!/usr/bin/env python3
"""
Strategy Feedback Loop
======================
Laeuft 1x taeglich (im Learning System Cron 22:30).
Liest Trade-Ergebnisse aus der DB, berechnet per-Strategy Metriken,
und passt Conviction + Parameter in strategies.json automatisch an.

Regeln:
- Min 5 geschlossene Trades pro Strategie bevor Anpassung
- Win-Rate < 30% nach 10+ Trades -> conviction -1 (min 1)
- Win-Rate > 50% nach 10+ Trades -> conviction +1 (max 5)
- Win-Rate > 60% nach 15+ Trades -> conviction +2 (max 5)
- Conviction < 2 -> Strategie wird "suspended" (keine neuen Trades)
- Conviction >= 4 -> Position Size darf auf 7500 EUR erhoeht werden
- Avg Holding Days < 1 bei Swing Trades -> Warnung "zu schneller Exit"
- Stop-Distance zu eng wenn > 60% der Losses durch Stop Hit -> Stop weiten

Schreibt Aenderungen in strategies.json:
- genesis.conviction_current = neuer Wert
- genesis.auto_adjusted = True
- genesis.last_updated = ISO timestamp
- genesis.feedback_history = [{date, old_conviction, new_conviction, reason}]

Ausserdem: Schreibt kurzen Report in memory/strategy-feedback-log.md

Usage: python3 scripts/intelligence/strategy_feedback.py
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
DB_PATH = WORKSPACE / 'data/trading.db'
STRATEGIES_PATH = WORKSPACE / 'data/strategies.json'
LOG_PATH = WORKSPACE / 'memory/strategy-feedback-log.md'


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_strategies():
    with open(STRATEGIES_PATH) as f:
        return json.load(f)


def save_strategies(strategies):
    with open(STRATEGIES_PATH, 'w') as f:
        json.dump(strategies, f, indent=2, ensure_ascii=False)


def run_feedback():
    """Main feedback loop."""
    now = datetime.now(timezone.utc)
    now_iso = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    now_date = now.strftime('%Y-%m-%d')

    conn = get_db()
    strategies = load_strategies()

    # Get all closed trades grouped by strategy
    closed = conn.execute("""
        SELECT * FROM trades
        WHERE status IN ('WIN', 'LOSS')
        ORDER BY strategy, exit_date
    """).fetchall()

    # Group by strategy
    by_strategy = {}
    for t in closed:
        sid = t['strategy'] or 'unknown'
        by_strategy.setdefault(sid, []).append(t)

    # Also count open trades per strategy
    open_trades = conn.execute("SELECT strategy, COUNT(*) as cnt FROM trades WHERE status='OPEN' GROUP BY strategy").fetchall()
    open_by_strat = {r['strategy']: r['cnt'] for r in open_trades}

    changes = []
    warnings = []
    report_lines = [
        f"# Strategy Feedback Report — {now_date}",
        f"_Generated: {now_iso}_\n",
    ]

    for sid, trades in sorted(by_strategy.items()):
        if sid not in strategies or not isinstance(strategies[sid], dict):
            report_lines.append(f"## {sid} — ⚠️ Not in strategies.json, skipping")
            continue

        strat = strategies[sid]
        genesis = strat.get('genesis', {})
        old_conviction = genesis.get('conviction_current', 3)
        new_conviction = old_conviction
        strat_name = strat.get('name', sid)
        strat_type = strat.get('type', 'paper')

        n_closed = len(trades)
        n_wins = sum(1 for t in trades if t['status'] == 'WIN')
        n_losses = sum(1 for t in trades if t['status'] == 'LOSS')
        win_rate = n_wins / n_closed if n_closed > 0 else 0
        n_open = open_by_strat.get(sid, 0)

        # Avg holding days
        holding_days = [t['holding_days'] or 0 for t in trades if t['holding_days'] is not None]
        avg_hold = sum(holding_days) / len(holding_days) if holding_days else 0

        # Stop hit ratio (losses where exit_type contains 'stop')
        stop_losses = sum(1 for t in trades if t['status'] == 'LOSS' and (t['exit_type'] or '').lower().startswith('stop'))
        stop_hit_ratio = stop_losses / n_losses if n_losses > 0 else 0

        # Avg PnL
        pnl_values = [t['pnl_pct'] or 0 for t in trades]
        avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0

        reasons = []

        # ---- Conviction adjustment rules ----
        if n_closed >= 5:
            # Win-Rate > 60% nach 15+ Trades -> conviction +2
            if n_closed >= 15 and win_rate > 0.60:
                adj = min(2, 5 - old_conviction)
                if adj > 0:
                    new_conviction = old_conviction + adj
                    reasons.append(f"Win-Rate {win_rate:.0%} bei {n_closed} Trades -> +{adj}")

            # Win-Rate > 50% nach 10+ Trades -> conviction +1
            elif n_closed >= 10 and win_rate > 0.50:
                adj = min(1, 5 - old_conviction)
                if adj > 0:
                    new_conviction = old_conviction + adj
                    reasons.append(f"Win-Rate {win_rate:.0%} bei {n_closed} Trades -> +{adj}")

            # Win-Rate < 30% nach 10+ Trades -> conviction -1
            if n_closed >= 10 and win_rate < 0.30:
                adj = min(1, old_conviction - 1)
                if adj > 0:
                    new_conviction = max(1, old_conviction - adj)
                    reasons.append(f"Win-Rate {win_rate:.0%} bei {n_closed} Trades -> -{adj}")

        # ---- Warnings ----
        # Swing trades with avg hold < 1 day
        is_swing = strat_type in ('paper', 'real') and strat_type != 'day_trade'
        if is_swing and avg_hold < 1.0 and n_closed >= 3:
            warnings.append(f"{sid} ({strat_name}): Avg Hold {avg_hold:.1f}d — zu schneller Exit bei Swing-Strategie")

        # Stop distance too tight
        if n_losses >= 3 and stop_hit_ratio > 0.60:
            warnings.append(f"{sid} ({strat_name}): {stop_hit_ratio:.0%} der Losses durch Stop Hit — Stop eventuell zu eng")

        # ---- Apply changes ----
        conviction_changed = new_conviction != old_conviction

        if conviction_changed:
            genesis['conviction_current'] = new_conviction
            genesis['auto_adjusted'] = True
            genesis['last_updated'] = now_iso
            history = genesis.setdefault('feedback_history', [])
            history.append({
                'date': now_date,
                'old_conviction': old_conviction,
                'new_conviction': new_conviction,
                'reason': '; '.join(reasons)
            })
            changes.append(f"{sid} ({strat_name}): Conviction {old_conviction} -> {new_conviction} ({'; '.join(reasons)})")
        else:
            # Still mark as evaluated
            genesis['last_updated'] = now_iso
            genesis['auto_adjusted'] = genesis.get('auto_adjusted', False)

        strat['genesis'] = genesis

        # ---- Suspension check ----
        status_note = ""
        if new_conviction < 2:
            strat['status'] = 'suspended'
            status_note = " ⛔ SUSPENDED"
        
        # Position size recommendation
        pos_size = "5000€"
        if new_conviction >= 4:
            pos_size = "7500€"
        
        report_lines.append(f"## {sid} — {strat_name}{status_note}")
        report_lines.append(f"- Trades: {n_closed} closed, {n_open} open")
        report_lines.append(f"- Win-Rate: {win_rate:.0%} ({n_wins}W / {n_losses}L)")
        report_lines.append(f"- Avg PnL: {avg_pnl:+.2f}%")
        report_lines.append(f"- Avg Hold: {avg_hold:.1f} days")
        report_lines.append(f"- Stop-Hit-Ratio: {stop_hit_ratio:.0%}")
        report_lines.append(f"- Conviction: {old_conviction} → {new_conviction}")
        report_lines.append(f"- Position Size: {pos_size}")
        report_lines.append("")

    # ---- Summary ----
    report_lines.append("## Summary")
    if changes:
        report_lines.append("### Conviction Changes")
        for c in changes:
            report_lines.append(f"- ✏️ {c}")
    else:
        report_lines.append("_Keine Conviction-Änderungen (min 5 geschlossene Trades pro Strategie nötig)_")

    if warnings:
        report_lines.append("\n### Warnings")
        for w in warnings:
            report_lines.append(f"- ⚠️ {w}")

    report_lines.append("")

    # Save strategies
    save_strategies(strategies)

    # Write log
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    report_text = '\n'.join(report_lines) + '\n'

    # Append to existing log or create
    if LOG_PATH.exists():
        existing = LOG_PATH.read_text()
        # Keep last 5 reports max
        reports = existing.split('\n# Strategy Feedback Report')
        if len(reports) > 5:
            reports = reports[-5:]
            existing = '\n# Strategy Feedback Report'.join(reports)
        with open(LOG_PATH, 'w') as f:
            f.write(report_text + '\n---\n\n' + existing)
    else:
        with open(LOG_PATH, 'w') as f:
            f.write(report_text)

    conn.close()

    # Print summary
    print(f"\n📊 Strategy Feedback Loop — {now_date}")
    print(f"   Strategies evaluated: {len(by_strategy)}")
    print(f"   Conviction changes: {len(changes)}")
    print(f"   Warnings: {len(warnings)}")
    if changes:
        for c in changes:
            print(f"   ✏️ {c}")
    if warnings:
        for w in warnings:
            print(f"   ⚠️ {w}")
    print(f"   Report: {LOG_PATH}")
    print("   ✅ Done")


if __name__ == '__main__':
    run_feedback()
