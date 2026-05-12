#!/usr/bin/env python3
"""
position_sizer.py — Phase 45aq Layer A2 (Victor 2026-05-11).

Berechnet Position-Größe basierend auf:
  - Conviction (Albert's Score, 0-1)
  - Volatilität (ATR — höher = kleinere Position)
  - Stop-Distance (€-Risiko pro Trade = 1% des Portfolios)
  - Kelly-Cap (max 5% des Portfolios in einer Position)
  - Korrelations-Discount (wenn schon Position in gleichem Cluster: -50%)

Formel:
  base_size = (portfolio_total * risk_per_trade_pct) / stop_distance_pct
  size = base_size * conviction_mult * vol_adj * corr_discount
  size = min(size, kelly_cap, max_absolute_eur)
"""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
FUND_FILE = WS / 'data' / 'paper_fund.json'

# Defaults (Phase 1 aggressivierung von Mai 2026)
# Phase 45at: Kohort-spezifisch konfigurierbar via aggression_profile
RISK_PER_TRADE_PCT = 0.015     # Phase 1: 1% → 1.5%
MAX_POSITION_PCT   = 0.07      # Phase 1: 5% → 7%
MAX_ABSOLUTE_EUR   = 3000.0    # Phase 1: 2500 → 3000
MIN_ABSOLUTE_EUR   = 200.0
DEFAULT_ATR_PCT    = 0.03


def _load_cohort_profile(cohort_id: str | None) -> dict:
    """Lade Aggression-Profil aus paper_cohorts. Default wenn keins."""
    if not cohort_id or not DB.exists():
        return {'risk_per_trade': RISK_PER_TRADE_PCT,
                'kelly_cap': MAX_POSITION_PCT,
                'max_absolute_eur': MAX_ABSOLUTE_EUR}
    try:
        c = sqlite3.connect(str(DB))
        r = c.execute("SELECT aggression_profile, current_cash_eur "
                      "FROM paper_cohorts WHERE cohort_id=?", (cohort_id,)).fetchone()
        c.close()
        if not r: return {}
        prof = json.loads(r[0]) if r[0] else {}
        return {
            'risk_per_trade': prof.get('risk_per_trade', RISK_PER_TRADE_PCT),
            'kelly_cap': prof.get('kelly_cap', MAX_POSITION_PCT),
            'max_absolute_eur': prof.get('max_absolute_eur', MAX_ABSOLUTE_EUR),
            'cohort_cash_eur': r[1],
        }
    except Exception:
        return {}


def calculate_position_size(ticker: str, entry_eur: float, stop_eur: float,
                             conviction: float = 0.6,
                             portfolio_total_eur: float | None = None,
                             cohort_id: str | None = None) -> dict:
    """
    Returns dict with: shares, position_eur, max_loss_eur, reasoning.
    """
    if entry_eur <= 0 or stop_eur <= 0 or entry_eur <= stop_eur:
        return {'error': 'invalid_prices', 'shares': 0}

    # Phase 45at: Kohort-spezifisches Profil + Cash
    profile = _load_cohort_profile(cohort_id)
    risk_pct = profile.get('risk_per_trade', RISK_PER_TRADE_PCT)
    kelly_pct = profile.get('kelly_cap', MAX_POSITION_PCT)
    max_abs = profile.get('max_absolute_eur', MAX_ABSOLUTE_EUR)

    # Portfolio-Total: bei Kohort-Mode = Kohort-Total, sonst global
    if cohort_id and 'cohort_cash_eur' in profile:
        # Cohort-Total = Cohort-Cash + Open-Position-Value dieser Kohorte
        portfolio_total_eur = profile['cohort_cash_eur']
        try:
            c = sqlite3.connect(str(DB))
            opens = c.execute(
                "SELECT entry_price, shares FROM paper_portfolio "
                "WHERE cohort_id=? AND status='OPEN'", (cohort_id,)
            ).fetchall()
            c.close()
            portfolio_total_eur += sum((r[0] or 0) * (r[1] or 0) for r in opens)
        except Exception: pass
    elif portfolio_total_eur is None:
        portfolio_total_eur = _portfolio_total()

    if portfolio_total_eur <= 0:
        return {'error': 'no_portfolio_data', 'shares': 0}

    # Stop-Distance
    stop_distance_pct = (entry_eur - stop_eur) / entry_eur
    if stop_distance_pct <= 0:
        return {'error': 'invalid_stop_above_entry', 'shares': 0}

    # ATR-Adjustment (Volatilität)
    atr_pct = _get_atr_pct(ticker) or DEFAULT_ATR_PCT
    # höhere Volatilität → kleinere Position
    # vol_adj zwischen 0.5 (ATR=6%) und 1.2 (ATR=1.5%)
    vol_adj = max(0.5, min(1.2, 0.03 / atr_pct))

    # Conviction-Multiplier: 0.4-1.5x
    conv_mult = max(0.4, min(1.5, conviction))

    # Korrelations-Discount: schon Position im selben Cluster?
    corr_discount = 1.0
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from portfolio_concentration_guard import _ticker_cluster, _open_positions_with_value
        new_cluster = _ticker_cluster(ticker)
        if new_cluster:
            for p in _open_positions_with_value():
                if p.get('cluster') == new_cluster:
                    corr_discount = 0.5  # Halbiere wenn schon im Cluster
                    break
    except Exception: pass

    # Base size aus Risk-Budget (Phase 45at: kohort-spezifischer Wert)
    risk_budget_eur = portfolio_total_eur * risk_pct
    # max_loss_eur = shares * (entry - stop)
    # shares = risk_budget / (entry - stop)
    shares_from_risk = risk_budget_eur / (entry_eur - stop_eur)
    base_eur = shares_from_risk * entry_eur

    # Adjustierungen anwenden
    adj_eur = base_eur * vol_adj * conv_mult * corr_discount

    # Kelly-Cap (kohort-spezifisch)
    max_kelly_eur = portfolio_total_eur * kelly_pct
    final_eur = min(adj_eur, max_kelly_eur, max_abs)

    # Min-Check
    if final_eur < MIN_ABSOLUTE_EUR:
        return {
            'error': f'below_min_size ({final_eur:.0f} < {MIN_ABSOLUTE_EUR})',
            'shares': 0, 'position_eur': round(final_eur, 2),
        }

    shares = max(1, int(final_eur / entry_eur))
    actual_position_eur = shares * entry_eur
    max_loss_eur = shares * (entry_eur - stop_eur)

    return {
        'shares': shares,
        'position_eur': round(actual_position_eur, 2),
        'max_loss_eur': round(max_loss_eur, 2),
        'max_loss_pct_of_portfolio': round(max_loss_eur / portfolio_total_eur * 100, 2),
        'reasoning': {
            'risk_budget_eur': round(risk_budget_eur, 2),
            'stop_distance_pct': round(stop_distance_pct * 100, 1),
            'atr_pct': round(atr_pct * 100, 1),
            'vol_adj': round(vol_adj, 2),
            'conviction': round(conviction, 2),
            'conv_mult': round(conv_mult, 2),
            'corr_discount': round(corr_discount, 2),
            'base_eur': round(base_eur, 2),
            'adj_eur': round(adj_eur, 2),
            'kelly_cap_eur': round(max_kelly_eur, 2),
            'portfolio_total_eur': round(portfolio_total_eur, 2),
        },
    }


def _portfolio_total() -> float:
    cash = 0.0
    if FUND_FILE.exists():
        try:
            cash = float(json.loads(FUND_FILE.read_text(encoding='utf-8')).get('cash', 0))
        except Exception: pass
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from portfolio_concentration_guard import _portfolio_total_eur
        return _portfolio_total_eur()
    except Exception: pass
    return cash


def _get_atr_pct(ticker: str) -> float | None:
    """Hole ATR% aus atr_cache.json oder rechne aus prices."""
    cache_file = WS / 'data' / 'atr_cache.json'
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding='utf-8'))
            v = cache.get(ticker.upper(), {})
            if isinstance(v, dict) and 'atr_pct' in v:
                return float(v['atr_pct'])
            if isinstance(v, (int, float)):
                return float(v)
        except Exception: pass
    # Fallback: rechne aus prices
    if not DB.exists(): return None
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT high, low, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 14",
            (ticker,)
        ).fetchall()
        c.close()
        if len(rows) < 5: return None
        ranges = [(r[0] - r[1]) / r[2] for r in rows if r[2] and r[2] > 0]
        if not ranges: return None
        return sum(ranges) / len(ranges)
    except Exception:
        return None


def main() -> int:
    import sys
    if len(sys.argv) < 3:
        print('Usage: position_sizer.py TICKER ENTRY STOP [CONVICTION]')
        return 2
    ticker = sys.argv[1]
    entry = float(sys.argv[2])
    stop = float(sys.argv[3])
    conv = float(sys.argv[4]) if len(sys.argv) > 4 else 0.6
    r = calculate_position_size(ticker, entry, stop, conv)
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
