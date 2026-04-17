#!/usr/bin/env python3
"""
Earnings Calendar — Phase 7.15 Discovery Source 3
===================================================
Fetcht Earnings-Termine fuer die naechsten 5 Tage (via yfinance .calendar
pro Ticker oder Finnhub free tier falls FINNHUB_API_KEY gesetzt).

Neue Tickers (nicht in UNIVERSE/strategies) mit Earnings in <=5 Tagen werden
zu candidate_tickers.json hinzugefuegt mit source='earnings_upcoming'.
Bestehende Tickers im UNIVERSE bekommen keinen Candidate-Eintrag (sind
bereits im Deep-Dive-Prozess).

Budget: Kostenlos (Finnhub free tier 60 req/min, yfinance unlimited).

CLI:
  python3 scripts/discovery/earnings_calendar.py
  python3 scripts/discovery/earnings_calendar.py --days 7
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))

from candidates import add_candidate, is_new_ticker  # noqa: E402
from market_scanner import UNIVERSE as SCAN_UNIVERSE  # noqa: E402

FINNHUB_API = 'https://finnhub.io/api/v1/calendar/earnings'


def fetch_finnhub(days_ahead: int, api_key: str) -> list[dict]:
    """Holt Earnings-Kalender ueber Finnhub free tier."""
    from_date = date.today().isoformat()
    to_date = (date.today() + timedelta(days=days_ahead)).isoformat()
    params = urllib.parse.urlencode({
        'from': from_date,
        'to': to_date,
        'token': api_key,
    })
    url = f'{FINNHUB_API}?{params}'
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode('utf-8'))
        return data.get('earningsCalendar', []) or []
    except Exception as e:
        print(f'[earnings] Finnhub Fehler: {e}')
        return []


def fetch_yfinance_calendar(tickers: list[str], days_ahead: int) -> list[dict]:
    """Fallback: yfinance pro-Ticker .calendar. Langsam, darum nur fuer SCAN_UNIVERSE."""
    try:
        import yfinance as yf
    except ImportError:
        return []

    cutoff = date.today() + timedelta(days=days_ahead)
    out = []
    for tk in tickers:
        try:
            t = yf.Ticker(tk)
            cal = getattr(t, 'calendar', None)
            if not cal:
                continue
            # yfinance returns dict with 'Earnings Date' key
            ed = None
            if isinstance(cal, dict):
                ed = cal.get('Earnings Date')
            if ed:
                if isinstance(ed, (list, tuple)) and ed:
                    ed = ed[0]
                try:
                    edate = ed.date() if hasattr(ed, 'date') else datetime.fromisoformat(str(ed)).date()
                except Exception:
                    continue
                if date.today() <= edate <= cutoff:
                    out.append({'symbol': tk, 'date': edate.isoformat(), 'epsEstimate': None})
        except Exception:
            continue
    return out


def score_for_earnings(days_until: int, eps_surprise: float | None) -> float:
    """Score basierend auf Naehe zum Earnings-Termin."""
    if days_until <= 1:
        base = 0.9
    elif days_until <= 3:
        base = 0.75
    else:
        base = 0.6
    if eps_surprise is not None:
        try:
            base = min(1.0, base + min(0.1, abs(float(eps_surprise)) / 10.0))
        except Exception:
            pass
    return round(base, 2)


def run(days_ahead: int = 5, dry: bool = False, yf_fallback_limit: int = 60) -> dict:
    finnhub_key = os.environ.get('FINNHUB_API_KEY', '').strip()
    events: list[dict] = []

    if finnhub_key:
        print(f'[earnings] Nutze Finnhub (key: ***{finnhub_key[-4:]})')
        events = fetch_finnhub(days_ahead, finnhub_key)
        print(f'[earnings] Finnhub: {len(events)} Events')

    if not events:
        # Fallback: yfinance, limited
        pool = SCAN_UNIVERSE[:yf_fallback_limit]
        print(f'[earnings] Fallback yfinance ueber {len(pool)} Tickers...')
        events = fetch_yfinance_calendar(pool, days_ahead)
        print(f'[earnings] yfinance: {len(events)} Events')

    today = date.today()
    new_count = 0
    upcoming_known = 0

    for ev in events:
        tk = str(ev.get('symbol', '')).strip().upper()
        dt_str = ev.get('date', '')
        if not tk or not dt_str:
            continue
        try:
            edate = date.fromisoformat(dt_str)
        except Exception:
            continue
        days_until = (edate - today).days
        if days_until < 0 or days_until > days_ahead:
            continue

        eps_est = ev.get('epsEstimate')
        score = score_for_earnings(days_until, eps_est)
        detail = f'Earnings in {days_until}d ({edate.isoformat()})'
        if eps_est is not None:
            detail += f' EPS-Est: {eps_est}'

        if is_new_ticker(tk):
            if not dry:
                added = add_candidate(tk, 'earnings_upcoming', detail, score=score)
                if added:
                    new_count += 1
                    print(f'  + {tk} score={score} — {detail}')
        else:
            upcoming_known += 1

    print(f'[earnings] {new_count} neue Kandidaten, {upcoming_known} bekannte Tickers mit Earnings')
    return {
        'status': 'ok',
        'events': len(events),
        'new_candidates': new_count,
        'known_with_earnings': upcoming_known,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=5)
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    result = run(days_ahead=args.days, dry=args.dry)
    sys.exit(0 if result.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
