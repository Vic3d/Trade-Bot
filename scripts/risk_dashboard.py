#!/usr/bin/env python3
"""
Risk Dashboard — Phase 21
==========================

Generiert ein Text-basiertes Portfolio-Risk-Dashboard für Discord.
Wird im Morgen-Briefing eingebettet.

Zeigt:
  - Sektor-Exposure mit Balkendiagramm
  - Regions-Exposure
  - Korrelations-Cluster (Warnungen)
  - Metriken: Diversification Ratio, Herfindahl, VaR
"""
from __future__ import annotations

import json
import os
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME',
                    str(Path(__file__).resolve().parent.parent)))
DATA = WS / 'data'
CORR_FILE = DATA / 'correlations.json'


def _load_correlations() -> dict | None:
    """Lädt die letzte correlation_refresh.py Ausgabe."""
    if not CORR_FILE.exists():
        return None
    try:
        return json.loads(CORR_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None


def generate_risk_block() -> str:
    """
    Generiert den Risk-Block für das Discord Morning Briefing.
    Kompakt formatiert (Discord 2000-char Limit beachten).
    """
    data = _load_correlations()
    if not data:
        return ''

    metrics = data.get('metrics', {})
    exposure = data.get('exposure', {})
    lines: list[str] = []

    lines.append('\n📐 **Portfolio-Risiko**')

    # Sektor-Exposure
    by_sector = exposure.get('by_sector', {})
    if by_sector:
        sorted_sectors = sorted(by_sector.items(), key=lambda x: -x[1].get('pct', 0))
        for sector, info in sorted_sectors[:5]:
            pct = info.get('pct', 0) * 100
            count = info.get('count', 0)
            bar_len = int(pct / 5)  # 20% = 4 blocks
            bar = '█' * bar_len + '░' * (10 - bar_len)
            lines.append(f'  {sector:12} {bar} {pct:4.0f}% ({count})')

    # Region
    by_region = exposure.get('by_region', {})
    if by_region:
        region_parts = []
        for region, info in sorted(by_region.items(), key=lambda x: -x[1].get('pct', 0)):
            pct = info.get('pct', 0) * 100
            if pct >= 5:
                region_parts.append(f'{region} {pct:.0f}%')
        if region_parts:
            lines.append(f'  🌍 {" | ".join(region_parts)}')

    # Metriken
    pdr = metrics.get('diversification_ratio', 0)
    hhi = metrics.get('herfindahl_sector', 0)
    var_95 = metrics.get('var_95_eur', 0)
    var_99 = metrics.get('var_99_eur', 0)

    # Bewertung
    pdr_icon = '✅' if pdr < 0.40 else '⚠️' if pdr < 0.60 else '🔴'
    hhi_icon = '✅' if hhi < 0.30 else '⚠️' if hhi < 0.50 else '🔴'

    lines.append(f'  {pdr_icon} Diversifikation: {pdr:.2f} (Ziel: <0.40)')
    lines.append(f'  {hhi_icon} Sektor-HHI: {hhi:.2f} (Ziel: <0.30)')
    if var_95:
        lines.append(f'  📉 VaR 95%: {var_95:+,.0f}€/Tag | 99%: {var_99:+,.0f}€/Tag')

    # Cluster-Warnungen
    clusters = metrics.get('clusters', [])
    if clusters:
        lines.append(f'  ⚠️ **Cluster:** {len(clusters)} korrelierte Gruppen')
        for c in clusters[:3]:
            lines.append(f'    → {", ".join(c)}')

    return '\n'.join(lines)


if __name__ == '__main__':
    block = generate_risk_block()
    if block:
        print(block)
    else:
        print('Keine Korrelationsdaten vorhanden — bitte correlation_refresh.py zuerst ausführen')
