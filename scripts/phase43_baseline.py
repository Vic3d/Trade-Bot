#!/usr/bin/env python3
"""
phase43_baseline.py — Phase 43h: Sauberes Performance-Tracking ab heute.

Problem: Lifetime-PnL (+5867€) verschleiert wie Active-CEO JETZT performt.
Lösung: Snapshot ab Baseline-Datum (29.04.2026 ~12:30 CET) + nur Trades
DANACH werden in Phase-43-Performance gerechnet.

Pre-Baseline-Positionen laufen regulär (Stops/Targets aktiv) aber zählen
NICHT in Phase-43-Metrics. Albert behält volles Lernen aus Anti-Patterns,
Lifecycle, Lessons.

Nutzung:
  python3 scripts/phase43_baseline.py --init     # einmalig: Snapshot
  python3 scripts/phase43_baseline.py            # Performance-Report
  python3 scripts/phase43_baseline.py --json     # für Discord/Brief

Aus Code:
  from phase43_baseline import get_performance
  p = get_performance()
  # p['total_pnl_eur'], p['unrealized_eur'], p['realized_eur'],
  # p['n_trades'], p['n_open'], p['n_closed'], p['win_rate'],
  # p['hunter_conversion_pct'], ...
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

DB             = WS / 'data' / 'trading.db'
BASELINE_FILE  = WS / 'data' / 'phase43_baseline.json'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def take_snapshot() -> dict:
    """Snapshot des aktuellen Portfolio-Zustands → wird die Phase-43-Baseline.
    Idempotent: existierende Baseline wird überschrieben (mit Warnung)."""
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Open positions (deren PnL pre-43 ist und nicht zählt)
    opens = c.execute(
        "SELECT id, ticker, strategy, entry_price, shares, entry_date, "
        "       stop_price, target_price "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    pre43_open_ids = [r['id'] for r in opens]
    pre43_open_value = sum((r['entry_price'] or 0) * (r['shares'] or 0)
                            for r in opens)

    # Live-Wert ziehen
    try:
        from core.live_data import get_price_eur
        live_value = 0.0
        for r in opens:
            p = get_price_eur(r['ticker']) or 0
            live_value += float(p) * (r['shares'] or 0)
    except Exception:
        live_value = pre43_open_value

    cash_row = c.execute(
        "SELECT value FROM paper_fund WHERE key='current_cash'"
    ).fetchone()
    fund_row = c.execute(
        "SELECT value FROM paper_fund WHERE key='fund_value'"
    ).fetchone()
    cash = float(cash_row[0] if cash_row else 0)
    fund_total = float(fund_row[0] if fund_row else 25000)

    c.close()

    snapshot = {
        'baseline_ts':              _now_iso(),
        'baseline_label':           'Phase 43 Active-CEO Live-Start',
        'cash_eur':                 round(cash, 2),
        'fund_value_eur':           round(fund_total, 2),
        'pre43_open_count':         len(opens),
        'pre43_open_value_entry':   round(pre43_open_value, 2),
        'pre43_open_value_live':    round(live_value, 2),
        'baseline_total_eur':       round(cash + live_value, 2),
        'pre43_open_position_ids':  pre43_open_ids,
        'pre43_open_tickers':       [r['ticker'] for r in opens],
        'created_at':               _now_iso(),
    }

    # Backup falls existiert
    if BASELINE_FILE.exists():
        try:
            old = json.loads(BASELINE_FILE.read_text())
            backup = BASELINE_FILE.with_suffix('.json.bak')
            backup.write_text(json.dumps(old, indent=2))
            print(f'  ⚠ existierende Baseline überschrieben → backup: {backup.name}',
                   file=sys.stderr)
        except Exception:
            pass

    BASELINE_FILE.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    return snapshot


def get_baseline() -> dict | None:
    """Lade aktuelle Baseline. None wenn noch nie initialisiert."""
    if not BASELINE_FILE.exists():
        return None
    try:
        return json.loads(BASELINE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None


def get_performance() -> dict:
    """Rechne Performance seit Baseline.

    Definition Phase-43-Trade:
      Trade dessen entry_date >= baseline_ts UND id NICHT in pre43_open_position_ids.

    Returns:
      {
        'baseline_ts', 'baseline_total_eur', 'days_since_baseline',
        'current_total_eur',   # cash + live-value aller open Phase-43-Positionen
                                  + live-value pre43-Positionen
        'phase43_realized_eur',     # Closed Phase-43-Trades PnL
        'phase43_unrealized_eur',   # Open Phase-43-Positionen Unrealized
        'phase43_total_pnl_eur',    # = realized + unrealized
        'phase43_n_open', 'phase43_n_closed', 'phase43_n_total',
        'phase43_n_wins', 'phase43_n_losses', 'phase43_win_rate_pct',
        'phase43_avg_pnl_per_closed', 'phase43_largest_win', 'phase43_largest_loss',
        'pre43_unrealized_eur',     # Bewegung der alten Positionen seit Baseline
        'hunter_proposals_total',
        'hunter_executed', 'hunter_blocked', 'hunter_watching', 'hunter_expired',
        'hunter_conversion_pct',
      }
    """
    baseline = get_baseline()
    if not baseline:
        return {'error': 'no_baseline', 'message': 'Erst init: phase43_baseline.py --init'}

    baseline_ts = baseline['baseline_ts']
    pre43_ids = set(baseline.get('pre43_open_position_ids', []))

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    # Phase-43-Trades = entry_date > baseline_ts UND id nicht in pre43
    # Vergleich auf Datums-Ebene: substr(entry_date,1,16) > '2026-04-29 12:30'
    bts_short = baseline_ts.replace('T', ' ')[:16]

    # Open Phase-43-Trades
    open_p43 = c.execute(
        "SELECT id, ticker, strategy, entry_price, shares, entry_date, sector "
        "FROM paper_portfolio WHERE status='OPEN' "
        "AND substr(entry_date,1,16) >= ? AND id NOT IN (" +
        ','.join('?' * len(pre43_ids)) + ")" if pre43_ids else
        "SELECT id, ticker, strategy, entry_price, shares, entry_date, sector "
        "FROM paper_portfolio WHERE status='OPEN' "
        "AND substr(entry_date,1,16) >= ?",
        ([bts_short] + list(pre43_ids)) if pre43_ids else (bts_short,)
    ).fetchall()

    # Closed Phase-43-Trades
    closed_p43 = c.execute(
        "SELECT id, ticker, strategy, entry_price, close_price, shares, "
        "       pnl_eur, pnl_pct, status, exit_type, entry_date, close_date "
        "FROM paper_portfolio WHERE status IN ('CLOSED','WIN','LOSS') "
        "AND substr(entry_date,1,16) >= ? "
        "AND id NOT IN (" + ','.join('?' * len(pre43_ids)) + ")" if pre43_ids else
        "SELECT id, ticker, strategy, entry_price, close_price, shares, "
        "       pnl_eur, pnl_pct, status, exit_type, entry_date, close_date "
        "FROM paper_portfolio WHERE status IN ('CLOSED','WIN','LOSS') "
        "AND substr(entry_date,1,16) >= ?",
        ([bts_short] + list(pre43_ids)) if pre43_ids else (bts_short,)
    ).fetchall()

    # Pre-43 open: aktuelle Live-Werte (für total_eur calc)
    pre43_open_now = c.execute(
        "SELECT id, ticker, entry_price, shares "
        "FROM paper_portfolio WHERE status='OPEN' AND id IN (" +
        ','.join('?' * len(pre43_ids)) + ")",
        tuple(pre43_ids)
    ).fetchall() if pre43_ids else []

    cash = float(c.execute(
        "SELECT value FROM paper_fund WHERE key='current_cash'"
    ).fetchone()[0] or 0)
    c.close()

    # Live-Preise + PnL
    try:
        from core.live_data import get_price_eur
    except Exception:
        get_price_eur = lambda t: None  # type: ignore

    # Phase-43 Unrealized
    p43_unrealized = 0.0
    p43_open_live_value = 0.0
    p43_open_details = []
    for r in open_p43:
        live = get_price_eur(r['ticker']) or 0
        if not live:
            continue
        live = float(live)
        e = float(r['entry_price'] or 0)
        s = float(r['shares'] or 0)
        unr = (live - e) * s
        p43_unrealized += unr
        p43_open_live_value += live * s
        p43_open_details.append({
            'ticker': r['ticker'], 'strategy': r['strategy'],
            'entry': e, 'live': live, 'shares': s,
            'unrealized_eur': round(unr, 0),
            'unrealized_pct': round((live - e) / e * 100, 2) if e else 0,
        })

    # Phase-43 Realized
    p43_realized = sum(float(r['pnl_eur'] or 0) for r in closed_p43)
    p43_wins = sum(1 for r in closed_p43 if (r['pnl_eur'] or 0) > 0)
    p43_losses = sum(1 for r in closed_p43 if (r['pnl_eur'] or 0) < 0)
    n_closed = len(closed_p43)
    p43_largest_win = max((float(r['pnl_eur'] or 0) for r in closed_p43), default=0)
    p43_largest_loss = min((float(r['pnl_eur'] or 0) for r in closed_p43), default=0)

    # Pre-43 Unrealized (Bewegung der alten Positionen)
    pre43_unr = 0.0
    pre43_live_value = 0.0
    for r in pre43_open_now:
        live = get_price_eur(r['ticker']) or 0
        if not live:
            continue
        live = float(live)
        e = float(r['entry_price'] or 0)
        s = float(r['shares'] or 0)
        pre43_unr += (live - e) * s
        pre43_live_value += live * s

    current_total = cash + p43_open_live_value + pre43_live_value

    # Hunter-Stats
    hunter_total = hunter_executed = hunter_blocked = hunter_watching = hunter_expired = hunter_rejected = 0
    try:
        props = json.loads((WS / 'data' / 'proposals.json').read_text(encoding='utf-8'))
        if isinstance(props, dict):
            props = props.get('proposals', [])
        for p in props:
            if not isinstance(p, dict):
                continue
            if p.get('source') != 'ceo_active':
                continue
            if p.get('created_at', '') < baseline_ts:
                continue
            hunter_total += 1
            st = p.get('status', '?')
            if st == 'executed': hunter_executed += 1
            elif st == 'execute_blocked': hunter_blocked += 1
            elif st == 'watching': hunter_watching += 1
            elif st == 'expired': hunter_expired += 1
            elif st == 'rejected': hunter_rejected += 1
    except Exception:
        pass

    # Days since baseline
    try:
        bdt = datetime.fromisoformat(baseline_ts.replace('Z', '+00:00'))
        days = (datetime.now(timezone.utc) - bdt).total_seconds() / 86400
    except Exception:
        days = 0

    return {
        'baseline_ts':                baseline_ts,
        'baseline_label':             baseline.get('baseline_label', '?'),
        'baseline_total_eur':         baseline['baseline_total_eur'],
        'days_since_baseline':        round(days, 1),
        'current_total_eur':          round(current_total, 2),
        'phase43_realized_eur':       round(p43_realized, 2),
        'phase43_unrealized_eur':     round(p43_unrealized, 2),
        'phase43_total_pnl_eur':      round(p43_realized + p43_unrealized, 2),
        'phase43_total_pnl_pct':      round((p43_realized + p43_unrealized) / baseline['baseline_total_eur'] * 100, 2),
        'phase43_n_open':             len(open_p43),
        'phase43_n_closed':           n_closed,
        'phase43_n_total':            len(open_p43) + n_closed,
        'phase43_n_wins':             p43_wins,
        'phase43_n_losses':           p43_losses,
        'phase43_win_rate_pct':       round(p43_wins / max(1, n_closed) * 100, 1),
        'phase43_avg_pnl_per_closed': round(p43_realized / max(1, n_closed), 2),
        'phase43_largest_win_eur':    round(p43_largest_win, 0),
        'phase43_largest_loss_eur':   round(p43_largest_loss, 0),
        'phase43_open_details':       p43_open_details,
        'pre43_unrealized_eur':       round(pre43_unr, 2),
        'hunter_proposals_total':     hunter_total,
        'hunter_executed':            hunter_executed,
        'hunter_blocked':             hunter_blocked,
        'hunter_watching':            hunter_watching,
        'hunter_expired':             hunter_expired,
        'hunter_rejected':            hunter_rejected,
        'hunter_conversion_pct':      round(hunter_executed / max(1, hunter_total) * 100, 1),
    }


def format_report(p: dict) -> str:
    """Hübsch formatierter Text-Report (für Discord/Brief)."""
    if 'error' in p:
        return f"❌ {p.get('message', p['error'])}"

    days = p['days_since_baseline']
    total_pnl = p['phase43_total_pnl_eur']
    total_pct = p['phase43_total_pnl_pct']
    icon = '✅' if total_pnl > 0 else '❌' if total_pnl < 0 else '·'
    lines = [
        f'═══ PHASE 43 PERFORMANCE (seit {p["baseline_ts"][:10]}, {days:.1f}d) ═══',
        '',
        f'{icon} **Total Phase-43-PnL: {total_pnl:+.0f}€ ({total_pct:+.2f}%)**',
        f'   ├─ Realized:    {p["phase43_realized_eur"]:+.0f}€  ({p["phase43_n_closed"]} closed)',
        f'   └─ Unrealized:  {p["phase43_unrealized_eur"]:+.0f}€  ({p["phase43_n_open"]} open)',
        '',
        f'📊 Trades: {p["phase43_n_total"]} (open {p["phase43_n_open"]}, '
        f'closed {p["phase43_n_closed"]})',
        f'   WR: {p["phase43_win_rate_pct"]:.0f}% ({p["phase43_n_wins"]}W/{p["phase43_n_losses"]}L)',
        f'   Largest Win:  {p["phase43_largest_win_eur"]:+.0f}€',
        f'   Largest Loss: {p["phase43_largest_loss_eur"]:+.0f}€',
        '',
        f'🎯 Hunter-Conversion: {p["hunter_conversion_pct"]:.1f}% '
        f'({p["hunter_executed"]} executed / {p["hunter_proposals_total"]} proposals)',
        f'   blocked={p["hunter_blocked"]} watching={p["hunter_watching"]} '
        f'expired={p["hunter_expired"]} rejected={p["hunter_rejected"]}',
        '',
        f'💼 Portfolio jetzt: {p["current_total_eur"]:.0f}€ '
        f'(Baseline {p["baseline_total_eur"]:.0f}€)',
    ]
    if p['phase43_open_details']:
        lines.append('')
        lines.append('**Open Phase-43-Positionen:**')
        for o in sorted(p['phase43_open_details'], key=lambda x: -x['unrealized_eur']):
            ic = '✅' if o['unrealized_eur'] > 0 else '❌' if o['unrealized_eur'] < 0 else '·'
            lines.append(
                f"  {ic} {o['ticker']:<8} {o['strategy']:<12} "
                f"@{o['entry']:.2f}→{o['live']:.2f} "
                f"{o['unrealized_pct']:+.1f}% ({o['unrealized_eur']:+.0f}€)"
            )

    if p['pre43_unrealized_eur']:
        lines.append('')
        lines.append(
            f'_Pre-43 Positionen Bewegung seit Baseline: '
            f'{p["pre43_unrealized_eur"]:+.0f}€ (zählt nicht in Phase-43-PnL)_'
        )

    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true',
                     help='Snapshot nehmen (überschreibt existierende Baseline)')
    ap.add_argument('--json', action='store_true', help='JSON output')
    args = ap.parse_args()

    if args.init:
        s = take_snapshot()
        print(f'✅ Phase 43 Baseline gesetzt @ {s["baseline_ts"]}')
        print(f'   Cash:        {s["cash_eur"]:.0f}€')
        print(f'   Open Value:  {s["pre43_open_value_live"]:.0f}€ '
              f'({s["pre43_open_count"]} positions)')
        print(f'   Total:       {s["baseline_total_eur"]:.0f}€')
        return 0

    p = get_performance()
    if args.json:
        print(json.dumps(p, indent=2, ensure_ascii=False))
    else:
        print(format_report(p))
    return 0


if __name__ == '__main__':
    sys.exit(main())
