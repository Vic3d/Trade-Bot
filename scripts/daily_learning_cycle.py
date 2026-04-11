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
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
ACCURACY_FILE = WS / 'memory/albert-accuracy.md'
LEARNINGS_FILE = WS / 'data/trading_learnings.json'
DAILY_LOG = WS / f"memory/{datetime.now().strftime('%Y-%m-%d')}.md"


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
            COUNT(CASE WHEN status='CLOSED' AND pnl_eur < 0 THEN 1 END) as losses
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
    entry = f"\n## {datetime.now().strftime('%H:%M')} — Auto-Learning Cycle\n\n{summary}\n"
    if DAILY_LOG.exists():
        existing = DAILY_LOG.read_text(encoding="utf-8")
        DAILY_LOG.write_text(existing + entry, encoding='utf-8')
    # Wenn kein Daily-Log existiert → nicht anlegen (Tagesabschluss macht das)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_full():
    print(f"[Daily Learning Cycle] Start — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print("\n[1/5] Alpha Decay Check...")
    decay_alerts = run_alpha_decay()

    print("\n[2/5] Feedback Loop (Signal-Kalibrierung)...")
    feedback_report = run_feedback()

    print("\n[3/5] Learning Engine (Strategy Scores)...")
    learnings = run_learning()

    print("\n[4/5] Accuracy Report generieren...")
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

    print("\n[5/5] Feature Importance (weekly, Freitags)...")
    fi_result = {}
    if datetime.now().weekday() == 4:  # Freitag
        try:
            from feature_importance import run_analysis, print_report, export_feature_weights
            fi_result = run_analysis(quick=True)
            weights = export_feature_weights(fi_result.get('composite_scores', {}))
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
        import sqlite3 as _sqlite3
        _db = _sqlite3.connect(str(WS / 'data' / 'trading.db'))
        _positions = _db.execute(
            'SELECT ticker, entry_price, stop_price, target_price, strategy, conviction, entry_date FROM paper_portfolio WHERE status="OPEN" ORDER BY entry_date'
        ).fetchall()
        _fund = dict(_db.execute('SELECT key, value FROM paper_fund').fetchall())
        _db.close()
        _now = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
        _lines = [
            '# State Snapshot — Trading Bot',
            f'**Zuletzt aktualisiert:** {_now}',
            f'**Positionen:** {len(_positions)} | **Cash:** {float(_fund.get("current_cash", 0)):.0f}EUR',
            '', '---', '',
            f'## Portfolio ({len(_positions)} Positionen)', '',
            '| Ticker | Entry | Stop | Target | Strategie | Conviction | Seit |',
            '|---|---|---|---|---|---|---|',
        ]
        for p in _positions:
            _lines.append(f'| {p[0]} | {p[1]:.2f} | {p[2] or "—"} | {p[3] or "—"} | {p[4]} | {p[5] or "—"} | {str(p[6])[:10]} |')
        (WS / 'memory' / 'state-snapshot.md').write_text('\n'.join(_lines), encoding='utf-8')
        print("  state-snapshot.md aktualisiert")
    except Exception as e:
        print(f"  Snapshot-Fehler (nicht kritisch): {e}")

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
