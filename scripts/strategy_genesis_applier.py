#!/usr/bin/env python3
"""
strategy_genesis_applier.py — Phase 45ba (Victor 2026-05-14).

Albert's Befund (CLI-Audit 2026-05-14): "Das System denkt viel, handelt aber
fast nicht — Vorschläge werden nie umgesetzt."

Konkrete Lücke:
  - strategy_genesis_engine.py (täglich 06:20, Opus) generiert create_strategy-
    Proposals und schreibt sie nach albert_strategist_proposals.jsonl.
  - NIEMAND wendet diese Proposals auf strategies.json an.
  - Folge: dieselben Proposals (PS_SILVER_BREAKOUT, PS_COPPER_BREAKOUT …)
    werden TÄGLICH neu vorgeschlagen, weil die Gap-Analyse sie nie als
    "existiert bereits" sieht. Karussell ohne Ausgang.

Dieses Skript schließt die Brücke:
  1. Liest create_strategy-Proposals aus albert_strategist_proposals.jsonl
     (Quelle: genesis_engine) der letzten N Tage.
  2. Für jedes target das NOCH NICHT in strategies.json existiert:
     - respektiert strategy_throttle (MAX_ACTIVE)
     - legt die Strategie an (status='active', genesis-Metadaten)
  3. Schreibt ein Ledger data/genesis_applied.jsonl — verhindert Doppel-Apply.
  4. Meldet das Ergebnis in ceo_inbox.

Bewusst NUR create_strategy (additiv, reversibel via Lifecycle-Audit).
kill/pause/rotate bleiben dem strategy_lifecycle + Menschen überlassen.

Run: täglich 06:35 (nach Genesis 06:20).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
PROPOSALS = WS / 'data' / 'albert_strategist_proposals.jsonl'
STRATS_FILE = WS / 'data' / 'strategies.json'
LEDGER = WS / 'data' / 'genesis_applied.jsonl'

LOOKBACK_DAYS = 3
PRIORITY_CONFIDENCE = {'high': 65, 'medium': 55, 'med': 55, 'low': 45}


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _recent_proposals(hours: int) -> list[dict]:
    """Alle create_strategy-Proposals aus genesis_engine der letzten N Stunden."""
    if not PROPOSALS.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    out = []
    try:
        with open(PROPOSALS, encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('ts', '') < cutoff:
                    continue
                # genesis_engine schreibt source='genesis_engine'; der Strategist-
                # Slot schreibt ohne source-Feld. Beide enthalten create_strategy.
                for p in rec.get('proposals', []) or []:
                    if p.get('action') == 'create_strategy' and p.get('target'):
                        out.append(p)
    except Exception:
        pass
    return out


def _already_applied() -> set[str]:
    """Targets die schon mal angewendet (oder geskippt-weil-existiert) wurden."""
    applied = set()
    if not LEDGER.exists():
        return applied
    try:
        with open(LEDGER, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('target'):
                        applied.add(e['target'])
                except Exception:
                    pass
    except Exception:
        pass
    return applied


def _build_strategy(p: dict, now: datetime) -> dict:
    tickers = []
    for t in p.get('tickers', []) or []:
        if isinstance(t, (list, tuple)) and t:
            tickers.append(t[0])
        elif isinstance(t, str):
            tickers.append(t)
    return {
        'name': p.get('target'),
        'type': 'paper',
        'status': 'active',
        'thesis': (p.get('thesis') or '')[:1000],
        'tickers': tickers,
        'entry_trigger': p.get('trigger', ''),
        'stop_logic': p.get('stop_logic', ''),
        'confidence': PRIORITY_CONFIDENCE.get(str(p.get('priority', '')).lower(), 55),
        'timeframe': f"{p.get('evaluate_after_days', 7)} Tage (eval)",
        'genesis': {
            'created': now.isoformat(timespec='seconds'),
            'source': 'strategy_genesis_applier',
            'trigger': p.get('trigger', ''),
            'rationale': p.get('rationale', ''),
            'expected_outcome': p.get('expected_outcome', ''),
            'evaluate_after_days': p.get('evaluate_after_days', 7),
            'auto_discovered': True,
        },
    }


def apply() -> dict:
    now = datetime.now(timezone.utc)
    proposals = _recent_proposals(LOOKBACK_DAYS * 24)
    strats = _load_json(STRATS_FILE, {})
    if not isinstance(strats, dict):
        return {'error': 'strategies.json ist kein dict', 'created': 0}

    already = _already_applied()

    # Throttle-Check-Funktion laden
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from strategy_throttle import can_create_new_strategy, log_throttle_block
    except Exception:
        def can_create_new_strategy(s):  # type: ignore
            return True, 'throttle-modul fehlt'
        def log_throttle_block(*a, **k):  # type: ignore
            pass

    # Dedupe innerhalb dieses Laufs: pro target nur 1x, neuestes Proposal gewinnt
    by_target: dict[str, dict] = {}
    for p in proposals:
        by_target[p['target']] = p  # spätere überschreiben frühere

    created, skipped_exist, skipped_throttle, ledger_rows = [], [], [], []
    for target, p in by_target.items():
        if target in strats:
            if target not in already:
                ledger_rows.append({'ts': now.isoformat(timespec='seconds'),
                                    'target': target, 'result': 'skipped_exists'})
            skipped_exist.append(target)
            continue
        if target in already:
            continue  # schon mal verarbeitet
        ok, reason = can_create_new_strategy(strats)
        if not ok:
            log_throttle_block('strategy_genesis_applier', target)
            skipped_throttle.append(target)
            ledger_rows.append({'ts': now.isoformat(timespec='seconds'),
                                'target': target, 'result': 'skipped_throttle',
                                'reason': reason})
            continue
        strats[target] = _build_strategy(p, now)
        created.append(target)
        ledger_rows.append({'ts': now.isoformat(timespec='seconds'),
                            'target': target, 'result': 'created',
                            'tickers': strats[target]['tickers']})

    # Persist
    if created:
        try:
            from atomic_json import atomic_write_json  # type: ignore
            atomic_write_json(STRATS_FILE, strats)
        except Exception:
            tmp = STRATS_FILE.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(strats, ensure_ascii=False, indent=1),
                           encoding='utf-8')
            tmp.replace(STRATS_FILE)

    if ledger_rows:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, 'a', encoding='utf-8') as f:
            for r in ledger_rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # CEO-Inbox
    if created:
        try:
            from ceo_inbox import write_event
            write_event(
                event_type='strategy.genesis_applied',
                message=(f'{len(created)} Genesis-Strategien aktiviert: '
                         + ', '.join(created)),
                severity='info', category='health', user_pinged=False,
                payload={'created': created, 'skipped_existing': skipped_exist,
                         'skipped_throttle': skipped_throttle},
            )
        except Exception:
            pass

    return {
        'ts': now.isoformat(timespec='seconds'),
        'proposals_seen': len(by_target),
        'created': created,
        'skipped_existing': skipped_exist,
        'skipped_throttle': skipped_throttle,
    }


def main() -> int:
    r = apply()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
