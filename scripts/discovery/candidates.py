"""Shared helpers for candidate_tickers.json.

Schema pro Ticker:
{
  "discovered_at": ISO timestamp (erster Treffer),
  "last_seen_at":  ISO timestamp (letzter Source-Hit),
  "sources": [{"type": str, "detail": str, "score": float, "ts": ISO}, ...],
  "priority": float (aggregiert aus sources),
  "status": "pending" | "analyzing" | "promoted" | "rejected" | "expired"
}
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
CANDIDATES_PATH = WS / 'data' / 'candidate_tickers.json'
STRATS_PATH = WS / 'data' / 'strategies.json'
UNIVERSE_HARDCODED_PATH = WS / 'scripts' / 'execution' / 'autonomous_scanner.py'

MAX_AGE_DAYS = 7
VALID_TICKER_RE = re.compile(r'^[A-Z0-9][A-Z0-9\.\-]{0,9}$')


def load_candidates() -> dict:
    if not CANDIDATES_PATH.exists():
        return {}
    try:
        return json.loads(CANDIDATES_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_candidates(data: dict) -> None:
    try:
        from atomic_json import atomic_write_json
        atomic_write_json(CANDIDATES_PATH, data)
    except Exception:
        CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        CANDIDATES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_known_tickers() -> set[str]:
    """Alle Tickers die bereits in UNIVERSE oder strategies.json sind."""
    known: set[str] = set()
    # UNIVERSE aus autonomous_scanner.py parsen
    try:
        if UNIVERSE_HARDCODED_PATH.exists():
            text = UNIVERSE_HARDCODED_PATH.read_text(encoding='utf-8', errors='ignore')
            # Match: ('TICKER',  'STRAT',  'desc...
            for m in re.finditer(r"\(\s*'([A-Z0-9\.\-]+)'\s*,", text):
                known.add(m.group(1).upper())
    except Exception:
        pass
    # strategies.json Tickers
    try:
        if STRATS_PATH.exists():
            strats = json.loads(STRATS_PATH.read_text(encoding='utf-8'))
            if isinstance(strats, dict):
                for sid, s in strats.items():
                    if isinstance(s, dict):
                        for t in s.get('tickers', []):
                            known.add(str(t).upper())
    except Exception:
        pass
    return known


def is_new_ticker(ticker: str) -> bool:
    """True wenn Ticker noch nicht bekannt ist."""
    t = ticker.upper()
    if not VALID_TICKER_RE.match(t):
        return False
    return t not in get_known_tickers()


def add_candidate(
    ticker: str,
    source_type: str,
    detail: str,
    score: float = 0.5,
) -> bool:
    """Fuegt einen Treffer zu candidate_tickers.json hinzu.
    Returns True wenn neu aufgenommen oder Source ergaenzt wurde.
    """
    t = ticker.upper().strip()
    if not VALID_TICKER_RE.match(t):
        return False
    if not is_new_ticker(t):
        return False  # bereits bekannt in UNIVERSE/strategies

    data = load_candidates()
    now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds')

    entry = data.get(t)
    if not entry:
        entry = {
            'discovered_at': now_iso,
            'last_seen_at': now_iso,
            'sources': [],
            'priority': 0.0,
            'status': 'pending',
        }
        data[t] = entry

    # Duplikate der gleichen Source gleichen Details vermeiden (letzte 24h)
    for s in entry['sources'][-10:]:
        if s.get('type') == source_type and s.get('detail') == detail:
            try:
                prev = datetime.fromisoformat(s.get('ts', '').replace('Z', '+00:00'))
                if (datetime.now(timezone.utc) - prev).total_seconds() < 86400:
                    return False
            except Exception:
                pass

    entry['sources'].append({
        'type': source_type,
        'detail': detail[:200],
        'score': round(float(score), 2),
        'ts': now_iso,
    })
    entry['last_seen_at'] = now_iso
    # Priority = max(score) + 0.1 fuer jede weitere Source-Art (bis +0.3)
    scores = [s.get('score', 0) for s in entry['sources']]
    types = {s.get('type') for s in entry['sources']}
    entry['priority'] = round(min(1.0, max(scores) + 0.1 * (len(types) - 1)), 2)
    save_candidates(data)
    return True


def prune_expired() -> int:
    """Entferne Kandidaten aelter als MAX_AGE_DAYS. Returns Anzahl entfernt."""
    data = load_candidates()
    if not data:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    removed = 0
    for t in list(data.keys()):
        entry = data[t]
        if entry.get('status') in ('promoted', 'rejected', 'expired'):
            # Behalte Rejected/Promoted fuer 7 Tage als Audit
            try:
                last = datetime.fromisoformat(entry.get('last_seen_at', '').replace('Z', '+00:00'))
                if last < cutoff:
                    del data[t]
                    removed += 1
            except Exception:
                del data[t]
                removed += 1
            continue
        try:
            disc = datetime.fromisoformat(entry.get('discovered_at', '').replace('Z', '+00:00'))
            if disc < cutoff:
                entry['status'] = 'expired'
                removed += 1
        except Exception:
            entry['status'] = 'expired'
            removed += 1
    save_candidates(data)
    return removed


def mark_status(ticker: str, status: str, note: str | None = None) -> None:
    data = load_candidates()
    entry = data.get(ticker.upper())
    if not entry:
        return
    entry['status'] = status
    if note:
        entry['note'] = note[:300]
    entry['status_updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    save_candidates(data)


def get_pending_candidates(max_count: int = 10) -> list[str]:
    """Sortiert nach priority DESC, nur status=pending."""
    data = load_candidates()
    pending = [
        (t, e.get('priority', 0.0))
        for t, e in data.items()
        if e.get('status') == 'pending'
    ]
    pending.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in pending[:max_count]]
