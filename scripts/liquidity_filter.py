#!/usr/bin/env python3
"""
liquidity_filter.py — Phase 45ae (Tradermacher-Methodik, Hebel 1).

Hard-Filter gegen illiquide/dünn gehandelte Tickers BEFORE Trade-Entry.
Lernung: 5 historische Phantom-Tick-Rollbacks (PYPL, SMCI, UEC, MOS, PAAS)
betrafen alle Tickers mit suboptimaler Liquidität.

Schwellen (Dirk-konservativ, halbiert für globale Reichweite):
- Marketcap > 750 Mio USD
- ADR (20d Average Daily Range) > 3%
- Avg Daily Volume > 1M Shares (20d)
- Preis > 5 USD-Equivalent

Cache: data/liquidity_cache.json (24h TTL — yfinance .info ist langsam).
Bypass: Manual/Victor/CLI-Sources umgehen den Filter (bewusst).

Integration: paper_trade_engine.py Guard 0g (nach Regime-Block).
"""
from __future__ import annotations
import json, os, sqlite3, time
from pathlib import Path
from typing import Tuple

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
CACHE = WS / 'data' / 'liquidity_cache.json'

# Schwellen (config-justierbar)
MIN_MARKETCAP_USD = 750_000_000
MIN_ADR_PCT       = 0.8       # Tote/stillgelegte Aktien fangen, nicht stabile Mega-Caps
MIN_AVG_VOL       = 1_000_000  # Shares pro Tag (20d)
MIN_PRICE_USD     = 5.0
CACHE_TTL_S       = 24 * 3600  # 24h

# Tickers die immer durchgehen (Indizes, Mega-Caps die yfinance manchmal nicht erkennt)
WHITELIST = {'SPY', 'QQQ', 'IWM', 'DIA', 'VIX'}


def _load_cache() -> dict:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=2), encoding='utf-8')
    except Exception:
        pass


def _get_marketcap(ticker: str) -> float | None:
    """Hole marketcap via yfinance (cached). Returns USD."""
    cache = _load_cache()
    entry = cache.get(ticker)
    now = time.time()
    if entry and (now - entry.get('ts', 0)) < CACHE_TTL_S:
        return entry.get('marketcap')
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        mc = info.get('marketCap')
        if mc:
            cache[ticker] = {'marketcap': float(mc), 'ts': now}
            _save_cache(cache)
            return float(mc)
    except Exception:
        pass
    return None


def _get_volume_and_adr(ticker: str, lookback: int = 20) -> tuple[float | None, float | None, float | None]:
    """Aus prices-Tabelle: (avg_volume, adr_pct, last_close)."""
    if not DB.exists():
        return None, None, None
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT close, high, low, volume FROM prices "
            "WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker, lookback)
        ).fetchall()
        c.close()
    except Exception:
        return None, None, None
    if len(rows) < 5:
        return None, None, None
    vols = [(r['volume'] or 0) for r in rows]
    avg_vol = sum(vols) / len(vols)
    # ADR = avg((high-low)/close * 100)
    ranges = []
    for r in rows:
        if r['close'] and r['high'] and r['low'] and r['close'] > 0:
            ranges.append((r['high'] - r['low']) / r['close'] * 100)
    adr_pct = sum(ranges) / len(ranges) if ranges else None
    last_close = rows[0]['close'] if rows else None
    return avg_vol, adr_pct, last_close


def passes_liquidity(ticker: str, current_price_usd: float | None = None) -> Tuple[bool, str, dict]:
    """
    Returns (passes, reason, details).

    passes=True  → Trade darf rein
    passes=False → reason erklärt warum + details enthält Werte
    """
    t = (ticker or '').upper().strip()
    if not t:
        return False, 'empty_ticker', {}
    if t in WHITELIST:
        return True, 'whitelist', {'ticker': t}

    # Non-USD Tickers (Suffix wie .DE, .OL, .L) → Marketcap-Check skip
    # (yfinance liefert Marketcap teilweise inkonsistent für Auslandsbörsen)
    is_non_usd = '.' in t

    details: dict = {'ticker': t}

    # 1. Marketcap (nur US-Tickers strict prüfen)
    if not is_non_usd:
        mc = _get_marketcap(t)
        details['marketcap_usd'] = mc
        if mc is not None and mc < MIN_MARKETCAP_USD:
            return False, f'marketcap_below_threshold ({mc/1e6:.0f}M < {MIN_MARKETCAP_USD/1e6:.0f}M)', details

    # 2. Volume + ADR aus DB
    avg_vol, adr_pct, last_close = _get_volume_and_adr(t)
    details['avg_volume_20d'] = avg_vol
    details['adr_pct_20d'] = adr_pct
    details['last_close'] = last_close

    if avg_vol is None:
        # Keine Preisdaten → defensiv DURCHLASSEN, anderer Guard fängt es
        # (sonst neue Tickers ohne History blockiert, das wollen wir nicht)
        return True, 'no_price_history_skip', details

    if avg_vol < MIN_AVG_VOL and not is_non_usd:
        return False, f'volume_too_low ({avg_vol:.0f} < {MIN_AVG_VOL})', details

    if adr_pct is not None and adr_pct < MIN_ADR_PCT:
        return False, f'adr_too_low ({adr_pct:.2f}% < {MIN_ADR_PCT}%)', details

    # 3. Preis-Floor
    price_check = current_price_usd if current_price_usd else last_close
    if price_check is not None and price_check < MIN_PRICE_USD:
        # Non-USD: 5 EUR ≈ 5 USD-Schwelle bleibt grob OK
        return False, f'price_below_floor ({price_check:.2f} < {MIN_PRICE_USD})', details

    return True, 'passes_all_checks', details


def main() -> int:
    """CLI: python liquidity_filter.py TICKER1 [TICKER2 ...]"""
    import sys
    tickers = sys.argv[1:] or ['NVDA', 'AAPL', 'PYPL', 'SMCI']
    for t in tickers:
        ok, reason, det = passes_liquidity(t)
        print(f"{t}: {'PASS' if ok else 'FAIL'} {reason}")
        for k, v in det.items():
            print(f"    {k}: {v}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
