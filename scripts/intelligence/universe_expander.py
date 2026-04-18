#!/usr/bin/env python3
"""
Universe Expander — Phase 20d
==============================

News-driven Discovery: sucht nach Tickers die in den letzten Tagen
wiederholt in News auftauchen, aber noch nicht im Universum sind.

**Regel:** Ticker erscheint in ≥ 3 unabhängigen News an ≥ 2 aufeinanderfolgenden
Tagen → Neu-Eintrag als `watchlist`.

**Läuft:** 01:00 CET täglich (vor universe_decay um 02:00)

**Quelle:** `news_events` Tabelle in trading.db
**Output:**
  - Neue Einträge in `universe.json` mit status=watchlist
  - Queue-Event für Digest-Benachrichtigung
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from core.universe import (  # noqa: E402
    STATUS_WATCHLIST,
    add_ticker,
    load_universe,
    record_news_mention,
)

DATA = WS / 'data'
DB = DATA / 'trading.db'


# ── Config ────────────────────────────────────────────────────────────────────

LOOKBACK_DAYS = 7                # Zeitfenster
MIN_MENTIONS = 3                 # Mindestanzahl an News
MIN_DISTINCT_SOURCES = 2         # Mindestens 2 verschiedene Quellen
MIN_DISTINCT_DAYS = 2            # An mindestens 2 verschiedenen Tagen
MAX_NEW_PER_RUN = 10             # Max Neuzugänge pro Lauf (Qualität > Menge)


# ── Ticker-Extraktion aus news_events ─────────────────────────────────────────

def _load_recent_news() -> list[dict]:
    """Lädt News-Events der letzten LOOKBACK_DAYS Tage."""
    if not DB.exists():
        return []
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT headline, source, published_at, tickers
            FROM news_events
            WHERE date(published_at) >= ?
              AND tickers IS NOT NULL
              AND tickers != ''
        """, (cutoff,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f'[expander] db load failed: {e}')
        return []


def _parse_tickers_field(field: str) -> list[str]:
    """news_events.tickers ist ein Komma- oder JSON-Feld."""
    if not field:
        return []
    field = field.strip()
    # JSON list?
    if field.startswith('['):
        try:
            return [t.strip().upper() for t in json.loads(field) if t]
        except Exception:
            pass
    # Comma-separated
    return [t.strip().upper() for t in field.split(',') if t.strip()]


# ── Discovery Logic ───────────────────────────────────────────────────────────

def discover() -> dict:
    print('── Universe Expander Run ──')
    news = _load_recent_news()
    print(f'Loaded {len(news)} news events from last {LOOKBACK_DAYS} days')

    if not news:
        return {'discovered': 0, 'added': 0}

    # ticker → list of (source, published_date)
    hits: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for n in news:
        for t in _parse_tickers_field(n.get('tickers') or ''):
            if not re.match(r'^[A-Z0-9][A-Z0-9.\-]{0,8}$', t):
                continue
            src = n.get('source') or 'unknown'
            day = (n.get('published_at') or '')[:10]
            hits[t].append((src, day))

    print(f'Distinct tickers in news: {len(hits)}')

    u = load_universe()
    known = set(u.keys())

    # Filter: new tickers only + mention threshold
    candidates: list[tuple[str, int, int, int]] = []  # (ticker, mentions, n_sources, n_days)
    for ticker, events in hits.items():
        if ticker in known:
            # Update news_mentions counter for existing tickers
            record_news_mention(ticker, delta=len(events))
            continue
        sources = {e[0] for e in events}
        days = {e[1] for e in events if e[1]}
        if (len(events) >= MIN_MENTIONS
                and len(sources) >= MIN_DISTINCT_SOURCES
                and len(days) >= MIN_DISTINCT_DAYS):
            candidates.append((ticker, len(events), len(sources), len(days)))

    # Sort by mention count (highest first), take top N
    candidates.sort(key=lambda x: (-x[1], -x[2]))
    candidates = candidates[:MAX_NEW_PER_RUN]

    print(f'Qualifying new candidates: {len(candidates)}')

    added: list[dict] = []
    for ticker, mentions, n_sources, n_days in candidates:
        try:
            entry = add_ticker(
                ticker=ticker,
                name=ticker,
                status=STATUS_WATCHLIST,
                source='news_discovery',
            )
            # Track mentions
            record_news_mention(ticker, delta=mentions)
            added.append({
                'ticker': ticker,
                'mentions': mentions,
                'sources': n_sources,
                'days': n_days,
            })
            print(f'  + {ticker:10} mentions={mentions} sources={n_sources} days={n_days}')
        except Exception as e:
            print(f'  ! {ticker} add failed: {e}')

    # Discord queue (optional — goes into evening digest)
    try:
        from discord_queue import queue_event
        if added:
            body = f'Neue Tickers auf Watchlist ({len(added)}):\n'
            for a in added[:10]:
                body += f'  • {a["ticker"]} — {a["mentions"]} News aus {a["sources"]} Quellen\n'
            queue_event(
                priority='info',
                title='Universe Discovery',
                body=body,
                source='universe_expander',
            )
    except Exception as e:
        print(f'[expander] queue event failed: {e}')

    return {
        'discovered': len(candidates),
        'added': len(added),
        'tickers': [a['ticker'] for a in added],
    }


if __name__ == '__main__':
    result = discover()
    print(f'\nResult: {result}')
