# Transcript Insights — Extrahierte Methodik

> Nur Methodik + Frameworks. Keine Marktmeinungen, keine Kursziele ohne Begründung.

---

## Dirk 7H — 24.03.2026 — Aktives Warten + Relative Stärke + Position Entry

*Quelle: Tradermacher Video, Dienstag 24.03.2026*

### Kern-Erkenntnisse

**"Aktives Warten" als Regime-Strategie**
- In unsicheren Märkten NICHT voll investieren, aber auch NICHT komplett raus
- "Fuß ins Wasser halten" — kleine Positionen, schnell raus wenn's nicht funktioniert
- Langsam in den Markt kommen, nicht 3 Aktien gleichzeitig ins Risiko
- TradeMind: Regime "CORRECTION/VOLATILE" → automatisch Positionsgrößen reduzieren, Anzahl offener Trades limitieren

**Relative Stärke — Simpel ohne Indikator**
- Methode: Die letzten 3 Tiefs des Index anschauen (tiefere Tiefs?)
- Dann Aktie vergleichen: Macht die Aktie HÖHERE Tiefs während der Index TIEFERE Tiefs macht?
- Wenn ja → echte relative Stärke, Kaufkandidat
- Beispiel: Nasdaq 3x tieferes Tief, Nebius 3x höheres Tief → Top-Kandidat
- TradeMind: "Tief-Vergleich-Score" — automatisch letzte 3 Tiefs von Aktie vs. Index vergleichen

**Öl als inverser Aktienmarkt-Indikator**
- Solange WTI UNTER der 10-Tage-Linie bleibt → positiver Druck auf Aktienmarkt
- WTI ÜBER 10-Tage-Linie → weiterer Druck auf Aktien
- Diese Parallele IMMER im Auge behalten
- TradeMind: WTI vs. EMA10 als Regime-Signal einbauen (bullisch/bärisch für Tech)

**EMA Crossback Pattern**
- Aktie bricht über gleitende Durchschnitte aus → fällt zurück IN die EMAs → bricht wieder aus
- Der Retest des Ausbruchs = zweite Einstiegschance (oft besser als erster Kauf)
- Im Stundenchart: Erster Ausbruch → Retest → Kauf am Retest mit engerem Stop
- TradeMind: EMA Crossback als eigenes Pattern erkennen + alertieren

**Inside Day als Konsolidierungs-Signal**
- Inside Day = Tageskerze komplett innerhalb der Vortageskerze
- In Kombination mit relativer Stärke = bullisches Continuation-Signal
- Mehrere Inside Days nacheinander = Spannung baut sich auf → Ausbruch kommt
- TradeMind: Inside Day Detection + Scoring (Inside Day + RS + Volumen)

**Average Daily Range (ADR) für Positionssizing**
- Applied Opto: ADR 13,22% → extrem volatil
- Wenn so eine Aktie 2 Tage in die richtige Richtung läuft mit 25% Depotanteil → massive Rendite
- Aber: Nur kaufen wenn der Markt STARTET (Follow-Through Day), nicht vorher
- TradeMind: ADR als Faktor für Positionsgröße — hohe ADR = kleinere Position ODER größere Position bei bestätigtem Trend

**15-Minuten-Chart für enge Entries**
- Bei Intraday-Schwäche: Warten bis Kurs die 20-Tage-Linie antestet
- Im 15-Min-Chart einsteigen → engerer Stop möglich → größere Position
- TradeMind: Intraday-Entry-Optimizer — "Warte auf Pullback zum EMA20 im 15min"

**Follow-Through Day als Regime-Wechsel**
- Kann der Markt sich durch die 200-Tage-Linie arbeiten?
- FTD = bestätigter Aufwärtstag mit Volumen nach Korrektur
- Erst NACH FTD aggressiver positionieren
- TradeMind: FTD-Detection als Regime-Switch-Trigger (CORRECTION → RECOVERY)

### Aktien-Watchlist (nur Methodik-relevant, keine Kursziele)
- **Nebius** — EMA Crossback + höhere Tiefs vs. Index = Top RS
- **Palantir (PLTR)** — Seitwärtskonsolidierung am Widerstand, hält bei Markt-Rückfall, überdurchschnittl. Volumen → bullisch (Victor hat Position!)
- **Robinhood Markets (HOOD)** — Boden bei $70, Inside Day, fundamental stark (EPS + Umsatz steigend), Bitcoin-RS als Rückenwind
- **Marvell Technology (MRVL)** — Saubere Flagge, EMA Crossback, Ausbruch über $91
- **Corning (GLW)** — Base-Breakout + Konsolidierung, hält während Markt fällt, Inside Day
- **Applied Opto Electronics (AAOI)** — ADR 13%, höhere Tiefs, High-Tight-Flag Formation, Potenzial $100→$150

### Für TradeMind umsetzen
1. **Tief-Vergleich-Score** — Automatisch letzte 3 Index-Tiefs vs. Aktien-Tiefs vergleichen
2. **WTI/EMA10 als Regime-Signal** — Öl unter EMA10 = bullisch für Tech
3. **EMA Crossback Detection** — Pattern-Scanner
4. **Inside Day + RS Combo** — Scoring-System
5. **ADR-basiertes Positionssizing** — In Conviction-Score einbauen
6. **FTD-Detection** — Regime-Wechsel automatisieren
7. **15-Min Entry Optimizer** — Intraday-Pullback zum EMA20 erkennen

---

## Lars Eriksen — 18.03.2026 — ATH-Szenarien + Scale-Trading
*Quelle: eriksen-athtargets-2026-03-18.txt*

### Kern-Erkenntnisse

**Binäres Denken = Systemischer Fehler**
- Privatanleger denken IN/OUT → kaufen systematisch auf Hochs
- Profis (Druckenmiller, Tudor Jones): Positions-Größe ist Variable, kein Schalter
- Scaling rein/raus = kontinuierliche Steuerung, nicht binäre Entscheidung
- TradeMind: Positions-Sizing als eigenes Steuerungselement, nicht nur Entry/Exit

**Aktiv vs. Passiv = zwei getrennte Buckets — Pflicht**
- Cashquote 50% im aktiven Portfolio ≠ Widerspruch zum langfristigen Portfolio
- Mischen der beiden Logiken = "sicherster Weg zur Underperformance"
- Konsequenz: TradeMind muss Aktiv/Passiv-Trennung erzwingen (kein implizites Mischen)
- Warnung für aktuelles Portfolio: NVDA ohne Stop "bis Earnings" = aktiver Bucket mit passiver Logik

**Sentimentdaten richtig lesen**
- Put/Call Ratio auf 4-Jahres-Hoch ist KEIN direktionales Short-Signal
- Institutionelle Put-Käufe = meist Absicherung bestehender Longs (Covered Puts), keine Wetten
- Rohe Sentiment-Daten ohne Kontext sind irreführend
- TradeMind: Sentiment-Indikator braucht Kontext-Layer (Absicherung vs. direktional)

**Korrelationen: Qualität über Quantität**
- Öl → Aktienmarkt: zu unzuverlässig für operative Entscheidungen
- Bankensektor → Gesamtmarkt: beständiger Indikator ("kein Bullenmarkt korrigiert groß ohne Banken")
- Regel: Nur Korrelationen nutzen die nachweislich über mehrere Marktphasen stabil sind
- TradeMind: Bankensektor-ETF (SX7E oder einzelne Großbanken) als Makro-Indikator

**Makro-Risiken relativieren**
- Absolute Zahlen ($1.2T Private Credit) ohne Verhältnis zum Markt ($224T Fixed Income) sind wertlos
- Bekanntes + lokalisierbares Risiko = kein Dominoeffekt-Risiko (Lehman-Vergleich falsch)
- TradeMind: Makro-Dashboard zeigt Verhältniszahlen, nicht nur Absolutwerte

---

## Lars Eriksen — 20.03.2026 — Rezessionsszenarien + Fed-Zwickmühle
*Quelle: inbound transcript, aufgenommen Donnerstag 20.03.2026*

### Kern-Erkenntnisse

**1-Jahres-Inflationsswap als Fed-Frühindikator**
- Der 1Y-Inflationsswap ist der entscheidende Echtzeitindikator für Fed-Erwartungen
- Unter 2% + Arbeitsmarkt-Schwäche → Fed kann mit gutem Gewissen senken
- Über 2,5–3% → Fed pausiert, egal ob Wachstum leidet
- Aktuell (März 2026): 3,25% → Fed blockiert. Kein Spielraum für Zinssenkungen
- TradeMind: 1Y-Swap als permanenter Dashboard-Indikator neben VIX

**Fed's Zwei-Bedingungen-Modell (duales Mandat)**
- Bedingung A: Inflation erkennbar Richtung 2% fallend
- Bedingung B: Arbeitsmarkt zeigt materielle Schwäche (signalisiert Wachstumseinbruch)
- NUR EINE dieser Bedingungen muss erfüllt sein
- "Materielle Schwäche" ≠ leicht erhöhte Arbeitslosigkeit — muss eindeutig sein
- Aktuell: Arbeitslosigkeit 4,1% (historisch niedrig), Jobless Claims stabil → Bedingung B nicht erfüllt

**"Behind the Curve"-Mechanismus — Das Kern-Dilemma**
- Geldpolitik wirkt mit 12–18 Monaten Verzögerung
- Problem: Fed kann erst reagieren wenn Schaden sichtbar ist → aber Maßnahme wirkt erst 12–18 Monate später
- Besonderes Dilemma jetzt: Wenn Konflikt 2–4 Wochen endet → Zinssenkung wäre falsch gewesen
- Regel: Je kürzer das auslösende Ereignis, desto gefährlicher voreilige Geldpolitik

**Phase 1 → Phase 2 Framework (Makroschock-Eskalation)**
- **Phase 1: Inflationsschock** — noch abwendbar; Fed zwickmühle aber kein struktureller Schaden
- **Phase 2: Wachstumsschock** — Märkte preisen Rezession ein; deutlich schlimmer für Aktien
- Kipppunkt: Wenn hohe Energiepreise >2–3 Monate anhalten → Phase 2 unvermeidlich
- Wir sind aktuell in Phase 1. Phase 2 = S&P mindestens –20–25%
- TradeMind: Phase-1/2-Indikator (Energie-Dauer × Konsumenten-Stress = Rezessionswahrscheinlichkeit)

**Rezessions-Transmissionsmechanismus (vollständige Kette)**
Öl hoch → Inputkosten steigen → Margen sinken → Investitionen gestoppt → Einstellungen gestoppt → Arbeitsmarkt dreht → Fed reagiert (zu spät) → Zinssenkungen wirken erst 12–18 Monate später
- Jeder Schritt hat Zeitverzögerung → Gesamtkette: 3–6 Monate
- Früh-Indikator: Unternehmensinvestitionen und Einstellungspläne (Surveys), nicht erst Jobless Claims

**Konsumenten-Puffer-Analyse (US-spezifisch)**
- Sparquote 2022: 8,4% → jetzt: ~4% (halbiert) → Puffer viel dünner
- Kreditkartenschulden auf Rekordhöhe (~$1,5 Billionen)
- Effekt: Kostenschocks treffen schneller durch als in früheren Zyklen
- Implikation: Wenn Öl >$100, kostet das einen US-Haushalt $150–200/Monat extra
- TradeMind: US-Konsumenten-Stress-Score als vorgelagerter Indikator für Consumer-Discretionary

**Szenario-Zeithorizont-Matrix (Eriksens Framework)**

| Szenario | Bedingung | Ölpreis | Wachstum | Rezession? |
|----------|-----------|---------|----------|-----------|
| De-Eskalation | Konflikt endet <4–5 Wochen | fällt auf 80–85$ | 1,5–1,7% | Nein |
| Milde Rezession | Energiepreise hoch >3 Monate | bleibt >$100 | 2–3 Quartale negativ | Ja (mild) |
| Schwere Rezession | Exportstopp USA oder langanhaltend | unbegrenzt | massive Kontraktion | Ja (schwer, –20–25% Indizes) |

Eriksen: Wahrscheinlichstes Szenario aktuell = De-Eskalation binnen 1–4 Wochen.

**Energie-Exportstopp als Tail-Risk (Mechanik)**
- US produziert 13,5–14M Barrel/Tag, exportiert davon ~4M
- US-Raffinerien ausgelegt auf schweres Öl (Venezuela/Nahost), NICHT leichtes Permian-Öl
- Exportstopp → sofortiger Überschuss den Inlandsnachfrage nicht aufnehmen kann → US-Ölpreis kollabiert
- Produzenten drosseln Förderung → gesamter US-Energie-Capex-Zyklus stoppt
- LNG: US produziert 110 Mrd Kubikfuss/Tag, Inland: 91 Mrd → 19 Mrd Überschuss = LNG-Exporte
- Europa: >90% LNG aus USA → Exportstopp = EU-Energiekrise
- Paradox: Exportstopp schadet den USA selbst schwer → ist deshalb unwahrscheinlich, aber nicht ausgeschlossen

**Edelmetall-Abverkauf als Bodenindikator**
- Wenn Edelmetalle (Gold, Silber) unter breitem Druck fallen, obwohl sie gut gelaufen sind → Zeichen von Positionsliquidierung (Not-Verkäufe)
- Das ist kontra-intuitiv, aber signalisiert: "Wir sind nah an einem Boden"
- Logik: Wer Gewinne realisieren muss, verkauft zuerst was im Plus ist
- TradeMind: Edelmetall-RSI-Divergenz als Markt-Boden-Sensor

**Cash-Quote Management bei Unsicherheit**
- Eriksen-Regel: 50% Cash bei erhöhter Unsicherheit (Geopolitik + VIX erhöht)
- Erhöht Cash weiter wenn Stops ausgelöst werden (kein Nachkaufen in Schwäche ohne klares Signal)
- Gleichzeitig: Schwäche aktiv nutzen für vorbereitete Positionen (Watchlist vorbereitet haben)
- Konsequenz: Cashquote ist aktives Instrument, nicht Fehler

### Bezug zu aktiven Strategien

- **EQNR/Öl-These**: Eriksens wahrscheinlichstes Szenario = De-Eskalation <4 Wochen → Öl auf 80–85$. Bei EQNR Entry 27,04€ und Stop 28,50€: Position ist gut positioniert für sanfte Landung. Aufmerksamkeit bei Deeskalationssignal → Exit-Trigger.
- **NVDA/MSFT/PLTR**: Phase-1/2-Framework direkt anwendbar. Wenn Phase 2 → mindestens –20% → alle Tech-Positionen ohne adequate Stops sind gefährdet. NVDA ohne Stop bleibt kritischste Schwachstelle.
- **BAYN.DE/A14WU5**: Konsumenten-Stress + milde Rezessionsrisiko drückt defensiv auf Consumer/Pharma. Tight stops in diesem Umfeld problematisch (bestätigt Heartbeat-Alert vom 20.03.).

---

## Lars Eriksen — 13.03.2026 — WPR Akkumulierungssignal
*Bereits in MEMORY.md unter "Trading-Wissen aufbauen" dokumentiert*

- WPR (Williams Percentage Range) auf Monatsbasis = seltenes, gewichtiges Signal
- Akkumulierung ≠ Kaufsignal (Kurs kann noch fallen, aber nächste große Bewegung ist aufwärts)
- Tranchenkauf: 3 Stufen vordefinieren, keine Improvisation
- Rollende Korrelation prüfen bevor man Markt-Ableitungen zieht

---
*Letzte Aktualisierung: 19.03.2026*

## 2026-03-22 — Dirk 7H / Tradermacher: 3 Kardinalsfehler im Trading

**Quelle:** René Berheit (Tradermacher), wöchentliches Video
**Archiv:** memory/transcripts/dirk7h-kardinalsfehler-2026-03-22.txt

### Fehler 1: Hohe Trefferquote → sinkendes Konto (Asymmetrisches Verhältnis)
- 60–70% Trefferquote aber Konto schrumpft = Gewinne zu früh mitgenommen, Verluste laufen gelassen
- Psychologischer Mechanismus: Trader will "recht haben" statt Profit machen
- **Diagnose-Tool:** Average Win vs. Average Loss tracken. Wenn Avg Loss > Avg Win → Problem
- **Regel:** Avg Win muss größer sein als Avg Loss. Trefferquote ist sekundär.
- Relevanz für TradeMind: Conviction-Score allein reicht nicht — Win/Loss-Ratio ist der kritische KPI

### Fehler 2: Strategiehopping
- In Drawdown-Phasen zur "gerade laufenden" Strategie wechseln = systemischer Fehler
- Timing-Problem: Man wechselt immer zur falschen Zeit, weil man nach dem Wechsel die nächste Schwächephase erwischt
- **Lösung:** Marktphasen-Analyse — wann funktioniert Strategie X, wann nicht?
- Schlechte Phase: Positionsgröße runter + durchhalten, NICHT wechseln
- Nur aufgeben wenn echter Edge nachweislich weg ist (nicht wegen normaler Drawdown-Phase)
- **Relevanz für TradeMind:** PS1–PS5 haben unterschiedliche Marktumfeld-Profile. Stop-Loss ist
  nicht Strategieversagen — erst nach >20 Trades statistisch bewerten.

### Fehler 3: Stop-Loss Regeln brechen
- Stop einmal verschoben → sofort emotionaler Zustand → restlichen Tag/Woche pausieren
- Stop-Fischen (Argument gegen Stops) ist irrelevant: 5x gefischt ist besser als 1x Kontoruin
- **Regel:** Stop-Bruch = sofortiger Handelsstopp für den Tag (Emotionaler Reset)
- **Relevanz für TradeMind:** Paper Trades: Stop unter Entry IMMER. Kein "mentaler Stop".

### Meta-Lektion
Jede Strategie hat Gut- und Schlechtphasen. Geduld + Disziplin + Risikomanagement > perfektes System.
Das perfekte System gibt es nicht — aber einen disziplinierten Umgang mit dem eigenen System.

---

## 2026-03-22 — Eriksen / Rendite Spezialisten 12/26: Hormus-Krise + Makro-Framework

**Quelle:** Rendite Spezialisten, Ausgabe 12/2026, 22.03.2026
**Archiv:** memory/transcripts/eriksen-rendite-spezialisten-2026-03-22.pdf

### Methodik 1: Brent-WTI-Spread als Energieexport-Risikoindikator
- Wenn Brent deutlich schneller steigt als WTI → Markt preist US-Energieexportstopp-Risiko ein
- Historisch normal: Brent 3-5$ über WTI (Qualitätsprämie + Transportkosten)
- Anomalie: Spread > 8-10$ = geopolitisches Risikopricing aktiv
- **Regel:** Brent-WTI Spread > 8$ = PS1-These bestätigt, keine Absicherung nötig
- **Regel:** Spread kollabiert plötzlich (< 3$) = De-Eskalations-Signal → Exit PS1-Positionen prüfen
- Bereits in macro_daily Tabelle getrackt ✅ — jetzt als Signal nutzen

### Methodik 2: FedEx als realwirtschaftlicher Frühindikator
- Logistikkonzerne (FedEx, UPS) sehen Wirtschaftsdaten 4-6 Wochen früher als offizielle Statistiken
- FedEx erhöht Guidance trotz Energiekrise = Realwirtschaft hält noch
- **Regel:** FedEx Quarterly Guidance ↑ = Rezession noch 1-2 Quartale entfernt
- **Regel:** FedEx Guidance ↓ = Phase-2-Übergang wahrscheinlich (Eriksen-Framework)
- TradeMind: FDX als Makro-Indikator bei phase_check ergänzen

### Methodik 3: "Bad News = Good News" Regime-Erkennung
- Normales Regime: Schlechte Wirtschaftsdaten → Zinssenkungshoffnung → Aktien steigen
- Aktuell AKTIV wenn: Inflation hoch + Zentralbank im Dilemma + Öl > $100
- Erkennungsmerkmal: Starke Konjunkturdaten beunruhigen Märkte (weil sie Zinssenkungen verhindern)
- **Regel:** Wenn starke ISM/NFP-Daten zu Kursrückgängen führen → "Bad News = Good News"-Regime aktiv
- Bedeutung: In diesem Regime sind defensive Sektoren attraktiver, Growth-Aktien (NVDA/PLTR) anfälliger
- TradeMind: Regime-Flag in learning_system.py ergänzen

### Methodik 4: EZB Stagflations-Indikator
- Signal: Inflation-Prognose ↑ + Wachstums-Prognose ↓ gleichzeitig = Stagflation
- Konsequenz: EZB kann weder senken (Inflation) noch straffen (Wachstum) → Dilemma
- Zinssenkungswahrscheinlichkeit sinkt → Immobilien, Versorger, wachstumsabhängige Sektoren leiden
- **Regel:** Wenn EZB Inflation >2,5% + Wachstum <1% prognostiziert → europäische Tech/Wachstums-Exposure reduzieren
- Bestätigt Eriksens 20.03 Phase-1/2-Framework: EZB-Stagflation = Phase-2-Beschleuniger

### Methodik 5: 200-Tage-Linie als Marktgesundheits-Checkpoint
- S&P 500 unter 200-Tage-MA erstmals seit Mai 2025 = strukturelle Schwäche
- Regel (technisch): Solange Index unter 200-MA → Risk-Off Modus, keine neuen aggressiven Longs
- Umkehr über 200-MA = Risk-On Signal, Positionen aufbauen (Tranchenlogik)
- TradeMind: 200-MA-Check für S&P 500 + DAX in Trading Monitor ergänzen

### Methodik 6: Energie-Unabhängigkeit als Dekaden-Trend
- Nicht politisch/ideologisch — sondern geopolitische Notwendigkeit
- Mechanismus: Gasabhängigkeit (erst Russland, jetzt USA) zeigt strukturelle Verwundbarkeit
- **Investitions-Implikation:** Erneuerbare Energie in Europa = struktureller Bull-Trend über 5-10 Jahre
- Betroffene Sektoren: Offshore-Wind, Solar, Netzinfrastruktur, Kernkraft (SMR)
- Konkret: Vestas (VWS.CO), Orsted (ORSTED.CO), Siemens Energy (ENR.DE), RWE (RWE.DE)
- PS1-Erweiterung: Neben kurzfristigem Öl-Play auch langfristige Energie-Unabhängigkeits-These ergänzen

### Direkte Portfolio-Relevanz (aktuell)
- EQNR: Brent-WTI Spread weiterhin hoch → These intakt, Stop 34,50€ halten
- OXY: Energie-Export-Risikopricing bestätigt Öl-Bull-Thesis kurzfristig
- A2QQ9R (Solar ETF): Energie-Unabhängigkeits-Trend bestätigt die langfristige These (auch wenn kurzfristig schwach)
- PLTR/NVDA: "Bad News = Good News"-Regime aktiv → Growth-Exposure kritisch beobachten

---

## 2026-03-22 — NACHTRAG: Begründete Mechanismen (bisher aussortiert)

> Korrektur: Eriksens und Dirk 7Hs begründete Prognosen enthalten lernbare Mechanismen.
> Filter ab jetzt: "Mechanismus vorhanden?" → Ja = relevant, unabhängig ob Meinung.

---

### Eriksen 22.03 — Mechanismus 1: Zinserwartungen vs. Immobilien (Vonovia-Case)
- **Beobachtung:** Vonovia +4,8 Mrd. € Gewinn + erhöhte Dividende → Aktie fällt zweistellig
- **Mechanismus:** Steigende Zinserwartungen → höhere Diskontierungsrate → Immobilienbewertungen fallen,
  unabhängig von aktuellen Gewinnen
- **Regel:** Wenn Bundesanleihen-Rendite >3% steigt → Immobilien-/REIT-Sektor strukturell unter Druck
- **Umkehrung:** Wenn Zinsen fallen/Senkungserwartungen steigen → Immobilien als erstes profitieren
- **TradeMind:** Sektor-Signal: BundRendite als Vorlaufindikator für Immobilien-ETFs (z.B. IPRP)

### Eriksen 22.03 — Mechanismus 2: Hormus-Dauer als Phase-Trigger
- **Mechanismus:** Je länger Hormus-Krise dauert, desto sicherer Phase-2-Übergang
  - <4 Wochen: Phase 1 (Inflationsschock), Realwirtschaft hält
  - 4-8 Wochen: Phase-2-Risiko steigt auf >50%
  - >8 Wochen: Phase 2 fast sicher (Wachstumsschock, Rezession)
- **Eskalations-Start:** ~20.03.2026 (US-israelische Luftangriffe)
- **Countdown:** Täglich überwachen — je Tag mehr = Phase-2-Druck steigt
- **Regel:** Wenn Hormus-Krise >28 Tage → PS1 Positionen trailing, NICHT aufbauen

### Eriksen 22.03 — Mechanismus 3: Fed "Held All Year" → Growth-Druck
- **Macquarie-These:** Nächster Fed-Schritt = Erhöhung 2027
- **Mechanismus:** Wenn Markt Fed-Pause für ganzes Jahr einpreist → Growth-Multiples
  (KGV von NVDA, PLTR, MSFT) stehen unter strukturellem Druck
- **Quantifizierung:** Fed-Funds-Futures einpreisen → wenn <1 Zinssenkung für 2026 → Risk-Off für Growth
- **Regel:** Fed-Pause-Regime + VIX > 25 → Growth-Exposition (NVDA/PLTR) auf max. 2 Tranchen begrenzen

### Dirk 7H 22.03 — Mechanismus: Historischer Analogie-Ansatz (Bitcoin-Beispiel)
- **Methodik (universell):** Wenn technische Konstellation + Makrobedingungen ein früheres Muster spiegeln
  → ähnlicher Ausgang wahrscheinlicher als Basisrate
- **Zwei-Säulen-Check:**
  1. Technisch: Gleiche Chart-Struktur? (Topbildung, Flaggen, MA-Position)
  2. Makro: Gleiche Bedingungen? (Geopolitik, Inflation, Zinszyklus)
- **Nur valide wenn BEIDE Säulen übereinstimmen** — eine allein reicht nicht
- **Anwendung TradeMind:** Vor jedem größeren Trade: "Welcher historische Fall ähnelt dem am meisten?"
  → Gleiche Marktphase, gleiche Sektor-Dynamik, gleiche Makrolage

### Dirk 7H 22.03 — Mechanismus: Movement-Flagge-Movement-Pattern
- **Definition:** Impulsive Bewegung → Konsolidierung (Flagge, 2-4 Wochen) → gleich große Anschlussbewegung
- **Messung:** Flaggenhöhe = erwartetes Ziel der Anschlussbewegung
- **Bestätigung:** Ausbruch aus Flagge mit erhöhtem Volumen
- **Invalidierung:** Kurs bewegt sich nachhaltig über/unter gleitenden Durchschnitt in Gegenrichtung
- **Relevant für:** DT3 (Gap-Fill), DT8 (BB Squeeze), PS-Swing-Entries

### Eriksen 13.03 — WPR-Signal (bisher nur kurz erwähnt, hier vollständig)
- **Williams Percentage Range (WPR) auf Monatsbasis** = sehr seltenes, starkes Signal
- **Bedeutung:** Zeigt Akkumulation durch große Marktteilnehmer (Smart Money kauft leise)
- **Wichtig:** Kurs kann noch fallen während WPR akkumuliert → kein Kaufsignal im klassischen Sinn
- **Tranchenkauf-Methodik daraus:**
  1. Tranche 1 bei erstem WPR-Signal (auch wenn Kurs noch fällt)
  2. Tranche 2 nach Bestätigung (zweites WPR-Signal oder Kurs-Stabilisierung)
  3. Tranche 3 nach Trendbestätigung (Kurs über MA20 + Volumen)
- **Rollende Korrelation prüfen:** Vor jeder Markt-Ableitung: Korrelation der letzten 3 Monate messen,
  nicht historische Durchschnittswerte annehmen
- **TradeMind:** WPR als monatliches Signal-Check für alle Watchlist-Positionen

---

---

## Lars Eriksen — 23.03.2026 (Gold-Korrektur)

**Quelle:** Transcript eriksen-2026-03-23-gold.txt
**Kontext:** Gold –5,6% an dem Tag, Trump de-eskaliert Iran, Brent –14%

### METHODIK

**1. Antizyklisches Kaufen — Voraussetzung: vorher definiertes Szenario**
- Regel: Man darf nur antizyklisch kaufen wenn man das Szenario VOR dem ersten Kauf definiert hat
- "Ist Gold in 2-3 Jahren höher?" → Ja → Also kaufe ich in Korrekturen nach
- Ohne vorab definierte These ist antizyklisches Kaufen kein Konzept sondern Hoffnung
- Gilt für Victor: Jede Position braucht eine ausformulierte These BEVOR der erste Kauf

**2. Seitenlinie = Rendite-Killer (mit Datenbasis)**
- 30 Jahre US-Privatanleger-Daten: Wer "an die Seitenlinie tritt" kauft meist NACH der Erholung
- Die 10 besten Tage eines Jahrzehnts passieren oft kurz nach großen Korrekturen
- Wer diese 10 Tage verpasst, halbiert seine Langfrist-Rendite
- Albert-Schluss: Gilt für Langfrist-Positionen. Kurzfristige Trades (EQNR) sind anders — da ist aktives Stop-Management korrekt.

**3. Warum Gold in Krisen fällt (Framework)**
- Wenn alles fällt → auch stark gelaufene Assets werden verkauft (erhöhte Investitionsquoten = mehr zu verkaufen)
- Inflationsangst → Zinssenkungen werden ausgepreist → Realrenditen steigen → bärisch für Gold
- Dollar wertet auf (in Krisen: Flight to Safety) → Gold in anderen Währungen teurer → weniger Nachfrage
- Wichtig: Gold-Fundis ≠ kurzfristige Gold-Kursbewegung. Beide können gleichzeitig stimmen.

**4. Überkauft/Überverkauft als Entry-Signal (nicht Charttechnik)**
- Eriksen kauft nicht auf Chartsignale sondern auf "Erstmals seit Jahren überverkauft"
- RSI-artiger Blick auf historische Extrema, nicht auf kurzfristige Muster
- Dann: Tranche kaufen, Weiteres Tief möglich (+5-10%) akzeptieren, nicht Boden erwischen versuchen

**5. Tranchenweise Entry statt perfekter Einstieg**
- "Ich kaufe, wissend dass ich vielleicht nicht das Tief erwische"
- Kapital für Nachkauf reservieren wenn möglich
- Perfekter Einstieg ist Glück, nicht Skill — Skill ist die Häufigkeit des richtigen Kaufbereichs

**6. Positionstypen trennen**
- Eriksen hat: aktives Depot (Trading, nimmt Gewinne mit) vs. Zukunftsdepot (Langfrist, hält durch)
- Im Zukunftsdepot keine Finger-Trading-Gedanken ("hätte bei 300 verkaufen können")
- Konsequenz für Albert+Victor: Strategien müssen klar sein: ist das ein Trade (aktiver Stop) oder Langfrist (durchhalten mit Thesis)

### BEGRÜNDETE THESE (Eriksen's Kaufargument Royal Gold / RGLD)

- **Ticker:** Royal Gold (RGLD), Goldstreaming-/Royalty-Unternehmen
- **Argument:** In vordefinierter Kaufzone, Gold strukturell bullisch durch Schuldenberg + Fiat-Entwertung
- **Zeitrahmen:** 2-3 Jahre
- **Albert's Einschätzung:** Royalty-Modell interessant (kaum Produktionsrisiken, partizipiert am Goldpreis). Aber: heute –~20% von 260 auf 207 — wenn Ceasefire Iran und Dollar weiter stark, könnte noch tiefer gehen. Strukturell überzeugend, kurzfristig weiteres Risiko. Watchlist für Victor: A14WU5 / First Majestic Silver (AG) ist ähnliche Logik aber Silber.

### ÜBERTRAGBAR AUF UNSER SYSTEM

- Langfrist-Positionen (NVDA, MSFT, PLTR) → Eriksen-Logik: nicht panikverkaufen, These prüfen nicht Kurs
- Kurzfrist-Trades (EQNR, Paper Trades) → aktiver Stop ist korrekt, Eriksen würde zustimmen
- Gold/Rohstoffe als Portfoliobaustein: bei nächstem Crisi-Crash als antizyklischen Buy prüfen
