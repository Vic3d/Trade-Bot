#!/usr/bin/env python3
"""
SEC EDGAR Insider & 13F Signals — Phase 10

Kostenlose Smart-Money-Intelligence direkt von der SEC:
- Form 4: Insider-Käufe/-Verkäufe (CEO, CFO, Directors)
- 13F:    Institutional Holdings (Quartalsweise, Stub v1)

Quellen (kostenlos, kein API-Key):
- https://www.sec.gov/files/company_tickers.json      (Ticker → CIK Mapping)
- https://data.sec.gov/submissions/CIK{cik}.json       (Filings Index)
- https://www.sec.gov/Archives/edgar/data/...          (Form 4 XML)

SEC Rate Limit: 10 req/sec + User-Agent mit Kontakt.

Signal-Output:
  insider_signal(ticker, days=30) → dict
    {
      'ticker': 'NVDA',
      'days': 30,
      'num_filings': 5,
      'buy_count': 3,     # P = open-market purchase
      'sell_count': 2,    # S = open-market sale
      'net_shares': -12000,
      'net_value_usd': -450_000,
      'cluster_buys': 2,  # unterschiedliche Insider kaufen innerhalb 7 Tage
      'score': +15,       # -100..+100
      'bias': 'BULLISH' | 'NEUTRAL' | 'BEARISH',
      'reason': '...',
    }
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    HAS_CFFI = True
except Exception:
    HAS_CFFI = False
    import urllib.request

log = logging.getLogger('sec_edgar')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
CACHE_DIR = DATA / 'sec_edgar_cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = os.getenv('SEC_EDGAR_UA', 'TradeMind Paper-Bot research@trademind.local')
HEADERS = {
    'User-Agent': UA,
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov',
}

_LAST_CALL_TS = 0.0
_MIN_INTERVAL = 0.12  # ≤ 10 req/s


def _rate_limit():
    global _LAST_CALL_TS
    elapsed = time.time() - _LAST_CALL_TS
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL_TS = time.time()


def _http_get(url: str, host: str | None = None, timeout: int = 15) -> str | None:
    _rate_limit()
    hdr = dict(HEADERS)
    if host:
        hdr['Host'] = host
    try:
        if HAS_CFFI:
            r = cffi_requests.get(url, headers=hdr, timeout=timeout, impersonate='chrome124')
            if r.status_code == 200:
                return r.text
            log.warning(f'SEC {url} → {r.status_code}')
            return None
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log.warning(f'SEC fetch {url} failed: {e}')
        return None


# ─────────────────────── CIK Lookup ────────────────────────────

_CIK_CACHE_FILE = CACHE_DIR / 'company_tickers.json'
_CIK_MAP: dict[str, str] | None = None


def _load_cik_map() -> dict[str, str]:
    """Return {TICKER_UPPER: 10-digit CIK string}."""
    global _CIK_MAP
    if _CIK_MAP is not None:
        return _CIK_MAP

    # Refresh wöchentlich
    need_refresh = True
    if _CIK_CACHE_FILE.exists():
        age = time.time() - _CIK_CACHE_FILE.stat().st_mtime
        if age < 7 * 86400:
            need_refresh = False

    if need_refresh:
        txt = _http_get('https://www.sec.gov/files/company_tickers.json', host='www.sec.gov')
        if txt:
            try:
                _CIK_CACHE_FILE.write_text(txt, encoding='utf-8')
            except Exception:
                pass

    if not _CIK_CACHE_FILE.exists():
        _CIK_MAP = {}
        return _CIK_MAP

    try:
        raw = json.loads(_CIK_CACHE_FILE.read_text(encoding='utf-8'))
        # Format: { "0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ... }
        mp: dict[str, str] = {}
        for _, rec in raw.items():
            t = str(rec.get('ticker', '')).upper()
            c = int(rec.get('cik_str', 0))
            if t and c:
                mp[t] = f'{c:010d}'
        _CIK_MAP = mp
    except Exception as e:
        log.warning(f'CIK map parse failed: {e}')
        _CIK_MAP = {}
    return _CIK_MAP


def get_cik(ticker: str) -> str | None:
    """NVDA → '0001045810' (10-digit string)."""
    t = ticker.upper().replace('.', '-')
    mp = _load_cik_map()
    return mp.get(t)


# ─────────────────────── Submissions Fetch ─────────────────────

def _fetch_submissions(cik: str) -> dict | None:
    url = f'https://data.sec.gov/submissions/CIK{cik}.json'
    txt = _http_get(url, host='data.sec.gov')
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception as e:
        log.warning(f'submissions parse failed for {cik}: {e}')
        return None


def _extract_form4_filings(sub: dict, days: int = 30) -> list[dict]:
    """Return list of {accession, filingDate, primaryDocument} for Form 4 in window."""
    try:
        rec = sub['filings']['recent']
    except Exception:
        return []
    forms = rec.get('form', [])
    dates = rec.get('filingDate', [])
    accs = rec.get('accessionNumber', [])
    docs = rec.get('primaryDocument', [])

    cutoff = date.today() - timedelta(days=days)
    out = []
    for i, f in enumerate(forms):
        if f != '4':
            continue
        try:
            fd = datetime.strptime(dates[i], '%Y-%m-%d').date()
        except Exception:
            continue
        if fd < cutoff:
            continue
        out.append({
            'accession': accs[i],
            'filingDate': dates[i],
            'primaryDocument': docs[i] if i < len(docs) else '',
        })
    return out


# ─────────────────────── Form 4 XML Parser ─────────────────────

# Transaction codes Form 4 (SEC Reg S-K)
BUY_CODES = {'P'}          # open-market purchase
SELL_CODES = {'S'}         # open-market sale
IGNORE_CODES = {'F', 'M', 'A', 'J', 'G', 'I', 'W', 'Z', 'K', 'L',
                'U', 'C', 'E', 'H', 'O', 'X'}


def _parse_form4_xml(xml_text: str) -> dict:
    """
    Return {
        'owner': str, 'title': str, 'is_director': bool, 'is_officer': bool,
        'buys': [ {shares, price, date, value} ],
        'sells': [ ... ],
    }
    """
    out = {'owner': '', 'title': '', 'is_director': False, 'is_officer': False,
           'buys': [], 'sells': []}
    try:
        # Namespace-lose Parse (SEC Form 4 hat keinen Default-Namespace)
        root = ET.fromstring(xml_text)
    except Exception as e:
        log.debug(f'Form 4 XML parse failed: {e}')
        return out

    # Owner + Rolle
    owner_el = root.find('.//reportingOwner')
    if owner_el is not None:
        nm = owner_el.find('.//rptOwnerName')
        if nm is not None and nm.text:
            out['owner'] = nm.text.strip()
        rel = owner_el.find('.//reportingOwnerRelationship')
        if rel is not None:
            if (rel.findtext('isDirector') or '').strip() in ('1', 'true', 'Y'):
                out['is_director'] = True
            if (rel.findtext('isOfficer') or '').strip() in ('1', 'true', 'Y'):
                out['is_officer'] = True
                out['title'] = (rel.findtext('officerTitle') or '').strip()

    # Non-Derivative Transactions (die echten Aktien)
    for tx in root.findall('.//nonDerivativeTransaction'):
        code = (tx.findtext('.//transactionCode') or '').strip()
        if code in IGNORE_CODES:
            continue
        shares_txt = tx.findtext('.//transactionShares/value') or '0'
        price_txt = tx.findtext('.//transactionPricePerShare/value') or '0'
        date_txt = tx.findtext('.//transactionDate/value') or ''
        try:
            shares = float(shares_txt)
            price = float(price_txt)
        except Exception:
            continue
        if shares <= 0:
            continue
        rec = {
            'shares': shares,
            'price': price,
            'date': date_txt,
            'value': shares * price,
        }
        if code in BUY_CODES:
            out['buys'].append(rec)
        elif code in SELL_CODES:
            out['sells'].append(rec)
    return out


def _fetch_form4(cik: str, accession: str, primary_doc: str) -> dict | None:
    # Accession im Pfad ohne Dashes
    acc_nodash = accession.replace('-', '')
    cik_int = int(cik)
    if not primary_doc:
        return None
    # primaryDocument kommt oft als "xslF345X06/wk-form4_XXX.xml" (HTML-Rendering-Pfad).
    # Raw-XML liegt ohne XSL-Präfix direkt im Accession-Verzeichnis.
    raw_doc = re.sub(r'^xsl[^/]+/', '', primary_doc)
    url = f'https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{raw_doc}'
    txt = _http_get(url, host='www.sec.gov')
    if not txt:
        # Fallback: Pfad mit XSL versuchen (manche Filings haben kein Strip-Prefix)
        url2 = f'https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary_doc}'
        txt = _http_get(url2, host='www.sec.gov')
        if not txt:
            return None
    return _parse_form4_xml(txt)


# ─────────────────────── Public API ────────────────────────────

_SIGNAL_CACHE_TTL = 6 * 3600  # 6h


def _cache_path(ticker: str, days: int) -> Path:
    return CACHE_DIR / f'signal_{ticker.upper()}_{days}d.json'


def insider_signal(ticker: str, days: int = 30, use_cache: bool = True) -> dict:
    """
    Aggregiertes Insider-Signal für einen Ticker (Form 4, letzte N Tage).

    Score-Logik (-100..+100):
    - Baseline 0
    - +30 wenn net_value > 0 (Netto-Kauf)
    - -30 wenn net_value < 0
    - +/-20 proportional zu |net_value| (log-skaliert, cap 1M$)
    - +15 wenn cluster_buys ≥ 2 (verschiedene Insider)
    - -15 wenn cluster_sells ≥ 2
    - +10 wenn CEO/CFO/Director unter den Käufern
    """
    ticker = ticker.upper()
    cache_file = _cache_path(ticker, days)
    if use_cache and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < _SIGNAL_CACHE_TTL:
            try:
                return json.loads(cache_file.read_text(encoding='utf-8'))
            except Exception:
                pass

    empty = {
        'ticker': ticker, 'days': days,
        'num_filings': 0, 'buy_count': 0, 'sell_count': 0,
        'net_shares': 0, 'net_value_usd': 0.0,
        'cluster_buys': 0, 'cluster_sells': 0,
        'score': 0, 'bias': 'NEUTRAL', 'reason': 'no data',
        'fetched_at': datetime.now().isoformat(timespec='seconds'),
    }

    cik = get_cik(ticker)
    if not cik:
        empty['reason'] = 'no CIK mapping (non-US ticker?)'
        return empty

    sub = _fetch_submissions(cik)
    if not sub:
        empty['reason'] = 'submissions fetch failed'
        return empty

    filings = _extract_form4_filings(sub, days=days)
    if not filings:
        empty['reason'] = 'no Form 4 in window'
        empty['num_filings'] = 0
        try:
            cache_file.write_text(json.dumps(empty, indent=2), encoding='utf-8')
        except Exception:
            pass
        return empty

    total_buy_shares = 0.0
    total_sell_shares = 0.0
    total_buy_value = 0.0
    total_sell_value = 0.0
    buyers: set[str] = set()
    sellers: set[str] = set()
    roles_buying: set[str] = set()

    parsed_count = 0
    MAX_PARSE = 15  # cap for rate limiting
    for flg in filings[:MAX_PARSE]:
        data = _fetch_form4(cik, flg['accession'], flg['primaryDocument'])
        if not data:
            continue
        parsed_count += 1
        owner = data.get('owner', '')
        for b in data['buys']:
            total_buy_shares += b['shares']
            total_buy_value += b['value']
            if owner:
                buyers.add(owner)
            if data.get('is_officer'):
                roles_buying.add('officer')
            if data.get('is_director'):
                roles_buying.add('director')
        for s in data['sells']:
            total_sell_shares += s['shares']
            total_sell_value += s['value']
            if owner:
                sellers.add(owner)

    net_shares = int(total_buy_shares - total_sell_shares)
    net_value = total_buy_value - total_sell_value

    # Score berechnen
    score = 0.0
    if net_value > 0:
        score += 30
    elif net_value < 0:
        score -= 30

    # Log-skaliert: 100k$ = ~5, 1M$ = ~20
    import math
    if abs(net_value) >= 10_000:
        mag = min(20.0, 20.0 * math.log10(abs(net_value) / 10_000 + 1) / math.log10(101))
        score += mag if net_value > 0 else -mag

    if len(buyers) >= 2:
        score += 15
    if len(sellers) >= 2:
        score -= 15
    if roles_buying and net_value > 0:
        score += 10

    score = max(-100, min(100, round(score)))

    if score >= 20:
        bias = 'BULLISH'
    elif score <= -20:
        bias = 'BEARISH'
    else:
        bias = 'NEUTRAL'

    reason_parts = []
    if total_buy_value > 0:
        reason_parts.append(f'buys {total_buy_value/1000:.0f}k$ ({len(buyers)} ppl)')
    if total_sell_value > 0:
        reason_parts.append(f'sells {total_sell_value/1000:.0f}k$ ({len(sellers)} ppl)')
    if roles_buying and net_value > 0:
        reason_parts.append('+'.join(sorted(roles_buying)) + ' buying')

    out = {
        'ticker': ticker, 'days': days,
        'num_filings': len(filings),
        'parsed': parsed_count,
        'buy_count': int(len(buyers)),
        'sell_count': int(len(sellers)),
        'net_shares': net_shares,
        'net_value_usd': round(net_value, 2),
        'cluster_buys': len(buyers),
        'cluster_sells': len(sellers),
        'score': score,
        'bias': bias,
        'reason': ' | '.join(reason_parts) if reason_parts else 'no open-market tx',
        'fetched_at': datetime.now().isoformat(timespec='seconds'),
    }
    try:
        cache_file.write_text(json.dumps(out, indent=2), encoding='utf-8')
    except Exception:
        pass
    return out


def thirteen_f_signal(ticker: str) -> dict:
    """Stub v1: 13F parsing ist teuer (quartalsweise, riesige XMLs).
    Placeholder für spätere Expansion."""
    return {
        'ticker': ticker.upper(),
        'available': False,
        'note': '13F institutional holdings — stub, implement later',
    }


# ─────────────────────── CLI ───────────────────────────────────

def _print_signal(sig: dict) -> None:
    bias_icon = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '⚪'}.get(sig['bias'], '?')
    print(f"\n{bias_icon} {sig['ticker']} Insider ({sig['days']}d)  "
          f"Score {sig['score']:+d}  [{sig['bias']}]")
    print(f"   Filings: {sig['num_filings']} (parsed {sig.get('parsed', 0)})  "
          f"Buys: {sig['buy_count']}  Sells: {sig['sell_count']}")
    print(f"   Net: {sig['net_shares']:+,} shares  /  ${sig['net_value_usd']:+,.0f}")
    print(f"   {sig['reason']}")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--ticker', '-t', required=False)
    p.add_argument('--days', '-d', type=int, default=30)
    p.add_argument('--nocache', action='store_true')
    p.add_argument('--tickers', nargs='+', help='Batch mode')
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    targets = args.tickers if args.tickers else ([args.ticker] if args.ticker else ['NVDA'])
    for t in targets:
        sig = insider_signal(t, days=args.days, use_cache=not args.nocache)
        _print_signal(sig)


if __name__ == '__main__':
    main()
