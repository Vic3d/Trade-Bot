#!/usr/bin/env python3
"""
Proposal Expirer — Phase 4.2
=============================
Räumt data/proposals.json auf:
  - Ältere als 48h ohne status=executed → status=expired
  - Verdict dauerhaft WARTEN/NICHT_KAUFEN seit 24h → status=cancelled_verdict
  - Trigger-Bedingung nicht erreichbar (z.B. entry_price 30% unter current) → status=cancelled_trigger

Läuft tägl. 06:00 CET (bevor Trading-Tag startet).

Das Problem das wir lösen:
  EQNR.OL Proposal stuck seit 04.04. bei status=PENDING obwohl Verdict WARTEN.
  proposal_executor loggte bei jedem 30-min-Cycle einen neuen BLOCK in
  ceo_decisions → Feedback-Loop zeigt nur Müll an.

Usage:
  python3 scripts/proposal_expirer.py               # Normal run
  python3 scripts/proposal_expirer.py --dry-run     # Nur zeigen
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
DATA = WS / 'data'
DB = DATA / 'trading.db'
PROPOSALS = DATA / 'proposals.json'
VERDICTS = DATA / 'deep_dive_verdicts.json'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_json import atomic_write_json


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _latest_price(ticker: str) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        c.close()
        return float(row[0]) if row and row[0] else None
    except Exception:
        return None


def _age_hours(iso_str: str) -> float | None:
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_BERLIN)
        return (datetime.now(_BERLIN) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _verdict_for(ticker: str, verdicts: dict) -> tuple[str, float | None]:
    """Returns (verdict, age_days)"""
    v = verdicts.get(ticker.upper(), {})
    if not v:
        return 'MISSING', None
    try:
        age = (datetime.now(_BERLIN).date() -
               datetime.fromisoformat(v['date']).date()).days
    except Exception:
        age = None
    return v.get('verdict', 'UNKNOWN'), age


def run(dry_run: bool = False) -> dict:
    proposals = _load_json(PROPOSALS, [])
    verdicts  = _load_json(VERDICTS, {})

    if not isinstance(proposals, list):
        print('proposals.json ist kein Array')
        return {'error': 'bad_format'}

    stats = {
        'total':              len(proposals),
        'expired_age':        0,  # > 48h ohne Aktion
        'cancelled_verdict':  0,  # WARTEN/NICHT_KAUFEN stabil
        'cancelled_trigger':  0,  # Trigger unerreichbar
        'kept':               0,
        'already_final':      0,
    }
    updated = []
    changes = []

    now_iso = datetime.now(_BERLIN).isoformat(timespec='seconds')

    for p in proposals:
        if not isinstance(p, dict):
            updated.append(p)
            continue

        status = str(p.get('status', 'PENDING')).upper()
        ticker = p.get('ticker', '').upper()

        # Already terminal?
        if status in ('EXECUTED', 'CLOSED', 'CANCELLED',
                      'CANCELLED_VERDICT', 'CANCELLED_TRIGGER',
                      'EXPIRED'):
            stats['already_final'] += 1
            updated.append(p)
            continue

        created = p.get('created_at', '')
        age_h = _age_hours(created)

        # Rule 1: Verdict-based
        verdict, v_age = _verdict_for(ticker, verdicts)
        if verdict in ('WARTEN', 'NICHT_KAUFEN') and v_age is not None and v_age >= 1:
            stats['cancelled_verdict'] += 1
            p['status'] = 'CANCELLED_VERDICT'
            p['cancelled_at'] = now_iso
            p['cancel_reason'] = f'verdict={verdict} seit {v_age}d'
            changes.append(f"  {ticker}: CANCELLED_VERDICT ({verdict} {v_age}d alt)")
            updated.append(p)
            continue

        # Rule 2: Age-based — >48h ohne Aktion
        if age_h is not None and age_h >= 48:
            stats['expired_age'] += 1
            p['status'] = 'EXPIRED'
            p['cancelled_at'] = now_iso
            p['cancel_reason'] = f'stuck {age_h:.0f}h without execution'
            changes.append(f"  {ticker}: EXPIRED ({age_h:.0f}h alt)")
            updated.append(p)
            continue

        # Rule 3: Trigger unerreichbar — Entry-Price 30%+ vom aktuellen weg
        entry = p.get('entry_price')
        if entry:
            price = _latest_price(ticker)
            if price and abs(price - entry) / entry > 0.30:
                stats['cancelled_trigger'] += 1
                p['status'] = 'CANCELLED_TRIGGER'
                p['cancelled_at'] = now_iso
                p['cancel_reason'] = f'price {price:.2f} vs entry {entry:.2f} drift >30%'
                changes.append(f"  {ticker}: CANCELLED_TRIGGER (Drift {((price-entry)/entry)*100:+.1f}%)")
                updated.append(p)
                continue

        # Keep
        stats['kept'] += 1
        updated.append(p)

    if not dry_run and changes:
        atomic_write_json(PROPOSALS, updated)

    print(f'=== Proposal Expirer {"[DRY]" if dry_run else ""} ===')
    print(f'Total: {stats["total"]}')
    print(f'  Already final:      {stats["already_final"]}')
    print(f'  Kept (noch aktiv):  {stats["kept"]}')
    print(f'  Expired (>48h):     {stats["expired_age"]}')
    print(f'  Cancelled verdict:  {stats["cancelled_verdict"]}')
    print(f'  Cancelled trigger:  {stats["cancelled_trigger"]}')
    if changes:
        print('\nÄnderungen:')
        for c in changes:
            print(c)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
