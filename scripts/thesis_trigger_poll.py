#!/usr/bin/env python3
"""
Thesis Trigger Poll — Phase 22
===============================
Pollt ACTIVE_WATCH Thesen in watchlist.json gegen entry_trigger_T123:
- Preis-Bedingungen (z.B. "STLD <$186", "CCJ <$50") via live_data
- Datums-Bedingungen (z.B. "nach Q1 am 30.04.") — feuert, wenn Datum erreicht
- Event-Keywords (z.B. "Liberation-Day-Ankuendigung") via News-Scan (letzte 12h)

Wenn irgend ein T1/T2/T3 feuert:
  - thesis_watchlist.mark_trigger_hit(sid, reason)
  - notify('thesis.trigger_hit', ...) — LOW tier (Digest)

Scheduler: alle 2h waehrend 09-21 CET (ergaenzt den bestehenden Thesis Monitor,
der nur Kill-Trigger prueft).

Usage:
  python3 scripts/thesis_trigger_poll.py         # Cycle
  python3 scripts/thesis_trigger_poll.py --dry   # Parse + Evaluate, aber keine Writes
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
STRATS = WS / 'data' / 'strategies.json'
DB_PATH = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'thesis_trigger_poll.log'

sys.path.insert(0, str(WS / 'scripts'))

try:
    from thesis_watchlist import mark_trigger_hit, _load as _load_watchlist
except Exception as e:
    print(f'FATAL import thesis_watchlist: {e}')
    sys.exit(1)

try:
    from notification_policy import notify
except Exception:
    def notify(event, msg, **kw):
        print(f'[NOTIFY {event}] {msg}')
        return False

try:
    from core.live_data import get_price
except Exception:
    def get_price(ticker, max_age_minutes=1440):
        return None


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec='seconds')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ── Parser ─────────────────────────────────────────────────────────────────
# Erkennt "TICKER <$186", "STLD <186", "CCJ <$50", "RHM.DE <€140"
_RE_PRICE_LT = re.compile(
    r'([A-Z]{2,6}(?:\.[A-Z]{1,3})?)\s*(?:<|unter|below)\s*[$€]?([0-9]+(?:[.,][0-9]+)?)',
    re.IGNORECASE
)
_RE_PRICE_GT = re.compile(
    r'([A-Z]{2,6}(?:\.[A-Z]{1,3})?)\s*(?:>|ueber|über|over|above)\s*[$€]?([0-9]+(?:[.,][0-9]+)?)',
    re.IGNORECASE
)
# Datums-Pattern: "30.03.", "am 07.05.", "bis 02.04."
_RE_DATE = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.?(?:(\d{4}))?\b')


def _extract_price_conditions(text: str, tickers: list[str]) -> list[dict]:
    """Findet Ticker-Preis-Bedingungen im Text. Returns [{ticker, op, price}]."""
    out = []
    upper = text.upper()
    # Prefer actual strategy-tickers — reduziert False Positives
    ticker_set = {t.upper() for t in tickers if t}
    for m in _RE_PRICE_LT.finditer(upper):
        tkr = m.group(1).upper()
        if tkr in ticker_set or any(tkr in t or t in tkr for t in ticker_set):
            out.append({'ticker': tkr, 'op': '<', 'price': float(m.group(2).replace(',', '.'))})
    for m in _RE_PRICE_GT.finditer(upper):
        tkr = m.group(1).upper()
        if tkr in ticker_set or any(tkr in t or t in tkr for t in ticker_set):
            out.append({'ticker': tkr, 'op': '>', 'price': float(m.group(2).replace(',', '.'))})
    return out


def _extract_dates(text: str, ref_year: int | None = None) -> list[date]:
    """Findet DD.MM.(YYYY)?. Ohne Jahr: nimm laufendes Jahr."""
    if ref_year is None:
        ref_year = date.today().year
    out = []
    for m in _RE_DATE.finditer(text):
        dd, mm = int(m.group(1)), int(m.group(2))
        yy = int(m.group(3)) if m.group(3) else ref_year
        try:
            out.append(date(yy, mm, dd))
        except ValueError:
            pass
    return out


# Keywords die auf News-Events zeigen (Gross/Kleinschreibung egal)
_EVENT_KEYWORDS = [
    'liberation-day', 'liberation day', 'opec+', 'q1 earnings', 'q1-earnings',
    'section 232', 'executive order', 'nato summit', 'nato-summit',
    'waffenstillstand', 'peace deal', 'sanktionen', 'tariff announcement',
]


def _extract_event_keywords(text: str) -> list[str]:
    lo = text.lower()
    return [kw for kw in _EVENT_KEYWORDS if kw in lo]


# ── News Scan ─────────────────────────────────────────────────────────────
def _recent_news(hours: int = 12) -> str:
    """Gibt alle News-Headlines der letzten N Stunden als konkateniertes Lowercase zurueck."""
    if not DB_PATH.exists():
        return ''
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    chunks = []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute('PRAGMA busy_timeout=3000')
        for sql, params in (
            ('SELECT headline, source FROM news_events WHERE published_at > ? LIMIT 500', (cutoff,)),
            ('SELECT headline FROM news_pipeline WHERE created_at > ? LIMIT 500', (cutoff,)),
        ):
            try:
                rows = conn.execute(sql, params).fetchall()
                for r in rows:
                    for cell in r:
                        if cell:
                            chunks.append(str(cell))
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return ' \n '.join(chunks).lower()


# ── Evaluation ─────────────────────────────────────────────────────────────
def _eval_price(cond: dict) -> tuple[bool, str]:
    px = get_price(cond['ticker'])
    if px is None:
        return False, f'{cond["ticker"]} price unavailable'
    ok = (px < cond['price']) if cond['op'] == '<' else (px > cond['price'])
    return ok, f'{cond["ticker"]} ${px:.2f} {cond["op"]} ${cond["price"]:.2f}'


def _eval_date(dates: list[date]) -> tuple[bool, str]:
    today = date.today()
    hit = [d for d in dates if d <= today and (today - d).days <= 3]
    if hit:
        return True, f'date passed: {hit[0].isoformat()}'
    return False, ''


def evaluate_trigger(trigger_text: str, tickers: list[str], news_lower: str) -> tuple[bool, str]:
    """Prueft einen einzelnen T-String. Returns (fired, reason)."""
    if not trigger_text:
        return False, ''

    # 1) Preis-Bedingung — deterministisch
    price_conds = _extract_price_conditions(trigger_text, tickers)
    for c in price_conds:
        ok, why = _eval_price(c)
        if ok:
            return True, f'PRICE {why}'

    # 2) Datum — wenn T sagt "nach X.Y." und X.Y. war gestern / heute
    #    UND kein Preis-Kriterium vorhanden oder unkritisch
    dates = _extract_dates(trigger_text)
    if dates and 'nach' in trigger_text.lower():
        ok, why = _eval_date(dates)
        if ok:
            # Wenn zusaetzlich Preis-Kriterium existiert und nicht erfuellt → kein Hit
            if price_conds:
                return False, f'date hit aber price cond offen'
            return True, f'DATE {why}'

    # 3) Event-Keywords in recent news
    kws = _extract_event_keywords(trigger_text)
    for kw in kws:
        if kw in news_lower:
            return True, f'EVENT news match: "{kw}"'

    return False, ''


# ── Main Cycle ─────────────────────────────────────────────────────────────
def run_cycle(dry: bool = False) -> dict:
    stats = {'checked': 0, 'fired': [], 'errors': []}

    if not STRATS.exists():
        _log('FATAL strategies.json fehlt')
        return stats

    strats = json.loads(STRATS.read_text(encoding='utf-8'))
    wl = _load_watchlist()
    theses = wl.get('theses', {})

    news_lower = _recent_news(hours=12)

    for sid, entry in theses.items():
        if entry.get('status') != 'ACTIVE_WATCH':
            continue
        stats['checked'] += 1
        cfg = strats.get(sid, {})
        t123 = cfg.get('entry_trigger_T123') or {}
        if not isinstance(t123, dict):
            continue
        tickers = cfg.get('tickers') or ([cfg.get('ticker')] if cfg.get('ticker') else [])
        try:
            for level in ('T1', 'T2', 'T3'):
                txt = t123.get(level) or ''
                if not txt:
                    continue
                fired, reason = evaluate_trigger(txt, tickers, news_lower)
                if fired:
                    msg = f'{sid} {level}: {reason} — "{txt[:80]}"'
                    _log(f'TRIGGER_HIT {msg}')
                    stats['fired'].append({'strategy': sid, 'level': level, 'reason': reason})
                    if not dry:
                        mark_trigger_hit(sid, f'{level}: {reason}')
                        notify(
                            'thesis.trigger_hit',
                            f'🎯 {sid} Entry-Trigger {level} hit — {reason}',
                            category='watchlist',
                        )
                    break  # nur ein Level pro Durchlauf feuern
        except Exception as e:
            stats['errors'].append({'strategy': sid, 'error': str(e)})

    _log(f'CYCLE checked={stats["checked"]} fired={len(stats["fired"])} errors={len(stats["errors"])}')
    return stats


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    result = run_cycle(dry=args.dry)
    print(json.dumps(result, indent=2, ensure_ascii=False))
