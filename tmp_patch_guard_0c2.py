#!/usr/bin/env python3
"""
tmp_patch_guard_0c2.py — Patcht Guard 0c2 in paper_trade_engine.py
===================================================================

Fügt eine Source-Validierung in Guard 0c2 ein:
Nur Verdicts von 'autonomous_ceo' oder 'discord_deepdive' werden akzeptiert.

Verwendung (auf dem Server ausführen):
  python3 /opt/trademind/tmp_patch_guard_0c2.py

Das Skript:
  1. Liest /opt/trademind/scripts/execution/paper_trade_engine.py
  2. Findet den exakten String nach _verdict_data.get(...)
  3. Ersetzt ihn durch die erweiterte Version mit Source-Check
  4. Verifiziert mit py_compile
  5. Gibt OK oder Fehler aus
"""

import py_compile
import shutil
import sys
from pathlib import Path

TARGET = Path('/opt/trademind/scripts/execution/paper_trade_engine.py')

# ─── Exakter Such-String (wie im Original) ────────────────────────────────────
OLD = (
    "            _ticker_verdict = _verdict_data.get(ticker.upper(), {})\n"
    "            _verdict = _ticker_verdict.get('verdict', '')"
)

# ─── Ersatz-String: gleicher Code + Source-Validierungs-Block ─────────────────
NEW = (
    "            _ticker_verdict = _verdict_data.get(ticker.upper(), {})\n"
    "            _verdict = _ticker_verdict.get('verdict', '')\n"
    "\n"
    "            # Source-Validierung: nur echte Deep Dives akzeptieren\n"
    "            _verdict_source = _ticker_verdict.get('source', '')\n"
    "            _trusted_sources = {'autonomous_ceo', 'discord_deepdive'}\n"
    "            if _verdict_source and _verdict_source not in _trusted_sources:\n"
    "                return {\n"
    "                    'success': False,\n"
    "                    'trade_id': None,\n"
    "                    'message': (\n"
    "                        f'❌ Deep Dive Guard: Verdict für {ticker} hat unvertrauenswürdige Quelle '\n"
    "                        f'\"{_verdict_source}\". Nur autonomous_ceo oder discord_deepdive erlaubt. '\n"
    "                        f'In Discord: \"Deep Dive {ticker}\" für echten Deep Dive.'\n"
    "                    ),\n"
    "                    'blocked_by': 'untrusted_verdict_source',\n"
    "                }"
)


def main() -> int:
    # ── Datei lesen ────────────────────────────────────────────────────────────
    if not TARGET.exists():
        print(f'FEHLER: Datei nicht gefunden: {TARGET}')
        return 1

    original = TARGET.read_text(encoding='utf-8')

    # ── Idempotenz-Check: bereits gepatcht? ───────────────────────────────────
    if 'untrusted_verdict_source' in original:
        print('INFO: Patch bereits angewendet (untrusted_verdict_source gefunden). Nichts zu tun.')
        return 0

    # ── Such-String vorhanden? ────────────────────────────────────────────────
    if OLD not in original:
        print('FEHLER: Exakter Such-String nicht gefunden. Datei möglicherweise verändert.')
        print()
        print('Gesucht:')
        print(repr(OLD))
        print()
        print('Tipp: grep -n "_ticker_verdict" /opt/trademind/scripts/execution/paper_trade_engine.py')
        return 1

    # ── Backup erstellen ──────────────────────────────────────────────────────
    backup = TARGET.with_suffix('.py.bak_guard0c2')
    shutil.copy2(TARGET, backup)
    print(f'Backup: {backup}')

    # ── Patch anwenden ────────────────────────────────────────────────────────
    patched = original.replace(OLD, NEW, 1)

    if patched == original:
        print('FEHLER: String-Ersatz hatte keinen Effekt (replace() gab gleiches zurück).')
        return 1

    TARGET.write_text(patched, encoding='utf-8')
    print(f'Patch angewendet: {TARGET}')

    # ── Syntax-Check ─────────────────────────────────────────────────────────
    try:
        py_compile.compile(str(TARGET), doraise=True)
        print('Syntax OK (py_compile bestanden)')
    except py_compile.PyCompileError as exc:
        print(f'SYNTAX-FEHLER nach Patch: {exc}')
        print('Stelle Backup wieder her...')
        shutil.copy2(backup, TARGET)
        print('Backup wiederhergestellt. Patch rückgängig gemacht.')
        return 1

    print()
    print('OK — Guard 0c2 Source-Validierung erfolgreich eingefügt.')
    print('Nächste Schritte:')
    print('  systemctl restart trademind-scheduler')
    print('  tail -f /opt/trademind/data/scheduler.log')
    return 0


if __name__ == '__main__':
    sys.exit(main())
