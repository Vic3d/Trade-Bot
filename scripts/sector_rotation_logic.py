#!/usr/bin/env python3
"""
Sector Rotation Logic — Automatische Sektorauswahl für Paper Lab
================================================================
Wenn Sektor underperformt → rotiere in nächstbesten

Logik:
1. Berechne 7-Tage-Performance pro Sektor aus paper_portfolio
2. Sektoren mit < 30% WR in letzten 7 Tagen → "cooling" Flag
3. Sektoren mit > 50% WR → "hot" Flag
4. Schreibe Ergebnis in data/sector_rotation_state.json
5. Paper Trading liest diese Datei und gewichtet Entries entsprechend

Autor: Albert (autonome Entscheidung — kein Victor-Auftrag)
Erstellt: 2026-03-31
Grund: High-Conviction-Trades verloren systematisch in bestimmten Sektoren.
       Sektor-Rotation verhindert dass wir in toten Sektoren weitertraden.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
OUTPUT = WS / 'data/sector_rotation_state.json'

# Sektor-Mapping: DB-Sektornamen → Display-Namen
# (autonomous_loop nutzt englische/kurze Sektornamen aus global_radar)
SECTOR_DISPLAY = {
    'HALB': 'Halbleiter',
    'semiconductor': 'Halbleiter',
    'technology': 'Tech',
    'defense': 'Rüstung',
    'energy': 'Energie',
    'energy_renewable': 'Energie',
    'metals': 'Rohstoffe',
    'materials': 'Rohstoffe',
    'fertilizer': 'Agrar',
    'AGRA': 'Agrar',
    'agriculture': 'Agrar',
    'healthcare': 'Healthcare',
    'uranium': 'Energie',
    'mixed': 'Mixed',
    'Other': 'Mixed',
}

# Bekannte schlechte Sektoren (aus Paper Lab Analyse — hartcodiert als Sicherheitsnetz)
KNOWN_BAD_SECTORS = {'Halbleiter', 'Agrar'}


def get_sector_performance_7d(db) -> dict:
    """
    Berechne 7-Tage Win-Rate pro Sektor aus paper_portfolio.
    Returns: {sektor: {'wins': n, 'total': n, 'win_rate': float, 'avg_pnl': float}}
    """
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    rows = db.execute("""
        SELECT sector, status, pnl_eur
        FROM paper_portfolio
        WHERE status IN ('WIN', 'CLOSED', 'LOSS')
          AND close_date > ?
          AND sector IS NOT NULL
    """, (cutoff,)).fetchall()

    perf = {}
    for row in rows:
        sector_raw = row[0] or 'Other'
        sector = SECTOR_DISPLAY.get(sector_raw, sector_raw)
        status = row[1]
        pnl = row[2] or 0.0

        if sector not in perf:
            perf[sector] = {'wins': 0, 'total': 0, 'pnl_sum': 0.0}

        perf[sector]['total'] += 1
        perf[sector]['pnl_sum'] += pnl
        if pnl > 0 or status == 'WIN':
            perf[sector]['wins'] += 1

    # Win-Rate berechnen
    result = {}
    for sector, data in perf.items():
        total = data['total']
        wins = data['wins']
        result[sector] = {
            'wins': wins,
            'total': total,
            'win_rate': round(wins / total, 3) if total > 0 else 0.0,
            'avg_pnl': round(data['pnl_sum'] / total, 2) if total > 0 else 0.0,
        }

    return result


def classify_sectors(perf: dict) -> tuple:
    """
    Klassifiziere Sektoren in hot / cooling / neutral.
    
    Returns: (hot_sectors, cooling_sectors, neutral_sectors)
    """
    hot = []
    cooling = []
    neutral = []

    # Sektoren mit bekannten 0%-WR-Strategien sind immer cooling
    for bad in KNOWN_BAD_SECTORS:
        if bad not in perf:
            # Kein 7d-Daten, aber bekannt schlecht → trotzdem cooling
            cooling.append(bad)

    for sector, data in perf.items():
        wr = data['win_rate']
        total = data['total']

        if sector in KNOWN_BAD_SECTORS:
            if sector not in cooling:
                cooling.append(sector)
            continue

        if total < 2:
            # Zu wenig Daten → neutral
            if sector not in neutral:
                neutral.append(sector)
            continue

        if wr > 0.50:
            hot.append(sector)
        elif wr < 0.30:
            if sector not in cooling:
                cooling.append(sector)
        else:
            neutral.append(sector)

    # Deduplizieren
    hot = sorted(set(hot))
    cooling = sorted(set(cooling))
    neutral = sorted(set(neutral))

    return hot, cooling, neutral


def build_rotation_multiplier(hot: list, cooling: list, neutral: list, perf: dict) -> dict:
    """
    Berechne rotation_multiplier pro Sektor.
    
    Logik:
    - hot (>50% WR): 1.3–1.5x je nach Stärke
    - neutral: 1.0x
    - cooling (<30% WR): 0.5x (nur bei ausreichend Daten)
    - bekannte Problemsektoren (0% WR, locked): 0.0x
    """
    multiplier = {}

    for sector in hot:
        data = perf.get(sector, {})
        wr = data.get('win_rate', 0.55)
        if wr >= 0.65:
            multiplier[sector] = 1.5
        else:
            multiplier[sector] = 1.3

    for sector in neutral:
        multiplier[sector] = 1.0

    for sector in cooling:
        if sector in KNOWN_BAD_SECTORS:
            multiplier[sector] = 0.0  # Komplett gesperrt
        else:
            data = perf.get(sector, {})
            total = data.get('total', 0)
            if total >= 3:
                multiplier[sector] = 0.5  # Reduziert aber nicht null
            else:
                multiplier[sector] = 0.7  # Wenig Daten → vorsichtig reduzieren

    return multiplier


def run():
    """Hauptfunktion: Berechne Sektor-Rotation-State und speichere JSON."""
    print(f"🔄 Sector Rotation Logic — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    # 7-Tage-Performance laden
    perf = get_sector_performance_7d(db)
    db.close()

    print(f"  7d-Daten: {len(perf)} Sektoren")
    for sector, data in sorted(perf.items()):
        print(f"    {sector:15s}: WR={data['win_rate']:.0%} ({data['wins']}/{data['total']}) | Avg P&L: {data['avg_pnl']:+.2f}€")

    # Klassifizieren
    hot, cooling, neutral = classify_sectors(perf)

    print(f"\n  🔥 HOT:     {hot}")
    print(f"  ❄️  COOLING: {cooling}")
    print(f"  ➡️  NEUTRAL: {neutral}")

    # Multiplier berechnen
    multiplier = build_rotation_multiplier(hot, cooling, neutral, perf)

    # State zusammenbauen
    state = {
        'timestamp': datetime.now().isoformat(),
        'hot_sectors': hot,
        'cooling_sectors': cooling,
        'neutral_sectors': neutral,
        'rotation_multiplier': multiplier,
        'sector_performance_7d': {k: {kk: vv for kk, vv in v.items()} for k, v in perf.items()},
        'meta': {
            'generated_by': 'sector_rotation_logic.py',
            'known_bad_sectors': list(KNOWN_BAD_SECTORS),
            'logic': 'hot>50%WR x1.3-1.5 | neutral x1.0 | cooling<30% x0.5 | known-bad x0.0',
        }
    }

    OUTPUT.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"\n  ✅ Geschrieben: {OUTPUT}")
    print(f"  Multiplier: {multiplier}")

    return state


if __name__ == '__main__':
    run()
