#!/usr/bin/env python3
"""
Sector Strength — Phase 25
==========================
Berechnet relative Stärke der 11 GICS-Sektoren über 5d und 20d.
Ranked Top-3 (Rückenwind) und Bottom-3 (Gegenwind).

Datenquelle: Sektor-ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC).
Fallback: SPY-relative Performance der ETFs.

Output: data/sector_strength.json
{
  "computed_at": "...",
  "ranking": [{"sector": "Technology", "etf": "XLK", "ret_5d": 3.2, "ret_20d": 8.1, "rank": 1}, ...],
  "top3": ["Technology", "Communication", "Consumer_Discretionary"],
  "bottom3": ["Utilities", "Consumer_Staples", "Energy"]
}

Hook: conviction_scorer liest top3/bottom3 → +5pt / -5pt Modifikator.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB = DATA / 'trading.db'
OUT = DATA / 'sector_strength.json'

SECTOR_ETFS = {
    'XLK':  'Technology',
    'XLF':  'Financials',
    'XLE':  'Energy',
    'XLV':  'Healthcare',
    'XLI':  'Industrials',
    'XLY':  'Consumer_Discretionary',
    'XLP':  'Consumer_Staples',
    'XLU':  'Utilities',
    'XLB':  'Materials',
    'XLRE': 'Real_Estate',
    'XLC':  'Communication',
}


def _ret_db(ticker: str, days: int) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker, days + 1),
        ).fetchall()
        c.close()
        if len(rows) < 2:
            return None
        latest = float(rows[0][0])
        oldest = float(rows[-1][0])
        if oldest <= 0:
            return None
        return (latest - oldest) / oldest * 100
    except Exception:
        return None


def _ret_yf(ticker: str, days: int) -> float | None:
    """Fallback: live via yfinance (Sektor-ETFs sind oft nicht in der DB)."""
    try:
        import yfinance as yf
        period = '1mo' if days <= 25 else '3mo'
        h = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if len(h) < days + 1:
            return None
        latest = float(h['Close'].iloc[-1])
        oldest = float(h['Close'].iloc[-(days + 1)])
        if oldest <= 0:
            return None
        return (latest - oldest) / oldest * 100
    except Exception:
        return None


def _ret(ticker: str, days: int) -> float | None:
    r = _ret_db(ticker, days)
    if r is not None:
        return r
    return _ret_yf(ticker, days)


def compute() -> dict:
    rows = []
    for etf, name in SECTOR_ETFS.items():
        r5 = _ret(etf, 5)
        r20 = _ret(etf, 20)
        if r5 is None and r20 is None:
            continue
        # Composite: 60% × 5d + 40% × 20d (kürzere Frist gewichteter für Reagibilität)
        score = (r5 or 0) * 0.6 + (r20 or 0) * 0.4
        rows.append({
            'sector': name,
            'etf': etf,
            'ret_5d': round(r5, 2) if r5 is not None else None,
            'ret_20d': round(r20, 2) if r20 is not None else None,
            'score': round(score, 2),
        })

    if not rows:
        return {'error': 'no_data', 'computed_at': datetime.now(timezone.utc).isoformat()}

    rows.sort(key=lambda x: x['score'], reverse=True)
    for i, r in enumerate(rows):
        r['rank'] = i + 1

    out = {
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'ranking': rows,
        'top3': [r['sector'] for r in rows[:3]],
        'bottom3': [r['sector'] for r in rows[-3:]],
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def get_sector_modifier(ticker: str) -> tuple[int, str]:
    """Liefert (modifier, reason) für conviction_scorer. +5 wenn Top-3, -5 wenn Bottom-3, 0 sonst."""
    try:
        if not OUT.exists():
            return 0, ''
        data = json.loads(OUT.read_text(encoding='utf-8'))
        # Map ticker → sector via portfolio_risk.TICKER_SECTOR
        try:
            from portfolio_risk import TICKER_SECTOR  # type: ignore
            sector = TICKER_SECTOR.get(ticker.upper())
            if not sector:
                return 0, ''
        except Exception:
            return 0, ''
        # Normalize sector name to match ETF names (z.B. 'Technology' direkt)
        s_upper = sector.upper().replace(' ', '_')
        for r in data.get('ranking', []):
            if r['sector'].upper() == s_upper:
                if r['rank'] <= 3:
                    return +5, f"Top-Sektor #{r['rank']} ({sector}, {r['score']:+.1f}%)"
                elif r['rank'] >= len(data['ranking']) - 2:
                    return -5, f"Bottom-Sektor #{r['rank']} ({sector}, {r['score']:+.1f}%)"
                return 0, ''
    except Exception:
        pass
    return 0, ''


def main():
    out = compute()
    if 'error' in out:
        print(f"❌ {out['error']}")
        return
    print(f"=== Sector Strength {out['computed_at'][:19]} ===")
    print(f"Top-3 (Rückenwind):  {', '.join(out['top3'])}")
    print(f"Bottom-3 (Gegenwind): {', '.join(out['bottom3'])}")
    print("\nFull Ranking:")
    for r in out['ranking']:
        print(f"  #{r['rank']:2}  {r['sector']:24}  {r['etf']}  "
              f"5d={r['ret_5d']:+.2f}%  20d={r['ret_20d']:+.2f}%  score={r['score']:+.2f}")


if __name__ == '__main__':
    main()
