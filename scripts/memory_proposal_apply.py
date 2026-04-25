#!/usr/bin/env python3
"""
memory_proposal_apply.py — Wendet Victor's "Speichern N,M"-Befehle an.

Lese-Quelle: data/memory_proposals.json (von daily_memory_proposal.py erzeugt).
Schreibt vorgeschlagene Markdown-Blöcke in die jeweiligen Ziel-Dateien
(prepended mit Datums-Header).

Befehle:
    "Speichern 1,3"     → nur Vorschläge 1 und 3
    "Speichern alle"    → alle pending Vorschläge
    "Verwerfen"         → alle pending Vorschläge verwerfen
    "Verwerfen 2"       → nur Vorschlag 2 verwerfen, Rest bleibt pending
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
PROPOSALS_FILE = WS / 'data' / 'memory_proposals.json'


def _load() -> dict:
    if not PROPOSALS_FILE.exists():
        return {'proposals': [], 'status': 'none'}
    try:
        return json.loads(PROPOSALS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'proposals': [], 'status': 'corrupt'}


def _save(data: dict) -> None:
    PROPOSALS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _parse_indices(cmd: str, total: int) -> list[int] | str:
    """Parst '1,3' oder 'alle' → 0-basierte Liste. 'alle' → alle Indices."""
    cmd = cmd.lower().strip()
    if 'alle' in cmd:
        return list(range(total))
    nums = re.findall(r'\d+', cmd)
    if not nums:
        return 'no_indices'
    indices = []
    for n in nums:
        i = int(n) - 1
        if 0 <= i < total:
            indices.append(i)
    return indices if indices else 'no_valid'


def _append_to_md(target_rel: str, title: str, content: str) -> bool:
    """Hängt Markdown-Eintrag mit Datums-Header an die Ziel-Datei."""
    path = WS / target_rel
    path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    block = f'\n## {today} — {title}\n\n{content.strip()}\n'
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(block)
        return True
    except Exception as e:
        print(f'[memory-apply] write error {path}: {e}')
        return False


def apply_command(victor_message: str) -> str:
    """Returns Discord-tauglicher Antwort-String."""
    data = _load()
    proposals = data.get('proposals') or []
    status = data.get('status', 'none')

    if not proposals:
        return ('📭 Keine offenen Memory-Vorschläge. Der nächste Vorschlag '
                'kommt heute Abend automatisch (21:30 CEST).')

    if status != 'pending':
        return f'⚠️ Vorschläge haben Status `{status}` — nichts zu tun.'

    cmd = victor_message.lower().strip()

    # Verwerfen
    if cmd.startswith('verwerfen'):
        idx = _parse_indices(cmd, len(proposals))
        if isinstance(idx, str) or not idx:
            # "Verwerfen" ohne Zahl → alle
            data['status'] = 'discarded'
            data['discarded_at'] = datetime.now().isoformat(timespec='seconds')
            _save(data)
            return f'🗑️ Alle {len(proposals)} Vorschläge verworfen.'
        # Selektiv verwerfen
        keep = [p for i, p in enumerate(proposals) if i not in idx]
        data['proposals'] = keep
        if not keep:
            data['status'] = 'discarded'
        _save(data)
        return f'🗑️ {len(idx)} Vorschlag/Vorschläge verworfen, {len(keep)} bleiben pending.'

    # Speichern
    if cmd.startswith('speichern'):
        idx = _parse_indices(cmd, len(proposals))
        if isinstance(idx, str):
            return ('❓ Verstehe nicht. Beispiel: `Speichern 1,3` oder '
                    '`Speichern alle` oder `Verwerfen`.')
        if not idx:
            return '❓ Keine gültigen Indices. Bereich: 1..' + str(len(proposals))

        applied = []
        for i in idx:
            p = proposals[i]
            ok = _append_to_md(p['target'], p['title'], p['content'])
            if ok:
                applied.append((i + 1, p['target']))

        # Status updaten — angewendete als 'applied' markieren
        for i in idx:
            proposals[i]['_applied_at'] = datetime.now().isoformat(timespec='seconds')

        # Wenn alle verarbeitet → status='applied', sonst pending lassen
        unapplied = [p for p in proposals if '_applied_at' not in p]
        data['proposals'] = unapplied  # nur noch nicht-bearbeitete bleiben
        if not unapplied:
            data['status'] = 'applied'
            data['applied_at'] = datetime.now().isoformat(timespec='seconds')
        _save(data)

        if not applied:
            return '⚠️ Keine Vorschläge konnten geschrieben werden (siehe Logs).'

        lines = [f'✅ {len(applied)} Vorschlag/Vorschläge gespeichert:']
        for n, tgt in applied:
            lines.append(f'  · [{n}] → `{tgt}`')
        if unapplied:
            lines.append(f'\n_{len(unapplied)} weitere Vorschläge bleiben pending._')
        return '\n'.join(lines)

    return ('❓ Unbekannter Befehl. Erlaubt: `Speichern 1,3` / '
            '`Speichern alle` / `Verwerfen [N]`.')


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: python3 memory_proposal_apply.py "Speichern alle"')
        sys.exit(1)
    print(apply_command(' '.join(sys.argv[1:])))
