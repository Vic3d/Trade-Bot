#!/usr/bin/env python3
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

# Fallback Token-Pfade für lokale Entwicklung
_LOCAL_TOKEN_FILE = Path(__file__).resolve().parent.parent / 'deploy' / '.env'

def _get_token() -> str:
    # 1. Server-Pfad (OpenClaw)
    if OPENCLAW_CFG.exists():
        cfg = json.loads(OPENCLAW_CFG.read_text(encoding="utf-8"))
        return cfg['channels']['discord']['token']
    # 2. Environment Variable
    import os
    token = os.environ.get('DISCORD_BOT_TOKEN', '')
    if token:
        return token
    # 3. Lokale .env Datei
    if _LOCAL_TOKEN_FILE.exists():
        for line in _LOCAL_TOKEN_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith('DISCORD_BOT_TOKEN=') and len(line) > 19:
                return line.split('=', 1)[1].strip()
    raise FileNotFoundError('Discord Bot Token nicht gefunden (weder OpenClaw, ENV, noch deploy/.env)')

def _log_outgoing(message: str) -> None:
    """Loggt ausgehende Bot-Nachrichten ins Chat-Log für Claude Code."""
    from datetime import datetime
    log_path = Path(__file__).resolve().parent.parent / 'data' / 'discord_chat_log.jsonl'
    try:
        entry = json.dumps({
            'ts': datetime.now().isoformat(),
            'role': 'system',  # Scheduler-Notifications, keine Albert-Antwort
            'content': message,
        }, ensure_ascii=False)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except Exception:
        pass

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
            ok = resp.status in (200, 201)
            if ok:
                _log_outgoing(message)
            return ok
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
