#!/usr/bin/env python3
"""
web_research.py — Phase 45bc (Victor 2026-05-14).

Victor: "Wenn die protokollpflichtigen Daten fehlen — recherchier sie.
Genau sowas muss automatisch passieren."

Problem: _handle_deep_dive() in discord_chat.py arbeitete bisher NUR mit
DB-Daten. Fehlten Fundamentals/Analyst-Konsens (z.B. bei DAX-Werten ohne
Preis-Historie), kam "Daten nicht verfügbar" statt einer Recherche — also
genau die Abkürzung, die das Deep-Dive-Protokoll als Anti-Pattern verbietet.

Dieses Modul schließt die Lücke: research_stock() nutzt das Anthropic
web_search-Tool und holt die protokollpflichtigen Daten LIVE aus dem Netz:
  - Technik (Kurs, MA50/200, RSI, 52W-Range, Performance)
  - Fundamentals (KGV/PEG sektorgerecht, Umsatz-/EPS-Trend, Schulden-Trend)
  - Analyst-Konsens NUR letzte 30 Tage (Up-/Downgrades, Kursziel-Range)
  - Leiche im Keller + 4b regulatorisch/politisches Risiko
  - Konkurrenz-Check

Gibt einen formatierten Text-Block zurück, der in den Deep-Dive-Prompt
injiziert wird. Schlägt die Recherche fehl → klarer Hinweis statt Stille.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

ANTHROPIC_MODEL = 'claude-sonnet-4-5'
MAX_SEARCHES = 6


def _research_prompt(ticker: str, company_hint: str = '') -> str:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    name = f' ({company_hint})' if company_hint else ''
    return f"""Heute ist {today}. Recherchiere im Web die folgenden Fakten zur
Aktie {ticker}{name} — für einen Trading-Deep-Dive. Suche aktiv, rate NICHTS.
Wenn ein Punkt nicht auffindbar ist, schreibe explizit "nicht gefunden".

Liefere strukturiert:

1. TECHNIK: aktueller Kurs, MA50, MA200, RSI(14), 52W-Hoch/Tief + Abstand,
   Performance 1M/3M/6M.
2. FUNDAMENTALS: KGV (aktuelles Jahr + nächstes Jahr e), PEG falls Tech-Wert,
   Umsatz-Trend, EPS-Trend (wächst/fällt — letzte Quartale), Marge,
   Schulden-Trend (steigend/fallend, letzte Jahre), Dividende/Yield.
3. ANALYST-KONSENS — NUR letzte 30 Tage: Up-/Downgrades, Kursziel-Range
   (min/median/max), Konsens-Rating. Ältere Meldungen ignorieren.
4. LEICHE IM KELLER: laufende Klagen/Kartellverfahren, Schuldenanstieg-Grund,
   teure Übernahmen, CEO-Wechsel/Gewinnwarnung letzte 90 Tage,
   Marktanteilsverluste an Konkurrenten.
5. REGULATORISCH/POLITISCH (Pflicht): Preisregulierung, staatliche Eingriffe,
   Zoll-Exposition, politische Sichtbarkeit des Produkts.
6. KONKURRENZ: Haupt-Konkurrent, dessen Bewertung/Wachstum im Vergleich —
   gewinnt oder verliert unser Kandidat?

Antworte kompakt in Stichpunkten mit Zahlen. Jede Zahl mit Quelle/Datum.
Keine Trading-Empfehlung — nur die recherchierten Fakten."""


def research_stock(ticker: str, company_hint: str = '') -> str:
    """
    Live-Web-Recherche der Deep-Dive-pflichtigen Daten.
    Returns: formatierter Fakten-Block (str). Bei Fehler: klarer Hinweis-String.
    """
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return '[WEB-RECHERCHE FEHLGESCHLAGEN: ANTHROPIC_API_KEY fehlt]'
    try:
        import anthropic
    except Exception as e:
        return f'[WEB-RECHERCHE FEHLGESCHLAGEN: anthropic SDK — {e}]'

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=3000,
            messages=[{'role': 'user',
                       'content': _research_prompt(ticker, company_hint)}],
            tools=[{
                'type': 'web_search_20250305',
                'name': 'web_search',
                'max_uses': MAX_SEARCHES,
            }],
        )
    except Exception as e:
        return f'[WEB-RECHERCHE FEHLGESCHLAGEN: {str(e)[:200]}]'

    # Alle Text-Blöcke der Antwort einsammeln (web_search_tool_result-Blöcke
    # überspringen — die enthalten die Roh-Suchergebnisse, nicht die Synthese).
    parts = []
    n_searches = 0
    try:
        for block in resp.content:
            btype = getattr(block, 'type', None)
            if btype == 'text':
                parts.append(block.text)
            elif btype == 'server_tool_use':
                n_searches += 1
    except Exception:
        pass

    text = '\n'.join(p.strip() for p in parts if p and p.strip())
    if not text:
        return '[WEB-RECHERCHE: keine verwertbare Antwort erhalten]'

    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return (f'[WEB-RECHERCHE {ticker} — {stamp}, {n_searches} Suchen]\n'
            f'{text}')


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print('Usage: web_research.py TICKER [company_hint]')
        return 1
    ticker = sys.argv[1]
    hint = sys.argv[2] if len(sys.argv) > 2 else ''
    print(research_stock(ticker, hint))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
