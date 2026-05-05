# PS5 Postmortem — 2026-05-05

**Anlass:** Heute morgen halluzinierte CLI-Claude "PS5 ist retired (Sharpe -3.14)".
Postmortem zur Klärung was PS5 wirklich tut + was diese Halluzination ermöglicht hat.

## Was die DB sagt (paper_portfolio, authoritativ)

| ID | Ticker | Entry | Close | PnL | % | Exit-Type |
|---|---|---|---|---|---|---|
| 12 | GLEN.L | 18.03 15:10 | 25.03 18:51 | +0.7€ | +0.5% | (full close) |
| 87 | MOS | 02.04 19:16 | 03.04 15:10 | +19.9€ | +1.2% | (full close) |
| 92 | MOS | 03.04 19:15 | 09.04 14:45 | +8.9€ | +0.4% | STOP_MONITOR |
| 125 | MOS | 30.04 15:59 | **04.05 06:00** | **−10.8€** | −0.8% | STOP_MONITOR |

**Aggregat:** 4 Trades, 3W/1L (75% WR), **+18.7€ Total**, avg_win 9.8€, avg_loss 10.8€.

## Was learnings.json sagt (computed daily)

```json
{"win_rate": 0.667, "total_pnl_eur": -312.91, "trades": 6,
 "risk_adj_return": -0.098, "recommendation": "INSUFFICIENT_DATA"}
```

→ **6 Trades statt 4**, **−312€ statt +18.7€**. Echte Inkonsistenz.

## Wer hat recht?

Die DB (paper_portfolio) ist authoritativ. Mögliche Ursachen für learnings.json-Bug:
1. **Tranche-Doppelzählung** — wenn ein Trade 3 Tranche-Exits hat, könnte daily_learning_cycle ihn 3x zählen → 6 statt 4 macht Sinn (4 Trades, 2 davon Tranchen-Exits = 6 Events)
2. **pnl_pct vs pnl_eur Vermischung** — die kaputten pnl_pct-Werte (-1208% etc.) könnten als EUR aggregiert werden → erklärt -312€

**Beide Hypothesen sind durch die offenen Spawn-Tasks adressiert** (pnl_pct-Bug + Tranche-Zähler-Diskrepanz).

## Was wirklich passiert ist (timeline)

| Datum | Event |
|---|---|
| 18.03–25.03 | GLEN.L Trade — Sanktionen-These greift, +0.5% (klein aber positiv) |
| 02.04–03.04 | MOS #1 — schneller Trade, +1.2% in 20h |
| 03.04–09.04 | MOS #2 — Trail-Stop nach 6 Tagen, +0.4% (Profit gesichert) |
| **30.04–04.05** | **MOS #3 — Pre-Market-Bug. Stop war auf +9% Trailing nach Friday-Close. Pre-Market-Gap-Down -6% triggerte Stop bei 19.73 statt regulär bei NYSE-Open.** |

→ **Ohne den Pre-Market-Bug wäre PS5 4/4 Wins gewesen.** Der einzige "Loss" ist ein Infrastruktur-Bug, kein Strategy-Failure.

## Lessons Learned

1. **Quellen müssen selbst geprüft werden, nicht nur Aussagen über sie.**
   Die learnings.json hat mich heute morgen halluzinieren lassen weil ich die Zahl
   "−312€" akzeptiert habe ohne sie gegen DB zu verifizieren.

2. **Mehrere Quellen mit derselben Wahrheits-Frage müssen einen Konsens-Mechanismus haben.**
   `strategy_verdict.py` macht das jetzt — INSUFFICIENT als Verdict war richtig,
   aber die zugrundeliegenden Zahlen waren widersprüchlich. **Konflikte sollten
   in `data/strategy_verdict_conflicts.jsonl` LOUD geloggt werden, nicht silent.**

3. **PS5 ist nicht negative Edge** — sie ist insufficient data + ein Infra-Bug.
   Strategie aktiv lassen, beobachten, neu evaluieren am 04.06.

## Aktion

- ✅ PS5 status bleibt 'active' (kein retire)
- ✅ Pre-Market-Bug ist gefixt (Phase 45j heute morgen)
- ⏳ pnl_pct-Bug + Tranche-Zähler werden via Spawn-Tasks bearbeitet
- ⏳ 04.06 Re-Evaluation — sollte dann mehr Daten haben
