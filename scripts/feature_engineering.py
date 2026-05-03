#!/usr/bin/env python3
"""
feature_engineering.py — Phase 45c (Sprint 2): Feature-Engineering-Pipeline.

Berechnet 30+ standardisierte Features pro Ticker auf Basis von OHLC-Daten.
Features werden taeglich nach Markt-Close in features-Tabelle geschrieben
und sind die Grundlage fuer Sprint 3 (XGBoost-Win-Prediction).

Feature-Kategorien:
  Technical (12): RSI, MACD, MACD-Signal, BB-Position, ATR-Pct,
                  Volume-Ratio, Price-vs-EMA20/50/200, ADX, Stochastic
  Trend (5):      5d/10d/20d/60d Returns, Trend-Direction
  Momentum (4):   Rate-of-Change, Higher-Highs-Count, Pullback-from-High
  Volatility (3): Realized-Vol-20d, Vol-Regime, ATR-Trend
  Macro-Context (4): VIX-Quartile, DXY-Change, 10Y-Yield-Slope, BrentChange
  Catalyst (3):   Days-to-Earnings, FOMC-Distance, Macro-Event-Recent
  Sentiment (LLM-augmented, 2): News-Sentiment-Score, News-Volume

Output:
  features-Tabelle in trading.db (ticker, date, feature_name, value)
  data/feature_metadata.json (feature-Namen, Statistik, Importance-Slots)

Run: python3 scripts/feature_engineering.py [--ticker EQNR.OL]
"""
from __future__ import annotations
import argparse, json, math, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
META = WS / 'data' / 'feature_metadata.json'

ALL_FEATURES = [
    # Technical
    'rsi_14', 'macd', 'macd_signal', 'macd_hist',
    'bb_position', 'atr_pct', 'volume_ratio',
    'price_vs_ema20', 'price_vs_ema50', 'price_vs_ema200',
    'adx_14', 'stoch_k',
    # Trend
    'ret_5d', 'ret_10d', 'ret_20d', 'ret_60d', 'trend_direction',
    # Momentum
    'roc_10', 'higher_highs_5', 'pullback_from_20d_high', 'distance_from_52w_high',
    # Volatility
    'realized_vol_20d', 'vol_regime', 'atr_trend',
    # Macro
    'vix_quartile', 'dxy_5d_chg', 'yield_10y_5d_chg', 'brent_5d_chg',
    # Catalyst
    'days_to_next_earnings', 'days_since_macro_event', 'macro_burst_recent',
]


def _ensure_table(c: sqlite3.Connection):
    c.execute('''
        CREATE TABLE IF NOT EXISTS features (
            ticker TEXT, date TEXT, feature_name TEXT, value REAL,
            PRIMARY KEY (ticker, date, feature_name)
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_feat_ticker_date ON features(ticker, date)')
    c.commit()


def _load_bars(c: sqlite3.Connection, ticker: str, days: int = 250) -> list[dict]:
    rows = c.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker=? ORDER BY date DESC LIMIT ?", (ticker, days)
    ).fetchall()
    bars = []
    for r in reversed(rows):  # chronologisch
        bars.append({'date': r[0], 'open': float(r[1] or 0),
                      'high': float(r[2] or 0), 'low': float(r[3] or 0),
                      'close': float(r[4] or 0), 'volume': float(r[5] or 0)})
    return bars


def _ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period: return [None] * len(values)
    k = 2 / (period + 1)
    ema = [None] * (period - 1)
    sma = sum(values[:period]) / period
    ema.append(sma)
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0: return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 2)


def _macd(closes: list[float]) -> tuple[float, float, float]:
    if len(closes) < 35: return 0, 0, 0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [(a-b) if (a is not None and b is not None) else None
                 for a, b in zip(ema12, ema26)]
    valid = [v for v in macd_line if v is not None]
    if len(valid) < 9: return 0, 0, 0
    signal = _ema(valid, 9)
    macd_v = round(valid[-1], 4)
    signal_v = round(signal[-1] if signal[-1] else 0, 4)
    return macd_v, signal_v, round(macd_v - signal_v, 4)


def _bollinger_position(closes: list[float], period: int = 20) -> float:
    """Returns position within BB: 0=lower, 0.5=middle, 1=upper."""
    if len(closes) < period: return 0.5
    sma = sum(closes[-period:]) / period
    var = sum((c - sma)**2 for c in closes[-period:]) / period
    sd = math.sqrt(var)
    if sd == 0: return 0.5
    upper, lower = sma + 2*sd, sma - 2*sd
    pos = (closes[-1] - lower) / (upper - lower) if upper > lower else 0.5
    return round(max(0, min(1, pos)), 3)


def _atr_pct(bars: list[dict], period: int = 14) -> float:
    if len(bars) < period + 1: return 0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]['high'], bars[i]['low'], bars[i-1]['close']
        tr = max(h-l, abs(h-pc), abs(l-pc))
        trs.append(tr)
    atr = sum(trs[-period:]) / period
    return round(atr / bars[-1]['close'] * 100, 3) if bars[-1]['close'] else 0


def _volume_ratio(bars: list[dict], period: int = 20) -> float:
    if len(bars) < period + 1: return 1
    avg = sum(b['volume'] for b in bars[-period-1:-1]) / period
    return round(bars[-1]['volume'] / avg, 2) if avg > 0 else 1


def _price_vs_ema(closes: list[float], period: int) -> float:
    """% Distance from EMA (negative = below)."""
    e = _ema(closes, period)
    if e[-1] is None or closes[-1] == 0: return 0
    return round((closes[-1] - e[-1]) / e[-1] * 100, 2)


def _adx(bars: list[dict], period: int = 14) -> float:
    """Wilders ADX simplified."""
    if len(bars) < period * 2: return 0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(bars)):
        h, l = bars[i]['high'], bars[i]['low']
        ph, pl, pc = bars[i-1]['high'], bars[i-1]['low'], bars[i-1]['close']
        up = h - ph; down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    if not trs[-period:]: return 0
    atr = sum(trs[-period:]) / period
    plus_di = 100 * sum(plus_dm[-period:]) / period / atr if atr else 0
    minus_di = 100 * sum(minus_dm[-period:]) / period / atr if atr else 0
    if plus_di + minus_di == 0: return 0
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return round(dx, 2)


def _stoch_k(bars: list[dict], period: int = 14) -> float:
    if len(bars) < period: return 50
    highest = max(b['high'] for b in bars[-period:])
    lowest = min(b['low'] for b in bars[-period:])
    if highest == lowest: return 50
    return round(100 * (bars[-1]['close'] - lowest) / (highest - lowest), 1)


def _ret_n_days(closes: list[float], n: int) -> float:
    if len(closes) < n + 1: return 0
    if closes[-n-1] == 0: return 0
    return round((closes[-1] - closes[-n-1]) / closes[-n-1] * 100, 2)


def _trend_direction(closes: list[float]) -> int:
    """1 = up, -1 = down, 0 = sideways. Basiert auf 20d-EMA-Slope."""
    e = _ema(closes, 20)
    if e[-5] is None or e[-1] is None: return 0
    diff = e[-1] - e[-5]
    if abs(diff) < 0.01 * e[-1]: return 0
    return 1 if diff > 0 else -1


def _higher_highs(bars: list[dict], n: int = 5) -> int:
    """Count of higher highs in last n bars."""
    if len(bars) < n: return 0
    return sum(1 for i in range(1, n) if bars[-i]['high'] > bars[-i-1]['high'])


def _pullback_from_high(closes: list[float], period: int = 20) -> float:
    if len(closes) < period: return 0
    recent_high = max(closes[-period:])
    if recent_high == 0: return 0
    return round((closes[-1] - recent_high) / recent_high * 100, 2)


def _distance_52w_high(closes: list[float]) -> float:
    if len(closes) < 252: return 0
    high_52w = max(closes[-252:])
    if high_52w == 0: return 0
    return round((closes[-1] - high_52w) / high_52w * 100, 2)


def _realized_vol(closes: list[float], period: int = 20) -> float:
    if len(closes) < period + 1: return 0
    rets = [(closes[i] - closes[i-1]) / closes[i-1]
            for i in range(-period, 0) if closes[i-1]]
    if not rets: return 0
    mean = sum(rets) / len(rets)
    var = sum((r - mean)**2 for r in rets) / len(rets)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 2)  # annualized %


def _macro_features(c: sqlite3.Connection) -> dict:
    """Cross-asset Macro-Features aus commodity_prices.json + macro_events."""
    out = {'vix_quartile': 2, 'dxy_5d_chg': 0, 'yield_10y_5d_chg': 0,
           'brent_5d_chg': 0, 'days_since_macro_event': 99,
           'macro_burst_recent': 0}
    cmd = WS / 'data' / 'commodity_prices.json'
    if cmd.exists():
        try:
            d = json.loads(cmd.read_text(encoding='utf-8'))
            p = d.get('prices', {})
            vix = (p.get('^VIX') or {}).get('spot')
            if vix:
                out['vix_quartile'] = (1 if vix < 15 else
                                        2 if vix < 25 else
                                        3 if vix < 40 else 4)
            out['dxy_5d_chg'] = (p.get('DX-Y.NYB') or {}).get('chg_7d_pct', 0)
            out['yield_10y_5d_chg'] = (p.get('^TNX') or {}).get('chg_7d_pct', 0)
            out['brent_5d_chg'] = (p.get('BZ=F') or {}).get('chg_7d_pct', 0)
        except Exception: pass
    try:
        n_recent = c.execute(
            "SELECT COUNT(*) FROM macro_events WHERE detected_at >= datetime('now','-24 hours')"
        ).fetchone()[0]
        out['macro_burst_recent'] = n_recent
        last = c.execute(
            "SELECT detected_at FROM macro_events ORDER BY detected_at DESC LIMIT 1"
        ).fetchone()
        if last and last[0]:
            try:
                ld = datetime.fromisoformat(last[0].replace('Z','+00:00'))
                out['days_since_macro_event'] = (datetime.now(timezone.utc) - ld).days
            except Exception: pass
    except Exception: pass
    return out


def _catalyst_features(c: sqlite3.Connection, ticker: str) -> dict:
    out = {'days_to_next_earnings': 999}
    try:
        row = c.execute(
            "SELECT date FROM earnings_calendar WHERE ticker=? "
            "AND date >= date('now') ORDER BY date ASC LIMIT 1", (ticker,)
        ).fetchone()
        if row and row[0]:
            d = datetime.strptime(row[0], '%Y-%m-%d')
            out['days_to_next_earnings'] = (d - datetime.now()).days
    except Exception: pass
    return out


def compute_features(ticker: str) -> dict:
    """Berechnet alle Features fuer Ticker as-of-now."""
    if not DB.exists(): return {}
    c = sqlite3.connect(str(DB))
    bars = _load_bars(c, ticker, 250)
    if len(bars) < 50:
        c.close()
        return {'error': f'insufficient_bars ({len(bars)})'}
    closes = [b['close'] for b in bars]

    feat = {
        'rsi_14': _rsi(closes, 14),
        'bb_position': _bollinger_position(closes, 20),
        'atr_pct': _atr_pct(bars, 14),
        'volume_ratio': _volume_ratio(bars, 20),
        'price_vs_ema20': _price_vs_ema(closes, 20),
        'price_vs_ema50': _price_vs_ema(closes, 50),
        'price_vs_ema200': _price_vs_ema(closes, 200) if len(closes) >= 200 else 0,
        'adx_14': _adx(bars, 14),
        'stoch_k': _stoch_k(bars, 14),
        'ret_5d': _ret_n_days(closes, 5),
        'ret_10d': _ret_n_days(closes, 10),
        'ret_20d': _ret_n_days(closes, 20),
        'ret_60d': _ret_n_days(closes, 60),
        'trend_direction': _trend_direction(closes),
        'roc_10': _ret_n_days(closes, 10),
        'higher_highs_5': _higher_highs(bars, 5),
        'pullback_from_20d_high': _pullback_from_high(closes, 20),
        'distance_from_52w_high': _distance_52w_high(closes),
        'realized_vol_20d': _realized_vol(closes, 20),
    }
    macd, sig, hist = _macd(closes)
    feat['macd'] = macd; feat['macd_signal'] = sig; feat['macd_hist'] = hist
    feat['vol_regime'] = (1 if feat['realized_vol_20d'] < 15 else
                          2 if feat['realized_vol_20d'] < 30 else 3)
    feat['atr_trend'] = 1 if feat['atr_pct'] > 3 else 0

    feat.update(_macro_features(c))
    feat.update(_catalyst_features(c, ticker))

    c.close()
    return feat


def persist_features(ticker: str, feat: dict) -> int:
    if not feat or 'error' in feat: return 0
    if not DB.exists(): return 0
    c = sqlite3.connect(str(DB))
    _ensure_table(c)
    today = datetime.now().strftime('%Y-%m-%d')
    n = 0
    for fname, val in feat.items():
        if val is None: continue
        try:
            c.execute(
                "INSERT OR REPLACE INTO features (ticker, date, feature_name, value) "
                "VALUES (?,?,?,?)", (ticker, today, fname, float(val))
            )
            n += 1
        except (ValueError, TypeError): pass
    c.commit(); c.close()
    return n


def _all_relevant_tickers() -> list[str]:
    """Sammle alle Tickers die wir tracken sollten."""
    out = set()
    if DB.exists():
        c = sqlite3.connect(str(DB))
        try:
            for r in c.execute("SELECT DISTINCT ticker FROM paper_portfolio").fetchall():
                if r[0]: out.add(r[0])
            for r in c.execute("SELECT DISTINCT ticker FROM prices "
                                "WHERE date >= date('now','-30 days')").fetchall():
                if r[0]: out.add(r[0])
        except Exception: pass
        c.close()
    sf = WS / 'data' / 'strategies.json'
    if sf.exists():
        try:
            d = json.loads(sf.read_text(encoding='utf-8'))
            for v in d.values():
                if isinstance(v, dict):
                    for t in v.get('tickers') or []:
                        out.add(t)
        except Exception: pass
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', help='nur einen Ticker')
    ap.add_argument('--all', action='store_true', help='alle relevanten Tickers')
    args = ap.parse_args()
    if args.ticker:
        feat = compute_features(args.ticker)
        n = persist_features(args.ticker, feat)
        print(f'{args.ticker}: {n} Features persisted')
        for k, v in feat.items(): print(f'  {k}: {v}')
        return 0
    if args.all:
        tickers = _all_relevant_tickers()
        total = 0
        for t in tickers:
            feat = compute_features(t)
            n = persist_features(t, feat)
            if n: total += n
            print(f'{t}: {n}')
        print(f'TOTAL: {total} feature-rows for {len(tickers)} tickers')
        return 0
    print('Usage: --ticker X or --all'); return 1


if __name__ == '__main__':
    sys.exit(main())
