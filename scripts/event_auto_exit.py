#!/usr/bin/env python3
"""
Event-Driven Auto-Exit — Phase 22.1
======================================
Wenn ein Markt-bewegendes Event getriggert wird (Iran Peace, Trump Announce,
Fed Emergency), schliesst das System automatisch betroffene Positionen —
statt nur Discord-Alert zu senden.

Datenquellen:
  - data/iran_peace_watch_state.json   (wird von iran_peace_watch.py geschrieben)
  - data/trump_watch_state.json        (wird von trump_watch.py geschrieben)

Mapping Event → betroffene Thesis-IDs:
  EVENT_IMPACT[event_type] = {
    'close_if_long':  [strategy_ids bzw. Ticker-Pattern],
    'close_if_short': [...],
  }

Auto-Close via:
  - Setzt `status='INVALIDATED'` in strategies.json fuer betroffene Strategy
  - Schreibt Kill-Marker in data/force_exit_queue.json
  - paper_exit_manager nimmt im naechsten Lauf (alle 30 Min) die Queue und
    schliesst die Positionen mit exit_reason='event_auto_exit'

CLI:
  python3 scripts/event_auto_exit.py         # Check alle Watch-Files
  python3 scripts/event_auto_exit.py --dry   # Nur Report, kein Close
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
STATE_DIR = WS / 'data'
STRAT_FILE = STATE_DIR / 'strategies.json'
QUEUE_FILE = STATE_DIR / 'force_exit_queue.json'
SEEN_FILE = STATE_DIR / 'event_auto_exit_seen.json'


# ──────────────────────────────────────────────────────────────────────────
# Impact-Map: Event-Typ → Welche Strategien sind betroffen?
# ──────────────────────────────────────────────────────────────────────────

EVENT_IMPACT = {
    # Iran-Deal UNTERZEICHNET — Oel faellt, Defense faellt, Peace-Bets gewinnen
    'IRAN_PEACE_SIGNED': {
        'close_long_ids':  ['PS1', 'PS2', 'PS3', 'PS_IranPivot', 'PS_EuroDefense'],
        'close_long_tickers': ['OXY', 'XOM', 'XLE', 'FRO', 'DHT', 'KTOS', 'HII',
                                'RHM.DE', 'BA.L', 'LDO.MI', 'LMT', 'NOC'],
        'rationale': 'Iran-Deal signed → Oel-Crash + Defense-Selloff',
    },
    # Iran-Krieg ESKALIERT — Gegenteil
    'IRAN_WAR_ESCALATE': {
        'close_long_ids':  ['S10'],  # Lufthansa Peace-Bet
        'close_long_tickers': ['LHA.DE', 'AF.PA', 'IAG.L'],  # Airlines
        'rationale': 'Iran-Eskalation → Oel-Spike + Airlines-Crash',
    },
    # Trump Emergency-Tweet mit Pharma/Trade-War
    'TRUMP_PHARMA_ANNOUNCE': {
        'close_long_ids':  [],
        'close_long_tickers': ['NVO', 'LLY', 'PFE', 'JNJ', 'NVS', 'MRK', 'ABBV'],
        'rationale': 'Trump-Pharma-Announcement (siehe NVO -30% Lehre)',
    },
    'TRUMP_TARIFF_ESCALATE': {
        'close_long_ids':  ['PS18', 'PS19'],  # Deutsche Autos, Emerging Markets
        'close_long_tickers': ['BMW.DE', 'DAI', 'MBG.DE', 'VOW3.DE', 'EEM', 'FXI'],
        'rationale': 'Tariff-Eskalation → deutsche Exporteure + EM unter Druck',
    },
}

# Keyword-Mapping: welche Keywords in Watch-States triggern welches Event?
KEYWORD_TO_EVENT = {
    'IRAN_PEACE_SIGNED': [
        'iran nuclear deal', 'iran agreement signed', 'iran ceasefire',
        'iran deal reached', 'hormuz reopened', 'iran sanctions lifted',
    ],
    'IRAN_WAR_ESCALATE': [
        'iran strike', 'iran attack', 'hormuz closed', 'iran missile',
        'strait of hormuz blocked', 'iran nuclear facility attacked',
    ],
    'TRUMP_PHARMA_ANNOUNCE': [
        'pharma price', 'drug pricing', 'pharmaceutical tariff',
        'ozempic deal', 'weight loss drug price',
    ],
    'TRUMP_TARIFF_ESCALATE': [
        'tariff germany', 'tariff china', 'tariff eu', 'trade war escalate',
        'impose tariff', '25% tariff', 'auto tariff',
    ],
}


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
    except Exception:
        return default


def _save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def detect_events() -> list[dict]:
    """
    Liest alle Watch-State-Files und gibt neu getriggerte Events zurueck.
    State-Files enthalten 'seen_hashes' + die Titles; wir re-lesen die RAW-State
    und versuchen die Keywords zu matchen.
    """
    events = []
    seen = _load_json(SEEN_FILE, {'processed_hashes': []})

    state_files = {
        'iran_peace_watch_state.json': 'iran_peace',
        'trump_watch_state.json': 'trump',
    }

    for fname, src in state_files.items():
        state = _load_json(STATE_DIR / fname, {})
        # Iran-Peace-Watch hat pro Hash kein Payload — wir koennen nur pruefen
        # ob NEUE Hashes seit letztem Run vorhanden sind
        current_hashes = set(state.get('seen_hashes', []))
        last_hashes = set(seen.get(src + '_last_hashes', []))
        new_hashes = current_hashes - last_hashes
        if not new_hashes:
            continue
        # Bei iran_peace_watch: jeder neue Hash ist per se ein Peace-Signal
        if src == 'iran_peace':
            events.append({
                'event_type': 'IRAN_PEACE_SIGNED',
                'source': src,
                'new_signals': len(new_hashes),
                'detected_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            })
        # Bei trump_watch: wir haben keinen Zugriff auf Titel → konservativ skip
        # (Trump-Watch State hat auch keine Keyword-Info drin)
        # → kann man spaeter erweitern wenn trump_watch state_file erweitert

    # Update seen
    for fname, src in state_files.items():
        state = _load_json(STATE_DIR / fname, {})
        seen[src + '_last_hashes'] = state.get('seen_hashes', [])
    _save_json(SEEN_FILE, seen)

    return events


def _load_strategies() -> dict:
    return _load_json(STRAT_FILE, {})


def _save_strategies(d: dict):
    _save_json(STRAT_FILE, d)


def close_affected(event: dict, dry: bool = False) -> list[dict]:
    """Markiert alle betroffenen Strategien/Positionen zum Force-Close."""
    impact = EVENT_IMPACT.get(event['event_type'])
    if not impact:
        return []

    close_ids = set(impact.get('close_long_ids', []))
    close_tickers = set(t.upper() for t in impact.get('close_long_tickers', []))

    strats = _load_strategies()
    affected = []

    for sid, strat in strats.items():
        if not isinstance(strat, dict):
            continue
        if strat.get('status') not in ('active', 'probation', 'watchlist'):
            continue

        hit = False
        if sid in close_ids:
            hit = True
        else:
            for t in (strat.get('tickers') or []):
                if str(t).upper() in close_tickers:
                    hit = True
                    break

        if hit:
            affected.append({
                'strategy_id': sid,
                'tickers': strat.get('tickers', []),
                'event_type': event['event_type'],
                'rationale': impact.get('rationale', ''),
            })
            if not dry:
                strat['status'] = 'INVALIDATED'
                strat['killed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                strat['kill_reason'] = f"auto_exit:{event['event_type']}"

    # Force-Exit-Queue schreiben (paper_exit_manager liest sie)
    if affected and not dry:
        queue = _load_json(QUEUE_FILE, {'entries': []})
        for a in affected:
            for t in a['tickers']:
                queue['entries'].append({
                    'ticker': str(t).upper(),
                    'strategy_id': a['strategy_id'],
                    'reason': f"event_auto_exit:{event['event_type']}",
                    'queued_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                })
        _save_json(QUEUE_FILE, queue)
        _save_strategies(strats)

    return affected


def run(dry: bool = False) -> dict:
    events = detect_events()
    if not events:
        print('[event-auto-exit] Keine neuen Events.')
        return {'status': 'ok', 'events': 0, 'closed': 0}

    total_closed = 0
    for ev in events:
        affected = close_affected(ev, dry=dry)
        print(f"[event-auto-exit] Event {ev['event_type']} ({ev['source']}): "
              f"{len(affected)} Strategien betroffen")
        for a in affected:
            tag = '(DRY)' if dry else '→ INVALIDATED'
            print(f"  {tag} {a['strategy_id']}: {a['tickers']}  — {a['rationale']}")
        total_closed += len(affected)

    return {'status': 'ok', 'events': len(events), 'closed': total_closed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    r = run(dry=args.dry)
    sys.exit(0)


if __name__ == '__main__':
    main()
