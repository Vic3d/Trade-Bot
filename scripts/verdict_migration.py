#!/usr/bin/env python3
"""
Verdict Migration — Phase 5.4
==============================
Einmal-Migration der deep_dive_verdicts.json:

1. Legacy-Verdicts OHNE source-Feld bekommen source='deep_dive' gesetzt
   wenn sie echte Deep-Dive-Signatur haben (analyst=Albert, key_findings,
   oder entry+stop+ziel_1).
2. Verdicts die von auto_deepdive_rule wrongful überschrieben wurden
   (KAUFEN → NICHT_KAUFEN aus Rule-Engine) werden aus auto_deepdive_flips.json
   wiederhergestellt, falls das alte KAUFEN ein echter Deep Dive war.

Idempotent — kann mehrfach laufen.

Usage:
  python3 scripts/verdict_migration.py              # normal
  python3 scripts/verdict_migration.py --dry-run    # nur zeigen
  python3 scripts/verdict_migration.py --restore    # auch wrongful overwrites zurückholen
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
VERDICTS_FILE = DATA / 'deep_dive_verdicts.json'
FLIP_LOG = DATA / 'auto_deepdive_flips.json'


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _save(p: Path, data):
    # Backup
    if p.exists():
        backup = p.with_suffix(p.suffix + f'.bak.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        backup.write_text(p.read_text(encoding='utf-8'), encoding='utf-8')
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def _is_real_deep_dive(v: dict) -> bool:
    """Gleiche Heuristik wie in auto_deepdive._is_real_deep_dive."""
    src = str(v.get('source', '')).lower()
    if src in ('discord_deepdive', 'albert_discord', 'deep_dive', 'albert'):
        return True
    analyst = str(v.get('analyst', ''))
    if analyst and analyst.lower().startswith('albert'):
        return True
    if isinstance(v.get('key_findings'), dict) and v['key_findings']:
        return True
    if v.get('entry') and v.get('stop') and v.get('ziel_1'):
        return True
    return False


def migrate_sources(verdicts: dict, dry_run: bool = False) -> list[str]:
    """Setzt source='deep_dive' auf Legacy-Verdicts (echte Albert-DDs)."""
    changes = []
    for ticker, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        if v.get('source'):
            continue  # bereits gesetzt
        if _is_real_deep_dive(v):
            v['source'] = 'deep_dive'
            v['migrated_at'] = datetime.now(_BERLIN).isoformat(timespec='seconds')
            changes.append(f'{ticker}: set source=deep_dive (analyst={v.get("analyst","?")})')
    return changes


def restore_wrongful_overwrites(verdicts: dict, dry_run: bool = False) -> list[str]:
    """
    Prüft auto_deepdive_flips.json: wenn ein KAUFEN-Verdict zu NICHT_KAUFEN
    geflipped wurde obwohl der aktuelle Verdict nicht offensichtlich von
    Albert stammt, könnte es ein wrongful overwrite sein.

    Strategie: finde für jeden Ticker den frühesten KAUFEN-Flip und schaue
    ob das alte KAUFEN in historischen Verdicts gespeichert war.
    Da wir die echten alten Verdicts nicht mehr haben (keine Historie vor
    Phase 3), können wir nur markieren und Albert bitten neu zu analysieren.
    """
    flips = _load(FLIP_LOG, [])
    if not isinstance(flips, list):
        return []

    # Heutige Flips von KAUFEN → NICHT_KAUFEN mit rule-Gründen
    today = datetime.now(_BERLIN).date()
    suspicious = []
    today_iso_prefix = today.isoformat()
    for f in flips:
        if not isinstance(f, dict):
            continue
        if not f.get('timestamp', '').startswith(today_iso_prefix):
            continue
        if f.get('old_verdict') == 'KAUFEN' and f.get('new_verdict') in ('NICHT_KAUFEN', 'WARTEN'):
            reasons = f.get('reasons', [])
            # Rule-Engine-Pattern erkennen
            if any('insider=' in r or 'macro=' in r or '52w_dd=' in r for r in reasons):
                suspicious.append(f['ticker'])

    changes = []
    for ticker in set(suspicious):
        v = verdicts.get(ticker)
        if not v or not isinstance(v, dict):
            continue
        # Nur wenn aktueller Verdict source='auto_deepdive_rule' ist
        if v.get('source') != 'auto_deepdive_rule':
            continue
        # Markiere als "questioned" — auto_deepdive-override wird nicht
        # blind rückgängig gemacht (wir wissen nicht was Albert ursprünglich
        # wirklich analysiert hat). Aber wir markieren zur manuellen Review.
        v['flag_possible_wrongful_override'] = True
        v['flag_reason'] = (
            f'KAUFEN→NICHT_KAUFEN durch Rule-Engine heute. '
            f'Falls Albert ursprünglich manuell KAUFEN vergeben hatte, '
            f'bitte Deep Dive via Discord neu anstoßen: "Deep Dive {ticker}"'
        )
        changes.append(f'{ticker}: FLAGGED possible wrongful overwrite')
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--restore', action='store_true',
                    help='Also flag wrongful overwrites from flip-log')
    args = ap.parse_args()

    verdicts = _load(VERDICTS_FILE, {})
    if not isinstance(verdicts, dict):
        print('verdicts is not a dict, aborting')
        sys.exit(1)

    source_changes = migrate_sources(verdicts, dry_run=args.dry_run)
    flag_changes = []
    if args.restore:
        flag_changes = restore_wrongful_overwrites(verdicts, dry_run=args.dry_run)

    print('=== Verdict Migration ===')
    print(f'Source-Patches: {len(source_changes)}')
    for c in source_changes:
        print(f'  {c}')
    if args.restore:
        print(f'Flagged overwrites: {len(flag_changes)}')
        for c in flag_changes:
            print(f'  {c}')

    if not args.dry_run and (source_changes or flag_changes):
        _save(VERDICTS_FILE, verdicts)
        print('→ verdicts.json geschrieben (Backup angelegt)')
    elif args.dry_run:
        print('[DRY-RUN — keine Änderungen geschrieben]')


if __name__ == '__main__':
    main()
