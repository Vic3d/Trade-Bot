#!/usr/bin/env python3
"""
learning_insights_reader.py — Phase 44b/A1: Lese Insights aus Lernpipeline.

Verifiziert: trading_learnings.json wird täglich befüllt mit market_scores
und time_scores, von 0 von 5 Decision-Modulen gelesen. Dieses Modul
schließt die Lücke.

Nutzung:
  from learning_insights_reader import (
      get_time_penalty, get_region_penalty,
      check_hard_block, get_combined_adjustment,
  )

  pen = get_time_penalty()           # aktuelle Stunde → Penalty
  pen = get_region_penalty(ticker)   # Region anhand Suffix
  blocked, reason = check_hard_block(ticker)  # bei extremer Schwäche

Schwellwerte (verifiziert aus eigenen Daten):
  HARD_BLOCK:     WR < 25% bei n >= 20
  PENALTY -0.10:  WR < 35% bei n >= 20
  PENALTY -0.05:  WR < 45% bei n >= 20
  NEUTRAL:        WR 45-55% oder n < 20
  BONUS +0.05:    WR > 55% bei n >= 20
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

LEARNINGS_FILE = WS / 'data' / 'trading_learnings.json'
CET = ZoneInfo('Europe/Berlin')

# Schwellwerte
MIN_N_FOR_DECISION = 20         # unter 20 Trades: nicht statistisch tragend
HARD_BLOCK_WR_THRESHOLD = 0.25
PENALTY_BIG_WR_THRESHOLD = 0.35   # → -0.10 Penalty
PENALTY_SMALL_WR_THRESHOLD = 0.45  # → -0.05 Penalty
BONUS_WR_THRESHOLD = 0.55          # → +0.05 Bonus


def _load_learnings() -> dict:
    if not LEARNINGS_FILE.exists():
        return {}
    try:
        return json.loads(LEARNINGS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _hour_to_bucket(hour: int) -> str:
    """Mapping Stunde → Time-Bucket (synchron zu paper_learning_engine.time_bucket)."""
    if 7 <= hour < 11:
        return 'morning'
    if 11 <= hour < 14:
        return 'midday'
    if 14 <= hour < 18:
        return 'afternoon'
    return 'evening'


def _ticker_to_region(ticker: str) -> str:
    """Mapping ticker → market region (synchron zu paper_learning_engine.infer_market)."""
    if not ticker:
        return 'US'
    if ticker.endswith(('.DE', '.AS', '.PA', '.CO', '.MI', '.MC', '.VI', '.SW')):
        return 'EU'
    if ticker.endswith('.L'):
        return 'UK'
    if ticker.endswith('.OL'):
        return 'NO'
    if ticker.endswith(('.T', '.HK', '.KS', '.SS')):
        return 'ASIA'
    return 'US'


def _classify(stats: dict | None) -> tuple[str, float, str]:
    """Klassifiziere Stats → (severity, conviction_delta, reason).

    severity ∈ {'BLOCK', 'STRONG_PENALTY', 'PENALTY', 'NEUTRAL', 'BONUS'}
    """
    if not stats or not isinstance(stats, dict):
        return 'NEUTRAL', 0.0, 'no_stats'

    n = stats.get('trades', 0) or 0
    wr = stats.get('win_rate', 0) or 0
    pnl = stats.get('total_pnl_eur', 0) or 0

    if n < MIN_N_FOR_DECISION:
        return 'NEUTRAL', 0.0, f'n<{MIN_N_FOR_DECISION} (n={n})'

    if wr < HARD_BLOCK_WR_THRESHOLD:
        return ('BLOCK', -0.20,
                f'WR {wr:.0%} (n={n}, PnL {pnl:+.0f}€) < {HARD_BLOCK_WR_THRESHOLD:.0%}')
    if wr < PENALTY_BIG_WR_THRESHOLD:
        return ('STRONG_PENALTY', -0.10,
                f'WR {wr:.0%} (n={n}, PnL {pnl:+.0f}€) < {PENALTY_BIG_WR_THRESHOLD:.0%}')
    if wr < PENALTY_SMALL_WR_THRESHOLD:
        return ('PENALTY', -0.05,
                f'WR {wr:.0%} (n={n}, PnL {pnl:+.0f}€) < {PENALTY_SMALL_WR_THRESHOLD:.0%}')
    if wr > BONUS_WR_THRESHOLD:
        return ('BONUS', 0.05,
                f'WR {wr:.0%} (n={n}, PnL {pnl:+.0f}€) > {BONUS_WR_THRESHOLD:.0%}')
    return 'NEUTRAL', 0.0, f'WR {wr:.0%} neutral (n={n})'


def get_time_penalty(now_cet: datetime | None = None) -> dict:
    """Liefere conviction-delta basierend auf aktueller Stunde + time_scores.

    Returns:
      {'severity': str, 'delta': float, 'reason': str, 'bucket': str}
    """
    if now_cet is None:
        now_cet = datetime.now(CET)
    bucket = _hour_to_bucket(now_cet.hour)
    learnings = _load_learnings()
    time_scores = learnings.get('time_scores', {}) or {}
    stats = time_scores.get(bucket)
    severity, delta, reason = _classify(stats)
    return {
        'severity': severity,
        'delta':    delta,
        'reason':   f'time[{bucket}] {reason}',
        'bucket':   bucket,
    }


def get_region_penalty(ticker: str) -> dict:
    """Liefere conviction-delta basierend auf Ticker-Region + market_scores."""
    region = _ticker_to_region(ticker)
    learnings = _load_learnings()
    market_scores = learnings.get('market_scores', {}) or {}
    stats = market_scores.get(region)
    severity, delta, reason = _classify(stats)
    return {
        'severity': severity,
        'delta':    delta,
        'reason':   f'region[{region}] {reason}',
        'region':   region,
    }


def check_hard_block(ticker: str, now_cet: datetime | None = None) -> tuple[bool, str]:
    """Prüfe ob Trade hard-blocked werden soll.

    Returns: (should_block, reason)
    """
    t = get_time_penalty(now_cet)
    r = get_region_penalty(ticker)
    if t['severity'] == 'BLOCK':
        return True, f'time-block: {t["reason"]}'
    if r['severity'] == 'BLOCK':
        return True, f'region-block: {r["reason"]}'
    # Combined extreme weakness
    if t['severity'] == 'STRONG_PENALTY' and r['severity'] == 'STRONG_PENALTY':
        return True, f'combined-block: {t["reason"]} + {r["reason"]}'
    return False, ''


def get_combined_adjustment(ticker: str, now_cet: datetime | None = None) -> dict:
    """Kombiniere time + region zu einer Conviction-Delta.

    Returns:
      {'block': bool, 'block_reason': str | None,
       'delta': float, 'reasons': list[str]}
    """
    blocked, br = check_hard_block(ticker, now_cet)
    if blocked:
        return {'block': True, 'block_reason': br, 'delta': 0.0, 'reasons': []}
    t = get_time_penalty(now_cet)
    r = get_region_penalty(ticker)
    delta = t['delta'] + r['delta']
    # Cap auf [-0.20, +0.10] (Bonus konservativer als Penalty)
    delta = max(-0.20, min(0.10, delta))
    reasons = []
    if t['delta'] != 0:
        reasons.append(t['reason'])
    if r['delta'] != 0:
        reasons.append(r['reason'])
    return {'block': False, 'block_reason': None,
            'delta': round(delta, 3), 'reasons': reasons}


def main() -> int:
    """CLI: Aktuellen Stand zeigen für gegebene Tickers."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickers', nargs='+', default=['NVDA', 'EQNR.OL', 'BAYN.DE', 'TTE.PA', 'BABA'])
    args = ap.parse_args()

    now = datetime.now(CET)
    print(f'═══ Learning Insights @ {now.strftime("%Y-%m-%d %H:%M %Z")} ═══')
    print()

    learnings = _load_learnings()
    print(f'time_scores:   {len(learnings.get("time_scores", {}))} buckets')
    print(f'market_scores: {len(learnings.get("market_scores", {}))} regions')
    print()

    print('--- Time-Bucket-Status (jetzt) ---')
    t = get_time_penalty(now)
    icon = '🔴' if t['severity'] == 'BLOCK' else '🟠' if 'PENALTY' in t['severity'] else '🟢' if t['severity'] == 'BONUS' else '⚪'
    print(f'  {icon} {t["bucket"]:<10} {t["severity"]:<16} delta={t["delta"]:+.2f} | {t["reason"]}')
    print()

    print('--- Per Ticker ---')
    for tk in args.tickers:
        adj = get_combined_adjustment(tk, now)
        if adj['block']:
            print(f'  🔴 {tk:<10} BLOCK — {adj["block_reason"]}')
        else:
            d = adj['delta']
            icon = '🟠' if d < 0 else '🟢' if d > 0 else '⚪'
            print(f'  {icon} {tk:<10} delta={d:+.2f} | {"; ".join(adj["reasons"]) or "neutral"}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
