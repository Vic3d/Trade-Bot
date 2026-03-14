# Trading Tool — Feature Backlog

**Zweck:** Jede Reibung im täglichen Trading sofort loggen. Jeder Schmerzpunkt = ein Feature.
**Regel:** Wenn Victor sagt "das nervt" oder "das hätte ich früher gebraucht" → sofort hier rein.

---

## 🔴 Prio Hoch (echte Reibung erlebt, KW11 bestätigt)

### 1. Echtzeit-Newsfeed (KRITISCH) — **MUSS diese Woche fixen**
- **Problem:** Bloomberg/Google RSS hat 30–60 Min Lag
- **Fallbeispiel 10.03.2026:** Hormuz-Falschinformation (Chris Wright Post) löste Öl-Crash aus
  - Albert zitierte News die 1h alt waren
  - Stop bei DR0.DE wurde ausgelöst bevor Korrektur der Falschinformation ankam
- **Lösung nötig:** <5 min Delay (Finnhub.io 60 calls/min, Polygon.io 5 calls/min)
- **Status:** Finnhub-Integration geplant 14.03.2026

### 2. Mental Stops sind nicht echte Stops — **RHM.DE Lektion KW11**
- **Problem:** RHM.DE Entry 1.635€, Stop 1.595€ war nur notiert (nicht in TR)
- **Konsequenz:** Position bei 1.563€ geschlossen (−4,4%), hätte nicht sein müssen
- **Lektion:** Stops MÜSSEN real in Trade Republic als Limit-Sell Ordern sein
- **Lösung:** Automatischer Stop-Sell-Order bei jedem Kauf setzen + UI-Warnung

### 3. Stop-Orders bei Bruchteilen (Fractional Shares)
- **Problem:** Trade Republic erlaubt keine Stop-Loss-Orders bei Bruchteilen
- **Betroffen:** Teure Aktien (RHM.DE ~1.635€, ASML ~1.200€, Booking ~5.000€)
- **Lösung:** Mental-Stop-Engine (KI übernimmt Monitoring alle 5–10 Min)
- **Priorität für TradeMind:** Autonomous-Mode Feature #1

- **Datenquellen-Manager:** Yahoo Finance hat 15-20min Delay für deutsche Nebenwerte (DR0.DE, BAYN.DE, RHM.DE). Onvista.de liefert live. Tool muss automatisch beste Quelle je nach Börsenplatz wählen. (09.03.2026)
- **Cron Delivery — `channel:last` Bug:** `channel: "last"` ohne `to` → Discord-Delivery schlägt fehl wenn letzter Kanal Discord war. Fix: Agent nutzt `message`-Tool direkt statt `announce` zu vertrauen. (09.03.2026)
- **Strategie-Thesis-Tracking:** Manuelle Strategiedateien (strategien.md) sind gut, aber brauchen automatischen News-vs-Thesis-Check. Intraday-Cron (11:30 + 14:30) löst das. (09.03.2026)
- **Proaktivität vs. Spam:** Agent war zu reaktiv — wartete auf Fragen statt selbst zu melden. Regel eingebaut: nur bei Handlungsbedarf melden. (09.03.2026)
- **Modell-Effizienz:** Einfache Preis-Alert-Crons (fetch → compare → notify) liefen mit Sonnet — Haiku völlig ausreichend, ~80% Kostenersparnis. (09.03.2026)
- **Timeout-Kalibrierung:** 30s Timeout für Cron-Alert-Jobs zu knapp bei Serverlast. 60s ist robuster. (09.03.2026)
- **P&L Berechnung US-Aktien:** IMMER USD-Kurs ÷ aktueller EURUSD=X → dann gegen EUR-Entry vergleichen. NIE USD-Kurs direkt gegen EUR-Entry — das ist falsch! (09.03.2026)

- **VIX-Ampel im Dashboard:** Sofort sehen ob Markt grün/gelb/orange/rot ist — ohne suchen
- **Relative Stärke automatisch:** Jede Position zeigt automatisch wie sie vs. Nasdaq performt (diese Woche, diesen Monat)
- **Power of Three Scanner:** Welche Aktien haben gerade EMAs eng zusammen? → täglich automatisch scannen
- **EMA-Abstände anzeigen:** Kurs X% über/unter EMA10/20/50 — direkt sichtbar ohne rechnen
- **News-Scanner:** Automatisch relevante Nachrichten zu aktiven Positionen tracken (OPEC+, Earnings, Geopolitik) — nur portfolio-relevante News filtern und melden. Beispiel: Kuwait drosselt Ölförderung → Alert für EQNR + DR0 Halter

## 🟡 Prio Mittel (wäre nice to have)

- **Stop-Abstand automatisch anzeigen:** Kurs und Stop eingeben → % Abstand sofort sichtbar
- **EUR-Anzeige immer:** EQNR in NOK verwirrt — immer automatisch in EUR umrechnen und anzeigen
- **FX-Rate immer sichtbar:** EUR/USD und EUR/NOK permanent im Dashboard
- **Öl-Überdehnung Alert:** Wenn Öl >20% über EMA50 → automatischer Makro-Kontext Alert
- **VIX-Trend:** nicht nur aktueller VIX sondern 5-Tage-Veränderung — steigt oder fällt die Angst?

## 🟢 Prio Niedrig / Ideen

*(wird gefüllt)*

---

## ✅ Umgesetzt
*(wird gefüllt wenn Entwicklung startet)*
