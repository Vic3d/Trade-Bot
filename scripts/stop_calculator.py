#!/usr/bin/env python3
"""
Stop Calculator — Phase 25
===========================
Berechnet adaptiven Stop-Loss basierend auf ATR (Average True Range)
statt -8% pauschal.

Logik:
  stop = entry × (1 - max(min_pct, atr_multiplier × atr%))

Default:
  - min_pct        = 0.05  (5% Mindestabstand)
  - atr_multiplier = 1.5
  - max_pct        = 0.10  (10% Maximalabstand — Hard Cap)

Vorteil:
  - Ruhige Aktien (low ATR) → enger Stop (z.B. 5%)
  - Volatile Aktien (high ATR) → weiter Stop bis Cap (z.B. 9-10%)
  - Verhindert Stop-Hunts durch normale Volatilität

Hook: autonomous_ceo + autonomous_scanner können `suggest_stop()` nutzen
  statt entry × 0.93.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'


def _atr_pct(ticker: str, period: int = 14) -> float | None:
    """Berechnet ATR% (ATR / Close × 100) der letzten `period` Tage."""
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT high, low, close FROM prices WHERE ticker=? "
            "ORDER BY date DESC LIMIT ?",
            (ticker.upper(), period + 1),
        ).fetchall()
        c.close()
        if len(rows) < period + 1:
            return None
        # rows[0] ist letzter Tag, rows[-1] ältester
        # Reverse für TR-Berechnung
        rows = list(reversed(rows))
        trs = []
        for i in range(1, len(rows)):
            h, l, _c = rows[i]
            prev_c = rows[i - 1][2]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        atr = sum(trs[-period:]) / period
        latest_close = rows[-1][2]
        if latest_close <= 0:
            return None
        return (atr / latest_close) * 100
    except Exception:
        return None


def suggest_stop(
    ticker: str,
    entry_price: float,
    min_pct: float = 0.05,
    max_pct: float = 0.10,
    atr_multiplier: float = 1.5,
) -> dict:
    """
    Liefert {'stop_price', 'stop_pct', 'method', 'reason'}.

    method:
      - 'atr'    : ATR-basiert (innerhalb [min_pct, max_pct])
      - 'min'    : Cap auf min_pct
      - 'max'    : Cap auf max_pct
      - 'fallback': ATR nicht berechenbar → entry × (1 - 0.07) = -7%
    """
    atr_pct = _atr_pct(ticker)
    if atr_pct is None:
        # Fallback: 7% (Mittel zwischen 5 und 8)
        stop_pct = 0.07
        return {
            'stop_price': round(entry_price * (1 - stop_pct), 4),
            'stop_pct': stop_pct,
            'method': 'fallback',
            'reason': 'ATR nicht berechenbar (zu wenig Daten)',
        }

    atr_stop_pct = (atr_pct / 100) * atr_multiplier  # z.B. 2.5% ATR × 1.5 = 3.75%
    if atr_stop_pct < min_pct:
        stop_pct = min_pct
        method = 'min'
        reason = f'ATR {atr_pct:.2f}% × {atr_multiplier} = {atr_stop_pct*100:.1f}% < min {min_pct*100:.0f}%'
    elif atr_stop_pct > max_pct:
        stop_pct = max_pct
        method = 'max'
        reason = f'ATR {atr_pct:.2f}% × {atr_multiplier} = {atr_stop_pct*100:.1f}% > max {max_pct*100:.0f}%'
    else:
        stop_pct = atr_stop_pct
        method = 'atr'
        reason = f'ATR {atr_pct:.2f}% × {atr_multiplier} = {stop_pct*100:.1f}%'

    return {
        'stop_price': round(entry_price * (1 - stop_pct), 4),
        'stop_pct': round(stop_pct, 4),
        'method': method,
        'reason': reason,
    }


def adjust_stop_if_too_wide(
    ticker: str,
    entry_price: float,
    proposed_stop: float,
    max_pct: float = 0.10,
) -> tuple[float, str]:
    """
    Passt den vorgeschlagenen Stop an wenn er weiter als max_pct ist.
    Returns (adjusted_stop, reason). Kein Adjust → reason = ''.
    """
    if proposed_stop <= 0 or entry_price <= 0:
        return proposed_stop, ''
    pct = (entry_price - proposed_stop) / entry_price
    if pct > max_pct:
        new_stop = round(entry_price * (1 - max_pct), 4)
        return new_stop, f'Stop war {pct*100:.1f}% (>{max_pct*100:.0f}% Cap) → adjusted to {new_stop:.2f}'
    return proposed_stop, ''


def main():
    import sys
    if len(sys.argv) < 3:
        print('Usage: python3 stop_calculator.py TICKER ENTRY_PRICE')
        sys.exit(1)
    ticker = sys.argv[1]
    entry = float(sys.argv[2])
    r = suggest_stop(ticker, entry)
    print(f"=== Stop-Suggestion {ticker} @ {entry} ===")
    print(f"Stop:     {r['stop_price']}  ({r['stop_pct']*100:.2f}% unter Entry)")
    print(f"Method:   {r['method']}")
    print(f"Reason:   {r['reason']}")


if __name__ == '__main__':
    main()
