#!/usr/bin/env python3
"""
Daily Learning Cycle — Automatischer Lernloop für Albert's Trading System
==========================================================================
Läuft täglich nach Marktschluss (22:00 CET).

Was passiert:
  1. Feedback Loop — Preis-Checks 30min/2h/24h für Overnight Events
  2. Strategy Scores updaten — conviction +/- basierend auf echten Trade-Ergebnissen
  3. Accuracy Report — albert-accuracy.md automatisch updaten
  4. Pattern Detection — welche Setups funktionieren, welche nicht

Usage:
  python3 daily_learning_cycle.py              # Vollständiger Cycle
  python3 daily_learning_cycle.py --quick      # Nur Scores + Accuracy (kein Feedback Loop)
  python3 daily_learning_cycle.py --report     # Nur Accuracy Report ausgeben
"""

import sqlite3
import json
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def _berlin_now() -> datetime:
    return datetime.now(ZoneInfo('Europe/Berlin'))
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
ACCURACY_FILE = WS / 'memory/albert-accuracy.md'
LEARNINGS_FILE = WS / 'data/trading_learnings.json'
DAILY_LOG = WS / f"memory/{datetime.now(ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d')}.md"


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


# ── 1. FEEDBACK LOOP ─────────────────────────────────────────────────────────

def run_alpha_decay() -> list[dict]:
    """Führt Alpha Decay Check aus und gibt Alerts zurück."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from alpha_decay import run_decay_check, format_discord_alert
        results, alerts = run_decay_check()
        print(f"  ✅ Alpha Decay: {len(results)} Strategien | {len(alerts)} Alert(s)")
        return alerts
    except Exception as e:
        print(f"  ⚠️  Alpha Decay Fehler: {e}")
        return []


def run_feedback():
    """Führt Signal-Feedback-Loop aus (Preis-Checks + Kalibrierung)."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from feedback_loop import run_feedback_loop
        report = run_feedback_loop()
        print(f"  ✅ Feedback Loop: {report[:120]}...")
        return report
    except Exception as e:
        print(f"  ⚠️  Feedback Loop Fehler: {e}")
        return None


# ── 2. LEARNING ENGINE ───────────────────────────────────────────────────────

def run_learning():
    """Updatet Strategy Scores + generiert Learnings JSON."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from paper_learning_engine import run_all, close_feedback_loop
        learnings = run_all()
        return learnings
    except Exception as e:
        print(f"  ⚠️  Learning Engine Fehler: {e}")
        return None


def sync_recommendations_to_db(learnings: dict | None) -> dict:
    """P0.4 — Sync Learning-Recommendations in thesis_status DB-Tabelle.

    Vor dieser Funktion: Lernloop schreibt SUSPEND in JSON, DB sagt aber
    weiterhin ACTIVE → autonome Execution liest DB → trade trotzdem.

    Jetzt: SUSPEND/REDUCE → degrade_thesis(); ELEVATE → set ACTIVE.
    """
    if not learnings:
        return {'synced': 0, 'errors': 0, 'skipped': 'no_learnings'}
    scores = learnings.get('strategy_scores', {})
    if not scores:
        return {'synced': 0, 'errors': 0, 'skipped': 'no_scores'}

    synced = 0
    errors = 0
    actions = []
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from core.thesis_engine import degrade_thesis, set_thesis_status
    except Exception as e:
        print(f"  ⚠️  thesis_engine import Fehler: {e}")
        return {'synced': 0, 'errors': 1, 'skipped': 'import_failed'}

    for sid, data in scores.items():
        rec = data.get('recommendation', 'KEEP')
        wr = data.get('win_rate', 0)
        pnl = data.get('total_pnl_eur', 0)
        trades = data.get('trades', 0)
        try:
            if rec == 'SUSPEND':
                reason = f"Learning: WR {wr:.0%} | PnL {pnl:+.0f}€ | {trades} trades → SUSPEND"
                if degrade_thesis(sid, reason):
                    actions.append(f"DEGRADED: {sid} ({reason[:60]})")
                    synced += 1
            elif rec == 'ELEVATE' and trades >= 5:
                reason = f"Learning: WR {wr:.0%} | PnL {pnl:+.0f}€ | {trades} trades → ELEVATE"
                if set_thesis_status(sid, 'ACTIVE', reason):
                    actions.append(f"ACTIVATED: {sid}")
                    synced += 1
            # REDUCE / KEEP / INSUFFICIENT_DATA → kein DB-Sync nötig
        except Exception as e:
            print(f"  ⚠️  sync({sid}) Fehler: {type(e).__name__}: {e}")
            errors += 1

    if actions:
        print(f"  🔄 Learning→DB Sync: {synced} updates")
        for a in actions[:10]:
            print(f"     {a}")
        # K4 — Discord-Notify für SUSPEND/ELEVATE (sonst nur in albert-accuracy.md)
        try:
            from discord_sender import send as _send
            _suspended = [a for a in actions if a.startswith('DEGRADED')]
            _elevated = [a for a in actions if a.startswith('ACTIVATED')]
            lines = []
            if _suspended:
                lines.append(f"🔴 **{len(_suspended)} Strategie(n) SUSPENDED** (Learning):")
                lines.extend(f"  • {a[10:]}" for a in _suspended[:5])
            if _elevated:
                lines.append(f"🟢 **{len(_elevated)} Strategie(n) ELEVATED**:")
                lines.extend(f"  • {a[11:]}" for a in _elevated[:5])
            if lines:
                _send('\n'.join(lines))
        except Exception as _e:
            print(f"  ⚠️  Discord-Notify fail: {_e}")
    return {'synced': synced, 'errors': errors, 'actions': actions}


# ── 3. ACCURACY REPORT ───────────────────────────────────────────────────────

def build_accuracy_report() -> str:
    """
    Generiert aktuellen Accuracy Report und schreibt ihn in albert-accuracy.md.
    Ersetzt manuelles Tracking vollständig.
    """
    conn = get_db()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ─ Portfolio-Übersicht ─
    paper = conn.execute("""
        SELECT
            COUNT(CASE WHEN status='OPEN' THEN 1 END) as open_pos,
            COUNT(CASE WHEN status IN ('WIN','CLOSED','LOSS') THEN 1 END) as closed_pos,
            SUM(CASE WHEN status='OPEN' THEN entry_price * shares ELSE 0 END) as invested,
            SUM(CASE WHEN status IN ('WIN','CLOSED','LOSS') THEN pnl_eur ELSE 0 END) as realized_pnl,
            COUNT(CASE WHEN status='WIN' THEN 1 END) as wins,
            COUNT(CASE WHEN status IN ('CLOSED','LOSS') AND pnl_eur < 0 THEN 1 END) as losses
        FROM paper_portfolio
        WHERE notes NOT LIKE '%DATENFEHLER%'
    """).fetchone()

    total_closed = (paper['closed_pos'] or 0)
    win_rate = (paper['wins'] or 0) / total_closed if total_closed > 0 else 0

    # ─ Strategie-Ranking ─
    strategies = conn.execute("""
        SELECT strategy,
               COUNT(*) as trades,
               SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins,
               SUM(pnl_eur) as total_pnl,
               AVG(pnl_pct) as avg_pct
        FROM paper_portfolio
        WHERE status IN ('WIN','CLOSED','LOSS')
          AND strategy IS NOT NULL
          AND notes NOT LIKE '%DATENFEHLER%'
        GROUP BY strategy
        ORDER BY SUM(pnl_eur) DESC
    """).fetchall()

    # ─ Conviction Changes (aus strategies.json) ─
    conviction_changes = []
    strat_file = WS / 'data/strategies.json'
    if strat_file.exists():
        strats = json.loads(strat_file.read_text(encoding="utf-8"))
        for sid, s in strats.items():
            genesis = s.get('genesis', {})
            history = genesis.get('feedback_history', [])
            for h in history[-3:]:  # Letzte 3 Änderungen
                conviction_changes.append(
                    f"- **{sid}**: {h.get('old_conviction', '?')} → {h.get('new_conviction', '?')} "
                    f"({h.get('date', '?')}) — {h.get('reason', '')[:80]}"
                )

    # ─ Offene Hypothesen ─
    learnings = {}
    if LEARNINGS_FILE.exists():
        learnings = json.loads(LEARNINGS_FILE.read_text(encoding="utf-8"))

    active_rules = learnings.get('active_rules', [])

    # ─ Report bauen ─
    lines = [
        f"# Albert Accuracy & Learning Report",
        f"*Generiert: {now} | Learning System v2.0 (Auto)*",
        "",
        "---",
        "",
        "## 📊 Portfolio-Performance",
        "",
        "| | Paper | Real |",
        "|---|---|---|",
        f"| Offene Positionen | {paper['open_pos'] or 0} | — |",
        f"| Geschlossene Positionen | {total_closed} | — |",
        f"| Realisierte P&L | {paper['realized_pnl'] or 0:+.2f}€ | — |",
        f"| Win-Rate | {win_rate:.0%} ({paper['wins'] or 0}W / {paper['losses'] or 0}L) | — |",
        "",
        "## 🏆 Strategie-Ranking (nach P&L)",
        "",
        "| Strategie | Trades | Win-Rate | Avg P&L% | Total P&L |",
        "|---|---|---|---|---|",
    ]

    for s in strategies:
        wr = (s['wins'] or 0) / (s['trades'] or 1)
        lines.append(
            f"| {s['strategy']} | {s['trades']} | {wr:.0%} | "
            f"{s['avg_pct'] or 0:+.1f}% | {s['total_pnl'] or 0:+.1f}€ |"
        )

    if conviction_changes:
        lines += [
            "",
            "## 🎯 Auto-Conviction-Änderungen",
            "",
        ]
        lines.extend(conviction_changes)

    if active_rules:
        lines += [
            "",
            "## 📋 Aktive Regeln (aus Lernloop)",
            "",
        ]
        for rule in active_rules:
            lines.append(f"- {rule}")

    lines += [
        "",
        "---",
        f"*Nächste Auto-Aktualisierung: täglich 22:00 CET via daily_learning_cycle.py*",
    ]

    report = '\n'.join(lines) + '\n'
    ACCURACY_FILE.write_text(report, encoding='utf-8')
    conn.close()
    return report


# ── 4. DAILY LOG ENTRY ────────────────────────────────────────────────────────

def append_to_daily_log(summary: str):
    """Hängt Learning-Summary an heutiges Daily-Log."""
    entry = f"\n## {_berlin_now().strftime('%H:%M')} — Auto-Learning Cycle\n\n{summary}\n"
    if DAILY_LOG.exists():
        existing = DAILY_LOG.read_text(encoding="utf-8")
        DAILY_LOG.write_text(existing + entry, encoding='utf-8')
    # Wenn kein Daily-Log existiert → nicht anlegen (Tagesabschluss macht das)


# ── CONVICTION WEIGHT RECALIBRATION ────────────────────────────────────────
# ENTFERNT 2026-04-23 (Sub-7 Bug 8): recalculate_conviction_weights() rief
# calculate_conviction(ticker='_HISTORICAL') mit LIVE-Marktdaten auf statt
# at-entry-Snapshots → korrelierte heutige Scores mit alten Trades = Müll
# in conviction_weights.json. Ersetzt durch K9-Bridge in feature_importance.py
# (bridge_to_conviction_weights), die echte at-entry Snapshot-Spalten aus
# paper_portfolio nutzt. Läuft Freitags via [5/7]-Block in run_full().

# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_full():
    print(f"[Daily Learning Cycle] Start — {_berlin_now().strftime('%Y-%m-%d %H:%M')}")

    print("\n[1/7] Alpha Decay Check...")
    decay_alerts = run_alpha_decay()

    print("\n[2/7] Feedback Loop (Signal-Kalibrierung)...")
    feedback_report = run_feedback()

    print("\n[3/7] Learning Engine (Strategy Scores)...")
    learnings = run_learning()

    print("\n[3b/7] Learning → DB Sync (P0.4)...")
    sync_result = sync_recommendations_to_db(learnings)
    print(f"  ✅ DB Sync: {sync_result.get('synced', 0)} updates, {sync_result.get('errors', 0)} errors")

    print("\n[4/7] Accuracy Report generieren...")
    accuracy = build_accuracy_report()
    print(f"  ✅ albert-accuracy.md aktualisiert")

    # Kurze Summary für Daily Log
    score_count = len(learnings.get('strategy_scores', {})) if learnings else 0
    rule_count = len(learnings.get('active_rules', [])) if learnings else 0
    decay_count = len(decay_alerts)
    summary = (
        f"Learning Cycle abgeschlossen:\n"
        f"- {score_count} Strategien bewertet\n"
        f"- {rule_count} aktive Regeln generiert\n"
        f"- {decay_count} Decay Alert(s)\n"
        f"- albert-accuracy.md automatisch aktualisiert"
    )

    # [5/7] Feature Importance (Freitags) — schreibt conviction_weights.json
    # via K9-Bridge (bridge_to_conviction_weights in feature_importance.main()).
    # Ersetzt die alte recalculate_conviction_weights()-Sonntags-Routine.
    print("\n[5/7] Feature Importance (weekly, Freitags)...")
    fi_result = {}
    if _berlin_now().weekday() == 4:  # Freitag (Berliner Zeit)
        try:
            from feature_importance import (
                run_analysis, export_feature_weights, bridge_to_conviction_weights,
            )
            fi_result = run_analysis(quick=True)
            export_feature_weights(fi_result.get('composite_scores', {}))
            bridged = bridge_to_conviction_weights(fi_result.get('composite_scores', {}))
            if bridged:
                w = bridged['weights']
                print(f"  ✅ Conviction-Weights (K9-Bridge): "
                      f"thesis={w['thesis']} tech={w['technical']} "
                      f"rr={w['risk_reward']} mkt={w['market_context']}")
            print(f"  ✅ Feature Importance: Top={list(fi_result.get('composite_scores',{}).items())[:1]}")
        except Exception as e:
            print(f"  ⚠️  Feature Importance Fehler (nicht kritisch): {e}")
    else:
        print("  ℹ️  Wöchentlich (Freitag) — heute kein Run")

    print("\n[6/7] Daily Log updaten...")
    fi_note = f"\n- Feature Importance: {len(fi_result.get('composite_scores',{}))} Features analysiert" if fi_result else ""
    summary = (
        f"Learning Cycle abgeschlossen:\n"
        f"- {score_count} Strategien bewertet\n"
        f"- {rule_count} aktive Regeln generiert\n"
        f"- {decay_count} Decay Alert(s){fi_note}\n"
        f"- albert-accuracy.md automatisch aktualisiert"
    )
    append_to_daily_log(summary)
    print(f"  ✅ Daily Log aktualisiert")

    print("\n[7/7] State Snapshot regenerieren...")
    try:
        import sqlite3 as _sql
        _db = WS / 'data/trading.db'
        _snap_path = WS / 'memory/state-snapshot.md'
        _conn = _sql.connect(str(_db))
        _conn.row_factory = _sql.Row
        _now_str = _berlin_now().strftime('%Y-%m-%d %H:%M')

        # Offene Positionen
        _positions = _conn.execute(
            "SELECT ticker, strategy, entry_price, shares, stop_price, target_price, "
            "entry_date, conviction FROM paper_portfolio WHERE status='OPEN' ORDER BY entry_date DESC"
        ).fetchall()

        # Cash
        _cash_row = _conn.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
        _cash = _cash_row[0] if _cash_row else 0.0

        # Letzte 5 abgeschlossene Trades
        _closed = _conn.execute(
            "SELECT ticker, strategy, entry_price, close_price AS exit_price, pnl_eur, "
            "close_date AS exit_date "
            "FROM paper_portfolio WHERE status IN ('CLOSED','WIN','LOSS') ORDER BY close_date DESC LIMIT 5"
        ).fetchall()

        # Aktive Strategien aus strategies.json
        _strats_file = WS / 'data/strategies.json'
        _active_strats = []
        try:
            _strats = json.loads(_strats_file.read_text())
            _active_strats = [k for k, v in _strats.items()
                              if isinstance(v, dict) and v.get('status') not in ('inactive', 'blocked')]
        except Exception:
            pass

        _conn.close()

        # Snapshot schreiben
        _lines = [
            f"# State Snapshot — Zuletzt aktualisiert: {_now_str}\n",
            f"*Auto-generiert durch daily_learning_cycle.py [7/7]*\n\n",
            f"## Cash\n",
            f"**Verfügbares Cash:** {_cash:,.0f}€\n\n",
            f"## Offene Positionen ({len(_positions)})\n",
        ]
        if _positions:
            _lines.append("| Ticker | Strategie | Entry | Stop | Target | Conviction | Datum |\n")
            _lines.append("|--------|-----------|-------|------|--------|------------|-------|\n")
            for _p in _positions:
                _lines.append(
                    f"| {_p['ticker']} | {_p['strategy']} | {_p['entry_price']:.2f}€ "
                    f"| {_p['stop_price']:.2f}€ | {_p['target_price']:.2f}€ "
                    f"| {_p['conviction'] or '—'} | {str(_p['entry_date'])[:10]} |\n"
                )
        else:
            _lines.append("*Keine offenen Positionen*\n")

        _lines.append(f"\n## Letzte 5 geschlossene Trades\n")
        if _closed:
            _lines.append("| Ticker | Strategie | Entry | Exit | PnL | Datum |\n")
            _lines.append("|--------|-----------|-------|------|-----|-------|\n")
            for _c in _closed:
                _pnl = _c['pnl_eur'] or 0
                _pnl_str = f"+{_pnl:.0f}€" if _pnl >= 0 else f"{_pnl:.0f}€"
                _lines.append(
                    f"| {_c['ticker']} | {_c['strategy']} | {_c['entry_price']:.2f}€ "
                    f"| {(_c['exit_price'] or 0):.2f}€ | {_pnl_str} "
                    f"| {str(_c['exit_date'])[:10]} |\n"
                )
        else:
            _lines.append("*Keine abgeschlossenen Trades*\n")

        _lines.append(f"\n## Aktive Strategien ({len(_active_strats)})\n")
        for _s in _active_strats:
            _lines.append(f"- {_s}\n")

        _snap_path.write_text(''.join(_lines), encoding='utf-8')
        print(f"  ✅ memory/state-snapshot.md aktualisiert ({len(_positions)} Positionen, {_cash:,.0f}€ Cash)")
    except Exception as _e:
        print(f"  ⚠️  State Snapshot Fehler (nicht kritisch): {_e}")

    print(f"\n✅ Learning Cycle fertig.")
    return summary


def run_quick():
    """Schneller Cycle — nur Scores + Accuracy, kein Feedback Loop."""
    print("[Quick Learning] Strategy Scores + Accuracy...")
    learnings = run_learning()
    build_accuracy_report()
    print("  ✅ Fertig")


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--report' in args:
        print(build_accuracy_report())
    elif '--quick' in args:
        run_quick()
    else:
        run_full()
