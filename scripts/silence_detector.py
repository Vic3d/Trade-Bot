#!/usr/bin/env python3
"""
silence_detector.py — Phase 45aa (Victor 2026-05-07).

User-Direktive: 'Stumme Bugs fallen ohne Detection nicht auf.'

Loesung: Meta-Detector der die ABWESENHEIT von erwartetem Signal als
Alarm wertet. Pro Datei/Job pruefen wir 'wann zuletzt Update?' — wenn
mehr als max_silence_h ohne Update: Alert.

Damit werden auch stumme Klassen sichtbar (A6 API-Outage, A8 Stale Cache,
G5 Cron-Tot, H2 Auto-Memory drift, J3 Truth-Social etc.).

Run: alle 30min via scheduler.
Output: data/silence_log.jsonl + Discord-HIGH bei Alarm.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
LOG = WS / 'data' / 'silence_log.jsonl'

# Erwartete Signal-Quellen + max Stille-Dauer in Stunden
WATCHLIST = [
    # Daten-Pipeline (sollte regelmaessig laufen)
    ('data/scheduler.log',                       0.5,  'scheduler stumm'),
    ('data/news_reactor_log.jsonl',              4.0,  'news_reactor keine Events'),
    ('data/ceo_active_loop.jsonl',               0.5,  'CEO-Loop steht'),
    ('data/halluzination_log.jsonl',             48.0, 'Hallu-Detector hat 48h nichts gefunden — verdaechtig sauber'),
    ('data/cli_audit_violations.jsonl',          168.0, 'CLI-Audit hat 7d nichts gefunden'),
    # Daten-Updates
    ('data/commodity_prices.json',               2.0,  'Commodity-Cache stale'),
    ('data/quant_metrics.json',                  30.0, 'Quant-Metrics nicht regeneriert (sollte taeglich 23:50)'),
    ('data/strategy_throttle_log.jsonl',         168.0, 'Throttle hat 7d nicht ausgeloest — wahrscheinlich okay'),
    # Audits
    ('data/price_consistency_log.jsonl',         48.0, 'Price-Consistency-Audit hat 48h nichts geloggt'),
    ('data/anomalous_moves_log.jsonl',           48.0, 'News-Free-Move 48h ohne Funde'),
    # Briefings (sollten im Log auftauchen wenn sie laufen)
    ('memory/state-snapshot.md',                 30.0, 'state-snapshot nicht regeneriert'),
]

# Severity nach Ueberschreitung
def _severity(actual_h: float, max_h: float) -> str:
    ratio = actual_h / max_h if max_h > 0 else 999
    if ratio > 3.0: return 'critical'
    if ratio > 1.5: return 'warning'
    return 'info'


def check() -> list[dict]:
    findings = []
    now = datetime.now(timezone.utc)
    for rel_path, max_h, desc in WATCHLIST:
        p = WS / rel_path
        if not p.exists():
            findings.append({
                'kind': 'missing_file', 'path': rel_path,
                'description': desc, 'severity': 'warning',
            })
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            age_h = (now - mtime).total_seconds() / 3600
            if age_h > max_h:
                findings.append({
                    'kind': 'stale_signal', 'path': rel_path,
                    'description': desc,
                    'age_hours': round(age_h, 1),
                    'max_allowed_hours': max_h,
                    'last_update': mtime.isoformat(timespec='seconds'),
                    'severity': _severity(age_h, max_h),
                })
        except Exception as e:
            findings.append({
                'kind': 'check_error', 'path': rel_path,
                'error': str(e), 'severity': 'info',
            })
    return findings


def main() -> int:
    findings = check()
    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'n_findings': len(findings),
        'critical': sum(1 for f in findings if f.get('severity') == 'critical'),
        'warning': sum(1 for f in findings if f.get('severity') == 'warning'),
        'findings': findings,
    }
    if findings:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(out, default=str) + '\n')
        # Alert nur bei critical/warning
        bad = [f for f in findings if f.get('severity') in ('critical', 'warning')]
        if bad:
            try:
                sys.path.insert(0, str(WS / 'scripts'))
                from discord_dispatcher import send_alert, TIER_HIGH
                msg = (f"🔇 **Silence-Detector** ({len(bad)} stumme Quellen):\n"
                       + '\n'.join(
                           f"  - {f['path']}: {f.get('age_hours','?')}h still "
                           f"(max {f.get('max_allowed_hours','?')}h) — {f['description']}"
                           for f in bad[:5]))
                send_alert(msg[:1900], tier=TIER_HIGH, category='system_error',
                            dedupe_key=f'silence_{datetime.now().strftime("%Y%m%d_%H")}')
            except Exception: pass
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
