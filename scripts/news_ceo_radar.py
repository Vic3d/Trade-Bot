#!/usr/bin/env python3
"""
News → CEO Radar
================
Liest news_gate.json, dedupliziert gegen letzte Läufe,
ruft bei neuen relevanten Hits den CEO auf und sendet
bei actionablen Erkenntnissen einen Discord-Alert.

Wird vom scheduler_daemon.py nach dem News Gate Update aufgerufen.
"""

import json
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
GATE_FILE    = WS / 'data/news_gate.json'
STATE_FILE   = WS / 'data/news_radar_state.json'
ANALYSIS_OUT = WS / 'memory/newswire-analysis.md'

# ─── Keywords per These (für frische Google-Suche) ──────────────────────────
THESIS_QUERIES = {
    # Geopolitik & Rohstoffe
    'S1_Iran':     'Iran Hormuz Öl Eskalation',
    'PS1_Oil':     'Brent WTI Ölpreis OPEC crude oil',
    'S4_Silver':   'Silber Silver Gold safe haven precious metals',
    'S11_Steel':   'Stahl Zölle STLD Steel Dynamics tariff',
    # Tech & KI
    'S3_KI':       'Nvidia PLTR Palantir AI artificial intelligence earnings',
    'S3_KI_b':     'Microsoft MSFT AI cloud earnings guidance',
    # Rüstung & Industrials
    'S12_Rüstung': 'defense spending NATO Rheinmetall BAE LDO',
    # Pharma & Biotech
    'PS_Pharma':   'Bayer BAYN pharma FDA approval drug earnings',
    # Makro & Zölle
    'PS_Macro':    'Trump tariff trade war Fed interest rate inflation',
    # Airlines
    'PS_Airlines': 'Lufthansa LHA airline travel demand earnings',
}

# Thesen mit aktivem Portfolio-Impact (für direkten Alert)
HIGH_IMPACT_THESES = {'S1_Iran', 'PS1_Oil', 'S11_Steel', 'S12_Rüstung', 'S3_KI', 'S3_KI_b', 'S4_Silver', 'PS_Macro', 'PS_Pharma', 'PS_Airlines'}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {'seen_headlines': [], 'last_run': None, 'last_alert_ts': None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def fetch_headlines(query: str, n: int = 5) -> list[str]:
    url = f'https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=de&gl=DE&ceid=DE:de'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read())
        return [item.findtext('title', '') for item in root.findall('.//item')[:n]]
    except Exception:
        return []


def run_ceo_report() -> str:
    """CEO live-Report als String zurückgeben."""
    try:
        r = subprocess.run(
            [sys.executable, str(WS / 'scripts/ceo.py'), '--live', '--report'],
            capture_output=True, text=True, timeout=90, cwd=str(WS)
        )
        return r.stdout.strip()[-1200:] if r.stdout else ''
    except Exception as e:
        return f'CEO Fehler: {e}'


def send_discord(msg: str):
    sys.path.insert(0, str(WS / 'scripts'))
    try:
        from discord_sender import send
        send(msg[:1900])
    except Exception as e:
        print(f'Discord Fehler: {e}')


def is_actionable(headlines: list[str]) -> bool:
    """Prüft ob Headlines echte Handlungssignale enthalten."""
    action_words = [
        # Geopolitik
        'attack', 'strike', 'explosion', 'blockade', 'sanctions',
        'Angriff', 'Explosion', 'Blockade', 'Sanktionen', 'Ultimatum',
        'ceasefire', 'Waffenstillstand', 'Einigung', 'Eskalation', 'escalation',
        # Makro
        'tariff', 'Zoll', 'trade war', 'Handelskrieg', 'Fed rate', 'Zinsentscheid',
        'recession', 'Rezession', 'inflation',
        # Marktbewegungen
        'spike', 'crash', 'surge', 'plunge', 'rally', 'Einbruch',
        '100 Dollar', '$100', 'all-time high', 'Rekord',
        # Tech-Katalysatoren
        'earnings beat', 'earnings miss', 'guidance raised', 'guidance lowered',
        'revenue beat', 'Umsatz', 'contract', 'partnership', 'acquisition',
        'breakthrough', 'Durchbruch', 'deal', 'agreement',
        # Pharma-Katalysatoren
        'FDA approval', 'FDA approved', 'clinical trial', 'Phase 3', 'drug approval',
        'Zulassung',
        # Rüstung
        'defense contract', 'Rüstungsauftrag', 'NATO order', 'military spending',
    ]
    text = ' '.join(headlines).lower()
    return any(w.lower() in text for w in action_words)


def main():
    state = load_state()
    seen  = set(state.get('seen_headlines', []))

    # ─── Frische Headlines je These sammeln ─────────────────────────────────
    new_hits: list[dict] = []

    for thesis, query in THESIS_QUERIES.items():
        headlines = fetch_headlines(query)
        for hl in headlines:
            key = hl[:70]
            if key and key not in seen:
                new_hits.append({'thesis': thesis, 'headline': hl})
                seen.add(key)

    # Auch news_gate.json einbeziehen (falls bereits geschrieben)
    if GATE_FILE.exists():
        try:
            gate = json.loads(GATE_FILE.read_text(encoding="utf-8"))
            for h in gate.get('top_hits', []):
                key = h.get('headline', '')[:70]
                if key and key not in seen:
                    new_hits.append({'thesis': h.get('thesis', '?'), 'headline': h.get('headline', '')})
                    seen.add(key)
        except Exception:
            pass

    if not new_hits:
        print('KEIN_SIGNAL — keine neuen Headlines')
        state['last_run'] = datetime.now().isoformat()
        state['seen_headlines'] = list(seen)[-300:]  # max 300 merken
        save_state(state)
        return

    # ─── Bestimme ob High-Impact-These getroffen ────────────────────────────
    high_impact = [h for h in new_hits if h['thesis'] in HIGH_IMPACT_THESES]
    actionable  = is_actionable([h['headline'] for h in new_hits])

    headlines_text = '\n'.join(
        f"  [{h['thesis']}] {h['headline'][:90]}"
        for h in new_hits[:10]
    )

    # ─── In Analysis-File schreiben ─────────────────────────────────────────
    ts = datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M')
    entry = (
        f'\n## [{ts}] News Radar — {len(new_hits)} neue Headlines\n'
        f'{headlines_text}\n'
        f'High-Impact: {len(high_impact)} | Actionable: {actionable}\n'
        '---\n'
    )
    if ANALYSIS_OUT.exists():
        with open(ANALYSIS_OUT, 'a') as f:
            f.write(entry)

    print(f'Neue Headlines: {len(new_hits)} | High-Impact: {len(high_impact)} | Actionable: {actionable}')
    for h in new_hits[:5]:
        print(f"  [{h['thesis']}] {h['headline'][:85]}")

    # ─── CEO nur bei High-Impact + Actionable aufrufen ──────────────────────
    if high_impact and actionable:
        print('→ CEO analysiert...')
        ceo_output = run_ceo_report()

        # Alert formatieren
        theses_list = ', '.join(sorted({h['thesis'] for h in high_impact}))
        top_headlines = '\n'.join(f"• {h['headline'][:85]}" for h in high_impact[:4])

        alert = (
            f'📡 **News Radar — {theses_list}**\n'
            f'{top_headlines}\n\n'
            f'**CEO Analyse:**\n'
            f'{ceo_output[:600]}'
        )

        send_discord(alert)
        state['last_alert_ts'] = datetime.now().isoformat()
        print('✅ Alert gesendet')
    else:
        print(f'→ Kein Alert (high_impact={len(high_impact)}, actionable={actionable})')

    # ─── State speichern ────────────────────────────────────────────────────
    state['last_run'] = datetime.now().isoformat()
    state['seen_headlines'] = list(seen)[-300:]
    save_state(state)


if __name__ == '__main__':
    main()
