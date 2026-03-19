# TradeMind — Masterplan: Perfektionierte Architektur
**Erstellt:** 2026-03-19 | **Status:** Analyse-Phase
**Prinzip:** Jeder Baustein wird einzeln perfektioniert, dann zusammengesetzt.

---

# LAYER 1 — DATA FOUNDATION

> Ohne perfekte Daten ist alles Müll. Das ist das Fundament.

---

## 1.1 Price Engine

### Ziel
Echtzeit + historische Kursdaten für alle Märkte, jederzeit verfügbar, in einer einheitlichen Struktur.

### Sub-Punkte

#### 1.1.1 — Live-Preise (Intraday)
**Ist-Zustand:** Yahoo Finance API (inoffiziell, fragil, 15min Delay bei DE-Aktien)
**Perfektioniert:**
- **Primär:** IBKR TWS API — echte Realtime-Kurse, alle Börsen, kein Delay
  - WebSocket-Stream: Preis-Updates push-basiert statt Polling
  - Kosten: $0 mit IBKR-Account (Market Data Bundles separat, ~$15/Monat für US+EU)
- **Sekundär:** Twelve Data oder Polygon.io als Fallback
  - Twelve Data: Echtzeit-WebSocket, 800 req/min, $29/Monat
  - Polygon.io: 5 req/min (Free), unlimitiert ab $29/Monat
- **Tertiär:** Yahoo Finance (Free Tier Backup, nie als Primary)
- **Lokal:** Redis-Cache mit 30s TTL — kein API-Call für Kurse die <30s alt sind

#### 1.1.2 — Historische Kurse (Daily/Weekly)
**Ist-Zustand:** Yahoo Chart API (range=3mo, interval=1d) — funktioniert, aber Rate-Limited
**Perfektioniert:**
- **Lokale SQLite-Tabelle `daily_prices`:**
  ```
  ticker | date | open | high | low | close | volume | adj_close | source
  ```
- **Backfill:** Einmalig 5 Jahre Tageskerzen pro Ticker laden (Yahoo/Polygon)
- **Inkrementell:** Jeden Abend 22:30 UTC neue Tageskerze appenden
- **Splits/Dividenden:** adj_close korrekt berechnen (Yahoo liefert das)
- **Warum wichtig:** EMA/SMA/RSI Berechnungen brauchen 200+ Tageskerzen

#### 1.1.3 — Intraday-Kerzen (5min/15min)
**Ist-Zustand:** Nicht vorhanden — nur Snapshots alle 15 Min
**Perfektioniert:**
- 5-Minuten-Kerzen für aktive Positionen (max 10 Ticker)
- Speichern in `intraday_candles` Tabelle (rolling 5 Tage)
- Benötigt für: Candlestick Pattern Detection, Umkehrkerzen, Volume Spikes
- Quelle: IBKR (Realtime) oder Twelve Data (5min Bars)

#### 1.1.4 — Multi-Currency Normalisierung
**Ist-Zustand:** `to_eur()` Funktion mit manuellem FX-Lookup
**Perfektioniert:**
- FX-Rates als eigener Ticker im System (EUR/USD, EUR/NOK, EUR/GBP)
- Alle Preise doppelt gespeichert: Original-Währung + EUR
- Historische FX-Rates für P&L-Berechnung (Entry in EUR zum damaligen Kurs)
- Edge Case: Norwegische Krone (EQNR) schwankt stark — FX-Risiko tracken

#### 1.1.5 — Data Quality Monitor
**Ist-Zustand:** Keiner — wenn Yahoo 404 gibt, fehlt der Preis einfach
**Perfektioniert:**
- Heartbeat pro Ticker: wenn >2 Runs kein Preis → Alert
- Stale-Detection: wenn Preis sich 24h nicht ändert (Wochenende excluded) → Flag
- Source-Tracking: welche API hat den Preis geliefert? → Audit-Trail
- Gap-Detection: wenn Preis >10% springt → sanity check bevor Alert feuert

---

## 1.2 News Pipeline

### Ziel
Alle relevanten Nachrichten dedupliziert, ticker-tagged, sentiment-scored, in <5min nach Publikation.

### Sub-Punkte

#### 1.2.1 — Quellen-Management
**Ist-Zustand:** Bloomberg RSS + Finnhub + Google News RSS — manuell konfiguriert
**Perfektioniert:**
- **Tier 1 (Echtzeit, <2min Delay):**
  - Finnhub Company News (60 calls/min) — per Ticker
  - Benzinga News API ($99/Monat) — schnellste Pre-Market News
  - Alpha Vantage News Sentiment ($49/Monat) — inkl. Sentiment Score
- **Tier 2 (5-30min Delay, kostenlos):**
  - Bloomberg RSS (markets, energy, technology, politics)
  - Google News RSS (per Ticker-Query)
  - Reuters RSS (wenn verfügbar)
- **Tier 3 (Deep Dive, on-demand):**
  - SEC EDGAR (Form 4 Insider Filing) — kostenlos
  - Seeking Alpha RSS — Analyse-Artikel
  - Reddit r/wallstreetbets Sentiment (snoowrap API)

#### 1.2.2 — Deduplikation
**Ist-Zustand:** Nicht vorhanden — gleiche Story 4x in DB
**Perfektioniert:**
- **URL-Hash:** SHA256 der URL → Primary Dedup Key
- **Headline-Fingerprint:** `difflib.SequenceMatcher` >80% Ähnlichkeit → gleicher Event
- **Event-Clustering:** Alle Artikel zum selben Event unter einer `event_id` gruppieren
- **Zeitfenster:** Artikel innerhalb von 2h mit >70% Ähnlichkeit = gleicher Event
- **Impact:** Conviction Score wird nicht mehr durch Duplikate aufgeblasen

#### 1.2.3 — Ticker-Tagging
**Ist-Zustand:** Keyword-Match ("NVDA" in Headline)
**Perfektioniert:**
- NER (Named Entity Recognition) — erkennt "Nvidia" auch wenn nur Name erwähnt
- Ticker-Alias-Map: {"Nvidia": "NVDA", "Equinor": "EQNR.OL", "Rheinmetall": "RHM.DE"}
- Sektor-Tagging: Artikel über "OPEC" → automatisch alle Öl-Positionen taggen
- Relevanz-Score: wie direkt betrifft die News den Ticker? (1.0 = direkt, 0.3 = Sektor)

#### 1.2.4 — Sentiment-Analyse
**Ist-Zustand:** Keine — nur Keyword-Match
**Perfektioniert:**
- **Level 1:** VADER Sentiment (kostenlos, schnell, gut für Headlines)
- **Level 2:** FinBERT (HuggingFace, spezialisiert auf Finanz-Texte, lokal runnable)
- **Level 3:** Claude API für nuancierte Analyse (nur bei kritischen Alerts)
- Output pro Artikel: `sentiment: {score: -0.7, label: "bearish", confidence: 0.85}`
- Aggregation: gewichteter Sentiment pro Ticker über letzte 24h

#### 1.2.5 — News-Momentum Tracking
**Ist-Zustand:** Teilweise (newswire_analyst.py)
**Perfektioniert:**
- Velocity: Wie schnell kommen neue Artikel zum selben Thema?
  - <3 Artikel/24h = normal
  - 5-10 = erhöhte Aufmerksamkeit
  - >10 = Momentum-Event → sofort Albert alertieren
- Theme-Tracking: Iran-Eskalation, Fed-Zinsen, NVDA Earnings — jedes Theme mit eigener Timeline
- Decay: Nachrichten >48h verlieren 50% Gewicht, >7 Tage = irrelevant

---

## 1.3 Macro Store

### Ziel
Alle makroökonomischen Indikatoren historisch gespeichert, jederzeit abfragbar, mit automatischen Regime-Labels.

### Sub-Punkte

#### 1.3.1 — Kern-Indikatoren
**Must-Have (täglich aktualisiert):**
| Indikator | Ticker | Warum |
|---|---|---|
| VIX | ^VIX | Markt-Angst, Regime-Detection |
| WTI Crude | CL=F | Öl-These, Inflation |
| Brent Crude | BZ=F | Europa-Öl, EQNR |
| US 10Y Yield | ^TNX | Risk-On/Off Proxy |
| US 2Y Yield | ^IRX | Fed-Policy Proxy |
| 2Y-10Y Spread | computed | Rezessions-Indikator |
| DXY (Dollar Index) | DX-Y.NYB | Commodity-Gegenläufig |
| Gold | GC=F | Safe Haven |
| EUR/USD | EURUSD=X | FX für Portfolio |
| Nikkei 225 | ^N225 | Asien-Frühindikator |
| Baltic Dry Index | via FRED | Globaler Handel |
| Kupfer | HG=F | Wirtschaftsgesundheit |

#### 1.3.2 — Event-Kalender
**Ist-Zustand:** Statische Liste im Dashboard
**Perfektioniert:**
- **API-Quelle:** Forex Factory API oder TradingEconomics (kostenlos bis 1000 req/Monat)
- Auto-Import: Fed Meetings, CPI, NFP, EZB, BoE, BoJ
- Earnings: Alpha Vantage Earnings Calendar oder Finnhub
- Jedes Event mit `expected_volatility: high/medium/low`
- Automatische Warnung: "Morgen NFP — keine neuen Positionen eröffnen bei VIX >25"

#### 1.3.3 — Historische Speicherung
- SQLite Tabelle `macro_daily`:
  ```
  date | indicator | value | prev_value | change_pct
  ```
- Backfill: 5 Jahre Daten (FRED API — kostenlos, stabil, offiziell)
- Update: Täglich 22:30 UTC
- Query: "Was war der VIX als ich EQNR gekauft habe?" → sofort beantwortbar

#### 1.3.4 — Regime-Klassifikation
- Automatische Labels basierend auf Indikatoren:
  ```
  VIX < 15 + Yields stabil + DXY neutral  → RISK_ON_CALM
  VIX 15-20 + Yields steigend             → RISK_ON_ACTIVE
  VIX 20-25 + Yields flach                → NEUTRAL
  VIX 25-30                               → CAUTION
  VIX > 30 + Yields fallend               → RISK_OFF
  VIX > 35 + DXY steigend + Gold steigend → CRISIS
  ```
- Jeder Trade wird mit aktuellem Regime-Label gespeichert
- Analyse: "Meine Trefferquote in RISK_ON: 68%, in CAUTION: 34%" → Regime-Filter

---

## 1.4 Trade Journal DB

### Ziel
Jeder Trade vollständig geloggt mit Kontext, maschinell auswertbar, Basis für alles Lernen.

### Sub-Punkte

#### 1.4.1 — Trade-Record Schema
```sql
CREATE TABLE trades (
  id INTEGER PRIMARY KEY,
  ticker TEXT NOT NULL,
  name TEXT NOT NULL,
  
  -- Timing
  entry_date TIMESTAMP NOT NULL,
  exit_date TIMESTAMP,
  holding_days INTEGER,
  
  -- Preise (immer EUR)
  entry_price_eur REAL NOT NULL,
  exit_price_eur REAL,
  stop_eur REAL,
  target_eur REAL,
  position_size_eur REAL,
  
  -- Berechnet
  pnl_eur REAL,
  pnl_pct REAL,
  risk_eur REAL,  -- (entry - stop) * shares
  reward_eur REAL,  -- (target - entry) * shares
  crv REAL,  -- reward / risk
  
  -- Kontext bei Entry
  entry_reason TEXT,  -- "EMA-Rücklauf + Volumen + S1 Iran-These"
  strategy_id TEXT,  -- "S1", "PS3" etc.
  conviction_at_entry INTEGER,  -- 0-100
  vix_at_entry REAL,
  regime_at_entry TEXT,  -- RISK_ON, CAUTION etc.
  
  -- Kontext bei Exit
  exit_reason TEXT,  -- "Stop getroffen" / "Ziel erreicht" / "These gebrochen"
  exit_type TEXT,  -- STOP_HIT, TARGET, MANUAL, TRAILING
  conviction_at_exit INTEGER,
  
  -- Lektion
  lesson TEXT,  -- "Stop war zu eng bei VIX >25"
  rule_followed BOOLEAN,  -- Hat der Trader seine eigene Regel eingehalten?
  
  -- Meta
  portfolio TEXT DEFAULT 'real',  -- 'real' oder 'paper'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 1.4.2 — Auto-Enrichment bei Entry
Wenn Victor sagt "EQNR long 28.40 Stop 27 S1":
1. Albert parsed: ticker=EQNR, entry=28.40, stop=27, strategy=S1
2. Auto-Enrichment:
   - VIX zum Zeitpunkt
   - Regime-Label
   - Letzte 5 News-Events für diesen Ticker (aus News Pipeline)
   - Conviction Score (aus Conviction Scorer)
   - Aktuelle Sektor-Stärke
   - Position Sizing Empfehlung (2%-Regel)

#### 1.4.3 — Auto-Enrichment bei Exit
Wenn Position geschlossen wird:
1. P&L berechnen (inkl. TR-Gebühren: 1€ pro Trade)
2. Holding-Dauer berechnen
3. Regime bei Exit vs. bei Entry vergleichen
4. News-Kontext bei Exit (was hat sich geändert?)
5. Regel-Compliance: hat Victor seinen eigenen Plan eingehalten?

#### 1.4.4 — Feedback-Verknüpfung
Jeder Trade wird verknüpft mit:
- Signal-Issue in Paperclip (welches Signal hat zum Trade geführt?)
- News-Events (welche Nachrichten waren relevant?)
- Strategie-Datei (welche These steckte dahinter?)
- → Kompletter Audit-Trail von Signal → Trade → Outcome → Lektion

#### 1.4.5 — Minimum Viable Dataset
- 20 Trades mit vollständigem Kontext = erste statistische Auswertung möglich
- 50 Trades = Strategie-Vergleich valide
- 100 Trades = Strategy DNA zuverlässig
- **AKTUELL:** ~10 echte Trades (unvollständig geloggt) → KRITISCHER ENGPASS

---

## 1.5 Signal DB (Paperclip-basiert)

### Ziel
Jede Prognose ist ein verfolgbarer Datenpunkt mit Outcome — die Basis für autonomes Trading.

### Sub-Punkte

#### 1.5.1 — Issue-Lifecycle
```
SIGNAL_DETECTED → Issue erstellt (status: todo)
    ↓
MONITORING → Lag-Zeit läuft (status: in_progress)
    ↓
OUTCOME → Validator prüft (status: done/cancelled)
    ↓
LEARNING → Accuracy-DB updaten, Conviction anpassen
```

#### 1.5.2 — Issue-Metadaten (Labels)
Jedes Signal-Issue bekommt strukturierte Labels:
- `pair:NIKKEI_COPPER` — welches Lead-Lag-Paar
- `regime:CAUTION` — Marktregime bei Signal
- `confidence:LOW|MEDIUM|HIGH` — basierend auf Accuracy
- `outcome:WIN|LOSS` — nach Validierung
- `actionable:YES|NO` — war das Signal handelbar?

#### 1.5.3 — Accuracy-Aggregation
Nach jeder Validierung:
```python
accuracy[pair_id] = wins / (wins + losses)
accuracy_by_regime[pair_id][regime] = ...
accuracy_by_vix_range[pair_id]["25-30"] = ...
```
→ "NIKKEI_COPPER ist 72% akkurat bei VIX <25 aber nur 41% bei VIX >30"

#### 1.5.4 — Signal → Trade Verknüpfung
Wenn ein Signal-Issue zu einem echten Trade führt:
- Issue bekommt Label `traded:YES`
- Trade-Record in Journal bekommt `signal_issue_id`
- → Geschlossener Loop: Signal → Trade → P&L → zurück zu Signal-Accuracy

---

# LAYER 2 — INTELLIGENCE ENGINE

> Rohdaten → Muster → Signale → Entscheidungen

---

## 2.1 Market Regime Detector

### Ziel
Jederzeit wissen: Risk-On oder Risk-Off? Bull, Bear, Sideways? — und alle anderen Module danach ausrichten.

### Sub-Punkte

#### 2.1.1 — Regime-Typen
```
BULL_CALM      → VIX <15, S&P >MA200, Yields stabil
BULL_VOLATILE  → VIX 15-20, S&P >MA200, Yields steigend
NEUTRAL        → VIX 20-25, gemischte Signale
CORRECTION     → VIX 25-30, S&P nahe MA50
BEAR           → VIX >30, S&P <MA200
CRISIS         → VIX >35, Credit Spreads weiten, Gold/USD steigen
```

#### 2.1.2 — Regime-Wechsel-Erkennung
- Nicht: "VIX ist 25 → NEUTRAL"
- Sondern: "VIX war 18, ist auf 25 gestiegen in 3 Tagen → REGIME_SHIFT"
- Velocity matters: schneller Anstieg = gefährlicher als langsamer
- Alert bei Regime-Wechsel → sofort alle Stop-Distanzen prüfen

#### 2.1.3 — Regime-Einfluss auf Module
| Modul | BULL_CALM | NEUTRAL | CORRECTION | CRISIS |
|---|---|---|---|---|
| Signal Engine | alle Signale | nur High-Confidence | nur Defensive | nur Hedges |
| Conviction | +10 Bonus | neutral | -20 Malus | -40 Malus |
| Position Sizing | 3% Risiko/Trade | 2% | 1% | 0.5% |
| Neue Entries | frei | selektiv | nur Watchlist | nur Short/Hedge |
| Trailing Stops | weit (ATR×3) | normal (ATR×2) | eng (ATR×1.5) | sofort BE |

#### 2.1.4 — Historischer Regime-Kalender
- Speichern: welches Regime galt an welchem Tag
- Backtest: "Meine Strategie S1 hat in BULL_CALM +12% gemacht, in CORRECTION -8%"
- → Regime-Filter für Strategy DNA

---

## 2.2 Signal Engine

### Ziel
Automatisierte Erkennung von Trading-Setups aus verschiedenen Quellen — alles mit Confidence Score.

### Sub-Punkte

#### 2.2.1 — Lead-Lag Detector ← *gerade gebaut*
- 5 Paare initial, erweiterbar auf 20+
- Jedes Paar mit eigener Accuracy-Historie
- Adaptive Thresholds: wenn NIKKEI_COPPER bei -2% feuert aber nur 45% akkurat ist → Threshold auf -3% erhöhen

#### 2.2.2 — Technical Pattern Scanner
**Candlestick Patterns (5min + Daily):**
- Hammer / Inverted Hammer (Reversal)
- Bullish/Bearish Engulfing
- Morning Star / Evening Star
- Doji (Indecision)
- Shooting Star
- Inside Day (Breakout pending)

**Indikatoren:**
- EMA-Kreuzungen: EMA10/20 (kurzfristig), EMA20/50 (mittelfristig), EMA50/200 (Golden/Death Cross)
- RSI: <30 überverkauft, >70 überkauft, Divergenzen
- MACD: Signal-Line Kreuzungen, Histogram-Divergenz
- Bollinger Bands: Squeeze (niedrige Vola → Breakout erwartet)
- Volume: >2× Durchschnitt = institutionelles Interesse

#### 2.2.3 — Volume Anomaly Detection ("Dark Pool Proxy")
- Normales Tagesvolumen als Baseline (20-Tage-SMA)
- Alert bei >2× Volume ohne offensichtliche News → institutionelle Bewegung
- Besonders stark wenn vor Earnings oder vor Makro-Events
- Empirisch: Volume-Anomalie 1-3 Tage VOR großer Kursbewegung

#### 2.2.4 — Earnings Signal Engine
- Pre-Earnings Momentum: Kurs steigt/fällt 5 Tage vor Earnings → Signal
- Post-Earnings Drift: Kurs bewegt sich nach Earnings in gleiche Richtung weiter
- Implied Volatility vs. Realized Volatility: wenn IV >> RV → Markt erwartet Überraschung
- → "PLTR Earnings in 5 Tagen: Kurs +3%, IV erhöht → LONG BIAS"

#### 2.2.5 — Geopolitik-Signal (automatisiert)
- liveuamap.com Scraper → Event-Count pro Region
- Velocity: >5 Events in 2h = Eskalation
- Verknüpfung: Iran-Events → Brent/EQNR, Ukraine-Events → RHM/PLTR
- Sentiment-Score: "Iran: 8 neue Events, davon 6 militärisch → ESKALATION"

#### 2.2.6 — Insider-Filing Tracker
- SEC EDGAR Form 4 (CEO/CFO Käufe/Verkäufe) — kostenlos
- Filter: nur Käufe > $100k (die sind aussagekräftig)
- Historisch: Insider-Käufe korrelieren mit +8% in 6 Monaten (Studien)
- → "PLTR: CEO kauft $2M in Aktien → Bullish Signal"

#### 2.2.7 — Signal-Fusion
- Einzelne Signale haben 40-60% Accuracy
- Kombiniert: wenn 3+ Signale gleichzeitig für denselben Ticker → 70%+ Accuracy
- **Confluence Score:** Anzahl gleichzeitig aktiver Signale × Gewicht
  ```
  Lead-Lag Signal     × 1.5 (wenn >60% akkurat)
  Candlestick         × 1.0
  Volume Anomaly      × 1.2
  News Sentiment      × 0.8 (oft Noise)
  Insider Filing      × 1.3
  Regime-Bestätigung  × 1.5
  ```
- Nur handeln wenn Confluence ≥ 4.0

---

## 2.3 Conviction Scorer

### Ziel
Ein einzelner Score (0-100) der sagt: wie sicher sind wir bei diesem Trade?

### Sub-Punkte

#### 2.3.1 — Score-Komponenten (7 Faktoren)
```
F1: Signal Confluence    (0-20)  — wie viele Signale bestätigen?
F2: News Momentum        (0-15)  — stützen aktuelle News die These?
F3: Regime-Alignment     (0-15)  — passt der Trade zum Marktregime?
F4: Historical Accuracy  (0-15)  — wie gut war dieses Setup historisch?
F5: VIX-Adjustment       (-20 bis +10) — Risiko-Umfeld
F6: Volumen-Bestätigung  (0-10)  — handelt das Smart Money mit?
F7: Sektor-Stärke        (0-15)  — ist der ganze Sektor stark oder nur diese Aktie?
```

#### 2.3.2 — Conviction-basierte Regeln
- **0-30:** Kein Trade. Nie. Egal was.
- **30-50:** Nur Paper Trading / Watchlist
- **50-70:** Trade erlaubt, 1% Risiko max
- **70-85:** Trade erlaubt, 2% Risiko, Normalposition
- **85-100:** High Conviction, 3% Risiko, größere Position OK

#### 2.3.3 — Self-Calibration
- Nach 50+ Trades: tatsächliche Win-Rate pro Conviction-Bucket messen
- "Conviction 70-85 hat 68% Win-Rate" → gut kalibriert
- "Conviction 30-50 hat 62% Win-Rate" → Score ist zu konservativ, Faktoren anpassen
- Automatisches Re-Weighting der 7 Faktoren basierend auf historischer Performance

---

## 2.4 Strategy DNA Engine

### Ziel
Verstehen: welche Trading-Strategien funktionieren für DIESEN Trader — und welche nicht.

### Sub-Punkte

#### 2.4.1 — Per-Strategy Metrics
Für jede Strategie (S1-S7, PS1-PS5):
- Win Rate (%)
- Ø Gewinn bei Win, Ø Verlust bei Loss
- Expectancy: (WinRate × AvgWin) - (LossRate × AvgLoss)
- Max Consecutive Losses
- Ø Holding-Dauer bei Win vs. Loss
- Beste/Schlechteste Regime

#### 2.4.2 — Trader-Profil
Aus allen Trades ein persönliches Profil erstellen:
- **Stärken:** "Du bist 73% treffsicher bei EMA-Rückläufen in BULL_CALM"
- **Schwächen:** "Breakout-Trades nach 15:30 Uhr: nur 28% Trefferquote"
- **Psychologie:** "Nach einem Verlust-Trade: nächster Trade in <2h hat 22% Win-Rate (Revenge Trading)"
- **Timing:** "Trades vor 10:00 Uhr: 61% Win. Nach 16:00 Uhr: 43% Win."

#### 2.4.3 — Strategy Evolution Tracking
- Versionierung: S1 v1 (März) → S1 v2 (April, angepasst nach Lektion)
- Vorher/Nachher: "S1 v1 hatte 45% WR, nach Anpassung: S1 v2 hat 62% WR"
- Was wurde geändert? → Audit-Trail

#### 2.4.4 — Strategy Kill-Trigger
Automatische Warnung wenn Strategie nicht mehr funktioniert:
- Win Rate < 35% über letzte 10 Trades → "S3 stirbt, überprüfen"
- Expectancy negativ über 20 Trades → "S5 kostet dich Geld — pausieren"
- Max Consecutive Losses > 5 → "S2 hat 6 Verluste hintereinander — sofort stoppen"

---

## 2.5 Backtesting Engine

### Ziel
Jede Strategie gegen historische Daten testen bevor echtes Geld fließt.

### Sub-Punkte

#### 2.5.1 — Backtest-Arten
- **Signal Backtest:** "Hätte Lead-Lag NIKKEI_COPPER in 2025 profitabel gehandelt?"
- **Strategy Backtest:** "S1 (Iran/Öl) mit Entry/Exit-Regeln gegen 2023-2026 Daten"
- **Portfolio Backtest:** "Alle 7 Strategien zusammen — Gesamt-P&L, Max Drawdown"
- **Walk-Forward:** In-Sample (2023-2024) optimieren, Out-of-Sample (2025) testen

#### 2.5.2 — Realismus-Regeln
- **Slippage:** 0.1% pro Trade (realistisch für Retail)
- **Gebühren:** 1€ pro Trade (Trade Republic)
- **Spread:** Mindestens 0.05% (Liquid Stocks) bis 0.3% (Small Caps)
- **Lookback-Bias vermeiden:** Kein Zugriff auf zukünftige Daten im Test
- **Survivorship Bias:** Auch delisted/bankrotte Aktien einbeziehen

#### 2.5.3 — Output-Format
```
Backtest: S1 Iran/Öl | Zeitraum: 2024-01 bis 2026-03
═══════════════════════════════════════════════════
Trades:              47
Win Rate:            59.6%
Avg Win:             +4.2%
Avg Loss:            -2.1%
Expectancy:          +1.64% pro Trade
Max Drawdown:        -8.3%
Sharpe Ratio:        1.42
Profit Factor:       2.01
Best Month:          +12.7% (Okt 2025)
Worst Month:         -5.1% (Jan 2026)
═══════════════════════════════════════════════════
```

---

# LAYER 3 — EXECUTION LAYER

> Empfehlung → Approval → Execution → Tracking

---

## 3.1 Advisory Mode (Phase A — jetzt)

### Sub-Punkte

#### 3.1.1 — Trade Proposal Format
Jede Empfehlung von Albert als strukturiertes Proposal:
```
📊 TRADE PROPOSAL — TRA-47
━━━━━━━━━━━━━━━━━━━━━━━━━━
Ticker:     Equinor ASA (EQNR.OL)
Richtung:   LONG
Entry:      28.40€
Stop:       27.00€ (−4.9%)
Ziel 1:     32.00€ (+12.7%)
Ziel 2:     35.00€ (+23.2%)
CRV:        2.6:1
Conviction: 82/100

Regime:     BULL_VOLATILE
VIX:        22.3
Strategie:  S1 (Iran/Öl)

Signale:
  ✅ Lead-Lag: Brent-WTI Spread $11.20 (>$10)
  ✅ News: 3 bullish Artikel in 6h
  ✅ Technical: EMA20 Support + RSI 42
  ⚠️ Volume: normal (kein Spike)

Risk:
  Position Size: 280€ (2% von 14.000€)
  Max Loss: 39.20€ (Entry → Stop)

APPROVE / REJECT
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### 3.1.2 — Approval-Workflow
- Victor sieht Proposal auf Discord / Dashboard
- Reagiert mit ✅ (approve) oder ❌ (reject)
- Bei Approve → Albert logged Trade in Journal
- Bei Reject → Albert logged Grund → Learning Data

#### 3.1.3 — Execution-Tracking
- Victor führt Trade manuell in TR aus
- Bestätigt: "EQNR long 28.40" → Albert speichert exakten Entry
- Monitor überwacht ab jetzt Stop/Ziel

---

## 3.2 Paper Trading (Phase B)

### Sub-Punkte

#### 3.2.1 — Separates Budget
- 1.000€ Startkapital (Paper)
- Komplett getrennt von Real-Portfolio
- Identische Regeln: 2% Risiko, Stops, Conviction-Minimum

#### 3.2.2 — Automatische Execution
- Albert erkennt Signal → Conviction Check → Position Sizing → "Kauf"
- Kein menschliches Approval nötig
- Alle Trades sofort geloggt mit vollständigem Kontext

#### 3.2.3 — Performance Tracking
- Daily Mark-to-Market
- Vergleich vs. Benchmark (S&P500, Nasdaq)
- Sharpe Ratio, Max Drawdown, Win Rate
- Monatlicher Report an Victor

#### 3.2.4 — Go-Live Kriterien
- Mindestens 3 Monate Paper Trading
- Win Rate > 55%
- Expectancy > 0
- Max Drawdown < 15%
- Sharpe Ratio > 1.0
- → DANN erst Live mit echtem Geld

---

## 3.3 Autonomous Mode (Phase C)

### Sub-Punkte

#### 3.3.1 — Broker-Integration
- IBKR TWS API (Paper + Live Account)
- Order Types: Market, Limit, Stop, Stop-Limit, Trailing Stop
- Pre-Trade Checks: Liquidität, Spread, Handelszeiten

#### 3.3.2 — Mental Stop System
- Keine echten Stop-Orders beim Broker (wegen Market Maker Manipulation)
- Stattdessen: 30-Sekunden Polling während Handelszeiten
- Wenn Kurs < Mental Stop → Market Sell sofort
- Failsafe: wenn 3× kein Preis → Position schließen + Alert

#### 3.3.3 — Risk Management (automatisch)
- Max 5 offene Positionen gleichzeitig
- Max 20% Portfolio in einem Sektor
- Max 3% Risiko pro Trade
- Max Drawdown -15% vom Peak → alle Positionen schließen
- Korrelations-Check: nicht 3× Öl gleichzeitig

#### 3.3.4 — Kill-Switch
- Victor kann jederzeit: "STOP ALL" → alle Positionen sofort geschlossen
- Automatischer Kill bei:
  - Internet-Ausfall > 5 Minuten
  - VIX > 40 (Crash-Modus)
  - Drawdown > 10% in einem Tag

---

# LAYER 4 — USER LAYER

> Erst relevant ab Vermarktung, aber jetzt schon mitdenken.

---

## 4.1 Dashboard
- React + Next.js
- Echtzeit-Updates via WebSocket
- Mobile-First (PWA)
- Tabs: Portfolio | Signals | Journal | Analytics | Settings

## 4.2 Notifications
- Prioritätssystem:
  - P0 (Stop Hit): Push + SMS + WhatsApp
  - P1 (Signal): Push + Discord
  - P2 (Info): nur App-Notification
  - P3 (Daily Summary): Email

## 4.3 Steuer-Tracking (DE)
- FIFO-Berechnung automatisch
- 26.375% Abgeltungssteuer + Soli
- After-Tax P&L anzeigen
- Jahresreport PDF für Steuerberater
- Tax-Loss Harvesting Vorschläge

## 4.4 Trade Import
- Trade Republic CSV Parser
- Scalable Capital CSV
- IBKR Flex Queries
- → Day 1: Portfolio + History sofort da

## 4.5 Onboarding
- 5-Minuten Quiz: Erfahrung, Risiko, Zeitbudget
- Ergebnis: personalisiertes Dashboard + empfohlene Strategien
- Geführter erster Trade
- "Dein Trading-Profil" vom ersten Tag

---

# ZUSAMMENFÜHRUNG — DAS SUPER-MODUL

```
                          ┌──────────────────┐
                          │   Victor (Board)  │
                          │   Approve/Reject  │
                          └────────┬─────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
              ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐
              │  Albert   │ │ Validator │ │   Risk    │
              │ (Analyst) │ │   (QA)    │ │ (Manager) │
              └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
                    │              │              │
         ┌──────────┴──────────────┴──────────────┴──────────┐
         │                INTELLIGENCE ENGINE                 │
         │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ │
         │  │ Regime  │ │ Signal   │ │Conviction│ │  DNA  │ │
         │  │Detector │ │ Engine   │ │ Scorer   │ │Engine │ │
         │  └────┬────┘ └────┬─────┘ └────┬─────┘ └───┬───┘ │
         │       └───────────┴────────────┴────────────┘     │
         │                        │                          │
         └────────────────────────┼──────────────────────────┘
                                  │
         ┌────────────────────────┼──────────────────────────┐
         │              DATA FOUNDATION                      │
         │  ┌───────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌──────┐│
         │  │ Price │ │ News │ │Macro │ │Journal │ │Signal││
         │  │Engine │ │Pipe  │ │Store │ │  DB    │ │  DB  ││
         │  └───────┘ └──────┘ └──────┘ └────────┘ └──────┘│
         └──────────────────────────────────────────────────┘
```

## Reihenfolge der Implementierung

### Sprint 1 (Woche 1-2): Fundament reparieren
- [ ] 1.4 Trade Journal DB Schema + Auto-Enrichment
- [ ] 1.2.2 News Deduplikation
- [ ] 1.5.4 Signal → Trade Verknüpfung in Paperclip

### Sprint 2 (Woche 3-4): Intelligence aufbauen
- [ ] 2.1 Market Regime Detector (VIX + Yields + DXY)
- [ ] 1.3 Macro Store (FRED + Yahoo, 5 Jahre Backfill)
- [ ] 2.3 Conviction Scorer v2 (7 Faktoren)

### Sprint 3 (Woche 5-6): Signal Engine erweitern
- [ ] 2.2.2 Technical Pattern Scanner (EMA/RSI/MACD)
- [ ] 2.2.3 Volume Anomaly Detection
- [ ] 2.2.7 Signal Fusion + Confluence Score

### Sprint 4 (Woche 7-8): Backtesting
- [ ] 2.5 Backtesting Engine (Walk-Forward)
- [ ] 1.1.2 Historische Kurse Backfill (5 Jahre)
- [ ] 2.4 Strategy DNA (erste Auswertung)

### Sprint 5 (Woche 9-12): Execution
- [ ] 3.1 Advisory Mode perfektionieren (Proposals via Discord)
- [ ] 3.2 Paper Trading automatisiert (IBKR Paper API)
- [ ] 3.3 Risk Management Modul

### Sprint 6+ (Monat 4-6): Produkt-Reife
- [ ] 4.1 Dashboard (React/Next.js)
- [ ] 4.2 Notification System
- [ ] 4.3 Steuer-Tracking
- [ ] 4.4 Trade Import
- [ ] 4.5 Onboarding

---

*Dieses Dokument wird nach jedem Sprint aktualisiert.*
*Jeder abgeschlossene Punkt wird mit Datum + Commit markiert.*
