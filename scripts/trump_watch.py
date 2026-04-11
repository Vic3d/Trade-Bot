#!/usr/bin/env python3
"""
Trump Watch — Truth Social Monitor für Iran Peace Signale
=========================================================
Scannt trumpstruth.org/feed (RSS) alle 30 Min nach Keywords
die auf einen Iran-Deal, Ceasefire oder Hormuz-Öffnung hindeuten.

Bei Match → Sofort-Alert an Victor mit Handlungsplan:
  EQNR Exit + LHA Entry

Autor: Albert 🎩 | 31.03.2026
"""

import json
import re
import sys
import hashlib
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
STATE_FILE = WS / 'data/trump_watch_state.json'
LOG_FILE = WS / 'memory/trump-watch-log.md'

FEED_URL = 'https://trumpstruth.org/feed'

# ── Keywords ──────────────────────────────────────────────────────────────────

# PEACE signals — wenn Trump einen Deal ankündigt
PEACE_KEYWORDS = [
    'deal', 'peace', 'ceasefire', 'agreement', 'treaty',
    'hormuz open', 'open for business', 'strait.*open',
    'negotiations.*success', 'war.*over', 'end.*war',
    'diplomatic', 'truce', 'armistice', 'surrender',
    'new regime.*agree', 'iran.*deal', 'iran.*peace',
    'mission accomplished', 'great victory', 'we won',
    'bring.*troops.*home', 'withdraw',
]

# ESCALATION signals — wenn Trump eskaliert
ESCALATION_KEYWORDS = [
    'destroy', 'obliterate', 'bomb', 'strike', 'attack',
    'nuclear', 'wipe out', 'devastat', 'annihilat',
    'no deal', 'deadline.*passed', 'deadline.*expired',
    'total destruction', 'kharg island',
    'power grid', 'electric.*plant', 'oil well.*destroy',
]

# IRAN-relevant (muss in Kombination mit peace/escalation sein)
IRAN_CONTEXT = [
    'iran', 'hormuz', 'persian gulf', 'tehran', 'kharg',
    'strait', 'regime', 'ayatollah', 'irgc', 'epic fury',
    'middle east', 'gulf', 'oil',
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
}


def load_state() -> dict:
    """Lade den letzten bekannten Stand."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {'seen_hashes': [], 'last_check': None, 'alert_count': 0}


def save_state(state: dict):
    """Speichere den aktuellen Stand."""
    state['last_check'] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_feed() -> list[dict]:
    """Hole Trump Truth Social Feed."""
    try:
        req = urllib.request.Request(FEED_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        print(f'FEHLER: Feed nicht erreichbar: {e}')
        return []

    posts = []
    try:
        root = ET.fromstring(data)
        for item in root.findall('.//item'):
            title = item.findtext('title', '') or ''
            desc = item.findtext('description', '') or ''
            link = item.findtext('link', '') or ''
            pub_date = item.findtext('pubDate', '') or ''
            
            # Content aus description extrahieren (oft HTML)
            content = re.sub(r'<[^>]+>', ' ', desc).strip()
            full_text = f'{title} {content}'.strip()
            
            if not full_text:
                continue
                
            post_hash = hashlib.md5(full_text[:200].encode()).hexdigest()[:12]
            
            posts.append({
                'title': title[:200],
                'content': content[:500],
                'full_text': full_text,
                'link': link,
                'pub_date': pub_date,
                'hash': post_hash,
            })
    except ET.ParseError as e:
        # Fallback: versuche als HTML zu parsen
        text = data.decode('utf-8', errors='replace')
        # Extrahiere Text-Blöcke
        blocks = re.findall(r'<p[^>]*>(.*?)</p>', text, re.DOTALL)
        for i, block in enumerate(blocks[:10]):
            clean = re.sub(r'<[^>]+>', ' ', block).strip()
            if len(clean) > 50:
                post_hash = hashlib.md5(clean[:200].encode()).hexdigest()[:12]
                posts.append({
                    'title': '',
                    'content': clean[:500],
                    'full_text': clean,
                    'link': FEED_URL,
                    'pub_date': '',
                    'hash': post_hash,
                })
    
    return posts


def classify_post(text: str) -> dict:
    """Klassifiziere einen Post: PEACE / ESCALATION / NEUTRAL."""
    text_lower = text.lower()
    
    # Prüfe Iran-Kontext
    has_iran_context = any(re.search(kw, text_lower) for kw in IRAN_CONTEXT)
    
    # Peace Score
    peace_matches = []
    for kw in PEACE_KEYWORDS:
        if re.search(kw, text_lower):
            peace_matches.append(kw)
    
    # Escalation Score
    escalation_matches = []
    for kw in ESCALATION_KEYWORDS:
        if re.search(kw, text_lower):
            escalation_matches.append(kw)
    
    peace_score = len(peace_matches)
    escalation_score = len(escalation_matches)
    
    # Kontext-Multiplikator
    if has_iran_context:
        peace_score *= 2
        escalation_score *= 2
    
    # Klassifikation
    if peace_score >= 4 and peace_score > escalation_score:
        signal = 'PEACE_SIGNAL'
        severity = 'CRITICAL' if peace_score >= 6 else 'HIGH'
    elif escalation_score >= 4 and escalation_score > peace_score:
        signal = 'ESCALATION_SIGNAL'
        severity = 'CRITICAL' if escalation_score >= 6 else 'HIGH'
    elif peace_score >= 2 and has_iran_context:
        signal = 'PEACE_WATCH'
        severity = 'MEDIUM'
    elif escalation_score >= 2 and has_iran_context:
        signal = 'ESCALATION_WATCH'
        severity = 'MEDIUM'
    elif has_iran_context and (peace_score > 0 or escalation_score > 0):
        signal = 'IRAN_MENTION'
        severity = 'LOW'
    else:
        signal = 'NEUTRAL'
        severity = 'NONE'
    
    return {
        'signal': signal,
        'severity': severity,
        'peace_score': peace_score,
        'escalation_score': escalation_score,
        'has_iran_context': has_iran_context,
        'peace_matches': peace_matches,
        'escalation_matches': escalation_matches,
    }


def build_peace_alert(post: dict, classification: dict) -> str:
    """Baue den Sofort-Alert für Victor bei Peace Signal."""
    return f"""🕊️ **TRUMP PEACE SIGNAL — Iran Deal**

**Post:** {post['content'][:300]}
**Link:** {post['link']}
**Keywords:** {', '.join(classification['peace_matches'])}
**Score:** Peace {classification['peace_score']} vs Escalation {classification['escalation_score']}

---
⚡ **SOFORT-HANDLUNGSPLAN:**

**1. EQNR** — Stop auf €35.20 liegt. Wenn Deal bestätigt:
   → Sofort VERKAUFEN (Market Order in TR)
   → Erwarteter Verlust: -8% bis -12% vom aktuellen Kurs

**2. LHA.DE** — Limit-Order €6.80–7.00 vorbereiten:
   → Wenn Deal bestätigt: SOFORT kaufen (LHA springt +15-25%)
   → Stop bei €6.00 setzen
   → WKN: 823212

**3. Öl-Positionen** (A3D42Y etc.):
   → Alle Stops prüfen, enger nachziehen

⚠️ NICHT sofort handeln — erst Faktencheck!
Rubio + Pentagon-Bestätigung abwarten, nicht nur Trump-Post."""


def build_escalation_alert(post: dict, classification: dict) -> str:
    """Baue den Alert für Victor bei Eskalations-Signal."""
    return f"""🔴 **TRUMP ESKALATION — Iran**

**Post:** {post['content'][:300]}
**Link:** {post['link']}
**Keywords:** {', '.join(classification['escalation_matches'])}

---
📊 **Einschätzung:** Trump droht öffentlich — das ist meist Verhandlungstaktik.
EQNR profitiert kurzfristig von Eskalation. Stop €35.20 bleibt.
Keine Aktion nötig, aber Iran Peace Watch bleibt aktiv."""


def log_check(posts: list, results: list):
    """Schreibe in das Trump Watch Log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    
    if not LOG_FILE.exists():
        LOG_FILE.write_text('# Trump Watch Log\n\n', encoding="utf-8")
    
    signals = [r for r in results if r['classification']['signal'] != 'NEUTRAL']
    
    with open(LOG_FILE, 'a') as f:
        if signals:
            for r in signals:
                f.write(f"\n## [{ts}] {r['classification']['signal']} (Peace:{r['classification']['peace_score']} Esc:{r['classification']['escalation_score']})\n")
                f.write(f"{r['post']['content'][:150]}...\n---\n")
        else:
            f.write(f"\n[{ts}] Scan: {len(posts)} Posts, keine Signale\n")


def main():
    state = load_state()
    seen = set(state.get('seen_hashes', []))
    
    # Feed holen
    posts = fetch_feed()
    if not posts:
        print('KEIN_SIGNAL — Feed leer oder nicht erreichbar')
        save_state(state)
        return
    
    # Neue Posts filtern
    new_posts = [p for p in posts if p['hash'] not in seen]
    
    if not new_posts:
        print(f'KEIN_SIGNAL — {len(posts)} Posts gescannt, keine neuen')
        save_state(state)
        return
    
    # Klassifizieren
    results = []
    alerts = []
    
    for post in new_posts:
        classification = classify_post(post['full_text'])
        results.append({'post': post, 'classification': classification})
        
        # Hashes merken
        seen.add(post['hash'])
        
        if classification['severity'] in ('CRITICAL', 'HIGH'):
            if 'PEACE' in classification['signal']:
                alerts.append(('PEACE', build_peace_alert(post, classification)))
            elif 'ESCALATION' in classification['signal']:
                alerts.append(('ESCALATION', build_escalation_alert(post, classification)))
    
    # State aktualisieren (max 200 Hashes behalten)
    state['seen_hashes'] = list(seen)[-200:]
    state['alert_count'] = state.get('alert_count', 0) + len(alerts)
    
    # Loggen
    log_check(posts, results)
    
    # Output
    signal_posts = [r for r in results if r['classification']['signal'] != 'NEUTRAL']
    
    if alerts:
        for alert_type, alert_text in alerts:
            print(f'DISCORD_ALERT:{alert_type}')
            print(alert_text)
            print('---')
    elif signal_posts:
        for r in signal_posts:
            c = r['classification']
            print(f"WATCH: {c['signal']} — Peace:{c['peace_score']} Esc:{c['escalation_score']} — {r['post']['content'][:100]}")
    else:
        print(f'KEIN_SIGNAL — {len(new_posts)} neue Posts gescannt, keine Iran-Relevanz')
    
    save_state(state)


if __name__ == '__main__':
    main()
