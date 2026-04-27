#!/usr/bin/env python3
"""
goal_auto_adjust.py — Phase 31b: RL-light Auto-Adjust auf Goal-Trend.

Läuft täglich 22:45 (nach goal_function.py um 22:30).

Logik:
  1. Liest letzte 7 Goal-Scores aus goal_scores.jsonl
  2. Berechnet Trend (Veränderung first → last)
  3. Wenn Trend "declining" (>5% Verschlechterung):
       → System wird vorsichtiger:
         min_crv  += 0.15
         max_position_pct  -= 1.0
         sector_cap_pct    -= 3.0
  4. Wenn Trend "improving" (>5% Verbesserung) UND alle Targets ✅:
       → System wird aggressiver:
         min_crv  -= 0.10
         max_position_pct  += 0.5
         sector_cap_pct    += 2.0

Bounded (so dass System nie wild wird):
  min_crv:           [1.3, 3.5]
  max_position_pct:  [8.0, 20.0]
  sector_cap_pct:   [15.0, 40.0]

Schreibt in `data/autonomy_config.json`:
{
  "min_crv": 1.5,
  "max_position_pct": 14.0,
  "sector_cap_pct": 28.0,
  "last_adjusted": "...",
  "adjustment_reason": "trend_improving",
  "trend_change_pct": +12.3
}

paper_trade_engine + risk_based_sizing + check_sector_exposure
LESEN diese Werte (mit Default-Fallback wenn File fehlt).

Hard Floor/Ceiling sind unverhandelbar — auch RL kann nicht alles
auf 0 setzen oder ins Risk fahren.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

SCORES_LOG     = WS / 'data' / 'goal_scores.jsonl'
CONFIG_FILE    = WS / 'data' / 'autonomy_config.json'

# Bounded ranges
BOUNDS = {
    'min_crv':          (1.3, 3.5),
    'max_position_pct': (8.0, 20.0),
    'sector_cap_pct':  (15.0, 40.0),
}

DEFAULTS = {
    'min_crv':          1.3,
    'max_position_pct': 15.0,
    'sector_cap_pct':  30.0,
}

# Adjust-Schritte
TIGHTEN_STEP = {
    'min_crv':          +0.15,
    'max_position_pct': -1.0,
    'sector_cap_pct':   -3.0,
}
LOOSEN_STEP = {
    'min_crv':          -0.10,
    'max_position_pct': +0.5,
    'sector_cap_pct':   +2.0,
}

TREND_THRESHOLD_PCT = 5.0  # ±5% triggert Anpassung
MIN_SCORES_FOR_ADJUST = 3


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULTS, **json.loads(CONFIG_FILE.read_text(encoding='utf-8'))}
        except Exception:
            pass
    return dict(DEFAULTS)


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')


def _load_recent_scores(n: int = 7) -> list[dict]:
    if not SCORES_LOG.exists():
        return []
    lines = SCORES_LOG.read_text(encoding='utf-8').strip().split('\n')[-n:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _bound(name: str, value: float) -> float:
    lo, hi = BOUNDS[name]
    return max(lo, min(hi, value))


def adjust(scores: list[dict]) -> dict:
    """
    Returns: {
        action: 'tighten' | 'loosen' | 'hold',
        reason: str,
        old_config: dict,
        new_config: dict,
        trend_change_pct: float,
    }
    """
    cfg = _load_config()
    old = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}

    if len(scores) < MIN_SCORES_FOR_ADJUST:
        return {
            'action': 'hold',
            'reason': f'insufficient_scores ({len(scores)} < {MIN_SCORES_FOR_ADJUST})',
            'old_config': old, 'new_config': old, 'trend_change_pct': 0,
        }

    first_util = scores[0].get('utility', 0)
    last_util  = scores[-1].get('utility', 0)
    if first_util == 0:
        return {'action': 'hold', 'reason': 'first_util_zero',
                'old_config': old, 'new_config': old, 'trend_change_pct': 0}
    change_pct = (last_util - first_util) / abs(first_util) * 100

    # Targets müssen für Loosen alle ✅ sein (sonst nicht aggressiver werden)
    last_score = scores[-1]
    all_targets_met = (
        last_score.get('on_target_winrate', False)
        and last_score.get('on_target_sharpe', False)
        and last_score.get('on_target_drawdown', False)
    )

    new_cfg = dict(old)
    if change_pct < -TREND_THRESHOLD_PCT:
        action = 'tighten'
        reason = f'trend_declining ({change_pct:+.1f}% in {len(scores)}d)'
        for k, step in TIGHTEN_STEP.items():
            new_cfg[k] = round(_bound(k, old[k] + step), 2)
    elif change_pct > TREND_THRESHOLD_PCT and all_targets_met:
        action = 'loosen'
        reason = f'trend_improving ({change_pct:+.1f}%) + all targets met'
        for k, step in LOOSEN_STEP.items():
            new_cfg[k] = round(_bound(k, old[k] + step), 2)
    else:
        action = 'hold'
        if change_pct > TREND_THRESHOLD_PCT and not all_targets_met:
            reason = f'improving but targets not met → hold'
        else:
            reason = f'stable ({change_pct:+.1f}%, threshold ±{TREND_THRESHOLD_PCT}%)'

    if action != 'hold':
        new_cfg['last_adjusted'] = datetime.now().isoformat(timespec='seconds')
        new_cfg['adjustment_reason'] = reason
        new_cfg['trend_change_pct'] = round(change_pct, 1)
        new_cfg['scores_n'] = len(scores)
        _save_config(new_cfg)

    return {
        'action': action, 'reason': reason,
        'old_config': old, 'new_config': new_cfg,
        'trend_change_pct': round(change_pct, 1),
    }


def main() -> int:
    print(f'─── Goal-Auto-Adjust @ {datetime.now().isoformat(timespec="seconds")} ───')
    scores = _load_recent_scores(n=7)
    print(f'Loaded {len(scores)} recent goal-scores')

    result = adjust(scores)
    print(f"Action: {result['action']}")
    print(f"Reason: {result['reason']}")
    print(f"Trend: {result['trend_change_pct']:+.1f}%")
    print(f"\nOld config: {result['old_config']}")
    print(f"New config: {result['new_config']}")

    # Discord nur bei tatsächlicher Anpassung
    if result['action'] != 'hold':
        try:
            from discord_dispatcher import send_alert, TIER_LOW
            old, new = result['old_config'], result['new_config']
            deltas = []
            for k in ('min_crv', 'max_position_pct', 'sector_cap_pct'):
                if old[k] != new[k]:
                    deltas.append(f"`{k}`: {old[k]} → {new[k]}")
            icon = '🔒' if result['action'] == 'tighten' else '🔓'
            msg = (
                f'{icon} **Auto-Adjust: {result["action"].upper()}**\n'
                f'Reason: {result["reason"]}\n'
                + '\n'.join(deltas)
                + f'\n_(Bounds: CRV [1.3, 3.5], Pos% [8, 20], Sektor% [15, 40])_'
            )
            send_alert(msg, tier=TIER_LOW, category='auto_adjust',
                       dedupe_key=f'adjust_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception as e:
            print(f'Discord error: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
