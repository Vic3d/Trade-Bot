#!/usr/bin/env python3
"""
Learning Engine — Autonomes Lernen aus Paper Trade Ergebnissen.

Läuft täglich (23:00 Cron) und nach jedem Trade-Abschluss.

Was es tut:
  1. Strategy Health auto-update (win rate + avg win/loss ratio)
  2. Trigger-Korrelation messen (welche News-Keywords gewinnen wirklich?)
  3. Score-Threshold auto-kalibrieren
  4. CRV-Minimum anpassen wenn Verluste größer als erwartet

Output:
  - strategies.json (health, win_rate, avg_pnl)
  - opportunity_profiles.json (trigger_weights)
  - memory/learning-log.md (was wurde geändert)
"""

import json, sqlite3, re
from pathlib import Path
from datetime import datetime, date

WS = Path(__file__).resolve().parent.parent
DB_PATH = WS / 'data/trading.db'
STRATEGIES_PATH = WS / 'data/strategies.json'
PROFILES_PATH = WS / 'data/opportunity_profiles.json'
LEARNING_LOG = WS / 'memory/learning-log.md'

# Mindest-Trades bevor Statistik relevant ist
MIN_TRADES_FOR_STATS = 5
# Mindest-Triggers bevor Gewichtung relevant ist
MIN_TRIGGER_OCCURRENCES = 3


def load_closed_trades():
    """Alle geschlossenen Paper Trades mit P&L laden."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    trades = conn.execute(
        "SELECT * FROM paper_portfolio WHERE status='CLOSED' AND pnl_pct IS NOT NULL"
    ).fetchall()
    conn.close()
    return [dict(t) for t in trades]


def calc_strategy_stats(trades):
    """Pro Strategie: win_rate, avg_win, avg_loss, win_loss_ratio."""
    by_strat = {}
    for t in trades:
        s = t.get('strategy', 'UNKNOWN')
        if s not in by_strat:
            by_strat[s] = []
        by_strat[s].append(t['pnl_pct'])

    stats = {}
    for strat, pnls in by_strat.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        n = len(pnls)
        win_rate = len(wins) / n if n > 0 else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        wl_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else 999
        avg_pnl = sum(pnls) / n if n > 0 else 0

        stats[strat] = {
            'n_trades': n,
            'win_rate': round(win_rate, 3),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'win_loss_ratio': round(wl_ratio, 2),
            'avg_pnl': round(avg_pnl, 2),
        }
    return stats


def determine_health(stat):
    """Strategie-Health aus Stats ableiten."""
    n = stat['n_trades']
    if n < MIN_TRADES_FOR_STATS:
        return 'yellow', f"Zu wenige Trades ({n}/{MIN_TRADES_FOR_STATS})"

    wr = stat['win_rate']
    wl = stat['win_loss_ratio']
    avg = stat['avg_pnl']

    if wr >= 0.60 and wl >= 1.5 and avg > 0:
        return 'green', f"WR {wr:.0%} | WL-Ratio {wl:.2f}x | Avg {avg:+.1f}%"
    elif wr < 0.50 or wl < 1.0 or avg < -5:
        return 'red', f"WR {wr:.0%} | WL-Ratio {wl:.2f}x | Avg {avg:+.1f}% — Edge nicht vorhanden"
    else:
        return 'yellow', f"WR {wr:.0%} | WL-Ratio {wl:.2f}x | Avg {avg:+.1f}% — beobachten"


def extract_triggers_from_notes(notes):
    """News-Trigger aus Trade-Notes extrahieren."""
    if not notes:
        return []
    # Format: "News-Signal Score X/10 | Trigger: A, B | headline"
    match = re.search(r'Trigger:\s*([^|]+)', notes)
    if match:
        raw = match.group(1).strip()
        return [t.strip() for t in raw.split(',') if t.strip()]
    return []


def calc_trigger_correlations(trades):
    """Trigger → Win-Rate Mapping."""
    trigger_stats = {}
    for t in trades:
        triggers = extract_triggers_from_notes(t.get('notes', ''))
        won = t['pnl_pct'] > 0
        for trigger in triggers:
            if trigger not in trigger_stats:
                trigger_stats[trigger] = {'wins': 0, 'losses': 0}
            if won:
                trigger_stats[trigger]['wins'] += 1
            else:
                trigger_stats[trigger]['losses'] += 1

    correlations = {}
    for trigger, s in trigger_stats.items():
        n = s['wins'] + s['losses']
        if n >= MIN_TRIGGER_OCCURRENCES:
            correlations[trigger] = {
                'n': n,
                'win_rate': round(s['wins'] / n, 2),
                'signal': 'strong' if s['wins'] / n >= 0.7 else ('weak' if s['wins'] / n < 0.4 else 'neutral')
            }
    return correlations


def calibrate_score_threshold(trades, current_threshold=5):
    """Score-Threshold anpassen basierend auf letzten 10 Trades."""
    recent = sorted(trades, key=lambda t: t.get('entry_date', ''), reverse=True)[:10]
    if len(recent) < 5:
        return current_threshold, "Zu wenige Trades für Kalibrierung"

    avg_pnl = sum(t['pnl_pct'] for t in recent) / len(recent)

    if avg_pnl < -2:
        new_threshold = min(current_threshold + 1, 8)
        return new_threshold, f"Letzte 10 Trades: Avg {avg_pnl:+.1f}% → Threshold erhöht"
    elif avg_pnl > 8 and current_threshold > 4:
        new_threshold = max(current_threshold - 0.5, 4)
        return new_threshold, f"Letzte 10 Trades: Avg {avg_pnl:+.1f}% → Threshold leicht gesenkt"
    else:
        return current_threshold, f"Letzte 10 Trades: Avg {avg_pnl:+.1f}% → Threshold bleibt bei {current_threshold}"


def run_learning_cycle():
    """Kompletten Lernzyklus ausführen. Gibt Log-Einträge zurück."""
    log = []
    changes = []
    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    log.append(f"\n## [{ts}] Learning Engine Run\n")

    trades = load_closed_trades()
    log.append(f"- Trades analysiert: {len(trades)}")

    if len(trades) < 3:
        log.append("- Zu wenige Trades — kein Update")
        _write_log(log)
        return changes

    # 1. Strategy Health Update
    strategy_stats = calc_strategy_stats(trades)
    try:
        with open(STRATEGIES_PATH) as f:
            strategies = json.load(f)
    except:
        strategies = {}

    for strat, stat in strategy_stats.items():
        new_health, reason = determine_health(stat)

        if strat not in strategies:
            strategies[strat] = {}

        old_health = strategies[strat].get('health', 'yellow')
        old_locked = strategies[strat].get('locked', False)

        # Manuell gesperrte Strategien nicht automatisch entsperren
        if old_locked and new_health != 'red':
            log.append(f"- {strat}: Manuell gesperrt — kein Auto-Unlock (Stats: {reason})")
            continue

        strategies[strat]['health'] = new_health
        strategies[strat]['win_rate'] = stat['win_rate']
        strategies[strat]['avg_pnl'] = stat['avg_pnl']
        strategies[strat]['win_loss_ratio'] = stat['win_loss_ratio']
        strategies[strat]['n_trades'] = stat['n_trades']
        strategies[strat]['last_evaluated'] = ts

        if old_health != new_health:
            emoji = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(new_health, '⚪')
            log.append(f"- **{strat}: {old_health} → {new_health} {emoji}** | {reason}")
            changes.append(f"{strat}: {old_health}→{new_health}")
        else:
            log.append(f"- {strat}: {new_health} (unverändert) | {reason}")

    with open(STRATEGIES_PATH, 'w') as f:
        json.dump(strategies, f, indent=2, ensure_ascii=False)

    # 2. Trigger-Korrelation
    correlations = calc_trigger_correlations(trades)
    if correlations:
        log.append(f"\n**Trigger-Korrelationen ({len(correlations)} mit ≥{MIN_TRIGGER_OCCURRENCES} Trades):**")
        for trigger, c in sorted(correlations.items(), key=lambda x: x[1]['win_rate'], reverse=True):
            signal_emoji = {'strong': '✅', 'neutral': '➡️', 'weak': '⚠️'}.get(c['signal'], '')
            log.append(f"  {signal_emoji} '{trigger}': {c['win_rate']:.0%} WR ({c['n']} Trades)")

        # Profile updaten mit Trigger-Gewichtungen
        try:
            with open(PROFILES_PATH) as f:
                profiles = json.load(f)
            for ticker, profile in profiles.items():
                updated = False
                for trigger in profile.get('bullish_triggers', []):
                    if trigger in correlations:
                        if 'trigger_stats' not in profile:
                            profile['trigger_stats'] = {}
                        profile['trigger_stats'][trigger] = correlations[trigger]
                        updated = True
                if updated:
                    profiles[ticker] = profile
            with open(PROFILES_PATH, 'w') as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.append(f"  Profil-Update Fehler: {e}")
    else:
        log.append("\n**Trigger-Korrelation:** Noch zu wenige Daten (<3 Trades pro Trigger)")

    # 3. Score-Threshold Kalibrierung
    current_threshold = 5  # Default
    new_threshold, threshold_reason = calibrate_score_threshold(trades, current_threshold)
    log.append(f"\n**Score-Threshold:** {threshold_reason}")
    if new_threshold != current_threshold:
        changes.append(f"Score-Threshold: {current_threshold}→{new_threshold}")
        # Threshold in strategies.json persistieren
        strategies['_meta'] = strategies.get('_meta', {})
        strategies['_meta']['score_threshold'] = new_threshold
        strategies['_meta']['threshold_reason'] = threshold_reason
        strategies['_meta']['threshold_updated'] = ts
        with open(STRATEGIES_PATH, 'w') as f:
            json.dump(strategies, f, indent=2, ensure_ascii=False)

    # 4. Zusammenfassung
    log.append(f"\n**Changes:** {len(changes)} | {', '.join(changes) if changes else 'Keine'}")
    log.append("---")

    _write_log(log)
    return changes


def _write_log(log_lines):
    """Learning-Log schreiben."""
    if not LEARNING_LOG.exists():
        LEARNING_LOG.write_text("# Learning Engine Log\n\nAutomatische Lernzyklen des Paper Trading Systems.\n")
    with open(LEARNING_LOG, 'a') as f:
        f.write('\n'.join(log_lines) + '\n')


if __name__ == '__main__':
    print("=== Learning Engine ===")
    changes = run_learning_cycle()
    print(f"Fertig. {len(changes)} Änderungen:")
    for c in changes:
        print(f"  → {c}")
    if not changes:
        print("  Keine Änderungen (alles stabil)")
