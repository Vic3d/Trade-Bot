# TradeMind — Professionalisierungs-Bauplan 🎩

**Erstellt:** 2026-03-26 | **Von:** Albert
**Ziel:** Von Prototyp (5/10) zu professionellem Standard (8/10) — ohne bezahlte APIs
**Budget:** €0 (nur kostenlose Datenquellen + eigene Rechenpower)
**Zeithorizont:** 6 Wochen (7 Phasen)

---

## Ausgangslage — Brutal Ehrlich

### Was wir haben
- 58 Python-Scripts (23.000 LOC), 286 Dateien
- SQLite DB: 180 Trades, 22.000 Preisdaten, 17.000 Makro-Daten, 1.261 Regime-Einträge
- 38 Cron-Jobs (alle Haiku = kosteneffizient)
- Geopolitischer Scanner (einzigartig im Retail-Bereich)
- Strategie Albert mit geschlossener Feedback-Loop
- Paper Trading mit 3 Styles (disciplined, aggressive, contrarian)

### Was NICHT funktioniert
| Problem | Ist | Soll | Impact |
|---|---|---|---|
| VIX-Daten bei Trades | 13% erfasst | 100% | Ohne das ist VIX-Strategie nicht validierbar |
| Preis-DB | 9 Tage veraltet | Täglich aktuell | Historische Analyse hat Lücken |
| Scripts | 58 lose Dateien, 17 redundant | 1 Package, ~25 Module | Wartbar, testbar, erweiterbar |
| Backtesting | Minimal, nicht valide | Walk-Forward, statistisch belastbar | Wissen ob Strategien ECHT funktionieren |
| Risikomanagement | Nur ATR-Stops | Portfolio-Level, Korrelation, Stress-Tests | Überleben bei Crash |
| CRV-Daten | 8% erfasst | 100% | Kernmetrik fehlt |
| Signal ↔ Trade Link | 0 Einträge | Lückenlos | Lernen unmöglich ohne Kausalkette |
| Strategie-Bewertung | "Win Rate" | Sharpe, Sortino, Max DD, p-value | Wissen was Zufall ist vs. Edge |

---

## Phase 1: Fundament — Datenqualität fixen (Woche 1)

> *"Müll rein = Müll raus. Erst die Daten, dann alles andere."*

### 1.1 Preis-DB täglich aktualisieren
**Problem:** Letzte Preise vom 17.03. — 9 Tage Lücke.
**Lösung:** Cron-Job der täglich um 23:30 alle Ticker aktualisiert.

```
Quellen (kostenlos):
- Yahoo Finance (yfinance Python-Lib) → US, UK, Oslo, HK Aktien + FX + Indizes
- Onvista Scraping → DE-Aktien (DR0.DE, RHM.DE, BAYN.DE)
- Kein Alpha Vantage nötig (yfinance ist unbegrenzt bei moderate usage)
```

**Script:** `trademind/data/price_updater.py`
- Alle Ticker aus `ticker_meta` + offene Positionen
- Upsert in `prices`-Tabelle (kein Duplikat)
- Error-Logging (welche Ticker fehlgeschlagen)
- **Rückfüllung:** Einmalig letzte 2 Jahre holen (yfinance `period="2y"`)

**Aufwand:** 2-3 Stunden
**Cron:** `30 23 * * 1-5` (Mo-Fr nach Börsenschluss)

### 1.2 VIX + Regime bei JEDEM Trade erfassen
**Problem:** Nur 13% der Trades haben VIX-Daten.
**Lösung:** In der Shared Library (Phase 2) wird `get_vix()` und `get_regime()` IMMER aufgerufen — bei Open UND Close.

**Quick Fix jetzt:** Rückwirkend VIX für alle 180 Trades aus `macro_daily` nachfüllen.

```python
# Pseudocode
for trade in all_trades:
    vix = macro_daily.get(trade.entry_date, 'vix_close')
    trade.vix_at_entry = vix
    if trade.exit_date:
        trade.vix_at_exit = macro_daily.get(trade.exit_date, 'vix_close')
```

**Aufwand:** 1 Stunde (einmaliges Backfill-Script + Integration in Shared Lib)

### 1.3 CRV für alle Trades berechnen
**Problem:** Nur 8% haben CRV.
**Lösung:** CRV ist berechenbar: `(target - entry) / (entry - stop)` oder wenn kein Target: default 3:1.

**Rückwirkend:** Für alle 180 Trades CRV aus Entry/Stop/Target berechnen.
**Prospektiv:** Automatisch beim Trade-Open.

**Aufwand:** 30 Minuten

### 1.4 Leere Tabellen befüllen oder löschen
- `signals`: Entweder aktiv befüllen (jedes Scanner-Signal) oder DROP
- `trade_news_link`: News-Events mit Trades verknüpfen (Scanner-Run → Trade)
- `trade_signal_link`: Signal → Trade Mapping
- `earnings_calendar`: Quarterly earnings für gehaltene Ticker importieren (Yahoo Finance gratis)

**Entscheidung:** signals + earnings = BEFÜLLEN. Links = Phase 3 (braucht erst Shared Lib).

**Aufwand:** 2 Stunden

### Phase 1 Deliverables
- [x] Preis-DB aktuell (2 Jahre History + täglicher Cron) ✅ 2026-03-26 — 25.998 Zeilen, 51 Ticker
- [x] 100% VIX-Coverage auf allen Trades ✅ 156 Entry + 158 Exit gefüllt → 0 NULL
- [x] 100% CRV-Coverage auf allen Trades ✅ 160 gesetzt (153 berechnet + 7 Default) → 5 NULL (Stop=Entry, unlösbar)
- [ ] Earnings-Kalender gefüllt (nächste 3 Monate) — Phase 1.4 offen
- [ ] signals-Tabelle aktiv oder gelöscht — Phase 1.4 offen

### Phase 1 Status: TEILWEISE ABGESCHLOSSEN (2026-03-26)
**Erledigt:** 1.1 (Preis-Backfill) + 1.2 (VIX+Regime) + 1.3 (CRV) + 1.4 (Cron-Script)
**Offen:** Earnings-Kalender, signals-Tabellen-Entscheidung
**Script:** `trademind/data/price_updater.py` — Cron: `30 23 * * 1-5 python3 trademind/data/price_updater.py --mode daily`
**Hinweis:** YARA.OL delisted bei Yahoo Finance (404) — Ticker prüfen

**Gesamtaufwand Phase 1:** ~1 Tag
**Validierung:** `python3 -c "SELECT COUNT(*) FROM trades WHERE vix_at_entry IS NULL"` → 0

---

## Phase 2: Architektur — Code konsolidieren (Woche 1-2)

> *"57 Scripts ist kein System. Es ist ein Haufen."*

### 2.1 Python Package `trademind/`

```
trademind/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── db.py              ← Einziger DB-Zugang (Connection Pool, Migrations)
│   ├── config.py           ← Trading-Config laden/validieren
│   ├── market_data.py      ← Yahoo, Onvista, FX — EINE Stelle für Preise
│   ├── vix.py              ← VIX holen + Zonen berechnen
│   ├── regime.py           ← Markt-Regime erkennen (ADX, MA, Momentum)
│   └── position_sizing.py  ← ATR, VIX-adaptiv, Kelly Criterion
│
├── strategies/
│   ├── __init__.py
│   ├── base.py             ← Abstrakte Klasse: scan(), enter(), exit(), review()
│   ├── albert.py           ← SA: Geopolitischer Kontra-Sniper
│   ├── day_trader.py       ← DT1-DT9 konsolidiert
│   ├── swing.py            ← PS1-PS5 (Paper Swing)
│   └── registry.py         ← Alle Strategien registriert, einheitlich aufrufbar
│
├── risk/
│   ├── __init__.py
│   ├── portfolio.py        ← Portfolio-Level Risiko (Korrelation, Exposure)
│   ├── correlation.py      ← Pairwise Korrelation + Cluster-Erkennung
│   ├── stress_test.py      ← "Was wenn VIX auf 50?" Szenarien
│   └── circuit_breaker.py  ← Max Drawdown Stop, Daily Loss Limit
│
├── analytics/
│   ├── __init__.py
│   ├── metrics.py          ← Sharpe, Sortino, Calmar, Max DD, p-value
│   ├── attribution.py      ← P&L Zerlegung: Strategie, Timing, Sizing
│   ├── learning.py         ← Post-Mortem, Insights, Meta-Reviews
│   └── backtester.py       ← Walk-Forward, Out-of-Sample, Monte Carlo
│
├── signals/
│   ├── __init__.py
│   ├── scanner.py          ← Geopolitischer Scanner (unified)
│   ├── news.py             ← News Fetcher + NLP Scoring
│   ├── technicals.py       ← RSI, MACD, Bollinger, ATR (ta-lib oder manuell)
│   └── earnings.py         ← Earnings Calendar + Surprise Detection
│
├── execution/
│   ├── __init__.py
│   ├── paper.py            ← Paper Trading Engine (mit Slippage-Modell!)
│   ├── broker_base.py      ← Abstrakte Broker-Klasse (für später: IBKR, TR)
│   └── simulator.py        ← Realistische Fills (Spread, Gap, Partial Fill)
│
├── reporting/
│   ├── __init__.py
│   ├── daily.py            ← Morgen-Briefing, Abend-Report
│   ├── weekly.py           ← Wochen-Report
│   └── dashboard.py        ← Dashboard-Daten generieren
│
└── cli.py                  ← Einziger Einstiegspunkt: `python3 -m trademind <cmd>`
```

### 2.2 Migration der 58 Scripts

| Kategorie | Anzahl | Aktion |
|---|---|---|
| **CORE** (behalten, refactoren) | 9 | → `trademind/strategies/`, `trademind/signals/` |
| **REDUNDANT** (löschen/mergen) | 17 | → Archiv `scripts/_archive/`, Code in Package übernehmen |
| **UTILITY** (zu Shared Lib) | 9 | → `trademind/core/`, `trademind/analytics/` |
| **DASHBOARD** | 3 | → `trademind/reporting/` |
| **SPECIALIZED** (prüfen) | 19 | Je nach Nutzung: keep oder archive |

### 2.3 Strategie-Interface (Kern-Design)

```python
class Strategy(ABC):
    """Jede Strategie implementiert dieses Interface."""
    
    @abstractmethod
    def scan(self) -> list[Signal]:
        """Markt scannen → Liste von Signalen zurückgeben."""
        
    @abstractmethod
    def should_enter(self, signal: Signal) -> TradeProposal | None:
        """Signal bewerten → Trade-Vorschlag oder None."""
    
    @abstractmethod
    def should_exit(self, position: Position) -> ExitDecision | None:
        """Offene Position prüfen → Exit-Entscheidung oder None (halten)."""
    
    @abstractmethod
    def post_mortem(self, trade: ClosedTrade) -> PostMortem:
        """Geschlossenen Trade analysieren → Lektionen extrahieren."""
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def max_positions(self) -> int: ...
    
    @property
    @abstractmethod
    def min_crv(self) -> float: ...
```

**Vorteil:** Neue Strategien in 50 Zeilen statt 500. Einheitliches Reporting. Einheitliche Datenerfassung.

### Phase 2 Deliverables
- [x] `trademind/` Package mit allen Core-Modulen ✅ 2026-03-26
  - `trademind/core/config.py` — Zentrale Pfade + Konstanten
  - `trademind/core/db.py` — get_db() + managed_db() Context-Manager
  - `trademind/core/vix.py` — get_vix() + get_vix_zone()
  - `trademind/core/regime.py` — get_regime() aus market-regime.json
  - `trademind/core/market_data.py` — get_price_yahoo(), to_eur(), get_atr()
  - `trademind/core/position_sizing.py` — calculate_position() VIX-adaptiv
  - `trademind/strategies/base.py` — Abstrakte Strategy Base Class (ABC)
  - `trademind/cli.py` — CLI Entry Point (stats, vix, regime, prices, sa)
  - `trademind/__main__.py` — python3 -m trademind Entry Point
- [x] 17 redundante Scripts archiviert → scripts/_archive/ ✅ 2026-03-26
- [ ] Alle Crons nutzen `python3 -m trademind <cmd>` statt individuelle Scripts — Phase 2.2 offen
- [ ] Tests: `python3 -m pytest trademind/tests/` (mindestens Smoke Tests) — Phase 2.2 offen

**Gesamtaufwand Phase 2:** 3-4 Tage (1 Tag erledigt: Core + Archive)
**Validierung:** `python3 -m trademind stats` läuft ✅ — 167 Trades, VIX 100%, CRV 98%

### Phase 2 Status: TEILWEISE ABGESCHLOSSEN (2026-03-26)
**Erledigt:** Core-Module (6), Strategy Base Class, CLI + __main__, 17 Scripts archiviert
**Offen:** Cron-Migration auf `python3 -m trademind`, pytest Tests, strategies/albert.py

---

## Phase 3: Risikomanagement — Portfolio-Level (Woche 2-3)

> *"Einzeltrade-Risiko ist gelöst. Portfolio-Risiko ist das echte Risiko."*

### 3.1 Korrelationsmatrix vor jedem Trade

**Vor jedem neuen Trade:**
1. Berechne 30-Tage Rolling Korrelation mit ALLEN offenen Positionen
2. Wenn Korrelation > 0.7 mit bestehender Position → **Trade abgelehnt** (oder Size halbiert)
3. Log den Grund

**Beispiel heute:** OXY + FRO = beide Öl/Tanker ≈ 0.70-0.80 Korrelation.
→ Das System hätte gewarnt: "FRO ist effektiv eine Verdopplung der OXY-Position."
→ Entweder FRO ablehnen oder OXY+FRO gemeinsam nur 1× Position Size.

**Daten:** yfinance (kostenlos, 30-Tage History reicht)

```python
def check_correlation(new_ticker: str, open_positions: list[str]) -> CorrelationResult:
    """
    Returns:
        approved: bool
        reason: str
        correlated_with: list[tuple[str, float]]  # [(ticker, corr), ...]
        suggested_action: 'full_size' | 'half_size' | 'reject'
    """
```

### 3.2 Portfolio-Exposure-Limits

| Dimension | Limit | Warum |
|---|---|---|
| Sektor | Max 40% in einem Sektor | Nicht alles in Öl |
| Region | Max 60% in einer Region | Nicht alles in USA |
| Theme | Max 50% in einem geo Theme | Nicht alles auf Iran-These |
| Korrelation | Max 0.7 Paar-Korrelation | Echte Diversifikation |
| Gesamt-Beta | Max 1.5 | Nicht zu viel Markt-Risiko |

### 3.3 Circuit Breaker

```python
CIRCUIT_BREAKERS = {
    'daily_loss_limit': -500,      # Max €500 Verlust/Tag → alle Trades pausiert
    'weekly_loss_limit': -1500,    # Max €1.500/Woche → nur noch Monitoring
    'max_drawdown': -3000,         # Max €3.000 Drawdown vom Peak → ALLES schließen
    'consecutive_losses': 5,        # 5 Verlierer am Stück → 24h Pause
    'vix_panic': 45,               # VIX > 45 → NUR schließen, keine neuen Trades
}
```

**Aktuell haben wir das nicht.** Wenn morgen 8 Trades gleichzeitig den Stop reißen, gibt's kein Sicherheitsnetz.

### 3.4 Stress-Tests (Szenarien)

```
Szenario 1: "VIX Spike auf 50" (2020-er Crash)
  → Was passiert mit unserem Portfolio?
  → Erwarteter Verlust: X€

Szenario 2: "Öl -20% über Nacht" (2020 Saudi-Russland Preiskrieg)  
  → OXY + FRO + EQNR alle gleichzeitig betroffen
  → Erwarteter Verlust: X€

Szenario 3: "Tech-Crash -15%" (2022 Style)
  → NVDA + MSFT + PLTR gleichzeitig
  → Erwarteter Verlust: X€

Szenario 4: "Black Swan — alles -10%"
  → Gesamtportfolio
  → Erwarteter Verlust: X€
```

**Berechnung:** Historische Worst-Case-Moves × aktuelle Position Sizes = erwarteter Loss.
**Keine bezahlte API nötig** — yfinance hat 2+ Jahre Daten, das reicht für Crash-Szenarien.

### Phase 3 Deliverables
- [ ] Korrelationscheck vor jedem Trade (automatisch, blockiert wenn >0.7)
- [ ] Portfolio-Exposure-Limits enforced
- [ ] Circuit Breaker aktiv (testet bei jedem Cron-Run)
- [ ] 4 Stress-Test-Szenarien berechnet und dokumentiert
- [ ] Wöchentlicher Risk-Report (Cron)

**Gesamtaufwand Phase 3:** 2 Tage
**Validierung:** Korrelationscheck hätte OXY+FRO flagged

---

## Phase 4: Statistische Validierung (Woche 3)

> *"Hoffnung ist keine Strategie. p-values sind es."*

### 4.1 Professionelle Metriken für JEDE Strategie

| Metrik | Was sie sagt | Berechnung |
|---|---|---|
| **Sharpe Ratio** | Rendite pro Risiko-Einheit | `(mean_return - risk_free) / std_return` |
| **Sortino Ratio** | Wie Sharpe, aber nur Downside-Risiko | `(mean_return - risk_free) / downside_std` |
| **Max Drawdown** | Größter Peak-to-Trough Verlust | `min(running_max - current_value)` |
| **Max DD Duration** | Wie LANGE im Drawdown | Tage vom Peak bis Recovery |
| **Calmar Ratio** | Rendite / Max Drawdown | `annual_return / max_drawdown` |
| **Profit Factor** | Gewinn / Verlust (brutto) | `sum(winners) / abs(sum(losers))` |
| **Expected Value** | Durchschnittl. Gewinn pro Trade | `(WR × avg_win) - ((1-WR) × avg_loss)` |
| **Win/Loss Ratio** | Wie groß Gewinner vs. Verlierer | `avg_win / avg_loss` |

### 4.2 Signifikanz-Tests

**Die zentrale Frage:** *"Ist diese Strategie besser als Zufall?"*

```python
from scipy import stats

def is_strategy_significant(trades: list[Trade], confidence: float = 0.95) -> dict:
    """
    Binomial Test: Ist die Win Rate signifikant besser als 50%?
    t-Test: Ist der Mean Return signifikant > 0?
    Bootstrap: 10.000 Resamplings → Confidence Interval
    """
    returns = [t.pnl_pct for t in trades]
    
    # 1. Binomial Test (Win Rate)
    wins = sum(1 for r in returns if r > 0)
    binom_p = stats.binom_test(wins, len(returns), 0.5)
    
    # 2. t-Test (Mean Return)
    t_stat, t_p = stats.ttest_1samp(returns, 0)
    
    # 3. Bootstrap Confidence Interval
    bootstrap_means = []
    for _ in range(10000):
        sample = np.random.choice(returns, size=len(returns), replace=True)
        bootstrap_means.append(np.mean(sample))
    ci_lower = np.percentile(bootstrap_means, 2.5)
    ci_upper = np.percentile(bootstrap_means, 97.5)
    
    return {
        'significant': binom_p < (1 - confidence) and t_p < (1 - confidence),
        'binom_p': binom_p,
        't_test_p': t_p,
        'ci_95': (ci_lower, ci_upper),
        'verdict': 'EDGE BESTÄTIGT' if ... else 'KEIN EDGE (Zufall)'
    }
```

**Was wir JETZT SCHON wissen (geschätzt):**
- DT4: 102 Trades, 43% WR → p-value ≈ 0.10 → **NICHT signifikant** (Zufall!)
- DT3: 9 Trades, 11% WR → p-value ≈ 0.002 → **Signifikant SCHLECHTER als Zufall** → ABSCHALTEN
- SA: 2 Trades → viel zu wenig Daten → keine Aussage möglich (braucht min. 30)

### 4.3 Walk-Forward Backtesting

**Problem mit normalem Backtesting:** Man optimiert auf dieselben Daten die man testet = Overfitting.

**Walk-Forward:**
1. Trainiere auf Daten Jan-Jun → Teste auf Jul-Aug (Out-of-Sample)
2. Trainiere auf Feb-Jul → Teste auf Aug-Sep
3. usw.
4. Aggregiere die Out-of-Sample Ergebnisse → DAS ist die echte Performance

**Daten:** yfinance hat 2+ Jahre History. Wir brauchen keine bezahlte API.

```
[=====TRAIN=====][==TEST==]
     [=====TRAIN=====][==TEST==]
          [=====TRAIN=====][==TEST==]
               [=====TRAIN=====][==TEST==]
```

### 4.4 Monte Carlo Simulation

*"Was KÖNNTE in Zukunft passieren basierend auf unseren bisherigen Ergebnissen?"*

```python
def monte_carlo(trades: list[Trade], num_simulations: int = 10000, 
                num_trades: int = 100) -> dict:
    """
    Ziehe zufällig aus unseren historischen Trade-Ergebnissen.
    Simuliere 10.000 Szenarien mit je 100 Trades.
    → Verteilung der möglichen Ergebnisse.
    """
    results = []
    returns = [t.pnl_eur for t in trades]
    
    for _ in range(num_simulations):
        scenario = np.random.choice(returns, size=num_trades, replace=True)
        equity_curve = np.cumsum(scenario)
        results.append({
            'final_pnl': equity_curve[-1],
            'max_drawdown': min(equity_curve - np.maximum.accumulate(equity_curve)),
            'peak': max(equity_curve),
        })
    
    return {
        'median_pnl': np.median([r['final_pnl'] for r in results]),
        'worst_5pct': np.percentile([r['final_pnl'] for r in results], 5),
        'best_5pct': np.percentile([r['final_pnl'] for r in results], 95),
        'prob_profitable': sum(1 for r in results if r['final_pnl'] > 0) / len(results),
        'median_max_dd': np.median([r['max_drawdown'] for r in results]),
    }
```

→ Output: "Nach 100 Trades mit SA-Strategie: 72% Wahrscheinlichkeit profitabel, Median +2.400€, Worst Case 5%: -3.100€"

### Phase 4 Deliverables
- [ ] Professionelle Metriken für ALLE Strategien (Sharpe, Sortino, Max DD, etc.)
- [ ] p-values für jede Strategie → Strategien mit p > 0.10 werden ABGESCHALTET
- [ ] Walk-Forward Backtester (2 Jahre yfinance Daten)
- [ ] Monte Carlo Simulator (10.000 Szenarien)
- [ ] Automatischer "Strategy Health Report" (wöchentlicher Cron)

**Gesamtaufwand Phase 4:** 2-3 Tage
**Dependencies:** scipy, numpy (pip install)
**Validierung:** DT3 + DT4 werden als "kein Edge" identifiziert

---

## Phase 5: Realistische Execution (Woche 4)

> *"Paper Trading ohne Slippage ist ein Märchen."*

### 5.1 Execution Simulator

**Aktuell:** Paper Trade wird zum exakten Yahoo-Preis eröffnet. Unrealistisch.

**Realistisches Modell:**

```python
def simulate_fill(price: float, side: str, volatility: float, 
                  time_of_day: str) -> float:
    """
    Simuliere realistischen Fill-Preis.
    
    Komponenten:
    1. Spread: 0.05-0.20% (abhängig von Liquidität)
    2. Slippage: 0-0.10% (abhängig von Volatilität + Tageszeit)
    3. Market Impact: 0% bei unserer Größe (< €15k pro Trade)
    4. Gap Risk: Modelliert für Overnight-Holds
    """
    
    # Spread (bid-ask)
    spread_pct = {
        'large_cap': 0.05,    # NVDA, MSFT
        'mid_cap': 0.10,      # OXY, FRO
        'small_cap': 0.20,    # AG, EXK
        'intl': 0.15,         # EQNR, RIO.L
    }
    
    # Slippage (marktabhängig)
    slippage = volatility * 0.01  # 1% des ATR
    
    # Gap Risk (Overnight)
    # Modell: 2% der Nächte gibt es >1% Gap
    
    if side == 'BUY':
        return price * (1 + spread_pct[cap] + slippage)
    else:
        return price * (1 - spread_pct[cap] - slippage)
```

### 5.2 Trade Republic Gebühren einrechnen

```python
COSTS_PER_TRADE = {
    'commission': 1.0,           # €1 pro Order
    'spread_estimate': 0.10,     # ~0.10% geschätzter Spread
    'fx_fee': 0.0,               # TR rechnet in EUR um (im Spread enthalten)
}

# Round Trip: Entry + Exit = €2 + 2× Spread
# Bei €5.000 Position: €2 + ~€10 Spread = €12 Round Trip = 0.24%
# → Trade muss >0.24% machen um Break-Even zu sein!
```

### 5.3 Gap-Modell für Overnight

**Problem:** Wir halten Positionen über Nacht. TR kann nachts nicht handeln.
**Risiko:** Overnight Gap kann Stop ÜBERSPRINGEN.

```python
def model_overnight_gap(ticker: str, holding_overnight: bool) -> dict:
    """
    Basierend auf historischen Daten:
    - Wie oft gapped dieser Ticker >1%?
    - Wie oft >3%?
    - Was ist der worst-case Gap der letzten 2 Jahre?
    """
    history = yf.download(ticker, period='2y')
    gaps = (history['Open'] - history['Close'].shift(1)) / history['Close'].shift(1) * 100
    
    return {
        'avg_gap': gaps.abs().mean(),
        'gap_gt_1pct': (gaps.abs() > 1).mean() * 100,  # % der Tage
        'gap_gt_3pct': (gaps.abs() > 3).mean() * 100,
        'worst_gap': gaps.min(),
        'risk_eur': worst_gap * position_size / 100,
    }
```

→ "OXY: 8% der Nächte Gap >1%, Worst Case -6.2%. Bei €15k Position = €930 Overnight-Risiko."

### Phase 5 Deliverables
- [ ] Slippage-Modell in Paper Trading Engine integriert
- [ ] TR-Gebühren automatisch abgezogen (€1 + Spread)
- [ ] Overnight Gap-Risiko berechnet und geloggt
- [ ] P&L-Zahlen werden realistischer (pessimistischer)

**Gesamtaufwand Phase 5:** 1-2 Tage
**Validierung:** P&L aller neuen Trades ~0.2-0.5% niedriger als vorher (realistisch!)

---

## Phase 6: Backtester auf professionellem Level (Woche 4-5)

> *"Nicht 'funktioniert die Strategie auf den Daten die ich kenne?', sondern 'funktioniert sie auf Daten die sie noch nie gesehen hat?'"*

### 6.1 Historische Daten aufbauen (kostenlos)

```python
import yfinance as yf

# 2 Jahre Tages-Daten für alle Ticker (KOSTENLOS, unbegrenzt)
tickers = ['OXY', 'FRO', 'EQNR.OL', 'AG', 'NVDA', 'MSFT', 'PLTR', ...]
for ticker in tickers:
    data = yf.download(ticker, period='2y', interval='1d')
    # → In prices-Tabelle speichern
    
# VIX History
vix = yf.download('^VIX', period='2y')

# Regime-Daten rekonstruieren aus SPY + MA + ADX
spy = yf.download('SPY', period='2y')
```

**→ 500+ Datenpunkte pro Ticker × 45 Ticker = 22.500 Datenpunkte. KOSTENLOS.**

### 6.2 Walk-Forward Framework

```python
class WalkForwardBacktester:
    """
    train_window: 6 Monate
    test_window: 1 Monat
    step: 1 Monat
    
    Ergebnis: Out-of-Sample Performance über 18 Fenster
    """
    
    def run(self, strategy: Strategy, tickers: list[str]) -> BacktestResult:
        results = []
        for train_start, train_end, test_start, test_end in self.windows():
            # 1. Strategie "lernt" auf Train-Daten
            strategy.calibrate(train_data)
            
            # 2. Strategie handelt auf Test-Daten (hat sie NIE gesehen)
            trades = strategy.simulate(test_data)
            
            # 3. Ergebnis erfassen
            results.append(evaluate(trades))
        
        return aggregate(results)
```

### 6.3 Benchmark-Vergleich

Jede Strategie wird verglichen mit:
1. **Buy & Hold SPY** (S&P 500) → "Schlägt unsere Strategie den Markt?"
2. **Buy & Hold DAX** → Für deutsche Trader
3. **Random Entry** (gleiche Position-Sizing, zufällige Entry/Exit) → "Ist unser Timing besser als Zufall?"
4. **Buy & Hold gleiche Ticker** → "Ist aktives Management besser als einfach kaufen und halten?"

### Phase 6 Deliverables
- [ ] 2 Jahre Tages-Daten für alle 45 Ticker + VIX + SPY + DAX
- [ ] Walk-Forward Backtester mit 6M Train / 1M Test Fenster
- [ ] Alle Strategien gegen 4 Benchmarks getestet
- [ ] Out-of-Sample Results dokumentiert
- [ ] Strategien die out-of-sample nicht funktionieren → MARKIERT

**Gesamtaufwand Phase 6:** 3-4 Tage
**Validierung:** "SA Out-of-Sample Sharpe: X.XX vs SPY Buy&Hold: Y.YY"

---

## Phase 7: Dashboard & Reporting (Woche 5-6)

> *"Daten die man nicht sieht, existieren nicht."*

### 7.1 Unified Dashboard

**Ein Dashboard statt 3:**
- Portfolio-Übersicht (alle Strategien, alle Positionen)
- Risk Dashboard (Korrelationsmatrix, Exposure, Circuit Breaker Status)
- Performance Dashboard (Sharpe, Sortino, Equity Curve, Benchmark-Vergleich)
- Strategy Health (p-values, Win Rate Trend, Edge-Indikator)
- Learning Dashboard (Lektionen, Top/Flop Setups, These-Trefferquote)

**Tech:** HTML + Chart.js (wie geo-dashboard, bewährt). Kein Framework nötig.

### 7.2 Automatische Reports (Cron)

| Report | Frequenz | Inhalt |
|---|---|---|
| **Morning Scan** | Mo-Fr 08:00 | Offene Positionen, Stops, Regime, Scanner |
| **SA Autonomous** | Mo-Fr 4x | Monitor, Close, Open (schon gebaut) |
| **Daily P&L** | Mo-Fr 22:00 | Tages-P&L, Win/Loss, Equity Curve Update |
| **Weekly Analytics** | Sa 11:00 | Sharpe, Max DD, Strategy Health, Learning Insights |
| **Monthly Review** | 1. So/Monat | Voller Report + Monte Carlo + Benchmark + Signifikanz |

### Phase 7 Deliverables
- [ ] Unified Dashboard (HTML, 5 Tabs)
- [ ] Equity Curve Chart (Chart.js)
- [ ] Risk Matrix Visualisierung
- [ ] Automatische Report-Pipeline

**Gesamtaufwand Phase 7:** 2-3 Tage

---

## Gesamtübersicht

| Phase | Was | Wann | Aufwand | Impact |
|---|---|---|---|---|
| **1** | Datenqualität fixen | Woche 1 | 1 Tag | 🔴 KRITISCH |
| **2** | Code konsolidieren | Woche 1-2 | 3-4 Tage | 🟠 HOCH |
| **3** | Portfolio-Risikomanagement | Woche 2-3 | 2 Tage | 🟠 HOCH |
| **4** | Statistische Validierung | Woche 3 | 2-3 Tage | 🔴 KRITISCH |
| **5** | Realistische Execution | Woche 4 | 1-2 Tage | 🟡 MITTEL |
| **6** | Professioneller Backtester | Woche 4-5 | 3-4 Tage | 🟠 HOCH |
| **7** | Dashboard & Reporting | Woche 5-6 | 2-3 Tage | 🟡 MITTEL |
| **GESAMT** | | **6 Wochen** | **~15-19 Tage** | **5/10 → 8/10** |

### Kosten: €0

| Ressource | Quelle | Preis |
|---|---|---|
| Preis-Daten (2 Jahre Daily) | yfinance | Kostenlos |
| VIX + Indizes | yfinance | Kostenlos |
| Geopolitik | Liveuamap + Google News | Kostenlos |
| Statistik | scipy + numpy | Kostenlos |
| Hosting | Bestehender Docker-Container | Bereits bezahlt |
| KI (Crons) | Haiku | ~$0.50/Tag (bereits budgetiert) |

### Was wir NICHT haben werden (und auch nicht brauchen — erstmal):
- ❌ Level 2 Orderbook-Daten (brauchen wir als Swing-Trader nicht)
- ❌ Tick-Daten / Intraday History (Intraday-Trading haben wir als unprofitabel identifiziert)
- ❌ Broker-API (kommt wenn Paper Trading profitabel ist)
- ❌ Options-Pricing (nicht unser Spielfeld — noch nicht)
- ❌ Echtzeit-Satellitenbilder (Nice-to-have, €50k/Jahr)

### Was wir am Ende haben (Target: 8/10):
- ✅ Saubere Daten (100% VIX, CRV, Regime bei jedem Trade)
- ✅ Ein Python-Package statt 58 Scripts
- ✅ Statistisch validierte Strategien (p-values, Sharpe, Walk-Forward)
- ✅ Portfolio-Level Risikomanagement (Korrelation, Exposure, Circuit Breaker)
- ✅ Realistische Paper-Trading-Ergebnisse (Slippage, Spread, Gaps)
- ✅ Professioneller Backtester (Walk-Forward, Monte Carlo, Benchmark)
- ✅ Unified Dashboard mit Equity Curve + Risk Matrix
- ✅ Geschlossene Feedback-Loop die NACHWEISLICH lernt

---

*"Ein schlechter Plan der umgesetzt wird schlägt einen perfekten Plan der in der Schublade liegt."*
*— Albert 🎩*

*Aber dieser Plan ist nicht schlecht. Und wir setzen ihn um.*
