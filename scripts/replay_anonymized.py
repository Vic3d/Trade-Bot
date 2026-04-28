#!/usr/bin/env python3
"""
replay_anonymized.py — Replay-Test ohne Hindsight-Leak.

Nimmt N closed Trades, baut SAUBERE Proposals daraus (keine Hinweise dass
es historische Trades sind, keine Exit-Type-Info, keine Notes).

Plus: A/B-Vergleich mit Phase-Toggles:
  --no-pattern-block: deaktiviert Anti-Pattern-Hard-Block
  --no-heatmap:       deaktiviert Heatmap-Multiplier
  --no-lifecycle:     deaktiviert Lifecycle-Block
  --no-mood:          deaktiviert Mood-Multiplier

So messen wir den ECHTEN Effekt jeder Phase.

Run:
  python3 scripts/replay_anonymized.py --n 20
  python3 scripts/replay_anonymized.py --n 20 --no-pattern-block
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'


def fetch_balanced_trades(n: int = 20) -> list[dict]:
    """Hole balanced sample (50/50 win/loss) ohne notes."""
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    half = n // 2
    wins = c.execute("""
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               pnl_eur, pnl_pct, sector, conviction, regime_at_entry,
               vix_at_entry, rsi_at_entry, entry_date
        FROM paper_portfolio
        WHERE status IN ('WIN','LOSS','CLOSED') AND pnl_eur > 0
          AND ticker NOT LIKE 'STRESS%' AND ticker NOT LIKE 'LCS%'
          AND ticker NOT LIKE 'MD%'
        ORDER BY RANDOM() LIMIT ?
    """, (half,)).fetchall()
    losses = c.execute("""
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               pnl_eur, pnl_pct, sector, conviction, regime_at_entry,
               vix_at_entry, rsi_at_entry, entry_date
        FROM paper_portfolio
        WHERE status IN ('WIN','LOSS','CLOSED') AND pnl_eur <= 0
          AND ticker NOT LIKE 'STRESS%' AND ticker NOT LIKE 'LCS%'
          AND ticker NOT LIKE 'MD%'
        ORDER BY RANDOM() LIMIT ?
    """, (n - half,)).fetchall()
    rows = list(wins) + list(losses)
    random.shuffle(rows)
    return [dict(r) for r in rows]


def make_clean_proposal(trade: dict) -> dict:
    """Saubere Proposal — keine Notes, kein Hindsight, kein Exit-Hinweis."""
    # Generic thesis basierend nur auf Strategy-Type — kein Trade-spezifisches Wissen
    strat_thesis = {
        'PS': 'Macro-thesis play — strukturelle 7-30d hold',
        'PT': 'Thesis swing — Wertorientierter Entry',
        'PM': 'Momentum swing — technische Setup',
        'S':  'Strategie-Setup nach Standard-Kriterien',
    }
    strat = trade.get('strategy', '')
    thesis = 'Standard Trading-Setup'
    for prefix, desc in strat_thesis.items():
        if strat.upper().startswith(prefix):
            thesis = desc
            break

    return {
        'ticker': trade['ticker'],
        'strategy': trade['strategy'],
        'entry_price': trade['entry_price'],
        'stop': trade['stop_price'] or trade['entry_price'] * 0.93,
        'target_1': trade['target_price'] or trade['entry_price'] * 1.15,
        'thesis': thesis,
        'sector': trade.get('sector') or '',
        'conviction': trade.get('conviction') or 50,
        # KEIN exit_type, KEIN pnl, KEIN status, KEINE notes
    }


def run_replay(n: int = 20, toggles: dict | None = None,
                batch_size: int = 4) -> dict:
    """Replay mit optionalen Phase-Toggles.
    Phase 41-Fix: Batch-Verarbeitung (max 4 proposals/LLM-Call) damit Tool-Loop
    nicht timeoutet. Plus Mock-Verdicts injecten damit Rules-Engine nicht alles
    auf "Verdict zu alt" blockt."""
    from ceo_brain import decide_llm

    toggles = toggles or {}

    if toggles.get('no_pattern_block'):
        os.environ['DISABLE_PATTERN_BLOCK'] = '1'
    if toggles.get('no_heatmap'):
        os.environ['DISABLE_HEATMAP_MULT'] = '1'
    if toggles.get('no_lifecycle'):
        os.environ['DISABLE_LIFECYCLE_BLOCK'] = '1'
    if toggles.get('no_mood'):
        os.environ['DISABLE_MOOD_MULT'] = '1'

    trades = fetch_balanced_trades(n)
    if not trades:
        return {'error': 'no_trades'}

    proposals = [make_clean_proposal(t) for t in trades]

    # Bug-Fix: Mock-Verdicts injecten damit Rules-Engine nicht alles auf
    # "Verdict zu alt" blockt. Wir geben jedem Test-Ticker frisches KAUFEN.
    mock_verdicts = {}
    today_iso = datetime.now().isoformat(timespec='seconds')
    for p in proposals:
        mock_verdicts[p['ticker']] = {
            'verdict': 'KAUFEN',
            'date': today_iso,
            'reasoning': 'Mock-Verdict für Replay-Test',
            'analyst': 'replay_test',
        }

    print(f'  {len(proposals)} clean proposals → batch_size={batch_size} '
          f'(toggles: {toggles or "all-on"}) ...')
    t0 = time.time()
    decisions = []
    for batch_start in range(0, len(proposals), batch_size):
        batch = proposals[batch_start:batch_start + batch_size]
        state = {
            'proposals_pending': batch,
            'open_positions': [],
            'cash_eur': 25000,
            'fund_value': 25000,
            'directive': {'mode': 'BULLISH', 'vix': 18, 'geo_alert_level': 'MEDIUM'},
            'verdicts': mock_verdicts,
        }
        print(f'    Batch {batch_start//batch_size + 1}: {len(batch)} proposals ...')
        bd = decide_llm(state)
        decisions.extend(bd)
        print(f'      → {len(bd)} decisions')
    elapsed = time.time() - t0
    print(f'  TOTAL: {elapsed:.1f}s, {len(decisions)} decisions')

    # Cleanup env vars
    for env_key in ('DISABLE_PATTERN_BLOCK', 'DISABLE_HEATMAP_MULT',
                    'DISABLE_LIFECYCLE_BLOCK', 'DISABLE_MOOD_MULT'):
        os.environ.pop(env_key, None)

    # Score
    dec_by_ticker = {d.get('ticker'): d for d in decisions if not d.get('_meta')}
    correct_skips = bad_skips = correct_executes = bad_executes = 0
    saved_eur = missed_eur = lost_eur = won_eur = 0.0
    details = []

    for t in trades:
        d = dec_by_ticker.get(t['ticker'], {})
        action = d.get('action', 'NO_DECISION')
        actual_pnl = t.get('pnl_eur', 0) or 0
        actual_outcome = 'WIN' if actual_pnl > 0 else 'LOSS'

        if action in ('SKIP', 'WATCH'):
            if actual_outcome == 'LOSS':
                correct_skips += 1
                saved_eur += abs(actual_pnl)
                v = '✅ Loss vermieden'
            else:
                bad_skips += 1
                missed_eur += actual_pnl
                v = '❌ Win verpasst'
        elif action == 'EXECUTE':
            if actual_outcome == 'WIN':
                correct_executes += 1
                won_eur += actual_pnl
                v = '✅ Win getroffen'
            else:
                bad_executes += 1
                lost_eur += abs(actual_pnl)
                v = '❌ Loss durchgelassen'
        else:
            v = '? keine Decision'

        details.append({
            'ticker': t['ticker'], 'strategy': t['strategy'],
            'real_pnl_eur': actual_pnl, 'real_outcome': actual_outcome,
            'ceo_action': action, 'ceo_confidence': d.get('confidence'),
            'verdict': v,
            'reason': (d.get('reason') or '')[:100],
            'pattern_blocked': d.get('_pattern_blocked', False),
            'lifecycle_blocked': d.get('_lifecycle_blocked', False),
            'hour_mult': d.get('_hour_multiplier'),
            'mood_mult': d.get('_mood_multiplier'),
        })

    n_total = len(trades)
    accuracy = (correct_skips + correct_executes) / n_total * 100 if n_total else 0
    net = saved_eur - missed_eur - lost_eur + won_eur

    # Phase-Effect-Tracking
    phase_effects = {
        'pattern_blocks': sum(1 for d in details if d['pattern_blocked']),
        'lifecycle_blocks': sum(1 for d in details if d['lifecycle_blocked']),
        'hour_mult_changes': sum(1 for d in details
                                  if d.get('hour_mult') and d['hour_mult'] != 1.0),
    }

    return {
        'toggles': toggles,
        'n_trades': n_total,
        'elapsed_sec': round(elapsed, 1),
        'accuracy_pct': round(accuracy, 1),
        'correct_skips': correct_skips,
        'bad_skips': bad_skips,
        'correct_executes': correct_executes,
        'bad_executes': bad_executes,
        'saved_eur': round(saved_eur, 0),
        'missed_eur': round(missed_eur, 0),
        'lost_eur': round(lost_eur, 0),
        'won_eur': round(won_eur, 0),
        'net_effect_eur': round(net, 0),
        'phase_effects': phase_effects,
        'details': details,
    }


def print_result(r: dict, label: str = ''):
    print(f'\n═══ {label} RESULT ═══')
    print(f'  n={r["n_trades"]}, Accuracy: {r["accuracy_pct"]}% '
          f'({r["correct_skips"] + r["correct_executes"]}/{r["n_trades"]})')
    print(f'  ✅ Loss vermieden: {r["correct_skips"]} (saved {r["saved_eur"]:+.0f}€)')
    print(f'  ❌ Win verpasst:   {r["bad_skips"]} (missed {r["missed_eur"]:+.0f}€)')
    print(f'  ✅ Win getroffen:  {r["correct_executes"]} (won {r["won_eur"]:+.0f}€)')
    print(f'  ❌ Loss durchgel.: {r["bad_executes"]} (lost {r["lost_eur"]:+.0f}€)')
    print(f'  📊 NET-EFFECT:     {r["net_effect_eur"]:+.0f}€')
    print(f'  Phase-Effekte: pattern_blocks={r["phase_effects"]["pattern_blocks"]}, '
          f'lifecycle_blocks={r["phase_effects"]["lifecycle_blocks"]}, '
          f'hour_mult≠1: {r["phase_effects"]["hour_mult_changes"]}')


def main() -> int:
    n = 20
    if '--n' in sys.argv:
        n = int(sys.argv[sys.argv.index('--n') + 1])

    print(f'═══ ANONYMIZED REPLAY (n={n}) ═══')

    toggles = {}
    if '--no-pattern-block' in sys.argv:
        toggles['no_pattern_block'] = True
    if '--no-heatmap' in sys.argv:
        toggles['no_heatmap'] = True
    if '--no-lifecycle' in sys.argv:
        toggles['no_lifecycle'] = True
    if '--no-mood' in sys.argv:
        toggles['no_mood'] = True

    # Single run
    r = run_replay(n, toggles)
    print_result(r, label=' '.join(toggles.keys()) or 'ALL-PHASES-ON')

    print('\n=== Trade Details ===')
    for d in r['details']:
        icon = '✅' if 'vermieden' in d['verdict'] or 'getroffen' in d['verdict'] else '❌'
        flags = []
        if d['pattern_blocked']: flags.append('PB')
        if d['lifecycle_blocked']: flags.append('LB')
        if d.get('hour_mult') and d['hour_mult'] != 1.0:
            flags.append(f'H={d["hour_mult"]}')
        flag_str = f' [{",".join(flags)}]' if flags else ''
        print(f"  {icon} {d['ticker']:<10} {d['strategy']:<18} "
              f"real={d['real_outcome']} ({d['real_pnl_eur']:+.0f}€) → "
              f"CEO={d['ceo_action']:<7} c={d['ceo_confidence'] or '?'}{flag_str}")
        if d['reason']:
            print(f"     {d['reason']}")

    # Save
    out = WS / 'data' / f'replay_anon_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    out.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nReport: {out}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
