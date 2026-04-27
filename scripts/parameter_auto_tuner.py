#!/usr/bin/env python3
"""
parameter_auto_tuner.py — Phase 30b: Auto-Tuning von Trade-Parametern.

Wöchentlich Mo 06:00 CEST. Liest closed Trades letzte 60d, berechnet
pro Strategie-Typ (PS_*, PT, PM, S*) die empirisch optimalen Parameter:

  1. optimal_stop_pct
       — Distribution der Loss-Trades. Wenn ATR-mean*1.5 < 8% Default →
         engerer Stop empfohlen. Sonst breiter.
  2. optimal_min_crv
       — Cutoff-Analyse: ab welchem CRV bricht Win-Rate ein?
  3. optimal_max_hold_days
       — Median-Hold-Time von Wins vs Losses. Setzt max bei 75% Quantil
         der Win-Hold-Times.

Schreibt Empfehlungen in `data/strategy_params_tuned.json`:
{
  "tuned_at": "...",
  "by_strategy_type": {
    "PS_": {"stop_pct": 6.5, "min_crv": 1.8, "max_hold_days": 18, "n_trades": 22},
    "PT":  {...},
    ...
  }
}

paper_trade_engine.py liest beim nächsten Trade diese Werte (mit Fallback
auf Default wenn n_trades < 10).

Discord-Push:
  📐 Parameter-Tuning Wochen-Update
  PS_*: Stop 8% → 6.5%, Min-CRV 1.3 → 1.8 (basierend auf 22 Trades)
  PT:   keine Änderung (n=4, zu wenig Daten)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB           = WS / 'data' / 'trading.db'
TUNED_FILE   = WS / 'data' / 'strategy_params_tuned.json'

WINDOW_DAYS  = 60
MIN_TRADES   = 8   # Minimum für Tuning-Empfehlung

# Strategie-Type Prefixes (längster wins)
TYPE_PREFIXES = ['PS_', 'PT', 'PM', 'S']

# Defaults zum Vergleich
DEFAULTS = {
    'stop_pct':       8.0,
    'min_crv':        1.3,
    'max_hold_days': 14,
}


def _classify(strategy: str) -> str | None:
    """Mapt strategy → type-prefix."""
    s = strategy.upper()
    best, best_len = None, -1
    for p in TYPE_PREFIXES:
        if s.startswith(p) and len(p) > best_len:
            best, best_len = p, len(p)
    return best


def _fetch_closed_trades() -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%d')
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT ticker, strategy, entry_price, stop_price, target_price,
               close_price, pnl_eur, pnl_pct, entry_date, close_date,
               exit_type
        FROM paper_portfolio
        WHERE status IN ('WIN','LOSS','CLOSED')
          AND COALESCE(close_date, entry_date) >= ?
          AND entry_price > 0
    """, (cutoff,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _hold_days(t: dict) -> int:
    try:
        e = datetime.fromisoformat(str(t['entry_date'])[:19])
        c = datetime.fromisoformat(str(t['close_date'])[:19])
        return max(0, (c - e).days)
    except Exception:
        return 0


def _trade_crv(t: dict) -> float:
    """Entry/Stop/Target → eingeplantes CRV."""
    e, s, tg = t['entry_price'], t.get('stop_price') or 0, t.get('target_price') or 0
    if e <= 0 or s <= 0 or tg <= 0 or s >= e:
        return 0
    return (tg - e) / (e - s)


def _quantile(vals: list[float], q: float) -> float:
    if not vals:
        return 0
    s = sorted(vals)
    idx = max(0, min(len(s) - 1, int(q * len(s))))
    return s[idx]


def tune_for_type(trades: list[dict]) -> dict:
    """Berechnet 3 Empfehlungen aus Trade-Sample."""
    n = len(trades)
    if n < MIN_TRADES:
        return {'n_trades': n, 'reason': 'insufficient_data'}

    wins = [t for t in trades if (t.get('pnl_eur') or 0) > 0]
    losses = [t for t in trades if (t.get('pnl_eur') or 0) <= 0]
    wr = len(wins) / n * 100

    # 1. STOP-PCT: max 75%-Quantil der Loss-pnl_pct (wenn 75% der Losses
    #    bei -X% lagen, ist X eine sinnvolle Stop-Distanz)
    loss_pcts = [abs(t.get('pnl_pct') or 0) for t in losses if t.get('pnl_pct') is not None]
    optimal_stop = round(_quantile(loss_pcts, 0.75), 1) if loss_pcts else DEFAULTS['stop_pct']
    # Bound: nicht enger als 3%, nicht weiter als 12%
    optimal_stop = max(3.0, min(12.0, optimal_stop))

    # 2. MIN-CRV: was war das CRV bei den Wins vs Losses?
    win_crvs = [_trade_crv(t) for t in wins if _trade_crv(t) > 0]
    loss_crvs = [_trade_crv(t) for t in losses if _trade_crv(t) > 0]
    if win_crvs and loss_crvs:
        # Nimm den 25%-Quantil von Wins als Schwelle
        optimal_crv = round(_quantile(win_crvs, 0.25), 1)
    else:
        optimal_crv = DEFAULTS['min_crv']
    optimal_crv = max(1.2, min(3.5, optimal_crv))

    # 3. MAX-HOLD-DAYS: 75%-Quantil der Win-Hold-Times
    win_holds = [_hold_days(t) for t in wins]
    if win_holds:
        optimal_hold = max(3, int(_quantile(win_holds, 0.75)))
    else:
        optimal_hold = DEFAULTS['max_hold_days']
    optimal_hold = min(40, optimal_hold)

    return {
        'n_trades':       n,
        'win_rate_pct':   round(wr, 1),
        'stop_pct':       optimal_stop,
        'min_crv':        optimal_crv,
        'max_hold_days':  optimal_hold,
        'avg_loss_pct':   round(mean(loss_pcts), 1) if loss_pcts else None,
        'median_win_hold': int(median(win_holds)) if win_holds else None,
    }


def main() -> int:
    print(f'─── Parameter-Auto-Tuner @ {datetime.now().isoformat(timespec="seconds")} ───')
    trades = _fetch_closed_trades()
    print(f'Loaded {len(trades)} closed trades (last {WINDOW_DAYS}d)')

    # Group by type
    by_type: dict[str, list[dict]] = {p: [] for p in TYPE_PREFIXES}
    for t in trades:
        tp = _classify(t.get('strategy', ''))
        if tp:
            by_type[tp].append(t)

    result = {
        'tuned_at': datetime.now().isoformat(timespec='seconds'),
        'window_days': WINDOW_DAYS,
        'by_strategy_type': {},
    }

    summary_lines = []
    for tp, ts in by_type.items():
        tune = tune_for_type(ts)
        result['by_strategy_type'][tp] = tune
        n = tune['n_trades']
        if n < MIN_TRADES:
            summary_lines.append(f'  · `{tp}` n={n} — zu wenig Daten')
            continue
        # Vergleich mit Default
        delta_stop = tune['stop_pct'] - DEFAULTS['stop_pct']
        delta_crv  = tune['min_crv'] - DEFAULTS['min_crv']
        summary_lines.append(
            f"  · `{tp}` n={n} WR={tune['win_rate_pct']:.0f}% "
            f"→ Stop {tune['stop_pct']:.1f}% ({delta_stop:+.1f}), "
            f"CRV {tune['min_crv']:.1f} ({delta_crv:+.1f}), "
            f"Hold {tune['max_hold_days']}d"
        )

    TUNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    TUNED_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Saved → {TUNED_FILE}')

    # Discord-Push (nur wenn min. 1 Type genug Daten hatte)
    has_data = any(t.get('n_trades', 0) >= MIN_TRADES
                   for t in result['by_strategy_type'].values())
    if has_data:
        msg = (f'📐 **Parameter-Auto-Tuning** ({WINDOW_DAYS}d Daten)\n\n'
               + '\n'.join(summary_lines)
               + '\n\n_Werte in `data/strategy_params_tuned.json`. '
               'Werden vom paper_trade_engine als Override gelesen (Default-Fallback wenn n<8)._')
        try:
            from discord_dispatcher import send_alert, TIER_LOW
            send_alert(msg, tier=TIER_LOW, category='param_tuning',
                       dedupe_key=f'tune_{datetime.now().strftime("%Y-W%U")}')
        except Exception as e:
            print(f'Discord error: {e}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
