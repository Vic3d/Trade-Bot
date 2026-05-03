# Sprint 0 Task 3: Conviction-Inversion-Bug — Diagnose

**Datum:** 2026-05-03
**Status:** ROOT-CAUSE identifiziert, NICHT in Sprint 0 gefixt (zu groß)

## Symptom

`conviction_calibration.py` lieferte `b = -0.948` (negative slope).
Logistische Regression: höhere Conviction → niedrigere Win-Wahrscheinlichkeit.
Das wirkte wie ein "inverted signal" — alarmierender Befund.

## Tatsächliche Daten-Verteilung

Bucket-Analyse aller 65 closed Trades:

| Bucket | N | Actual WR |
|---|---:|---:|
| **0-10%** | **60** | **65.0%** |
| 50-60% | 3 | 66.7% |
| 60-70% | 1 | 0.0% |
| 90-100% | 1 | 0.0% |

**92% aller Trades haben Conviction 0-10%.** Median Conviction WIN = 5, Median LOSS = 5.

→ Das System DIFFERENZIERT NICHT. Es ist nicht inverted, es ist KAPUTT.

## Root-Cause

`scripts/intelligence/conviction_scorer.py` hat **6+ Code-Pfade die `'score': 0` als Default-Fallback returnen**:

- Line 845: bei Strategy-Lookup-Fail
- Line 868: bei BLOCKED-Status
- Line 899/920/966/997: bei verschiedenen Daten-Lücken

Wenn IRGENDWAS fehlschlägt (Cache-Miss, fehlender Preis, Strategy nicht gefunden, unvollständige Macro-Daten) → Score = 0.

## Konsequenz für Logistic-Fit

Mit 60 Trades bei Conviction 5 (alle in einem Bucket) und nur 5 Trades > 10% (4 davon Loser):
- Logistic-Regression sieht: niedrige Werte → hohe WR; höhere Werte → niedrigere WR
- Slope wird negativ — aber das ist Artefakt der Sample-Verteilung, kein echtes Signal

## Was das für Sprint 0 bedeutet

**Conviction-Score ist als P(win)-Predictor unbrauchbar.**
Aktuelle Nutzung in:
- `paper_trade_engine.py` Guard 2 (Conviction >= 45 minimum)
- `conviction_calibration.py` (logistic fit)
- `ml_forecaster.py` (als Feature)
- Position-Sizing (in `risk_based_sizing.py`)

Diese alle arbeiten mit kaputten Werten.

## Fix-Plan (Sprint 1+)

1. **Sprint 0 (heute): NICHT fixen.** Conviction-Score-Logik komplett umbauen wäre 8-15h Code mit hohem Test-Bedarf.

2. **Sprint 1 (Backtest-Framework): Conviction-Score wird IRRELEVANT.** XGBoost auf Feature-Engineered Features wird Conviction ersetzen als P(win)-Predictor. Conviction bleibt als simple Heuristik.

3. **Quick-Mitigation jetzt:**
   - Conviction-Threshold von 45 → 0 setzen (sonst werden Trades fälschlich geblockt durch kaputten Score)
   - Im aggressive_paper_mode ist das schon so
   - In Strategy-Logik: nicht mehr von conviction-Wert abhängig machen

4. **Sprint 1 deliverable:** XGBoost-Klassifier auf den 30+ Features = echter P(win). Conviction-Score wird zu "Setup-Quality-Hint" gestuft, nicht mehr Trade-Gate.

## Bewertung

- **Inverted-Signal-Befund von Sprint 0:** ein FALSCHER ALARM aufgrund kaputter Daten
- **Realer Befund:** Conviction-Scorer ist seit Anfang kaputt, alle Bewertungen waren bedeutungslos
- **Impact auf existierende Trades:** wir haben Trades mit "Conviction 5" gemacht ohne dass das eine echte Information war. Glück mit WR 63% kommt also NICHT aus Conviction-Filter sondern aus Strategy-Selection (Hunter-LLM) und Stop-Management

## Action-Items

- [x] Diagnose dokumentiert
- [ ] Sprint 1: XGBoost-Replacement bauen
- [ ] Sprint 1: Conviction-Bewertung als bloßer "Setup-Quality-Hint" deklarieren
- [ ] Sprint 1: Logistic-Calibration auf den XGBoost-Output (nicht conviction)
