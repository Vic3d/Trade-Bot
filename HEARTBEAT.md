# HEARTBEAT.md — Updated 04.04.2026 16:40

## TradeMind Build-Status (Zusammenfassung 04.04.2026)

### ✅ ALLES GEBAUT — System Ready für Montag

| Item | Status | Details |
|------|--------|---------|
| **1. Feature-Daten** | ✅ | 81/92 Trades mit Features (RSI, VIX, HMM, MA50, Volume, ATR) |
| **2. Backtest neue Strategien** | ✅ | PS_Copper, PS_China, PS_AIInfra backtested |
| **3. Advisory Layer** | ✅ | Trade-Entscheidungen erklären: Stärken + Risiken in Discord |
| **4. Preis-Staleness-Check** | ✅ | Guard 0: kein Trade wenn Kurs > 3 Tage alt |
| **5. Portfolio-Exposure** | ✅ | Guard 6: max 30% pro These, 20% pro Sektor |
| **6. News Sentiment** | ✅ | Bearishe News senken Conviction Score |
| **7. Performance Dashboard** | ✅ | `http://localhost:8765` läuft, zeigt P&L/WR/Positionen/Thesen |
| **8. Strukturierte Alerts** | ✅ | `discord_sender.send_alert(priority, title, body)` |
| **Bonus: Strategy Discovery** | ✅ | Sa 14:00 — sucht wöchentlich neue Thesen aus News |
| **Bonus: Scanner Universe** | ✅ | 50 → 62 Ticker (TIER_A 13, TIER_B 31, TIER_C 18) |
| **Bonus: Neue 3 Strategien** | ✅ | PS_Copper (31x News), PS_China (31x), PS_AIInfra (24x+) |

**Win-Rate:** 48% (40/83 closed) — Ziel 55%+ bis real money

---

## Montag 07.04.2026 — Erste echte Tests

### 09:15 CET — Scanner läuft mit vollständigem System
- ✅ market_hours.py: Weekend/Holiday-Check
- ✅ 62 Ticker mit Thesis-Linkage
- ✅ conviction_scorer mit allen 8 Faktoren
- ✅ Features werden beim Entry gesammelt
- ✅ Advisory Layer erklärt alle Trades
- ✅ Exposure Guards prüfen Limits

### 15:30–22:00 — US Börsenöffnung
- Neue Conviction-getriebene Trades erwartet
- Dashboard zeigt Live-P&L
- News-Gate tracked aktive Thesen

---

## Monitoring (täglich bis Win-Rate > 55%)

- [ ] Win-Rate-Tracking: albert-accuracy.md
- [ ] Feature-Qualität: Alle neuen Trades müssen Features haben
- [ ] News-Sentiment: Überprüfe ob bearishe/bullishe News korrekt gescoret sind
- [ ] Portfolio-Exposure: Kein Cluster > 30% pro These

---

## Bekannte Grenzen (Dokumentiert)

1. **RL-Agent:** Braucht 200+ echte Trades mit vollständigen Features bevor brauchbar
2. **HMM-Regime:** 8 States, aber Übergangswahrscheinlichkeiten noch vom Initial-Seeding
3. **ML-Backtest:** Overfitting-Risiko da Training und Test auf gleicher Datenmenge

→ **Lösung:** Erst 50+ echte Trades sammeln mit Features, dann neuer Train-Test-Split

---

## Offene Einstufige Aufgaben

- [ ] Update MEMORY.md mit TradeMind Überblick (nur Main Session!)
- [ ] Backtest-Report reviewen (backtest_results.json)
- [ ] Dashboard im Browser testen (http://localhost:8765)
- [ ] Claude Code Max Auth fertig machen (OAuth noch pending)

---

## Regeln

- **Nachts (23:00–08:00 CET):** Nur kritische Alerts (Stops hit, Regime wechsel)
- **Tagsüber:** Nur Handlungsbedarf melden, kein Spam
- **Während Scanner läuft (09:15–22:00):** Alerts im Discord Channel 1475255728313864413
