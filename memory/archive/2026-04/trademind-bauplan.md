# TradeMind — Bauplan: Bestand → Masterplan
**Erstellt:** 2026-03-19 | **Repo:** Vic3d/Trade-Bot (master)
**Prinzip:** Kein Neubau — bestehenden Code refactoren, erweitern, verbinden.

---

## INVENTAR — Was wir haben

### Datenbank: trading.db (SQLite, 2.8 MB)
| Tabelle | Rows | Qualität | Masterplan-Zuordnung |
|---|---|---|---|
| `prices` | 22.124 | ✅ 2 Jahre, 44 Ticker | → 1.1 Price Engine (Basis da!) |
| `ticker_meta` | 45 | ✅ Ticker/Name/Sektor/Strategie | → 1.1.4 Ticker-Registry |
| `trades` | 22 | ⚠️ Conviction/Regime oft NULL | → 1.4 Trade Journal |
| `paper_portfolio` | 14 | ⚠️ Stops auf Breakeven, pnl=NULL | → 3.2 Paper Trading |
| `paper_fund` | 3 | ✅ cash/start/total | → 3.2 Paper Trading |

### Scripts: 46 Python-Dateien (~500 KB Code)
**KERN (aktiv, funktioniert):**
| Script | KB | Masterplan-Modul | Status |
|---|---|---|---|
| `trading_monitor.py` | 57 | 1.1 + 2.2 + 2.3 | ✅ Kern — v2.2, läuft 15-minutig |
| `signal_tracker.py` | 13 | 1.5 Signal DB | ✅ Neu, Paperclip-basiert |
| `learning_system.py` | 28 | 2.4 Strategy DNA | ⚠️ Läuft, aber kaum Daten |
| `news_fetcher.py` | 11 | 1.2 News Pipeline | ✅ Bloomberg+Finnhub+Google |
| `newswire_analyst.py` | 10 | 1.2.4 Sentiment | ⚠️ Keyword-Match, kein echtes NLP |
| `portfolio_summary.py` | 6 | 1.1 Price Engine | ✅ Cron-Context für alle Jobs |
| `strategy_monitor.py` | 17 | 2.1 Regime + 2.4 DNA | ⚠️ Liest strategies.json, checkt Health |
| `trade_journal.py` | 16 | 1.4 Trade Journal | ⚠️ Existiert, aber Entries unvollständig |
| `auto_trader.py` | 33 | 3.2 Paper Trading | ⚠️ Groß, aber nie sauber validiert |
| `paper_trading.py` | 22 | 3.2 Paper Trading | ⚠️ Duplikation mit auto_trader |
| `evening_report.py` | 5 | 1.4 + Reporting | ✅ Täglich via Cron |
| `backtester.py` | 12 | 2.5 Backtesting | ⚠️ Basis da, Walk-Forward fehlt |
| `correlation_matrix.py` | 7 | 3.3 Risk Management | ✅ Freitags-Cron |
| `portfolio_risk.py` | 11 | 3.3 Risk Management | ✅ Freitags-Cron |
| `price_db.py` | 11 | 1.1.2 Historische Kurse | ✅ Füllt prices-Tabelle |
| `regime_detector.py` | 8 | 2.1 Regime Detector | ⚠️ Existiert! Braucht Feinschliff |
| `sentiment_scorer.py` | 10 | 1.2.4 Sentiment | ⚠️ Existiert, braucht FinBERT |
| `position_sizer.py` | 7 | 3.3.3 Risk Management | ⚠️ Existiert, nicht integriert |
| `unified_scorer.py` | 18 | 2.3 Conviction Scorer | ⚠️ Existiert, 7 Faktoren angelegt |
| `sector_rotation.py` | 5 | 2.1 Regime | ⚠️ Existiert, Basisform |

**VERALTET / DUPLIKATE (Kandidaten für Archive):**
| Script | Grund |
|---|---|
| `stop_loss_monitor.py` | Ersetzt durch trading_monitor.py |
| `morning_briefing.py` | Cron macht das direkt |
| `morning_analysis.py` | Duplikat |
| `newswire.py` | Alte Version von newswire_analyst.py |
| `newswire_poll.py` | Alte Version |
| `newswire_price_tracker.py` | In trading_monitor integriert |
| `newswire_learner.py` | In learning_system integriert |
| `stock_keywords.py` | Nie produktiv genutzt |
| `stock_screener.py` | Nie produktiv genutzt |
| `correlation_tracker.py` | Duplikat von correlation_calculator |
| `trade_logger.py` | Duplikat von trade_journal |
| `strategy_updater.py` | Manuell, nie automatisiert |

### Data Files (data/)
| Datei | Status | Zuordnung |
|---|---|---|
| `strategies.json` | ✅ 12 Strategien (S1-S7 + PS1-PS5) | 2.4 Strategy DNA |
| `backtest_results.json` | ⚠️ Einmalig, nicht aktuell | 2.5 Backtesting |
| `correlations.json` | ✅ Aktuell | 3.3 Risk |
| `current_regime.json` | ⚠️ Regime-Label da, aber statisch | 2.1 Regime |
| `sentiment.json` | ⚠️ 18 KB, Keyword-basiert | 1.2.4 Sentiment |
| `lag_knowledge.json` | ✅ Neu, 5 Lead-Lag-Paare | 1.5 Signal DB |
| `news_cache.json` | ✅ Rolling Cache | 1.2 News |
| `screener_results.json` | ⚠️ Einmalig | 2.2 Signal Engine |

### Vercel Dashboard (Trade-Bot Repo)
| Endpoint | Status | Zuordnung |
|---|---|---|
| `/api/dashboard` | ✅ 6 Tabs, live | 4.1 Dashboard |
| `/api/prices` | ✅ 17 Ticker live | 1.1 Price Engine |
| `/api/config` | ✅ GET/POST trading_config | Config-Management |
| `/api/trade` | ✅ POST Trade-Log | 1.4 Trade Journal |
| `/api/manifest` | ✅ PWA | 4.1 Dashboard |

### Paperclip (lokal, Port 53476)
| Entity | Status |
|---|---|
| Company: TradeMind | ✅ |
| Agent: Albert (engineer) | ✅ |
| Agent: Validator (qa) | ✅ |
| Project: Signal Tracking | ✅ |
| Issue TRA-1: Bot-Analyse | ✅ done |
| Issue TRA-2: Nikkei→Copper Signal | ✅ aktiv |

---

## BAUPLAN — 6 Sprints

### Architektur-Entscheidung

```
KEINE neue App bauen.
Bestehenden Code REFACTOREN + VERBINDEN.

Repo:           Vic3d/Trade-Bot (master)
Backend:        Python Scripts + SQLite (trading.db)
Dashboard:      Vercel Serverless (api/*.js)
Orchestration:  Paperclip (Issues) + OpenClaw (Crons)
```

---

## SPRINT 1 — Fundament reparieren (Woche 1-2)

### S1.1 — DB Schema erweitern
**Datei:** `scripts/db_migrate.py` (NEU)

```sql
-- trades Tabelle erweitern (fehlende Spalten)
ALTER TABLE trades ADD COLUMN position_size_eur REAL;
ALTER TABLE trades ADD COLUMN risk_eur REAL;
ALTER TABLE trades ADD COLUMN reward_eur REAL;
ALTER TABLE trades ADD COLUMN crv REAL;
ALTER TABLE trades ADD COLUMN vix_at_entry REAL;
ALTER TABLE trades ADD COLUMN exit_type TEXT;  -- STOP_HIT, TARGET, MANUAL, TRAILING
ALTER TABLE trades ADD COLUMN signal_issue_id TEXT;  -- Paperclip Issue verknüpfung
ALTER TABLE trades ADD COLUMN holding_days INTEGER;
ALTER TABLE trades ADD COLUMN fees_eur REAL DEFAULT 1.0;

-- Macro-Tabelle (NEU)
CREATE TABLE IF NOT EXISTS macro_daily (
  date TEXT NOT NULL,
  indicator TEXT NOT NULL,
  value REAL,
  prev_value REAL,
  change_pct REAL,
  PRIMARY KEY (date, indicator)
);

-- Regime-Tabelle (NEU)
CREATE TABLE IF NOT EXISTS regime_history (
  date TEXT PRIMARY KEY,
  regime TEXT NOT NULL,
  vix REAL,
  dxy REAL,
  us10y REAL,
  us2y REAL,
  wti REAL,
  gold REAL
);

-- News Events (NEU — ersetzt news_cache.json)
CREATE TABLE IF NOT EXISTS news_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url_hash TEXT UNIQUE,
  headline TEXT NOT NULL,
  source TEXT,
  published_at TEXT,
  tickers TEXT,  -- JSON array ["NVDA", "MSFT"]
  sentiment_score REAL,
  sentiment_label TEXT,
  event_cluster_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Signal Log (NEU — SQLite-Backup von Paperclip Issues)
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pair_id TEXT NOT NULL,
  lead_ticker TEXT,
  lag_ticker TEXT,
  signal_value TEXT,
  lag_price_at_signal REAL,
  lag_price_at_check REAL,
  outcome TEXT,  -- WIN, LOSS, PENDING
  accuracy_at_time REAL,
  paperclip_issue_id TEXT,
  created_at TEXT,
  checked_at TEXT
);
```

**Aufwand:** 2h
**Abhängigkeiten:** Keine
**Commit:** `db: Schema v2 — macro, regime, news_events, signals Tabellen`

### S1.2 — Trade Journal Auto-Enrichment
**Datei:** `scripts/trade_journal.py` (REFACTOR)

Wenn Trade geloggt wird, automatisch:
1. VIX zum Zeitpunkt holen → `vix_at_entry`
2. Regime-Label aus `regime_history` → `regime_at_entry`
3. Conviction Score berechnen → `conviction_at_entry`
4. Position Size nach 2%-Regel → `position_size_eur`, `risk_eur`
5. CRV berechnen → `crv`
6. Letzte 5 News-Events für Ticker verknüpfen

Bei Exit:
1. P&L berechnen (inkl. 1€ TR-Gebühr)
2. Holding-Days berechnen
3. Exit-Type bestimmen (STOP_HIT/TARGET/MANUAL)
4. Regime bei Exit loggen

**Aufwand:** 4h
**Abhängigkeiten:** S1.1 (DB Schema)
**Refactored von:** trade_journal.py (16 KB, Basis existiert)

### S1.3 — News Deduplikation
**Datei:** `scripts/news_fetcher.py` (ERWEITERN)

```python
def is_duplicate(headline, existing_headlines, threshold=0.80):
    """difflib.SequenceMatcher Deduplikation"""
    for h in existing_headlines:
        if SequenceMatcher(None, headline.lower(), h.lower()).ratio() > threshold:
            return True
    return False
```

+ URL-Hash beim Insert in `news_events` Tabelle
+ Ticker-Tagging mit Alias-Map (Nvidia→NVDA, Equinor→EQNR.OL)

**Aufwand:** 2h
**Abhängigkeiten:** S1.1
**Refactored von:** news_fetcher.py + newswire_analyst.py

### S1.4 — Macro Store befüllen
**Datei:** `scripts/macro_store.py` (NEU)

1. FRED API (kostenlos): VIX, DXY, US10Y, US2Y, Gold — 5 Jahre Backfill
2. Yahoo Finance: WTI, Brent, Nikkei, Kupfer — 5 Jahre Backfill
3. Täglicher Cron 22:30: neue Tageswerte appenden
4. `macro_daily` Tabelle befüllen

**Aufwand:** 3h
**Abhängigkeiten:** S1.1

### S1.5 — Aufräumen: Scripts archivieren
**Aktion:** `scripts/archive/` — 12 veraltete Scripts verschieben
**Aufwand:** 30 Min
**Commit:** `cleanup: 12 veraltete Scripts nach archive/ verschoben`

---

## SPRINT 2 — Intelligence aufbauen (Woche 3-4)

### S2.1 — Regime Detector v2
**Datei:** `scripts/regime_detector.py` (REFACTOR)

Existiert bereits (8 KB)! Erweitern um:
1. 6 Regime-Typen statt aktuellem binären Risk-On/Off
2. Regime-Velocity: wie schnell ändert sich das Regime?
3. Output in `regime_history` Tabelle + `data/current_regime.json`
4. Alert bei Regime-Wechsel → Discord

Input: `macro_daily` Tabelle (aus S1.4)
Output: Regime-Label für heute + historisch

**Aufwand:** 4h
**Abhängigkeiten:** S1.4 (Macro Store)
**Refactored von:** regime_detector.py (7.7 KB Basis da)

### S2.2 — Conviction Scorer v2
**Datei:** `scripts/unified_scorer.py` (REFACTOR)

Existiert bereits (18 KB, 7 Faktoren angelegt)! Erweitern um:
1. Regime-Alignment als Faktor (aus S2.1)
2. News-Momentum aus `news_events` Tabelle (aus S1.3)
3. Signal Confluence (aus signal_tracker.py)
4. Self-Calibration: nach 50 Trades Faktoren re-gewichten
5. Output: Score 0-100 pro Ticker, gespeichert in DB

**Aufwand:** 4h
**Abhängigkeiten:** S2.1 (Regime), S1.3 (News)
**Refactored von:** unified_scorer.py (17.7 KB, Grundstruktur da)

### S2.3 — Signal Engine erweitern
**Datei:** `scripts/signal_tracker.py` (ERWEITERN)

1. INPEX-Ticker fixen (1605.T statt INPEX.T)
2. Technical Pattern Scanner integrieren (aus trading_monitor.py Candlestick-Code)
3. Volume Anomaly Detection: >2× 20-Tage-SMA Volume
4. Signal Fusion: Confluence Score wenn 3+ Signale für gleichen Ticker
5. Alle Signale → `signals` Tabelle + Paperclip Issue

**Aufwand:** 6h
**Abhängigkeiten:** S1.1 (DB)
**Refactored von:** signal_tracker.py + trading_monitor.py (Candlestick-Code)

### S2.4 — Historische Preise Backfill
**Datei:** `scripts/price_db.py` (ERWEITERN)

Existiert (11 KB, füllt `prices` Tabelle)! Erweitern:
1. Backfill auf 5 Jahre (aktuell 2 Jahre, 22K Rows → ~55K)
2. Adjusted Close korrekt berechnen (Splits/Dividenden)
3. Intraday-Kerzen für aktive Positionen (5min, rolling 5 Tage)
4. Quality Monitor: Alert wenn Ticker >24h keinen neuen Preis hat

**Aufwand:** 3h
**Abhängigkeiten:** Keine

---

## SPRINT 3 — Backtesting + DNA (Woche 5-6)

### S3.1 — Backtesting Engine v2
**Datei:** `scripts/backtester.py` (REFACTOR)

Existiert (12 KB)! Erweitern:
1. Walk-Forward statt nur In-Sample
2. Slippage (0.1%) + Gebühren (1€) + Spread (0.05%)
3. Regime-Filter: "Teste S1 nur in BULL_CALM"
4. Output: Sharpe, Max Drawdown, Profit Factor, Win Rate
5. Ergebnisse in `data/backtest_results.json` (aktualisiert)

**Aufwand:** 8h
**Abhängigkeiten:** S2.4 (5 Jahre Preisdaten), S2.1 (Regime)
**Refactored von:** backtester.py + run_backtests.py (21 KB zusammen)

### S3.2 — Strategy DNA Engine
**Datei:** `scripts/learning_system.py` (REFACTOR)

Existiert (28 KB)! Erweitern:
1. Per-Strategy Metrics: Win Rate, Expectancy, Max Consecutive Losses
2. Per-Regime Metrics: "S1 in BULL_CALM: 68%, in CORRECTION: 34%"
3. Trader-Profil: Timing-Analyse, Revenge-Trading Detection
4. Strategy Kill-Trigger: WR <35% über 10 Trades → Alert
5. Strategy Evolution Tracking: v1 → v2 Vergleich

**Aufwand:** 6h
**Abhängigkeiten:** S1.2 (Journal), S2.1 (Regime)
**Refactored von:** learning_system.py (28 KB, größtes Script)

### S3.3 — Self-Calibration Loop
**Datei:** `scripts/calibration.py` (NEU)

1. Conviction Score Buckets auswerten (0-30, 30-50, 50-70, 70-85, 85-100)
2. Tatsächliche Win Rate pro Bucket messen
3. Wenn Bucket-WR stark abweicht → Faktor-Gewichte anpassen
4. Lead-Lag Accuracy pro Regime auswerten
5. Wöchentlicher Cron (Samstag 10:00)

**Aufwand:** 4h
**Abhängigkeiten:** S2.2 (Conviction), S3.2 (DNA)

---

## SPRINT 4 — Execution perfektionieren (Woche 7-8)

### S4.1 — Trade Proposal System
**Datei:** `scripts/trade_proposal.py` (NEU)

Format wie im Masterplan:
```
📊 TRADE PROPOSAL — TRA-47
Ticker: EQNR.OL | LONG | Entry 28.40€ | Stop 27€ | CRV 2.6:1
Conviction: 82/100 | Regime: BULL_VOLATILE
Signale: Lead-Lag ✅ | News ✅ | Technical ✅ | Volume ⚠️
Risk: 280€ (2%) | Max Loss: 39€
→ APPROVE / REJECT
```

1. Signal Engine detektiert Setup → Proposal generieren
2. Conviction, Regime, CRV, Position Size automatisch
3. An Victor via Discord senden
4. Victor reagiert → Trade loggen oder Reject loggen

**Aufwand:** 4h
**Abhängigkeiten:** S2.2, S2.3

### S4.2 — Paper Trading v2
**Datei:** `scripts/auto_trader.py` (REFACTOR)

Existiert (33 KB)! Aufräumen:
1. Duplikation mit paper_trading.py eliminieren (1 File)
2. Conviction-Check vor jedem Paper-Trade
3. Regime-Filter: kein Entry in CRISIS/BEAR
4. Automatisches Stop-Management (Trailing nach +5%)
5. Performance vs. Benchmark tracken

**Aufwand:** 6h
**Abhängigkeiten:** S2.2, S3.2
**Refactored von:** auto_trader.py (33 KB) + paper_trading.py (22 KB)

### S4.3 — Risk Management Modul
**Datei:** `scripts/risk_manager.py` (NEU, aus bestehenden Scripts)

Zusammenführung von:
- `portfolio_risk.py` (11 KB) — Sektor-Exposure
- `correlation_matrix.py` (7 KB) — Korrelationen
- `position_sizer.py` (7 KB) — 2%-Regel

Neues:
1. Max 5 offene Positionen Check
2. Max 20% Sektor-Konzentration Check
3. Max Drawdown Monitor (Daily Mark-to-Market)
4. Pre-Trade Risk Gate: wird in trade_proposal.py eingebaut

**Aufwand:** 4h
**Abhängigkeiten:** S1.1 (DB)
**Refactored von:** portfolio_risk.py + correlation_matrix.py + position_sizer.py (25 KB)

---

## SPRINT 5 — Dashboard v2 (Woche 9-10)

### S5.1 — Dashboard Rebuild (React/Next.js)
**Repo:** Vic3d/Trade-Bot (neuer Branch `dashboard-v2`)

Migration von Serverless-HTML zu echtem Frontend:
1. Next.js App mit Vercel
2. Echtzeit via Polling (alle 30s) oder WebSocket (später)
3. Mobile-First Design (PWA bleibt)

Tabs:
- 📈 **Portfolio** — Live Kurse, P&L, Stops, Conviction
- 📡 **Signals** — aktive Signal-Issues aus Paperclip
- 📓 **Journal** — Trade History mit Kontext
- 📊 **Analytics** — Strategy DNA, Win Rates, Regime-Performance
- 🛡️ **Risk** — Exposure, Korrelation, Drawdown
- ⚙️ **Settings** — Alerts, Thresholds, Strategien

### S5.2 — API-Schicht erweitern
Neue Vercel Endpoints:
- `GET /api/signals` — aktive Signale + Outcomes
- `GET /api/regime` — aktuelles Regime + Historie
- `GET /api/analytics` — Strategy DNA Metrics
- `GET /api/risk` — Portfolio Risk Dashboard
- `POST /api/approve` — Trade Proposal genehmigen
- `GET /api/macro` — Macro Dashboard (VIX, Yields, etc.)

### S5.3 — Notification System
- Discord: alle Alerts (wie jetzt, verbessert)
- Browser Push: Stop-Alerts <2% (existiert!)
- Email Digest: wöchentliche Performance Summary
- Prioritäts-Levels: P0 (sofort überall) → P3 (nur Email)

---

## SPRINT 6 — Produkt-Features (Woche 11-12)

### S6.1 — Steuer-Tracking (DE)
- FIFO-Berechnung aus `trades` Tabelle
- 26.375% Abgeltungssteuer + Soli
- After-Tax P&L pro Trade + Gesamt
- Tax-Loss Harvesting Vorschläge
- Jahresreport PDF Export

### S6.2 — Trade Import
- Trade Republic CSV Parser
- → Day 1 Mehrwert: bestehende History sofort in DB

### S6.3 — Onboarding Flow
- 5-Minuten Quiz → Trader-Profil
- Empfohlene Strategien basierend auf Profil
- Geführter erster Trade

---

## DATEISTRUKTUR nach Sprint 6

```
Vic3d/Trade-Bot/
├── api/                          # Vercel Serverless
│   ├── dashboard.js              # Haupt-Dashboard (oder Next.js)
│   ├── prices.js                 # Live Kurse
│   ├── config.js                 # GET/POST Config
│   ├── trade.js                  # Trade loggen
│   ├── signals.js                # Signal-Issues
│   ├── regime.js                 # Regime-Status
│   ├── analytics.js              # Strategy DNA
│   ├── risk.js                   # Risk Dashboard
│   ├── approve.js                # Trade Approval
│   ├── macro.js                  # Macro Dashboard
│   └── manifest.js               # PWA Manifest
│
├── scripts/                      # Python Backend
│   ├── core/                     # Kern-Module (NEU: Ordnerstruktur)
│   │   ├── price_engine.py       # ← price_db.py refactored
│   │   ├── news_pipeline.py      # ← news_fetcher.py + newswire_analyst.py merged
│   │   ├── macro_store.py        # NEU
│   │   ├── trade_journal.py      # ← refactored mit Auto-Enrichment
│   │   └── db_migrate.py         # NEU
│   │
│   ├── intelligence/             # Intelligence Engine
│   │   ├── regime_detector.py    # ← refactored
│   │   ├── signal_engine.py      # ← signal_tracker.py + Patterns
│   │   ├── conviction_scorer.py  # ← unified_scorer.py refactored
│   │   ├── strategy_dna.py       # ← learning_system.py refactored
│   │   ├── backtester.py         # ← refactored
│   │   └── calibration.py        # NEU
│   │
│   ├── execution/                # Execution Layer
│   │   ├── trade_proposal.py     # NEU
│   │   ├── paper_trader.py       # ← auto_trader.py + paper_trading.py merged
│   │   ├── risk_manager.py       # ← portfolio_risk + correlation merged
│   │   └── position_sizer.py     # ← refactored
│   │
│   ├── crons/                    # Cron-Runner (dünne Wrapper)
│   │   ├── trading_monitor.py    # ← Kern bleibt, nutzt core/ Module
│   │   ├── evening_report.py     # ← bleibt
│   │   ├── daily_summary.py      # ← bleibt
│   │   └── email_monitor.py      # ← bleibt (Josh)
│   │
│   └── archive/                  # Veraltete Scripts
│       ├── stop_loss_monitor.py
│       ├── morning_briefing.py
│       └── ... (12 Dateien)
│
├── data/                         # Persistente Daten
│   ├── trading.db                # SQLite (Haupt-DB)
│   ├── trading_config.json       # Positions-Config
│   ├── strategies.json           # Strategie-Definitionen
│   ├── lag_knowledge.json        # Lead-Lag Paare
│   └── current_regime.json       # Aktuelles Regime
│
├── memory/                       # Albert's Gedächtnis
│   ├── trademind-masterplan.md   # Perfektionierte Architektur
│   ├── trademind-bauplan.md      # DIESES DOKUMENT
│   └── ...
│
└── dashboard/                    # Next.js Frontend (Sprint 5)
    ├── pages/
    ├── components/
    └── ...
```

---

## TIMELINE

```
Woche 1-2:   Sprint 1 — Fundament (DB, Journal, News, Macro)
Woche 3-4:   Sprint 2 — Intelligence (Regime, Conviction, Signals)
Woche 5-6:   Sprint 3 — Backtesting + DNA
Woche 7-8:   Sprint 4 — Execution (Proposals, Paper Trading, Risk)
Woche 9-10:  Sprint 5 — Dashboard v2
Woche 11-12: Sprint 6 — Steuer, Import, Onboarding

TOTAL: 12 Wochen → MVP Ready (Advisory Mode, perfektioniert)
Danach: 3 Monate Paper Trading → Autonomous Mode
```

---

## KOSTEN-SCHÄTZUNG (monatlich)

| Service | Preis | Wofür |
|---|---|---|
| Vercel (Free) | 0€ | Dashboard Hosting |
| OpenClaw | ~15€/Monat | Crons + Agents |
| Finnhub (Free) | 0€ | Company News |
| FRED API (Free) | 0€ | Macro Daten |
| Yahoo Finance | 0€ | Preise (inoffiziell) |
| Polygon (Free) | 0€ | US News (5 req/min) |
| **TOTAL Phase 1** | **~15€/Monat** | |
| IBKR (ab Sprint 4) | ~15€/Monat | Market Data |
| **TOTAL Phase 2** | **~30€/Monat** | |

---

*Sprint 1 startet sofort. Jeder Sprint-Abschluss = Git Tag + Bauplan-Update.*
