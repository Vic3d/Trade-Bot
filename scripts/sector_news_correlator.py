#!/usr/bin/env python3
"""
sector_news_correlator.py — Phase 45ao Layer 3 (Victor 2026-05-11).

Verknüpft Markt-Puls mit News-Activity. Cross-Match-Logik:
  - Sektor läuft + News bestätigen → HIGH_CONVICTION (kombinierter Driver)
  - Sektor läuft ohne News → STRUCTURAL (Smart Money, leise Akkumulation)
  - News-Cluster ohne Markt-Bewegung → NOISE (Markt glaubt es nicht)
  - Markt fällt + bullish News → TRAP (definitiv vermeiden)

Output: data/sector_news_correlation.json + ergänzt market_pulse_latest.md.
Run: täglich 06:15 (nach Market-Pulse, vor Strategy-Genesis).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))

PULSE_FILE = WS / 'data' / 'market_pulse_latest.json'
NEWS_LOG   = WS / 'data' / 'news_reactor_log.jsonl'
OUT_JSON   = WS / 'data' / 'sector_news_correlation.json'

# Sektor → Keyword-Mapping (für News-Filterung)
SECTOR_KEYWORDS = {
    'GDX':  ['gold', 'newmont', 'barrick', 'mining', 'precious metals', 'agnico'],
    'GDXJ': ['junior gold', 'gold miners', 'exploration'],
    'SLV':  ['silver', 'silbermine', 'hecla', 'pan american'],
    'GLD':  ['gold', 'precious metal', 'fed pivot', 'usd schwäche'],
    'XLE':  ['oil', 'öl', 'brent', 'wti', 'opec', 'hormuz', 'iran', 'tanker'],
    'XLF':  ['bank', 'fed', 'interest rate', 'zins', 'jpmorgan', 'wells fargo'],
    'XLK':  ['tech', 'nvidia', 'apple', 'microsoft', 'ai', 'ki'],
    'XLV':  ['healthcare', 'biotech', 'pharma', 'fda', 'drug approval'],
    'XLU':  ['utility', 'utilities', 'power', 'electricity', 'grid'],
    'XLP':  ['staples', 'consumer', 'procter', 'walmart'],
    'XLB':  ['materials', 'chemicals', 'mining', 'rohstoffe'],
    'ITA':  ['defense', 'rüstung', 'pentagon', 'nato', 'weapons', 'military'],
    'URA':  ['uranium', 'nuclear', 'atomstrom', 'cameco'],
    'COPX': ['copper', 'kupfer', 'freeport', 'mining'],
    'LIT':  ['lithium', 'albemarle', 'sqm', 'ev battery'],
    'TAN':  ['solar', 'first solar', 'enphase', 'renewable'],
    'KRE':  ['regional bank', 'community bank', 'banking crisis'],
    'XBI':  ['biotech', 'fda', 'drug', 'clinical trial'],
    'SMH':  ['semiconductor', 'chip', 'asml', 'tsmc', 'nvidia', 'broadcom'],
    'IBIT': ['bitcoin', 'crypto', 'btc'],
}


def _load_recent_news(hours: int = 48) -> list[dict]:
    if not NEWS_LOG.exists(): return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    out = []
    try:
        with open(NEWS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = e.get('ts') or e.get('timestamp', '')
                    if ts > cutoff:
                        out.append(e)
                except Exception: pass
    except Exception: pass
    return out


def _count_sector_news(news: list[dict]) -> dict:
    """Anzahl News-Events pro Sektor (basierend auf Keywords)."""
    counts = {sec: 0 for sec in SECTOR_KEYWORDS}
    samples = {sec: [] for sec in SECTOR_KEYWORDS}
    for ev in news:
        text = (ev.get('news', '') + ' ' + ev.get('headline', '') + ' '
                + ev.get('summary', '')).lower()
        for sec, kws in SECTOR_KEYWORDS.items():
            if any(kw in text for kw in kws):
                counts[sec] += 1
                if len(samples[sec]) < 3:
                    samples[sec].append((ev.get('news', '') or ev.get('headline', ''))[:120])
    return {sec: {'count': n, 'samples': samples[sec]}
            for sec, n in counts.items() if n > 0}


def correlate() -> dict:
    if not PULSE_FILE.exists():
        return {'error': 'no_market_pulse'}
    pulse = json.loads(PULSE_FILE.read_text(encoding='utf-8'))
    news = _load_recent_news(48)
    sector_news = _count_sector_news(news)

    correlations = []
    for etf_data in pulse.get('all_etfs', []):
        ticker = etf_data['ticker']
        chg_5d = etf_data['chg_5d']
        news_info = sector_news.get(ticker, {'count': 0, 'samples': []})
        news_count = news_info['count']

        # Cross-Match Classification
        if abs(chg_5d) < 1 and news_count >= 5:
            label = 'NOISE'  # News aber kein Move
            desc = 'News-Cluster ohne Markt-Bewegung — Markt glaubt es nicht'
        elif chg_5d >= 3 and news_count >= 3:
            label = 'HIGH_CONVICTION'  # News + Move
            desc = 'Sektor läuft + News bestätigen → kombinierter Driver'
        elif chg_5d >= 3 and news_count < 3:
            label = 'STRUCTURAL'  # Move ohne News
            desc = 'Sektor läuft ohne News-Bestätigung — strukturell / Smart Money'
        elif chg_5d <= -3 and news_count >= 5:
            label = 'TRAP'  # Bullish News + Markt fällt
            desc = 'News bullish, Markt fällt → Falle, vermeiden'
        elif chg_5d <= -3:
            label = 'DOWNTREND'
            desc = 'Sektor fällt — keine Long-Opportunity'
        else:
            label = 'NEUTRAL'
            desc = 'Kein klares Cross-Signal'

        correlations.append({
            'ticker': ticker,
            'sector': etf_data.get('sector', '?'),
            'chg_5d': chg_5d,
            'chg_30d': etf_data.get('chg_30d'),
            'news_count_48h': news_count,
            'news_samples': news_info['samples'],
            'cross_label': label,
            'description': desc,
        })

    # Sort by interestingness: HIGH_CONVICTION first, then STRUCTURAL
    rank = {'HIGH_CONVICTION': 0, 'STRUCTURAL': 1, 'TRAP': 2, 'NOISE': 3, 'NEUTRAL': 4, 'DOWNTREND': 5}
    correlations.sort(key=lambda x: (rank.get(x['cross_label'], 99), -x['chg_5d']))

    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'n_news_events_48h': len(news),
        'correlations': correlations,
        'high_conviction': [c for c in correlations if c['cross_label'] == 'HIGH_CONVICTION'],
        'structural':      [c for c in correlations if c['cross_label'] == 'STRUCTURAL'],
        'traps':           [c for c in correlations if c['cross_label'] == 'TRAP'],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False),
                        encoding='utf-8')
    return out


def main() -> int:
    r = correlate()
    if 'error' in r:
        print(json.dumps(r))
        return 1
    print(f"News-Events 48h: {r['n_news_events_48h']}")
    print(f"HIGH_CONVICTION: {len(r['high_conviction'])}")
    for c in r['high_conviction'][:5]:
        print(f"  {c['ticker']:6} {c['sector']:25} 5d={c['chg_5d']:+}% news={c['news_count_48h']}")
    print(f"STRUCTURAL: {len(r['structural'])}")
    for c in r['structural'][:5]:
        print(f"  {c['ticker']:6} {c['sector']:25} 5d={c['chg_5d']:+}% (kein News-Driver)")
    print(f"TRAPS: {len(r['traps'])}")
    for c in r['traps']:
        print(f"  {c['ticker']:6} {c['sector']:25} 5d={c['chg_5d']:+}% news={c['news_count_48h']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
