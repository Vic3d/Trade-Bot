#!/usr/bin/env python3
"""
alert_dispatcher.py — Liest CEO-Queue und sendet CRITICAL/ALERT direkt an Discord
===================================================================================
Wird alle 15 Min von einem Haiku-Cron aufgerufen.
Bei CRITICAL: sendet sofort an Victor via message-Tool.
Bei ALERT: sammelt und sendet kompakten Überblick.

Output-Protokoll:
  KEIN_SIGNAL          — Queue leer, nichts zu tun
  DISCORD_ALERT:...    — Alert muss an Victor (vom aufrufenden Cron gesendet)
"""

import json
import sys
from pathlib import Path
from datetime import datetime

WS = Path('/data/.openclaw/workspace')
sys.path.insert(0, str(WS / 'scripts'))

from ceo_queue import read_queue, mark_processed, purge_old

def main():
    # Alte Einträge bereinigen
    purge_old(max_age_hours=24)
    
    # Unverarbeitete Items lesen (WATCH und höher)
    items = read_queue(min_priority='ALERT', unprocessed_only=True)
    
    if not items:
        print('KEIN_SIGNAL')
        return
    
    # Nach Priorität sortieren
    critical = [i for i in items if i.get('priority') == 'CRITICAL']
    alerts = [i for i in items if i.get('priority') == 'ALERT']
    
    messages = []
    
    # CRITICAL items — einzeln und sofort
    for item in critical:
        msg = f"🚨 **CRITICAL — {item.get('source', '?')}**\n"
        msg += f"{item.get('headline', '')}\n"
        if item.get('detail'):
            msg += f"{item['detail'][:200]}\n"
        if item.get('thesis'):
            msg += f"These: {item['thesis']}"
        messages.append(msg)
    
    # ALERT items — zusammenfassen
    if alerts:
        msg = f"📊 **{len(alerts)} Alert{'s' if len(alerts)>1 else ''} seit letztem Check:**\n"
        for a in alerts[:5]:
            msg += f"• [{a.get('source', '?')}] {a.get('headline', '')[:100]}\n"
        messages.append(msg)
    
    # Alle als verarbeitet markieren
    all_ids = [i.get('id') for i in items if i.get('id')]
    mark_processed(all_ids)
    
    # Output für den aufrufenden Cron
    full_message = '\n---\n'.join(messages)
    print(f"DISCORD_ALERT:{full_message}")


if __name__ == '__main__':
    main()
