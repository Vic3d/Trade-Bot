"""
ceo_trade_review.py — STUB (Phase 5 cleanup)
=============================================
This file is superseded by the dual-gate entry system in autonomous_scanner.py
(Phase 1) and the thesis engine in core/thesis_engine.py (Phase 0/4).

The ceo_review() function is kept as a no-op stub for backward compatibility
with any legacy callers (e.g. autonomous_loop.py).

Albert | TradeMind v3 | 2026-04-10
"""


def ceo_review(candidate: dict) -> dict:
    """
    STUB: Legacy CEO trade review gate.
    Replaced by: thesis_engine + autonomous_scanner dual-gate system.
    Always returns APPROVE to avoid blocking trades from new system.
    """
    return {
        'decision': 'APPROVE',
        'reason': 'ceo_trade_review stubbed — using thesis_engine + dual-gate scanner',
        'thesis': '',
        'negation': '',
        'horizon': '',
        'final_score': candidate.get('conviction', 5),
        'mode': 'NORMAL',
    }


def load_ceo_directive() -> dict:
    """STUB: Load from ceo_directive.json directly."""
    from pathlib import Path
    import json
    try:
        p = Path('/data/.openclaw/workspace/data/ceo_directive.json')
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return {'mode': 'NORMAL', 'trading_rules': {}}
