#!/usr/bin/env python3
"""
Catalyst Calendar — Phase 22
=============================
Aggregiert benannte Katalysator-Events in die naechsten 30 Tage aus mehreren Quellen:

  1. Finnhub Earnings-Calendar (API-Key in env FINNHUB_API_KEY)
  2. Trading Economics Macro-Calendar (free-tier scrape, JSON feed)
  3. Hartcodierte Geo/OPEC/FOMC-Events (gepflegt in CATALYST_SEED)
  4. yfinance .calendar Fallback fuer aktive Portfolio-Ticker

Schreibt:
  - SQLite-Tabelle `catalysts`
  - data/catalyst_calendar.json (fuer Scenario Mapper & Morgen-Briefing)

Aufgerufen:
  - Scheduler: 06:20 (vor Scenario Mapper 06:30)
  - CLI: python3 scripts/catalyst_calendar.py [--days 30]

Schema `catalysts`:
  id TEXT PRIMARY KEY           -- hash(date|type|ticker|desc)
  date TEXT                     -- YYYY-MM-DD
  type TEXT                     -- FOMC | EARNINGS | FDA | OPEC | ELECTION | GEO | ECB | CPI
  ticker TEXT                   -- AAPL (oder null bei Makro)
  sector TEXT                   -- Tech | Oil | Defense | None
  description TEXT
  consensus_expectation TEXT    -- 'EPS 3.40 expected'
  importance INTEGER            -- 1=low, 5=critical
  source TEXT                   -- finnhub | trading_economics | manual | yfinance
  last_updated TEXT
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'catalyst_calendar.json'

sys.path.insert(0, str(WS / 'scripts'))


# ────────────────────────────────────────────────────────────────────────────
# Hartcodierter Seed — pflegt Fed/ECB/OPEC/Elections 2026
# ────────────────────────────────────────────────────────────────────────────

# Form: (YYYY-MM-DD, type, ticker, sector, description, importance)
CATALYST_SEED_2026 = [
    # FOMC-Sitzungen 2026 (FED)
    ('2026-04-22', 'FOMC', None, 'Macro', 'FOMC-Sitzung + Rate Decision', 5),
    ('2026-06-10', 'FOMC', None, 'Macro', 'FOMC-Sitzung', 5),
    ('2026-07-29', 'FOMC', None, 'Macro', 'FOMC-Sitzung', 5),
    ('2026-09-16', 'FOMC', None, 'Macro', 'FOMC-Sitzung', 5),
    ('2026-11-04', 'FOMC', None, 'Macro', 'FOMC-Sitzung', 5),
    ('2026-12-16', 'FOMC', None, 'Macro', 'FOMC-Sitzung', 5),
    # EZB-Sitzungen
    ('2026-04-30', 'ECB', None, 'Macro', 'EZB Zinsentscheid', 5),
    ('2026-06-11', 'ECB', None, 'Macro', 'EZB Zinsentscheid', 5),
    ('2026-07-23', 'ECB', None, 'Macro', 'EZB Zinsentscheid', 5),
    # OPEC+ Meetings (geschaetzt, monatlich)
    ('2026-04-28', 'OPEC', None, 'Energy', 'OPEC+ JMMC Meeting', 4),
    ('2026-05-31', 'OPEC', None, 'Energy', 'OPEC+ Meeting', 4),
    ('2026-06-30', 'OPEC', None, 'Energy', 'OPEC+ Meeting', 4),
    # US CPI (mid-month)
    ('2026-05-13', 'CPI', None, 'Macro', 'US CPI April', 4),
    ('2026-06-11', 'CPI', None, 'Macro', 'US CPI May', 4),
    # Geopolitische Deadlines (manuell gepflegt)
    ('2026-04-25', 'GEO', None, 'Geo', 'Iran-Deal Deadline (geschaetzt, Trump)', 5),
    ('2026-05-09', 'GEO', None, 'Geo', 'Taiwan Election Aftermath', 3),
]


# ────────────────────────────────────────────────────────────────────────────
# SQLite-Schema
# ────────────────────────────────────────────────────────────────────────────

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS catalysts (
        id TEXT PRIMARY KEY,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        ticker TEXT,
        sector TEXT,
        description TEXT,
        consensus_expectation TEXT,
        importance INTEGER DEFAULT 3,
        source TEXT,
        last_updated TEXT
      );
      CREATE INDEX IF NOT EXISTS idx_catalysts_date ON catalysts(date);
      CREATE INDEX IF NOT EXISTS idx_catalysts_ticker ON catalysts(ticker);
    """)
    conn.commit()


def make_id(date: str, ctype: str, ticker: str | None, desc: str) -> str:
    key = f"{date}|{ctype}|{ticker or '_'}|{desc[:60]}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO catalysts
           (id, date, type, ticker, sector, description, consensus_expectation,
            importance, source, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row['id'], row['date'], row['type'], row.get('ticker'),
            row.get('sector'), row.get('description'), row.get('consensus_expectation'),
            row.get('importance', 3), row.get('source', 'manual'),
            datetime.now(timezone.utc).isoformat(timespec='seconds'),
        ),
    )


# ────────────────────────────────────────────────────────────────────────────
# Source 1: Finnhub Earnings
# ────────────────────────────────────────────────────────────────────────────

def fetch_finnhub_earnings(days: int = 30) -> list[dict]:
    api_key = os.getenv('FINNHUB_API_KEY')
    if not api_key:
        print('[catalyst] Finnhub API-Key fehlt — skip Earnings')
        return []
    today = datetime.now(timezone.utc).date()
    until = today + timedelta(days=days)
    url = (
        f'https://finnhub.io/api/v1/calendar/earnings'
        f'?from={today}&to={until}&token={api_key}'
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f'[catalyst] Finnhub-Fehler: {e}')
        return []

    events = []
    for e in data.get('earningsCalendar', []):
        symbol = e.get('symbol')
        date = e.get('date')
        if not symbol or not date:
            continue
        eps_est = e.get('epsEstimate')
        rev_est = e.get('revenueEstimate')
        desc = f"Earnings {symbol}"
        if eps_est:
            desc += f" (EPS est {eps_est})"
        events.append({
            'id': make_id(date, 'EARNINGS', symbol, desc),
            'date': date,
            'type': 'EARNINGS',
            'ticker': symbol,
            'sector': None,
            'description': desc,
            'consensus_expectation': f"EPS {eps_est}, Rev {rev_est}" if eps_est else None,
            'importance': 4 if symbol in ('AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META', 'AMZN', 'TSLA') else 3,
            'source': 'finnhub',
        })
    print(f'[catalyst] Finnhub: {len(events)} Earnings-Events in {days}d')
    return events


# ────────────────────────────────────────────────────────────────────────────
# Source 2: Trading Economics (free feed)
# ────────────────────────────────────────────────────────────────────────────

def fetch_trading_economics_macro(days: int = 30) -> list[dict]:
    """Free trading-economics API nutzt guest-Auth 'guest:guest'."""
    today = datetime.now(timezone.utc).date()
    until = today + timedelta(days=days)
    url = (
        f'https://api.tradingeconomics.com/calendar'
        f'?c=guest:guest&d1={today}&d2={until}&f=json'
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f'[catalyst] TradingEconomics-Fehler: {e}')
        return []

    events = []
    important_keywords = ('GDP', 'CPI', 'Fed', 'ECB', 'Unemployment', 'PMI', 'Retail', 'Rate')
    countries = ('United States', 'Euro Area', 'Germany', 'China', 'Japan', 'United Kingdom')
    for e in data:
        if not isinstance(e, dict):
            continue
        country = e.get('Country', '')
        event = e.get('Event', '')
        date = (e.get('Date') or '')[:10]
        if not date or country not in countries:
            continue
        if not any(k in event for k in important_keywords):
            continue
        imp = e.get('Importance', 2) or 2
        events.append({
            'id': make_id(date, 'MACRO', None, f'{country} {event}'),
            'date': date,
            'type': 'MACRO',
            'ticker': None,
            'sector': 'Macro',
            'description': f'{country}: {event}',
            'consensus_expectation': e.get('Forecast') or None,
            'importance': min(5, max(1, int(imp) + 1)),
            'source': 'trading_economics',
        })
    print(f'[catalyst] TradingEconomics: {len(events)} Macro-Events in {days}d')
    return events


# ────────────────────────────────────────────────────────────────────────────
# Source 3: yfinance Fallback fuer Portfolio-Ticker
# ────────────────────────────────────────────────────────────────────────────

def fetch_yfinance_for_portfolio() -> list[dict]:
    try:
        import yfinance as yf
    except ImportError:
        return []
    # Aktive Strategy-Ticker laden
    strat_file = WS / 'data' / 'strategies.json'
    if not strat_file.exists():
        return []
    try:
        strats = json.loads(strat_file.read_text(encoding='utf-8'))
    except Exception:
        return []
    tickers = set()
    for s in strats.values():
        if not isinstance(s, dict):
            continue
        if s.get('status') in ('active', 'watchlist', 'probation', 'watching'):
            for t in s.get('tickers', []) or []:
                if t and len(t) <= 8 and '.' not in t and '_' not in t:  # US-Ticker only
                    tickers.add(t.upper())

    events = []
    for tk in list(tickers)[:30]:  # cap
        try:
            tobj = yf.Ticker(tk)
            cal = getattr(tobj, 'calendar', None)
            if cal is None:
                continue
            # yfinance .calendar ist dict in neueren Versionen
            if isinstance(cal, dict):
                date_val = cal.get('Earnings Date')
                if isinstance(date_val, list) and date_val:
                    date_val = date_val[0]
                if hasattr(date_val, 'strftime'):
                    date = date_val.strftime('%Y-%m-%d')
                else:
                    date = str(date_val)[:10]
                if date and date[:4].isdigit():
                    events.append({
                        'id': make_id(date, 'EARNINGS', tk, f'Earnings {tk}'),
                        'date': date,
                        'type': 'EARNINGS',
                        'ticker': tk,
                        'sector': None,
                        'description': f'Earnings {tk} (yfinance)',
                        'importance': 3,
                        'source': 'yfinance',
                    })
        except Exception:
            continue
    print(f'[catalyst] yfinance Portfolio-Fallback: {len(events)} Events')
    return events


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def run(days: int = 30) -> dict:
    conn = sqlite3.connect(str(DB))
    try:
        ensure_schema(conn)

        all_events: list[dict] = []

        # Seed-Events (nur zukuenftige)
        today = datetime.now(timezone.utc).date()
        for date, ctype, ticker, sector, desc, imp in CATALYST_SEED_2026:
            try:
                dt = datetime.strptime(date, '%Y-%m-%d').date()
                if dt < today or (dt - today).days > days:
                    continue
                all_events.append({
                    'id': make_id(date, ctype, ticker, desc),
                    'date': date, 'type': ctype, 'ticker': ticker, 'sector': sector,
                    'description': desc, 'importance': imp, 'source': 'manual',
                })
            except Exception:
                continue

        all_events += fetch_finnhub_earnings(days)
        all_events += fetch_trading_economics_macro(days)
        all_events += fetch_yfinance_for_portfolio()

        # Dedup + Write
        seen = set()
        unique = []
        for e in all_events:
            if e['id'] in seen:
                continue
            seen.add(e['id'])
            unique.append(e)
            upsert(conn, e)
        conn.commit()

        # JSON-Export
        unique_sorted = sorted(unique, key=lambda r: (r['date'], -r.get('importance', 3)))
        export = {
            'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'horizon_days': days,
            'total_events': len(unique_sorted),
            'events': unique_sorted,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding='utf-8')

        # Top-7-Events anzeigen
        print(f'\n[catalyst] Top-7 Events naechste {days} Tage:')
        for e in unique_sorted[:7]:
            imp = '★' * e.get('importance', 3)
            print(f"  {e['date']} [{e['type']:<10}] {imp:<5} {e.get('ticker') or '-':<8} {e.get('description','')[:80]}")

        return {
            'status': 'ok',
            'events_total': len(unique_sorted),
            'by_type': {t: sum(1 for e in unique_sorted if e['type'] == t) for t in {e['type'] for e in unique_sorted}},
        }
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    args = ap.parse_args()
    r = run(days=args.days)
    print(f"\n[catalyst] Summary: {r}")
    sys.exit(0 if r.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
