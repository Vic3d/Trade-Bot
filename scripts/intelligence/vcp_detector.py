#!/usr/bin/env python3
"""
VCP Detector — Volatility Contraction Pattern (Mark Minervini / Dirk Mueller)
==============================================================================
Erkennt das "Post-Base-Konsolidierung nach starkem Lauf"-Setup.

Kriterien fuer einen VCP-Score (0-100):
  1. Strong Prior Move   — Ticker ist >50% vom 60d-Tief (25pt)
  2. Above Trend         — Preis > EMA50 > EMA200 (20pt)
  3. Contraction         — ATR(14) ist in letzten 10 Tagen gefallen (25pt)
  4. Tight Range         — letzte 5 Tage Range <5% (15pt)
  5. Volume Dry-Up       — Avg-Vol(10) < Avg-Vol(50) (15pt)

Integration ins conviction_scorer als BONUS:
  score >= 70 → +5 Conviction-Bonus ("VCP ready")
  score >= 85 → +8 Conviction-Bonus ("prime VCP")

CLI:
  python3 scripts/intelligence/vcp_detector.py AMZN MRVL HOOD BE
"""
from __future__ import annotations
import json
import os
import sqlite3
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
DB = WS / 'data' / 'trading.db'


def _get_prices(ticker: str, days: int = 250) -> list[dict]:
    """Returns list of {date, close, high, low, volume} descending by date."""
    if not DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            """
            SELECT date, close, COALESCE(high, close), COALESCE(low, close),
                   COALESCE(volume, 0)
            FROM prices
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (ticker, days)
        ).fetchall()
        conn.close()
        return [
            {'date': r[0], 'close': float(r[1]), 'high': float(r[2]),
             'low': float(r[3]), 'volume': float(r[4] or 0)}
            for r in rows if r[1] is not None
        ]
    except Exception:
        return []


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr(rows: list[dict], period: int = 14) -> list[float]:
    """Wilder ATR. rows: descending. Returns list of ATRs ascending (oldest-first)."""
    if len(rows) < period + 1:
        return []
    rows_asc = list(reversed(rows))
    trs = []
    for i in range(1, len(rows_asc)):
        h = rows_asc[i]['high']
        l = rows_asc[i]['low']
        pc = rows_asc[i - 1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return []
    atrs = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        atrs.append((atrs[-1] * (period - 1) + tr) / period)
    return atrs


def analyze(ticker: str) -> dict:
    """VCP-Analyse. Returns {score, reasons[], ready, pattern}."""
    rows = _get_prices(ticker, 250)
    if len(rows) < 60:
        return {'ticker': ticker, 'score': 0, 'reasons': ['insufficient_data'],
                'ready': False, 'pattern': 'NONE'}

    closes_desc = [r['close'] for r in rows]
    closes_asc = list(reversed(closes_desc))  # alt -> neu
    highs_desc = [r['high'] for r in rows]
    lows_desc = [r['low'] for r in rows]
    vols_desc = [r['volume'] for r in rows]

    last = closes_desc[0]
    reasons = []
    score = 0

    # 1. Strong prior move: last vs low of last 60d
    low_60 = min(lows_desc[:60])
    move_pct = (last - low_60) / low_60 * 100 if low_60 > 0 else 0
    if move_pct >= 50:
        score += 25
        reasons.append(f'move+25 ({move_pct:.0f}% vom 60d-Low)')
    elif move_pct >= 25:
        score += 12
        reasons.append(f'move+12 ({move_pct:.0f}%)')
    else:
        reasons.append(f'move+0 ({move_pct:.0f}% — zu schwach)')

    # 2. Above trend: price > EMA50 > EMA200
    ema50 = _ema(closes_asc[-50:], 50) if len(closes_asc) >= 50 else None
    ema200 = _ema(closes_asc[-200:], 200) if len(closes_asc) >= 200 else None
    if ema50 and ema200 and last > ema50 > ema200:
        score += 20
        reasons.append(f'trend+20 (last>{ema50:.1f}>{ema200:.1f})')
    elif ema50 and last > ema50:
        score += 10
        reasons.append(f'trend+10 (last>{ema50:.1f})')
    else:
        reasons.append('trend+0')

    # 3. Contraction: ATR(14) letzte 10 Tage fallend?
    atrs = _atr(rows, 14)
    if len(atrs) >= 20:
        recent_atr = statistics.mean(atrs[-5:])
        prev_atr = statistics.mean(atrs[-15:-10])
        if recent_atr < prev_atr * 0.85:
            score += 25
            reasons.append(f'contract+25 (ATR {prev_atr:.2f}->{recent_atr:.2f})')
        elif recent_atr < prev_atr:
            score += 12
            reasons.append(f'contract+12 (ATR leicht fallend)')
        else:
            reasons.append(f'contract+0 (ATR steigt)')
    else:
        reasons.append('contract_nodata')

    # 4. Tight Range: last 5 days (high-low)/close < 5%
    if len(rows) >= 5:
        h5 = max(highs_desc[:5])
        l5 = min(lows_desc[:5])
        rng = (h5 - l5) / last * 100 if last > 0 else 99
        if rng < 5:
            score += 15
            reasons.append(f'tight+15 (5d-range {rng:.1f}%)')
        elif rng < 8:
            score += 7
            reasons.append(f'tight+7 ({rng:.1f}%)')
        else:
            reasons.append(f'tight+0 ({rng:.1f}%)')

    # 5. Volume dry-up: avg10 < avg50
    if len(vols_desc) >= 50:
        v10 = statistics.mean(vols_desc[:10]) if vols_desc[:10] else 0
        v50 = statistics.mean(vols_desc[:50])
        if v50 > 0 and v10 < v50 * 0.85:
            score += 15
            reasons.append(f'vol_dry+15 (v10={v10:.0f} < v50={v50:.0f})')
        elif v50 > 0 and v10 < v50:
            score += 7
            reasons.append(f'vol_dry+7')
        else:
            reasons.append(f'vol_dry+0')

    ready = score >= 70
    if score >= 85:
        pattern = 'PRIME_VCP'
    elif score >= 70:
        pattern = 'VCP_READY'
    elif score >= 45:
        pattern = 'CONSOLIDATING'
    else:
        pattern = 'NONE'

    return {
        'ticker': ticker,
        'score': score,
        'reasons': reasons,
        'ready': ready,
        'pattern': pattern,
        'price': last,
    }


def get_bonus_for_strategy(ticker: str) -> tuple[int, str]:
    """API fuer conviction_scorer. Returns (bonus_points, reason)."""
    if not ticker:
        return 0, 'no ticker'
    r = analyze(ticker)
    if r['pattern'] == 'PRIME_VCP':
        return 8, f'VCP prime ({r["score"]}/100): {", ".join(r["reasons"][:3])}'
    if r['pattern'] == 'VCP_READY':
        return 5, f'VCP ready ({r["score"]}/100)'
    return 0, f'no VCP ({r["pattern"]}, {r["score"]}/100)'


if __name__ == '__main__':
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['AMZN', 'HOOD', 'MRVL', 'BE', 'NVDA', 'NBIS']
    for t in tickers:
        r = analyze(t)
        print(f'{t:8} score={r["score"]:>3} {r["pattern"]:14} price={r.get("price","?")}')
        for reason in r['reasons']:
            print(f'     - {reason}')
