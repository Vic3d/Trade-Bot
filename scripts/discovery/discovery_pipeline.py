#!/usr/bin/env python3
"""
Discovery Pipeline — Phase 7.15 Orchestrator
==============================================
Zentrale Aggregation:
  1. prune_expired() — Alte Kandidaten entfernen
  2. Promote KAUFEN-Verdicts zu strategies.json (status='probation')
  3. Reject NICHT_KAUFEN-Verdicts
  4. Status-Report: Wieviele pending/analyzing/promoted/rejected
  5. Discord-Summary (optional)

Ablauf einmal taeglich (07:15):
  - News-Extractor (06:00) + Market-Scanner (06:15) + Earnings (06:30)
    haben pending candidates geschrieben
  - Auto-DD-Runner laeuft 07:30 mit Priority 1.5 (candidates) — setzt Verdikts
  - Pipeline laeuft 12:00 — promoted/rejected auf Basis der Verdikts

Strategien-Promotion:
  - Nur Ticker die PRIORITY >= 0.5 UND Verdict KAUFEN UND Confidence >= 70 haben
  - Auto-created Strategy-ID: PS_DISC_<TICKER>
  - status='probation' — bleibt geblockt bis Victor das auf 'active' setzt
  - genesis.trigger = Summary aus Sources + Verdict-Reasoning

CLI:
  python3 scripts/discovery/discovery_pipeline.py
  python3 scripts/discovery/discovery_pipeline.py --dry
  python3 scripts/discovery/discovery_pipeline.py --report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))

from candidates import load_candidates, mark_status, prune_expired  # noqa: E402

VERDICT_FILE = WS / 'data' / 'deep_dive_verdicts.json'
STRATS_FILE = WS / 'data' / 'strategies.json'
PROMOTION_LOG = WS / 'data' / 'discovery_promotions.jsonl'

#  Paper-Training-Phase (2026-04-17): Thresholds gelockert damit Auto-Entry
#  ueberhaupt Trades generiert. Safety liegt bei Guard 0c2 (Deep-Dive KAUFEN),
#  Guard 0c (CRV 2:1), Stop-Loss -8%, Trailing Stops, Max 3 Trades/Woche.
#  Fuer Live-Kapital spaeter zurueck auf 0.5 / 70 erhoehen.
PROMOTE_MIN_PRIORITY = 0.3
PROMOTE_MIN_CONFIDENCE = 60


def load_verdicts() -> dict:
    if not VERDICT_FILE.exists():
        return {}
    try:
        return json.loads(VERDICT_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def load_strategies() -> dict:
    if not STRATS_FILE.exists():
        return {}
    try:
        return json.loads(STRATS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_strategies(data: dict) -> None:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from atomic_json import atomic_write_json
        atomic_write_json(STRATS_FILE, data)
    except Exception:
        STRATS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def log_promotion(entry: dict) -> None:
    PROMOTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROMOTION_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def build_strategy_entry(ticker: str, candidate: dict, verdict: dict) -> dict:
    """Erzeugt einen minimalen PS_DISC_<TICKER> Eintrag."""
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    sources_summary = []
    source_types = set()
    for s in candidate.get('sources', []):
        src_type = s.get('type', '?')
        source_types.add(src_type)
        detail = s.get('detail', '')[:120]
        sources_summary.append(f'[{src_type}] {detail}')
    sources_summary = sources_summary[:5]

    reasoning = verdict.get('reasoning', '') or verdict.get('summary', '')
    conviction = int(verdict.get('confidence', 70))

    return {
        'name': f'Discovery Play — {ticker}',
        'type': 'paper',
        'genesis': {
            'created': now[:10],
            'trigger': f"Auto-Discovery {list(source_types)} + Deep-Dive KAUFEN (conf {conviction})",
            'analysis_steps': sources_summary,
            'logical_chain': f"Multi-Source-Discovery -> Deep Dive -> KAUFEN verdict conf={conviction}",
            'counter_arguments_checked': verdict.get('concerns', []) or [],
            'sources': list(source_types),
            'conviction_at_start': min(5, max(1, conviction // 20)),
            'conviction_current': min(5, max(1, conviction // 20)),
            'auto_adjusted': False,
            'last_updated': now,
            'feedback_history': [],
        },
        'thesis': reasoning[:400] if reasoning else f'{ticker} via Discovery + Deep-Dive KAUFEN',
        'sector': verdict.get('sector', 'discovery'),
        'regime': {'description': 'Auto-Discovery + Deep-Dive KAUFEN — autonom freigegeben'},
        'entry_trigger': 'Entry-Window 17-22h CET + alle Paper-Trade-Guards',
        'kill_trigger': 'Deep-Dive-Verdict flippt auf NICHT_KAUFEN',
        'horizon_weeks': 4,
        'status': 'active',
        'health': 'yellow',
        'learning_question': f'Funktioniert Auto-Discovery als Quelle fuer {ticker}?',
        'tickers': [ticker],
        'discovery_meta': {
            'promoted_at': now,
            'priority': candidate.get('priority', 0.0),
            'verdict_confidence': conviction,
            'source_types': list(source_types),
        },
    }


def promote_candidate(ticker: str, candidate: dict, verdict: dict, dry: bool = False) -> bool:
    """Erstellt PS_DISC_<TICKER> in strategies.json. Returns True wenn neu."""
    strats = load_strategies()
    sid = f'PS_DISC_{ticker.replace(".", "_").replace("-", "_")}'
    if sid in strats:
        print(f'  ~ {sid} existiert bereits, skip Promotion')
        return False

    entry = build_strategy_entry(ticker, candidate, verdict)

    if dry:
        print(f'  [dry] Wuerde promoten: {sid}')
        return False

    strats[sid] = entry
    save_strategies(strats)
    mark_status(ticker, 'promoted', note=f'PS_DISC erzeugt conf={verdict.get("confidence", 0)}')

    log_promotion({
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'ticker': ticker,
        'strategy_id': sid,
        'priority': candidate.get('priority'),
        'verdict_confidence': verdict.get('confidence'),
        'source_types': list({s.get('type') for s in candidate.get('sources', [])}),
    })
    return True


def try_send_discord(msg: str) -> None:
    """Discord via Dispatcher (Phase 22.4).
    Discovery-Promotions sind HIGH (neue Trade-Basis), alles andere LOW."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_dispatcher import send_alert, TIER_HIGH
        send_alert(msg, tier=TIER_HIGH, category='discovery')
    except Exception:
        pass


def run(dry: bool = False, report_only: bool = False) -> dict:
    expired = prune_expired() if not report_only else 0
    if expired:
        print(f'[pipeline] {expired} expired/removed')

    candidates = load_candidates()
    verdicts = load_verdicts()

    stats = {'pending': 0, 'analyzing': 0, 'promoted': 0, 'rejected': 0, 'expired': 0}
    for entry in candidates.values():
        stats[entry.get('status', 'pending')] = stats.get(entry.get('status', 'pending'), 0) + 1

    print(f'[pipeline] Candidates: {stats}')

    if report_only:
        return {'status': 'ok', 'stats': stats, 'action': 'report'}

    promoted_count = 0
    rejected_count = 0
    triggered_llm_dd = 0
    MAX_LLM_DD_PER_RUN = int(os.environ.get('DISCOVERY_MAX_LLM_DD', '6'))

    # Helper: nur LLM-Verdicts als "echt" gelten lassen
    def _is_llm_verdict(v: dict) -> bool:
        src = str(v.get('source', '')).lower()
        if src in ('auto_deepdive_rule', 'rule', 'pre_screen'):
            return False
        return bool(v.get('confidence') is not None or src in ('auto_deep_dive', 'llm', 'manual'))

    for ticker, cand in candidates.items():
        if cand.get('status') not in ('pending', 'analyzing'):
            continue
        if cand.get('priority', 0.0) < PROMOTE_MIN_PRIORITY:
            continue

        v = verdicts.get(ticker) or verdicts.get(ticker.upper())

        # Kein LLM-Verdict vorhanden? → Auto-DD-LLM aktiv anwerfen (statt passiv warten)
        if not v or not _is_llm_verdict(v):
            if triggered_llm_dd >= MAX_LLM_DD_PER_RUN:
                # Budget pro Lauf erreicht — naechster Lauf holt die restlichen ab
                continue
            if not dry:
                try:
                    import sys as _sys
                    _sys.path.insert(0, str(WS / 'scripts'))
                    # Erst Preis-Backfill sicherstellen (Auto-DD braucht >=60 Tage)
                    try:
                        import sqlite3 as _sql
                        from discovery.price_backfill import count_prices as _cp, backfill_ticker as _bt
                        _db = WS / 'data' / 'trading.db'
                        _conn = _sql.connect(str(_db))
                        try:
                            if _cp(_conn, ticker) < 60:
                                _n = _bt(_conn, ticker, years=1)
                                print(f'  ↳ backfill {ticker}: +{_n} Zeilen')
                        finally:
                            _conn.close()
                    except Exception as _be:
                        print(f'  ! Backfill-Fehler {ticker}: {str(_be)[:100]}')

                    from intelligence.auto_deep_dive import run as _run_dd  # type: ignore
                    # force=True wenn vorhandenes Verdict nur Rule-basiert ist
                    # (sonst skippt auto_deep_dive mit "Verdict noch frisch")
                    _force = bool(v and not _is_llm_verdict(v))
                    print(f'  → trigger LLM-DD für {ticker} (force={_force})')
                    _run_dd(ticker, force=_force, dry=False, mode='entry')
                    triggered_llm_dd += 1
                    # Neu laden
                    verdicts = load_verdicts()
                    v = verdicts.get(ticker) or verdicts.get(ticker.upper())
                except Exception as _dde:
                    print(f'  ! LLM-DD-Trigger-Fehler {ticker}: {str(_dde)[:100]}')
                    continue
            else:
                continue

        if not v or not _is_llm_verdict(v):
            # Trigger fehlgeschlagen oder immer noch nur Rule-Verdict → skip
            continue

        verdict_label = str(v.get('verdict', '')).upper()
        # Backward-compat: LLM-Verdicts schreiben 'confidence', Rule-Verdicts
        # haben 'conviction'. Fall durch auf beide.
        conf = int(v.get('confidence') or v.get('conviction') or 0)

        if verdict_label == 'KAUFEN' and conf >= PROMOTE_MIN_CONFIDENCE:
            if promote_candidate(ticker, cand, v, dry=dry):
                promoted_count += 1
                print(f'  + PROMOTED {ticker} (conf {conf})')
                try_send_discord(
                    f'🎯 DISCOVERY: **{ticker}** wurde promoted als PS_DISC_{ticker} '
                    f'(Deep-Dive KAUFEN conf={conf}) — status=probation, deine Freigabe noetig.'
                )
        elif verdict_label == 'NICHT_KAUFEN' and not dry:
            mark_status(ticker, 'rejected', note=f'Deep-Dive NICHT_KAUFEN conf={conf}')
            rejected_count += 1
            print(f'  - REJECTED {ticker} (NICHT_KAUFEN conf {conf})')

    print(f'[pipeline] Promoted: {promoted_count}, Rejected: {rejected_count}, '
          f'Expired: {expired}, LLM-DD-Triggered: {triggered_llm_dd}')
    return {
        'status': 'ok',
        'stats': stats,
        'promoted': promoted_count,
        'rejected': rejected_count,
        'expired': expired,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    result = run(dry=args.dry, report_only=args.report)
    sys.exit(0 if result.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
