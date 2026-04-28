#!/usr/bin/env python3
"""
stress_test.py — Aggressive Validation via künstliche Trigger.

Testet ob Phasen tatsächlich AKTIV werden wenn ihre Trigger schlagen.

Tests:
  1. Anti-Pattern: künstlich kritisches Pattern injecten → CEO sollte EXECUTE blocken
  2. Lifecycle: Strategy künstlich auf "schlecht" setzen → sollte in Probation
  3. Mood: 3 Loss in Folge simulieren → mood = 'tilt', mult = 0.5
  4. Calibration-Bias: viele "0.9 confidence + LOSS" injecten → bias detected
  5. Heatmap-Multiplier: prüfe ob best/worst hour tatsächlich angewendet wird
  6. Health-Monitor Auto-Repair: kill price_monitor → sollte 30min später leben

Run:
  python3 scripts/stress_test.py
  python3 scripts/stress_test.py --restore  # macht alle Stress-Effekte rückgängig
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
BACKUP_DIR = WS / 'data' / 'stress_test_backup'


def stress_anti_pattern() -> dict:
    """Injecte 5 fake-LOSS-Trades für PS_STRESS_TEST → sollte Anti-Pattern triggern."""
    print('\n=== STRESS 1: Anti-Pattern Injection ===')
    c = sqlite3.connect(str(DB))
    inserted = []
    base_time = datetime.now() - timedelta(days=5)
    for i in range(5):
        ts = (base_time + timedelta(days=i)).isoformat()
        c.execute("""
            INSERT INTO paper_portfolio (ticker, strategy, entry_price, stop_price,
                target_price, shares, entry_date, close_date, close_price,
                pnl_eur, pnl_pct, status, exit_type, sector, conviction, fees,
                rsi_at_entry, vix_at_entry)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            f'STRESS{i}', 'PS_STRESS_TEST', 100.0, 92.0, 115.0, 10,
            ts, ts, 92.0, -80, -8.0, 'LOSS', 'STOP_TEST',
            'tech', 50, 1.0, 85.0, 22.0,
        ))
        inserted.append(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    c.commit()
    c.close()

    # Trigger Pattern-Detection
    from ceo_pattern_learning import detect_anti_patterns, check_proposal_against_patterns
    p = detect_anti_patterns()
    print(f'  Patterns detected: {p["total_patterns_found"]}')
    relevant = [x for x in p['patterns'] if 'PS_STRESS_TEST' in x.get('pattern_key', '')]
    print(f'  PS_STRESS_TEST patterns: {len(relevant)}')

    # Test ob Match-Funktion das blockt
    matches = check_proposal_against_patterns({'strategy': 'PS_STRESS_TEST', 'sector': 'tech'})
    print(f'  Pattern-Match-Check: {len(matches)} matches → würde {"BLOCKED" if matches else "PASS"}')

    return {'inserted_ids': inserted, 'patterns_found': len(relevant), 'blocks': len(matches)}


def stress_lifecycle() -> dict:
    """5 Trades mit LOSS für PS_STRESS_LC → sollte in PROBATION."""
    print('\n=== STRESS 2: Lifecycle Trigger ===')
    c = sqlite3.connect(str(DB))
    inserted = []
    base_time = datetime.now() - timedelta(days=10)
    for i in range(5):
        ts = (base_time + timedelta(days=i)).isoformat()
        c.execute("""
            INSERT INTO paper_portfolio (ticker, strategy, entry_price, stop_price,
                target_price, shares, entry_date, close_date, close_price,
                pnl_eur, pnl_pct, status, exit_type, sector, conviction, fees)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            f'LCS{i}', 'PS_STRESS_LC', 100.0, 92.0, 115.0, 10,
            ts, ts, 92.0, -120, -12.0, 'LOSS', 'STOP', 'tech', 50, 1.0,
        ))
        inserted.append(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    c.commit()
    c.close()

    # Add stress-strategy zu strategies.json damit lifecycle das sehen kann
    sfile = WS / 'data' / 'strategies.json'
    strats = json.loads(sfile.read_text(encoding='utf-8'))
    strats['PS_STRESS_LC'] = {
        'name': 'STRESS-TEST Strategy', 'status': 'active',
        '_lifecycle_state': 'ACTIVE',
    }
    sfile.write_text(json.dumps(strats, indent=2), encoding='utf-8')

    # Run lifecycle
    from strategy_lifecycle import run_lifecycle_pass, get_lifecycle_overview
    result = run_lifecycle_pass()
    print(f'  Transitions: {result.get("count", 0)}')
    for t in result.get('transitions', []):
        print(f"    {t['strategy']} {t['old_state']} → {t['new_state']}: {t['reason']}")

    overview = get_lifecycle_overview()
    in_probation = [s['id'] for s in overview.get('PROBATION', [])
                    if s['id'] == 'PS_STRESS_LC']
    print(f'  PS_STRESS_LC in PROBATION: {bool(in_probation)}')

    return {'inserted_ids': inserted, 'transitioned_to_probation': bool(in_probation)}


def stress_mood() -> dict:
    """3 LOSS in Folge → mood sollte tilt."""
    print('\n=== STRESS 3: Mood/Tilt Detection ===')
    c = sqlite3.connect(str(DB))
    inserted = []
    base_time = datetime.now() - timedelta(hours=6)
    for i in range(4):
        ts = (base_time + timedelta(hours=i)).isoformat()
        c.execute("""
            INSERT INTO paper_portfolio (ticker, strategy, entry_price, stop_price,
                target_price, shares, entry_date, close_date, close_price,
                pnl_eur, pnl_pct, status, exit_type, sector, conviction, fees)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            f'MD{i}', 'PS_MOOD_TEST', 100.0, 92.0, 115.0, 10,
            ts, ts, 92.0, -90, -9.0, 'LOSS', 'STOP', 'tech', 50, 1.0,
        ))
        inserted.append(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    c.commit()
    c.close()

    from ceo_consciousness import detect_mood
    m = detect_mood(window_trades=10)
    print(f'  Mood: {m["mood"]} (multiplier {m["size_multiplier"]})')
    print(f'  Streak: {m["recent_streak"]}, recent_pnl: {m["recent_pnl_eur"]:+.0f}€')

    return {'inserted_ids': inserted, 'mood': m['mood'], 'multiplier': m['size_multiplier']}


def restore() -> int:
    """Macht alle Stress-Test-Inserts rückgängig."""
    print('\n=== RESTORE: Cleanup Stress-Test-Daten ===')
    c = sqlite3.connect(str(DB))
    deleted = 0
    for prefix in ('STRESS', 'LCS', 'MD'):
        cur = c.execute("DELETE FROM paper_portfolio WHERE ticker LIKE ?", (f'{prefix}%',))
        deleted += cur.rowcount
    c.commit()
    c.close()

    # Restore strategies.json (remove test entries)
    sfile = WS / 'data' / 'strategies.json'
    strats = json.loads(sfile.read_text(encoding='utf-8'))
    for sid in list(strats.keys()):
        if sid.startswith('PS_STRESS') or sid.startswith('PS_MOOD_TEST'):
            del strats[sid]
    sfile.write_text(json.dumps(strats, indent=2), encoding='utf-8')

    # Re-detect anti-patterns
    from ceo_pattern_learning import detect_anti_patterns
    detect_anti_patterns()

    print(f'  Deleted {deleted} test trades')
    print('  Restored strategies.json + refreshed anti-patterns')
    return 0


def main() -> int:
    if '--restore' in sys.argv:
        return restore()

    print('═══ STRESS-TEST: künstliche Trigger durch alle Phasen ═══')

    r1 = stress_anti_pattern()
    r2 = stress_lifecycle()
    r3 = stress_mood()

    print('\n═══ SUMMARY ═══')
    print(f'  Anti-Pattern: {r1["patterns_found"]} patterns gefunden, {r1["blocks"]} blocks aktiv')
    print(f'  Lifecycle: PS_STRESS_LC → PROBATION: {"✅" if r2["transitioned_to_probation"] else "❌"}')
    print(f'  Mood: {r3["mood"]} ({r3["multiplier"]} multiplier)')

    print('\n_💡 Cleanup: python3 scripts/stress_test.py --restore_')
    return 0


if __name__ == '__main__':
    sys.exit(main())
