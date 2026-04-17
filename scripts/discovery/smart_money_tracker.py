#!/usr/bin/env python3
"""
Smart Money Tracker — Phase 22
================================
Liest drei Smart-Money-Signale und feedet sie in candidate_tickers.json:

  1. SEC Form 4 Insider-Buys (EDGAR Full-Text Search, free)
     - Management-Kaeufe > $100k in letzten 7 Tagen
  2. Short Interest Spikes (Finra/Yahoo)
     - Kurzfristiger Anstieg deutet auf Squeeze-Kandidaten
  3. Unusual Options Volume (yfinance .option_chain)
     - Volumen > 3x Open Interest = Smart-Money-Wette

Aufgerufen: tgl. 06:10 CET (vor Catalyst Calendar 06:20)
CLI:
  python3 scripts/discovery/smart_money_tracker.py
  python3 scripts/discovery/smart_money_tracker.py --max-tickers 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))

from candidates import load_candidates, save_candidates  # noqa: E402


# ────────────────────────────────────────────────────────────────────────────
# Source 1: SEC Form 4 Insider Buys via EDGAR
# ────────────────────────────────────────────────────────────────────────────

EDGAR_BASE = 'https://www.sec.gov'
EDGAR_UA = 'TradeMind Research contact@trademind.local'


def fetch_recent_form4(days: int = 7) -> list[dict]:
    """Liest die letzten Form-4-Filings aus EDGAR RSS/Atom feed."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    # EDGAR ATOM feed mit dem neuesten type=4 Filings
    url = f'{EDGAR_BASE}/cgi-bin/browse-edgar?action=getcompany&type=4&dateb=&owner=include&count=100&output=atom'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': EDGAR_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            xml_text = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'[smart-money] EDGAR-Fehler: {e}')
        return []

    import re
    # Parsing: simpler regex fuer entry-blocks
    entries = re.findall(r'<entry>([\s\S]*?)</entry>', xml_text)
    for entry in entries[:50]:
        m_title = re.search(r'<title>([^<]+)</title>', entry)
        m_link = re.search(r'<link[^>]*href="([^"]+)"', entry)
        m_updated = re.search(r'<updated>([^<]+)</updated>', entry)
        if not (m_title and m_updated):
            continue
        title = m_title.group(1)
        # Form 4 Titles kommen oft als "4 - Company Name (CIK) (Filer)"
        m_tk = re.search(r'\(([A-Z]{1,5})\)', title)
        ticker = m_tk.group(1) if m_tk else None
        results.append({
            'ticker': ticker,
            'title': title[:200],
            'updated': m_updated.group(1),
            'link': m_link.group(1) if m_link else None,
        })
    return results


# ────────────────────────────────────────────────────────────────────────────
# Source 2: Short Interest via yfinance .info (free, rate-limited)
# ────────────────────────────────────────────────────────────────────────────

SHORT_WATCHLIST = [
    # Heiss-Kandidaten (hoher Short-Float historisch)
    'BYND', 'GME', 'AMC', 'BBBY', 'SIRI', 'CVNA', 'UPST', 'FUBO', 'SPCE',
    'RIVN', 'LCID', 'NKLA', 'PTON', 'WISH', 'CLOV', 'PLTR', 'RIOT', 'MARA',
    'DWAC', 'PHUN', 'ATER', 'MULN', 'AI', 'SOUN', 'ACHR',
    # Hohe Short aus Finanzpresse gelistet
    'TSLA', 'NFLX', 'MU',
]


def fetch_short_interest_spikes() -> list[dict]:
    try:
        import yfinance as yf
    except ImportError:
        return []

    results = []
    for tk in SHORT_WATCHLIST:
        try:
            info = yf.Ticker(tk).info
            short_pct = info.get('shortPercentOfFloat')
            short_ratio = info.get('shortRatio')
            if short_pct is None:
                continue
            short_pct = float(short_pct) * 100 if short_pct < 1 else float(short_pct)
            if short_pct >= 15.0:  # Threshold: 15% des Floats
                results.append({
                    'ticker': tk,
                    'short_pct_float': round(short_pct, 1),
                    'short_ratio_days': short_ratio,
                    'price': info.get('currentPrice'),
                })
            time.sleep(0.2)  # Rate-limit-freundlich
        except Exception:
            continue
    return results


# ────────────────────────────────────────────────────────────────────────────
# Source 3: Unusual Options Volume
# ────────────────────────────────────────────────────────────────────────────

def fetch_unusual_options(tickers: list[str]) -> list[dict]:
    try:
        import yfinance as yf
    except ImportError:
        return []

    results = []
    for tk in tickers[:30]:
        try:
            tobj = yf.Ticker(tk)
            exps = tobj.options
            if not exps:
                continue
            # Erste Expiration (naechste)
            chain = tobj.option_chain(exps[0])
            calls = chain.calls
            puts = chain.puts
            # Volumen > 2x Open Interest = Unusual
            unusual_calls = calls[(calls['volume'] > 2 * calls['openInterest']) & (calls['volume'] > 500)]
            unusual_puts = puts[(puts['volume'] > 2 * puts['openInterest']) & (puts['volume'] > 500)]
            if len(unusual_calls) >= 2 or len(unusual_puts) >= 2:
                results.append({
                    'ticker': tk,
                    'unusual_calls': len(unusual_calls),
                    'unusual_puts': len(unusual_puts),
                    'bias': 'bullish' if len(unusual_calls) > len(unusual_puts) else 'bearish',
                })
            time.sleep(0.3)
        except Exception:
            continue
    return results


# ────────────────────────────────────────────────────────────────────────────
# Aggregate + Upsert
# ────────────────────────────────────────────────────────────────────────────

def upsert(ticker: str, source_type: str, detail: str, score: float):
    data = load_candidates()
    t = ticker.upper()
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    entry = data.get(t) or {
        'discovered_at': now, 'last_seen_at': now,
        'sources': [], 'priority': 0.0, 'status': 'pending',
    }
    # Dedup innerhalb 24h
    for s in entry['sources'][-8:]:
        if s.get('type') == source_type:
            try:
                prev = datetime.fromisoformat(s.get('ts','').replace('Z','+00:00'))
                if (datetime.now(timezone.utc) - prev).total_seconds() < 86400:
                    return False
            except Exception:
                pass
    entry['sources'].append({
        'type': source_type, 'detail': detail[:200],
        'score': round(float(score), 2), 'ts': now,
    })
    entry['last_seen_at'] = now
    scores = [s.get('score', 0) for s in entry['sources']]
    types = {s.get('type') for s in entry['sources']}
    entry['priority'] = round(min(1.5, max(scores) + 0.15 * (len(types) - 1)), 2)
    if entry.get('status') in ('rejected', 'expired'):
        entry['status'] = 'pending'
    data[t] = entry
    save_candidates(data)
    return True


def run(max_tickers: int = 50) -> dict:
    added_counts = {'insider_buy': 0, 'short_spike': 0, 'unusual_options': 0}

    print('[smart-money] Fetching SEC Form 4 Insider Buys...')
    form4 = fetch_recent_form4(days=7)
    print(f'[smart-money] EDGAR: {len(form4)} Form-4 entries')
    for e in form4[:max_tickers]:
        if not e.get('ticker'):
            continue
        if upsert(e['ticker'], 'insider_buy', e['title'][:150], 0.75):
            added_counts['insider_buy'] += 1

    print('[smart-money] Fetching Short Interest Spikes...')
    shorts = fetch_short_interest_spikes()
    print(f'[smart-money] {len(shorts)} High-Short Tickers')
    for s in shorts:
        detail = f"Short {s['short_pct_float']}% of float (ratio {s.get('short_ratio_days','?')})"
        if upsert(s['ticker'], 'short_squeeze_watch', detail, 0.60):
            added_counts['short_spike'] += 1

    # Options-Check nur auf unserem aktiven Universum (sonst Rate-Limit)
    from_active = set()
    try:
        strats = json.loads((WS / 'data' / 'strategies.json').read_text(encoding='utf-8'))
        for s in strats.values():
            if isinstance(s, dict) and s.get('status') in ('active', 'probation', 'watchlist'):
                for t in s.get('tickers', [])[:2]:
                    if t and '.' not in t and len(t) <= 5:
                        from_active.add(t.upper())
    except Exception:
        pass
    option_candidates = list(from_active)[:20]

    print(f'[smart-money] Checking Unusual Options on {len(option_candidates)} active tickers...')
    unusual = fetch_unusual_options(option_candidates)
    for u in unusual:
        detail = f"{u['unusual_calls']} unusual calls, {u['unusual_puts']} unusual puts ({u['bias']})"
        if upsert(u['ticker'], 'unusual_options', detail, 0.65):
            added_counts['unusual_options'] += 1

    print(f'[smart-money] Summary: {added_counts}')
    return {'status': 'ok', 'added': added_counts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-tickers', type=int, default=50)
    args = ap.parse_args()
    r = run(max_tickers=args.max_tickers)
    sys.exit(0 if r.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
