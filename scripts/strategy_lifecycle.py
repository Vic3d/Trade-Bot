#!/usr/bin/env python3
"""
strategy_lifecycle.py — Phase 39: Strategy-Lifecycle mit Re-Test.

Lebenszyklus:
  ACTIVE (default)
    ↓ wenn Pattern-Häufung ODER schlechte Performance
  PROBATION (14 Tage Probezeit, halbierte Größe, intensives Tracking)
    ↓ nach Probation-Period
    Re-Test:
      - Shadow-Performance der letzten 14d
      - Real-Performance falls min. 3 Trades in Probation
      - Backtest gegen historische Daten
    ↓ Resultat:
      WR ≥ 50% AND avg_pnl > 0  → REACTIVATE (zurück zu ACTIVE)
      WR < 30% OR avg_pnl < -10€ → SUSPENDED (zur Seite gelegt, 30d Cooldown)
      Dazwischen                  → bleibt in PROBATION (weitere 14d)

  SUSPENDED (zur Seite gelegt, kein Trading)
    ↓ nach Cooldown (30d)
    Auto-Reactivate-Check: Backtest letzte 30d
      Hätte sie funktioniert? → PROBATION (Test-Phase)
      Nein → bleibt SUSPENDED weitere 30d

  RETIRED (3x SUSPENDED-Cycles ohne Erfolg → permanent aus dem Spiel)

Trigger für Probation:
  - 3+ Anti-Patterns mit dieser Strategy
  - Win-Rate letzte 30d < 35%
  - 3 LOSS in Folge
  - Strategy von daily_learning_cycle als SUSPEND empfohlen

Schreibt Status in strategies.json als _lifecycle_state, _lifecycle_changed_at,
_probation_until, _suspension_until, _failed_cycles.

Discord-Alerts bei jedem Status-Wechsel.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB                = WS / 'data' / 'trading.db'
STRATEGIES_FILE   = WS / 'data' / 'strategies.json'
LIFECYCLE_LOG     = WS / 'data' / 'strategy_lifecycle_log.jsonl'

# Lifecycle-Konstanten
PROBATION_DAYS         = 14
SUSPENSION_COOLDOWN_DAYS = 30
RETIRE_AFTER_FAILED_CYCLES = 3

PROBATION_TRIGGERS = {
    'anti_pattern_threshold':  3,    # 3+ Anti-Patterns → Probation
    'min_win_rate_pct':       35,    # WR < 35% → Probation
    'consecutive_losses':      3,    # 3 LOSS in Folge → Probation
    'min_avg_pnl_eur':       -50,    # avg PnL < -50 → Probation
}

REACTIVATE_THRESHOLDS = {
    'min_win_rate_pct':       50,
    'min_avg_pnl_eur':         0,
    'min_sample_size':         3,
}

PERMANENT_SUSPEND_THRESHOLDS = {
    'max_win_rate_pct':       30,
    'max_avg_pnl_eur':       -10,
    'min_sample_size':         3,
}


def _load_strategies() -> dict:
    if not STRATEGIES_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_strategies(data: dict) -> None:
    STRATEGIES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                encoding='utf-8')


def _log_lifecycle(strategy: str, old_state: str, new_state: str,
                    reason: str, metrics: dict) -> None:
    entry = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'strategy': strategy,
        'old_state': old_state,
        'new_state': new_state,
        'reason': reason,
        'metrics': metrics,
    }
    LIFECYCLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LIFECYCLE_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def get_strategy_metrics(strategy: str, days: int = 30) -> dict:
    """Performance-Metriken für eine Strategy."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT pnl_eur, pnl_pct, close_date FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND strategy = ?
              AND COALESCE(close_date, entry_date) >= ?
            ORDER BY close_date DESC
        """, (strategy, cutoff)).fetchall()
        c.close()
    except Exception:
        return {'error': 'db_error', 'strategy': strategy}

    if not rows:
        return {'strategy': strategy, 'n': 0, 'window_days': days}

    pnls = [r['pnl_eur'] or 0 for r in rows]
    wins = sum(1 for p in pnls if p > 0)

    # Consecutive losses (von neueste rückwärts)
    consec_losses = 0
    for p in pnls:
        if p < 0:
            consec_losses += 1
        else:
            break

    return {
        'strategy': strategy,
        'n': len(pnls),
        'window_days': days,
        'wins': wins,
        'win_rate': round(wins / len(pnls) * 100, 1),
        'avg_pnl_eur': round(mean(pnls), 2),
        'sum_pnl_eur': round(sum(pnls), 0),
        'consecutive_losses': consec_losses,
    }


def count_active_anti_patterns(strategy: str) -> int:
    """Wieviele Anti-Patterns hat diese Strategy aktuell?"""
    try:
        from ceo_pattern_learning import load_anti_patterns
        patterns = load_anti_patterns()
        return sum(1 for p in patterns
                   if p.get('pattern_key', '').startswith(strategy + '|'))
    except Exception:
        return 0


def should_enter_probation(strategy: str) -> tuple[bool, str]:
    """Returns (should_probate, reason)."""
    metrics = get_strategy_metrics(strategy, days=30)

    # Trigger 1: Anti-Patterns
    n_patterns = count_active_anti_patterns(strategy)
    if n_patterns >= PROBATION_TRIGGERS['anti_pattern_threshold']:
        return True, f'{n_patterns} active anti-patterns'

    if metrics.get('n', 0) >= 5:
        # Trigger 2: WR
        if metrics['win_rate'] < PROBATION_TRIGGERS['min_win_rate_pct']:
            return True, f'WR {metrics["win_rate"]}% < {PROBATION_TRIGGERS["min_win_rate_pct"]}%'
        # Trigger 4: avg_pnl
        if metrics['avg_pnl_eur'] < PROBATION_TRIGGERS['min_avg_pnl_eur']:
            return True, f'avg_pnl {metrics["avg_pnl_eur"]}€ < {PROBATION_TRIGGERS["min_avg_pnl_eur"]}€'

    # Trigger 3: Consecutive losses
    if metrics.get('consecutive_losses', 0) >= PROBATION_TRIGGERS['consecutive_losses']:
        return True, f'{metrics["consecutive_losses"]} consecutive losses'

    return False, ''


def evaluate_probation(strategy: str) -> tuple[str, str, dict]:
    """Returns (decision, reason, metrics).
    decision: 'REACTIVATE' | 'SUSPEND' | 'EXTEND_PROBATION'."""
    metrics = get_strategy_metrics(strategy, days=PROBATION_DAYS)

    if metrics.get('n', 0) < REACTIVATE_THRESHOLDS['min_sample_size']:
        # Zu wenig Daten — extend probation
        return 'EXTEND_PROBATION', f'only {metrics.get("n",0)} trades, need {REACTIVATE_THRESHOLDS["min_sample_size"]}', metrics

    wr = metrics['win_rate']
    avg_pnl = metrics['avg_pnl_eur']

    # Permanent-Suspend?
    if (wr <= PERMANENT_SUSPEND_THRESHOLDS['max_win_rate_pct']
            and avg_pnl <= PERMANENT_SUSPEND_THRESHOLDS['max_avg_pnl_eur']):
        return 'SUSPEND', f'WR {wr}% + avg {avg_pnl}€ = clear loser', metrics

    # Reactivate?
    if (wr >= REACTIVATE_THRESHOLDS['min_win_rate_pct']
            and avg_pnl >= REACTIVATE_THRESHOLDS['min_avg_pnl_eur']):
        return 'REACTIVATE', f'WR {wr}% + avg {avg_pnl}€ = healthy', metrics

    # Dazwischen
    return 'EXTEND_PROBATION', f'WR {wr}% + avg {avg_pnl}€ = mixed', metrics


def evaluate_suspension_recovery(strategy: str) -> tuple[str, str, dict]:
    """Nach Suspension-Cooldown: Backtest gegen letzte 30d.
    Hätte die Strategy in der Suspension-Phase Geld gemacht?"""
    metrics = get_strategy_metrics(strategy, days=30)
    # Wenn Strategy nicht traded hat (was richtig ist da SUSPENDED), nutzen wir
    # SHADOW_TRADES (Phase 28) — die hätten die hypothetische Performance.
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        rows = c.execute("""
            SELECT pnl_pct, status FROM shadow_trades
            WHERE strategy = ? AND ts_created >= ?
              AND status IN ('WIN','LOSS','EXPIRED')
        """, (strategy, cutoff)).fetchall()
        c.close()
        shadow_n = len(rows)
        shadow_wins = sum(1 for r in rows if r['status'] == 'WIN')
        shadow_pnl = sum(r['pnl_pct'] or 0 for r in rows)
    except Exception:
        shadow_n = 0
        shadow_wins = 0
        shadow_pnl = 0

    if shadow_n < REACTIVATE_THRESHOLDS['min_sample_size']:
        return 'EXTEND_SUSPENSION', f'only {shadow_n} shadow trades', {'shadow': shadow_n}

    shadow_wr = shadow_wins / shadow_n * 100
    if shadow_wr >= REACTIVATE_THRESHOLDS['min_win_rate_pct']:
        return 'TO_PROBATION', f'shadow WR {shadow_wr:.0f}%, give it a real chance', {
            'shadow_n': shadow_n, 'shadow_wr': shadow_wr, 'shadow_pnl_pct_sum': shadow_pnl,
        }

    return 'EXTEND_SUSPENSION', f'shadow WR only {shadow_wr:.0f}%, still bad', {
        'shadow_n': shadow_n, 'shadow_wr': shadow_wr,
    }


def transition(strategy_data: dict, new_state: str, reason: str,
                metrics: dict | None = None) -> dict:
    """Setze neuen Lifecycle-State auf einer Strategy + audit-log."""
    old_state = strategy_data.get('_lifecycle_state', 'ACTIVE')
    now_iso = datetime.now().isoformat(timespec='seconds')

    strategy_data['_lifecycle_state'] = new_state
    strategy_data['_lifecycle_changed_at'] = now_iso
    strategy_data['_lifecycle_reason'] = reason

    if new_state == 'PROBATION':
        until = datetime.now() + timedelta(days=PROBATION_DAYS)
        strategy_data['_probation_until'] = until.isoformat(timespec='seconds')
        strategy_data['status'] = 'active'  # darf weiter handeln, aber halbiert
        strategy_data['_size_multiplier'] = 0.5

    elif new_state == 'SUSPENDED':
        until = datetime.now() + timedelta(days=SUSPENSION_COOLDOWN_DAYS)
        strategy_data['_suspension_until'] = until.isoformat(timespec='seconds')
        strategy_data['status'] = 'suspended'
        strategy_data['_failed_cycles'] = strategy_data.get('_failed_cycles', 0) + 1
        if strategy_data.get('_failed_cycles', 0) >= RETIRE_AFTER_FAILED_CYCLES:
            new_state = 'RETIRED'
            strategy_data['_lifecycle_state'] = 'RETIRED'
            reason = f'{strategy_data["_failed_cycles"]} failed cycles → permanently retired'

    elif new_state == 'ACTIVE':
        strategy_data.pop('_probation_until', None)
        strategy_data.pop('_suspension_until', None)
        strategy_data.pop('_size_multiplier', None)
        strategy_data['status'] = 'active'

    elif new_state == 'RETIRED':
        strategy_data['status'] = 'retired'

    return {
        'old_state': old_state, 'new_state': new_state,
        'reason': reason, 'metrics': metrics or {},
    }


def run_lifecycle_pass() -> dict:
    """Hauptschleife — durchläuft alle Strategies + transitions."""
    strategies = _load_strategies()
    if not strategies:
        return {'error': 'no_strategies'}

    transitions_made = []
    now = datetime.now()

    for sid, sdata in strategies.items():
        if not isinstance(sdata, dict):
            continue
        # Skip permanent-blocked
        if sid.upper() in {'AR-AGRA', 'AR-HALB'} or sid.upper().startswith('DT'):
            continue

        current_state = sdata.get('_lifecycle_state', 'ACTIVE')

        # === ACTIVE: prüfe Probation-Trigger ===
        if current_state == 'ACTIVE':
            should_prob, reason = should_enter_probation(sid)
            if should_prob:
                metrics = get_strategy_metrics(sid, days=30)
                t = transition(sdata, 'PROBATION', reason, metrics)
                transitions_made.append({'strategy': sid, **t})
                _log_lifecycle(sid, 'ACTIVE', 'PROBATION', reason, metrics)

        # === PROBATION: prüfe ob Probation-Period vorbei ===
        elif current_state == 'PROBATION':
            until_str = sdata.get('_probation_until')
            if until_str:
                try:
                    until_dt = datetime.fromisoformat(until_str)
                    if now >= until_dt:
                        decision, reason, metrics = evaluate_probation(sid)
                        if decision == 'REACTIVATE':
                            t = transition(sdata, 'ACTIVE', reason, metrics)
                        elif decision == 'SUSPEND':
                            t = transition(sdata, 'SUSPENDED', reason, metrics)
                        else:
                            # Extend
                            sdata['_probation_until'] = (now + timedelta(days=PROBATION_DAYS)).isoformat(timespec='seconds')
                            t = {'old_state': 'PROBATION', 'new_state': 'PROBATION',
                                 'reason': f'EXTENDED: {reason}', 'metrics': metrics}
                        transitions_made.append({'strategy': sid, **t})
                        _log_lifecycle(sid, 'PROBATION', t['new_state'], reason, metrics)
                except Exception as e:
                    print(f'[lifecycle] {sid} probation parse error: {e}', file=sys.stderr)

        # === SUSPENDED: prüfe Cooldown vorbei ===
        elif current_state == 'SUSPENDED':
            until_str = sdata.get('_suspension_until')
            if until_str:
                try:
                    until_dt = datetime.fromisoformat(until_str)
                    if now >= until_dt:
                        decision, reason, metrics = evaluate_suspension_recovery(sid)
                        if decision == 'TO_PROBATION':
                            t = transition(sdata, 'PROBATION', reason, metrics)
                        else:
                            # Extend Suspension
                            sdata['_suspension_until'] = (now + timedelta(days=SUSPENSION_COOLDOWN_DAYS)).isoformat(timespec='seconds')
                            t = {'old_state': 'SUSPENDED', 'new_state': 'SUSPENDED',
                                 'reason': f'EXTENDED: {reason}', 'metrics': metrics}
                        transitions_made.append({'strategy': sid, **t})
                        _log_lifecycle(sid, 'SUSPENDED', t['new_state'], reason, metrics)
                except Exception as e:
                    print(f'[lifecycle] {sid} suspension parse error: {e}', file=sys.stderr)

    if transitions_made:
        _save_strategies(strategies)

    return {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'transitions': transitions_made,
        'count': len(transitions_made),
    }


def get_size_multiplier(strategy: str) -> float:
    """Returns Size-Multiplier basierend auf Lifecycle.
    PROBATION: 0.5, ACTIVE: 1.0, SUSPENDED: 0 (sollte gar nicht traden)."""
    strategies = _load_strategies()
    sdata = strategies.get(strategy, {})
    if not isinstance(sdata, dict):
        return 1.0
    state = sdata.get('_lifecycle_state', 'ACTIVE')
    if state == 'PROBATION':
        return float(sdata.get('_size_multiplier', 0.5))
    if state in ('SUSPENDED', 'RETIRED'):
        return 0.0
    return 1.0


def get_lifecycle_overview() -> dict:
    """Quick-Overview für Discord."""
    strategies = _load_strategies()
    by_state = {'ACTIVE': [], 'PROBATION': [], 'SUSPENDED': [], 'RETIRED': []}
    for sid, sdata in strategies.items():
        if not isinstance(sdata, dict):
            continue
        state = sdata.get('_lifecycle_state', 'ACTIVE')
        if state in by_state:
            by_state[state].append({
                'id': sid,
                'reason': sdata.get('_lifecycle_reason', ''),
                'changed_at': sdata.get('_lifecycle_changed_at', ''),
                'failed_cycles': sdata.get('_failed_cycles', 0),
            })
    return by_state


def main() -> int:
    print(f'─── Strategy-Lifecycle Pass @ {datetime.now().isoformat(timespec="seconds")} ───')
    result = run_lifecycle_pass()
    print(f'Transitions: {result.get("count", 0)}')
    for t in result.get('transitions', []):
        print(f"  {t['strategy']:<22} {t['old_state']} → {t['new_state']}: {t['reason']}")

    overview = get_lifecycle_overview()
    print(f'\n=== Aktueller Bestand ===')
    for state, items in overview.items():
        print(f'  {state}: {len(items)}')

    # Discord-Alert nur bei tatsächlichen Transitions
    if result.get('transitions'):
        try:
            from discord_dispatcher import send_alert, TIER_MEDIUM
            lines = [f'🔄 **Strategy-Lifecycle Update** ({result["count"]} Transitions)']
            for t in result['transitions']:
                icon = {'PROBATION': '⚠️', 'SUSPENDED': '🚫', 'ACTIVE': '✅', 'RETIRED': '⚰️'}.get(t['new_state'], '?')
                lines.append(f"  {icon} `{t['strategy']:<22}` {t['old_state']} → **{t['new_state']}**")
                lines.append(f"     _{t['reason']}_")
            send_alert('\n'.join(lines), tier=TIER_MEDIUM, category='lifecycle',
                       dedupe_key=f'lifecycle_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
