# Projekt: Paper Trading System — Autonomes Analyse-Trading

## Vision
Albert lernt durch systematische Marktanalyse und Paper-Trading,
eigenständig profitable Trades zu identifizieren und auszuführen.
Langfristziel: Autonomes Trading mit nachweisbarer Edge.

## Status: Phase 1 — Fundament ✅ (Basis fertig)
*Gestartet: 17.03.2026*
*Phase 1 Basis: 17.03.2026 — alle 4 Scripts gebaut + getestet*

## Architektur

```
[Daten-Pipeline]
Yahoo Finance API → SQLite DB (daily closes, 2Y+ History)
Google News RSS → Sentiment-Score (pos/neg/neutral)
Liveuamap → Geopolitik-Events

[Analyse-Engine]
Stock Screener → Multi-Faktor-Score pro Aktie
Sektor-Rotation → Welcher Sektor hat Momentum?
Relative-Stärke → Aktie vs. Sektor vs. Markt
Support/Resistance → Automatisch aus Preis-History

[Strategie-Engine]
Backtester → Strategie gegen History testen
Signal-Generator → Trigger erfüllt? → Conviction Score
Risk Manager → Positionsgröße, Korrelation, Max Drawdown

[Execution]
Paper-Portfolio → Trades ausführen + dokumentieren
Trade-Journal (SQLite) → Jeder Trade strukturiert gespeichert
Lern-Engine → Win/Loss-Rate pro Strategie → Gewichte anpassen

[Reporting]
Morgen-Briefing → Signals + Watchlist + Portfolio-Status
Abend-Report → P&L + Markt-Review + Lessons
Wochen-Review → Strategie-Performance + Learnings
```

## Phase 1 — Sofort-Tasks

### 1.1 SQLite Preis-Datenbank ✅
- [x] Script: `scripts/price_db.py`
- [x] Tabellen: prices + ticker_meta
- [x] Initial-Load: 44/45 Ticker (YARA.OL delisted), 22.124 Datensätze
- [x] Daily-Update: `python3 price_db.py update`
- [x] Abfragen: SMA, RSI14, Relative Stärke, Volumen-Ratio

### 1.2 Stock Screener ✅
- [x] Script: `scripts/stock_screener.py`
- [x] 5-Faktor-Scoring (RSI, Trend, RS, SMA-Dist, Volumen) → max 100
- [x] Output: JSON + human-readable Ranking
- [x] Strategie-Filter: `--strategy PS1` etc.

### 1.3 Trade-Journal ✅
- [x] Script: `scripts/trade_journal.py`
- [x] CLI: open/close/list/stats
- [x] Stats: Win-Rate, Avg Win/Loss, CRV, nach Strategie

### 1.4 Backtester v1 ✅
- [x] Script: `scripts/backtester.py`
- [x] Regelengine: RSI + SMA Entry, Stop/Target/Trailing Exit
- [x] Output: Trades, Win-Rate, P&L, Drawdown, Sharpe
- [x] Strategy-Mode: `--strategy PS3` testet alle Ticker

### Erkenntnisse Phase 1:
- RSI<35 + Kurs>SMA50 ist in 2J-History sehr selten → Parameter-Tuning nötig
- Screener Top-Picks: HAL (85/100), OXY (75), CF (75), DHT (65), HII (65)
- YARA.OL ist delisted bei Yahoo — Alternative suchen oder entfernen

## Phase 2 — Woche 3-4
- [ ] Backtester für alle PS1-PS5 Strategien laufen lassen
- [ ] Unprofitable Strategien streichen oder anpassen
- [ ] Parameter-Optimierung (Stop-Abstand, Trailing-Level)

## Phase 3 — Monat 2
- [ ] Signal-Engine mit automatischen Alerts
- [ ] Conviction Score v2 (datenbasiert statt Bauchgefühl)
- [ ] Automatische Watchlist-Generierung

## Phase 4 — Monat 3+
- [ ] Autonome Execution im Paper Fund
- [ ] Lern-Engine: Strategie-Gewichte nach Win-Rate anpassen
- [ ] Portfolio-Optimierung (Korrelation, Drawdown)

## Prinzipien
1. **Daten schlagen Meinungen** — Kein Trade ohne quantitative Grundlage
2. **Backtest vor Live-Trade** — Jede Strategie muss historisch funktionieren
3. **Fehler dokumentieren** — Jeder Verlust ist eine Lektion
4. **Geduld** — System braucht 3-6 Monate um Edge nachzuweisen
5. **Iteration** — Jede Woche etwas besser werden

## Metriken (ab Phase 2)
- Win-Rate pro Strategie (Ziel: >55%)
- Durchschnittliches CRV realisiert (Ziel: >1,5:1)
- Max Drawdown (Ziel: <15%)
- Sharpe Ratio (Ziel: >1,0)
- Trefferquote Screener vs. Random (muss statistisch signifikant besser sein)
