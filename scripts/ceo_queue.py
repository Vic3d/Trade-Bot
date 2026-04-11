"""
ceo_queue.py — Gemeinsame Trigger-Queue für den CEO
====================================================
Alle Haiku-Collector schreiben hierher wenn sie etwas Relevantes finden.
Der CEO (Sonnet) liest die Queue und entscheidet was zu tun ist.

Prioritäten:
  INFO     — Routine-Fund, nur für Kontext
  WATCH    — Beobachten, kein sofortiger Handlungsbedarf
  ALERT    — CEO sollte das kennen (z.B. Thesis-Shift-Signal)
  CRITICAL — Sofortiger Handlungsbedarf (Stop Hit, Peace Deal, VIX Spike)

Usage:
  from ceo_queue import enqueue, read_queue, clear_processed

  enqueue(
      source='GeoScanner',
      priority='ALERT',
      headline='Iran schließt Hormuz teilweise',
      detail='Liveuamap: 3 Tanker gestoppt, US Navy reagiert',
      thesis='S1_Iran'
  )
"""

import json
from datetime import datetime
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
QUEUE_PATH = WS / 'data/ceo_trigger_queue.json'


def enqueue(source: str, priority: str, headline: str, detail: str = '', thesis: str = ''):
    """Eintrag zur CEO-Queue hinzufügen."""
    assert priority in ('INFO', 'WATCH', 'ALERT', 'CRITICAL'), f'Ungültige Priorität: {priority}'

    queue = _read_raw()
    queue.append({
        'id': f'{datetime.now().strftime("%Y%m%d%H%M%S")}_{source[:8]}',
        'timestamp': datetime.now().isoformat(),
        'source': source,
        'priority': priority,
        'headline': headline,
        'detail': detail,
        'thesis': thesis,
        'processed': False
    })
    QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2))


def read_queue(min_priority: str = 'WATCH', unprocessed_only: bool = True) -> list:
    """Queue lesen, gefiltert nach Priorität."""
    order = {'INFO': 0, 'WATCH': 1, 'ALERT': 2, 'CRITICAL': 3}
    min_level = order.get(min_priority, 1)

    queue = _read_raw()
    result = [
        q for q in queue
        if order.get(q.get('priority', 'INFO'), 0) >= min_level
        and (not unprocessed_only or not q.get('processed', False))
    ]
    return sorted(result, key=lambda x: order.get(x.get('priority', 'INFO'), 0), reverse=True)


def mark_processed(entry_ids: list):
    """Einträge als verarbeitet markieren."""
    queue = _read_raw()
    for entry in queue:
        if entry.get('id') in entry_ids:
            entry['processed'] = True
    QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2))


def has_critical() -> bool:
    """Gibt True zurück wenn unverarbeitete CRITICAL/ALERT Items in der Queue sind."""
    return len(read_queue(min_priority='ALERT')) > 0


def summary() -> str:
    """Kompakte Queue-Zusammenfassung für CEO."""
    items = read_queue(min_priority='WATCH')
    if not items:
        return 'Queue leer.'
    lines = [f'Queue: {len(items)} unverarbeitete Items']
    for item in items[:8]:
        lines.append(f"  [{item['priority']}] [{item['source']}] {item['headline']}")
        if item.get('detail'):
            lines.append(f"    → {item['detail'][:100]}")
    return '\n'.join(lines)


def _read_raw() -> list:
    try:
        if QUEUE_PATH.exists():
            return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def purge_old(max_age_hours: int = 24):
    """Verarbeitete und alte Einträge bereinigen."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
    queue = _read_raw()
    queue = [
        q for q in queue
        if not q.get('processed') or q.get('timestamp', '') > cutoff
    ]
    QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    print(summary())
