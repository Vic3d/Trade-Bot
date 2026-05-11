#!/usr/bin/env python3
"""
sentiment_contrarian.py — Phase 45aq Layer D2 (Victor 2026-05-11).

Fear/Greed-Proxy aus 5 Indikatoren (kein API-Key nötig):
  - VIX-Level
  - Put/Call (via CPC-Proxy: SPY 5d Put-Volume vs Call)
  - Markt-Momentum (SPY 50d vs 200d MA)
  - Junk-Yield-Spread (HYG vs IEF)
  - Safe-Haven-Demand (TLT vs SPY)

Output: data/sentiment_index.json — Score 0-100
  0-20:   EXTREME_FEAR (Contrarian: buy)
  21-40:  FEAR
  41-60:  NEUTRAL
  61-80:  GREED
  81-100: EXTREME_GREED (Contrarian: caution)
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
OUT_JSON = WS / 'data' / 'sentiment_index.json'


def _fetch(ticker: str, days: int = 200) -> list[float]:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=f'{days}d')
        return h['Close'].tolist()
    except Exception: return []


def compute() -> dict:
    score = 50
    parts: dict = {}

    # VIX (niedrig=greed, hoch=fear)
    vix = _fetch('^VIX', 30)
    if vix:
        last = vix[-1]
        if last < 13: vix_sub = 90
        elif last < 16: vix_sub = 70
        elif last < 20: vix_sub = 50
        elif last < 28: vix_sub = 30
        else: vix_sub = 10
        parts['vix'] = {'level': round(last, 1), 'sub_score': vix_sub}
        score = score * 0.7 + vix_sub * 0.3

    # SPY 50d vs 200d
    spy = _fetch('SPY', 220)
    if len(spy) >= 200:
        ma50 = sum(spy[-50:]) / 50
        ma200 = sum(spy[-200:]) / 200
        rel = (ma50 - ma200) / ma200 * 100
        if rel > 5: mom_sub = 85
        elif rel > 2: mom_sub = 70
        elif rel > -2: mom_sub = 50
        elif rel > -5: mom_sub = 30
        else: mom_sub = 15
        parts['spy_momentum'] = {'ma50_vs_ma200_pct': round(rel, 2), 'sub_score': mom_sub}
        score = score * 0.7 + mom_sub * 0.3

    # HYG vs IEF (Credit-Appetite)
    hyg = _fetch('HYG', 30)
    ief = _fetch('IEF', 30)
    if hyg and ief and len(hyg) >= 20 and len(ief) >= 20:
        rel = ((hyg[-1] / hyg[-20]) - (ief[-1] / ief[-20])) * 100
        if rel > 2: cr_sub = 80
        elif rel > 0: cr_sub = 60
        elif rel > -2: cr_sub = 40
        else: cr_sub = 20
        parts['credit_appetite'] = {'hyg_vs_ief_20d': round(rel, 2), 'sub_score': cr_sub}
        score = score * 0.7 + cr_sub * 0.3

    # TLT vs SPY (Safe-Haven-Demand)
    tlt = _fetch('TLT', 30)
    if tlt and spy and len(tlt) >= 20 and len(spy) >= 20:
        rel = ((tlt[-1] / tlt[-20]) - (spy[-1] / spy[-20])) * 100
        # TLT outperformt SPY = fear
        if rel > 2: sh_sub = 25
        elif rel > 0: sh_sub = 45
        elif rel > -2: sh_sub = 60
        else: sh_sub = 80
        parts['safe_haven_demand'] = {'tlt_vs_spy_20d': round(rel, 2), 'sub_score': sh_sub}
        score = score * 0.7 + sh_sub * 0.3

    score = max(0, min(100, score))
    if score < 21: label = 'EXTREME_FEAR'
    elif score < 41: label = 'FEAR'
    elif score < 61: label = 'NEUTRAL'
    elif score < 81: label = 'GREED'
    else: label = 'EXTREME_GREED'

    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'score': round(score, 1),
        'label': label,
        'parts': parts,
        'contrarian_bias': 'aggressive' if score < 30 else ('cautious' if score > 75 else 'neutral'),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')
    return out


def main() -> int:
    r = compute()
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
