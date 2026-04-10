#!/usr/bin/env python3.13
"""
Discord Sender — Direkter Bot-API-Zugriff ohne OpenClaw-Agent.
Liest Bot-Token aus OpenClaw-Config → sendet Nachrichten via HTTP.
Kein LLM, keine Tokens, keine Kosten.
"""
import json
import urllib.request
import urllib.error
from pathlib import Path

OPENCLAW_CFG = Path('/data/.openclaw/openclaw.json')
VICTOR_DM = '1492225799062032484'   # Victor DM Channel

def _get_token() -> str:
    cfg = json.loads(OPENCLAW_CFG.read_text())
    return cfg['channels']['discord']['token']

def send(message: str, channel_id: str = VICTOR_DM) -> bool:
    """Sendet Discord-Nachricht direkt via Bot API. Gibt True bei Erfolg zurück."""
    try:
        token = _get_token()
        url = f'https://discord.com/api/v10/channels/{channel_id}/messages'
        payload = json.dumps({'content': message[:2000]}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'TradeMind-Scheduler/1.0',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f'Discord send error: {e}')
        return False

if __name__ == '__main__':
    import sys
    msg = ' '.join(sys.argv[1:]) or 'Test von discord_sender.py'
    ok = send(msg)
    print('✅ Gesendet' if ok else '❌ Fehler')


def send_alert(priority: str, title: str, body: str):
    """
    Strukturierter Alert mit Priorität.
    priority: 'critical' | 'warning' | 'info' | 'success'
    """
    icons = {'critical': '🚨', 'warning': '⚠️', 'info': '📊', 'success': '✅'}
    icon = icons.get(priority, '📌')
    msg = f"{icon} **{title}**\n{body}"
    send(msg)
