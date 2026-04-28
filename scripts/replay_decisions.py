#!/usr/bin/env python3
"""
replay_decisions.py — Validierung: würde der NEUE CEO die alten Trades anders entscheiden?

Nimmt N closed Trades aus der DB, baut Synthetic-Proposals daraus, lässt CEO-Brain
entscheiden. Vergleicht NEUE Decision (EXECUTE/SKIP/WATCH) mit REAL-Outcome (PnL).

Output:
  - "Würde CEO X% der Loss-Trades skippen?" (Verbesserung)
  - "Würde CEO Y% der Win-Trades skippen?" (Schaden)
  - Net-Effect: gespart vs verpasst

Run:
  python3 scripts/replay_decisions.py --n 10
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'


def fetch_random_closed_trades(n: int = 10, balanced: bool = True) -> list[dict]:
    """N closed trades sample. balanced: 50% wins, 50% losses."""
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    if balanced:
        wins = c.execute("""
            SELECT id, ticker, strategy, entry_price, stop_price, target_price,
                   pnl_eur, pnl_pct, sector, notes
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED') AND pnl_eur > 0
            ORDER BY RANDOM() LIMIT ?
        """, (n // 2,)).fetchall()
        losses = c.execute("""
            SELECT id, ticker, strategy, entry_price, stop_price, target_price,
                   pnl_eur, pnl_pct, sector, notes
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED') AND pnl_eur <= 0
            ORDER BY RANDOM() LIMIT ?
        """, (n - n // 2,)).fetchall()
        rows = list(wins) + list(losses)
    else:
        rows = c.execute("""
            SELECT id, ticker, strategy, entry_price, stop_price, target_price,
                   pnl_eur, pnl_pct, sector, notes
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
            ORDER BY RANDOM() LIMIT ?
        """, (n,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def trade_to_proposal(trade: dict) -> dict:
    """Konvertiere closed trade in synthetic proposal (wie es zur Entry-Zeit aussah)."""
    return {
        'ticker': trade['ticker'],
        'strategy': trade['strategy'],
        'entry_price': trade['entry_price'],
        'stop': trade['stop_price'] or trade['entry_price'] * 0.93,
        'target_1': trade['target_price'] or trade['entry_price'] * 1.15,
        'thesis': (trade.get('notes') or '')[:200],
        'sector': trade.get('sector') or '',
    }


def replay_one_batch(trades: list[dict]) -> dict:
    """Schicke trades als Proposals an CEO-Brain, vergleiche mit real outcome."""
    from ceo_brain import decide_llm

    proposals = [trade_to_proposal(t) for t in trades]
    state = {
        'proposals_pending': proposals,
        'open_positions': [],
        'cash_eur': 25000,
        'fund_value': 25000,
        'directive': {'mode': 'BULLISH', 'vix': 18, 'geo_alert_level': 'MEDIUM'},
        'verdicts': {},
    }

    print(f'  Replay-Batch: {len(proposals)} proposals → CEO-Brain ...')
    t0 = time.time()
    decisions = decide_llm(state)
    elapsed = time.time() - t0
    print(f'  CEO antwortete in {elapsed:.1f}s mit {len(decisions)} decisions')

    # Map decisions back to original trades
    dec_by_ticker = {d.get('ticker'): d for d in decisions if not d.get('_meta')}
    correct_skips = 0   # Trade war LOSS UND CEO sagt SKIP → korrekt
    bad_skips = 0       # Trade war WIN UND CEO sagt SKIP → schlecht
    correct_executes = 0  # Trade war WIN UND CEO sagt EXECUTE → korrekt
    bad_executes = 0    # Trade war LOSS UND CEO sagt EXECUTE → schlecht
    saved_eur = 0       # Sum der vermiedenen Losses
    missed_eur = 0      # Sum der verpassten Wins

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
                verdict = '✅ vermieden'
            else:
                bad_skips += 1
                missed_eur += actual_pnl
                verdict = '❌ verpasst'
        elif action == 'EXECUTE':
            if actual_outcome == 'WIN':
                correct_executes += 1
                verdict = '✅ getroffen'
            else:
                bad_executes += 1
                verdict = '❌ Loss durchgelassen'
        else:
            verdict = '? keine Decision'

        details.append({
            'ticker': t['ticker'], 'strategy': t['strategy'],
            'real_pnl_eur': actual_pnl, 'real_outcome': actual_outcome,
            'ceo_action': action, 'ceo_confidence': d.get('confidence'),
            'verdict': verdict,
            'reason': (d.get('reason') or '')[:120],
        })

    return {
        'n_trades': len(trades),
        'n_decisions': len(decisions),
        'elapsed_sec': round(elapsed, 1),
        'correct_skips': correct_skips,
        'bad_skips': bad_skips,
        'correct_executes': correct_executes,
        'bad_executes': bad_executes,
        'saved_eur': round(saved_eur, 0),
        'missed_eur': round(missed_eur, 0),
        'net_effect': round(saved_eur - missed_eur, 0),
        'accuracy_pct': round((correct_skips + correct_executes) / max(1, len(trades)) * 100, 1),
        'details': details,
    }


def main() -> int:
    n = 10
    if '--n' in sys.argv:
        n = int(sys.argv[sys.argv.index('--n') + 1])

    print(f'═══ REPLAY: würde der NEUE CEO {n} alte Trades anders entscheiden? ═══\n')

    trades = fetch_random_closed_trades(n=n, balanced=True)
    if not trades:
        print('Keine closed trades in DB.')
        return 1

    print(f'Sample: {len(trades)} trades '
          f'({sum(1 for t in trades if (t["pnl_eur"] or 0) > 0)} WIN, '
          f'{sum(1 for t in trades if (t["pnl_eur"] or 0) <= 0)} LOSS)\n')

    result = replay_one_batch(trades)

    print(f'\n═══ RESULT ═══')
    print(f'  Accuracy: {result["accuracy_pct"]}% ({result["correct_skips"]+result["correct_executes"]}/{result["n_trades"]})')
    print(f'  Korrekt vermiedene Verluste: {result["correct_skips"]} (-{result["saved_eur"]:.0f}€ saved)')
    print(f'  Verpasste Wins:               {result["bad_skips"]}  ({result["missed_eur"]:+.0f}€ missed)')
    print(f'  Korrekt getroffene Wins:      {result["correct_executes"]}')
    print(f'  Loss durchgelassen:           {result["bad_executes"]}')
    print(f'  NET-EFFECT: {result["net_effect"]:+.0f}€ '
          f'({"besser" if result["net_effect"] > 0 else "schlechter" if result["net_effect"] < 0 else "neutral"})')

    print(f'\n=== Details ===')
    for d in result['details']:
        icon = '✅' if 'vermieden' in d['verdict'] or 'getroffen' in d['verdict'] else '❌'
        print(f"  {icon} {d['ticker']:<10} real={d['real_outcome']} ({d['real_pnl_eur']:+.0f}€) "
              f"→ CEO={d['ceo_action']:<7} conf={d['ceo_confidence'] or '?'}")
        if d['reason']:
            print(f"     {d['reason']}")

    # Save report
    out = WS / 'data' / f'replay_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nReport: {out}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
