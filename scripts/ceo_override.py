#!/usr/bin/env python3
"""
ceo_override.py — Manueller Override der CEO-Direktive mit TTL-Lock.

Nutzung:
    python3 scripts/ceo_override.py BULLISH --themes AI,POWER_GRID --max-week 5 --hours 8
    python3 scripts/ceo_override.py UNLOCK    # Lock entfernen, Auto-Job darf wieder schreiben
    python3 scripts/ceo_override.py STATUS    # zeige aktuelle Direktive + Lock

Mode-Werte: BULLISH | NEUTRAL | DEFENSIVE | SHUTDOWN
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DIRECTIVE = WS / 'data' / 'ceo_directive.json'

VALID_MODES = {'BULLISH', 'NEUTRAL', 'DEFENSIVE', 'SHUTDOWN'}


def load() -> dict:
    if not DIRECTIVE.exists():
        return {}
    return json.loads(DIRECTIVE.read_text(encoding='utf-8'))


def save(d: dict) -> None:
    DIRECTIVE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')


def cmd_status() -> int:
    d = load()
    if not d:
        print('Keine Direktive vorhanden.')
        return 1
    print(f"Mode:       {d.get('mode')}")
    print(f"Regime:     {d.get('regime')}")
    print(f"Themes:     {d.get('focus_themes', '—')}")
    print(f"VIX:        {d.get('vix')}")
    print(f"GeoScore:   {d.get('geo_score')} ({d.get('geo_alert_level')})")
    print(f"Timestamp:  {d.get('timestamp')}")
    lock = d.get('_locked_until')
    if lock:
        try:
            lock_dt = datetime.fromisoformat(str(lock).replace('Z', '+00:00'))
            if lock_dt.tzinfo is None:
                lock_dt = lock_dt.replace(tzinfo=timezone.utc)
            remaining = (lock_dt - datetime.now(timezone.utc)).total_seconds() / 60
            if remaining > 0:
                print(f"🔒 LOCKED: noch {remaining:.0f}min "
                      f"(by {d.get('_locked_by','?')}, reason: {d.get('_locked_reason','—')})")
            else:
                print(f"🔓 Lock expired ({-remaining:.0f}min ago) — Auto-Job darf schreiben")
        except Exception:
            print(f"🔒 LOCKED: {lock}")
    else:
        print("🔓 No lock — Auto-Job überschreibt frei")
    return 0


def cmd_unlock() -> int:
    d = load()
    if not d:
        print('Keine Direktive vorhanden.')
        return 1
    d.pop('_locked_until', None)
    d.pop('_locked_by', None)
    d.pop('_locked_reason', None)
    save(d)
    print('🔓 Lock entfernt — Auto-Job darf jetzt überschreiben.')
    return 0


def cmd_set(mode: str, themes: str | None, max_week: int | None, hours: int) -> int:
    if mode not in VALID_MODES:
        print(f'Ungültiger Mode: {mode}. Erlaubt: {", ".join(sorted(VALID_MODES))}')
        return 2

    d = load()
    now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds')
    lock_until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec='seconds')

    d['mode'] = mode
    d['mode_reason'] = f'Manueller Override via ceo_override.py ({hours}h Lock)'
    d['regime'] = {'BULLISH': 'RISK_ON', 'NEUTRAL': 'NEUTRAL',
                   'DEFENSIVE': 'RISK_OFF', 'SHUTDOWN': 'HALT'}[mode]
    d['timestamp'] = now_iso
    d['_locked_until'] = lock_until
    d['_locked_by'] = os.environ.get('USER', 'cli')
    d['_locked_reason'] = f'manual override {mode}'

    if themes:
        d['focus_themes'] = [t.strip().upper() for t in themes.split(',') if t.strip()]
    if max_week is not None:
        tr = d.setdefault('trading_rules', {})
        tr['max_new_positions_per_week'] = max_week
        tr['max_new_positions_today'] = min(max_week, max(2, max_week // 2 + 1))

    save(d)
    print(f'✅ Direktive gesetzt: mode={mode}, lock={hours}h (bis {lock_until[:16]})')
    if themes:
        print(f'   Themes: {d["focus_themes"]}')
    if max_week is not None:
        print(f'   Max new positions/week: {max_week}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', help='BULLISH|NEUTRAL|DEFENSIVE|SHUTDOWN | UNLOCK | STATUS')
    ap.add_argument('--themes', help='Komma-Liste, z.B. AI,POWER_GRID,RARE_EARTH')
    ap.add_argument('--max-week', type=int, help='Max neue Positionen/Woche')
    ap.add_argument('--hours', type=int, default=4, help='Lock-Dauer in Stunden (default 4)')
    args = ap.parse_args()

    cmd = args.mode.upper()
    if cmd == 'STATUS':
        return cmd_status()
    if cmd == 'UNLOCK':
        return cmd_unlock()
    return cmd_set(cmd, args.themes, args.max_week, args.hours)


if __name__ == '__main__':
    sys.exit(main())
