#!/usr/bin/env python3
"""
Pre-Mortem Gate — Phase 22
============================
Vor jedem Entry: Zwingt explizite Falsifikation.
Ohne klares "Wenn X passiert, ist die These tot + Exit-Plan" → BLOCK.

Prueft den `falsification`-String im Deep-Dive-Verdict:
  - Muss konkretes, messbares Ereignis enthalten (Preis, Datum, Metric)
  - Muss Exit-Trigger beschreiben
  - Vage Phrasen wie "wenn Markt dreht" oder "bei schlechten News" = BLOCK

CLI:
  python3 scripts/pre_mortem_check.py TICKER
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
VERDICTS = WS / 'data' / 'deep_dive_verdicts.json'

# Vage Phrasen die KEINE valide Falsifikation sind
VAGUE_PHRASES = [
    'wenn markt dreht', 'bei schlechten news', 'wenn es nicht klappt',
    'bei unerwarteten ereignissen', 'wenn kurs faellt', 'market turns',
    'bad news', 'something changes', 'generally bearish', 'if it goes wrong',
    'wenn sich die lage verschlechtert', 'allgemeine marktschwaeche',
]

# Mindestens EINES dieser Elemente muss in einer guten Falsifikation stehen
CONCRETE_MARKERS = [
    r'\$?\d+[\.,]?\d*\s*(%|\$|€|usd|eur)',  # Preis/Zahl mit Einheit
    r'\b(below|above|unter|ueber|breaks?|durchbricht)\b.*\d',  # Preis-Trigger
    r'\b(earnings|fomc|ecb|ceo|fda|guidance|report)\b',  # Konkrete Ereignisse
    r'\b(stop|exit|verkauf|sell|close)\b.*(\d|thesis|these)',  # Exit-Plan
    r'\b\d{4}-\d{2}-\d{2}\b',  # ISO-Datum
    r'\b(q[1-4]|quarter)\b',
]


def load_verdict(ticker: str) -> dict | None:
    if not VERDICTS.exists():
        return None
    data = json.loads(VERDICTS.read_text(encoding='utf-8'))
    return data.get(ticker.upper())


def check_falsification(text: str) -> tuple[bool, str]:
    """Return (is_valid, reason)."""
    if not text or not isinstance(text, str):
        return False, 'Falsifikation fehlt komplett'
    t = text.strip().lower()
    if len(t) < 30:
        return False, f'Falsifikation zu kurz ({len(t)} Zeichen, min 30)'
    # Vage Phrasen
    for phrase in VAGUE_PHRASES:
        if phrase in t:
            return False, f'Vage Phrase erkannt: "{phrase}"'
    # Konkrete Marker
    markers_found = 0
    for pattern in CONCRETE_MARKERS:
        if re.search(pattern, t, re.IGNORECASE):
            markers_found += 1
    if markers_found < 2:
        return False, f'Nicht genug konkrete Marker ({markers_found}/2 benoetigt: Preis, Datum, Event, Exit)'
    return True, f'OK ({markers_found} konkrete Marker)'


def run(ticker: str) -> dict:
    v = load_verdict(ticker)
    if not v:
        return {'status': 'blocked', 'ticker': ticker, 'reason': 'Kein Verdict vorhanden'}
    fals = v.get('falsification') or v.get('bear_scenario') or ''
    ok, reason = check_falsification(fals)
    return {
        'status': 'ok' if ok else 'blocked',
        'ticker': ticker.upper(),
        'falsification': fals[:200],
        'reason': reason,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ticker')
    args = ap.parse_args()
    r = run(args.ticker)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r['status'] == 'ok' else 2)


if __name__ == '__main__':
    main()
