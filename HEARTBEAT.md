# HEARTBEAT.md

## Trading-Checks (rotierend, 2-4x täglich)

- [ ] Aktive Positionen: Stops gefährdet? Trailing Stop fällig? (projekt-trading.md)
- [ ] Strategie-Check: News vs. Thesen in strategien.md — Statuswechsel? → strategy-changelog.md updaten!
- [ ] Watchlist: Neue Signale bei RHM.DE, RIO.L, BHP.L, BAYN.DE?
- [ ] Iran-Krise: Neue Eskalation auf liveuamap.com? Portfolio-Impact?
- [ ] Offene Prognosen in albert-accuracy.md — bewertbar? Ergebnis nachtragen!

## Projekt-Checks (1x täglich)

- [ ] Memory pflegen: tägliche Notizen in memory/YYYY-MM-DD.md
- [ ] Taskboard DobroTech: `curl -s -H "X-Password: Fichte" http://todo.dobro-work.com:3333/terminbot/api/tasks`

## Offene Einmalige Aufgaben

- [ ] DobroTech Agent-Infrastruktur-Konzept mit Victor besprechen — Details: memory/projekt-dobrotech-agentinfra.md (von Vincent nachts erarbeitet, noch nicht besprochen)
- [ ] TradeMind v2.1.2 Feedback von Victor — Dashboard live testen, Versionsnummer bestätigen, weitere Features freigeben

## AKTUELLE ALERTS (29.03.2026 — 19:00 MEZ)

**TRADING SESSION AKTIV — MASSIVE BUILDS HEUTE:**
- ✅ VIX Hard Block (BEAR-Regime bei VIX 31.1) — Tech geblockt, PS_* + Öl/Gold erlaubt
- ✅ Paper Trade Engine integriert in 15-Min Monitor — Watchlist-Scan automatisch
- ✅ News Dedup + Sentiment Magnitude — wired in newswire_analyst.py
- ✅ Autonomous Scanner live — 3 Tiers, 80+ Ticker, täglich 09:15 Scan
- ✅ STLD T1 Paper Trade eröffnet (ID 34) + NUE Tier A + CLF/DHT Tier C Paper Trades
- ✅ Preisdaten-Sync: alle Watchlist-Ticker in trading.db → Conviction Scorer hat echte Daten

🔴 **KUBA-TANKER:** Anatoly Kolodkin erwartet 29.03 (HEUTE). Keine Victor-Update seit gestern. UK Royal Navy + US SOUTHCOM tracking. Status: **S9 offen**
- 💡 DHT (Tanker) ist gerade +32% — Kuba-Effekt?

🟢 **Iran-These (S1):** HALTEN — Houthis attackieren, Pentagon plant Operationen, Trump deadlines extend. Geopolitik-Prämie intakt.

🟢 **Portfolio Live (Stand ~18:00 MEZ):**
  - PLTR €124.29 (Entry €132.11) | −5.9% | Stop €127 (−2.2% Distanz, VIX 31 eng!)
  - A3D42Y €29.02 (Entry €27.90) | +4.0% | Stop €24
  - A2DWAW €7.01 (Entry €7.00) | +0.2% | Stop €6.30
  - Paper: STLD (ID 34, $171 Entry), NUE, CLF, DHT neu

📋 **30.03 Morgen — STLD Real Trade:**
  - Entry Zone $162–171, STLD momentan $170.97
  - US-Börsenstart 15:30 MEZ → Manual Entry prüfen
  - Stop $155 SOFORT in Trade Republic setzen (WKN 903772)
  - Liberation Day 02.04 — Trump will politischen Win

## Regeln

- Nachts (23:00-08:00) still sein, außer Kritisches
- Nur melden wenn Handlungsbedarf — kein Spam
- Während aktiver Trading-Session: nur Trading-Alerts, kein Projekt-Spam
- Checks in heartbeat-state.json tracken
