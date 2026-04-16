#!/usr/bin/env python3
"""
Alpha Decay Detector — Phase 3 des ML-Bauplans
===============================================
Erkennt automatisch wenn ein Signal seine Vorhersagekraft verliert.

Kernidee:
  Statt gleichgewichteter Win-Rate (alle Trades gleich wichtig)
  → Exponentiell gewichtete Win-Rate (neuere Trades zählen mehr)

  Wenn EWMA-Win-Rate << Raw-Win-Rate:
    → Signal war früher besser → DECAY DETECTED

  Wenn EWMA-Win-Rate sich stabilisiert unter Schwellenwert:
    → Signal hat keine Edge mehr → SUSPEND CANDIDATE

Ausgabe:
  - decay_score pro Strategie (0.0 = stabil, >0.10 = warnsignal)
  - status: STABLE / WARNING / DECAY / SUSPENDED
  - data/alpha_decay.json (wird von CEO + Learning Cycle gelesen)

Usage:
  python3 alpha_decay.py              # Vollständige Analyse
  python3 alpha_decay.py --quick      # Nur Warnungen ausgeben
  python3 alpha_decay.py --watch PS1  # Einzelstrategie tracken
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

import numpy as np

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
DECAY_FILE = WS / 'data/alpha_decay.json'
STRATEGIES_FILE = WS / 'data/strategies.json'
CHANGELOG = WS / 'memory/strategy-changelog.md'

# ── Parameter ────────────────────────────────────────────────────────────────
DECAY_LAMBDA = 0.88        # Gewichtungsabfall: 0.88 = neuere Trades ~5x wichtiger als alte
MIN_TRADES = 8             # Unter diesem Wert: kein zuverlässiges Signal
WARN_THRESHOLD = 0.08      # Differenz raw vs. ewma: WARNING
DECAY_THRESHOLD = 0.15     # Differenz raw vs. ewma: DECAY
EWMA_FLOOR = 0.38          # EWMA-Win-Rate unter diesem Wert → schlechte Edge
SUSPEND_FLOOR = 0.30       # EWMA-Win-Rate unter diesem Wert → SUSPEND CANDIDATE
ROLLING_WINDOW = 10        # Trailing-Fenster für "aktuelle" Win-Rate


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def load_strategy_trades(strategy_id: str) -> list[dict]:
    """Lädt alle geschlossenen Trades einer Strategie chronologisch."""
    conn = get_db()
    rows = conn.execute("""
        SELECT entry_date, close_date, pnl_eur, pnl_pct,
               CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END as win,
               ticker, exit_type
        FROM paper_portfolio
        WHERE strategy = ?
          AND status IN ('WIN', 'CLOSED', 'LOSS')
          AND pnl_eur IS NOT NULL
        ORDER BY COALESCE(close_date, entry_date) ASC
    """, (strategy_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ewma_win_rate(outcomes: list[int], lam: float = DECAY_LAMBDA) -> float:
    """
    Exponentiell gewichtete Win-Rate.
    outcomes: Liste von 0/1 (chronologisch, älteste zuerst)
    lam: Decay-Faktor (0.88 → neuester Trade hat 12% mehr Gewicht als vorheriger)
    """
    if not outcomes:
        return 0.5
    n = len(outcomes)
    weights = np.array([lam ** (n - 1 - i) for i in range(n)])
    weights /= weights.sum()
    return float(np.dot(weights, outcomes))


def rolling_win_rate(outcomes: list[int], window: int = ROLLING_WINDOW) -> float | None:
    """Win-Rate der letzten N Trades."""
    recent = outcomes[-window:]
    if len(recent) < 3:
        return None
    return sum(recent) / len(recent)


def momentum_trend(outcomes: list[int], half: int = 5) -> str:
    """
    Vergleicht erste Hälfte vs. zweite Hälfte der Trades.
    → IMPROVING / STABLE / DECLINING
    """
    if len(outcomes) < half * 2:
        return 'INSUFFICIENT'
    first_half = outcomes[:half]
    second_half = outcomes[-half:]
    wr_first = sum(first_half) / len(first_half)
    wr_second = sum(second_half) / len(second_half)
    diff = wr_second - wr_first
    if diff > 0.10:
        return 'IMPROVING'
    elif diff < -0.10:
        return 'DECLINING'
    return 'STABLE'


def classify_status(raw_wr: float, ewma_wr: float, rolling_wr: float | None,
                    n_trades: int, trend: str) -> tuple[str, str]:
    """
    Gibt Status + Erklärung zurück.
    Status: STABLE / WARNING / DECAY / SUSPEND_CANDIDATE / INSUFFICIENT_DATA
    """
    if n_trades < MIN_TRADES:
        return 'INSUFFICIENT_DATA', f'Nur {n_trades} Trades (mind. {MIN_TRADES} nötig)'

    decay_score = raw_wr - ewma_wr
    effective_wr = rolling_wr if rolling_wr is not None else ewma_wr

    if effective_wr < SUSPEND_FLOOR and n_trades >= MIN_TRADES:
        return 'SUSPEND_CANDIDATE', (
            f'EWMA Win-Rate {ewma_wr:.0%} < {SUSPEND_FLOOR:.0%} — Edge möglicherweise weg'
        )

    if decay_score > DECAY_THRESHOLD or (effective_wr < EWMA_FLOOR and trend == 'DECLINING'):
        return 'DECAY', (
            f'Raw {raw_wr:.0%} vs. EWMA {ewma_wr:.0%} — '
            f'Differenz {decay_score:+.0%} zeigt nachlassende Performance'
        )

    if decay_score > WARN_THRESHOLD or trend == 'DECLINING':
        return 'WARNING', (
            f'Trend: {trend} | EWMA {ewma_wr:.0%} (raw: {raw_wr:.0%})'
        )

    return 'STABLE', f'Win-Rate stabil | EWMA {ewma_wr:.0%} | Trend: {trend}'


def analyze_strategy(strategy_id: str) -> dict:
    """Vollständige Alpha-Decay-Analyse für eine Strategie."""
    trades = load_strategy_trades(strategy_id)

    if not trades:
        return {
            'strategy': strategy_id,
            'status': 'NO_DATA',
            'n_trades': 0,
            'raw_win_rate': None,
            'ewma_win_rate': None,
            'decay_score': None,
            'rolling_win_rate': None,
            'trend': None,
            'explanation': 'Keine geschlossenen Trades',
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

    outcomes = [t['win'] for t in trades]
    n = len(outcomes)
    raw_wr = sum(outcomes) / n
    ewma_wr = ewma_win_rate(outcomes)
    rolling_wr = rolling_win_rate(outcomes)
    trend = momentum_trend(outcomes)
    decay_score = raw_wr - ewma_wr
    status, explanation = classify_status(raw_wr, ewma_wr, rolling_wr, n, trend)

    # Zeitraum der Trades
    first_date = trades[0].get('entry_date', '')[:10]
    last_date = (trades[-1].get('close_date') or trades[-1].get('entry_date', ''))[:10]

    return {
        'strategy': strategy_id,
        'status': status,
        'n_trades': n,
        'raw_win_rate': round(raw_wr, 3),
        'ewma_win_rate': round(ewma_wr, 3),
        'rolling_win_rate': round(rolling_wr, 3) if rolling_wr is not None else None,
        'decay_score': round(decay_score, 3),
        'trend': trend,
        'explanation': explanation,
        'first_trade': first_date,
        'last_trade': last_date,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def run_all() -> dict:
    """Analysiert alle Strategien mit mindestens einem Trade."""
    conn = get_db()
    strategies_with_trades = [
        row[0] for row in conn.execute("""
            SELECT DISTINCT strategy FROM paper_portfolio
            WHERE status IN ('WIN','CLOSED','LOSS')
              AND strategy IS NOT NULL
              AND pnl_eur IS NOT NULL
        """).fetchall()
    ]
    conn.close()

    results = {}
    for sid in strategies_with_trades:
        results[sid] = analyze_strategy(sid)

    # Speichern
    DECAY_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    return results


def get_alerts(results: dict) -> list[dict]:
    """Gibt nur Strategien mit WARNING, DECAY oder SUSPEND_CANDIDATE zurück."""
    alerts = []
    for sid, r in results.items():
        if r['status'] in ('WARNING', 'DECAY', 'SUSPEND_CANDIDATE'):
            alerts.append(r)
    return sorted(alerts, key=lambda x: {
        'SUSPEND_CANDIDATE': 0, 'DECAY': 1, 'WARNING': 2
    }.get(x['status'], 9))


def update_strategy_changelog(alerts: list[dict]):
    """Schreibt Decay-Ereignisse in strategy-changelog.md."""
    if not alerts:
        return
    today = datetime.now(_BERLIN).strftime('%Y-%m-%d')
    entry_lines = [f"\n## {today} — Alpha Decay Check\n"]
    for a in alerts:
        icon = {'SUSPEND_CANDIDATE': '🔴', 'DECAY': '🟠', 'WARNING': '🟡'}.get(a['status'], '⚪')
        entry_lines.append(
            f"- {icon} **{a['strategy']}**: {a['status']} | "
            f"EWMA {a['ewma_win_rate']:.0%} (raw {a['raw_win_rate']:.0%}) | "
            f"{a['explanation']}"
        )
    entry_lines.append("")

    if CHANGELOG.exists():
        existing = CHANGELOG.read_text(encoding='utf-8')
        CHANGELOG.write_text(existing + '\n'.join(entry_lines), encoding='utf-8')
    else:
        CHANGELOG.write_text('\n'.join(entry_lines), encoding='utf-8')


def format_bar(value: float, max_val: float = 1.0, width: int = 20) -> str:
    """ASCII-Balken für Win-Rate."""
    filled = int(value / max_val * width)
    return '█' * filled + '░' * (width - filled)


def print_report(results: dict):
    """Gibt formatierten Report auf STDOUT aus."""
    print("\n" + "="*60)
    print("Alpha Decay Detector — Strategie-Status")
    print("="*60)

    # Sortierung: Alerts zuerst, dann Stable
    order = {'SUSPEND_CANDIDATE': 0, 'DECAY': 1, 'WARNING': 2,
             'STABLE': 3, 'INSUFFICIENT_DATA': 4, 'NO_DATA': 5}
    sorted_results = sorted(results.items(), key=lambda x: order.get(x[1]['status'], 9))

    status_icons = {
        'STABLE': '🟢',
        'WARNING': '🟡',
        'DECAY': '🟠',
        'SUSPEND_CANDIDATE': '🔴',
        'INSUFFICIENT_DATA': '⚪',
        'NO_DATA': '⚫',
    }

    for sid, r in sorted_results:
        icon = status_icons.get(r['status'], '❓')
        n = r['n_trades']
        raw = r['raw_win_rate']
        ewma = r['ewma_win_rate']
        roll = r['rolling_win_rate']
        trend = r['trend'] or '—'
        decay = r['decay_score']

        if raw is None:
            print(f"\n{icon} {sid:12s} | {r['status']}")
            continue

        bar_raw = format_bar(raw)
        bar_ewma = format_bar(ewma) if ewma else '—'

        print(f"\n{icon} {sid:12s} | {r['status']:20s} | {n:3d} Trades")
        print(f"   Raw  {raw:.0%} {bar_raw}")
        print(f"   EWMA {ewma:.0%} {bar_ewma}  (Δ {decay:+.0%})")
        if roll is not None:
            print(f"   Last {min(ROLLING_WINDOW, n)}  {roll:.0%} {format_bar(roll)}")
        print(f"   Trend: {trend} | {r['explanation'][:70]}")

    # Alerts
    alerts = get_alerts(results)
    if alerts:
        print(f"\n{'='*60}")
        print(f"⚠️  {len(alerts)} ALERT(S):")
        for a in alerts:
            icon = status_icons.get(a['status'], '?')
            print(f"  {icon} {a['strategy']}: {a['explanation']}")
    else:
        print(f"\n✅ Keine kritischen Decay-Signale")

    print("="*60)


# ── Integration: wird von daily_learning_cycle.py aufgerufen ─────────────────

def degrade_on_decay(alerts: list[dict]) -> list[str]:
    """
    Degradiert Strategien mit DECAY oder SUSPEND_CANDIDATE Status automatisch.

    Ruft thesis_engine.degrade_thesis() auf — damit werden:
    - Keine neuen Entries mehr erlaubt
    - Discord-Alert gesendet
    - thesis_status in DB aktualisiert

    Returns: Liste degradierter Strategie-IDs
    """
    degraded = []
    try:
        import sys as _sys
        _sys.path.insert(0, str(STRATEGIES_FILE.parent.parent / 'scripts'))
        _sys.path.insert(0, str(STRATEGIES_FILE.parent.parent / 'scripts' / 'core'))
        from thesis_engine import degrade_thesis
    except Exception as e:
        print(f"[alpha_decay] thesis_engine Import fehlgeschlagen: {e}")
        return []

    for alert in alerts:
        sid    = alert['strategy']
        status = alert['status']

        if status not in ('DECAY', 'SUSPEND_CANDIDATE'):
            continue  # WARNING allein reicht nicht für Degradierung

        ewma = alert.get('ewma_win_rate', 0)
        n    = alert.get('n_trades', 0)
        reason = (
            f"Alpha Decay: EWMA Win-Rate {ewma:.0%} | Status: {status} | "
            f"{n} Trades analysiert | Trend: {alert.get('trend', '?')}"
        )

        ok = degrade_thesis(sid, reason)
        if ok:
            degraded.append(sid)
            print(f"[alpha_decay] {sid} -> DEGRADED (alpha decay)")
        else:
            print(f"[alpha_decay] {sid}: degrade_thesis() fehlgeschlagen")

    return degraded


def run_decay_check() -> tuple[dict, list[dict]]:
    """
    Haupteinstiegspunkt für automatische Checks.
    Degradiert automatisch bei DECAY / SUSPEND_CANDIDATE.
    Returns: (results, alerts)
    """
    results = run_all()
    alerts = get_alerts(results)
    if alerts:
        update_strategy_changelog(alerts)
        # Automatische Degradierung bei nachgewiesenem Alpha-Verlust
        degraded = degrade_on_decay(alerts)
        if degraded:
            print(f"[alpha_decay] {len(degraded)} Strategien automatisch degradiert: {degraded}")
    return results, alerts


def format_discord_alert(alerts: list[dict]) -> str | None:
    """Formatiert Discord-Nachricht für Decay-Alerts."""
    if not alerts:
        return None
    lines = ["🧬 **Alpha Decay Alert**"]
    for a in alerts:
        icon = {'SUSPEND_CANDIDATE': '🔴', 'DECAY': '🟠', 'WARNING': '🟡'}.get(a['status'], '⚪')
        lines.append(
            f"{icon} **{a['strategy']}** — {a['status']}\n"
            f"  EWMA {a['ewma_win_rate']:.0%} vs. Raw {a['raw_win_rate']:.0%} "
            f"| Trend: {a['trend']} | {a['n_trades']} Trades"
        )
    return '\n'.join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--watch' in args:
        sid = args[args.index('--watch') + 1]
        r = analyze_strategy(sid)
        print(json.dumps(r, indent=2))

    elif '--quick' in args:
        results = run_all()
        alerts = get_alerts(results)
        if alerts:
            print(format_discord_alert(alerts))
        else:
            print(f"✅ Alle Strategien stabil ({len(results)} analysiert)")

    else:
        results = run_all()
        print_report(results)
        alerts = get_alerts(results)
        if alerts:
            update_strategy_changelog(alerts)
            print(f"\n→ {len(alerts)} Alert(s) in strategy-changelog.md eingetragen")
        print(f"\n→ Ergebnisse gespeichert: {DECAY_FILE}")
