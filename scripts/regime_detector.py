#!/usr/bin/env python3
"""
regime_detector.py — VIX-basierter Markt-Regime-Detektor
Klassifiziert: CALM / NORMAL / ELEVATED / PANIC
Passt Positionsgrößen und Stop-Levels an.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from price_db import get_prices, init_tables

# Regime-Definitionen
REGIMES = {
    'CALM':     {'vix_min': 0,  'vix_max': 15,  'position_factor': 1.0,  'stop_factor': 1.0,  'desc': 'Trend-Following aggressiv, volle Positionsgrößen'},
    'NORMAL':   {'vix_min': 15, 'vix_max': 22,  'position_factor': 1.0,  'stop_factor': 1.0,  'desc': 'Standard-Strategien, normale Positionsgrößen'},
    'ELEVATED': {'vix_min': 22, 'vix_max': 30,  'position_factor': 0.75, 'stop_factor': 1.5,  'desc': 'Breitere Stops (+50%), kleinere Positionen (75%), nur starke Setups'},
    'PANIC':    {'vix_min': 30, 'vix_max': 999, 'position_factor': 0.50, 'stop_factor': 2.0,  'desc': 'Nur Hedges (Gold, VIX-Plays), minimale Positionsgrößen (50%)'},
}

# Welche Strategien in welchem Regime erlaubt
STRATEGY_REGIMES = {
    'PS1': {'regimes': ['NORMAL', 'ELEVATED', 'PANIC'], 'reason': 'Öl profitiert von Krisen'},
    'PS2': {'regimes': ['NORMAL', 'ELEVATED'],           'reason': 'Tanker brauchen stabilen Ölmarkt'},
    'PS3': {'regimes': ['NORMAL', 'ELEVATED', 'PANIC'], 'reason': 'Defense profitiert von Krisen'},
    'PS4': {'regimes': ['ELEVATED', 'PANIC'],            'reason': 'Metalle NUR bei hohem VIX'},
    'PS5': {'regimes': ['NORMAL', 'ELEVATED'],           'reason': 'Dünger braucht stabile Nachfrage'},
}

BASE_POSITION_SIZE = 150  # EUR


def classify_regime(vix_value):
    """Classify VIX value into regime."""
    for name, config in REGIMES.items():
        if config['vix_min'] <= vix_value < config['vix_max']:
            return name
    return 'PANIC'


def get_current_regime():
    """Get current market regime based on latest VIX."""
    rows = get_prices('^VIX', days=5)
    if not rows:
        return {'regime': 'UNKNOWN', 'vix': None, 'position_size_factor': 1.0, 'stop_factor': 1.0, 'error': 'Keine VIX-Daten'}
    
    # Latest close
    latest = rows[-1]
    vix = latest[4]  # close
    date = latest[0]
    regime = classify_regime(vix)
    config = REGIMES[regime]
    
    return {
        'regime': regime,
        'vix': round(vix, 2),
        'date': date,
        'position_size_factor': config['position_factor'],
        'stop_factor': config['stop_factor'],
        'description': config['desc'],
    }


def is_strategy_compatible(strategy, regime=None):
    """Check if a strategy is compatible with the current/given regime."""
    if regime is None:
        regime = get_current_regime()['regime']
    
    if strategy not in STRATEGY_REGIMES:
        return False, f'Unbekannte Strategie: {strategy}'
    
    config = STRATEGY_REGIMES[strategy]
    compatible = regime in config['regimes']
    
    if compatible:
        ideal = regime in ['ELEVATED', 'PANIC'] and strategy in ['PS4', 'PS1', 'PS3']
        suffix = ' (ideal für dieses Regime)' if ideal else ''
        return True, f"{config['reason']}{suffix}"
    else:
        return False, f"Nicht kompatibel in {regime} — {config['reason']}"


def get_regime_history(days=30):
    """Get regime changes over the last N days."""
    rows = get_prices('^VIX', days=days + 5)
    if not rows:
        return []
    
    history = []
    prev_regime = None
    prev_vix = None
    
    for row in rows:
        date, _, _, _, vix, _ = row
        if vix is None:
            continue
        regime = classify_regime(vix)
        if prev_regime is not None and regime != prev_regime:
            history.append({
                'date': date,
                'from': prev_regime,
                'to': regime,
                'vix_from': round(prev_vix, 1),
                'vix_to': round(vix, 1),
            })
        prev_regime = regime
        prev_vix = vix
    
    return history


def get_position_sizing(base_size=None, regime=None):
    """Get adjusted position size for current regime."""
    if base_size is None:
        base_size = BASE_POSITION_SIZE
    if regime is None:
        regime = get_current_regime()['regime']
    
    config = REGIMES.get(regime, REGIMES['NORMAL'])
    adjusted = base_size * config['position_factor']
    return {
        'base_size': base_size,
        'adjusted_size': round(adjusted, 2),
        'factor': config['position_factor'],
        'regime': regime,
    }


def print_report():
    """Print full regime report."""
    current = get_current_regime()
    
    if current.get('error'):
        print(f"❌ {current['error']}")
        return current
    
    regime = current['regime']
    vix = current['vix']
    
    # Regime emoji
    regime_emoji = {'CALM': '🟢', 'NORMAL': '🔵', 'ELEVATED': '🟡', 'PANIC': '🔴'}.get(regime, '⚪')
    
    print(f"\n{'='*60}")
    print(f"AKTUELLES REGIME: {regime_emoji} {regime} (VIX {vix})")
    print(f"Datum: {current['date']}")
    print(f"{'='*60}")
    
    sizing = get_position_sizing()
    print(f"\nPositionsgröße: {int(current['position_size_factor']*100)}% (max {sizing['adjusted_size']:.0f}€ statt {sizing['base_size']}€)")
    print(f"Stop-Anpassung: {'+' if current['stop_factor'] > 1 else ''}{int((current['stop_factor']-1)*100)}% {'(breiter)' if current['stop_factor'] > 1 else '(normal)'}")
    print(f"Beschreibung: {current['description']}")
    
    # Strategy compatibility
    print(f"\nStrategie-Check:")
    for ps_id, ps_config in STRATEGY_REGIMES.items():
        compatible, reason = is_strategy_compatible(ps_id, regime)
        icon = '✅' if compatible else '❌'
        names = {'PS1': 'Öl', 'PS2': 'Tanker', 'PS3': 'Defense', 'PS4': 'Metalle', 'PS5': 'Dünger'}
        print(f"  {ps_id} ({names.get(ps_id, '?')}): {icon} {'Kompatibel' if compatible else 'NICHT kompatibel'} — {reason}")
    
    # Regime history
    history = get_regime_history(days=30)
    print(f"\nRegime-History (30d):")
    if history:
        for h in history:
            print(f"  {h['date']}: {h['from']} → {h['to']} (VIX {h['vix_from']} → {h['vix_to']})")
    else:
        print("  Keine Regime-Wechsel in den letzten 30 Tagen")
    
    # VIX trend (last 5 days)
    rows = get_prices('^VIX', days=10)
    if rows and len(rows) >= 5:
        recent = rows[-5:]
        vix_values = [r[4] for r in recent if r[4] is not None]
        if vix_values:
            trend = vix_values[-1] - vix_values[0]
            trend_icon = '📈' if trend > 1 else ('📉' if trend < -1 else '➡️')
            print(f"\nVIX-Trend (5d): {trend_icon} {trend:+.1f} ({vix_values[0]:.1f} → {vix_values[-1]:.1f})")
    
    return current


def save_regime():
    """Save current regime to JSON."""
    current = get_current_regime()
    
    # Add strategy compatibility
    current['strategy_compatibility'] = {}
    for ps_id in STRATEGY_REGIMES:
        compatible, reason = is_strategy_compatible(ps_id, current.get('regime'))
        current['strategy_compatibility'][ps_id] = {
            'compatible': compatible,
            'reason': reason,
        }
    
    current['position_sizing'] = get_position_sizing()
    current['regime_history_30d'] = get_regime_history(30)
    current['timestamp'] = datetime.now().isoformat()
    
    json_path = Path("/data/.openclaw/workspace/data/current_regime.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(current, f, indent=2)
    print(f"\n💾 Regime gespeichert in: {json_path}")


if __name__ == '__main__':
    init_tables()
    print_report()
    save_regime()
