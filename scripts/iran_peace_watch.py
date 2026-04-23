#!/usr/bin/env python3
"""
Iran Peace Watch — Sofort-Alert für S10 Lufthansa
Läuft alle 30 Min. Sendet SOFORT wenn Peace-Signal gefunden.
"""
import urllib.request, urllib.parse, re, json, time, hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WORKSPACE = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
STATE_FILE = WORKSPACE / 'data/iran_peace_watch_state.json'

PEACE_KEYWORDS = [
    'iran ceasefire', 'iran waffenstillstand', 'iran peace',
    'iran friedensgespräche', 'iran nuclear deal', 'hormuz reopened',
    'iran de-escalation', 'iran deeskalation', 'iran agreement',
    'iran verhandlungen', 'iran talks success', 'iran truce',
    'middle east ceasefire', 'iran sanctions lifted',
    'khamenei ceasefire', 'iran stops', 'waffenstillstand nahost',
    'friedensgespräche iran', 'hormuz öffnung',
]

# Bug W (2026-04-22): Negationen, die ein Peace-Match invalidieren —
# event_auto_exit konsumiert ANY new hash als IRAN_PEACE_SIGNED → False-Positives
# wie "Trump rejects iran ceasefire" würden Defense+Oil-Positionen schließen.
NEGATION_KEYWORDS = [
    'reject', 'rejects', 'rejected', 'collapse', 'collapses', 'collapsed',
    'fails', 'failed', 'breakdown', 'breaks down', 'no deal', 'walk out',
    'walked out', 'abandons', 'abandoned', 'abgebrochen', 'gescheitert',
    'scheitert', 'lehnt ab', 'lehnt iran ab', 'kein deal', 'pause',
    'suspend', 'suspended', 'ausgesetzt',
]

QUERIES = [
    'Iran ceasefire peace 2026',
    'Iran Waffenstillstand Friedensgespräche',
    'Hormuz strait reopened',
    'Iran nuclear deal negotiations',
    'Iran war end ceasefire',
]

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {'seen_hashes': [], 'last_run': None}

def save_state(state):
    state['seen_hashes'] = state['seen_hashes'][-200:]  # max 200
    STATE_FILE.write_text(json.dumps(state, indent=2))

def headline_hash(h):
    return hashlib.md5(h.lower().strip().encode()).hexdigest()[:12]

def fetch_news(query):
    q = urllib.parse.quote(query)
    url = f'https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            content = r.read().decode('utf-8', errors='replace')
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', content)[1:6]
        sources = re.findall(r'<source.*?>(.*?)</source>', content)[:6]
        return list(zip(titles, sources + [''] * 10))
    except:
        return []

def check_liveuamap():
    """Liveuamap Iran kurz checken auf Peace-Signale."""
    try:
        req = urllib.request.Request(
            'https://iran.liveuamap.com/',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            content = r.read().decode('utf-8', errors='replace')
        low = content.lower()
        hits = [kw for kw in PEACE_KEYWORDS if kw in low]
        return hits
    except:
        return []

def run():
    state = load_state()
    new_signals = []
    
    print(f'Iran Peace Watch — {datetime.now(_BERLIN).strftime("%Y-%m-%d %H:%M")}')
    
    # 1. Google News
    for query in QUERIES:
        for title, source in fetch_news(query):
            h = headline_hash(title)
            if h in state['seen_hashes']:
                continue
            low = title.lower()
            matched = [kw for kw in PEACE_KEYWORDS if kw in low]
            # Bug W: Negation aussortieren — "rejected/collapsed/failed" = keine Peace.
            if matched and any(neg in low for neg in NEGATION_KEYWORDS):
                continue
            if matched:
                new_signals.append({
                    'title': title,
                    'source': source,
                    'keywords': matched,
                    'hash': h,
                })
                state['seen_hashes'].append(h)
    
    # 2. Liveuamap
    map_hits = check_liveuamap()
    if map_hits:
        print(f'  Liveuamap Iran: {map_hits}')
    
    state['last_run'] = datetime.now().isoformat()
    save_state(state)
    
    if new_signals:
        print(f'PEACE_SIGNAL_FOUND: {len(new_signals)} neue Treffer')
        for s in new_signals:
            print(f'  • {s["title"][:80]} [{s["source"]}]')
        # Für Discord-Alert formatieren
        lines = ['☮️ **S10 PEACE-SIGNAL — Iran**\n']
        for s in new_signals[:4]:
            lines.append(f'📰 {s["title"]}')
            if s["source"]: lines.append(f'   _Quelle: {s["source"]}_')
        lines.append('\n💡 **S10 Lufthansa** jetzt auf Watch-Status prüfen:')
        lines.append('`python3 scripts/s10_lufthansa_monitor.py`')
        lines.append('\n⚡ Bei 2+ Triggern → Entry vorbereiten!')
        print('DISCORD_ALERT:' + '\n'.join(lines))
    else:
        print(f'KEIN_SIGNAL — Keine neuen Peace-Signale ({len(QUERIES)} Queries)')

if __name__ == '__main__':
    run()
