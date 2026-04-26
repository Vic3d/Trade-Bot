#!/usr/bin/env python3
"""
sizing_ab_test.py — A/B-Test zwischen conviction-based und risk-based Sizing.

Mechanik (Hybrid: Random-per-Trade + Shadow Logging):
  1. Für jeden Trade werden BEIDE Modi berechnet (conviction + risk_based)
  2. Welcher Mode tatsächlich verwendet wird, entscheidet ein deterministischer
     Hash auf (ticker + entry_date) → ~50/50 Split, reproducible
  3. Beide Berechnungen werden in `sizing_ab_log` SQL-Tabelle gespeichert
  4. Nach 20+ Trades: weekly compare report zeigt PnL/WR pro Mode +
     Counterfactual-Analyse ("hätte Mode B besser sized?")

Nutzen:
  - Echte PnL-Daten für beide Modi (50% der Trades pro Mode)
  - Plus Counterfactual: Was hätte der ANDERE Mode gemacht?
  - Statistik wird nach jedem Trade aktualisiert

Aktivierung:
  autonomy_config.json: {"sizing_mode": "ab_test"}
  → paper_trade_engine.py liest 'ab_test' und ruft pick_and_size()
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
DB = WS / 'data' / 'trading.db'


def _ensure_table() -> None:
    conn = sqlite3.connect(str(DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sizing_ab_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ticker TEXT NOT NULL,
            strategy TEXT NOT NULL,
            entry_price REAL,
            stop_price REAL,
            portfolio_value REAL,
            mode_used TEXT NOT NULL,
            shares_conviction INTEGER,
            shares_risk_based INTEGER,
            position_eur_conviction REAL,
            position_eur_risk_based REAL,
            shares_used INTEGER,
            trade_id INTEGER
        )
    """)
    conn.commit()
    conn.close()


def _pick_mode(ticker: str, entry_date: str) -> str:
    """Deterministischer 50/50-Split via Hash."""
    key = f'{ticker}|{entry_date[:10]}'
    h = hashlib.md5(key.encode()).hexdigest()
    return 'conviction' if int(h, 16) % 2 == 0 else 'risk_based'


def compute_both(
    ticker: str, strategy: str,
    entry_price: float, stop_price: float,
    portfolio_value_eur: float,
    conviction_score: int | None = None,
) -> dict:
    """
    Berechnet beide Modi und gibt das komplette Bild zurück.
    Returns: {
        'mode_used': 'conviction' | 'risk_based',
        'shares_used': int,
        'shares_conviction': int,
        'shares_risk_based': int,
        'pos_eur_conviction': float,
        'pos_eur_risk_based': float,
    }
    """
    # ── Mode A: Conviction-based ───────────────────────────────
    shares_conv = 0
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from conviction_scorer import get_position_size as _gps
        shares_conv = int(_gps(conviction_score or 50, portfolio_value_eur,
                                entry_price, stop_price))
    except Exception:
        # Fallback: 2% risk method
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share > 0:
            shares_conv = int(portfolio_value_eur * 0.02 / risk_per_share)

    # ── Mode B: Risk-based (Erichsen-Formel) ───────────────────
    shares_rb = 0
    try:
        from execution.risk_based_sizing import size_position_risk_based as _rb
        result = _rb(strategy=strategy, portfolio_value_eur=portfolio_value_eur,
                     entry_price=entry_price, stop_price=stop_price)
        if not result.get('skip'):
            shares_rb = int(result.get('shares', 0))
    except Exception:
        pass

    pos_eur_conv = shares_conv * entry_price
    pos_eur_rb   = shares_rb   * entry_price

    # ── Mode-Pick ──────────────────────────────────────────────
    today = datetime.now().strftime('%Y-%m-%d')
    mode_used = _pick_mode(ticker, today)

    if mode_used == 'conviction':
        shares_used = shares_conv
    else:
        shares_used = shares_rb

    # Wenn der gewählte Mode 0 zurückgibt → Fallback auf den anderen,
    # damit Trade nicht durch A/B-Test verhindert wird.
    if shares_used <= 0:
        shares_used = shares_conv if shares_conv > 0 else shares_rb
        mode_used += '_fallback'

    return {
        'mode_used': mode_used,
        'shares_used': shares_used,
        'shares_conviction': shares_conv,
        'shares_risk_based': shares_rb,
        'pos_eur_conviction': round(pos_eur_conv, 2),
        'pos_eur_risk_based': round(pos_eur_rb, 2),
    }


def log_decision(
    ticker: str, strategy: str,
    entry_price: float, stop_price: float,
    portfolio_value_eur: float,
    decision: dict,
    trade_id: int | None = None,
) -> None:
    """Speichert die Entscheidung in sizing_ab_log."""
    _ensure_table()
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("""
            INSERT INTO sizing_ab_log
            (timestamp, ticker, strategy, entry_price, stop_price, portfolio_value,
             mode_used, shares_conviction, shares_risk_based,
             position_eur_conviction, position_eur_risk_based, shares_used, trade_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec='seconds'),
            ticker, strategy, entry_price, stop_price, portfolio_value_eur,
            decision['mode_used'],
            decision['shares_conviction'],
            decision['shares_risk_based'],
            decision['pos_eur_conviction'],
            decision['pos_eur_risk_based'],
            decision['shares_used'],
            trade_id,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[sizing_ab] log error: {e}')


if __name__ == '__main__':
    # Smoke test
    d = compute_both('NVDA', 'PS_NVDA', 100.0, 95.0, 25000, conviction_score=60)
    print(json.dumps(d, indent=2))
    log_decision('NVDA', 'PS_NVDA', 100.0, 95.0, 25000, d)
    print('Logged to sizing_ab_log.')
