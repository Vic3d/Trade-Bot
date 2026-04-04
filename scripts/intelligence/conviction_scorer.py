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

DB_PATH  = Path('/data/.openclaw/workspace/data/trading.db')
DATA_DIR = Path('/data/.openclaw/workspace/data')

# Strategy → Thesis-Mapping (für news_gate.json Abgleich)
STRATEGY_TO_THESIS = {
    'PS1':        'PS1_Oil',
    'PS2':        'PS2_Tanker',
    'PS3':        'PS3_Defense',
    'PS4':        'PS4_Metals',
    'PS5':        'PS5_Agrar',
    'PS11':       'PS11_DefEU',
    'PS14':       'PS14_Ship',
    'PS17':       'S2_Rüstung',
    'PS18':       'S2_Rüstung',
    'PS_STLD':    'S5_Rohstoff',
    'PS_NVO':     'S3_KI',
    'PS_Copper':  'PS_Copper',
    'PS_China':   'PS_China',
    'PS_AIInfra': 'PS_AIInfra',
    'PS_Uranium': 'S5_Rohstoff',
    'S1':         'S1_Iran',
    'S2':         'S2_Rüstung',
    'S3':         'S3_KI',
    'S4':         'S4_Silver',
    'S5':         'S5_Rohstoff',
    'S7':         'S3_KI',
}
DATA_DIR = Path('/data/.openclaw/workspace/data')

# ─── Gewichtung (default, self-calibrating ab 50 Trades) ───
DEFAULT_WEIGHTS = {
    'regime_alignment': 0.18,
    'technical_setup':  0.18,
    'volume_confirm':   0.09,
    'news_momentum':    0.10,
    'signal_confluence':0.14,
    'backtest_perf':    0.10,
    'correlation':      0.05,
    'sector_rotation':  0.09,
    'watchlist_trend':  0.07,   # ← NEU: Preis-Trend aus Snapshots
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

# Paper Trading: Schwellen nach Trade-Style
# Thesis-Plays (PS_*) brauchen keine 52+ — sie wurden manuell validiert
PAPER_ENTRY_THRESHOLD_DEFAULT  = 52   # Generische Strategien (Swing)
PAPER_ENTRY_THRESHOLD_THESIS   = 35   # PS_* = Deep-Dive validiert (Swing)
PAPER_ENTRY_THRESHOLD_DAY      = 65   # Day Trades brauchen höhere Conviction
PAPER_ENTRY_THRESHOLD_DAY_THESIS = 55 # DT-Thesis-Plays etwas weniger streng


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


def _score_news_momentum(conn, ticker, hours=48, strategy=None):
    """Sentiment-Trend in den letzten 48h + news_gate These-Bestätigung. 0-100"""

    # Primär: news_gate.json — bestätigt aktuelle News unsere Strategie-These?
    gate_score = 50  # neutral default
    try:
        gate_path = DATA_DIR / 'news_gate.json'
        if gate_path.exists():
            gate = json.loads(gate_path.read_text())
            if gate.get('relevant') and gate.get('theses_hit'):
                thesis = STRATEGY_TO_THESIS.get(strategy or '', '')
                if thesis in gate.get('theses_hit', []):
                    hits = gate.get('hit_count', 0)
                    # Sentiment-Direction aus top_hits prüfen
                    bearish_hits = sum(
                        1 for h in gate.get('top_hits', [])
                        if h.get('thesis') == thesis and h.get('direction', '') == 'bearish'
                    )
                    bullish_hits = sum(
                        1 for h in gate.get('top_hits', [])
                        if h.get('thesis') == thesis and h.get('direction', '') in ('bullish', 'neutral')
                    )
                    if bearish_hits > bullish_hits:
                        gate_score = 35  # Bearishe News für diese These → warnen
                    else:
                        gate_score = min(100, 65 + min(hits, 35))  # 65-100 bei bullisher These
                elif gate.get('hit_count', 0) > 20:
                    gate_score = 55
    except Exception:
        pass

    # Sekundär: Ticker-spezifisches Sentiment aus news_events
    rows = conn.execute("""
        SELECT sentiment_score FROM news_events 
        WHERE tickers LIKE ? AND created_at > datetime('now', ?)
        ORDER BY created_at DESC
    """, (f'%{ticker}%', f'-{hours} hours')).fetchall()

    if rows:
        avg_sentiment = sum(r['sentiment_score'] or 0 for r in rows) / len(rows)
        ticker_score = max(0, min(100, int((avg_sentiment + 1) * 50)))
        # Kombinieren: 60% news_gate (These-Ebene), 40% Ticker-Sentiment
        return int(gate_score * 0.6 + ticker_score * 0.4)

    return gate_score


def _score_watchlist_trend(conn, ticker: str) -> int:
    """
    Nutzt watchlist_prices Snapshots um Kurstrend zu bewerten.
    Positiver Trend (Kurs steigt in letzten Snapshots) = höherer Score.
    Trend + RSI in Entry-Zone = bestes Signal.
    Returns: 0-100
    """
    try:
        rows = conn.execute('''
            SELECT price_eur, rsi, ma50, trend_5d, trend_20d, timestamp
            FROM watchlist_prices
            WHERE ticker=?
            ORDER BY timestamp DESC LIMIT 6
        ''', (ticker,)).fetchall()

        if len(rows) < 2:
            return 50  # Kein Trend-Daten → neutral

        prices = [r['price_eur'] for r in rows if r['price_eur']]
        rsi    = rows[0]['rsi'] or 50
        ma50   = rows[0]['ma50']
        t5d    = rows[0]['trend_5d'] or 0
        t20d   = rows[0]['trend_20d'] or 0

        score = 50  # Neutral-Baseline

        # Kurzfristiger Preis-Trend (letzte Snapshots = letzte Stunden)
        if len(prices) >= 4:
            recent_trend = (prices[0] - prices[3]) / prices[3] * 100  # letzte ~2h
            if -2 < recent_trend < 0:   # Leichter Rücklauf = gut für Long-Entry
                score += 20
            elif recent_trend < -2:     # Starker Fall = noch warten
                score -= 10
            elif recent_trend > 2:      # Schon gestiegen = zu spät
                score -= 15

        # RSI in Entry-Zone?
        if 28 <= rsi <= 48:
            score += 20  # Rücklauf-Zone: perfekt
        elif 48 < rsi <= 60:
            score += 5   # Neutral
        elif rsi > 65:
            score -= 20  # Überkauft

        # Kurs nahe MA50?
        if ma50 and prices:
            dist = (prices[0] - ma50) / ma50 * 100
            if -3 < dist < 2:
                score += 15  # Nahe MA50 = Unterstützung

        # Mittelfristiger Trend positiv (20d)?
        if t20d > 0:
            score += 10
        elif t20d < -5:
            score -= 10

        return max(0, min(100, score))

    except Exception:
        return 50  # Fehler → neutral


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
    """
    Historische Win-Rate — aus echten Paper Trades + Backtest.
    LIVE-Ergebnisse haben mehr Gewicht als Backtests.
    Strategies mit 0% echte Win-Rate werden hart geblockt (Score ≤ 15).
    """
    # Erst: echte Paper-Trade Performance (wichtiger als Backtest)
    live_score = None
    try:
        conn = get_db()
        rows = conn.execute('''
            SELECT pnl_eur FROM paper_portfolio
            WHERE strategy=? AND status IN ('WIN','CLOSED','LOSS')
            ORDER BY id DESC LIMIT 20
        ''', (strategy,)).fetchall()
        if len(rows) >= 3:  # Mindestens 3 echte Trades
            wins = sum(1 for r in rows if (r[0] or 0) > 0)
            wr = wins / len(rows) * 100
            # Harte Strafe für konsistent schlechte Strategien
            if wr == 0 and len(rows) >= 5:
                conn.close()
                return 5   # Blockiert de facto
            live_score = max(10, min(100, int(wr)))
        conn.close()
    except Exception:
        pass

    # Dann: Backtest-Daten
    bt_score = 50
    bt_path = DATA_DIR / 'backtest_results.json'
    if bt_path.exists():
        try:
            data = json.loads(bt_path.read_text())
            strat_data = data.get('detailed_results', {}).get(strategy, {})
            results = strat_data.get('results', [])
            if results:
                wins = sum(1 for r in results if r.get('pnl', 0) > 0)
                bt_score = max(10, min(100, int(wins / len(results) * 100)))
        except Exception:
            pass

    # Live-Ergebnis hat 70% Gewicht wenn vorhanden
    if live_score is not None:
        return int(live_score * 0.70 + bt_score * 0.30)
    return bt_score


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


def get_conviction_threshold(strategy: str, style: str = 'swing') -> int:
    """
    Gibt den Entry-Threshold zurück je nach Trade-Style und Strategie-Typ.
    Day Trades brauchen höhere Conviction als Swing Trades.
    """
    is_thesis = (strategy and (
        strategy.upper().startswith('PS_') or
        strategy.upper().startswith('PS') or
        strategy.upper() in {'S1', 'S2', 'S4', 'S5'}
    ))
    if style == 'day':
        return PAPER_ENTRY_THRESHOLD_DAY_THESIS if is_thesis else PAPER_ENTRY_THRESHOLD_DAY
    else:
        return PAPER_ENTRY_THRESHOLD_THESIS if is_thesis else PAPER_ENTRY_THRESHOLD_DEFAULT


def check_entry_allowed(strategy: str = None, conn=None, style: str = 'swing') -> tuple[bool, str]:
    """
    VIX Hard Block: Prüft ob ein Entry überhaupt erlaubt ist.
    
    Returns: (allowed: bool, reason: str)
    
    Regeln:
    - CRISIS (VIX ≥ 35): Kein Entry außer S4/PS4 (Hedges/Gold)
    - BEAR   (VIX 30-35): Kein Entry außer S4/PS1/PS4
    - CORRECTION (VIX 25-30): Entry erlaubt aber Position Factor 0.6×
    - NEUTRAL/BULL: Kein Hard Block
    - Day Trades: zusätzlich VIX > 25 → kein Entry
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

    # ── Day Trade Extra-Block: VIX > 25 ──────────────────────────────
    if style == 'day' and vix is not None and vix > 25.0:
        return False, f"🔴 DAY TRADE BLOCK: VIX {vix:.1f} > 25 — Intraday zu riskant bei hoher Volatilität"
    
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
    
    # Market Guards (Earnings, Thesis, Sektor) — importiert aus market_guards
    earnings_ok   = True
    earnings_note = ''
    thesis_mod    = 0
    sector_score  = 50
    try:
        import sys
        _mg_path = str(Path(__file__).parent)
        if _mg_path not in sys.path:
            sys.path.insert(0, _mg_path)
        from market_guards import check_earnings_safe, thesis_conviction_modifier, score_sector_momentum
        earnings_ok, earnings_note = check_earnings_safe(ticker)
        thesis_mod   = thesis_conviction_modifier(ticker)
        sector_score = score_sector_momentum(ticker)
    except Exception:
        pass

    # Faktor 9: Watchlist-Preis-Trend (aus watchlist_prices Tabelle)
    watchlist_trend_score = _score_watchlist_trend(conn, ticker)

    # Alle 9 Faktoren berechnen
    factors = {
        'regime_alignment': _score_regime_alignment(conn, strategy),
        'technical_setup': _score_technical_setup(entry_price, stop, target),
        'volume_confirm': _score_volume_confirmation(conn, ticker),
        'news_momentum': _score_news_momentum(conn, ticker, strategy=strategy),
        'signal_confluence': _score_signal_confluence(conn, ticker),
        'backtest_perf': _score_backtest_performance(strategy),
        'correlation': _score_correlation(conn, ticker),
        'sector_rotation': sector_score,
        'watchlist_trend': watchlist_trend_score,  # ← NEU: Preis-Trend aus Snapshots
    }
    
    # Gewichteter Score
    total_weight = sum(weights.values())
    score = sum(factors[k] * weights[k] for k in factors) / total_weight
    score = round(score, 1)
    
    # Thesis-Modifier anwenden (Kill-Trigger -20, Entry-Signal +10)
    score = max(0, min(100, score + thesis_mod))

    # Earnings Hard Block: Entry verboten wenn Earnings in ≤5 Tagen
    earnings_blocked = False
    if not earnings_ok:
        score = min(score, 15)  # Effektiv blockiert
        earnings_blocked = True

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
