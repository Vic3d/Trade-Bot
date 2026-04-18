# TradeMind — Lernarchitektur
*Stand: 13.03.2026*

## Das Kernproblem beim Lernen

Eine Vorhersage kann auf 4 Arten enden:

| | Richtig | Falsch |
|---|---|---|
| **Aus dem richtigen Grund** | ✅ Echtes Signal | 🟡 Pech — Thesis war gut |
| **Aus dem falschen Grund** | ⚠️ Glück — gefährlich | ❌ Doppelt schlecht |

Das System muss zwischen ✅ und ⚠️ unterscheiden können.
Nur ✅ ist echter Lernfortschritt.

---

## Was jetzt in der DB gespeichert wird

### events (NewsWire)
- Jede Headline mit Strategie-Tag, direction, score
- price_at_event, price_4h_later, price_1d_later
- **outcome** (1=Richtung bestätigt, 0=nicht)

### trades (Trade Journal)
- Jeder Trade mit Entry, Stop, Strategie, Conviction Score
- Verknüpft mit den NewsWire-Events die das Setup ausgelöst haben
- Exit + P&L + outcome (win/loss/stopped)
- rule_violation: wurde eine Regel gebrochen?

### recommendations (Empfehlungs-Log)
- Jede Empfehlung mit expliziter Begründung
- **invalidation**: Was würde die These widerlegen? (PFLICHT)
- **outcome_reasoning**: Warum war es richtig/falsch (wichtigste Lern-Spalte)
- **causal_confirmed**: War die Kausalität bestätigt — nicht nur der Preis?
- **beat_benchmark**: Hat die Empfehlung SPY geschlagen?

### macro_context
- VIX, DXY, Brent alle 30 Min
- Regime: green/yellow/orange/red
- Kontext für jeden Trade und jede Empfehlung

---

## Der Lern-Loop

```
1. NewsWire erfasst Headlines (kontinuierlich)
          ↓
2. Analyst Cron klassifiziert (alle 30 Min, Haiku)
   → schreibt in newswire-analysis.md
          ↓
3. Albert bewertet auf Nachfrage oder bei High-Conviction
   → loggt Empfehlung in recommendations-Tabelle
   → mit Begründung + Invalidierungs-Bedingung
          ↓
4. Price Tracker füllt Outcome-Daten (alle 30 Min)
   → outcome nach 4h und 24h
   → VIX-Kontext gespeichert
          ↓
5. Weekly Review (Sonntag 20:00, Sonnet)
   → Liest alle Empfehlungen + Trades der Woche
   → Bewertet: Glück oder Können?
   → Schreibt outcome_reasoning in DB
   → Aktualisiert weekly-review.md
          ↓
6. Quarterly: strategien.md wird datengetrieben überarbeitet
   → Welche Keywords sind echtes Signal?
   → Welche Strategien schlagen Buy-and-Hold?
   → Neue Regeln entstehen aus Daten, nicht Intuition
```

---

## Die drei Qualitätsfragen

**Frage 1: Schlagen wir Buy-and-Hold?**
→ Jede Empfehlung wird gegen SPY verglichen (beat_benchmark)
→ Wenn nein: Was ist der Grund aktiv zu traden?

**Frage 2: Verbessert sich die Trefferquote?**
→ Monat 1: Baseline messen
→ Monat 3: Hat sich die Accuracy verbessert?
→ Wenn nicht: Was ändern wir?

**Frage 3: Können wir Glück von Können trennen?**
→ causal_confirmed = 1: Thesis wurde durch Ereignisse bestätigt
→ causal_confirmed = 0: Preis stieg aber NICHT wegen unserer Begründung
→ Nur causal_confirmed=1 Trades zählen für Strategie-Validierung

---

## Was das System NICHT kann (bewusste Grenzen)

1. **Makro-Shifts automatisch erkennen**: Wenn sich das gesamte Markt-Regime ändert
   (z.B. Iran-Krieg endet → S1 komplett invalidiert), braucht es Sonnet-Urteil.

2. **Qualitative Begründungen generieren**: "Warum war diese Empfehlung gut?"
   muss Sonnet beurteilen — nicht automatisierbar.

3. **Emotionale Faktoren**: Revenge Trades, FOMO, Overconfidence
   → Erkennbar nur wenn rule_violation konsequent geloggt wird.

4. **Schwarze Schwäne**: Ereignisse die keine historischen Muster haben.
   Der Algorithmus hat keine Meinung zu etwas das noch nie passiert ist.

---

## Dateipfade

| Datei | Inhalt |
|---|---|
| memory/newswire.db | SQLite: events, trades, recommendations, macro_context |
| memory/newswire-analysis.md | Haiku-Analysen (alle 30 Min) |
| memory/weekly-review.md | Sonnet-Review (Sonntag) |
| memory/tradingtool-lernplan.md | Phasen 1-4 Roadmap |
| memory/strategien.md | Aktive Strategien (manuell, wird quarterly datengetrieben) |
| scripts/newswire.py | Daemon (News-Erfassung) |
| scripts/newswire_analyst.py | Tier-2 Keyword-Filter |
| scripts/newswire_price_tracker.py | Preis + VIX + Outcome |
| scripts/trade_logger.py | Trade Journal + Conviction Score |
