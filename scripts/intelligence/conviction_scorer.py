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

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB_PATH  = WS / 'data' / 'trading.db'
DATA_DIR = WS / 'data'

ENTRY_THRESHOLD = 45  # Minimum conviction score to enter a trade


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
    return conn


# ─── Decay + DNA Modifier ────────────────────────────────────────────────────

def _apply_decay_and_dna(strategy: str, score: int) -> int:
    """Apply alpha_decay status penalty and DNA VIX-range bonus/penalty."""
    try:
        # Alpha Decay check
        _decay_path = WS / 'data' / 'alpha_decay.json'
        if _decay_path.exists():
            _decay_data = json.loads(_decay_path.read_text(encoding='utf-8'))
            _strat_decay = _decay_data.get(strategy, {})
            _status = _strat_decay.get('status', '')
            if _status in ('DECAY', 'SUSPEND_CANDIDATE'):
                score -= 10
            elif _status == 'WARNING':
                score -= 5

        # DNA VIX-range check
        _dna_path = WS / 'data' / 'dna.json'
        if _dna_path.exists():
            _dna_data = json.loads(_dna_path.read_text(encoding='utf-8'))
            _strat_dna = _dna_data.get(strategy, {})
            _vix_range = _strat_dna.get('optimal_vix_range')
            if _vix_range:
                # Read current VIX from ceo_directive.json
                _ceo_path = WS / 'data' / 'ceo_directive.json'
                if _ceo_path.exists():
                    _ceo = json.loads(_ceo_path.read_text(encoding='utf-8'))
                    _vix = _ceo.get('vix')
                    if _vix is not None:
                        _vix = float(_vix)
                        _lo = float(_vix_range[0]) if isinstance(_vix_range, (list, tuple)) and len(_vix_range) >= 2 else None
                        _hi = float(_vix_range[1]) if isinstance(_vix_range, (list, tuple)) and len(_vix_range) >= 2 else None
                        if _lo is not None and _hi is not None:
                            if _lo <= _vix <= _hi:
                                score += 5
                            else:
                                score -= 5

        return max(0, score)
    except Exception:
        return score


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
        return (_apply_decay_and_dna(strategy, 0), 'BLOCK: thesis INVALIDATED — kill trigger fired')

    if effective_status == 'DEGRADED':
        # Check for entry_trigger confirmation bonus (capped at 15)
        entry_bonus = _check_entry_trigger_bonus(strategy, strategy_cfg)
        ng_bonus = _news_gate_bonus(strategy)
        score = min(15, 10 + entry_bonus + ng_bonus)
        score = _apply_decay_and_dna(strategy, score)
        return (score, f'DEGRADED thesis — capped at {score}/15 (ng={ng_bonus})')

    if effective_status in ('ACTIVE', 'WATCHING', 'EVALUATING'):
        base = 20
        entry_bonus = _check_entry_trigger_bonus(strategy, strategy_cfg)
        ng_bonus = _news_gate_bonus(strategy)
        score = min(35, base + entry_bonus + ng_bonus)
        score = _apply_decay_and_dna(strategy, score)
        return (score, f'ACTIVE thesis — {score}/35 (bonus={entry_bonus}, news_gate={ng_bonus})')

    # PAUSED or unknown
    _paused_score = _apply_decay_and_dna(strategy, 10)
    return (_paused_score, f'thesis status {effective_status} — partial credit {_paused_score}/35')


def _news_gate_bonus(strategy: str) -> int:
    """
    Liest news_gate.json und gibt +5 Bonus wenn diese Strategie
    in den theses_hit der letzten 24h vorkommt.
    Matching: 'PS1' trifft 'PS1_Oil', 'S1' trifft 'S1_Iran' etc.
    Returns 0 or 5.
    """
    try:
        ng_path = DATA_DIR / 'news_gate.json'
        if not ng_path.exists():
            return 0
        ng = json.loads(ng_path.read_bytes().decode('utf-8', errors='replace'))
        if not isinstance(ng, dict):
            return 0
        theses_hit = ng.get('theses_hit', [])
        for hit in theses_hit:
            # Match: 'PS1' == 'PS1_Oil' (prefix) oder exakter Match
            if hit == strategy or hit.startswith(strategy + '_') or hit.startswith(strategy):
                return 5
    except Exception:
        pass
    return 0


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
                data = json.loads(regime_file.read_text(encoding="utf-8"))
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

    score = min(15, vix_score + regime_bonus)
    bonus_str = f' +{regime_bonus}regime_fit' if regime_bonus else ''
    return (score, f'{vix_str}{bonus_str} → {score}/15')


# ─── Position Sizing ──────────────────────────────────────────────────────────

def get_position_size(
    score: float,
    portfolio_value: float,
    entry_price: float,
    stop_price: float,
) -> int:
    """
    Risk-based position sizing:
      score >= 60: 2% risk (STRONG)
      score >= 45: 1% risk (MODERATE)
      else:        0 shares (skip)

    Capped at 5% of portfolio per position.
    Returns number of shares (integer).
    """
    if score < ENTRY_THRESHOLD:
        return 0

    risk_pct = 0.02 if score >= 60 else 0.01
    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0:
        return 0

    risk_amount = portfolio_value * risk_pct
    shares = int(risk_amount / risk_per_share)

    # Cap at 5% of portfolio per position
    max_shares = int(portfolio_value * 0.05 / entry_price)
    return min(shares, max_shares)


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

    # ── CEO-Modus-Check: Score-Anpassung basierend auf CEO-Direktive ────
    try:
        _directive_path = DATA_DIR / 'ceo_directive.json'
        if _directive_path.exists():
            _directive = json.loads(_directive_path.read_text(encoding='utf-8'))
            _ceo_mode = _directive.get('mode', 'NORMAL')
            if _ceo_mode == 'SHUTDOWN':
                return {
                    'score': 0, 'recommendation': 'BLOCKED',
                    'block_reason': 'CEO-Modus: SHUTDOWN — keine neuen Trades',
                    'entry_allowed': False,
                    'factors': {'thesis_strength': 0, 'technical_alignment': 0,
                                'risk_reward_quality': 0, 'market_context': 0},
                    'position_sizing': 'SKIP', 'vix': None, 'regime': None,
                }
            elif _ceo_mode == 'DEFENSIVE':
                thesis_score = max(0, thesis_score - 5)  # Conviction reduzieren
    except Exception:
        pass

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

    # ── Total Score (4 factors) ───────────────────────────────────────────
    total = thesis_score + tech_score + rr_score + mkt_score

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
            **({'crowd_reaction': crowd_mod} if crowd_mod != 0 else {}),
        },
        'factor_reasons': {
            'thesis_strength':     thesis_reason,
            'technical_alignment': tech_reason,
            'risk_reward_quality': rr_reason,
            'market_context':      mkt_reason,
            **({'crowd_reaction': f'modifier {crowd_mod:+d}'} if crowd_mod != 0 else {}),
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
