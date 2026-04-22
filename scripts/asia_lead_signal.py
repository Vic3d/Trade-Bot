#!/usr/bin/env python3
"""
Asia Lead Signal — Phase 25
============================
Berechnet täglich vor Morning-Brief (07:00 CET) das Asia-Sentiment als
Frühindikator für US/EU-Open.

Indizes (via yfinance):
  - ^N225  Nikkei 225 (Japan)
  - ^HSI   Hang Seng (Hong Kong)
  - ^KS11  KOSPI (Korea)
  - 000001.SS Shanghai Composite (China)

Output: data/asia_lead.json
{
  "computed_at": "...",
  "session_date": "2026-04-19",
  "n225": {"close": 38500, "change_pct": -1.2},
  "avg_change": -0.8,
  "signal": "BEARISH" | "NEUTRAL" | "BULLISH",
  "us_gap_forecast": "down" | "neutral" | "up",
  "recommendation": "Halte Cash, evtl. Morgen-Block verlängern" | ...
}

Hook: Morning-Brief + entry_gate können das nutzen.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
OUT = DATA / 'asia_lead.json'

INDICES = {
    '^N225':      'Nikkei 225',
    '^HSI':       'Hang Seng',
    '^KS11':      'KOSPI',
    '000001.SS':  'Shanghai Composite',
}


def _fetch_change(ticker: str) -> dict | None:
    import math
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        h = t.history(period='10d', auto_adjust=False)
        # NaN-Zeilen entfernen (yfinance liefert manchmal Lücken)
        h = h.dropna(subset=['Close'])
        if len(h) < 2:
            return None
        last = float(h['Close'].iloc[-1])
        prev = float(h['Close'].iloc[-2])
        if math.isnan(last) or math.isnan(prev) or prev <= 0:
            return None
        change = (last - prev) / prev * 100
        return {'close': round(last, 2), 'change_pct': round(change, 2)}
    except Exception as e:
        print(f'[asia_lead] {ticker} fail: {e}')
        return None


def compute() -> dict:
    out: dict = {
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'session_date': datetime.now(_BERLIN).strftime('%Y-%m-%d'),
    }
    changes: list[float] = []
    for tk, name in INDICES.items():
        d = _fetch_change(tk)
        if d:
            out[tk.lstrip('^').lower().replace('.', '_')] = {**d, 'name': name}
            changes.append(d['change_pct'])

    if not changes:
        out['signal'] = 'NO_DATA'
        out['avg_change'] = 0.0
        out['us_gap_forecast'] = 'neutral'
        out['recommendation'] = 'Keine Asia-Daten verfügbar'
        OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
        return out

    avg = sum(changes) / len(changes)
    out['avg_change'] = round(avg, 2)

    if avg <= -1.5:
        out['signal'] = 'BEARISH'
        out['us_gap_forecast'] = 'down'
        out['recommendation'] = (
            'Asia stark negativ — US-Open vermutlich rot. Morgen-Block ggf. bis 13h ausweiten. '
            'Keine FOMO-Entries.'
        )
    elif avg <= -0.5:
        out['signal'] = 'WEAK_BEARISH'
        out['us_gap_forecast'] = 'down'
        out['recommendation'] = 'Asia leicht negativ — vorsichtig bei Long-Entries vor 14h.'
    elif avg >= 1.5:
        out['signal'] = 'BULLISH'
        out['us_gap_forecast'] = 'up'
        out['recommendation'] = (
            'Asia stark positiv — US-Open vermutlich grün. Tier-A Setups dürfen früher entered werden.'
        )
    elif avg >= 0.5:
        out['signal'] = 'WEAK_BULLISH'
        out['us_gap_forecast'] = 'up'
        out['recommendation'] = 'Asia leicht positiv — normales Trading-Regime.'
    else:
        out['signal'] = 'NEUTRAL'
        out['us_gap_forecast'] = 'neutral'
        out['recommendation'] = 'Asia neutral — keine besonderen Anpassungen.'

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def get_signal() -> dict | None:
    """Liefert das aktuelle Signal für andere Module."""
    try:
        if not OUT.exists():
            return None
        return json.loads(OUT.read_text(encoding='utf-8'))
    except Exception:
        return None


def main():
    out = compute()
    print(f"=== Asia Lead Signal {out['session_date']} ===")
    for k, v in out.items():
        if isinstance(v, dict) and 'change_pct' in v:
            arrow = '🔴' if v['change_pct'] < 0 else '🟢'
            print(f"  {arrow} {v.get('name', k):20}  {v['change_pct']:+.2f}%  ({v['close']})")
    print(f"\nDurchschnitt: {out['avg_change']:+.2f}%")
    print(f"Signal:      {out['signal']}")
    print(f"US-Gap:      {out['us_gap_forecast']}")
    print(f"Empfehlung:  {out['recommendation']}")


if __name__ == '__main__':
    main()
