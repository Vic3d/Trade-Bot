#!/usr/bin/env python3
"""
Signal-Level Learning — Phase 16
=================================

Meta-learning: measures which PREDICTIVE SIGNALS actually predict outcomes.
Goes beyond strategy win-rate (Phase 5 daily_learning_cycle) by asking:

  "If Phase 10 insider score < -50 at entry, how often did trades fail in 14d?"
  "Does Phase 11 macro bias agreement improve win-rate?"
  "Which conviction factor breakdown correlates with wins?"

Reads:
  - trades table (closed trades only)
  - conviction_at_entry, regime_at_entry, vix_at_entry on each row
  - deep_dive_verdicts.json historical snapshots (if available)
  - Recent trade_journal entries

Writes:
  data/signal_alpha.json — alpha coefficients per signal
  data/signal_learning_report.md — human-readable summary

Run weekly (Sonntag 09:30 CET — hooked into scheduler).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger('signal_learning')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB = DATA / 'trading.db'
OUT_JSON = DATA / 'signal_alpha.json'
OUT_MD = DATA / 'signal_learning_report.md'


def _fetch_closed_trades() -> list[dict]:
    out: list[dict] = []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT id, ticker, strategy, entry_price, exit_price,
                   pnl_pct, pnl_eur, conviction_at_entry, regime_at_entry,
                   vix_at_entry, holding_days, result, exit_type
              FROM trades
             WHERE status IN ('CLOSED','WIN','LOSS') AND pnl_pct IS NOT NULL
        """).fetchall()
        c.close()
        out = [dict(r) for r in rows]
    except Exception as e:
        log.warning(f'fetch trades: {e}')
    return out


def _split(trades: list[dict], predicate) -> tuple[list[dict], list[dict]]:
    yes: list[dict] = []
    no: list[dict] = []
    for t in trades:
        try:
            (yes if predicate(t) else no).append(t)
        except Exception:
            no.append(t)
    return yes, no


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {'n': 0, 'wr': 0.0, 'avg_pnl_pct': 0.0, 'total_pnl_eur': 0.0}
    wins = sum(1 for t in trades if (t.get('pnl_pct') or 0) > 0)
    total_pnl_eur = sum((t.get('pnl_eur') or 0) for t in trades)
    avg_pnl_pct = sum((t.get('pnl_pct') or 0) for t in trades) / len(trades)
    return {
        'n': len(trades),
        'wr': round(wins / len(trades) * 100, 1),
        'avg_pnl_pct': round(avg_pnl_pct, 2),
        'total_pnl_eur': round(total_pnl_eur, 2),
    }


def _alpha(yes: dict, no: dict) -> dict:
    """Baseline-relative alpha: delta win-rate and delta avg pnl."""
    return {
        'yes': yes,
        'no': no,
        'delta_wr': round(yes['wr'] - no['wr'], 1),
        'delta_pnl_pct': round(yes['avg_pnl_pct'] - no['avg_pnl_pct'], 2),
    }


def run() -> dict:
    trades = _fetch_closed_trades()
    log.info(f'Signal Learning: {len(trades)} closed trades')

    if len(trades) < 10:
        log.warning('not enough trades for meaningful stats (<10)')
        report = {'warning': 'insufficient data', 'n': len(trades)}
        OUT_JSON.write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report

    baseline = _stats(trades)

    experiments: dict = {}

    # 1) Conviction score > 60 vs < 60
    yes, no = _split(trades, lambda t: (t.get('conviction_at_entry') or 0) >= 60)
    experiments['conviction>=60'] = _alpha(_stats(yes), _stats(no))

    # 2) VIX < 20 vs >= 20
    yes, no = _split(trades, lambda t: (t.get('vix_at_entry') or 99) < 20)
    experiments['vix<20'] = _alpha(_stats(yes), _stats(no))

    # 3) Regime BULLISH at entry
    yes, no = _split(trades, lambda t: 'BULL' in str(t.get('regime_at_entry') or '').upper())
    experiments['regime_bullish'] = _alpha(_stats(yes), _stats(no))

    # 4) Short holding (<= 7d) vs long
    yes, no = _split(trades, lambda t: (t.get('holding_days') or 99) <= 7)
    experiments['holding<=7d'] = _alpha(_stats(yes), _stats(no))

    # 5) Exit type STOP vs other (expect negative on STOP)
    yes, no = _split(trades, lambda t: str(t.get('exit_type') or '').upper().startswith('STOP'))
    experiments['exit_stop'] = _alpha(_stats(yes), _stats(no))

    # 6) Strategy type PS_* (thesis plays) vs other
    yes, no = _split(trades, lambda t: str(t.get('strategy') or '').startswith('PS_'))
    experiments['strategy_PS*'] = _alpha(_stats(yes), _stats(no))

    report = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'baseline': baseline,
        'experiments': experiments,
    }

    OUT_JSON.write_text(json.dumps(report, indent=2), encoding='utf-8')

    # Markdown summary
    lines = [
        '# Signal Learning Report',
        f'_Generated {report["generated_at"]}_',
        '',
        f'**Baseline:** n={baseline["n"]} · WR={baseline["wr"]}% · '
        f'Avg PnL={baseline["avg_pnl_pct"]}% · Total PnL={baseline["total_pnl_eur"]}€',
        '',
        '## Signal Alpha (vs baseline)',
        '',
        '| Signal | Yes n | Yes WR | No n | No WR | ΔWR | ΔPnL% |',
        '|---|---|---|---|---|---|---|',
    ]
    for name, exp in experiments.items():
        y, n = exp['yes'], exp['no']
        lines.append(
            f'| {name} | {y["n"]} | {y["wr"]}% | {n["n"]} | {n["wr"]}% | '
            f'{exp["delta_wr"]:+.1f} | {exp["delta_pnl_pct"]:+.2f} |'
        )
    OUT_MD.write_text('\n'.join(lines), encoding='utf-8')

    return report


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    r = run()
    print(json.dumps(r, indent=2)[:2000])


if __name__ == '__main__':
    main()
