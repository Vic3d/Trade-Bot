#!/usr/bin/env python3
"""
Event Calendar — Upcoming Market-Moving Events
==============================================
Lädt täglich relevante Events (Fed, OPEC, Earnings, Makro-Daten)
und speichert sie in data/upcoming_events.json.

Quellen:
  - Google News RSS: Suche nach bevorstehenden Makro-Events (kostenlos, kein API-Key)
  - Finnhub Earnings Calendar (kostenlos, Free-Plan)

Hinweis: Finnhub Economic Calendar erfordert paid plan (403 auf Free).
         Ersatz: Google News Suche nach Event-Namen + "this week"/"preview".

thesis_news_hunter liest upcoming_events.json um event-bewusste
Suchanfragen zu bauen (z.B. "FOMC meeting expectations" am Tag vor Fed-Entscheid).

Läuft täglich 07:30 CET.
"""

import json
import os
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')

WS   = Path('/data/.openclaw/workspace')
DATA = WS / 'data'

FINNHUB_KEY  = os.getenv('FINNHUB_KEY', 'd6o6lm1r01qu09ciaj3gd6o6lm1r01qu09ciaj40')
OUTPUT_FILE  = DATA / 'upcoming_events.json'
LOG_FILE     = DATA / 'event_calendar.log'


def log(msg: str):
    ts = datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _get(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except Exception as e:
        log(f'HTTP-Fehler: {e} | {url[:60]}')
        return None


# ── Makro-Event-Suche via Google News ────────────────────────────────────────
#
# Finnhub Economic Calendar erfordert Paid Plan (gibt 403 auf Free).
# Ersatz: Für jedes wichtige Makro-Thema Google News RSS durchsuchen.
# Wenn aktuelle Artikel zum Event gefunden werden → Event ist "upcoming".
#
# Themen mit hohem Trading-Impact für unser Portfolio:
MACRO_EVENT_QUERIES = [
    # Name (für Output),  Suchanfrage,                                    Sektor
    ('FOMC Meeting',      'FOMC Federal Reserve interest rate decision',   'macro'),
    ('ECB Rate Decision', 'ECB European Central Bank rate decision',        'macro'),
    ('OPEC Meeting',      'OPEC oil production meeting decision',           'energy'),
    ('US NFP Jobs',       'nonfarm payroll jobs report this week',          'macro'),
    ('US CPI Inflation',  'US CPI inflation data release this week',        'macro'),
    ('US GDP Data',       'US GDP data release economic growth',            'macro'),
    ('Iran Sanctions',    'Iran oil sanctions decision US Treasury',        'energy'),
    ('Trump Tariffs',     'Trump tariffs trade war announcement',           'macro'),
    ('Earnings Season',   'earnings season preview S&P 500',               'equities'),
]


def fetch_economic_events_via_news(days_window: int = 3) -> list[dict]:
    """
    Sucht via Google News RSS nach bevorstehenden Makro-Events.
    Gibt eine Liste von Events zurück die in den nächsten days_window Tagen relevant sind.
    """
    results = []
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=48)  # Artikel der letzten 48h

    for event_name, query, sector in MACRO_EVENT_QUERIES:
        encoded = urllib.parse.quote(query)
        url = f'https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en'
        raw = _get(url)
        if not raw:
            time.sleep(0.3)
            continue

        try:
            root  = ET.fromstring(raw)
            items = root.findall('.//item')
            fresh_articles = 0
            latest_title   = ''

            for item in items[:5]:
                title = item.findtext('title', '')
                pub   = item.findtext('pubDate', '')
                try:
                    pub_dt = parsedate_to_datetime(pub)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt > cutoff:
                        fresh_articles += 1
                        if not latest_title:
                            latest_title = title
                except Exception:
                    pass

            # Wenn aktuelle Artikel zum Thema gefunden → Event ist "im Gange" oder "upcoming"
            if fresh_articles >= 2:
                today = datetime.now(_BERLIN).strftime('%Y-%m-%d')
                results.append({
                    'type':     'economic',
                    'name':     event_name,
                    'date':     today,
                    'country':  'US',
                    'impact':   'high',
                    'sector':   sector,
                    'headline': latest_title[:120],
                    'articles': fresh_articles,
                })
                log(f'  ✓ {event_name}: {fresh_articles} aktuelle Artikel gefunden')

        except Exception as e:
            log(f'  Fehler bei {event_name}: {e}')

        time.sleep(0.5)  # Rate-Limit Google News

    return results


def fetch_earnings_calendar(days_ahead: int = 5) -> list[dict]:
    """Lädt Finnhub Earnings Calendar für aktive Portfolio-Tickers."""
    # Aktive Tickers aus strategies.json laden
    strats_file = DATA / 'strategies.json'
    watch_tickers = set()
    try:
        strategies = json.loads(strats_file.read_text(encoding='utf-8'))
        for sid, s in strategies.items():
            if isinstance(s, dict) and s.get('status', 'active').lower() not in ('inactive', 'blocked', 'suspended'):
                for t in s.get('tickers', []):
                    # US-Tickers ohne Suffix
                    clean = t.replace('.DE', '').replace('.PA', '').replace('.OL', '').replace('.L', '').replace('.AS', '').replace('.CO', '')
                    if len(clean) <= 5:
                        watch_tickers.add(clean)
    except Exception:
        pass

    if not watch_tickers:
        return []

    now     = datetime.now(timezone.utc)
    from_dt = now.strftime('%Y-%m-%d')
    to_dt   = (now + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

    url = f'https://finnhub.io/api/v1/calendar/earnings?from={from_dt}&to={to_dt}&token={FINNHUB_KEY}'
    raw = _get(url)
    if not raw:
        return []

    result = []
    try:
        data   = json.loads(raw)
        events = data.get('earningsCalendar', [])
        for ev in events:
            symbol = ev.get('symbol', '')
            if symbol in watch_tickers:
                result.append({
                    'type':     'earnings',
                    'ticker':   symbol,
                    'date':     ev.get('date', ''),
                    'time':     ev.get('hour', 'unknown'),   # 'bmo' (before market), 'amc' (after)
                    'eps_est':  ev.get('epsEstimate'),
                    'rev_est':  ev.get('revenueEstimate'),
                    'impact':   'high',  # earnings immer wichtig
                    'name':     f'{symbol} Earnings',
                    'country':  'US',
                })
    except Exception:
        pass

    return result


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def run() -> dict:
    log('=== Event Calendar Update ===')

    economic = fetch_economic_events_via_news(days_window=3)
    log(f'Makro-Events via News: {len(economic)} aktive Events erkannt')

    time.sleep(0.5)

    earnings = fetch_earnings_calendar(days_ahead=5)
    log(f'Earnings Calendar: {len(earnings)} Portfolio-Tickers berichten (nächste 5 Tage)')

    all_events = sorted(economic + earnings, key=lambda x: x.get('date', ''))

    # In JSON schreiben
    output = {
        'updated_at':  datetime.now(timezone.utc).isoformat(),
        'events':      all_events,
        'summary': {
            'economic_count': len(economic),
            'earnings_count': len(earnings),
            'next_high_impact': next(
                (f"{e['date']} {e['name']}" for e in all_events if e.get('impact') == 'high'),
                'keine'
            ),
        },
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    log(f'-> {OUTPUT_FILE.name} geschrieben ({len(all_events)} Events total)')

    # Wichtige Events ausgeben
    today = datetime.now(_BERLIN).strftime('%Y-%m-%d')
    tomorrow = (datetime.now(_BERLIN) + timedelta(days=1)).strftime('%Y-%m-%d')
    today_events = [e for e in all_events if e.get('date', '') in (today, tomorrow)]
    if today_events:
        log('Events heute/morgen:')
        for e in today_events:
            log(f"  [{e['date']}] {e['name']} ({e.get('country', '')}) — Impact: {e.get('impact', '?')}")

    return output


if __name__ == '__main__':
    run()
