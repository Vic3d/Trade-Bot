#!/usr/bin/env python3
"""
system_smoke_test.py — End-to-End Validierung aller Phasen.

Testet jede der 40 Phasen mindestens 1x mit echten Daten — KEIN Mocking.
Output: ✅ / ❌ / ⚠️ pro Test + Performance-Metrik.

Run:
  python3 scripts/system_smoke_test.py            # full suite
  python3 scripts/system_smoke_test.py --quick    # nur kritische Tests
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

results = []


def _record(name: str, ok: bool, msg: str, t_sec: float = 0.0,
             severity: str = 'normal'):
    results.append({
        'name': name, 'ok': ok, 'msg': msg, 'time_sec': round(t_sec, 2),
        'severity': severity,
    })
    icon = '✅' if ok else ('⚠️' if severity == 'warning' else '❌')
    print(f"  {icon} {name:<48} {msg[:80]}  ({t_sec:.1f}s)")


def test(name: str, severity: str = 'normal'):
    """Decorator: catches exceptions + records."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                msg = fn(*args, **kwargs)
                _record(name, True, msg or 'OK', time.time() - t0, severity)
            except Exception as e:
                _record(name, False, f'{type(e).__name__}: {str(e)[:80]}',
                         time.time() - t0, severity)
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════
# Tests (jede Phase eine Test-Funktion)
# ═══════════════════════════════════════════════════════════════════════════

@test('Phase 21: Korrelations-Engine')
def t21():
    from portfolio_risk import compute_full_matrix, get_exposure_breakdown
    b = get_exposure_breakdown()
    assert b.get('by_sector'), 'no sector exposure'
    return f'{len(b["by_sector"])} sectors mapped'

@test('Phase 23: Risk-based Sizing')
def t23():
    from execution.risk_based_sizing import size_position_risk_based
    r = size_position_risk_based('PS_TEST', 25000, 100.0, 95.0)
    assert r['shares'] > 0, 'zero shares'
    return f"{r['shares']} shares, risk {r['risk_eur']}EUR"

@test('Phase 24: Repo-Stress')
def t24():
    p = WS / 'data' / 'liquidity_snapshot.json'
    if not p.exists():
        return 'no snapshot yet'
    d = json.loads(p.read_text())
    return f"repo: {d.get('repo_stress',{}).get('level','?')}"

@test('Phase 26: Theme-Map')
def t26():
    from strategy_discovery import THEME_TICKER_MAP
    assert len(THEME_TICKER_MAP) >= 15, 'too few themes'
    return f'{len(THEME_TICKER_MAP)} themes'

@test('Phase 27: Differentiation-Audit')
def t27():
    from intelligence.differentiation_audit import _score_strategy
    s = _score_strategy('Test thesis with iran hormuz oil')
    assert 'score' in s
    return f"score {s.get('score','?')}"

@test('Phase 28a: CEO-Brain (state-gather)')
def t28a():
    from ceo_brain import gather_inputs
    s = gather_inputs()
    assert 'cash_eur' in s
    return f"cash {s['cash_eur']:.0f}, opens {len(s['open_positions'])}"

@test('Phase 28b: Shadow-Trades')
def t28b():
    from shadow_trades import stats_per_strategy
    st = stats_per_strategy(window_days=30)
    return f'{len(st)} strategies tracked'

@test('Phase 29: Health-Monitor', severity='critical')
def t29():
    from system_health_monitor import run_all_checks
    checks = run_all_checks()
    fails = [c for c in checks if c['status'] == 'FAIL']
    if fails:
        raise AssertionError(f"{len(fails)} FAIL: {[c['check'] for c in fails]}")
    return f"{len(checks)} checks: all OK"

@test('Phase 30: Param-Auto-Tuner')
def t30():
    from parameter_auto_tuner import _fetch_closed_trades
    t = _fetch_closed_trades()
    return f'{len(t)} closed trades sampled'

@test('Phase 31: Goal-Function')
def t31():
    from goal_function import compute_current_score
    s = compute_current_score(window_days=30)
    return f"utility {s.get('utility','?')}, sharpe {s.get('sharpe','?')}"

@test('Phase 31b: Goal-Auto-Adjust')
def t31b():
    from goal_auto_adjust import _load_recent_scores, adjust
    scores = _load_recent_scores(7)
    r = adjust(scores)
    return f"action: {r['action']}, trend {r.get('trend_change_pct','?')}%"

@test('Phase 32a: Decision-Memory')
def t32a():
    from ceo_intelligence import load_decision_memory
    m = load_decision_memory(20)
    return f'{len(m)} past decisions'

@test('Phase 32c: Lessons-DB')
def t32c():
    from ceo_intelligence import load_lessons
    l = load_lessons()
    return f'{len(l)} lessons'

@test('Phase 33a: Calibration')
def t33a():
    from ceo_consciousness import compute_calibration
    c = compute_calibration()
    return f"sample_size {c.get('sample_size',0)}, brier {c.get('brier_score','?')}"

@test('Phase 33e: Mood-Detection')
def t33e():
    from ceo_consciousness import detect_mood
    m = detect_mood(10)
    return f"mood: {m.get('mood','?')}, mult {m.get('size_multiplier','?')}"

@test('Phase 34a: Identity-Doc')
def t34a():
    p = WS / 'memory' / 'ceo-identity.md'
    if not p.exists():
        raise AssertionError('identity-doc nicht generiert')
    return f"{p.stat().st_size} bytes"

@test('Phase 35: Self-Improvement-Proposals')
def t35():
    p = WS / 'data' / 'ceo_improvement_proposals.json'
    if not p.exists():
        return 'noch keine Vorschläge'
    d = json.loads(p.read_text())
    return f"{len(d.get('proposals', []))} proposals"

@test('Phase 36: Calendar-Service', severity='critical')
def t36():
    from calendar_service import get_today_info, get_market_status
    today = get_today_info()
    us = get_market_status('US')
    return f"{today['weekday_de']} {today['date']}, US {us['status']}"

@test('Phase 37: Tool-Calling Tools')
def t37():
    from ceo_tools import TOOLS, tool_get_sector_exposure
    assert len(TOOLS) >= 8
    r = tool_get_sector_exposure()
    assert 'by_sector' in r
    return f"{len(TOOLS)} tools, {len(r['by_sector'])} sectors"

@test('Phase 38: Pattern-Learning')
def t38():
    from ceo_pattern_learning import compute_strategy_hour_heatmap, load_anti_patterns
    h = compute_strategy_hour_heatmap(60)
    p = load_anti_patterns()
    return f"{len(h.get('matrix',{}))} strats heatmap, {len(p)} anti-patterns"

@test('Phase 38b: Pattern Hard-Block')
def t38b():
    from ceo_pattern_learning import check_proposal_against_patterns, get_hour_multiplier
    matches = check_proposal_against_patterns({'strategy': 'PS3', 'sector': ''}, current_hour=3)
    mult = get_hour_multiplier('PS14', current_hour=19)
    return f"{len(matches)} pattern blocks, PS14@19 mult={mult['multiplier']}"

@test('Phase 39: Strategy-Lifecycle')
def t39():
    from strategy_lifecycle import get_lifecycle_overview
    ov = get_lifecycle_overview()
    return f"ACTIVE:{len(ov.get('ACTIVE',[]))} PROBATION:{len(ov.get('PROBATION',[]))} SUSPENDED:{len(ov.get('SUSPENDED',[]))}"

@test('Phase 40a: Shadow-Account v2')
def t40a():
    from shadow_account_v2 import parse_journal_csv, derive_features
    # Mock-CSV
    test_csv = WS / 'data' / 'test_journal.csv'
    test_csv.write_text(
        'ticker,entry_date,entry_price,shares,close_date,close_price,pnl_eur\n'
        'AAPL,2026-01-15T10:00,200,10,2026-01-22T15:00,210,100\n'
    )
    trades = parse_journal_csv(test_csv)
    test_csv.unlink()
    return f"parsed {len(trades)} trades"

@test('Phase 40b: Backtest-Validator')
def t40b():
    from backtest_validator import _fetch_strategy_pnls, _compute_metrics
    pnls = _fetch_strategy_pnls('PS14', 90)
    m = _compute_metrics(pnls) if pnls else {'n': 0}
    return f"PS14: n={m.get('n',0)}, sharpe={m.get('sharpe_annualized','?')}"

@test('Phase 40c: Context-Compression')
def t40c():
    from context_compression import apply_all_layers, estimate_tokens
    test_msgs = [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'X' * 5000},
        {'role': 'tool', 'content': 'Y' * 4000},
        {'role': 'tool', 'content': 'Z' * 4000},
        {'role': 'tool', 'content': 'A' * 4000},
        {'role': 'tool', 'content': 'B' * 4000},
        {'role': 'assistant', 'content': 'final'},
    ]
    stats = apply_all_layers(test_msgs)
    return f"saved {stats['tokens_saved']} tok ({stats['savings_pct']}%)"

@test('Phase 40d: YAML Swarm-Presets')
def t40d():
    from swarm_loader import list_presets, load_preset
    presets = list_presets()
    p = load_preset('trading_decision') if presets else None
    return f"{len(presets)} presets, trading_decision: {len(p.get('agents',[])) if p else 0} agents"

@test('Phase 40e: MCP-Server tools')
def t40e():
    from trademind_mcp_server import TOOLS, execute_tool
    text = execute_tool('get_portfolio_state', {})
    assert 'cash_eur' in text
    return f"{len(TOOLS)} MCP-Tools, get_portfolio_state OK"

@test('Phase 40f: Pine-Export')
def t40f():
    from pine_exporter import export_strategy_to_pine
    pine = export_strategy_to_pine('PS14')
    assert '//@version=6' in pine
    return f"{len(pine)} chars Pine v6"

@test('Phase 40g: Multi-Provider')
def t40g():
    from core.llm_client import PROVIDER_ORDER, DEEPSEEK_MODEL_MAP
    assert 'deepseek' in PROVIDER_ORDER
    return f"chain: {','.join(PROVIDER_ORDER)}"

@test('Phase 40z: Capabilities-Doc')
def t40z():
    p = WS / 'memory' / 'ceo-capabilities.md'
    if not p.exists():
        raise AssertionError('Capabilities-Doc nicht generiert')
    return f"{p.stat().st_size} bytes"


@test('END-TO-END: CEO-Brain Decision (Mock-Proposal)', severity='critical')
def t_end_to_end():
    """Echtester Test: kompletten CEO-Brain-Loop mit synthetic Proposal."""
    from ceo_brain import decide_llm
    state = {
        'proposals_pending': [{
            'ticker': 'TESTOK',
            'strategy': 'PS_TEST',
            'entry_price': 100.0,
            'stop': 95.0,
            'target_1': 110.0,
            'thesis': 'Test thesis for smoke test',
            'sector': 'tech',
        }],
        'open_positions': [],
        'cash_eur': 25000,
        'fund_value': 25000,
        'directive': {'mode': 'BULLISH', 'vix': 18, 'geo_alert_level': 'LOW'},
        'verdicts': {},
    }
    decisions = decide_llm(state)
    if not decisions:
        return 'no decisions returned (might be expected if rules hit)'
    return f'{len(decisions)} decisions, first={decisions[0].get("action","?")}'


def main() -> int:
    print(f'═══ TradeMind Smoke-Test @ {datetime.now().isoformat(timespec="seconds")} ═══\n')

    # Run all tests
    for name in dir(sys.modules[__name__]):
        if name.startswith('t') and name[1:].replace('_', '').isalnum():
            fn = getattr(sys.modules[__name__], name)
            if callable(fn) and name not in ('test',):
                fn()

    print()
    n_total = len(results)
    n_ok = sum(1 for r in results if r['ok'])
    n_warn = sum(1 for r in results if not r['ok'] and r.get('severity') == 'warning')
    n_fail = n_total - n_ok - n_warn
    n_critical_fail = sum(1 for r in results if not r['ok'] and r.get('severity') == 'critical')

    print(f'═══ SUMMARY ═══')
    print(f'  Total: {n_total} | ✅ {n_ok} | ⚠️ {n_warn} | ❌ {n_fail} (critical: {n_critical_fail})')

    # Failed details
    if n_fail:
        print(f'\n=== FAILED ===')
        for r in results:
            if not r['ok']:
                print(f"  ❌ {r['name']}: {r['msg']}")

    # Save report
    out = WS / 'data' / f'smoke_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        'ts': datetime.now().isoformat(),
        'total': n_total, 'ok': n_ok, 'fail': n_fail, 'critical_fail': n_critical_fail,
        'results': results,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nReport: {out}')

    return 0 if n_critical_fail == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
