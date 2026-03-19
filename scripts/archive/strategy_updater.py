#!/usr/bin/env python3
"""
Strategy Updater — Thesis-Log für strategien.md pflegen
========================================================
Wird von AI-Cron-Jobs (Morgen-Briefing, Abend-Report) aufgerufen.
Aktualisiert den Thesis-Log und Status einer Strategie.

Verwendung:
  from strategy_updater import update_strategy

  update_strategy(
      strategy_num=1,
      event_date="15.03.",
      event_text="Israel expandiert Strikes Westiran, Iran-FM: keine Verhandlungen",
      impact="Eskalation fortgesetzt, keine De-Eskalation",
      new_status="🟢🔥"
  )

Autor: Albert 🎩 | v1.0 | 15.03.2026
"""

import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

WORKSPACE = Path('/data/.openclaw/workspace')
STRATEGIEN_PATH = WORKSPACE / 'memory' / 'strategien.md'


def _load() -> str:
    return STRATEGIEN_PATH.read_text(encoding='utf-8')


def _save(content: str):
    STRATEGIEN_PATH.write_text(content, encoding='utf-8')


def _now_berlin_date() -> str:
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    return now.strftime('%d.%m.%Y, %H:%M Uhr')


def update_strategy(strategy_num: int, event_date: str, event_text: str,
                    impact: str, new_status: str):
    """
    Aktualisiert eine Strategie in strategien.md.

    Parameters:
        strategy_num  int    Strategie-Nummer (1-7)
        event_date    str    Datum des Events, z.B. "15.03."
        event_text    str    Beschreibung des Events
        impact        str    Auswirkung auf die Thesis
        new_status    str    Neuer Status, z.B. "🟢🔥", "🟡", "🔴"
    """
    content = _load()

    # ─── Strategie-Sektion finden ─────────────────────────────────
    # Sucht "## STRATEGIE {num}:" — erste Occurrence (S6/S7 kommen doppelt vor)
    pattern = rf'(## STRATEGIE {strategy_num}[:\s].*?)(?=## STRATEGIE \d|## Neue Strategien|\Z)'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        # Fallback: "## STRATEGIE S{num}"
        pattern2 = rf'(## STRATEGIE S{strategy_num}[:\s].*?)(?=## STRATEGIE \d|## Neue Strategien|\Z)'
        match = re.search(pattern2, content, re.DOTALL)
    if not match:
        print(f"[strategy_updater] FEHLER: Strategie {strategy_num} nicht gefunden!")
        return False

    section_start = match.start()
    section_end = match.end()
    section = match.group(1)

    # ─── Status-Zeile aktualisieren ───────────────────────────────
    # Format: **Status: 🟢 STARK** *(Stand: ...)*
    # oder:   **Status: 🟡 NEUTRAL** *(Stand: ...)*
    status_pattern = r'\*\*Status:[^*]+\*\*[^\n]*'
    status_match = re.search(status_pattern, section)

    if status_match:
        old_status_line = status_match.group(0)
        # Status-Label bestimmen
        label = _status_label(new_status)
        now_str = _now_berlin_date()
        new_status_line = f'**Status: {new_status} {label}** *(Stand: {now_str})*'
        section = section[:status_match.start()] + new_status_line + section[status_match.end():]
    else:
        print(f"[strategy_updater] WARNUNG: Keine Status-Zeile in Strategie {strategy_num} gefunden")

    # ─── Thesis-Log Tabelle: neue Zeile anhängen ─────────────────
    # Findet die Thesis-Log Tabelle und appended am Ende
    thesis_pattern = r'(\*\*Thesis-Log:\*\*.*?\n\|.*?\n\|[-|]+\n)((?:\|.*\n)*)'
    thesis_match = re.search(thesis_pattern, section, re.DOTALL)

    if thesis_match:
        table_header = thesis_match.group(1)
        existing_rows = thesis_match.group(2)
        new_row = f'| {event_date} | {event_text} | {impact} | {new_status} |\n'
        new_rows = existing_rows + new_row
        section = (section[:thesis_match.start()] +
                   table_header + new_rows +
                   section[thesis_match.end():])
    else:
        # Kein Thesis-Log gefunden — ans Ende der Sektion anhängen
        new_table = (f'\n**Thesis-Log:**\n'
                     f'| Datum | Event | Wirkung | Status |\n'
                     f'|-------|-------|---------|--------|\n'
                     f'| {event_date} | {event_text} | {impact} | {new_status} |\n')
        section = section.rstrip() + new_table + '\n'

    # ─── Section in Gesamtdatei zurückschreiben ───────────────────
    new_content = content[:section_start] + section + content[section_end:]
    _save(new_content)

    print(f"[strategy_updater] S{strategy_num}: Status → {new_status} | Event: {event_date} eingetragen ✅")
    return True


def _status_label(status_emoji: str) -> str:
    """Gibt das passende Wort-Label für einen Status-Emoji zurück."""
    if '🔴' in status_emoji:
        return 'GESCHWÄCHT'
    if '🟡' in status_emoji:
        return 'NEUTRAL'
    if '🟢' in status_emoji and '🔥' in status_emoji:
        return 'STARK 🔥'
    if '🟢' in status_emoji:
        return 'STARK'
    return ''


def get_all_statuses() -> dict:
    """
    Liest alle Strategie-Status aus strategien.md.
    Returns: {1: '🟢🔥', 2: '🟢', 3: '🟡', 4: '🟢', 5: '🟡', 6: '🟢', 7: '🟡'}
    """
    content = _load()
    result = {}

    for num in range(1, 8):
        pattern = rf'## STRATEGIE [S]?{num}[:\s].*?\*\*Status:\s*([^\*]+)\*\*'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            status_raw = match.group(1).strip()
            # Nur Emoji-Teil extrahieren (vor dem Wort-Label)
            emoji_part = re.match(r'([🟢🟡🔴🔥⬆️🚨]+)', status_raw)
            if emoji_part:
                result[num] = emoji_part.group(1)
            else:
                result[num] = status_raw.split()[0] if status_raw else '🟡'

    return result


# ─── Batch-Updates ──────────────────────────────────────────────────

def apply_march_15_updates():
    """
    Trägt die Updates vom 15.03.2026 nach.
    Einmalig ausführen — idempotent prüft auf doppelte Zeilen.
    """
    content = _load()

    # S1 schon aktualisiert? Check auf "15.03." in S1-Sektion
    s1_match = re.search(r'## STRATEGIE 1.*?(?=## STRATEGIE 2)', content, re.DOTALL)
    s1_updated = s1_match and '15.03.' in s1_match.group(0)

    if not s1_updated:
        print("[strategy_updater] Applying S1 update 15.03....")
        update_strategy(
            strategy_num=1,
            event_date='15.03.',
            event_text=(
                'Israel expandiert Strikes auf Westiran, Iran-FM: keine Verhandlungen, '
                'Trump droht Kharg Island Zerstörung, IEA Notreserven aktiviert'
            ),
            impact=(
                'Eskalation fortgesetzt — kein De-Eskalations-Signal. '
                'Kharg-Island-Drohung = nukleares Preisniveau-Risiko für Öl'
            ),
            new_status='🟢🔥'
        )
    else:
        print("[strategy_updater] S1 15.03. bereits eingetragen, überspringe.")

    # S4 schon aktualisiert?
    s4_match = re.search(r'## STRATEGIE 4.*?(?=## STRATEGIE 5|## STRATEGIE S5)', content, re.DOTALL)
    s4_updated = s4_match and '15.03.' in s4_match.group(0)

    if not s4_updated:
        print("[strategy_updater] Applying S4 update 15.03....")
        update_strategy(
            strategy_num=4,
            event_date='15.03.',
            event_text=(
                'Gold/Silber scharf hoch auf Safe-Haven-Nachfrage + schwachem USD. '
                'First Majestic Silver (AG) $22,56 — in Entry-B-Zone (<$24,30)'
            ),
            impact=(
                'Safe-Haven-Thesis bestätigt. USD schwach = Silber stark. '
                'AG Entry-B-Signal AKTIV — auf Umkehrkerze warten'
            ),
            new_status='🟢'
        )
    else:
        print("[strategy_updater] S4 15.03. bereits eingetragen, überspringe.")


# ─── CLI / Test ─────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=== Strategy Updater — Selbsttest ===\n")

    # 15.03. Updates anwenden
    apply_march_15_updates()

    print("\n--- Alle aktuellen Strategie-Status ---")
    statuses = get_all_statuses()
    labels = {1: 'Iran/Öl', 2: 'Rüstung', 3: 'KI-Halbleiter', 4: 'Silber/Gold',
              5: 'Rohstoffe', 6: 'Solar/Energie', 7: 'Biotech'}
    for num, status in statuses.items():
        print(f"  S{num} ({labels.get(num, '?')}): {status}")

    print("\nSelbsttest abgeschlossen. ✅")
