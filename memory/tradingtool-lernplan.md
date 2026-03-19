# TradeMind — Learning System Roadmap
*Stand: 13.03.2026 | Albert + Victor*

---

## Was wir heute haben (Baseline)

- NewsWire: News-Erfassung + Keyword-Match + SQLite
- Price Tracker: T=0, T+4h, T+1d + outcome-Feld
- Trade Logger: Entry/Exit + Conviction Score (5 Faktoren)
- Analyst Cron: Haiku-Analyse alle 30 Min → newswire-analysis.md

---

## Phase 1 — Datenqualität (Woche 1–4)
*Alles danach ist wertlos wenn die Daten schlecht sind*

### P1.1 — News-Deduplication (KRITISCH)
**Problem:** Gleiche Reuters-Story erscheint in Bloomberg RSS + 3 Google Queries
→ F4 "News-Momentum" zählt 4 Events aber es ist 1 Geschichte
→ Conviction Score wird künstlich aufgeblasen

**Fix:** URL-Hash + Headline-Fingerprint beim Eintragen prüfen.
Wenn >80% Ähnlichkeit → gleicher Event, kein neuer DB-Eintrag.
`difflib.SequenceMatcher` reicht völlig.

**Impact:** Conviction Score wird deutlich genauer.

---

### P1.2 — VIX-Regime Integration (KRITISCH)
**Problem:** Ein bullish EQNR-Signal bei VIX 15 ist ein Setup.
Dasselbe Signal bei VIX 35 ist Rauschen — alle Aktien fallen im Crash.
Das System macht aktuell keinen Unterschied.

**Fix:** VIX als F5 in Conviction Score.
- VIX < 20: +1 (grünes Licht)
- VIX 20–25: 0 (neutral)
- VIX 25–30: –1 (Vorsicht)
- VIX > 30: –2 (kein Entry egal was die News sagen)

Yahoo Finance: `^VIX` alle 30 Min im Price Tracker holen.
In DB: `macro_context`-Tabelle mit Timestamp + VIX + DXY + Brent.

**Impact:** Verhindert, dass das System in Crashphasen falsche Signale gibt.

---

### P1.3 — Trade Journal Disziplin (KRITISCH)
**Problem:** Ohne echte Trades in der DB lernt das System nichts über Strategie-Qualität.
Keyword-Accuracy sagt: "die News hatte Recht".
Aber war das auch ein gutes Setup? War der Einstieg sauber? Wurde die Regel gehalten?

**Lösung:** Jeden Trade sofort loggen. Kein Trade ohne DB-Eintrag.
Format für Victor: `"EQNR long 28.40 Stop 27 S1"`
Albert verknüpft automatisch die letzten 5 NewsWire-Events für diesen Ticker.

**Impact:** Erst ab ~20 geloggten Trades wird das System statistisch auswertbar.

---

### P1.4 — Sentiment-Magnitude (mittlere Prio)
**Problem:** Aktuell nur binär: bullish / bearish.
"Iran kündigt Hormuz-Schließung an" und "Ölpreis steigt leicht" sind beide "bullish".
Das ist nicht dasselbe.

**Fix:** Score 1 = mildly bullish/bearish, Score 3 = strongly bullish/bearish
Bestimmt aus Wörtern: "vows", "strikes", "threatens" > "suggests", "hints", "slightly"
Einfache Keyword-Stärke-Gewichtung, kein LLM nötig.

---

## Phase 2 — Signalqualität (Monat 2–3)
*Braucht ~500 Events und ~20 Trades als Grundlage*

### P2.1 — Keyword Auto-Weighting
Nach 4 Wochen: Welche Keywords haben tatsächlich Kursbewegungen ausgelöst?

```python
# Beispiel-Query nach 4 Wochen:
SELECT keyword, AVG(price_move_4h), COUNT(*), accuracy_pct
FROM keyword_events
GROUP BY keyword
ORDER BY accuracy_pct DESC
```

Keywords mit < 50% Trefferquote → Gewichtung halbieren
Keywords mit > 75% Trefferquote → Gewichtung verdoppeln

**Automatisch aktualisiert** durch wöchentlichen Cron.
Kein manuelles Eingreifen nötig.

---

### P2.2 — Setup-Score → P&L Korrelation
Kernfrage: **Führen High-Conviction Scores (4–5) tatsächlich zu besseren Trades?**

```
Conviction 5: Avg P&L = +X%, Win-Rate = Y%
Conviction 3: Avg P&L = +X%, Win-Rate = Y%
Conviction 1: Avg P&L = +X%, Win-Rate = Y%
```

Wenn Conviction 5 nicht besser performt als Conviction 2 → Scoring-Modell überarbeiten.
Wenn korreliert → Conviction-Schwelle für Entry erhöhen (nur noch >3 traden).

---

### P2.3 — Zeitliche Muster
Macht es einen Unterschied wann die News kommt?

- Pre-Market (06:00–09:00): News wird "eingepreist" bis Xetra öffnet → Entry am Open oft teurer
- Intraday (09:00–17:30): Direktere Reaktion, mehr Volatilität
- Post-Market (17:30–22:00): US-Session bestimmt Eröffnung morgen

Einfache Spalte `time_bucket` in events-Tabelle:
`pre_market / intraday / post_market / overnight`

---

### P2.4 — Negative Space Tracking
**Problem bisher komplett ignoriert:**
Was ist wenn EQNR sich stark bewegt, aber KEIN NewsWire-Event gefeuert hat?

→ Das zeigt: Es gibt einen wichtigen Treiber den unsere Keywords nicht erfassen.
→ Lösung: Täglich Kursbewegungen >2% ohne DB-Match tracken → zeigt Keyword-Lücken.

Cron täglich 22:00: Prüfe alle Portfolio-Ticker → Bewegt sich was ohne Headline?
→ Flag als "unexplained move" → Albert schaut manuell nach → Keyword ergänzen.

---

## Phase 3 — Strategieentwicklung (Monat 3–6)
*Braucht valide Daten aus Phase 1+2*

### P3.1 — Evidenzbasierte Entry-Regeln
Nicht mehr: "Ich glaube EQNR bei Hormuz-News ist gut"
Sondern: "In den letzten 3 Monaten: EQNR long bei hormuz-direct + conviction ≥ 4 + VIX < 22 → 78% Win-Rate, Avg +3.2%, Max Drawdown –1.8%"

Das ist eine **Regel** die aus Daten entstanden ist.
Wird ins `strategien.md` übertragen mit Konfidenz-Level und Datenbasis.

---

### P3.2 — Optimale Position Sizing
Aktuell: Victor entscheidet Positionsgröße nach Gefühl.

Datenbasiert:
```
Conviction 5, VIX < 20, Sektor im Aufwärtstrend → 3% Portfolio
Conviction 3, VIX 22, keine Leading-Indicator-Bestätigung → 1% Portfolio
Conviction < 3 → nicht handeln
```

Basiert auf historischer Volatilität der Aktie + Korrelation zu anderen Positionen.

---

### P3.3 — Backtesting Framework
Gegeben: alle Events der letzten 3 Monate + tatsächliche Kursentwicklung.
Frage: Was wäre passiert wenn wir bei jedem High-Conviction Signal gehandelt hätten?

Kein Live-Trading — reines Data-Replay.
Zeigt: Welche Strategien hätten funktioniert, welche nicht.

---

## Phase 4 — Autonome Empfehlungen (Monat 6–12)

### P4.1 — Strategy DNA Dokument (auto-updated)
`strategien.md` wird nicht mehr manuell gepflegt.
Sonnet schreibt es weekly neu basierend auf:
- Keyword-Accuracy-Daten
- Trade-Outcome-Daten
- Marktregime (VIX, Sektor-Trends)

### P4.2 — Echtzeit-Empfehlungen
Bei High-Conviction Event (Score ≥ 4, VIX < 22):
System generiert automatisch:
- Ticker + Richtung
- Evidenzbasierter Entry-Bereich
- Stop-Vorschlag (aus historischer Volatilität)
- CRV aus historischen Avg Win/Loss
- Konfidenz: "74% Win-Rate auf Basis von 28 ähnlichen Setups"

### P4.3 — Portfolio-Korrelation automatisch
Nie zwei stark korrelierte Positionen gleichzeitig mit vollem Risiko.
(NVDA + MSFT + PLTR alle gleichzeitig = nicht 3× Risiko, sondern quasi 1 Position)
Automatische Korrelations-Matrix aus historischen Kursdaten.

---

## Offene kritische Fragen

1. **Wie misst man Strategie-Qualität fair?**
   Nicht nur P&L absolut — sondern risikobereinigt (Sharpe Ratio äquivalent).
   Ein Trade mit +1% Gewinn bei 0.3% Risk ist besser als +3% bei 2% Risk.

2. **Was ist der Benchmark?**
   Schlägt das System einen simplen "Buy & Hold SPY"?
   Wenn nicht — warum aktiv traden?
   Diese Frage muss das System beantworten können.

3. **Wann ist genug Daten genug?**
   Statistisch: >30 Trades pro Setup für valide Aussagen.
   Realistisch: 3–6 Monate aktives Trading mit konsequentem Logging.

---

## Sofort-Prioritäten (diese Woche)

| # | Task | Impact | Aufwand |
|---|------|--------|---------|
| 1 | P1.1 News-Dedup bauen | Hoch | 1h |
| 2 | P1.2 VIX in Price Tracker | Hoch | 1h |
| 3 | P1.3 Erste Trades loggen | Kritisch | 0 (Disziplin) |
| 4 | P1.4 Sentiment-Magnitude | Mittel | 2h |
| 5 | P2.4 Negative Space Cron | Mittel | 1h |

---

## Learning 19.03.2026 — Macro-Signal → Strategie-Menu

**Auslöser:** Nikkei −3.4% Warnung (09:15) → RIO.L −6.2% (13:50) ✅ Korrekt

**Was gut war:** Warnung wurde ausgegeben.

**Was Victor will:** Bei Macro-Signalen nicht nur warnen, sondern sofort eine vollständige Analyse + Strategie-Menu liefern.

### Standard-Template für Macro-Signal-Analyse

Wenn ein Macro-Frühindikator (Nikkei, VIX-Spike, Brent-WTI Spread, etc.) ausgelöst wird:

**1. Warum ist das relevant? (1–2 Sätze)**
Nicht nur "Nikkei fällt" sondern: "Nikkei fällt → Asien-Industrienachfrage sinkt → Eisenerz/Kupfer unter Druck → Rohstoffproduzenten (RIO, GLEN, BHP) direkt betroffen"

**2. Welche Positionen sind betroffen?**
Konkret mit Ticker + aktueller Stop-Distanz

**3. Strategie-Menu (immer 3 Optionen):**
- 🟢 **Halten + Stop enger**: wenn Thesis noch intakt, aber Risiko begrenzen
- 🟡 **Teilverkauf**: wenn Signal stark, aber Grundthesis überlebt
- 🔴 **Exit**: wenn Signal die Kern-Thesis direkt trifft

**4. Wahrscheinlichkeit + Zeitrahmen:**
"Hohes Risiko intraday, wenn Nikkei −3%+ ohne Erholung bis 12:00"

**5. Lernziel:**
Dieses Format soll Macro-Warnungen zu echten Entscheidungshilfen machen — nicht nur Alarme.

### Bereits bewährte Macro-Indikatoren
- **Nikkei 225 (^N225) < −2%** → Rohstoffe (RIO, GLEN, BHP, EQNR) unter Druck
- **Brent-WTI Spread > $10** → struktureller Öl-Lieferengpass → EQNR/OXY bullisch
- **VIX > 28** → Breite Panik, Tech-Positionen gefährdet, Stops zu eng
- **USD/JPY stabil trotz Nikkei-Fall** → kein globaler Crash, nur Sektor-Rotation
