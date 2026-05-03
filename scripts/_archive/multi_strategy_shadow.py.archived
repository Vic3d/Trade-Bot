#!/usr/bin/env python3
"""
multi_strategy_shadow.py — Phase 44d: Massive parallele Strategy-Validierung.

Erkenntnis: 36 von 41 Strategien wurden NIE getradet. Wir wissen nicht
ob sie funktionieren weil wir sie nie ausprobiert haben.

Lösung: Jede Strategie bekommt fiktive 25k€ und tradet UNABHÄNGIG mit
identischem Setup-Algo. Nach 30 Tagen: ehrliches Ranking.

Mechanismus:
  - Jeden Tag (oder live triggered): pro Strategie versuchen 1-2 Setups
    zu finden basierend auf strategies.json Definition + Live-Tickers
  - Setups werden in shadow_strategy_trades-Tabelle geschrieben
  - Live-Preis-Tracking, Auto-Close bei Stop/Target
  - Performance-Report nach 30 Tagen

Run:
  python3 scripts/multi_strategy_shadow.py --init       # Setup Tabelle
  python3 scripts/multi_strategy_shadow.py --hunt       # 1 Hunt-Cycle
  python3 scripts/multi_strategy_shadow.py --update     # Live-Preis + Stop-Check
  python3 scripts/multi_strategy_shadow.py --report     # Vergleich aller Strategien
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

DB              = WS / 'data' / 'trading.db'
STRATEGIES_FILE = WS / 'data' / 'strategies.json'

POSITION_SIZE_EUR = 800
SHADOW_FUND       = 25000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_table():
    c = sqlite3.connect(str(DB))
    c.execute('''CREATE TABLE IF NOT EXISTS shadow_strategy_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        entry_price_eur REAL,
        stop_price_eur REAL,
        target_price_eur REAL,
        shares REAL,
        position_eur REAL,
        rationale TEXT,
        status TEXT DEFAULT 'OPEN',
        opened_at TEXT,
        closed_at TEXT,
        close_price_eur REAL,
        last_price_eur REAL,
        last_updated TEXT,
        unrealized_pnl_eur REAL,
        realized_pnl_eur REAL DEFAULT 0,
        UNIQUE(strategy_id, ticker, opened_at)
    )''')
    c.commit()
    c.close()


def _live_price(ticker: str) -> float:
    try:
        from core.live_data import get_price_eur
        p = get_price_eur(ticker)
        return float(p) if p else 0
    except Exception:
        return 0


def hunt_cycle() -> dict:
    """Pro aktive Strategie 1 Setup versuchen.
    Logik: nimm ersten ticker aus strategies.json[strategy].tickers,
    der noch keine OPEN shadow position hat."""
    init_table()
    strats = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Welche Strategien haben schon offen?
    open_pairs = set()
    for r in c.execute(
        "SELECT strategy_id, ticker FROM shadow_strategy_trades WHERE status='OPEN'"
    ).fetchall():
        open_pairs.add((r['strategy_id'], r['ticker']))

    opened = []
    skipped = {'no_tickers': 0, 'all_tickers_open': 0,
                'no_price': 0, 'paused': 0, 'permanent_blocked': 0}
    PERMANENT_BLOCKED = {'AR-AGRA', 'AR-HALB', 'DT1', 'DT2', 'DT3', 'DT4', 'DT5'}
    now = _now_iso()

    for sid, meta in strats.items():
        if not isinstance(meta, dict):
            continue
        if sid in PERMANENT_BLOCKED:
            skipped['permanent_blocked'] += 1
            continue
        if meta.get('status') in ('paused', 'auto_deprecated', 'retired'):
            skipped['paused'] += 1
            continue

        tickers = meta.get('tickers', []) or []
        if not tickers:
            skipped['no_tickers'] += 1
            continue

        # Erster verfügbarer Ticker
        chosen = None
        for tk in tickers:
            if (sid, tk) not in open_pairs:
                chosen = tk
                break
        if not chosen:
            skipped['all_tickers_open'] += 1
            continue

        live = _live_price(chosen)
        if live <= 0:
            skipped['no_price'] += 1
            continue

        # Default 5% stop, 15% target = 3:1 R:R
        stop = round(live * 0.95, 2)
        target = round(live * 1.15, 2)
        shares = round(POSITION_SIZE_EUR / live, 4)

        try:
            c.execute(
                "INSERT INTO shadow_strategy_trades "
                "(strategy_id, ticker, entry_price_eur, stop_price_eur, "
                " target_price_eur, shares, position_eur, rationale, "
                " opened_at, last_price_eur, last_updated, unrealized_pnl_eur) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                (sid, chosen, live, stop, target, shares, POSITION_SIZE_EUR,
                 f'Shadow-Test {sid}: {meta.get("thesis","")[:120]}',
                 now, live, now)
            )
            opened.append({'strategy': sid, 'ticker': chosen, 'entry': live})
        except sqlite3.IntegrityError:
            pass

    c.commit()
    c.close()
    return {'opened': len(opened), 'skipped': skipped, 'opened_list': opened[:20]}


def update_prices() -> dict:
    """Live-Preise + Stop/Target-Check."""
    init_table()
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT * FROM shadow_strategy_trades WHERE status='OPEN'"
    ).fetchall()
    now = _now_iso()
    updates = {'updated': 0, 'stops_hit': 0, 'targets_hit': 0}

    for r in rows:
        live = _live_price(r['ticker'])
        if live <= 0:
            continue
        unr = (live - r['entry_price_eur']) * r['shares']

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
            realized = (close_price - r['entry_price_eur']) * r['shares']
            c.execute(
                "UPDATE shadow_strategy_trades SET status=?, closed_at=?, "
                " close_price_eur=?, last_price_eur=?, last_updated=?, "
                " realized_pnl_eur=?, unrealized_pnl_eur=0 WHERE id=?",
                (new_status, now, close_price, live, now, realized, r['id'])
            )
        else:
            c.execute(
                "UPDATE shadow_strategy_trades SET last_price_eur=?, "
                " last_updated=?, unrealized_pnl_eur=? WHERE id=?",
                (live, now, unr, r['id'])
            )
        updates['updated'] += 1

    c.commit()
    c.close()
    return updates


def report() -> dict:
    """Performance-Ranking aller Strategien."""
    init_table()
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    rows = c.execute(
        "SELECT strategy_id, "
        " COUNT(*) as n_total, "
        " SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as n_open, "
        " SUM(CASE WHEN status LIKE 'CLOSED%' THEN 1 ELSE 0 END) as n_closed, "
        " SUM(CASE WHEN status='CLOSED_TARGET' THEN 1 ELSE 0 END) as n_target, "
        " SUM(CASE WHEN status='CLOSED_STOP' THEN 1 ELSE 0 END) as n_stop, "
        " SUM(realized_pnl_eur) as realized, "
        " SUM(unrealized_pnl_eur) as unrealized "
        "FROM shadow_strategy_trades GROUP BY strategy_id "
        "ORDER BY (COALESCE(SUM(realized_pnl_eur),0) + "
        " COALESCE(SUM(unrealized_pnl_eur),0)) DESC"
    ).fetchall()
    c.close()

    return {
        'ts': _now_iso(),
        'strategies': [dict(r) for r in rows],
    }


def format_report(r: dict) -> str:
    lines = [f'═══ MULTI-STRATEGY SHADOW REPORT @ {r["ts"][:16]} ═══', '']
    lines.append(f'{"Strategy":<14} {"Total":>5} {"Open":>5} {"Closed":>6} {"Target":>6} {"Stop":>5} {"Realized":>9} {"Unreal":>8} {"Sum":>9}')
    lines.append('-' * 88)
    total = {'realized': 0, 'unrealized': 0, 'n': 0}
    for s in r['strategies'][:30]:
        rl = s['realized'] or 0
        ur = s['unrealized'] or 0
        sm = rl + ur
        total['realized'] += rl
        total['unrealized'] += ur
        total['n'] += s['n_total']
        icon = '✅' if sm > 0 else '❌' if sm < 0 else '·'
        lines.append(
            f'{icon} {s["strategy_id"]:<12} {s["n_total"]:>5} {s["n_open"]:>5} '
            f'{s["n_closed"]:>6} {s["n_target"]:>6} {s["n_stop"]:>5} '
            f'{rl:>+9.0f} {ur:>+8.0f} {sm:>+9.0f}'
        )
    lines.append('-' * 88)
    lines.append(f'TOTAL: {total["n"]} trades | realized {total["realized"]:+.0f}€ | unrealized {total["unrealized"]:+.0f}€')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true')
    ap.add_argument('--hunt', action='store_true')
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()

    if args.init:
        init_table()
        print('shadow_strategy_trades table ready.')
        return 0

    if args.hunt:
        r = hunt_cycle()
        print(f'Opened: {r["opened"]} | Skipped: {r["skipped"]}')
        for s in r['opened_list']:
            print(f"  + {s['strategy']:<12} {s['ticker']:<10} @ {s['entry']:.2f}")
        return 0

    if args.update:
        r = update_prices()
        print(f'Updated: {r["updated"]} | Stops: {r["stops_hit"]} | Targets: {r["targets_hit"]}')
        return 0

    r = report()
    print(format_report(r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
