#!/usr/bin/env python3
"""
stress_scenario_tester.py — Phase 45aq Layer D3 (Victor 2026-05-11).

Tägliche Stress-Test der offenen Positionen unter 5 Szenarien:
  S1: Gold-Crash -10% (alle Edelmetall-Positionen reagieren)
  S2: USD-Strength +3% (alle Non-US-Assets -3%)
  S3: VIX-Spike +50% → equity -8% breit
  S4: Brent-Crash -15% → Energy -10%, Tanker -15%
  S5: Risk-Off-Cascade: SPY -5%, alle High-Beta -10%

Output: data/stress_scenarios.json mit max-Drawdown pro Szenario.
Warnung in ceo_inbox wenn irgendein Szenario <-8% Portfolio-Drawdown.
Run: täglich 22:30 nach Tranche-Check.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT_JSON = WS / 'data' / 'stress_scenarios.json'

# Pro Cluster: Beta zu Stress-Szenarien
CLUSTER_BETAS = {
    'GOLD_SILVER_MINER': {'gold_crash': 1.5, 'usd_strength': -0.8, 'vix_spike': 0.3,
                           'brent_crash': 0.1, 'risk_off': 0.5},
    'OIL_ENERGY':        {'gold_crash': 0.0, 'usd_strength': -0.3, 'vix_spike': -0.5,
                           'brent_crash': 1.4, 'risk_off': -0.8},
    'OIL_TANKER':        {'gold_crash': 0.0, 'usd_strength': -0.2, 'vix_spike': -0.6,
                           'brent_crash': 1.5, 'risk_off': -0.9},
    'TECH_SEMI':         {'gold_crash': 0.0, 'usd_strength': -0.4, 'vix_spike': -1.0,
                           'brent_crash': 0.0, 'risk_off': -1.2},
    'BANK_FINANCIAL':    {'gold_crash': 0.0, 'usd_strength': 0.2, 'vix_spike': -0.8,
                           'brent_crash': 0.0, 'risk_off': -1.0},
    'BIOTECH':           {'gold_crash': 0.0, 'usd_strength': -0.3, 'vix_spike': -0.7,
                           'brent_crash': 0.0, 'risk_off': -1.1},
    'DEFENSE':           {'gold_crash': 0.0, 'usd_strength': 0.1, 'vix_spike': -0.2,
                           'brent_crash': 0.0, 'risk_off': -0.3},
    'UTILITIES':         {'gold_crash': 0.0, 'usd_strength': 0.0, 'vix_spike': -0.3,
                           'brent_crash': 0.0, 'risk_off': -0.4},
}

SCENARIOS = {
    'gold_crash_10pct':    {'gold_crash': -10},
    'usd_strength_3pct':   {'usd_strength': -3},
    'vix_spike_50pct':     {'vix_spike': -8},
    'brent_crash_15pct':   {'brent_crash': -15},
    'risk_off_cascade':    {'risk_off': -5},
}


def run_stress_test() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from portfolio_concentration_guard import _open_positions_with_value, _portfolio_total_eur, _ticker_cluster
    except Exception as e:
        return {'error': f'import: {e}'}

    positions = _open_positions_with_value()
    total = _portfolio_total_eur()
    if total <= 0 or not positions:
        return {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'note': 'no_positions'}

    results: dict = {}
    for scen_name, scen_factors in SCENARIOS.items():
        pos_impact = 0.0
        for p in positions:
            cluster = p.get('cluster') or _ticker_cluster(p['ticker'])
            betas = CLUSTER_BETAS.get(cluster, {'risk_off': -0.5})  # Default: leicht negativ
            shock = 0.0
            for factor, pct in scen_factors.items():
                shock += betas.get(factor, 0) * pct
            position_loss = p.get('current_value_eur', 0) * (shock / 100)
            pos_impact += position_loss
        impact_pct = pos_impact / total * 100
        results[scen_name] = {
            'eur_impact': round(pos_impact, 2),
            'portfolio_pct': round(impact_pct, 2),
        }

    worst_scenario = min(results.items(), key=lambda x: x[1]['portfolio_pct'])
    worst_pct = worst_scenario[1]['portfolio_pct']

    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'portfolio_total_eur': round(total, 2),
        'scenarios': results,
        'worst_scenario': worst_scenario[0],
        'worst_pct': worst_pct,
        'alert': worst_pct < -8,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')

    if out['alert']:
        try:
            from ceo_inbox import write_event
            write_event(
                event_type='stress_alert',
                message=f"Worst scenario {worst_scenario[0]}: {worst_pct:.1f}% Portfolio-DD",
                severity='warning', category='health',
                user_pinged=False, payload=out,
            )
        except Exception: pass
    return out


def main() -> int:
    r = run_stress_test()
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
