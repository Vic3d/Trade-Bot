#!/usr/bin/env python3
"""
pre_entry_validator.py — Phase 45ai (Victor 2026-05-09).

META-LAYER: Generischer Plausibility-Check vor JEDEM Trade-Entry.
Statt für jede Bug-Klasse einen eigenen Guard zu bauen, prüft dieser
Validator alle bekannten UND unbekannte Klassen mit 7 Sanity-Checks.

Lernung: 5 historische Phantom-Rollbacks + FRO.OL hätten alle durch
mind. einen dieser Checks gefangen werden müssen.

Integration: paper_trade_engine.py Guard 0a2 (vor allen anderen Guards).
"""
from __future__ import annotations
import os, sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

# Schwellen (justierbar)
# Phase 45ap: 50% → 20% verschärft. PAAS-Bug (USD vs EUR Mismatch ~18%)
# wäre mit 50% durchgerutscht und ist mit 20% gefangen.
MAX_PRICE_DEV_VS_DB     = 0.20  # Entry vs DB-Last-Close (war 0.50)
MAX_LIVE_DEV_VS_DB      = 0.10  # Live yfinance vs DB-Last-Close
MAX_STALE_PRICE_DAYS    = 5     # DB-Last-Close darf nicht älter als
MIN_PRICE_USD           = 1.0   # Penny-Stock-Floor
MAX_PRICE_USD           = 5000  # Berkshire-A ausgenommen


def validate(ticker: str, entry_price: float,
             stop_price: float | None = None,
             target_price: float | None = None,
             direction: str = 'long') -> Tuple[bool, list[str], dict]:
    """
    Returns (ok, issues, details).
      ok=True  → alle Checks bestanden
      ok=False → mind. ein Check failed, issues listet alle Failures
    """
    issues: list[str] = []
    det: dict = {'ticker': ticker, 'entry_price': entry_price}

    if not ticker or not isinstance(entry_price, (int, float)):
        return False, ['invalid_input'], det

    # Check 1: Preis-Floor (Penny-Stock-Block)
    if entry_price < MIN_PRICE_USD:
        issues.append(f'price_below_floor ({entry_price:.4f} < {MIN_PRICE_USD})')

    # Check 2: Preis-Ceiling (Berkshire-A oder Bug)
    if entry_price > MAX_PRICE_USD:
        issues.append(f'price_above_ceiling ({entry_price:.0f} > {MAX_PRICE_USD})')

    # Check 3: Stop muss unter Entry sein (LONG) bzw. über (SHORT)
    if stop_price is not None:
        if direction == 'long' and stop_price >= entry_price:
            issues.append(f'stop_above_entry_long (stop={stop_price} entry={entry_price})')
        if direction == 'short' and stop_price <= entry_price:
            issues.append(f'stop_below_entry_short (stop={stop_price} entry={entry_price})')

    # Check 4: Stop-Distance plausibel (nicht <0.5%, nicht >50%)
    if stop_price is not None:
        dist = abs(entry_price - stop_price) / entry_price if entry_price > 0 else 0
        det['stop_distance_pct'] = round(dist * 100, 2)
        if dist < 0.005:
            issues.append(f'stop_distance_microscopic ({dist*100:.2f}%)')
        if dist > 0.50:
            issues.append(f'stop_distance_extreme ({dist*100:.0f}%)')

    # Check 5: Target/Stop-Ratio (CRV Sanity)
    if stop_price is not None and target_price is not None and direction == 'long':
        risk = entry_price - stop_price
        reward = target_price - entry_price
        if risk > 0 and reward / risk < 0.5:
            issues.append(f'crv_inverted (R={risk:.2f} REW={reward:.2f})')

    # Check 6: Entry-Preis vs DB-Last-Close (Listing-Mismatch / Phantom)
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            row = c.execute(
                "SELECT date, close FROM prices WHERE ticker=? "
                "ORDER BY date DESC LIMIT 1", (ticker,)
            ).fetchone()
            c.close()
            if row and row[1]:
                last_close = float(row[1])
                last_date = row[0]
                det['db_last_close'] = last_close
                det['db_last_date'] = last_date
                # Stale check
                try:
                    last_dt = datetime.fromisoformat(str(last_date)[:10])
                    age_d = (datetime.now() - last_dt).days
                    det['db_staleness_days'] = age_d
                    if age_d > MAX_STALE_PRICE_DAYS:
                        issues.append(f'db_price_stale ({age_d}d old)')
                except Exception:
                    pass
                # Range check
                if last_close > 0:
                    dev = abs(entry_price - last_close) / last_close
                    det['entry_vs_db_pct'] = round(dev * 100, 1)
                    if dev > MAX_PRICE_DEV_VS_DB:
                        issues.append(
                            f'entry_vs_db_mismatch '
                            f'(entry={entry_price:.2f} db={last_close:.2f} '
                            f'dev={dev*100:.0f}%)')
        except Exception as e:
            det['db_check_err'] = str(e)

    # Check 7: Live yfinance vs DB-Last-Close (Phantom-Tick)
    # Nur wenn DB-Preis frisch (<3d) — sonst sinnlos
    if DB.exists() and 'db_staleness_days' in det and det['db_staleness_days'] <= 3:
        try:
            import yfinance as yf
            live = yf.Ticker(ticker).fast_info.last_price
            if live:
                live = float(live)
                det['yf_live'] = round(live, 2)
                last_close = det.get('db_last_close', 0)
                if last_close > 0:
                    live_dev = abs(live - last_close) / last_close
                    det['live_vs_db_pct'] = round(live_dev * 100, 1)
                    if live_dev > MAX_LIVE_DEV_VS_DB:
                        issues.append(
                            f'live_phantom (live={live:.2f} db={last_close:.2f} '
                            f'dev={live_dev*100:.0f}%)')
        except Exception:
            pass  # yfinance ist optional

    return (len(issues) == 0), issues, det


def main() -> int:
    """CLI: python pre_entry_validator.py TICKER ENTRY [STOP] [TARGET]"""
    import sys, json
    if len(sys.argv) < 3:
        print('Usage: pre_entry_validator.py TICKER ENTRY_PRICE [STOP] [TARGET]')
        return 2
    ticker = sys.argv[1]
    entry = float(sys.argv[2])
    stop = float(sys.argv[3]) if len(sys.argv) > 3 else None
    target = float(sys.argv[4]) if len(sys.argv) > 4 else None
    ok, issues, det = validate(ticker, entry, stop, target)
    print(json.dumps({'ok': ok, 'issues': issues, 'details': det},
                     indent=2, default=str))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
