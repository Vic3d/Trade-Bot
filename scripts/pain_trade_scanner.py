#!/usr/bin/env python3
"""
Pain Trade Scanner — Phase 22
===============================
Taegliche Messung der Markt-Positionierung aus mehreren freien Datenquellen.
Identifiziert wo der Konsens einseitig (crowded) ist und wo Contrarian-Opportunities
lauern.

Datenquellen:
  - CBOE Put/Call Ratio (via yfinance proxy ^CPC or ^VIX)
  - VIX Term-Structure (Spot vs 3M)
  - AAII Sentiment (wenn scrapebar)
  - Fear & Greed via CNN (scrape)
  - Sector-Relative-Strength (ETF Preis-Momentum)

Output:
  data/positioning.json mit:
    - put_call_ratio
    - vix_spot + vix_term_structure (contango/backwardation)
    - aaii_bullish_pct
    - fear_greed_index
    - sectors: {tech, energy, financials, ...} mit positioning + pain_trade

Gekoppelt an Deep-Dive-Prompt: auto_deep_dive liest positioning.json und reichert
jede Analyse mit Pain-Trade-Flag an.

Laeuft: tgl. 07:00 CET. CLI:
  python3 scripts/pain_trade_scanner.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
OUT = WS / 'data' / 'positioning.json'

sys.path.insert(0, str(WS / 'scripts'))


# ────────────────────────────────────────────────────────────────────────────
# Signal-Fetchers
# ────────────────────────────────────────────────────────────────────────────

def _get_close(ticker: str, period: str = '5d') -> float | None:
    """Robuster Close-Fetch via yfinance.Ticker.history (funktioniert besser als download)."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=period)
        if h is None or h.empty:
            return None
        return float(h['Close'].iloc[-1])
    except Exception:
        return None


def fetch_vix_structure() -> dict:
    """VIX Spot + 3M → Contango (bull-komplacency) / Backwardation (panic)."""
    try:
        v_spot = _get_close('^VIX')
        v_3m = _get_close('^VIX3M')
        if v_spot is None:
            return {'status': 'error', 'error': 'VIX close not available'}
        structure = 'unknown'
        if v_3m:
            ratio = v_spot / v_3m
            if ratio < 0.92:
                structure = 'contango_deep'    # Komplacency, Long-Vol moeglich
            elif ratio < 1.0:
                structure = 'contango'          # Normal
            elif ratio < 1.1:
                structure = 'backwardation'     # Stress
            else:
                structure = 'backwardation_deep'  # Panic
        return {
            'vix_spot': round(v_spot, 2),
            'vix_3m': round(v_3m, 2) if v_3m else None,
            'structure': structure,
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def fetch_put_call_ratio() -> dict:
    """CBOE Put/Call via yfinance ^CPC (falls verfuegbar, sonst Proxy aus VIX)."""
    val = _get_close('^CPC')
    if val is not None:
        state = 'greed' if val < 0.7 else 'fear' if val > 1.2 else 'neutral'
        return {'put_call': round(val, 2), 'state': state}
    return {'put_call': None, 'state': 'unknown'}


def fetch_fear_greed_cnn() -> dict:
    """CNN Fear & Greed Index via JSON-Endpoint (oft verfuegbar ohne Key)."""
    url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
    # CNN blockt einfache User-Agents mit HTTP 418 — echter Browser-UA noetig
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://edition.cnn.com/',
        'Origin': 'https://edition.cnn.com',
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
        fg = data.get('fear_and_greed', {})
        score = fg.get('score')
        rating = fg.get('rating')
        if score is not None:
            return {'score': round(float(score), 1), 'rating': rating}
    except Exception as e:
        # Fallback: Ableitung aus VIX
        v = _get_close('^VIX')
        if v is not None:
            # VIX 10-15 = extreme greed 75+, VIX 30+ = extreme fear 25-
            score = max(0, min(100, 100 - (v - 12) * 3.5))
            rating = ('extreme fear' if score < 25 else 'fear' if score < 45
                      else 'neutral' if score < 55 else 'greed' if score < 75 else 'extreme greed')
            return {'score': round(score, 1), 'rating': rating, 'source': 'vix_derived'}
        return {'score': None, 'rating': 'unknown', 'error': str(e)[:80]}
    return {'score': None, 'rating': 'unknown'}


def fetch_sector_momentum() -> dict:
    """Sektor-ETFs: 20-day relative strength vs SPY. Overextended = crowded."""
    sectors = {
        'tech': 'XLK',
        'energy': 'XLE',
        'financials': 'XLF',
        'healthcare': 'XLV',
        'industrials': 'XLI',
        'consumer_disc': 'XLY',
        'utilities': 'XLU',
        'materials': 'XLB',
        'staples': 'XLP',
        'real_estate': 'XLRE',
        'communications': 'XLC',
    }
    # Einzel-Fetch via Ticker.history (robuster als yf.download-Batch)
    try:
        import yfinance as yf
    except Exception as e:
        return {'error': f'yfinance import: {e}'}

    def _series(tk: str):
        try:
            h = yf.Ticker(tk).history(period='30d')
            return h['Close'] if h is not None and not h.empty else None
        except Exception:
            return None

    spy = _series('SPY')
    if spy is None or len(spy) < 2:
        return {'error': 'SPY-Daten fehlen'}
    spy_ret = float(spy.iloc[-1] / spy.iloc[0] - 1) * 100

    result = {}
    for name, etf in sectors.items():
        try:
            s = _series(etf)
            if s is None or len(s) < 2:
                continue
            ret = float(s.iloc[-1] / s.iloc[0] - 1) * 100
            rel = ret - spy_ret
            # Positioning-Score: 0.0-1.0, 0.5 = neutral
            # Extreme rel-Strength → crowded long
            positioning = max(0.0, min(1.0, 0.5 + rel / 20.0))
            if positioning > 0.75:
                state = 'crowded_long'
                pain_trade = 'short_or_avoid_new_longs'
            elif positioning < 0.30:
                state = 'underowned'
                pain_trade = 'long_contrarian'
            else:
                state = 'neutral'
                pain_trade = 'none'
            result[name] = {
                'ret_20d_pct': round(ret, 2),
                'rel_vs_spy_pct': round(rel, 2),
                'positioning': round(positioning, 2),
                'state': state,
                'pain_trade': pain_trade,
            }
        except Exception:
            continue
    return result


# ────────────────────────────────────────────────────────────────────────────
# Aggregate + Scoring
# ────────────────────────────────────────────────────────────────────────────

def compute_market_regime(vix_info: dict, pc: dict, fg: dict) -> str:
    """Zusammengefasste Markt-Positionierung in 1 Label."""
    score = 50  # Neutral-Basis
    # VIX-Struktur
    if vix_info.get('structure') == 'contango_deep':
        score += 20
    elif vix_info.get('structure') == 'contango':
        score += 10
    elif vix_info.get('structure') == 'backwardation':
        score -= 10
    elif vix_info.get('structure') == 'backwardation_deep':
        score -= 20
    # P/C Ratio
    if pc.get('state') == 'greed':
        score += 15
    elif pc.get('state') == 'fear':
        score -= 15
    # Fear & Greed
    fg_score = fg.get('score')
    if fg_score:
        score = int(0.6 * score + 0.4 * float(fg_score))

    if score >= 75:
        return 'extreme_greed'
    elif score >= 60:
        return 'greed'
    elif score <= 25:
        return 'extreme_fear'
    elif score <= 40:
        return 'fear'
    return 'neutral'


def run() -> dict:
    print('[pain-trade] Sammle Positionierungs-Daten...')
    vix_info = fetch_vix_structure()
    pc = fetch_put_call_ratio()
    fg = fetch_fear_greed_cnn()
    sectors = fetch_sector_momentum()
    regime = compute_market_regime(vix_info, pc, fg)

    # Pain-Trade-Kandidaten (top-3 je Richtung)
    _sector_items = [(s, d) for s, d in sectors.items() if isinstance(d, dict)]
    crowded_longs = sorted(
        [(s, d.get('positioning', 0)) for s, d in _sector_items if d.get('state') == 'crowded_long'],
        key=lambda x: -x[1],
    )[:3]
    underowned = sorted(
        [(s, d.get('positioning', 0)) for s, d in _sector_items if d.get('state') == 'underowned'],
        key=lambda x: x[1],
    )[:3]

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'regime': regime,
        'vix_spot': vix_info.get('vix_spot'),
        'vix_3m': vix_info.get('vix_3m'),
        'vix_structure': vix_info.get('structure'),
        'put_call_ratio': pc.get('put_call'),
        'put_call_state': pc.get('state'),
        'fear_greed_score': fg.get('score'),
        'fear_greed_rating': fg.get('rating'),
        'sectors': sectors,
        'crowded_longs': [{'sector': s, 'positioning': p} for s, p in crowded_longs],
        'underowned_sectors': [{'sector': s, 'positioning': p} for s, p in underowned],
        'pain_trades_summary': {
            'avoid_or_fade': [s for s, _ in crowded_longs],
            'contrarian_long_candidates': [s for s, _ in underowned],
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"[pain-trade] Regime: {regime.upper()}")
    print(f"[pain-trade] VIX: {vix_info.get('vix_spot')} ({vix_info.get('structure')})")
    print(f"[pain-trade] P/C: {pc.get('put_call')} ({pc.get('state')})  F&G: {fg.get('score')} ({fg.get('rating')})")
    if crowded_longs:
        print(f"[pain-trade] Crowded-Long: {', '.join(s for s,_ in crowded_longs)}")
    if underowned:
        print(f"[pain-trade] Underowned: {', '.join(s for s,_ in underowned)}")

    return {'status': 'ok', 'regime': regime}


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    r = run()
    sys.exit(0 if r.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
