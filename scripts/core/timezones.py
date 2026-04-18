#!/usr/bin/env python3
"""
timezones.py — Zentraler Timezone-Helper fuer TradeMind
=======================================================

Victor ist Deutscher. Alle **User-Facing Zeiten** (Discord-Messages, Reports,
Log-Zeilen die Menschen lesen) gehen in **deutsche Zeit** (CET/CEST automatisch).

Server-TZ: Europe/Berlin. `datetime.now()` gibt bereits Lokalzeit zurueck —
aber UTC-Timestamps aus DB (entry_date, close_date etc.) muessen konvertiert
werden bevor sie angezeigt werden.

Usage:
    from core.timezones import now_cet, fmt_cet, to_cet

    print(now_cet())                          # 2026-04-18 08:24:30+02:00
    print(fmt_cet())                          # "18.04.2026 08:24 CEST"
    print(fmt_cet(dt, fmt='%H:%M'))           # "08:24"
    cet_dt = to_cet(utc_dt_from_db)           # konvertiert UTC → CEST

Fuer interne Daten (DB-Writes, API-Calls) weiterhin UTC benutzen. CET nur fuer
**Anzeige**. Das vermeidet DST-Buggs in Datenbank-Queries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo('Europe/Berlin')
UTC = timezone.utc


def now_cet() -> datetime:
    """Aktuelle Zeit in deutscher Zeit (CET im Winter, CEST im Sommer)."""
    return datetime.now(BERLIN)


def now_utc() -> datetime:
    """Aktuelle UTC-Zeit (fuer DB-Writes)."""
    return datetime.now(UTC)


def to_cet(dt: datetime) -> datetime:
    """Konvertiert beliebigen datetime nach deutsche Zeit.

    - Naive datetime → als UTC interpretiert (DB-Konvention)
    - Aware datetime → korrekt konvertiert
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(BERLIN)


def fmt_cet(dt: datetime | None = None, fmt: str = '%d.%m.%Y %H:%M %Z') -> str:
    """Formatiert datetime als deutsche Zeit.

    Default-Format: "18.04.2026 08:24 CEST"
    """
    if dt is None:
        dt = now_cet()
    else:
        dt = to_cet(dt)
    return dt.strftime(fmt)


def fmt_cet_short(dt: datetime | None = None) -> str:
    """Kurz-Format: "08:24" (nur Uhrzeit, fuer Intraday-Meldungen)."""
    return fmt_cet(dt, fmt='%H:%M')


def fmt_cet_date(dt: datetime | None = None) -> str:
    """Nur Datum: "18.04.2026"."""
    return fmt_cet(dt, fmt='%d.%m.%Y')


def is_weekend() -> bool:
    """True wenn Sa oder So in deutscher Zeit."""
    return now_cet().weekday() >= 5


def is_eu_market_hours() -> bool:
    """Xetra/LSE/Euronext Handelszeit: Mo-Fr 09:00-17:30 CEST."""
    n = now_cet()
    if n.weekday() >= 5:
        return False
    t = n.time()
    return t.hour * 60 + t.minute >= 9 * 60 and t.hour * 60 + t.minute < 17 * 60 + 30


def is_us_market_hours() -> bool:
    """NYSE/Nasdaq Regular: Mo-Fr 15:30-22:00 CEST (Sommer) / 15:30-22:00 CET (Winter)."""
    n = now_cet()
    if n.weekday() >= 5:
        return False
    t = n.time()
    return t.hour * 60 + t.minute >= 15 * 60 + 30 and t.hour * 60 + t.minute < 22 * 60


def is_asia_market_hours() -> bool:
    """Tokyo/HK/Shanghai Overlap: Mo-Fr 01:00-10:00 CEST."""
    n = now_cet()
    if n.weekday() >= 5:
        return False
    t = n.time()
    return t.hour >= 1 and t.hour < 10


def tz_label() -> str:
    """Aktuelles Kurzlabel: "CEST" oder "CET"."""
    return now_cet().strftime('%Z')


if __name__ == '__main__':
    print(f"Now CET: {fmt_cet()}")
    print(f"Now UTC: {now_utc().isoformat(timespec='seconds')}")
    print(f"TZ Label: {tz_label()}")
    print(f"Weekend: {is_weekend()}")
    print(f"EU Market: {is_eu_market_hours()}")
    print(f"US Market: {is_us_market_hours()}")
    print(f"Asia Market: {is_asia_market_hours()}")
