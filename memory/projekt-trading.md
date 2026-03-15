# Projekt: Trading

**Angelegt:** 2026-03-04 | **Zuletzt aktualisiert:** 2026-03-13 22:00
**Broker:** Trade Republic (alle Kurse in EUR, Lang & Schwarz Exchange)
**Status:** AKTIV 🟢

---

## 📐 Anzeigeregeln (STANDING INSTRUCTIONS)

- **Preise immer in €** — keine USD, GBp, NOK etc. im Output an Victor
- Umrechnung intern erledigen (÷ EURUSD, ÷ EURNOK, GBp × GBPEUR ÷ 100)
- Ticker in Klammern zur Identifikation okay, aber Kurs = immer €

---

## 🤖 Alberts autonome Pflichten (STANDING INSTRUCTIONS)

**Festgelegt: 10.03.2026 von Victor**

Bei jedem Morgen-Briefing und bei jedem relevanten Check:

1. **Eigenständig Nachrichten suchen** (Google News RSS, web_fetch) zu:
   - Geopolitik: Iran, Israel, Hormuz, Saudi-Arabien, Trump-Statements
   - Ölpreis-Bewegungen und -Treiber
   - Portfolio-relevante Stocks (RHM, PLTR, NVDA, etc.)
   - Makro: Fed, VIX, Nasdaq-Sentiment

2. **Strategie ableiten** — nicht nur Daten präsentieren, sondern:
   - These bestätigt / erschüttert / neutral?
   - Stops gefährdet?
   - Handlungsbedarf ja/nein?
   - Konkrete Empfehlung (halten / Stop anpassen / verkaufen / nachkaufen)

3. **Eigeninitiative**: Wenn Lage es erfordert (Kursbewegung ≥3%, breaking news, Stop-Gefährdung) → Victor unaufgefordert kontaktieren, nicht auf nächsten geplanten Check warten.

**Victor fragt nicht nach diesen Infos — Albert liefert sie proaktiv.**

---

## 🧠 Trading-Philosophie (Dirk 7H / Tradermacher)

- **Stil:** Swing Trading — Haltedauer Tage bis Wochen
- **Ansatz:** Fundamental + Volumen + Charttechnik kombiniert
- **Marktumfeld immer zuerst checken** — Nasdaq Rückenwind oder Gegenwind?
- Kein blindes Kaufen — auf Setups warten, Rückläufe bevorzugen
- Gewinne laufen lassen, Verluste begrenzen (Stops konsequent setzen)
- "Winning Horses never get back to the box" — starke Aktien zeigen sich früh

### EMA-Stärke-Hierarchie (Dirk 7H, gelernt 12.03.2026)
Je kleiner der EMA an dem eine Aktie Unterstützung findet, desto stärker ist sie im aktuellen Zyklus:
- **EMA-20** = stärkste Aktien → erste Ausbrecher wenn Bullenmarkt startet
- **EMA-50** = mittlere Stärke → zweite Welle der Ausbrüche
- **EMA-200** = schwächere Aktien aktuell → letzte Welle, aber Charlie Munger Methode: Qualitätswerte an EMA200 kaufen = langfristig Markt schlagen

**Praktische Anwendung:**
- Wenn Bullenmarkt startet: zuerst EMA-20-Aktien kaufen, dann EMA-50, dann EMA-200
- EMA-200-Aktien brauchen mehr Geduld, aber besseres CRV bei Qualitätstiteln
- Signal für Bullenmarkt: Nasdaq 50-Tagelinie durchbrochen → dann Risiko erhöhen

### Parabolik-Warnung & Mean Reversion (Dirk 7H, gelernt 12.03.2026)
- Parabolischer Kursanstieg (stark von EMAs entfernt) = Gummiband-Effekt
- Je weiter weg vom EMA, desto schärfer die Rückkehr (Mean Reversion)
- Parallele: Silber parabolisch → scharfer Absturz
- **Regel:** Nie in parabolischen Anstieg einsteigen (Rohstoffe, WTI etc.)
- **Wer schon drin ist:** Teilgewinne sichern (z.B. 1/3 raus, Rest laufen lassen mit Trailing Stop)
- Short-Strategie: Dirk shortet in fallende EMAs hinein (nicht wenn Unterstützung gerissen wird)

### Relative Stärke-Hierarchie (Dirk 7H, März 2026)
**Je kürzer der EMA der als Support hält, desto stärker die Aktie:**
- 🏆 **20-Tage-Linie:** Stärkste Aktien (z.B. Tief/DJT) — brechen zuerst zu neuen Highs
- 💪 **50-Tage-Linie:** Mittlere Stärke (z.B. Intel, Nebius) — gute Swing-Setups
- ✅ **200-Tage-Linie:** Basis-Qualitätsaktien (z.B. NVDA, AMD, Broadcom) — Charlie Munger Zone
→ Im beginnenden Bullenmarkt: erst 20er brechen aus, dann 50er, dann 200er. Reihenfolge zeigt Marktrotation.

### 200-Tage-Linie Strategie (Charlie Munger / Dirk 7H)
**Kern:** Qualitativ hochwertige Aktien an der 200-Tage-Linie kaufen → schlägt S&P 500 langfristig
- Einstieg NUR nach Konsolidierung + Umkehrsignal (keine fallenden Messer kaufen)
- 50-Tage-Linie Durchbruch = erstes starkes bullisches Bestätigungssignal → erst dann Risiko erhöhen
- Bis dahin: Geduld, enger Stop, kleine Position oder Cash
- Dirk bei 100% Cash bis Nasdaq über 50-Tage-Linie (Stand: März 2026)

### Öl / Rohstoffe: Parabolik-Warnung (Dirk 7H, März 2026)
**Parabolische Anstiege enden in Mean Reversion** (Gummiband-Effekt):
- Wenn WTI mit täglichen Gap-Ups steigt + immer weiter von MAs entfernt → Vorsicht
- Referenz: Silber 2011 (parabolisch → Crash)
- **Konsequenz für Positionen:** Wenn bereits drin → 1/3 Teilgewinn nehmen, Rest laufen lassen
- **Neu einsteigen bei Parabolik:** NEIN. Lieber Oil Services (Halliburton etc.) in bullischer Konsolidierung
- **Dirk's Short-Strategie bei Öl:** Nicht auf Ausbrüche shorten, sondern in fallende gleitende Durchschnitte shorten (Short im Abwärtstrend = Gegenteil zu Long im Aufwärtstrend)

---

## 📐 Strategien

### 1. High Volume Breakout ("Winning Horses")
**Wann:** Aktie bricht mit außergewöhnlichem Volumen nach oben aus (>2x Durchschnitt) nach klarem Katalysator (Earnings, News)

**Scan-Kriterien (vorbörslich ab 15:00 Uhr):**
- Gap >5% nach oben
- Relatives Volumen ≥2x Durchschnitt
- Klarer fundamentaler Katalysator (Earnings Beat, strukturelle News)
- Aktie stärker als Nasdaq (relative Stärke)
- Marktumfeld: kein extremer Gegenwind

**Einstieg A — Opening Range High (aggressiv, ~20% Trefferquote):**
- Erste 5-Min-Kerze nach 15:30 Uhr abwarten
- Einstieg wenn Hoch dieser Kerze überschritten wird
- Stop: unter Tagestief

**Einstieg B — High Volume Edge / HVE (Standard):**
- Hoch des Tages mit höchstem Volumen markieren
- Einstieg wenn Folgekerze dieses HVE überschreitet
- Stop: unter Tief der Ausbruchskerze

**Einstieg C — EMA-10 Rücklauf (bestes R/R, geduldig):**
- Nach Ausbruch: Rücklauf zur 10-Tage-EMA abwarten
- Konsolidierung an EMA + erneuter Ausbruch über HVE = Einstieg
- Stop: unter EMA-10 oder lokales Rücklauf-Tief
- Variante "EMA Catchup": starke Aktien laufen seitwärts bis EMA aufholt

---

### 2. Earnings Trade — Fishhook / High Volume Close (HVC)
**Wann:** Nach starken Earnings-Überraschungen (Beat auf Umsatz + EPS + Guidance)

**Setup-Erkennung:**
- Aktie reagiert nachbörslich stark nach oben
- Analyst-Upgrades folgen am nächsten Morgen
- Nasdaq-Umfeld stabil

**Einstieg A — Fishhook (konservativ):**
- Ersten Handelstag nach Earnings abwarten
- Einstieg wenn Hoch des Earnings-Reaktionstages überschritten wird
- Stop: unter Tief des Tages, an dem Ausbruchskerze startete

**Einstieg B — Rücklauf auf Eröffnungskurs:**
- Wenn Markt intraday Schwäche zeigt → Aktie fällt auf Eröffnungskurs zurück
- Einstieg bei Stabilisierung + Erholung, Stop eng unter Rücklauf-Tief
- Bestes R/R bei volatilen Märkten

**Einstieg C — Rundes Level:**
- Wichtigen Widerstand identifizieren
- Ausbruch darüber mit Volumen = Einstieg, Stop unter Tagestief

**Peer-Plays beachten:** Starke Earnings eines Sektorführers → ETF + Konkurrenten prüfen

---

### 3. Intraday Rücklauf-Entry ("Nerven behalten")
**Wann:** Starke Aktie im Uptrend erleidet Intraday-Schwäche durch Marktdruck

**Ablauf:**
1. Aktie ist ausgebrochen / in starkem Aufwärtstrend
2. Intraday-Einbruch kommt → Stops laufen lassen, **keine Panik**
3. Im 10-Min-Chart: Kurs landet auf EMA-10/20, erste Erholungskerze bildet sich
4. Einstieg wenn nächste Kerze das Hoch der Erholungskerze überschreitet
5. Stop: direkt unter Intraday-Tief (~1,5% Risiko)
6. Tageschart: Rücklauf zur 10/20-Tage-Linie = klassischer Nachkauf-Punkt

**Gilt für:** DR0.DE, EQNR, XOM, NVDA (nach Earnings), starke Halbleiter-Werte

---

### 4. Support & Resistance Zonen (Kontextwissen)
**Einsatz:** Nicht als eigenständige Scalping-Strategie, sondern als Kontext für Swing Trades

- Hohe Zeiteinheit (D1/W) → große S&R-Zonen identifizieren
- TradingView Indikator: "SR Channel" (kostenlos) automatisiert die Suche
- Zonen als Referenz für Stop-Placement und Zielbereiche nutzen
- Stop ÜBER Widerstandszone setzen (nicht zu eng — Stop-Fishing vermeiden)
- Zonen wo Kurs in Vergangenheit mehrfach gedreht hat = höhere Zuverlässigkeit

---

## 🔒 Trailing Stop Regeln

**Wann:** Nur im **täglichen 16:00-Abend-Report** — anhand abgeschlossener Tageskerze entscheiden. Kein intraday Nachzug.

**Stufe 1 — Breakeven sichern (ab +5% Gewinn):**
- Stop auf Einstiegskurs (Breakeven) nachziehen
- Oder knapp darüber (letztes Tagestief über Entry)

**Stufe 2 — Gewinne schützen (ab +10% Gewinn):**
- Stop auf 50% des bisherigen Gewinns nachziehen
- Beispiel: Entry 100€, Kurs 110€ → Stop auf ~105€

**Stufe 3 — Near Target (innerhalb 5% vom Ziel):**
- Stop auf letztes markantes Swing-Low (Tageschart) eng nachziehen

**Grundprinzip:**
- Stop NIEMALS nach unten verschieben
- Orientierung: Breakeven → EMA-10 (Tageschart) → Swing-Lows
- Konkreten neuen Level + Begründung anhand Tagesverlauf nennen

---

## 📊 Aktive Positionen

**Format:** NAME (TICKER): Kurs | Entry | P&L: +X€ (+X%) | Stop → Abstand

---

### Nvidia (NVDA)
- **WKN:** 918422 | **ISIN:** US67066G1040
- **Einstieg:** 25.02.2026 @ 167,88€ (~195,50$)
- **Stop:** keiner — Halte-Strategie bis Earnings
- **Ziel:** Quartalszahlen Q1 FY2027 → **27.05.2026** abwarten
- **Fundamentals:** EPS 2027e: 9,04€ | KGV 17,2x | PEG 0,32
- **Trade-Logik:** AI-GPU Marktführer (Blackwell), strukturelle Unterbewertung relativ zum Wachstum
- **Status:** HALTEN 📌

**Q4 FY2026 Earnings (05.03.2026) — RUNDUM BEAT:**
- Umsatz: $68,1 Mrd (+73% YoY) vs $65,9 Mrd erwartet ✅
- Rechenzentrum: $62,3 Mrd (+75% YoY) ✅
- EPS bereinigt: $1,62 (+82%) vs $1,57 erwartet ✅
- Bruttomarge: 75,2% ✅
- Q1 FY2027 Guidance: $78 Mrd vs $72,8 Mrd erwartet ✅ MASSIVES BEAT
- Goldman Sachs Upgrade: Kaufen, Ziel $250

**🎯 Zwei-Stufen-Nachkauf-Plan (vereinbart 06.03.2026):**
- **Stufe 1 (bevorzugt):** Kurs fällt auf $178–180 + Umkehrkerze → Nachkaufen, Stop unter $175
- **Stufe 2 (konservativ):** Schlusskurs über $190 mit Volumen >220M → kleiner Nachkauf
- → Albert meldet SOFORT bei Stufe 1 (unter $180) und Stufe 2 (über $190 mit Vol)

**Wichtige Levels:**
- Support: $177–180 (letztes Korrekturtief)
- Widerstand: $193–197 (30T-Hoch)
- Fishhook-Level: $203,50 (Earnings-Hoch nachbörslich)
- Goldman-Ziel: $250

---

### Microsoft (MSFT)
- **Einstieg:** 04.03.2026 @ 351,85€ (~408$)
- **Stop:** 338,00€ (~395$)
- **Ziel 1:** 387€ (~450$) | **Ziel 2:** 404€ (~470$)
- **Schlüssellevel:** 355€ (~412$ muss gehalten werden)
- **Status:** HALTEN

---

### Palantir (PLTR)
- **Einstieg:** 04.03.2026 @ 132,11€ (~153$)
- **Stop:** ~~109,00€~~ → **127,00€** ← nachgezogen 09.03.2026
- **Ziel 1:** 159€ (~185$) | **Ziel 2:** ATH
- **Schlüssellevel:** 138€ (~160$ = 50-Tage-Linie)
- **Status:** HALTEN

---

### Rheinmetall AG (RHM.DE) — NEU 🟢 12.03.2026
- **Einstieg:** 12.03.2026 @ **1.570€** (kleine Position, Option aufzustocken)
- **Stop:** **1.520€** ← REAL in TR setzen! (Lektion 11.03. — kein mentaler Stop)
- **Ziel 1:** 1.750€ (+11,5%) | **Ziel 2:** 1.900€ (+21%)
- **CRV:** 3,6:1 ✅
- **Aufstocken:** bei Bestätigung über 1.626€ (EMA-10/Signal A)
- **Trade-Logik:** Earnings-Abverkauf beendet, Rüstungs-Thesis intakt (langer Konflikt), Umkehrkerze nach +3% Intraday-Move, dann Stabilisierung über 1.550€
- **Status:** 🟢 AKTIV

### Rheinmetall AG (RHM.DE) — GESCHLOSSEN 🔴 11.03.2026
- **Einstieg:** 09.03.2026 @ **1.635€** (halbe Größe, VIX 32)
- **Ausstieg:** 11.03.2026 @ **~1.563€** (Abverkauf unter Support 1.562€)
- **Realisierter Verlust:** ~-72€/Aktie (-4,4%)
- **Grund:** Stop 1.595€ (mental) unterschritten am 11.03. Seitwärtsbewegung bei 1.574-1.586€, dann weiterer Abverkauf unter 1.562€ (Support) → Position geschlossen nach Dirks Regel
- **Lektion:** Stop MUSS real in TR gesetzt werden — Mental Stops werden nicht respektiert wenn Markt schnell dreht
- **→ WATCHLIST: Wiedereinsteig wenn Setup stimmt (siehe unten)**

---

### Rio Tinto (RIO.L) — NEU ✅ 09.03.2026
- **WKN:** 852147 | **ISIN:** GB0007188757
- **Kursreferenz:** Trade Republic (EUR) | Yahoo Finance RIO.L (GBp)
- **Einstieg:** 09.03.2026 @ **76,92€** (Trade Republic, ~18:39 Uhr)
- **Katalysator:** Dirk 7H kauft heute ebenfalls eine Tranche. Rohstoff-Superzyklus + Kupfer/Lithium-Transformation. VIX-Spike antizyklisch.
- **Stop:** kein fester Stop in TR — Victor beobachtet manuell (Stand 10.03.2026)
- **Ziel 1:** 85,00€ (+10,5%) — 8-Wochen-Hoch-Zone
- **Ziel 2:** 95,00€ (+23,5%) — Rohstoff-Superzyklus Ziel
- **CRV:** Ziel 1: 2.1:1 | Ziel 2: 4.7:1 ⭐⭐
- **Cron-Alert:** Aktiv (alle 15 Min)
- **Mittwoch:** Dirk veröffentlicht 2 weitere Käufe → abgleichen!
- **Status:** 🟢 AKTIV

---

### Equinor (EQNR)
- **Einstieg:** 04.03.2026 @ 27,04€ (Xetra)
- **Kursquelle:** EQNR.OL (NOK) ÷ EURNOK=X
- **Stop:** **28,50€** ← nachgezogen 15.03.2026 (Kurs 30,39€, +12,4% Gewinn → Dirk-Regel: >10% = 50% Gewinn sichern)
- Vorher: 27,00€ (12.03.) → 25,00€ (10.03.) → 28,50€ (09.03.) → initial
- **Ziel 1:** ~~29,50€~~ ✅ ERREICHT | **Ziel 2:** 31–32€ (+15-18%)
- **Trade-Logik:** Geopolitik Öl/Gas (Iran-Eskalation + Hormuz-Blockade) — Nordsee-Leichtöl EQNR ist einzigartige Prämie-Profiteur
- **Status:** HALTEN — Stop 28,50€ sichert 1,46€/Aktie Gewinn. Ziel 2 (31-32€) im Blick. Iran-These 🟢🔥

---

### Bayer (BAYN.DE) — NEU 🟢 10.03.2026
- **Einstieg:** 10.03.2026 @ **39,95€**
- **Stop:** **38,00€** ✅ real in TR gesetzt (10.03.2026)
- **Ziel 1:** 44€ | **Ziel 2:** 46€
- **Katalysator:** Roundup-Settlement / Ausbruch über 39,50€ bestätigt
- **Status:** HALTEN

---

### Deutsche Rohstoff AG (DR0.DE) — GESCHLOSSEN 🔴 10.03.2026 (Trade 1)
- **Einstieg:** 04.03.2026 @ 76,35€ | **Ausstieg:** 10.03.2026 @ ~77,00€ (Stop)
- **Gewinn:** ~+0,85% | **Lessons:** Stops waren mental → Lektion 1

### Deutsche Rohstoff AG (DR0.DE) — GESCHLOSSEN 🔴 10.03.2026 (Trade 2)
- **Einstieg:** 10.03.2026 @ **82,15€**
- **Ausstieg:** 10.03.2026 @ **~79,00€** (Stop ausgelöst) ← genauen Ausführungspreis bestätigen
- **Realisierter Verlust:** ~-3,15€/Aktie (-3,8%)
- **Haltedauer:** ~3 Stunden
- **Lessons:** Stop hat funktioniert ✅ — Lektion 1 korrekt angewendet. Einstieg war gegen Dirks Öl-Warnung (parabolisch). Timing ungünstig — Hormuz-Falschinformation löste Crash aus.
- **→ WATCHLIST: Kein Re-Entry bis Öl-Thesis klarer**

---

## 👀 Watchlist

### Deutsche Rohstoff AG (DR0.DE) — ✅ Re-Entry erfolgt (→ aktive Position)

### First Majestic Silver (AG)
- **Entry A:** 26–29$ (antizyklisch) | **Entry B:** Ausbruch >30$ (Schlusskurs)
- **Stop nach Kauf:** <23$
- **Ziel 1:** 32$ | **Ziel 2:** 38–42$
- **Status:** WATCHLIST — Setup abwarten

### Silber ETC (ISPA.DE)
- **Entry:** Ausbruch über 36,90€ ODER Rücksetzer auf 35,80€
- **Stop:** unter 34,50€
- **Ziel 1:** 38–39€ | **Ziel 2:** 40–42€
- **Katalysator:** Gold-Bullenmarkt zieht Silber zeitversetzt mit
- **Status:** WATCHLIST — auf Ausbruch warten

### Bayer (BAYN.DE) — ✅ AKTIV (→ Aktive Positionen)
- Gekauft 10.03.2026 @ 39,95€ | Stop 38,00€ ✅ in TR | Ziel 1: 44€ | Ziel 2: 46€
- Vollständige Analyse → siehe Aktive Positionen

### ExxonMobil (XOM) — NEU
- **Kontext:** Dirk 7H hat gekauft — Energie-Sektor, Base-Ausbruch
- **Entry:** Intraday Rücklauf auf EMA-10 abwarten
- **Stop:** unter letztem Intraday-Tief
- **Status:** WATCHLIST — auf Rücklauf-Setup warten

### Valero Energy (VLO) — NEU
- **Kontext:** Stärkste Energie-Aktie der letzten 5 Tage (+11,4%), nur -2% vom 52W-Hoch
- **Entry:** Nächster Hammer-Tief (Rücklauf zur 10-Tage-EMA)
- **Stop:** unter letztem Swing-Low
- **Status:** WATCHLIST — auf Pullback warten

### Vertex Pharmaceuticals (VRTX) — NEU
- **Sektor:** Biotech | **Empfohlen:** 06.03.2026
- **Score:** B — Watchlist
- **Entry A:** Ausbruch >440$ (Schlusskurs + Volumen ≥1,5x Durchschnitt)
- **Entry B:** Rücklauf auf EMA-10 (~410$) + Reversal-Kerze
- **Stop nach Kauf:** unter letztem Swing-Low (~395$)
- **Ziel 1:** 470$ | **Ziel 2:** ~510$ (ATH-Bereich)
- **CRV (Entry B):** ca. 3:1
- **Fundamental:** CF-Monopol (Trikafta), Pipeline in Schmerz/Nierenerkrankungen, EPS-Wachstum ~15% p.a.
- **Trigger:** Markt-Setup + eines der beiden Entry-Levels erreicht
- **Status:** WATCHLIST — Alert bei >440$ oder <415$

### Rheinmetall AG (RHM.DE) — NEU 🟢 12.03.2026

- **Einstieg:** 12.03.2026 @ **1.570€** (kleine Position, Option auf Aufstockung)
- **Stop:** **1.520€** ✅ real in TR gesetzt (12.03.2026, ~13:00)
- **Ziel 1:** 1.750€ | **Ziel 2:** 1.900€
- **CRV:** 3,6:1 ✅
- **Aufstockung wenn:** Kurs hält über 1.550€ + Volumen, ODER Ausbruch >1.626€ (Signal A)
- **Kontext:** Earnings-Abverkauf beendet, Rüstungs-Thesis intakt (langer Iran-Konflikt, NATO-Ausgaben). Signal-B Reversal nach -8% Post-Earnings-Dip.
- **Status:** AKTIV

---

### Rheinmetall AG (RHM.DE) — WATCHLIST 🔔 (Position geschlossen 11.03.2026)
- **Aktuell (06.03.2026):** 1.592,50€ | 52W: 933–2.008€
- **EMA-10:** ~1.626€ | **EMA-20:** ~1.652€
- **Story:** Europas Rüstungs-Champion — NATO-Ausgaben, Bundeswehr, Ukraine. Strukturelles Wachstum über Jahre.
- **Kaufsignal A (konservativ):** Kurs schließt über EMA-10 (1.626€) → Entry 1.630€, Stop 1.520€, Ziel 1 1.750€, Ziel 2 1.900€, CRV ~2:1
- **Kaufsignal B (aggressiv):** Rücklauf auf 1.547–1.580€ + Umkehrkerze → Entry ~1.590€, Stop 1.520€, Ziel 1.750€, CRV 2,1:1
- **Trendbruch:** Unter 1.520€ → NICHT kaufen
- **Cron-Alert:** alle 15 Min Mo-Fr 09:00–17:00 aktiv
- **Status:** 👀 WATCHLIST — Alert aktiv 🔔

### Rio Tinto (RIO.L) — NEU 🔔
- **Ticker London:** RIO.L | **WKN:** 852147 | **ISIN:** GB0007188757
- **Frankfurt:** RIO.DE (in TR verifizieren)
- **Kursreferenz:** Yahoo Finance RIO.L (GBp, live ~09:54 CET) | Onvista: onvista.de/aktien/Rio-Tinto-PLC-Aktie-GB0007188757
- **Analysiert:** 09.03.2026 | **Sektor:** Rohstoffe / Basismetalle

**📖 These:**
Rio Tinto transformiert sich vom reinen Eisenerz-Riesen zum Kupfer/Lithium-Konzern. Langfristig profitiert RIO massiv von der Energiewende (Kupfer für Leitungen, Lithium für Batterien). Kurzfristig stützt der Ölschock den gesamten Rohstoff-Sektor — Inflationserwartungen steigen, Realzinsen sinken, Rohstoffe profitieren. Dividendenanpassung letzte Woche hat Druck erzeugt → mögliche Kaufgelegenheit bei Support.

**📊 Chartlage (Stand 09.03.2026):**
- Aktuell: 6.524 GBp | 52w Hoch: 7.557 GBp | 52w Tief: 4.024 GBp
- 20-Wochen-MA: 6.158 GBp (Kurs drüber ✅ — langfristiger Aufwärtstrend intakt)
- 50-Wochen-MA: 5.202 GBp
- **Kurs genau am 8-Wochen-Tief** → potentielle Support-Zone

**🎯 Einstieg:**

**Entry A — Reversal-Signal (bevorzugt):**
- Bedingung: Tagesschluss **über 6.700 GBp** mit erhöhtem Volumen → bestätigt, dass heutiger Support hält
- Entry: ~6.720 GBp (≈ 77€)
- Stop: 6.350 GBp (≈ 73€) — unter Support
- Ziel 1: 7.000 GBp (≈ 80€) | Ziel 2: 7.350 GBp (≈ 84€)
- **CRV: 1.9:1** ✅

**Entry B — Rücklauf-Setup (bestes CRV):**
- Bedingung: Kurs fällt weiter auf 20-Wochen-MA (6.158 GBp ≈ 71€) + Umkehrkerze auf Wochenbasis
- Entry: ~6.200 GBp (≈ 71€)
- Stop: 5.900 GBp (≈ 68€)
- Ziel 1: 7.000 GBp | Ziel 2: 7.350 GBp
- **CRV: 3.0:1** ⭐ Bevorzugtes Setup

**❌ Nicht einsteigen wenn:**
- Kurs fällt unter 6.350 GBp ohne Reversal-Kerze
- VIX > 30 (aktuell 29,49 — grenzwertig!)
- China kündigt neue Iron-Ore-Restriktionen an

**🔔 Cron-Alert aktiv:** <6.350 GBp (Support gebrochen) | >6.700 GBp (Entry A Signal)
**Status:** 👀 WATCHLIST — Alert aktiv 🔔

---

### BHP Group (BHP.L) — NEU ⚠️
- **Ticker London:** BHP.L | **WKN:** A2N9XE | **ISIN:** GB00BH0P3Z91
- **Frankfurt:** BHP.DE (in TR verifizieren)
- **Kursreferenz:** Yahoo Finance BHP.L (GBp)
- **Analysiert:** 09.03.2026 | **Sektor:** Rohstoffe / Basismetalle

**📖 These:**
BHP ist nach RIO der zweitgrößte Miner der Welt. Die OZ-Minerals-Übernahme macht BHP zum zweitgrößten Kupferproduzenten — langfristig enormer Wachstumstreiber. **Kurzfristiges Risiko:** Eisenerz ist ~60% der Einnahmen, China Trade Restrictions sind heute aktives Thema. BHP ist deshalb riskanter als RIO — erst nach RIO kaufen.

**📊 Chartlage (Stand 09.03.2026):**
- Aktuell: 2.601 GBp | 52w Hoch: 3.088 GBp | 52w Tief: 1.560 GBp
- 20-Wochen-MA: 2.385 GBp (Kurs drüber ✅)
- 8-Wochen-Tief: 2.465 GBp — Kurs fast da
- **Letzte 2 Wochen: Ausverkauf** — aktiver Verkaufsdruck

**🎯 Einstieg:**

**Entry A — Breakout (konservativ):**
- Bedingung: Tagesschluss über **2.700 GBp** + Volumen (bestätigt Boden)
- Entry: ~2.720 GBp (≈ 31€)
- Stop: 2.450 GBp (≈ 28€)
- Ziel 1: 2.900 GBp | Ziel 2: 3.000 GBp
- **CRV: 1.5:1** (knapp — nur wenn starkes Volumen)

**Entry B — Rücklauf auf 20W-MA (bestes Setup):**
- Bedingung: Kurs fällt auf 20-Wochen-MA (2.385 GBp ≈ 27€) + Umkehrkerze + China-Lage klärt sich
- Entry: ~2.400 GBp (≈ 28€)
- Stop: 2.300 GBp (≈ 26€)
- Ziel 1: 2.900 GBp | Ziel 2: 3.088 GBp (52w-Hoch)
- **CRV: 5:1** ⭐⭐ Wenn es so weit fällt, Traum-Setup

**❌ Nicht einsteigen solange:**
- China Iron Ore Restrictions News aktiv (Stand: 09.03.2026 — WARTEN)
- VIX > 30
- Kurs unter 2.450 GBp ohne Reversal

**⚡ Reihenfolge:** BHP erst nach RIO kaufen. RIO hat besseres CRV und weniger China-Risiko.
**🔔 Cron-Alert aktiv:** <2.450 GBp (Support gebrochen) | >2.700 GBp (Entry A Signal)
**Status:** 👀 WATCHLIST — ⚠️ ERHÖHTES RISIKO (China Iron Ore) — Alert aktiv 🔔

---

### Meta (META) — NEU 🔥
- **Dirk 7H Top-Pick (07.03.2026)**
- **Stärke:** Einzige Mag7-Aktie über 50-Tage-Linie
- **Setup:** Power of Three — EMAs (10/20/50) laufen eng zusammen → Ausbruch steht kurz bevor
- **Entry:** Überschreitung des Freitags-Hochs (07.03.2026) mit Volumen
- **Stop:** Freitags-Tief → extrem enges Risiko möglich
- **Katalysator:** Long Konsolidierung seit Anfang 2025, hohes Capex KI, aber relative Stärke vs. Peers
- **Status:** WATCHLIST — Entry Montag beobachten

### EQT Corporation (EQT) — NEU
- **Kontext:** Große Base nahezu fertig — Ausbruchspotenzial
- **Charakter:** Eher Investment (Monate), kein kurzfristiger Zock
- **Entry:** Bestätigter Ausbruch über 63$ mit Volumen
- **Status:** WATCHLIST — Base beobachten

---

## ⛽ Energie-Sektor Makro-Kontext

**WTI Rohöl:** $65 → $81 in 8 Handelstagen (+24%) — Katalysator: US/Israel/Iran-Angriff
**Thesis:** Geopolitische Prämie im Ölpreis — kann schnell drehen (Waffenstillstand = -10%)
**Risiko:** Geopolitik-Trades sind volatil — Stops konsequent einhalten
**Peer-Plays auf NVDA-Earnings:** Semiconductor ETF (SOXX), Micron (MU), Intel (INTC)

---

## 🔄 Monitoring & Alerts

### Kursquellen (Yahoo Finance API)
```python
import urllib.request, json
def fetch(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.load(r)
    meta = d['chart']['result'][0]['meta']
    return meta['regularMarketPrice']

# Ticker-Mapping:
# NVDA, MSFT, PLTR → USD ÷ EURUSD=X
# EQNR.OL → NOK ÷ EURNOK=X
# DR0.DE, ISPA.DE, BAYN.DE → direkt EUR
```

### Aktive Cron-Alerts
| Job | Trigger | Aktion |
|-----|---------|--------|
| DR0.DE Stop | ≤78,00€ (alle 10 Min, Mo-Fr 9-18h) | Sofort melden |
| BAYN.DE Alert | ≥39,50€ oder ≤35,00€ (alle 15 Min) | Sofort melden |
| RHM.DE Alert | ≥1.626€ (EMA-10) oder ≤1.580€ (Rücklauf) (alle 15 Min) | Sofort melden |
| RIO.L Alert | <6.350 GBp (Support) oder >6.700 GBp (Entry A) — alle 15 Min 8-16h | Sofort melden |
| BHP.L Alert | <2.450 GBp (Support) oder >2.700 GBp (Entry A) — alle 15 Min 8-16h | Sofort melden |
| NVDA Stufe 1 | <$180 | Sofort melden: Rücklauf-Zone |
| NVDA Stufe 2 | >$190 + Vol >220M | Sofort melden: Bestätigungs-Entry |
| Strategie-Check | Mo-Fr 11:30 + 14:30 | News vs. Thesis-Playbook — meldet NUR bei Statuswechsel oder kritischer Entwicklung — NEU (09.03.) |
| Morgen-Briefing | Mo-Fr 08:00 | Portfolio + Markt + Aktienempfehlung (geändert 07.03.) |
| Xetra Opening-Check | Mo-Fr 10:00 | 1h nach Xetra-Eröffnung — NEU (07.03.) |
| US Opening-Check | Mo-Fr 16:30 | 1h nach NYSE/NASDAQ-Eröffnung — NEU (07.03.) |
| Abend-Report | Mo-Fr 22:00 | Portfolio + **Trailing Stop Review** (geändert 07.03., vorher 16:00) |
| Tagesabschluss | täglich 23:00 | Tageslog, Learnings, Zusammenfassung |
| Wöchentliche Review | Sa 10:00 | Performance, Hypothesen, Feature-Backlog |
| Wochenend-News-Sammlung | Sa 19:00 | Relevante News fürs Wochenende — NEU (07.03.) |
| Wochenstrategie | So 22:00 | Strategieplanung für die neue Woche — NEU (07.03., vorher 09:00) |
| NVDA Earnings | 26.05.2026 17:00 | Erinnerung: Earnings morgen |

### Melde-Regeln
- **SOFORT melden:** Stop Loss ausgelöst, Stop-Gefährdung (<3% Abstand), Kaufsignal aktiv
- **Abend-Report:** Trailing Stop Review, Tageslog, Watchlist-Status
- **Nie intraday:** Trailing Stop Entscheidungen — immer anhand abgeschlossener Tageskerze

---

## 📅 Empfehlungs-Rotation (Morgen-Briefing)

### Scoring-System
- **SCORE A:** Starkes Setup → Kaufempfehlung mit vollständiger Strategie (Entry, Stop, Ziel, CRV, Größe)
- **SCORE B:** Interessant aber kein Trigger → Watchlist mit konkretem Alert-Level
- **SCORE C:** Kein Setup → überspringen

### Bereits analysierte Sektoren
| Datum | Sektor | Aktie | Score | Ergebnis |
|-------|--------|-------|-------|---------|
| 04.03.2026 | Gold/Rohstoffe | AEM | B | Watchlist, Dip-Entry 220-235$ |
| 04.03.2026 | Rüstung/Europa | RHM.DE | B | Watchlist, Entry 1580-1650€ |
| 04.03.2026 | Rohstoffe/Metall | RIO | B | Momentum, Entry bei Rücksetzer |
| 04.03.2026 | Tech | ORCL | C | Mehr Research nötig |
| 04.03.2026 | Pharma/Defensiv | PFE | B | Nahe Hoch, defensiver Kauf |
| 06.03.2026 | Biotech | VRTX | B | Watchlist, Entry-Trigger: Ausbruch >440$ mit Vol oder Rücklauf auf EMA-10 (~410$) |
| 09.03.2026 | Finanzwerte | JPM | B | Watchlist. Profitiert von Rohstoff-Trading-Boom, hohen Zinsen. Kein Entry bei VIX >25. Alert bei VIX <22 + JPM über EMA-10. |
| 09.03.2026 | Rohstoffe/Miner | RIO.L | B→✅ | **GEKAUFT 09.03.2026 @ 76,92€**. Dirk 7H kauft ebenfalls. Stop 73€. Ziel 85/95€. |
| 09.03.2026 | Rohstoffe/Miner | BHP.L | B | Watchlist. Kupfer-Story, China Iron Ore Risiko aktuell. Erst nach RIO kaufen. Entry A: >2.700 GBp | Entry B: 20W-MA (2.385 GBp). Alert aktiv. |
| 10.03.2026 | Konsumgüter | COST (Costco) | B | Watchlist. Defensive Consumer Staples, Pricing Power, relative Stärke vs. Markt. Entry bei Rücklauf auf EMA-10 oder Ausbruch über letztes Swing-Hoch. Stop: unter EMA-10. Kein Entry solange VIX >25. |
| 11.03.2026 | REITs | PLD (Prologis) | B | Watchlist. Industrielogistik-REIT, Near-Shoring-Trend, KI-Datacenter-Infrastruktur. Entry bei Rücklauf auf EMA-10 oder Ausbruch über $115. Stop: unter EMA-20. Kein Entry solange VIX >22. |

### Nächste Sektoren
Energie → Finanzwerte → Konsumgüter → REITs → Emerging Markets → Halbleiter → Transport/Logistik

---

## 📝 Tageslog

| Datum | NVDA (EUR) | MSFT (EUR) | PLTR (EUR) | EQNR (EUR) | DR0 (EUR) | EUR/USD | Notes |
|-------|-----------|-----------|-----------|-----------|----------|---------|-------|
| 04.03. Kauf | 167,88 | 351,85 | 131,40 | 27,04 | — | 1.1633 | Einstieg MSFT/PLTR/EQNR |
| 04.03. 18:40 | — | 351,59 | 131,77 | 26,78 | — | 1.1633 | EQNR unter Einstieg ⚠️ |
| 05.03. 10:20 | — | 348,15 | 131,62 | 26,38 | 76,35 | 1.1639 | EQNR Stop Sell gesetzt. DR0 Einstieg |
| 05.03. 13:50 | — | 348,71 | 131,83 | 27,02 | 79,00 | 1.1620 | DR0 +3,5% ✅ |
| 05.03. 16:00 | — | 354,07 | 134,57 | 27,46 | 80,20 | 1.1605 | PLTR +6,1% Tag 🚀 |
| 06.03. 08:42 | 157,82 | 353,52 | 131,42 | 27,43 | 80,40 | 1.1614 | NVDA Q4 Earnings Beat. Zwei-Stufen-Plan aktiv. Energie-Thesis bestätigt (Öl $81) |
| 06.03. 09:51 | 157,93 | 353,76 | 131,51 | 27,57 | 80,50 | 1.1609 | Morgen-Briefing. NVDA $183,34 (3,34$ über Stufe-1-Zone). Biotech VRTX auf Watchlist. |
| 06.03. 13:12 | 158,64 | 355,34 | 132,09 | 28,03 | 81,60 | 1.1557 | RHM.DE 1.574,50€ — in Kaufsignal-B-Zone (1.547–1.580€). Umkehrkerze abwarten. MSFT genau am Schlüssellevel 355€. |
| 06.03. 14:12 | 158,50 | 355,04 | 131,99 | 27,89 | 81,70 | 1.1567 | ISPA.DE 35,885€ — fast am Rücksetzer-Entry (35,80€)! RHM.DE 1.578€ — noch in B-Zone. Alles stabil, keine Stops gefährdet. |
| 06.03. 16:00 | 157,47 | 354,95 | 131,78 | 28,26 | 80,50 | 1.1579 | Abend-Report. DR0 +5,44% → Stop-Nachzug Stufe 1 auf 76,35€ (Breakeven). EQNR +4,51% fast Stufe 1. AG -10,86%! Setup beschädigt. ISPA unter Rücklauf-Entry. EUR/NOK: 11,1362 |
| 06.03. 16:42 | 157,10 | 355,72 | 133,75 | 28,46 | 82,30 | 1.1582 | DR0 Stop auf 78€ nachgezogen (Kurs 82,30€, +7,79%). Sichert 1,65€ Gewinn. PLTR erholt +1,46%. |
| 07.03. 08:12 | 153,02 | 351,91 | 135,24 | 28,46 | 82,30 | 1.1621 | Samstag — Freitags-Schlusskurse. NVDA $177,82 ⚠️ Stufe-1-Alert (unter $180). EQNR +5,24% (Breakeven-Stufe). Eriksen: Iran kurzer Konflikt wahrscheinlich, Öl ~$90-95 Deckel. Dirk 7H: MSFT nicht auf Kaufliste, Meta Top-Pick (Power of Three). Meta auf Watchlist. |
| 07.03. 23:00 | 153,02 | 351,91 | 135,24 | 28,46 | 82,30 | 1.1621 | Tagesabschluss. VIX 29,49 — Angst-Zone ⚠️. SMH -6,4% (1W), unter EMA50 — kein Tech-Rückenwind. Brent $92,69 (+33% über EMA50 = überdehnt). Kuwait drosselt Förderung (bullisch EQNR/DR0), USA hebt Russland-Ölsanktionen für Indien aus (bearisch mittelfristig). Netto: Iran-Premium bleibt dominanter Faktor. Cron-Zeitplan komplett überarbeitet. News-Infrastruktur (Google RSS + Yahoo Finance) aufgebaut. Neue Phase-1-Dateien angelegt. |
| 08.03. 20:12 | — | — | — | — | — | — | Sonntag — Geopolitik-Intensivtag. Siehe Geopolitik-Strategie-Block unten. |
| 08.03. 23:00 | 153,02 | 351,91 | 135,24 | 28,43 | 82,30 | 1.1621 | Tagesabschluss. Hormuz-Sperrung + US Navy Eskorte (ein Tanker passiert). Venezuela-Ölrückkehr (Trump/Rodríguez) = neuer bearischer Ölpreisfaktor. Wochenstrategie KW11 gespeichert. DR0 fast am Ziel. VIX 29,49 — H005 aktiv. |
| 09.03. 08:00 | 154,01 | 354,08 | 136,07 | 28,47 | 82,30 | 1.1550 | Morgen-Briefing KW11. BAPCO Force Majeure (Bahrain-Raffinerie getroffen). NVDA $177,89 — immer noch in Stufe-1-Zone. DR0 am Ziel (82-84€). Finanzwerte (JPM) Score B. VIX 29,49 🟠. |
| 09.03. 22:00 | 156,93 | 351,76 | 134,40 | 29,17 | 84,00 | 1.1639 | US-Schluss. WTI Shooting-Star: $119 High → $84,84 Schluss (-6,7% vs. Freitag!). VIX 25,50 (von 35,3 High). NVDA +2,68% 🚀. PLTR -0,5%. DR0 AT ZIEL 84€. Stop DR0 → 83,50€. EQNR Stop 28,50€ kritisch (2,3% weg). Ceasefire-Kontakte Iran durch China/RU/FR. Strategie 1 auf 🟡 degradiert. RHM Naval-Akquisition ✅. |
| 10.03. 08:00 | 156,97 | 351,85 | 134,44 | 29,22 | 80,00 | 1.1636 | Morgen-Briefing. ⚠️ DR0 KRITISCH: Onvista 80,00€, Stop war 83,50€ → wahrscheinlich ausgelöst! WTI $89,61 / Brent $93,71 — Erholung. VIX 25,50 🟠. N225 54.248. Trump-PK: Iran-Raketenfähigkeit 90% zerstört, will härter treffen wenn Öl sabotiert. KONSUMGÜTER: Costco (COST) Score B auf Watchlist. |
| 10.03. 22:00 | 159,09 | 349,37 | 130,14 | 27,99 | — | 1.1614 | US-Schluss. WTI $86,74, Brent $87,84. VIX 24,93. QQQ +0,8%. IRAN VERMINT HORMUZ — Trump droht mit "military consequences". US CENTCOM vernichtet 10 iranische Minenlegeschiffe. Strategie 1: 🔴→🟡 (Hormuz-Minen = echte Eskalation). DR0 beide Positionen geschlossen. BAYN.DE (neu) 39,355€, RHM.DE 1.635€, RIO.L 78,97€. EQNR 27,99€ — Stop 25,00€ sicher. |
| 11.03. 08:00 | 158,78 | 348,68 | 129,88 | 28,02 | — | 1.1637 | Morgen-Briefing. Nikkei +1,43%, INPEX +1,96% — Risk-On aus Japan. Nasdaq +1,27%, VIX 24,93 🟡. Iran-Eskalation über Nacht: UAE/Saudi getroffen, US THAAD verlegt, G7-Videokonferenz heute. RHM.DE 1.665€ (+1,8%). BAYN 39,65€ (-0,8%). RIO.L 78,97€ (+2,7%). EQNR 28,02€ (+3,6%). PLTR 129,88€ — nur 2,3% über Stop 127€ ⚠️. REITs-Sektor: Prologis (PLD) Score B. |
| 11.03. 10:00 | 159,16 | 349,52 | 130,19 | 28,18 | — | 1.1609 | Xetra Opening-Check. 🚨 RHM 1.577€ UNTER Mental Stop 1.595€ (−3,5% vs Entry 1.635€) — Earnings bevorstehend, Pre-Earnings-Schwäche. Warte auf Victors Entscheidung. ⚠️ PLTR 130,19€ = nur 2,5% über Stop 127€ (vorbörslich −3,3%). Druckenmiller AI-Verkauf drückt Sentiment. Cargo ship in Hormuz getroffen — EQNR-These intakt. VIX 25,46 🟡. BAYN 39,33€ — 3,4% über Stop, grenzwertig. |
| 11.03. 16:30 | 159,72 | 347,87 | 130,01 | — | — | 1.1578 | US Opening-Check. NDX −0,20%, VIX 25,08 🟡, WTI $86,94 (+4,2%). ⚠️ PLTR 130,01€ — 2,3% über Stop 127€ KRITISCH. ⚠️ MSFT 347,87€ — 2,8% über Stop 338€. NVDA $184,92 — kein Nachkauf-Signal. RHM Jahresbericht: Umsatz/Gewinn ok, Marge enttäuscht → Aktie rot, Position closed ✅. Druckenmiller-Abverkauf AI-Heavy drückt PLTR. |
| 12.03. 22:00 | 159,75 | 350,76 | 131,39 | 28,47 | 79,90 | 1.1629 | Tagesabschluss. **MASSIVE ESKALATION:** Israel startet große Airstrikes direkt auf Teheran + IRGC-Basen. WTI $91,00 (+4,6% intraday). EQNR +5,3% → Stop auf Breakeven (27,00€) nachgezogen ✅. RHM −1% Post-Earnings normal, These bleibt. RIO +3,9% stabil. NVDA −4,8% unter Geopolitik-Druck (VIX 25,1), Hold bis Earnings. **Öl-These bestätigt 🟢 — längerer Konflikt realisiert, kein Deeskalationssignal.** |

---

## 🌍 Geopolitik-Strategie — Iran-Konflikt (Stand: 08.03.2026, 20:12 Uhr)

**Letztes Update:** Täglich aktualisieren wenn neue Eskalationsstufe oder Deeskalationssignal

### Aktuelle Lage (Zusammenfassung Wochenende 07-08.03.)
- Khamenei tot (US/Israel-Angriff Ende Feb)
- Iran hat neuen Obersten Führer gewählt — **Name geheim** (Israel hat gedroht jeden Nachfolger zu töten)
- Israel führt systematische Strikes auf Teherans Öl-Infrastruktur, Munitionsdepots, Basij, innere Sicherheitsstruktur
- Iran feuert täglich Raketen/Drohnen auf Israel, VAE, Saudi-Arabien, Kuwait, Bahrain, Qatar
- **Hormuz-Straße von Iran gesperrt** (bestätigt 08.03., Macron fordert Öffnung)
- US Navy eskortiert Öltanker durch Hormuz
- VAE offiziell im Verteidigungsmodus (17 Raketen + 117 Drohnen abgefangen)
- Israelischer Generalstabschef: "Krieg wird lange dauern"
- Macron telefoniert mit Iran + USA — Frankreich als Vermittler aktiv
- Irans Präsident hat sich entschuldigt (Zeichen von Pragmatismus)

### Szenarien & Wahrscheinlichkeiten (aktualisiert 08.03.)

| Szenario | Wahrscheinlichkeit | Zeithorizont | Öl | Portfolio |
|----------|-------------------|--------------|-----|-----------|
| A) Kurze De-Eskalation (Macron vermittelt, Gesichtswahrung) | ~~40%~~ → **5%** | — | — | PRAKTISCH AUSGESCHLOSSEN |
| B) Mittellanger Konflikt (Hardliner, aber kein totaler Regimesturz) | ~~45%~~ → **50%** | 2-4 Monate | $90-120 | EQNR/DR0 halten, Trailing Stops eng |
| C) Langer Krieg + Regimesturz (Trumps erklärtes Ziel) | ~~15%~~ → **45%** | 6+ Monate | $120-150+ | Energie maximal bullish, Tech crasht |

**Update 09.03.2026 (02:00 Uhr):** Szenario A offiziell tot.
- Mojtaba Khamenei (Hardliner) als neuer Führer bestätigt, IRGC schwört Treue
- Trump: "keine Verhandlungen", "nobody left to surrender" (Air Force One)
- Irans Parlamentssprecher: "kein Waffenstillstand"
- Brent $108,73 (+17% heute, +28% letzte Woche) — Markt preist Szenario B/C ein
- Netanyahu: "organised plan with many surprises to destabilise the regime"

**Venezuela-Faktor (neu 08.03.):** Trump erkennt Rodríguez an → Venezuelan Oil fließt wieder nach Houston (Shell-Deal, Konsularabkommen wiederhergestellt) → bearischer Ölpreisfaktor mittelfristig. Teilweise Gegengewicht zur Iran-Prämie. DR0 + EQNR: Stop-Disziplin noch wichtiger!

### Strategische Schlüsse für Portfolio

**EQNR (Equinor) + DR0.DE (Deutsche Rohstoff AG):**
- Ölpreis wird durch Hormuz-Sperrung + Infrastrukturschäden gestützt
- **Montag Xetra-Eröffnung:** Stop sofort auf Breakeven nachziehen (EQNR: 27,04€ / DR0: 76,35€)
- Ziele bleiben: EQNR 29,50-32€ / DR0 82-84€ (DR0 fast am Ziel!)
- **Exit-Trigger:** Konkretes Waffenstillstandsabkommen ODER Öl fällt >5% in einem Tag ohne News → sofort verkaufen
- Macron-Kanal genau beobachten — wenn Verhandlungen konkret werden → Öl dreht schnell

**Rheinmetall AG (RHM.DE):**
- Langfristiger Krieg = langfristiger Rüstungsbedarf
- "Krieg wird lange dauern" (Israelischer Generalstabschef) = direktes Kaufsignal für Rheinmetall
- Setup: Kurs 1.592,50€, EMA-10 bei 1.625,68€ — Montag genau beobachten
- Gap nach oben wahrscheinlich → Kaufsignal A (>1.626€) könnte Montag früh kommen
- **Stop:** 1.520€ | Ziel 1: 1.750€ | Ziel 2: 1.900€ (nahe 52w Hoch 2.008€)

**Palantir (PLTR):**
- Defense/Intelligence profitiert unabhängig von Konfliktdauer
- Bereits +2,4% im Plus — läuft gut, kein Handlungsbedarf
- PLTR ist der "ruhige Profiteur" — Stop 109€ weit weg

**Nvidia (NVDA):**
- Konflikt = Marktangst = VIX steigt = Tech unter Druck
- Hormuz-Sperrung könnte VIX >30 treiben → negativer Druck auf NVDA
- NVDA bei $177,82 — in STUFE-1-Zone ($177-180) → kein Nachkauf solange VIX hoch
- Halte-Strategie bis Earnings 27.05.2026 bleibt

**Microsoft (MSFT):**
- Geopolitischer Gegenwind für Tech bleibt
- Dirk 7H: "Nicht auf Kaufliste" → bestätigt durch aktuelle Lage
- Breakeven-Position — kein Handlungsbedarf

### Geopolitische Warnsignale (sofort melden wenn eines eintritt)
1. 🟢 **De-Eskalation:** Waffenstillstand / Hormuz öffnet / Iran nimmt Verhandlungsangebot an → EQNR + DR0 Exit prüfen
2. 🔴 **Eskalation:** Isfahan-Angriff (Nuklear) / Hormuz komplett blockiert (Schiffe versenkt) / Iran-Boden-Invasion → Öl $120+, Markt crasht
3. 🟡 **Neuer Akteur:** Türkei, Russland, China mischen sich ein → Komplexität steigt, Unsicherheit nimmt zu
4. ⚡ **Irans neuer Führer bekannt + Hardliner:** Szenario B/C wahrscheinlicher
5. ⚡ **Irans neuer Führer bekannt + Pragmatiker:** Szenario A wahrscheinlicher

---

## 📊 ABEND-REPORT — Freitag 13.03.2026 22:00 (US-Schluss)

### Portfolio-Status (10 Positionen)

| Name (TICKER) | Kurs | P&L | Score | Status | Action |
|---|---|---|---|---|---|
| Nvidia (NVDA) | 157,85€ | -6,0% | -1 | 🟡 NEUTRAL/ABWARTEN | ⚠️ KEIN STOP! |
| Microsoft (MSFT) | 346,40€ | -1,5% | -2,5 | 🔴 VORSICHT/HALTEN | Stop OK (338€) |
| Palantir (PLTR) | 132,19€ | +0,1% | -2,5 | 🔴 VORSICHT/HALTEN | Stop OK (127€) |
| Equinor ASA (EQNR) | 30,40€ | +12,4% | +1,3 | 🟢 NEUTRAL | ⚠️ RSI 79 überkauft! |
| Bayer AG (BAYN.DE) | 38,63€ | -3,3% | -3,3 | 🔴 VORSICHT/HALTEN | ⚠️ Stop 1,7% weg! |
| Rio Tinto (RIO.L) | 77,16€ | +0,3% | +0,5 | 🟡 NEUTRAL/ABWARTEN | Stop OK (73€) |
| Invesco Solar (A2QQ9R) | 25,25€ | +12,7% | -1,8 | 🔴 VORSICHT/HALTEN | 🔴 KEIN STOP! |
| VanEck Oil (A3D42Y) | 26,59€ | -4,7% | +0,5 | 🟡 NEUTRAL/ABWARTEN | Stop OK (24€) |
| L&G Cyber (A14WU5) | 26,46€ | -8,2% | -3,3 | 🔴 VORSICHT/HALTEN | ⚠️ Stop 2,0% weg! |
| iShares Biotech (A2DWAW) | 7,27€ | +3,8% | -1,0 | 🟡 NEUTRAL/ABWARTEN | Stop OK (6,3€) |

### Overnight-Risiken (TEIL 2)

**🔴 KRITISCH:**
- EQNR: +12,4% bullish, aber RSI 79 = starke Überkauftheit. Profit-taking über Wochenende wahrscheinlich.
- A2QQ9R (Solar ETF): KEIN STOP + +12,7% Gewinn + schwaches Volumen = Gap-Down-Falle Montag möglich.
- BAYN.DE: Stop 38€ nur 1,7% weg bei VIX 27.2 (high volatility). ATR= 0,93€, geometrisch zu eng.
- A14WU5 (Cyber): Stop 25,95€ nur 2,0% weg, ähnliches Problem wie BAYN.

**🟡 TECH-SEKTOR UNTER DRUCK:**
- NVDA, MSFT, PLTR alle leicht negativ (-1,5% bis -1,7%)
- Grund: VIX 27.2 (orange band), Geopolitik Iran/Hormuz, Oil shock möglich über Wochenende
- Worst Case: Iran-Eskalation übers Wochenende + Öl spike → Montag-Eröffnung Abverkauf Tech

**🟢 ENERGIE BULLISH:**
- EQNR + RIO.L profitieren von Öl-Szenario B/C (mittelfristig)
- Aber: EQNR überkauft. RIO.L weiterhin konstruktiv (Rohstoff-Generalist).

### News-Faktor (TEIL 5)

**Geopolitik:**
- Iran Hormuz-Sperrchroniká bestätigt (Status: langfristig)
- Mojtaba Khamenei (Hardliner) als neuer Supreme Leader — Szenario B/C (2-6 Monate Konflikt) wahrscheinlicher
- USA/Trump: "keine Verhandlungen"
- Trump erkennt Venezuela-Regierung an → Ölfluss nach Houston steigt → mittelfristiger bearischer Ölfaktor
- Brent noch bei $100,98, aber Tension bleibt hoch

**Portfolio-News:**
- **EQNR:** Share Buyback angekündigt (bullish, aber überlagert durch Überkauftheit RSI)
- **NVDA/MSFT/PLTR:** Keine breaking news, Tech-ETF-Artikel generisch (VIX-getrieben)
- **RIO.L:** Copper plays weiterhin interessant, Bioleaching-Technologie im Fokus
- **BAYN.DE:** "Es geht wieder bergab" (WELT, 12.03.) — bearisch, aber kein neuer Schock

### Stop-Audit (TEIL 4)

**🔴 SOFORT PRÜFEN:**
1. **NVDA**: Kein Stop gesetzt! Entry 167,88€, aktuell 157,85€ (-6%). Vorschlag: 2×ATR = 151,23€ oder fester 153€ (-8,9%)
2. **A2QQ9R (Solar ETF)**: Kein Stop! Aktuell 25,25€ (+12,7%), Vorschlag: 23,00€ (-8,9%)
3. **BAYN.DE**: Stop 38,00€ zu eng (1,7%), Vorschlag: 36,50€ (-5,5%)
4. **A14WU5 (Cyber)**: Stop 25,95€ zu eng (2,0%), Vorschlag: 25,00€ (-5,5%) oder 24,50€ (-7,0%)
5. **EQNR**: Stop 27,00€ = Breakeven. Bei Überkauftheit: Nachziehen auf 29,00€ (Gewinn sichern) oder 30,00€ (50% Gewinn sichern)?

**Trailing Stop Logic (TEIL 4):**
- EQNR: +12,4% → Stop auf 50% Gewinn = 26,35€ (Entry 27,04€ + 6,2% = 28,71€ Ziel) — zu konservativ?
- A2QQ9R: +12,7% → Stop auf Breakeven minimum, besser 8-10% unter aktuell = 23€

### Strategien-Status (S1-S7)

- **S1 (Iran/Öl):** 🟡 Bestätigt aber gefährlich überkauft. EQNR/RIO.L halten, aber Gewinne realisieren in Tranchen.
- **S3 (KI-Infrastruktur):** 🔴 Unter Druck (NVDA -6%, MSFT -1,5%, PLTR +0,1%). VIX-getrieben, kein fundamentales Bruchs. HALTEN bis S.
- **S5 (Rohstoffe/Industrie):** 🟡 RIO.L stabil, aber schwach voluminös. EQNR bricht aus, aber Überkauftheit.
- **Übrige:** Neutral oder data-schwach (keine Signale).

### Handlungsempfehlungen (für Montag früh)

1. **NVDA + A2QQ9R:** Stops SOFORT setzen — kein Wochenende ohne Sicherung.
2. **EQNR:** Tranchen-Gewinnmitnahme prüfen (50% Position @ 31€, 25% @ 32€?).
3. **BAYN.DE + A14WU5:** Stops nachziehen um 3-5% zur Reduktion von Whipsaw-Risiko.
4. **Iran-Lage:** Über Wochenende monitoren. Wenn Eskalationssignal (Isfahan-Angriff, Hormuz-Blockade verschärft) → sofort melden.
5. **Montag-Planung:** VIX-Druck abwarten bis 10:00 Xetra-Eröffnung, dann Stops final adjustten.

### Learnings aus dieser Session
- **Stops müssen physisch gesetzt sein BEVOR Weekend/Volatility.** NVDA + A2QQ9R sind rote Flaggen.
- **ETFs (A2QQ9R, A3D42Y, A14WU5, A2DWAW)** brauchen aggressivere Stops als einzelne Aktien — Volumen-Variabilität ist höher.
- **VIX 27+ = Tech-Druck.** Geopolitik = Öl-Play interessant, aber Tech-Portfolio sollte defensiver werden.
- **Überkauftheit (RSI >75) + Wochenende = sehr gefährlich.** EQNR-Beispiel: +12,4% in 5 Tagen, RSI 79 — Profit-taking ist mathematisch wahrscheinlich.

---

## Woche 11/2026 — Freitag 13.03 (21:00 UTC)

### Markt-Snapshot
- VIX: 27.2 (volatil) — Geopolitik bleibt der Haupttreiber
- Tech: Schwach (MSFT/NVDA/PLTR rot oder neutral)
- Oil/Energie: Stark (EQNR +12.4%, A3D42Y Oil Services bullish)

### Portfolio-Status
| Ticker | Pos | P&L | Signal | Aktion |
|--------|-----|-----|--------|--------|
| EQNR | LONG | +12.4% | 🟢 Trend OK | HALTEN |
| MSFT | LONG | -1.5% | 🔴 Downtrend | VORSICHT/SELL |
| BAYN.DE | LONG | -3.3% | 🔴 Tightstop | REDUZIEREN |
| A2QQ9R | LONG | +12.7% | ⚠️ NO STOP | SET STOP 24€ |
| Andere | MIXED | ±5% | 🟡 Neutral | WATCH |

### Kritische Erkenntnisse

**1. Stop-Management bleibt KEY-Schwachstelle**
- A2QQ9R war +12.7% OHNE STOP — das ist fahrlässig
- Lesson: Automatisches Stop-Setting für alle Neupositionen?
- Action: Tradingtool muss jeden Entry mit Stop-Rule initialisieren

**2. Volumen-Filter funktioniert**
- BAYN.DE (0.4× Volumen) → Stop 1.7% zu eng → Gap-Risiko = real
- A14WU5 (0.3× Volumen) → gleiches Problem
- Lesson: Illiquid = nur größere Stops oder nicht anfassen

**3. VIX-Regime bestätigt**
- VIX 27.2 = volatil → S2 (Trend Following) best performer (EQNR)
- Mean-Reversion Plays (S1) tot → RSI-bounce Szenarios funktionieren nicht
- Lesson: Regelwerk nach VIX-Regime adaptieren

**4. Geopolitik wirkt**
- Ukraine + Iran = Ölpreis Ballast entfernt (über 100$/bbl)
- EQNR "no spare capacity" Quote Bullish
- Lesson: Newsfeed mit Geopolitik-Weight erhöhen

### To-Do für Tradingtool v2
- [ ] Auto-Stop-Setting für neue Long-Positionen (Entry + 2×ATR/2%min)
- [ ] Volumen-Liquidity-Score in Trade-Gating (vetoable < 0.5×)
- [ ] VIX-Regime-Switching für S1/S2 Gewichtung
- [ ] Geopolitik-News-Feed Integration (Iran, Ukraine, Russia-Sanktionen)
- [ ] Overnight-Gap-Risiko-Score bei Freitag-Closes

