"""
Strategy Validator — Gate 1 der Trade-Pipeline
Prüft: Hat diese Strategie eine vollständige These?

Gibt zurück:
  {'valid': True, 'thesis': '...', 'negation': '...', 'horizon': '...'}
  {'valid': False, 'reason': 'Missing negation field'}
"""

import json
from pathlib import Path


def load_strategies(path: str = None) -> dict:
    if path is None:
        path = Path(__file__).parent.parent / 'data' / 'strategies.json'
    with open(path) as f:
        return json.load(f)


def validate_strategy(strategy_id: str, strategies: dict) -> dict:
    s = strategies.get(strategy_id)
    if not s:
        return {'valid': False, 'reason': f'Strategie {strategy_id} nicht gefunden'}

    required = ['thesis', 'negation', 'horizon', 'tickers']
    missing = [f for f in required if not s.get(f) and s.get(f) != []]

    if missing:
        return {'valid': False, 'reason': f'Fehlende Felder: {missing}'}

    if s.get('locked') or s.get('health') == 'paused':
        return {'valid': False, 'reason': f'Strategie pausiert: {s.get("pause_reason", s.get("lock_reason", ""))}'}

    return {
        'valid': True,
        'thesis': s['thesis'],
        'negation': s['negation'],
        'horizon': s['horizon'],
        'health': s.get('health', 'unknown')
    }


if __name__ == '__main__':
    import sys
    strats = load_strategies()
    ids = sys.argv[1:] if len(sys.argv) > 1 else list(strats.keys())[:10]
    for sid in ids:
        if sid.startswith('_'):
            continue
        r = validate_strategy(sid, strats)
        status = '✓' if r['valid'] else '✗'
        detail = r.get('thesis', r.get('reason', ''))[:70]
        print(f"{status} {sid}: {detail}")
