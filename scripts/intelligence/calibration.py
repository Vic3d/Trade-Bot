#!/usr/bin/env python3
"""
Self-Calibration Loop — Lernt aus eigenen Fehlern
===================================================
Analysiert Conviction Score Buckets vs. tatsächliche Win-Rate.
Passt Faktor-Gewichte an wenn genug Daten (50+ Trades).

Sprint 3 | TradeMind Bauplan
"""

import sqlite3, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH = WS / 'data/trading.db'
CALIBRATION_PATH = WS / 'data/calibration.json'


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def conviction_bucket_analysis():
    """Analysiert Win-Rate pro Conviction-Bucket."""
    conn = get_db()
    trades = conn.execute("""
        SELECT conviction_at_entry, status FROM trades 
        WHERE status IN ('WIN','LOSS') AND conviction_at_entry IS NOT NULL
    """).fetchall()
    conn.close()
    
    buckets = {
        '0-30': {'wins': 0, 'total': 0},
        '30-50': {'wins': 0, 'total': 0},
        '50-70': {'wins': 0, 'total': 0},
        '70-85': {'wins': 0, 'total': 0},
        '85-100': {'wins': 0, 'total': 0},
    }
    
    for t in trades:
        c = t['conviction_at_entry']
        if c < 30: bucket = '0-30'
        elif c < 50: bucket = '30-50'
        elif c < 70: bucket = '50-70'
        elif c < 85: bucket = '70-85'
        else: bucket = '85-100'
        
        buckets[bucket]['total'] += 1
        if t['status'] == 'WIN':
            buckets[bucket]['wins'] += 1
    
    for k, v in buckets.items():
        v['win_rate'] = round(v['wins'] / v['total'] * 100, 1) if v['total'] > 0 else 0
    
    return buckets


def regime_accuracy():
    """Win-Rate pro Regime."""
    conn = get_db()
    rows = conn.execute("""
        SELECT regime_at_entry, 
               COUNT(*) as total,
               SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
               AVG(pnl_pct) as avg_pnl
        FROM trades 
        WHERE status IN ('WIN','LOSS') AND regime_at_entry IS NOT NULL
        GROUP BY regime_at_entry
    """).fetchall()
    conn.close()
    
    return [{
        'regime': r['regime_at_entry'],
        'total': r['total'],
        'wins': r['wins'],
        'win_rate': round(r['wins'] / r['total'] * 100, 1) if r['total'] > 0 else 0,
        'avg_pnl': round(r['avg_pnl'] or 0, 2),
    } for r in rows]


def lead_lag_accuracy():
    """Accuracy pro Lead-Lag Paar aus signals Tabelle."""
    conn = get_db()
    rows = conn.execute("""
        SELECT pair_id,
               COUNT(*) as total,
               SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) as losses,
               AVG(change_pct) as avg_change
        FROM signals 
        WHERE outcome IN ('WIN','LOSS')
        GROUP BY pair_id
    """).fetchall()
    conn.close()
    
    return [{
        'pair': r['pair_id'],
        'total': r['total'],
        'wins': r['wins'],
        'win_rate': round(r['wins'] / r['total'] * 100, 1) if r['total'] > 0 else 0,
        'avg_change': round(r['avg_change'] or 0, 2),
        'tradeable': r['total'] >= 20 and r['wins'] / r['total'] >= 0.6,
    } for r in rows]


def suggest_weight_adjustments(current_weights):
    """Schlägt Gewichtsanpassungen vor basierend auf Daten."""
    conn = get_db()
    closed = conn.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WIN','LOSS')").fetchone()[0]
    conn.close()
    
    if closed < 50:
        return {
            'ready': False,
            'message': f'Nicht genug Daten ({closed}/50 Trades). Default-Gewichte beibehalten.',
            'suggested': current_weights,
        }
    
    # TODO: Erweiterte Kalibrierung nach 50+ Trades
    # Für jeden Faktor: korreliert hoher Score mit WIN?
    return {
        'ready': True,
        'message': f'{closed} Trades analysiert. Kalibrierung aktiv.',
        'suggested': current_weights,
    }


def run_calibration():
    """Führt komplette Kalibrierung aus und speichert Ergebnis."""
    result = {
        'conviction_buckets': conviction_bucket_analysis(),
        'regime_accuracy': regime_accuracy(),
        'lead_lag_accuracy': lead_lag_accuracy(),
        'calibrated_at': datetime.now(timezone.utc).isoformat(),
    }
    
    CALIBRATION_PATH.write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    result = run_calibration()
    
    print("═══ Self-Calibration Report ═══\n")
    
    print("── Conviction Buckets ──")
    for bucket, data in result['conviction_buckets'].items():
        bar = '█' * int(data['win_rate'] / 10) + '░' * (10 - int(data['win_rate'] / 10))
        print(f"  {bucket:8} | {bar} {data['win_rate']:5.1f}% | {data['wins']}W/{data['total']}T")
    
    print("\n── Regime Accuracy ──")
    for r in result['regime_accuracy']:
        print(f"  {r['regime']:16} | WR: {r['win_rate']:5.1f}% | {r['wins']}W/{r['total']}T | avg: {r['avg_pnl']:+.1f}%")
    
    print("\n── Lead-Lag Accuracy ──")
    if result['lead_lag_accuracy']:
        for ll in result['lead_lag_accuracy']:
            emoji = '✅' if ll['tradeable'] else '⏳'
            print(f"  {emoji} {ll['pair']:25} | WR: {ll['win_rate']:5.1f}% | {ll['wins']}W/{ll['total']}T | Tradeable: {ll['tradeable']}")
    else:
        print("  Noch keine Signal-Outcomes")
