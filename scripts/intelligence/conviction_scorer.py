#!/usr/bin/env python3
"""
Conviction Scorer v3 — 4-Faktor Trade-Bewertung
================================================
Replaces the old 9-factor broken scorer with 4 properly calibrated factors:

1. Thesis Strength     (35 pts max) — Is the macro thesis still valid?
2. Technical Alignment (30 pts max) — Trend/RSI/Volume confirming?
3. Risk/Reward Quality (20 pts max) — CRV + stop placement
4. Market Context      (15 pts max) — VIX environment

Scoring thresholds:
  >= 60 : STRONG  → 2% risk sizing
  >= 45 : MODERATE → 1% risk sizing
  <  45 : WEAK    → skip trade

ENTRY_THRESHOLD = 45

Albert | TradeMind v3 | 2026-04-10
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WS       = Path('/data/.openclaw/workspace')
DB_PATH  = WS / 'data' / 'trading.db'
DATA_DIR = WS / 'data'

ENTRY_THRESHOLD = 50  # Phase 25: war 45, jetzt 50 (höhere Selektion)

# Adaptive Gewichte — werden wöchentlich aus Trade-Ergebnissen berechnet
CONVICTION_WEIGHTS_FILE = DATA_DIR / 'conviction_weights.json'
DEFAULT_WEIGHTS = {'thesis': 35, 'technical': 30, 'risk_reward': 20, 'market_context': 15}


# ─── DB Helper ────────────────────────────────────────────────────────────────

def _get_current_vix(conn=None) -> float:
    """Liest aktuellen VIX aus DB. Gibt 20.0 als Fallback zurück."""
    try:
        should_close = conn is None
        if conn is None:
            conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if should_close:
            conn.close()
        return float(row[0]) if row else 20.0
    except Exception:
        return 20.0


def _get_current_regime(conn=None) -> str:
    """Liest aktuelles Marktregime aus DB. Gibt UNKNOWN als Fallback zurück."""
    try:
        should_close = conn is None
        if conn is None:
            conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if should_close:
            conn.close()
        return str(row[0]) if row else 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ─── Factor 1: Thesis Strength (0-35 pts) ────────────────────────────────────

def _score_thesis_strength(strategy: str, ticker: str = '') -> tuple[int, str]:
    """
    Evaluates whether the macro thesis behind this strategy is still valid.

    Returns: (score: int, reason: str)
    If thesis is INVALIDATED: returns (0, 'BLOCK') — caller should skip trade.

    Scoring:
      ACTIVE thesis:   base 20 pts
      + entry_trigger keywords match recent thesis_checks: +5 to +15 pts
      DEGRADED thesis: cap at 15 pts
      INVALIDATED:     return 0 immediately (block)
    """
    # Load strategies.json
    strategies = {}
    try:
        strategies_path = DATA_DIR / 'strategies.json'
        if strategies_path.exists():
            strategies = json.loads(strategies_path.read_text(encoding='utf-8'))
    except Exception:
        pass

    strategy_cfg = strategies.get(strategy, {})
    json_status = strategy_cfg.get('status', 'active').lower()

    # Check thesis_status table in DB
    db_status = None
    health_score = 100
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT status, health_score FROM thesis_status WHERE thesis_id = ?",
            (strategy,)
        ).fetchone()
        conn.close()
        if row:
            db_status = row['status']
            health_score = row['health_score'] or 100
    except Exception:
        pass

    # DB status takes precedence over JSON status
    effective_status = db_status or ('ACTIVE' if json_status == 'active' else 'PAUSED')

    if effective_status == 'INVALIDATED':
        return (0, 'BLOCK: thesis INVALIDATED — kill trigger fired')

    if effective_status == 'DEGRADED':
        # Check for entry_trigger confirmation bonus (capped at 15)
        entry_bonus = _check_entry_trigger_bonus(strategy, strategy_cfg)
        score = min(15, 10 + entry_bonus)
        return (score, f'DEGRADED thesis — capped at {score}/15')

    if effective_status in ('ACTIVE', 'WATCHING', 'EVALUATING'):
        base = 20
        entry_bonus = _check_entry_trigger_bonus(strategy, strategy_cfg)
        score = min(35, base + entry_bonus)
        return (score, f'ACTIVE thesis — {score}/35 (bonus={entry_bonus})')

    # PAUSED or unknown
    return (10, f'thesis status {effective_status} — partial credit 10/35')


def _check_entry_trigger_bonus(strategy: str, strategy_cfg: dict) -> int:
    """
    Checks recent thesis_checks table for entry trigger confirmations.
    Returns 0-15 bonus points.
    """
    entry_trigger = strategy_cfg.get('entry_trigger', '')
    if not entry_trigger:
        return 0

    # Parse entry trigger keywords
    import re
    keywords = [k.strip().lower() for k in re.split(r'[,;|]|\bOR\b|\bODER\b', entry_trigger, flags=re.IGNORECASE)
                if len(k.strip()) >= 4]
    if not keywords:
        return 0

    # Check thesis_checks table for recent positive matches
    try:
        conn = get_db()
        rows = conn.execute(
            """
            SELECT news_headline, direction FROM thesis_checks
            WHERE thesis_id = ?
              AND datetime(checked_at) >= datetime('now', '-48 hours')
              AND kill_trigger_match = 0
            ORDER BY checked_at DESC LIMIT 20
            """,
            (strategy,)
        ).fetchall()
        conn.close()

        if not rows:
            return 0

        combined = ' '.join((r['news_headline'] or '') for r in rows).lower()
        matches = sum(1 for kw in keywords if kw in combined)

        if matches >= 3:
            return 15
        elif matches == 2:
            return 10
        elif matches == 1:
            return 5
        return 0
    except Exception:
        return 0


# ─── Factor 2: Technical Alignment (0-30 pts) ─────────────────────────────────

def _score_technical_alignment(
    entry_price: float | None,
    ema20: float | None,
    ema50: float | None,
    rsi: float | None,
    vol_ratio: float | None,
) -> tuple[int, str]:
    """
    Technical factor scoring:
      trend_aligned (price > ema20 > ema50): +12 pts
      momentum_in_range (RSI 40-72):        +10 pts
      volume_confirms (vol_ratio >= 0.8):   +8 pts

    Returns: (score, breakdown_str)
    """
    score = 0
    parts = []

    # Trend alignment: price > EMA20 > EMA50
    if entry_price and ema20 and ema50:
        if entry_price > ema20 > ema50:
            score += 12
            parts.append('trend+12')
        elif entry_price > ema50:
            score += 5
            parts.append('trend~+5')
        else:
            parts.append('trend+0')
    else:
        # Partial credit if some data available
        score += 5
        parts.append('trend_nodata+5')

    # RSI momentum in healthy range (40-72)
    if rsi is not None:
        if 40 <= rsi <= 72:
            score += 10
            parts.append(f'rsi({rsi:.0f})+10')
        elif 35 <= rsi < 40 or 72 < rsi <= 78:
            score += 5
            parts.append(f'rsi({rsi:.0f})+5')
        else:
            parts.append(f'rsi({rsi:.0f})+0')
    else:
        score += 5
        parts.append('rsi_nodata+5')

    # Volume confirmation
    if vol_ratio is not None:
        if vol_ratio >= 0.8:
            score += 8
            parts.append(f'vol({vol_ratio:.1f})+8')
        elif vol_ratio >= 0.5:
            score += 4
            parts.append(f'vol({vol_ratio:.1f})+4')
        else:
            parts.append(f'vol({vol_ratio:.1f})+0')
    else:
        score += 3
        parts.append('vol_nodata+3')

    return (min(30, score), ' | '.join(parts))


def _fetch_technical_data(ticker: str, entry_price: float | None) -> dict:
    """
    Fetches EMA20, EMA50, RSI, volume ratio from DB prices table.
    Returns dict with keys: ema20, ema50, rsi, vol_ratio (all may be None).
    """
    result = {'ema20': None, 'ema50': None, 'rsi': None, 'vol_ratio': None}
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT close, volume FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 55",
            (ticker,)
        ).fetchall()
        conn.close()

        closes  = [r['close']  for r in rows if r['close']  is not None]
        volumes = [r['volume'] for r in rows if r['volume'] is not None]

        if len(closes) >= 20:
            result['ema20'] = sum(closes[:20]) / 20  # Simple MA as proxy
        if len(closes) >= 50:
            result['ema50'] = sum(closes[:50]) / 50

        # RSI calculation (14-period)
        if len(closes) >= 15:
            gains, losses = [], []
            for i in range(14):
                diff = closes[i] - closes[i + 1]
                if diff > 0:
                    gains.append(diff)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(diff))
            avg_gain = sum(gains) / 14 or 0.001
            avg_loss = sum(losses) / 14 or 0.001
            rs = avg_gain / avg_loss
            result['rsi'] = 100 - (100 / (1 + rs))

        # Volume ratio: today vs 20-day average
        if len(volumes) >= 2:
            current_vol = volumes[0]
            avg_vol = sum(volumes[1:min(21, len(volumes))]) / max(len(volumes) - 1, 1)
            if avg_vol > 0:
                result['vol_ratio'] = current_vol / avg_vol

    except Exception:
        pass
    return result


# ─── Factor 3: Risk/Reward Quality (0-20 pts) ─────────────────────────────────

def _score_risk_reward(
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    atr: float | None = None,
) -> tuple[int, str]:
    """
    CRV-based score + ATR stop placement check.

    CRV >= 3.0: 20 pts
    CRV >= 2.5: 15 pts
    CRV >= 2.0: 10 pts
    CRV <  2.0: 0 pts (block)

    stop_distance check:
      wider than 3x ATR: -5 pts penalty

    Returns: (score, reason)
    If CRV < 2.0 returns (0, 'BLOCK: CRV too low')
    """
    if not entry_price or not stop_price or not target_price:
        return (10, 'no_price_data — partial 10/20')

    risk = abs(entry_price - stop_price)
    reward = abs(target_price - entry_price)

    if risk <= 0:
        return (0, 'BLOCK: zero risk distance')

    crv = reward / risk

    if crv >= 3.0:
        base = 20
    elif crv >= 2.5:
        base = 15
    elif crv >= 2.0:
        base = 10
    else:
        return (0, f'BLOCK: CRV {crv:.2f} < 2.0 minimum')

    # ATR stop distance penalty
    penalty = 0
    if atr and atr > 0:
        stop_dist_atr = risk / atr
        if stop_dist_atr > 3.0:
            penalty = 5

    score = max(0, base - penalty)
    penalty_str = f' (-{penalty} wide_stop)' if penalty else ''
    return (score, f'CRV={crv:.2f} → {score}/20{penalty_str}')


# ─── Factor 4: Market Context (0-15 pts) ──────────────────────────────────────

def _score_market_context(strategy: str) -> tuple[int, str]:
    """
    VIX-based market context score.

    VIX < 20:    15 pts
    VIX 20-25:   10 pts
    VIX 25-30:    5 pts
    VIX > 30:     0 pts (no block — just no points)

    Regime fit modifier (up to +5, capped at 15 total):
      strategy preferred_regime matches current regime → small bonus
    """
    vix = None
    regime = 'UNKNOWN'

    try:
        conn = get_db()
        vix_row = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if vix_row:
            vix = vix_row['value']

        regime_row = conn.execute(
            "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if regime_row:
            regime = regime_row['regime']
        conn.close()
    except Exception:
        pass

    # Fallback: read from market-regime.json
    if vix is None or regime == 'UNKNOWN':
        try:
            regime_file = DATA_DIR / 'market-regime.json'
            if regime_file.exists():
                data = json.loads(regime_file.read_text())
                if vix is None:
                    vix = data.get('vix')
                if regime == 'UNKNOWN':
                    regime = data.get('current_regime', 'UNKNOWN')
        except Exception:
            pass

    # VIX score
    if vix is None:
        vix_score = 7  # neutral/unknown
        vix_str = 'VIX=n/a'
    elif vix < 20:
        vix_score = 15
        vix_str = f'VIX={vix:.1f}<20'
    elif vix < 25:
        vix_score = 10
        vix_str = f'VIX={vix:.1f} 20-25'
    elif vix < 30:
        vix_score = 5
        vix_str = f'VIX={vix:.1f} 25-30'
    else:
        vix_score = 0
        vix_str = f'VIX={vix:.1f}>30'

    # Regime fit: check strategy's preferred_regime
    regime_bonus = 0
    try:
        strategies = {}
        strategies_path = DATA_DIR / 'strategies.json'
        if strategies_path.exists():
            strategies = json.loads(strategies_path.read_text(encoding='utf-8'))
        s_cfg = strategies.get(strategy, {})
        preferred = s_cfg.get('preferred_regime', s_cfg.get('regime', ''))
        if preferred and regime and preferred.upper() in regime.upper():
            regime_bonus = 3
    except Exception:
        pass

    # CRASH hard block — kein Trading in Crash-Regimen
    if regime and 'CRASH' in regime.upper():
        return (-999, f'BLOCK: Crash-Regime ({regime}) — Trading gesperrt')

    # BEAR regime: Conviction-Abzug
    bear_penalty = 0
    if regime and regime.upper() in ('BEAR', 'BEARISH', 'RISK_OFF'):
        bear_penalty = -5

    score = min(15, max(0, vix_score + regime_bonus + bear_penalty))
    bonus_str = f' +{regime_bonus}regime_fit' if regime_bonus else ''
    bear_str  = f' {bear_penalty}bear' if bear_penalty else ''
    return (score, f'{vix_str}{bonus_str}{bear_str} → {score}/15')


# ─── Factor 5: Priced-In Check (-20 to +5) ───────────────────────────────────

def _score_priced_in(ticker: str, entry_price: float | None = None) -> tuple[int, str]:
    """
    Variant Perception Gate: Has the market already priced in this thesis?

    Checks distance from 52-week high and 6-month momentum.
    A thesis on a stock at 52W-high = zero edge. The market already knows.

    Scoring (penalty modifier):
      <5%  from 52W high:  -20 pts  (thesis fully priced in — everyone knows)
      5-15% from 52W high: -10 pts  (partially priced in)
      15-30% from 52W high:  0 pts  (neutral)
      >30% from 52W high:   +5 pts  (beaten down — market may NOT know yet)

    Additional 6M momentum penalty:
      6M return >50%: -5 pts (thesis has already run)
      6M return >30%: -3 pts (running hot)

    Returns: (modifier: int, reason: str)
    """
    try:
        conn = get_db()
        # Last 252 trading days (~1 year)
        rows = conn.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 252",
            (ticker,)
        ).fetchall()
        conn.close()

        closes = [r['close'] for r in rows if r['close'] is not None]
        if len(closes) < 20:
            return (0, 'priced_in=n/a (no data)')

        current = entry_price if entry_price else closes[0]
        high_52w = max(closes[:min(252, len(closes))])

        # Distance from 52W high (negative = below high)
        dist_pct = (current - high_52w) / high_52w  # e.g. -0.05 = 5% below high

        if dist_pct >= -0.05:  # within 5% of 52W high
            dist_penalty = -20
            dist_str = f'{abs(dist_pct)*100:.1f}%_from_52Wh=-20'
        elif dist_pct >= -0.15:  # 5-15% below high
            dist_penalty = -10
            dist_str = f'{abs(dist_pct)*100:.1f}%_from_52Wh=-10'
        elif dist_pct >= -0.30:  # 15-30% below high
            dist_penalty = 0
            dist_str = f'{abs(dist_pct)*100:.1f}%_from_52Wh=0'
        else:  # >30% below high — beaten down
            dist_penalty = 5
            dist_str = f'{abs(dist_pct)*100:.1f}%_from_52Wh=+5'

        # 6M momentum check (~126 trading days)
        mom_penalty = 0
        mom_str = ''
        if len(closes) >= 126:
            price_6m_ago = closes[125]
            if price_6m_ago > 0:
                return_6m = (current - price_6m_ago) / price_6m_ago
                if return_6m > 0.50:
                    mom_penalty = -5
                    mom_str = f' +6M_run({return_6m*100:.0f}%)=-5'
                elif return_6m > 0.30:
                    mom_penalty = -3
                    mom_str = f' +6M_run({return_6m*100:.0f}%)=-3'

        total_modifier = dist_penalty + mom_penalty
        return (total_modifier, f'priced_in: {dist_str}{mom_str} → {total_modifier:+d}')

    except Exception as e:
        return (0, f'priced_in=n/a ({e})')


# ─── Factor 6: Alpha Decay + DNA ──────────────────────────────────────────────

def _apply_decay_and_dna(strategy: str) -> tuple[int, str]:
    """
    Modifier basierend auf Alpha-Decay-Trend + DNA-Kill-Warning.

    Alpha Decay (data/alpha_decay.json):
      trend == 'DECAYING'  → -10 (Strategie verliert Edge)
      trend == 'IMPROVING' → +5  (Strategie gewinnt Edge)

    DNA (data/dna.json):
      kill_warning = True  → -5  (Strategie auf der Abschuss-Liste)
      win_rate > 0.60      → +5  (Strategie überperformt)

    Returns: (modifier: int, reason: str)
    """
    modifier = 0
    parts = []

    # ── Alpha Decay Check ──────────────────────────────────────────────
    try:
        decay_file = DATA_DIR / 'alpha_decay.json'
        if decay_file.exists():
            decay_data = json.loads(decay_file.read_text(encoding='utf-8'))
            s_decay = decay_data.get(strategy, {})
            trend  = s_decay.get('trend', '')
            status = s_decay.get('status', '')
            if trend == 'DECAYING' or status == 'DECAYING':
                modifier -= 10
                parts.append('alpha_decay=-10')
            elif trend == 'IMPROVING':
                modifier += 5
                parts.append('alpha_improving=+5')
    except Exception:
        pass

    # ── DNA Check: Strategie-Performance-Warnung ───────────────────────
    try:
        dna_file = DATA_DIR / 'dna.json'
        if dna_file.exists():
            dna = json.loads(dna_file.read_text(encoding='utf-8'))
            for s in dna.get('strategies', []):
                if s.get('id') == strategy or s.get('strategy') == strategy:
                    if s.get('kill_warning'):
                        modifier -= 5
                        parts.append('dna_kill=-5')
                    elif (s.get('win_rate') or 0) > 0.60:
                        modifier += 5
                        parts.append('dna_wr=+5')
                    break
    except Exception:
        pass

    reason = ' | '.join(parts) if parts else 'decay+dna=0'
    return (modifier, reason)


# ─── Position Sizing ──────────────────────────────────────────────────────────

def get_position_size(
    score: float,
    portfolio_value: float,
    entry_price: float,
    stop_price: float,
) -> int:
    """
    Phase 25 — Conviction-Brackets:
      score >= 70: 2.5% risk (HIGH_CONVICTION)  → ~2.000€ Position
      score >= 60: 2.0% risk (STRONG)           → ~1.500€ Position
      score >= 50: 1.0% risk (MODERATE)         → ~1.000€ Position
      else:        0 shares (skip)

    Capped at 8% of portfolio per position (war 5%, jetzt mehr Spielraum für High-Conviction).
    Returns number of shares (integer).
    """
    if score < ENTRY_THRESHOLD:
        return 0

    if score >= 70:
        risk_pct = 0.025
    elif score >= 60:
        risk_pct = 0.02
    else:
        risk_pct = 0.01

    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0:
        return 0

    risk_amount = portfolio_value * risk_pct
    shares = int(risk_amount / risk_per_share)

    # Cap at 8% of portfolio per position (Phase 25: war 5%)
    max_shares = int(portfolio_value * 0.08 / entry_price)
    return min(shares, max_shares)


# ─── Adaptive Weights + Backtest Factor ──────────────────────────────────────

def _load_adaptive_weights() -> dict:
    """
    Lädt adaptive Gewichte aus conviction_weights.json.
    Fallback zu DEFAULT_WEIGHTS wenn Datei fehlt, veraltet oder zu wenig Trades.
    """
    try:
        if CONVICTION_WEIGHTS_FILE.exists():
            data = json.loads(CONVICTION_WEIGHTS_FILE.read_text(encoding='utf-8'))
            # Max 7 Tage alt
            computed_at = data.get('computed_at', '')
            if computed_at:
                from datetime import timedelta
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(computed_at)).days
                if age > 7:
                    return DEFAULT_WEIGHTS.copy()
            # Min 20 Trades Datenbasis
            if data.get('trade_count', 0) < 20:
                return DEFAULT_WEIGHTS.copy()
            weights = data.get('weights', {})
            # Validierung: alle Keys vorhanden und im Bereich [10, 50]
            for key in DEFAULT_WEIGHTS:
                if key not in weights or not (10 <= weights[key] <= 50):
                    return DEFAULT_WEIGHTS.copy()
            return weights
    except Exception:
        pass
    return DEFAULT_WEIGHTS.copy()


def _score_backtest_validation(strategy: str) -> tuple[int, str]:
    """
    Faktor 5: Backtest Validation Bonus/Malus.
    Liest backtest_results.json und gibt +10 bis -5 Punkte.

    Scoring:
      PnL positiv UND WR >= 55%: +10
      PnL positiv ODER WR >= 50%: +5
      PnL negativ UND WR < 45%: -5
      Keine Daten: 0
    """
    try:
        bt_file = DATA_DIR / 'backtest_results.json'
        if not bt_file.exists():
            return (0, 'backtest=n/a (keine Datei)')

        # P1.6 — Cache TTL: Backtest > 14 Tage alt = veraltet
        import os as _os
        from datetime import datetime as _dt, timezone as _tz
        try:
            _age_days = (_dt.now().timestamp() - _os.path.getmtime(bt_file)) / 86400.0
        except Exception:
            _age_days = 0
        _stale = _age_days > 14

        # P1.6 — Backtest-Validation: live-WR vs backtest-WR vergleichen
        _val_file = DATA_DIR / 'backtest_validation_status.json'
        _val_penalty = 0  # Bonus halbieren wenn live deutlich schlechter
        if _val_file.exists():
            try:
                _val = json.loads(_val_file.read_text(encoding='utf-8'))
                _strat_val = _val.get(strategy, {})
                if _strat_val.get('downgrade'):
                    _val_penalty = -5

            except Exception:
                pass

        bt_data = json.loads(bt_file.read_text(encoding='utf-8'))
        bt_entry = bt_data.get(strategy, {})
        if isinstance(bt_entry, dict):
            bt_orig = bt_entry.get('original', bt_entry)
        else:
            return (0, 'backtest=n/a (kein Eintrag)')

        bt_trades = bt_orig.get('trades', 0)
        bt_pnl = bt_orig.get('pnl', 0)
        bt_wr = bt_orig.get('wr', bt_orig.get('win_rate', 0.5))

        if bt_trades < 5:
            return (0, f'backtest=n/a ({bt_trades} Trades < 5)')

        # Score-Bonus berechnen
        _bonus = 0
        _label = 'backtest_neutral'
        if bt_pnl > 0 and bt_wr >= 0.55:
            _bonus = 10; _label = 'backtest_strong'
        elif bt_pnl > 0 or bt_wr >= 0.50:
            _bonus = 5; _label = 'backtest_ok'
        elif bt_pnl < 0 and bt_wr < 0.45:
            _bonus = -5; _label = 'backtest_weak'

        # Stale → Bonus halbieren (Vorsicht), Penalty bleibt voll
        if _stale and _bonus > 0:
            _bonus = _bonus // 2
            _label += '_stale'
        # Validation-Penalty draufrechnen
        _bonus += _val_penalty
        return (_bonus, f'{_label}: PnL={bt_pnl:+.0f}, WR={bt_wr:.0%}, age={_age_days:.0f}d → {_bonus:+d}')
    except Exception as e:
        return (0, f'backtest=error ({e})')


# ─── Main Conviction Calculator ───────────────────────────────────────────────

def calculate_conviction(
    ticker: str,
    strategy: str,
    entry_price: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    atr: float | None = None,
    ema20: float | None = None,
    ema50: float | None = None,
    rsi: float | None = None,
    vol_ratio: float | None = None,
) -> dict:
    """
    Calculates conviction score (0-100) for a trade setup.

    Returns dict with:
      score, recommendation, factors, entry_allowed, block_reason,
      position_sizing (STRONG/MODERATE/WEAK), vix, regime
    """
    # ── Factor 1: Thesis Strength ─────────────────────────────────────────
    thesis_score, thesis_reason = _score_thesis_strength(strategy, ticker)

    # Hard block: INVALIDATED thesis
    if thesis_reason.startswith('BLOCK'):
        return {
            'score': 0,
            'recommendation': 'BLOCKED',
            'block_reason': thesis_reason,
            'entry_allowed': False,
            'factors': {
                'thesis_strength': 0,
                'technical_alignment': 0,
                'risk_reward_quality': 0,
                'market_context': 0,
            },
            'position_sizing': 'SKIP',
            'vix': None,
            'regime': None,
        }

    # ── Factor 2: Technical Alignment ────────────────────────────────────
    # If not provided, try to fetch from DB
    if ema20 is None or rsi is None or vol_ratio is None:
        tech_data = _fetch_technical_data(ticker, entry_price)
        ema20     = ema20 or tech_data.get('ema20')
        ema50     = ema50 or tech_data.get('ema50')
        rsi       = rsi or tech_data.get('rsi')
        vol_ratio = vol_ratio or tech_data.get('vol_ratio')

    tech_score, tech_reason = _score_technical_alignment(
        entry_price, ema20, ema50, rsi, vol_ratio
    )

    # ── Factor 3: Risk/Reward Quality ────────────────────────────────────
    rr_score, rr_reason = _score_risk_reward(entry_price, stop, target, atr)

    # Hard block: CRV too low
    if rr_reason.startswith('BLOCK'):
        return {
            'score': 0,
            'recommendation': 'BLOCKED',
            'block_reason': rr_reason,
            'entry_allowed': False,
            'factors': {
                'thesis_strength': thesis_score,
                'technical_alignment': tech_score,
                'risk_reward_quality': 0,
                'market_context': 0,
            },
            'position_sizing': 'SKIP',
            'vix': None,
            'regime': None,
        }

    # ── Factor 4: Market Context ──────────────────────────────────────────
    mkt_score, mkt_reason = _score_market_context(strategy)

    # Hard block: CRASH regime
    if mkt_score == -999:
        return {
            'score': 0,
            'recommendation': 'BLOCKED',
            'block_reason': mkt_reason,
            'entry_allowed': False,
            'factors': {
                'thesis_strength':    thesis_score,
                'technical_alignment': tech_score,
                'risk_reward_quality': rr_score,
                'market_context':     0,
            },
            'factor_reasons': {
                'thesis_strength':    thesis_reason,
                'technical_alignment': tech_reason,
                'risk_reward_quality': rr_reason,
                'market_context':     mkt_reason,
            },
            'position_sizing': 'SKIP',
            'vix': None,
            'regime': None,
            'vix_block': False,
            'vix_block_reason': None,
        }

    # ── Factor 5: Priced-In Check ─────────────────────────────────────────
    priced_in_mod, priced_in_reason = _score_priced_in(ticker, entry_price)

    # ── Hard Block: Downtrend / Falling Knife ────────────────────────────
    # Verhindert Käufe in fallende Aktien ("Catching a Falling Knife").
    # Regel: Kein Long-Eintrag wenn Preis UNTER EMA50 UND 3-Monats-Trend negativ.
    if entry_price and ema50 and entry_price < ema50:
        try:
            conn = get_db()
            rows_3m = conn.execute(
                "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 63",
                (ticker,)
            ).fetchall()
            conn.close()
            closes_3m = [r['close'] for r in rows_3m if r['close'] is not None]
            if len(closes_3m) >= 20:
                trend_3m = (closes_3m[0] - closes_3m[-1]) / closes_3m[-1]
                if trend_3m < -0.10:  # >10% gefallen in 3 Monaten → Downtrend
                    block_msg = (
                        f'BLOCK: Downtrend — Preis {entry_price:.2f} unter EMA50 {ema50:.2f} '
                        f'UND 3M-Trend {trend_3m*100:.1f}% (Falling Knife)'
                    )
                    return {
                        'score': 0,
                        'recommendation': 'BLOCKED',
                        'block_reason': block_msg,
                        'entry_allowed': False,
                        'factors': {
                            'thesis_strength':    thesis_score,
                            'technical_alignment': tech_score,
                            'risk_reward_quality': rr_score,
                            'market_context':     mkt_score,
                            'priced_in_modifier': priced_in_mod,
                        },
                        'factor_reasons': {
                            'thesis_strength':    thesis_reason,
                            'technical_alignment': tech_reason,
                            'risk_reward_quality': rr_reason,
                            'market_context':     mkt_reason,
                            'priced_in_modifier': priced_in_reason,
                            'downtrend_block':    block_msg,
                        },
                        'position_sizing': 'SKIP',
                        'vix': None,
                        'regime': None,
                        'vix_block': False,
                        'vix_block_reason': None,
                    }
        except Exception:
            pass  # Kein Datenblock wenn Daten fehlen — lieber zu wenig als zu viel sperren

    # Hard block: thesis already fully priced in (within 5% of 52W high)
    if priced_in_mod <= -20:
        return {
            'score': 0,
            'recommendation': 'BLOCKED',
            'block_reason': f'Fully priced in — {priced_in_reason}',
            'entry_allowed': False,
            'factors': {
                'thesis_strength':    thesis_score,
                'technical_alignment': tech_score,
                'risk_reward_quality': rr_score,
                'market_context':     mkt_score,
                'priced_in_modifier': priced_in_mod,
            },
            'factor_reasons': {
                'thesis_strength':    thesis_reason,
                'technical_alignment': tech_reason,
                'risk_reward_quality': rr_reason,
                'market_context':     mkt_reason,
                'priced_in_modifier': priced_in_reason,
            },
            'position_sizing': 'SKIP',
            'vix': None,
            'regime': None,
            'vix_block': False,
            'vix_block_reason': None,
        }

    # ── Adaptive Gewichte anwenden ────────────────────────────────────────
    weights = _load_adaptive_weights()
    # Skaliere Faktor-Scores proportional zu den adaptiven Gewichten
    # (Original: thesis=35, tech=30, rr=20, mkt=15)
    w_thesis = weights.get('thesis', 35)
    w_tech = weights.get('technical', 30)
    w_rr = weights.get('risk_reward', 20)
    w_mkt = weights.get('market_context', 15)

    thesis_weighted = thesis_score * (w_thesis / 35) if w_thesis != 35 else thesis_score
    tech_weighted = tech_score * (w_tech / 30) if w_tech != 30 else tech_score
    rr_weighted = rr_score * (w_rr / 20) if w_rr != 20 else rr_score
    mkt_weighted = mkt_score * (w_mkt / 15) if w_mkt != 15 else mkt_score

    # ── Factor 5: Backtest Validation ────────────────────────────────────
    bt_score, bt_reason = _score_backtest_validation(strategy)

    # ── Total Score (4 weighted factors + priced-in + backtest) ───────────
    total = thesis_weighted + tech_weighted + rr_weighted + mkt_weighted + priced_in_mod + bt_score

    # ── Factor 6: Alpha Decay + DNA Modifier ─────────────────────────────
    decay_dna_mod, decay_dna_reason = _apply_decay_and_dna(strategy)
    total = max(0, min(100, total + decay_dna_mod))

    # ── K1 — Victor-Feedback Trust-Malus ─────────────────────────────────
    trust_mod = 0.0
    trust_reason = ''
    try:
        import sys as _sys
        _sys.path.insert(0, str(DATA_DIR.parent / 'scripts'))
        from victor_feedback import get_trust_malus as _get_trust_malus
        trust_mod, trust_reason = _get_trust_malus(strategy=strategy, ticker=ticker)
        if trust_mod != 0:
            total = max(0, min(100, total + trust_mod))
    except Exception as _e:
        pass

    # ── P25-2 — Sektor-Wetter Modifier ───────────────────────────────────
    sector_mod = 0
    sector_reason = ''
    try:
        from sector_strength import get_sector_modifier as _get_sector_mod
        sector_mod, sector_reason = _get_sector_mod(ticker)
        if sector_mod != 0:
            total = max(0, min(100, total + sector_mod))
    except Exception:
        pass

    # ── P25-9 — Multi-Timeframe Check (Daily + Weekly beide bullish) ─────
    mtf_mod = 0
    mtf_reason = ''
    try:
        import sqlite3 as _sqlite
        _conn = _sqlite.connect(str(DATA_DIR / 'trading.db'))
        rows = _conn.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 60",
            (ticker.upper(),),
        ).fetchall()
        _conn.close()
        if len(rows) >= 50:
            closes = [float(r[0]) for r in rows]
            # Daily-Trend: Preis vs MA20
            ma20 = sum(closes[:20]) / 20
            daily_bull = closes[0] > ma20
            # Weekly-Trend: 5d-Preis vs 25d-Preis (Proxy für W1 vs W5)
            avg_recent = sum(closes[:5]) / 5
            avg_prior = sum(closes[20:45]) / 25 if len(closes) >= 45 else sum(closes[20:]) / max(1, len(closes) - 20)
            weekly_bull = avg_recent > avg_prior
            if daily_bull and weekly_bull:
                mtf_mod = +3
                mtf_reason = 'D+W beide bullish'
            elif daily_bull and not weekly_bull:
                mtf_mod = -2
                mtf_reason = 'D bull, W bear (Counter-Trend)'
            elif not daily_bull and weekly_bull:
                mtf_mod = -1
                mtf_reason = 'D bear in W-Uptrend (Pullback)'
            else:
                mtf_mod = -3
                mtf_reason = 'D+W beide bearish'
            total = max(0, min(100, total + mtf_mod))
    except Exception:
        pass

    # ── Optional: Crowd Reaction Modifier (-15 to +15) ────────────────────
    crowd_mod = 0
    if total >= 40:
        try:
            from crowd_reaction import get_crowd_modifier
            strategy_cfg = {}
            try:
                sp = DATA_DIR / 'strategies.json'
                if sp.exists():
                    strategy_cfg = json.loads(sp.read_text(encoding='utf-8')).get(strategy, {})
            except Exception:
                pass
            strategy_name   = strategy_cfg.get('name', strategy)
            entry_trigger   = strategy_cfg.get('entry_trigger', '')
            scenario        = f"{strategy_name}: {entry_trigger}"
            crowd_mod       = get_crowd_modifier(strategy, scenario)
            total           = max(0, min(100, total + crowd_mod))
        except Exception:
            pass  # crowd reaction is optional

    # ── Factor 6b: Options-Flow Confluence Booster ───────────────────────
    # Lernung aus MD-Files: Unusual-Call-Volume ist Smart-Money-Signal.
    # Wenn für den Ticker aktive Call-Alerts in options_flow_state.json
    # existieren, +5 (weak) bis +10 (strong) auf den Gesamtscore.
    # Caps bei 0..100, damit nie Über-Overflow.
    of_mod = 0
    of_reason = None
    try:
        of_file = DATA_DIR / 'options_flow_state.json'
        if of_file.exists():
            of_data = json.loads(of_file.read_text(encoding='utf-8'))
            alerted = of_data.get('alerted', {}) or {}
            tk_up = ticker.upper()
            call_hits = 0
            put_hits = 0
            max_vol = 0
            for key in alerted.keys():
                parts = key.split('_')
                if len(parts) < 2:
                    continue
                if parts[0].upper() != tk_up:
                    continue
                vol = alerted.get(key) or 0
                if parts[1].upper() == 'CALL':
                    call_hits += 1
                    if vol > max_vol:
                        max_vol = vol
                elif parts[1].upper() == 'PUT':
                    put_hits += 1
            net_bull = call_hits - put_hits
            if net_bull >= 3 or (net_bull >= 1 and max_vol >= 5000):
                of_mod = 10  # Strong confluence
            elif net_bull >= 1:
                of_mod = 5   # Weak confluence
            elif put_hits >= 3 and call_hits == 0:
                of_mod = -5  # Bearish flow gegen den Bullish-Trade
            if of_mod != 0:
                total = max(0, min(100, total + of_mod))
                of_reason = f'flow calls={call_hits} puts={put_hits} max_vol={max_vol} → {of_mod:+d}'
    except Exception:
        pass  # Options-flow ist optional — bei Fehler keinen Bonus

    # ── Factor 7: Insider Signal (Phase 10, SEC EDGAR Form 4) ─────────────
    # ±10 modifier basierend auf Insider-Käufen/-Verkäufen der letzten 30 Tage
    insider_mod = 0
    insider_reason = None
    try:
        from intelligence.sec_edgar import insider_signal  # type: ignore
        sig = insider_signal(ticker, days=30, use_cache=True)
        raw = int(sig.get('score', 0))  # -100..+100
        insider_mod = max(-10, min(10, round(raw / 10)))
        if insider_mod != 0:
            total = max(0, min(100, total + insider_mod))
            insider_reason = f"{sig.get('bias')} {insider_mod:+d} ({sig.get('reason', '')})"
    except Exception:
        pass  # insider signal is optional (non-US ticker, fetch fail, etc.)

    # ── Sizing recommendation ─────────────────────────────────────────────
    if total >= 60:
        sizing = 'STRONG'        # 2% risk
        recommendation = 'STRONG_BUY'
    elif total >= ENTRY_THRESHOLD:
        sizing = 'MODERATE'      # 1% risk
        recommendation = 'BUY'
    else:
        sizing = 'SKIP'
        recommendation = 'AVOID'

    # Determine VIX and regime for metadata
    vix = None
    regime = None
    try:
        conn = get_db()
        vix_row = conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if vix_row:
            vix = vix_row['value']
        reg_row = conn.execute(
            "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if reg_row:
            regime = reg_row['regime']
        conn.close()
    except Exception:
        pass

    return {
        'score': round(total, 1),
        'recommendation': recommendation,
        'entry_allowed': total >= ENTRY_THRESHOLD,
        'block_reason': None,
        'factors': {
            'thesis_strength':     thesis_score,
            'technical_alignment': tech_score,
            'risk_reward_quality': rr_score,
            'market_context':      mkt_score,
            'priced_in_modifier':  priced_in_mod,
            'backtest_validation': bt_score,
            'decay_dna_modifier':  decay_dna_mod,
            **({'crowd_reaction': crowd_mod} if crowd_mod != 0 else {}),
            **({'insider_signal': insider_mod} if insider_mod != 0 else {}),
            **({'options_flow': of_mod} if of_mod != 0 else {}),
        },
        'factor_reasons': {
            'thesis_strength':     thesis_reason,
            'technical_alignment': tech_reason,
            'risk_reward_quality': rr_reason,
            'market_context':      mkt_reason,
            'priced_in_modifier':  priced_in_reason,
            'backtest_validation': bt_reason,
            'decay_dna':           decay_dna_reason,
            **({'crowd_reaction': f'modifier {crowd_mod:+d}'} if crowd_mod != 0 else {}),
            **({'insider_signal': insider_reason} if insider_reason else {}),
            **({'options_flow': of_reason} if of_reason else {}),
        },
        'position_sizing': sizing,
        'vix': vix,
        'regime': regime,
        # Legacy compat fields
        'vix_block': False,
        'vix_block_reason': None,
    }


def check_entry_allowed(strategy: str = None, conn=None, style: str = 'swing') -> tuple[bool, str]:
    """
    Phase 2: VIX is now ONLY a conviction score modifier — no hard VIX block.
    Entry is allowed unless thesis is INVALIDATED.

    Kept for backward compatibility with paper_trade_engine.py
    Returns: (allowed: bool, reason: str)
    """
    # The only hard block is now thesis INVALIDATED
    if strategy:
        ts, reason = _score_thesis_strength(strategy)
        if reason.startswith('BLOCK'):
            return False, f'Thesis INVALIDATED: {reason}'

    # Get VIX for info only (no block)
    vix = None
    regime = 'UNKNOWN'
    try:
        _conn = conn or get_db()
        vix_row = _conn.execute(
            "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if vix_row:
            vix = vix_row['value']
        reg_row = _conn.execute(
            "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if reg_row:
            regime = reg_row['regime']
        if conn is None:
            _conn.close()
    except Exception:
        pass

    vix_str = f'{vix:.1f}' if vix else 'n/a'
    return True, f'Entry allowed — Regime {regime} (VIX={vix_str}). VIX is conviction modifier only.'


def score_all_open_trades() -> list[dict]:
    """Scores all open trades for monitoring."""
    try:
        conn = get_db()
        trades = conn.execute(
            "SELECT id, ticker, strategy, entry_price, stop_price, target_price "
            "FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        conn.close()
    except Exception:
        return []

    results = []
    for t in trades:
        result = calculate_conviction(
            ticker=t['ticker'],
            strategy=t['strategy'] or 'DEFAULT',
            entry_price=t['entry_price'],
            stop=t['stop_price'],
            target=t['target_price'],
        )
        result['trade_id'] = t['id']
        result['ticker'] = t['ticker']
        results.append(result)

    return sorted(results, key=lambda x: x['score'], reverse=True)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        results = score_all_open_trades()
        print(f'=== Conviction Scores v3 — {len(results)} open trades ===')
        for r in results:
            icon = '[STRONG]' if r['score'] >= 60 else ('[MOD]' if r['score'] >= 45 else '[WEAK]')
            print(f"  {icon} {r['ticker']:12} Score: {r['score']:5.1f} -> {r['recommendation']}")
            for k, v in r['factors'].items():
                print(f"      {k:25} {v:3}/{'35' if k=='thesis_strength' else '30' if k=='technical_alignment' else '20' if k=='risk_reward_quality' else '15'}")
            print()

    elif len(sys.argv) >= 4:
        ticker   = sys.argv[1]
        strategy = sys.argv[2]
        entry    = float(sys.argv[3]) if len(sys.argv) > 3 else None
        stop_p   = float(sys.argv[4]) if len(sys.argv) > 4 else None
        target_p = float(sys.argv[5]) if len(sys.argv) > 5 else None

        result = calculate_conviction(ticker, strategy, entry, stop_p, target_p)
        print(f'Conviction v3: {result["score"]}/100 -> {result["recommendation"]} ({result["position_sizing"]})')
        for k, v in result['factors'].items():
            reason = result['factor_reasons'].get(k, '')
            print(f'  {k:25} {v:3}  [{reason}]')
        if not result['entry_allowed']:
            print(f'  BLOCKED: {result["block_reason"]}')

    else:
        print('Usage: conviction_scorer.py TICKER STRATEGY ENTRY STOP TARGET')
        print('       conviction_scorer.py all')
