# Paper Trades — Simulierte Trades für Statistik

*System: Albert testet Trading-Thesen ohne echtes Kapital zu riskieren.*
*Entry-Kurse: Montag 17.03.2026 Xetra/NYSE Open (werden bei Marktöffnung aktualisiert)*
*Monitor: alle 15 Min via trading_monitor.py + paper_trade_checker.py*

---

## Aktive Paper Trades

| # | Datum | Aktie | Richtung | Entry | Stop | Ziel 1 | Strategie | Risiko | Status | Was teste ich |
|---|---|---|---|---|---|---|---|---|---|---|
| P001 | 17.03. | Occidental Petroleum (OXY) | LONG | ~50,70€ | 46,50€ | 56,00€ | S1 Öl | 🟡 | ⏳ Offen | Öl-These bei US Large Cap |
| P002 | 17.03. | BAE Systems (BA.L) | LONG | ~26,72€ | 24,80€ | 29,00€ | S2 Rüstung | 🟡 | ⏳ Offen | ATH-Breakout Defense |
| P003 | 17.03. | ASML (ASML) | LONG | ~1178€ | 1120,00€ | 1280,00€ | S6 Tech | 🟡 | ⏳ Offen | ❓ GEGEN meine VIX-Regel (VIX>25) |
| P004 | 17.03. | Barrick Gold (GOLD) | LONG | ~41,56€ | 38,00€ | 48,00€ | S4 Gold | 🟡 | ⏳ Offen | Mean Reversion Gold/Miner Disconnect |
| P005 | 17.03. | Vermilion Energy (VET.TO) | LONG | ~10,32€ | 9,20€ | 12,00€ | S1 Öl | 🟡 | ⏳ Offen | Small Cap Öl EU-Exposure |
| P006 | 17.03. | ProShares Ultra VIX (UVXY) | SHORT | ~45,76€ | 52,00€ | 35,00€ | Macro | 🔴🔴 | ⏳ Offen | VIX-ETPs decayen strukturell |
| P007 | 17.03. | Direxion Semi Bear 3x (SOXS) | SHORT | ~36,14€ | 42,00€ | 28,00€ | S6 Tech | 🔴🔴 | ⏳ Offen | Semis erholen sich → Bear-ETF fällt |
| P008 | 17.03. | Plug Power (PLUG) | LONG | ~1,88€ | 1,40€ | 2,80€ | Spekulation | 🔴🔴 | ⏳ Offen | Wasserstoff-Lotterie, fast penny stock |
| P009 | 17.03. | Frontline PLC (FRO) | LONG | ~26,41€ | 23,00€ | 33,00€ | S1 Öl | 🔴 | ⏳ Offen | Tanker-Lag zu Ölpreis (Disconnect) |
| P010 | 17.03. | Hecla Mining (HL) | LONG | ~17,16€ | 14,80€ | 22,00€ | S4 Silber | 🔴 | ⏳ Offen | Überverkaufter Silber-Miner |
| P011 | 17.03. | Endeavour Silver (EXK) | LONG | ~8,72€ | 7,00€ | 12,00€ | S4 Silber | 🔴 | ⏳ Offen | Silber Micro Cap Hebel |
| P012 | 17.03. | Energy Fuels (UUUU) | LONG | ~16,34€ | 13,50€ | 22,00€ | Uran/SeltErden | 🔴 | ⏳ Offen | Uran + Seltene Erden strategisch |
| P013 | 17.03. | Halliburton (HAL) | LONG | ~29,48€ | 26,50€ | 36,00€ | S1 Öl | 🟡 | ⏳ Offen | Öl-Services Leverage auf WTI |
| P014 | 17.03. | Kratos Defense (KTOS) | LONG | ~76,60€ | 70,00€ | 90,00€ | S2 Rüstung | 🟡 | ⏳ Offen | Drohnen-Boom Konsolidierung |
| P015 | 17.03. | Huntington Ingalls (HII) | LONG | ~363,80€ | 340,00€ | 410,00€ | S2 Rüstung | 🟡 | ⏳ Offen | US Navy / Marine-Aufrüstung |
| P016 | 17.03. | CF Industries (CF) | LONG | ~113,39€ | 100,00€ | 135,00€ | Dünger | 🟡 | ⏳ Offen | Dünger-Momentum hält an |
| P017 | 17.03. | Mosaic Company (MOS) | LONG | ~25,65€ | 22,50€ | 32,00€ | Dünger | 🟡 | ⏳ Offen | Kali-Superzyklus Sanktionen |
| P018 | 17.03. | Pan American Silver (PAAS) | LONG | ~49,11€ | 43,00€ | 60,00€ | S4 Silber | 🟡 | ⏳ Offen | Silber Mid Cap Comeback |
| P019 | 17.03. | MP Materials (MP) | LONG | ~50,07€ | 43,00€ | 65,00€ | SelteneErden | 🟡 | ⏳ Offen | Einzige US Seltene-Erden-Mine |
| P020 | 17.03. | Enphase Energy (ENPH) | SHORT | ~38,57€ | 44,00€ | 30,00€ | Solar | 🟡 | ⏳ Offen | Solar intern schwach trotz ETF-Stärke |
| P021 | 17.03. | Cleveland-Cliffs (CLF) | LONG | ~7,40€ | 6,00€ | 10,00€ | Stahl | 🟡 | ⏳ Offen | Stahl Contrarian + Trump-Zölle |
| P022 | 17.03. | Airbus (AIR.DE) | LONG | TBD Mo Open | 158,00€ | 192,00€ | S2 Rüstung | 🟢 | ⏳ Offen | Rüstung + Aviation EU |
| P023 | 17.03. | Hensoldt (HAG.DE) | LONG | TBD Mo Open | 40,00€ | 55,00€ | S2 Rüstung | 🟢 | ⏳ Offen | Radar DE, weniger überkauft als RHM |
| P024 | 17.03. | Schlumberger/SLB (SLB) | SHORT | ~39,14€ | 44,00€ | 30,00€ | S1 Öl | 🟡 | ⏳ Offen | Öl-Services Disconnect (fällt trotz WTI↑) |
| P025 | 17.03. | DHT Holdings (DHT) | LONG | ~14,75€ | 12,50€ | 20,00€ | S1 Öl | 🔴 | ⏳ Offen | Günstigster Tanker, positivste Basis |

---

## Abgeschlossene Paper Trades

| # | Datum | Aktie | Entry | Exit | P&L | ✅/❌ | Dauer | Lektion |
|---|---|---|---|---|---|---|---|---|
| — | — | Noch keine abgeschlossenen Paper Trades | — | — | — | — | — | — |

---

## Paper-Trade Statistik

- **Gesamt:** 25 Trades eröffnet | ✅ 0 (0%) | ❌ 0 (0%)
- **Offene Positionen:** 25
- **Avg Win:** — | **Avg Loss:** — | **CRV realisiert:** —
- **Nach Risiko-Level:** 🔴🔴 3 Trades | 🔴 5 Trades | 🟡 14 Trades | 🟢 2 Trades + 1 Spekulation
- **Nach Richtung:** LONG 21 | SHORT 4

---

## Kombinations-Statistik (Echt + Paper)

*Echte Trades: 3 abgeschlossen (33% Win-Rate)*
*Paper Trades: 0 abgeschlossen*
*Gesamt: 3 abgeschlossen — zu wenig für valide Statistik*
*Ziel: 50 abgeschlossene Trades (Mix echt + paper)*

---

## Thesen im Test

### S1 Iran/Öl (7 Paper Trades: P001, P005, P009, P013, P024, P025 + OXY)
Kernfrage: Profitiert alles was mit Öl zu tun hat gleichermaßen?
Hypothese: Produzenten (DR0, EQNR) > Services (HAL, SLB) > Tanker (FRO, DHT) in Reaktionszeit

### S2 Rüstung (4 Trades: P002, P014, P015, P022, P023)
Kernfrage: US Defense vs. EU Defense — wer läuft besser?
Hypothese: EU (BAE, Airbus, Hensoldt) hat mehr Nachholbedarf als US (bereits hoch)

### S4 Silber/Gold (4 Trades: P010, P011, P018, P004)
Kernfrage: Kleine Miner vs. große Miner vs. Metall direkt
Hypothese: Metall steigt → Miner profitieren 2-3× (Hebel-Effekt)

### VIX-Regel Test (P003 ASML Long)
Kernfrage: Ist "kein Tech-Kauf bei VIX>25" eine valide Regel?
Hypothese: ASML wird in den nächsten 2 Wochen fallen → Regel bestätigt

### Decay-Trades (P006 UVXY Short, P007 SOXS Short)
Kernfrage: Können Leveraged/Inverse ETPs geshortet werden für strukturellen Edge?
Hypothese: Ja — aber Timing muss stimmen, Stop muss HART sein

---

## Regeln für Paper Trades

1. Stop wird behandelt als wäre es echter Stop → automatisch als ❌ geschlossen wenn gerissen
2. Ziel 1 erreicht → 50% "verkauft" (Gewinn realisiert), Rest läuft bis Ziel 2 oder Stop
3. Harter Exit nach max. Dauer — kein "ach, noch eine Woche"
4. Bei Waffenstillstands-News → Öl-Trades sofort prüfen
5. Lektionen nach jedem geschlossenen Trade eintragen

*Erstellt: 15.03.2026 21:32 | Monitoring: trading_monitor.py + paper_trade_checker.py*
