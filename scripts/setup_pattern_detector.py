#!/usr/bin/env python3
"""
setup_pattern_detector.py — Phase 45ao Layer 5 (Victor 2026-05-11).

Technische Pattern-Erkennung auf der Watchlist (aus Strategien + Drilldown).
Erkennt:
  - PULLBACK_EMA10: Aktie über EMA10 nach Breakout, leichter Rücksetzer
  - BOLLINGER_SQUEEZE: Bands eng → Volatility-Expansion-Setup
  - VOLUME_CLIMAX_REVERSAL: extremes Volumen + Reversal-Bar
  - RANGE_BREAK: Konsolidierungsausbruch mit Volumen
  - GAP_FOLLOWTHROUGH: Gap-Up + Halt (kein Fade)

Output: data/setup_signals.jsonl (eine Zeile pro erkanntes Pattern).
Run: alle 30 Minuten während US-Marktzeit (15:30-22:00 CEST Mo-Fr).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))

PULSE_FILE = WS / 'data' / 'market_pulse_latest.json'
STRATS_FILE = WS / 'data' / 'strategies.json'
SIGNALS_LOG = WS / 'data' / 'setup_signals.jsonl'


def _ema(values: list, period: int) -> list:
    if len(values) < period: return [None] * len(values)
    k = 2 / (period + 1)
    out = [None] * (period - 1)
    sma = sum(values[:period]) / period
    out.append(sma)
    for i in range(period, len(values)):
        out.append(values[i] * k + out[-1] * (1 - k))
    return out


def _bollinger(values: list, period: int = 20, std_mult: float = 2.0):
    if len(values) < period: return None, None, None
    recent = values[-period:]
    mid = sum(recent) / period
    var = sum((v - mid) ** 2 for v in recent) / period
    sd = var ** 0.5
    return mid - std_mult * sd, mid, mid + std_mult * sd


def detect_patterns(ticker: str) -> list[dict]:
    """Lade Daten + suche nach Patterns. Returns list of pattern-dicts."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        h = t.history(period='60d')
        if len(h) < 30: return []
    except Exception:
        return []

    closes = h['Close'].tolist()
    highs = h['High'].tolist()
    lows = h['Low'].tolist()
    volumes = h['Volume'].tolist()

    last_close = closes[-1]
    last_high = highs[-1]
    last_low = lows[-1]
    last_vol = volumes[-1]
    prev_close = closes[-2]

    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = last_vol / max(avg_vol_20, 1)

    patterns = []

    # 1. PULLBACK_EMA10
    ema10 = _ema(closes, 10)
    ema20 = _ema(closes, 20)
    if ema10[-1] and ema20[-1]:
        # Uptrend: EMA10 > EMA20
        # Last close zwischen EMA10 und 5d-High → Pullback
        high_5d = max(highs[-5:])
        chg_5d = (closes[-1] - closes[-5]) / closes[-5] * 100
        if (closes[-1] > ema20[-1] and ema10[-1] > ema20[-1]
              and chg_5d > 2 and chg_5d < 8
              and closes[-1] < high_5d * 0.98
              and closes[-1] > ema10[-1] * 0.97):
            patterns.append({
                'pattern': 'PULLBACK_EMA10',
                'confidence': 0.7,
                'last_close': round(last_close, 2),
                'ema10': round(ema10[-1], 2),
                'ema20': round(ema20[-1], 2),
                'high_5d': round(high_5d, 2),
                'entry_hint': f'Bruch über {round(high_5d, 2)} mit Volumen',
                'stop_hint': f'Stop unter EMA20 ({round(ema20[-1] * 0.99, 2)})',
            })

    # 2. BOLLINGER_SQUEEZE
    bb_low, bb_mid, bb_high = _bollinger(closes, 20)
    if bb_low and bb_mid:
        bb_width = (bb_high - bb_low) / bb_mid * 100
        if bb_width < 4:  # sehr enge Bänder = Squeeze
            patterns.append({
                'pattern': 'BOLLINGER_SQUEEZE',
                'confidence': 0.55,
                'bb_width_pct': round(bb_width, 2),
                'bb_high': round(bb_high, 2),
                'bb_low': round(bb_low, 2),
                'last_close': round(last_close, 2),
                'entry_hint': f'Bruch über {round(bb_high, 2)} oder unter {round(bb_low, 2)}',
            })

    # 3. VOLUME_CLIMAX_REVERSAL
    if vol_ratio > 2.5:
        # Down-Day mit Vol-Spike + Long-Lower-Wick → Reversal
        body = abs(last_close - prev_close)
        lower_wick = (min(last_close, prev_close) - last_low)
        if lower_wick > body * 1.5 and last_close > prev_close:
            patterns.append({
                'pattern': 'VOLUME_CLIMAX_REVERSAL_BULL',
                'confidence': 0.6,
                'vol_ratio': round(vol_ratio, 1),
                'last_close': round(last_close, 2),
                'entry_hint': f'Über Today-High {round(last_high, 2)}',
                'stop_hint': f'Unter Today-Low {round(last_low, 2)}',
            })

    # 4. RANGE_BREAK
    high_20 = max(highs[-21:-1])  # vorige 20 days, ohne heute
    low_20 = min(lows[-21:-1])
    range_pct = (high_20 - low_20) / low_20 * 100 if low_20 > 0 else 0
    if range_pct < 8 and last_close > high_20 and vol_ratio > 1.3:
        patterns.append({
            'pattern': 'RANGE_BREAK_UP',
            'confidence': 0.65,
            'range_pct': round(range_pct, 2),
            'high_20': round(high_20, 2),
            'last_close': round(last_close, 2),
            'vol_ratio': round(vol_ratio, 1),
            'entry_hint': f'Bereits ausgebrochen — Pullback auf {round(high_20, 2)} abwarten',
            'stop_hint': f'Stop unter {round(high_20 * 0.97, 2)}',
        })

    return patterns


def get_watchlist_tickers() -> set[str]:
    """Tickers aus aktiven Strategien + Top-Drilldown-Komponenten."""
    tickers = set()
    # Aus strategies.json
    try:
        s = json.loads(STRATS_FILE.read_text(encoding='utf-8'))
        for sid, meta in s.items():
            if not isinstance(meta, dict): continue
            if meta.get('status') != 'active': continue
            for t in (meta.get('tickers') or meta.get('ticker_universe') or []):
                if t and isinstance(t, str):
                    tickers.add(t.upper())
    except Exception: pass
    # Aus market_pulse drilldowns
    try:
        p = json.loads(PULSE_FILE.read_text(encoding='utf-8'))
        for etf, comps in (p.get('drilldowns') or {}).items():
            for c in comps:
                tickers.add(c['ticker'].upper())
    except Exception: pass
    return tickers


def main() -> int:
    tickers = get_watchlist_tickers()
    print(f'Watchlist: {len(tickers)} tickers')

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    n_signals = 0
    SIGNALS_LOG.parent.mkdir(parents=True, exist_ok=True)
    for t in sorted(tickers):
        try:
            patterns = detect_patterns(t)
            for p in patterns:
                signal = {'ts': now, 'ticker': t, **p}
                with open(SIGNALS_LOG, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(signal, ensure_ascii=False) + '\n')
                n_signals += 1
                print(f'  📊 {t}: {p["pattern"]} conf={p["confidence"]}')
        except Exception as e:
            print(f'  WARN {t}: {e}', file=sys.stderr)

    print(f'Total signals detected: {n_signals}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
