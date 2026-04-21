# State Snapshot — Zuletzt aktualisiert: 2026-04-20 22:45
*Auto-generiert durch daily_learning_cycle.py [7/7]*

## Cash
**Verfügbares Cash:** 13,787€

## Offene Positionen (2)
| Ticker | Strategie | Entry | Stop | Target | Conviction | Datum |
|--------|-----------|-------|------|--------|------------|-------|
| MUV2.DE | PS_MUV2 | 545.00€ | 523.00€ | 616.00€ | 6 | 2026-04-04 |
| TTE.PA | PS1 | 77.56€ | 72.83€ | 91.75€ | 6 | 2026-04-02 |

## Letzte 5 geschlossene Trades
| Ticker | Strategie | Entry | Exit | PnL | Datum |
|--------|-----------|-------|------|-----|-------|
| SIE.DE | PS17 | 204.70€ | 242.55€ | +185€ | 2026-04-20 |
| ASML.AS | STANDALONE | 1139.20€ | 1245.00€ | +464€ | 2026-04-20 |
| BMW.DE | PS18 | 79.24€ | 83.50€ | +108€ | 2026-04-20 |
| CCJ | PS2 | 121.62€ | 103.28€ | -221€ | 2026-04-20 |
| RHM.DE | PS11 | 1409.50€ | 1452.20€ | +60€ | 2026-04-11 |

## Aktive Strategien (36)
- PS1
- PS2
- PS3
- PS4
- PS5
- S1
- S2
- S3
- S4
- S5
- S6
- S7
- emerging_themes
- DT1
- DT2
- DT3
- DT4
- _config
- PT
- PS10
- PS11
- PS12
- PS13
- PS14
- PS15
- PS16
- PS17
- PS_STLD
- PS_NVO
- PS_CCJ
- AR-HALB
- AR-AGRA
- PS_LHA
- PS18
- PS19
- PS20


---

## INCIDENT 2026-04-21: Overnight Stop-Disaster (ROLLED BACK)

**6 Trades neutralisiert** (-1802.86 EUR) — alle ausgeloest durch den Pre-Fix Market-Hours/Stale-Price/Pence-Bug am 2026-04-20 23:08 CET:

| Ticker | Strategy | P&L | Bug |
|--------|----------|-----|-----|
| PSX | PT | -170€ | NYSE geschlossen, stale price |
| OXY | PS1 | -77€ | NYSE geschlossen, stale price |
| ORCL | PT | -157€ | NYSE geschlossen, stale price |
| CCJ | PS16 | -127€ | NYSE geschlossen, stale price |
| BP.L | PT | **-1102€** | Pence/EUR-Bug (556p als 556€) |
| AA | PT | -169€ | NYSE geschlossen, stale price |

**Action:** `exit_type='BUG_ROLLBACK_2026-04-21'`, `postmortem_done=2` (excluded from learning).
**Cash-Reset:** 5846.24€ -> 7649.10€ (+1802.86€)
**Audit Trail:** `data/incident_log.json`

**Strategien PT, PS1, PS16 NICHT abgewertet** — diese Trades zaehlen nicht als Strategy-Failures.

