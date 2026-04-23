#!/usr/bin/env python3
"""
Universe — Phase 20
====================

Zentrale Source-of-Truth für alle Tickers im TradeMind-System.
Ersetzt hardcoded TIER_A/B/C Listen, DEFAULT_TICKERS, KEYWORD_TICKER_MAP.

**Kern-Idee:** Jeder Ticker hat einen Lifecycle:

    watchlist → active → dormant → (active) → archived

**Status-Bedeutung:**
  - active:     wird täglich gescannt, Entries erlaubt
  - watchlist:  beobachtet (News-Monitoring), Entry nur nach Deep Dive
  - dormant:    temporär inaktiv, wird nicht mehr gescannt, kann reaktiviert werden
  - blocked:    permanent aus (politisches Risiko, Bilanzbetrug, etc.)
  - archived:   historisch — nicht mehr im Scope, aber im System als Referenz

**Datei:** data/universe.json
**Schema:**
    {
      "NVDA": {
        "name": "NVIDIA Corporation",
        "sector": "AI/Semiconductors",
        "currency": "USD",
        "market": "us_large",
        "status": "active",
        "added_at": "2026-01-15",
        "last_signal": "2026-04-14",
        "last_trade": "2026-03-22",
        "source": "news|thesis|manual|discovery",
        "news_mentions_30d": 42,
        "linked_thesis": "PS_AI",
        "dormant_reason": null,
        "dormant_since": null,
        "conviction_history": [[date, score], ...],
        "keywords": ["KI", "Halbleiter", "AI Chips"]
      },
      ...
    }
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
UNIVERSE_FILE = WS / 'data' / 'universe.json'

# Status-Konstanten
STATUS_ACTIVE = 'active'
STATUS_WATCHLIST = 'watchlist'
STATUS_DORMANT = 'dormant'
STATUS_BLOCKED = 'blocked'
STATUS_ARCHIVED = 'archived'

SCANNABLE_STATUSES = {STATUS_ACTIVE, STATUS_WATCHLIST}


# ── Low-Level I/O ─────────────────────────────────────────────────────────────

def load_universe() -> dict:
    """Lädt das gesamte Universum. Leeres Dict wenn Datei fehlt.

    Bugfix 2026-04-23: filtert Metadaten-Keys (`_info`, `_count`, `_updated`)
    raus damit Aufrufer die nur Ticker→dict-Eintraege erwarten nicht ueber
    'str/int has no attribute get' crashen (siehe autonomous_scanner.py:1002).
    """
    if not UNIVERSE_FILE.exists():
        return {}
    try:
        raw = json.loads(UNIVERSE_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[universe] load failed: {e}")
        return {}
    # Nur dict-Werte zurueckgeben (Ticker-Eintraege). Underscore-Keys
    # bleiben als Metadaten in der Datei, aber nicht in der API.
    return {k: v for k, v in raw.items()
            if isinstance(v, dict) and not k.startswith('_')}


def save_universe(u: dict) -> None:
    """Speichert das Universum atomar (tmp + rename)."""
    UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = UNIVERSE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(u, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(UNIVERSE_FILE)


# ── Ticker-Level Queries ──────────────────────────────────────────────────────

def get_ticker(ticker: str) -> dict | None:
    """Holt einen einzelnen Ticker-Eintrag."""
    u = load_universe()
    return u.get(ticker)


def ticker_exists(ticker: str) -> bool:
    return ticker in load_universe()


def get_tickers_by_status(
    statuses: Iterable[str] = (STATUS_ACTIVE,),
) -> list[str]:
    """Gibt alle Tickers mit einem der angegebenen Status zurück."""
    u = load_universe()
    statuses = set(statuses)
    return sorted([t for t, v in u.items() if v.get('status') in statuses])


def get_active_tickers() -> list[str]:
    """Shortcut: alle aktiven Tickers (für Scanner)."""
    return get_tickers_by_status([STATUS_ACTIVE])


def get_scannable_tickers() -> list[str]:
    """Alle Tickers die gescannt werden dürfen (active + watchlist)."""
    return get_tickers_by_status(SCANNABLE_STATUSES)


def get_tickers_by_sector(sector: str) -> list[str]:
    u = load_universe()
    return sorted([
        t for t, v in u.items()
        if v.get('sector', '').lower() == sector.lower()
        and v.get('status') in SCANNABLE_STATUSES
    ])


# ── Mutations ─────────────────────────────────────────────────────────────────

def add_ticker(
    ticker: str,
    name: str = '',
    sector: str = '',
    currency: str = 'EUR',
    market: str = '',
    status: str = STATUS_WATCHLIST,
    source: str = 'manual',
    linked_thesis: str | None = None,
    keywords: list[str] | None = None,
) -> dict:
    """Fügt einen neuen Ticker hinzu oder aktualisiert einen bestehenden."""
    u = load_universe()
    today = date.today().isoformat()

    if ticker in u:
        # Merge: existing takes precedence for stable fields
        entry = u[ticker]
        if name and not entry.get('name'):
            entry['name'] = name
        if sector and not entry.get('sector'):
            entry['sector'] = sector
        if keywords:
            existing_kw = set(entry.get('keywords') or [])
            existing_kw.update(keywords)
            entry['keywords'] = sorted(existing_kw)
    else:
        entry = {
            'name': name or ticker,
            'sector': sector,
            'currency': currency,
            'market': market,
            'status': status,
            'added_at': today,
            'last_signal': None,
            'last_trade': None,
            'source': source,
            'news_mentions_30d': 0,
            'linked_thesis': linked_thesis,
            'dormant_reason': None,
            'dormant_since': None,
            'conviction_history': [],
            'keywords': keywords or [],
        }
        u[ticker] = entry

    save_universe(u)
    return entry


def set_status(ticker: str, status: str, reason: str | None = None) -> bool:
    """Setzt den Status eines Tickers mit Audit-Trail."""
    u = load_universe()
    if ticker not in u:
        return False

    old_status = u[ticker].get('status')
    u[ticker]['status'] = status
    today = date.today().isoformat()

    if status == STATUS_DORMANT:
        u[ticker]['dormant_reason'] = reason or 'unspecified'
        u[ticker]['dormant_since'] = today
    elif status == STATUS_ACTIVE:
        u[ticker]['dormant_reason'] = None
        u[ticker]['dormant_since'] = None

    # Audit log
    history = u[ticker].setdefault('status_history', [])
    history.append({
        'date': today,
        'from': old_status,
        'to': status,
        'reason': reason,
    })
    # Keep last 20 only
    u[ticker]['status_history'] = history[-20:]

    save_universe(u)
    return True


def mark_dormant(ticker: str, reason: str) -> bool:
    return set_status(ticker, STATUS_DORMANT, reason)


def mark_active(ticker: str, reason: str = 'reactivated') -> bool:
    return set_status(ticker, STATUS_ACTIVE, reason)


def mark_blocked(ticker: str, reason: str) -> bool:
    return set_status(ticker, STATUS_BLOCKED, reason)


def record_signal(ticker: str, conviction: float) -> None:
    """Trackt ein Scan-Signal (Conviction-Score Update)."""
    u = load_universe()
    if ticker not in u:
        return
    today = date.today().isoformat()
    u[ticker]['last_signal'] = today
    hist = u[ticker].setdefault('conviction_history', [])
    hist.append([today, round(conviction, 1)])
    u[ticker]['conviction_history'] = hist[-50:]  # last 50 signals
    save_universe(u)


def record_trade(ticker: str) -> None:
    """Trackt einen ausgeführten Trade."""
    u = load_universe()
    if ticker not in u:
        return
    u[ticker]['last_trade'] = date.today().isoformat()
    save_universe(u)


def record_news_mention(ticker: str, delta: int = 1) -> None:
    """Inkrementiert den 30d-News-Counter."""
    u = load_universe()
    if ticker not in u:
        return
    u[ticker]['news_mentions_30d'] = (u[ticker].get('news_mentions_30d') or 0) + delta
    save_universe(u)


# ── Keyword-Map (ersetzt hardcoded KEYWORD_TICKER_MAP) ────────────────────────

def get_keyword_map() -> dict[str, list[str]]:
    """
    Baut einen Keyword→Tickers-Mapping dynamisch aus dem Universum.
    Ersetzt die hardcoded KEYWORD_TICKER_MAP in news_scraper.py.
    """
    u = load_universe()
    keyword_map: dict[str, list[str]] = {}
    for ticker, meta in u.items():
        if meta.get('status') not in SCANNABLE_STATUSES:
            continue
        for kw in (meta.get('keywords') or []):
            kw_lower = kw.lower()
            keyword_map.setdefault(kw_lower, []).append(ticker)
    return keyword_map


# ── Bulk-Queries für Reports ──────────────────────────────────────────────────

def stats() -> dict:
    """Zählt Tickers pro Status + Sektor für Reports."""
    u = load_universe()
    by_status: dict[str, int] = {}
    by_sector: dict[str, int] = {}
    for t, v in u.items():
        s = v.get('status', 'unknown')
        by_status[s] = by_status.get(s, 0) + 1
        sec = v.get('sector', 'unknown')
        by_sector[sec] = by_sector.get(sec, 0) + 1
    return {
        'total': len(u),
        'by_status': by_status,
        'by_sector': dict(sorted(by_sector.items(), key=lambda x: -x[1])),
    }


def stale_candidates(days: int = 30) -> list[tuple[str, int]]:
    """Tickers die seit N Tagen kein Signal produziert haben (Kandidaten für dormant)."""
    u = load_universe()
    today = date.today()
    result = []
    for t, v in u.items():
        if v.get('status') != STATUS_ACTIVE:
            continue
        last = v.get('last_signal')
        if not last:
            days_since = (today - datetime.fromisoformat(v.get('added_at', today.isoformat())).date()).days
        else:
            days_since = (today - datetime.fromisoformat(last).date()).days
        if days_since >= days:
            result.append((t, days_since))
    return sorted(result, key=lambda x: -x[1])


# ── Self-test ─────────────────────────────────────────────────────────────────

def _self_test():
    print('── Universe Self-Test ──')
    print(f'Universe file: {UNIVERSE_FILE}')
    print(f'Exists: {UNIVERSE_FILE.exists()}')
    if UNIVERSE_FILE.exists():
        s = stats()
        print(f'Total tickers: {s["total"]}')
        print(f'By status: {s["by_status"]}')
        print(f'Top sectors: {list(s["by_sector"].items())[:5]}')
        active = get_active_tickers()
        print(f'Active ({len(active)}): {active[:15]}...' if len(active) > 15 else f'Active ({len(active)}): {active}')
    else:
        print('No universe file yet — run migrate_to_universe.py first.')


if __name__ == '__main__':
    _self_test()
