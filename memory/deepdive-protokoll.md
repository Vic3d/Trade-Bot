# Deep Dive Protokoll — Albert

**Zweck:** Strukturierte Analyse vor jeder Aktien-Einschätzung. Kein Überspringen. Kein Kurzschluss.
**Erstellt:** 28.03.2026 — nach MOS-Analyse-Fehler (reaktives Denken statt Struktur)

---

## Paper Trading — Pflichtregeln (KEINE AUSNAHMEN)

**Bevor eine Aktie ins Paper-Portfolio aufgenommen wird:**

1. Vollständiger Deep Dive nach diesem Protokoll — alle 6 Schritte
2. Folgende Mindest-Kriterien müssen erfüllt sein:

### Bewertungsregel — Sektor-abhängig (nicht KGV pauschal)

Profis benutzen keine fixe KGV-Grenze. Stattdessen: **sektorgerechte Metrik + Vergleich zum Sektor-Durchschnitt.**

| Sektor-Typ | Primäre Metrik | Gut | Okay | Teuer | Beispiele |
|---|---|---|---|---|---|
| **Öl / Energie / Rohstoffe** | EV/EBITDA oder KCV | ≤ 6x | 6–9x | > 10x | EQNR, OXY, TTE, RIO, BHP |
| **Zykliker** (Stahl, Dünger, Bergbau) | EV/EBITDA | ≤ 5x | 5–8x | > 10x | MOS, NUE, STLD, PKX |
| **Industrie / Airlines / Infra** | KGV | ≤ 10x | 10–15x | > 18x | LHA, RHM, KMI |
| **Tech / Wachstum** | PEG-Ratio | < 0.5 | 0.5–1.5 | > 2.0 | NVDA, PLTR, MSFT |
| **Banken / Versicherungen** | Kurs/Buchwert (KBV) | < 1.0 | 1.0–1.5 | > 2.0 | Deutsche Bank, Allianz |
| **Pharma / Biotech** | KGV + Pipeline | ≤ 15x | 15–25x | > 30x | BAYN, NOVO-B |

**Relative Bewertung (immer):**
- Aktie vs. eigener Sektor-Durchschnitt — günstiger oder teurer?
- Aktie vs. eigener historischer Durchschnitt (5 Jahre) — wo steht sie im Zyklus?
- Bei Zinsen > 3%: KGV ≤ 1/Anleiherendite = faire Bewertung (Buffett-Regel)
  - 10J-Bund aktuell ~2.7% → faire KGV-Grenze ≈ 37x (Aktien noch attraktiv vs. Anleihen)

**Zweites Kriterium — immer zusätzlich prüfen:**
- EPS-Trend: Stabil oder steigend (kein Earnings-Trough-Kauf ohne starken Katalysator)
- Schulden-Trend: Nicht 3+ Jahre steigend ohne strategischen Grund

| Kriterium | Anforderung |
|---|---|
| **Bewertung** | Sektor-gerechte Metrik (s.o.) im grünen oder gelben Bereich |
| **EPS-Trend** | Stabil oder steigend — fallend = nur mit explizitem Erholungs-Katalysator |
| **Schulden-Trend** | Nicht 3+ Jahre steigend ohne Grund |
| **Analyst-Konsens** | Kein aktiver Downgrade in letzten 30 Tagen |
| **Katalysator** | Frisch (≤30 Tage) und spezifisch — kein alter Hut |
| **Sektor-Kontext** | Aktie läuft nicht gegen den eigenen Sektor |
| **CRV** | Mindestens 2:1 (Stop vs. Ziel) |

3. Erst wenn alle Kriterien grün → Position eröffnen
4. Jede Position wird mit diesen Daten in `memory/positions-live.md` dokumentiert

**Vorbild-Setup (Maßstab: Lufthansa-Analyse 28.03.2026):**
- KGV 6x (weit unter Sektor-Schnitt)
- Wachsende Earnings + steigende Dividende
- Klarer externer Katalysator (Iran-Ende = Ölpreis fällt = Margen steigen direkt)
- Antizyklisch: Kauf bei maximaler Angst, nicht nach dem Ausbruch
- Tranchen-Strategie: nicht alles auf einmal

**Was wir NICHT wollen (Gegenbeispiel MOS):**
- KGV 16x in einem Trough-Jahr
- Schulden 3 Jahre steigend
- Aktie fällt während Sektor steigt
- Kein frischer Katalysator für 2026

---

## Ablauf bei jedem Deep Dive — Zug der Analyse

**Wenn Victor "Deep Dive [Aktie]" sagt:**

1. **Daten holen ZUERST** — kein Kommentar, keine These, keine Meinung
   - Yahoo Finance: Kurs, MA50/MA200, RSI, Volumen, 52W-Range, Performance
   - Onvista (DE-Aktien): KGV 2025/2026e/2027e, Dividende, PEG, Index
   - Macrotrends: Umsatz-Trend + Long-Term Debt Trend (mindestens 5 Jahre)
   - Google News RSS: Analyst-Konsens letzte 30 Tage (Upgrades / Downgrades)
   - Google News RSS: Aktuelle Risiken / "schwere Zeiten" Suche

2. **Gegenthese suchen BEVOR These formulieren**
   - Aktiv nach negativen Nachrichten, Schulden-Anstieg, Downgrades suchen
   - "Leiche im Keller" Checkliste durchgehen

3. **Erst dann: Synthese und Einschätzung**
   - Szenarien (Bear / Base / Bull) mit konkreten Kurszielen
   - Konfidenz explizit nennen
   - Strategie mit Entry / Stop / Ziel / CRV

**Keine Abkürzungen. Keine spontanen Thesen vor den Daten.**

---

## Pflicht-Reihenfolge (alle 6 Schritte, immer)

### Schritt 1 — Technisches Bild (Fakten, keine Bewertung)
- Kurs, 52W-High/Low, Abstand in %
- MA50 und MA200 — Kurs drüber oder drunter?
- RSI(14) und RSI(7)
- Volumen: heute vs. 20T-Durchschnitt
- ATR(14) — wie volatil ist das Ding?
- Performance: 1W / 1M / 3M / 6M
- **KEIN Urteil in diesem Schritt.**

### Schritt 2 — Fundamentals (letzte 4 Quartale)
- Umsatz: Trend steigend / fallend / seitwärts? (Macrotrends verifizieren)
- Gewinn (EPS): positiv? wachsend? (Onvista für DE-Aktien: KGV 2025/2026e/2027e)
- Marge: stabil oder unter Druck?
- P/E, P/B, PEG im Sektorvergleich — günstig oder teuer?
- **Verschuldung: Absolute Höhe + TREND (steigend oder fallend?) — Macrotrends Long-Term Debt**
  - Steigende Schulden bei fallender Marge = Warnsignal
  - Schulden/Umsatz-Ratio berechnen
- Dividende: Höhe + Trend + Yield auf aktuellen Kurs
- Index-Zugehörigkeit: DAX40 / MDAX / SDAX / kein Index? (Onvista zeigt das)
- **Quellen: Onvista (DE-Aktien), Macrotrends (Schulden/Umsatz-Historie), Yahoo Finance**

### Schritt 3 — Analyst-Konsens (NUR letzte 30 Tage)
- Upgrades / Downgrades in den letzten 30 Tagen?
- Kursziele: Range (niedrigstes / höchstes / Median)
- Konsens-Rating: Buy / Hold / Sell
- **WICHTIG: Ältere Meldungen explizit ignorieren wenn neuere da sind**

### Schritt 4 — "Leiche im Keller" (aktiv nach Risiken suchen)
Ziel: Die versteckten Risiken finden BEVOR ich eine These formuliere.
Pflicht-Fragen:
- **Schulden:** Steigen die Schulden obwohl das Geschäft gut läuft? Warum? (Übernahmen? Verluste?)
- **Übernahmen/Integration:** Läuft gerade eine teure Übernahme? Integrationsrisiko?
- **Regulierung:** Gibt es laufende Kartellverfahren, Klagen, Staatseingriffe?
- **Abhängigkeiten:** Von einem Rohstoff, Währung, Großkunden, Lieferant abhängig?
- **Strukturelle Schwäche:** Verliert das Unternehmen Marktanteile an Konkurrenten?
- **Management:** CEO-Wechsel, Insiderverkäufe, Gewinnwarnung in letzten 90 Tagen?
- **Makro-Abhängigkeit:** Welcher externe Schock würde das Geschäftsmodell zerstören?
- Aktiv nach dem suchen was die These WIDERLEGT
- Warum könnte die Aktie weiter fallen?
- **Erst wenn alle Fragen beantwortet sind → weiter zu Schritt 5**

### Schritt 5 — Industrie & Makro-Kontext
- Was treibt den Sektor strukturell? (Angebot/Nachfrage)
- Wer sind die direkten Konkurrenten und wie laufen die?
- Welche Makro-Faktoren sind relevant? (Zölle, Geopolitik, FX)
- Ist das ein neuer Katalysator oder alte Nachricht?
- **Kriterium "frischer Katalysator": muss in den letzten 30 Tagen aufgetreten sein**

### Schritt 6 — Synthese & Einschätzung
- Erst JETZT: These formulieren
- Konfidenz explizit nennen: 🔴 Niedrig / 🟡 Mittel / 🟢 Hoch
- Zeithorizont: kurzfristig (Wochen) / mittelfristig (Monate) / langfristig (Jahre)
- Invalidierungsbedingung: Was macht die These falsch?
- Entry-Trigger: Welche Bedingung muss erfüllt sein bevor Geld reingeht?

### ⬛ TRADING-VERDICT — Pflichtabschluss jeder Analyse

Jede Analyse endet mit diesem Block — immer, ohne Ausnahme:

```
---
## ⬛ Trading-Verdict: [Aktienname]

**Handlung:**     KAUFEN / WARTEN / NICHT KAUFEN
**Strategie:**    Einmaliger Kauf / Tranchen / Kein Trade
**Entry:**        [Kurs oder Trigger]
**Stop:**         [Kurs] ([X]% Risiko)
**Ziel 1:**       [Kurs] ([X]% Upside) — CRV [X]:1
**Ziel 2:**       [Kurs] ([X]% Upside) — CRV [X]:1
**Zeithorizont:** [Wochen / Monate / Jahre]
**Konfidenz:**    🔴 / 🟡 / 🟢
**Invalidierung:**  [Was macht die These falsch?]
---
```

Wenn Handlung = WARTEN oder NICHT KAUFEN:
- Trotzdem Entry-Trigger und Stop angeben
- "Alert setzen wenn: [Bedingung]"

---

## Anti-Patterns (VERBOTEN)

- ❌ Scanner-Score → sofort These bauen (Schritt 1 überspringen)
- ❌ Alte Nachrichten als frische Katalysatoren verkaufen
- ❌ Victor's Gegenargument sofort akzeptieren ohne eigene Recherche
- ❌ Erste Bestätigungs-News finden → These für valide erklären
- ❌ "Das klingt logisch" ohne Zahlen zu prüfen
- ❌ Konfidenz nicht nennen

---

## Qualitäts-Check vor Abgabe ("Leiche im Keller" Checkliste)

Bevor ich eine Einschätzung sende, alle 8 Punkte abhaken:

1. ✅ Aktuellster Analyst-Konsens (≤30 Tage) geprüft?
2. ✅ Schulden-Trend verifiziert (steigend oder fallend)? Macrotrends gecheckt?
3. ✅ Index-Zugehörigkeit bekannt? (DAX/MDAX/kein Index)
4. ✅ KGV, PEG, Dividende von Onvista/Yahoo geholt?
5. ✅ Aktiv nach Gegenargumenten gesucht — NICHT nur Bestätigendes?
6. ✅ Katalysator wirklich neu (≤30 Tage) oder alter Hut?
7. ✅ Konfidenz explizit genannt (🔴/🟡/🟢)?
8. ✅ Invalidierungsbedingung: Was macht die These falsch?

→ Jedes NEIN = zurück zur Recherche. Kein Abkürzen.

---

## Lern-Beispiel: MOS (28.03.2026)

**Fehler:**
- Scanner Score 48 → sofort Kali-Sanktions-These gebaut (Schritt 3+4 übersprungen)
- Sanktionen von 2021/2022 als "aktuellen Katalysator" verkauft
- Morgan Stanley-Upgrade (Januar) gefunden → These hochrevidiert
- UBS-Cut von vorgestern ($27 Ziel) erst beim dritten Suchen gefunden

**Was korrekt gewesen wäre:**
- Schritt 3: UBS-Cut vom 26.03. wäre sofort aufgetaucht
- Schritt 4: Gegenthese "Kali-Preise bleiben gedrückt" hätte die Sanktions-These zerstört
- Ergebnis: "Kein klares Investment, Base Case $28-32, Konfidenz 🟡 Mittel"

---

*Dieses Protokoll gilt für alle Aktien-Deep-Dives, egal wie offensichtlich das Setup aussieht.*
