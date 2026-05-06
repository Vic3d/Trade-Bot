#!/usr/bin/env python3
"""
narrative_generator.py — Phase 45s: Zentraler Narrativ-Generator fuer Briefings.

User-Direktive Victor 2026-05-06: 'Ich moechte diesen Narrativblock bei
JEDEM Briefing haben.'

Mechanik:
  build_narrative(facts: list[str], briefing_type: str) -> str
    - facts: strukturierte Fakten-Zeilen (DB-Queries vorgekocht)
    - briefing_type: 'morning'|'us_open'|'evening'|'friday'|'week_ahead'
  -> 4-6 Saetze Fliesstext via call_llm(haiku)

Jeder Briefing-Type hat eigene Prompt-Anweisungen damit der Narrativ
Kontext-passend ist (z.B. Morgen=Tagesplan, Abend=Learnings).

Bei LLM-Fehler: Fakten-Backup wird formatiert zurueckgegeben, damit
Briefings nie ohne Inhalt rausgehen.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))


PROMPTS = {
    'morning': (
        "Schreibe Victor einen kurzen Tages-Eroeffnungstext (4-6 Saetze, "
        "KEIN Bullet-List). Erwaehne:\n"
        "1. Wie war die Nacht (relevante News, Asia-Lead, Markt-Snapshot)\n"
        "2. Wie steht das Portfolio gerade (offene Positionen MTM)\n"
        "3. Was ist der Plan fuer heute (Catalysts, Watchlist-Themen)\n"
    ),
    'us_open': (
        "Schreibe Victor einen kurzen US-Open-Bruefungstext (4-6 Saetze, "
        "KEIN Bullet-List). Erwaehne:\n"
        "1. Wie reagiert der Markt auf den Open (Index, VIX, FX)\n"
        "2. Was bedeutet das fuer offene US-Positionen\n"
        "3. Was ist der Plan fuer den US-Handelstag\n"
    ),
    'evening': (
        "Schreibe Victor einen kurzen Tagesabschluss-Text (4-6 Saetze, "
        "KEIN Bullet-List). Sei ehrlich auch bei Fehlern:\n"
        "1. Wie lief der Tag konkret (Trades, PnL, was passierte)\n"
        "2. Was haben wir HEUTE gelernt (Pattern, Bugs, Insights)\n"
        "3. Wenn relevant: was sollte korrigiert werden\n"
    ),
    'friday': (
        "Schreibe Victor einen kurzen Wochenabschluss-Text (5-7 Saetze, "
        "KEIN Bullet-List). Erwaehne:\n"
        "1. Wie lief die Woche (Performance, Highlights, Tiefpunkte)\n"
        "2. Welche Pattern + Bugs sind aufgefallen\n"
        "3. Welche konkreten Aufraum-Aktionen empfehlen wir nach dem Wochenende\n"
    ),
    'week_ahead': (
        "Schreibe Victor einen kurzen Wochenausblick (5-7 Saetze, "
        "KEIN Bullet-List). Erwaehne:\n"
        "1. Was kommt kommende Woche (Catalysts, Earnings, Fed)\n"
        "2. Wie positionieren wir uns konkret\n"
        "3. Welche Watchlist-Schwerpunkte\n"
    ),
}


def build_narrative(facts: list[str], briefing_type: str = 'morning',
                    persona: str = 'albert') -> str:
    """Zentraler Narrativ-Generator. Returns formatted plain text."""
    if not facts:
        return "(keine Fakten verfuegbar)"

    facts_block = '\n'.join(facts)
    base_intro = (
        "Du bist Albert, der CEO eines autonomen Trading-Bots. "
        "Du sprichst direkt mit Victor in Du-Form. Keine Floskeln, "
        "kein Pathos. Nimm NUR die Fakten unten — erfinde NICHTS dazu. "
        "Wenn nichts passiert ist, sag das auch so.\n\n"
    )
    instr = PROMPTS.get(briefing_type, PROMPTS['morning'])
    prompt = f"{base_intro}{instr}\nFAKTEN:\n{facts_block}\n"

    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from core.llm_client import call_llm  # type: ignore
        text, _ = call_llm(
            prompt, model_hint='haiku', max_tokens=700,
            audit_context=f'narrative_{briefing_type}',
        )
        return (text or '').strip() or _fallback(facts_block)
    except Exception as e:
        return _fallback(facts_block, error=str(e))


def _fallback(facts_block: str, error: str = '') -> str:
    suffix = f" [LLM-Fehler: {error[:80]}]" if error else ""
    return f"(LLM unavailable, Fakten-Backup{suffix}):\n{facts_block}"
