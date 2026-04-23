# TradeMind — Datenbank-Schema (trading.db)

**Letzte Aktualisierung:** 2026-04-23 (Sub-7 Cleanup)

---

## Single Source of Truth: `paper_portfolio`

Alle aktiven Trade-Operationen (Entry, Exit, Trailing-Stops, Feature-Snapshots,
Postmortems) laufen ausschließlich über die Tabelle **`paper_portfolio`**.

Diese Tabelle wird geschrieben von:
- `scripts/execution/paper_trade_engine.py` (Entries)
- `scripts/paper_exit_manager.py` (Exits, Trailing-Tranchen)
- `scripts/feature_collector.py` (At-Entry-Feature-Snapshots)
- `scripts/postmortem_runner.py` (Failure-Categories)

Gelesen von:
- `scripts/paper_learning_engine.py` (Strategy-Scores, Recommendations)
- `scripts/feature_importance.py` (K9-Bridge → conviction_weights.json)
- `scripts/daily_digest.py` (Discord-Reports)
- `scripts/risk_dashboard.py` (Phase 21 Exposure-Dashboard)

Begleittabellen:
- `trade_tranches` — partielle Exits via Trailing-Stop-System
- `paper_fund` — Cash-Stand (Single-Row)
- `news_events` — News-Context für Thesen
- `macro_daily` — VIX, SPY u.a. Tages-Indikatoren

---

## ⚠️  LEGACY-ARCHIV: `trades`

Die Tabelle **`trades`** ist historisches Archiv aus der Pre-Paper-Portfolio-Ära
(264 Zeilen, Schema mit 45 Spalten inkl. thesis/lessons/scanner_score/geo_theme).

**Status:** READ-ONLY für neue Features. Keine neuen Reader/Writer hinzufügen.

Verbleibende aktive Schreiber (Sub-7 Audit, 2026-04-23):
- `scripts/core/trade_journal.py` — Sekundär-Journal (über `execution/trade_proposal.py`)
- `scripts/core/trade_import.py` — Manueller CSV/JSON-Import
- `scripts/trade_journal.py` — Top-Level (deprecated, nur via unified_scorer)
- `scripts/position_update.py` — CLI Stop-Update-Tool

Diese 4 Schreiber sollen langfristig auf `paper_portfolio` migriert oder ersatzlos
entfernt werden. Für Sub-7 wurde bewusst **kein Rename** durchgeführt weil die
Schemas zu unterschiedlich sind (45 vs 38 Spalten, viele unique Spalten in
`trades`) und 25+ Reader gebrochen würden.

**Regel:** Wenn du eine Trade-Auswertung baust, frage immer `paper_portfolio` ab,
niemals `trades`. Wenn du historische Daten >2025-12 brauchst, prüfe ob sie in
`paper_portfolio` existieren bevor du auf `trades` ausweichst.

---

## Snapshot-Felder (At-Entry, in `paper_portfolio`)

Seit Sub-7 (2026-04-23) werden folgende Features beim Entry persistiert
(via `feature_collector.save_features()`):

| Spalte | Quelle | Coverage Apr 2026 |
|--------|--------|-------------------|
| `rsi_at_entry` | live_data.compute_rsi | ~95% |
| `volume_ratio` | live_data | ~95% |
| `vix_at_entry` | macro_daily | 100% |
| `atr_pct_at_entry` | live_data | ~95% |
| `ma50_distance` | live_data | ~95% |
| `day_of_week` | entry_date | 100% |
| `hour_of_entry` | entry_date | 100% |
| `sector_momentum` | Sektor-ETF 5d-Return | 96% (Backfill) |
| `spy_5d_return` | macro_daily.SPY | 100% |
| `hmm_regime` | regime_detector | ~80% (Sub-7 Fix) |
| `feature_version` | konstant 1 | 100% |
| `regime_at_entry` | regime_detector.name | ~80% |

Backfill-Tool für historische Lücken: `scripts/backfill_historical_features.py`.

---

## Konsistenz-Checks

```sql
-- 1. paper_portfolio sollte alle aktiven Positionen abbilden
SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN';

-- 2. trade_tranches darf nur paper_portfolio.id referenzieren
SELECT COUNT(*) FROM trade_tranches t
LEFT JOIN paper_portfolio p ON t.portfolio_id = p.id
WHERE p.id IS NULL;

-- 3. trades-Schreiber prüfen (sollte über Zeit auf 0 sinken)
SELECT MAX(entry_date) FROM trades;
```
