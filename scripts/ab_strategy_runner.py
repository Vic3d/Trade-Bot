#!/usr/bin/env python3
"""
ab_strategy_runner.py — Phase 43k: A/B-Test zweier Trading-Strategien.

Zwei Strategien laufen parallel als Shadow-Trades (kein echtes Cash):

  STRATEGY A — "Conservative-Global" (CEO-Empfehlung):
    · Ignore US-BigCap-Earnings (Region/Sektor-Cap voll)
    · Focus: EU + Asia + Aerospace/Industrials
    · 3 Setups: RKLB, KGX.DE, SAP.DE
    · Stop -6%, Target +12%

  STRATEGY B — "Tradermacher-Aggressive":
    · Ignoriert Sektor/Region-Caps für Earnings-Plays
    · 5 Setups: META, AMZN, MSFT, GOOGL, AAPL
    · Stop -7%, Target +15%

Nach 3 Tagen wird verglichen via compare_strategies().

Usage:
  python3 scripts/ab_strategy_runner.py --init    # Setup beide Strategien jetzt
  python3 scripts/ab_strategy_runner.py --update  # Live-Preise aktualisieren (cron alle 30min)
  python3 scripts/ab_strategy_runner.py --report  # Performance-Vergleich
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'

POSITION_SIZE_EUR = 1500  # Standard pro Shadow-Trade

STRATEGY_A_SETUPS = [
    {'ticker': 'RKLB',   'rationale': 'Aerospace-Sektor frisch, Tradermacher EMA-Pullback bestätigt',
     'stop_pct': 7,  'target_pct': 15, 'sector': 'aerospace'},
    {'ticker': 'KGX.DE', 'rationale': 'EU-Industrials, Datacenter-Build Profiteur, Region+Sektor frisch',
     'stop_pct': 6,  'target_pct': 12, 'sector': 'industrials'},
    {'ticker': 'SAP.DE', 'rationale': 'EU-Software, Cloud-Korrelation zu MSFT/AMZN ohne Tech-Cap-Hit',
     'stop_pct': 5,  'target_pct': 10, 'sector': 'software'},
]

STRATEGY_B_SETUPS = [
    {'ticker': 'META',  'rationale': 'Tradermacher: Range-Top-Ausbruch, beste Setup',
     'stop_pct': 7,  'target_pct': 15, 'sector': 'tech'},
    {'ticker': 'AMZN',  'rationale': 'Tradermacher: Korrektur und Erholung',
     'stop_pct': 7,  'target_pct': 15, 'sector': 'tech'},
    {'ticker': 'MSFT',  'rationale': 'Tradermacher: EMA-Crossback bei Down-Gap',
     'stop_pct': 7,  'target_pct': 15, 'sector': 'tech'},
    {'ticker': 'GOOGL', 'rationale': 'Tradermacher: Cup-and-Handle bei 337',
     'stop_pct': 7,  'target_pct': 15, 'sector': 'tech'},
    {'ticker': 'AAPL',  'rationale': 'Tradermacher: Doppelboden-Ausbruch >275 (Earnings Do)',
     'stop_pct': 7,  'target_pct': 15, 'sector': 'tech'},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_table():
    c = sqlite3.connect(str(DB))
    c.execute('''CREATE TABLE IF NOT EXISTS ab_test_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant TEXT NOT NULL,            -- 'A' | 'B'
        ticker TEXT NOT NULL,
        sector TEXT,
        entry_price_eur REAL,
        stop_price_eur REAL,
        target_price_eur REAL,
        shares REAL,
        position_eur REAL,
        rationale TEXT,
        status TEXT DEFAULT 'OPEN',       -- OPEN | CLOSED_TARGET | CLOSED_STOP | CLOSED_MANUAL
        opened_at TEXT,
        closed_at TEXT,
        close_price_eur REAL,
        last_price_eur REAL,
        last_updated TEXT,
        unrealized_pnl_eur REAL,
        unrealized_pnl_pct REAL,
        UNIQUE(variant, ticker, opened_at)
    )''')
    c.commit()
    c.close()


def _resolve_price(ticker: str) -> float:
    try:
        from core.live_data import get_price_eur
        p = get_price_eur(ticker)
        if p:
            return float(p)
    except Exception:
        pass
    return 0.0


def init_strategies(force: bool = False) -> dict:
    """Lege beide Strategien jetzt mit Live-Entry-Preis an."""
    _create_table()
    c = sqlite3.connect(str(DB))

    # Check if already initialized today
    today = datetime.now().strftime('%Y-%m-%d')
    existing = c.execute(
        "SELECT COUNT(*) FROM ab_test_trades WHERE substr(opened_at,1,10)=?",
        (today,)
    ).fetchone()[0]

    if existing > 0 and not force:
        c.close()
        return {'status': 'already_initialized', 'count': existing,
                'message': f'Heute schon {existing} Shadow-Trades aktiv. --force zum überschreiben.'}

    inserted = {'A': [], 'B': []}
    now = _now_iso()

    for variant, setups in [('A', STRATEGY_A_SETUPS), ('B', STRATEGY_B_SETUPS)]:
        for s in setups:
            ticker = s['ticker']
            entry = _resolve_price(ticker)
            if entry <= 0:
                inserted[variant].append({'ticker': ticker, 'status': 'no_price'})
                continue
            stop = round(entry * (1 - s['stop_pct'] / 100), 2)
            target = round(entry * (1 + s['target_pct'] / 100), 2)
            shares = round(POSITION_SIZE_EUR / entry, 4)
            try:
                c.execute(
                    "INSERT INTO ab_test_trades "
                    "(variant, ticker, sector, entry_price_eur, stop_price_eur, "
                    " target_price_eur, shares, position_eur, rationale, "
                    " opened_at, last_price_eur, last_updated, "
                    " unrealized_pnl_eur, unrealized_pnl_pct) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (variant, ticker, s['sector'], entry, stop, target,
                     shares, POSITION_SIZE_EUR, s['rationale'],
                     now, entry, now, 0.0, 0.0)
                )
                inserted[variant].append({
                    'ticker': ticker, 'entry': entry, 'stop': stop,
                    'target': target, 'shares': shares,
                })
            except sqlite3.IntegrityError:
                inserted[variant].append({'ticker': ticker, 'status': 'duplicate'})

    c.commit()
    c.close()
    return {'status': 'initialized', 'inserted': inserted}


def update_prices() -> dict:
    """Aktualisiere Live-Preise + check Stop/Target-Hits."""
    _create_table()
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, variant, ticker, entry_price_eur, stop_price_eur, "
        "       target_price_eur, shares "
        "FROM ab_test_trades WHERE status='OPEN'"
    ).fetchall()
    now = _now_iso()
    updates = {'price_updated': 0, 'stops_hit': 0, 'targets_hit': 0}

    for r in rows:
        live = _resolve_price(r['ticker'])
        if live <= 0:
            continue

        unr_eur = (live - r['entry_price_eur']) * r['shares']
        unr_pct = (live - r['entry_price_eur']) / r['entry_price_eur'] * 100

        new_status = 'OPEN'
        close_price = None
        if live <= r['stop_price_eur']:
            new_status = 'CLOSED_STOP'
            close_price = r['stop_price_eur']
            updates['stops_hit'] += 1
        elif live >= r['target_price_eur']:
            new_status = 'CLOSED_TARGET'
            close_price = r['target_price_eur']
            updates['targets_hit'] += 1

        if new_status != 'OPEN':
            c.execute(
                "UPDATE ab_test_trades SET status=?, closed_at=?, "
                "    close_price_eur=?, last_price_eur=?, last_updated=?, "
                "    unrealized_pnl_eur=?, unrealized_pnl_pct=? "
                "WHERE id=?",
                (new_status, now, close_price, live, now,
                 (close_price - r['entry_price_eur']) * r['shares'],
                 (close_price - r['entry_price_eur']) / r['entry_price_eur'] * 100,
                 r['id'])
            )
        else:
            c.execute(
                "UPDATE ab_test_trades SET last_price_eur=?, last_updated=?, "
                "    unrealized_pnl_eur=?, unrealized_pnl_pct=? "
                "WHERE id=?",
                (live, now, unr_eur, unr_pct, r['id'])
            )
        updates['price_updated'] += 1

    c.commit()
    c.close()
    return updates


def compare_strategies() -> dict:
    """Vergleiche A vs B Performance."""
    _create_table()
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM ab_test_trades").fetchall()
    c.close()

    by_variant = {'A': [], 'B': []}
    for r in rows:
        d = dict(r)
        # PnL: realized (closed) oder unrealized (open)
        if d['status'].startswith('CLOSED') and d.get('close_price_eur'):
            d['pnl_eur'] = round(
                (d['close_price_eur'] - d['entry_price_eur']) * d['shares'], 2)
            d['pnl_pct'] = round(
                (d['close_price_eur'] - d['entry_price_eur']) / d['entry_price_eur'] * 100, 2)
        else:
            d['pnl_eur'] = round(d.get('unrealized_pnl_eur') or 0, 2)
            d['pnl_pct'] = round(d.get('unrealized_pnl_pct') or 0, 2)
        by_variant[d['variant']].append(d)

    summary = {}
    for variant, trades in by_variant.items():
        if not trades:
            summary[variant] = {'n': 0}
            continue
        total_pnl = sum(t['pnl_eur'] for t in trades)
        n_open = sum(1 for t in trades if t['status'] == 'OPEN')
        n_closed = sum(1 for t in trades if t['status'].startswith('CLOSED'))
        n_target = sum(1 for t in trades if t['status'] == 'CLOSED_TARGET')
        n_stop = sum(1 for t in trades if t['status'] == 'CLOSED_STOP')
        n_winners = sum(1 for t in trades if t['pnl_eur'] > 0)
        n_losers = sum(1 for t in trades if t['pnl_eur'] < 0)
        summary[variant] = {
            'n': len(trades),
            'total_pnl_eur': round(total_pnl, 2),
            'avg_pnl_pct': round(sum(t['pnl_pct'] for t in trades) / len(trades), 2),
            'n_open': n_open, 'n_closed': n_closed,
            'n_target_hit': n_target, 'n_stop_hit': n_stop,
            'n_winners': n_winners, 'n_losers': n_losers,
            'win_rate_pct': round(n_winners / len(trades) * 100, 1),
            'best_trade': max(trades, key=lambda x: x['pnl_eur']) if trades else None,
            'worst_trade': min(trades, key=lambda x: x['pnl_eur']) if trades else None,
        }

    # Winner determination
    if summary.get('A', {}).get('n') and summary.get('B', {}).get('n'):
        a = summary['A']['total_pnl_eur']
        b = summary['B']['total_pnl_eur']
        if a > b:
            winner = 'A'
            margin = a - b
        elif b > a:
            winner = 'B'
            margin = b - a
        else:
            winner = 'tie'
            margin = 0
        summary['_verdict'] = {
            'winner': winner, 'margin_eur': round(margin, 2),
            'a_pnl': a, 'b_pnl': b,
        }

    return {
        'summary': summary,
        'trades_a': [dict(t) for t in by_variant['A']],
        'trades_b': [dict(t) for t in by_variant['B']],
    }


def format_report(result: dict) -> str:
    s = result['summary']
    lines = [
        '═══ A/B TEST PERFORMANCE ═══',
        '',
    ]

    for variant, label in [('A', 'CONSERVATIVE-GLOBAL (CEO)'),
                            ('B', 'TRADERMACHER-AGGRESSIVE')]:
        d = s.get(variant, {'n': 0})
        if d['n'] == 0:
            lines.append(f'\n[{variant}] {label}: keine Trades')
            continue
        icon = '✅' if d['total_pnl_eur'] > 0 else '❌' if d['total_pnl_eur'] < 0 else '·'
        lines.extend([
            f'',
            f'━━ STRATEGY {variant}: {label} ━━',
            f'  {icon} Total PnL: {d["total_pnl_eur"]:+,.0f}€  '
            f'(avg {d["avg_pnl_pct"]:+.2f}% pro Trade)',
            f'  Trades: {d["n"]} (open {d["n_open"]}, closed {d["n_closed"]})',
            f'  Closures: {d["n_target_hit"]} Target | {d["n_stop_hit"]} Stop',
            f'  Win-Rate: {d["win_rate_pct"]:.0f}% ({d["n_winners"]}W / {d["n_losers"]}L)',
        ])
        if d.get('best_trade'):
            bt = d['best_trade']
            lines.append(f'  Best:  {bt["ticker"]:<8} {bt["pnl_eur"]:+.0f}€ ({bt["pnl_pct"]:+.1f}%)')
        if d.get('worst_trade'):
            wt = d['worst_trade']
            lines.append(f'  Worst: {wt["ticker"]:<8} {wt["pnl_eur"]:+.0f}€ ({wt["pnl_pct"]:+.1f}%)')

    if '_verdict' in s:
        v = s['_verdict']
        winner_text = (f'🏆 STRATEGY {v["winner"]} GEWINNT  '
                        f'({v["margin_eur"]:+.0f}€ Vorsprung)'
                        if v['winner'] != 'tie' else '🤝 GLEICHSTAND')
        lines.extend([
            '',
            '═══ VERDICT ═══',
            winner_text,
            f'  A: {v["a_pnl"]:+.0f}€  vs.  B: {v["b_pnl"]:+.0f}€',
        ])

    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true', help='Beide Strategien initialisieren')
    ap.add_argument('--force', action='store_true', help='Auch wenn schon initialisiert')
    ap.add_argument('--update', action='store_true', help='Live-Preise aktualisieren')
    ap.add_argument('--report', action='store_true', help='Performance-Vergleich')
    args = ap.parse_args()

    if args.init:
        r = init_strategies(force=args.force)
        print(f'Status: {r["status"]}')
        if r.get('inserted'):
            for variant, items in r['inserted'].items():
                print(f'  Strategy {variant}:')
                for it in items:
                    if 'entry' in it:
                        print(f"    + {it['ticker']:<8} entry={it['entry']:.2f} "
                              f"stop={it['stop']:.2f} target={it['target']:.2f} "
                              f"shares={it['shares']}")
                    else:
                        print(f"    - {it['ticker']:<8} ({it.get('status','?')})")
        elif r.get('message'):
            print(r['message'])
        return 0

    if args.update:
        r = update_prices()
        print(f'Updated: {r}')
        return 0

    if args.report or not (args.init or args.update):
        r = compare_strategies()
        print(format_report(r))
        return 0

    return 0


if __name__ == '__main__':
    sys.exit(main())
