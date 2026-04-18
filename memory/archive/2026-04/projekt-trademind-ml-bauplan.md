# TradeMind ML — Bauplan (Langfristig)
*Erstellt: 2026-04-04 | Status: PLANUNG*
*Ziel: Vom regelbasierten Scoring → echtes selbstlernendes Trading-System*

---

## Ausgangslage (April 2026)

**Was wir haben:**
- ✅ SQLite Trading DB (`trading.db`) mit allen Trades
- ✅ Regelbasiertes Conviction Scoring (Win-Rate → +/- conviction)
- ✅ Signal Feedback Loop (price_at_flag → 30min/2h/24h)
- ✅ Paper Exit Manager mit automatischem Learning-Hook
- ✅ Daily Learning Cycle Cron (22:45)
- ❌ Kein echtes ML-Modell
- ❌ Keine Feature-Daten (RSI, Volume, VIX bei Entry gespeichert)
- ❌ Kein Backtest-Engine
- ❌ Kein Online-Learning

**Verfügbar auf dem System:**
- Python 3.14.3
- Nur pip + wheel installiert (alles muss noch installiert werden)
- SQLite 3 (builtin)

---

## Architektur-Übersicht

```
Phase 1: Feature Tracking     → "Was war der Markt bei diesem Trade?"
Phase 2: Backtest Engine      → "Hätte das auf echten Daten funktioniert?"
Phase 3: Alpha Decay          → "Verliert mein Signal an Kraft?"
Phase 4: Online Learning      → "Lerne ich aus jedem Trade direkt?"
Phase 5: Regime Detection     → "In welchem Markt bin ich gerade?"
Phase 6: Feature Importance   → "Welche Signale haben wirklich Vorhersagekraft?"
Phase 7: Strategy DNA         → "Was ist das optimale Profil einer guten Strategie?"
Phase 8: Reinforcement Learning → "Kann ich autonom traden?"
Phase 9: Real Money           → Kontrolliertere Echtgeld-Aktivierung
```

---

## Phase 1 — Feature Tracking (JETZT, Woche 1-2)

**Ziel:** Jeden Trade-Entry mit Marktdaten anreichern. Ohne das können wir nie lernen *warum* etwas funktioniert.

**Was gespeichert wird (pro Trade):**
```sql
ALTER TABLE paper_portfolio ADD COLUMN rsi_at_entry REAL;
ALTER TABLE paper_portfolio ADD COLUMN volume_ratio REAL;  -- vol / avg_20d_vol
ALTER TABLE paper_portfolio ADD COLUMN vix_at_entry REAL;
ALTER TABLE paper_portfolio ADD COLUMN atr_pct_at_entry REAL;
ALTER TABLE paper_portfolio ADD COLUMN ma50_distance REAL; -- % über/unter MA50
ALTER TABLE paper_portfolio ADD COLUMN day_of_week INTEGER; -- 0=Mo, 4=Fr
ALTER TABLE paper_portfolio ADD COLUMN hour_of_entry INTEGER;
ALTER TABLE paper_portfolio ADD COLUMN sector_momentum REAL; -- Sektor-ETF 5d Return
ALTER TABLE paper_portfolio ADD COLUMN spy_5d_return REAL; -- Marktkontext
```

**Implementierung:**
- `scripts/feature_collector.py` — holt RSI/Volume/ATR via Yahoo Finance
- Wird in `paper_trade_engine.py` bei jedem INSERT aufgerufen
- Backfill: bestehende offene Trades rückwirkend anreichern

**Liefert nach 50 Trades:**
- Erste statistische Auswertung: Welche Feature-Ranges correlieren mit Wins?

**Abhängigkeiten:** numpy (leicht, builtin-ähnlich), keine ML-Library nötig

---

## Phase 2 — Backtest Engine (Woche 3-6)

**Ziel:** Strategien auf 2+ Jahre historischen Daten testen, BEVOR sie Paper-Trading werden. Walk-Forward-Methode: niemals in die Zukunft schauen.

**Walk-Forward-Prinzip:**
```
Trainings-Fenster: 2 Jahre   Test-Fenster: 3 Monate → rollt vor
Jan 2023 - Dez 2024  →  Test Jan-Mar 2025
Apr 2023 - Mär 2025  →  Test Apr-Jun 2025
...
```

**Was backtested wird:**
- Alle PS/PT/PM Strategien
- Gleiche Einstiegs-Regeln wie im Paper-System
- Gleiche Stop/Target-Logik
- Output: Sharpe Ratio, Max Drawdown, Win-Rate, Alpha vs. SPY

**Implementierung:**
- `scripts/backtest_engine.py` — OHLCV Download (yfinance), Strategie-Simulation
- `scripts/walk_forward.py` — automatisiertes Roll-Forward Testing
- Ergebnisse in `data/backtest_results.json`

**Warum wichtig:** Paper Trading mit 3 Monaten Data sagt nichts. Backtest auf 2+ Jahren sagt sehr viel.

**Abhängigkeiten:** yfinance (schon genutzt), pandas, numpy

---

## Phase 3 — Alpha Decay Detection (Monat 2)

**Ziel:** Automatisch erkennen wenn ein Signal seine Vorhersagekraft verliert.

**Kernidee:** Neuere Trades zählen mehr als alte (Exponential Moving Average auf Win-Rate).

```python
# Statt: Win-Rate = Wins / Alle Trades (gleichgewichtet)
# Besser: exponentiell gewichtete Win-Rate
decay_factor = 0.92  # ältere Trades verlieren 8% Gewicht pro Trade
weighted_win_rate = ewma(outcomes, alpha=1-decay_factor)
```

**Trigger:**
- Decay-adjustierte Win-Rate fällt unter Raw-Win-Rate → Signal altert
- Differenz > 10%p → `alpha_decay_alert` → Strategie in "MONITORING" Status

**Implementierung:**
- Erweiterung von `paper_learning_engine.py`
- Neues Feld `alpha_decay_score` in `trading_learnings.json`

**Abhängigkeiten:** numpy (EWMA)

---

## Phase 4 — Online Learning mit River (Monat 2-3)

**Ziel:** Modell das sich mit JEDEM Trade aktualisiert — kein wöchentliches Batch-Retraining.

**Warum River statt Scikit-Learn:**
- Scikit-Learn: batch → braucht alle Daten auf einmal → retraining-Overhead
- River: one-sample-at-a-time → update nach jedem Trade → 0 Overhead
- Perfekt für unsere Trade-Frequenz (5-20 Trades/Woche)

**Modell-Architektur:**
```python
from river import linear_model, preprocessing, compose

model = compose.Pipeline(
    preprocessing.StandardScaler(),
    linear_model.LogisticRegression()  # Output: Win-Wahrscheinlichkeit 0-1
)

# Features: [rsi, volume_ratio, vix, ma50_distance, sector_momentum, spy_5d]
# Label: 1 = WIN, 0 = LOSS

# Bei jedem Trade-Close → model.learn_one(features, outcome)
# Bei jedem Trade-Entry → model.predict_proba_one(features) → Win-Wahrscheinlichkeit
```

**Integration:**
- `scripts/online_model.py` — River Model wrapper
- Model-State wird in `data/river_model.pkl` gespeichert (persistent)
- Bei Trade-Entry: `predict_proba` → entry_confidence als Feature
- Bei Trade-Close: `learn_one` → Modell updatet

**Warum das besser als unser aktuelles Scoring:**
- Aktuell: "DT4 hat 40% Win-Rate" → binär
- Mit River: "Dieses spezifische Setup (RSI 67, VIX 24, Volume 1.8x) hat 73% Win-Wahrscheinlichkeit"

**Installation:** `pip install river`
**Abhängigkeiten:** river (pure Python, leicht)

---

## Phase 5 — Regime Detection mit HMM (Monat 3-4)

**Ziel:** Automatische Erkennung des aktuellen Markt-Regimes — präziser als VIX-Schwellenwerte.

**Warum HMM (Hidden Markov Model):**
- Markt wechselt zwischen "versteckten Zuständen" (Bull/Bear/Sideways/Crash)
- HMM lernt diese Zustände aus Preis-/Volatilitäts-Daten
- Objektiver als "VIX < 20 = Bull" — das ist willkürlich

**Architektur:**
```python
from hmmlearn import hmm

model = hmm.GaussianHMM(n_components=4)  # 4 Regime
# Features: [daily_return, vix_change, volume_change, spread]
model.fit(market_data_2years)

# Output: regime_probability[0-3] für jeden Tag
# Regime 0 = Bull, 1 = Neutral, 2 = Risk-Off, 3 = Crash
# Objektiviert durch Daten, nicht durch meine Meinung
```

**Integration:**
- `scripts/regime_detector.py` — täglicher Regime-Score
- CEO Direktive nutzt Regime-Scores statt VIX-Schwellenwerte
- Strategie-Allocation passt sich dynamisch an Regime an

**Training-Daten:** 5 Jahre S&P 500 + VIX + Volume → solide Regime-Erkennung

**Installation:** `pip install hmmlearn`

---

## Phase 6 — Feature Importance Engine (Monat 4-5)

**Ziel:** Wissenschaftlich ermitteln welche der gespeicherten Features tatsächlich Vorhersagekraft haben.

**Voraussetzung:** Mindestens 150-200 geschlossene Trades mit vollständigen Feature-Daten (aus Phase 1)

**Modell:** Random Forest + SHAP (SHapley Additive exPlanations)
```python
from sklearn.ensemble import RandomForestClassifier
import shap

# X = Feature-Matrix (RSI, Volume, VIX, etc. bei Entry)
# y = Outcomes (1=WIN, 0=LOSS)
rf = RandomForestClassifier(n_estimators=100)
rf.fit(X_train, y_train)

# SHAP: welche Features hatten welchen Einfluss auf welchen Trade?
explainer = shap.TreeExplainer(rf)
shap_values = explainer(X_test)
# Output: "RSI bei Entry war das wichtigste Feature (+0.23 Einfluss)"
```

**Was wir lernen:**
- Sind Einstiegs-RSI-Werte wirklich prädiktiv? (oder war es nur Zufall)
- Welche VIX-Range führt zu den besten Outcomes?
- Ist Wochentag relevant? (Monday-Effect etc.)
- Welche Kombination aus Features ist optimal?

**Retraining:** Wöchentlich (Sonntag 08:00) auf Rolling-6-Monate-Fenster

**Installation:** `pip install scikit-learn shap`

---

## Phase 7 — Strategy DNA (Monat 5-6)

**Ziel:** Jede Strategie bekommt ein datengetriebenes "DNA-Profil" — die optimalen Einstiegsbedingungen, nicht von mir definiert sondern aus den Daten destilliert.

**Was Strategy DNA enthält:**
```json
{
  "PS1": {
    "optimal_rsi_range": [45, 65],
    "optimal_vix_range": [20, 30],
    "volume_ratio_min": 1.3,
    "best_regime": "NEUTRAL",
    "worst_weekday": 0,
    "expected_win_rate": 0.63,
    "confidence_interval": [0.54, 0.72],
    "feature_importance": {
      "vix_at_entry": 0.31,
      "rsi_at_entry": 0.24,
      "volume_ratio": 0.18,
      "spy_5d_return": 0.14,
      "sector_momentum": 0.13
    }
  }
}
```

**Integration:**
- Entry Gate prüft DNA-Profil → nur traden wenn aktuelle Bedingungen im Optimal-Range
- CEO nutzt DNA um Conviction-Scores zu verfeinern
- Neue Strategien werden gegen bekannte DNA-Profile gecheckt

---

## Phase 8 — Reinforcement Learning (Jahr 2, ab Q1 2027)

**Ziel:** Autonomes Trading-System das ohne explizite Regeln lernt, aus Erfahrung zu handeln.

**Warum erst Jahr 2:**
- Braucht 10.000+ simulierte Trades (aus Backtest Engine) zum Trainieren
- Ohne Phase 1-7 als Fundament → Overfitting-Chaos
- Emotionsloser Realismus: RL-Systeme funktionieren erst nach Monaten Training

**Architektur:**
```
Environment → State (Markt + Portfolio) → Agent (PPO) → Action (BUY/SELL/HOLD) → Reward (Sharpe)
```

**Konkret:**
```python
from stable_baselines3 import PPO
from gymnasium import Env

class TradingEnv(Env):
    def __init__(self, historical_data): ...
    def step(self, action):  # BUY=0, SELL=1, HOLD=2
        # Simuliert Trade, gibt Reward zurück
        reward = sharpe_ratio_delta  # Risikoadjustiert
        return next_state, reward, done, info

# Training: 1 Mio Timesteps auf historischen Daten
model = PPO("MlpPolicy", env, verbose=1)
model.learn(total_timesteps=1_000_000)
```

**Deployment:**
- Erst: Paper Trading mit RL-Agent (Schatten-Modus, Empfehlungen)
- Dann: Hybrid (RL schlägt vor, Mensch bestätigt)
- Ziel: Autonomes Paper Trading → Echtgeld wenn Sharpe > 1.5 über 6 Monate

**Installation:** `pip install stable-baselines3 gymnasium`

---

## Phase 9 — Real Money Aktivierung (Jahr 2+)

**Kriterien (ALLE müssen erfüllt sein):**
- [ ] 6+ Monate Paper Trading mit Win-Rate >55% (nicht Einzelmonate, rolling average)
- [ ] Feature Model (Phase 6): Predictions auf OOS-Daten >60% Accuracy
- [ ] RL-Agent (Phase 8): Sharpe Ratio >1.2 im Backtest, >0.8 in Paper
- [ ] Max Drawdown im Paper: <15%
- [ ] Alpha Decay Detection (Phase 3): Keine Strategie im "DECAY" Status
- [ ] Backtest (Phase 2): Alle aktiven Strategien validiert auf 2+ Jahre Daten

**Echtgeld-Rollout:**
- Start: 500-1000€ (nicht mehr) — Verhalten in echten Märkten validieren
- Behavioral Check: Slippage, Spread, TR-Ausführungszeiten
- Erst bei stabil >3 Monate: Scale-up

---

## Technologie-Stack (Aufbaureihenfolge)

```
Phase 1: numpy, pandas          → pip install numpy pandas
Phase 2: yfinance, pandas       → pip install yfinance (schon vorhanden)
Phase 3: numpy                  → aus Phase 1
Phase 4: river                  → pip install river
Phase 5: hmmlearn, numpy        → pip install hmmlearn
Phase 6: scikit-learn, shap     → pip install scikit-learn shap
Phase 7: (keine neue Deps)      → aus Phase 6
Phase 8: stable-baselines3,     → pip install stable-baselines3 gymnasium
         gymnasium, torch
Phase 9: (deployment only)
```

---

## Timeline

| Phase | Wann | Trades nötig | Dauer |
|-------|------|-------------|-------|
| 1 Feature Tracking | April 2026 | 0 (sofort) | 2 Wochen |
| 2 Backtest Engine | April-Mai 2026 | 0 (historical) | 4 Wochen |
| 3 Alpha Decay | Mai 2026 | 20+ | 1 Woche |
| 4 Online Learning (River) | Mai-Juni 2026 | 30+ | 2 Wochen |
| 5 Regime Detection | Juni 2026 | 0 (historical) | 2 Wochen |
| 6 Feature Importance | Juli-August 2026 | 150-200 | 4 Wochen |
| 7 Strategy DNA | Sept 2026 | 200+ | 2 Wochen |
| 8 Reinforcement Learning | Q1 2027 | 10k+ simuliert | 2-3 Monate |
| 9 Real Money | Q2-Q3 2027 | — | ongoing |

---

## Was "übertrieben" war (und warum es das NICHT ist)

Ich hatte diese als "übertrieben" bezeichnet:
- RL (Phase 8) — übertrieben für *jetzt*. Nicht für Jahr 2.
- Feature Importance/SHAP — übertrieben ohne Daten. Ab 150+ Trades: der wichtigste Teil.
- Backtesting — für Retail-Trader "overkill". Für ein System das Echtgeld handeln soll: Pflicht.

**Kurz:** Nichts auf dieser Liste ist wirklich übertrieben. Es ist der Standard bei jedem ernsthaften System. Der Unterschied ist nur: Reihenfolge. Phase 1 baut das Fundament für alles andere.

---

## Nächster Schritt

**Sofort umsetzbar:** Phase 1 (Feature Tracking)
- `pip install numpy pandas` → läuft auf unserem System
- `feature_collector.py` bauen → 1-2h Arbeit
- DB-Migration → 30 Minuten
- Sofort: jeder neue Trade wird mit Marktdaten angereichert

**Freigabe Victor:** Soll ich Phase 1 heute implementieren?
