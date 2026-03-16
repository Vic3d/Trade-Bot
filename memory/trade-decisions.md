# Trade Decisions — Entscheidungslog

Jede relevante Trading-Entscheidung wird hier festgehalten:
- **Was** wurde entschieden (Kauf, Verkauf, Halten, Stop setzen)
- **Warum** (Begründung + Datenlage zum Zeitpunkt)
- **Ergebnis** (wird nachträglich eingetragen)

Ziel: Victor kann nachvollziehen ob Albert richtig lag und warum.

---

## Format

```
### YYYY-MM-DD — [Aktie] — [Aktion]
**Kurs zum Zeitpunkt:** XX,XX €
**Entscheidung:** [Kaufen / Verkaufen / Halten / Stop anpassen / Watchlist]
**Begründung:**
- Punkt 1
- Punkt 2
**Risiko:** [was könnte schiefgehen]
**Ergebnis:** [wird nachgetragen — Datum, Kurs, P&L, Lektion]
```

---

## Entscheidungen

### 2026-03-11 — Rheinmetall AG (RHM.DE) — Verkauf / Stop ausgelöst
**Kurs zum Zeitpunkt:** ~1.563 €
**Entry war:** 1.635 €
**Entscheidung:** Position geschlossen (Stop ausgelöst)
**Begründung:**
- Stop bei ~1.580 € mental gesetzt (nicht in TR eingetragen — Fehler!)
- Markt drehte schnell, kein real gesetzter Stop → Ausführung zu spät
- Verlust –4,4%
**Risiko damals:** Kurs fällt unter Unterstützung bei 1.580 €
**Ergebnis:** Stop ausgelöst, –4,4%. Wichtige Lektion: Stops IMMER real in TR setzen.
**Lektion eingetragen:** memory/trading-lessons.md ✅

---

### 2026-03-11 — Nvidia (NVDA) — Halten
**Kurs zum Zeitpunkt:** ~158,89 €
**Entry:** 167,88 €
**Entscheidung:** Halten bis Earnings 27.05.2026
**Begründung:**
- Langfristiger AI-Infrastruktur-Trend intakt
- Earnings-Catalyst erwartet Q2 2026
- Kein Stop gesetzt — bewusste Langfrist-Position
**Risiko:** Marktbreite Korrektur durch Geopolitik (Iran, VIX-Spike)
**Ergebnis:** [offen]

---

### 2026-03-11 — Microsoft (MSFT) — Halten
**Kurs zum Zeitpunkt:** ~348,92 €
**Entry:** 351,85 €
**Entscheidung:** Halten, Stop 338 €
**Begründung:**
- Azure Cloud-Wachstum stabil
- KI-Integration (Copilot) noch nicht eingepreist
- Stop real gesetzt: 338 €
**Risiko:** Geopolitischer Risk-off drückt Tech
**Ergebnis:** [offen]

---

### 2026-03-11 — Palantir Technologies (PLTR) — Halten mit engem Stop
**Kurs zum Zeitpunkt:** ~129,97 €
**Entry:** 132,11 €
**Entscheidung:** Halten, Stop 127 € (⚠️ eng!)
**Begründung:**
- Government-Verträge stabil
- Stop bei 127 € = 3,8% vom Entry — sehr eng
- Bewusst eng wegen hoher Bewertung
**Risiko:** Stop wird schnell ausgelöst bei Volatilität
**Ergebnis:** [offen]

---

### 2026-03-11 — Equinor ASA (EQNR) — Halten / Buy-back läuft
**Kurs zum Zeitpunkt:** ~28,03 €
**Entry:** 27,04 €
**Entscheidung:** Halten, Stop 25 € real
**Begründung:**
- Q1 Buy-back läuft → Kursunterstützung
- Ölpreis stabil
- Dividende attraktiv
**Risiko:** Ölpreisverfall, Hormuz-Eskalation könnte paradoxerweise EQNR auch treffen
**Ergebnis:** [offen] — Kharg Island Bombing 14.03.2026 könnte Ölpreis spike auslösen

---

### 2026-03-11 — Bayer AG (BAYN.DE) — Halten
**Kurs zum Zeitpunkt:** ~39,51 €
**Entry:** 39,95 €
**Entscheidung:** Halten, Stop 38 € real
**Begründung:**
- Glyphosat-Rechtsrisiken noch nicht vollständig eingepreist
- Pharma-Pipeline als Gegengewicht
- Stop 38 € gibt etwas Luft
**Risiko:** Neue Klagewellen, regulatorische Entscheidungen
**Ergebnis:** [offen]

---

### 2026-03-11 — Rio Tinto (RIO.L) — Stop setzen (Versäumnis dokumentiert)
**Kurs zum Zeitpunkt:** ~78,98 €
**Entry:** 76,92 €
**Entscheidung:** Stop bei 73 € in TR setzen (⚠️ war noch nicht gesetzt!)
**Begründung:**
- +2,7% im Plus
- Kein Stop → volles Downside-Risiko
- Empfehlung: sofort 73 € in TR eintragen
**Risiko:** Ohne Stop: unbegrenzter Verlust
**Ergebnis:** [offen — Stop gesetzt?]

---

### 2026-03-14 — Equinor ASA (EQNR) — Beobachtung / Kharg Island
**Kurs zum Zeitpunkt:** unbekannt (Wochenende, Markt zu)
**Entscheidung:** Beobachten, kein Handeln bis Marktöffnung Mo
**Begründung:**
- Trump bestätigt Bombardierung Kharg Island (Irans Haupt-Ölexport-Terminal)
- Kurzsristig bullisch für Öl + EQNR
- Aber: extreme Volatilität möglich, Wochenend-Gap-Risiko
- US Navy Eskort-Gerücht: NICHT bestätigt (nur Truppenverlegung bestätigt laut BBC)
**Risiko:** Gap-down wenn Eskalation übertrieben war | Gap-up wenn Hormuz-Schließung droht
**Ergebnis:** [offen — Xetra Mo 09:00 prüfen]

### 2026-03-15 18:00 — Microsoft (MSFT) — Stop-Warnung
**Kurs:** 340,50€ | **Entry:** 351,85€ | **P&L:** -3.2%
**Alert:** Stop-Warnung | **Stop:** 338,00€
**Strategie:** S3
**Kontext:** VIX: 26.4 | WTI: $91.20 | Conviction: 45/100 [Schwaches Signal — Vorsicht]


### 2026-03-16 08:01 — Microsoft (MSFT) — Stop-Warnung
**Kurs:** 345,94€ | **Entry:** 351,85€ | **P&L:** -1.7%
**Alert:** Stop-Warnung | **Stop:** 338,00€
**Strategie:** S3
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 20/100 [Schwaches Signal — Vorsicht]


### 2026-03-16 08:01 — Equinor ASA (EQNR) — Trailing-Signal
**Kurs:** 30,43€ | **Entry:** 27,04€ | **P&L:** +12.5%
**Alert:** Trailing-Signal | **Stop:** 28,50€
**Strategie:** S1
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 100/100 [Starkes Signal]


### 2026-03-16 08:01 — Equinor ASA (EQNR) — Trailing-Signal
**Kurs:** 30,43€ | **Entry:** 27,04€ | **P&L:** +12.5%
**Alert:** Trailing-Signal | **Stop:** 28,50€
**Strategie:** S1
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 100/100 [Starkes Signal]


### 2026-03-16 08:01 — Invesco Solar Energy ETF (A2QQ9R) — Target-Reached
**Kurs:** 48,43€ | **Entry:** 22,40€ | **P&L:** +116.2%
**Alert:** Target-Reached | **Stop:** —
**Strategie:** S1/S6
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 60/100 [Moderates Signal]


### 2026-03-16 08:01 — Invesco Solar Energy ETF (A2QQ9R) — Trailing-Signal
**Kurs:** 48,43€ | **Entry:** 22,40€ | **P&L:** +116.2%
**Alert:** Trailing-Signal | **Stop:** —
**Strategie:** S1/S6
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 60/100 [Moderates Signal]


### 2026-03-16 08:01 — Invesco Solar Energy ETF (A2QQ9R) — Trailing-Signal
**Kurs:** 48,43€ | **Entry:** 22,40€ | **P&L:** +116.2%
**Alert:** Trailing-Signal | **Stop:** —
**Strategie:** S1/S6
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 60/100 [Moderates Signal]


### 2026-03-16 08:01 — VanEck Oil Services ETF (A3D42Y) — Trailing-Signal
**Kurs:** 324,58€ | **Entry:** 27,90€ | **P&L:** +1063.4%
**Alert:** Trailing-Signal | **Stop:** 24,00€
**Strategie:** S1
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 80/100 [Starkes Signal]


### 2026-03-16 08:01 — VanEck Oil Services ETF (A3D42Y) — Trailing-Signal
**Kurs:** 324,58€ | **Entry:** 27,90€ | **P&L:** +1063.4%
**Alert:** Trailing-Signal | **Stop:** 24,00€
**Strategie:** S1
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 80/100 [Starkes Signal]


### 2026-03-16 08:01 — L&G Cyber Security ETF (A14WU5) — Trailing-Signal
**Kurs:** 56,98€ | **Entry:** 28,80€ | **P&L:** +97.8%
**Alert:** Trailing-Signal | **Stop:** 25,95€
**Strategie:** S3
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 80/100 [Starkes Signal]


### 2026-03-16 08:01 — L&G Cyber Security ETF (A14WU5) — Trailing-Signal
**Kurs:** 56,98€ | **Entry:** 28,80€ | **P&L:** +97.8%
**Alert:** Trailing-Signal | **Stop:** 25,95€
**Strategie:** S3
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 80/100 [Starkes Signal]


### 2026-03-16 08:01 — iShares Biotech ETF (A2DWAW) — Trailing-Signal
**Kurs:** 144,75€ | **Entry:** 7,00€ | **P&L:** +1967.9%
**Alert:** Trailing-Signal | **Stop:** 6,30€
**Strategie:** S7
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 60/100 [Moderates Signal]


### 2026-03-16 08:01 — iShares Biotech ETF (A2DWAW) — Trailing-Signal
**Kurs:** 144,75€ | **Entry:** 7,00€ | **P&L:** +1967.9%
**Alert:** Trailing-Signal | **Stop:** 6,30€
**Strategie:** S7
**Kontext:** VIX: 27.2 | WTI: $99.33 | Conviction: 60/100 [Moderates Signal]


### 2026-03-16 15:00 — Rheinmetall AG (RHM.DE) — Trailing-Signal
**Kurs:** 1649,00€ | **Entry:** 1570,00€ | **P&L:** +5.0%
**Alert:** Trailing-Signal | **Stop:** 1520,00€
**Strategie:** S2
**Kontext:** VIX: 24.4 | WTI: $94.18 | Conviction: 90/100 [Starkes Signal]


---

*Dieses Log wird bei jeder relevanten Entscheidung aktualisiert.*
*Offene Positionen ("Ergebnis: offen") werden nachgetragen sobald die Position geschlossen wird.*
