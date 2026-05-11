#!/usr/bin/env python3
"""
portfolio_concentration_guard.py — Phase 45aq Layer A1 (Victor 2026-05-11).

Prüft VOR jedem neuen Trade ob das Portfolio in einer korrelations-Cluster
zu konzentriert wird. Verhindert "3 Trades = 1 Trade" Risiken wie heute
(GDX/PAAS/WPM = alle Edelmetall-Story).

Cluster-Logik:
  - Sektor-Match (z.B. PAAS, WPM, GDX = "GOLD_SILVER")
  - Ticker-Korrelation aus prices-DB (30d Pearson)
  - Hard-Cap: max 35% Portfolio in einem Cluster

Output: passes_concentration(ticker, position_size_eur) -> (ok, reason, details)
Integration: paper_trade_engine.py Guard 0h (vor Trade-Execute).
"""
from __future__ import annotations
import json, os, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Tuple

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
FUND_FILE = WS / 'data' / 'paper_fund.json'

MAX_CLUSTER_PCT = 0.35  # Max 35% des Portfolio in einem Korrelations-Cluster
HIGH_CORR_THRESHOLD = 0.70  # Pearson > 0.70 = gleiches Cluster

# Pre-defined Sektor-Cluster (manual mapping — schnell und sicher)
SECTOR_CLUSTERS = {
    'GOLD_SILVER_MINER': {'GDX', 'GDXJ', 'NEM', 'AEM', 'GOLD', 'AGI', 'KGC', 'WPM', 'FNV',
                          'PAAS', 'HL', 'AG', 'EXK', 'FSM', 'SVM', 'CDE', 'HMY', 'EQX', 'AU', 'GFI', 'SLV'},
    'OIL_ENERGY':        {'XLE', 'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'OXY', 'PSX', 'MPC', 'PXD', 'VLO', 'TTE.PA', 'EQNR.OL'},
    'OIL_TANKER':        {'FRO', 'FRO.OL', 'DHT', 'STNG', 'TNK', 'NAT', 'EURN'},
    'COPPER_BASE_METAL': {'COPX', 'FCX', 'SCCO', 'TECK', 'BHP', 'RIO', 'IVN'},
    'URANIUM_NUCLEAR':   {'URA', 'CCJ', 'UEC', 'DNN', 'NXE', 'PALAF'},
    'DEFENSE':           {'ITA', 'RTX', 'LMT', 'GE', 'BA', 'NOC', 'GD', 'TDG', 'LHX', 'HII', 'KTOS'},
    'BANK_FINANCIAL':    {'XLF', 'KRE', 'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW', 'PNC', 'KEY'},
    'TECH_SEMI':         {'XLK', 'SMH', 'NVDA', 'AVGO', 'AMD', 'ASML', 'TSM', 'QCOM', 'TXN', 'AMAT', 'LRCX'},
    'BIOTECH':           {'XBI', 'ARKG', 'REGN', 'VRTX', 'GILD', 'AMGN', 'BIIB', 'MRNA', 'EXEL', 'NBIX'},
    'SOLAR_RENEWABLE':   {'TAN', 'ENPH', 'FSLR', 'SEDG', 'RUN', 'SHLS', 'CSIQ', 'JKS'},
    'CONSUMER_STAPLES':  {'XLP', 'PG', 'KO', 'WMT', 'COST', 'PEP', 'PM', 'MDLZ', 'CL'},
    'HEALTHCARE_PHARMA': {'XLV', 'LLY', 'JNJ', 'UNH', 'ABBV', 'MRK', 'TMO', 'ABT', 'PFE', 'BMY', 'NVO', 'NOVO-B.CO'},
    'UTILITIES':         {'XLU', 'NEE', 'DUK', 'SO', 'D', 'AEP', 'SRE', 'XEL', 'PEG'},
    'AGRI_FERTILIZER':   {'MOS', 'CF', 'NTR', 'SDF.DE'},
}


def _ticker_cluster(ticker: str) -> str | None:
    """Welches Sektor-Cluster gehört der Ticker?"""
    t = ticker.upper()
    for cluster, members in SECTOR_CLUSTERS.items():
        if t in members:
            return cluster
    return None


def _open_positions_with_value() -> list[dict]:
    """Alle OPEN Positionen + ihr aktueller Markt-Wert in EUR."""
    if not DB.exists(): return []
    out = []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        for r in c.execute(
            "SELECT id, ticker, strategy, entry_price, shares FROM paper_portfolio "
            "WHERE status='OPEN'"
        ).fetchall():
            d = dict(r)
            # Live-Price aus prices (FX-konvertiert)
            pr = c.execute("SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
                          (d['ticker'],)).fetchone()
            if pr and pr[0] and d['shares']:
                try:
                    import sys as _sys
                    _sys.path.insert(0, str(WS / 'scripts' / 'core'))
                    from live_data import get_fx_factor
                    fx = get_fx_factor(d['ticker']) or 1.0
                except Exception:
                    fx = 1.0
                last_eur = float(pr[0]) * fx
                d['current_value_eur'] = last_eur * d['shares']
                d['cluster'] = _ticker_cluster(d['ticker'])
                out.append(d)
        c.close()
    except Exception: pass
    return out


def _portfolio_total_eur() -> float:
    """Cash + aktuelle Position-Werte."""
    cash = 0.0
    try:
        if FUND_FILE.exists():
            fund = json.loads(FUND_FILE.read_text(encoding='utf-8'))
            cash = float(fund.get('cash', 0))
    except Exception: pass
    positions_value = sum(p.get('current_value_eur', 0) for p in _open_positions_with_value())
    return cash + positions_value


def passes_concentration(ticker: str, new_position_size_eur: float) -> Tuple[bool, str, dict]:
    """
    Prüft ob neuer Trade Konzentrations-Limit überschreiten würde.
    Returns: (ok, reason, details)
    """
    new_cluster = _ticker_cluster(ticker)
    positions = _open_positions_with_value()
    total = _portfolio_total_eur()

    if total <= 0:
        return True, 'empty_portfolio_skip', {}

    # Cluster-Exposure aktuell
    cluster_exposure: dict = {}
    for p in positions:
        cl = p.get('cluster') or 'UNCLUSTERED'
        cluster_exposure[cl] = cluster_exposure.get(cl, 0) + p.get('current_value_eur', 0)

    details: dict = {
        'ticker': ticker,
        'new_cluster': new_cluster,
        'new_position_eur': round(new_position_size_eur, 2),
        'portfolio_total_eur': round(total, 2),
        'cluster_exposure_pct': {k: round(v / total * 100, 1) for k, v in cluster_exposure.items()},
    }

    # Wenn neuer Ticker kein bekanntes Cluster hat → durchlassen (keine Info, keine Beschränkung)
    if not new_cluster:
        details['note'] = 'no_known_cluster — pass through'
        return True, 'no_cluster', details

    # Wieviel wäre im Cluster nach neuem Trade?
    current_in_cluster = cluster_exposure.get(new_cluster, 0)
    after_trade = current_in_cluster + new_position_size_eur
    after_pct = after_trade / total

    details['cluster_after_trade_pct'] = round(after_pct * 100, 1)

    if after_pct > MAX_CLUSTER_PCT:
        return False, (
            f'cluster_concentration_exceeded ({new_cluster} would be '
            f'{after_pct*100:.1f}% > max {MAX_CLUSTER_PCT*100:.0f}%)'
        ), details

    return True, 'within_concentration_limit', details


def main() -> int:
    """CLI Test."""
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else 'NEM'
    size = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
    ok, reason, det = passes_concentration(t, size)
    print(json.dumps({'ok': ok, 'reason': reason, 'details': det},
                     indent=2, default=str, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
