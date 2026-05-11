#!/usr/bin/env python3
"""
macro_regime_detector.py — Phase 45aq Layer B1 (Victor 2026-05-11).

Quantitative Regime-Erkennung aus 5 Indikatoren statt manueller Direktive:
  1. VIX-Niveau + Term-Structure (VIX vs VIX3M)
  2. Yield-Curve (^TNX 10Y vs ^FVX 5Y; ggf. 10Y-2Y wenn verfügbar)
  3. USD-Trend (DXY)
  4. Credit-Spread-Proxy (HYG vs IEF)
  5. Gold/Silver-Ratio (XAU/XAG)

Output: data/macro_regime.json mit
  - regime: RISK_ON | RISK_OFF | TRANSITION | CRISIS
  - confidence: 0-1
  - sub-indikatoren mit Bewertung

Run: täglich 06:05 (nach Market-Pulse).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
OUT_JSON = WS / 'data' / 'macro_regime.json'


def _fetch_price(ticker: str, days: int = 60) -> list[float]:
    """Aktuelle + historische Closes."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=f'{days}d')
        return h['Close'].tolist()
    except Exception:
        return []


def detect_regime() -> dict:
    score = 0  # negativ = risk-off, positiv = risk-on
    indicators: dict = {}

    # 1. VIX (negativ: VIX hoch = risk-off)
    vix = _fetch_price('^VIX', 30)
    if vix:
        last_vix = vix[-1]
        avg_vix = sum(vix[-20:]) / min(20, len(vix))
        indicators['vix'] = {'last': round(last_vix, 1), 'avg_20d': round(avg_vix, 1)}
        if last_vix < 16:
            score += 2; indicators['vix']['signal'] = 'risk_on'
        elif last_vix > 25:
            score -= 2; indicators['vix']['signal'] = 'risk_off'
        elif last_vix > 30:
            score -= 4; indicators['vix']['signal'] = 'crisis'
        else:
            indicators['vix']['signal'] = 'neutral'

    # 2. Yield-Curve (10Y rising vs 5Y)
    tnx = _fetch_price('^TNX', 30)  # 10Y in %
    fvx = _fetch_price('^FVX', 30)  # 5Y
    if tnx and fvx:
        spread = tnx[-1] - fvx[-1]
        indicators['yield_curve'] = {
            '10y': round(tnx[-1], 2), '5y': round(fvx[-1], 2),
            'spread': round(spread, 2),
        }
        if spread > 0.3:
            score += 1; indicators['yield_curve']['signal'] = 'steepening_risk_on'
        elif spread < -0.3:
            score -= 1; indicators['yield_curve']['signal'] = 'inverted_risk_off'
        else:
            indicators['yield_curve']['signal'] = 'flat'

    # 3. USD-Trend (DXY) — schwach = risk-on
    dxy = _fetch_price('DX-Y.NYB', 30)
    if not dxy:
        dxy = _fetch_price('UUP', 30)  # ETF-Proxy
    if dxy and len(dxy) >= 20:
        chg_20d = (dxy[-1] - dxy[-20]) / dxy[-20] * 100
        indicators['usd'] = {'last': round(dxy[-1], 2), 'chg_20d_pct': round(chg_20d, 2)}
        if chg_20d < -2:
            score += 1; indicators['usd']['signal'] = 'weakening_risk_on'
        elif chg_20d > 2:
            score -= 1; indicators['usd']['signal'] = 'strengthening_risk_off'
        else:
            indicators['usd']['signal'] = 'flat'

    # 4. Credit-Spread (HYG/IEF) — HYG fallend gegen IEF = Credit-Stress
    hyg = _fetch_price('HYG', 30)
    ief = _fetch_price('IEF', 30)
    if hyg and ief and len(hyg) >= 20 and len(ief) >= 20:
        hyg_chg = (hyg[-1] - hyg[-20]) / hyg[-20] * 100
        ief_chg = (ief[-1] - ief[-20]) / ief[-20] * 100
        rel = hyg_chg - ief_chg
        indicators['credit'] = {
            'hyg_chg_20d': round(hyg_chg, 2),
            'ief_chg_20d': round(ief_chg, 2),
            'hyg_minus_ief': round(rel, 2),
        }
        if rel > 1:
            score += 1; indicators['credit']['signal'] = 'spread_tightening_risk_on'
        elif rel < -1:
            score -= 2; indicators['credit']['signal'] = 'spread_widening_risk_off'
        else:
            indicators['credit']['signal'] = 'neutral'

    # 5. Gold/Silver-Ratio (XAU/XAG) — Verhältnis fallend = Risk-On
    gold = _fetch_price('GC=F', 30)
    silver = _fetch_price('SI=F', 30)
    if gold and silver and len(gold) >= 20:
        ratio_now = gold[-1] / silver[-1]
        ratio_20d = gold[-20] / silver[-20]
        chg = (ratio_now - ratio_20d) / ratio_20d * 100
        indicators['gold_silver_ratio'] = {
            'now': round(ratio_now, 1), 'chg_20d_pct': round(chg, 2),
        }
        if chg < -3:
            score += 1; indicators['gold_silver_ratio']['signal'] = 'falling_risk_on'
        elif chg > 3:
            score -= 1; indicators['gold_silver_ratio']['signal'] = 'rising_risk_off'
        else:
            indicators['gold_silver_ratio']['signal'] = 'flat'

    # Regime-Klassifikation
    if score >= 4:
        regime = 'RISK_ON'
    elif score >= 1:
        regime = 'TRANSITION_BULLISH'
    elif score <= -4:
        regime = 'CRISIS'
    elif score <= -1:
        regime = 'RISK_OFF'
    else:
        regime = 'NEUTRAL'

    # Confidence: |score| / max_possible
    max_score = 8
    confidence = min(1.0, abs(score) / max_score)

    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'regime': regime,
        'score': score,
        'confidence': round(confidence, 2),
        'indicators': indicators,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False),
                        encoding='utf-8')
    return out


def main() -> int:
    r = detect_regime()
    print(f"Regime: {r['regime']} (score={r['score']}, conf={r['confidence']})")
    for k, v in r['indicators'].items():
        print(f"  {k}: {v.get('signal','?')} — {v}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
