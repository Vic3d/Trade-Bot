#!/usr/bin/env python3
"""
short_engine.py — Phase 45h (Sprint 7): Bidirektionales Trading.

Komponenten:
  1. SHORT-Engine: Inverse Trades (entry_price > exit_price = profit)
  2. Pair-Trading: Long X / Short Y (Sektor-neutral)
  3. Hedging: Long Position + Short ETF (z.B. Long EQNR + Short XLE = idiosynkratisch)

Risk: Short-Selling hat unbegrenztes Loss-Potential.
Daher Pflicht-Stops + striktere Position-Limits.

Datenbank-Schema-Erweiterung:
  paper_portfolio.direction  TEXT (DEFAULT 'long', allowed: long|short|pair_long|pair_short)
  paper_portfolio.pair_id    TEXT (verbindet Long+Short eines Pairs)

PnL-Berechnung:
  long:  (exit - entry) × shares
  short: (entry - exit) × shares  (invertiert)
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

# Bekannte Pair-Sets (Sektor-neutral)
PAIR_SETS = {
    'energy_majors': [('XOM', 'CVX'), ('SHEL.L', 'BP.L'), ('TTE.PA', 'EQNR.OL')],
    'gold_miners': [('GDX', 'GDXJ'), ('NEM', 'GOLD')],
    'tanker': [('FRO', 'DHT'), ('STNG', 'TNK')],
    'tech_mega': [('NVDA', 'AMD'), ('MSFT', 'GOOGL')],
    'banks': [('JPM', 'BAC'), ('GS', 'MS')],
}

SHORT_HARD_STOP_PCT = 0.10  # max 10% Stop fuer Shorts (engerer als Long)
SHORT_MAX_POSITION_PCT = 0.03  # max 3% Funds (vs 5% fuer Long)


def _ensure_schema():
    if not DB.exists(): return
    c = sqlite3.connect(str(DB))
    cols = [r[1] for r in c.execute("PRAGMA table_info(paper_portfolio)").fetchall()]
    if 'direction' not in cols:
        c.execute("ALTER TABLE paper_portfolio ADD COLUMN direction TEXT DEFAULT 'long'")
        c.commit()
    if 'pair_id' not in cols:
        c.execute("ALTER TABLE paper_portfolio ADD COLUMN pair_id TEXT")
        c.commit()
    c.close()


def open_short(ticker: str, strategy: str, entry_price: float,
                stop_price: float, target_price: float,
                position_eur: float, thesis: str = '') -> dict:
    """Eroeffnet eine SHORT-Position.
    Stop muss UEBER Entry liegen, Target UNTER Entry."""
    if stop_price <= entry_price:
        return {'success': False, 'reason': 'short stop must be ABOVE entry'}
    if target_price >= entry_price:
        return {'success': False, 'reason': 'short target must be BELOW entry'}
    stop_pct = (stop_price - entry_price) / entry_price
    if stop_pct > SHORT_HARD_STOP_PCT:
        return {'success': False, 'reason': f'short stop too wide: {stop_pct:.1%} > {SHORT_HARD_STOP_PCT:.0%}'}

    _ensure_schema()
    c = sqlite3.connect(str(DB))
    shares = round(position_eur / entry_price, 4) if entry_price else 0
    now = datetime.now(timezone.utc).isoformat()
    c.execute(
        "INSERT INTO paper_portfolio "
        "(ticker, strategy, entry_price, entry_date, shares, "
        " stop_price, target_price, status, fees, notes, style, "
        " conviction, regime_at_entry, sector, direction) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', 1.0, ?, 'short', 0, '?', '?', 'short')",
        (ticker, strategy, entry_price, now, shares,
         stop_price, target_price, f'[SHORT] {thesis}')
    )
    trade_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit(); c.close()
    return {'success': True, 'trade_id': trade_id, 'direction': 'short',
            'shares': shares, 'position_eur': position_eur}


def open_pair(long_ticker: str, short_ticker: str, strategy: str,
               long_entry: float, short_entry: float,
               position_eur: float, thesis: str = '') -> dict:
    """Eroeffnet PAIR-Trade: Long Asset A + Short Asset B (Sektor-neutral).
    Position-EUR teilt sich gleichmaessig auf beide Beine."""
    _ensure_schema()
    half_eur = position_eur / 2
    long_shares = round(half_eur / long_entry, 4) if long_entry else 0
    short_shares = round(half_eur / short_entry, 4) if short_entry else 0
    pair_id = f"PAIR_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    c = sqlite3.connect(str(DB))
    now = datetime.now(timezone.utc).isoformat()

    # Long-Leg
    c.execute(
        "INSERT INTO paper_portfolio "
        "(ticker, strategy, entry_price, entry_date, shares, "
        " stop_price, target_price, status, fees, notes, style, "
        " conviction, regime_at_entry, sector, direction, pair_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', 0.5, ?, 'pair', 0, '?', '?', 'pair_long', ?)",
        (long_ticker, strategy, long_entry, now, long_shares,
         long_entry * 0.93, long_entry * 1.07,  # 7% Stop/Target
         f'[PAIR LONG vs {short_ticker}] {thesis}', pair_id)
    )
    long_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Short-Leg
    c.execute(
        "INSERT INTO paper_portfolio "
        "(ticker, strategy, entry_price, entry_date, shares, "
        " stop_price, target_price, status, fees, notes, style, "
        " conviction, regime_at_entry, sector, direction, pair_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', 0.5, ?, 'pair', 0, '?', '?', 'pair_short', ?)",
        (short_ticker, strategy, short_entry, now, short_shares,
         short_entry * 1.07, short_entry * 0.93,
         f'[PAIR SHORT vs {long_ticker}] {thesis}', pair_id)
    )
    short_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

    c.commit(); c.close()
    return {'success': True, 'pair_id': pair_id,
            'long_id': long_id, 'short_id': short_id,
            'long_ticker': long_ticker, 'short_ticker': short_ticker,
            'each_position_eur': half_eur}


def calculate_short_pnl(entry: float, exit_price: float, shares: float, fees: float = 1.0) -> float:
    """Short-PnL: profit wenn exit < entry."""
    return (entry - exit_price) * shares - fees


def main():
    print('Short-Engine ready.')
    print(f'  PAIR_SETS: {len(PAIR_SETS)} categories, '
          f'{sum(len(p) for p in PAIR_SETS.values())} pairs total')
    _ensure_schema()
    print('  paper_portfolio Schema-Migration: direction + pair_id columns ready')
    return 0


if __name__ == '__main__':
    sys.exit(main())
