#!/usr/bin/env python3
"""
Regime Detector v2 — Multi-Faktor Marktregime-Klassifikation
=============================================================
6 Regime-Typen basierend auf VIX, DXY, Yields, SP500 vs. MA200.
Regime-Velocity: wie schnell ändert sich das Regime?
Speichert Historie in regime_history Tabelle.

Sprint 2 | TradeMind Bauplan
"""

import sqlite3, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH = WS / 'data/trading.db'

# ─── 6 Regime-Typen ────────────────────────────────────────────
REGIMES = {
    'BULL_CALM': {
        'desc': 'Starker Aufwärtstrend, niedrige Volatilität',
        'position_factor': 1.2,
        'stop_factor': 0.8,
        'allowed_strategies': ['S1','S2','S3','S4','S5','S6','S7','PS1','PS2','PS3','PS4','PS5'],
    },
    'BULL_VOLATILE': {
        'desc': 'Aufwärtstrend mit Schwankungen',
        'position_factor': 1.0,
        'stop_factor': 1.0,
        'allowed_strategies': ['S1','S2','S3','S4','S5','S6','S7','PS1','PS2','PS3','PS4','PS5'],
    },
    'NEUTRAL': {
        'desc': 'Seitwärtsmarkt, moderate Volatilität',
        'position_factor': 0.8,
        'stop_factor': 1.2,
        'allowed_strategies': ['S1','S2','S4','S6','PS1','PS3','PS4'],
    },
    'CORRECTION': {
        'desc': 'Rücksetzer 5-10%, erhöhte Volatilität',
        'position_factor': 0.6,
        'stop_factor': 1.5,
        'allowed_strategies': ['S1','S4','PS1','PS3','PS4'],
    },
    'BEAR': {
        'desc': 'Abwärtstrend >10%, hohe Volatilität',
        'position_factor': 0.4,
        'stop_factor': 2.0,
        'allowed_strategies': ['S4','PS1','PS4'],
    },
    'CRISIS': {
        'desc': 'Panik, VIX >35, Nur Hedges',
        'position_factor': 0.25,
        'stop_factor': 2.5,
        'allowed_strategies': ['S4','PS4'],
    },
}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_macro(conn, indicator, date=None):
    """Holt letzten Wert eines Makro-Indikators."""
    if date:
        r = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator=? AND date<=? ORDER BY date DESC LIMIT 1",
            (indicator, date)
        ).fetchone()
    else:
        r = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator=? ORDER BY date DESC LIMIT 1",
            (indicator,)
        ).fetchone()
    return r['value'] if r else None


def get_sp500_ma200(conn, date=None):
    """SP500 vs. 200-Tage-MA Verhältnis."""
    if date:
        rows = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='SP500' AND date<=? ORDER BY date DESC LIMIT 200",
            (date,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='SP500' ORDER BY date DESC LIMIT 200"
        ).fetchall()
    
    if len(rows) < 50:
        return None
    
    current = rows[0]['value']
    ma200 = sum(r['value'] for r in rows) / len(rows)
    return round((current / ma200 - 1) * 100, 2)  # % über/unter MA200


def classify_regime(vix, dxy=None, us10y=None, us2y=None, sp500_vs_ma200=None):
    """
    Multi-Faktor Regime-Klassifikation.
    
    Primär: VIX (Hauptfaktor)
    Sekundär: SP500 vs MA200 (Trend-Bestätigung)
    Tertiär: Yield Curve (Rezessions-Indikator)
    """
    if vix is None:
        return 'NEUTRAL'
    
    # Primär-Klassifikation via VIX
    if vix < 15:
        regime = 'BULL_CALM'
    elif vix < 20:
        regime = 'BULL_VOLATILE'
    elif vix < 25:
        regime = 'NEUTRAL'
    elif vix < 30:
        regime = 'CORRECTION'
    elif vix < 35:
        regime = 'BEAR'
    else:
        regime = 'CRISIS'
    
    # Sekundär: SP500 vs MA200 kann Regime verschärfen
    if sp500_vs_ma200 is not None:
        if sp500_vs_ma200 < -10 and regime in ('NEUTRAL', 'CORRECTION'):
            regime = 'BEAR'  # Trend bestätigt Schwäche
        elif sp500_vs_ma200 > 5 and regime in ('NEUTRAL', 'BULL_VOLATILE'):
            regime = 'BULL_CALM'  # Trend bestätigt Stärke
    
    # Tertiär: Invertierte Yield Curve = Warnsignal
    if us10y and us2y and (us10y - us2y) < -0.5:
        # Invertiert → Rezessionswarnung, mindestens NEUTRAL
        if regime in ('BULL_CALM', 'BULL_VOLATILE'):
            regime = 'NEUTRAL'
    
    return regime


def detect_regime_velocity(conn, current_regime, lookback_days=10):
    """
    Misst wie schnell sich das Regime ändert.
    Returns: STABLE, SHIFTING, VOLATILE
    """
    rows = conn.execute("""
        SELECT regime FROM regime_history 
        ORDER BY date DESC LIMIT ?
    """, (lookback_days,)).fetchall()
    
    if len(rows) < 3:
        return 'UNKNOWN'
    
    regimes = [r['regime'] for r in rows]
    changes = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i-1])
    
    if changes == 0:
        return 'STABLE'
    elif changes <= 2:
        return 'SHIFTING'
    else:
        return 'VOLATILE'


def detect_current_regime(date=None):
    """
    Erkennt aktuelles Regime und speichert in DB.
    Returns: dict mit regime, velocity, factors
    """
    conn = get_db()
    
    vix = get_macro(conn, 'VIX', date)
    dxy = get_macro(conn, 'DXY', date)
    us10y = get_macro(conn, 'US10Y', date)
    us2y = get_macro(conn, 'US2Y', date)
    wti = get_macro(conn, 'WTI', date)
    gold = get_macro(conn, 'GOLD', date)
    sp500_vs_ma200 = get_sp500_ma200(conn, date)
    
    regime = classify_regime(vix, dxy, us10y, us2y, sp500_vs_ma200)
    velocity = detect_regime_velocity(conn, regime)
    
    today = date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    # In regime_history speichern
    conn.execute("""
        INSERT OR REPLACE INTO regime_history (date, regime, vix, dxy, us10y, us2y, wti, gold, sp500_vs_ma200, regime_velocity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (today, regime, vix, dxy, us10y, us2y, wti, gold, sp500_vs_ma200, velocity))
    conn.commit()
    
    # current_regime.json aktualisieren
    regime_data = {
        'date': today,
        'regime': regime,
        'velocity': velocity,
        'factors': {
            'vix': vix, 'dxy': dxy, 'us10y': us10y, 'us2y': us2y,
            'wti': wti, 'gold': gold, 'sp500_vs_ma200': sp500_vs_ma200
        },
        'config': REGIMES[regime],
        'updated_at': datetime.now(timezone.utc).isoformat()
    }
    
    json_path = DB_PATH.parent / 'current_regime.json'
    json_path.write_text(json.dumps(regime_data, indent=2))
    
    conn.close()
    return regime_data


def backfill_regime_history():
    """Backfill regime_history aus macro_daily."""
    conn = get_db()
    
    dates = conn.execute("""
        SELECT DISTINCT date FROM macro_daily WHERE indicator='VIX' ORDER BY date
    """).fetchall()
    
    filled = 0
    for row in dates:
        date = row['date']
        existing = conn.execute("SELECT 1 FROM regime_history WHERE date=?", (date,)).fetchone()
        if existing:
            continue
        
        vix = get_macro(conn, 'VIX', date)
        dxy = get_macro(conn, 'DXY', date)
        us10y = get_macro(conn, 'US10Y', date)
        us2y = get_macro(conn, 'US2Y', date)
        wti = get_macro(conn, 'WTI', date)
        gold = get_macro(conn, 'GOLD', date)
        sp500_vs_ma200 = get_sp500_ma200(conn, date)
        
        regime = classify_regime(vix, dxy, us10y, us2y, sp500_vs_ma200)
        
        conn.execute("""
            INSERT OR IGNORE INTO regime_history (date, regime, vix, dxy, us10y, us2y, wti, gold, sp500_vs_ma200)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, regime, vix, dxy, us10y, us2y, wti, gold, sp500_vs_ma200))
        filled += 1
    
    conn.commit()
    conn.close()
    return filled


def regime_summary():
    """Zusammenfassung der Regime-Verteilung."""
    conn = get_db()
    rows = conn.execute("""
        SELECT regime, COUNT(*) as days, 
               MIN(date) as first, MAX(date) as last,
               AVG(vix) as avg_vix
        FROM regime_history 
        GROUP BY regime ORDER BY days DESC
    """).fetchall()
    conn.close()
    return rows


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'backfill':
        filled = backfill_regime_history()
        print(f"✅ {filled} Tage Regime-History backfilled")
        
        for r in regime_summary():
            print(f"  {r['regime']:16} | {r['days']:4}d | VIX ø{r['avg_vix']:.1f} | {r['first']} → {r['last']}")
    
    else:
        result = detect_current_regime()
        print(f"═══ Regime Detector v2 ═══")
        print(f"  Regime: {result['regime']} ({REGIMES[result['regime']]['desc']})")
        print(f"  Velocity: {result['velocity']}")
        print(f"  VIX: {result['factors']['vix']} | DXY: {result['factors']['dxy']} | SP500 vs MA200: {result['factors']['sp500_vs_ma200']}%")
        print(f"  Position Factor: {result['config']['position_factor']} | Stop Factor: {result['config']['stop_factor']}")
        print(f"  Erlaubte Strategien: {result['config']['allowed_strategies']}")
