# Positions Live — Einzige Wahrheitsquelle für aktuelle Positionen

> **PFLICHT:** Nach jeder Stop-Änderung, jedem Kauf/Verkauf sofort hier updaten.
> **Sync:** Albert updated immer GLEICHZEITIG diese Datei + trading_config.json
> Format: immer in EUR. Letzter Update-Zeitstempel pflegen.

**Zuletzt aktualisiert:** 2026-03-28 11:09 CET (Auto-Sync)

---

## 🟢 Aktive Positionen

| Name (Ticker) | Entry | Stop (REAL in TR) | Letzter Kurs | P&L | Notiz |
|---|---|---|---|---|---|
| Palantir (PLTR) | 132.11€ | 127.00€ | 124.29€ | -5.9% | Stop nachgezogen 09.03. |
| VanEck Oil Services ETF (A3D42Y) | 27.90€ | 24.00€ | 29.02€ | +4.0% |  |
| iShares Biotech ETF (A2DWAW) | 7.00€ | 6.30€ | 7.01€ | +0.2% |  |
| Equinor ASA (EQNR) | 33.58€ | 34.20€ | — | — | Iran-These: Trump nicht glaubwürdig, Krieg nicht vorbei. US ADR Accumulation +65% Vol-Trend. |

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

---

## 📋 Update-Protokoll

| Datum | Was | Alt | Neu |
|

---

## ⚡ Sync-Regeln (PFLICHT) — Single Source of Truth Architektur

```
positions-live.md  ← DU und ALBERT schreiben NUR HIER
       ↓ (automatisch beim Monitor-Start + manuell via sync_positions.py)
trading_config.json  ← Monitor liest hier (immer frisch)
trading.db           ← DB wird synchronisiert (Stops, Status)
portfolio.py         ← Alle Reports/Scripts lesen über diese Klasse
```

**Wenn Victor einen Trade oder Stop meldet:**
1. Albert updated SOFORT diese Datei (positions-live.md) — und NUR diese
2. `python3 scripts/sync_positions.py` propagiert in alle anderen Dateien
3. Der Monitor macht das automatisch alle 15 Min

**Was NICHT mehr getan wird:**
- ❌ Stops direkt in trading_config.json schreiben
- ❌ Stops direkt in trading.db schreiben  
- ❌ Positionsdaten in strategien.md, MEMORY.md oder HEARTBEAT.md tracken
- ❌ Werte aus mehreren Dateien "zusammensuchen"

**Lesezugriff für Scripts:**
- Reports (evening_report.py etc.) → `from portfolio import Portfolio`
- Monitor (trading_monitor.py) → sync läuft beim Start, dann trading_config.json
- Alle anderen → `from portfolio import Portfolio` oder `sync_positions.py` aufrufen
