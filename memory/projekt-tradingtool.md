# Projekt: Trading Tool (Arbeitstitel: "TradeMind")

**Angelegt:** 2026-03-07 | **Zuletzt aktualisiert:** 2026-03-09
**Status:** 🌱 Phase 1 — Lernphase (aktiv)
**Beteiligte:** Victor (Lead), Albert (Proto-Tool + Dokumentation)
**Ziel:** Beste Retail-Trading-App der Welt. Start als persönliches Tool, Vermarktung ~2027.

---

## 🎯 Vision & USP

### Das Produkt
> *"Die erste Plattform wo eine KI mit deinem Geld handelt — transparent, nachvollziehbar, lernend. Du schaust zu, du lernst, du wirst besser."*

**Drei USP-Ebenen:**
1. **Einzigartig:** Autonomes KI-Trading für Retail — mit vollem Audit-Log, KI erklärt jede Entscheidung
2. **Strategie-Quelle:** KI entwickelt Strategien eigenständig (Marktanalyse, Frameworks, Setups) — Nutzer executes, wird besser dadurch. NICHT: KI repliziert Nutzer-Muster. (Korrigiert 13.03.2026)
3. **Brücke:** Bloomberg-Level Analyse. Trade Republic Einfachheit. Retail-Preis.

### Zwei Zielgruppen — ein Produkt (selten!)

```
Einsteiger:       "Ich lerne traden — die KI zeigt mir wie"
                  → Mentor Mode, Onboarding, Psychology Score, Erklärungen

Fortgeschritten:  "Ich trade schon — die KI macht es effizienter"
                  → Autonomous Mode, Screener, API, Attribution, Webhooks
```

Beide Gruppen nutzen dasselbe Produkt — unterschiedliche Features im Vordergrund.
Upgrade-Pfad: Einsteiger → lernt durch Mentor Mode → wird fortgeschritten → wechselt zu Autonomous.

---

### Marktlücke
| Tool | Stärke | Schwäche |
|---|---|---|
| TradingView | Beste Charts | Kein Broker, keine KI |
| Trade Republic | Einfaches Trading | Null Analyse |
| eToro | Copy Trading | Gamified, oberflächlich |
| Bloomberg Terminal | Professionell | $24.000/Jahr, unbenutzbar für Retail |
| Robinhood | UX | Keine echte Analyse |

**Niemand kombiniert:** Professionelle Analyse + autonomes KI-Trading + lernende Strategie für Retail.

---

## 🤖 KI — Zwei Modi

### Modus 1: Advisory KI
- Analysiert Markt, schlägt konkrete Trades vor (Entry, Stop, Ziel, Strategie, Begründung)
- Victor/Nutzer entscheidet ob er handelt
- KI lernt aus Entscheidungen des Nutzers → wird besser darin seinen Stil zu verstehen
- Kein Zeitdruck, Nutzer reagiert wann er will

### Modus 2: Autonomous KI
- Nutzer gibt KI ein separates Budget (komplett getrennt vom manuellen Portfolio!)
- KI handelt **nur während Börsenöffnung** vollständig selbstständig
- Entwickelt eigene Strategie, optimiert sich kontinuierlich
- **Mental Stop Loss:** KI setzt sich selbst Stops (keine echten Stop-Orders beim Broker) → monitort Preis live → verkauft automatisch wenn Mental Stop erreicht
- Kill-Switch jederzeit für Nutzer
- Vollständiger Audit-Log: jede Entscheidung mit Begründung

**Mental Stop Technisch:**
- Polling alle 30-60 Sekunden während Börsenöffnung
- Netzwerk-Failsafe: bei 3x Datenfehler → Position schließen + Alert
- Gap-Handling: Kurs springt unter Stop (Overnight) → sofort zum Marktpreis verkaufen

**KI Strategie-Entwicklung (3 Phasen):**
```
Phase A — Regelbasiert:
KI handelt nach definierten Regeln (Dirk 7H etc.)
Kein Lernen, nur Ausführung → Basis-Benchmark

Phase B — Lernend:
KI optimiert Parameter aus eigener Trade-History
Backtesting gegen eigene Daten
→ Wird besser als Regelversion

Phase C — Eigenständig:
KI entwickelt eigene Muster die kein Mensch formuliert hätte
→ Echter autonomer Trader
```

---

## 💡 Feature-Set

### Core Features
- **Portfolio Dashboard** — Kurse, P&L, offene Positionen, Stops (manual + KI getrennt)
- **Smart Alerts** — Stop-Gefährdung, Kaufsignale, KI-Aktionen
- **Trade Journal** — jeder Trade automatisch geloggt: Entry, Exit, Grund, P&L, Strategie
- **Performance Analytics** — Trefferquote pro Strategie, Ø R/R, beste/schlechteste Setups
- **TR Integration** — Trade Republic inoffizielle API, später direkte Order-Platzierung

### KI Features
- **Advisory Mode** — Vorschläge mit Begründung
- **Autonomous Mode** — eigenes Budget, eigene Strategie, Mental Stops
- **Mentor Mode** — KI erklärt jede Entscheidung wie ein Trading-Coach
- **Strategy DNA** — KI analysiert alle Trades des Nutzers, erstellt persönliches Strategie-Profil
- **Emotional Trading Detector** — erkennt Revenge Trades, FOMO, Abweichungen von Strategie

### Analyse Features
- **Screener** — High Volume Breakout automatisch scannen (Gap >5%, Vol >2x, Katalysator)
- **Market Regime Detection** — Bull/Bear/Sideways, Risk-On/Risk-Off, Volatilität → KI passt Verhalten an
- **Scenario Engine** — "Was passiert mit Portfolio wenn Öl auf $110 steigt?"
- **Korrelations-Matrix** — zeigt ob Positionen zu korreliert sind
- **Makro-Dashboard** — Öl, VIX, Nasdaq-Trend, DXY, Gold, Sektor-Rotation
- **Earnings Calendar** — KI handelt nicht blind in Earnings-Nächte
- **Makro-Kalender** — Fed, CPI, NFP → erhöhte Volatilität einkalkulieren
- **KI-Marktbriefing** — scannt Quellen, filtert was für Portfolio relevant ist, fasst zusammen
- **Risk Score** — Echtzeit-Risiko-Score 1-100 (Konzentration, Korrelation, fehlende Stops)

### Power Features (für Profis)
- **Natural Language Trading** — "Kauf NVDA wenn unter $175 mit Stop $170" → KI setzt um
- **Dark Pool Detection** — ungewöhnliche Volumenmuster vor der Bewegung erkennen
- **Insider-Filing Tracker** — SEC Form 4, US-Insider-Käufe automatisch gescannt
- **Backtesting Engine** — Strategie gegen historische Daten testen
- **Paper Trading Modus** — neue Strategien risikolos simulieren (parallel zu Live)
- **Strategy Versioning** — wie hat sich KI-Strategie entwickelt? welche Änderung brachte was?
- **Parallelbetrieb** — Paper-Spur (neue Strategien) + Live-Spur (bewährte Strategie) gleichzeitig

### Risiko-Framework (Autonomous Mode)
- Max Drawdown: z.B. -15% vom KI-Budget → automatischer Stop
- Max Position Size: z.B. 20% des KI-Budgets pro Trade
- Max offene Positionen: z.B. 5 gleichzeitig
- Positions-Sizing Algorithmus: Entry/Stop-Abstand × Budget × Risiko% = Positionsgröße
- Kein Hebel bis KI nachweislich profitabel (mind. 6 Monate Paper/Live)
- Liquiditäts-Check: Mindestvolumen vor jedem Trade

### Steuer-Tracking (Deutschland — Pflicht!)
- FIFO-Kostenbasis automatisch tracken
- After-Tax P&L anzeigen (nicht nur Brutto)
- Steuerlast Echtzeit: "X€ Gewinne → Y€ Steuer fällig"
- Jahresreport für Steuerberater (CSV/PDF Export)
- Tax-Loss Harvesting Vorschläge: "Verkauf X spart dir Y€ Steuern durch Verlustverrechnung"
- Kein deutsches Retail-Tool macht das gut → Alleinstellungsmerkmal

### Performance Attribution
- Welche Trades haben am meisten zum Gewinn beigetragen?
- Trefferquote pro Strategie: Fishhook vs. HVE vs. EMA-Rücklauf vs. Inside Day
- Bester Sektor für diesen Nutzer
- Alpha vs. Benchmark (Nasdaq, S&P500) — schlage ich den Markt?
- Direkte Datenbasis für Strategy DNA

### Trading Psychology Score
- Tageszeit-Analyse: wann macht Nutzer schlechte Entscheidungen?
- Post-Loss Performance: Revenge Trading Pattern erkennen
- Strategie-Abweichungsrate: wie oft weicht Nutzer von eigenem Plan ab?
- Wöchentlicher Score mit konkreten Verbesserungshinweisen
- **Produkt-Narrativ:** nicht nur Trading Tool — "Werde ein besserer Trader"

### Trade Import (CSV)
- Bestehende Trade-History aus TR, Scalable etc. als CSV importieren
- Sofortiger Mehrwert am ersten Tag
- Strategy DNA startet nicht bei Null (kein Cold Start Problem)
- Unterstützte Formate: Trade Republic CSV, Scalable Capital, IBKR

### Multi-Channel Notifications
- Push Notification (App)
- WhatsApp / Telegram Bot
- Email Digest (täglich/wöchentlich konfigurierbar)
- Discord Integration (für Community später)
- Prioritätssystem: Stop Loss = sofort überall | Tages-Summary = Email

### API / Webhook System (Power User)
- Webhook bei Alert-Trigger → eigene Automatisierungen möglich
- REST API für eigene Scripts
- Zapier / Make Integration
- Schafft Ökosystem: Power User bleiben wegen eigener Integrationen

### Onboarding Flow (Produkt)
- Quiz beim Start: Trader-Typ, Risikobereitschaft, Zeit pro Tag
- Sofort personalisiertes Dashboard basierend auf Antworten
- Geführter erster Trade Journal Eintrag
- Tutorial mit echten Märkten: "Dein erstes Setup"
- Schlechtes Onboarding = Churn. Gutes Onboarding = Lifetime Customer.

### Später / Produkt
- **Multi-Broker Support** — nicht nur TR, auch IB, Scalable etc.
- **Strategy Marketplace** — Trader veröffentlichen Strategien, Top-Performer verdienen %
- **Options-Tracking** — Hedging-Strategien visualisieren
- **Alert-Hierarchie** — Push + WhatsApp für Kritisches, nur App-Notification für Info

---

## 💰 Monetarisierung (ab 2027)

```
Free Tier:
→ Portfolio Tracking, Basic Alerts, 1 Strategie

Pro (~15€/Monat):
→ KI Advisory, Screener, Scenario Engine,
  Mentor Mode, alle Strategien, Trade Journal

Autonomous (~29€/Monat + 10% der KI-Gewinne):
→ KI handelt autonom mit eigenem Budget
→ Performance Fee nur bei Gewinn (fair!)

Enterprise (später):
→ Strategy Marketplace, White-Label, API-Zugang
```

---

## 🔌 Broker-Strategie

### Persönliche Nutzung (Phase 1–2)
- **Trade Republic** inoffizielle API — akzeptables Risiko für privaten Gebrauch
- Kein stabiles Fundament für kommerzielles Produkt

### Produkt (ab Phase 5)
- **Interactive Brokers (IBKR)** als offizieller Broker-Backbone
  - Vollständige offizielle TWS API — stabil, dokumentiert, kostenlos
  - Alle Märkte: NYSE, NASDAQ, Xetra, Oslo Børs — komplette Abdeckung
  - Paper Trading eingebaut (Pflicht für KI-Test-Phase)
  - Professioneller Standard (Hedgefonds bis Retail)
  - Nutzer öffnet IBKR-Account → linked mit dem Tool
- **Alpaca** als Fallback für rein US-lastige Features (hat kein Xetra)
- **Strategie:** Victor handelt privat weiter über TR. Die App-KI läuft über IBKR.

### Auslands-Registrierung (bei Launch)
- Estland (e-Residency) — einfach, günstig, EU-konform, beliebt bei Fintechs
- Alternativ: Malta (EU, fintech-freundlich)
- Erst relevant wenn Launch konkret wird — in Phase 1 noch kein Thema

---

## 🎯 Expansion-Strategie: Trader-Typen

### Prinzip: Strategy Packs
Nicht das Tool neu bauen für jeden Trader-Typ. Stattdessen modulare Strategy Packs on top einer gemeinsamen Core-Infrastruktur:

```
CORE (für alle Trader-Typen):
→ Portfolio, Daten, Alerts, Trade Journal, KI-Engine, Backtesting

Strategy Pack "Swing Trading"  → Phase 1 — Dirk 7H Methodik
Strategy Pack "Growth"         → Phase 2 — Fundamentaldaten, DCF
Strategy Pack "Day Trading"    → Phase 3 — Realtime, Orderbook
Strategy Pack "Options"        → Phase 4 — Delta/Gamma/IV
```

Nutzer wählt Stil beim Onboarding. KI passt sich automatisch an. Neuer Trader-Typ = neues Pack, kein Rewrite der Core-Infrastruktur.

### Expansion-Reihenfolge

**Stufe 1 — Swing Trading (2026–2027) ← WIR SIND HIER**
- Dirk 7H Methodik vollständig kodiert
- EMA 10/20/50/200, Relative Volume, Pattern-Erkennung
- Haltedauer Tage bis Wochen → kein Echtzeit-Tick nötig
- Yahoo Finance 15min Delay reicht aus
- Ziel: Für Victor perfekt → für jeden Swing Trader perfekt

**Stufe 2 — Growth Investing (2027–2028)**
- Längere Haltedauer (Wochen bis Monate)
- Fundamentaldaten im Fokus: KGV, EPS-Wachstum, Margen, DCF
- Gleiche Infrastruktur, andere Analyse-Overlays
- Kleinster Sprung von Swing Trading

**Stufe 3 — Day Trading (2028+)**
- Anderes Spiel: echte Realtime-Daten (ms), Level 2 Orderbook
- Neue Infrastruktur nötig → erst wenn Core-Produkt stabil + profitabel
- Höchste technische Komplexität

**Stufe 4 — Options (später)**
- Komplett eigenes Universum: Delta, Gamma, IV, Strategien (Straddles etc.)
- Eigenes Produkt-Modul, nicht nur ein Pack
- Langfristige Vision

---

## 🏗️ Tech-Stack

- **Frontend:** Next.js (Web-first, später React Native für Mobile)
- **Backend:** Python + FastAPI (alle Finanz-Libraries in Python zuhause)
- **Datenbank:** PostgreSQL (Trade Journal, History, Strategie-Versionen)
- **Echtzeit:** WebSockets für Live-Preise + Alert-Delivery
- **Dataquellen:**
  - Yahoo Finance API (Primär, kostenlos, 15min Delay — reicht für Swing Trading)
  - Polygon.io oder Alpha Vantage (Fallback + Real-Time für Autonomous Mode)
- **News-Quellen (kostenlos, bereits getestet 07.03.2026):**
  - Google News RSS → spezifische Themen-News, deutsche Qualitätsmedien (NZZ, Spiegel, Handelsblatt, tagesschau), mehrere Quellen = höhere Glaubwürdigkeit
  - Yahoo Finance News Search → allgemeine Marktstimmung, schnelle Headlines
  - Prinzip: Nachricht die in beiden Quellen erscheint = glaubwürdiger als Einzelquelle
- **Broker:** Trade Republic inoffizielle API (Python-Library)
- **KI:** regelbasiert → LLM-gestützte Analyse → autonomes Trading (schrittweise)

---

## 🗺️ Roadmap

### ✅ Phase 1 — Lernphase (März–Juni 2026)
**Kein Code. Wissen aufbauen. Aktiv lernen — nicht nur passiv beobachten.**

**Strukturiertes Trade Journal (ab sofort, jeder Trade):**
```
Datum | Ticker | Strategie (Fishhook/HVE/EMA-Rücklauf/Inside Day/...)
Entry | Stop | Ziel | Positionsgröße | Marktregime
Begründung: warum dieser Trade? (1 Satz)
Exit: Grund (Stop/Ziel/Manuell)
Nachher: Was lief gut? Was falsch?
```
→ Datenschatz für Backtesting + Strategy DNA. Was jetzt nicht geloggt wird, fehlt später.

**Hypothesen formulieren und tracken:**
- Aktiv Thesen aufstellen: "Fishhook funktioniert besser nach Earnings"
- Nach 10+ Trades auswerten → bestätigt? → ins Tool übernehmen
- Datei: `memory/trading-hypothesen.md`

**Dirk 7H Predictions tracken:**
- Was empfiehlt er? → ich logge
- Was ist eingetreten? → ich tracke
- Trefferquote pro Setup nach 3 Monaten → KI-Gewichtung later
- Datei: `memory/dirk-predictions.md`

**Benchmark-Tracking:**
- Victors P&L monatlich vs. QQQ (Nasdaq ETF)
- Frage: schlage ich den Markt? Mit welchem Aufwand?
- Basis für später: lohnt sich KI vs. passives Investieren?

**Feature-Backlog (laufend):**
- Jede Reibung sofort loggen: "Das hat mich genervt" → wird Feature
- Datei: `memory/tradingtool-features.md`
- Jede Reibung die Victor spürt = Feature das Nutzer später lieben

**Albert als aktiver Screener:**
- Jeden Morgen (Mo–Fr): HVB-Kandidaten nach Dirk 7H Kriterien scannen
- Kandidaten melden → Victor entscheidet
- Tracken ob Kandidaten gewonnen hätten → Screener-Qualität messen
- Nach 3 Monaten: wie gut ist Alberts Screener? → Basis für Advisory Mode

**Wöchentliche Review-Session (Samstags ~10:00):**
- Albert bereitet Zusammenfassung vor: Trades, Performance, Learnings
- Victor gibt Feedback
- Neue Hypothesen formulieren
- Feature-Backlog reviewen
- ~30 Minuten — maximales Learning

**Laufende Dokumentation:**
- Welche Alerts waren nützlich vs. Lärm?
- Welche manuellen Schritte nerven → werden Features
- Welche Daten fehlen mir gerade?
- Welche TR API Endpunkte werden gebraucht?

**Ziel:** Vollständiges Lastenheft aus echten Erfahrungen + strukturierter Datenschatz für Backtesting.

### Phase 2 — MVP (Juni–August 2026)
**Web-App, nur für Victor.**
- Portfolio Dashboard (Kurse, P&L, Stops)
- Smart Alerts (was Albert jetzt manuell macht)
- Trade Journal
- TR API eingebunden (Monitoring, noch keine Orders)
- Basic KI Advisory (regelbasiert)

### Phase 3 — Intelligence (August–Oktober 2026)
- Screener (High Volume Breakout automatisiert)
- Makro-Dashboard + Earnings Calendar
- Mehrere Strategien wählbar
- Backtesting Grundgerüst
- Mentor Mode
- Strategy DNA Grundgerüst

### Phase 4 — Autonomous KI (Oktober–Dezember 2026)
- Paper Trading Modus
- KI handelt nach Regeln, Mental Stop Engine
- Market Regime Detection
- Erst nach 2-3 Monate Paper → Live mit kleinem Budget
- Vollständiger Audit-Log

### Phase 5 — Produkt Launch (2027)
- Multi-User Architektur
- Freemium Modell live
- Beta für externe Nutzer
- BaFin-Klärung (autonomes Trading, Finanzberatung)
- Strategy Marketplace Konzept
- Marketing

---

## 📥 Report-Verarbeitungs-Protokoll

**Wenn Victor einen externen Report/Transcript schickt (Dirk 7H, Eriksen, etc.):**

1. **Analyse:** Kernthesen extrahieren, auf Victors aktuelle Positionen anwenden
2. **Eigene Einschätzung:** Unabhängig bewerten — stimme ich zu? Wo weiche ich ab? Warum?
3. **Learnings extrahieren:** Neue Patterns, Regeln, Konzepte → in "Muster die algorithmisch erkennbar sein müssen"
4. **Watchlist/Portfolio updaten** wenn neue Kandidaten oder neue Info zu bestehenden Positionen
5. **NICHT dauerhaft speichern:** Momentaufnahmen (Marktmeinung, aktuelle Kurse) bleiben nicht in Langzeitgedächtnis — nur die Methodik

**Quellen bisher:**
- Dirk 7H / Tradermacher → Technische Analyse, Swing Trading Setups, Patterns
- Lars Eriksen / Eriksen Geld und Gold → Makro, Geopolitik, Szenarien

---

## 📝 Learnings aus Lernphase

*(wird laufend gefüllt)*

### Alerts & Monitoring
- Trailing Stop Review NUR nach Tagesschluss — intraday ist Overtrading-Trigger
- NVDA Zwei-Stufen-Alert ($180/$190) → granulare Setup-spezifische Alerts sind wertvoll
- Nachts (23-08 Uhr) komplett still außer Stop Loss ausgelöst

### Daten
- Yahoo Finance 15min Delay reicht für Swing Trading aus
- FX-Umrechnung Pflicht: USD/EUR, NOK/EUR separat abrufen
- EQNR.OL in NOK, dann ÷ EURNOK=X für EUR-Preis
- **Onvista.de für deutsche Aktien (Pflicht!):** Yahoo Finance hat 15-20min Delay für Xetra-Werte (DR0.DE, BAYN.DE, RHM.DE). Onvista.de liefert Echtzeit-Kurse.
  - Scraping: `re.findall(r'"last":([0-9.]+)', html)` auf die jeweilige Produktseite
  - DR0.DE: `https://www.onvista.de/aktien/Deutsche-Rohstoff-AG-Aktie-DE000A0XYG76`
  - RHM.DE: `https://www.onvista.de/aktien/Rheinmetall-AG-Aktie-DE0007030009`
  - BAYN.DE: `https://www.onvista.de/aktien/Bayer-Aktie-DE000BAY0017`
  - **Regel:** Kaufsignal-Alerts für DE-Aktien immer via Onvista, nicht Yahoo

### Strategie-Erkenntnisse
- Geopolitik-Trades (EQNR, DR0): Stops konsequent, Geopolitik-Prämie kann schnell weg sein
- Mental Stop > echte Stop Order: kein Stop-Hunting durch Market Maker
- Ölpreis als Taktgeber bei Geopolitik-Konflikten (nicht nur Folge)
- Market Regime entscheidend: selbe Strategie in Bull vs. Bear komplett anders

### Was nervt / wird Feature
- Bloomberg RSS hat ~30-60 min Lag → nicht für Abend-Reports geeignet (10.03.2026)
- Polygon.io Free Tier: 5 calls/min, gut für Kurse aber API-Key-Rotation nach Discord-Exposure nötig

### Muster die algorithmisch erkennbar sein müssen (aus Dirk 7H Videos)
- **Power of Three / Power of Free:** EMAs (10/20/50) laufen eng zusammen → Ausbruch steht kurz bevor. Richtung unklar, aber enges Risiko möglich. → Screener-Pattern
- **Inside Day:** Hoch und Tief des Tages innerhalb der Vortagskerze → Setup-Signal. Ausbruch über Inside-Day-Hoch = Entry
- **Undercut & Rally:** Kurs unterschreitet letztes Tief kurz, zieht dann direkt wieder hoch → antizyklischer Kauf. → Screener-Pattern
- **Kangaroo Market:** Eigener Marktregime-Typ — weder Bull noch Bear, sideways/volatil. KI-Verhalten: kleiner positionieren, enger absichern
- **Livermore Levels:** Runde Zahlen ($400, $300 etc.) als starke psychologische S&R-Zonen → automatisch markieren
- **Gap Close:** Aktie läuft in altes Gap zurück → klassischer Trade. Verkauf (Teil) wenn Gap geschlossen

### Markt-Gesundheitsindikatoren (für Makro-Dashboard Pflicht)
- **SMH (Semiconductor ETF):** "Kanarienvogel in der Kohlemine" — bricht er, bricht der Gesamtmarkt
- **Nasdaq 50-Tage-Linie:** Darüber = Rückenwind, darunter = Gegenwind für alle Momentum-Trades
- **Nasdaq 200-Tage-Linie:** Letzte Verteidigungslinie im Abschwung

### VIX — Pflicht-Indikator mit Ampelsystem
Eigene Analyse 07.03.2026 bestätigt: VIX ist DIE Steuerungsgröße für Marktregime.
```
VIX < 20:    🟢 Grün  — normaler Bullenmarkt, Momentum-Trades voll
VIX 20–25:   🟡 Gelb  — milde Unsicherheit, Positionsgrößen reduzieren
VIX 25–30:   🟠 Orange — Angst, kein Neu-Einstieg Tech, nur Stops managen
VIX > 30:    🔴 Rot   — Panik, defensive Haltung, Cash erhöhen
VIX > 40:    💀 Crash — Kapitulation (historisch oft Kaufsignal!)
```
→ KI-Regelwerk: bei VIX > 25 keine neuen Tech-Positionen eröffnen
→ Bei VIX-Kollaps von >30 auf <20: starkes Re-Entry Signal

### Power of Three — Numerisch verifizierbar
Dirks visuelle Einschätzung lässt sich mathematisch bestätigen:
- EMA10, EMA20, EMA50 berechnen
- Wenn Spread zwischen EMA10 und EMA50 < 0,5% des Kurses → Power of Three aktiv
- Beispiel META 07.03.2026: EMA10=653,88 / EMA20=655,09 / EMA50=655,56 → Spread 1,68$ auf $644 = 0,26% ✅
- Screener: automatisch scannen welche Aktien gerade Power of Three zeigen

### Relative Stärke — Automatisch berechnen
Kursveränderung Aktie vs. Nasdaq in gleicher Periode:
- PLTR +14,6% vs. Nasdaq -1,3% in 1 Woche = massive relative Stärke
- Formel: RelStärke = Aktie_Performance - Nasdaq_Performance
- Positiv = Aktie stärker als Markt → kaufenswert
- Negativ = Aktie schwächer als Markt → Finger weg
- Im Dashboard immer anzeigen: "X% stärker/schwächer als Nasdaq"

### Venezuela-Faktor: Geopolitische Ölpreis-Gegenkraft (08.03.2026)
Ölpreis ist kein Ein-Faktor-Markt — mehrere geopolitische Kräfte gleichzeitig:
- **Bullish:** Hormuz-Sperrung, Iran-Eskalation, Infrastrukturschäden → Angst-Prämie
- **Bearish:** Venezuela-Öl kommt zurück (Trump erkennt Rodríguez an, Shell-Deal, US-Konsularabkommen) → mehr Angebot
- **Netto:** Iran dominiert kurzfristig, Venezuela ist Deckel-Faktor mittelfristig
→ Tool muss Öl-Multifaktor-Gleichgewicht modellieren, nicht nur einen Treiber

### US Navy Eskorte = Blockade ≠ physisch unmöglich (08.03.2026)
Hormuz "gesperrt" durch Iran — aber ein großer Tanker hat passiert (US Navy Eskorte).
Lehre: Politische Blockade-Ankündigung ≠ physischer Totalausfall. Markt priced Risikoprämie,
nicht vollständige Unterbrechung. Tool: Eskorte-News als moderierendes Signal für Öl-Alert.

### Öl-Überdehnung als Kontraindikator
07.03.2026: Brent +33% über EMA50 → nicht nachhaltig
- Formel: (Kurs - EMA50) / EMA50 × 100
- Bei Öl > +20% über EMA50 → Kontraindikator (geopolitische Prämie übertrieben)
- Bedeutet: entweder weitere Eskalation ODER baldige Korrektur
- → Signal für Trading Tool: "Öl überdehnt — Geopolitik-Prämie prüfen"

### WTI Shooting-Star = Geopolitik-Prämie entweicht (09.03.2026)
Konkretes Fallbeispiel: WTI Intraday-Hoch $119,48 → Schluss $84,84 (-6,7% vs. Freitag)
- Shooting-Star-Kerze (langer oberer Docht, kleiner Körper, nahe Tief) = Erschöpfungssignal
- Auslöser: Trump "short-term excursion" + Iran Deeskalationssignale → Prämie entweicht sofort
- Konsequenz im Portfolio: DR0.DE + EQNR Trailing Stops sofort nachziehen
- **Algorithmus:** Bei Öl-Tageskerze mit Docht >2x Körperlänge + Schlusskurs <Öffnungskurs → "Geopolitik-Entladung"-Signal
- Wichtig: IRGC-Strikes liefen noch gleichzeitig → Markt ignoriert Realität, priced Narrative

### Nikkei 225 als Öl-Früh-Kontraindikator
Japan = weltgrößter Öl-Nettoimporteur → Nikkei fällt systematisch wenn Öl steigt
- 09.03.2026: Nikkei -6%+ bei Brent $108+ → antizyklisches Signal für europäische Eröffnung
- Ticker: ^N225 (Nikkei) + 1605.T (INPEX Corp, japanischer Ölproduzent — steigt bei Öl)
- Wenn INPEX steigt UND Nikkei fällt → Öl-Schock wird ernstgenommen
- TSE schließt ~08:00 CET → Morgen-Briefing greift Japan-Daten vor Xetra-Eröffnung ab
- **Dashboard-Pflicht:** Nikkei als Makro-Indikator im Öl-Kontext-Panel anzeigen

### VIX-Ausnahme: Rüstungsaktien sind anti-zyklisch (BESTÄTIGT KW11)
Grundregel: VIX > 25 → keine neuen Positionen (Risiko-Off)
**Ausnahme:** Rüstungsaktien (RHM.DE, BAE, LDOS, NOC) dürfen bei VIX > 25 gekauft werden wenn:
1. Der Konflikt DER Treiber des VIX-Anstiegs ist (nicht Makro, Zinsen etc.)
2. Die Rüstungs-Thesis direkt vom Konflikt profitiert
3. Positionsgröße halbiert (VIX-Puffer)
- **Praxis KW11:** RHM.DE bei VIX=32 gekauft — halbe Position. Position hielt −1% (besser als Tech −6%)
- **Screener-Logik:** Sektor Aerospace&Defense bei VIX>25 NICHT ausblenden, nur mit "⚠️ Half-Size"-Flag

### Stop-Berechnung: immer vom Entry, nie vom aktuellen Kurs (10.03.2026)
"2% Abstand" = 2% vom Einstiegskurs.
Beispiel: Entry 1.635€ → Stop = 1.635 × 0,98 = 1.602,30€ (nicht 2% vom Tageskurs!)
→ Pflicht-Formel im Tool: `stop = entry × (1 - stop_pct / 100)`

### Stop-Breite muss zur Volatilität passen (10.03.2026, BESTÄTIGT 14.03.2026)
**DR0.DE Fall-Studie:** Stop 77€ bei Entry 76,35€ = 0,85% Abstand bei Öl-Crash-Volatilität
- Tages-Tief war 75,10€ — Stop wurde ausgelöst
- Stop war zu eng, verschärft durch hohe Volatilität (Geopolitik-Event)
- **Algorithmus:** ATR(14) × 1.5 als Mindestabstand
- **Feature:** "Stop-Warnung: zu eng für aktuelle Volatilität" bei Eingabe

### Öl-Szenarien differenzieren: Ankündigung vs. Live-Aktion (14.03.2026 — KW11 LEARNING)
**Zwei unterschiedliche Öl-Preis-Muster bei Geopolitik:**

**Modus A — "Politische Ankündigung":**
- WTI +10–15% intraday, schnelle Mean-Reversion (−5 bis −10% nächster Tag)
- Beispiel: 07.03. Iran droht Raketen → 09.03. WTI −6,7% vs. Freitag
- **Trading:** Halbe Position, enge Stops (15% ATR)

**Modus B — "Live Militär-Aktion":**
- WTI +4% stabil, strukturelle Baseline-Erhöhung
- Beispiel: 12.03. Israel bombardiert Teheran → WTI +4,6% stabil, bleibt oben
- **Trading:** Volle Position, normales CRV
- **Dauer:** 4–6 Wochen statt 2 Wochen

**Konsequenz für Tool:** Automatische Klassifizierung der Geopolitik-News als Ankündigung vs. Aktion → Stop-Breite + Position-Größe anpassen

### 🔴 Mental Stop > Real Stop ist FALSCH — echte Stops in TR setzen! (11.03.2026)
RHM.DE Lektions-Wrap: Entry 1.635€, Stop 1.595€ war MENTAL (nicht in Trade Republic eingetragen).
- Overnight/früh: Kurs unterschreitet unter 1.595€ → Albert sieht Mental Stop gebrochen
- Victor wendet Dirks Regel an (kein Averaging Down unter Stop) → Position sofort schließen @ 1.563€
- **Realisierter Verlust: -72€/Aktie (-4,4%)**
- Wenn echter Stop in TR gesetzt gewesen wäre → Ausführung garantiert gewesen, keine emotionalen Diskussionen

**Pflicht ab jetzt:**
1. Stop IMMER in Trade Republic eingeben — NICHT mental absichern
2. Albert prüft: "Stop in TR aktiviert?" bei jeder neuen Position
3. Feature: "Check: Halten Sie echte Stops in Ihrem Broker ein?" als Onboarding-Pflicht

**Warum echte Stops besser sind:**
- Keine Gefühle, keine Diskussionen — automatische Ausführung
- Gap-Risiko (Overnight) ist dann Broker-Problem, nicht Nutzer-Problem
- Mentale Stops führen zu Überlegungen ("vielleicht halte ich noch...") → Revenge Trading

### News-Infrastruktur-Upgrade (11.03.2026)
**Status:** Multi-Source News-Fetcher deployed
- `scripts/news_fetcher.py` erstellt — kombiniert Bloomberg RSS + Finnhub + Polygon + Google News
- Alle Morgen/Abend/Strategie-Briefings nutzen jetzt einheitliche Quelle
- Reuters als Fallback für Breaking News (wenn eines der anderen Systeme down ist)
- **Lesson:** Bloomberg RSS allein zu langsam für operative Briefings (30-60 Min Lag) — Kombination nötig

### API-Key-Sicherheit: Rotation-Protokoll (11.03.2026)
Polygon.io API-Key wurde in Discord exponiert (Chat-History)
**Sofort-Maßnahmen:**
1. Key rotieren
2. Alle API-Calls auf neuen Key umstellen
3. Keine API-Keys jemals in Screenshots/Chat/Discord speichern
4. Nur `.env` Dateien mit `.gitignore` Schutz
5. Wenn ein Key kompromittiert: 5-Min Rotation Ziel

**Für Tool später:** API-Key-Verwaltung Vault (1Password, HashiCorp Vault) mit Rotation-Reminder alle 90 Tage

### Kontext zusammendenken → proaktive Handlungsempfehlung (10.03.2026)
Wenn A (Stop potenziell ausgelöst) + B (Markt jetzt offen) + C (Victor muss handeln) = klare Situation → SOFORT sagen: "L&S ist offen, geh die Stops setzen" — nicht warten bis Victor fragt.
**KI-Prinzip:** Einzelfakten kombinieren und direkte Handlungsempfehlung ausgeben, nicht nur Fakten präsentieren.

### API-Key-Sicherheit: niemals in Discord/Chat (10.03.2026)
Polygon.io API-Key wurde in Discord exponiert → sofort rotieren.
**Protokoll:** API-Keys nur in `.env` oder passwortgeschützten Dateien. Nie in Chat-Nachrichten, niemals ins Trade Journal kopieren. Bei Exposition: sofort Key-Rotation auslösen + Victor benachrichtigen.

### News-Quellen-Hierarchie (Geschwindigkeit vs. Zuverlässigkeit)
Erfahrung 10.03.2026: Bloomberg RSS hat ~30-60 min Lag, abends keine frischen Artikel
Reihenfolge für Breaking News:
1. **Finnhub.io** (noch nicht eingerichtet — nächste Prio) — ~5-30 min Delay, 60 calls/min Free
2. **Polygon.io** — 1-2h für US-Aktien-News, 5 calls/min Free
3. **Bloomberg RSS** — zuverlässig aber langsam, gut für Kontext
4. **Yahoo Finance News** — Marktsentiment, Headlines
→ Für autonomes Tool: Finnhub als primäre News-Quelle + Bloomberg als Bestätigung

### EMA-Analyse als objektive Bestätigung
Eigener Ansatz: Nicht nur Charts visuell lesen — EMAs numerisch berechnen
- Gibt Dirks visuelle Einschätzungen eine objektive zweite Meinung
- Beispiel: Dirk sagt "MSFT erholt sich" → EMA-Analyse zeigt: über EMA10/20 aber -6,2% unter EMA50 → Short-Covering bestätigt, keine echte Stärke
- Kombination: visuell (Dirk) + numerisch (Albert) = bessere Entscheidungen

---

## 🕷️ Scraping-Infrastruktur

Modul: `workspace/modules/human_scraper.py`

Für TradeMind relevante Scraper:
- `LivemapScraper` — Geopolitik-Radar (Iran, Ukraine, Israel, Lebanon, China, Taiwan, Venezuela)
- `YahooFinanceScraper` — Portfolio-Kurse, VIX, Nasdaq

Verwendung im Backend:
```python
from modules.human_scraper import create_scraper

# Geopolitik
livemap = create_scraper("livemap")
iran_news = livemap.fetch_region("iran")
tier1 = livemap.fetch_tier1()  # Iran + Ukraine + Israel + Lebanon

# Kurse
finance = create_scraper("finance")
quotes = finance.fetch_portfolio(["NVDA", "MSFT", "PLTR", "EQNR.OL"])
```

Installation:
```bash
pip install -r workspace/modules/requirements.txt
playwright install chromium
```

## 🔗 Ressourcen & Links

- TR inoffizielle API: *(Link eintragen)*
- Yahoo Finance API Docs: https://query2.finance.yahoo.com
- Polygon.io: https://polygon.io
- Dirk 7H / Tradermacher Strategien: siehe `memory/projekt-trading.md`

## 💡 Ideen-Backlog (für später)

### WebSocket News-Listener auf VPS (11.03.2026)
**Idee von Victor:** Statt RSS-Polling einen echten WebSocket-Listener auf dem VPS aufsetzen.

**Architektur:**
```
Finnhub/Polygon WebSocket (Push, real-time)
    → Python Daemon auf VPS (PM2-managed)
    → Parser filtert nach Portfolio-Ticker
    → Relevant? → OpenClaw Tool Call → Discord Alert
    → Alle Events → PostgreSQL/SQLite auf VPS
```

**Warum noch nicht jetzt:**
- Für Swing Trading reicht 15-Min-Polling
- WebSocket-Daemon erhöht Infrastruktur-Komplexität (Crash-Handling, Restart)
- Aktuell keine DB auf VPS vorhanden

**Wann sinnvoll:**
- Wenn Stop-Alerts unter 15 Min nötig werden
- Wenn Trading-Tool für Kunden gebaut wird (TradeMind)
- Als Grundlage für einen echten Alert-Service

**Wichtig:** Bloomberg hat kein öffentliches WebSocket — Finnhub + Polygon sind die richtigen Quellen (Keys vorhanden: FINNHUB_KEY, POLYGON_KEY)

### NewsWire — Echtzeit-News-Listener (geplant: Freitag 14.03.2026)

**Was:** Python-Daemon der Finnhub WebSocket + Bloomberg RSS pollt und Portfolio-relevante News in Echtzeit an Discord liefert.

**Architektur:**
```
newsire.py (PM2 Daemon)
├── Bein 1: Finnhub WebSocket (wss://ws.finnhub.io)
│   └── Push-News für Portfolio-Ticker + Keywords
├── Bein 2: Bloomberg RSS Poller (5-Min-Cycle)
│   └── markets / energy / technology / politics
├── Filter: 3-Stufen (Keyword → Score → optional Haiku)
├── Output: Discord Webhook (direkt, kein LLM für Stufe 1+2)
└── Storage: SQLite (Event-Log für Reports)
```

**Freitag-Zeitplan:**
- 09:00 — Grundgerüst: WebSocket-Connect + Reconnect-Logic
- 10:00 — Keyword-Filter + Scoring (Stufe 1+2)
- 11:00 — Bloomberg RSS Poller in gleicher Event-Loop
- 12:00 — Discord Webhook Integration
- 13:00 — SQLite Logging + PM2 Setup
- 14:00 — Testlauf mit Live-Daten
- 15:00 — Optional: Haiku-Anbindung für Stufe 3

**Abhängigkeiten:**
- Finnhub Key: ✅ vorhanden (d6o6lm1r01qu09ciaj3g...)
- Discord Webhook URL: ✅ 13.03.2026 — https://discord.com/api/webhooks/1481903416035770460/4FkmKMpoPVgoU1NcclX43FFhzKbDinXVXOMVFMuCk9lo8PUpe4Ycu_m9N25UCoJ_tAEZ
- PM2: ✅ läuft bereits auf dem Server
- Python websockets: `pip install websockets` am Freitag

**Manueller Trigger-Name:** `newswire`

### Ölpreis-Szenarien Engine (Pflicht für finale TradeMind)

**Learnings aus Phase 1:**

Öl ist nicht einfach eine Rohstoff-Basis — es ist ein Konflikt-Indikator. Die Unterscheidung zwischen:
- **Geopolitischer Panik** (Ankündigung, schnelle Mean-Reversion)
- **Strukturellem Ölschock** (tatsächliche Aktion, Baseline-Shift)

...ist Fundamental für die richtige Position-Sizing und Stop-Placement.

**Algo für TradeMind:**
```
Wenn "Geopolitik-News zu Öl":
  → Parse: "Ankündigung" oder "Live-Aktion"?
  → Berechne: Öl-Volatilität (14-Tage ATR)
  → If Panik-Modus: Verkleiner Position 50%, enger Stop (15% ATR)
  → If Struktur-Modus: volle Position, Stop auf 50% ATR
  → Output: "Öl-Szenario-Klassifizierung" im Dashboard
```

**Daten die dazu nötig sind:**
- WTI + Brent intraday Daten (15-Min, nicht nur Daily)
- News-Sentiment zu Iran/OPEC/Konflikt
- Aktuelle Baseline (wo war Öl vor 1 Monat?) — Mean-Reversion-Ziel berechnen

**Feature später:**
Dashboard-Panel "Öl-Szenarien": zeigt aktuell welcher Modus läuft (Panik vs. Struktur) + erwartete Dauer

---

### NewsWire — Echtzeit-News-Listener (geplant: Freitag 14.03.2026)
**Status:** Geplant
**Trigger-Name:** NewsWire
**Architektur:**
- Finnhub WebSocket (Push, real-time News + Ticker-Events)
- Bloomberg RSS Poller (5-Min-Cycle, in gleicher Event-Loop)
- 3-Stufen Keyword-Filter (Portfolio → Geopolitik → Makro)
- SQLite Event-Log (newswire.db)
- Discord Webhook für Alerts (kein LLM für Stufe 1+2)
- Haiku-Call nur bei Score ≥3 (Stufe 3)
- PM2 managed, auto-restart

**Dateien:**
- `scripts/newswire.py` — Haupt-Daemon
- `data/newswire.db` — Event-DB
- PM2 ecosystem config

**Keywords:**
- PORTFOLIO: nvda, nvidia, msft, microsoft, pltr, palantir, equinor, eqnr, rio tinto, bayer, bayn, rheinmetall
- GEOPOLITIK: iran, hormuz, strait, sanctions, tariff, trump
- ROHSTOFFE: oil, crude, wti, brent, copper, silver, gold
- MAKRO: fed, ecb, rate hike, rate cut, inflation, recession

---

## 🎓 Neue Learnings (12.03.2026)

### Öl-These strukturell bestätigt — Geopolitik-Eskalation vs. Politische Ankündigung (12.03.2026)
**Erkenntnis:** Ölpreis hat zwei verschiedene Bewegungs-Modi bei Geopolitik:

**Modus A — "Politische Ankündigung":**
- Iran droht Raketen-Salve (nur Ankündigung)
- Markt: Panik → WTI +10–15% intraday
- Realität: Raketen werden teilweise abgefangen
- Markt-Reaktion: Sharp Mean-Reversion zum nächsten Tag (-5% bis -10%)
- Beispiel: 07.03. WTI gap up zu $119 → 09.03. Schluss $84,84 (−6,7% vs. Freitag)

**Modus B — "Live Militär-Aktion" (neu 12.03.2026):**
- Israel startet GROSSE direkte Airstrikes auf Teheran
- Nicht Ankündigung, sondern tatsächliche Bombardierung
- Trump LIVE bestätigt: "Krieg mit Iran läuft gut"
- Markt: Öl +4,6% stabil (keine Panik-Spike, sondern strukturelle Erhöhung)
- Baseline: WTI bleibt höher (nicht schnelle Mean-Reversion)
- Beispiel: 12.03. WTI $86,94 → $91,00 (+4,6%, stabil)

**Unterscheidung für Tool:**
- Modus A: Öl > +20% über EMA50 = Kontraindikator → Short-Setup wahrscheinlich
- Modus B: Öl baseline erhöht sich, aber weniger volatile Bewegungen → Hold-Setup wahrscheinlich
→ **Feature:** Öl-Szenarien-Engine die zwischen "Ankündigung-Panik" und "Live-Aktion-Baseline" unterscheidet (via News-Sentiment-Analyse)

**Praktisch für EQNR/DR0:**
- Trailing Stop nach +5% Gewinn auf Breakeven (27,00€ für EQNR) ist richtig
- Diese Position hält länger (nicht nur Panik-Trade)
- Geopolitik-Update: Szenario B/C wahrscheinlicher → längere Ölpreis-Stütze

---

## 🎓 Neue Learnings (11.03.2026)

### KRITISCH: Mental Stops sind nicht real
RHM.DE-Erkenntnis: Victor hatte Stop 1.595€ mental notiert, aber nicht in TR gesetzt.
- Nacht-/Morgen-Bewegung unterschritt 1.595€ schnell
- Seitwärtsbewegung 1.574–1.586€ bei dünnem Volumen (0,4x)
- Kein echtes Stop-Sell → manuelle Entscheidung nötig → Victor folgte Dirk-Regel und schloss bei 1.563€ (-4,4%)

**REGEL für TradeMind:** Jede Stop-Order MUSS real im Broker gesetzt sein (Limit-Sell unterhalb wichtigen Support-Niveaus). Mental Stops sind nur für strategische Orientierung, nicht für Ausführung.

**UI-Feature:** \"Stop nicht in TR gesetzt ❌\" Warnung auf Position anzeigen wenn Differenz zwischen Plan + Realität detektiert.

### Druckenmiller KI-Rotation: Big Spender → Profitable
Mark Druckenmiller beobachtet: Große CapEx-KI-Spender divergieren von echten KI-Profit-Titeln (NVDA, PLTR, ARM).
Marktinterpretation: KI-Bubble-Phase endet, echte Economics-Fragen fangen an.

→ **Screener-Feature:** Sektor-Rotation Pattern erkennen (CapEx vs. EBIT-Yield-Divergenz)
→ **Position-Weighting:** NVDA + PLTR sind \"Profitabilität-Leader\" → höher gewichten wenn Rotation eintritt


---
## Transcript-Analyse: Dirk 7H (Tradermacher) (2026-03-13)
*Quelle: test-these-dirk7h.txt*

## Dirk 7H (Tradermacher) — 2026-03-13 — RHM.DE Long-These

**Methodik-Erkenntnisse:**
- Rücksetzer in intaktem Aufwärtstrend kaufen: EMA50-Touch als Einstieg (nicht Bottom-Fishing)
- EMA200-Verletzung = Exit, egal wie gut die Story klingt — Technicals vor Narrativ
- Kleinere Aktien ohne konkrete Verträge meiden: nur Marktführer mit sichtbarem Auftragsbuch

**Risiko-Regeln:**
- Stop immer strukturell gesetzt (unter EMA200 oder letztem Swing-Low)
- CRV-Minimum 3:1 für Rücksetzer-Trades in volatilen Sektoren

**Begründete These: Rheinmetall AG (RHM.DE) long**

Argumente der Quelle:
- NATO 3% BIP-Beschluss: struktureller Treiber 5-10 Jahre
- Auftragsbuch bis 2030 sichtbar: kein Zykliker, planbare Einnahmen
- EMA50-Rücksetzer: technisch valider Einstiegspunkt
- CRV 3:1 (Stop 1.480€, Ziel 1.800€, Entry ~1.560€)

Alberts unabhängige Analyse:
- Bestätigt durch NewsWire: 6 bullish RHM-Events in 48h, S2-Thesis intakt
- Gegenargument identifiziert: Margenenttäuschung Q4 nicht erwähnt — kurzfristiger Druck möglich
- VIX 28 (orange): kein ideales Umfeld für neue Positionen heute
- Eigener Schluss: These überzeugend für 3-12 Monate, Einstieg besser bei VIX < 22 oder Boden-Bestätigung 1.540-1.560€
- Handlungsrelevanz: Watchlist mit Einstiegsbedingungen, nicht sofort

---
## Transcript-Analyse: Lars Eriksen (2026-03-13)
*Quelle: eriksen-bitcoin-wpr-2026-03-13.txt*

## Lars Eriksen — 2026-03-13 — WPR Akkumulierungssignal

**Methodik:**
- Kaufsignal vs. Akkumulierungssignal: Akkumulierung = nächste große Bewegung aufwärts, aber Kurs kann noch fallen. Früher + günstiger als prozyklisches Signal.
- Williams Percentage Range (WPR) auf MONATSBASIS bei großen Basiswerten: hohes Gewicht durch Seltenheit (3× in 7 Jahren)
- Antizyklisches vs. prozyklisches Kaufen: Vor Ausbruchssignal einsteigen für besseres CRV
- Tranchenkauf: 3 Stufen vordefinieren, keine Improvisation. Begründung: Bodenbildungsrisiko bleibt auch bei Signal
- Portfoliogewichtungs-Rebalancing als Kaufbegründung: emotionsloser, methodischer Ansatz
- Rollende Korrelations-Check (30T): wenn alle niedrig → eigenständige Analyse, keine Markt-Ableitungen
- Langfristig relevanteste Korrelation eines Assets identifizieren (Bitcoin → Geldmenge)
- Sentiment als Kontraindikator: abgekühltes Interesse = Setup-Bestätigung, nicht Warnsignal

**Red Flags:**
- Nie alles auf einmal bei Akkumulierungssignal — immer Tranchen
- Keine Korrelationsableitung wenn Korrelation niedrig/unbeständig
---

## 📊 Wochenauswertung — Woche 1 (2026-03-07 bis 13.03)

**Status Strategien:** 9 Positionen offen, noch keine geschlossenen Trades.
- S1 (Iran/Öl): EQNR.OL, DR0.DE → +4,2% / -2,8%
- S3 (KI/Tech): NVDA, MSFT, PLTR, META → mixed
- S5 (Rohstoffe): 1 offen
- S6 (Energie-Wende): 1 offen  
- S7 (Biotech): 1 offen

**Dimension-Trefferquote:** noch keine Daten (mindestens 5 geschlossene Trades pro Dimension nötig).

**Gelernte Regel — Öl-Szenarios differenzieren:**
Öl hat zwei Bewegungsmuster bei Geopolitik:
1. **Panik-Ankündigung** (z.B. Iran droht Raketen): +15% intraday, schnelle Mean-Reversion nächster Tag (-5 bis -10%)
2. **Live-Aktion** (z.B. Israel bombardiert Teheran): +4% stabil, strukturelle Baseline-Erhöhung

→ **Tool-Feature:** Entry/Stop anpassen je nach Szenario. Panik = halbe Position + enge Stops. Aktion = volle Position + normales CRV.

---
