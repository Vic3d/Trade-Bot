#!/usr/bin/env python3
"""
Feedback Engine — Das Herz der Learning Loop
============================================
Schicht 1: Messen    (Was performen welche Strategien wirklich?)
Schicht 2: Bewerten  (Hat eine Strategie einen statistischen Edge?)
Schicht 3: Handeln   (Health updaten, Gewichte anpassen, Kills auslösen)

Läuft täglich 22:30 nach Learning Engine.
Ist der einzige Prozess der strategies.json + dt_weights.json ändern darf.
"""

import sqlite3, json, math
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict

WS          = Path('/data/.openclaw/workspace')
DB          = WS / 'data/trading.db'
STRAT_JSON  = WS / 'data/strategies.json'
DT_WEIGHTS  = WS / 'data/dt_weights.json'
FEEDBACK_LOG = WS / 'memory/feedback-log.md'

# ── Schwellwerte ────────────────────────────────────────────────
MIN_TRADES_FOR_JUDGMENT = 15   # Weniger Trades → kein Urteil
KILL_WR_THRESHOLD       = 0.32 # Win-Rate < 32% nach MIN_TRADES → disable
PROMOTE_WR_THRESHOLD    = 0.55 # Win-Rate > 55% → erhöhtes Gewicht
KILL_SHARPE_THRESHOLD   = -2.0 # Sharpe < -2 → sofortiger Kill
MIN_EV_TO_TRADE         = 0.0  # Expected Value > 0 erforderlich

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def calc_sharpe(pnls: list) -> float:
    """Vereinfachter Sharpe (Risk-Free = 0)."""
    if len(pnls) < 3:
        return 0.0
    avg = sum(pnls) / len(pnls)
    variance = sum((p - avg) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(variance) if variance > 0 else 0.001
    return avg / std

def calc_expected_value(wins: int, losses: int, avg_win: float, avg_loss: float) -> float:
    """EV = P(win)*avg_win + P(loss)*avg_loss"""
    total = wins + losses
    if total == 0: return 0.0
    pw = wins / total
    pl = losses / total
    return pw * avg_win + pl * avg_loss

def analyze_dt_strategies() -> dict:
    """Analysiert alle DT-Strategien aus trades-Tabelle."""
    conn = get_db()
    results = {}

    strategies = [r['strategy'] for r in conn.execute(
        "SELECT DISTINCT strategy FROM trades WHERE strategy LIKE 'DT%'"
    ).fetchall()]

    for strat in strategies:
        if '-CTR' in strat:
            continue  # CTR-Varianten separat

        rows = conn.execute("""
            SELECT pnl_eur, status, regime_at_entry, conviction_at_entry
            FROM trades
            WHERE strategy = ? AND status IN ('WIN','LOSS') AND pnl_eur IS NOT NULL
        """, (strat,)).fetchall()

        open_count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE strategy=? AND status='OPEN'", (strat,)
        ).fetchone()[0]

        if not rows:
            results[strat] = {'status': 'no_data', 'trades': 0}
            continue

        pnls = [r['pnl_eur'] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        wr = len(wins) / len(pnls)
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        sharpe = calc_sharpe(pnls)
        ev = calc_expected_value(len(wins), len(losses), avg_win, avg_loss)
        total_pnl = sum(pnls)

        results[strat] = {
            'trades': len(pnls),
            'open': open_count,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(wr, 3),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'sharpe': round(sharpe, 3),
            'expected_value': round(ev, 2),
            'total_pnl': round(total_pnl, 2),
        }

    conn.close()
    return results

def analyze_ps_strategies() -> dict:
    """Analysiert PS-Swing-Strategien aus paper_portfolio."""
    conn = get_db()
    results = {}

    strategies = [r['strategy'] for r in conn.execute(
        "SELECT DISTINCT strategy FROM paper_portfolio"
    ).fetchall()]

    for strat in strategies:
        rows = conn.execute("""
            SELECT pnl_eur, close_price, entry_price
            FROM paper_portfolio
            WHERE strategy=? AND status='CLOSED'
              AND pnl_eur IS NOT NULL AND pnl_eur != 0
        """, (strat,)).fetchall()

        open_count = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE strategy=? AND status='OPEN'", (strat,)
        ).fetchone()[0]

        if not rows:
            results[strat] = {'status': 'no_data', 'trades': 0, 'open': open_count}
            continue

        pnls = [r['pnl_eur'] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        wr = len(wins) / len(pnls) if pnls else 0

        results[strat] = {
            'trades': len(pnls),
            'open': open_count,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(wr, 3),
            'total_pnl': round(sum(pnls), 2),
            'sharpe': round(calc_sharpe(pnls), 3),
        }

    conn.close()
    return results

def update_dt_weights(dt_analysis: dict) -> dict:
    """Passt DT-Gewichte basierend auf Performance an."""
    # Lade aktuelle Gewichte
    if DT_WEIGHTS.exists():
        weights = json.load(open(DT_WEIGHTS))
    else:
        weights = {s: {'enabled': True, 'weight': 1.0, 'kills': 0} for s in dt_analysis}

    changes = []

    for strat, data in dt_analysis.items():
        if data.get('status') == 'no_data' or data['trades'] < MIN_TRADES_FOR_JUDGMENT:
            continue

        wr = data['win_rate']
        sharpe = data['sharpe']
        ev = data['expected_value']

        if strat not in weights:
            weights[strat] = {'enabled': True, 'weight': 1.0, 'kills': 0}

        was_enabled = weights[strat].get('enabled', True)

        # KILL-Bedingungen
        if sharpe < KILL_SHARPE_THRESHOLD and data['trades'] >= MIN_TRADES_FOR_JUDGMENT:
            if was_enabled:
                weights[strat]['enabled'] = False
                weights[strat]['kill_reason'] = f'Sharpe {sharpe:.2f} < {KILL_SHARPE_THRESHOLD}'
                weights[strat]['kills'] = weights[strat].get('kills', 0) + 1
                changes.append(f'🔴 KILL {strat}: Sharpe {sharpe:.2f} | WR {wr:.0%} | EV {ev:.2f}€')

        elif ev < MIN_EV_TO_TRADE and data['trades'] >= MIN_TRADES_FOR_JUDGMENT * 2:
            if was_enabled:
                weights[strat]['enabled'] = False
                weights[strat]['kill_reason'] = f'EV {ev:.2f} < 0 nach {data["trades"]} Trades'
                changes.append(f'🔴 DISABLE {strat}: EV {ev:.2f}€ nach {data["trades"]} Trades')

        # PROMOTE-Bedingungen
        elif wr >= PROMOTE_WR_THRESHOLD and data['trades'] >= MIN_TRADES_FOR_JUDGMENT:
            old_w = weights[strat].get('weight', 1.0)
            new_w = min(2.5, old_w * 1.2)  # Max 2.5x Gewicht
            if new_w > old_w + 0.05:
                weights[strat]['weight'] = round(new_w, 2)
                weights[strat]['enabled'] = True
                changes.append(f'🟢 PROMOTE {strat}: WR {wr:.0%} → Gewicht {old_w:.1f}→{new_w:.1f}')

        # RE-ENABLE wenn Kill überholt
        elif was_enabled is False and wr > KILL_WR_THRESHOLD + 0.1:
            weights[strat]['enabled'] = True
            weights[strat]['kill_reason'] = None
            changes.append(f'🟡 RE-ENABLE {strat}: WR erholt auf {wr:.0%}')

    weights['_last_updated'] = datetime.now().isoformat()
    with open(DT_WEIGHTS, 'w') as f:
        json.dump(weights, f, indent=2)

    return changes

def update_ps_health(ps_analysis: dict) -> list:
    """Aktualisiert health-Felder in strategies.json."""
    if not STRAT_JSON.exists():
        return []

    strats = json.load(open(STRAT_JSON))
    changes = []

    for ps_id, data in ps_analysis.items():
        if ps_id not in strats:
            continue
        if data['trades'] < 5:  # Weniger als 5 echte Trades → kein Urteil
            continue

        wr = data['win_rate']
        old_health = strats[ps_id].get('health', 'unknown')

        if wr >= 0.50:
            new_health = 'green'
        elif wr >= 0.35:
            new_health = 'yellow'
        else:
            new_health = 'red'

        # Statistik in strategies.json rückschreiben
        strats[ps_id]['wins'] = data['wins']
        strats[ps_id]['losses'] = data['losses']
        strats[ps_id]['trades'] = data['trades']
        strats[ps_id]['pnl'] = data['total_pnl']
        strats[ps_id]['win_rate'] = data['win_rate']
        strats[ps_id]['last_evaluated'] = date.today().isoformat()

        if new_health != old_health and old_health not in ('testing', 'unknown'):
            strats[ps_id]['health'] = new_health
            changes.append(f'PS Health {ps_id}: {old_health} → {new_health} (WR {wr:.0%})')

    with open(STRAT_JSON, 'w') as f:
        json.dump(strats, f, indent=2)

    return changes

def write_log(dt_analysis, ps_analysis, dt_changes, ps_changes):
    """Schreibt übersichtlichen Feedback-Log."""
    if not FEEDBACK_LOG.exists():
        FEEDBACK_LOG.write_text('# Feedback Engine Log\n\n')

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f'\n## [{ts}]\n']

    lines.append('### Day Trades\n')
    lines.append('| Strategie | Trades | WR | EV | Sharpe | Status |\n')
    lines.append('|---|---|---|---|---|---|\n')
    for strat in sorted(dt_analysis):
        d = dt_analysis[strat]
        if d.get('status') == 'no_data': continue
        lines.append(f"| {strat} | {d['trades']} | {d['win_rate']:.0%} | {d['expected_value']:.1f}€ | {d['sharpe']:.2f} | {'🔴' if d['sharpe'] < KILL_SHARPE_THRESHOLD else '🟢' if d['win_rate'] >= PROMOTE_WR_THRESHOLD else '🟡'} |\n")

    if dt_changes:
        lines.append('\n**Änderungen DT:**\n')
        for c in dt_changes: lines.append(f'- {c}\n')

    if ps_changes:
        lines.append('\n**Änderungen PS:**\n')
        for c in ps_changes: lines.append(f'- {c}\n')

    lines.append('\n---\n')

    with open(FEEDBACK_LOG, 'a') as f:
        f.writelines(lines)

def run():
    print(f"[Feedback Engine {datetime.now().strftime('%H:%M')}]")

    dt_analysis = analyze_dt_strategies()
    ps_analysis = analyze_ps_strategies()

    print(f"  DT-Strategien analysiert: {len(dt_analysis)}")
    print(f"  PS-Strategien analysiert: {len(ps_analysis)}")

    dt_changes = update_dt_weights(dt_analysis)
    ps_changes = update_ps_health(ps_analysis)

    all_changes = dt_changes + ps_changes
    write_log(dt_analysis, ps_analysis, dt_changes, ps_changes)

    if all_changes:
        print(f"  {len(all_changes)} Änderungen:")
        for c in all_changes:
            print(f"    {c}")
        print(f"CHANGES: {len(all_changes)}")
    else:
        print("  Keine Änderungen nötig.")
        print("KEIN_SIGNAL")

    # Summary für Briefings
    best = sorted([(s, d) for s,d in dt_analysis.items() if d.get('trades',0) >= 5],
                  key=lambda x: x[1].get('expected_value',0), reverse=True)
    if best:
        print(f"\nBeste DT-Strategie: {best[0][0]} (EV {best[0][1]['expected_value']:.1f}€, WR {best[0][1]['win_rate']:.0%})")

    return all_changes

if __name__ == '__main__':
    run()
