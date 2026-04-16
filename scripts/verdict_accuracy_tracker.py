#!/usr/bin/env python3
"""
Verdict Accuracy Tracker — Phase 7.1
======================================
Misst wie gut Albert's Deep-Dive-Verdikte tatsächlich performen.

Für jedes Verdict (KAUFEN/WARTEN/NICHT_KAUFEN):
  - Preis am Verdict-Datum (vwap/close)
  - Preise 7d, 14d, 30d später
  - KAUFEN = "hit" wenn Preis +5% innerhalb 30d erreicht (vor dem Stop)
  - NICHT_KAUFEN = "hit" wenn Preis -5% innerhalb 30d fiel (avoid correct)
  - WARTEN = "hit" wenn Preis ±3% blieb (flat correct)

Schreibt data/verdict_accuracy.json mit Per-Verdict Score + Aggregat.
Wird täglich ausgeführt (22:30 — nach Learning Cycle, vor Honesty).

Usage:
  python3 scripts/verdict_accuracy_tracker.py
  python3 scripts/verdict_accuracy_tracker.py --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
VERDICTS_FILE = WS / 'data' / 'deep_dive_verdicts.json'
ACCURACY_FILE = WS / 'data' / 'verdict_accuracy.json'

WIN_THRESHOLD_KAUFEN = 0.05   # +5% = hit
LOSS_THRESHOLD_NICHT = -0.05  # -5% = avoid war korrekt
FLAT_THRESHOLD_WARTEN = 0.03  # ±3% = warten war korrekt


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _price_at_or_after(conn: sqlite3.Connection, ticker: str, date: str) -> float | None:
    row = conn.execute(
        "SELECT close FROM prices WHERE ticker=? AND date>=? ORDER BY date ASC LIMIT 1",
        (ticker, date[:10])
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def _price_range_extremes(conn: sqlite3.Connection, ticker: str,
                          from_date: str, to_date: str) -> tuple[float | None, float | None]:
    """Return (min_low, max_high) im Zeitraum — für Intra-Range hit detection."""
    row = conn.execute("""
        SELECT MIN(COALESCE(low, close)), MAX(COALESCE(high, close))
        FROM prices WHERE ticker=? AND date>=? AND date<=?
    """, (ticker, from_date[:10], to_date[:10])).fetchone()
    if not row or row[0] is None:
        return None, None
    return float(row[0]), float(row[1])


def _evaluate_verdict(conn, ticker: str, v: dict, now: datetime) -> dict | None:
    """Gibt Evaluation oder None wenn noch zu jung (<3d)."""
    verdict = v.get('verdict', '').upper()
    date_str = v.get('date') or v.get('timestamp', '')[:10]
    if not date_str:
        return None
    try:
        vd = datetime.fromisoformat(date_str[:19]) if len(date_str) > 10 else datetime.strptime(date_str, '%Y-%m-%d')
    except Exception:
        return None

    age_days = (now.replace(tzinfo=None) - vd).days
    if age_days < 3:
        return {'ticker': ticker, 'verdict': verdict, 'age_days': age_days,
                'status': 'too_young', 'hit': None}

    entry_price = _price_at_or_after(conn, ticker, vd.strftime('%Y-%m-%d'))
    if entry_price is None:
        return {'ticker': ticker, 'verdict': verdict, 'age_days': age_days,
                'status': 'no_entry_price', 'hit': None}

    window_days = min(age_days, 30)
    end_date = (vd + timedelta(days=window_days)).strftime('%Y-%m-%d')
    low, high = _price_range_extremes(conn, ticker, vd.strftime('%Y-%m-%d'), end_date)
    if low is None:
        return {'ticker': ticker, 'verdict': verdict, 'age_days': age_days,
                'status': 'no_range', 'hit': None}

    max_up = (high - entry_price) / entry_price
    max_dn = (low - entry_price) / entry_price

    # Hit-Logik
    hit = None
    if verdict == 'KAUFEN':
        hit = max_up >= WIN_THRESHOLD_KAUFEN
    elif verdict == 'NICHT_KAUFEN':
        hit = max_dn <= LOSS_THRESHOLD_NICHT
    elif verdict == 'WARTEN':
        hit = max_up < FLAT_THRESHOLD_WARTEN and max_dn > -FLAT_THRESHOLD_WARTEN

    return {
        'ticker':       ticker,
        'verdict':      verdict,
        'source':       v.get('source', 'unknown'),
        'analyst':      v.get('analyst', ''),
        'verdict_date': vd.strftime('%Y-%m-%d'),
        'age_days':     age_days,
        'entry_price':  round(entry_price, 4),
        'max_up_pct':   round(max_up * 100, 2),
        'max_dn_pct':   round(max_dn * 100, 2),
        'window_days':  window_days,
        'hit':          hit,
        'status':       'evaluated',
    }


def _aggregate(evals: list[dict]) -> dict:
    """Gruppiere nach source (discord vs auto-rule vs deep_dive) + verdict."""
    groups = {}
    for e in evals:
        if e.get('status') != 'evaluated' or e.get('hit') is None:
            continue
        src = e.get('source', 'unknown')
        # Vereinheitliche Albert-Sources
        src_norm = 'albert' if any(k in src.lower() for k in ('albert', 'deep_dive', 'discord'))\
                  else 'auto_rule' if 'auto' in src.lower() else src
        key = f'{src_norm}::{e["verdict"]}'
        g = groups.setdefault(key, {'total': 0, 'hits': 0, 'sum_up': 0.0, 'sum_dn': 0.0})
        g['total'] += 1
        if e['hit']:
            g['hits'] += 1
        g['sum_up'] += e['max_up_pct']
        g['sum_dn'] += e['max_dn_pct']

    # Rates berechnen
    out = {}
    for k, v in groups.items():
        out[k] = {
            'n':           v['total'],
            'hit_rate':    round(v['hits'] / v['total'] * 100, 1) if v['total'] else 0,
            'avg_max_up':  round(v['sum_up'] / v['total'], 2) if v['total'] else 0,
            'avg_max_dn':  round(v['sum_dn'] / v['total'], 2) if v['total'] else 0,
        }
    return out


def run(verbose: bool = False) -> dict:
    verdicts = _load(VERDICTS_FILE, {})
    if not isinstance(verdicts, dict):
        return {'error': 'bad_verdicts_file'}

    now = datetime.now(_BERLIN)
    conn = sqlite3.connect(str(DB))

    evals = []
    for ticker, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        e = _evaluate_verdict(conn, ticker, v, now)
        if e is not None:
            evals.append(e)

    # Auch aus verdicts_history (falls Historie da)
    try:
        hist_rows = conn.execute("""
            SELECT ticker, verdict, source, verdict_date
            FROM verdicts_history
            WHERE verdict_date <= date('now', '-3 days')
        """).fetchall()
        for r in hist_rows:
            tkr, vd, src, date = r
            if any(e['ticker'] == tkr and e['verdict_date'] == date[:10] for e in evals):
                continue
            e = _evaluate_verdict(conn, tkr, {
                'verdict': vd, 'source': src, 'date': date,
            }, now)
            if e is not None:
                e['from_history'] = True
                evals.append(e)
    except sqlite3.OperationalError:
        pass

    conn.close()

    agg = _aggregate(evals)

    result = {
        'generated_at':  now.isoformat(timespec='seconds'),
        'total_evals':   len(evals),
        'evaluated_n':   sum(1 for e in evals if e.get('status') == 'evaluated'),
        'too_young_n':   sum(1 for e in evals if e.get('status') == 'too_young'),
        'no_data_n':     sum(1 for e in evals if e.get('status') in ('no_entry_price', 'no_range')),
        'by_source_verdict': agg,
        'evaluations':  evals,
    }

    # Persistieren
    ACCURACY_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    # Print Report
    print('═' * 60)
    print(f'  Verdict Accuracy — {now.strftime("%d.%m.%Y %H:%M")}')
    print('═' * 60)
    print(f'  Total evals:    {len(evals)}')
    print(f'  Evaluated:      {result["evaluated_n"]}')
    print(f'  Too young:      {result["too_young_n"]}')
    print(f'  Missing data:   {result["no_data_n"]}')
    print()
    print('  Hit-Rate by Source × Verdict:')
    print('  ' + '─' * 50)
    for key, m in sorted(agg.items()):
        src, vd = key.split('::', 1)
        print(f'  {src:12} {vd:15} n={m["n"]:2}  hit={m["hit_rate"]:5.1f}%  '
              f'up/dn: {m["avg_max_up"]:+6.2f}%/{m["avg_max_dn"]:+6.2f}%')

    if verbose:
        print()
        print('  Einzel-Evaluationen:')
        for e in sorted(evals, key=lambda x: x.get('verdict_date', ''), reverse=True):
            hit_mark = '✓' if e.get('hit') == True else ('✗' if e.get('hit') == False else '?')
            if e.get('status') == 'evaluated':
                print(f'  {hit_mark} {e["ticker"]:10} {e["verdict"]:12} '
                      f'{e["verdict_date"]} src={e["source"][:18]:18} '
                      f'up={e["max_up_pct"]:+6.2f}% dn={e["max_dn_pct"]:+6.2f}%')
    print('═' * 60)

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()
    run(verbose=args.verbose)


if __name__ == '__main__':
    main()
