#!/usr/bin/env python3
"""
Correlation Matrix Refresh — Phase 21
======================================

Täglicher Job (07:15 CET): berechnet die Korrelationsmatrix für alle
offenen + aktiven Tickers und speichert das Ergebnis.

Output:
  - data/correlations.json (vollständige Matrix + Metriken)
  - Console-Log für Scheduler

Scheduler-Eintrag:
  ('Correlation Matrix', 'correlation_refresh.py', [], 7, 15, [0,1,2,3,4])
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from portfolio_risk import (
    _get_open_positions,
    compute_full_matrix,
    compute_diversification_ratio,
    compute_herfindahl_sector,
    find_correlation_clusters,
    compute_parametric_var,
    get_exposure_breakdown,
)

DATA = WS / 'data'
CORR_FILE = DATA / 'correlations.json'


def refresh() -> dict:
    """Berechnet Korrelationsmatrix + Portfolio-Metriken und speichert alles."""
    print('── Correlation Matrix Refresh ──')

    positions = _get_open_positions()
    if not positions:
        print('Keine offenen Positionen — skip')
        return {'pairs_computed': 0}

    tickers = [p.get('ticker', '').upper() for p in positions if p.get('ticker')]
    tickers = list(set(tickers))  # Dedupe
    print(f'Tickers: {len(tickers)} ({", ".join(tickers[:10])}...)')

    # Matrix berechnen
    matrix = compute_full_matrix(tickers, days=30)
    pairs = sum(1 for t in matrix for t2 in matrix[t] if t != t2) // 2
    print(f'Matrix: {len(matrix)}x{len(matrix)} ({pairs} Paare berechnet)')

    # Portfolio-Metriken
    pdr = compute_diversification_ratio(positions, matrix)
    hhi = compute_herfindahl_sector(positions)
    clusters = find_correlation_clusters(matrix, threshold=0.60)
    var_95 = compute_parametric_var(positions, matrix, confidence=0.95)
    var_99 = compute_parametric_var(positions, matrix, confidence=0.99)
    exposure = get_exposure_breakdown(positions)

    print(f'Diversification Ratio: {pdr:.3f} (Ziel: < 0.40)')
    print(f'Herfindahl Sektor:     {hhi:.3f} (Ziel: < 0.30)')
    print(f'VaR 95% (1-Tag):       {var_95:+,.0f} EUR')
    print(f'VaR 99% (1-Tag):       {var_99:+,.0f} EUR')

    if clusters:
        print(f'Korrelations-Cluster:  {len(clusters)}')
        for c in clusters:
            print(f'  {", ".join(c)}')
    else:
        print('Korrelations-Cluster:  keine (gut diversifiziert)')

    # Speichern
    result = {
        'timestamp': datetime.now().isoformat(),
        'date': date.today().isoformat(),
        'tickers': list(matrix.keys()),
        'correlation_matrix': matrix,
        'metrics': {
            'diversification_ratio': pdr,
            'herfindahl_sector': hhi,
            'var_95_eur': var_95,
            'var_99_eur': var_99,
            'clusters': clusters,
            'position_count': len(positions),
            'total_exposure_eur': exposure['total_eur'],
        },
        'exposure': exposure,
    }

    try:
        CORR_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'Gespeichert: {CORR_FILE}')
    except Exception as e:
        print(f'Speichern fehlgeschlagen: {e}')

    return {
        'pairs_computed': pairs,
        'diversification_ratio': pdr,
        'herfindahl': hhi,
        'var_95_eur': var_95,
        'clusters': len(clusters),
    }


if __name__ == '__main__':
    result = refresh()
    print(f'\nResult: {result}')
