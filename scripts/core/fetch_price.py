#!/usr/bin/env python3
"""
fetch_price.py — Sicherer Yahoo Finance Preis-Fetch
=====================================================
Verhindert Futures-Kontrakt-Rollover-Fehler.

Problem: Bei =F Symbolen (CL=F, BZ=F, GC=F) liefert Yahoo
`chartPreviousClose` manchmal den Preis des ALTEN Kontrakts.
Das erzeugt falsche Tages-%-Änderungen (z.B. scheinbares -28%).

Lösung: Für =F Symbole immer den ersten Intraday-Open als
Referenz nutzen (interval=5m, range=1d). Das ist der echte
Tagesbeginn des AKTUELLEN Kontrakts.

USAGE:
    from core.fetch_price import safe_price, safe_batch

    data = safe_price('CL=F')   # {'price': 112.06, 'change_pct': +6.9, ...}
    batch = safe_batch(['CL=F', 'BZ=F', '^VIX', 'EURUSD=X'])

2026-04-03 | TRA-178 | Fix Futures-Rollover-Artefakt
"""

import json, time, urllib.request, urllib.parse
from typing import Optional


FUTURES_SUFFIXES = ('=F',)   # CL=F, BZ=F, GC=F, SI=F, HG=F ...


def _is_futures(ticker: str) -> bool:
    return any(ticker.endswith(s) for s in FUTURES_SUFFIXES)


def safe_price(ticker: str, timeout: int = 8, retries: int = 2) -> Optional[dict]:
    """
    Holt aktuellen Preis sicher von Yahoo Finance.

    Für Futures-Symbole (=F): nutzt ersten Intraday-Open als Referenz
    statt chartPreviousClose → kein Rollover-Artefakt.

    Returns dict:
        price      float  — aktueller Preis
        change_pct float  — Tages-%-Änderung (korrekt auch bei Rollover)
        prev_ref   float  — Referenzpreis für die %-Berechnung
        currency   str    — 'USD', 'EUR', etc.
        is_futures bool   — True wenn =F Symbol
    oder None bei Fehler.
    """
    enc = urllib.parse.quote(ticker)
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{enc}?interval=5m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)

            result = data['chart']['result'][0]
            meta   = result['meta']
            quote  = result['indicators']['quote'][0]

            price = meta.get('regularMarketPrice', 0)
            ccy   = meta.get('currency', 'USD')

            # Intraday-Daten extrahieren
            opens  = [v for v in (quote.get('open')  or []) if v is not None]
            closes = [v for v in (quote.get('close') or []) if v is not None]
            highs  = [v for v in (quote.get('high')  or []) if v is not None]
            lows   = [v for v in (quote.get('low')   or []) if v is not None]

            # ── Preis + Referenzpreis-Wahl ──────────────────────────────────
            # Futures-Rollover-Problem: Bei =F Symbolen kann regularMarketPrice
            # im Meta vom NEUEN Kontrakt sein, während Intraday-Daten den ALTEN
            # Kontrakt zeigen (oder umgekehrt). Lösung: für Futures ausschließlich
            # Intraday-Daten verwenden — kein Meta-Preis, kein chartPreviousClose.
            futures = _is_futures(ticker)
            if futures and closes:
                # Aktueller Preis = letzter Intraday-Close (gleicher Kontrakt)
                price    = closes[-1]
                # Referenz  = erster Intraday-Open (Tagesbeginn, gleicher Kontrakt)
                prev_ref = opens[0] if opens else closes[0]
            else:
                # Aktien/ETFs/FX: Meta-Daten sind zuverlässig
                prev_ref = meta.get('chartPreviousClose',
                           meta.get('previousClose', price))

            change_pct = ((price - prev_ref) / prev_ref * 100) if prev_ref else 0.0

            return {
                'price':      price,
                'change_pct': round(change_pct, 2),
                'prev_ref':   prev_ref,
                'currency':   ccy,
                'is_futures': futures,
                'closes':     closes,
                'opens':      opens,
                'highs':      highs,
                'lows':       lows,
            }

        except Exception as e:
            if attempt < retries:
                time.sleep(1.5 ** attempt)
            else:
                return None

    return None


def safe_batch(tickers: list, delay: float = 0.12) -> dict:
    """
    Holt Preise für mehrere Ticker.
    Returns {ticker: data_dict_or_None}.
    """
    results = {}
    for t in tickers:
        results[t] = safe_price(t)
        if len(tickers) > 1:
            time.sleep(delay)
    return results


def to_eur(price: float, currency: str, fx: dict) -> Optional[float]:
    """Konvertiert Preis zu EUR anhand FX-Dict {'EURUSD': 1.15, 'EURNOK': 11.0, ...}."""
    if price is None:
        return None
    if currency == 'EUR':
        return price
    elif currency == 'USD':
        return price / fx.get('EURUSD', 1.15)
    elif currency in ('GBp', 'GBX'):
        return (price / 100) / fx.get('EURGBP', 0.86)
    elif currency == 'GBP':
        return price / fx.get('EURGBP', 0.86)
    elif currency == 'NOK':
        return price / fx.get('EURNOK', 11.0)
    return price


# ── Quick-Test ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('=== Futures-Rollover-Test ===')
    for ticker in ['CL=F', 'BZ=F', 'GC=F', '^VIX', 'EURUSD=X']:
        d = safe_price(ticker)
        if d:
            tag = '⚠️ FUTURES' if d['is_futures'] else '      Aktie'
            print(f'  {tag} | {ticker:<12} | ${d["price"]:>8.2f} | {d["change_pct"]:>+6.2f}%'
                  f'  (ref: ${d["prev_ref"]:.2f})')
        else:
            print(f'  FEHLER: {ticker}')
