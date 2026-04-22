#!/usr/bin/env python3
"""
Universe Decay — Phase 20c
============================

Täglicher Cleanup-Job der inaktive Tickers automatisch auf `dormant` setzt.

**Läuft:** 02:00 CET (vor auto_deepdive um 02:30)

**Decay-Regeln (ODER-verknüpft):**

  1. Kein Signal seit 30 Tagen              → dormant('stale_no_signal')
  2. Kein Trade seit 60d + < 5 Signale      → dormant('low_activity')
  3. Falling Knife ≥ 14 Tage in Folge       → dormant('falling_knife_persistent')
  4. Avg Conviction < 35 über letzte 10 Sig → dormant('low_conviction')
  5. Verdict=NICHT_KAUFEN + Score < 40      → dormant('negative_verdict')

**Resurrection (Auto-Reaktivierung):**
  - Ticker mit News-Mentions ≥ 5 in 7 Tagen UND positive Conviction ≥ 55
  - → dormant → watchlist (nicht direkt active, braucht Deep Dive)

**Output:**
  - data/universe_decay_log.json  (Audit-Trail)
  - Queue-Event für Digest-Benachrichtigung
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from core.universe import (  # noqa: E402
    STATUS_ACTIVE,
    STATUS_WATCHLIST,
    STATUS_DORMANT,
    load_universe,
    save_universe,
    mark_dormant,
    set_status,
)

DATA = WS / 'data'
DB = DATA / 'trading.db'
DECAY_LOG = DATA / 'universe_decay_log.json'


# ── Config ────────────────────────────────────────────────────────────────────

STALE_DAYS = 30
LOW_ACTIVITY_DAYS = 60
LOW_ACTIVITY_MIN_SIGNALS = 5
FALLING_KNIFE_STREAK = 14
LOW_CONVICTION_AVG = 35.0
LOW_CONVICTION_WINDOW = 10
RESURRECTION_NEWS_7D = 5
RESURRECTION_CONVICTION = 55.0


# ── Falling Knife Check ───────────────────────────────────────────────────────

def _is_falling_knife_now(ticker: str) -> bool:
    """Single snapshot: ist dieser Ticker gerade ein Falling Knife?"""
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute("""
            SELECT close FROM prices WHERE ticker = ?
            ORDER BY date DESC LIMIT 70
        """, (ticker,)).fetchall()
        conn.close()
    except Exception:
        return False
    if len(rows) < 65:
        return False
    closes = [r[0] for r in rows if r[0] is not None]
    if len(closes) < 65:
        return False
    current = closes[0]
    ema50 = sum(closes[:50]) / 50
    three_months_ago = closes[63] if len(closes) > 63 else closes[-1]
    trend_3m = (current - three_months_ago) / three_months_ago if three_months_ago else 0
    return current < ema50 and trend_3m < -0.10


# ── Decay Rules ───────────────────────────────────────────────────────────────

def _days_ago(iso_date: str | None) -> int:
    if not iso_date:
        return 99999
    try:
        d = datetime.fromisoformat(iso_date).date()
        return (date.today() - d).days
    except Exception:
        return 99999


def _avg_recent_conviction(history: list, window: int) -> float | None:
    if not history:
        return None
    tail = history[-window:]
    if not tail:
        return None
    vals = [x[1] for x in tail if isinstance(x, list) and len(x) >= 2]
    return sum(vals) / len(vals) if vals else None


def evaluate_ticker(ticker: str, entry: dict) -> tuple[str | None, str | None]:
    """
    Prüft alle Decay-Regeln. Gibt (new_status, reason) zurück,
    oder (None, None) wenn Ticker bleibt wie er ist.
    """
    status = entry.get('status')

    # Nur active → dormant transitions prüfen (watchlist bleibt unberührt)
    if status != STATUS_ACTIVE:
        return (None, None)

    last_signal = entry.get('last_signal')
    last_trade = entry.get('last_trade')
    history = entry.get('conviction_history') or []

    days_since_signal = _days_ago(last_signal) if last_signal else _days_ago(entry.get('added_at'))
    days_since_trade = _days_ago(last_trade) if last_trade else 99999

    # Rule 1: Stale — kein Signal seit 30 Tagen
    if days_since_signal >= STALE_DAYS:
        return (STATUS_DORMANT, f'stale_no_signal ({days_since_signal}d)')

    # Rule 2: Low activity — kein Trade seit 60d + wenig Signals
    if days_since_trade >= LOW_ACTIVITY_DAYS and len(history) < LOW_ACTIVITY_MIN_SIGNALS:
        return (STATUS_DORMANT, f'low_activity ({days_since_trade}d no trade, {len(history)} signals)')

    # Rule 3: Falling Knife persistent
    dormant_since_check = entry.get('falling_knife_since')
    if _is_falling_knife_now(ticker):
        if not dormant_since_check:
            # erstes Mal — tracken
            entry['falling_knife_since'] = date.today().isoformat()
        else:
            days_fk = _days_ago(dormant_since_check)
            if days_fk >= FALLING_KNIFE_STREAK:
                return (STATUS_DORMANT, f'falling_knife_persistent ({days_fk}d)')
    else:
        # Reset wenn kein Falling Knife mehr
        if 'falling_knife_since' in entry:
            entry.pop('falling_knife_since', None)

    # Rule 4: Low average conviction
    avg = _avg_recent_conviction(history, LOW_CONVICTION_WINDOW)
    if avg is not None and len(history) >= LOW_CONVICTION_WINDOW and avg < LOW_CONVICTION_AVG:
        return (STATUS_DORMANT, f'low_conviction (avg {avg:.1f})')

    return (None, None)


def evaluate_resurrection(ticker: str, entry: dict) -> bool:
    """
    Prüft ob ein dormant Ticker reaktiviert werden sollte.
    Rückgabewert: True = auf watchlist setzen.
    """
    if entry.get('status') != STATUS_DORMANT:
        return False
    news_30d = entry.get('news_mentions_30d') or 0
    if news_30d < RESURRECTION_NEWS_7D:
        return False
    history = entry.get('conviction_history') or []
    recent_avg = _avg_recent_conviction(history, 5)
    if recent_avg is None or recent_avg < RESURRECTION_CONVICTION:
        return False
    return True


# ── Main Run ──────────────────────────────────────────────────────────────────

def run() -> dict:
    print('── Universe Decay Run ──')
    u = load_universe()
    if not u:
        print('Empty universe — nothing to do')
        return {'processed': 0, 'dormant': 0, 'resurrected': 0}

    dormant_moves: list[dict] = []
    resurrected: list[dict] = []
    today = date.today().isoformat()

    for ticker, entry in list(u.items()):
        # Skip Meta-Keys (_info, _count, _updated) und Legacy-Strukturen
        # (sectors{}, etfs_for_regime_check{}) — Decay arbeitet nur auf
        # per-Ticker-Dicts mit 'status'-Feld.
        if ticker.startswith('_') or not isinstance(entry, dict):
            continue
        if 'status' not in entry:
            continue
        # Decay check
        new_status, reason = evaluate_ticker(ticker, entry)
        if new_status == STATUS_DORMANT:
            entry['status'] = STATUS_DORMANT
            entry['dormant_reason'] = reason
            entry['dormant_since'] = today
            entry.setdefault('status_history', []).append({
                'date': today,
                'from': STATUS_ACTIVE,
                'to': STATUS_DORMANT,
                'reason': reason,
            })
            dormant_moves.append({'ticker': ticker, 'reason': reason})
            continue

        # Resurrection check
        if evaluate_resurrection(ticker, entry):
            entry['status'] = STATUS_WATCHLIST
            entry['dormant_reason'] = None
            entry['dormant_since'] = None
            entry.setdefault('status_history', []).append({
                'date': today,
                'from': STATUS_DORMANT,
                'to': STATUS_WATCHLIST,
                'reason': 'resurrection: news_mentions + conviction rebound',
            })
            resurrected.append({'ticker': ticker})

    save_universe(u)

    # Audit log
    log_entry = {
        'date': today,
        'dormant_moves': dormant_moves,
        'resurrected': resurrected,
        'total_active': sum(1 for v in u.values() if v.get('status') == STATUS_ACTIVE),
        'total_dormant': sum(1 for v in u.values() if v.get('status') == STATUS_DORMANT),
        'total_watchlist': sum(1 for v in u.values() if v.get('status') == STATUS_WATCHLIST),
    }
    try:
        existing = []
        if DECAY_LOG.exists():
            existing = json.loads(DECAY_LOG.read_text(encoding='utf-8'))
        existing.append(log_entry)
        existing = existing[-90:]  # last 90 runs
        DECAY_LOG.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'[decay] log write failed: {e}')

    # Discord queue (via digest, not immediate)
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_queue import queue_event
        if dormant_moves or resurrected:
            body = ''
            if dormant_moves:
                body += f'\n💤 Dormant ({len(dormant_moves)}):\n'
                for m in dormant_moves[:5]:
                    body += f'  • {m["ticker"]}: {m["reason"]}\n'
                if len(dormant_moves) > 5:
                    body += f'  … und {len(dormant_moves)-5} weitere\n'
            if resurrected:
                body += f'\n🔄 Reaktiviert ({len(resurrected)}):\n'
                for r in resurrected[:5]:
                    body += f'  • {r["ticker"]}\n'
            queue_event(
                priority='info',
                title='Universe Decay',
                body=body,
                source='universe_decay',
            )
    except Exception as e:
        print(f'[decay] queue event failed: {e}')

    print(f'Dormant moves: {len(dormant_moves)}')
    for m in dormant_moves[:10]:
        print(f'  {m["ticker"]:12} → {m["reason"]}')
    print(f'Resurrected: {len(resurrected)}')
    for r in resurrected[:10]:
        print(f'  {r["ticker"]:12}')
    print(f'Final: active={log_entry["total_active"]} dormant={log_entry["total_dormant"]} watchlist={log_entry["total_watchlist"]}')

    return {
        'processed': len(u),
        'dormant': len(dormant_moves),
        'resurrected': len(resurrected),
    }


if __name__ == '__main__':
    run()
