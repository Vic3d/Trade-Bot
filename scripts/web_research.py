#!/usr/bin/env python3
"""
web_research.py — Phase 45bc (Victor 2026-05-14).

Victor: "Wenn die protokollpflichtigen Daten fehlen — recherchier sie.
Genau sowas muss automatisch passieren."

Problem: _handle_deep_dive() in discord_chat.py arbeitete bisher NUR mit
DB-Daten. Fehlten Fundamentals/Analyst-Konsens (z.B. bei DAX-Werten ohne
Preis-Historie), kam "Daten nicht verfügbar" statt einer Recherche — also
genau die Abkürzung, die das Deep-Dive-Protokoll als Anti-Pattern verbietet.

Dieses Modul schließt die Lücke: research_stock() ruft die Claude-CLI
(Max-Subscription, KEIN API-Key — der ist im System ungültig) mit
freigeschaltetem WebSearch-Tool und holt die protokollpflichtigen Daten
LIVE aus dem Netz:
  - Technik (Kurs, MA50/200, RSI, 52W-Range, Performance)
  - Fundamentals (KGV/PEG sektorgerecht, Umsatz-/EPS-Trend, Schulden-Trend)
  - Analyst-Konsens NUR letzte 30 Tage (Up-/Downgrades, Kursziel-Range)
  - Leiche im Keller + 4b regulatorisch/politisches Risiko
  - Konkurrenz-Check

Gibt einen formatierten Text-Block zurück, der in den Deep-Dive-Prompt
injiziert wird. Schlägt die Recherche fehl → klarer Hinweis statt Stille.
"""
from __future__ import annotations
import json, os, subprocess
from datetime import datetime, timezone

CLI_TIMEOUT = 420  # Web-Recherche mit mehreren Suchen dauert — Deep Dive ist gründlich, nicht schnell


def _research_prompt(ticker: str, company_hint: str = '') -> str:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    name = f' ({company_hint})' if company_hint else ''
    return f"""Heute ist {today}. Recherchiere mit dem WebSearch-Tool die
folgenden Fakten zur Aktie {ticker}{name} — für einen Trading-Deep-Dive.
Suche aktiv mehrfach. Rate NICHTS. Wenn ein Punkt nicht auffindbar ist,
schreibe explizit "nicht gefunden".

Liefere strukturiert in Stichpunkten, jede Zahl mit Quelle/Datum:

1. TECHNIK: aktueller Kurs, MA50, MA200, RSI(14), 52W-Hoch/Tief + Abstand,
   Performance 1M/3M/6M.
2. FUNDAMENTALS: KGV (aktuelles + nächstes Jahr e), PEG falls Tech-Wert,
   Umsatz-Trend, EPS-Trend (wächst/fällt — letzte Quartale), Marge,
   Schulden-Trend (steigend/fallend, letzte Jahre), Dividende/Yield.
3. ANALYST-KONSENS — NUR letzte 30 Tage: Up-/Downgrades, Kursziel-Range
   (min/median/max), Konsens-Rating. Ältere Meldungen ignorieren.
4. LEICHE IM KELLER: laufende Klagen/Kartellverfahren, Grund für
   Schuldenanstieg, teure Übernahmen, CEO-Wechsel/Gewinnwarnung letzte
   90 Tage, Marktanteilsverluste an Konkurrenten.
5. REGULATORISCH/POLITISCH (Pflicht): Preisregulierung, staatliche
   Eingriffe, Zoll-Exposition, politische Sichtbarkeit des Produkts.
6. KONKURRENZ: Haupt-Konkurrent, dessen Bewertung/Wachstum im Vergleich —
   gewinnt oder verliert unser Kandidat?

Arbeite effizient: ziele auf ~6-8 gezielte Suchen, nicht mehr.
Keine Trading-Empfehlung — nur die recherchierten Fakten, kompakt."""


def research_stock(ticker: str, company_hint: str = '') -> str:
    """
    Live-Web-Recherche der Deep-Dive-pflichtigen Daten via Claude-CLI
    (Max-Subscription) mit WebSearch-Tool.
    Returns: formatierter Fakten-Block (str). Bei Fehler: klarer Hinweis-String.
    """
    cmd = [
        'claude', '-p',
        '--model', 'sonnet',
        '--output-format', 'json',
        '--allowedTools', 'WebSearch',
        '--disable-slash-commands',
        '--setting-sources', 'user',
        '--no-session-persistence',
    ]
    # ANTHROPIC_API_KEY raus → CLI nutzt Subscription-Billing (API-Key ungültig)
    cli_env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
    cli_env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'

    try:
        result = subprocess.run(
            cmd,
            input=_research_prompt(ticker, company_hint),
            capture_output=True, text=True,
            timeout=CLI_TIMEOUT, check=False, env=cli_env,
        )
    except subprocess.TimeoutExpired:
        return f'[WEB-RECHERCHE {ticker} FEHLGESCHLAGEN: CLI-Timeout {CLI_TIMEOUT}s]'
    except Exception as e:
        return f'[WEB-RECHERCHE {ticker} FEHLGESCHLAGEN: {str(e)[:200]}]'

    if result.returncode != 0:
        err = (result.stderr or result.stdout or '').strip()[:200]
        return f'[WEB-RECHERCHE {ticker} FEHLGESCHLAGEN: CLI exit {result.returncode} — {err}]'

    raw = (result.stdout or '').strip()
    text = ''
    try:
        data = json.loads(raw)
        text = (data.get('result') or data.get('content') or '').strip()
    except (json.JSONDecodeError, ValueError, AttributeError):
        text = raw

    if not text:
        return f'[WEB-RECHERCHE {ticker}: keine verwertbare Antwort erhalten]'

    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return f'[WEB-RECHERCHE {ticker} — {stamp}]\n{text}'


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
