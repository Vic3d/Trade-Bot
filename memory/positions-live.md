# Positions Live — Einzige Wahrheitsquelle für aktuelle Positionen

> **PFLICHT:** Nach jeder Stop-Änderung, jedem Kauf/Verkauf sofort hier updaten.
> **Sync:** Albert updated immer GLEICHZEITIG diese Datei + trading_config.json
> Format: immer in EUR. Letzter Update-Zeitstempel pflegen.

**Zuletzt aktualisiert:** 2026-03-29 09:26 CET (NVO + LLY Paper Watchlist hinzugefügt)

---

## 🟢 Aktive Positionen

| Name (Ticker) | Entry | Stop (REAL in TR) | Letzter Kurs | P&L | Notiz |
|---|---|---|---|---|---|
| Palantir (PLTR) | 132.11€ | 127.00€ | 124.29€ | -5.9% | Stop nachgezogen 09.03. |
| VanEck Oil Services ETF (A3D42Y) | 27.90€ | 24.00€ | 29.02€ | +4.0% |  |
| iShares Biotech ETF (A2DWAW) | 7.00€ | 6.30€ | 7.01€ | +0.2% |  |
| Equinor ASA (EQNR) | 33.58€ | 34.20€ | — | — | Iran-These: Trump nicht glaubwürdig, Krieg nicht vorbei. US ADR Accumulation +65% Vol-Trend. |

---

## 👁️ Paper Watchlist — Tranchensetups (noch kein Kauf, Trigger ausstehend)

> Diese Positionen sind vorbereitet. Sobald Trigger feuert → Tranche 1 ausführen, hier updaten.
> Korrelation NVO ↔ LLY täglich beobachten: wenn LLY steigt aber NVO fällt = Marktanteilsverlust bestätigt → NVO-Konfidenz runter.

| Name (Ticker) | Typ | Kurs (Stand 29.03.) | Trigger Tranche 1 | Stop | Ziel 1 | Ziel 2 | Status |
|---|---|---|---|---|---|---|---|
| Novo Nordisk (NVO / NOVO-B.CO) | VALUE / Turnaround | ~33€ ($36) | Q1'26 Earnings EPS-Rückgang ≤15% ODER pos. Pipeline-News | ~25€ ($27) | ~48€ ($52) | ~65€ ($70) | 🟡 WARTEN |
| Eli Lilly (LLY) | GROWTH / Konkurrenz-Monitor | ~812€ ($878) | Rückfall auf ~$720 (PE ~31x auf $22.95 EPS) | ~$650 | ~$950 | ~$1.100 | 🔵 MONITOR |

### NVO — Tranchenplan (4× 25%)
| Tranche | Trigger | Entry-Kurs ca. |
|---|---|---|
| T1 (25%) | Q1'26 Earnings: EPS-Rückgang ≤15% YoY | ~$36–38 |
| T2 (25%) | Positive Pipeline-News (Amycretin/Petrelintide Phase 2+) | ~$38–42 |
| T3 (25%) | Wochenschluss >$45 mit Volumen (MA-Rückeroberung) | ~$45 |
| T4 (25%) | EPS-Wachstum 2027 bestätigt | ~$50+ |

**Invalidierung NVO gesamt:** EPS 2026 fällt >30% | LLY Retatrutide >30% Gewichtsverlust Phase 3 | NVO unter $27

### LLY — Korrelations-Beobachtung
- **Kein aktiver Trade** — zu teuer bei PE 38x
- **Zweck:** Wenn LLY steigt während NVO fällt → Marktanteilsverlust strukturell → NVO-These schwächer
- **Zweck:** Wenn beide fallen → Sektor-Repricing (IRA/Preisdruck) → NVO-These neutral bleibt
- **Trade-Schwelle:** LLY unter $720 + EPS-Wachstum ≥30% → neuer Deep Dive

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
