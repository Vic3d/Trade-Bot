"""
trademind/core/market_data.py — Marktdaten (Preise, FX, ATR)

Einzige Stelle für Yahoo Finance Requests.
Rate-limiting: 0.3s sleep zwischen Requests.

Usage:
    from trademind.core.market_data import get_price_yahoo, to_eur, get_atr

    price, currency = get_price_yahoo('NVDA')
    price_eur = to_eur(price, currency)
    atr = get_atr('NVDA')
"""
import json
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

from trademind.core.config import FX_FALLBACK

_RATE_LIMIT_SLEEP = 0.3   # Sekunden zwischen Yahoo-Requests
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 TradeMind/2.0"}

# FX-Cache: {currency: rate} — einfacher In-Process-Cache
_fx_cache: dict[str, float] = {}


def _yahoo_fetch(url: str) -> dict:
    """Interner Helfer: Yahoo Finance JSON holen + Rate-Limit."""
    req = Request(url, headers=_YAHOO_HEADERS)
    data = json.loads(urlopen(req, timeout=10).read())
    time.sleep(_RATE_LIMIT_SLEEP)
    return data


def get_price_yahoo(ticker: str) -> tuple[float | None, str | None]:
    """
    Aktuellen Kurs von Yahoo Finance holen.

    Returns:
        (price: float, currency: str) oder (None, None) bei Fehler
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        data = _yahoo_fetch(url)
        meta = data["chart"]["result"][0]["meta"]
        price    = float(meta.get("regularMarketPrice", 0))
        currency = meta.get("currency", "USD")
        return price, currency
    except Exception as e:
        print(f"  ⚠️  Price fetch failed for {ticker}: {e}")
        return None, None


def to_eur(price: float, currency: str) -> float:
    """
    Preis in EUR umrechnen.

    Unterstützte Währungen: USD, GBP, NOK, SEK, DKK, HKD, CAD
    Fallback auf harte Kurse aus config wenn Yahoo nicht erreichbar.
    """
    if currency == "EUR":
        return round(price, 4)

    # Cache prüfen
    if currency in _fx_cache:
        return round(price * _fx_cache[currency], 4)

    try:
        pair = f"{currency}EUR=X"
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}?interval=1d&range=1d"
        data = _yahoo_fetch(url)
        rate = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        _fx_cache[currency] = rate
        return round(price * rate, 4)
    except Exception:
        rate = FX_FALLBACK.get(currency, 1.0)
        return round(price * rate, 4)


def get_atr(ticker: str, period: int = 14) -> float | None:
    """
    ATR(period) aus Yahoo Finance berechnen (30 Tage Tages-Daten).

    Falls < period Datenpunkte: Durchschnitt aller verfügbaren TRs.
    Returns None bei Fehler.
    """
    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
        data = _yahoo_fetch(url)
        quote  = data["chart"]["result"][0]["indicators"]["quote"][0]
        highs  = quote["high"]
        lows   = quote["low"]
        closes = quote["close"]

        trs = []
        for i in range(1, len(highs)):
            if highs[i] is not None and lows[i] is not None and closes[i - 1] is not None:
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i]  - closes[i - 1]),
                )
                trs.append(tr)

        if not trs:
            return None
        window = trs[-period:] if len(trs) >= period else trs
        return round(sum(window) / len(window), 4)
    except Exception as e:
        print(f"  ⚠️  ATR fetch failed for {ticker}: {e}")
        return None
