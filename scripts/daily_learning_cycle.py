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

WS = Path('/data/.openclaw/workspace')
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
        strats = json.loads(strat_file.read_text())
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
        learnings = json.loads(LEARNINGS_FILE.read_text())

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
    ACCURACY_FILE.write_text(report)
    conn.close()
    return report


# ── 4. DAILY LOG ENTRY ────────────────────────────────────────────────────────

def append_to_daily_log(summary: str):
    """Hängt Learning-Summary an heutiges Daily-Log."""
    entry = f"\n## {_berlin_now().strftime('%H:%M')} — Auto-Learning Cycle\n\n{summary}\n"
    if DAILY_LOG.exists():
        existing = DAILY_LOG.read_text()
        DAILY_LOG.write_text(existing + entry)
    # Wenn kein Daily-Log existiert → nicht anlegen (Tagesabschluss macht das)


# ── 5b. CONVICTION WEIGHT RECALIBRATION (Sonntags) ──────────────────────────

def recalculate_conviction_weights():
    """
    Berechnet adaptive Conviction-Gewichte aus Trade-Ergebnissen.
    Läuft nur Sonntags. Korreliert Faktor-Scores mit Win/Loss.

    Schreibt data/conviction_weights.json mit:
      weights: {thesis: X, technical: Y, risk_reward: Z, market_context: W}
      computed_at: ISO timestamp
      trade_count: N
    """
    if _berlin_now().weekday() != 6:  # Nur Sonntag (Berliner Zeit)
        print("  ℹ️  Gewichte-Rekalibrierung nur Sonntags")
        return None

    conn = get_db()
    try:
        trades = conn.execute("""
            SELECT id, strategy, conviction, pnl_eur, status
            FROM paper_portfolio
            WHERE status IN ('WIN', 'LOSS', 'CLOSED')
              AND conviction IS NOT NULL
              AND conviction > 0
            ORDER BY exit_date DESC
            LIMIT 50
        """).fetchall()
    except Exception as e:
        print(f"  ⚠️  Gewichte-Rekalibrierung DB-Fehler: {e}")
        conn.close()
        return None

    conn.close()

    if len(trades) < 20:
        print(f"  ℹ️  Zu wenig Trades ({len(trades)}/20 min) für Gewichte-Rekalibrierung")
        return None

    # Faktor-Scores aus conviction_scorer nachladen
    factor_wins = {'thesis': 0, 'technical': 0, 'risk_reward': 0, 'market_context': 0}
    factor_total = {'thesis': 0, 'technical': 0, 'risk_reward': 0, 'market_context': 0}

    try:
        sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))
        from conviction_scorer import calculate_conviction

        for t in trades:
            is_win = (t['pnl_eur'] or 0) > 0
            # Re-score mit aktuellen Daten (approximation)
            try:
                result = calculate_conviction(
                    ticker='_HISTORICAL',
                    strategy=t['strategy'] or 'DEFAULT',
                )
                factors = result.get('factors', {})
                for key, factor_key in [
                    ('thesis', 'thesis_strength'),
                    ('technical', 'technical_alignment'),
                    ('risk_reward', 'risk_reward_quality'),
                    ('market_context', 'market_context'),
                ]:
                    val = factors.get(factor_key, 0)
                    if val > 0:
                        factor_total[key] += 1
                        if is_win:
                            factor_wins[key] += 1
            except Exception:
                pass
    except Exception as e:
        print(f"  ⚠️  Faktor-Scoring Fehler: {e}")
        return None

    # Gewichte berechnen: höhere Korrelation mit Wins = höheres Gewicht
    raw_weights = {}
    for key in factor_total:
        if factor_total[key] > 0:
            raw_weights[key] = factor_wins[key] / factor_total[key]
        else:
            raw_weights[key] = 0.25  # Default gleichverteilt

    # Normalisieren auf Summe 100 mit Constraints [10, 50]
    total_raw = sum(raw_weights.values()) or 1
    weights = {}
    for key in raw_weights:
        w = (raw_weights[key] / total_raw) * 100
        weights[key] = max(10, min(50, round(w)))

    # Re-normalisieren falls Constraints die Summe verzerrt haben
    w_sum = sum(weights.values())
    if w_sum != 100:
        diff = 100 - w_sum
        # Anpassung am größten Gewicht
        max_key = max(weights, key=weights.get)
        weights[max_key] += diff

    output = {
        'weights': weights,
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'trade_count': len(trades),
        'raw_correlations': {k: round(v, 3) for k, v in raw_weights.items()},
    }

    weights_file = WS / 'data' / 'conviction_weights.json'
    weights_file.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"  ✅ Conviction-Gewichte rekalibriert: {weights} ({len(trades)} Trades)")
    return output


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_full():
    print(f"[Daily Learning Cycle] Start — {_berlin_now().strftime('%Y-%m-%d %H:%M')}")

    print("\n[1/5] Alpha Decay Check...")
    decay_alerts = run_alpha_decay()

    print("\n[2/5] Feedback Loop (Signal-Kalibrierung)...")
    feedback_report = run_feedback()

    print("\n[3/5] Learning Engine (Strategy Scores)...")
    learnings = run_learning()

    print("\n[3b/5] Learning → DB Sync (P0.4)...")
    sync_result = sync_recommendations_to_db(learnings)
    print(f"  ✅ DB Sync: {sync_result.get('synced', 0)} updates, {sync_result.get('errors', 0)} errors")

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

    print("\n[5/7] Conviction-Gewichte Rekalibrierung (Sonntags)...")
    cw_result = recalculate_conviction_weights()

    print("\n[6/7] Feature Importance (weekly, Freitags)...")
    fi_result = {}
    if _berlin_now().weekday() == 4:  # Freitag (Berliner Zeit)
        try:
            from feature_importance import run_analysis, print_report, export_feature_weights
            fi_result = run_analysis(quick=True)
            weights = export_feature_weights(fi_result.get('composite_scores', {}))
            print(f"  ✅ Feature Importance: Top={list(fi_result.get('composite_scores',{}).items())[:1]}")
        except Exception as e:
            print(f"  ⚠️  Feature Importance Fehler (nicht kritisch): {e}")
    else:
        print("  ℹ️  Wöchentlich (Freitag) — heute kein Run")

    print("\n[7/7] Daily Log updaten...")
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

    print("\n[8/8] State Snapshot regenerieren...")
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
