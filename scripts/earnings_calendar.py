#!/usr/bin/env python3
"""
Earnings Calendar — Phase 25
=============================
Cached Earnings-Termine pro Ticker via yfinance.

Output: data/earnings_calendar.json
{
  "AAPL": {"next_earnings": "2026-04-30", "fetched_at": "..."},
  ...
}

Hook: entry_gate.py prüft `is_earnings_blackout(ticker)` —
  blockt Entry wenn Earnings in <3 Tagen, ausser wenn die Strategie-Genesis
  Earnings explizit als Katalysator nennt.

Refresh: einmal pro Woche (Mo 06:00) für alle Portfolio + Watchlist Tickers.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB = DATA / 'trading.db'
OUT = DATA / 'earnings_calendar.json'
CACHE_TTL_DAYS = 7  # Refresh wöchentlich
BLACKOUT_DAYS = 3   # Block bei Earnings in <3 Tagen


def _load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f'[earnings_calendar] save fail: {e}')


def _fetch_next_earnings(ticker: str) -> str | None:
    """Liefert YYYY-MM-DD oder None."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
        # yf 0.2+ returns dict, älter pandas DataFrame
        if isinstance(cal, dict):
            ed = cal.get('Earnings Date')
            if isinstance(ed, list) and ed:
                return str(ed[0])[:10]
            if ed:
                return str(ed)[:10]
        else:
            try:
                ed = cal.loc['Earnings Date'][0]
                return str(ed)[:10]
            except Exception:
                pass
    except Exception:
        pass
    return None


def _collect_active_tickers() -> set[str]:
    out: set[str] = set()
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT DISTINCT ticker FROM trades WHERE status='OPEN' "
            "UNION SELECT DISTINCT ticker FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        for r in rows:
            if r[0]:
                out.add(str(r[0]).upper())
        c.close()
    except Exception:
        pass
    try:
        s_path = DATA / 'strategies.json'
        if s_path.exists():
            sd = json.loads(s_path.read_text(encoding='utf-8'))
            for sid, cfg in sd.items():
                if isinstance(cfg, dict):
                    for t in cfg.get('tickers', []) or [cfg.get('ticker')]:
                        if t:
                            out.add(str(t).upper())
    except Exception:
        pass
    return out


def refresh(tickers: list[str] | None = None) -> dict:
    cache = _load()
    if tickers is None:
        tickers = sorted(_collect_active_tickers())
    now = datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)).isoformat()

    refreshed = 0
    skipped = 0
    for tk in tickers:
        ent = cache.get(tk, {})
        if ent.get('fetched_at', '') > cutoff:
            skipped += 1
            continue
        nx = _fetch_next_earnings(tk)
        cache[tk] = {'next_earnings': nx, 'fetched_at': now}
        refreshed += 1
        if refreshed % 10 == 0:
            print(f'  ... {refreshed} fetched')

    _save(cache)
    return {'refreshed': refreshed, 'skipped': skipped, 'total': len(cache)}


def is_earnings_blackout(ticker: str, days: int = BLACKOUT_DAYS) -> tuple[bool, str]:
    """Returns (blocked, reason). True wenn Earnings in <days Tagen."""
    try:
        cache = _load()
        ent = cache.get(ticker.upper(), {})
        nx = ent.get('next_earnings')
        if not nx:
            return False, ''
        nx_dt = datetime.strptime(nx[:10], '%Y-%m-%d')
        delta = (nx_dt - datetime.now()).days
        if 0 <= delta <= days:
            return True, f'Earnings in {delta}d ({nx})'
    except Exception:
        pass
    return False, ''


def main():
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print(f"=== Earnings Calendar Refresh ===")
    r = refresh(tickers)
    print(f"Refreshed: {r['refreshed']} | Skipped (cache): {r['skipped']} | Total: {r['total']}")

    cache = _load()
    upcoming = []
    for tk, ent in cache.items():
        nx = ent.get('next_earnings')
        if not nx:
            continue
        try:
            d = (datetime.strptime(nx[:10], '%Y-%m-%d') - datetime.now()).days
            if 0 <= d <= 14:
                upcoming.append((d, tk, nx))
        except Exception:
            pass
    upcoming.sort()
    if upcoming:
        print(f"\n📅 Earnings in den nächsten 14 Tagen:")
        for d, tk, nx in upcoming:
            flag = '🚨' if d <= BLACKOUT_DAYS else '  '
            print(f"  {flag} {tk:6}  in {d:2}d  ({nx})")


if __name__ == '__main__':
    main()
