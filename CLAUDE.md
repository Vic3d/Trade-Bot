# TradeMind — Projekt-Übersicht für Claude Sessions
**Letzte Aktualisierung:** 2026-04-12
**WICHTIG: Diese Datei als erstes lesen. Nicht neu bauen was bereits existiert.**

---

## Was ist das hier?

TradeMind ist ein **autonomer Paper-Trading-Bot** den Victor und Albert (Claude) gemeinsam betreiben.
Albert agiert als AI-CEO: er scannt Nachrichten, bewertet Thesen, führt Trades aus, lernt aus Ergebnissen und reportiert täglich per Discord.

**Broker:** Trade Republic (Paper Fund = 25.000€ Startkapital, Preise immer in EUR)
**Server:** Hetzner VPS 178.104.152.135 | `/opt/trademind` | Branch: `feature/accelerate-trading`
**Local Worktree:** `C:\Users\victo\Trade-Bot\.claude\worktrees\trusting-shannon\`

---

## Kern-Philosophie (von Victor festgelegt)

1. **Deep Dive vor jedem Trade** — Keine Aktie kaufen ohne vollständigen 6-Schritt Deep Dive
2. **Thesen-basiert** — Erst Thesis, dann Trade. Nie Momentum-Chasing.
3. **Keine permanenten Blacklists** — Strategien/Aktien werden durch Deep Dive dynamisch bewertet, nicht statisch geblockt
4. **Max 2-3 neue Positionen pro Woche** — Qualität über Quantität
5. **Stop-Loss ist heilig** — Kein "Hoffnung statt Stop"
6. **Alles updaten = deploy** — Victor sagt "Alles updaten" → Claude committed, pushed, deployed via SSH

---

## Bereits implementierte Features — NICHT neu bauen

### Deep Dive System ✅ (seit 28.03.2026)
- **Protokoll:** `memory/deepdive-protokoll.md` — 6 Schritte + Leiche im Keller (8 Fragen) + Trading-Verdict
- **Discord-Command:** "Deep Dive TICKER" → `_handle_deep_dive()` in `scripts/discord_chat.py`
- **Verdikts-Speicherung:** `data/deep_dive_verdicts.json` (KAUFEN / WARTEN / NICHT_KAUFEN)
- **Pre-Trade-Gate:** Guard 0c2 in `scripts/execution/paper_trade_engine.py` — blockiert autonome Entries ohne aktuelles KAUFEN-Verdict

### Entry Gate ✅ (seit ~29.03.2026)
- **Datei:** `scripts/entry_gate.py`
- **Gates:** Quellen-Qualität (Tier 1/2/3), Regime-Kompatibilität, VIX-Sanity, Strategy-Lock
- **Neu (12.04.2026):** Block 4b Politisches Risiko, Strategy-Permanent-Block (DT1-5, AR-AGRA, AR-HALB)

### Conviction Scorer ✅ (v3)
- **Datei:** `scripts/intelligence/conviction_scorer.py`
- **4 Faktoren:** Thesis Strength (35pt) + Technical Alignment (30pt) + Risk/Reward (20pt) + Market Context (15pt)
- **Entry-Threshold:** 45 Punkte minimum
- **Falling Knife Block:** Preis < EMA50 UND 3M-Trend < -10% → BLOCKED

### Trailing Stop / Tranche-System ✅ (v2)
- **Datei:** `scripts/paper_exit_manager.py`
- **Logik:** Tranche 1 (+5% → 1/3 raus), Tranche 2 (+10% → 1/3 raus), Tranche 3 (ATR-Trailing)
- **Tabelle:** `trade_tranches` in SQLite (wird bei Start automatisch erstellt)
- **Hard Stops:** Stop-Loss, Thesis INVALIDATED, Max-Hold-Time, Circuit Breaker -8%

### Learning Loop ✅
- **Datei:** `scripts/daily_learning_cycle.py` — läuft täglich 22:00 CET
- **Recommendation:** P&L-gewichtet (nicht nur Win-Rate!) — seit 12.04.2026 fix
  - SUSPEND wenn WR < 30% ODER (WR < 45% UND PnL < -200€ mit 15+ Trades)
  - REDUCE wenn WR < 50% und PnL negativ
  - ELEVATE nur wenn WR > 60% UND PnL positiv
- **Strategy Scores:** `data/trading_learnings.json`
- **State Snapshot:** `memory/state-snapshot.md` (tägl. auto-regeneriert als Schritt [7/7])

### Discord-Bot (Albert) ✅
- **Datei:** `scripts/discord_chat.py`
- **Polling:** Alle 30s Victors DM-Kanal
- **Commands:** "Deep Dive TICKER", "Stopp STRATEGY_ID", beliebige Fragen
- **Model:** claude-opus-4-5
- **Channel:** 1492225799062032484 | Victor User ID: 452053147620343808

### Scheduler Daemon ✅ (Phase 8 — kostenoptimiert, kein LLM-Overhead)
- **Datei:** `scripts/scheduler_daemon.py`
- **Service:** `trademind-scheduler` (systemd, läuft als `trademind` user)
- **Wichtige Jobs:** Live Data Refresh (5x tägl.), Overnight Collector (00/02/04/06h), Morning Brief (08:30), Thesis Monitor (alle 30min 09-21h), Daily Learning (22:45), Backtest (So+Mi)

### Paper Trade Engine Guards ✅ (Stand 12.04.2026)
Reihenfolge der Guards in `execute_paper_entry()`:
- 0a: **Morgen-Block** 06-11h CET (0% Win-Rate historisch) — für autonome Entries
- 0b: Stop < Entry Pflicht
- 0c: CRV minimum 2:1
- 0c2: **Deep Dive Verdict Gate** — braucht KAUFEN-Verdict < 14 Tage
- 0: CEO Directive (BEARISH = nur Thesis-Plays)
- 0d: Deep Dive Pre-Trade (Falling Knife + 40% unter 52W-Hoch)
- 2b: **Wöchentliches Trade-Limit** max 3/Woche
- 6b: Position < 15% vom Fund
- 6c: Cash-Reserve > 10% nach Trade

---

## Strategie-Typen

| Code | Typ | Edge | Haltezeit | Stop | Ziel |
|------|-----|------|-----------|------|------|
| PS_* | Thesis Play | Makro-These | 7-30 Tage | 5-8% | +10-20% |
| PT | Thesis Swing | Makro-These | 7-30 Tage | 5-8% | +10-20% |
| PM | Momentum Swing | Technisch + Katalysator | 2-7 Tage | 3-5% | +5-10% |
| DT1-9 | Day Trade | **PAUSED** — alle suspended | intraday | — | — |
| AR-* | Auto-Rotation | **GEBLOCKT** | — | — | — |

---

## Trading-Regeln (kurz)

| Regel | Wert | Durchgesetzt in |
|-------|------|-----------------|
| Entry-Fenster | 17-22h CET (51% WR) | `autonomous_scanner.py` + `paper_trade_engine.py` |
| Position-Größe | max 1.500€ | `paper_trade_engine.py` Guard 6b |
| Trades/Woche | max 3 | `paper_trade_engine.py` Guard 2b |
| Cash-Reserve | min 10% | `paper_trade_engine.py` Guard 6c |
| Stop-Loss | -8% hard | `paper_exit_manager.py` |
| CRV | min 2:1 | `paper_trade_engine.py` Guard 0c |
| Deep Dive | vor jedem Trade | `paper_trade_engine.py` Guard 0c2 |
| Falling Knife | Preis < EMA50 + 3M < -10% | `conviction_scorer.py` + Guard 0d |
| Morgen-Block | 06-11h | `paper_trade_engine.py` Guard 0a |
| Blocked Strategien | DT1-5, AR-AGRA, AR-HALB | `entry_gate.py` Gate 0 |

---

## Key Files — Was wo steht

```
data/
├── trading.db              ← Haupt-Datenbank (Trades, Preise, Makro, News)
├── strategies.json         ← Alle Thesen/Strategien mit Config + Genesis
├── trading_learnings.json  ← Strategy Scores, Win-Rates, Recommendations
├── deep_dive_verdicts.json ← Deep Dive Verdicts pro Ticker (neu 12.04.2026)
├── ceo_directive.json      ← Markt-Bias (BULLISH/NEUTRAL/BEARISH/HALT)
└── proposals.json          ← Ausstehende Trade-Vorschläge

memory/
├── deepdive-protokoll.md   ← 6-Schritt Deep Dive (PFLICHT lesen!)
├── albert-accuracy.md      ← Strategy Performance Report (tägl. aktualisiert)
├── state-snapshot.md       ← Aktueller Portfolio-Status
├── paper-strategien.md     ← Trade-Vor-Checkliste, Strategie-Framework
├── paper-trading-workflow.md ← 6-Phasen-Workflow
├── strategien.md           ← PS1-PS11, S1-S11 vollständig dokumentiert
├── trademind-masterplan.md ← Langzeitstrategie
└── projekt-trading.md      ← Architektur-Dokumentation (45KB)

scripts/
├── entry_gate.py                       ← Gate-System (vor jedem Trade)
├── discord_chat.py                     ← Albert Discord-Bot + Deep Dive
├── scheduler_daemon.py                 ← 24/7 Cron-Ersatz
├── daily_learning_cycle.py             ← Feedback Loop tägl. 22:00
├── paper_learning_engine.py            ← Strategy Score Berechnung
├── paper_exit_manager.py               ← Exits + Trailing Stops
├── overnight_collector.py              ← Nacht-News-Collector
├── execution/
│   ├── paper_trade_engine.py           ← Trade-Ausführung (alle Guards)
│   └── autonomous_scanner.py          ← Tier A/B/C Scanner
├── intelligence/
│   ├── conviction_scorer.py            ← 4-Faktor Scoring
│   └── thesis_discovery.py            ← Auto-Thesis aus News
└── core/
    ├── thesis_engine.py                ← Thesis-Lifecycle + Kill-Trigger
    └── live_data.py                    ← Alle Preise IMMER in EUR
```

---

## Deployment

```bash
# Lokal → Server (alles in einem):
bash deploy/deploy.sh

# Manuell:
git push origin claude/trusting-shannon
ssh root@178.104.152.135
  cd /opt/trademind
  git merge origin/claude/trusting-shannon --no-edit -X theirs
  systemctl restart trademind-scheduler

# Logs prüfen:
tail -f /opt/trademind/data/scheduler.log

# Portfolio auf Server prüfen:
# (Python-Script nach /tmp/ kopieren und ausführen — kein Inline-Python wegen Quotes)
```

---

## Dinge die NICHT getan werden sollen

- ❌ AR-AGRA, AR-HALB, DT1-DT5 aktivieren — permanent blockiert
- ❌ Aktien pauschal auf Blackliste setzen (dynamischer Deep Dive statt Blacklist)
- ❌ Trades ohne Deep Dive Verdict setzen (für autonome Entries)
- ❌ `strategies.json` auf Server blind überschreiben (hat Live-State)
- ❌ `data/` und `memory/` Dateien als `root` ändern ohne `chown trademind:trademind`
- ❌ Den Trailing Stop Tranche-Mechanismus umbauen — er ist bewusst so designed
- ❌ Morgen-Entries (06-11h) für autonome Strategien erlauben

---

## Performance-Snapshot (Stand 09.04.2026)

| | |
|---|---|
| Cash | 28.297€ |
| Startkapital | 25.000€ |
| Gesamt-P&L | +13.2% |
| Win-Rate | 41% (Paper, alle Trades) |
| Beste Strategie | S1 (100% WR, +2.320€) |
| Worst Single Trade | PS_NVO (-843€, NVO nach Trump-Preisdeal) |
| Trailing Stop WR | 75% (mit Trail) vs. 38% (ohne) |

**Lektion aus NVO:** Block 4b (Politisches Risiko) ist Pflicht — Trump-Deals mit Pharma sind reale Gefahr.
**Lektion aus RHM.DE:** Falling Knife ist Falling Knife, auch wenn 52W-Hoch verlockend aussieht.
