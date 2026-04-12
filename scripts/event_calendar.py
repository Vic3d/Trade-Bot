#!/usr/bin/env python3
"""
Event Calendar — Upcoming Market-Moving Events
==============================================
Lädt täglich relevante Events (Fed, OPEC, Earnings, Makro-Daten)
und speichert sie in data/upcoming_events.json.

Quellen:
  - Finnhub Economic Calendar (kostenlos)
  - Finnhub Earnings Calendar (kostenlos)

thesis_news_hunter liest upcoming_events.json um event-bewusste
Suchanfragen zu bauen (z.B. "FOMC meeting expectations" am Tag vor Fed-Entscheid).

Läuft täglich 07:30 CET.
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS   = Path('/data/.openclaw/workspace')
DATA = WS / 'data'

FINNHUB_KEY  = os.getenv('FINNHUB_KEY', 'd6o6lm1r01qu09ciaj3gd6o6lm1r01qu09ciaj40')
OUTPUT_FILE  = DATA / 'upcoming_events.json'
LOG_FILE     = DATA / 'event_calendar.log'


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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


# ── Finnhub Economic Calendar ────────────────────────────────────────────────

# Events die für unser Portfolio wichtig sind
HIGH_IMPORTANCE_EVENTS = [
    'fed', 'fomc', 'interest rate', 'ecb', 'bank of england', 'boe',
    'opec', 'oil', 'gdp', 'cpi', 'inflation', 'unemployment', 'nonfarm',
    'payroll', 'pmi', 'ism', 'retail sales', 'housing', 'earnings',
]


def fetch_economic_calendar(days_ahead: int = 7) -> list[dict]:
    """Lädt Finnhub Economic Calendar für die nächsten N Tage."""
    now  = datetime.now(timezone.utc)
    from_dt = now.strftime('%Y-%m-%d')
    to_dt   = (now + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

    url = f'https://finnhub.io/api/v1/calendar/economic?from={from_dt}&to={to_dt}&token={FINNHUB_KEY}'
    raw = _get(url)
    if not raw:
        return []

    try:
        data = json.loads(raw)
        events = data.get('economicCalendar', [])
    except Exception:
        return []

    result = []
    for ev in events:
        event_name = ev.get('event', '').lower()
        impact     = ev.get('impact', '').lower()  # 'high', 'medium', 'low'
        country    = ev.get('country', '')
        date_str   = ev.get('time', ev.get('date', ''))

        # Nur wichtige Events (high impact ODER keyword match)
        is_important = (
            impact == 'high' or
            any(kw in event_name for kw in HIGH_IMPORTANCE_EVENTS)
        )
        if not is_important:
            continue

        # Nur relevante Länder
        if country not in ('US', 'EU', 'DE', 'GB', 'JP', 'CN', 'OPEC', ''):
            continue

        result.append({
            'type':    'economic',
            'name':    ev.get('event', ''),
            'date':    date_str[:10],
            'time':    date_str,
            'country': country,
            'impact':  impact,
            'actual':  ev.get('actual', ''),
            'forecast': ev.get('estimate', ''),
        })

    return result


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

    economic = fetch_economic_calendar(days_ahead=7)
    log(f'Economic Calendar: {len(economic)} wichtige Events (nächste 7 Tage)')

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
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    today_events = [e for e in all_events if e.get('date', '') in (today, tomorrow)]
    if today_events:
        log('Events heute/morgen:')
        for e in today_events:
            log(f"  [{e['date']}] {e['name']} ({e.get('country', '')}) — Impact: {e.get('impact', '?')}")

    return output


if __name__ == '__main__':
    run()
