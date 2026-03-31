# 🎩 TradeMind CEO — Upgrade Blueprint v1.0

**Erstellt:** 31.03.2026 | **Status:** PLAN | **Ziel:** CEO von 6.5/10 auf 9/10
**Autor:** Albert | **Auftraggeber:** Victor

---

## Ausgangslage (CEO v1.0 — aktuell)

| Bereich | Score | Status |
|---|---|---|
| Architektur | 8/10 | ✅ Solide Basis |
| Risikomanagement | 7/10 | ⚠️ Modi gut, Metriken schwach |
| Datenquellen | 5/10 | ❌ Nur statische Dateien |
| Quant-Tiefe | 4/10 | ❌ Keine Risk-Adjusted Metrics |
| Position Sizing | 3/10 | ❌ Statisch, kein Kelly |
| Korrelation | 0/10 | ❌ Nicht vorhanden |
| Geopolitik-NLP | 6/10 | ⚠️ Infrastruktur da, CEO nutzt sie nicht |
| Stress-Testing | 0/10 | ❌ Nicht vorhanden |

**Gesamtnote: 6.5/10**

---

## Zielarchitektur (CEO v3.0)

```
┌─────────────────────────────────────────────────┐
│              TradeMind CEO v3.0                  │
│         "Das zentrale Nervensystem"              │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ MARKET   │  │ RISK     │  │ SIGNAL   │      │
│  │ BRAIN    │  │ ENGINE   │  │ SCORER   │      │
│  │          │  │          │  │          │      │
│  │ • VIX    │  │ • Sharpe │  │ • Entry  │      │
│  │ • Regime │  │ • Kelly  │  │ • Exit   │      │
│  │ • Sector │  │ • VaR    │  │ • Trail  │      │
│  │ • Correl │  │ • Correl │  │ • Scale  │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │              │              │            │
│       └──────────┬───┘──────────────┘            │
│                  ▼                                │
│  ┌──────────────────────────────────────┐        │
│  │         DECISION ENGINE              │        │
│  │  Mode × Risk × Signal → Directive    │        │
│  └──────────────┬───────────────────────┘        │
│                 │                                 │
│       ┌─────────┴─────────┐                      │
│       ▼                   ▼                      │
│  ┌─────────┐        ┌─────────┐                  │
│  │  REAL   │        │ PAPER   │                  │
│  │ TRADING │        │   LAB   │                  │
│  │ (konserv│        │ (exper- │                  │
│  │  ativ)  │        │ mentell)│                  │
│  └─────────┘        └─────────┘                  │
│                                                  │
│  ┌──────────────────────────────────────┐        │
│  │         GEO-INTEL LAYER              │        │
│  │  Trump Watch • PIFS • NewsWire       │        │
│  │  Liveuamap • Congressional Flow      │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│  ┌──────────────────────────────────────┐        │
│  │         LEARNING ENGINE              │        │
│  │  Accuracy Tracker • Strategy DNA     │        │
│  │  Regime Classifier • Post-Mortem     │        │
│  └──────────────────────────────────────┘        │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## Phase 1: Risk Engine (CEO v1.5)
**Zeitrahmen:** 1 Woche | **Priorität:** KRITISCH | **Impact:** 6.5 → 7.5

### P1.A — Risk-Adjusted Metrics
**Was:** Sharpe Ratio, Sortino Ratio, Calmar Ratio einbauen
**Warum:** Win-Rate allein ist irreführend. 30% WR mit 3:1 CRV schlägt 60% WR mit 0.5:1 CRV.
**Wo:** Neue Funktion `calculate_risk_metrics()` in `ceo.py`

```python
# Zu berechnen:
# 1. Sharpe Ratio = (Portfolio Return - Risk Free Rate) / Portfolio StdDev
#    - Risk Free Rate: 4.5% (US 10Y Treasury aktuell)
#    - Annualisiert: √252 × daily Sharpe
#    - Ziel: > 1.0 (gut), > 2.0 (exzellent)
#
# 2. Sortino Ratio = (Return - Risk Free) / Downside Deviation
#    - Wie Sharpe, aber nur negative Volatilität zählt
#    - Ziel: > 1.5
#
# 3. Calmar Ratio = Annualized Return / Max Drawdown
#    - Misst Return pro Einheit Drawdown-Risiko
#    - Ziel: > 1.0
#
# 4. Profit Factor = Gross Profit / Gross Loss
#    - Einfachste Metrik: wieviel verdienst du pro Euro Verlust?
#    - Ziel: > 1.5
#
# 5. CRV (Chance-Risiko-Verhältnis) pro Trade
#    - Avg Win / Avg Loss
#    - System muss CRV > 1.5 anstreben
#
# 6. Expectancy = (WR × Avg Win) - ((1-WR) × Avg Loss)
#    - Erwartungswert pro Trade in EUR
#    - Muss POSITIV sein, sonst System unprofitabel
```

**Daten:** Alles aus `paper_portfolio` Tabelle berechenbar (entry_price, exit_price, pnl_eur, shares)

**CEO-Integration:**
- `determine_trading_mode()` nutzt Sharpe + Sortino statt nur Win-Rate
- SHUTDOWN-Trigger: Sharpe < -1.0 ODER Expectancy < 0 über 30 Trades
- Report zeigt alle 6 Metriken

### P1.B — Korrelationsmatrix
**Was:** Portfolio-Konzentration erkennen und steuern
**Warum:** 5 Öl-Positionen = 1 große Position. CEO muss das wissen.
**Wo:** Neue Funktion `calculate_correlation_matrix()` in `ceo.py`

```python
# Methodik:
# 1. Für alle offenen Positionen: Sektor + Sub-Sektor aus strategies.json
# 2. Historische Preis-Korrelation (Pearson) aus trading.db
#    - Korrelation > 0.7 = "quasi gleiche Position"
#    - Korrelation < -0.3 = "natürlicher Hedge"
# 3. Portfolio Concentration Index (HHI)
#    - HHI = Σ(Gewicht²) für jeden Sektor
#    - HHI > 0.25 = konzentriert → Warnung
#    - HHI > 0.50 = gefährlich konzentriert → max 1 neue Position in dem Sektor
#
# Output: concentration_warnings[] in Direktive
# Beispiel: "⚠️ 68% des Portfolios in Energy — max 1 neue Öl-Position"
```

**Daten-Anforderung:** Braucht historische Preisdaten in DB (aus trading_monitor.py bereits vorhanden: `price_history` Tabelle)

**CEO-Integration:**
- Neue Sektion `portfolio_concentration` in der Direktive
- `build_trading_rules()` blockt Sektoren die über HHI-Limit sind
- Report zeigt: "Portfolio-Balance: Energy 45% | Metals 30% | Tech 25%"

### P1.C — Volatility-Adjusted Position Sizing (Kelly Criterion)
**Was:** Optimale Positionsgröße pro Trade berechnen
**Warum:** €2.000 für jeden Trade ist falsch. Ein Trade mit 70% WR und 3:1 CRV verdient mehr Kapital als einer mit 40% WR und 1.5:1 CRV.
**Wo:** Neue Funktion `calculate_position_size()` in `ceo.py`

```python
# Kelly Criterion (modifiziert — "Half Kelly" für Sicherheit):
#
# Kelly% = (WR × CRV - (1 - WR)) / CRV
# Position Size = Kelly% × Portfolio × 0.5 (Half Kelly)
#
# Beispiel:
#   WR = 60%, CRV = 2.0
#   Kelly = (0.60 × 2.0 - 0.40) / 2.0 = 0.40 = 40%
#   Half Kelly = 20% des Portfolios
#   Bei €25.000 Portfolio = €5.000 Positionsgröße
#
# Beispiel 2:
#   WR = 35%, CRV = 1.2
#   Kelly = (0.35 × 1.2 - 0.65) / 1.2 = -0.19 = NEGATIV
#   → Trade NICHT eingehen! Negativer Erwartungswert.
#
# Sicherheitsregeln:
#   - Max Position = 15% des Portfolios (auch wenn Kelly höher)
#   - Min Position = €200 (sonst fressen TR-Gebühren die Rendite)
#   - Kelly < 0 = KEIN TRADE (Erwartungswert negativ)
#   - Im DEFENSIVE Mode: Max 10% statt 15%
#
# VIX-Adjustment:
#   - VIX < 20: Kelly × 1.0 (normal)
#   - VIX 20-28: Kelly × 0.75 (reduziert)
#   - VIX 28-35: Kelly × 0.50 (stark reduziert)
#   - VIX > 35: Kelly × 0.25 (minimal)
```

**CEO-Integration:**
- `trading_rules` enthält nicht mehr statische `max_position_size_eur`
- Stattdessen: `position_sizing: { method: "half_kelly", vix_adj: 0.75, max_pct: 15 }`
- Entry Signal Engine liest Kelly-Werte und berechnet exakte Positionsgröße pro Trade

---

## Phase 2: Market Brain (CEO v2.0)
**Zeitrahmen:** 2 Wochen | **Priorität:** HOCH | **Impact:** 7.5 → 8.5

### P2.A — Live-Daten-Integration
**Was:** CEO liest aktuelle Marktdaten statt statische Dateien
**Warum:** Die Direktive basiert auf Daten die Stunden alt sein können.

```python
# Datenquellen (kostenlos):
# 1. Yahoo Finance API (bereits in trading_monitor.py)
#    - VIX, S&P 500, Sektorindizes, Einzeltitel
#    - Rate Limit: ~2000/Stunde (kein Key nötig)
#
# 2. Finnhub (bereits API Key vorhanden)
#    - Market News, Company News
#    - 60 calls/min
#
# 3. Alpha Vantage (Key: 0QEDLYI734MI7O5T)
#    - Technische Indikatoren (RSI, MACD, Bollinger)
#    - 25 calls/Tag (Free) — sparsam nutzen!
#
# Neuer Flow:
#   ceo.py --live
#   → Holt VIX, SPY, Sektor-ETFs live
#   → Berechnet Regime aus Live-Daten
#   → Schreibt Direktive mit aktuellem Marktstand
#
# Caching: Ergebnisse in data/market_cache.json (TTL: 5 Min)
# Damit: CEO kann 4x täglich live laufen statt 1x mit alten Daten
```

### P2.B — Regime-Klassifikator (Enhanced)
**Was:** Marktregime automatisch erkennen statt aus Datei lesen
**Warum:** Aktuelles `market-regime.json` wird extern geschrieben und kann veraltet sein.

```python
# Regime-Typen:
# 1. BULL_TREND    — SPY > MA200 + MA50 > MA200 + VIX < 20
# 2. BULL_VOLATILE — SPY > MA200 + VIX 20-30
# 3. RANGE_BOUND   — SPY ±5% um MA200 + kein klarer Trend
# 4. CORRECTION    — SPY 10-20% unter ATH + VIX 25-35
# 5. BEAR_TREND    — SPY < MA200 + MA50 < MA200 + VIX > 25
# 6. CRASH         — SPY > 20% unter ATH ODER VIX > 40
#
# Zusätzlich: Sektor-Regime
#   - Für jeden Sektor-ETF (XLE, XLF, XLK, XLV, XLI, XLB)
#   - Gleiche Logik: Trend + Volatilität
#   - CEO weiß dann: "Energy ist im Bull-Trend, Tech ist in Correction"
#
# Daten: 200 Tage History aus Yahoo Finance (einmal laden, täglich updaten)
# Storage: data/regime_history.json (Zeitreihe)
```

### P2.C — Erweiterte Geo-Intel-Integration
**Was:** CEO liest aktiv NewsWire-Daten und berechnet echten Geo-Score
**Warum:** Aktueller Geo-Score zählt nur aktive Strategien — das ist keine Analyse.

```python
# Neuer Geo-Score (0-100):
#
# Quellen (bereits vorhanden, CEO nutzt sie nicht):
# 1. newswire-analysis.md → Sentiment + Magnitude
# 2. overnight_events in DB → Letzte 24h Events
# 3. Trump Truth Social (trumpstruth.org/feed) → Keywords
# 4. Liveuamap-Regionen → Eskalationslevel
#
# Berechnung:
#   base_score = 0
#   + Σ(event.magnitude × event.sector_relevance) für Events letzte 24h
#   + trump_escalation_keywords × 15 (wenn "bomb", "destroy", "war")
#   + trump_deescalation_keywords × -10 (wenn "deal", "peace", "progress")
#   + liveuamap_event_count × 2 (für Iran, Israel, Hormuz)
#   + congressional_flow_anomaly × 20 (PIFS Peace Basket alert)
#
# Output:
#   geo_score: 72
#   geo_trend: "ESCALATING" | "STABLE" | "DEESCALATING"
#   geo_hotspots: ["Iran/Hormuz", "Taiwan Strait"]
#   geo_trades_affected: ["EQNR", "OXY", "LHA.DE"]
```

### P2.D — Stress-Testing / Scenario Analysis
**Was:** "Was passiert wenn...?" Szenarien berechnen
**Warum:** CEO muss vorbereitet sein, nicht nur reagieren.

```python
# Szenarien (automatisch berechnet):
#
# 1. VIX Spike (+50%):
#    - Alle offenen Positionen: geschätzter P&L bei aktuellem Stop
#    - Portfolio Max-Loss wenn alle Stops gleichzeitig getriggert
#
# 2. Sector Crash (-10%):
#    - Für jeden Sektor: was passiert wenn er 10% fällt?
#    - Welche Positionen sind betroffen?
#
# 3. Iran Peace Deal (unser spezifisches Szenario):
#    - EQNR: -8% bis -12%
#    - OXY, XOM: -5% bis -8%
#    - LHA.DE: +15% bis +25%
#    - Netto Portfolio-Effekt?
#
# 4. Liberation Day Worst Case (Trumps Zölle):
#    - Tech: -5% bis -8%
#    - Energy: ±2%
#    - Industrials: -3% bis -5%
#
# 5. Flash Crash (SPY -5% intraday):
#    - Alle Stops getriggert? Gesamt-Verlust?
#    - Slippage-Schätzung (Stops ≠ exakter Preis)
#
# Output in Direktive:
#   stress_tests: {
#     "max_portfolio_loss_all_stops": -€2,340,
#     "iran_peace_net_impact": +€890,
#     "vix_spike_impact": -€1,200,
#     "sector_concentration_risk": "HIGH — 60% Energy"
#   }
```

---

## Phase 3: Learning Engine (CEO v2.5)
**Zeitrahmen:** 2-3 Wochen | **Priorität:** MITTEL | **Impact:** 8.5 → 9.0

### P3.A — Post-Mortem Analyzer
**Was:** Automatische Analyse JEDES geschlossenen Trades
**Warum:** Wir lernen aktuell nur aus Win-Rate. Jeder Trade hat eine Story.

```python
# Für jeden geschlossenen Trade:
#
# 1. Entry-Qualität (0-10):
#    - War der Entry-Zeitpunkt gut? (Kurs vs. Tages-Range)
#    - War der Conviction Score korrekt?
#    - Welches Regime herrschte beim Entry?
#
# 2. Exit-Qualität (0-10):
#    - Stop-Hit oder Take-Profit?
#    - Wie weit lief der Kurs NACH dem Exit? (verpasster Gewinn)
#    - War der Exit zu früh / zu spät?
#
# 3. Holding Period Analyse:
#    - Optimale Haltedauer für diese Strategie?
#    - Gewinner werden zu früh verkauft? (Disposition Effect)
#    - Verlierer werden zu lange gehalten?
#
# 4. Regime-Match:
#    - Welches Regime war am profitabelsten für diese Strategie?
#    - Sollte die Strategie nur in bestimmten Regimen aktiv sein?
#
# Output: data/trade_postmortems.json
# CEO liest das und passt Strategie-Parameter automatisch an
```

### P3.B — Strategy DNA Evolution
**Was:** Strategie-Parameter automatisch optimieren basierend auf historischer Performance
**Warum:** Statische Parameter (Stop bei -8%, Ziel bei +12%) sind suboptimal.

```python
# Für jede Strategie mit 10+ geschlossenen Trades:
#
# 1. Optimaler Stop-Abstand:
#    - Analyse: bei welchem Stop-Level waren die meisten Trades profitabel?
#    - Ergebnis: "S1 performt am besten mit Stop bei -6%, nicht -8%"
#
# 2. Optimaler Take-Profit:
#    - Analyse: wie weit liefen Gewinner im Schnitt?
#    - Ergebnis: "S1 Gewinner laufen im Schnitt +14% — TP bei +12% ist zu eng"
#
# 3. Optimale Holding Period:
#    - Analyse: Trades < 3 Tage: 20% WR, 3-10 Tage: 45% WR, > 10 Tage: 35% WR
#    - Ergebnis: "S1 braucht 3-10 Tage zum Reifen — kein Day Trading!"
#
# 4. Regime-Filter:
#    - "S3 (KI/Halbleiter) nur in BULL_TREND und BULL_VOLATILE"
#    - "S1 (Iran/Öl) funktioniert in jedem Regime" ← das wäre ein wichtiges Finding
#
# Umsetzung:
#   - data/strategy_dna.json wird von CEO automatisch geschrieben
#   - Entry Signal Engine liest DNA und passt Parameter an
#   - Victor bekommt wöchentlichen "Evolution Report"
```

### P3.C — Anomaly Detection
**Was:** Ungewöhnliche Muster automatisch erkennen
**Warum:** Der beste Edge kommt aus Dingen die andere nicht sehen.

```python
# Pattern-Erkennung:
#
# 1. Volume Anomalies:
#    - Ticker X handelt 3× durchschnittliches Volumen → Alert
#    - Sektor Y handelt 2× Volumen → Sektor-Rotation?
#
# 2. Correlation Breaks:
#    - EQNR und Ölpreis normalerweise Korrelation 0.85
#    - Heute: Korrelation 0.3 → etwas stimmt nicht → Alert
#
# 3. Congressional Flow Anomaly:
#    - Normalerweise 5 Trades/Woche in Energy
#    - Diese Woche: 20 Trades → Smart Money bewegt sich
#
# 4. News-Sentiment Divergence:
#    - Nachrichtenlage negativ, aber Kurs steigt → Insider kaufen?
#    - Nachrichtenlage positiv, aber Kurs fällt → Smart Money verkauft?
#
# 5. Trump Pattern Recognition:
#    - "Deal" + "shortly" + positive Sprache = De-Eskalation wahrscheinlich
#    - "Destroy" + "obliterate" + Drohungen = Eskalation oder Verhandlungstaktik?
#    - Historisches Pattern-Matching gegen seine früheren Posts
```

---

## Phase 4: Autonomous Intelligence (CEO v3.0)
**Zeitrahmen:** 4-6 Wochen | **Priorität:** ZUKUNFT | **Impact:** 9.0 → 9.5

### P4.A — Adaptive Mode Switching ✅ DONE (31.03.2026)
**Was:** CEO wechselt Modi nicht nur anhand fester Schwellen, sondern lernt optimale Schwellen
**Status:** Implementiert — `calculate_adaptive_thresholds()` berechnet adaptive VIX-Schwellen aus:
- VIX-History (vix_history.json, max 200 Einträge, täglich append)
- DB regime_history + trades Tabelle als Fallback
- 30d Statistik (avg, std, z-score)
- Performance-Feedback: VIX 25-32 Trades → WR prüft ob Schwelle hoch/runter
- Integration in `determine_trading_mode()`, Direktive-Sektion `adaptive_thresholds`, Report

### P4.B — Multi-Timeframe Integration ✅ DONE (31.03.2026)
**Was:** CEO analysiert Daily, Weekly, Monthly Timeframes gleichzeitig
**Status:** Implementiert — `analyze_multi_timeframe()` analysiert SPY + 6 Sektor-ETFs:
- Daily (Price vs MA50), Weekly (MA50 vs MA200), Monthly (Price vs MA200 ±5%)
- Alignment: ALIGNED_BULL | ALIGNED_BEAR | MIXED
- Trading Bias: LONG_ONLY | CAUTIOUS_LONG | NEUTRAL
- Integration: ALIGNED_BEAR → mindestens DEFENSIVE, CAUTIOUS_LONG → max 10d Haltedauer
- Direktive-Sektion `multi_timeframe`, Report zeigt alle Sektoren + Bias

### P4.C — Portfolio Optimization (Mean-Variance)
**Was:** Markowitz-Optimierung für optimale Portfolio-Allokation
**Beispiel:** Gegeben 10 Kandidaten und Budget €10.000 → welche Kombination maximiert Return bei gegebenem Risiko?

### P4.D — Backtesting Engine
**Was:** Jede Strategie-Änderung wird gegen historische Daten getestet BEVOR sie live geht
**Beispiel:** "Neuer Stop bei -6% statt -8% → Backtest: +12% mehr Gewinn, -3% mehr Drawdown → Akzeptiert."

---

## Implementation Roadmap

```
KW 14 (31.03 - 06.04):
├── P1.A: Risk-Adjusted Metrics ────────── 2-3 Tage
├── P1.B: Korrelationsmatrix ───────────── 1-2 Tage
└── P1.C: Kelly Position Sizing ────────── 1-2 Tage
    → CEO v1.5 RELEASE → Ziel: 7.5/10

KW 15-16 (07.04 - 20.04):
├── P2.A: Live-Daten-Integration ───────── 3-4 Tage
├── P2.B: Enhanced Regime Klassifikator ── 2-3 Tage
├── P2.C: Geo-Intel Integration ────────── 2-3 Tage
└── P2.D: Stress-Testing ──────────────── 2-3 Tage
    → CEO v2.0 RELEASE → Ziel: 8.5/10

KW 17-19 (21.04 - 11.05):
├── P3.A: Post-Mortem Analyzer ─────────── 3-4 Tage
├── P3.B: Strategy DNA Evolution ───────── 3-4 Tage
└── P3.C: Anomaly Detection ───────────── 3-4 Tage
    → CEO v2.5 RELEASE → Ziel: 9.0/10

KW 20-25 (12.05 - 22.06):
├── P4.A: Adaptive Mode Switching ──────── 1 Woche
├── P4.B: Multi-Timeframe ─────────────── 1 Woche
├── P4.C: Portfolio Optimization ───────── 1-2 Wochen
└── P4.D: Backtesting Engine ──────────── 2 Wochen
    → CEO v3.0 RELEASE → Ziel: 9.5/10
```

---

## Technische Constraints

- **Keine externen Abhängigkeiten** — nur Python stdlib + sqlite3 + urllib
- **Kein Paid API** — Yahoo Finance (free), Finnhub (free), Alpha Vantage (free 25/day)
- **Keine GPU** — kein ML das GPU braucht. Alle Berechnungen CPU-basiert.
- **Cron-kompatibel** — jeder CEO-Lauf muss in <30 Sekunden abschließen
- **Backward-kompatibel** — `ceo_directive.json` Format erweitern, nicht brechen
- **Paper Lab zuerst** — jedes Feature wird erst im Paper Lab getestet bevor es Real Trading beeinflusst

---

## Erfolgsmetriken

| Metrik | Aktuell | Nach v1.5 | Nach v2.0 | Nach v3.0 |
|---|---|---|---|---|
| Win-Rate | 21% | 30%+ | 35%+ | 40%+ |
| Sharpe Ratio | N/A | > 0.5 | > 1.0 | > 1.5 |
| Profit Factor | N/A | > 1.2 | > 1.5 | > 2.0 |
| Max Drawdown | 12.9% | < 15% | < 12% | < 10% |
| Avg Holding Period | ? | Optimiert | Regime-angepasst | Adaptive |
| Geo-Score Genauigkeit | ~30% | 50% | 70% | 85% |
| False Signals (Paper) | ~60% | 45% | 30% | 20% |

---

## Was das System EINZIGARTIG macht (vs. Konkurrenz)

Kein Trading-Bot auf dem Markt hat:
1. **Geopolitik-NLP** — Trump Truth Social + Liveuamap + Congressional Flows
2. **Strategy Validation Gate** — Thesis/Negation/Horizon PFLICHT vor jedem Trade
3. **Dual-Mode** — Real (konservativ, Victor entscheidet) + Paper Lab (experimentell, Albert entscheidet)
4. **Iran Peace Watch** — spezifischer Trigger für Rotations-Trade EQNR → LHA
5. **CEO als Orchestrator** — nicht nur Signalgeber, sondern vollständiger Entscheidungsbaum

Das ist unser Moat. Die Quant-Tiefe können andere auch — aber die Geopolitik-Integration ist Innovation.

---

## Nächster Schritt

Victor entscheidet: **Starten wir Phase 1 diese Woche?**
Wenn ja, beginne ich mit P1.A (Risk-Adjusted Metrics) — das ist der höchste Impact pro Zeiteinheit.
