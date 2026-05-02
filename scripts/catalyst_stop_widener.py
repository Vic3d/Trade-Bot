#!/usr/bin/env python3
"""
catalyst_stop_widener.py — Phase 44n: Earnings/Fed/Major-Event aware Stops.

Vor bekannten Volatilitaets-Treibern (Earnings am naechsten Boersentag,
FOMC-Tag, Fed-Speech) → Stop temporaer weiten. Verhindert Stop-Outs durch
einmalige Event-Vola.

Logik:
  1) Pruefe pro offener Position: gibt es heute oder morgen einen Catalyst?
  2) Catalyst-Typen + Widening-Faktor:
       Earnings:      Stop x 0.97 (3% weiter)
       FOMC:          Stop x 0.97
       Fed-Speech:    Stop x 0.985 (1.5% weiter)
       Macro-Release (CPI, NFP): Stop x 0.985
  3) Nach Event (T+1): Stop wieder auf normalen Trail (von stop_manager_daily).

Run: python3 scripts/catalyst_stop_widener.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'catalyst_widener_log.jsonl'

WIDEN_FACTORS = {
    'EARNINGS':       0.97,
    'FOMC':           0.97,
    'FED_SPEECH':     0.985,
    'CPI':            0.985,
    'NFP':            0.985,
    'ECB':            0.985,
}


def _get_upcoming_catalysts(c: sqlite3.Connection, ticker: str, days: int = 2) -> list[dict]:
    """Holt Earnings/Macro fuer ticker innerhalb von 'days' Tagen.
    Versucht erst earnings_calendar, dann catalyst_calendar als Fallback."""
    out = []
    today = datetime.now().strftime('%Y-%m-%d')
    until = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    # Earnings
    try:
        rows = c.execute(
            "SELECT date, type FROM earnings_calendar "
            "WHERE ticker=? AND date >= ? AND date <= ?",
            (ticker, today, until)
        ).fetchall()
        for r in rows:
            out.append({'type': 'EARNINGS', 'date': r[0]})
    except Exception: pass
    # Catalyst
    try:
        rows = c.execute(
            "SELECT date, event_type FROM catalyst_calendar "
            "WHERE ticker=? AND date >= ? AND date <= ?",
            (ticker, today, until)
        ).fetchall()
        for r in rows:
            cat = (r[1] or '').upper()
            if 'FOMC' in cat: out.append({'type': 'FOMC', 'date': r[0]})
            elif 'CPI' in cat: out.append({'type': 'CPI', 'date': r[0]})
            elif 'NFP' in cat: out.append({'type': 'NFP', 'date': r[0]})
    except Exception: pass
    return out


def _get_macro_catalysts() -> list[dict]:
    """Allgemeine Macro-Events naechste 2 Tage (gelten fuer alle Positionen)."""
    out = []
    today = datetime.now().strftime('%Y-%m-%d')
    until = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
    try:
        from calendar_service import FED_MEETINGS_2026
        for d in FED_MEETINGS_2026:
            if today <= d <= until:
                out.append({'type': 'FOMC', 'date': d})
    except Exception: pass
    return out


def widen_stops(dry_run: bool = False) -> dict:
    if not DB.exists():
        return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    opens = c.execute(
        "SELECT id, ticker, strategy, entry_price, stop_price, notes "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()

    macro_cats = _get_macro_catalysts()
    actions = []
    for r in opens:
        tid, ticker = r['id'], r['ticker']
        entry = float(r['entry_price'] or 0)
        stop = float(r['stop_price'] or 0)
        notes = (r['notes'] or '')

        # Schon mal getted heute? (dann skip)
        today_key = datetime.now().strftime('%Y-%m-%d')
        if f'WIDENED_{today_key}' in notes:
            continue

        cats = _get_upcoming_catalysts(c, ticker) + macro_cats
        if not cats:
            continue

        # Strongest catalyst gewinnt
        strongest = max(cats, key=lambda x: WIDEN_FACTORS.get(x['type'], 1.0) and (1 - WIDEN_FACTORS.get(x['type'], 1.0)))
        factor = WIDEN_FACTORS.get(strongest['type'], 1.0)
        new_stop = round(stop * factor, 4)
        if new_stop >= stop:
            continue  # nichts zu weiten

        actions.append({
            'tid': tid, 'ticker': ticker, 'catalyst': strongest['type'],
            'date': strongest['date'], 'old_stop': stop, 'new_stop': new_stop,
            'factor': factor,
        })
        if not dry_run:
            c.execute(
                "UPDATE paper_portfolio SET stop_price=?, "
                "  notes=COALESCE(notes,'') || ? WHERE id=?",
                (new_stop,
                 f' | CATALYST-WIDEN_{today_key} {strongest["type"]} {stop:.2f}->{new_stop:.2f}',
                 tid))
            c.commit()

    c.close()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': datetime.now(timezone.utc).isoformat(),
                              'dry_run': dry_run, 'actions': actions},
                             ensure_ascii=False) + '\n')
    return {'reviewed': len(opens), 'widened': len(actions), 'actions': actions}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    r = widen_stops(dry_run=args.dry_run)
    print(f'Catalyst-Widener: reviewed={r.get("reviewed",0)}, widened={r.get("widened",0)}')
    for a in r.get('actions', []):
        print(f"  {a['ticker']:<10} {a['catalyst']} ({a['date']}): "
              f"stop {a['old_stop']:.2f} → {a['new_stop']:.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
