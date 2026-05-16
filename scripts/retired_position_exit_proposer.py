#!/usr/bin/env python3
"""
retired_position_exit_proposer.py — Phase 45bf (Victor 2026-05-16).

Albert-Capability-Request (Digest 16.05): "ARKG (PS15) und MOS (PS5) laufen
auf retired Strategien. Ich diagnostiziere das seit 3 Tagen ohne Exit. Das
ist kein Willensproblem — Brain-Tick kann keine Exits triggern, nur Tagebuch
schreiben."

Lösung: Dieses Skript scannt täglich alle offenen Positionen, prüft ihren
Strategie-Status gegen die kanonische DEAD-Liste (strategy_throttle) und
generiert für jede „verwaiste" Position einen Exit-Proposal:
  - Eintrag in data/exit_proposals.jsonl (CEO-Confirmation-Queue)
  - HIGH-Notification in ceo_inbox (in der nächsten Brain-Tick-Runde sichtbar)
  - Dedupe pro Trade-ID innerhalb 24h (kein Spam)

Bewusst KEIN Auto-Exit — der User wollte explizit „CEO-bestätigungspflichtig".
Die Verbindung Proposal→Execution kann ein separater paper_exit_manager-Hook
in einer späteren Phase ziehen.

Scheduler: täglich 07:30 CEST (Mo-Fr, vor EU-Pre-Market).
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
STRATS = WS / 'data' / 'strategies.json'
PROPOSALS = WS / 'data' / 'exit_proposals.jsonl'

DEDUPE_WINDOW_H = 24


def _load_dead_statuses() -> set[str]:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from strategy_throttle import DEAD_STATUSES
        return {s.lower() for s in DEAD_STATUSES}
    except Exception:
        return {'paused', 'retired', 'auto_deprecated', 'archived', 'draft'}


def _recently_proposed(trade_id: int, now: datetime) -> bool:
    if not PROPOSALS.exists():
        return False
    cutoff = (now - timedelta(hours=DEDUPE_WINDOW_H)).isoformat()
    try:
        with open(PROPOSALS, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if (e.get('trade_id') == trade_id
                        and e.get('ts', '') >= cutoff):
                    return True
    except Exception:
        pass
    return False


def scan() -> dict:
    now = datetime.now(timezone.utc)
    dead = _load_dead_statuses()

    # Strategien laden
    try:
        strats = json.loads(STRATS.read_text(encoding='utf-8'))
    except Exception as e:
        return {'error': f'strategies_load_fail: {e}'}

    # Offene Positionen
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT id, ticker, strategy, entry_price, entry_date, shares, "
            "stop_price, target_price "
            "FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        c.close()
    except Exception as e:
        return {'error': f'db_fail: {e}'}

    proposals = []
    for tid, ticker, sid, entry, edate, shares, stop, target in rows:
        meta = strats.get(sid)
        if not isinstance(meta, dict):
            continue
        status = str(meta.get('status', '')).lower()
        health = str(meta.get('health', '')).lower()
        if status not in dead and health not in dead:
            continue
        if _recently_proposed(tid, now):
            continue
        proposals.append({
            'ts': now.isoformat(timespec='seconds'),
            'trade_id': tid,
            'ticker': ticker,
            'strategy': sid,
            'strategy_status': status or '?',
            'strategy_health': health or '?',
            'entry_price': entry,
            'entry_date': edate,
            'shares': shares,
            'current_stop': stop,
            'reason': (f"Strategy {sid} ist {status or health} — "
                       f"laufende Position ohne aktive These."),
            'recommended_action': 'CLOSE_AT_NEXT_OPEN',
            'status': 'PENDING_CEO_CONFIRMATION',
        })

    if proposals:
        PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPOSALS, 'a', encoding='utf-8') as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + '\n')

        # CEO-Inbox
        try:
            from ceo_inbox import write_event
            tickers_str = ', '.join(
                f"{p['ticker']}({p['strategy']})" for p in proposals)
            write_event(
                event_type='retired_position_exit_proposal',
                message=(f'{len(proposals)} offene Position(en) auf '
                         f'toten Strategien — Exit-Proposal generiert: '
                         f'{tickers_str}. Bestätigung in '
                         f'data/exit_proposals.jsonl.'),
                severity='warning', category='action_required',
                user_pinged=False,
                payload={'proposals': proposals},
            )
        except Exception:
            pass

    return {
        'ts': now.isoformat(timespec='seconds'),
        'open_positions': len(rows),
        'new_exit_proposals': len(proposals),
        'proposals': [{'trade_id': p['trade_id'], 'ticker': p['ticker'],
                       'strategy': p['strategy']} for p in proposals],
    }


def main() -> int:
    r = scan()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
