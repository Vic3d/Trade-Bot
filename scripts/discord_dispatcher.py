#!/usr/bin/env python3
"""
Discord Dispatcher — Phase 22.4 Priority-Tiering
===================================================
Zentrale Schaltstelle fuer alle Discord-Nachrichten. Entscheidet anhand
Tier+Kategorie, ob sofort raus, in Batch-Queue oder nur in Abend-Report.

Tier-Levels:
  HIGH   — sofort, 24/7 inkl. Nacht. Trade-Ausfuehrung, Stop-Hit,
           Circuit Breaker, Tier-1-Geo-Alert, Auto-Promote KAUFEN,
           Kill-Trigger aktiv.
  MEDIUM — Batch 4x/Tag (09:00, 12:00, 17:00, 22:00). Tranche-Exits,
           Verdict-Changes, Thesis-Updates ohne Action, Alpha-Decay.
  LOW    — nur Abend-Report 22:00 konsolidiert. Market-Open-Pings,
           Debug-Warnings, Scanner-Misses, Geo-Tier-2/3.

Quiet-Hours 23:00-07:00: Nur HIGH durchlassen, MEDIUM/LOW warten.

Dedupe: Gleicher dedupe_key innerhalb 1h wird unterdrueckt.

API:
  from discord_dispatcher import send_alert
  send_alert("STOP HIT NVDA", tier='HIGH', category='trade')
  send_alert("Thesis aged 30d", tier='LOW', category='thesis',
             dedupe_key='PS_NVDA_age')

Flush (aus Scheduler):
  from discord_dispatcher import flush_medium, flush_low
  flush_medium()  # 4x/Tag
  flush_low()     # 1x/Tag im Abend-Report
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
QUEUE_MEDIUM = WS / 'data' / 'discord_queue_medium.jsonl'
QUEUE_LOW = WS / 'data' / 'discord_queue_low.jsonl'
DEDUPE_LOG = WS / 'data' / 'discord_dedupe.json'

QUIET_START_H = 23  # 23:00
QUIET_END_H = 7     # 07:00

TIER_HIGH = 'HIGH'
TIER_MEDIUM = 'MEDIUM'
TIER_LOW = 'LOW'
VALID_TIERS = (TIER_HIGH, TIER_MEDIUM, TIER_LOW)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _in_quiet_hours() -> bool:
    """Lokale Zeit CET — wir verwenden UTC+1 ganz einfach (Sommer +2 wird
    in CET/CEST nicht exakt, aber 23-07 Slot ist gross genug)."""
    h = (_now() + timedelta(hours=2)).hour  # CEST
    return h >= QUIET_START_H or h < QUIET_END_H


def _load_dedupe() -> dict:
    if not DEDUPE_LOG.exists():
        return {}
    try:
        return json.loads(DEDUPE_LOG.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_dedupe(d: dict) -> None:
    try:
        DEDUPE_LOG.parent.mkdir(parents=True, exist_ok=True)
        DEDUPE_LOG.write_text(json.dumps(d, indent=2), encoding='utf-8')
    except Exception:
        pass


def _is_duplicate(dedupe_key: str, window_sec: int = 3600) -> bool:
    if not dedupe_key:
        return False
    d = _load_dedupe()
    last_iso = d.get(dedupe_key)
    if not last_iso:
        return False
    try:
        last = datetime.fromisoformat(last_iso)
        age = (_now() - last).total_seconds()
        return age < window_sec
    except Exception:
        return False


def _mark_sent(dedupe_key: str) -> None:
    if not dedupe_key:
        return
    d = _load_dedupe()
    d[dedupe_key] = _now().isoformat()
    # Alte Keys (>24h) wegwerfen
    cutoff = _now() - timedelta(hours=24)
    d = {k: v for k, v in d.items()
         if datetime.fromisoformat(v.replace('Z', '+00:00')) > cutoff}
    _save_dedupe(d)


def _append_queue(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _send_now(msg: str) -> bool:
    """Direkter Send via discord_sender."""
    try:
        import sys
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        return send(msg)
    except Exception as e:
        print(f'[dispatcher] send_error: {e}')
        return False


def send_alert(
    message: str,
    tier: str = TIER_HIGH,
    category: str = 'general',
    dedupe_key: str | None = None,
) -> bool:
    """
    Zentrale Alert-API.

    Args:
        message: Nachrichten-Text (max 2000 Zeichen wg Discord-Limit)
        tier: HIGH | MEDIUM | LOW
        category: trade | thesis | geo | debug | market | discovery | ...
        dedupe_key: Optional — gleicher Key innerhalb 1h wird suppressed

    Returns:
        True wenn zugestellt oder erfolgreich gequeued, False bei Fehler.
    """
    if tier not in VALID_TIERS:
        tier = TIER_HIGH  # Safety-Default: im Zweifel durchlassen

    if _is_duplicate(dedupe_key or ''):
        return False

    entry = {
        'ts': _now().isoformat(timespec='seconds'),
        'tier': tier,
        'category': category,
        'message': message,
    }

    # Quiet-Hours: MEDIUM/LOW warten bis zum naechsten Flush
    quiet = _in_quiet_hours()

    if tier == TIER_HIGH:
        # Immer sofort — auch Nachts
        ok = _send_now(message)
        if ok and dedupe_key:
            _mark_sent(dedupe_key)
        return ok

    if tier == TIER_MEDIUM:
        _append_queue(QUEUE_MEDIUM, entry)
        if dedupe_key:
            _mark_sent(dedupe_key)
        return True

    if tier == TIER_LOW:
        _append_queue(QUEUE_LOW, entry)
        if dedupe_key:
            _mark_sent(dedupe_key)
        return True

    return False


def _drain_queue(path: Path) -> list[dict]:
    """Liest Queue-Datei, leert sie, returnt Eintraege."""
    if not path.exists():
        return []
    entries = []
    try:
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        path.unlink()  # queue leeren
    except Exception as e:
        print(f'[dispatcher] drain_error {path}: {e}')
    return entries


def _format_digest(entries: list[dict], title: str) -> str:
    """Bundelt Entries nach Kategorie in eine Nachricht."""
    if not entries:
        return ''
    # Nach Kategorie gruppieren
    by_cat: dict[str, list[dict]] = {}
    for e in entries:
        by_cat.setdefault(e.get('category', 'general'), []).append(e)

    lines = [f'**{title}**  ({len(entries)} Events)']
    cat_icons = {
        'trade': '📈', 'thesis': '🧠', 'geo': '🌍', 'debug': '⚙️',
        'market': '📊', 'discovery': '🔍', 'exit': '🚪',
        'verdict': '⚖️', 'general': '📌',
    }
    for cat, items in by_cat.items():
        icon = cat_icons.get(cat, '📌')
        lines.append(f'\n{icon} **{cat.upper()}** ({len(items)}):')
        # Max 10 pro Kategorie im Digest
        for e in items[:10]:
            ts = e.get('ts', '')[11:16]  # HH:MM
            msg = e.get('message', '')[:180]
            lines.append(f'  `{ts}` {msg}')
        if len(items) > 10:
            lines.append(f'  ... +{len(items) - 10} weitere')
    return '\n'.join(lines)[:1990]


def flush_medium() -> int:
    """Sendet MEDIUM-Queue als kompakten Digest. Aus Scheduler 4x/Tag.
    Waehrend Quiet-Hours: skip (naechster Flush nimmt mit).
    Returns Anzahl zugestellter Events."""
    if _in_quiet_hours():
        return 0
    entries = _drain_queue(QUEUE_MEDIUM)
    if not entries:
        return 0
    digest = _format_digest(entries, 'Digest — Updates')
    if digest:
        _send_now(digest)
    return len(entries)


def flush_low() -> int:
    """Konsolidiert LOW-Queue, haengt sie an den 22:00 Abend-Report oder
    sendet als eigene Nachricht. Aus Scheduler 1x/Tag abends."""
    entries = _drain_queue(QUEUE_LOW)
    if not entries:
        return 0
    digest = _format_digest(entries, 'Tages-Hintergrund')
    if digest:
        _send_now(digest)
    return len(entries)


def get_queue_stats() -> dict:
    """Debug: wieviel steht in Queues?"""
    def _count(p: Path) -> int:
        if not p.exists():
            return 0
        try:
            return sum(1 for _ in p.open(encoding='utf-8'))
        except Exception:
            return 0
    return {
        'medium_queued': _count(QUEUE_MEDIUM),
        'low_queued': _count(QUEUE_LOW),
        'quiet_hours_active': _in_quiet_hours(),
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--test', action='store_true')
    ap.add_argument('--flush-medium', action='store_true')
    ap.add_argument('--flush-low', action='store_true')
    ap.add_argument('--stats', action='store_true')
    args = ap.parse_args()

    if args.test:
        print('HIGH test:')
        send_alert('🧪 HIGH test — sollte sofort ankommen', tier='HIGH', category='debug')
        print('MEDIUM test:')
        send_alert('🧪 MEDIUM test — in Batch gequeued', tier='MEDIUM', category='debug')
        print('LOW test:')
        send_alert('🧪 LOW test — im Abend-Report', tier='LOW', category='debug')
        print(get_queue_stats())
    elif args.flush_medium:
        n = flush_medium()
        print(f'flushed {n} MEDIUM events')
    elif args.flush_low:
        n = flush_low()
        print(f'flushed {n} LOW events')
    elif args.stats:
        print(json.dumps(get_queue_stats(), indent=2))
    else:
        ap.print_help()
