# Trading Lessons — Gelernte Fehler

*Angelegt: 09.03.2026 | Wird nach jedem Fehler ergänzt*

---

## LEKTION 1: Mentale Stops existieren nicht
**Datum:** 09.03.2026
**Was passierte:** DR0.DE lief von +10% Gewinn (84€) zurück auf -1,2% Verlust (75,40€). Kein einziger Stop war real in Trade Republic gesetzt. Alle Stops waren "mental" — außer EQNR bei 25,80€.
**Verlust durch Fehler:** ~8€ pro Aktie DR0 (entgangener Gewinn + Verlust)

**Regel:**
> Ein Stop der nicht in Trade Republic sitzt, existiert nicht.
> Stop wird beim Kauf gesetzt — nicht später, nicht nach dem Schlafen, nicht "gleich".
> Reihenfolge: Kauf → Stop setzen → fertig. Keine Ausnahmen.

**Konkret:**
- Stop direkt nach Kauf in TR setzen (noch bevor das Fenster geschlossen wird)
- Minimaler Stop = Entry minus vereinbartes Risiko (z.B. 5%)
- Nachziehen nur nach Marktschluss (nie intraday)

---

## LEKTION 2: Nachrichten-getriebene Moves werden zu spät erkannt
**Datum:** 09.03.2026
**Was passierte:** Trump sagte "short term excursion" + Russia Öl-Sanktionen Easing — WTI crashte von $103 auf $84 (-18%). Albert hat das NICHT in Echtzeit gemeldet. Strategie-Check lief nur 11:30 + 14:30. Der Move passierte zwischen 14:30 und 22:00 — 7,5 Stunden Blindflug.

**Regel:**
> Preisbewegungen ≥5% in Öl oder VIX-Sprung ≥5 Punkte = SOFORT-Alert, nicht beim nächsten geplanten Check.
> Nachrichten mit den Stichwörtern: Trump + Iran/Öl/Ceasefire/Sanctions = SOFORT recherchieren und melden.

**Konkret (bereits umgesetzt):**
- Intraday Alert Monitor (Cron `56f90272`): läuft jede 30 Min, 09:00-22:30, Mo-Fr
- Trigger: WTI ±5% vom Tageshoch/-tief, WTI ±3% in 30 Min, VIX +5 Punkte
- Bei Trigger: Reuters-News holen + Portfolio-Impact + Empfehlung senden

**Noch offen:**
- Reine Nachrichten-Überwachung (ohne Preisbewegung) als separater Layer
- Keywords: Trump, Iran, ceasefire, Hormuz, sanctions, oil — alle 60 Min prüfen

---

## LEKTION 4: Kontext zusammendenken — nicht auf Fragen warten
**Datum:** 10.03.2026
**Was passierte:** Albert wusste gleichzeitig (1) DR0 Stop gefährdet, (2) Stops müssen nachgetragen werden, (3) L&S öffnet 07:30. Hat diese Infos NICHT zusammengeführt und Victor proaktiv gesagt: "L&S ist jetzt offen, setz die Stops." Stattdessen gewartet bis Victor fragt.

**Regel:**
> Wenn mehrere bekannte Fakten zusammen eine klare Handlungsempfehlung ergeben → SOFORT sagen. Nicht warten bis der Mensch die Dots selbst verbindet.
> "Ich weiß A, ich weiß B, A+B = du musst jetzt X tun" → direkt raus damit.

---

## LEKTION 3: Angenommene Stops sind falsche Sicherheit
**Datum:** 09.03.2026
**Was passierte:** Albert hat in allen Analysen und Reports mit "Stop X€" gearbeitet als wären diese real. Victor hatte das Gefühl die Positionen sind geschützt — waren sie nicht.

**Regel:**
> Albert fragt beim Morgen-Briefing aktiv: "Sind alle Stops in TR gesetzt?"
> Abend-Report enthält Checkliste: reale Stops für alle offenen Positionen bestätigt?
> Bei jeder neuen Position: Stop-Level vereinbaren UND Victor explizit fragen ob gesetzt.

---

## LEKTION 6: News-Aktualität immer angeben
**Datum:** 10.03.2026
**Was passierte:** Intraday-Alert zitierte Bloomberg-News die 1 Stunde alt war als wäre sie aktuell. Victor traf Entscheidungen auf Basis veralteter Information. DR0.DE Stop ausgelöst — kurz danach kam Korrektur der Falschinformation (Öl erholte sich).

**Regel:**
> Jede News-Meldung MUSS mit Uhrzeit zitiert werden: "Bloomberg, 17:15 Uhr".
> Wenn News älter als 30 Minuten: explizit warnen "⚠️ Diese Info ist X Minuten alt — könnte veraltet sein."
> Für Intraday-Entscheidungen: News älter als 30 Min = nicht als Entscheidungsgrundlage verwenden.

---

## LEKTION 5: Immer voller Name + Ticker
**Datum:** 10.03.2026
**Was passierte:** "RHM.DE" in Dokumenten führte zur Verwechslung mit einer anderen Position. Victor dachte Rheinmetall AG wäre ausgestoppt, war aber eine andere Aktie.

**Regel:**
> Positionen immer als "Voller Name (TICKER)" schreiben — z.B. "Rheinmetall AG (RHM.DE)", nie nur "RHM.DE".
> Gilt für alle Dateien, Nachrichten, Reports, Tabellen.

---

## Stop-Checkliste für neue Positionen

Jedes Mal wenn Victor eine neue Position eröffnet:
1. Welcher Stop? (Albert schlägt Level vor)
2. Victor setzt Stop in TR (nicht später)
3. Albert bestätigt Stop im System
4. Stop ist live — erst dann ist die Position "sauber"

---

## Verbesserungen die daraus entstanden

| Problem | Lösung | Status |
|---|---|---|
| Kein Intraday-Alert bei Preisbewegungen | Cron `56f90272`: jede 30 Min WTI/VIX Monitor | ✅ live ab 10.03. |
| Stops nur mental | Neue Regel: Stop bei Kauf setzen, Bestätigung an Albert | ✅ dokumentiert |
| Falsche Stop-Annahmen in Analysen | Morgen-Briefing + Abend-Report mit Stop-Verifikation | 🔄 umzusetzen |
| Nachrichten-Lücke zwischen Checks | Nachrichten-Monitor (Keywords) als Ergänzung | 📋 geplant |
