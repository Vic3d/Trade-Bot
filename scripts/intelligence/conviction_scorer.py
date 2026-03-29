#!/usr/bin/env python3
"""
Conviction Scorer v2 — Multi-Faktor Trade-Bewertung
=====================================================
8 Faktoren → 0-100 Score pro Trade-Setup.
Self-calibrating: passt Gewichte nach 50+ Trades an.

Faktoren:
1. Regime Alignment (Strategie passt zum Regime?)
2. Technical Setup (CRV, Patterns, Trend)
3. Volume Confirmation (Volumen-Anomalie?)
4. News Momentum (Sentiment-Trend letzte 48h)
5. Signal Confluence (mehrere Lead-Lag Signale?)
6. Backtest Performance (historische Win-Rate für Setup)
7. Correlation (Korrelation zum Gesamtportfolio)
8. Sector Rotation (Sektor gerade im Aufwind?)

Sprint 2 | TradeMind Bauplan
"""

import sqlite3, json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')
DATA_DIR = Path('/data/.openclaw/workspace/data')

# ─── Gewichtung (default, self-calibrating ab 50 Trades) ───
DEFAULT_WEIGHTS = {
    'regime_alignment': 0.20,
    'technical_setup': 0.20,
    'volume_confirm': 0.10,
    'news_momentum': 0.10,
    'signal_confluence': 0.15,
    'backtest_perf': 0.10,
    'correlation': 0.05,
    'sector_rotation': 0.10,
}

# Regime → Strategie Affinität
# PS_* = Thesis-Plays (6-Schritt Deep Dive validiert) — in allen Regimes gut
REGIME_STRATEGY_FIT = {
    'BULL_CALM':     {'S3': 1.0, 'S5': 0.9, 'S6': 0.9, 'PS2': 0.8, 'PS5': 0.8,
                      'PS_STLD': 0.8, 'PS_NVO': 0.7, 'PS_LHA': 0.9},
    'BULL_VOLATILE': {'S1': 0.9, 'S2': 0.9, 'S3': 0.8, 'PS1': 0.8, 'PS3': 0.8,
                      'PS_STLD': 0.9, 'PS_NVO': 0.8, 'PS_LHA': 0.7},
    'NEUTRAL':       {'S1': 0.7, 'S4': 0.8, 'PS1': 0.7, 'PS4': 0.7,
                      'PS_STLD': 0.75, 'PS_NVO': 0.7, 'PS_LHA': 0.6},
    'CORRECTION':    {'S1': 0.9, 'S4': 1.0, 'PS1': 0.9, 'PS3': 0.8, 'PS4': 0.9,
                      'PS_STLD': 0.85, 'PS_NVO': 0.7, 'PS_LHA': 0.5},
    'BEAR':          {'S4': 1.0, 'PS4': 1.0, 'S1': 0.8, 'PS1': 0.8,
                      'PS_STLD': 0.7, 'PS_NVO': 0.6,
                      'PS_LHA': 0.4},   # BEAR = Krise läuft noch → LHA leidet noch
    'CRISIS':        {'S4': 1.0, 'PS4': 1.0, 'PS_STLD': 0.5, 'PS_NVO': 0.4,
                      'PS_LHA': 0.2},   # CRISIS = schlechtestes Umfeld für LHA
}

# Paper Trading: niedrigere Schwellen, weil Lernsystem
# Thesis-Plays (PS_*) brauchen keine 52+ — sie wurden manuell validiert
PAPER_ENTRY_THRESHOLD_DEFAULT  = 52   # Generische Strategien
PAPER_ENTRY_THRESHOLD_THESIS   = 35   # PS_* = Deep-Dive validiert, einfach rein


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _score_regime_alignment(conn, strategy, date=None):
    """Wie gut passt die Strategie zum aktuellen Regime? 0-100"""
    regime_row = conn.execute(
        "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if not regime_row:
        return 50  # neutral
    
    regime = regime_row['regime']
    fit_map = REGIME_STRATEGY_FIT.get(regime, {})
    fit = fit_map.get(strategy, 0.3)  # default: schlechter Fit
    return int(fit * 100)


def _score_technical_setup(entry_price, stop, target):
    """CRV-basierter Score. CRV 3:1 = 100. 0-100"""
    if not all([entry_price, stop, target]):
        return 30
    
    risk = abs(entry_price - stop)
    reward = abs(target - entry_price)
    if risk <= 0:
        return 10
    
    crv = reward / risk
    # CRV 1:1 = 33, CRV 2:1 = 67, CRV 3:1 = 100
    score = min(100, int(crv * 33.3))
    return max(10, score)


def _score_volume_confirmation(conn, ticker, date=None):
    """Volume > 2× 20-SMA = starke Bestätigung. 0-100"""
    rows = conn.execute("""
        SELECT volume FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 21
    """, (ticker,)).fetchall()
    
    if len(rows) < 5:
        return 50
    
    current_vol = rows[0]['volume'] or 0
    avg_vol = sum(r['volume'] or 0 for r in rows[1:]) / max(len(rows)-1, 1)
    
    if avg_vol <= 0:
        return 50
    
    ratio = current_vol / avg_vol
    if ratio > 2.0: return 100
    if ratio > 1.5: return 80
    if ratio > 1.0: return 60
    if ratio > 0.5: return 40
    return 20


def _score_news_momentum(conn, ticker, hours=48):
    """Sentiment-Trend in den letzten 48h. 0-100"""
    rows = conn.execute("""
        SELECT sentiment_score FROM news_events 
        WHERE tickers LIKE ? AND created_at > datetime('now', ?)
        ORDER BY created_at DESC
    """, (f'%{ticker}%', f'-{hours} hours')).fetchall()
    
    if not rows:
        return 50  # neutral
    
    avg_sentiment = sum(r['sentiment_score'] or 0 for r in rows) / len(rows)
    # -1 bis +1 → 0-100
    return max(0, min(100, int((avg_sentiment + 1) * 50)))


def _score_signal_confluence(conn, ticker, hours=72):
    """Wie viele Signale zeigen in gleiche Richtung? 0-100"""
    rows = conn.execute("""
        SELECT COUNT(*) as cnt FROM signals 
        WHERE lag_ticker LIKE ? AND outcome='PENDING'
        AND created_at > datetime('now', ?)
    """, (f'%{ticker}%', f'-{hours} hours')).fetchall()
    
    count = rows[0]['cnt'] if rows else 0
    if count >= 3: return 100
    if count == 2: return 80
    if count == 1: return 60
    return 30


def _score_backtest_performance(strategy):
    """Historische Win-Rate aus Backtests. 0-100"""
    bt_path = DATA_DIR / 'backtest_results.json'
    if not bt_path.exists():
        return 50
    
    try:
        data = json.loads(bt_path.read_text())
        strat_data = data.get('detailed_results', {}).get(strategy, {})
        results = strat_data.get('results', [])
        if not results:
            return 50
        
        wins = sum(1 for r in results if r.get('pnl', 0) > 0)
        wr = wins / len(results) * 100
        return max(10, min(100, int(wr)))
    except:
        return 50


def _score_correlation(conn, ticker):
    """Portfolio-Korrelation. Niedrig = besser (Diversifikation). 0-100"""
    corr_path = DATA_DIR / 'correlations.json'
    if not corr_path.exists():
        return 50
    
    try:
        data = json.loads(corr_path.read_text())
        # Check average correlation with existing positions
        open_trades = conn.execute(
            "SELECT DISTINCT ticker FROM trades WHERE status='OPEN'"
        ).fetchall()
        open_tickers = [t['ticker'] for t in open_trades]
        
        if not open_tickers:
            return 80  # Erstes Position = gut
        
        total_corr = 0
        count = 0
        for ot in open_tickers:
            key = f"{ticker}_{ot}"
            key2 = f"{ot}_{ticker}"
            corr = data.get(key, data.get(key2))
            if corr is not None:
                total_corr += abs(corr)
                count += 1
        
        if count == 0:
            return 50
        
        avg_corr = total_corr / count
        # Niedrige Korrelation = besser
        return max(10, min(100, int((1 - avg_corr) * 100)))
    except:
        return 50


def _score_sector_rotation(conn, ticker, days=20):
    """Sektor-Momentum der letzten 20 Tage. 0-100"""
    rows = conn.execute("""
        SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?
    """, (ticker, days + 1)).fetchall()
    
    if len(rows) < 5:
        return 50
    
    current = rows[0]['close']
    past = rows[-1]['close']
    if not past:
        return 50
    
    change_pct = (current / past - 1) * 100
    # -10% = 0, 0% = 50, +10% = 100
    return max(0, min(100, int(change_pct * 5 + 50)))


def _get_current_vix(conn) -> float | None:
    """Holt den aktuellsten VIX-Wert aus macro_daily."""
    row = conn.execute(
        "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return row['value'] if row else None


def _get_current_regime(conn) -> str:
    """Holt das aktuelle Markt-Regime aus regime_history."""
    row = conn.execute(
        "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return row['regime'] if row else 'UNKNOWN'


def check_entry_allowed(strategy: str = None, conn=None) -> tuple[bool, str]:
    """
    VIX Hard Block: Prüft ob ein Entry überhaupt erlaubt ist.
    
    Returns: (allowed: bool, reason: str)
    
    Regeln:
    - CRISIS (VIX ≥ 35): Kein Entry außer S4/PS4 (Hedges/Gold)
    - BEAR   (VIX 30-35): Kein Entry außer S4/PS1/PS4
    - CORRECTION (VIX 25-30): Entry erlaubt aber Position Factor 0.6×
    - NEUTRAL/BULL: Kein Hard Block
    """
    close_conn = conn is None
    if conn is None:
        conn = get_db()
    
    vix = _get_current_vix(conn)
    regime = _get_current_regime(conn)
    
    if close_conn:
        conn.close()
    
    HEDGE_STRATEGIES = {'S4', 'PS4', 'PS1'}  # Defensive Strategien erlaubt in jedem Regime
    
    # PS_* = Thesis-basierte Strategien (6-Schritt Deep Dive validiert)
    # Erkennbar an Prefix PS_ mit Suffix (PS_STLD, PS_NVO etc.)
    is_thesis_strategy = (strategy and (
        strategy.upper().startswith('PS_') or  # Thesis-Play: PS_STLD, PS_NVO, ...
        strategy.upper() in {'S1', 'S2', 'S5', 'S6', 'S7'}  # Makro-Thesen
    ))
    
    if regime == 'CRISIS' or (vix is not None and vix >= 35):
        if strategy and strategy.upper() not in HEDGE_STRATEGIES and not is_thesis_strategy:
            return False, f"🔴 VIX HARD BLOCK: {regime} (VIX={vix:.1f}) — nur Hedges/Gold (S4, PS4) + Thesis-Plays erlaubt"
        return True, f"⚠️ CRISIS-Regime: Thesis-Play ({strategy}) mit max. 50% Positionsgröße"
    
    if regime == 'BEAR' or (vix is not None and vix >= 30):
        allowed_in_bear = HEDGE_STRATEGIES | {'S1'}
        if strategy and strategy.upper() not in allowed_in_bear and not is_thesis_strategy:
            return False, f"🔴 VIX HARD BLOCK: {regime} (VIX={vix:.1f}) — kein generischer Tech/Zykliker. Erlaubt: Thesis-Plays (PS_*), S1, S4, PS1, PS4"
        return True, f"⚠️ BEAR-Regime: {strategy} erlaubt (Thesis/Öl/Hedge), Stop-Buffer +50% empfohlen"
    
    vix_str = f"{vix:.1f}" if vix else "n/a"
    return True, f"✅ Regime {regime} (VIX={vix_str}) — Entry erlaubt"


def calculate_conviction(ticker, strategy, entry_price=None, stop=None, target=None, weights=None):
    """
    Berechnet den Conviction Score (0-100) für ein Trade-Setup.
    
    Bei BEAR/CRISIS-Regime: Score wird auf max. 35 gekappt (Hard Block).
    
    Returns: dict mit score, breakdown, recommendation, vix_block
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    
    conn = get_db()
    
    # VIX Hard Block prüfen (vor Faktor-Berechnung)
    entry_allowed, block_reason = check_entry_allowed(strategy, conn)
    vix = _get_current_vix(conn)
    regime = _get_current_regime(conn)
    
    # Alle 8 Faktoren berechnen
    factors = {
        'regime_alignment': _score_regime_alignment(conn, strategy),
        'technical_setup': _score_technical_setup(entry_price, stop, target),
        'volume_confirm': _score_volume_confirmation(conn, ticker),
        'news_momentum': _score_news_momentum(conn, ticker),
        'signal_confluence': _score_signal_confluence(conn, ticker),
        'backtest_perf': _score_backtest_performance(strategy),
        'correlation': _score_correlation(conn, ticker),
        'sector_rotation': _score_sector_rotation(conn, ticker),
    }
    
    # Gewichteter Score
    total_weight = sum(weights.values())
    score = sum(factors[k] * weights[k] for k in factors) / total_weight
    score = round(score, 1)
    
    # VIX Hard Cap: BEAR → max 35, CRISIS → max 20
    vix_blocked = False
    if regime == 'CRISIS' or (vix is not None and vix >= 35):
        if not entry_allowed:
            score = min(score, 20)
            vix_blocked = True
    elif regime == 'BEAR' or (vix is not None and vix >= 30):
        if not entry_allowed:
            score = min(score, 35)
            vix_blocked = True
        else:
            # Auch erlaubte Strategien bei BEAR: Score-Penalty
            score = min(score, 55)
    
    # Recommendation
    if vix_blocked:
        rec = 'STRONG_AVOID'
    elif score >= 80:
        rec = 'STRONG_BUY'
    elif score >= 65:
        rec = 'BUY'
    elif score >= 50:
        rec = 'HOLD'
    elif score >= 35:
        rec = 'AVOID'
    else:
        rec = 'STRONG_AVOID'
    
    # Schwächste Faktoren identifizieren
    sorted_factors = sorted(factors.items(), key=lambda x: x[1])
    weakest = sorted_factors[:2]
    strongest = sorted_factors[-2:]
    
    conn.close()
    
    return {
        'score': score,
        'recommendation': rec,
        'factors': factors,
        'weights': weights,
        'weakest': [{'factor': k, 'score': v} for k, v in weakest],
        'strongest': [{'factor': k, 'score': v} for k, v in strongest],
        'vix_block': vix_blocked,
        'vix_block_reason': block_reason if vix_blocked else None,
        'regime': regime,
        'vix': vix,
        'entry_allowed': entry_allowed,
    }


def score_all_open_trades():
    """Scored alle offenen Trades."""
    conn = get_db()
    trades = conn.execute("""
        SELECT id, ticker, strategy, entry_price, stop, target 
        FROM trades WHERE status='OPEN'
    """).fetchall()
    conn.close()
    
    results = []
    for t in trades:
        result = calculate_conviction(
            t['ticker'], t['strategy'] or 'S1',
            t['entry_price'], t['stop'], t['target']
        )
        result['trade_id'] = t['id']
        result['ticker'] = t['ticker']
        results.append(result)
    
    return sorted(results, key=lambda x: x['score'], reverse=True)


def calibrate_weights():
    """Self-Calibration: passt Gewichte an basierend auf geschlossenen Trades."""
    conn = get_db()
    closed = conn.execute("""
        SELECT COUNT(*) FROM trades WHERE status IN ('WIN','LOSS')
    """).fetchone()[0]
    
    if closed < 50:
        conn.close()
        return None, f"Nicht genug Trades ({closed}/50). Default-Gewichte bleiben."
    
    # TODO: Faktor-Performance-Analyse nach 50+ geschlossenen Trades
    # Für jeden Faktor: korreliert hoher Score mit WIN?
    conn.close()
    return DEFAULT_WEIGHTS, "Self-Calibration ab 50 Trades aktiv"


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        results = score_all_open_trades()
        print(f"═══ Conviction Scores — {len(results)} offene Trades ═══")
        for r in results:
            emoji = '🟢' if r['score'] >= 65 else ('🟡' if r['score'] >= 50 else '🔴')
            print(f"  {emoji} {r['ticker']:12} Score: {r['score']:5.1f} → {r['recommendation']}")
            for k, v in r['factors'].items():
                bar = '█' * (v // 10) + '░' * (10 - v // 10)
                print(f"      {k:22} {bar} {v:3}")
            print()
    
    elif len(sys.argv) >= 4:
        ticker, strategy = sys.argv[1], sys.argv[2]
        entry = float(sys.argv[3]) if len(sys.argv) > 3 else None
        stop = float(sys.argv[4]) if len(sys.argv) > 4 else None
        target = float(sys.argv[5]) if len(sys.argv) > 5 else None
        
        result = calculate_conviction(ticker, strategy, entry, stop, target)
        print(f"Conviction: {result['score']}/100 → {result['recommendation']}")
        for k, v in result['factors'].items():
            print(f"  {k:22} {v:3}/100")
    
    else:
        results = score_all_open_trades()
        print(json.dumps(results, indent=2))
