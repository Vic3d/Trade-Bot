"""
CEO Trade Review — Gate 2 der Trade-Pipeline
Der CEO prüft jeden Kandidaten gegen:
1. Aktuelle Direktive (Modus, erlaubte Strategien)
2. Sektor-Rotation (hot/cooling)
3. Strategie-Validierung (These vorhanden?)
4. Portfolio-Limits (max Positionen, Sektor-Konzentration)

Output:
  APPROVE: Trade öffnen
  REJECT:  Trade ablehnen + Grund
  WATCH:   Auf Watchlist setzen, noch nicht kaufen
"""

import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent.parent / 'data'


def load_ceo_directive() -> dict:
    try:
        with open(BASE / 'ceo_directive.json') as f:
            return json.load(f)
    except Exception:
        return {'mode': 'NORMAL', 'trading_rules': {}}


def load_strategies() -> dict:
    with open(BASE / 'strategies.json') as f:
        return json.load(f)


def load_rotation_state() -> dict:
    try:
        with open(BASE / 'sector_rotation_state.json') as f:
            return json.load(f)
    except Exception:
        return {'rotation_multiplier': {}}


def count_open_positions() -> int:
    """Count positions opened today (for max_new_positions_today check)."""
    try:
        db = sqlite3.connect(BASE / 'trading.db')
        return db.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN' AND date(entry_date)=date('now')"
        ).fetchone()[0]
    except Exception:
        return 0


def count_total_open_positions() -> int:
    """Count all currently open positions."""
    try:
        db = sqlite3.connect(BASE / 'trading.db')
        return db.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
    except Exception:
        return 0


def count_sector_positions(sector: str) -> int:
    try:
        db = sqlite3.connect(BASE / 'trading.db')
        return db.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN' AND sector=?", (sector,)
        ).fetchone()[0]
    except Exception:
        return 0


# Import after definition to avoid circular import issues
try:
    from strategy_validator import validate_strategy
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from strategy_validator import validate_strategy


def ceo_review(candidate: dict) -> dict:
    """
    candidate = {
        'ticker': 'EQNR.OL',
        'strategy_id': 'PS1',
        'price': 401.0,
        'conviction': 5,
        'signal': 'WEAK',
        'sector': 'Energie'
    }
    """
    # 1. CEO-Direktive lesen
    directive = load_ceo_directive()
    mode = directive.get('mode', 'NORMAL')

    # 2. Strategy validieren
    strategies = load_strategies()
    validation = validate_strategy(candidate['strategy_id'], strategies)
    if not validation['valid']:
        return {'decision': 'REJECT', 'reason': f"Keine These: {validation['reason']}"}

    # 3. CEO-Modus prüfen
    if mode == 'SHUTDOWN':
        return {'decision': 'REJECT', 'reason': 'CEO: SHUTDOWN aktiv'}

    rules = directive.get('trading_rules', {})
    blocked = rules.get('blocked_strategies', [])
    if candidate['strategy_id'] in blocked:
        return {'decision': 'REJECT', 'reason': f"CEO: {candidate['strategy_id']} geblockt"}

    # Check allowed strategies (if whitelist is set)
    allowed = rules.get('allowed_strategies', [])
    if allowed and candidate['strategy_id'] not in allowed:
        return {'decision': 'REJECT', 'reason': f"CEO: {candidate['strategy_id']} nicht in allowed_strategies"}

    # 4. Sektor-Rotation
    rotation = load_rotation_state()
    multiplier = rotation.get('rotation_multiplier', {}).get(candidate['sector'], 1.0)
    if multiplier == 0.0:
        return {'decision': 'REJECT', 'reason': f"Sektor {candidate['sector']} cooling (×0.0)"}

    # 5. Conviction nach Rotation
    final_score = candidate['conviction'] * multiplier

    # 6. Min-Conviction je nach Modus
    min_conv = {'DEFENSIVE': 4, 'NORMAL': 3, 'AGGRESSIVE': 1}.get(mode, 3)
    if final_score < min_conv:
        return {'decision': 'WATCH', 'reason': f'Score {final_score:.1f} < Min {min_conv} für {mode}'}

    # 7. Portfolio-Limits: max neue Positionen heute
    max_new_today = rules.get('max_new_positions_today', 10)
    opened_today = count_open_positions()
    if opened_today >= max_new_today:
        return {'decision': 'WATCH', 'reason': f'Tageslimit erreicht: {opened_today}/{max_new_today} neue Positionen heute'}

    # Total portfolio limit (aus _config)
    # Hard cap: max 15 Positionen gleichzeitig
    total_open = count_total_open_positions()
    if total_open >= 15:
        return {'decision': 'WATCH', 'reason': f'Portfolio-Limit: {total_open}/15 Positionen gesamt'}

    # 8. Max Sektor-Konzentration (max 3 Positionen pro Sektor)
    sector_count = count_sector_positions(candidate['sector'])
    if sector_count >= 3:
        return {'decision': 'WATCH', 'reason': f'Sektor {candidate["sector"]} bereits {sector_count} Positionen — max 3'}

    # APPROVE
    return {
        'decision': 'APPROVE',
        'thesis': validation['thesis'],
        'negation': validation['negation'],
        'horizon': validation['horizon'],
        'final_score': final_score,
        'mode': mode
    }


if __name__ == '__main__':
    test_candidates = [
        {'ticker': 'EQNR.OL', 'strategy_id': 'S1', 'price': 401.0, 'conviction': 6, 'signal': 'WEAK', 'sector': 'Energie'},
        {'ticker': 'AMAT', 'strategy_id': 'AR-HALB', 'price': 150.0, 'conviction': 7, 'signal': 'STRONG', 'sector': 'Halbleiter'},
        {'ticker': 'OXY', 'strategy_id': 'PS1', 'price': 45.0, 'conviction': 5, 'signal': 'WEAK', 'sector': 'Energie'},
    ]
    for c in test_candidates:
        r = ceo_review(c)
        detail = r.get('reason', r.get('thesis', ''))[:70]
        print(f"{c['ticker']} ({c['strategy_id']}): {r['decision']} — {detail}")
