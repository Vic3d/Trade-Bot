#!/usr/bin/env python3
"""
Mid-Term Election Year Bias — Phase 22
========================================
Statistik aus Dirk-Mueller-Video 22.04.2026:
  - S&P 500 Mid-Term-Election-Year Ø Drawdown: -16%
  - Nach Drawdown Ø Jahresgewinn: +36% (Median +39%)
  - USA ist 2026 im Mid-Term-Election-Year (Wahl Nov 2026)

Dieser Job prueft:
  1. Sind wir in einem Mid-Term-Election-Year? (gerade Jahr ohne Praesidentschaftswahl)
  2. Hat S&P 500 den statistischen Drawdown bereits hinter sich (>=8%)?
  3. Wenn ja → BULLISH-Bias aktiv mit +3 Conviction-Bonus

Schreibt data/midterm_bias.json, das vom conviction_scorer als +3 Bonus gelesen wird.

Scheduler: 1x woechentlich (z.B. Sonntag 23:00).
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'midterm_bias.json'
LOG = WS / 'data' / 'midterm_bias.log'


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec='seconds')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def is_midterm_year(year: int | None = None) -> bool:
    """
    US Mid-Term Elections: alle 4 Jahre, 2 Jahre nach Praesidentschafts-Wahl.
    Praesidentenwahlen: 2020, 2024, 2028, ...
    Mid-Term-Wahlen: 2018, 2022, 2026, 2030, ...
    """
    if year is None:
        year = date.today().year
    return year % 4 == 2  # 2022, 2026, 2030...


def _spy_drawdown_from_52w_high() -> tuple[float, float, float]:
    """Returns (drawdown_pct, current_close, high_52w). drawdown in decimal (-0.10 = -10%)."""
    if not DB.exists():
        return 0.0, 0.0, 0.0
    try:
        conn = sqlite3.connect(str(DB))
        # 52w = 252 Handelstage. Nur EIN Ticker — nicht mischen (SPY ETF vs ^GSPC Index).
        rows = []
        for tk in ('SPY', '^GSPC', 'SPX'):
            rows = conn.execute(
                "SELECT date, close FROM prices WHERE ticker = ? "
                "ORDER BY date DESC LIMIT 260",
                (tk,)
            ).fetchall()
            if rows:
                break
        conn.close()
        if not rows:
            return 0.0, 0.0, 0.0
        closes = [float(r[1]) for r in rows if r[1] is not None]
        if len(closes) < 20:
            return 0.0, 0.0, 0.0
        last = closes[0]
        high = max(closes[:252])
        dd = (last - high) / high if high > 0 else 0
        return dd, last, high
    except Exception as e:
        _log(f'ERR spy data: {e}')
        return 0.0, 0.0, 0.0


def build_bias() -> dict:
    today = date.today()
    year = today.year
    midterm = is_midterm_year(year)

    result = {
        'active': False,
        'bias': 'NEUTRAL',
        'conviction_bonus': 0,
        'year': year,
        'is_midterm_year': midterm,
        'updated_at': today.isoformat(),
        'reason': '',
        'stats': {
            'avg_drawdown_pct': -16,
            'avg_annual_return_pct': 36,
            'median_annual_return_pct': 39,
            'source': 'Dirk Mueller / Tradermacher Video 22.04.2026',
        }
    }

    if not midterm:
        result['reason'] = f'{year} ist kein Mid-Term-Year (naechster: {year + (2 - year % 4) % 4})'
        return result

    dd, last, high = _spy_drawdown_from_52w_high()
    result['spy_drawdown_pct'] = round(dd * 100, 2)
    result['spy_52w_high'] = round(high, 2)
    result['spy_last'] = round(last, 2)

    if dd <= -0.08:  # mindestens 8% Drawdown passiert
        result['active'] = True
        result['bias'] = 'BULLISH'
        result['conviction_bonus'] = 3
        result['reason'] = (
            f'Mid-Term-Year {year}: SPY {result["spy_drawdown_pct"]}% vom 52W-High — '
            f'statistisch Ø +36% Gewinn nach -16% Drawdown'
        )
    else:
        result['reason'] = (
            f'Mid-Term-Year {year}: SPY nur {result["spy_drawdown_pct"]}% vom 52W-High — '
            f'Drawdown noch nicht ausreichend (<8%) fuer Mean-Revert-Setup'
        )

    return result


def main():
    bias = build_bias()
    OUT.write_text(json.dumps(bias, indent=2, ensure_ascii=False), encoding='utf-8')
    _log(f'active={bias["active"]} bias={bias["bias"]} bonus={bias["conviction_bonus"]} '
         f'dd={bias.get("spy_drawdown_pct","?")}%')
    print(json.dumps(bias, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
