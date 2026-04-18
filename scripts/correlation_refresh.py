#!/usr/bin/env python3
"""Correlation Matrix Refresh — Phase 21 Pro.

Taeglicher Job (07:15 CET): aggregierte Korrelationsmatrix
(Ledoit-Wolf 50% + EWMA 30% + Conditional 20%) ueber alle relevanten Tickers.

Pipeline:
  1. Tickers sammeln (offene Positionen + recent trades 60d + watchlist)
  2. 180d Preise + VIX laden
  3. Sektor-Map laden
  4. compute_aggregated_matrix() -> PSD-repariert
  5. Persist: data/correlations.json + data/correlations_history/<date>.json
  6. Drift vs gestern -> Discord-Notice falls > 0.15

Usage:
  python3 scripts/correlation_refresh.py [--verbose]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from portfolio_risk import _get_open_positions, TICKER_SECTOR
from risk.correlation_engine import (
    compute_aggregated_matrix,
    load_price_history,
    load_vix_history,
    save_correlation_matrix,
    save_snapshot,
    matrix_drift_distance,
)
from risk.matrix_validator import nearest_psd, is_psd

DATA = WS / 'data'
DB = DATA / 'trading.db'
HISTORY_DIR = DATA / 'correlations_history'
DRIFT_THRESHOLD = 0.15


# ─── Ticker Universe ─────────────────────────────────────────────────────────
def collect_relevant_tickers() -> list[str]:
    """Offene Positionen + recent (60d) closed Trades + Watchlist."""
    tickers: set[str] = set()

    for p in _get_open_positions():
        t = (p.get('ticker') or '').upper().strip()
        if t:
            tickers.add(t)

    if DB.exists():
        try:
            conn = sqlite3.connect(str(DB))
            cutoff = (date.today() - timedelta(days=60)).isoformat()
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM paper_portfolio "
                "WHERE entry_date >= ?",
                (cutoff,),
            ).fetchall()
            for (t,) in rows:
                if t:
                    tickers.add(t.upper().strip())
            conn.close()
        except Exception as e:
            print(f'[warn] recent-trades query: {e}')

    # Watchlist via strategies.json
    strat_file = DATA / 'strategies.json'
    if strat_file.exists():
        try:
            data = json.loads(strat_file.read_text(encoding='utf-8'))
            strategies = data.get('strategies', data) if isinstance(data, dict) else data
            if isinstance(strategies, dict):
                strategies = list(strategies.values())
            for s in strategies:
                if not isinstance(s, dict):
                    continue
                for t in s.get('tickers', []) or []:
                    if t:
                        tickers.add(str(t).upper().strip())
        except Exception as e:
            print(f'[warn] strategies.json: {e}')

    return sorted(tickers)


def load_sector_map() -> dict[str, str]:
    sector_map = dict(TICKER_SECTOR)
    cfg_file = DATA / 'trading_config.json'
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
            for k, v in (cfg.get('ticker_sector') or {}).items():
                sector_map[k.upper()] = v
        except Exception:
            pass
    return sector_map


# ─── Drift Notification ──────────────────────────────────────────────────────
def notify_drift(distance: float, n_tickers: int) -> None:
    try:
        from discord_sender import send
        msg = (
            f"⚠️ **Correlation-Regime-Shift erkannt**\n"
            f"Frobenius-Distanz vs. gestern: `{distance:.3f}` "
            f"(Schwelle {DRIFT_THRESHOLD})\n"
            f"Universe: {n_tickers} Tickers\n"
            f"_Cluster-Struktur hat sich geaendert. "
            f"Pruefe Risk-Dashboard im Morgen-Brief._"
        )
        send(msg)
    except Exception as e:
        print(f'[warn] discord notify failed: {e}')


def _load_yesterday_snapshot() -> dict | None:
    """Letzter Snapshot in den letzten 7 Tagen (ausser heute)."""
    today_iso = date.today().isoformat()
    for offset in range(1, 8):
        d = (date.today() - timedelta(days=offset)).isoformat()
        path = HISTORY_DIR / f'{d}.json'
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if payload.get('date') != today_iso:
                    return payload
            except Exception:
                continue
    return None


# ─── Main ────────────────────────────────────────────────────────────────────
def main(verbose: bool = False) -> dict:
    print('── Correlation Matrix Refresh (Phase 21 Pro) ──')
    started = datetime.now()

    tickers = collect_relevant_tickers()
    print(f'Universe: {len(tickers)} Tickers')
    if verbose:
        print(f'  {tickers}')
    if len(tickers) < 2:
        print('Zu wenig Tickers — skip')
        return {'status': 'skipped', 'reason': 'too_few_tickers'}

    print('Lade 180d Preis-Historie...')
    prices = load_price_history(tickers, days=180)
    covered = [t for t, s in prices.items() if len(s) >= 30]
    print(f'  {len(covered)}/{len(tickers)} mit >=30 Tagen Daten')
    if len(covered) < 2:
        print('Zu wenig Preis-Daten — skip')
        return {'status': 'skipped', 'reason': 'no_prices'}
    prices = {t: prices[t] for t in covered}

    print('Lade VIX-Historie...')
    vix = load_vix_history(days=180)
    if vix is None or len(vix) < 30:
        print('  VIX zu kurz — Conditional faellt auf Sample zurueck')
        vix = None

    sector_map = load_sector_map()

    print('Berechne aggregierte Matrix (LW 50% + EWMA 30% + Conditional 20%)...')
    result = compute_aggregated_matrix(
        prices=prices,
        vix_series=vix,
        sector_map=sector_map,
    )
    matrix = result['aggregated']
    out_tickers = result['tickers']
    estimators = result.get('estimators', {})
    metadata = result.get('metadata', {})

    if matrix.size == 0 or not out_tickers:
        print('Aggregation lieferte leere Matrix — abort')
        return {'status': 'failed', 'reason': 'empty_matrix'}

    if not is_psd(matrix):
        print('  Matrix nicht PSD — Higham-Repair')
        matrix = nearest_psd(matrix)
        metadata['psd_repaired'] = True

    metadata['n_universe'] = len(tickers)
    metadata['n_covered'] = len(out_tickers)

    save_correlation_matrix(matrix, out_tickers, metadata)
    snap = save_snapshot(matrix, out_tickers, estimators, metadata)
    print(f'Gespeichert: data/correlations.json + snapshot {snap.name}')

    # Drift Detection
    yesterday = _load_yesterday_snapshot()
    distance = None
    if yesterday:
        try:
            y_matrix = np.asarray(yesterday.get('aggregated', []), dtype=float)
            y_tickers = yesterday.get('tickers', [])
            # Nur gemeinsame Tickers (gleiche Order) vergleichen
            common = [t for t in out_tickers if t in y_tickers]
            if len(common) >= 3:
                idx_t = [out_tickers.index(t) for t in common]
                idx_y = [y_tickers.index(t) for t in common]
                m_today = matrix[np.ix_(idx_t, idx_t)]
                m_yest = y_matrix[np.ix_(idx_y, idx_y)]
                distance = matrix_drift_distance(m_today, m_yest)
                print(f'Drift vs {yesterday.get("date")}: {distance:.3f} '
                      f'(Schwelle {DRIFT_THRESHOLD}, {len(common)} gemeinsame Tickers)')
                if distance > DRIFT_THRESHOLD:
                    notify_drift(distance, len(common))
            else:
                print(f'Zu wenig gemeinsame Tickers ({len(common)}) — Drift skipped')
        except Exception as e:
            print(f'[warn] drift compute: {e}')
    else:
        print('Kein Vortag-Snapshot — Drift-Check skipped')

    elapsed = (datetime.now() - started).total_seconds()
    print(f'Fertig in {elapsed:.1f}s')
    return {
        'status': 'ok',
        'n_tickers': len(out_tickers),
        'drift_distance': distance,
        'snapshot': str(snap),
        'elapsed_sec': elapsed,
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()
    result = main(verbose=args.verbose)
    print(f'\nResult: {json.dumps(result, indent=2, default=str)}')
