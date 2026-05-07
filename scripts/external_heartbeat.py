#!/usr/bin/env python3
"""
external_heartbeat.py — Phase 45aa (Victor 2026-05-07).

Dead-Man-Switch fuer den Scheduler-Daemon. Pingt einen externen Service
(healthchecks.io oder eigener Endpoint) regelmaessig. Wenn der Ping
ausbleibt, alerted der externe Service den User.

Schliesst Klasse G5 'Cron läuft nicht' — wenn systemd selbst broken
ist, kann interner Watchdog nicht alerten.

Konfiguration via data/heartbeat_config.json:
  {
    "url": "https://hc-ping.com/<uuid>",
    "enabled": true,
    "label": "trademind-scheduler"
  }

Wenn URL leer/disabled: lokaler Heartbeat in data/heartbeat_local.json
(damit Silence-Detector ihn checken kann).

Run: alle 5min via scheduler.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as _req
from urllib.error import URLError

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
CONFIG = WS / 'data' / 'heartbeat_config.json'
LOCAL_LOG = WS / 'data' / 'heartbeat_local.json'


def main() -> int:
    cfg = {}
    if CONFIG.exists():
        try: cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
        except Exception: pass

    url = cfg.get('url', '')
    enabled = cfg.get('enabled', True)
    label = cfg.get('label', 'trademind')

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')

    # Externer Ping
    external_status = 'disabled'
    if enabled and url:
        try:
            req = _req.Request(url, method='GET',
                                 headers={'User-Agent': f'{label}/heartbeat'})
            with _req.urlopen(req, timeout=10) as resp:
                external_status = f'ok_{resp.status}'
        except (URLError, Exception) as e:
            external_status = f'fail:{type(e).__name__}'

    # Lokaler Heartbeat (immer)
    LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_LOG.write_text(json.dumps({
        'last_ping_utc': now,
        'label': label,
        'external_status': external_status,
        'external_url_configured': bool(url),
    }, indent=2), encoding='utf-8')

    print(f'[heartbeat] {now} external={external_status}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
