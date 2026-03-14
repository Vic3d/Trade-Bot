# Projekt: AG (First Majestic Silver) - Umkehrkerze-Detektor

**Status:** 🟢 AKTIV  
**Erstellt:** 2026-03-13 20:05 UTC  
**Position:** Keine (Watch-only)

## Zweck
Automatische Erkennung von Umkehrkerzen-Mustern in AG (First Majestic Silver Corp) auf 5-Minuten-Basis.
- **Pattern 1:** HAMMER — Long Lower Wick (>2x Body), Close in oberer 60% Range
- **Pattern 2:** BULLISH ENGULFING — Aktuelle Kerze umfasst vorherige, bullische Tendenz
- **Pattern 3:** CLOSE_NEAR_HIGH — Close nahe Range-High, starker Bodyanteil

## Alert-Parameter
```
Entry:  Current Close
Stop:   $22.00
Target: $25-28
```

## Daten-Quelle
- Yahoo Finance API (`/v8/finance/chart/{ticker}`)
- Interval: 5min, Range: 1 day (letzte 2 Kerzen)
- Aktueller Kurs: $22.56 (2026-03-13 20:05 UTC)

## Cron-Job
- **ID:** b69b6a48-a71c-4c65-a9c7-402f2f3e2ae6
- **Delivery:** Discord → Victor DM (452053147620343808)
- **Fehlerbehandlung:** KEIN_SIGNAL bei <0.01 Range oder keine Pattern-Match

## Technische Notes
- Range-Filter: `k2['h'] - k2['l'] < 0.01` → SKIP
- Body Calculation: `abs(k2['c'] - k2['o'])`
- Lower Wick: min(open, close) - low

## Status-Log
- **2026-03-13 20:05:** Detektor aktiviert
- **2026-03-13 20:35:** HAMMER erkannt @ $22.56 — Alert gesendet
