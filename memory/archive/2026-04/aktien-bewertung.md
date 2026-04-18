# Aktien-Bewertungssystem — Albert Standard v2

**Erstellt:** 2026-03-25 | **Update:** 2026-03-25 v2 (auf Anweisung Victor)
**Regel:** JEDE Aktie durchläuft ALLE 5 Stufen BEVOR sie empfohlen wird. Keine Ausnahmen.

---

## Stufe 1: Top-Down — Makro + Geopolitik + Branchenzyklus

**Bevor wir eine einzelne Aktie anschauen: Wo stehen wir im großen Bild?**

| Check | Frage |
|---|---|
| Makro-Regime | Risk-On oder Risk-Off? (VIX, Zinsen, USD-Stärke) |
| Geopolitik | Welche Konflikte/Events beeinflussen den Sektor? |
| Branchenzyklus | Wo steht die Branche? (Expansion / Peak / Kontraktion / Trough) |
| Kausalkette | In welcher Phase der These stehen wir? (z.B. Lag-These: Phase 1-5) |
| Geldfluss | Wohin fließt Smart Money? (Sektor-ETF-Flows, A/D bei Sektor-Leadern) |
| Katalysator | Was ist der nächste Event der den Sektor bewegen kann? (Earnings, OPEC, Politik) |

**Ergebnis:** Nur Sektoren/Branchen weiterverfolgen die im aktuellen Regime Sinn machen.

---

## Stufe 2: Technische Analyse — Chart + Timing

| Check | Methode | Bewertung |
|---|---|---|
| **Trend** | Kurs vs. EMA20 + EMA50 | Über beiden = Aufwärtstrend ✅ / Unter beiden = Abwärtstrend ❌ |
| **Momentum** | RSI(14) | <30 überverkauft (Bounce?) / 30-70 neutral / >70 überkauft (Vorsicht) |
| **Relative Stärke** | Performance vs. Sektor-Peers (vom 3M-Hoch) | Besser als Peers ✅ / Schwächer ❌ |
| **Volumen-Qualität** | A/D Ratio 10d (Up-Vol vs. Down-Vol) | >1.5x Käufer ✅ / <1.0x Verkäufer ❌ |
| **Abverkaufs-Charakter** | Volumen an Drop-Tagen (>-3%) vs. Normalvolumen | <1.5x = Gewinnmitnahme ✅ / >1.5x = Distribution ❌ |
| **Support-Level** | Fibonacci-Retracement vom letzten Swing | Nahe Support = besser / Zwischen Levels = riskanter |

**Technisches Urteil:**
- ✅ Aufwärtstrend + Käufer-Volumen + stärker als Peers → **Timing passt**
- 🟡 Gemischte Signale → **Auf Bestätigung warten**
- ❌ Abwärtstrend + Distribution + schwächer als Peers → **Nicht kaufen**

---

## Stufe 3: Fundamentalanalyse — Kennzahlen + FCF + Bilanz-Gesundheit

### 3a: Kernkennzahlen (RELATIV zum Branchendurchschnitt)

| Kennzahl | Was sie sagt | Gut wenn... |
|---|---|---|
| **EV/EBITDA** | Unternehmenswert vs. operativer Gewinn (schuldenbereinigt) | Unter Branchenmedian |
| **P/E Ratio** | Preis vs. Gewinn | Unter Branchenmedian |
| **P/B Ratio** | Preis vs. Buchwert | Unter Branchenmedian (besonders bei Asset-Heavy wie Tanker/Raffinerien) |
| **Profit Margin** | Wie viel vom Umsatz bleibt als Gewinn | Über Branchenmedian |
| **ROE** | Eigenkapitalrendite | >15% stark, >10% ok |
| **Dividendenrendite** | Cashflow an Aktionäre | Kontext: hohe Div bei fallenden Gewinnen = Warnsignal |

**Wichtig:** Absolute Schwellen (P/E < 15 = gut) sind irreführend! Ein P/E von 25 ist für Tech normal, für Raffinerien teuer. IMMER Branchenmedian berechnen und relativ bewerten.

### 3b: Free Cash Flow Analyse

| Kennzahl | Formel | Was sie sagt |
|---|---|---|
| **Free Cash Flow (FCF)** | Operating CF − CapEx | Echtes Geld das übrig bleibt |
| **FCF Yield** | FCF / Marktkapitalisierung | Was du pro investiertem € an Cash bekommst. >5% = attraktiv |
| **FCF Margin** | FCF / Umsatz | Wie effizient wird Umsatz in freies Cash verwandelt |
| **OCF vs. Net Income** | Operating CF / Net Income | >1.0 = Gewinne sind durch Cash gedeckt ✅ / <0.8 = Papiergewinne ⚠️ |
| **FCF-Trend** | FCF dieses Jahr vs. Vorjahr | Steigend ✅ / Fallend ⚠️ |

**Red Flag:** Wenn ein Unternehmen Gewinne meldet aber der operative Cashflow deutlich niedriger ist → die Gewinne sind nicht "echt" (Accounting-Tricks, Einmaleffekte).

### 3c: Bilanz-Gesundheit (Piotroski F-Score Basis)

9-Punkte-Check, jeder Punkt = 1 oder 0:

| # | Check | Quelle | 1 Punkt wenn... |
|---|---|---|---|
| 1 | Net Income | Income Statement | Positiv |
| 2 | Operating Cash Flow | Cash Flow Statement | Positiv |
| 3 | ROA-Trend | Income + Balance | ROA steigt vs. Vorjahr |
| 4 | Earnings-Qualität | CF vs. Income | OCF > Net Income |
| 5 | Verschuldung | Balance Sheet | Long-term Debt/Assets sinkt vs. Vorjahr |
| 6 | Liquidität | Balance Sheet | Current Ratio steigt vs. Vorjahr |
| 7 | Verwässerung | Balance Sheet | Keine neuen Aktien ausgegeben |
| 8 | Brutto-Marge | Income Statement | Gross Margin steigt vs. Vorjahr |
| 9 | Asset Turnover | Income + Balance | Umsatz/Assets steigt vs. Vorjahr |

**Ergebnis:** F-Score 7-9 = gesund ✅ | 4-6 = neutral 🟡 | 0-3 = gefährdet ❌

### 3d: Automatische Disqualifikation

Diese Aktien werden NICHT empfohlen, egal wie gut der Rest aussieht:
- ⛔ Negative Profit Margin (Unternehmen verliert Geld)
- ⛔ Debt/Equity > 5x (Schulden-Falle)
- ⛔ OCF negativ über 2+ Quartale (verbrennt Cash)
- ⛔ FCF Yield negativ (erzeugt kein freies Cash)

---

## Stufe 4: Relative Bewertung — Branchenvergleich

**Nicht "ist die Aktie gut?" sondern "ist sie BESSER als die Peers?"**

Methode:
1. Alle Kandidaten im gleichen Sektor sammeln (min. 5)
2. Für jede Kennzahl den **Median** berechnen
3. Jede Aktie relativ zum Median bewerten:
   - Bewertungs-Kennzahlen (EV/EBITDA, P/E, P/B): **unter** Median = besser
   - Qualitäts-Kennzahlen (Margin, ROE, FCF Yield): **über** Median = besser
   - Schulden (Debt/Eq): **unter** Median = besser
4. **Rang-Score:** Für jede Kennzahl Rang 1-N vergeben, Gesamtrang = Durchschnitt aller Ränge

**Ergebnis:** Top-Quartil im Sektor = ✅ | Mitte = 🟡 | Unteres Quartil = ❌

---

## Stufe 5: Praxis-Check — Handelbarkeit + Portfolio-Fit

| Check | Frage |
|---|---|
| **WKN/ISIN** | Verifiziert? (nicht raten!) |
| **Handelbarkeit** | Auf Trade Republic / gewünschtem Broker verfügbar? |
| **Liquidität** | Durchschn. Volumen > 100k/Tag? (Sonst Spread-Risiko) |
| **Währung** | EUR/USD/NOK/GBP → FX-Kosten einkalkulieren |
| **Portfolio-Fit** | Klumpenrisiko? Wie viel % vom Portfolio ist schon in diesem Sektor? |
| **Stop-Level** | Wo? Passt zur VIX-Regel (VIX 25-30 → 5-8% Buffer)? |
| **CRV** | Chance-Risiko-Verhältnis mindestens 2:1? |
| **Positionsgröße** | Max. Verlust pro Trade ≤ 2% des Portfolios |

---

## Gesamt-Urteil

| Stufe 1 | Stufe 2 | Stufe 3 | Stufe 4 | Stufe 5 | Empfehlung |
|---|---|---|---|---|---|
| ✅ | ✅ | ✅ | ✅ | ✅ | 🟢 **KAUFEN** — alle Ampeln grün |
| ✅ | ✅ | 🟡 | ✅ | ✅ | 🟡 Möglich, Fundamental-Schwächen benennen |
| ✅ | 🟡 | ✅ | ✅ | ✅ | 🟡 Watchlist — auf technisches Einstiegssignal warten |
| Irgendwas ❌ | — | — | — | — | 🔴 NICHT empfehlen |
| — | — | Disqualifikation | — | — | 🔴 NICHT empfehlen |

---

## Datenquellen

| Daten | Quelle | API |
|---|---|---|
| Kurs, Chart, Volumen | Yahoo Finance | `query1.finance.yahoo.com/v8/finance/chart/` |
| P/E, Margin, ROE, Debt | Finnhub | `finnhub.io/api/v1/stock/metric` (US-Aktien) |
| Cash Flow Statement | Yahoo Finance | `query1.finance.yahoo.com/v10/finance/quoteSummary/?modules=cashflowStatementHistory` |
| Balance Sheet | Yahoo Finance | `...modules=balanceSheetHistory` |
| Income Statement | Yahoo Finance | `...modules=incomeStatementHistory` |
| EU-Aktien Fundamentals | Yahoo Finance (Fallback) | `modules=financialData,defaultKeyStatistics` |

---

## Prozess-Regeln

1. **ERST alle 5 Stufen, DANN Empfehlung** — keine Abkürzungen
2. **IMMER Branchenvergleich** — nie absolute Kennzahlen allein bewerten
3. **Fehlende Daten = ehrlich sagen** — "Fundamentals nicht verfügbar für diesen Ticker"
4. **Lag-These bei Öl/Energie IMMER mitführen** — in welcher Phase sind wir?
5. **Minimum 5 Peers** für relativen Vergleich — sonst kein Ranking möglich
6. **Ergebnis immer mit Unsicherheit** — "Screening sagt X, aber DCF fehlt"

---

## Fehler-Log (damit ich lerne)

| Datum | Fehler | Lektion |
|---|---|---|
| 25.03.2026 | FRO empfohlen ohne Technik-Check → schwächster Tanker | Immer Peer-Vergleich VOR Empfehlung |
| 25.03.2026 | PBF "Score +8" trotz negativer Margin | Disqualifikation eingebaut |
| 25.03.2026 | DINO als Top 3 trotz 0.9% Margin | Margin unter Branchenmedian = schlecht |
| 25.03.2026 | Absolute P/E-Schwellen statt Branchenvergleich | Jetzt: alles relativ zum Sektor-Median |
| 25.03.2026 | Kein FCF-Check | FCF-Analyse als eigene Stufe eingebaut |

## Fehler-Log (Fortsetzung)

| Datum | Fehler | Lektion |
|---|---|---|
| 25.03.2026 | Ust-Luga Angriff: Kurzschluss-Analyse ohne Faktencheck. EU-Sanktionen ignoriert, Tanker-These recycled die wir gerade fallen gelassen hatten, EQNR als "neue Erkenntnis" verkauft obwohl es die Basis-These war. | **NEUE REGEL: Bei Breaking News ERST Fakten prüfen (wer ist betroffen, welche Handelsströme, welche Sanktionen gelten), DANN gegen eigenes gespeichertes Wissen abgleichen, DANN erst bewerten.** Nie reflexartig Portfolio-Impact schreiben. |
