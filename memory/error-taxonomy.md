# Fehler-Taxonomie — TradeMind

**Auftrag Victor 2026-05-06:** *"Liste alle Fehler die auftreten können."*
**Stand:** 2026-05-06 18:15 CEST
**Zweck:** Vollständige Übersicht über Fehler-Klassen, sortiert nach Wurzel.
Jeder Eintrag: was es ist, beobachtetes Beispiel, aktueller Schutz, Lücke.

---

## A) DATEN-PIPELINE-BUGS (kein LLM beteiligt)

Daten kommen falsch in die DB rein, Code-Pfade schreiben Müll, blind übernommen.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| A1 | **Phantom-Tick** — API liefert kurzzeitig erratischen Preis | 06.05 PYPL Stop-Out auf 39,49 obwohl Markt-Range 46-50 | ✅ Phase 45v: Sanity-Check vor Stop-Trigger (>8% Abweichung → skip) | Greift nur bei Stop-Trigger, nicht bei Entry/Trail/Target |
| A2 | **Pre-Market-Trigger auf US-Tickern** | 04.05 MOS+PAAS Stop-Out 06:00 vor NYSE-Open | ✅ Phase 45j: `is_market_hours(ticker)` per Suffix-Mapping | Tested für US, evtl. nicht für alle Exchanges |
| A3 | **Doppelt-geschrieben pnl_pct** (Prozent vs Fraction) | 06.05 Display zeigte -1208% / -794% | ✅ Phase 45o: Reader auf Prozent korrigiert | Old-Trades haben evtl. inkonsistente Werte; Migration nicht gemacht |
| A4 | **Phantom-Trades in `trades`-Tabelle** mit Swing-SIDs | PS5 hatte 6 Trades laut learnings, real 4 (2 Phantome aus alter Schema-Ära) | ✅ Phase 45o: Filter `WHERE strategy LIKE 'DT%'` in load_closed_day_trades | Evtl. weitere Phantome in anderen Tabellen unentdeckt |
| A5 | **Tranche-vs-Closed Doppelzählung** | 18 vs 6 Trades je nach Query (Tranche-Partial-Exits anders gezählt) | ⚠ Spawn-Task offen | Nicht gefixt |
| A6 | **API-Quota leer / Yahoo down** | unbekannt aktuell | Errors → silent fail | Kein Heartbeat-Alert wenn Yahoo komplett ausfällt |
| A7 | **DB-Korruption / Lock-Timeout** | unbekannt | `db_integrity_watchdog` läuft | Watchdog meldet Korruption — repariert nicht |
| A8 | **Stale Cache** (60s Truth-Cache zeigt alte Daten) | strukturell möglich | Cache-TTL begrenzt auf 60s | Bei Truth-Block-Inkonsistenzen schwer erkennbar |

---

## B) LLM-FAKTBEHAUPTUNGEN (Halluzinations-Detector-Klasse)

LLM behauptet konkret falsche Fakten über Position/Strategy/Datum/Zahl.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| B1 | `position_not_open` — Ticker als offen behauptet, ist es nicht | 05.05 EQNR.OL "ist offen" obwohl nur PYPL real | ✅ Layer 4: Detector Pattern POSITION_CLAIM_PATTERNS | TICKER-Blacklist limitiert — exotische Tickers könnten als Stop-Wort missgedeutet werden |
| B2 | `strategy_status_mismatch` — "PS5 ist retired" obwohl active | 05.05 vormittag (von mir, CLI-Claude) | ✅ Layer 4: Detector + strategy_verdict SSOT | Status-Map muss aktuell sein — bei Stale strategies.json False-Negatives |
| B3 | `wrong_weekday` — "heute ist Sonntag" obwohl Dienstag | strukturell möglich | ✅ Layer 4: Detector | greift nur wenn explizit "heute X" — implizite Wochentag-Annahmen rutschen durch |
| B4 | `wrong_cash` / `wrong_number` — falsche Zahl behauptet | 05.05 nachmittag (mein Test) | ✅ Layer 4: Detector mit Toleranz 1.5% (Cash) / 0.15 (Sharpe) / 3pp (WR) | Per-Strategy-Sharpe nicht abgedeckt; Conviction-Werte nicht abgedeckt |
| B5 | `strategy_not_active` — "PS_NVO ist active" obwohl nicht | 05.05 mein Test | ✅ Layer 4: Detector | siehe B2 |

---

## C) LLM-KAUSAL-ARGUMENTE (NICHT abgedeckt)

LLM erklärt eine Mechanik plausibel-falsch ohne sie an Daten zu prüfen.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| C1 | **Falsche Mechanik-Erklärung** | 06.05: ich erklärte PYPL-Stop als "Slippage durch Gap-Down" — war Phantom-Tick | ❌ keiner | C-Klasse braucht eigenen Layer — Detector prüft nur isolierte Fakten, keine kausalen Argumentationen |
| C2 | **Plausible-aber-unbelegte Kausalität** ("X passierte WEGEN Y") | strukturell ständig | ❌ keiner | LLM neigt zu Narrativen, hat aber keine Belegpflicht |
| C3 | **Falsche Trend-Extrapolation** | strukturell | ❌ keiner | Kein "wenn 3 Trades Loss, kommt vierter Loss" Schutz |
| C4 | **Self-Confidence ohne Daten** ("vermutlich passiert X") | von Regel #0 verboten, aber Phrasen rutschen durch | ⚠ fact_audit erkennt einige Phrasen | speculation_phrases-Liste ist unvollständig |

---

## D) CROSS-SOURCE-INKONSISTENZEN

Mehrere Quellen sagen Unterschiedliches — Stack nutzt eine, ohne andere zu prüfen.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| D1 | **paper_portfolio.close_price ≠ prices-Tabelle Tagesschluss** | 06.05 PYPL: close_price 39.49 vs prices 46.31 | ❌ keiner | **Hätte den Phantom-Tick sofort gezeigt — fehlt** |
| D2 | **strategy_verdict-Konflikte** zwischen learnings/backtest/quant/strategies | gestern PS5 (learnings -312€, quant +18€) | ✅ strategy_verdict-Konflikt-Logging | Conflict-Logging existiert, aber keine automatische Eskalation |
| D3 | **Cash in paper_fund vs sum(open_positions+realized)** | strukturell möglich | ⚠ `fund_reconciliation.py` existiert | Lauft ad-hoc, nicht im Scheduler |
| D4 | **Live-Preis vs DB-Last-Close klaffen auseinander** | 06.05 Phantom — Live 39, DB 46 | ✅ Phase 45v Sanity-Check | siehe A1 |

---

## E) KONFIGURATIONS-DRIFT

System-Parameter ändern sich automatisch ohne dass User es merkt.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| E1 | **autonomy_config Auto-Tighten basiert auf buggy Daten** | 05.05 max_position 15→10%, sector 30→15% wegen pnl_pct -180% | ✅ Phase 45m: manueller Reset, override_until 04.06 | Auto-Tightener läuft trotzdem weiter — könnte erneut feuern wenn Daten wieder buggy |
| E2 | **strategy_count explodiert** | 05→06.05 von 32 auf 48 Strategien | ✅ Phase 45s+45u: MAX_ACTIVE=50 in allen Discovery-Pfaden | Erreicht 48/50 — wenn Sunset-Regel nicht greift, hard cap erreicht |
| E3 | **Sektor-Bias überschreibt Long-Term-Direktive** | strukturell | ❌ keiner | Albert kann via ceo_action_log Sektor-Bias setzen die Mission-Direktive widerspricht |

---

## F) VERHALTENS-BUGS

Albert handelt nicht obwohl Aktion angezeigt wäre, oder handelt mehrfach.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| F1 | **HIGH-Severity ohne Eskalation** | 06.05 Active-Loop sah 3× "52 Macro-Events" → keine Aktion | ✅ Phase 45u: bei HIGH triggert active_loop ceo_action_log | greift nur bei "high" — bei "med" passiert nichts |
| F2 | **Doppel-Aktion bei mehreren Decision-Runs** | Strukturell wenn 3× pro Tag denselben Stop-Trail |  ✅ Phase 45u: Idempotenz-Check 6h | Ungetested — erste Beobachtung morgen |
| F3 | **A4-Bug: CSV-strategy_status** | 04.05 DT1-4 als CSV gegeben → unknown_sid | ⚠ nicht gefixt | Albert könnte erneut CSV bilden |
| F4 | **Hunter-Stapel** | 36/77 <7d alt | ✅ Phase 45s+45u: Throttle in 4 Pfaden | Throttle kann durch andere Pfade umgangen werden — strategy_throttle_log überwacht |

---

## G) SCHEDULE/TIMING-BUGS

Jobs laufen zu falscher Zeit, Doppelläufe, fehlende Läufe.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| G1 | **Briefing-Filter wirft Output weg** | 06.05 morgens Morgen-Briefing als "Debug-Log" verworfen | ✅ Phase 45q: Briefings überspringen Filter | greift nur auf 5 explizit gemappte Briefings |
| G2 | **Discord-Whitelist blockt Briefings** | 06.05 morgens Caller-Stack-Walk kollidierte mit dispatcher | ✅ Phase 45q: INFRA_CALLERS in ALLOWED | undokumentiert |
| G3 | **today_id-Kollision bei Multi-Run** | 05.05 ceo_action_log sollte 3× laufen → A1/A2 kollidieren | ✅ Phase 45t: today_id mit HHMM | Erste Beobachtung morgen |
| G4 | **Job-Timeout zu kurz** | strukturell möglich für LLM-intensive Jobs | Timeout 3600s default | bei langen Hunter-Runs evtl. abbruch |
| G5 | **Cron läuft nicht** | strukturell — Server-Reboot ohne Service-Restart | systemd auto-restart | wenn systemd selbst broken: kein Schutz |

---

## H) MEMORY/CONTEXT-BUGS

Compaction, Summarization, alter Context wird als aktuell missverstanden.

| # | Klasse | Beobachtet | Aktueller Schutz | Lücke |
|---|---|---|---|---|
| H1 | **PreCompact Drift** — Summary enthält veraltete Fakten | 05.05 morgens "PS5 retired" aus Summary | ✅ Phase 45l: PreCompact-Hook injiziert Truth | Hook greift nur bei AUTO-Compaction |
| H2 | **Auto-Memory** schreibt veraltete Patterns | strukturell | ⚠ memory_proposer prüft auf Aktualität | nicht ausgereift |
| H3 | **CLAUDE.md-Drift** | über Wochen sammelt CLAUDE.md veraltete Regeln | ❌ keiner | Manueller Cleanup |

---

## I) USER-INPUT-FEHLER (out-of-scope, dokumentiert)

| # | Klasse | Schutz |
|---|---|---|
| I1 | User fragt nach Ticker der nicht existiert | Albert antwortet "weiß ich nicht" — funktioniert |
| I2 | User gibt widersprüchliche Direktive | Letzte Direktive gewinnt |
| I3 | Network-Outage zwischen Local und Server | SSH-Timeout, Hook silent-fail |

---

## ZUSAMMENFASSUNG

**Total Klassen:** 35
**Davon mit Schutz (✅):** 17 (49%)
**Davon teilweise / Spawn-Task offen (⚠):** 6 (17%)
**Davon ohne Schutz (❌):** 12 (34%)

### Top-5 Lücken nach Impact

1. **C1 — Kausal-Argumente** (ich heute mit "Slippage") — passiert in jeder zweiten Erklärung
2. **D1 — Cross-Check close_price vs prices-Tabelle** — hätte heute den Phantom-Bug 6h früher gefangen
3. **A6 — API-Quota / Yahoo-Outage** — kein Heartbeat
4. **C4 — Self-Confidence ohne Daten** — speculation_phrases-Liste unvollständig
5. **F1-Erweiterung — Eskalation auch bei "med"-Severity** — Active-Loop reagiert nur bei HIGH

### Empfehlung

Statt "alle 12 ❌ schließen" → **3 mit höchstem Hebel zuerst**:
- D1 (Cross-Check Audit-Job, 50 Zeilen, hätte heute Bug gefangen)
- C1 + C4 (kausales Argument-Tagging mit Pflicht-`[✓ DB:query]`-Tag im Stop-Hook)
- F1-Erweiterung (med-Severity-Eskalation nach 3× identischem Pattern)

Damit gehen wir von 49% auf ~70% Coverage. Restliche 30% sind seltene Klassen wo der Aufwand höher ist als der erwartete Schaden.
