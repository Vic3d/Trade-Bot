# TradeMind — Projekt-Dokumentation
**Letzte Änderung:** 2026-04-04  
**Status:** Paper Trading aktiv, autonomer Loop geschlossen  

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

### Warum das wichtig ist
TradeMind ist kein normales Tool-Projekt. Es ist der Beweis dass:
- eine KI eigenständig bessere Trading-Entscheidungen treffen kann als der Durchschnitts-Retail-Trader
- ein System das aus seinen eigenen Fehlern lernt sich selbst verbessert
- Geopolitik + Makro + Technik systematisch kombinierbar sind

**Roadmap:**
- 2026 Q1-Q2: Paper Trading, ML-Pipeline aufbauen, Lernphase
- 2026 Q3-Q4: Erste Real-Money-Trades (kleine Positionen), System validieren
- 2027: Produkt für andere Trader, Vermarktung

---

---

## Was ist TradeMind?

TradeMind ist Victors autonomes Trading-System. Es soll selbstständig:
1. Nachrichten sammeln und auswerten
2. Eigene Strategien entwickeln und gegenchecken
3. Paper-Trades eröffnen, überwachen und schließen
4. Aus Ergebnissen lernen und besser werden
5. Irgendwann (ca. 2027) echtes Geld traden

Victor ist der Mensch der die Strategie-Thesen vorgibt und das System überwacht. Albert (KI) entscheidet Entries/Exits autonom im Paper-Modus.

---

## Architektur — Der autonome Loop

```
[1] NEWS SAMMELN
    scripts/core/news_pipeline.py
    → fetcht Bloomberg RSS + Google News → trading.db:news_events
    → läuft 4x täglich via scheduler_daemon.py (09:00, 13:00, 17:00, 21:00)

[2] NEWS AUSWERTEN
    scripts/news_gate_updater.py
    → matched news_events gegen Strategie-Thesen (PS1_Oil, PS3_Defense etc.)
    → schreibt data/news_gate.json: {relevant, theses_hit, hit_count}
    → läuft 4x täglich (5 Min nach News-Fetch)

[3] CONVICTION BERECHNEN
    scripts/intelligence/conviction_scorer.py
    → 8 Faktoren: Regime, Technical, Volume, News Momentum, Confluence,
      Backtest, Correlation, Sector Rotation
    → news_gate.json fließt in news_momentum-Faktor
    → Output: Score 0-100 + recommendation + vix_block
    → Thresholds: PS_* Thesis-Plays = 35+, Standard = 52+

[4] SCANNER SUCHT SETUPS
    scripts/execution/autonomous_scanner.py
    → 80+ Ticker in 3 Tiers (A=konservativ, B=moderat, C=aggressiv)
    → Tier A: Thesis-Plays, RSI-Bounce, 18%+ unter 52W-High, CRV 2:1+
    → Tier B: Sektor-Rotation, EMA-Cross, Oversold-Bounce
    → Tier C: News-Katalysator, Breakouts
    → WICHTIG: läuft nur wenn Börsen offen (exchange_calendars, ticker-spezifisch)
    → ruft execute_paper() auf → paper_trade_engine

[5] TRADE AUSFÜHREN
    scripts/execution/paper_trade_engine.py
    → Guards: VIX Hard Block → Conviction → Duplicate → Sektor-Limit → Cash
    → schreibt in trading.db:paper_portfolio
    → speichert alle Features bei Entry (RSI, Volume, VIX, Regime, MA50...)

[6] POSITIONEN ÜBERWACHEN
    scripts/paper_exit_manager.py
    → prüft Stop-Loss, Trailing Stop, Zielkurs
    → läuft 3x täglich (10:00, 14:00, 18:30) via scheduler_daemon
    → WICHTIG: läuft nur wenn Börsen offen
    → triggert nach Exit sofort: online_model.learn_from_closed_trade()

[7] LERNEN
    scripts/online_model.py      → River ML, nach jedem Trade Update
    scripts/alpha_decay.py       → EWMA λ=0.88, Strategie-Edge tracken
    scripts/daily_learning_cycle.py → täglich 22:45, Regeln ableiten
    scripts/backtest_engine.py   → Wochenende, historische Validierung
    scripts/feature_importance.py → wöchentlich, welche Features zählen?
    scripts/strategy_dna.py      → optimale Parameter je Strategie
    scripts/rl_agent.py          → PPO Reinforcement Learning (nächste Ausbaustufe)
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

---

## Strategie-Thesen (Aktive)

Diese Thesen sind von Victor validiert und bilden die Grundlage für Trades:

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
| PS_NVO | Novo Nordisk | GLP-1 Bewertungsabschlag, PE 10x | NOVO-B.CO |

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

## Regeln für neuen Trades

1. **Markt offen?** → `market_hours.is_trading_day(ticker)` — exchange-spezifisch via exchange_calendars
2. **VIX Hard Block?** → `check_entry_allowed(strategy)`
3. **Conviction hoch genug?** → `calculate_conviction() >= threshold`
4. **Duplicate?** → Ticker schon offen?
5. **Sektor-Limit?** → max 3 Positionen je Sektor
6. **Cash?** → min. 500€ freies Kapital
7. **Alle Guards grün** → Trade öffnen, Features speichern

---

## Scheduler — Was wann läuft

**Python Daemon** (`scripts/scheduler_daemon.py`, PID in data/scheduler.pid):
Läuft 24/7, keine LLM-Kosten, keine Tokens.

| Zeit | Job | Script |
|------|-----|--------|
| 07:00 tägl. | Regime Detector | regime_detector.py |
| 09:00/13:00/17:00/21:00 | News Analyst | newswire_analyst.py |
| 09:05/13:05/17:05/21:05 | News Gate Update | news_gate_updater.py |
| 10:00/14:00/18:30 Mo-Fr | Exit Manager | paper_exit_manager.py |
| 09:15/12:30/16:30 Mo-Fr | Autonomous Scanner | autonomous_scanner.py |
| 21:00 tägl. | Alpha Decay | alpha_decay.py |
| 22:45 tägl. | Daily Learning | daily_learning_cycle.py |
| 02:00 tägl. | RL Training | rl_trainer.py |
| Sa 11:30 | Feature Analyzer | feature_collector.py |
| So 09:00 | Backtest Engine | backtest_engine.py |
| Sa 12:00 | Strategy DNA | strategy_dna.py |
| Fr 22:30 | Feature Importance | feature_importance.py |

**OpenClaw Crons** (LLM, für menschlich lesbare Outputs):
- 08:30 Mo-Fr: Morgen-Briefing (Sonnet)
- 10:00 Mo-Fr: Xetra Opening-Check (Sonnet)
- 16:30 Mo-Fr: US Opening-Check (Sonnet)
- 22:00 Mo-Fr: Abend-Report (Sonnet)
- 23:00 tägl.: Tagesabschluss (Sonnet)
- 10:00/14:00 Mo-Fr: Strategie-Check (Haiku)
- Stündlich: Daemon Watchdog (Haiku, 30s) — ID: cbadbb9a

---

## Paper Portfolio — Stand 04.04.2026

| Ticker | Strategie | Entry | Stop | +/- | Status |
|--------|-----------|-------|------|-----|--------|
| RHM.DE | PS11 | 1409.50 | 1299.56 | +11.4% | 🟢 |
| ZIM | PS14 | 22.83 | 21.67 | +15.2% | 🟢 |
| MOS | PS5 | 22.72 | 20.14 | +15.2% | 🟢 |
| NOVO-B.CO | PS_NVO | 200.85 | 201.85 | +17.9% | 🟢 |
| ASML.AS | STANDALONE | 1139.20 | 1050.00 | +1.9% | ⬜ |
| TTE.PA | PS1 | 77.56 | 72.83 | +2.0% | ⬜ |
| EQNR.OL | PS1 | 399.10 | 363.39 | +0.0% | ⬜ |
| BMW.DE | PS18 | 79.24 | 75.31 | ? | ⬜ |
| SIE.DE | PS17 | 204.70 | 193.34 | ? | ⬜ |

**Closed Trades:** 84 gesamt | 48% Win-Rate | +1.462€ realisiert

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
    news_gate.json          ← Aktuelle News-These-Treffer
    ceo_directive.json      ← Aktuelles Regime + Trading-Regeln
    strategy_dna.json       ← Optimale Parameter je Strategie
    feature_importance.json ← Top-Features für ML
    alpha_decay.json        ← Strategie-Edge-Scores
    river_model.pkl         ← Trainiertes Online-ML-Modell
    hmm_regime.pkl          ← Trainiertes HMM-Modell
  scripts/
    core/
      news_pipeline.py      ← News-Fetch + DB-Ingest
      market_hours.py       ← Exchange-spezifische Feiertage
      fetch_price.py        ← Preisabruf (Yahoo Finance)
    execution/
      paper_trade_engine.py ← Trade-Ausführung + Guards
      autonomous_scanner.py ← Selbstständige Setup-Suche
    intelligence/
      conviction_scorer.py  ← 8-Faktor Conviction Score ← HERZSTÜCK
      market_guards.py      ← Earnings, Sector-Checks
    paper_exit_manager.py   ← Stop/Trailing/Ziel-Management
    news_gate_updater.py    ← News → These-Matching
    newswire_analyst.py     ← News-Analyse Pipeline
    scheduler_daemon.py     ← Python-Daemon (läuft 24/7)
    discord_sender.py       ← Discord Direktnachrichten (kein LLM)
  memory/
    strategien.md           ← Alle aktiven Thesen (Victor's Playbook)
    albert-accuracy.md      ← Trefferquoten + offene Prognosen
    strategy-changelog.md   ← Statuswechsel der Strategien
    newswire-analysis.md    ← Letzter Newswire-Analyst-Output
```

---

## Wichtige Regeln für KI-Agenten

1. **Markt-Check immer zuerst** — `market_hours.is_trading_day(ticker)` vor jedem Trade
2. **conviction_scorer liegt in scripts/intelligence/**, NICHT in scripts/ (Shadowing-Problem!)
3. **python3.13 nutzen** für alle ML-Scripts (river + numpy laufen NUR auf 3.13, nicht 3.14)
4. **Stops immer korrekt** — Stop muss UNTER Entry liegen (Long-Trades). Bei Trailing: nie über Kurs setzen
5. **news_gate.json Struktur:** `{relevant, theses_hit: ["PS1_Oil","S1_Iran",...], hit_count, top_hits}`
6. **Strategie-Naming:** paper_trade_engine nutzt `PS1`, `PS3`, `PS11` etc. NICHT `PS1_Oil`. Mapping in conviction_scorer.py
7. **Weekend-Check:** Scanner + Exit Manager blocken sich selbst an Wochenenden und Feiertagen
8. **Keine echten Trades** — alles Paper bis Victor explizit auf Real umschaltet
