#!/usr/bin/env python3
"""
kelly_sizer.py — Phase 45f (Sprint 5): Kelly-Criterion Position-Sizing.

Ersetzt 'fest 1500EUR' durch:
  Position-Size = funds × Kelly-fraction × ML-conviction-factor

Kelly-Formel: f = (p × b - q) / b
  p = Win-Probability (vom ML-Modell, Sprint 3)
  q = 1 - p
  b = avg_win / avg_loss (vom Backtest, Sprint 1)

Wir nutzen FRACTIONAL KELLY (1/4) — empirisch sicherer, weil
Kelly-Schaetzungen Volatilitaet haben.

Cap: max 5% des Funds pro Position.

Output:
  data/kelly_sizing_log.jsonl   pro Sizing-Decision
  Funktion get_kelly_size(strategy, ml_prob) -> EUR
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'kelly_sizing_log.jsonl'

KELLY_FRACTION = 0.25  # 1/4 Kelly (konservativ)
MAX_POSITION_PCT = 0.05  # 5% des Funds max
MIN_POSITION_EUR = 200
MAX_POSITION_EUR = 1500


def _strategy_payoff_ratio(c: sqlite3.Connection, strategy: str) -> tuple[float, float]:
    """avg_win / avg_loss aus historischen Trades dieser Strategy.
    Returns (b, win_rate) — Defaults bei zu wenig Daten."""
    rows = c.execute(
        "SELECT pnl_eur FROM paper_portfolio "
        "WHERE strategy=? AND status IN ('WIN','LOSS','CLOSED') "
        "AND pnl_eur IS NOT NULL", (strategy,)
    ).fetchall()
    pnls = [float(r[0]) for r in rows]
    if len(pnls) < 3: return 1.5, 0.55  # konservative Defaults
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
    if not wins or not losses: return 1.5, 0.55
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    b = avg_win / avg_loss if avg_loss > 0 else 1.5
    wr = len(wins) / len(pnls)
    return b, wr


def _get_funds() -> float:
    if not DB.exists(): return 25000
    c = sqlite3.connect(str(DB))
    try:
        cash_row = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
        cash = float(cash_row[0]) if cash_row else 25000
        # Plus offene Positionen
        opens = c.execute(
            "SELECT entry_price, shares FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        deployed = sum(float(r[0] or 0) * float(r[1] or 0) for r in opens)
        return cash + deployed
    finally: c.close()


def get_kelly_size(strategy: str, ml_winprob: float | None = None) -> dict:
    """Berechnet Kelly-Fractional-Sizing.
    ml_winprob: P(win) vom ML-Modell, fallback auf historische WR der Strategy."""
    if not DB.exists(): return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    b, hist_wr = _strategy_payoff_ratio(c, strategy)
    c.close()

    # Win-Probability aus ML oder historischer WR
    if ml_winprob is not None and 0 < ml_winprob < 1:
        p = ml_winprob; source = 'ml_model'
    else:
        p = hist_wr; source = 'historical_wr'
    q = 1 - p

    # Kelly: f = (p*b - q) / b
    if b <= 0 or p <= q/b:
        kelly_f = 0.0  # negative edge → no bet
    else:
        kelly_f = (p * b - q) / b

    fractional_kelly = kelly_f * KELLY_FRACTION
    funds = _get_funds()
    raw_eur = funds * fractional_kelly
    cap_eur = funds * MAX_POSITION_PCT
    final_eur = max(MIN_POSITION_EUR, min(raw_eur, cap_eur, MAX_POSITION_EUR))

    if kelly_f <= 0:
        final_eur = 0  # kein Trade

    out = {
        'strategy': strategy,
        'ml_winprob': ml_winprob, 'historical_wr': hist_wr,
        'p': p, 'q': q, 'b': b, 'source': source,
        'kelly_full': round(kelly_f, 3),
        'kelly_fractional': round(fractional_kelly, 3),
        'funds_eur': round(funds, 0),
        'raw_kelly_eur': round(raw_eur, 0),
        'cap_eur': round(cap_eur, 0),
        'final_position_eur': round(final_eur, 0),
        'ts': datetime.now(timezone.utc).isoformat(),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(out, ensure_ascii=False) + '\n')
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--strategy', default='S1')
    ap.add_argument('--prob', type=float, default=None)
    args = ap.parse_args()
    r = get_kelly_size(args.strategy, args.prob)
    print(json.dumps(r, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
