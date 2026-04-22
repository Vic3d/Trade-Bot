#!/usr/bin/env python3
"""
Political Risk Detector — Phase 22
===================================
Scant News der letzten 14 Tage + Ticker-Sektor-Mapping nach politischen
Gefahren-Signalen. Setzt strategies.json → strategy['political_risk_flag']=True
wenn Risiko erkannt.

Trigger-Pattern (case-insensitive):
  TRUMP_TARIFF      — Trump + (tariff|zoll|deal) + Sektor-match
  PHARMA_PRICE      — (drug price|pharma price|Medicare Part D) + Pharma-Ticker
  FDA_DEADLINE      — (FDA decision|PDUFA) + pending
  EU_REGULATION     — (EU Commission|digital markets act|AI Act) + Tech
  CHINA_SANCTIONS   — (export control|sanction|entity list) + Chip/AI
  CONGRESS_HEARING  — (subpoena|testify|hearing) + specific ticker

Gegenbeispiel das wir verhindern muessen: NVO — Trump-Pharma-Preisdeal drueckte
Kurs -30% in Tagen. System hatte "keine Fundamentaldaten" und sah nur Chart.

Usage:
  python3 scripts/intelligence/political_risk_detector.py
    → scant alle Strategien und setzt Flags in strategies.json
"""
from __future__ import annotations
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
DB = WS / 'data' / 'trading.db'
STRATS = WS / 'data' / 'strategies.json'
LOG = WS / 'data' / 'political_risk.log'


# Pattern-Library
RISK_PATTERNS = [
    {
        'id': 'TRUMP_TARIFF',
        'regex': r'\b(trump|tariff|zoll|zölle|section 232|section 301)\b',
        'sectors_hit': ['Auto', 'Tech', 'Pharma', 'Retail', 'Steel', 'Agriculture'],
        'weight': 0.8,
    },
    {
        'id': 'PHARMA_PRICE',
        'regex': r'\b(drug price|pharma price|medicare part d|inflation reduction act|most favored nation)\b',
        'sectors_hit': ['Pharma', 'Biotech', 'Healthcare'],
        'weight': 1.0,
    },
    {
        'id': 'FDA_DEADLINE',
        'regex': r'\b(fda (rejection|decision|delay|reject)|pdufa|complete response letter)\b',
        'sectors_hit': ['Pharma', 'Biotech'],
        'weight': 0.9,
    },
    {
        'id': 'EU_REGULATION',
        'regex': r'\b(eu commission|digital markets act|ai act|gdpr fine|antitrust)\b',
        'sectors_hit': ['Tech', 'Software'],
        'weight': 0.7,
    },
    {
        'id': 'CHINA_SANCTIONS',
        'regex': r'\b(export control|entity list|semiconductor sanction|chip ban|chinese tariff)\b',
        'sectors_hit': ['Semiconductor', 'Tech', 'AI'],
        'weight': 0.8,
    },
    {
        'id': 'CONGRESS_HEARING',
        'regex': r'\b(subpoena|senate hearing|house hearing|testify before congress|ftc probe)\b',
        'sectors_hit': ['Tech', 'Pharma', 'Finance'],
        'weight': 0.6,
    },
    {
        'id': 'RUSSIA_SANCTIONS',
        'regex': r'\b(russia sanction|oligarch|swift exclusion|oil price cap)\b',
        'sectors_hit': ['Oil', 'Energy', 'Defense'],
        'weight': 0.5,
    },
]

# Ticker-zu-Sektor-Mapping (minimal, kann aus portfolio_risk.py TICKER_SECTOR erweitert werden)
TICKER_SECTOR = {
    'NVO': 'Pharma', 'PFE': 'Pharma', 'MRK': 'Pharma', 'LLY': 'Pharma',
    'JNJ': 'Pharma', 'BMY': 'Pharma', 'ABBV': 'Pharma', 'GILD': 'Biotech',
    'STLD': 'Steel', 'CLF': 'Steel', 'NUE': 'Steel', 'X': 'Steel',
    'OXY': 'Oil', 'TTE.PA': 'Oil', 'EQNR.OL': 'Oil', 'XOM': 'Oil', 'CVX': 'Oil',
    'FRO': 'Oil', 'DHT': 'Oil', 'SHEL.L': 'Oil',
    'DAI': 'Auto', 'BMW.DE': 'Auto', 'BYDDY': 'Auto', 'F': 'Auto', 'GM': 'Auto',
    'AAPL': 'Tech', 'MSFT': 'Tech', 'GOOGL': 'Tech', 'META': 'Tech',
    'NVDA': 'Semiconductor', 'AMD': 'Semiconductor', 'INTC': 'Semiconductor',
    'KTOS': 'Defense', 'HII': 'Defense', 'RHM.DE': 'Defense', 'HAG.DE': 'Defense',
    'SAAB-B.ST': 'Defense', 'BA.L': 'Defense', 'LMT': 'Defense', 'NOC': 'Defense',
    'CCJ': 'Uranium', 'URA': 'Uranium', 'URNM': 'Uranium',
    'SAP': 'Tech', 'AIR.PA': 'Aerospace', 'SIE.DE': 'Industrial',
    'LHA.DE': 'Airline',
}


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec='seconds')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _fetch_recent_news(days: int = 14) -> list[dict]:
    """Liest News der letzten N Tage aus trading.db."""
    if not DB.exists():
        return []
    conn = sqlite3.connect(str(DB))
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        rows = conn.execute('''
            SELECT headline, source, published_at
            FROM news_events
            WHERE published_at >= ?
            ORDER BY published_at DESC
            LIMIT 2000
        ''', (cutoff,)).fetchall()
        conn.close()
        return [{'title': r[0] or '', 'source': r[1] or '', 'at': r[2] or ''} for r in rows]
    except Exception as e:
        conn.close()
        _log(f'news fetch err: {e}')
        return []


def _scan_ticker(ticker: str, news: list[dict]) -> dict:
    """Scant News nach Pattern-Hits fuer einen Ticker."""
    sector = TICKER_SECTOR.get(ticker, 'Unknown')
    hits = []
    for art in news:
        title = art['title'].lower()
        if not title:
            continue
        # Ticker-Erwaehnung boosted Signal
        ticker_mentioned = ticker.lower().replace('.', ' ').split()[0] in title
        for pat in RISK_PATTERNS:
            if re.search(pat['regex'], title, re.IGNORECASE):
                sector_match = sector in pat['sectors_hit']
                if sector_match or ticker_mentioned:
                    hits.append({
                        'pattern': pat['id'],
                        'weight': pat['weight'] * (1.5 if ticker_mentioned else 1.0),
                        'title': art['title'][:120],
                        'at': art['at'][:10],
                    })
                    break
    score = sum(h['weight'] for h in hits)
    return {
        'ticker': ticker,
        'sector': sector,
        'hits': hits[:5],  # top 5
        'score': round(score, 2),
        'flagged': score >= 1.5,
    }


def scan_all_strategies() -> dict:
    if not STRATS.exists():
        _log('strategies.json fehlt')
        return {}
    strats = json.loads(STRATS.read_text(encoding='utf-8'))
    news = _fetch_recent_news(14)
    _log(f'scanning {len(strats)} strats gegen {len(news)} news')
    changed = False
    stats = {'scanned': 0, 'flagged': 0, 'cleared': 0}

    for sid, cfg in strats.items():
        if not isinstance(cfg, dict) or sid.startswith('_') or sid == 'emerging_themes':
            continue
        tickers = cfg.get('tickers') or ([cfg.get('ticker')] if cfg.get('ticker') else [])
        if not tickers:
            continue
        stats['scanned'] += 1
        worst = None
        for t in tickers:
            if not t:
                continue
            r = _scan_ticker(t, news)
            if r['flagged'] and (worst is None or r['score'] > worst['score']):
                worst = r

        was_flagged = bool(cfg.get('political_risk_flag'))
        if worst:
            cfg['political_risk_flag'] = True
            cfg['political_risk_reason'] = (
                f'{worst["ticker"]} ({worst["sector"]}): '
                f'{",".join(h["pattern"] for h in worst["hits"])} — score {worst["score"]}'
            )
            cfg['political_risk_detected_at'] = datetime.now().isoformat(timespec='seconds')
            stats['flagged'] += 1
            if not was_flagged:
                _log(f'FLAG_NEW {sid}: {cfg["political_risk_reason"]}')
                changed = True
            elif was_flagged:
                changed = True
        else:
            if was_flagged:
                cfg['political_risk_flag'] = False
                cfg['political_risk_cleared_at'] = datetime.now().isoformat(timespec='seconds')
                stats['cleared'] += 1
                _log(f'FLAG_CLEARED {sid}')
                changed = True

    if changed:
        STRATS.write_text(json.dumps(strats, indent=2, ensure_ascii=False), encoding='utf-8')
    _log(f'STATS {stats}')
    return stats


if __name__ == '__main__':
    s = scan_all_strategies()
    print('\n── Political Risk Scan ──')
    for k, v in s.items():
        print(f'  {k:12} {v}')
