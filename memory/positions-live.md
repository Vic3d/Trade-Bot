# Positions Live — Einzige Wahrheitsquelle für aktuelle Positionen

> **PFLICHT:** Nach jeder Stop-Änderung, jedem Kauf/Verkauf sofort hier updaten.
> **Sync:** Albert updated immer GLEICHZEITIG diese Datei + trading_config.json
> Format: immer in EUR. Letzter Update-Zeitstempel pflegen.

**Zuletzt aktualisiert:** 2026-03-21 09:25 CET

---

## 🟢 Aktive Positionen

| Name (Ticker) | Entry | Stop (REAL in TR) | Letzter Kurs | P&L | Notiz |
|---|---|---|---|---|---|
| Palantir (PLTR) | 132,11€ | 127,00€ | 130,18€ | -1,5% | HALTEN |
| Equinor ASA (EQNR) | 27,04€ | 34,50€ | 35,68€ | +30% | Stop nachgezogen 20.03. 16:00 CET |
| VanEck Oil Services ETF (A3D42Y) | 27,91€ | 24,00€ | 27,09€ | -2,9% | Öl-These |
| iShares Biotech ETF (A2DWAW) | 7,00€ | 6,30€ | 7,04€ | +0,5% | — |

---

## ✅ Geschlossene Positionen (letzte 30 Tage)

| Name (Ticker) | Entry | Exit | P&L | Datum | Notiz |
|---|---|---|---|---|---|
| Bayer AG (BAYN.DE) | 39,95€ | 37,48€ | -6,2% | 20.03.2026 | Stop ausgelöst + Slippage |
| L&G Cyber Security ETF (A14WU5) | 28,80€ | ~25,95€ | ~-10% | 20.03.2026 | Stop ausgelöst |
| Nvidia (NVDA) | 167,88€ | ~154,56€ | -7,9% | 19.03.2026 | Manuell geschlossen, kein Stop gesetzt |
| Microsoft (MSFT) | 351,85€ | ~338,00€ | -4,0% | 19.03.2026 | Stop 338€ ausgelöst |
| Rio Tinto (RIO.L) | 76,92€ | ~73,00€ | -5,1% | 19.03.2026 | Stop 73€ ausgelöst, danach Watchlist |
| Rheinmetall AG (RHM.DE) T2 | 1.570€ | 1.605€ | +2,2% | 16.03.2026 | Manuell |
| Rheinmetall AG (RHM.DE) T1 | 1.635€ | ~1.563€ | -4,4% | 11.03.2026 | Stop |
| Deutsche Rohstoff AG (DR0.DE) T2 | 82,15€ | ~79,00€ | -3,8% | 10.03.2026 | Stop |
| Deutsche Rohstoff AG (DR0.DE) T1 | 76,35€ | ~77,00€ | +0,85% | 10.03.2026 | Stop |
| Invesco Solar ETF (A2QQ9R) | — | — | — | — | Phantom — nie wirklich gekauft |

---

## 📋 Update-Protokoll

| Datum | Was | Alt | Neu |
|---|---|---|---|
| 20.03.2026 16:00 | EQNR Stop nachgezogen | 33,00€ | 34,50€ |
| 20.03.2026 19:30 | BAYN.DE geschlossen | aktiv | Exit 37,48€ (-6,2%) |
| 20.03.2026 19:34 | A14WU5 geschlossen | aktiv | Exit ~25,95€ (~-10%) |
| 19.03.2026 16:31 | NVDA geschlossen | aktiv | Exit ~154,56€ (-7,9%) |
| 19.03.2026 | MSFT Stop ausgelöst | aktiv | Exit ~338€ (-4,0%) |
| 19.03.2026 | RIO.L Stop ausgelöst | aktiv | Exit ~73€ (-5,1%) |
| 21.03.2026 09:25 | Datei initialisiert + bereinigt | — | Albert |

---

## ⚡ Sync-Regeln (PFLICHT)

Wenn Victor eine Stop-Änderung oder einen Trade mitteilt:
1. Diese Datei updaten (Tabelle + Update-Protokoll)
2. **Gleichzeitig** `trading_config.json` updaten (positions Array)
3. Kein Agent liest für live Daten aus `projekt-trading.md` — veraltet
4. `state-snapshot.md` = Monitor-Output, kann 15 Min veraltet sein — nicht als Wahrheitsquelle nutzen
