#!/usr/bin/env python3
"""
Thesis Watchlist Manager — Phase 22
====================================
Verwaltet data/watchlist.json: bis zu 30 aktive Thesen im Beobachtungs-Modus.

Status-Maschine:
  DRAFT         → nicht alle 6 Felder ausgearbeitet, nicht tradebar
  ACTIVE_WATCH  → vollstaendig, warten auf Entry-Trigger
  TRIGGER_HIT   → Entry-Trigger erreicht, Ausfuehrung freigegeben
  TRADED        → Position offen (gespiegelt aus paper_portfolio)
  CLOSED        → Trade geschlossen (Exit-Ergebnis geloggt)
  ARCHIVED      → Katalysator stale oder Kill-Trigger gefeuert ohne Trade

Integration:
  - thesis_quality_score bestimmt Mode (FULL_AUTO / SEMI_AUTO / DRAFT)
  - thesis_monitor polled Entry-Trigger und Kill-Trigger
  - paper_trade_engine checked bei Entry ob These in ACTIVE_WATCH ist

Usage:
  python3 scripts/thesis_watchlist.py --rebuild       # aus strategies.json bauen
  python3 scripts/thesis_watchlist.py --status        # Dashboard ausgeben
  python3 scripts/thesis_watchlist.py --tick          # Status-Update eintakten
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
STRATS = WS / 'data' / 'strategies.json'
WATCHLIST = WS / 'data' / 'watchlist.json'
LOG = WS / 'data' / 'watchlist.log'

sys.path.insert(0, str(WS / 'scripts'))
try:
    from intelligence.catalyst_utils import catalyst_status
    from intelligence.thesis_quality_score import score_thesis
except Exception as e:
    print(f'FATAL import: {e}')
    sys.exit(1)


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec='seconds')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _load() -> dict:
    if not WATCHLIST.exists():
        return {'updated': None, 'theses': {}}
    try:
        return json.loads(WATCHLIST.read_text(encoding='utf-8'))
    except Exception:
        return {'updated': None, 'theses': {}}


def _save(data: dict) -> None:
    data['updated'] = datetime.now().isoformat(timespec='seconds')
    WATCHLIST.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def _derive_status(strategy: dict, tqs_result: dict) -> str:
    """Bestimmt Watchlist-Status aus Strategie-State."""
    if tqs_result['mode'] == 'DRAFT':
        return 'DRAFT'
    # Katalysator stale?
    cat = catalyst_status(strategy)
    if cat['state'] == 'STALE':
        return 'ARCHIVED'
    # Per Default: ACTIVE_WATCH. TRIGGER_HIT/TRADED wird von thesis_monitor gesetzt
    if strategy.get('health') == 'paused':
        return 'ARCHIVED'
    if strategy.get('locked') and not cat['lock_override']:
        return 'ARCHIVED'
    return 'ACTIVE_WATCH'


def rebuild_from_strategies() -> dict:
    """Initialisiert watchlist.json aus strategies.json."""
    if not STRATS.exists():
        _log('FATAL strategies.json fehlt')
        return {}
    strats = json.loads(STRATS.read_text(encoding='utf-8'))
    wl = _load()
    wl.setdefault('theses', {})

    rebuild_stats = {'draft': 0, 'active': 0, 'archived': 0}
    count_cap = 30

    for sid, cfg in strats.items():
        if not isinstance(cfg, dict) or sid.startswith('_') or sid == 'emerging_themes':
            continue
        tqs = score_thesis(cfg)
        status = _derive_status(cfg, tqs)
        entry = wl['theses'].get(sid, {})
        entry.update({
            'strategy_id': sid,
            'tickers': cfg.get('tickers') or ([cfg.get('ticker')] if cfg.get('ticker') else []),
            'thesis': (cfg.get('thesis') or cfg.get('description') or '')[:200],
            'tqs': tqs['tqs'],
            'grade': tqs['grade'],
            'mode': tqs['mode'],
            'missing_fields': tqs['missing'],
            'status': status,
            'catalyst_state': catalyst_status(cfg)['state'],
            'last_updated': datetime.now().isoformat(timespec='seconds'),
        })
        if 'first_added' not in entry:
            entry['first_added'] = datetime.now().isoformat(timespec='seconds')
        wl['theses'][sid] = entry

        if status == 'DRAFT':
            rebuild_stats['draft'] += 1
        elif status == 'ARCHIVED':
            rebuild_stats['archived'] += 1
        else:
            rebuild_stats['active'] += 1

    # Cap bei 30 aktiven: archive Ueberschuss mit niedrigstem TQS
    active = [(k, v) for k, v in wl['theses'].items() if v['status'] == 'ACTIVE_WATCH']
    if len(active) > count_cap:
        active.sort(key=lambda kv: kv[1]['tqs'])
        overflow = active[: len(active) - count_cap]
        for k, _ in overflow:
            wl['theses'][k]['status'] = 'ARCHIVED'
            wl['theses'][k]['archived_reason'] = 'watchlist_cap_30'
            _log(f'ARCHIVED {k} (cap reached, TQS {wl["theses"][k]["tqs"]})')

    _save(wl)
    _log(f'REBUILD {rebuild_stats}')
    return rebuild_stats


def get_tradable_thesis(strategy_id: str) -> dict | None:
    """
    API fuer paper_trade_engine: darf diese These gerade getradet werden?
    Returns None wenn nicht, sonst {status, mode, tqs, ...}.
    """
    wl = _load()
    e = wl.get('theses', {}).get(strategy_id)
    if not e:
        return None
    if e['status'] not in ('ACTIVE_WATCH', 'TRIGGER_HIT'):
        return None
    if e['mode'] == 'DRAFT':
        return None
    return e


def mark_trigger_hit(strategy_id: str, reason: str) -> None:
    wl = _load()
    if strategy_id in wl.get('theses', {}):
        wl['theses'][strategy_id]['status'] = 'TRIGGER_HIT'
        wl['theses'][strategy_id]['trigger_hit_at'] = datetime.now().isoformat(timespec='seconds')
        wl['theses'][strategy_id]['trigger_reason'] = reason
        _save(wl)
        _log(f'TRIGGER_HIT {strategy_id}: {reason}')


def mark_traded(strategy_id: str, trade_id: int | str) -> None:
    wl = _load()
    if strategy_id in wl.get('theses', {}):
        wl['theses'][strategy_id]['status'] = 'TRADED'
        wl['theses'][strategy_id]['trade_id'] = trade_id
        wl['theses'][strategy_id]['traded_at'] = datetime.now().isoformat(timespec='seconds')
        _save(wl)
        _log(f'TRADED {strategy_id} trade_id={trade_id}')


def mark_closed(strategy_id: str, result: dict) -> None:
    wl = _load()
    if strategy_id in wl.get('theses', {}):
        wl['theses'][strategy_id]['status'] = 'CLOSED'
        wl['theses'][strategy_id]['close_result'] = result
        wl['theses'][strategy_id]['closed_at'] = datetime.now().isoformat(timespec='seconds')
        _save(wl)
        _log(f'CLOSED {strategy_id} pnl={result.get("pnl_eur")}')


def dashboard() -> str:
    wl = _load()
    theses = wl.get('theses', {})
    if not theses:
        return '(Watchlist leer — erst --rebuild ausfuehren)'
    groups = {}
    for sid, e in theses.items():
        groups.setdefault(e['status'], []).append((sid, e))
    lines = [f'=== Watchlist ({len(theses)} Thesen, updated {wl.get("updated")}) ===']
    for status in ('TRIGGER_HIT', 'TRADED', 'ACTIVE_WATCH', 'DRAFT', 'CLOSED', 'ARCHIVED'):
        items = groups.get(status, [])
        if not items:
            continue
        items.sort(key=lambda kv: -kv[1]['tqs'])
        lines.append(f'\n-- {status} ({len(items)}) --')
        for sid, e in items[:15]:
            tix = ','.join((e.get('tickers') or [])[:3])
            lines.append(
                f'  {sid:14} TQS={e["tqs"]:>3} {e["grade"]} {e["mode"]:10} '
                f'cat={e.get("catalyst_state","?"):10} [{tix}]'
            )
        if len(items) > 15:
            lines.append(f'  ... +{len(items)-15} mehr')
    return '\n'.join(lines)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebuild', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--tick', action='store_true', help='schnelle Status-Re-Sync')
    args = ap.parse_args()
    if args.rebuild or args.tick:
        s = rebuild_from_strategies()
        print(s)
    if args.status or not any([args.rebuild, args.tick]):
        print(dashboard())
