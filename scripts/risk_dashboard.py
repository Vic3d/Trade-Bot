#!/usr/bin/env python3
"""Risk Dashboard — Phase 21 Pro.

Generiert Portfolio-Risk-Report aus aktueller Korrelationsmatrix +
offenen Positionen.

Modi:
  --morning  : kompakter Discord-Post (Sektor/Region/VaR/Cluster)
  --evening  : volles Markdown-Dashboard nach memory/risk-dashboard.md
               + Stress-Test-Ergebnisse
  (default)  : printet komplettes Dashboard auf stdout

Usage:
  python3 scripts/risk_dashboard.py
  python3 scripts/risk_dashboard.py --morning
  python3 scripts/risk_dashboard.py --evening
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from portfolio_risk import _get_open_positions, get_sector
from risk.correlation_engine import (
    load_current_matrix,
    load_price_history,
    compute_returns,
)
from risk.var_calculator import (
    parametric_var,
    component_var,
    diversification_ratio,
    effective_n_bets,
)
from risk.clustering import (
    hierarchical_cluster,
    find_dangerous_clusters,
    hrp_weights,
)
from risk.stress_test import run_all_scenarios

DATA = WS / 'data'
MEMORY = WS / 'memory'
DASH_FILE = MEMORY / 'risk-dashboard.md'

EU_SUFFIXES = ('.DE', '.AS', '.PA', '.MI', '.OL', '.CO', '.L', '.MC', '.BR')
ASIA_SUFFIXES = ('.HK', '.T', '.TO', '.SS', '.SZ')


def _region(ticker: str) -> str:
    t = ticker.upper()
    if any(t.endswith(s) for s in EU_SUFFIXES):
        return 'EU'
    if any(t.endswith(s) for s in ASIA_SUFFIXES):
        return 'Asia'
    return 'US'


def _bar(pct: float, width: int = 14) -> str:
    n = max(0, min(width, int(round(pct * width))))
    return '#' * n + '.' * (width - n)


# ─── State ───────────────────────────────────────────────────────────────────
def gather_state() -> dict:
    positions = _get_open_positions()
    # Bug Z (2026-04-22): vorher nur Summe der offenen Positionen → Cash fehlte
    # → alle %-Anteile (Sektor, VaR/Fund) systematisch zu hoch.
    _pos_eur = sum(p.get('position_size_eur', 0.0) or 0.0 for p in positions)
    _cash_eur = 0.0
    try:
        import sqlite3 as _sql
        from pathlib import Path as _P
        import os as _o
        _db = _P(_o.getenv('TRADEMIND_HOME', '/opt/trademind')) / 'data' / 'trading.db'
        if _db.exists():
            _c = _sql.connect(str(_db))
            _r = _c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
            _c.close()
            if _r:
                _cash_eur = float(_r[0] or 0)
    except Exception:
        pass
    fund_total = (_cash_eur + _pos_eur) or 25000.0

    matrix, tickers, meta = load_current_matrix()
    if matrix.size == 0:
        return {
            'positions': positions, 'fund_total': fund_total,
            'matrix': np.zeros((0, 0)), 'tickers': [], 'pos_map': {},
            'metadata': {}, 'error': 'no_matrix',
        }

    pos_map: dict[str, float] = {}
    for p in positions:
        t = (p.get('ticker') or '').upper()
        if t and t in tickers:
            pos_map[t] = pos_map.get(t, 0.0) + (p.get('position_size_eur') or 0.0)

    return {
        'positions': positions, 'pos_map': pos_map, 'fund_total': fund_total,
        'matrix': matrix, 'tickers': tickers, 'metadata': meta,
    }


# ─── Sections ────────────────────────────────────────────────────────────────
def render_sector_block(positions, fund_total) -> list[str]:
    sectors: dict[str, float] = {}
    for p in positions:
        s = p.get('sector') or get_sector(p.get('ticker', ''))
        v = p.get('position_size_eur') or 0.0
        sectors[s] = sectors.get(s, 0.0) + v
    if not sectors:
        return ['  _keine offenen Positionen_']
    rows = []
    for s, v in sorted(sectors.items(), key=lambda x: -x[1]):
        pct = v / fund_total if fund_total > 0 else 0.0
        rows.append(f'  {s:<14} {v:>7,.0f} EUR {pct*100:>5.1f}%  {_bar(pct)}')
    return rows


def render_region_block(positions, fund_total) -> list[str]:
    regions: dict[str, float] = {}
    for p in positions:
        r = _region(p.get('ticker', ''))
        v = p.get('position_size_eur') or 0.0
        regions[r] = regions.get(r, 0.0) + v
    rows = []
    for r in ('US', 'EU', 'Asia'):
        v = regions.get(r, 0.0)
        pct = v / fund_total if fund_total > 0 else 0.0
        rows.append(f'  {r:<6} {v:>7,.0f} EUR {pct*100:>5.1f}%  {_bar(pct)}')
    return rows


def render_var_block(state: dict) -> dict:
    pos_map = state.get('pos_map', {})
    matrix = state['matrix']
    tickers_full = state['tickers']
    if not pos_map or matrix.size == 0:
        return {'lines': ['  _keine VaR-Berechnung moeglich_'],
                'var95': 0, 'var99': 0, 'dr': None, 'enb': None,
                'sub_tickers': [], 'sub_corr': None,
                'weights_eur': [], 'vols': []}

    sub_tickers = [t for t in tickers_full if t in pos_map]
    idx = [tickers_full.index(t) for t in sub_tickers]
    sub_corr = matrix[np.ix_(idx, idx)]
    weights_eur = np.array([pos_map[t] for t in sub_tickers], dtype=float)

    prices = load_price_history(sub_tickers, days=60)
    rets = compute_returns(prices)
    vols = []
    for t in sub_tickers:
        r = rets.get(t)
        vols.append(float(np.std(r, ddof=1)) if r is not None and len(r) >= 5 else 0.02)
    vols = np.array(vols)

    cov = sub_corr * np.outer(vols, vols)
    var95 = parametric_var(weights_eur, cov, confidence=0.95)
    var99 = parametric_var(weights_eur, cov, confidence=0.99)
    comp = component_var(weights_eur, cov, confidence=0.95)
    dr = diversification_ratio(weights_eur, vols, cov)
    enb = effective_n_bets(weights_eur, cov)

    pairs = sorted(zip(sub_tickers, comp), key=lambda x: -x[1])[:3]
    top_lines = [f'    {t:<10} {c:>6,.0f} EUR  ({c/var95*100 if var95 else 0:>4.1f}% Beitrag)'
                 for t, c in pairs]

    lines = [
        f'  VaR 95% (1d):    {var95:>8,.0f} EUR  ({var95/state["fund_total"]*100:.2f}% Fund)',
        f'  VaR 99% (1d):    {var99:>8,.0f} EUR',
        f'  Diversification: {dr:.2f}  (1.0 = keine Diversifikation)',
        f'  Effective N:     {enb:.1f}  (von {len(sub_tickers)} Positionen)',
        '  Top Risk-Treiber:',
        *top_lines,
    ]
    return {
        'lines': lines, 'var95': float(var95), 'var99': float(var99),
        'dr': float(dr), 'enb': float(enb),
        'sub_tickers': sub_tickers, 'sub_corr': sub_corr,
        'weights_eur': weights_eur.tolist(), 'vols': vols.tolist(),
    }


def render_cluster_block(state: dict) -> list[str]:
    matrix = state['matrix']
    tickers = state['tickers']
    pos_map = state.get('pos_map', {})
    if matrix.size == 0 or not pos_map:
        return ['  _keine Cluster-Analyse moeglich_']
    sub_tickers = [t for t in tickers if t in pos_map]
    if len(sub_tickers) < 2:
        return ['  (zu wenig Positionen fuer Clustering)']
    idx = [tickers.index(t) for t in sub_tickers]
    sub_corr = matrix[np.ix_(idx, idx)]
    cl = hierarchical_cluster(sub_corr, sub_tickers, distance_threshold=0.5)
    open_pos = [{'ticker': t, 'value_eur': pos_map[t]} for t in sub_tickers]
    danger = find_dangerous_clusters(
        cl['cluster_assignment'], open_pos,
        corr_matrix=sub_corr, tickers=sub_tickers,
        fund_total=state['fund_total'],
    )
    lines = [f'  Cluster gesamt: {cl["n_clusters"]}']
    if not danger:
        lines.append('  Keine kritischen Cluster (gut diversifiziert)')
    else:
        lines.append(f'  WARN: {len(danger)} kritische Cluster:')
        for d in danger:
            ac = f'{d["avg_corr"]:.2f}' if d['avg_corr'] is not None else 'n/a'
            lines.append(
                f'    [{d["cluster_id"]}] {", ".join(d["tickers"])} -> '
                f'{d["total_exposure_eur"]:,.0f} EUR ({d["pct_of_fund"]*100:.0f}%) '
                f'avg_corr={ac} | {d["reason"]}'
            )
    return lines


def render_stress_block(state: dict) -> list[str]:
    pos_map = state.get('pos_map', {})
    if not pos_map:
        return ['  _keine Positionen fuer Stress-Test_']
    results = run_all_scenarios(pos_map)
    lines = []
    for r in results:
        name = r.get('name', r.get('scenario', '?'))
        if 'error' in r:
            lines.append(f'  {name}: [skip] {r["error"]} (cov={r.get("n_covered", 0)})')
            continue
        worst = r['worst_position']
        lines.append(f'  {name}')
        lines.append(
            f'    P&L: {r["total_pl_eur"]:+,.0f} EUR ({r["total_pl_pct"]*100:+.1f}%)  '
            f'MaxDD: {r["max_drawdown_eur"]:+,.0f} EUR  '
            f'Worst: {worst["ticker"]} ({worst["pl_eur"]:+,.0f} EUR)  '
            f'cov={r["n_covered"]}/{r["n_total"]}'
        )
    return lines


def render_hrp_block(var_data: dict) -> list[str]:
    sub_tickers = var_data.get('sub_tickers', [])
    sub_corr = var_data.get('sub_corr')
    vols = var_data.get('vols', [])
    weights_eur = var_data.get('weights_eur', [])
    if not sub_tickers or sub_corr is None or len(sub_tickers) < 2:
        return ['  _HRP nicht verfuegbar_']
    hrp = hrp_weights(np.asarray(sub_corr), np.asarray(vols), sub_tickers)
    total = sum(weights_eur) or 1.0
    lines = [f'  {"Ticker":<10} {"Aktuell":>8}  {"HRP-Ideal":>10}  {"Delta":>8}']
    for i, t in enumerate(sub_tickers):
        actual_w = weights_eur[i] / total
        hrp_w = hrp.get(t, 0.0)
        delta = (hrp_w - actual_w) * 100
        lines.append(f'  {t:<10} {actual_w*100:>7.1f}%  {hrp_w*100:>9.1f}%  {delta:+7.1f}%')
    return lines


# ─── Composers ───────────────────────────────────────────────────────────────
def compose_full(state: dict) -> str:
    out = []
    out.append('=== RISK DASHBOARD (Phase 21 Pro) ===')
    out.append(f'Stand: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    out.append(f'Fund: {state["fund_total"]:,.0f} EUR  '
               f'Positionen: {len(state["positions"])}')
    out.append('')

    if state.get('error') == 'no_matrix':
        out.append('WARN: Korrelationsmatrix nicht verfuegbar (Refresh laeuft 07:15).')
        return '\n'.join(out)

    out.append('-- SEKTOR-EXPOSURE --')
    out.extend(render_sector_block(state['positions'], state['fund_total']))
    out.append('')
    out.append('-- REGIONS-EXPOSURE --')
    out.extend(render_region_block(state['positions'], state['fund_total']))
    out.append('')

    var_data = render_var_block(state)
    out.append('-- VALUE AT RISK --')
    out.extend(var_data['lines'])
    out.append('')
    out.append('-- KORRELATIONS-CLUSTER --')
    out.extend(render_cluster_block(state))
    out.append('')
    out.append('-- STRESS-TEST (historische Krisen auf JETZT) --')
    out.extend(render_stress_block(state))
    out.append('')
    out.append('-- HRP-VERGLEICH (informativ, kein Sizing-Vorschlag) --')
    out.extend(render_hrp_block(var_data))
    out.append('')
    return '\n'.join(out)


def compose_morning(state: dict) -> str:
    if state.get('error') == 'no_matrix':
        return '📊 **Risk Dashboard**\n_Matrix noch nicht berechnet (Refresh laeuft 07:15)._'

    var_data = render_var_block(state)
    fund = state['fund_total']
    var95 = var_data.get('var95', 0)
    dr = var_data.get('dr') or 0
    enb = var_data.get('enb') or 0

    sectors: dict[str, float] = {}
    for p in state['positions']:
        s = p.get('sector') or get_sector(p.get('ticker', ''))
        sectors[s] = sectors.get(s, 0.0) + (p.get('position_size_eur') or 0.0)
    top_sec = max(sectors.items(), key=lambda x: x[1]) if sectors else ('-', 0)

    regions: dict[str, float] = {}
    for p in state['positions']:
        r = _region(p.get('ticker', ''))
        regions[r] = regions.get(r, 0.0) + (p.get('position_size_eur') or 0.0)
    top_reg = max(regions.items(), key=lambda x: x[1]) if regions else ('-', 0)

    cluster_warn = ''
    matrix = state['matrix']
    tickers = state['tickers']
    pos_map = state.get('pos_map', {})
    if matrix.size > 0 and pos_map:
        sub_tickers = [t for t in tickers if t in pos_map]
        if len(sub_tickers) >= 2:
            idx = [tickers.index(t) for t in sub_tickers]
            sub_corr = matrix[np.ix_(idx, idx)]
            cl = hierarchical_cluster(sub_corr, sub_tickers, distance_threshold=0.5)
            open_pos = [{'ticker': t, 'value_eur': pos_map[t]} for t in sub_tickers]
            danger = find_dangerous_clusters(
                cl['cluster_assignment'], open_pos,
                corr_matrix=sub_corr, tickers=sub_tickers, fund_total=fund,
            )
            if danger:
                # K4 — Namen der kritischen Cluster direkt in die Notification
                _cluster_names = []
                for d in danger[:3]:
                    _cluster_names.append(', '.join(d.get('tickers', [])[:5]))
                _csummary = ' | '.join(_cluster_names)
                cluster_warn = f'\n⚠️  **{len(danger)} kritische Cluster (corr>0.7):** {_csummary}'

    return (
        f'📊 **Risk Dashboard** ({date.today().isoformat()})\n'
        f'• VaR 95% (1d): **{var95:,.0f} EUR** ({var95/fund*100:.2f}% Fund)\n'
        f'• Diversification Ratio: **{dr:.2f}**  |  Effective N: **{enb:.1f}**\n'
        f'• Top-Sektor: **{top_sec[0]}** ({top_sec[1]/fund*100:.0f}%)\n'
        f'• Top-Region: **{top_reg[0]}** ({top_reg[1]/fund*100:.0f}%)'
        f'{cluster_warn}'
    )


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--morning', action='store_true')
    ap.add_argument('--evening', action='store_true')
    args = ap.parse_args()

    state = gather_state()

    if args.morning:
        msg = compose_morning(state)
        print(msg)
        try:
            from discord_sender import send
            send(msg)
        except Exception as e:
            print(f'[warn] discord send: {e}')
        return

    full = compose_full(state)
    print(full)

    if args.evening:
        try:
            DASH_FILE.parent.mkdir(parents=True, exist_ok=True)
            DASH_FILE.write_text(
                f'# Risk Dashboard — {date.today().isoformat()}\n\n```\n{full}\n```\n',
                encoding='utf-8',
            )
            print(f'\nGespeichert: {DASH_FILE}')
        except Exception as e:
            print(f'[warn] write dashboard: {e}')


if __name__ == '__main__':
    main()
