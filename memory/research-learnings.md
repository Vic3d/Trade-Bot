# Research Learnings

Strukturierte Lerneinträge aus externen Quellen (Transkripte, Artikel, Videos).
Generiert von `scripts/research_intake.py` ODER manuell durch Albert nach Discord-Intake.

Format pro Eintrag: Summary → Verdict → Thesen → Methoden → Prinzipien → Warnungen.

---

## 2026-04-30 — Tradermacher: Shell / Öl-Sektor (Webinar-Vorschau)

**Summary:** Tradermacher zeigt am Beispiel Shell warum Öl-Aktien bei steigendem
Brent-Preis überproportional Performance zeigen — Free-Cashflow-Hebel durch fixe
Kostenstruktur. Sales-Pitch für Webinar drumherum.

**Verdict:** Wertvoll wegen METHODIK (Capex-Breakeven + FCF-Sensitivity) — Ölpreis-Prognose selbst ist Glaskugel und ignorieren.

### Thesen
- **SHEL.AS / SHEL.L** (long, swing/position, conf=med) — Bei Brent dauerhaft 120$+
  würde Shell auf 130-150$ ADR repricen. Aktuell ~85$ ADR ≈ Brent 90-100$ eingepreist.
  - *Catalyst:* Brent-Anstieg auf 120$+ und Markt überzeugt sich von Persistenz
  - *Rationale:* FCF-Yield steigt von 6-8% auf 11-13% bei Brent +30$, weil Capex fix bleibt
- **EQNR.OL** (long, position) — bestätigt unsere S1-These, Capex-Breakeven von Equinor laut
  Schätzung sehr niedrig (Norwegen-Off-Shore profitabel auch bei niedrigen Preisen)
- **TTE.PA** (long, position, conf=med) — Tradermacher hält selbst, Total Energies hat zusätzlich
  Renewables-Anteil

### Methoden / Frameworks
- **Capex-Breakeven-Framework** (valuation, applicable: energy, commodities) —
  Pro Öl-Aktie: bei welchem Brent-Preis ist Free-Cashflow nach Capex = 0?
  Shell ~35$, Equinor lt. Schätzung tiefer. Stocks mit niedrigem Breakeven haben
  größeren FCF-Hebel bei steigenden Preisen, sind defensiver bei Crashs.
- **FCF-Sensitivity-Analyse** (valuation, applicable: alle Rohstoff-Plays) —
  Statt KGV: rechne FCF bei drei Preisszenarien (-30%, base, +30%). Nicht-lineare
  Kursziele ableiten. Bei Brent 60$ → Shell 25-35$, bei 120$ → 126-154$.
- **Diversifikations-Argument** (portfolio, applicable: alle) — Öl-Stocks sind oft
  *negativ korreliert* zu anderen Sektoren weil bei steigendem Öl die Inflation
  steigt → andere Sektoren leiden. Rohstoff-Hedge im Portfolio.

### Prinzipien
- "Nicht der Umsatz, sondern Free-Cashflow nach Capex zählt für Rohstoff-Producer"
- "Bei Bedingung 'wenn dann' arbeiten — Szenario entwickeln, nicht prognostizieren"
- "Rein chartechnisch ausbrechen ≠ saubere fundamentale These — beides muss matchen"

### Warnungen
- ⚠️ Trade-Timing bei Rohstoff-Aktien ist hart — Markt preist Persistenz erst spät ein
  (siehe Goldminen 2024: Goldpreis lange voraus, Aktien folgten erst mit ~1 Jahr Delay)
- ⚠️ Hochgehebelte Producer (hoher Fremdkapitalanteil) explodieren stärker nach oben,
  fallen aber auch heftiger — nicht für defensive Allokation

---

## 2026-04-30 — Tradermacher: Rheinmetall / Defense-Sektor (gleicher Stream)

**Summary:** Tradermacher beobachtet implizit Defense-Sektor mit Vorsicht:
RHM-Rally (200€ → 1700€ in 2 Jahren) ist großteils gelaufen. Der Stream selbst
spricht über Öl, aber RHM-Bezug ergibt sich aus der Iran/Geopolitik-Diskussion.

**Verdict:** Skeptisch — Defense-Long ist mid-2026 nicht mehr asymmetrisch. Bestätigt unsere PS3/PS11 Pause-Entscheidung.

### Thesen
- **Defense-Big-Caps (RHM.DE, LMT, RTX, NOC)** (neutral, position, conf=low) —
  Rally weitgehend eingepreist. NATO-Budget-Erhöhungen sind im Konsens, kein
  asymmetrischer Edge mehr ohne neuen Eskalations-Schock
  - *Catalyst:* Würde nur durch neuen Krieg/Eskalation funktionieren, nicht durch Status quo

### Prinzipien
- "Wenn die Rally bei einem Sektor schon gelaufen ist, brauchst du einen NEUEN
  asymmetrischen Trigger — sonst ist Long-Entry spät und teuer"
- "Eingepreist sein heißt: gute News kommt, Aktie fällt trotzdem (sell the news)"

---

## 2026-04-30 — Renaissance Medallion / Jim Simons (eigene Recherche)

**Summary:** Kurze Web-Recherche zu Renaissance Medallion-Fonds Ergebnissen:
50.75% Win-Rate über Jahrzehnte, dafür 150-300k Trades pro Tag. Profitabilität
durch Volumen, nicht durch hohen Edge pro Trade.

**Verdict:** Bekannt aber NICHT applikabel auf uns — wir haben weder die Latency,
noch das Volumen, noch das Quant-Team. Dient als Mental-Model.

### Methoden / Frameworks
- **High-Volume-Low-Edge-Modell** (sizing, applicable: HFT/quant only) —
  Bei 50%+1% WR und 150k Trades/Tag wird Gesetz der großen Zahlen wirksam.
  *NICHT für Retail/Swing-Trading anwendbar* — wir brauchen größeren Edge pro Trade.

### Prinzipien
- "Edge × Frequenz = Profit. Wenig Edge braucht hohe Frequenz; bei niedriger
  Frequenz braucht jeder Trade größeren Edge"
- Für uns: Da wir wenig Frequenz haben (1-7 Trades/Woche) **muss jeder Trade
  signifikanten Edge haben** — kein Edge-Verwässerung durch zu viele Strategien

---

## 2026-04-30 — Paul Tudor Jones (eigene Recherche, vom CEO als Style-Reference)

**Summary:** PTJ-Trading-Stil: Defense first, R:R minimum 3:1, gnadenloser Stop,
keine Hoffnung-Trades. Konvektion aus Risiko, nicht aus Gewinnerwartung.

**Verdict:** Wertvoll als Mindset — anwendbar für unser Setup auch ohne sein Kapital.

### Methoden / Frameworks
- **PTJ-R:R-Regel** (risk, applicable: alle) — Setze Stop und Target VOR Entry,
  R:R muss mindestens 3:1 sein. Wenn nicht, kein Trade.
- **5%-Tages-Risiko-Cap** (risk, applicable: portfolio) — Niemals mehr als 5%
  Portfolio-Risiko an einem Tag (für uns adaptiert: 1-2% bei kleineren Konten).

### Prinzipien
- "Defense first — der erste Job ist nicht Geld zu verdienen, sondern Geld nicht zu verlieren"
- "Keine Hoffnungs-Trades — wenn die These verletzt ist, raus, sofort"
- "Gewinner laufen lassen, Verlierer schnell beenden — Asymmetrie ist die Edge"

### Warnungen
- ⚠️ PTJ-Cap (5%) ist für seine Strategie korrekt — bei kleinen Paper-Konten ist
  das zu locker. Für uns gilt: max 1-2% Portfolio-Risiko pro Trade.
