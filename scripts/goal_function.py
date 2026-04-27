#!/usr/bin/env python3
"""
goal_function.py — Phase 31: Explizite Utility für autonome Optimierung.

Bisher hat das System implizit "PnL maximieren" als Ziel. Das ist
gefährlich — System nimmt high-variance Trades, Drawdown explodiert,
PnL-Spitzen verdecken systematische Schwächen.

Jetzt: Explizite Goal-Function.
   utility = pnl_eur * 1.0
            + sharpe_score * 1000     # gewichtet hoch
            - max_drawdown_pct * 200   # negativ für tiefe Drawdowns
            - lone_concentration_eur * 0.5  # gegen Klumpenrisiko

CEO-Brain liest diese Function bei seiner Entscheidung. Er bewertet
nicht nur "wieviel kann ich verdienen?", sondern "wie wirkt sich
EXECUTE auf mein Goal-Score aus?".

Gleichzeitig läuft hier `compute_current_score()` täglich, schreibt
in data/goal_scores.jsonl. Die letzten 7 Tage = Performance-Trend.

Optimierungs-Loop (Phase 31b, später):
  Wenn Goal-Score 7d-Trend negativ → Schwellen verschärfen (CRV höher,
  position-size kleiner, sektor-cap enger). Ein RL-light approach.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB           = WS / 'data' / 'trading.db'
SCORES_LOG   = WS / 'data' / 'goal_scores.jsonl'
GOAL_CONFIG  = WS / 'data' / 'goal_function.json'

DEFAULT_WEIGHTS = {
    'pnl_eur_weight':       1.0,
    'sharpe_weight':     1000.0,
    'drawdown_weight':   -200.0,
    'concentration_weight': -0.5,
    'win_rate_target':     0.55,  # 55%
    'sharpe_target':       1.5,
    'max_drawdown_target': 0.10,  # 10% max DD
}


def _load_weights() -> dict:
    if GOAL_CONFIG.exists():
        try:
            return {**DEFAULT_WEIGHTS, **json.loads(GOAL_CONFIG.read_text(encoding='utf-8'))}
        except Exception:
            pass
    return DEFAULT_WEIGHTS


def _fetch_closed_trades(days: int = 30) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT pnl_eur, pnl_pct, COALESCE(close_date, entry_date) as date,
               ticker, strategy
        FROM paper_portfolio
        WHERE status IN ('WIN','LOSS','CLOSED')
          AND COALESCE(close_date, entry_date) >= ?
          AND pnl_eur IS NOT NULL
    """, (cutoff,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _fetch_open_positions() -> list[dict]:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT ticker, strategy, entry_price, shares
        FROM paper_portfolio WHERE status='OPEN'
    """).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        d['position_eur'] = (d['entry_price'] or 0) * (d['shares'] or 0)
        out.append(d)
    return out


def _sharpe(pnl_pct_series: list[float]) -> float:
    """Annualisierter Sharpe (vereinfacht — pro Trade als Tag-Equivalent)."""
    if len(pnl_pct_series) < 5:
        return 0
    m = mean(pnl_pct_series)
    s = pstdev(pnl_pct_series)
    if s == 0:
        return 0
    # Approx. tägliche Sharpe → annualisiert ×sqrt(252)
    return (m / s) * math.sqrt(252) if s > 0 else 0


def _max_drawdown(cum_pnls: list[float]) -> float:
    """Max-Drawdown als Prozent vom Peak."""
    if not cum_pnls:
        return 0
    peak = cum_pnls[0]
    max_dd = 0
    for v in cum_pnls:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def compute_current_score(window_days: int = 30) -> dict:
    """
    Returns: {
        utility, pnl_eur, sharpe, max_drawdown_pct, concentration,
        n_trades, win_rate, weights, timestamp
    }
    """
    weights = _load_weights()
    trades = _fetch_closed_trades(days=window_days)
    opens = _fetch_open_positions()

    n = len(trades)
    pnl_total = sum((t['pnl_eur'] or 0) for t in trades)
    wins = sum(1 for t in trades if (t['pnl_eur'] or 0) > 0)
    wr = (wins / n) if n else 0

    # Sharpe
    pnl_pcts = [t.get('pnl_pct') or 0 for t in trades]
    sharpe = _sharpe(pnl_pcts)

    # Max Drawdown (cumulative pnl)
    sorted_trades = sorted(trades, key=lambda t: t.get('date', ''))
    cum_pnl = []
    running = 25000  # base
    for t in sorted_trades:
        running += (t.get('pnl_eur') or 0)
        cum_pnl.append(running)
    max_dd = _max_drawdown(cum_pnl)

    # Concentration: größte Position vs total OPEN-EUR
    total_open = sum(p['position_eur'] for p in opens)
    largest = max((p['position_eur'] for p in opens), default=0)
    concentration = (largest / total_open) if total_open > 0 else 0
    # Lone concentration (>30% in einer Position)
    lone = max(0, largest - 0.30 * total_open)

    # Utility-Berechnung
    utility = (
        pnl_total * weights['pnl_eur_weight']
        + sharpe   * weights['sharpe_weight']
        + (-max_dd * 100) * weights['drawdown_weight']  # max_dd in % (z.B. 0.05)
        + lone     * weights['concentration_weight']
    )

    return {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'window_days': window_days,
        'utility': round(utility, 1),
        'pnl_eur': round(pnl_total, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'concentration_largest_pct': round(concentration * 100, 1),
        'lone_concentration_eur': round(lone, 0),
        'n_trades': n,
        'win_rate': round(wr * 100, 1),
        'weights': weights,
        # Targets
        'on_target_winrate':  wr >= weights['win_rate_target'],
        'on_target_sharpe':   sharpe >= weights['sharpe_target'],
        'on_target_drawdown': max_dd <= weights['max_drawdown_target'],
    }


def log_score(score: dict) -> None:
    SCORES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SCORES_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(score, ensure_ascii=False) + '\n')


def trend_7d() -> dict:
    """Liest letzte 7 Scores aus Log, berechnet Trend."""
    if not SCORES_LOG.exists():
        return {'trend': 'no_data', 'n': 0}
    lines = SCORES_LOG.read_text(encoding='utf-8').strip().split('\n')[-7:]
    scores = []
    for ln in lines:
        try:
            scores.append(json.loads(ln))
        except Exception:
            continue
    if len(scores) < 3:
        return {'trend': 'insufficient_data', 'n': len(scores)}

    utilities = [s['utility'] for s in scores]
    first = utilities[0]
    last = utilities[-1]
    trend = 'improving' if last > first * 1.05 else 'declining' if last < first * 0.95 else 'flat'
    return {
        'trend': trend,
        'n': len(scores),
        'first_utility': first,
        'last_utility': last,
        'change_pct': round((last - first) / abs(first) * 100, 1) if first != 0 else 0,
    }


def main() -> int:
    print(f'─── Goal-Function Score @ {datetime.now().isoformat(timespec="seconds")} ───')
    score = compute_current_score(window_days=30)
    print(json.dumps(score, indent=2))
    log_score(score)

    trend = trend_7d()
    print(f'\nTrend (7d): {trend}')

    # Discord daily push (1x am Tag)
    try:
        from discord_dispatcher import send_alert, TIER_LOW
        targets_status = (
            f"WR {'✅' if score['on_target_winrate'] else '❌'} {score['win_rate']}%/55% | "
            f"Sharpe {'✅' if score['on_target_sharpe'] else '❌'} {score['sharpe']}/1.5 | "
            f"DD {'✅' if score['on_target_drawdown'] else '❌'} {score['max_drawdown_pct']}%/10%"
        )
        msg = (
            f'🎯 **Goal-Function Score** ({score["window_days"]}d)\n'
            f'Utility: **{score["utility"]:.0f}** | PnL: {score["pnl_eur"]:+.0f}€\n'
            f'{targets_status}\n'
            f'Trend (7d): **{trend.get("trend","?")}** ({trend.get("change_pct",0):+.1f}%)\n'
            f'Konzentration: {score["concentration_largest_pct"]}% in größter Position'
        )
        send_alert(msg, tier=TIER_LOW, category='goal_score',
                   dedupe_key=f'goal_{datetime.now().strftime("%Y-%m-%d")}')
    except Exception as e:
        print(f'Discord error: {e}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
