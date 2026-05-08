#!/usr/bin/env python3
"""
cross_asset_divergence.py — Phase 45z (Victor 2026-05-07).

Edge-Detection-Klasse J2: Erkennt isolierte Sector-Moves.

Logik: Wenn z.B. Brent −7% faellt, aber S&P/USD/Gold neutral bleiben,
ist das ein isolierter Sektor-Move — typischer Insider-Vorlauf vor
Trump-/Politik-Events. Echtes Makro-Event bewegt mehrere Asset-Klassen
parallel.

Mechanik:
  Pro Sektor-Cluster:
    1. Hauptasset des Clusters (z.B. Energy → Brent)
    2. Vergleichs-Assets (S&P, USD, VIX)
    3. Wenn Hauptasset Move >3% UND Vergleichs-Assets <0.5% bewegt
       → Divergence-Alert (Insider-Vorlauf-Verdacht)

Run: alle 10min. Output: data/divergence_log.jsonl
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
COMMODITIES = WS / 'data' / 'commodity_prices.json'
OUT_LOG = WS / 'data' / 'divergence_log.jsonl'

# Asset-Cluster: Hauptasset → Vergleichs-Assets (sollten korrelieren bei
# echten Makro-Events)
CLUSTERS = {
    'energy': {
        'main': ['BZ=F', 'CL=F'],  # Brent + WTI
        'comparators': ['^GSPC', '^VIX', 'GC=F'],  # S&P, VIX, Gold
        'main_threshold_pct': 3.0,
        'comparator_threshold_pct': 0.7,
    },
    'metals': {
        'main': ['GC=F', 'SI=F'],
        'comparators': ['^GSPC', '^VIX', 'BZ=F'],
        'main_threshold_pct': 2.5,
        'comparator_threshold_pct': 0.7,
    },
}


def _load_prices() -> dict:
    if not COMMODITIES.exists(): return {}
    try:
        d = json.loads(COMMODITIES.read_text(encoding='utf-8'))
        return d.get('prices') or {}
    except Exception:
        return {}


def detect() -> list[dict]:
    prices = _load_prices()
    if not prices: return []
    findings: list[dict] = []

    for cluster_name, cfg in CLUSTERS.items():
        # Hauptasset-Bewegung (max abs)
        main_moves = []
        for sym in cfg['main']:
            p = prices.get(sym)
            if not p or p.get('chg_24h_pct') is None: continue
            main_moves.append((sym, p.get('name', sym), float(p['chg_24h_pct'])))
        if not main_moves: continue
        main_moves.sort(key=lambda x: -abs(x[2]))
        biggest = main_moves[0]
        if abs(biggest[2]) < cfg['main_threshold_pct']: continue

        # Comparator-Bewegungen
        comp_moves = []
        for sym in cfg['comparators']:
            p = prices.get(sym)
            if not p or p.get('chg_24h_pct') is None: continue
            comp_moves.append((sym, p.get('name', sym), float(p['chg_24h_pct'])))
        if not comp_moves: continue

        max_comp_move = max(abs(c[2]) for c in comp_moves)
        if max_comp_move > cfg['comparator_threshold_pct']:
            # Comparator hat sich auch bewegt → Makro-Event, nicht isoliert
            continue

        # Divergence!
        findings.append({
            'kind': 'cross_asset_divergence',
            'cluster': cluster_name,
            'main_asset': biggest[0],
            'main_name': biggest[1],
            'main_move_pct': round(biggest[2], 2),
            'comparators': [(c[0], round(c[2], 2)) for c in comp_moves],
            'reason': (f'{biggest[1]} bewegt sich {biggest[2]:+.1f}%, '
                       f'aber Comparators max {max_comp_move:.1f}% — isolierter '
                       f'Sektor-Move (Insider-Vorlauf-Verdacht)'),
        })

    return findings


def main() -> int:
    findings = detect()
    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'n_findings': len(findings),
        'findings': findings,
    }
    if findings:
        OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(out, default=str) + '\n')
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from discord_dispatcher import send_alert, TIER_HIGH
            msg = (f"🚨 **Cross-Asset-Divergence** ({len(findings)} Findings):\n"
                   + '\n'.join(f"  - {f['cluster']}: {f['reason']}"
                               for f in findings[:3]))
            # Phase 45af: detector_finding → SILENT → ceo_inbox (kein Discord)
            send_alert(msg[:1900], tier=TIER_HIGH, category='detector_finding',
                        dedupe_key=f'divergence_{datetime.now().strftime("%Y%m%d_%H")}')
        except Exception: pass
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
