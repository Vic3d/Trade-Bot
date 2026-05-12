#!/usr/bin/env python3
"""
position_pnl.py — Phase 45ar (Victor 2026-05-12).

ZENTRALER FX-SICHERER POSITION-PNL-HELPER. Single Source of Truth.

Jeder Code-Pfad der unrealized/realized PnL berechnet MUSS diese Funktionen
benutzen — keine eigenen `(live - entry) * shares` Berechnungen mehr.

Hintergrund-Bug (Phase 45ap+45aq fix):
  - paper_portfolio.entry_price = EUR (autonomous_scanner konvertiert)
  - prices.close                = NATIV (USD/NOK/GBP/...)
  - Mischung → fake +17-18% PnL

Funktionen:
  to_eur(price_native, ticker) -> float            FX-konvertiere
  get_live_price_eur(ticker) -> float | None       Live-EUR-Preis aus DB
  position_pnl(entry_eur, live_eur, shares) -> dict  PnL-Computation
  get_position_pnl(ticker, entry_eur, shares) -> dict  All-in-one
"""
from __future__ import annotations
import os, sqlite3, sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

# Helper-Modul aus core/
sys.path.insert(0, str(WS / 'scripts' / 'core'))


def to_eur(price_native: float, ticker: str) -> float:
    """Konvertiere nativen Preis (USD/NOK/etc.) zu EUR via FX-Faktor."""
    if not price_native or price_native <= 0:
        return 0.0
    try:
        from live_data import get_fx_factor
        fx = get_fx_factor(ticker) or 1.0
    except Exception:
        fx = 1.0
    return float(price_native) * fx


def get_fx(ticker: str) -> float:
    """FX-Faktor für Ticker — public utility."""
    try:
        from live_data import get_fx_factor
        return get_fx_factor(ticker) or 1.0
    except Exception:
        return 1.0


def get_live_price_eur(ticker: str) -> tuple[float | None, float | None, str | None]:
    """
    Liest Last-Close aus prices-Tabelle UND konvertiert zu EUR.
    Returns: (live_eur, live_native, last_date) — alle None wenn nicht verfügbar.
    """
    if not DB.exists():
        return None, None, None
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT date, close FROM prices WHERE ticker=? "
            "ORDER BY date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        c.close()
        if not row or not row[1]:
            return None, None, None
        live_native = float(row[1])
        live_eur = to_eur(live_native, ticker)
        return live_eur, live_native, row[0]
    except Exception:
        return None, None, None


def position_pnl(entry_eur: float, live_eur: float, shares: float) -> dict:
    """
    Reine PnL-Math (ohne FX-Konvertierung; Caller hat schon konvertiert).
    Returns dict mit pnl_eur, pnl_pct, change.
    """
    if not entry_eur or entry_eur <= 0 or not shares:
        return {'pnl_eur': 0.0, 'pnl_pct': 0.0, 'valid': False}
    pnl_eur = (live_eur - entry_eur) * shares
    pnl_pct = (live_eur / entry_eur - 1) * 100
    return {
        'pnl_eur': round(pnl_eur, 2),
        'pnl_pct': round(pnl_pct, 2),
        'entry_eur': round(entry_eur, 2),
        'live_eur': round(live_eur, 2),
        'shares': shares,
        'valid': True,
    }


def get_position_pnl(ticker: str, entry_eur: float, shares: float) -> dict:
    """
    All-in-one: holt Live-Preis, konvertiert, berechnet PnL.
    Returns dict mit allem (oder valid=False).
    """
    live_eur, live_native, last_date = get_live_price_eur(ticker)
    if live_eur is None:
        return {'ticker': ticker, 'valid': False, 'reason': 'no_live_price'}
    pnl = position_pnl(entry_eur, live_eur, shares)
    pnl.update({
        'ticker': ticker,
        'live_native': round(live_native, 2) if live_native else None,
        'fx_factor': round(get_fx(ticker), 4),
        'last_date': last_date,
    })
    return pnl


def main() -> int:
    """CLI Test."""
    import sys, json
    if len(sys.argv) < 4:
        print('Usage: position_pnl.py TICKER ENTRY_EUR SHARES')
        return 2
    r = get_position_pnl(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
