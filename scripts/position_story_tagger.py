#!/usr/bin/env python3
"""
position_story_tagger.py — Phase 45aq Layer E1 (Victor 2026-05-11).

Tagt jede Position mit einer Story-Kategorie statt nur Strategy-ID.
Beispiel: GDX/PAAS/WPM + ARKG sind aktuell beide Teil von "FED_PIVOT_USD_WEAK"
weil beide von Fed-Pivot + USD-Schwäche profitieren.

Story-Heuristik:
  - Edelmetall-Miner + Biotech (rate-sensitive) → FED_PIVOT_RISK_ON
  - Öl + Tanker → HORMUZ_ENERGY_SHOCK
  - Defense + Eastern-Europe-Stoffe → GEOPOLITICAL_TENSION
  - Tech-Semi + AI-Hyperscaler-Power → AI_INFRASTRUCTURE_DEMAND
  - Solar/Renewable + Uranium → ENERGY_TRANSITION

Output: data/position_stories.json + ergänzt current_truth-Block.
Run: täglich 06:25 (vor Strategist).
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT_JSON = WS / 'data' / 'position_stories.json'

# Story-Map: Cluster → Story
CLUSTER_STORY = {
    'GOLD_SILVER_MINER':  'FED_PIVOT_USD_WEAK',
    'BIOTECH':            'FED_PIVOT_RATE_SENSITIVE',
    'BANK_FINANCIAL':     'YIELD_CURVE',
    'OIL_ENERGY':         'HORMUZ_ENERGY_SHOCK',
    'OIL_TANKER':         'HORMUZ_ENERGY_SHOCK',
    'COPPER_BASE_METAL':  'INDUSTRIAL_DEMAND_AI',
    'URANIUM_NUCLEAR':    'ENERGY_TRANSITION',
    'DEFENSE':            'GEOPOLITICAL_TENSION',
    'TECH_SEMI':          'AI_INFRASTRUCTURE',
    'SOLAR_RENEWABLE':    'ENERGY_TRANSITION',
    'CONSUMER_STAPLES':   'DEFENSIVE_BUCKET',
    'HEALTHCARE_PHARMA':  'DEFENSIVE_BUCKET',
    'UTILITIES':          'DEFENSIVE_BUCKET',
    'AGRI_FERTILIZER':    'FOOD_SECURITY',
}


def analyze() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from portfolio_concentration_guard import _open_positions_with_value, _portfolio_total_eur
    except Exception as e:
        return {'error': f'import: {e}'}

    positions = _open_positions_with_value()
    total = _portfolio_total_eur()
    if not positions:
        return {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'note': 'no_positions'}

    story_exposure: dict = {}
    tagged_positions = []
    for p in positions:
        cluster = p.get('cluster') or 'UNCLUSTERED'
        story = CLUSTER_STORY.get(cluster, 'UNTAGGED')
        value = p.get('current_value_eur', 0)
        story_exposure[story] = story_exposure.get(story, 0) + value
        tagged_positions.append({
            'ticker': p['ticker'],
            'strategy': p['strategy'],
            'cluster': cluster,
            'story': story,
            'value_eur': round(value, 2),
        })

    story_pcts = {s: round(v / total * 100, 1) for s, v in story_exposure.items()}

    # Konzentrations-Warning: wenn eine Story > 50%
    warnings = []
    for s, pct in story_pcts.items():
        if pct > 50 and s != 'UNTAGGED':
            warnings.append(f"Story '{s}' = {pct}% Portfolio — Konzentrations-Risk")

    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'portfolio_total_eur': round(total, 2),
        'tagged_positions': tagged_positions,
        'story_exposure_pct': story_pcts,
        'warnings': warnings,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False),
                        encoding='utf-8')
    return out


def main() -> int:
    r = analyze()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
