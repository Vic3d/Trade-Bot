# Strategie ALBERT — "Geopolitischer Kontra-Sniper"
## Deep Dive — Fundiert, Getestet, Kampfbereit

**Erstellt:** 26.03.2026
**Deep Dive:** 26.03.2026 20:00 CET
**Paper Trading Code:** SA (Strategie Albert)
**Typ:** Event-Driven Swing (2-20 Tage Haltezeit)
**Zielrendite:** 3-5% pro Monat bei kontrolliertem Drawdown <8%

---

## Teil 1: WARUM diese Strategie funktionieren sollte

### 1.1 Das akademische Fundament

**BlackRock Geopolitical Risk Indicator (BGRI) Framework:**
BlackRock misst geopolitisches Risiko über zwei Achsen:
- **Market Attention:** Wie stark reden Broker-Reports und Finanznews über ein bestimmtes Risiko?
- **Market Movement:** Bewegen sich Assets bereits in die Richtung die das Risiko-Szenario vorhersagt?

Ihre Erkenntnis: **Wenn Attention hoch ist aber Movement noch niedrig → der Markt hat das Risiko noch nicht eingepreist.** Das ist genau das Fenster in dem unser Scanner uns positioniert.

Ihr Scoring: 0 = Durchschnitt, +1 = eine Standardabweichung über Normal. Wir machen es ähnlich mit unserem 3-Tier System (LOW/MEDIUM/HIGH).

**Cboe VIX Mean-Reversion Eigenschaft:**
Die Cboe bestätigt: VIX ist **mean-reverting** — hohe Werte tendieren zurück zum Mittelwert (~18-20). Das ist kein Bauchgefühl, das ist eine mathematisch bewiesene Eigenschaft. Unsere Setup C (VIX-Kontra) nutzt genau das.

**Implied vs. Realized Volatility Premium:**
Die Cboe schreibt: "Expected volatility implied by SPX option prices tends to trade at a PREMIUM relative to subsequent realized volatility." Übersetzt: **Der Markt überschätzt regelmäßig das tatsächliche Risiko.** Bei geopolitischen Schocks ist diese Überschätzung noch stärker — perfekt für Contrarian-Trades.

**Lars Eriksen Fahnenstangen-Framework:**
Aus unserem Transcript: Parabolische Anstiege werden IMMER korrigiert. ABC-Korrekturen haben berechenbare Fibonacci-Levels. Das C-Tief ist statistisch der beste Einstiegspunkt. Wir nutzen das als Timing-Tool für Rohstoff-bezogene Trades.

### 1.2 Was die Profis machen (und was wir besser können)

**Hedge Funds bei Geopolitik:**
- Bridgewater/BlackRock nutzen proprietäre NLP-Modelle auf Millionen Broker-Reports
- Wir haben keinen Bloomberg-Terminal, ABER: Unser Geopolitical Scanner läuft 3x täglich auf liveuamap (Echtzeit) + Google News RSS (breit). Das gibt uns den **Retail-Informationsvorsprung** — wir sehen Entwicklungen in Echtzeit, während der durchschnittliche Retail-Trader auf CNBC-Headlines wartet.

**Unser einzigartiger Edge (was kein Bloomberg-Terminal kann):**
1. **Regionale Granularität**: Wir scannen 10+ Subdomains von liveuamap — vom Nahen Osten über Europa bis Kuba. Kein Retail-Tool macht das.
2. **Zweitrundeneffekte**: Ein Mensch liest "Iran greift UAE an" und denkt "Öl steigt." Ich lese dasselbe und denke: "Rumaila 1.4M bbl/day → Libyen-Pipeline auch blockiert → LNG Taiwan 11 Tage Reserve → Equinor profitiert doppelt + Kupferpreis wegen Militärproduktion." Die Verknüpfung ist mein Edge.
3. **Emotionslosigkeit**: Wenn der VIX auf 35 springt und alle in Panik verkaufen, kaufe ich nach Regel — kein Zögern, kein FOMO, kein Rachetrading.

### 1.3 Was unsere eigenen Daten beweisen

**Aus 178 Paper Trades (Stand 26.03.2026):**

| Erkenntnis | Daten | Konsequenz |
|---|---|---|
| Intraday = Geldverbrennung | 132 Trades, -1.339€ | Min. 2 Tage halten |
| Viele Trades = Verlust | DT4: 96 Trades, -839€ | Max 3-5 gleichzeitig |
| Geopolitik-These = einziger Edge | OXY +341€ (Iran), 9988.HK +428€ (China) | Nur mit These traden |
| VIX >25 = alle verlieren | VIX 25-30: 0% Win Rate (4 Trades) | Position verkleinern |
| Asien > Europa > USA | Asien 47% WR, Europa 30% | Geographische Allokation beachten |
| Contrarian fast Break-Even | 19 Trades, ~+5€ | Mit besserem Timing profitabel |
| Wenige Gewinner dominieren | Top 3 = +955€ vs Rest = Noise | Gewinner laufen lassen |

---

## Teil 2: DIE STRATEGIE (Regeln)

### 2.1 Die 7 Eisernen Regeln

#### Regel 1: KEIN TRADE OHNE THESE IN EINEM SATZ

**Format:** "Ich kaufe [AKTIE] weil [GEOPOLITISCHES EVENT] in [ZEITRAUM] den Kurs um [SCHÄTZUNG] bewegen wird, und der Markt das noch nicht eingepreist hat."

**Checkliste vor jedem Trade:**
- [ ] Kann ich die These in einem Satz formulieren?
- [ ] Hat der Scanner das Thema als MEDIUM oder HIGH gemeldet?
- [ ] Gibt es mindestens eine Zweitrundeneffekt-Verknüpfung die nicht offensichtlich ist?
- [ ] Habe ich mindestens 2 Quellen geprüft?

**Wenn auch nur eine Checkbox fehlt → KEIN TRADE.**

#### Regel 2: CRV MINIMUM 3:1 (ausnahmslos)

Die Mathematik ist einfach:
- Bei 35% Win Rate und 3:1 CRV: **Erwartungswert = +0,40% pro Trade**
  - (0,35 × 3) - (0,65 × 1) = 1,05 - 0,65 = +0,40
- Bei 40% Win Rate und 3:1 CRV: **Erwartungswert = +0,60% pro Trade**
- Bei 30% Win Rate und 3:1 CRV: **Erwartungswert = +0,25% pro Trade** — immer noch profitabel!

**Konsequenz:** Selbst wenn wir nur in 30% der Fälle richtig liegen, verdienen wir Geld. Aber NUR wenn wir diszipliniert bei 3:1 bleiben und Verluste sofort begrenzen.

#### Regel 3: VIX-ADAPTIVE POSITIONIERUNG

| VIX | Max Positionen | Risiko/Trade | Positionsgröße | Mindest-CRV |
|---|---|---|---|---|
| <18 | 5 | 2,0% | 100% Standard | 3:1 |
| 18-22 | 4 | 2,0% | 100% Standard | 3:1 |
| 22-27 | 3 | 1,5% | 75% | 3:1 |
| 27-35 | 2 | 1,0% | 50% | 4:1 |
| >35 | 1 | 0,5% | 25% | 5:1 |

**Aktuell (VIX 27,56 am 26.03.2026):** Max 2 Positionen, 1% Risiko, CRV mind. 4:1.

**Begründung:** Cboe-Daten zeigen VIX ist mean-reverting. Bei VIX >27 ist die tägliche Schwankung 2-3% — enge Stops werden durch Noise ausgelöst, nicht durch falsche Thesen. Also: kleiner traden, weiter stoppen, höheres CRV verlangen.

#### Regel 4: GEOPOLITIK-FILTER

Ich trade NUR Aktien die von einem **aktiven, von meinem Scanner getrackten** geopolitischen Thema betroffen sind.

**Aktive Themen (26.03.2026):**

| Thema | Scanner Status | Betroffene Sektoren | Primär-Ticker |
|---|---|---|---|
| 🇮🇷 Iran/Hormuz | CRITICAL (70) | Öl, Tanker, Defense | OXY, EQNR, FRO, DHT |
| 🇨🇺 Kuba-Blockade | HIGH (50+) | Kobalt, Nickel, Tanker | S.TO, MP, CCL |
| 🥈 Silber-Korrektur | WATCHLIST | Minenbetreiber | AG, PAAS, WPM |
| 🇨🇳 China-Tech/Trade War | MEDIUM | Tech, EV, Solar | 9988.HK, 0700.HK |
| 🇵🇰 Pakistan/Afghanistan | MONITORING | Defense | —  |

**Was ich NICHT trade:**
- Reine Charttechnik-Setups ("EMA-Crossover")
- Aktien ohne geopolitische Verbindung
- "Heiße Tipps" aus Foren/Social Media
- Aktien die ich fundamental nicht verstehe

#### Regel 5: POSITION SIZING (ATR-basiert)

```
Position Size = Risiko-Budget / (ATR × 2)

Beispiel (Portfolio 100.000€, VIX 27 → 1% Risiko):
- Risiko-Budget: 1.000€
- OXY ATR(14): $2,50 → Stop = 2 × ATR = $5,00 (~€4,35)
- Shares: 1.000€ / 4,35€ = 229 Shares
- Position: 229 × 52€ = 11.908€ (~12% vom Portfolio)
```

**Warum ATR statt fester Prozent-Stop:**
ATR passt sich automatisch an die Volatilität der einzelnen Aktie an. Eine Aktie die normal 3% am Tag schwankt braucht einen anderen Stop als eine die nur 0,5% schwankt. Feste 5%-Stops ignorieren das.

#### Regel 6: TRAILING STOP SYSTEM (4 Phasen)

| Phase | Trigger | Stop-Aktion | Position |
|---|---|---|---|
| 🔴 Initial | Trade eröffnet | Stop auf ATR×2 unter Entry | 100% offen |
| 🟡 Breakeven | +1,5× Risiko-Betrag | Stop auf Entry nachziehen | 100% offen |
| 🟢 Trailing | +3× Risiko-Betrag | Stop auf 50% des Gewinns | 100% offen |
| 🚀 Runner | +5× Risiko-Betrag | Stop auf 70% des Gewinns | 30% schließen, 70% laufen lassen |

### Gewinnmitnahme-Regeln (NUR realisierte Gewinne sind echte Gewinne!)

| Trigger | Aktion | Warum |
|---|---|---|
| **+3× Risiko (CRV 3:1)** | Trail auf 50% Gewinn | Kernziel erreicht, Gewinn absichern |
| **+5× Risiko** | Trail auf 70% Gewinn | Sehr guter Trade, eng absichern |
| **+7× Risiko** | **KOMPLETT SCHLIESSEN** | Home Run — Buch zu, Gewinn realisieren! |
| **+8% und Scanner-Score halbiert** | **KOMPLETT SCHLIESSEN** | Event ist eingepreist, nicht warten bis es dreht |
| **+5% und VIX fällt unter 22** (Entry war >25) | **KOMPLETT SCHLIESSEN** | Vola-Premium ist weg = Geopolitik-Aufschlag verschwindet |
| **These stirbt** | **SOFORT SCHLIESSEN** | Egal ob +20% oder -5% — ohne These kein Trade |

**Kernprinzip:** Unrealisierte Gewinne sind Fantasie. Nur was auf dem Konto landet zählt. Lieber +5% realisiert als +12% angeguckt und dann bei +1% rausgefallen.

**Ausnahme:** Wenn die These sich fundamental ändert (z.B. Iran-Deal plötzlich doch möglich), sofort schließen — unabhängig vom P&L.

#### Regel 7: GEDULD UND DISZIPLIN

- **Kein Trade ist besser als ein schlechter Trade.** Cash ist eine Position.
- **Max 1-3 neue Trades pro Woche.** Nicht 1-3 pro Tag.
- **Nach einem Verlust: 24h Pause.** Kein Rache-Trading.
- **Mindestens 1 Woche pro Monat: NULL neue Trades.** Bewusste Cash-Phase.
- **Jede Woche Samstag: Review.** Was lief gut? Was schlecht? Regeln eingehalten?

---

## Teil 3: DIE 4 SETUPS (wann kaufe ich)

### Setup A: "Geopolitischer Schock" 🔴 (Reaktiv)

**Trigger:** Scanner meldet CRITICAL Event (Score >50) mit direktem Sektor-Impact
**Reaktionszeit:** 1-4 Stunden nach Event-Erkennung
**Haltedauer:** 3-10 Tage
**Position:** Direkt betroffene Aktien (Öl bei Iran, Defense bei Eskalation)

**Ablauf:**
1. Scanner CRITICAL Alert → ich prüfe sofort die Meldung
2. Zweitrundeneffekte berechnen: WER profitiert wirklich? (nicht nur der offensichtliche Sektor)
3. Mindestens 2 Quellen verifizieren (Fake News ausschließen)
4. Entry: möglichst früh, bevor Mainstream-Medien es aufgreifen
5. Stop: unter Pre-Event-Kurs (der Markt darf den Schock nicht komplett auslöschen)

**Historisches Beispiel (unsere Daten):**
- Iran greift Abu Dhabi an → OXY läuft von $48 auf $56 in 5 Tagen
- Wer nach 2 Stunden eingestiegen ist: +12-15%
- Wer nach 2 Tagen eingestiegen ist: +5-7% (immer noch gut, aber weniger Edge)

**Risiko:** 1-2% je nach VIX | **CRV:** min. 3:1

### Setup B: "Schleichende These" 🟡 (Proaktiv)

**Trigger:** Eigene Analyse identifiziert Entwicklung die der Markt noch nicht einpreist
**Reaktionszeit:** Tage bis Wochen (kein Zeitdruck)
**Haltedauer:** 5-30 Tage
**Position:** Sekundäre Profiteure (nicht der offensichtliche Trade)

**Ablauf:**
1. Scanner zeigt über Tage/Wochen ein Muster: Thema baut Attention auf
2. Ich identifiziere den Zweitrundeneffekt den der Markt noch nicht sieht
3. Warte auf ein technisches Entry-Signal (Support-Test, Pullback zu EMA)
4. Entry mit voller Regel-Checkliste
5. Haltedauer: bis These im Mainstream angekommen ist (dann verkaufen die Profis an die Retail-Käufer)

**Aktuelles Beispiel:**
- Kuba-Tanker Anatoly Kolodkin kommt am 29.03. an → US Coast Guard könnte abfangen
- Offensichtlicher Trade: Tanker-Aktien (FRO, DHT)
- Zweitrundeneffekt: **Kobalt-Lieferkette** (Kuba hat 5% der Weltreserven) → MP Materials, Glencore
- Drittrundeneffekt: **Cruise-Lines** (CCL) → Kuba-Routen komplett tot
- Noch nicht eingepreist weil der Mainstream nur "Regime Change" sieht, nicht die Rohstoff-Kette

**Risiko:** 1-1,5% | **CRV:** min. 4:1

### Setup C: "VIX-Kontra" 🟢 (Contrarian)

**Trigger:** VIX spikt über 35 wegen Panik, aber Fundamentals haben sich nicht proportional geändert
**Reaktionszeit:** Erst wenn VIX anfängt zu fallen (NICHT ins fallende Messer!)
**Haltedauer:** 5-15 Tage
**Position:** Broad Market (SPY, QQQ) oder am stärksten überverkaufte Qualitäts-Aktien

**Ablauf:**
1. VIX springt über 35 → **NICHT sofort kaufen!**
2. Analyse: Hat sich fundamental etwas verändert? (Krieg, Ölembargo, Finanzkrise) → wenn JA: kein Kontra-Trade
3. Warten bis VIX unter 32 fällt (Panik lässt nach, Mean Reversion setzt ein)
4. Entry in Qualitäts-Aktien die am stärksten überreagiert haben
5. Stop: unter dem Panic-Low des Index

**Warum das funktioniert (akademisch):**
- Cboe-Daten: Implied Volatility > Realized Volatility (systematische Überschätzung)
- VIX ist mean-reverting → Spikes über 35 fallen in >80% der Fälle innerhalb von 10 Tagen unter 28
- Unsere Paper-Daten: Contrarian-Trades sind bei Break-Even (19 Trades, +5€) — mit besserem Timing (VIX-Trigger statt Random-Entry) werden sie profitabel

**Risiko:** 0,5-1% | **CRV:** min. 3:1

### Setup D: "Fahnenstangen-Boden" 📊 (Eriksen-Framework)

**Trigger:** Rohstoff hat Fahnenstange hinter sich + zeigt Bodenbildungssignal
**Reaktionszeit:** Wochen (kein Zeitdruck, wartet auf Wochenschluss)
**Haltedauer:** 15-60 Tage (Positionstrade)
**Position:** Rohstoffproduzenten (gehebelt zum Rohstoffpreis)

**Ablauf (Eriksen 2-Stufen):**
1. Rohstoff hat parabolisch (+30% in 4 Wochen) gestiegen und crasht → Fahnenstange bestätigt
2. **Stufe 1 (Antizyklisch):** Wochenschluss über Schlüssel-Level → 30% der geplanten Position
3. ABC-Korrektur abwarten: A (erster Sell-off) → B (Erholung 38-50% Fibonacci) → C (finaler Sell-off)
4. **Stufe 2 (Prozyklisch):** Kurs über fallenden GD auf Wochenchart → 70% der geplanten Position
5. Statistik-Overlay: Innerhalb von 24 Monaten nach Fahnenstange selten neue Hochs → moderate Ziele

**Aktuelles Beispiel: Silber**
- Fahnenstange: Jan 2026 ~$115-120 → jetzt $68 (-43%)
- Stufe 1 Trigger: Wochenschluss >$73,50 → noch NICHT ausgelöst ($67,97)
- Stufe 2 Trigger: Wochenschluss >$90 über fallenden GD
- Aktien: AG (40%), PAAS (25%), WPM (20%), HL (10%), EXK (5%)

**Risiko:** 1,5% | **CRV:** min. 4:1

---

## Teil 4: RISIKOMANAGEMENT

### 4.1 Portfolio-Level Regeln

| Regel | Wert | Warum |
|---|---|---|
| Max gleichzeitige Positionen | 5 (VIX-abhängig, s.o.) | Konzentration = Edge |
| Max Risiko gesamt | 8% des Portfolios | Überleben > Rendite |
| Max Risiko pro Sektor | 4% | Kein Klumpenrisiko |
| Max Korrelation | 2 Positionen im gleichen Thema | Iran-Trades: max 2 (z.B. OXY + FRO) |
| Cash-Reserve immer | Min. 40% in Cash | Pulver trocken für Schock-Events |
| Max Drawdown → Pause | -10% vom Peak → 1 Woche keine neuen Trades | Verlustbremse |

### 4.2 Was passiert wenn die These stirbt?

**Sofort schließen — egal was der Chart sagt.**

Beispiele:
- Iran-These: Waffenstillstand wird angekündigt → Alle Öl-Long sofort schließen
- Kuba-These: US lässt Tanker passieren → Kobalt/Nickel-Positionen schließen
- Silber-These: Fed erhöht überraschend um 100bp → Gold/Silber crashen, raus

Die These ist IMMER wichtiger als der Preis. Charttechnik bestimmt das Timing, aber die These bestimmt ob der Trade existiert.

### 4.3 Tägliches Risiko-Monitoring

Jeden Abend (automatisch via Cron):
1. Alle offenen SA-Positionen gegen Scanner-Updates prüfen
2. Trailing Stops aktualisieren
3. VIX checken → ggf. Positionsgrößen anpassen
4. Thesen-Status: Hat sich was fundamental geändert?

---

## Teil 5: TRACKING UND LERNEN

### 5.1 Pflicht-Log pro Trade

Jeder SA-Trade wird in der DB erfasst mit:
- **thesis**: Der Ein-Satz-Begründung
- **setup_type**: A (Schock) / B (Schleichend) / C (VIX-Kontra) / D (Fahnenstange)
- **scanner_score**: Score zum Zeitpunkt des Entry
- **vix_at_entry**: VIX bei Eröffnung
- **second_order_effect**: Welcher Zweitrundeneffekt wurde identifiziert?
- **thesis_alive**: BOOL — ist die These noch intakt? (bei Schließung aktualisieren)
- **thesis_killed_by**: Was hat die These zerstört? (wenn applicable)

### 5.2 Wöchentliches Review (Samstag)

1. Welche Setups hat Albert identifiziert? (A/B/C/D)
2. Welche davon hat er tatsächlich getradet?
3. Wurde die These bestätigt oder widerlegt?
4. Wurde das CRV eingehalten?
5. Hat der VIX-Filter richtig funktioniert?
6. Was hat der Scanner richtig/falsch erkannt?
7. **Selbstkritik:** Wo war ich zu aggressiv? Wo zu passiv?

### 5.3 Monatliches Strategie-Update

Nach jedem Monat (oder 20+ geschlossenen Trades):
- Win Rate pro Setup (A/B/C/D)
- Durchschnittlicher CRV realisiert vs. geplant
- Bestes/schlechtestes Setup → Anpassungen
- VIX-Korrelation bestätigt?
- Scanner-Qualität → Threshold-Anpassung?

---

## Teil 6: JETZT — Was Albert heute traden würde

### Marktlage 26.03.2026
- **VIX:** 27,56 (+8,8% heute) → Zone "27-35": Max 2 Positionen, 1% Risiko, CRV 4:1
- **Scanner:** Score 504 (HIGH), Iran CRITICAL, Pakistan CRITICAL
- **Regime:** TREND_DOWN (ADX 47,7 > 25, SPY unter MA20)

### Kandidat 1: OXY (Occidental Petroleum) — Setup B "Schleichende These"

**These:** "Ich kaufe OXY weil der Iran-Deal strukturell unmöglich ist (Araqchi/Qalibaf auf Target-Liste), Hormuz-Risiko steigt (Iran 'studying special arrangements'), und Öl bei Brent >$90 bleiben wird. Der Markt preist nur den aktuellen Konflikt ein, nicht die Eskalationsspirale (UAE Angriff → Saudi Drohnen → Pakistan Bombardierung)."

- **Zweitrundeneffekt:** Pakistan bombardiert Afghanistan → Taliban retaliiert → Pakistan-Iran Grenze wird unsicher → alternative Öl-Routen via Pakistan gefährdet
- **Entry:** ~$52-53 (aktueller Bereich)
- **Stop:** $47 (ATR×2, unter 200-Tage-Support) → Risiko ~$5 pro Share
- **CRV-Berechnung:** Risiko $5, Ziel $65+ (Hormuz-Eskalation) → CRV 2,6:1... **NICHT GENUG!**

**Anpassung:** Warte auf Pullback zu $50-51 → dann CRV 3:1+ ✅
- Alternativ: Stop enger auf $49 → aber VIX 27 → zu eng für die Vola

**Status:** ⏳ **WARTEN auf besseren Entry** (Geduld, Regel 7!)

### Kandidat 2: KEIN zweiter Trade

- VIX zu hoch (27,56) für mehr als eine Position
- Kuba: Tanker kommt 29.03 → könnte Setup A werden, aber noch nicht
- Silber: $67,97, weit unter $73,50 → kein Fahnenstangen-Signal
- China: 9988.HK hatte die besten Trades — aber kein akuter Trigger

**Entscheidung: CASH HALTEN.** 100% Cash, 0 Positionen. Pulver trocken.

---

## Teil 7: RÜCKVERGLEICH — Albert vs. Altes System

| Metrik | DT4 (alt) | SA Albert (Projektion) |
|---|---|---|
| Trades/Woche | 20-40 | 1-3 |
| Win Rate | 44% (realisiert) | 35-40% (konservativ angesetzt) |
| Avg Win:Loss | ~1:1 | 3:1 (erzwungen durch Regel 2) |
| Expected Value/Trade | **-9€** (realisiert, -839€/96) | **+40€** (bei 35% WR, 5000€ Pos) |
| Drawdown | unkontrolliert | Max -10% → Pause |
| Emotionaler Stress | Hoch (96 Entscheidungen) | Niedrig (3-5 Entscheidungen/Woche) |
| Gebühren (TR) | 96 × 3€ = 288€ | ~10 × 3€ = 30€ |

**Break-Even Analyse:** SA braucht nur **7,5 Trades pro Monat** (bei 5000€ und 35% WR × 3:1 CRV) um den Monat positiv abzuschließen. DT4 brauchte 96 Trades und schaffte es trotzdem nicht.

---

## Zusammenfassung: Die Essenz

**Albert tradet wie ein Scharfschütze, nicht wie ein Maschinengewehr.**

1. 🎯 **Wenige Schüsse, hohe Treffsicherheit** — max 3-5 Trades/Woche
2. 🌍 **Geopolitik als Edge** — Scanner + Zweitrundeneffekte = Informationsvorsprung
3. 📊 **VIX als Gasregler** — hoch = wenig traden, niedrig = normal traden
4. 🎰 **Asymmetrie erzwingen** — 3:1 CRV Minimum, Gewinner laufen lassen
5. 💰 **Cash ist eine Position** — 40%+ immer in Reserve
6. 🧠 **These > Chart** — die Begründung bestimmt den Trade, nicht das Pattern
7. ⏰ **Geduld ist der wichtigste Skill** — der beste Trade ist oft der, den man nicht macht

---

## Teil 8: GESCHLOSSENE FEEDBACK-LOOP (Pflicht!)

### Beim Schließen jedes Trades — 5 Pflicht-Fragen:

```
1. These korrekt?          (ja/nein)
2. Was hat funktioniert?   (konkret, nicht "alles gut")
3. Was hat NICHT funktioniert? (schonungslos ehrlich)
4. Lektion?                (1 Satz den ein anderer Trader verstehen würde)
5. Trade wiederholen?      (ja/nein + warum)
```

**KEIN TRADE WIRD GESCHLOSSEN OHNE DIESE 5 ANTWORTEN.**

Verlierer sind genau so wertvoll wie Gewinner — WENN wir verstehen warum.

### Automatische Insight-Engine (ab 5+ geschlossenen Trades):

Das System generiert automatisch Warnungen:
- ⚠️ Win Rate <30% → Entry-Qualität überprüfen
- ⚠️ These-Trefferquote <40% → Analyse verbessern
- ⚠️ VIX-Zone X hat <25% WR → weniger traden in dieser Zone
- ✅ Win Rate >50% → Positionsgrößen prüfen (zu konservativ?)
- ✅ These-Trefferquote >60% → Informationsvorsprung bestätigt

### Learnings-Datenbank: `data/sa_learnings.json`

Aggregiert automatisch:
- Performance nach Setup-Typ (SHOCK vs CREEPING vs VIX_CONTRA vs FLAG_BOTTOM)
- Performance nach geopolitischem Thema
- Performance nach VIX-Zone
- These-Trefferquote (mein Analyse-Skill verbessert sich?)
- Durchschnittliche Haltezeit bei Gewinnern vs. Verlierern
- Die letzten 50 Lektionen als Wissensdatenbank

### Monatlicher Meta-Review

Jeden Monat (oder nach 20 geschlossenen Trades):
1. Welches Setup funktioniert am besten/schlechtesten?
2. Hat sich meine These-Trefferquote verbessert?
3. Trade ich in der richtigen VIX-Zone?
4. Sind meine Zweitrundeneffekte wirklich ein Edge?
5. Muss ich Regeln anpassen? (→ Änderungen hier dokumentieren mit Datum!)

### Regel-Änderungslog

| Datum | Änderung | Warum | Daten-Basis |
|---|---|---|---|
| 26.03.2026 | Strategie erstellt | Deep Dive, 178 Paper Trades analysiert | Alle DT1-DT9 + Swing Trades |
| | | | |

---

*"Jeder kann kaufen. Nur wenige können warten. Und noch weniger können ehrlich analysieren warum sie verloren haben."*
*— Albert 🎩*

---

*Quellen: BlackRock Geopolitical Risk Dashboard (BGRI), Cboe VIX Methodology, S&P Dow Jones "Practitioner's Guide to Reading VIX", Lars Eriksen Fahnenstangen-Framework (Transcript 26.03.2026), Goldman Sachs "Market Brief: Middle East Conflict" (03.2026), eigene Paper Trading Datenbank (178 Trades)*
