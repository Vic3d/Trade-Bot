# Entscheidungs-Log — Trading Strategie

Wichtige Entscheidungen mit dem Kontext der dazu geführt hat.
Kein Marktrauschen — nur was die Strategie wirklich beeinflusst hat.

## 2026-03-26 — DR0.DE Stop auf 91€ gesetzt

**Entscheidung:** Stop-Loss für Deutsche Rohstoff AG (DR0.DE) auf 91,00€ gesetzt.
**Position:** Entry 87,44€ | Kurs ~95,50€ (+9%) | Stop 91€ → +4,1% Gewinn gesichert
**Kontext:** Aktie +8,99% seit Entry. Dirk 7H Trailing-Stop-Regel greift ab +5%. Volatilität DR0 sehr hoch (55% annualisiert). Iran-Krise eskaliert (UAE getroffen, Iraq Rumaila-Ölfeld angegriffen, Libyen-Gas-Pipeline), S1-Thesis 🟢🔥.
**Kern-Reasoning:** Stop über Breakeven (87,44€) und über "Minimum 90€"-Empfehlung. Gibt ~4,6% Puffer zum aktuellen Kurs bei gleichzeitig +4,1% gesichertem Gewinn. Sinnvoller Kompromiss zwischen Gewinnschutz und Laufenlassen bei starker Thesis.
**Nächster Schritt:** Bei Kurs >98€ → Stop auf 92-93€ nachziehen.

---

## 2026-03-11 — Rheinmetall AG (RHM.DE) Position geschlossen

**Entscheidung:** Exit bei ~1.563€, Entry war 1.635€ → Verlust –4,4%

**Kontext:**
- Rüstungsrally hatte Momentum verloren nach NATO-Ankündigung
- Kein Stop war real in TR gesetzt — mentaler Stop versagte bei schneller Bewegung
- Victor entschied manuell zu verkaufen

**Kern-Reasoning:**
- Momentum-Bruch nach Rally war klares Signal
- Ohne echten Stop kein automatischer Schutz → manueller Exit notwendig
- Position war zu lange ohne Absicherung gehalten

**Re-Entry Plan:**
- Signal A: Kurs >1.625€ + erhöhtes Volumen
- Signal B: Rücklauf in Zone 1.480–1.520€

**Lesson:**
Stop IMMER real in TR setzen. Mentale Stops versagen wenn der Markt schnell dreht.

---

## 2026-03-14 — Entscheidungs-Log eingeführt

**Entscheidung:** Neues Memory-Format für Strategie-Entscheidungen

**Kontext:**
Victor: "Vielleicht sollten wir auch wichtige Nachrichten festhalten die wichtig waren für die Entscheidung einer Strategie."

**Kern-Reasoning:**
- Beschlüsse waren in strategien.md dokumentiert, aber nicht das *Warum*
- Nach Wochen unklar warum eine Entscheidung getroffen wurde
- Nachvollziehbarkeit wichtig für Lerneffekt + Strategie-Verbesserung

---

## 2026-03-19 — RIO.L Exit (Stop ausgelöst, TR nicht handelbar)
**Entscheidung:** Rio Tinto (RIO.L) verkauft — Exit bei ~72.25€
**Kontext:** 
- Stop lag bei 73€ (real in TR gesetzt)
- TR zeigte RIO.L heute als "nicht handelbar" (Volatilitätsstopp bei −6%)
- Victor hat manuell abverkauft sobald handelbar
- Auslöser: Nikkei −3.4% → Asien-Nachfrage-Angst → Rohstoffe schwach (exakt wie heute Morgen 09:15 gewarnt)
**Kern-Reasoning:** Stop war gesetzt, Stop wurde gerissen — Regel befolgt. Kein Sinn auf Erholung zu warten wenn Thesis (Rohstoff-Nachfrage) gerade weiter unter Druck ist.
**Ergebnis:** Entry 76.92€ → Exit ~72.25€ = **−4.8€, −6.2%**
**Lesson:** 
1. Stop muss REAL in TR gesetzt sein — aber auch dann kann TR "nicht handelbar" zeigen → mentale Backup-Entscheidung trotzdem klar haben
2. RIO.L hatte Conviction 0 im Monitor — das war das richtige Signal, die Position zu klein zu halten
3. Nikkei als Frühindikator für Rohstoffe hat funktioniert (09:15 Warnung → 13:50 Exit)

## 2026-03-20 — MSFT geschlossen + Neue Rohstoff-Strategie

**Entscheidung:** 
1. MSFT Microsoft (MSFT) verkauft (Stop getriggert)
2. Neue Strategie PS6: Edelmetalle & Kupfer angelegt

**Kontext:** 
- MSFT Stop 338€ wurde getriggert, Victor hat Position am 20.03. geschlossen
- Victor sieht Einstiegsmöglichkeiten bei Silber, Gold und Kupfer
- Alle drei sind -10% bis -31% von 52W-Hochs korrigiert

**Kern-Reasoning:**
- Makro-Treiber intakt: Iran-Geopolitik, Fed-Cuts, USD-Schwäche
- Strukturelle Kupfernachfrage durch KI-Boom + E-Autos
- Kein sofortiger Einstieg Silber — Reversal-Bestätigung abwarten

**Lesson:** Stop bei MSFT konsequent exekutiert — richtig. Nicht am fallenden Messer festhalten.

## 2026-03-20 — Bayer AG (BAYN.DE) Exit
**Entscheidung:** Stop 38€ ausgelöst, Marktorder bei 37.48€ exekutiert
**Kontext:** Kurs fiel durch Stop ohne Teilfüllung bei 38€ (Lücke)
**Kern-Reasoning:** Konsequente Stop-Disziplin — kein Nachkauf, kein Hoffen
**Lesson:** Bei volatilen Titeln Limit-Order statt Market-Order am Stop erwägen → weniger Slippage (hier: -0.52€ = ca. 1.3% zusätzlich)

## 2026-03-23 — EQNR Stop ausgelöst, Position geschlossen

**Entscheidung:** Position Equinor ASA (EQNR) durch Stop-Loss bei 34,46€ automatisch geschlossen

**Kontext:** Bearischer Markt am 23.03.2026 — Iran-Krise Phase-1-Schock (Trump 48h-Ultimatum 22.03., Asiatische Märkte -4 bis -6% über Nacht, Brent ~$112). Victor: "sehr bärischer Markt heute, vielleicht zu einem späteren Zeitpunkt Wiedereintritt beobachten"

**Kern-Reasoning:** Trailing Stop hatte Gewinne gesichert — Entry 27,04€, Stop nachgezogen auf 34,50€ (20.03.). Phase-1-Schock verkauft alles, auch Gewinner. Stop hat sauber funktioniert.

**Ergebnis:** +27,4% (Entry 27,04€ → Exit 34,46€, ~3 Wochen Haltedauer)

**Lesson:** Trailing Stop Regel bestätigt: nach +5% Gewinne mitnehmen durch Stop-Nachziehen. Phase-1-Schocks sind nicht prognostizierbar — Schutz durch mechanischen Stop besser als Bauchgefühl.

**Nächster Schritt:** Re-Entry EQNR beobachten wenn Phase-2 (Gewinner-Selektion) einsetzt

## 2026-03-23 — EQNR Re-Entry verworfen

**Entscheidung:** Kein Re-Entry in Equinor ASA (EQNR) zum jetzigen Zeitpunkt

**Kontext:** Victor fragte nach Re-Entry um 16:29. EQNR bei 31,74€ nach –5,5% heute. Brent –14% ($112→$98) nach Trump-De-Eskalation (postponed Iran strikes, "productive talks"). Trade Republic zeigt 29,5% Downside vs Analysten-Konsensus.

**Kern-Reasoning:**
- Analysten-Konsensus: ~22,37€ → EQNR noch 29,5% über Fair Value
- Unser Entry war 27,04€ — Analysten-Ziel liegt DARUNTER
- Brent $98 hat noch ~$13-17 Kriegsprämie drin (Pre-Krise: $81)
- Vollständiger Ceasefire würde EQNR auf 22-25€ drücken
- Victor: "Einstieg jetzt wäre pokern auf einen Rebound" ✅

**Lesson:** Geopolitische Risikoprämien können schnell und vollständig deflationieren. Nach +38% Ölrally genug Gewinn mitgenommen (Stop +27,4%). Re-Entry erst wenn Boden bestätigt.

**Re-Entry Bedingungen (dokumentiert für spätere Nutzung):**
- Entry-Zone: 335-350 NOK (28,5-29,8€) nur wenn Brent 2-3 Tage stabil >$90
- Stop: 310 NOK (26,4€)
- Realistischer Einstieg erst bei 24-26€ (Fair Value ohne Geopolitik-Premium)
- Oder: Re-Eskalation Signal (Hormuz erneut blockiert) → dann sofort über 400 NOK kaufen

## 2026-03-24 — Options-Flow als primärer Trade-Trigger (Grundsatzentscheidung)

**Entscheidung:** Options-Flow-Signale ab sofort als **Echtzeit-Trigger für Trade-Entscheidungen** nutzen — nicht nur beobachten, sondern bei starken Signalen sofort handlungsfähig sein.

**Kontext:** Am 24.03.2026 kamen über den ganzen Tag hinweg massive bullische Öl/Energie-Flows rein:
- 08:45: XLE $65 Call → 12.677 Vol (dickster Flow des Tages)
- 17:02: XLE $66 Call → 2.448 Vol (neuer Strike, neue Laufzeit)
- 17:30: OXY $65 Call → 7.849 Vol, **Vol/OI 59.9x** (fast alles frisch eröffnet)
- Zusätzlich: USO, XOM, CVX, BNO — alles Calls, alles bullisch, alles April-Verfall
- Das war kein einmaliger Spike — **anhaltende Käufe über den ganzen Tag**

Victor: "Genau solche Informationen sind super wichtig. Wenn so was passiert, muss man sofort gucken ob man da einen Trade tätigt."

**Kern-Reasoning:** Options-Flow kommt 30-90 Minuten VOR den News. Wer Calls mit 60x Vol/OI kauft, hat eine informierte Wette laufen. Das ist der nächstbeste Indikator nach Insider-Wissen — und legal handelbar.

**Lesson:**
1. Bei Vol/OI >10x + OI=0 (🔥 FRISCH) → **sofort** Victor benachrichtigen mit konkretem Trade-Vorschlag
2. Bei mehreren Tickern gleichzeitig bullisch (Cluster-Signal) → Konfidenz erhöhen, aggressiver
3. Nicht nur melden, sondern direkt sagen: "Entry X, Stop Y, Ziel Z"
4. April-Verfall = Smart Money erwartet Bewegung in 2-4 Wochen → Horizont beachten

## 2026-03-25 — Öl-Positionen HALTEN trotz Ceasefire-Hoffnungen

**Entscheidung:** A3D42Y (VanEck Oil Services ETF) und alle Öl-Positionen werden gehalten. Kein Teilverkauf trotz Brent -4% overnight und Trump-Ceasefire-Signalen.

**Kontext:**
- Trump hat 15-Punkte-Plan mit Iran vorgeschlagen (24./25.03.)
- Brent fiel -4% overnight auf ~$100
- Silver +8% auf Ceasefire-Hoffnungen
- OXY April-Calls mit 18.931 Kontrakten — institutioneller Käufer kauft in die Schwäche
- CFTC CoT (17.03.): Hedge Fonds netto +31.502 long auf WTI

**Kern-Reasoning (Victors Analyse):**
Trumps Forderungen (Atomanlangen schließen + keine ballistischen Raketen) sind DIESELBEN Forderungen wie vor dem Krieg — damals gab es keine Einigung. Iran KANN diese Forderungen strukturell nicht erfüllen, weil:
1. Nukleare Fähigkeit + Raketen = einzige Lebensversicherung des Regimes
2. Historisches Muster: Libyen (Gaddafi gab WMDs auf → 2011 gestürzt), Irak (Saddam kooperierte → 2003 invadiert). Iran hat dieselbe Tabelle vor Augen.
3. Ohne Deterrence = Iran ist das nächste Libyen. Das ist rational nicht akzeptierbar.

**Deal-Wahrscheinlichkeit:**
- Kein Deal / Talks scheitern: 60%
- Kleiner Teil-Deal (Einfrierung, kein Abrüstung): 30%
- Echter Großdeal (alle Trump-Forderungen): 10%

**Lesson:**
Ceasefire-Rhetoric ≠ Ceasefire-Realität. Strukturelle Unmöglichkeit eines Deals (Regime-Survival-Logik) schlägt kurzfristige Marktreaktion. Öl-Thesis intakt solange keine konkreten, verifizierbaren Zugeständnisse Irans.

**Risiko-Monitor:**
Exit-Signal wäre: konkreter Teil-Deal mit verifizierbaren Maßnahmen — NICHT nur Gesprächsankündigung oder Trump-Tweet.

## 2026-03-25 — Neue Regel: Insider-Geldstrom-Tracking

**Entscheidung:** Ab sofort Geldströme auf Insider-Aktivität überwachen. Bei Erkennung: sofort Paper-Hedge-Trade + Victor informieren.

**Kontext:** Reuters meldete dass Trader $500 Mio. auf Öl-Short gewettet haben BEVOR Trump seinen Verhandlungs-Tweet postete. Brent fiel daraufhin von $112 auf $95 (−15%). Victor: "Du kannst Trump nicht vorhersagen, aber wenn du es an den Geldflüssen erkennst, ob irgendwo schon wieder Insiderwissen gehandelt wird — teste sowas bei Paper Labs und melde dich falls du solche Ströme siehst."

**Kern-Reasoning:** Politische Tweets sind nicht vorhersehbar, aber die Geldströme die VOR den Tweets kommen (Insider/Smart Money) sind messbar. Ungewöhnliches Options-Volumen, CoT-Divergenzen und Put/Call Ratio Spikes sind Frühwarnsignale.

**Tracking-Signale:**
1. Ungewöhnliches Put-Volumen bei Öl/Energy während bullischer Stimmung
2. CoT: Non-Commercials bauen heimlich Longs ab während Retail long geht
3. Put/Call Ratio Spikes bei OXY, XLE, Öl-Futures
4. Block Trades / Dark Pool Aktivität

**Lesson:** "Follow the money, not the narrative." Wenn alle bullisch reden aber das Smart Money short geht → Hedge aufbauen.

## 2026-03-25 — EQNR Re-Entry (Victor)

**Entscheidung:** Equinor ASA (EQNR) gekauft bei 33,58€, Stop 33,20€.

**Kontext:** Victor: "Ich glaube einfach Donald Trump nicht. Ich denke, der Irak-Krieg ist noch lange nicht zu Ende." Kurs aktuell 34,52€ (+3,3% seit Entry). Öl fällt wegen Trump-Verhandlungsrhetorik (Brent $112→$95), aber:
- Prof. Jäger (NTV): Deal bis Freitag "sehr skeptisch", 15-Punkt-Plan für Iran inakzeptabel
- US ADR Accumulation: +65% Volumen-Trend, A/D 2.8x (Amerikaner kaufen)
- OXY April-Calls 18.931 Kontrakte, CoT netto +31.502 long
- Tanker +10-14% (physische Nachfrage steigt trotz Papier-Ölpreis-Fall)

**Kern-Reasoning:** Der Papiermarkt preist einen Deal ein, den es strukturell nicht geben kann. Die physischen Signale (Tanker, Accumulation) widersprechen der Verhandlungs-Euphorie. Victor vertraut der eigenen Analyse über die Trump-Rhetoric.

**Risiko:** Stop bei 33,20€ = nur 1,1% Risiko — SEHR eng. Bei VIX 25+ und Öl-Volatilität kann das schnell ausgestoppt werden.

**Lesson:** —
