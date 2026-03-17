# Paper Fund — Verbesserungsplan

*Stand: 17.03.2026 | Ziel: Vom Hobby-Trader zum systematischen System*

---

## Prio 1: Backtests JETZT laufen lassen (diese Woche)

Jede aktive Strategie durch den Backtester jagen:
- PS1 (Öl): OXY, TTE.PA — bei WTI >$85 + RSI-Entry
- PS2 (Tanker): FRO, DHT — die Lag-These quantifizieren
- PS3 (Defense): KTOS, HII, HAG.DE — Trend-Following-Params
- PS4 (Metalle): HL, PAAS — VIX-korrelierte Entries
- PS5 (Dünger): MOS, CF — Sanktions-Cycle

Unprofitable Strategien sofort streichen oder anpassen.
→ Ergebnis: "PS2 hatte in 2 Jahren 35% Win-Rate → STREICHEN"

## Prio 2: Short-Strategien einführen

Nur Long = blind auf einer Seite. Neue Strategien:
- PS6: VIX-Spike-Reversal — UVXY Short nach VIX >35
- PS7: Sektor-Rotation-Short — Schwächsten Sektor shorten vs. stärksten long
- PS8: Überbewertungs-Short — RSI >80 + Kurs >20% über SMA200

## Prio 3: Regime-Detektor bauen

Script: `regime_detector.py`
```
VIX < 15:  CALM → Trend-Following, aggressive Entries
VIX 15-22: NORMAL → Standard-Strategien
VIX 22-30: ELEVATED → Breitere Stops, defensivere Positionierung
VIX > 30:  PANIC → Nur Hedge-Plays, Gold/VIX, kein neuer Tech
```
Jede Strategie bekommt eine Regime-Kompatibilität.
PS3 (Defense) funktioniert in ELEVATED/PANIC → breiter handeln.
PS4 (Metalle) funktioniert NUR in ELEVATED → sonst Finger weg.

## Prio 4: Korrelations-Tracker

Script: `correlation_tracker.py`
- Berechnet 30-Tage-Korrelation zwischen allen Positionen
- Warnt wenn Portfolio-Korrelation > 0.7 ("Du hast 4 Öl-Positionen")
- Empfiehlt Diversifikation: "Füge unkorrelierten Sektor hinzu"
- Max. 3 Positionen mit Korrelation >0.6 zueinander

## Prio 5: Fundamental-Daten in Screener

Erweitere stock_screener.py um:
- F6: KGV vs. Sektor-Durchschnitt (niedrig = 20, hoch = 0)
- F7: Schuldenquote (niedrig = 20, hoch = 0)
- F8: Nächste Earnings (< 2 Wochen = 0 "zu riskant", > 2 Wochen = 10)
Datenquelle: Yahoo Finance Summary-Seite scrapen

## Prio 6: News-Sentiment-Score

Script: `sentiment_scorer.py`
- Google News RSS für Portfolio-Ticker holen
- Einfaches Keyword-Scoring: "beats expectations" +2, "misses" -2, "war" -1, "contract won" +3
- Output: Sentiment-Score pro Ticker pro Tag
- In Morning-Analysis integrieren: "KTOS Sentiment: +5 (3 positive Headlines)"

## Prio 7: Trade-Replay

Nach jedem geschlossenen Trade: "Was wäre wenn?"
- Hätte ein anderer Stop besser funktioniert?
- Hätte ich früher/später einsteigen sollen?
- Wie sah der Chart am Entry-Tag wirklich aus?
→ Vergleich: Mein Trade vs. Optimaler Trade vs. Random Entry

## Prio 8: Paper → Real Promotion-System

Wenn eine Paper-Strategie:
- 20+ Trades abgeschlossen hat
- Win-Rate > 55%
- Avg CRV > 1,5:1
- Max Drawdown < 15%
→ Empfehlung an Victor: "Diese Strategie ist bereit für echtes Geld"

## Zeitleiste

| Woche | Was |
|---|---|
| 1 (jetzt) | Backtests alle Strategien + Regime-Detektor |
| 2 | Korrelations-Tracker + Short-Strategien definieren |
| 3 | Fundamental-Daten im Screener + Sentiment-Score |
| 4 | Trade-Replay + Paper→Real Promotion |
| Monat 2+ | Alles zusammen → autonome Entscheidungen |
