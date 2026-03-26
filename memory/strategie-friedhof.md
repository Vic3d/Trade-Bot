# Strategie-Friedhof 🪦

> Hier ruhen Strategien die nicht funktioniert haben — mit vollständiger Dokumentation WARUM.
> Jede Beerdigung ist ein Learning. Kein Trade stirbt umsonst.

---

## 🪦 DT3 — "Bollinger Breakout" | Beerdigt: 2026-03-26

**Was war die Idee?**
Kaufe wenn der Kurs das obere Bollinger Band durchbricht (Momentum-Breakout). Verkaufe wenn er zurückfällt.

**Daten:**
- 9 Trades | 1 Win, 8 Losses | WR: 11%
- P&L: **-415€** | Avg Trade: -46€
- Sharpe: **-12.55** | Profit Factor: 0.17
- p-value: 1.000 → **signifikant SCHLECHTER als Zufall**

**Warum hat's nicht funktioniert?**
1. **Bollinger-Breakouts sind kein Edge im aktuellen Regime.** Bei VIX 25-30 sind die Bänder so breit, dass "Breakout" nur Noise ist.
2. **Zu wenige Trades für Momentum-Strategie** — 9 Trades in 2 Wochen ist zu wenig Sample, aber 1 von 9 gewonnen reicht um zu sagen: das ist kein Zufall-Pech, das ist ein schlechtes Signal.
3. **Kein Sektorfilter** — hat blind in alles reingehandelt ohne zu prüfen ob der Sektor überhaupt Momentum hat.

**Was haben wir gelernt?**
- Bollinger Bands allein sind kein Einstiegssignal — sie messen Volatilität, nicht Richtung
- Bei hohem VIX sind technische Breakout-Signale unzuverlässig (zu viel Noise)
- Eine Strategie die nach 9 Trades 11% WR hat, wird nach 100 Trades nicht magisch besser

**Würde ich die Idee nochmal versuchen?**
Nur mit: Sektorfilter + VIX <25 Bedingung + Volumen-Bestätigung. Aber nicht in dieser Form.

---

## 🪦 DT4 — "Volume Monster" | Beerdigt: 2026-03-26

**Was war die Idee?**
Kaufe bei ungewöhnlich hohem Volumen (>2× Durchschnitt) — die Theorie: hohes Volumen = institutionelle Käufer = Kurs steigt weiter.

**Daten:**
- 102 Trades | 44 Wins, 58 Losses | WR: 43%
- P&L: **-725€** | Avg Trade: -7€
- Sharpe: **-4.38** | Profit Factor: 0.80
- p-value: 0.93 → **kein statistischer Edge, nicht besser als Zufall**
- Monte Carlo: Nur 24% Wahrscheinlichkeit profitabel über 100 Trades

**Warum hat's nicht funktioniert?**
1. **Hohes Volumen ≠ Aufwärtsdruck.** Hohes Volumen bei Sell-Offs ist genauso häufig wie bei Rallies. Die Strategie hat nicht unterschieden.
2. **Zu viele Trades** — 102 in 2 Wochen = 7-8 pro Tag. Bei unserer Positionsgröße (€5.000) und TR-Kosten (€8/Roundtrip) fressen die Gebühren den Mini-Edge.
3. **Kein Richtungsfilter** — hat bei hohem Volumen IMMER long gekauft, auch wenn der Markt fiel.
4. **DT4 war die teuerste Strategie:** Geschätzte Execution-Kosten allein: 102 × 8€ = **816€** — mehr als die Trading-Verluste!

**Was haben wir gelernt?**
- Volumen allein ist kein Signal — Richtung + Volumen zusammen könnte funktionieren
- Hohe Trade-Frequenz + kleine Edge = Execution-Kosten fressen alles
- **102 Trades ist statistisch genug** um zu sagen: das funktioniert nicht. Kein "vielleicht wird's besser".
- Eine Strategie mit negativem Expected Value (-7€/Trade) wird NIEMALS profitabel, egal wie lange man wartet

**Würde ich die Idee nochmal versuchen?**
Nur als Filter (Volumen als Bestätigung), nicht als primäres Signal. Und nie wieder mit >2 Trades/Tag.

---

## 🟡 DT1 — "Momentum Scalper" | Auf Bewährung: 2026-03-26

**Nicht beerdigt, aber unter Beobachtung.**

**Daten:**
- 11 Trades | 4 Wins, 7 Losses | WR: 36%
- P&L: **-244€** | Sharpe: -0.30
- p-value: 0.89 → kein Edge nachweisbar

**Warum noch nicht beerdigt?**
- Nur 11 Trades — zu wenig für ein endgültiges Urteil
- Sharpe ist negativ aber nicht katastrophal
- Braucht 20+ Trades für faire Bewertung

**Deadline:** Wenn nach 30 Trades p-value noch >0.20 → beerdigen.

---

## Meta-Learnings aus dem DT-Experiment

### Was wir INSGESAMT aus Intraday-Trading gelernt haben:

1. **Intraday ist für uns strukturell unrentabel.** 132 Intraday-Trades = -1.339€. Die Execution-Kosten (Spread + Slippage + TR-Gebühr) fressen jeden Mini-Edge. Bei €5.000 Positionsgröße braucht ein Trade >0.17% Bewegung NUR um die Kosten zu decken.

2. **Wenige große Swing-Trades schlagen viele kleine Intraday-Trades.** OXY Swing (+341€, +17%, 1 Trade) > DT4 gesamt (-725€, 102 Trades). Der Beweis: Qualität > Quantität.

3. **VIX >25 ist Gift für technische Signale.** Alle DT-Strategien haben bei VIX 25-30 Geld verloren. Die Volatilität macht Stops zu eng und Signale zu unzuverlässig.

4. **102 Trades reichen für ein statistisches Urteil.** Man muss nicht 500 Trades warten um zu wissen dass es nicht funktioniert. Bei p=0.93 nach 102 Trades ist die Sache klar.

5. **Execution-Kosten sind real.** 1.340€ auf 163 Trades. Das war vorher unsichtbar. Jetzt wissen wir's.

---

*"Der beste Trade ist der Trade den du NICHT machst."*
*— Jede Strategie die hier liegt hat das bewiesen.*
*— Albert 🎩, 26.03.2026*
