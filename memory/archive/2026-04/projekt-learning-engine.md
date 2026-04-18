# Projekt: Learning Engine — Cross-System Lernen

## Vision
Ein System das aus ALLEN Trades lernt (echt + paper) und die Erkenntnisse
zurück in Analyse und Entscheidungen fließen lässt.

## Kern-Idee: Feedback Loops

### Loop 1: Strategie-Gewichtung
- Nach jedem geschlossenen Trade: Win/Loss → Strategie-Score updaten
- S1 (Öl) hat 70% Win-Rate → mehr Gewicht im Screener
- S4 (Edelmetalle) hat 30% → weniger Gewicht oder aufgeben
- Ergebnis: Screener-Score berücksichtigt Strategie-Erfolg

### Loop 2: Parameter-Lernen
- Backtester testet verschiedene Stop/Ziel-Kombinationen
- Ergebnis: "Für Öl-Aktien ist 8% Stop + 15% Ziel optimal"
- Diese Parameter fließen automatisch in trading_config.json
- Und in den 15-Min-Monitor (trading_monitor.py)

### Loop 3: Muster-Erkennung
- Wenn bestimmte News-Muster zu Kursbewegungen führen:
  "Iran-Eskalation + WTI >$90 → EQNR steigt in 80% der Fälle innerhalb 48h"
- Diese Muster in einer Pattern-DB speichern
- Bei ähnlichen News automatisch Alert: "Pattern Match: Iran-Eskalation erkannt"

### Loop 4: Fehler-Vermeidung
- Jeder Verlust wird analysiert: Was war der Fehler?
- Häufigste Fehler identifizieren (z.B. "Momentum-Chasing", "Stop zu eng")
- Bei neuem Trade prüfen: "Machst du gerade denselben Fehler wie bei RHM am 11.03.?"
- Konkret: Checkliste wird um historische Fehler-Patterns erweitert

### Loop 5: Paper → Echt Brücke
- Wenn eine Paper-Strategie 20+ Trades mit >55% Win-Rate hat:
  → Empfehlung an Victor: "PS3 (EU-Defense) hat im Paper Fund 62% Win-Rate über 3 Monate. Echtes Geld wert?"
- Wenn eine echte Strategie verliert:
  → Automatisch Paper-Varianten testen mit angepassten Parametern

## Technische Umsetzung

### learning_engine.py (zu bauen)
```python
# Kernfunktionen:
update_strategy_weights()    # Nach jedem Trade-Close
get_optimal_params(strategy) # Aus Backtester-Ergebnissen
check_error_patterns(trade)  # Vor jedem neuen Trade
recommend_real_trades()      # Paper → Echt Promotion
generate_weekly_insights()   # Was hat diese Woche gelehrt?
```

### Integration in bestehende Crons
- Morgen-Briefing: + Screener-Scores für echte Positionen
- Trading-Monitor: + Backtester-optimierte Parameter
- Abend-Report: + Learning-Insights des Tages
- Wochen-Review: + Strategie-Performance echt vs. paper

## Roadmap
- [ ] Woche 1: trade_journal.py für echte Trades erweitern
- [ ] Woche 1: stock_screener.py in Morgen-Briefing einbauen
- [ ] Woche 2: learning_engine.py — Strategie-Gewichtung (Loop 1)
- [ ] Woche 2: Backtester-Parameter in trading_config.json übertragen (Loop 2)
- [ ] Woche 3: Fehler-Pattern-DB (Loop 4)
- [ ] Woche 4: Paper → Echt Promotion-Logik (Loop 5)
- [ ] Monat 2: Muster-Erkennung (Loop 3)
