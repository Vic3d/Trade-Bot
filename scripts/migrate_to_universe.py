#!/usr/bin/env python3
"""
Migration Script — Phase 20
============================

Baut die initiale data/universe.json aus allen bestehenden Quellen:

  1. autonomous_scanner.py UNIVERSE (TIER_A/B/C)
  2. news_scraper.py DEFAULT_TICKERS + KEYWORD_TICKER_MAP
  3. data/strategies.json (active thesis tickers)
  4. data/deep_dive_verdicts.json (evaluated tickers)
  5. Letzte 90 Tage Trades aus trading.db

**Seed-Strategie:** konservativ-klein.
  - Ticker mit aktiver These + letztem Signal/Trade in 30 Tagen → status=active
  - Ticker mit aktiver These ohne neueste Signale            → status=watchlist
  - Ticker aus DEFAULT_TICKERS ohne Thesis-Link              → status=dormant
  - Ticker aus Trades in letzten 90d aber ohne aktive These  → status=watchlist

Nach der Migration sind die vier "klebrigen" Tickers weiterhin im System,
aber die automatische Decay-Logik (Phase 20c) kann sie sauber herausfiltern.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from core.universe import (  # noqa: E402
    STATUS_ACTIVE,
    STATUS_WATCHLIST,
    STATUS_DORMANT,
    STATUS_BLOCKED,
    load_universe,
    save_universe,
)


DATA = WS / 'data'
DB = DATA / 'trading.db'


# ── Market-Klassifikation (Mapping) ───────────────────────────────────────────

def classify(ticker: str) -> tuple[str, str]:
    """Returns (market_key, currency)"""
    t = ticker.upper()
    if '.DE' in t or '.F' in t:
        return ('eu_mid', 'EUR')
    if '.PA' in t:
        return ('eu_mid', 'EUR')
    if '.MI' in t or '.AS' in t or '.BR' in t:
        return ('eu_mid', 'EUR')
    if '.L' in t:
        return ('uk', 'GBP')
    if '.OL' in t:
        return ('no_oil', 'NOK')
    if '.CO' in t or '.ST' in t:
        return ('eu_mid', 'EUR')
    # US default
    return ('us_mid', 'USD')


# ── Sektor-Hints aus Thesis-Codes ─────────────────────────────────────────────

SECTOR_HINTS = {
    'PS1': 'Energy/Oil',
    'PS2': 'Shipping/Tankers',
    'PS3': 'Defense',
    'PS4': 'Precious Metals',
    'PS5': 'Materials/Agrar',
    'PS10': 'Copper',
    'PS11': 'Defense EU',
    'PS14': 'Shipping',
    'PS17': 'EU Industrials',
    'PS18': 'EU Auto',
    'PS_Copper': 'Copper/Mining',
    'PS_China': 'China Recovery',
    'PS_Uranium': 'Uranium',
    'PS_AIInfra': 'AI Infrastructure',
    'S3': 'Tech/Semiconductors',
    'S5': 'Rare Earth',
    'S7': 'Pharma',
}


# ── Quellen lesen ─────────────────────────────────────────────────────────────

def read_scanner_universe() -> list[tuple[str, str, str]]:
    """Liest die hardcoded TIER_A/B/C Liste aus autonomous_scanner.py."""
    try:
        from execution.autonomous_scanner import UNIVERSE
    except Exception as e:
        print(f"[migrate] autonomous_scanner import failed: {e}")
        return []
    result = []
    for tier, items in UNIVERSE.items():
        for ticker, thesis, reason in items:
            result.append((ticker, thesis, reason))
    return result


def read_strategies() -> dict[str, list[str]]:
    """Gibt {thesis_code: [tickers]} zurück für active thesen."""
    path = DATA / 'strategies.json'
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[migrate] strategies.json: {e}")
        return {}
    result = {}
    for code, v in data.items():
        if not isinstance(v, dict):
            continue
        status = v.get('status', '')
        if status not in ('active', 'experimental'):
            continue
        tickers = v.get('tickers') or []
        if tickers:
            result[code] = tickers
    return result


def read_news_scraper_defaults() -> tuple[list[str], dict[str, list[str]]]:
    """Liest DEFAULT_TICKERS + KEYWORD_TICKER_MAP aus news_scraper.py (AST parse
    um den Logging-Init zu umgehen)."""
    import ast
    src_path = WS / 'scripts' / 'core' / 'news_scraper.py'
    if not src_path.exists():
        return [], {}
    try:
        tree = ast.parse(src_path.read_text(encoding='utf-8'))
        defaults: list[str] = []
        keyword_map: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id == 'DEFAULT_TICKERS' and isinstance(node.value, ast.List):
                            defaults = [
                                e.value for e in node.value.elts
                                if isinstance(e, ast.Constant) and isinstance(e.value, str)
                            ]
                        elif target.id == 'KEYWORD_TICKER_MAP' and isinstance(node.value, ast.Dict):
                            for k, v in zip(node.value.keys, node.value.values):
                                if isinstance(k, ast.Constant) and isinstance(v, ast.List):
                                    keyword_map[k.value] = [
                                        e.value for e in v.elts
                                        if isinstance(e, ast.Constant)
                                    ]
        return defaults, keyword_map
    except Exception as e:
        print(f"[migrate] news_scraper AST parse failed: {e}")
        return [], {}


def read_recent_trades(days: int = 90) -> set[str]:
    """Tickers aus Trades in letzten N Tagen."""
    if not DB.exists():
        return set()
    try:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM paper_portfolio WHERE date(entry_date) >= ?",
            (cutoff,)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        print(f"[migrate] trades query: {e}")
        return set()


def read_verdicts() -> dict[str, dict]:
    path = DATA / 'deep_dive_verdicts.json'
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


# ── Keyword-Reverse-Map ───────────────────────────────────────────────────────

def build_ticker_keywords(keyword_map: dict[str, list[str]]) -> dict[str, list[str]]:
    """Invertiert keyword→tickers zu ticker→keywords."""
    result: dict[str, list[str]] = {}
    for kw, tickers in keyword_map.items():
        for t in tickers:
            result.setdefault(t, []).append(kw)
    return result


# ── Haupt-Migration ───────────────────────────────────────────────────────────

def migrate(dry_run: bool = False) -> dict:
    print('── Phase 20 Universe Migration ──\n')

    scanner = read_scanner_universe()
    strategies = read_strategies()
    defaults, keyword_map = read_news_scraper_defaults()
    recent_trades = read_recent_trades(90)
    verdicts = read_verdicts()
    ticker_kw = build_ticker_keywords(keyword_map)

    print(f'Scanner UNIVERSE: {len(scanner)} ticker-thesis entries')
    print(f'Active strategies: {len(strategies)} with {sum(len(v) for v in strategies.values())} ticker refs')
    print(f'DEFAULT_TICKERS: {len(defaults)}')
    print(f'Recent trades (90d): {len(recent_trades)}')
    print(f'Deep Dive verdicts: {len(verdicts)}')
    print()

    # Build consolidated map
    universe: dict[str, dict] = {}

    def _ensure(ticker: str, **overrides):
        if ticker not in universe:
            market, currency = classify(ticker)
            universe[ticker] = {
                'name': ticker,
                'sector': '',
                'currency': currency,
                'market': market,
                'status': STATUS_DORMANT,  # default, upgraded below
                'added_at': date.today().isoformat(),
                'last_signal': None,
                'last_trade': None,
                'source': 'migration',
                'news_mentions_30d': 0,
                'linked_thesis': None,
                'dormant_reason': None,
                'dormant_since': None,
                'conviction_history': [],
                'keywords': ticker_kw.get(ticker, []),
                'status_history': [],
            }
        for k, v in overrides.items():
            if v is not None:
                universe[ticker][k] = v

    # 1. Scanner tickers → active (these are victor's validated)
    scanner_theses: dict[str, str] = {}
    for ticker, thesis, reason in scanner:
        sector = SECTOR_HINTS.get(thesis, '')
        scanner_theses[ticker] = thesis
        _ensure(
            ticker,
            sector=sector,
            linked_thesis=thesis,
            source='scanner_universe',
        )

    # 2. Strategy-File tickers → merge / upgrade
    for code, tickers in strategies.items():
        sector = SECTOR_HINTS.get(code, '')
        for t in tickers:
            _ensure(
                t,
                sector=sector,
                linked_thesis=code,
                source='strategies_json',
            )

    # 3. Recent traded tickers → watchlist (at minimum)
    for t in recent_trades:
        _ensure(t, source='recent_trade')
        if t in universe:
            universe[t]['last_trade'] = universe[t].get('last_trade') or date.today().isoformat()

    # 4. Verdict tickers → watchlist
    for t, v in verdicts.items():
        _ensure(t, source='deep_dive_verdict')

    # 5. Default news tickers → watchlist (low priority, can decay)
    for t in defaults:
        _ensure(t, source='news_default')

    # ── Status-Entscheidung ───────────────────────────────────────────────
    # Rules:
    #   - in scanner UNIVERSE AND active thesis AND has recent activity → active
    #   - in scanner UNIVERSE (but no recent activity)                  → watchlist
    #   - in strategies.json active                                     → watchlist
    #   - has verdict KAUFEN                                            → active
    #   - else                                                          → dormant
    today = date.today().isoformat()
    for t, entry in universe.items():
        in_scanner = t in scanner_theses
        in_strategies = any(t in tks for tks in strategies.values())
        has_recent_trade = t in recent_trades
        verdict = verdicts.get(t, {}).get('verdict', '').upper()

        if verdict == 'KAUFEN':
            entry['status'] = STATUS_ACTIVE
        elif in_scanner and (in_strategies or has_recent_trade):
            entry['status'] = STATUS_ACTIVE
        elif in_scanner or in_strategies:
            entry['status'] = STATUS_WATCHLIST
        elif has_recent_trade:
            entry['status'] = STATUS_WATCHLIST
        else:
            entry['status'] = STATUS_DORMANT
            entry['dormant_reason'] = 'migration: no active thesis link'
            entry['dormant_since'] = today

    # Audit entry for all
    for t, entry in universe.items():
        entry['status_history'].append({
            'date': today,
            'from': None,
            'to': entry['status'],
            'reason': f"migration source={entry['source']}",
        })

    # ── Stats ─────────────────────────────────────────────────────────────
    by_status: dict[str, int] = {}
    for v in universe.values():
        s = v['status']
        by_status[s] = by_status.get(s, 0) + 1

    print('── Migration Result ──')
    print(f'Total tickers: {len(universe)}')
    for s, n in sorted(by_status.items()):
        print(f'  {s:12} {n}')
    print()

    # Sample
    active = sorted([t for t, v in universe.items() if v['status'] == STATUS_ACTIVE])
    print(f'Active tickers ({len(active)}):')
    for t in active:
        th = universe[t].get('linked_thesis', '?')
        sec = universe[t].get('sector', '?')
        print(f'  {t:12} thesis={th:15} sector={sec}')
    print()

    if dry_run:
        print('(dry run — not written)')
        return universe

    save_universe(universe)
    print(f'✅ Written to {WS}/data/universe.json')
    return universe


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    migrate(dry_run=args.dry_run)
