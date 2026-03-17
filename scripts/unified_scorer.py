#!/usr/bin/env python3
"""
unified_scorer.py — Unified Signal Score Engine
DAS GEHIRN: Kombiniert ALLE Analyse-Quellen zu einem einzigen Score pro Aktie.

Quellen: stock_screener, backtester, regime_detector, correlation_tracker,
         sentiment_scorer, learning_engine
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from price_db import get_closes, init_tables, STRATEGY_MAP, ALL_TICKERS

DATA_DIR = Path("/data/.openclaw/workspace/data")
BACKTEST_PATH = DATA_DIR / "backtest_results.json"

# Gewichtung der Faktoren
WEIGHTS = {
    'screener': 0.25,
    'backtest': 0.25,
    'regime': 0.15,
    'correlation': 0.15,
    'sentiment': 0.10,
    'learning': 0.10,
}

# Indices/FX excluded from scoring
EXCLUDE = {"^GSPC", "^VIX", "^GDAXI", "CL=F", "GC=F", "EURUSD=X", "EURGBP=X", "EURNOK=X"}

# Ideal strategy-regime combos
IDEAL_COMBOS = {
    ('PS1', 'ELEVATED'), ('PS1', 'PANIC'),
    ('PS3', 'ELEVATED'), ('PS3', 'PANIC'),
    ('PS4', 'ELEVATED'), ('PS4', 'PANIC'),
}


def _load_backtest_results():
    """Load cached backtest results."""
    try:
        with open(BACKTEST_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_best_backtest_for_ticker(ticker, strategy, bt_data):
    """Find best backtest result for ticker in strategy. Returns (win_rate, total_pnl) or None."""
    detailed = bt_data.get('detailed_results', {})
    strat_data = detailed.get(strategy, {})
    results = strat_data.get('results', [])

    best_wr = 0
    best_pnl = 0
    found = False

    for r in results:
        if r.get('ticker') == ticker and r.get('trades', 0) > 0:
            found = True
            wr = r.get('win_rate', 0)
            pnl = r.get('total_pnl', 0)
            if wr > best_wr or (wr == best_wr and pnl > best_pnl):
                best_wr = wr
                best_pnl = pnl

    if not found:
        return None
    return best_wr, best_pnl


def score_screener(ticker):
    """Get screener score (0-100). Uses stock_screener inline."""
    try:
        from stock_screener import screen_ticker, SCREENABLE
        from price_db import get_relative_strength

        all_rs = []
        for t in SCREENABLE:
            rs = get_relative_strength(t)
            all_rs.append(rs)

        result = screen_ticker(ticker, all_rs)
        if result is None:
            return 50, "Keine Daten"

        score = result['score']
        factors = result.get('factors', {})
        details_parts = []
        for fname, fdata in factors.items():
            details_parts.append(fdata.get('reason', ''))
        details = '; '.join(details_parts[:3])
        return score, details
    except Exception as e:
        return 50, f"Fehler: {e}"


def score_backtest(ticker, strategy):
    """Score based on backtest results (0-100)."""
    bt_data = _load_backtest_results()
    result = _get_best_backtest_for_ticker(ticker, strategy, bt_data)

    if result is None:
        return 15, "Keine Backtest-Daten"

    wr, pnl = result

    if wr > 60:
        base = 80 + min(20, (wr - 60) / 2)
    elif wr >= 50:
        base = 60 + (wr - 50) * 2
    elif wr >= 40:
        base = 30 + (wr - 40) * 3
    else:
        base = max(0, wr * 0.75)

    # Bonus for positive P&L
    if pnl > 0:
        base = min(100, base + 10)

    details = f"{strategy}: {pnl:+.1f}% P&L, {wr:.0f}% WR"
    return round(base), details


def score_regime(strategy):
    """Score based on regime compatibility (0-100)."""
    try:
        from regime_detector import get_current_regime, is_strategy_compatible
        current = get_current_regime()
        regime = current.get('regime', 'UNKNOWN')

        if regime == 'UNKNOWN':
            return 50, "Kein Regime-Daten"

        compatible, reason = is_strategy_compatible(strategy, regime)

        if (strategy, regime) in IDEAL_COMBOS:
            return 100, f"{regime} — {strategy} IDEAL"
        elif compatible:
            return 80, f"{regime} — {strategy} kompatibel"
        else:
            return 20, f"{regime} — {strategy} inkompatibel"
    except Exception as e:
        return 50, f"Regime-Fehler: {e}"


def score_correlation(ticker, portfolio_tickers):
    """Score based on correlation to existing portfolio (0-100)."""
    if not portfolio_tickers or ticker in portfolio_tickers:
        return 70, "Im Portfolio / kein Vergleich"

    try:
        from correlation_tracker import calc_correlation
        correlations = []
        for pt in portfolio_tickers:
            if pt == ticker:
                continue
            corr = calc_correlation(ticker, pt, days=30)
            if corr is not None:
                correlations.append(abs(corr))

        if not correlations:
            return 70, "Keine Korrelations-Daten"

        avg_corr = sum(correlations) / len(correlations)

        if avg_corr < 0.3:
            score = 90 + min(10, (0.3 - avg_corr) * 33)
        elif avg_corr < 0.5:
            score = 60 + (0.5 - avg_corr) * 100
        elif avg_corr < 0.7:
            score = 30 + (0.7 - avg_corr) * 100
        else:
            score = max(0, 20 - (avg_corr - 0.7) * 66)

        details = f"Avg corr {avg_corr:.2f}"
        if avg_corr < 0.3:
            details += " — gut diversifiziert"
        elif avg_corr > 0.7:
            details += " — HOCHKORRELIERT"
        return round(min(100, max(0, score))), details
    except Exception as e:
        return 50, f"Korrelations-Fehler: {e}"


def score_sentiment(ticker):
    """Score based on news sentiment (0-100)."""
    try:
        from sentiment_scorer import score_headlines
        result = score_headlines(ticker, max_articles=5)
        sent_score = result.get('score', 0)

        if sent_score > 5:
            base = 80 + min(20, (sent_score - 5) * 2)
        elif sent_score >= 1:
            base = 60 + (sent_score - 1) * 5
        elif sent_score == 0:
            base = 50
        elif sent_score >= -5:
            base = 20 + (sent_score + 5) * 5
        else:
            base = max(0, 20 + (sent_score + 5) * 4)

        headline = result.get('top_headline', 'N/A')
        if len(headline) > 50:
            headline = headline[:47] + '...'
        details = f"{sent_score:+d} News-Score"
        return round(min(100, max(0, base))), details
    except Exception as e:
        return 50, f"Sentiment-Fehler: {e}"


def score_learning(ticker, strategy):
    """Score based on learning engine error patterns (0-100)."""
    try:
        from learning_engine import check_error_patterns
        warnings = check_error_patterns(ticker, strategy, 0)

        error_count = sum(1 for w in warnings if w.startswith('⚠️') or w.startswith('🔴'))
        info_count = sum(1 for w in warnings if w.startswith('ℹ️'))
        ok = any('Keine bekannten' in w or w.startswith('✅') for w in warnings)

        if ok and error_count == 0:
            return 80, "Keine Fehler-Pattern"
        elif error_count >= 2:
            return 10, f"{error_count} Warnungen"
        elif error_count == 1:
            return 40, "1 Warnung"
        else:
            return 70, f"{info_count} Info(s)"
    except Exception as e:
        return 50, f"Learning-Fehler: {e}"


def unified_score(ticker, strategy, current_portfolio_tickers=None):
    """
    Calculate unified score for a ticker with a given strategy.
    Returns dict with unified_score, verdict, and component breakdown.
    """
    if current_portfolio_tickers is None:
        current_portfolio_tickers = []

    components = {}

    # 1. Screener
    s, d = score_screener(ticker)
    components['screener'] = {'score': s, 'weighted': round(s * WEIGHTS['screener'], 2), 'details': d}

    # 2. Backtest
    s, d = score_backtest(ticker, strategy)
    components['backtest'] = {'score': s, 'weighted': round(s * WEIGHTS['backtest'], 2), 'details': d}

    # 3. Regime
    s, d = score_regime(strategy)
    components['regime'] = {'score': s, 'weighted': round(s * WEIGHTS['regime'], 2), 'details': d}

    # 4. Correlation
    s, d = score_correlation(ticker, current_portfolio_tickers)
    components['correlation'] = {'score': s, 'weighted': round(s * WEIGHTS['correlation'], 2), 'details': d}

    # 5. Sentiment
    s, d = score_sentiment(ticker)
    components['sentiment'] = {'score': s, 'weighted': round(s * WEIGHTS['sentiment'], 2), 'details': d}

    # 6. Learning
    s, d = score_learning(ticker, strategy)
    components['learning'] = {'score': s, 'weighted': round(s * WEIGHTS['learning'], 2), 'details': d}

    # Total
    total = sum(c['weighted'] for c in components.values())
    total = round(min(100, max(0, total)))

    if total > 70:
        verdict = 'BUY'
    elif total >= 40:
        verdict = 'WATCH'
    else:
        verdict = 'AVOID'

    return {
        'ticker': ticker,
        'strategy': strategy,
        'unified_score': total,
        'verdict': verdict,
        'components': components,
        'timestamp': datetime.now().isoformat(),
    }


def score_candidate_list(tickers_with_strategies, current_portfolio=None):
    """Score a list of (ticker, strategy) tuples. Returns sorted list."""
    if current_portfolio is None:
        current_portfolio = []

    results = []
    for ticker, strategy in tickers_with_strategies:
        try:
            result = unified_score(ticker, strategy, current_portfolio)
            results.append(result)
        except Exception as e:
            print(f"  ⚠ {ticker}: {e}")

    results.sort(key=lambda x: x['unified_score'], reverse=True)
    return results


def score_current_portfolio(portfolio_tickers_strategies):
    """Score all existing positions for hold/sell decisions."""
    results = []
    all_tickers = [t for t, _ in portfolio_tickers_strategies]

    for ticker, strategy in portfolio_tickers_strategies:
        other_tickers = [t for t in all_tickers if t != ticker]
        try:
            result = unified_score(ticker, strategy, other_tickers)
            # Adjust verdict for existing positions (higher hold threshold)
            if result['unified_score'] < 30:
                result['verdict'] = 'SELL'
            elif result['unified_score'] < 50:
                result['verdict'] = 'WATCH'
            else:
                result['verdict'] = 'HOLD'
            results.append(result)
        except Exception as e:
            print(f"  ⚠ {ticker}: {e}")

    results.sort(key=lambda x: x['unified_score'], reverse=True)
    return results


def find_best_opportunities(n=10):
    """Find top N opportunities from all tickers in DB."""
    # Get current portfolio tickers from paper portfolio
    portfolio_tickers = _get_paper_portfolio_tickers()

    candidates = []
    for strategy, tickers in STRATEGY_MAP.items():
        for ticker in tickers:
            if ticker in EXCLUDE:
                continue
            candidates.append((ticker, strategy))

    # Deduplicate (ticker might be in multiple strategies — pick best)
    seen = {}
    for ticker, strategy in candidates:
        if ticker not in seen:
            seen[ticker] = strategy
        # We'll score all combos and pick best per ticker

    results = []
    scored_tickers = set()

    for ticker, strategy in candidates:
        key = f"{ticker}_{strategy}"
        if key in scored_tickers:
            continue
        scored_tickers.add(key)

        try:
            result = unified_score(ticker, strategy, portfolio_tickers)
            results.append(result)
        except Exception:
            continue

    # Deduplicate: keep best score per ticker
    best_per_ticker = {}
    for r in results:
        t = r['ticker']
        if t not in best_per_ticker or r['unified_score'] > best_per_ticker[t]['unified_score']:
            best_per_ticker[t] = r

    sorted_results = sorted(best_per_ticker.values(), key=lambda x: x['unified_score'], reverse=True)
    return sorted_results[:n]


def _get_paper_portfolio_tickers():
    """Get current paper portfolio tickers from paper-portfolio.md or trade journal."""
    try:
        from trade_journal import get_open_trades
        trades = get_open_trades()
        return [t['ticker'] for t in trades]
    except Exception:
        pass

    # Fallback: parse paper-portfolio.md
    tickers = []
    pp_path = Path("/data/.openclaw/workspace/memory/paper-portfolio.md")
    try:
        content = pp_path.read_text()
        import re
        for line in content.split('\n'):
            if '| LONG |' in line or '| SHORT |' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) > 2:
                    ticker = parts[2].strip()
                    if ticker and ticker not in ('Ticker', '---'):
                        tickers.append(ticker)
    except Exception:
        pass

    return tickers


def _get_portfolio_with_strategies():
    """Get portfolio tickers with their strategies."""
    portfolio = []
    pp_path = Path("/data/.openclaw/workspace/memory/paper-portfolio.md")

    # First try trade journal
    try:
        from trade_journal import get_open_trades
        trades = get_open_trades()
        for t in trades:
            portfolio.append((t['ticker'], t['strategy'] or 'PS1'))
        if portfolio:
            return portfolio
    except Exception:
        pass

    # Fallback: guess strategy from STRATEGY_MAP
    tickers = _get_paper_portfolio_tickers()
    for ticker in tickers:
        strat = 'PS1'
        for s, t_list in STRATEGY_MAP.items():
            if ticker in t_list:
                strat = s
                break
        portfolio.append((ticker, strat))

    return portfolio


def print_score(result):
    """Pretty-print a single unified score."""
    r = result
    verdict_emoji = {'BUY': '🟢', 'WATCH': '🟡', 'AVOID': '🔴', 'HOLD': '🟢', 'SELL': '🔴'}.get(r['verdict'], '⚪')

    print(f"\n{'='*65}")
    print(f"  {r['ticker']} ({r['strategy']}) — Unified Score: {r['unified_score']}/100 {verdict_emoji} {r['verdict']}")
    print(f"{'='*65}")

    for name, comp in r['components'].items():
        bar_len = int(comp['score'] / 5)
        bar = '█' * bar_len + '░' * (20 - bar_len)
        print(f"  {name:<12} {bar} {comp['score']:>3}/100 (×{WEIGHTS[name]:.2f} = {comp['weighted']:>5.1f})  {comp['details']}")

    print(f"{'─'*65}")
    print(f"  TOTAL: {r['unified_score']}/100 → {verdict_emoji} {r['verdict']}")


def cmd_single(ticker, strategy):
    """Score a single ticker."""
    init_tables()
    portfolio = _get_paper_portfolio_tickers()
    result = unified_score(ticker, strategy, portfolio)
    print_score(result)
    return result


def cmd_portfolio():
    """Score all portfolio positions."""
    init_tables()
    portfolio = _get_portfolio_with_strategies()
    if not portfolio:
        print("❌ Kein Portfolio gefunden")
        return []

    print(f"\n{'='*65}")
    print(f"  📊 PORTFOLIO SCORING — {len(portfolio)} Positionen")
    print(f"{'='*65}")

    results = score_current_portfolio(portfolio)

    print(f"\n{'Rank':>4} {'Ticker':<10} {'Strategie':<6} {'Score':>6} {'Verdict':<8} Details")
    print(f"{'─'*70}")

    for i, r in enumerate(results, 1):
        verdict_emoji = {'HOLD': '🟢', 'WATCH': '🟡', 'SELL': '🔴'}.get(r['verdict'], '⚪')
        top_comp = max(r['components'].items(), key=lambda x: x[1]['weighted'])
        weak_comp = min(r['components'].items(), key=lambda x: x[1]['weighted'])
        print(f"  {i:>2}. {r['ticker']:<10} {r['strategy']:<6} {r['unified_score']:>5}/100 "
              f"{verdict_emoji} {r['verdict']:<6}  Best: {top_comp[0]}={top_comp[1]['score']} | "
              f"Weak: {weak_comp[0]}={weak_comp[1]['score']}")

    return results


def cmd_opportunities(n=10):
    """Find top N opportunities."""
    init_tables()
    print(f"\n{'='*65}")
    print(f"  🔍 TOP {n} OPPORTUNITIES")
    print(f"{'='*65}")

    results = find_best_opportunities(n)

    print(f"\n{'Rank':>4} {'Ticker':<10} {'Strategie':<6} {'Score':>6} {'Verdict':<8} Key Factors")
    print(f"{'─'*75}")

    for i, r in enumerate(results, 1):
        verdict_emoji = {'BUY': '🟢', 'WATCH': '🟡', 'AVOID': '🔴'}.get(r['verdict'], '⚪')
        # Show top 2 components
        sorted_comps = sorted(r['components'].items(), key=lambda x: x[1]['weighted'], reverse=True)
        top2 = ' | '.join(f"{c[0]}={c[1]['score']}" for c in sorted_comps[:2])
        print(f"  {i:>2}. {r['ticker']:<10} {r['strategy']:<6} {r['unified_score']:>5}/100 "
              f"{verdict_emoji} {r['verdict']:<6}  {top2}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Unified Signal Score Engine')
    parser.add_argument('ticker', nargs='?', help='Ticker to score')
    parser.add_argument('strategy', nargs='?', help='Strategy (PS1-PS5)')
    parser.add_argument('--portfolio', action='store_true', help='Score all portfolio positions')
    parser.add_argument('--opportunities', action='store_true', help='Find top opportunities')
    parser.add_argument('-n', type=int, default=10, help='Number of opportunities (default: 10)')
    args = parser.parse_args()

    if args.portfolio:
        cmd_portfolio()
    elif args.opportunities:
        cmd_opportunities(args.n)
    elif args.ticker and args.strategy:
        cmd_single(args.ticker.upper(), args.strategy.upper())
    else:
        print("Usage:")
        print("  python3 unified_scorer.py KTOS PS3          — Score single ticker")
        print("  python3 unified_scorer.py --portfolio       — Score all positions")
        print("  python3 unified_scorer.py --opportunities   — Find top 10 chances")
        sys.exit(1)
