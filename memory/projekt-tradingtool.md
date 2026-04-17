# TradeMind — Projekt-Dokumentation
**Letzte Änderung:** 2026-04-11  
**Status:** Paper Trading aktiv, autonomer Loop geschlossen, 24/7 auf Hetzner VPS

---

## Das große Ziel

### Ebene 1 — Persönlich (2026)
Victor lernt eigenständig und profitabel zu traden. TradeMind ist sein Lehrmeister:
das System zwingt ihn zur Disziplin (Stops, Conviction, Regime) und zeigt ihm
durch Paper-Trades was funktioniert — ohne echtes Geld zu riskieren während er lernt.

### Ebene 2 — Produkt (2027+)
**"Die beste Retail-Trading-App" — autonomes KI-Trading + Advisory + Strategy DNA**

Zielgruppe: Retail-Trader die nicht täglich Charts analysieren wollen, aber
trotzdem intelligent investieren möchten. Das System:
- entwickelt Strategien basierend auf Geopolitik + Makro
- checkt Nachrichten gegen aktive Thesen
- entscheidet selbstständig Entries/Exits
- erklärt seine Entscheidungen (Advisory-Layer)
- lernt kontinuierlich aus Ergebnissen

Victor baut TradeMind erst für sich, dann für andere.
Der eigene Lernprozess ist die Produktentwicklung.

**Roadmap:**
- 2026 Q1-Q2: Paper Trading, ML-Pipeline aufbauen, Lernphase
- 2026 Q3-Q4: Erste Real-Money-Trades (kleine Positionen), System validieren
- 2027: Produkt für andere Trader, Vermarktung

---

## Infrastruktur

### Hetzner VPS (Produktions-Server)
- **IP:** 178.104.152.135
- **OS:** Ubuntu 24.04, Python 3.12 (System), Python 3.13 (venv)
- **Systemd-Services:** `trademind-scheduler.service`, `trademind-api.service`
- **Watchdog:** Cron alle 5 Min prüft ob Services laufen, startet neu falls nötig
- **Pfad:** `/data/.openclaw/workspace/` (Haupt-Workspace)

### Lokale Entwicklung
- Victor entwickelt auf Windows, synct via Git nach Hetzner
- Git Repo: `github.com/Vic3d/Trade-Bot` (master branch)
- Auto-Backup: täglich 13:00 + 23:00 → GitHub push

### Claude API Modell-Strategie (Kostenoptimiert)
| Komponente | Modell | Warum |
|---|---|---|
| Albert Discord Chat | Claude Sonnet | Muss intelligent kommunizieren |
| CEO AI-Analyse | Claude Sonnet | Entscheidungsqualität kritisch |
| Thesis Discovery | Claude Haiku | Batch-Screening, hohe Tokenzahl |
| Entity Extraction | Claude Haiku | Strukturierte Datenextraktion |

Geschätzte Kosten: ~$2-4/Monat bei normalem Betrieb.

---

## Architektur — Der autonome Loop

```
[1] NEWS SAMMELN (24/7, 8x täglich)
    scripts/core/news_pipeline.py + scripts/overnight_collector.py
    → Bloomberg RSS + Google News + Overnight Events
    → trading.db:news_events + newswire.db:events
    → Abdeckung: Asien (01:00+04:00 UTC), EU (07:00+09:00+13:00), US (14:00+17:00+20:30)

[2] NEWS AUSWERTEN + CEO RADAR
    scripts/news_gate_updater.py → matched News gegen Strategie-Thesen
    scripts/news_ceo_radar.py → IMPACT_RULES Klassifizierung (Sektoren/Strategien)
    → data/news_gate.json: {relevant, theses_hit, hit_count}
    → overnight_collector: IMPACT_RULES für DE, Öl, Defense, Asia, China

[3] CEO DIREKTIVE (Hybrid: Python-Regeln + Claude Sonnet AI)
    scripts/ceo.py --live
    → Liest: VIX, Regime, News Gate, Overnight Events, Strategies, Portfolio
    → Python-Regeln bestimmen Basis-Modus (FULL_RISK_ON → CRISIS_LOCKDOWN)
    → Claude Sonnet AI analysiert Nachrichten, identifiziert Risiken/Chancen
    → AI kann Python-Modus überschreiben wenn Confidence ≥ 0.75
    → Output: data/ceo_directive.json (mode, exposure, sectors, ai_analysis)
    → Läuft Mo-Fr 07:05 UTC

[4] CONVICTION BERECHNEN
    scripts/intelligence/conviction_scorer.py ← HERZSTÜCK
    → 8 Faktoren: Regime, Technical, Volume, News Momentum, Confluence,
      Backtest, Correlation, Sector Rotation
    → news_gate.json fließt in news_momentum-Faktor
    → Output: Score 0-100 + recommendation + vix_block
    → Thresholds: PS_* Thesis-Plays = 35+, Standard = 52+

[5] SCANNER SUCHT SETUPS (80+ Ticker, 3 Sessions)
    scripts/execution/autonomous_scanner.py
    → 80+ Ticker in 3 Tiers (A=konservativ, B=moderat, C=aggressiv)
    → Globale Abdeckung: Japan, China/HK, EU (DE/FR/NL/UK/IT/ES/Nordics/CH), US
    → Tier A: Thesis-Plays, RSI-Bounce, 18%+ unter 52W-High, CRV 2:1+
    → Tier B: Sektor-Rotation, EMA-Cross, Oversold-Bounce
    → Tier C: News-Katalysator, Breakouts
    → WICHTIG: läuft nur wenn Börsen offen (exchange_calendars, ticker-spezifisch)
    → Scanner-Zeiten: 08:00-19:30 UTC (deckt Asien-Nachlauf + EU + US-Eröffnung)
    → ruft execute_paper() auf → paper_trade_engine

[6] TRADE AUSFÜHREN
    scripts/execution/paper_trade_engine.py
    → Guards: VIX Hard Block → Conviction → Duplicate → Sektor-Limit → Cash
    → schreibt in trading.db:paper_portfolio
    → speichert alle Features bei Entry (RSI, Volume, VIX, Regime, MA50...)
    → Victor tradet NUR in EUR (Trade Republic)

[7] POSITIONEN ÜBERWACHEN
    scripts/paper_exit_manager.py
    → prüft Stop-Loss, Trailing Stop, Zielkurs
    → läuft 3x täglich (10:00, 14:00, 18:30) via scheduler_daemon
    → WICHTIG: läuft nur wenn Börsen offen
    → triggert nach Exit sofort: online_model.learn_from_closed_trade()

[8] THESIS MONITORING (30 Min Zyklus, Mo-Fr 09:00-21:00)
    scripts/core/thesis_engine.py --monitor
    → Prüft Kill-Trigger gegen aktuelle News
    → Bei Match: degradiert Thesis-Status (🟢→🟡→🔴)
    → 26 Slots/Tag, lückenlose Überwachung während Handelszeiten

[9] LERNEN
    scripts/online_model.py      → River ML, nach jedem Trade Update
    scripts/alpha_decay.py       → EWMA λ=0.88, Strategie-Edge tracken
    scripts/daily_learning_cycle.py → täglich 22:45, Regeln ableiten
    scripts/backtest_engine.py   → Wochenende, historische Validierung
    scripts/feature_importance.py → wöchentlich, welche Features zählen?
    scripts/strategy_dna.py      → optimale Parameter je Strategie
    scripts/rl_agent.py          → PPO Reinforcement Learning (nächste Ausbaustufe)

[10] AUTONOME THESEN-ENTDECKUNG (2x/Woche, Claude Haiku)
     scripts/intelligence/thesis_discovery.py
     → Analysiert aktuelle Geopolitik + Makro + Sektortrends
     → Entdeckt neue Investment-Thesen automatisch
     → Erstellt theme_candidates.json für manuelle Review
     → Läuft So + Mi 07:00 UTC
```

---

## Globale Marktabdeckung

### Ticker-Universum (80+)
| Region | Beispiel-Ticker | Börse |
|---|---|---|
| **Deutschland** | SIE.DE, BMW.DE, RHM.DE, MUV2.DE, DTE.DE, SAP.DE | Xetra |
| **Frankreich** | MC.PA (LVMH), OR.PA (L'Oreal), SU.PA, BNP.PA, TTE.PA | Euronext Paris |
| **Niederlande** | ASML.AS, INGA.AS, AD.AS | Euronext Amsterdam |
| **UK** | SHEL.L, HSBA.L, AZN.L, ULVR.L, BA.L | LSE |
| **Italien** | ISP.MI, RACE.MI, ENEL.MI | Borsa Italiana |
| **Spanien** | ITX.MC, SAN.MC, IBE.MC | BME |
| **Nordics** | ERIC-B.ST, NOKIA.HE, NOVO-B.CO, NESTE.HE | OMX/Helsinki/Copenhagen |
| **Schweiz** | NESN.SW, NOVN.SW, ABBN.SW | SIX |
| **Japan** | 8306.T (MUFG), 7203.T (Toyota), 8035.T (Tokyo Electron), 6758.T (Sony) | TSE |
| **China/HK** | 9988.HK (Alibaba), 0700.HK (Tencent), 2318.HK, 3690.HK | HKEX |
| **China ADR** | BABA, PDD, JD | NYSE/NASDAQ |
| **Asia ETFs** | EWJ, FXI, KWEB | US-listed |
| **US** | NVDA, MSFT, AAPL, AMZN, GOOGL, LMT, RTX, OXY | NYSE/NASDAQ |
| **Öl/Tanker** | TTE.PA, EQNR.OL, OXY, FRO, DHT | Diverse |
| **Gold/Rohstoffe** | GLD, SLV, MOS | US-listed |

### Overnight Collector — IMPACT_RULES
News werden automatisch Sektoren/Strategien zugeordnet:
- **DE:** DAX, Bundesbank, German economy → S1 watchlist
- **Öl/Energie:** Oil supply/price, crude, OPEC, pipeline → S1 + PS1
- **Defense:** NATO, military, arms → S3/S11
- **Japan:** BOJ, Nikkei, TOPIX → japan watchlist
- **China:** PBOC, yuan, tariff, Alibaba/Tencent → china watchlist
- **Airlines:** Kerosene, jet fuel, aviation fuel → S10/S11 bearish (spezifisch, kein "oil" catch-all!)
- **Semiconductor:** TSMC, chip, semiconductor → S7
- **Nuclear:** uranium, nuclear energy → watchlist

---

## CEO — Das zentrale Gehirn

### Hybrid-Architektur (Python-Regeln + Claude Sonnet AI)

**Python-Regeln (Baseline):**
Deterministische Modi basierend auf VIX, Regime, Sektor-Stress:
| Modus | Bedingung | Wirkung |
|---|---|---|
| FULL_RISK_ON | VIX < 15, BULL_CALM | Volle Exposure, alle Sektoren |
| SELECTIVE | VIX 15-25 | Nur hohe Conviction |
| DEFENSIVE | VIX 25-30 | Nur Thesis-Plays + Hedges |
| CRISIS_LOCKDOWN | VIX > 35 | Nur Hedges, Cash-Quote hoch |

**Claude Sonnet AI (Override-Layer):**
- Liest: overnight_events, newswire events, news_gate.json, strategies.json
- Identifiziert: Risiken, Chancen, Sektor-Outlook
- Kann Python-Modus überschreiben wenn AI Confidence ≥ 0.75
- Fallback: Bei API-Fehler gelten Python-Regeln
- Output wird in `ceo_directive.json` unter `ai_analysis` gespeichert

### CEO Directive (Output)
```json
{
  "mode": "SELECTIVE",
  "max_exposure": 0.7,
  "sector_blocks": ["airlines"],
  "sector_focus": ["defense", "energy"],
  "ai_analysis": {
    "risks": [...],
    "opportunities": [...],
    "sector_outlook": {...},
    "override_mode": null,
    "confidence": 0.62
  }
}
```

---

## Datenbank — trading.db

Hauptdatei: `/data/.openclaw/workspace/data/trading.db`

| Tabelle | Inhalt |
|---------|--------|
| `paper_portfolio` | Alle Paper Trades (offen + geschlossen) mit 36 Spalten inkl. Features |
| `news_events` | Alle News (Bloomberg RSS + Google News, dedupliziert) |
| `prices` | OHLCV-Preisdaten je Ticker und Datum |
| `macro_daily` | VIX, Makro-Indikatoren |
| `regime_history` | HMM-Regime je Tag (NEUTRAL/BULL_CALM/CORRECTION/BEAR/CRISIS) |
| `signals` | Lead-Lag Signale für Confluence-Score |
| `sector_momentum` | Sektor-Rotation Scores |
| `trade_journal` | Detaillierte Trade-Begründungen |

Zweite DB: `/data/.openclaw/workspace/data/newswire.db`
| Tabelle | Inhalt |
|---------|--------|
| `events` | Overnight + CEO Radar Events (entity, impact, sector, strategy) |

---

## Strategie-Thesen (Aktive)

| ID | Name | Kern-These | Ticker-Beispiele |
|----|------|-----------|-----------------|
| PS1 | Oil/Iran | Geopolitische Prämie durch Iran/Hormuz → Öl-Preis hoch | TTE.PA, EQNR.OL, OXY |
| PS2 | Tanker | Hormuz-Stress → Tanker-Rates steigen | FRO, DHT |
| PS3 | Defense US | NATO-Spending + Trump | KTOS, LMT, RTX |
| PS4 | Metals/Gold | Sicherer Hafen, Inflation-Hedge | GLD, SLV |
| PS5 | Agriculture | Dünger/Kali bei Versorgungsengpass | MOS |
| PS11 | Defense EU | EU Aufrüstung, Deutschland 2% BIP | RHM.DE, BA.L, SIE.DE |
| PS14 | Shipping | Container-Shipping Normalisierung | ZIM |
| PS17 | EU Domestic | Inlandsmarkt-Profiteure im Handelskrieg | SIE.DE |
| PS18 | EU Auto | EU-Autobauer Recovery | BMW.DE |
| PS_NVO | Novo Nordisk | GLP-1 Bewertungsabschlag, PE 10x | NOVO-B.CO |
| PS_MUV2 | Munich Re | Versicherung als Stabilitätsanker | MUV2.DE |

---

## Conviction Score — Wie er berechnet wird

```python
Score = (
  news_momentum:    0-100  × 0.10  # news_gate.json These-Treffer
  regime_alignment: 0-100  × 0.20  # Passt Regime zu Strategie?
  technical_setup:  0-100  × 0.20  # CRV, RSI, Trend
  volume_confirm:   0-100  × 0.10  # Volumen-Anomalie
  signal_confluence:0-100  × 0.15  # Mehrere Signale in eine Richtung?
  backtest_perf:    0-100  × 0.10  # Historische Win-Rate
  correlation:      0-100  × 0.05  # Portfolio-Korrelation
  sector_rotation:  0-100  × 0.10  # Sektor im Aufwind?
)
```

Thresholds: `PS_*` Thesis-Plays = 35+ | Standard = 52+  
VIX Blocks: VIX ≥ 35 = nur Hedges | VIX 30-35 = nur Öl/Defense/Hedges

---

## Regeln für neue Trades

1. **Markt offen?** → `market_hours.is_trading_day(ticker)` — exchange-spezifisch via exchange_calendars
2. **VIX Hard Block?** → `check_entry_allowed(strategy)`
3. **Conviction hoch genug?** → `calculate_conviction() >= threshold`
4. **Duplicate?** → Ticker schon offen?
5. **Sektor-Limit?** → max 3 Positionen je Sektor
6. **Cash?** → min. 500€ freies Kapital
7. **Alle Guards grün** → Trade öffnen, Features speichern

---

## Scheduler — Was wann läuft

**Python Daemon** (`scripts/scheduler_daemon.py`, systemd auf Hetzner):
Läuft 24/7, keine LLM-Kosten, keine Tokens.

### Tägliche Jobs (24/7)
| Zeit (UTC) | Job | Script |
|---|---|---|
| 02:00 | RL Training | rl_trainer.py |
| 02:00 | CEO Radar Nacht | news_ceo_radar.py |
| 07:00 | CEO Radar Morgen | news_ceo_radar.py |
| 07:05 | Regime Detector | regime_detector.py |
| 07:00+09:00+13:00+17:00+21:00 | Live Data Refresh | core/live_data.py |
| 09:00+13:00+17:00+21:00 | Newswire Analyst | newswire_analyst.py |
| 09:05+13:05+17:05+21:05 | News Gate Update | news_gate_updater.py |
| 09:10+13:10+17:10+21:10 | CEO Radar | news_ceo_radar.py |
| 21:00 | Alpha Decay | alpha_decay.py |
| 21:30 | Performance Tracker | performance_tracker.py |
| 22:45 | Daily Learning | daily_learning_cycle.py |

### Mo-Fr Jobs
| Zeit (UTC) | Job | Script | Discord? |
|---|---|---|---|
| 08:30 | Morgen-Briefing | morning_brief_generator.py | Ja |
| 09:30 | Xetra Opening | us_opening_report.py | Ja |
| 09:00-21:00 (30min) | Thesis Monitor | core/thesis_engine.py --monitor | Nein |
| 09:00-21:00 (30min) | Watchlist Tracker | watchlist_tracker.py | Nein |
| 10:00+14:00+18:30 | Exit Manager | paper_exit_manager.py | Nein |
| 09:15+12:30+16:30 | Auto Scanner | autonomous_scanner.py | Nein |
| 16:30 | US Opening | us_opening_report.py | Ja |
| 22:00 | Abend-Report | evening_report.py | Ja |
| 22:00 | Advisory Backfill | advisory_layer.py | Nein |
| 23:00 | Tagesabschluss | daily_summary.py | Ja |

### Wochenend-Jobs
| Zeit | Job | Script |
|---|---|---|
| Sa 11:30 | Feature Analyzer | feature_collector.py |
| Sa 12:00 | Strategy DNA | strategy_dna.py |
| Sa 14:00 | Strategy Discovery | strategy_discovery.py |
| So 07:00 | Thesis Discovery | intelligence/thesis_discovery.py |
| Mi 07:00 | Thesis Discovery (mid-week) | intelligence/thesis_discovery.py |
| So 09:00 | Backtest Engine | backtest_engine.py |
| Fr 22:30 | Feature Importance | feature_importance.py |

### Background-Threads im Scheduler
- **Albert Discord Chat** — `discord_chat.py` als Daemon-Thread, pollt Discord alle 30s
- **Price Monitor** — `price_monitor.py` als separater Prozess

---

## Albert — Discord Chat Interface

- Pollt Discord DM Channel (1475255728313864413) alle 30 Sekunden
- Antwortet auf Victor's Nachrichten mit Claude Sonnet
- Kann: Trades erklären, Portfolio-Status geben, News diskutieren
- Persönlichkeit definiert in SOUL.md: locker, direkt, meinungsstark, kompetent

---

## Paper Portfolio — Stand 11.04.2026

| Ticker | Strategie | Entry | Stop | Conviction | Status |
|---|---|---|---|---|---|
| SIE.DE | PS17 | 204.70€ | 214.94€ | 3 | offen |
| ASML.AS | STANDALONE | 1139.20€ | 1144.90€ | — | offen |
| TTE.PA | PS1 | 77.56€ | 72.83€ | 6 | offen |
| BMW.DE | PS18 | 79.24€ | 79.64€ | 7 | offen |
| MUV2.DE | PS_MUV2 | 545.00€ | 523.00€ | 6 | offen |

**Cash:** 6494€ | **Startkapital:** 25000€

**Letzte geschlossene Trades (Auswahl):**
- NOVO-B.CO: -843€ (-84.2%) — schwerer Verlust
- EQNR.OL: -1824€ (-91.1%) — schwerer Verlust
- RHM.DE: +60€ (+3.0%)
- MOS: +9€ (+0.3%)

---

## ML-Pipeline — Phasen

| Phase | Script | Status | Beschreibung |
|-------|--------|--------|-------------|
| 1 | feature_collector.py | ✅ | 11 Features bei jedem Entry |
| 2 | backtest_engine.py | ✅ | 622 historische Trades |
| 3 | alpha_decay.py | ✅ | EWMA λ=0.88, Strategie-Edge |
| 4 | online_model.py | ✅ | River ML, 624 Samples |
| 5 | regime_detector.py | ✅ | HMM 4 Regimes, täglich |
| 6 | feature_importance.py | ✅ | RSI top-Feature (0.695) |
| 7 | strategy_dna.py | ✅ | DNA Gate, weiche Constraint |
| 8 | rl_agent.py | 🔄 | PPO Agent, noch lernend |

---

## Wichtige Dateipfade

```
/data/.openclaw/workspace/
  data/
    trading.db              ← Haupt-Datenbank
    newswire.db             ← Overnight/CEO Radar Events
    news_gate.json          ← Aktuelle News-These-Treffer
    ceo_directive.json      ← Aktuelles Regime + Trading-Regeln + AI-Analyse
    strategies.json         ← Alle Strategien mit Status + Kill-Triggers
    strategy_dna.json       ← Optimale Parameter je Strategie
    feature_importance.json ← Top-Features für ML
    alpha_decay.json        ← Strategie-Edge-Scores
    river_model.pkl         ← Trainiertes Online-ML-Modell
    hmm_regime.pkl          ← Trainiertes HMM-Modell
    theme_candidates.json   ← Auto-entdeckte Thesen (Thesis Discovery)
  scripts/
    scheduler_daemon.py     ← Python-Daemon (läuft 24/7, 160+ Jobs)
    ceo.py                  ← CEO Gehirn (Python + Claude Sonnet AI)
    discord_chat.py         ← Albert Discord Chat (Sonnet)
    core/
      news_pipeline.py      ← News-Fetch + DB-Ingest
      market_hours.py       ← Exchange-spezifische Feiertage
      fetch_price.py        ← Preisabruf (Yahoo Finance)
      thesis_engine.py      ← Thesis-Monitoring + Kill-Trigger
      live_data.py          ← Live-Preise + Makro-Refresh
    execution/
      paper_trade_engine.py ← Trade-Ausführung + Guards
      autonomous_scanner.py ← 80+ Ticker Setup-Suche
    intelligence/
      conviction_scorer.py  ← 8-Faktor Conviction Score ← HERZSTÜCK
      thesis_discovery.py   ← Autonome Thesen-Entdeckung (Haiku)
      market_guards.py      ← Earnings, Sector-Checks
    overnight_collector.py  ← Overnight Events + IMPACT_RULES
    paper_exit_manager.py   ← Stop/Trailing/Ziel-Management
    news_gate_updater.py    ← News → These-Matching
    newswire_analyst.py     ← News-Analyse Pipeline
    news_ceo_radar.py       ← CEO Radar (Keyword-Scan)
    discord_sender.py       ← Discord Direktnachrichten (kein LLM)
  deploy/
    trademind-scheduler.service  ← systemd Service
    trademind-api.service        ← API Service
    setup-vps.sh                 ← VPS Setup-Script
    migrate-to-vps.sh           ← Daten-Migration
    watchdog-cron.sh            ← Service-Watchdog
  memory/
    strategien.md           ← Alle aktiven Thesen (Victor's Playbook)
    albert-accuracy.md      ← Trefferquoten + offene Prognosen
    strategy-changelog.md   ← Statuswechsel der Strategien
    newswire-analysis.md    ← Letzter Newswire-Analyst-Output
    state-snapshot.md       ← Aktueller Portfolio-Stand
    projekt-tradingtool.md  ← DIESE DATEI
```

---

## Wichtige Regeln für KI-Agenten

1. **Markt-Check immer zuerst** — `market_hours.is_trading_day(ticker)` vor jedem Trade
2. **conviction_scorer liegt in scripts/intelligence/**, NICHT in scripts/ (Shadowing-Problem!)
3. **python3 nutzen** für alle Scripts auf VPS (nicht python3.14!)
4. **Stops immer korrekt** — Stop muss UNTER Entry liegen (Long-Trades). Bei Trailing: nie über Kurs setzen
5. **news_gate.json Struktur:** `{relevant, theses_hit: ["PS1_Oil","S1_Iran",...], hit_count, top_hits}`
6. **Strategie-Naming:** paper_trade_engine nutzt `PS1`, `PS3`, `PS11` etc. NICHT `PS1_Oil`. Mapping in conviction_scorer.py
7. **Weekend-Check:** Scanner + Exit Manager blocken sich selbst an Wochenenden und Feiertagen
8. **Keine echten Trades** — alles Paper bis Victor explizit auf Real umschaltet
9. **Victor tradet NUR in EUR** — alle Preise, Stops, Ziele immer in EUR (Trade Republic)
10. **Airlines-Regel in IMPACT_RULES:** Nur spezifische Keywords (kerosene, jet fuel), NICHT "oil" (sonst false positives!)
11. **CEO AI kann überschreiben** — aber nur bei Confidence ≥ 0.75, sonst gelten Python-Regeln
12. **Thesis Discovery auf Haiku** — spart Tokens, Qualität reicht für Screening
