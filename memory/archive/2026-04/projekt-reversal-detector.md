# Projekt: Umkehrkerze-Detektoren (5min Intraday)

## Status
🟡 **In Entwicklung** — Initial Setup, Ticker-Bugs gefunden

## Ziele
- Echtzeit-Umkehrsignale (Hammer, Bullish Engulfing, Close-High)
- 5min Kerzen via Yahoo Finance
- Alert via Discord bei Trigger

## Aktuell Aktive Detektoren

### MAG (First Majestic Silver)
- **Ticker:** MAG (NYSE) / MAG.TO (TSX)
- **Problem:** Code nutzte "AG" — falscher Ticker!
- **Status:** 🔴 DISABLED — Ticker wird repariert
- **Quelle:** Yahoo Finance intraday
- **Alert-Channel:** Victor DM (452053147620343808)

## Fehler / Bugs

### 2026-03-13
- **Ticker-Bug:** Code sagte `ticker='AG'` → Yahoo kennt das nicht
- **Fix:** Zu `ticker='MAG'` ändern
- **Subprocess-Bug:** `subprocess.run()` mit `openclaw message send` — sollte direkt in Job formuliert werden
- **Logik-Bug:** Stops/Targets hardcoded ($22/$25-28) — nicht adaptiv

## Nächste Schritte

1. Ticker zu MAG korrigieren ✓ (hier dokumentiert)
2. Yahoo-Abfrage testen
3. Fallback: Alternative zu yahoo_intraday() für 5min-Daten?
4. Discord-Alert direkt im Python implementieren oder via Cron-Delivery
5. ATR-basierte dynamische Stops/Targets

## Dateipfade

- Cron-Job: `/data/.openclaw/workspace/` (executes via OpenClaw)
- Script: temp in /tmp (garbage-collected)
