# Future-Features Backlog
**Letzte Aktualisierung:** 2026-04-28
**Zweck:** Features die wir gerade nicht brauchen, aber später wertvoll sein könnten. Quelle + warum + wie integrierbar dokumentiert.

---

## Aus Fincept-Terminal (AGPL-3.0, 28k LOC, C++/Qt6/Python)
**Repo:** `git@github.com:Fincept-Corporation/FinceptTerminal.git`
**Local-Cache:** `/tmp/FinceptTerminal/` (nach Clone)

### ✅ ÜBERNOMMEN (Phase 41c)
- **11 Investor-Personas** als JSON → `data/personas/investor_agents.json` + `scripts/ceo_personas.py`
  - Buffett, Graham, Lynch, Munger, Klarman, Marks, Greenblatt, Einhorn, Miller, Eveillard, Whitman
  - Strategy-Mapping: PS_* → Buffett+Marks+Klarman, PT → Lynch+Greenblatt, PM → Einhorn+Miller, S* → Buffett+Munger
  - Cold-Start fallback: Graham+Eveillard

### 🟡 LATER — Hedge-Fund-Agents (Renaissance Technologies Framework)
**Wo im Repo:** `fincept-qt/scripts/agents/hedgeFundAgents/renaissance_technologies_hedge_fund_agent/`
**Wert:** Quant-Trading-Style mit Statistical Arbitrage, Mean Reversion, Pattern Detection
**Wann nützlich:** Wenn wir DT-Strategien wieder aktivieren oder HFT testen wollen
**Aufwand:** ~1 Tag — Adapter wie ceo_personas.py bauen
**Trigger zum Reaktivieren:** Sobald Day-Trading wieder relevant wird

### 🟡 LATER — Geopolitics-Agents (Grand Chessboard + Prisoners-of-Geography)
**Wo im Repo:** `fincept-qt/scripts/agents/GeopoliticsAgents/`
**Wert:** Tiefere geopolitische Analyse als unser aktueller `geo_alert`
- Grand Chessboard: Brzezinski-Framework (Eurasia-Strategie)
- Prisoners of Geography: Marshall-Framework (Geographie als Determinant)
**Wann nützlich:** Bei makro-Krisen wo unser geo_score zu grob ist
**Aufwand:** ~3-4h — JSON-Configs + Integration in directive.json
**Trigger:** Wenn wir öfter politische Risiken falsch einschätzen

### 🟡 LATER — qlib AI Quant Lab (Microsoft OSS)
**Wo im Repo:** `fincept-qt/scripts/ai_quant_lab/qlib_*.py` (14 Module)
- qlib_rl.py — Reinforcement Learning Trading
- qlib_meta_learning.py — Meta-Learning für Strategie-Selection
- qlib_online_learning.py — Online-Adaption (Drift Detection)
- qlib_high_frequency.py — HFT-Models
- qlib_feature_engineering.py — automatische Faktor-Generierung
- qlib_portfolio_opt.py — Mean-Variance Optimization
- qlib_advanced_backtest.py — Walk-Forward + CV
**Wert:** Komplettes ML-Quant-Framework, ergänzt unser `backtest_engine.py`
**Wann nützlich:** Wenn wir ML-basierte Strategien testen wollen
**Aufwand:** ~1-2 Wochen für sauberen Adapter
**Trigger:** Wenn wir 100+ closed Trades haben und ML-Edge suchen
**Achtung:** qlib selbst ist MIT-lizensiert, Fincept-Wrapper aber AGPL — direkt qlib einbinden statt Wrapper

### 🟡 LATER — CFA-Level Analytics
**Wo im Repo:** Diverse C++ Module in `fincept-qt/src/`
- DCF-Models (Discounted Cash Flow Valuation)
- VaR (Value at Risk) — wir haben rudimentär in portfolio_risk.py
- Sharpe / Sortino / Information Ratio
- Derivatives Pricing (Black-Scholes, Binomial)
**Wann nützlich:** Wenn wir Value-Investing-Strategien (langfristig) ergänzen
**Aufwand:** Module sind in C++, Python-Bindings müssten wir selber schreiben
**Trigger:** Wenn wir LEAPS oder Optionen tradern

### 🟡 LATER — 100+ Data-Connectors
**Wo im Repo:** `fincept-qt/src/screens/data_sources/connectors/` (C++)
- DBnomics (Makro-Daten 2000+ Provider)
- Polygon (Realtime US-Equities)
- FRED (Fed Economic Data) — könnte unser overnight_collector ergänzen
- IMF / World Bank — global Macro
- Kraken / HyperLiquid (Crypto-WebSocket)
- AkShare (China-Markets)
**Wann nützlich:** Wenn wir konkrete Daten-Lücken merken (z.B. Asien-Coverage schwach)
**Aufwand:** Pro Connector 2-4h
**Trigger:** Bei Makro-Daten-Bedarf
**Pragmatisch:** FRED-Connector wäre sofort hilfreich für VIX/Yields

### 🔴 NICHT ÜBERNEHMEN
- Qt6-UI / C++20 Frontend → wir sind headless-Bot, kein User sitzt davor
- 16 Broker-Integrations (Zerodha, AngelOne, IBKR…) → wir nutzen TradeRepublic Paper
- Maritime Tracking / Satellite Data → für unsere Swing-Trades irrelevant
- Visual Node-Editor → wir konfigurieren via JSON/Python, kein No-Code

---

## Wie reaktivieren?
Wenn ein "later"-Feature relevant wird:
1. Hier in dieser Datei die "Wann nützlich"-Zeile prüfen
2. Trigger-Condition erfüllt? → Phase-Nummer reservieren
3. Aus `/tmp/FinceptTerminal/` den entsprechenden Pfad clonen
4. Adapter analog zu `ceo_personas.py` bauen
5. Hier "✅ ÜBERNOMMEN" markieren mit Phase-Nummer

---

## Lizenz-Hinweis
Fincept ist **AGPL-3.0** — wenn wir Code (nicht nur JSON-Configs/Prompts) übernehmen,
muss unser Repo entweder auch AGPL bleiben oder die Übernahme als
"separate process / API call" sauber gekapselt sein. Bei JSON-Configs (Prompts)
ist das Risiko niedriger, weil das eher Daten als Code sind.
