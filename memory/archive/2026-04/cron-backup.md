# Cron-Jobs Backup — Stand 2026-03-14

Dieses File enthält eine Übersicht aller aktiven Cron-Jobs.
Bei einem Reset: Jobs müssen manuell neu eingerichtet werden.
SSH-Key neu generieren, dann Victor bitten ihn bei Vic3d/Trade-Bot zu hinterlegen.

---

## Tägliche Jobs (Mo-Fr)

| Zeit | Name | Job-ID |
|------|------|--------|
| 08:00 | Morgen-Briefing | 4b33792f |
| 10:00 | Xetra Opening-Check | 3b0e14ef |
| 11:30 + 14:30 | Strategie-Check | 936265c1 |
| 14:00 + 18:00 | E-Mail Monitor Schutzeichel | 022b7a13 / 80fb2cb4 |
| 16:30 | US Opening-Check | dfb50964 |
| 22:00 | Abend-Report | 933dadfd |
| 23:00 | Tagesabschluss | be60a4c0 |
| 13:00 täglich | Midday Backup → GitHub | f26760c2 |
| 23:00 täglich | Daily Backup → GitHub | 80365b26 |

## Intraday (Mo-Fr, alle X Min)

| Intervall | Name | Job-ID |
|-----------|------|--------|
| alle 5 Min | AG Umkehrkerze-Detektor | b69b6a48 |
| alle 15 Min | Stop-Loss Monitor | de343e15 |
| alle 15 Min | Intraday Alert Monitor (WTI/VIX) | 56f90272 |
| alle 15 Min | Rheinmetall Re-Entry Alert | 5d57b69e |
| alle 15 Min | BHP Watchlist Alert | 6958bdd5 |
| alle 15 Min | Rio Tinto Position Monitor | a17e0905 |
| alle 15 Min | Bayer Position Monitor | c4f6deb6 |
| alle 15 Min | ASML Entry Alert | d2a04d8f |
| alle 15 Min | AG Reuters Deep-Dive | 5a26144c |
| alle 30 Min | NewsWire Analyst | 6411ad19 |
| alle 30 Min | NewsWire Price Tracker | 28b86afa |
| stündlich | Transcript Analyzer | 06e35db7 |

## Wöchentliche Jobs

| Zeit | Name | Job-ID |
|------|------|--------|
| Sa 09:00 | Job-Cleanup Check | cedf9781 |
| Sa 10:00 | Wöchentliche Trading Review | dd5e1b84 |
| Sa 19:00 | Wochenend-News-Sammlung | 2e646754 |
| Fr 17:30 | Portfolio Risk Check | 7d83ecda |
| Fr 19:00 | Korrelationsmatrix | a44ec94c |
| Fr 20:00 | Strategy Learner | 2522722d |
| So 20:00 | Weekly Strategy Review | 8d5cbc51 |
| So 20:00 | NewsWire Learner | d1178f89 |
| So 21:00 | Strategie-Distillation | 2162e2e7 |
| So 22:00 | Wochenstrategie | 44a00dc4 |

## Einmalige Jobs

| Datum | Name | Job-ID |
|-------|------|--------|
| 2026-05-26 | NVDA Earnings Reminder | 9b8aef61 |

---

*Zuletzt aktualisiert: 2026-03-14*
*GitHub Backup: Vic3d/Trade-Bot (SSH: ~/.ssh/id_ed25519_vic3d)*
