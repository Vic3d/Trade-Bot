#!/usr/bin/env python3
"""
daily_position_audit.py — Täglicher Live-Check aller OPEN-Positionen.

Läuft 2x täglich (08:30 + 22:00 CET). Für JEDE OPEN-Position:
  1. Holt Live-EUR-Preis (get_price_eur)
  2. Vergleicht mit entry/stop/target
  3. Berechnet aktuellen unrealisierten PnL (eur + %)
  4. Distance-to-Stop und Distance-to-Target in %
  5. Currency-Sanity-Check (Ratio entry vs live)
  6. Stop-Trigger-Warning (Live <= Stop * 1.02 → ALARM)
  7. Stale-Data-Check (Live-Preis nicht abrufbar → ALARM)

Output:
  - Discord-Report 2x täglich (chunked falls > 1900)
  - Schreibt in `data/position_audit.jsonl` (append-only Trend-Tracking)

Damit hat Victor die Garantie:
  - Jede Position wurde mindestens 2x/Tag mit Live-Daten verifiziert
  - Bei Stop-Nähe oder Stale-Data sofort Alarm
  - Currency-Mismatch wird bemerkt selbst wenn Guards versagen
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB         = WS / 'data' / 'trading.db'
AUDIT_LOG  = WS / 'data' / 'position_audit.jsonl'

STOP_WARN_PCT     = 2.0   # Live innerhalb 2% des Stops → WARN
TARGET_WARN_PCT   = 2.0   # Live innerhalb 2% des Targets → WARN  (FYI)
CURRENCY_RATIO_LO = 0.5
CURRENCY_RATIO_HI = 2.0


def audit_all_open() -> dict:
    try:
        from core.live_data import get_price_eur
    except Exception as e:
        return {'error': f'live_data nicht ladbar: {e}', 'positions': []}

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    opens = c.execute("""
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               shares, entry_date, sector
        FROM paper_portfolio WHERE status='OPEN'
        ORDER BY entry_date DESC
    """).fetchall()
    c.close()

    results = []
    summary = {
        'total': len(opens),
        'live_ok': 0,
        'stale_data': 0,
        'currency_mismatch': 0,
        'stop_warn': 0,
        'target_warn': 0,
        'unrealized_pnl_total': 0.0,
    }

    for r in opens:
        tk = r['ticker']
        entry = r['entry_price'] or 0
        stop = r['stop_price'] or 0
        target = r['target_price'] or 0
        shares = r['shares'] or 0

        try:
            live = get_price_eur(tk)
        except Exception as e:
            live = None

        item = {
            'id': r['id'], 'ticker': tk, 'strategy': r['strategy'],
            'entry': entry, 'stop': stop, 'target': target,
            'shares': shares, 'entry_date': str(r['entry_date'])[:10],
            'live_eur': live,
        }

        if not live or live <= 0:
            item['flag'] = 'STALE_DATA'
            summary['stale_data'] += 1
            results.append(item)
            continue

        # Ratio (currency check)
        if entry > 0:
            ratio = live / entry
            item['ratio'] = round(ratio, 3)
            if ratio < CURRENCY_RATIO_LO or ratio > CURRENCY_RATIO_HI:
                item['flag'] = 'CURRENCY_MISMATCH'
                summary['currency_mismatch'] += 1
                results.append(item)
                continue

        # PnL
        if entry > 0 and shares > 0:
            move_pct = (live - entry) / entry * 100
            unrealized_eur = (live - entry) * shares
            item['move_pct'] = round(move_pct, 2)
            item['unrealized_eur'] = round(unrealized_eur, 2)
            summary['unrealized_pnl_total'] += unrealized_eur

        # Distance to stop / target
        if stop > 0 and live > 0:
            dist_stop_pct = (live - stop) / live * 100
            item['dist_to_stop_pct'] = round(dist_stop_pct, 2)
            if dist_stop_pct <= STOP_WARN_PCT:
                item['flag'] = 'STOP_WARN'
                summary['stop_warn'] += 1
        if target > 0 and live > 0:
            dist_target_pct = (target - live) / live * 100
            item['dist_to_target_pct'] = round(dist_target_pct, 2)
            if dist_target_pct <= TARGET_WARN_PCT:
                item.setdefault('flag', 'TARGET_WARN')
                summary['target_warn'] += 1

        if 'flag' not in item:
            item['flag'] = 'OK'
            summary['live_ok'] += 1

        results.append(item)

    return {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'summary': summary,
        'positions': results,
    }


def format_for_discord(audit: dict) -> str:
    s = audit['summary']
    lines = [
        f'📊 **Tägliches Position-Audit** ({datetime.now().strftime("%H:%M %d.%m")})',
        f'Total OPEN: {s["total"]} | Live OK: {s["live_ok"]} | '
        f'Unrealized PnL: **{s["unrealized_pnl_total"]:+.0f}€**',
    ]
    if s['stop_warn'] or s['stale_data'] or s['currency_mismatch']:
        lines.append(f'⚠️ Issues: stale={s["stale_data"]}, currency-mismatch={s["currency_mismatch"]}, '
                     f'near-stop={s["stop_warn"]}, near-target={s["target_warn"]}')
    lines.append('')

    # Per-Position Tabelle (sortiert nach unrealized_eur descending)
    sorted_pos = sorted(audit['positions'],
                        key=lambda p: p.get('unrealized_eur', 0), reverse=True)
    for p in sorted_pos:
        flag = p.get('flag', '?')
        icon = {'OK': '✅', 'STOP_WARN': '🚨', 'TARGET_WARN': '🎯',
                'STALE_DATA': '❌', 'CURRENCY_MISMATCH': '💱'}.get(flag, '?')
        live = p.get('live_eur', 0) or 0
        move = p.get('move_pct', 0)
        upnl = p.get('unrealized_eur', 0) or 0
        dist_stop = p.get('dist_to_stop_pct', '?')
        line = (f"{icon} `{p['ticker']:<10}` "
                f"entry {p['entry']:>7.2f} → live {live:>7.2f} "
                f"({move:+5.1f}%, {upnl:+5.0f}€) | "
                f"stop-Δ {dist_stop}%")
        if flag != 'OK':
            line += f' [{flag}]'
        lines.append(line)

    return '\n'.join(lines)


def main() -> int:
    audit = audit_all_open()
    if 'error' in audit:
        print(f'❌ {audit["error"]}')
        return 1

    # Persist
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(audit, ensure_ascii=False) + '\n')

    msg = format_for_discord(audit)
    print(msg)

    # Discord-Push
    s = audit['summary']
    severity = 'low'
    if s.get('currency_mismatch') or s.get('stale_data'):
        severity = 'high'
    elif s.get('stop_warn'):
        severity = 'medium'
    try:
        from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM, TIER_LOW
        tier = {'high': TIER_HIGH, 'medium': TIER_MEDIUM, 'low': TIER_LOW}[severity]
        for i in range(0, len(msg), 1900):
            send_alert(msg[i:i+1900], tier=tier, category='position_audit',
                       dedupe_key=f'audit_{datetime.now().strftime("%Y-%m-%d-%H")}')
    except Exception as e:
        print(f'Discord error: {e}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
