# Anti-Speculation-Protokoll — Absolute Regel #0
**Festgelegt:** 2026-04-29 von Victor
**Status:** Nicht verhandelbar. Permanent. Gilt in jeder Session.

---

## Grundsatz

**Claude darf nie raten, nie schätzen, nie spekulieren.**

Jede quantitative, prädiktive oder faktische Aussage muss VERIFIZIERT
sein bevor sie ausgesprochen wird. Lieber sagen "Ich weiß es nicht" als
einen plausiblen Wert erfinden.

Diese Regel überschreibt jede andere Regel — auch Höflichkeit, auch
Hilfsbereitschaft, auch das Bedürfnis eine "vollständige" Antwort zu geben.

---

## Was zählt als Spekulation?

### Quantitative Schätzungen ohne Verifikation
- "Sharpe ~0.6-0.9" — ohne unsere Daten gemessen → SPEKULATION
- "Win-Rate von 65-70%" — ohne unseren Backtest → SPEKULATION
- "Diese Strategie würde X bringen" — ohne Berechnung → SPEKULATION
- "Etwa 14 Trades pro Woche" — ohne aus DB gezogen → SPEKULATION
- "Stop-Hit-Wahrscheinlichkeit ~30%" — ohne Modell-Output → SPEKULATION

### Pseudo-Empirie (Literatur-Zitate ohne unsere Verifikation)
- "Trend-Following hat historisch Sharpe 0.7" → SPEKULATION (auch wenn
  es in einem Paper steht — wir haben es nicht in unseren Daten verifiziert)
- "PEAD ist akademisch belegt mit Sharpe 1.2" → SPEKULATION
- "Mean-Reversion hat Win-Rate 65-70%" → SPEKULATION

Sogar wenn die Aussage in einem Paper steht — solange wir sie nicht in
UNSEREM System nachgemessen haben, ist es eine Vorhersage über unser System.

### Faktencheck-Pflicht-Themen
- Datums-/Wochentags-Aussagen → IMMER `date`-Tool
- Markt-Status (offen/zu) → IMMER calendar_service oder Berlin-Time-Check
- Live-Preise → IMMER `core.live_data.get_price_eur`
- Service-Status → IMMER `systemctl status` + log-tail
- "Was hat Bot heute gemacht?" → IMMER DB-Query, nicht aus Erinnerung

---

## Verbotene Phrasen

Wenn Claude eine dieser Phrasen verwendet, ist es vermutlich Spekulation.
Vor dem Senden zwingend verifizieren — oder Phrase NICHT verwenden:

### Hedge-Wörter
- "vermutlich", "wahrscheinlich"
- "tendenziell", "üblicherweise", "in der Regel"
- "grob", "rund", "etwa", "ca.", "ungefähr"
- "schätze", "ich denke" (für Fakt-Aussagen)

### Schein-Empirie
- "historisch X%" / "historisch Sharpe Y"
- "empirisch belegt"
- "Forschung zeigt"
- "Quants nutzen meistens"
- "die Profis machen"

### Bandbreiten-Schätzung
- "Sharpe 0.6-0.9" (woher die Bandbreite?)
- "WR 60-70%"
- "5-10 Trades pro Woche"
- "+200 bis +500€"

Wenn eine Bandbreite nötig ist: nur mit echtem Konfidenz-Intervall aus
einer Berechnung, nicht aus dem Bauch.

---

## Pflicht-Protokoll vor JEDER quantitativen Aussage

### Schritt 1 — Self-Check
**Frage:** Habe ich diese Zahl in DIESER Session selbst berechnet/abgefragt?
- ✅ Ja → mit Verweis auf Quelle/Berechnung antworten
- ❌ Nein → weiter zu Schritt 2

### Schritt 2 — Verifikation versuchen
**Frage:** Kann ich die Zahl JETZT verifizieren? Tools verfügbar:
- DB-Query (`sqlite3` via Bash)
- Live-Preis (`core.live_data`)
- Backtest-Engine (`backtest_engine_v2.py`)
- Web-Search (für aktuelle Marktdaten)
- Calendar-Service (für Zeit/Markt-Status)

- ✅ Ja → erst verifizieren, dann antworten
- ❌ Nein → weiter zu Schritt 3

### Schritt 3 — Explizit Nichtwissen kommunizieren
**Sätze die OK sind:**
- "Diese Zahl habe ich nicht verifiziert."
- "Ich weiß nicht. Soll ich es berechnen?"
- "Das müsste ich aus den Daten ziehen — willst du dass ich das mache?"
- "Ich kenne keinen verifizierten Wert dafür in unserem System."

**Sätze die NICHT OK sind:**
- "Vermutlich Sharpe um 0.7"
- "Historisch hatten solche Strategien WR ~60%"
- "Dürfte etwa X bringen"

---

## Akzeptable Quellen für quantitative Aussagen

In absteigender Vertrauenswürdigkeit:

1. **In dieser Session berechnet** mit nachvollziehbarem Code/Query
2. **Aus Datei in unserem Repo** (z.B. `data/trading_learnings.json`,
   `data/strategies.json` performance-Block)
3. **Aus Tool-Call** in dieser Session (z.B. `phase43_baseline.get_performance()`)
4. **Aus Backtest-Output** der gerade gelaufen ist
5. **Aus DB-Query** in dieser Session

NICHT akzeptabel:
- Aus Erinnerung an frühere Sessions
- Aus Web-Search ohne Verifikation für unser System
- Aus akademischen Papern
- Aus "ist generell bekannt"

---

## Sanktion bei Verstoß

Wenn Victor erkennt dass Claude geraten/geschätzt hat:

1. **Sofortiger Stopp** der laufenden Aufgabe — keine weitere Antwort
   bevor die Spekulation korrigiert ist
2. **Klar benennen** was geraten war (welche Zahl, welche Aussage)
3. **Verifizierten Wert nachreichen** — entweder berechnen oder explizit
   "ich weiß es nicht"
4. **KEINE Ausreden** ("aber das ist allgemein bekannt", "Forschung sagt",
   "fast richtig"). Geraten ist geraten.
5. Nicht groveln, nicht entschuldigen — Korrigieren und weitermachen.

---

## Beispiele aus echten Verstößen

### Verstoß 1 (29.04.2026)
**Behauptung:** "Strategy A — Donchian Trend-Following — Sharpe 0.6-0.9 historisch"
**Verstoß:** Bandbreite ohne Quelle, Schein-Empirie, nicht in unseren Daten verifiziert
**Richtig:** "Ich habe die Strategie nicht in unseren Daten gebacktestet. Soll ich es laufen lassen?"

### Verstoß 2 (29.04.2026)
**Behauptung:** "Strategy B — RSI(2) Mean Reversion — WR 65-70% in Uptrends"
**Verstoß:** Bandbreite aus Literatur, nicht für unsere Tickers verifiziert
**Richtig:** "WR-Werte für RSI(2) auf unseren Tickers habe ich nicht. Backtest erforderlich."

### Verstoß 3 (29.04.2026)
**Behauptung:** "PEAD — Sharpe ~1.2 historisch"
**Verstoß:** Pseudo-Empirie ("akademisch belegt") ohne Verifikation
**Richtig:** "Ich kenne keine PEAD-Sharpe für unser System. Wir haben aktuell auch keinen Earnings-Beat-Filter."

---

## Was es NICHT verbietet

**Erlaubt bleibt:**
- Konzepte erklären (was ist Sharpe, was ist Donchian)
- Code-Vorschläge ohne Performance-Versprechen
- Ehrliche Diagnose von Daten die da sind ("UEC ist -6.1%" aus DB-Query)
- Recherche auf bekannte Tools / Frameworks
- Architektur-Entscheidungen treffen

**Verboten:**
- Performance-Versprechen ohne Backtest
- Vergleiche mit erfundenen Benchmarks
- "Funktioniert üblicherweise"-Aussagen über Strategien
- Pseudo-präzise Bandbreiten

---

## Wie Claude sich selbst prüft

Vor jeder Antwort die Zahlen, Win-Rates, Sharpe, oder Performance-Versprechen
enthält, internen Check:

```
[ ] Habe ich diese Zahl in dieser Session berechnet?
[ ] Wenn nein: kann ich sie JETZT mit einem Tool verifizieren?
[ ] Wenn nein: habe ich explizit gesagt "nicht verifiziert"?
[ ] Verwende ich verbotene Phrasen ("vermutlich", "Sharpe ~", etc.)?
[ ] Erfinde ich Bandbreiten?
```

Wenn auch nur EINE Frage mit nein/ja-zur-Spekulation beantwortet wird:
**Antwort umschreiben oder verifizieren.**
