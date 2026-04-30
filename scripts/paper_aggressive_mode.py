#!/usr/bin/env python3
"""
paper_aggressive_mode.py — Phase 44d: Paper-Trading-Aggressive-Mode.

Erkenntnis aus Daten (W12+W13 vs W17):
  - W12 (Peak): 19 Trades, R:R 8.3, Energy-Cluster
  - W13 (Strong): 30 Trades, 9 Sektoren, schnelles Trading
  - W17 (jetzt): 2 Trades, Filter blockt alles
  → Filter-Inflation hat den Edge gekillt

Lösung: Aggressive-Mode für Paper (kein Echtgeld-Risiko).
  - Position-Size 1500€ → 600€ (kleiner, dafür mehr)
  - Sektor-Cap 25% → 40%
  - Region-Cap 70% → 90%
  - Max Open Positions: 13 → 40
  - Trades/Woche: 7 → 50
  - Cash-Reserve: 10% → 5%

Nutzung:
  Settings werden aus data/paper_aggressive_settings.json gelesen.
  paper_trade_engine + ceo_active_hunter checken diese Werte vor jedem Cap.

  python3 scripts/paper_aggressive_mode.py --enable
  python3 scripts/paper_aggressive_mode.py --disable
  python3 scripts/paper_aggressive_mode.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
SETTINGS_FILE = WS / 'data' / 'paper_aggressive_settings.json'

DEFAULT_AGGRESSIVE = {
    'enabled': True,
    'reason': 'Paper-Trading: maximieren Volumen für Statistik (W12+W13 zeigen >19 Trades/Woche möglich)',
    'enabled_at': None,
    # Paper-spezifische Caps
    'position_size_eur':       600,    # 1500 → 600
    'max_position_pct':        0.05,   # 15% → 5% des Funds
    'max_open_positions':      40,     # 13 → 40
    'sector_cap_pct':          0.40,   # 0.25 → 0.40
    'region_cap_pct':          0.90,   # 0.70 → 0.90
    'cash_reserve_pct':        0.05,   # 0.10 → 0.05
    'weekly_trade_limit':      50,     # 7 → 50
    'min_crv':                 1.5,    # 2.0 → 1.5 (mehr Setups durch)
}

DEFAULT_CONSERVATIVE = {
    'enabled': False,
    'position_size_eur':       1500,
    'max_position_pct':        0.15,
    'max_open_positions':      13,
    'sector_cap_pct':          0.25,
    'region_cap_pct':          0.70,
    'cash_reserve_pct':        0.10,
    'weekly_trade_limit':      7,
    'min_crv':                 2.0,
}


def get_settings() -> dict:
    """Liefere aktuelle Settings. Default = AGGRESSIVE."""
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return dict(DEFAULT_AGGRESSIVE)


def is_aggressive() -> bool:
    return get_settings().get('enabled', False)


def get_cap(key: str, default):
    """Konvenient: get specific cap with conservative fallback."""
    s = get_settings()
    if s.get('enabled'):
        return s.get(key, DEFAULT_AGGRESSIVE.get(key, default))
    return DEFAULT_CONSERVATIVE.get(key, default)


def enable() -> None:
    s = dict(DEFAULT_AGGRESSIVE)
    s['enabled_at'] = datetime.now(timezone.utc).isoformat()
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False),
                               encoding='utf-8')


def disable() -> None:
    s = dict(DEFAULT_CONSERVATIVE)
    s['disabled_at'] = datetime.now(timezone.utc).isoformat()
    SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False),
                               encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--enable', action='store_true')
    ap.add_argument('--disable', action='store_true')
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args()

    if args.enable:
        enable()
        s = get_settings()
        print('🔥 AGGRESSIVE PAPER-MODE ENABLED')
        for k, v in s.items():
            print(f'  {k}: {v}')
    elif args.disable:
        disable()
        print('🛡️ Conservative mode (default)')
    else:
        s = get_settings()
        print(f'Status: {"AGGRESSIVE" if s.get("enabled") else "CONSERVATIVE"}')
        for k, v in s.items():
            print(f'  {k}: {v}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
