#!/usr/bin/env python3
"""
detector_action_bridge.py — Phase 45az (Victor 2026-05-14).

Albert's Audit-Befund: "547 Detector-Findings, 0 ausgelöste Actions —
die Detector→Action-Bridge ist tot."

Dieses Skript schließt die Lücke:
  1. Liest kritische Detector-Findings aus ceo_inbox (severity critical/warning)
  2. Prüft ob es zu jedem Finding-Typ in den letzten 24h eine CEO-Action gab
  3. Findings OHNE Action → Eskalation:
     - 1. mal unbehandelt: in detector_escalations.jsonl loggen
     - wiederholt unbehandelt: als HIGH-Self-Action für Albert + im Digest sichtbar
  4. Schreibt ESKALATIONS-Event zurück in ceo_inbox damit CEO-Brain es sieht

Run: täglich 09:45 (vor Improvement-Digest 10:00).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
INBOX = WS / 'data' / 'ceo_inbox.jsonl'
ACTION_LOG = WS / 'data' / 'ceo_action_log.jsonl'
ESCALATIONS = WS / 'data' / 'detector_escalations.jsonl'
SELF_ACTIONS = WS / 'data' / 'albert_self_actions.jsonl'

# Welche Event-Typen sind "behandelbar" — und welche Action-Topics zählen als Behandlung
DETECTOR_TYPES = {
    'detector_finding', 'silence.stale_signal', 'macro.breaking_event',
    'pre_entry_block', 'concentration_block',
}


def _recent(path: Path, hours: int) -> list[dict]:
    if not path.exists(): return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = e.get('ts', '')
                    if ts >= cutoff:
                        out.append(e)
                except Exception: pass
    except Exception: pass
    return out


def analyze() -> dict:
    now = datetime.now(timezone.utc)

    # 1. Kritische Detector-Findings letzte 24h
    findings = _recent(INBOX, 24)
    critical = [
        f for f in findings
        if f.get('event_type') in DETECTOR_TYPES
        and f.get('severity') in ('critical', 'warning')
    ]
    # Nach Typ gruppieren
    by_type = Counter(f.get('event_type', '?') for f in critical)

    # 2. CEO-Actions letzte 24h
    actions = _recent(ACTION_LOG, 24)
    action_topics = []
    for a in actions:
        for act in a.get('actions', []):
            action_topics.append((act.get('type', '') + ' ' + act.get('topic', '')).lower())
    action_blob = ' '.join(action_topics)

    # 3. Welche Finding-Typen haben KEINE korrespondierende Action?
    unhandled = []
    for ftype, count in by_type.items():
        # Heuristik: taucht ein Stichwort aus dem Finding-Typ in irgendeiner Action auf?
        keyword = ftype.split('.')[0].split('_')[0]  # z.B. 'silence', 'macro', 'detector'
        handled = keyword in action_blob
        if not handled:
            # Sample-Finding für Kontext
            sample = next((f.get('message', '')[:160] for f in critical
                           if f.get('event_type') == ftype), '')
            unhandled.append({
                'finding_type': ftype,
                'count_24h': count,
                'sample': sample,
            })

    # 4. Eskalations-Historie laden — was wurde schon X mal eskaliert?
    past_escalations = _recent(ESCALATIONS, 24 * 7)  # 7 Tage
    escalation_count = Counter(e.get('finding_type', '?') for e in past_escalations)

    # 5. Neue Eskalationen schreiben + bei Wiederholung Self-Action
    new_escalations = []
    for u in unhandled:
        ftype = u['finding_type']
        prior = escalation_count.get(ftype, 0)
        severity = 'high' if prior >= 2 else 'med'
        esc = {
            'ts': now.isoformat(timespec='seconds'),
            'finding_type': ftype,
            'count_24h': u['count_24h'],
            'sample': u['sample'],
            'prior_escalations_7d': prior,
            'severity': severity,
        }
        new_escalations.append(esc)

        # Bei wiederholter Nichtbehandlung → HIGH-Self-Action für Albert
        if prior >= 2:
            try:
                SELF_ACTIONS.parent.mkdir(parents=True, exist_ok=True)
                with open(SELF_ACTIONS, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'ts': now.isoformat(timespec='seconds'),
                        'action': f'handle_ignored_detector:{ftype}',
                        'reason': (f'{ftype} wurde {u["count_24h"]}x in 24h gemeldet, '
                                   f'{prior}x eskaliert, NIE behandelt. Sample: {u["sample"]}'),
                        'priority': 'high',
                        'source': 'detector_action_bridge',
                    }, ensure_ascii=False) + '\n')
            except Exception: pass

    # Persist Eskalationen
    if new_escalations:
        ESCALATIONS.parent.mkdir(parents=True, exist_ok=True)
        with open(ESCALATIONS, 'a', encoding='utf-8') as f:
            for e in new_escalations:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')

        # Eskalations-Event zurück in ceo_inbox (CEO-Brain sieht es)
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from ceo_inbox import write_event
            high_esc = [e for e in new_escalations if e['severity'] == 'high']
            if high_esc:
                write_event(
                    event_type='detector.escalation',
                    message=(f'{len(high_esc)} Detector-Finding-Typen werden seit Tagen '
                             f'ignoriert: ' + ', '.join(e['finding_type'] for e in high_esc)),
                    severity='warning', category='health',
                    user_pinged=False,
                    payload={'escalations': high_esc},
                )
        except Exception: pass

    return {
        'ts': now.isoformat(timespec='seconds'),
        'critical_findings_24h': len(critical),
        'finding_types': dict(by_type),
        'unhandled_types': len(unhandled),
        'new_escalations': len(new_escalations),
        'high_severity_escalations': sum(1 for e in new_escalations if e['severity'] == 'high'),
        'details': new_escalations,
    }


def main() -> int:
    r = analyze()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
