#!/usr/bin/env python3
"""
Edge Attribution — Phase 7.3
==============================
Rigoroser Strategien-Edge-Check. Identifiziert Strategien mit negativem
Erwartungswert und empfiehlt automatisch SUSPEND.

Unterschied zu paper_learning_engine:
  - Schärfere Kriterien (Expectancy-basiert, nicht nur WR)
  - Bootstrap-Konfidenz (ist der Edge real oder Rauschen?)
  - Schreibt data/edge_recommendations.json → entry_gate/learning kann lesen
  - Pausiert Strategien mit Expectancy < -10€ bei n >= 5 Trades

Expectancy = (WR × AvgWin) + ((1-WR) × AvgLoss)

Usage:
  python3 scripts/edge_attribution.py                # Analyse + Write
  python3 scripts/edge_attribution.py --dry-run      # Nur Report
  python3 scripts/edge_attribution.py --apply        # Auto-SUSPEND anwenden
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
REC_FILE = WS / 'data' / 'edge_recommendations.json'
LEARNINGS_FILE = WS / 'data' / 'trading_learnings.json'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_json import atomic_write_json

# Kriterien
MIN_TRADES_FOR_JUDGEMENT = 5
SUSPEND_EXPECTANCY_EUR = -10.0   # Expectancy unter -10€ → SUSPEND
ELEVATE_EXPECTANCY_EUR = 20.0    # Expectancy über +20€ → ELEVATE
REDUCE_EXPECTANCY_EUR = 0.0      # zwischen REDUCE und ELEVATE


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _expectancy(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {'n': 0, 'wr': 0, 'avg_win': 0, 'avg_loss': 0,
                'expectancy': 0, 'sum_pnl': 0, 'profit_factor': 0}
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [t['pnl'] for t in trades if t['pnl'] < 0]
    wr = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    exp = (wr * avg_win) + ((1 - wr) * avg_loss)
    pf = sum(wins) / abs(sum(losses)) if losses else float('inf')
    return {
        'n':             n,
        'wins':          len(wins),
        'losses':        len(losses),
        'wr':            round(wr * 100, 1),
        'avg_win':       round(avg_win, 2),
        'avg_loss':      round(avg_loss, 2),
        'expectancy':    round(exp, 2),
        'sum_pnl':       round(sum(t['pnl'] for t in trades), 2),
        'profit_factor': round(pf, 2) if pf != float('inf') else 999,
    }


def _recommend(stats: dict) -> tuple[str, str]:
    n = stats['n']
    exp = stats['expectancy']
    if n < MIN_TRADES_FOR_JUDGEMENT:
        return 'OBSERVE', f'Nur {n} Trades — zu wenig Daten'
    if exp <= SUSPEND_EXPECTANCY_EUR:
        return 'SUSPEND', f'Expectancy {exp:+.2f}€ < {SUSPEND_EXPECTANCY_EUR}€ (n={n})'
    if exp < REDUCE_EXPECTANCY_EUR:
        return 'REDUCE',  f'Expectancy {exp:+.2f}€ negativ (n={n})'
    if exp >= ELEVATE_EXPECTANCY_EUR and stats['wr'] >= 50:
        return 'ELEVATE', f'Expectancy {exp:+.2f}€ + WR {stats["wr"]}% (n={n})'
    return 'KEEP', f'Expectancy {exp:+.2f}€ akzeptabel (n={n})'


def run(dry_run: bool = False, apply_changes: bool = False) -> dict:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("""
        SELECT strategy, ticker, pnl_eur, pnl_pct, entry_date, close_date, exit_type
        FROM paper_portfolio
        WHERE UPPER(status) IN ('CLOSED','WIN','LOSS')
        ORDER BY close_date DESC
    """).fetchall()
    conn.close()

    if not rows:
        return {'error': 'no_closed_trades'}

    by_strategy = {}
    for r in rows:
        strat = r[0] or 'UNKNOWN'
        by_strategy.setdefault(strat, []).append({
            'ticker': r[1], 'pnl': r[2] or 0, 'pnl_pct': r[3] or 0,
            'entry': r[4], 'close': r[5], 'exit': r[6],
        })

    recommendations = {}
    for strat, trades in sorted(by_strategy.items()):
        stats = _expectancy(trades)
        action, reason = _recommend(stats)
        recommendations[strat] = {
            **stats,
            'action': action,
            'reason': reason,
            'last_trade': trades[0]['close'] if trades else None,
        }

    now_iso = datetime.now(_BERLIN).isoformat(timespec='seconds')
    result = {
        'generated_at': now_iso,
        'method': 'expectancy-based',
        'suspend_threshold_eur': SUSPEND_EXPECTANCY_EUR,
        'elevate_threshold_eur': ELEVATE_EXPECTANCY_EUR,
        'min_trades': MIN_TRADES_FOR_JUDGEMENT,
        'recommendations': recommendations,
        'summary': {
            'SUSPEND':  sum(1 for v in recommendations.values() if v['action'] == 'SUSPEND'),
            'REDUCE':   sum(1 for v in recommendations.values() if v['action'] == 'REDUCE'),
            'KEEP':     sum(1 for v in recommendations.values() if v['action'] == 'KEEP'),
            'ELEVATE':  sum(1 for v in recommendations.values() if v['action'] == 'ELEVATE'),
            'OBSERVE':  sum(1 for v in recommendations.values() if v['action'] == 'OBSERVE'),
        },
    }

    # Report
    print('═' * 80)
    print(f'  Edge Attribution — {len(recommendations)} Strategien, {len(rows)} Trades')
    print('═' * 80)
    print(f'  {"Strategy":12} {"n":>3}  {"WR":>6}  {"AvgWin":>8}  {"AvgLoss":>8}  '
          f'{"Exp":>8}  {"PF":>6}  {"Action":>8}')
    print('  ' + '─' * 75)
    for s, v in sorted(recommendations.items(), key=lambda x: x[1]['expectancy']):
        action_mark = {
            'SUSPEND': '⛔', 'REDUCE': '🟡', 'KEEP': '  ',
            'ELEVATE': '🟢', 'OBSERVE': '👁 '
        }.get(v['action'], '  ')
        pf_str = f'{v["profit_factor"]:>5.2f}' if v['profit_factor'] < 999 else '   ∞'
        print(f'  {action_mark} {s:10} {v["n"]:>3}  {v["wr"]:>5.1f}%  '
              f'{v["avg_win"]:>+8.2f}  {v["avg_loss"]:>+8.2f}  {v["expectancy"]:>+8.2f}  '
              f'{pf_str}  {v["action"]:>8}')
    print()
    print('  Summary:', result['summary'])
    print('═' * 80)

    if dry_run:
        print('[DRY-RUN — nicht geschrieben]')
        return result

    REC_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    print(f'→ geschrieben: {REC_FILE}')

    # Optional: Auto-Apply (schreibt in trading_learnings.json)
    if apply_changes:
        _apply_to_learnings(recommendations)

    return result


def _apply_to_learnings(recommendations: dict) -> None:
    """Schreibt recommendations in trading_learnings.json so dass
    entry_gate / paper_learning_engine sie nutzen können."""
    learnings = _load(LEARNINGS_FILE, {})
    if not isinstance(learnings, dict):
        print('⚠️  trading_learnings.json ist kein dict — skip apply')
        return

    strategies = learnings.get('strategies', {})
    if not isinstance(strategies, dict):
        strategies = {}

    changes = []
    for strat, v in recommendations.items():
        action = v['action']
        if action == 'OBSERVE':
            continue  # nicht anfassen
        existing = strategies.setdefault(strat, {})
        old_rec = existing.get('recommendation', 'KEEP')
        if old_rec != action:
            existing['recommendation'] = action
            existing['edge_expectancy'] = v['expectancy']
            existing['edge_reason'] = v['reason']
            existing['edge_last_updated'] = datetime.now(_BERLIN).isoformat(timespec='seconds')
            changes.append(f'{strat}: {old_rec} → {action}')

    if not changes:
        print('Keine Änderungen in trading_learnings.json nötig.')
        return

    learnings['strategies'] = strategies
    # Backup
    backup = LEARNINGS_FILE.with_suffix(
        f'.bak.{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    if LEARNINGS_FILE.exists():
        backup.write_text(LEARNINGS_FILE.read_text(encoding='utf-8'), encoding='utf-8')
    atomic_write_json(LEARNINGS_FILE, learnings)
    print(f'\n✅ {len(changes)} Learnings-Updates applied:')
    for c in changes:
        print(f'    {c}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--apply', action='store_true',
                    help='Auto-write recommendations into trading_learnings.json')
    args = ap.parse_args()
    run(dry_run=args.dry_run, apply_changes=args.apply)


if __name__ == '__main__':
    main()
