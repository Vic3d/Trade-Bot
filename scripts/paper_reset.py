#!/usr/bin/env python3
"""
paper_reset.py — Phase 44d: Quartals-Reset für Paper-Trading.

Zweck: nach Performance-Snapshot Cash + Open-Positions zurücksetzen
auf 25.000€ Startkapital. Lerndaten (Anti-Patterns, Lifecycle, Lessons)
bleiben unverändert.

WICHTIG: Reset behält:
  - trading_learnings.json (Strategy-Scores)
  - anti_patterns.json
  - strategies.json (Status, Genesis, Lifecycle)
  - ceo_self_reflection.json
  - macro_events Tabelle
  - news_events Tabelle

Reset entfernt nur:
  - Open-Positions (status='OPEN' → status='RESET_CLOSED' mit close-price = live)
  - Cash zurück auf 25.000€
  - Phase-43-Baseline neu setzen

Run:
  python3 scripts/paper_reset.py --snapshot       # Snapshot vor Reset
  python3 scripts/paper_reset.py --execute        # ECHTER Reset
  python3 scripts/paper_reset.py --status         # letzter Reset-Stand
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
RESET_LOG       = WS / 'data' / 'paper_reset_log.jsonl'
RESET_SNAPSHOT  = WS / 'data' / 'paper_reset_snapshots.jsonl'

START_CAPITAL = 25000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def take_snapshot() -> dict:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Aktueller Cash
    cash_row = c.execute(
        "SELECT value FROM paper_fund WHERE key='current_cash'"
    ).fetchone()
    cash = float(cash_row[0]) if cash_row else 0

    # Open Positions
    opens = c.execute(
        "SELECT id, ticker, strategy, entry_price, shares, entry_date "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()

    # Live-Werte
    try:
        from core.live_data import get_price_eur
    except Exception:
        get_price_eur = lambda t: None  # type: ignore

    open_value_live = 0
    open_value_entry = 0
    for r in opens:
        live = get_price_eur(r['ticker']) or r['entry_price'] or 0
        live = float(live)
        s = float(r['shares'] or 0)
        open_value_live += live * s
        open_value_entry += float(r['entry_price'] or 0) * s

    # Closed PnL Summe
    closed_sum = c.execute(
        "SELECT SUM(pnl_eur) FROM paper_portfolio "
        "WHERE status IN ('CLOSED','WIN','LOSS')"
    ).fetchone()[0] or 0

    c.close()

    snap = {
        'ts': _now_iso(),
        'cash_eur': round(cash, 2),
        'open_positions_count': len(opens),
        'open_value_entry_eur': round(open_value_entry, 2),
        'open_value_live_eur': round(open_value_live, 2),
        'closed_lifetime_pnl_eur': round(closed_sum, 2),
        'fund_value_total_eur': round(cash + open_value_live, 2),
        'roi_pct': round((cash + open_value_live - START_CAPITAL) / START_CAPITAL * 100, 2),
    }
    RESET_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with open(RESET_SNAPSHOT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(snap, ensure_ascii=False) + '\n')
    return snap


def execute_reset() -> dict:
    """Führt Reset durch.
    1. Snapshot speichern
    2. Open Positions schließen mit Live-Preis (status='RESET_CLOSED')
    3. Cash zurück auf 25.000€
    4. Phase-43-Baseline neu setzen
    """
    snap = take_snapshot()
    now = _now_iso()
    today = datetime.now().strftime('%Y-%m-%d')

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    try:
        from core.live_data import get_price_eur
    except Exception:
        get_price_eur = lambda t: None  # type: ignore

    # 1. Open positions schließen
    opens = c.execute(
        "SELECT id, ticker, entry_price, shares FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    closed = []
    for r in opens:
        live = get_price_eur(r['ticker']) or r['entry_price'] or 0
        live = float(live)
        e = float(r['entry_price'] or 0)
        s = float(r['shares'] or 0)
        pnl = (live - e) * s
        pnl_pct = ((live - e) / e * 100) if e else 0
        c.execute(
            "UPDATE paper_portfolio SET status='RESET_CLOSED', "
            " close_date=?, close_price=?, pnl_eur=?, pnl_pct=?, "
            " exit_type='PAPER_RESET', "
            " notes=COALESCE(notes,'') || ? WHERE id=?",
            (now, live, pnl, pnl_pct,
             f' | Reset @ {today}: live {live:.2f} pnl {pnl:+.0f}€',
             r['id'])
        )
        closed.append({'ticker': r['ticker'], 'pnl': round(pnl, 2)})

    # 2. Cash zurück auf 25.000€
    c.execute(
        "UPDATE paper_fund SET value=? WHERE key='current_cash'",
        (str(START_CAPITAL),)
    )
    c.execute(
        "INSERT OR REPLACE INTO paper_fund (key, value) VALUES (?,?)",
        ('fund_value', str(START_CAPITAL))
    )

    c.commit()
    c.close()

    # 3. Phase-43-Baseline neu nehmen
    try:
        from phase43_baseline import take_snapshot as _ph_snap
        _ph_snap()
    except Exception as e:
        print(f'[reset] phase43-snapshot err: {e}', file=sys.stderr)

    result = {
        'ts': now,
        'pre_reset_snapshot': snap,
        'closed_positions': len(closed),
        'closed_total_pnl_eur': round(sum(c['pnl'] for c in closed), 2),
        'cash_after': START_CAPITAL,
        'closed_list': closed[:20],
    }

    # Log
    with open(RESET_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False) + '\n')

    # Discord-Push (post-fact)
    try:
        from discord_dispatcher import send_alert, TIER_HIGH
        msg = (
            f'🔄 **PAPER-RESET** ausgeführt @ {today}\n'
            f'Pre-Reset: {snap["fund_value_total_eur"]:.0f}€ '
            f'(ROI {snap["roi_pct"]:+.1f}%)\n'
            f'Geschlossen: {len(closed)} Positionen, '
            f'Reset-PnL {result["closed_total_pnl_eur"]:+.0f}€\n'
            f'Cash zurück auf {START_CAPITAL}€\n'
            f'_Lerndaten (Anti-Patterns, Lifecycle, Lessons) bleiben._'
        )
        send_alert(msg, tier=TIER_HIGH, category='paper_reset')
    except Exception:
        pass

    return result


def status() -> dict:
    """Letzter Reset + Snapshots."""
    snaps = []
    if RESET_SNAPSHOT.exists():
        with open(RESET_SNAPSHOT, encoding='utf-8') as f:
            for line in f:
                try: snaps.append(json.loads(line))
                except: pass
    resets = []
    if RESET_LOG.exists():
        with open(RESET_LOG, encoding='utf-8') as f:
            for line in f:
                try: resets.append(json.loads(line))
                except: pass
    return {
        'snapshots_count': len(snaps),
        'last_snapshot': snaps[-1] if snaps else None,
        'resets_count': len(resets),
        'last_reset': resets[-1] if resets else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', action='store_true')
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args()

    if args.snapshot:
        s = take_snapshot()
        print(json.dumps(s, indent=2))
        return 0

    if args.execute:
        r = execute_reset()
        print(f'✅ Reset ausgeführt @ {r["ts"][:16]}')
        print(f'  Geschlossen: {r["closed_positions"]} positions ({r["closed_total_pnl_eur"]:+.0f}€)')
        print(f'  Cash: {r["cash_after"]}€')
        return 0

    s = status()
    print(json.dumps(s, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
