"""
VIX Context Module — ersetzt absoluten VIX-Wert durch kontextuellen Score.
Drei Dimensionen: Perzentil (52W), Term Structure (Spot/3M), Asset-Korrelation.
"""
import sqlite3, json
from pathlib import Path
from datetime import datetime, timedelta

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'

def get_vix_percentile() -> dict:
    """
    Berechnet VIX 52-Wochen-Perzentil aus macro_daily Tabelle.
    Returns: {vix_current, vix_percentile, vix_52w_high, vix_52w_low, context_label}
    """
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    # macro_daily ist ein Key-Value Store: indicator='VIX', value=Kurs
    rows = db.execute("""
        SELECT date, value AS vix FROM macro_daily 
        WHERE indicator = 'VIX'
        AND value IS NOT NULL 
        AND date >= date('now', '-365 days')
        ORDER BY date ASC
    """).fetchall()
    
    if not rows or len(rows) < 10:
        return {"vix_percentile": 50, "context_label": "UNKNOWN", "n_observations": 0}
    
    values = [r['vix'] for r in rows]
    current = values[-1]
    below_current = sum(1 for v in values if v <= current)
    percentile = round(below_current / len(values) * 100, 1)
    
    if percentile < 25: label = "CALM"
    elif percentile < 50: label = "NORMAL"
    elif percentile < 75: label = "ELEVATED"
    elif percentile < 90: label = "HIGH"
    else: label = "EXTREME"
    
    return {
        "vix_current": current,
        "vix_percentile": percentile,
        "vix_52w_high": max(values),
        "vix_52w_low": min(values),
        "context_label": label,
        "n_observations": len(values)
    }

def get_vix_term_structure() -> dict:
    """
    Holt VIX (Spot) und VIX3M via Yahoo Finance.
    Ratio < 1.0 = Contango (normal/ruhig)
    Ratio > 1.0 = Backwardation (akute Angst)
    """
    import urllib.request
    
    def fetch(ticker):
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                import json as j
                d = j.load(r)
            return d['chart']['result'][0]['meta'].get('regularMarketPrice')
        except:
            return None
    
    vix_spot = fetch('^VIX')
    vix_3m = fetch('^VIX3M')
    
    if not vix_spot:
        return {"term_structure": "UNKNOWN", "ratio": None}
    
    if not vix_3m:
        # Fallback: schätze VIX3M als 105% von Spot (historischer Durchschnitt)
        vix_3m = vix_spot * 1.05
    
    ratio = round(vix_spot / vix_3m, 3)
    
    if ratio < 0.85: structure = "STEEP_CONTANGO"      # Sehr beruhigt
    elif ratio < 0.95: structure = "CONTANGO"           # Normal
    elif ratio < 1.05: structure = "FLAT"               # Neutral
    elif ratio < 1.15: structure = "BACKWARDATION"      # Akute Angst
    else: structure = "STEEP_BACKWARDATION"              # Extremer Stress
    
    return {
        "vix_spot": vix_spot,
        "vix_3m": vix_3m,
        "ratio": ratio,
        "term_structure": structure,
        "interpretation": "Akute Angst" if ratio > 1.0 else "Kontango (normal)"
    }

# Asset-VIX-Korrelations-Definitionen
ASSET_VIX_CORRELATION = {
    # Stark positiv = fallen stark bei VIX-Spike → VIX-Limit voll anwenden
    "NVDA": +0.85, "PLTR": +0.80, "MSFT": +0.75, "AMD": +0.82, "GOOGL": +0.70,
    "SMCI": +0.85, "ANET": +0.78, "DELL": +0.72, "QQQ": +0.85,
    # Leicht positiv → halber VIX-Abschlag
    "BAYN.DE": +0.45, "SAP.DE": +0.50, "ASML.AS": +0.60, "LHA.DE": +0.40,
    # Neutral/schwach
    "VALE": +0.20, "FCX": +0.25, "TECK": +0.20, "GLEN.L": +0.15,
    # Negativ / Safe Haven = profitieren bei VIX-Spike → kein VIX-Limit
    "BZ=F": -0.30, "OXY": -0.25, "EQNR": -0.20, "EQNR.OL": -0.20,
    "TTE.PA": -0.22, "PSX": -0.18, "XOM": -0.20, "CVX": -0.22,
    "FRO": -0.35, "DHT": -0.38, "ZIM": -0.15,
    "RHM.DE": -0.40, "KTOS": -0.30, "LMT": -0.25, "RTX": -0.22, "NOC": -0.20,
    "SAAB-B.ST": -0.35, "HII": -0.20, "BA": +0.10,
    "GC=F": -0.45, "SI=F": -0.30, "GOLD": -0.40, "NEM": -0.35,
    "AG": -0.25, "HL": -0.20, "PAAS": -0.22, "WPM": -0.30,
    "A3D42Y": -0.30, "A2DWAW": +0.30,
}

def get_asset_vix_sensitivity(ticker: str) -> dict:
    """
    Gibt VIX-Sensitivität für einen Ticker zurück.
    Positive Korrelation = fällt bei VIX-Spike
    Negative Korrelation = steigt bei VIX-Spike
    """
    corr = ASSET_VIX_CORRELATION.get(ticker, 0.0)
    
    if corr > 0.6: category = "HIGH_SENSITIVITY"    # Stark geblockt bei VIX > threshold
    elif corr > 0.3: category = "MODERATE_SENSITIVITY"  # Abschlag
    elif corr > -0.1: category = "LOW_SENSITIVITY"  # Minimaler Abschlag
    else: category = "NEGATIVE_CORRELATION"          # Kein VIX-Block
    
    return {
        "ticker": ticker,
        "correlation": corr,
        "category": category,
        "vix_block_applies": corr > 0.3
    }

def calculate_position_multiplier(ticker: str, vix: float, percentile: float = 50) -> float:
    """
    Berechnet Positions-Größen-Multiplikator basierend auf VIX + Asset-Korrelation.
    
    Ersetzt den harten VIX > 27 Switch durch kontinuierliche Kurve.
    
    Returns: 0.0 (block) bis 1.0 (volle Größe)
    """
    sensitivity = get_asset_vix_sensitivity(ticker)
    corr = sensitivity["correlation"]
    
    # Negative Korrelation → nie blocken, volle Größe (profitiert von Stress)
    if corr < -0.1:
        return 1.0
    
    # Basisabschlag durch VIX-Level (nur für positive Korrelation)
    if vix <= 20:
        base_mult = 1.0
    elif vix <= 40:
        base_mult = max(0.4, 1.0 - (vix - 20) / 33.3)
    else:
        base_mult = 0.4
    
    # Perzentil-Korrektur: bei sehr hohem Perzentil etwas vorsichtiger
    if percentile > 90:
        base_mult *= 0.85
    
    # Asset-Korrelation skaliert den Abschlag
    # Stark positiv (0.8) → voller Abschlag
    # Leicht positiv (0.3) → halber Abschlag
    correlation_weight = min(1.0, max(0.0, (corr - 0.3) / 0.5))
    final_mult = 1.0 - (1.0 - base_mult) * correlation_weight
    
    # Hard block nur für stark positiv korrelierte Assets bei extremem VIX
    if corr > 0.6 and vix > 35 and percentile > 85:
        return 0.0  # Echtes Block (wie vorher, aber nur für Tech bei VIX 35+)
    
    return round(final_mult, 2)

if __name__ == "__main__":
    ctx = get_vix_percentile()
    ts = get_vix_term_structure()
    print(f"VIX: {ctx.get('vix_current', 'N/A')} | Perzentil: {ctx['vix_percentile']}% ({ctx['context_label']})")
    print(f"Term Structure: {ts['term_structure']} | Ratio: {ts.get('ratio', 'N/A')}")
    print("\nBeispiel-Multiplier bei VIX 31, Perzentil 85%:")
    for t in ['NVDA', 'PLTR', 'EQNR', 'DHT', 'RHM.DE', 'GC=F', 'BAYN.DE']:
        m = calculate_position_multiplier(t, 31.0, 85.0)
        s = get_asset_vix_sensitivity(t)
        print(f"  {t:12s}: {m:.2f}x  ({s['category']}, corr={s['correlation']:+.2f})")
