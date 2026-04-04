#!/usr/bin/env python3
"""
Conviction Scorer — Das Herzstück des autonomen Tradings
========================================================

Kombiniert:
  1. These-Bestätigung (News vs. Strategie-Thesis)
  2. Regime-Alignment (erlaubt die Marktlage diese Strategie?)
  3. Technisches Setup (RSI, MA50-Distanz, Volume)
  4. VIX-Faktor (Volatilitäts-Anpassung)

Output: Conviction Score 0-100
  0-30: BLOCK — zu niedrig
  30-60: CAUTION — nur kleine Position
  60-80: OK — normale Position
  80+: STRONG — größere Position erlaubt

Wird von paper_trade_engine.py und autonomous_scanner.py genutzt.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

WS = Path('/data/.openclaw/workspace')


# ── These-Taxonomie ──────────────────────────────────────────────────────────

THESIS_KEYWORDS = {
    'PS1_Oil': {
        'keywords': ['iran', 'hormuz', 'oil', 'brent', 'opec', 'crude', 'wti'],
        'tickers': ['TTE.PA', 'EQNR.OL', 'OXY', 'FRO', 'EQNR'],
        'bearish_keywords': ['biden', 'release', 'reserve', 'production up', 'eia'],
    },
    'PS2_Tanker': {
        'keywords': ['tanker', 'vlcc', 'shipping lane', 'suez', 'hormuz', 'freight'],
        'tickers': ['FRO', 'DHT'],
        'bearish_keywords': ['oversupply', 'normalization', 'rate down'],
    },
    'PS3_Defense': {
        'keywords': ['nato', 'defense', 'defense spending', 'militär', 'ukraine', 'rheinmetall', 'ktos', 'hii'],
        'tickers': ['RHM.DE', 'KTOS', 'HII', 'HAG.DE', 'BA.L', 'SAAB-B.ST'],
        'bearish_keywords': ['peace', 'ceasefire', 'talks', 'negoti'],
    },
    'PS4_Silver': {
        'keywords': ['silver', 'silber', 'precious metal', 'inflation', 'hedge'],
        'tickers': ['HL', 'PAAS', 'AG', 'ISPA.DE'],
        'bearish_keywords': ['rate hike', 'deflation', 'usd strength'],
    },
    'PS5_Agriculture': {
        'keywords': ['fertilizer', 'dünger', 'agriculture', 'mosaic', 'mos', 'potash', 'crop'],
        'tickers': ['MOS'],
        'bearish_keywords': ['surplus', 'low prices', 'oversupply'],
    },
    'PS14_Shipping': {
        'keywords': ['shipping', 'container', 'freight', 'zim', 'normalization', 'demand'],
        'tickers': ['ZIM', 'MATX', 'SBLK'],
        'bearish_keywords': ['slowdown', 'recession', 'overcapacity'],
    },
}


def load_news_gate() -> dict:
    """Lädt aktuelle news_gate.json — zeigt welche Thesen gerade News-Bestätigung haben."""
    try:
        path = WS / 'data/news_gate.json'
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {'relevant': False, 'theses_hit': [], 'hit_count': 0}


def load_ceo_directive() -> dict:
    """Lädt CEO Directive — Regime, VIX, Trade Rules."""
    try:
        path = WS / 'data/ceo_directive.json'
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {'mode': 'NEUTRAL', 'regime': 'NEUTRAL', 'vix': 20.0, 'geo_score': 0}


def get_current_regime() -> str:
    """Liest aktuelles HMM-Regime aus ceo_directive."""
    directive = load_ceo_directive()
    return directive.get('regime', 'NEUTRAL')


def get_current_vix() -> float:
    """Liest aktuellen VIX aus ceo_directive."""
    directive = load_ceo_directive()
    return directive.get('vix', 20.0)


def get_regime_weights() -> dict:
    """Regime-spezifische Strategie-Gewichte."""
    regime = get_current_regime()
    
    weights = {
        'BULL': {
            'PS1_Oil': 0.8,      # Öl-These weaker in bull
            'PS2_Tanker': 0.9,   # Tanker schwach
            'PS3_Defense': 0.6,  # Defense nicht bevorzugt
            'PS4_Silver': 0.5,   # Silver ist defensiv
            'PS5_Agriculture': 0.7,
            'PS14_Shipping': 0.8,
        },
        'NEUTRAL': {
            'PS1_Oil': 1.0,
            'PS2_Tanker': 1.0,
            'PS3_Defense': 1.0,
            'PS4_Silver': 1.0,
            'PS5_Agriculture': 1.0,
            'PS14_Shipping': 1.0,
        },
        'RISK_OFF': {
            'PS1_Oil': 1.0,      # Geopolitik-Premium
            'PS2_Tanker': 1.2,   # Shipping-Lag bei Volatilität
            'PS3_Defense': 1.3,  # Defense stark
            'PS4_Silver': 1.5,   # Silver ist safe haven
            'PS5_Agriculture': 0.8,
            'PS14_Shipping': 0.7,
        },
        'CRASH': {
            'PS1_Oil': 1.2,      # Öl-Prämie max
            'PS2_Tanker': 1.1,   # Tanker volatil
            'PS3_Defense': 1.5,  # Defense max
            'PS4_Silver': 1.8,   # Silver ist ultimate hedge
            'PS5_Agriculture': 0.5,
            'PS14_Shipping': 0.3,
        }
    }
    
    return weights.get(regime, weights['NEUTRAL'])


def score_thesis_alignment(strategy: str, ticker: str, news_gate: dict) -> int:
    """
    These-Bestätigung: haben aktuelle News diese Strategie-These bestätigt?
    
    Returns: 0-40 Punkte
      0  = keine News für diese These
      20 = These in News erwähnt
      40 = These in TOP Hits oder HIGH Geo-Score
    """
    if strategy not in THESIS_KEYWORDS:
        return 0
    
    # News-Gate Treffer?
    if strategy in news_gate.get('theses_hit', []):
        return 35  # Top Hit
    
    # Geo-Score check (für geopolitische Thesen)
    if strategy in ['PS1_Oil', 'PS3_Defense', 'PS2_Tanker']:
        geo_score = news_gate.get('geo_score', 0) or load_ceo_directive().get('geo_score', 0)
        if geo_score >= 70:
            return 30  # High geo relevance
        elif geo_score >= 50:
            return 20
    
    # Standard: etwas Bestätigung wenn Neuigkeit vorhanden
    if news_gate.get('hit_count', 0) > 0:
        return 15
    
    return 0


def score_regime_alignment(strategy: str) -> int:
    """
    Regime-Alignment: erlaubt das aktuelle Regime diese Strategie?
    
    Returns: -10 bis +30 Punkte
      -10 = Regime blockt diese These
       0  = neutral
      +30 = Regime bevorzugt diese These
    """
    regime = get_current_regime()
    weights = get_regime_weights()
    
    weight = weights.get(strategy, 1.0)
    
    if weight < 0.7:
        return -10  # Regime blockt
    elif weight > 1.3:
        return 30   # Regime bevorzugt stark
    elif weight > 1.0:
        return 20   # Regime bevorzugt leicht
    else:
        return 0    # Neutral


def score_technical_setup(ticker: str, entry_price: float, current_price: float = None) -> int:
    """
    Technisches Setup: RSI, MA50-Distanz, Volume
    
    Returns: 0-20 Punkte
    
    Holt Daten aus trading.db (historische Daten vom feature_collector)
    """
    try:
        conn = sqlite3.connect(str(WS / 'data/trading.db'))
        cur = conn.cursor()
        
        # Neueste OHLCV-Daten
        cur.execute("""
            SELECT close, rsi, volume
            FROM daily_bars
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT 1
        """, (ticker,))
        row = cur.fetchone()
        
        if not row:
            conn.close()
            return 10  # Default wenn keine Daten
        
        close, rsi, volume = row
        current_price = current_price or close
        
        score = 0
        
        # RSI-Score: optimal 40-60 (nicht überkauft)
        if rsi is not None:
            if 40 <= rsi <= 60:
                score += 10  # Ideal
            elif 30 <= rsi < 70:
                score += 5   # OK
            # else 0 — überkauft/überverkauft
        
        # Einstiegs-Timing: nicht zu tief unter MA50
        # (würde auf separate MA50-Berechnung prüfen, hier vereinfacht)
        # Für jetzt: +5 wenn entry_price sinnvoll gewählt
        if entry_price > 0:
            drawdown = (current_price - entry_price) / entry_price
            if -0.05 <= drawdown <= 0.10:  # -5% to +10% ok
                score += 5
        
        conn.close()
        return min(score, 20)
        
    except Exception:
        return 10  # Fallback


def score_vix_factor() -> int:
    """
    VIX-Anpassung: hohe Volatilität reduziert Conviction minimal
    
    Returns: -5 bis 0 Punkte
      0   = VIX < 18 (niedrig, normal)
      -3  = VIX 20-25
      -5  = VIX > 30 (hoch, riskant)
    """
    vix = get_current_vix()
    
    if vix < 18:
        return 0
    elif vix < 25:
        return -2
    elif vix < 30:
        return -4
    else:
        return -5


def check_entry_allowed(
    ticker: str,
    strategy: str,
    entry_price: float,
    current_price: float = None
) -> dict:
    """
    HAUPTFUNKTION — berechnet Conviction Score und entscheidet ob Trade erlaubt
    
    Args:
        ticker: z.B. 'TTE.PA'
        strategy: z.B. 'PS1_Oil'
        entry_price: Entry-Preis in EUR
        current_price: aktueller Kurs (optional, wird sonst aus DB geholt)
    
    Returns: {
        'allowed': bool,
        'score': 0-100,
        'reasoning': str,
        'components': {
            'thesis_alignment': int,
            'regime_alignment': int,
            'technical': int,
            'vix_factor': int,
        }
    }
    """
    
    # Komponenten berechnen
    news_gate = load_news_gate()
    
    thesis_score = score_thesis_alignment(strategy, ticker, news_gate)
    regime_score = score_regime_alignment(strategy)
    technical_score = score_technical_setup(ticker, entry_price, current_price)
    vix_score = score_vix_factor()
    
    total_score = thesis_score + max(0, regime_score) + technical_score + vix_score
    total_score = max(0, min(100, total_score))  # Clamp 0-100
    
    # Entscheidung
    allowed = total_score >= 40
    
    if total_score < 30:
        reason = "❌ BLOCK — Conviction zu niedrig"
    elif total_score < 50:
        reason = "⚠️ CAUTION — nur kleine Position"
    elif total_score < 70:
        reason = "✅ OK — normale Position"
    elif total_score < 85:
        reason = "🟢 STRONG — größere Position erlaubt"
    else:
        reason = "🔥 MAXIMUM — volle Überzeugung"
    
    return {
        'allowed': allowed,
        'score': total_score,
        'reasoning': reason,
        'components': {
            'thesis_alignment': thesis_score,
            'regime_alignment': max(0, regime_score),
            'technical': technical_score,
            'vix_factor': max(0, vix_score),
        },
        'regime': get_current_regime(),
        'vix': get_current_vix(),
    }


def calculate_conviction(
    ticker: str,
    strategy: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    current_price: float = None
) -> dict:
    """
    Erweiterte Version mit Risk-Reward Berechnung
    
    Returns: {
        'score': 0-100,
        'allowed': bool,
        'risk_reward': float,
        'position_size_factor': 0.0-2.0,
        ...
    }
    """
    
    result = check_entry_allowed(ticker, strategy, entry_price, current_price)
    
    # Risk-Reward Ratio
    risk = entry_price - stop_price
    reward = target_price - entry_price
    risk_reward = reward / risk if risk > 0 else 0
    
    # Position-Size Anpassung basierend auf Conviction + RRR
    if result['score'] >= 80 and risk_reward >= 2.0:
        position_factor = 2.0  # 2x größer
    elif result['score'] >= 70 and risk_reward >= 1.5:
        position_factor = 1.5
    elif result['score'] >= 50 and risk_reward >= 1.0:
        position_factor = 1.0
    elif result['score'] >= 40:
        position_factor = 0.5  # Halb-Position
    else:
        position_factor = 0.0  # Kein Trade
    
    result['risk_reward'] = round(risk_reward, 2)
    result['position_size_factor'] = position_factor
    result['advice'] = (
        f"{result['reasoning']} | RRR {risk_reward:.1f}:1 | "
        f"Regime {result['regime']} | VIX {result['vix']:.1f}"
    )
    
    return result


if __name__ == '__main__':
    # Test
    print("=== Conviction Scorer Test ===")
    print()
    
    test_cases = [
        ('TTE.PA', 'PS1_Oil', 77.56, 72.83, 85.0),
        ('RHM.DE', 'PS3_Defense', 1409.5, 1479.98, 1550.0),
        ('DHT', 'PS2_Tanker', 22.0, 20.0, 26.0),
    ]
    
    for ticker, strategy, entry, stop, target in test_cases:
        result = calculate_conviction(ticker, strategy, entry, stop, target)
        print(f"{ticker} ({strategy})")
        print(f"  Score: {result['score']:.0f} | {result['reasoning']}")
        print(f"  Components: {result['components']}")
        print(f"  RRR: {result['risk_reward']:.1f}:1 | Position: {result['position_size_factor']:.1f}x")
        print()
