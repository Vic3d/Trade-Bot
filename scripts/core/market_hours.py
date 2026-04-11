#!/usr/bin/env python3
"""
Market Hours — Exchange-spezifische Öffnungszeiten + Feiertage
==============================================================
Nutzt exchange_calendars für genaue Kalender je Börse.

Unterstützte Ticker-Suffixe → Exchange-Mapping:
  .DE, .F  → XETR (Xetra/Frankfurt)
  .OL      → XOSL (Oslo)
  .AS      → XAMS (Amsterdam/Euronext)
  .PA      → XPAR (Paris/Euronext)
  .CO      → XCSE (Copenhagen)
  .L       → XLON (London)
  .ST      → XSTO (Stockholm)
  .HE      → XHEL (Helsinki)
  .MI      → XMIL (Milan)
  (kein Suffix / US) → XNYS (NYSE)
"""

from datetime import datetime, date, timezone
from typing import Optional

try:
    import exchange_calendars as xcals
    XCALS_AVAILABLE = True
except ImportError:
    XCALS_AVAILABLE = False

# Ticker-Suffix → Exchange-Code
SUFFIX_TO_EXCHANGE = {
    '.DE':  'XETR',
    '.F':   'XETR',
    '.OL':  'XOSL',
    '.AS':  'XAMS',
    '.PA':  'XPAR',
    '.CO':  'XCSE',
    '.L':   'XLON',
    '.ST':  'XSTO',
    '.HE':  'XHEL',
    '.MI':  'XMIL',
    '.BR':  'XBRU',
    '.SW':  'XSWX',
    '.VI':  'XWBO',
}

# Exchange → Öffnungszeiten (UTC)
EXCHANGE_HOURS = {
    'XETR': (7, 0, 15, 30),    # 09:00–17:30 MEZ = 07:00–15:30 UTC (Sommerzeit)
    'XOSL': (7, 0, 15, 20),
    'XAMS': (7, 0, 15, 30),
    'XPAR': (7, 0, 15, 30),
    'XCSE': (7, 0, 15, 0),
    'XLON': (8, 0, 16, 30),    # 08:00–16:30 UTC
    'XSTO': (7, 0, 15, 30),
    'XHEL': (7, 0, 15, 0),
    'XMIL': (7, 0, 15, 30),
    'XNYS': (13, 30, 20, 0),   # 09:30–16:00 ET = 13:30–20:00 UTC
}


def get_exchange(ticker: str) -> str:
    """Ermittelt Exchange-Code aus Ticker-Suffix."""
    ticker_upper = ticker.upper()
    for suffix, exchange in SUFFIX_TO_EXCHANGE.items():
        if ticker_upper.endswith(suffix.upper()):
            return exchange
    return 'XNYS'  # Default: NYSE für US-Ticker


def is_trading_day(ticker: str, check_date: Optional[date] = None) -> bool:
    """
    Prüft ob heute/check_date ein Handelstag für diesen Ticker ist.
    Berücksichtigt Wochenenden UND börsenspezifische Feiertage.
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()

    # Wochenende — gilt für alle Börsen
    if check_date.weekday() >= 5:
        return False

    if not XCALS_AVAILABLE:
        # Fallback: nur Wochenend-Check
        return True

    exchange = get_exchange(ticker)

    try:
        cal = xcals.get_calendar(exchange)
        return cal.is_session(check_date.isoformat())
    except Exception:
        # Unbekannte Exchange → nur Wochenend-Check
        return check_date.weekday() < 5


def is_market_open_now(ticker: str) -> bool:
    """
    Prüft ob die Börse für diesen Ticker JETZT geöffnet ist.
    (Handelstag + innerhalb der Handelszeiten)
    """
    now_utc = datetime.now(timezone.utc)

    if not is_trading_day(ticker, now_utc.date()):
        return False

    exchange = get_exchange(ticker)
    hours = EXCHANGE_HOURS.get(exchange, (13, 30, 20, 0))
    open_h, open_m, close_h, close_m = hours

    now_minutes = now_utc.hour * 60 + now_utc.minute
    open_minutes = open_h * 60 + open_m
    close_minutes = close_h * 60 + close_m

    return open_minutes <= now_minutes <= close_minutes


def any_market_open(tickers: list[str]) -> bool:
    """True wenn mindestens eine der übergebenen Börsen gerade offen ist."""
    return any(is_market_open_now(t) for t in tickers)


def is_any_trading_day(tickers: list[str], check_date: Optional[date] = None) -> bool:
    """True wenn mindestens eine der übergebenen Börsen heute handelt."""
    return any(is_trading_day(t, check_date) for t in tickers)


if __name__ == '__main__':
    from datetime import date as d

    test_tickers = ['AAPL', 'RHM.DE', 'EQNR.OL', 'BA.L', 'TTE.PA', 'ASML.AS', 'ZIM', 'MOS']
    today = datetime.now(timezone.utc)

    print(f"=== Market Hours Check — {today.strftime('%A %Y-%m-%d %H:%M UTC')} ===\n")

    for ticker in test_tickers:
        exchange = get_exchange(ticker)
        trading = is_trading_day(ticker)
        open_now = is_market_open_now(ticker)
        status = '🟢 OFFEN' if open_now else ('📅 Heute Handelstag, aber außerhalb Handelszeiten' if trading else '🔴 Kein Handelstag heute')
        print(f"  {ticker:12} [{exchange}] → {status}")

    print()
    print(f"Irgendeine Börse heute Handelstag? {is_any_trading_day(test_tickers)}")
    print(f"Irgendeine Börse gerade offen?     {any_market_open(test_tickers)}")
