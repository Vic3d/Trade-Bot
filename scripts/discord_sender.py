#!/usr/bin/env python3
"""
Discord Sender — Direkter Bot-API-Zugriff ohne OpenClaw-Agent.
Liest Bot-Token aus OpenClaw-Config → sendet Nachrichten via HTTP.
Kein LLM, keine Tokens, keine Kosten.

**Nachtruhe:** 23:00-07:00 CET — alle Nachrichten werden in die Queue
geschoben statt direkt gesendet (außer force=True). Das Morning Briefing
um 08:30 fasst alles zusammen.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

OPENCLAW_CFG = Path('/data/.openclaw/openclaw.json')
VICTOR_DM = '1492225799062032484'   # Victor DM Channel

# Nachtruhe-Fenster (deutsche Ortszeit, DST-aware)
QUIET_START = 23   # 23:00 deutsche Zeit
QUIET_END = 7      # 07:00 deutsche Zeit

# Fallback Token-Pfade für lokale Entwicklung
_LOCAL_TOKEN_FILE = Path(__file__).resolve().parent.parent / 'deploy' / '.env'


def _german_hour() -> int:
    """Aktuelle Stunde in deutscher Ortszeit (CET/CEST automatisch)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Europe/Berlin')).hour
    except Exception:
        # Fallback: CET (UTC+1) — im Sommer 1h daneben, aber safe
        return datetime.now(timezone(timedelta(hours=1))).hour


def _is_quiet_hours() -> bool:
    """True wenn gerade Nachtruhe ist (23:00-07:00 deutsche Zeit)."""
    hour = _german_hour()
    return hour >= QUIET_START or hour < QUIET_END


def _queue_for_morning(message: str) -> None:
    """Schiebt Nachricht in die Queue für das Morgen-Briefing."""
    try:
        WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
        queue_file = WS / 'data' / 'discord_queue.json'
        q = []
        if queue_file.exists():
            try:
                q = json.loads(queue_file.read_text(encoding='utf-8'))
            except Exception:
                q = []
        q.append({
            'ts': datetime.now().isoformat(timespec='seconds'),
            'priority': 'info',
            'icon': '🌙',
            'title': 'Nacht-Event',
            'body': message[:500],
            'source': 'quiet_hours',
        })
        queue_file.write_text(json.dumps(q, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'Queue for morning failed: {e}')


def _get_token() -> str:
    # 1. Server-Pfad (OpenClaw)
    if OPENCLAW_CFG.exists():
        cfg = json.loads(OPENCLAW_CFG.read_text(encoding='utf-8'))
        return cfg['channels']['discord']['token']
    # 2. Environment Variable
    token = os.environ.get('DISCORD_BOT_TOKEN', '')
    if token:
        return token
    # 3. Lokale .env Datei
    if _LOCAL_TOKEN_FILE.exists():
        for line in _LOCAL_TOKEN_FILE.read_text(encoding='utf-8').splitlines():
            if line.startswith('DISCORD_BOT_TOKEN=') and len(line) > 19:
                return line.split('=', 1)[1].strip()
    raise FileNotFoundError('Discord Bot Token nicht gefunden')


def _log_outgoing(message: str) -> None:
    """Loggt ausgehende Bot-Nachrichten ins Chat-Log."""
    log_path = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind')) / 'data' / 'discord_chat_log.jsonl'
    try:
        entry = json.dumps({
            'ts': datetime.now().isoformat(),
            'role': 'system',
            'content': message,
        }, ensure_ascii=False)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except Exception:
        pass


def send(message: str, channel_id: str = VICTOR_DM, force: bool = False) -> bool:
    """Sendet Discord-Nachricht direkt via Bot API.

    Während der Nachtruhe (23:00-07:00 CET) werden Nachrichten
    automatisch in die Queue für das Morgen-Briefing geschoben.
    force=True überspringt die Nachtruhe (für echte Notfälle wie Stop-Hits).
    """
    # Nachtruhe-Check
    if not force and _is_quiet_hours():
        print(f'[discord] Nachtruhe — in Queue geschoben: {message[:80]}...')
        _queue_for_morning(message)
        return True  # "sent" to queue

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
