#!/usr/bin/env python3
"""
calendar_service.py — Phase 36: Echter Kalender für CEO-System.

Damit das System (und ich, CLI Claude) NIE wieder rät welcher Tag ist
oder ob Markt offen ist.

Funktionen:
  - get_today_info()          → date, weekday, time_zone, days_to_weekend
  - get_market_status()       → US/EU/Asia open/closed/pre/post
  - time_until_next_open()    → Sekunden bis nächste relevante Markt-Öffnung
  - get_upcoming_events()     → Earnings + Holidays + Fed-Meetings + Geo
  - get_trading_window_today() → "16h-22h" (best-WR-window)
  - is_holiday(date, market)  → True/False
  - format_for_prompt()       → Markdown-Block für CEO-Brain

CLI:
  python3 scripts/calendar_service.py             # full status report
  python3 scripts/calendar_service.py --today     # nur heute
  python3 scripts/calendar_service.py --week      # 7d Vorschau
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
DIRECTIVE_FILE = WS / 'data' / 'ceo_directive.json'

BERLIN = ZoneInfo('Europe/Berlin')
NY     = ZoneInfo('America/New_York')
TOKYO  = ZoneInfo('Asia/Tokyo')

# Market sessions in local times
MARKET_HOURS = {
    'US':    {'tz': NY,     'open': time(9, 30), 'close': time(16, 0),
              'pre': time(4, 0), 'post': time(20, 0)},
    'EU':    {'tz': BERLIN, 'open': time(9, 0),  'close': time(17, 30),
              'pre': time(8, 0), 'post': time(20, 0)},
    'ASIA':  {'tz': TOKYO,  'open': time(9, 0),  'close': time(15, 0),
              'pre': time(8, 0), 'post': time(16, 0)},
}

DE_WEEKDAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

# Top US/EU Holidays 2026 (vereinfacht — komplette Liste ist long)
US_HOLIDAYS_2026 = {
    '2026-01-01': "New Year's Day",
    '2026-01-19': 'MLK Day',
    '2026-02-16': "Presidents' Day",
    '2026-04-03': 'Good Friday',
    '2026-05-25': 'Memorial Day',
    '2026-06-19': 'Juneteenth',
    '2026-07-03': 'Independence Day (observed)',
    '2026-09-07': 'Labor Day',
    '2026-11-26': 'Thanksgiving',
    '2026-11-27': 'Black Friday (early close)',
    '2026-12-25': 'Christmas',
}
DE_HOLIDAYS_2026 = {
    '2026-01-01': 'Neujahr',
    '2026-04-03': 'Karfreitag',
    '2026-04-06': 'Ostermontag',
    '2026-05-01': 'Tag der Arbeit',
    '2026-05-14': 'Christi Himmelfahrt',
    '2026-05-25': 'Pfingstmontag',
    '2026-10-03': 'Tag der Deutschen Einheit',
    '2026-12-24': 'Heiligabend (Halbtag)',
    '2026-12-25': '1. Weihnachtstag',
    '2026-12-26': '2. Weihnachtstag',
    '2026-12-31': 'Silvester (Halbtag)',
}

# Fed-Meetings 2026 (FOMC)
FED_MEETINGS_2026 = [
    '2026-01-28', '2026-03-18', '2026-04-29', '2026-06-17',
    '2026-07-29', '2026-09-16', '2026-11-04', '2026-12-16',
]


def get_berlin_time() -> dict:
    """Phase 43f: Single-Source-of-Truth für die Berliner Uhrzeit.
    Liefert sowohl Zeit-String als auch volle datetime-Objekt + DST-Info.

    Beispiel-Output:
      {
        'time_hms':    '14:32:18',
        'time_hm':     '14:32',
        'date':        '2026-04-29',
        'iso':         '2026-04-29T14:32:18+02:00',
        'tz_abbrev':   'CEST',           # automatisch CET im Winter / CEST im Sommer
        'is_dst':      True,
        'human':       '14:32 Mi 29.04. CEST',
        'utc_offset':  '+02:00',
        'unix_ts':     1745934738,
      }
    """
    now_berlin = datetime.now(BERLIN)
    is_dst = bool(now_berlin.dst())
    tz_abbrev = 'CEST' if is_dst else 'CET'
    weekday_short = DE_WEEKDAYS[now_berlin.weekday()][:2]  # 'Mo','Di','Mi',...
    return {
        'time_hms':   now_berlin.strftime('%H:%M:%S'),
        'time_hm':    now_berlin.strftime('%H:%M'),
        'date':       now_berlin.strftime('%Y-%m-%d'),
        'iso':        now_berlin.isoformat(timespec='seconds'),
        'tz_abbrev':  tz_abbrev,
        'is_dst':     is_dst,
        'human':      f"{now_berlin.strftime('%H:%M')} {weekday_short} "
                       f"{now_berlin.strftime('%d.%m.')} {tz_abbrev}",
        'utc_offset': now_berlin.strftime('%z')[:3] + ':' + now_berlin.strftime('%z')[3:],
        'unix_ts':    int(now_berlin.timestamp()),
    }


def get_today_info() -> dict:
    """Echte Datums-Information — nie raten."""
    now_berlin = datetime.now(BERLIN)
    bt = get_berlin_time()
    return {
        'datetime_berlin': now_berlin.isoformat(timespec='seconds'),
        'date': now_berlin.strftime('%Y-%m-%d'),
        'time': now_berlin.strftime('%H:%M:%S'),
        'time_hm': now_berlin.strftime('%H:%M'),
        'tz_abbrev': bt['tz_abbrev'],
        'is_dst': bt['is_dst'],
        'utc_offset': bt['utc_offset'],
        'weekday_de': DE_WEEKDAYS[now_berlin.weekday()],
        'weekday_num': now_berlin.weekday(),  # 0=Mo
        'is_weekend': now_berlin.weekday() >= 5,
        'iso_week': now_berlin.isocalendar()[1],
        'days_to_weekend': max(0, 5 - now_berlin.weekday()) if now_berlin.weekday() < 5 else 0,
        'days_to_monday': (7 - now_berlin.weekday()) % 7 or 7,
    }


def is_holiday(date_str: str, market: str = 'US') -> tuple[bool, str]:
    """Returns (is_holiday, name)."""
    holidays = US_HOLIDAYS_2026 if market == 'US' else DE_HOLIDAYS_2026
    if date_str in holidays:
        return True, holidays[date_str]
    return False, ''


def get_market_status(market: str = 'US') -> dict:
    """Status: closed | pre | open | post"""
    info = MARKET_HOURS.get(market.upper())
    if not info:
        return {'status': 'unknown', 'market': market}

    now = datetime.now(info['tz'])
    today_str = now.strftime('%Y-%m-%d')

    # Weekend
    if now.weekday() >= 5:
        return {'market': market, 'status': 'closed_weekend',
                'reason': 'Wochenende', 'local_time': now.strftime('%H:%M')}

    # Holiday
    is_hol, hol_name = is_holiday(today_str, market)
    if is_hol:
        return {'market': market, 'status': 'closed_holiday',
                'reason': hol_name, 'local_time': now.strftime('%H:%M')}

    t = now.time()
    if t < info['pre']:
        status = 'closed_overnight'
    elif t < info['open']:
        status = 'pre_market'
    elif t < info['close']:
        status = 'open'
    elif t < info['post']:
        status = 'post_market'
    else:
        status = 'closed_overnight'

    return {
        'market':     market,
        'status':     status,
        'local_time': now.strftime('%H:%M'),
        'tz':         str(info['tz']),
        'opens_at':   info['open'].strftime('%H:%M') + f' ({info["tz"]})',
        'closes_at':  info['close'].strftime('%H:%M') + f' ({info["tz"]})',
    }


def time_until_next_open(market: str = 'US') -> dict:
    """Sekunden bis nächste Marktöffnung."""
    info = MARKET_HOURS.get(market.upper())
    if not info:
        return {'seconds': None, 'human': 'unknown'}

    now = datetime.now(info['tz'])
    target = now.replace(hour=info['open'].hour, minute=info['open'].minute,
                         second=0, microsecond=0)

    # If already past open today, push to tomorrow
    if now.time() >= info['open']:
        target += timedelta(days=1)

    # Skip weekends + holidays
    while target.weekday() >= 5 or is_holiday(target.strftime('%Y-%m-%d'), market)[0]:
        target += timedelta(days=1)

    delta_sec = (target - now).total_seconds()
    hours = int(delta_sec // 3600)
    minutes = int((delta_sec % 3600) // 60)
    return {
        'market': market,
        'seconds': int(delta_sec),
        'next_open_local': target.strftime('%Y-%m-%d %H:%M %Z'),
        'human': f'{hours}h {minutes}min' if hours < 48 else f'{hours//24}d {hours%24}h',
    }


def get_upcoming_events(days_ahead: int = 7,
                        watch_tickers: list[str] | None = None) -> dict:
    """Alle Events der nächsten N Tage."""
    now = datetime.now(BERLIN)
    cutoff = now + timedelta(days=days_ahead)

    events = {
        'earnings': [],
        'fed_meetings': [],
        'us_holidays': [],
        'de_holidays': [],
        'today_geo_alert': 'unknown',
    }

    # Fed
    for d_str in FED_MEETINGS_2026:
        try:
            d = datetime.fromisoformat(d_str).replace(tzinfo=BERLIN)
            if now.date() <= d.date() <= cutoff.date():
                events['fed_meetings'].append({
                    'date': d_str,
                    'days_away': (d.date() - now.date()).days,
                })
        except Exception:
            continue

    # Holidays
    for d_str in sorted(US_HOLIDAYS_2026):
        try:
            d = datetime.fromisoformat(d_str).date()
            if now.date() <= d <= cutoff.date():
                events['us_holidays'].append({
                    'date': d_str, 'name': US_HOLIDAYS_2026[d_str],
                    'days_away': (d - now.date()).days,
                })
        except Exception:
            continue
    for d_str in sorted(DE_HOLIDAYS_2026):
        try:
            d = datetime.fromisoformat(d_str).date()
            if now.date() <= d <= cutoff.date():
                events['de_holidays'].append({
                    'date': d_str, 'name': DE_HOLIDAYS_2026[d_str],
                    'days_away': (d - now.date()).days,
                })
        except Exception:
            continue

    # Earnings (aus DB)
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        if watch_tickers:
            placeholders = ','.join('?' * len(watch_tickers))
            params = list(watch_tickers) + [
                now.strftime('%Y-%m-%d'),
                cutoff.strftime('%Y-%m-%d'),
            ]
            cur = c.execute(f"""
                SELECT ticker, next_date FROM earnings_calendar
                WHERE ticker IN ({placeholders})
                  AND next_date BETWEEN ? AND ?
                ORDER BY next_date
            """, params)
        else:
            cur = c.execute("""
                SELECT ticker, next_date FROM earnings_calendar
                WHERE next_date BETWEEN ? AND ?
                ORDER BY next_date LIMIT 30
            """, (now.strftime('%Y-%m-%d'), cutoff.strftime('%Y-%m-%d')))
        for r in cur:
            try:
                d = datetime.fromisoformat(str(r['next_date'])[:10]).date()
                events['earnings'].append({
                    'ticker':   r['ticker'],
                    'date':     str(r['next_date'])[:10],
                    'days_away': (d - now.date()).days,
                })
            except Exception:
                continue
        c.close()
    except Exception as e:
        events['_earnings_error'] = str(e)

    # Geo-Alert
    try:
        d = json.loads(DIRECTIVE_FILE.read_text(encoding='utf-8'))
        events['today_geo_alert'] = d.get('geo_alert_level', 'unknown')
        events['today_vix'] = d.get('vix')
    except Exception:
        pass

    return events


def get_trading_window_today() -> dict:
    """Welche Stunde heute hat historisch beste WR? (51% bei 17-22h CET)"""
    today = get_today_info()
    if today['is_weekend']:
        return {'window': 'closed', 'reason': 'Wochenende'}
    return {
        'best_window_cet': '17:00-22:00',
        'best_wr_pct': 51,
        'reason': 'historische Win-Rate-Daten',
        'morning_block': '06:00-11:00 (0% WR — autonome Trades blockiert)',
    }


def format_for_prompt() -> str:
    """Formatierter Kontext für CEO-Brain Prompt."""
    today = get_today_info()
    us = get_market_status('US')
    eu = get_market_status('EU')
    asia = get_market_status('ASIA')
    next_us = time_until_next_open('US')
    next_eu = time_until_next_open('EU')
    events = get_upcoming_events(days_ahead=7)

    # Phase 43f: Berliner Uhrzeit als prominenter Anker-Header (CET/CEST automatisch)
    bt = get_berlin_time()
    lines = [
        '═══ KALENDER & MARKT-STATUS ═══',
        f"⏰ BERLIN: {bt['human']} (UTC{bt['utc_offset']}) | {today['weekday_de']}, "
        f"{today['date']} | KW {today['iso_week']}",
        f"Markt US:    {us['status']:<20} ({us['local_time']} {us.get('tz','?').split('/')[-1]})",
        f"Markt EU:    {eu['status']:<20} ({eu['local_time']} {bt['tz_abbrev']})",
        f"Markt Asia:  {asia['status']:<20} ({asia['local_time']} JST)",
    ]
    if us['status'] != 'open':
        lines.append(f"  → US opens in: {next_us['human']}")
    if eu['status'] != 'open':
        lines.append(f"  → EU opens in: {next_eu['human']}")

    if events['fed_meetings']:
        lines.append('\nFed-Meetings (7d):')
        for f in events['fed_meetings']:
            lines.append(f"  · {f['date']} (in {f['days_away']}d)")
    if events['earnings']:
        lines.append('\nEarnings (7d, your tickers):')
        for e in events['earnings'][:8]:
            lines.append(f"  · {e['ticker']} am {e['date']} (in {e['days_away']}d)")
    if events['us_holidays']:
        lines.append('\nUS-Feiertage (7d):')
        for h in events['us_holidays']:
            lines.append(f"  · {h['date']} {h['name']} (in {h['days_away']}d)")
    if events['de_holidays']:
        lines.append('\nDE-Feiertage (7d):')
        for h in events['de_holidays']:
            lines.append(f"  · {h['date']} {h['name']} (in {h['days_away']}d)")

    lines.append(f"\nGeo-Alert heute: {events.get('today_geo_alert','?')}, "
                 f"VIX {events.get('today_vix','?')}")

    win = get_trading_window_today()
    if win.get('best_window_cet'):
        lines.append(f"Best Trading-Window heute: {win['best_window_cet']} CET ({win['best_wr_pct']}% WR)")

    return '\n'.join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--today', action='store_true')
    ap.add_argument('--week', action='store_true')
    ap.add_argument('--prompt', action='store_true', help='Output für CEO-Brain Prompt')
    args = ap.parse_args()

    if args.prompt:
        print(format_for_prompt())
        return 0

    if args.today:
        print(json.dumps(get_today_info(), indent=2, ensure_ascii=False))
        print()
        print(json.dumps({
            'us': get_market_status('US'),
            'eu': get_market_status('EU'),
            'asia': get_market_status('ASIA'),
        }, indent=2, ensure_ascii=False))
        return 0

    if args.week:
        print(json.dumps(get_upcoming_events(days_ahead=7), indent=2, ensure_ascii=False))
        return 0

    # Default: full
    print(format_for_prompt())
    return 0


if __name__ == '__main__':
    sys.exit(main())
