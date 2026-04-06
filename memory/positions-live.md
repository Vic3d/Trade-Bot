# Positions Live — Einzige Wahrheitsquelle für aktuelle Positionen

> **PFLICHT:** Nach jeder Stop-Änderung, jedem Kauf/Verkauf sofort hier updaten.
> **Sync:** Albert updated immer GLEICHZEITIG diese Datei + trading_config.json
> Format: immer in EUR. Letzter Update-Zeitstempel pflegen.

**Zuletzt aktualisiert:** 2026-04-06 12:10 CET (Auto-Sync vom Monitor)

---

## 🟢 Aktive Positionen

| Name (Ticker) | Entry | Stop (REAL in TR) | Letzter Kurs | P&L | Notiz |
|---|---|---|---|---|---|
| Palantir (PLTR) | 132.11€ | 127.00€ | 128.46€ | -2.8% | Stop nachgezogen 09.03. |
| VanEck Oil Services ETF (A3D42Y) | 27.90€ | 24.00€ | 28.49€ | +2.1% |  |
| iShares Biotech ETF (A2DWAW) | 7.00€ | 6.30€ | 7.36€ | +5.2% |  |

---

## ✅ Geschlossene Positionen (letzte 30 Tage)

| Name (Ticker) | Entry | Exit | P&L | Datum | Notiz |
|---|---|---|---|---|---|
| Nvidia (NVDA) | 167.88€ | 154.56€ | -7.9% | 2026-03-19 | Manuell geschlossen |
| Microsoft (MSFT) | 351.85€ | 338.00€ | -3.9% | 2026-03-19 | Stop 338€ ausgelöst |
| Bayer AG (BAYN.DE) | 39.95€ | 37.48€ | -6.2% | 2026-03-20 | Stop ausgelöst + Slippage |
| Rio Tinto (RIO.L) | 76.92€ | 73.00€ | -5.1% | 2026-03-19 | Stop 73€ ausgelöst |
| Rheinmetall AG (RHM.DE) | 1570.00€ | 1605.00€ | 2.2% | 2026-03-16 | VERKAUFT 16.03. @ ~1605€ (+2,2%) | Watchlist Re-Entry >1626€ |
| Invesco Solar Energy ETF (A2QQ9R) | 22.40€ | — | — | 2026-03-20 | Phantom-Position, nie gekauft |
| L&G Cyber Security ETF (A14WU5) | 28.80€ | 25.95€ | -9.9% | 2026-03-20 | Stop ausgelöst |
| Equinor ASA (EQNR) | 33.58€ | 34.20€ | 1.8% | 2026-04-01 | Stop 34.20€ ausgelöst 01.04.2026 ~11:30 CET. Iran-Deal-Signal (Brent -14.5%). S1-These falsch. |

---

## 📋 Update-Protokoll

| Datum | Was | Alt | Neu |
|

---

## ⚡ Sync-Regeln (PFLICHT)

Wenn Victor eine Stop-Änderung oder einen Trade mitteilt:
1. `trading_config.json` updaten (positions Array) — Monitor liest von hier
2. Diese Datei wird beim nächsten Monitor-Run (alle 15 Min) automatisch aktualisiert
3. Bei dringenden Änderungen: Albert updated beide Dateien sofort manuell
4. `state-snapshot.md` = Monitor-Output mit live Preisen, kann 15 Min veraltet sein
5. `projekt-trading.md` = nur Strategie-Doku — NICHT für live Daten
