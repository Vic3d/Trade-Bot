#!/usr/bin/env python3
"""
Paper Learning Engine — Closed-Loop Lernmaschine
==================================================
Wertet BEIDE Paper-Trading-Systeme aus und generiert Learnings.
  - paper_portfolio: Swing Trades (Albert's Fund, 3x/Tag)
  - trades: Day Trades (Day Trader v2, 5min)

Usage:
  python3 paper_learning_engine.py              # Vollständige Analyse + Learnings
  python3 paper_learning_engine.py --weekly-report  # Wöchentlicher Markdown-Report
  python3 paper_learning_engine.py --update-scores  # Nur Strategy Scores updaten
"""

import sqlite3, json, sys, math
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

WORKSPACE = Path('/data/.openclaw/workspace')
DB_PATH   = WORKSPACE / 'data/trading.db'
STRATEGIES_JSON = WORKSPACE / 'data/strategies.json'
LEARNINGS_JSON  = WORKSPACE / 'data/trading_learnings.json'
WEEKLY_REPORT   = WORKSPACE / 'memory/paper-trading-weekly.md'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_json import atomic_write_json


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_closed_swing_trades():
    """Lädt abgeschlossene Swing Trades aus paper_portfolio."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, ticker, strategy, entry_price, close_price, shares, fees,
               pnl_eur, pnl_pct, entry_date, close_date, notes
        FROM paper_portfolio
        WHERE status IN ('CLOSED','WIN','LOSS')
          AND entry_price IS NOT NULL
          AND close_price IS NOT NULL
          AND pnl_eur IS NOT NULL
          AND notes NOT LIKE '%DATENFEHLER%'
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_closed_day_trades():
    """Lädt abgeschlossene Day Trades aus trades-Tabelle."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, ticker, strategy, direction, entry_price, exit_price,
               shares, pnl_eur, pnl_pct, status, entry_date, exit_date,
               holding_days, conviction_at_entry, regime_at_entry, exit_type
        FROM trades
        WHERE status IN ('WIN', 'LOSS')
          AND entry_price IS NOT NULL
          AND exit_price IS NOT NULL
          AND pnl_eur IS NOT NULL
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def infer_market(ticker: str) -> str:
    """Leitet Markt aus Ticker-Suffix ab."""
    if ticker.endswith('.DE') or ticker.endswith('.AS') or ticker.endswith('.PA') or ticker.endswith('.CO'):
        return 'EU'
    if ticker.endswith('.L'):
        return 'UK'
    if ticker.endswith('.OL'):
        return 'NO'
    if ticker.endswith('.T') or ticker.endswith('.HK'):
        return 'ASIA'
    return 'US'


def parse_hour(date_str) -> int | None:
    """Extrahiert Stunde aus datetime-String."""
    if not date_str:
        return None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str[:16], fmt[:len(date_str[:16])]).hour
        except Exception:
            continue
    return None


def time_bucket(hour: int | None) -> str:
    if hour is None:
        return 'unknown'
    if 7 <= hour < 11:
        return 'morning'
    if 11 <= hour < 14:
        return 'midday'
    if 14 <= hour < 18:
        return 'afternoon'
    return 'evening'


def _recency_weight(exit_date_str: str | None, half_life_days: int = 60) -> float:
    """
    P25-8: Exponentieller Recency-Decay.
    Trade von heute → 1.0, Trade von vor 60d → 0.5, vor 120d → 0.25.

    Formel: weight = 0.5 ** (age_days / half_life_days)
    """
    if not exit_date_str:
        return 1.0
    try:
        from datetime import datetime as _dt, timezone as _tz
        # Akzeptiert YYYY-MM-DD oder ISO
        ed = _dt.fromisoformat(str(exit_date_str)[:19].replace('T', ' '))
        # Bug 6 (2026-04-23): _dt.utcnow() in Py3.12+ deprecated → naive UTC.
        now_utc = _dt.now(_tz.utc).replace(tzinfo=None)
        age_days = max(0, (now_utc - ed).days)
        return 0.5 ** (age_days / half_life_days)
    except Exception:
        return 1.0


def build_strategy_stats(trades: list, source: str) -> dict:
    """Berechnet Win-Rate, Avg P&L, etc. pro Strategie. P25-8: mit Recency-Decay."""
    stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0,
                                  'pnl_list': [], 'source': source,
                                  'weighted_wins': 0.0, 'weighted_losses': 0.0,
                                  'weighted_pnl': 0.0, 'weight_sum': 0.0})
    for t in trades:
        strat = t.get('strategy') or 'UNKNOWN'
        strat_base = strat.split('-')[0] if '-' in strat else strat
        pnl = t.get('pnl_eur') or 0
        pnl_pct = t.get('pnl_pct') or 0

        # P25-8 Recency-Decay
        w = _recency_weight(t.get('exit_date') or t.get('close_date'))

        stats[strat_base]['total_pnl'] += pnl
        stats[strat_base]['pnl_list'].append(pnl_pct)
        stats[strat_base]['weighted_pnl'] += pnl * w
        stats[strat_base]['weight_sum'] += w

        is_win = (pnl > 0) if source == 'swing' else (t.get('status') == 'WIN')
        if is_win:
            stats[strat_base]['wins'] += 1
            stats[strat_base]['weighted_wins'] += w
        else:
            stats[strat_base]['losses'] += 1
            stats[strat_base]['weighted_losses'] += w

    # Add weighted_win_rate field
    for s, v in stats.items():
        ws = v['weighted_wins'] + v['weighted_losses']
        v['weighted_win_rate'] = (v['weighted_wins'] / ws) if ws > 0 else 0.0

    return dict(stats)


def compute_risk_adjusted_return(pnl_list: list) -> float:
    """Sharpe-ähnlicher Score: Avg / Std (vereinfacht)."""
    if not pnl_list or len(pnl_list) < 2:
        return 0.0
    avg = sum(pnl_list) / len(pnl_list)
    std = math.sqrt(sum((x - avg) ** 2 for x in pnl_list) / len(pnl_list))
    if std == 0:
        return avg
    return avg / std


def analyze_trailing_stops() -> dict:
    """Analysiert ob Trailing Stops Gewinne schützen oder zu früh rauswerfen.

    Sub-7 #2 Fix (2026-04-23): Single-Source = paper_portfolio + trade_tranches.
    "Mit Trail" = Trade hat ≥1 Tranche-Exit (Tranche 1/2/3 ausgelöst).
    "Ohne Trail" = CLOSED ohne Tranche-Aktivität (Hard Stop, Manual, etc).
    Wenn trade_tranches leer ist → noch keine Trail-Events — informativ
    leeres Resultat statt irreführende Zombie-Statistik aus alter `trades`-
    Tabelle.
    """
    conn = get_db()

    # Trades mit Trail-Aktivität (haben mind. 1 Tranche-Eintrag)
    with_trail = conn.execute("""
        SELECT COUNT(*) as n,
        SUM(CASE WHEN p.pnl_eur > 0 THEN 1 ELSE 0 END) as wins,
        COALESCE(AVG(p.pnl_pct), 0) as avg_pct,
        COALESCE(SUM(p.pnl_eur), 0) as total_pnl,
        (SELECT COALESCE(AVG(c), 0) FROM
            (SELECT COUNT(*) as c FROM trade_tranches GROUP BY trade_id)) as avg_trails
        FROM paper_portfolio p
        WHERE p.status = 'CLOSED'
          AND p.id IN (SELECT DISTINCT trade_id FROM trade_tranches)
    """).fetchone()

    # Trades ohne Trail-Aktivität (Hard Stop, Manual, Thesis-Invalidated, etc.)
    without_trail = conn.execute("""
        SELECT COUNT(*) as n,
        SUM(CASE WHEN p.pnl_eur > 0 THEN 1 ELSE 0 END) as wins,
        COALESCE(AVG(p.pnl_pct), 0) as avg_pct,
        COALESCE(SUM(p.pnl_eur), 0) as total_pnl
        FROM paper_portfolio p
        WHERE p.status = 'CLOSED'
          AND p.id NOT IN (SELECT DISTINCT trade_id FROM trade_tranches)
    """).fetchone()

    # "Left on table" Approximation: Trades die stark im Plus waren aber
    # mit kleinerem PnL geschlossen haben (>5% PnL Differenz heuristisch).
    # paper_portfolio hat kein max_unrealized_pct → ATR-basierte Schätzung
    # via expected_exit_price wenn vorhanden, sonst übersprungen.
    slippage = conn.execute("""
        SELECT ticker, strategy, expected_exit_price, close_price, pnl_pct,
               exit_type
        FROM paper_portfolio
        WHERE status = 'CLOSED'
          AND expected_exit_price IS NOT NULL
          AND close_price IS NOT NULL
          AND expected_exit_price > close_price
        ORDER BY (expected_exit_price - close_price) DESC LIMIT 5
    """).fetchall()

    conn.close()

    n_with = with_trail['n'] or 0
    n_without = without_trail['n'] or 0

    result = {
        'with_trail': {
            'trades': n_with,
            'win_rate': round((with_trail['wins'] or 0) / max(n_with, 1) * 100, 1) if n_with > 0 else 0.0,
            'avg_pnl_pct': round(with_trail['avg_pct'] or 0, 2),
            'total_pnl': round(with_trail['total_pnl'] or 0, 2),
            'avg_trail_count': round(with_trail['avg_trails'] or 0, 1),
        },
        'without_trail': {
            'trades': n_without,
            'win_rate': round((without_trail['wins'] or 0) / max(n_without, 1) * 100, 1) if n_without > 0 else 0.0,
            'avg_pnl_pct': round(without_trail['avg_pct'] or 0, 2),
            'total_pnl': round(without_trail['total_pnl'] or 0, 2),
        },
        'worst_left_on_table': [
            {'ticker': r['ticker'], 'strategy': r['strategy'],
             'expected_exit': round(r['expected_exit_price'] or 0, 2),
             'actual_close': round(r['close_price'] or 0, 2),
             'pnl_pct': round(r['pnl_pct'] or 0, 2),
             'exit_type': r['exit_type'] or '?'}
            for r in slippage
        ],
        'note': ('trade_tranches noch nicht populiert — Tranche-System aktiv aber'
                 ' bisher kein Exit-Event geloggt') if n_with == 0 else None,
    }
    return result


def analyze_styles() -> dict:
    """Vergleiche Trading-Stile: disciplined vs aggressive vs contrarian."""
    conn = get_db()
    styles = ['disciplined', 'aggressive', 'contrarian']
    results = {}
    for style in styles:
        pp = conn.execute(
            "SELECT COUNT(*) as n, "
            "SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins, "
            "COALESCE(SUM(pnl_eur), 0) as total_pnl, "
            "COALESCE(AVG(pnl_pct), 0) as avg_pct "
            "FROM paper_portfolio WHERE status IN ('CLOSED','WIN','LOSS') AND style=?", (style,)).fetchone()
        dt = conn.execute(
            "SELECT COUNT(*) as n, "
            "SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins, "
            "COALESCE(SUM(pnl_eur), 0) as total_pnl, "
            "COALESCE(AVG(pnl_pct), 0) as avg_pct "
            "FROM trades WHERE status IN ('WIN','LOSS') AND style=?", (style,)).fetchone()
        total_n = (pp['n'] or 0) + (dt['n'] or 0)
        total_wins = (pp['wins'] or 0) + (dt['wins'] or 0)
        total_pnl = (pp['total_pnl'] or 0) + (dt['total_pnl'] or 0)
        if total_n > 0:
            results[style] = {
                'trades': total_n, 'wins': total_wins,
                'win_rate': round(total_wins / total_n * 100, 1),
                'total_pnl': round(total_pnl, 2),
            }
    conn.close()
    return results


def analyze_strategies() -> dict:
    """
    Vergleiche Strategien (DT1-DT9, PS1-PS5, PT, PM) über beide Tabellen.
    Output: Win-Rate, Avg P&L, Avg Holding Time, Best/Worst pro Strategie.
    """
    swing = load_closed_swing_trades()
    day   = load_closed_day_trades()

    swing_stats = build_strategy_stats(swing, 'swing')
    day_stats   = build_strategy_stats(day, 'day')

    # Merge
    all_strategies = {}
    for strat, s in swing_stats.items():
        all_strategies[strat] = s
    for strat, s in day_stats.items():
        if strat in all_strategies:
            # Merge
            all_strategies[strat]['wins']      += s['wins']
            all_strategies[strat]['losses']    += s['losses']
            all_strategies[strat]['total_pnl'] += s['total_pnl']
            all_strategies[strat]['pnl_list']  += s['pnl_list']
            all_strategies[strat]['source']     = 'both'
        else:
            all_strategies[strat] = s

    result = {}
    for strat, s in all_strategies.items():
        total = s['wins'] + s['losses']
        win_rate = s['wins'] / total if total > 0 else 0
        avg_pnl = sum(s['pnl_list']) / len(s['pnl_list']) if s['pnl_list'] else 0
        rar = compute_risk_adjusted_return(s['pnl_list'])
        result[strat] = {
            'trades': total,
            'wins': s['wins'],
            'losses': s['losses'],
            'win_rate': round(win_rate, 3),
            'avg_pnl_pct': round(avg_pnl, 2),
            'total_pnl_eur': round(s['total_pnl'], 2),
            'risk_adj_return': round(rar, 3),
            'source': s['source']
        }
    return result


def detect_patterns() -> dict:
    """
    Finde Muster in Gewinn/Verlust-Trades:
    - Welche Tageszeit performt besser?
    - Welche Märkte (DE/US/UK) performen besser?
    - Sektor-Performance
    """
    swing = load_closed_swing_trades()
    day   = load_closed_day_trades()

    # ─ Markt-Performance ─
    market_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0})

    for t in swing:
        m = infer_market(t['ticker'])
        pnl = t.get('pnl_eur') or 0
        market_stats[m]['total_pnl'] += pnl
        if pnl > 0:
            market_stats[m]['wins'] += 1
        else:
            market_stats[m]['losses'] += 1

    for t in day:
        m = infer_market(t['ticker'])
        pnl = t.get('pnl_eur') or 0
        market_stats[m]['total_pnl'] += pnl
        if t.get('status') == 'WIN':
            market_stats[m]['wins'] += 1
        else:
            market_stats[m]['losses'] += 1

    market_scores = {}
    for m, s in market_stats.items():
        total = s['wins'] + s['losses']
        market_scores[m] = {
            'trades': total,
            'win_rate': round(s['wins'] / total, 3) if total > 0 else 0,
            'total_pnl_eur': round(s['total_pnl'], 2)
        }

    # ─ Tageszeit-Performance (Day Trades) ─
    time_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0})
    for t in day:
        hour = parse_hour(t.get('entry_date'))
        bucket = time_bucket(hour)
        pnl = t.get('pnl_eur') or 0
        time_stats[bucket]['total_pnl'] += pnl
        if t.get('status') == 'WIN':
            time_stats[bucket]['wins'] += 1
        else:
            time_stats[bucket]['losses'] += 1

    time_scores = {}
    for b, s in time_stats.items():
        total = s['wins'] + s['losses']
        time_scores[b] = {
            'trades': total,
            'win_rate': round(s['wins'] / total, 3) if total > 0 else 0,
            'total_pnl_eur': round(s['total_pnl'], 2)
        }

    return {
        'market_scores': market_scores,
        'time_scores': time_scores
    }


def _adaptive_thresholds() -> dict:
    """Sub-7 #3: Berechnet adaptive Recommendation-Schwellen aus dem
    rolling 90-Tage-Median des Portfolios. Verhindert dass im Bear-Markt
    alle Strategien als SUSPEND gebrandmarkt werden, weil dann selbst
    eine 35%-WR-Strategie überdurchschnittlich gut sein kann.

    Fallback auf hardcodierte Defaults wenn nicht genug Daten (<20 Trades
    in 90d) — bewährte Werte aus 12.04.2026 Audit.
    """
    DEFAULTS = {
        'suspend_wr': 0.30, 'suspend_combo_wr': 0.45,
        'reduce_wr': 0.50, 'elevate_wr': 0.60,
        'suspend_pnl': -200.0, 'reduce_pnl': -100.0,
    }
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT pnl_eur FROM paper_portfolio
            WHERE status = 'CLOSED' AND pnl_eur IS NOT NULL
              AND close_date >= date('now', '-90 day')
        """).fetchall()
        conn.close()
        if len(rows) < 20:
            return DEFAULTS
        pnls = sorted(r[0] for r in rows)
        wins = sum(1 for p in pnls if p > 0)
        baseline_wr = wins / len(pnls)
        # Adaptive Schwellen: -10pp vom Median für SUSPEND, +10pp für ELEVATE
        # Begrenzt auf [0.20, 0.40] für SUSPEND damit Schutzfunktion erhalten bleibt.
        suspend_wr = max(0.20, min(0.40, baseline_wr - 0.10))
        suspend_combo_wr = max(0.35, min(0.55, baseline_wr - 0.05))
        reduce_wr = max(0.40, min(0.60, baseline_wr))
        elevate_wr = max(0.50, min(0.70, baseline_wr + 0.10))
        # P&L-Schwellen: 25%-Quartil als REDUCE, 10%-Quartil als SUSPEND
        # (negative Schwellen — schlechtester Quartil)
        if len(pnls) >= 10:
            q10 = pnls[max(0, int(len(pnls) * 0.10) - 1)]
            q25 = pnls[max(0, int(len(pnls) * 0.25) - 1)]
            suspend_pnl = min(-100.0, q10 * 5)  # 5x worst-decile als kumulativer Verlust
            reduce_pnl = min(-50.0, q25 * 3)
        else:
            suspend_pnl = DEFAULTS['suspend_pnl']
            reduce_pnl = DEFAULTS['reduce_pnl']
        return {
            'suspend_wr': suspend_wr, 'suspend_combo_wr': suspend_combo_wr,
            'reduce_wr': reduce_wr, 'elevate_wr': elevate_wr,
            'suspend_pnl': suspend_pnl, 'reduce_pnl': reduce_pnl,
            'baseline_wr': baseline_wr, 'sample_n': len(pnls),
        }
    except Exception:
        return DEFAULTS


def get_recommendation(win_rate: float, trades: int, total_pnl_eur: float = 0.0) -> str:
    """
    Gibt Empfehlung basierend auf Win-Rate, Anzahl Trades UND realem P&L.

    BUG FIX (12.04.2026): Vorher nur Win-Rate → DT2 (41% WR, -579€) und DT4
    (40% WR, -858€) bekamen 'KEEP' obwohl sie dauerhaft Geld verlieren.

    Sub-7 #3 (23.04.2026): Schwellen sind jetzt adaptiv aus dem rolling
    90-Tage-Portfolio-Median (siehe _adaptive_thresholds). Bear-Markt
    Schutz: in schwachem Marktumfeld werden Schwellen automatisch nach
    unten verschoben.

    Logik:
    - SUSPEND: WR < suspend_wr ODER (WR < suspend_combo_wr UND P&L < suspend_pnl mit 15+ Trades)
    - REDUCE:  WR < reduce_wr UND P&L < reduce_pnl (genug Daten aber kein Edge)
    - ELEVATE: WR > elevate_wr UND P&L positiv
    - KEEP:    Alles dazwischen
    """
    if trades < 10:
        return 'INSUFFICIENT_DATA'

    # ── Hard Guardrails (NICHT adaptiv) ──
    # Verhindern dass Bear-Markt-Adaptive eine Geldvernichter-Strategie schützt.
    # Sub-7 #3 Hotfix: Ohne diese Klausel bekam DT4 (40% WR, -858€, 112 Trades)
    # in einem Bear-Markt mit baseline_wr=16% ein KEEP — falsch.
    if trades >= 30 and total_pnl_eur < -500:
        return 'SUSPEND'  # Klares Geldvernichter-Profil, unabhängig von Marktphase
    if trades >= 15 and total_pnl_eur < -300 and win_rate < 0.45:
        return 'SUSPEND'  # Genug Daten + nennenswerter Verlust + schwache WR

    th = _adaptive_thresholds()

    # Adaptive SUSPEND: WR deutlich unter Markt-Baseline
    if win_rate < th['suspend_wr']:
        return 'SUSPEND'

    # Adaptive P&L-SUSPEND: Strategie verliert Geld trotz moderater WR
    if trades >= 15 and win_rate < th['suspend_combo_wr'] and total_pnl_eur < th['suspend_pnl']:
        return 'SUSPEND'

    # REDUCE: Positiver Ansatz aber negatives Ergebnis — Conviction runter
    if trades >= 10 and total_pnl_eur < th['reduce_pnl'] and win_rate < th['reduce_wr']:
        return 'REDUCE'

    # ELEVATE: Nur wenn sowohl Win-Rate als auch P&L gut (UND mind. 10 Trades,
    # plus stricter Trade-Count damit ein 5-Trade-Hotrun keine ELEVATE auslöst)
    if trades >= 10 and win_rate > th['elevate_wr'] and total_pnl_eur > 0:
        return 'ELEVATE'

    return 'KEEP'


def update_strategy_scores() -> list:
    """
    Updated Conviction Scores in data/strategies.json basierend auf echten Ergebnissen.
    Strategy mit <30% Win-Rate nach 10+ Trades → conviction -1
    Strategy mit >60% Win-Rate nach 10+ Trades → conviction +1
    Returns: list of changes made
    """
    strategy_analysis = analyze_strategies()
    changes = []

    if not STRATEGIES_JSON.exists():
        print("  ⚠️ strategies.json nicht gefunden — skip score update")
        return changes

    strategies = json.loads(STRATEGIES_JSON.read_text())

    for strat_id, analysis in strategy_analysis.items():
        rec = get_recommendation(
            analysis['win_rate'],
            analysis['trades'],
            analysis.get('total_pnl_eur', 0.0)  # P&L jetzt miteinbezogen
        )
        if rec == 'INSUFFICIENT_DATA':
            continue

        if strat_id not in strategies:
            continue

        strat = strategies[strat_id]
        genesis = strat.get('genesis', {})
        current_conv = genesis.get('conviction_current', genesis.get('conviction_at_start', 3))

        if rec in ('SUSPEND', 'REDUCE') and current_conv > 1:
            new_conv = max(1, current_conv - 1)
            genesis['conviction_current'] = new_conv
            genesis['auto_adjusted'] = True
            genesis['last_updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            pnl_val = analysis.get('total_pnl_eur', 0)
            reason = (
                f'Win-Rate {analysis["win_rate"]:.0%} nach {analysis["trades"]} Trades < 30%'
                if rec == 'SUSPEND' and analysis['win_rate'] < 0.30
                else f'Win-Rate {analysis["win_rate"]:.0%} + P&L {pnl_val:+.0f}€ — kein Edge'
            )
            genesis.setdefault('feedback_history', []).append({
                'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'action': 'conviction_decreased',
                'reason': reason,
                'old_conviction': current_conv,
                'new_conviction': new_conv,
                'total_pnl_eur': round(pnl_val, 2),
                'win_rate': round(analysis['win_rate'], 3),
            })
            strategies[strat_id]['genesis'] = genesis
            changes.append(
                f"{strat_id}: conviction {current_conv} → {new_conv} "
                f"(WR {analysis['win_rate']:.0%}, PnL {pnl_val:+.0f}€, {rec})"
            )

        elif rec == 'ELEVATE' and current_conv < 5:
            new_conv = min(5, current_conv + 1)
            genesis['conviction_current'] = new_conv
            genesis['auto_adjusted'] = True
            genesis['last_updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            pnl_val = analysis.get('total_pnl_eur', 0)
            genesis.setdefault('feedback_history', []).append({
                'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'action': 'conviction_increased',
                'reason': f'Win-Rate {analysis["win_rate"]:.0%} + P&L {pnl_val:+.0f}€ > 60% WR',
                'old_conviction': current_conv,
                'new_conviction': new_conv,
                'total_pnl_eur': round(pnl_val, 2),
                'win_rate': round(analysis['win_rate'], 3),
            })
            strategies[strat_id]['genesis'] = genesis
            changes.append(
                f"{strat_id}: conviction {current_conv} → {new_conv} "
                f"(WR {analysis['win_rate']:.0%}, PnL {pnl_val:+.0f}€, ELEVATE)"
            )

    atomic_write_json(STRATEGIES_JSON, strategies)
    return changes


def calibrate_confidence() -> dict:
    """Berechne echte Win-Rate pro Confidence-Bucket (Verbesserung 5)."""
    conn = get_db()
    buckets = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 101)]
    results = {}
    for low, high in buckets:
        label = f"{low}-{high}"
        row = conn.execute("""
            SELECT COUNT(*) as n,
            SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins
            FROM trades WHERE status IN ('WIN','LOSS')
            AND conviction_at_entry >= ? AND conviction_at_entry < ?
        """, (low, high)).fetchone()
        n = row[0] if row else 0
        wins = row[1] if row else 0
        if n and n > 0:
            results[label] = {
                'trades': n,
                'win_rate': round((wins or 0) / n * 100, 1)
            }
    conn.close()
    return results


def close_feedback_loop() -> dict:
    """
    Schreibt vollständige Learnings in data/trading_learnings.json.
    Enthält Strategy Scores, Market Scores, Time Scores, Active Rules.
    """
    strategy_analysis = analyze_strategies()
    patterns = detect_patterns()

    # Strategy Scores mit Empfehlungen
    strategy_scores = {}
    active_rules = []

    for strat_id, analysis in strategy_analysis.items():
        rec = get_recommendation(
            analysis['win_rate'],
            analysis['trades'],
            analysis.get('total_pnl_eur', 0.0)
        )
        strategy_scores[strat_id] = {
            'win_rate': analysis['win_rate'],
            'avg_pnl_pct': analysis['avg_pnl_pct'],
            'total_pnl_eur': analysis['total_pnl_eur'],
            'trades': analysis['trades'],
            'risk_adj_return': analysis['risk_adj_return'],
            'recommendation': rec,
            'source': analysis['source']
        }

        # Active Rules generieren
        if rec in ('SUSPEND', 'REDUCE'):
            pnl_str = f", PnL {analysis.get('total_pnl_eur', 0):+.0f}€" if analysis.get('total_pnl_eur') else ''
            active_rules.append(
                f"{strat_id} {rec.lower()}: {analysis['win_rate']:.0%} win rate"
                f"{pnl_str} after {analysis['trades']} trades"
            )
        elif rec == 'ELEVATE':
            active_rules.append(
                f"{strat_id} elevated: {analysis['win_rate']:.0%} win rate, avg {analysis['avg_pnl_pct']:+.1f}%"
            )

    # ── Trailing Stop Analyse ──
    trail_analysis = analyze_trailing_stops()

    # Confidence-Kalibrierung (Verbesserung 5)
    conf_calib = calibrate_confidence()

    learnings = {
        'last_updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'strategy_scores': strategy_scores,
        'market_scores': patterns['market_scores'],
        'time_scores': patterns['time_scores'],
        'trailing_stops': trail_analysis,
        'active_rules': active_rules,
        'confidence_calibration': conf_calib
    }

    atomic_write_json(LEARNINGS_JSON, learnings)
    print(f"  ✅ trading_learnings.json geschrieben ({len(strategy_scores)} Strategien, {len(active_rules)} Regeln)")
    return learnings


def generate_weekly_report():
    """
    Erstellt Markdown-Report für memory/paper-trading-weekly.md.
    Beide Systeme Side-by-Side, Strategy Ranking, Empfehlungen.
    """
    swing = load_closed_swing_trades()
    day   = load_closed_day_trades()
    strategy_analysis = analyze_strategies()
    patterns = detect_patterns()
    now = datetime.now(timezone.utc)
    week = now.strftime('%Y-W%W')

    # ─ Totals ─
    swing_pnl   = sum(t['pnl_eur'] for t in swing)
    swing_wins  = sum(1 for t in swing if (t['pnl_eur'] or 0) > 0)
    swing_total = len(swing)
    swing_wr    = swing_wins / swing_total if swing_total > 0 else 0

    day_wins    = sum(1 for t in day if t['status'] == 'WIN')
    day_total   = len(day)
    day_pnl     = sum((t['pnl_eur'] or 0) for t in day)
    day_wr      = day_wins / day_total if day_total > 0 else 0

    # ─ Top/Worst Trades ─
    all_closed = [
        {**t, '_system': 'SWING', '_pnl': t['pnl_eur'] or 0} for t in swing
    ] + [
        {**t, '_system': 'DAY', '_pnl': t['pnl_eur'] or 0} for t in day
    ]

    sorted_trades = sorted(all_closed, key=lambda x: x['_pnl'], reverse=True)
    top3    = sorted_trades[:3]
    worst3  = sorted_trades[-3:]

    # ─ Strategy Ranking (nach Risk-Adjusted Return) ─
    # Empfehlungen einbauen
    for strat_id, a in strategy_analysis.items():
        # Bug AE (2026-04-23): vorher 2-Arg → P&L-Gewichtung wurde umgangen,
        # DT-Strategien erschienen wieder als KEEP trotz negativem P&L.
        a['recommendation'] = get_recommendation(
            a['win_rate'], a['trades'], a.get('total_pnl_eur', 0.0)
        )
    ranked = sorted(
        [(k, v) for k, v in strategy_analysis.items() if v['trades'] >= 3],
        key=lambda x: x[1]['risk_adj_return'],
        reverse=True
    )

    # ─ Market/Time Patterns ─
    market_scores = patterns['market_scores']
    time_scores   = patterns['time_scores']

    # ─ Report bauen ─
    lines = [
        f"# Paper Trading Weekly Report — {week}",
        f"*Erstellt: {now.strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "## 📊 System Vergleich",
        "",
        "| Metrik | 🔵 Albert's Fund (Swing) | 🟠 Day Trader v2 (Day) |",
        "|--------|--------------------------|------------------------|",
        f"| Abgeschlossene Trades | {swing_total} | {day_total} |",
        f"| Win-Rate | {swing_wr:.0%} | {day_wr:.0%} |",
        f"| Total P&L | {swing_pnl:+.1f}€ | {day_pnl:+.1f}€ |",
        f"| Gesamt P&L | **{swing_pnl + day_pnl:+.1f}€** | |",
        "",
        "## 🏆 Top 3 Trades",
        "",
    ]

    for i, t in enumerate(top3, 1):
        ticker = t.get('ticker', '?')
        pnl    = t['_pnl']
        system = t['_system']
        strat  = t.get('strategy', '?')
        reason = t.get('notes') or t.get('thesis') or '—'
        if reason and len(reason) > 80:
            reason = reason[:80] + '...'
        lines.append(f"**#{i} {ticker}** ({system}, {strat}) — P&L: **+{pnl:.1f}€**")
        lines.append(f"> {reason}")
        lines.append("")

    lines += ["## 💀 Worst 3 Trades", ""]
    for i, t in enumerate(worst3, 1):
        ticker = t.get('ticker', '?')
        pnl    = t['_pnl']
        system = t['_system']
        strat  = t.get('strategy', '?')
        reason = t.get('notes') or t.get('thesis') or '—'
        if reason and len(reason) > 80:
            reason = reason[:80] + '...'
        lines.append(f"**#{i} {ticker}** ({system}, {strat}) — P&L: **{pnl:.1f}€**")
        lines.append(f"> {reason}")
        lines.append("")

    lines += ["## 📈 Strategy Ranking (Risk-Adjusted Return)", "",
              "| Rang | Strategie | Trades | Win-Rate | Avg P&L% | RAR | Empfehlung |",
              "|------|-----------|--------|----------|----------|-----|------------|"]

    for i, (strat_id, a) in enumerate(ranked, 1):
        rec = a.get('recommendation', 'KEEP')
        rec_emoji = {'ELEVATE': '🚀', 'SUSPEND': '🛑', 'KEEP': '✅', 'INSUFFICIENT_DATA': '⏳'}.get(rec, '❓')
        lines.append(
            f"| {i} | {strat_id} | {a['trades']} | {a['win_rate']:.0%} | {a['avg_pnl_pct']:+.1f}% | {a['risk_adj_return']:+.2f} | {rec_emoji} {a['recommendation']} |"
        )

    lines += ["",
              "## 🌍 Markt-Performance",
              "",
              "| Markt | Trades | Win-Rate | Total P&L |",
              "|-------|--------|----------|-----------|"]
    for m, s in sorted(market_scores.items(), key=lambda x: x[1]['total_pnl_eur'], reverse=True):
        lines.append(f"| {m} | {s['trades']} | {s['win_rate']:.0%} | {s['total_pnl_eur']:+.1f}€ |")

    lines += ["",
              "## ⏰ Tageszeit-Performance (Day Trades)",
              "",
              "| Tageszeit | Trades | Win-Rate | Total P&L |",
              "|-----------|--------|----------|-----------|"]
    for b, s in sorted(time_scores.items(), key=lambda x: x[1]['total_pnl_eur'], reverse=True):
        lines.append(f"| {b} | {s['trades']} | {s['win_rate']:.0%} | {s['total_pnl_eur']:+.1f}€ |")

    # ─ Empfehlungen ─
    lines += ["", "## 💡 Konkrete Empfehlungen", ""]
    for strat_id, a in ranked:
        if a['recommendation'] == 'SUSPEND':
            lines.append(f"- 🛑 **{strat_id} pausieren** — Win-Rate {a['win_rate']:.0%} nach {a['trades']} Trades")
        elif a['recommendation'] == 'ELEVATE':
            lines.append(f"- 🚀 **{strat_id} hochfahren** — Win-Rate {a['win_rate']:.0%}, avg {a['avg_pnl_pct']:+.1f}%")

    if market_scores:
        best_market = max(market_scores.items(), key=lambda x: x[1]['total_pnl_eur'])
        worst_market = min(market_scores.items(), key=lambda x: x[1]['total_pnl_eur'])
        lines.append(f"- 🌍 Bester Markt: **{best_market[0]}** ({best_market[1]['total_pnl_eur']:+.1f}€)")
        lines.append(f"- ⚠️ Schlechtester Markt: **{worst_market[0]}** ({worst_market[1]['total_pnl_eur']:+.1f}€)")

    if time_scores:
        best_time = max(time_scores.items(), key=lambda x: x[1]['win_rate'])
        lines.append(f"- ⏰ Beste Tageszeit: **{best_time[0]}** ({best_time[1]['win_rate']:.0%} Win-Rate)")

    # ─ Style-Vergleich (disciplined vs aggressive vs contrarian) ─
    style_data = analyze_styles()
    if style_data:
        lines += ["", "## 🎭 Trading-Stil Vergleich", "",
                  "| Stil | Trades | Win-Rate | Total P&L |",
                  "|------|--------|----------|-----------|"]
        for style_name in ['disciplined', 'aggressive', 'contrarian']:
            if style_name in style_data:
                s = style_data[style_name]
                emoji = {'disciplined': '🎯', 'aggressive': '🔥', 'contrarian': '🎲'}.get(style_name, '❓')
                lines.append(f"| {emoji} {style_name} | {s['trades']} | {s['win_rate']:.0f}% | {s['total_pnl']:+.1f}€ |")
        lines += ["", "*disciplined = Signal abwarten | aggressive = vor Signal kaufen | contrarian = gegen den Konsens*"]

    # ─ Confidence Kalibrierung (Verbesserung 5) ─
    conf_calib = calibrate_confidence()
    if conf_calib:
        lines += ["", "## 🎯 Confidence Kalibrierung", "",
                  "| Confidence-Bucket | Trades | Echte Win-Rate |",
                  "|-------------------|--------|----------------|"]
        for bucket, data_b in sorted(conf_calib.items()):
            lines.append(f"| {bucket}% | {data_b['trades']} | {data_b['win_rate']:.1f}% |")
        lines += ["", "*Zeigt ob höhere Confidence tatsächlich zu höherer Win-Rate führt.*"]

    # ─ Benchmark Vergleich (Verbesserung 2) ─
    benchmark_path = WORKSPACE / 'data/benchmark_history.json'
    if benchmark_path.exists():
        try:
            bench_data = json.loads(benchmark_path.read_text())
            if bench_data:
                sorted_dates = sorted(bench_data.keys())
                # Letzte Woche: letzte 7 Einträge
                recent = sorted_dates[-7:]
                if len(recent) >= 2:
                    start_date = recent[0]
                    end_date   = recent[-1]
                    start = bench_data[start_date]
                    end   = bench_data[end_date]
                    spy_start = start.get('spy') or 0
                    spy_end   = end.get('spy') or 0
                    dax_start = start.get('dax') or 0
                    dax_end   = end.get('dax') or 0
                    pv_start  = start.get('portfolio_value') or 0
                    pv_end    = end.get('portfolio_value') or 0
                    spy_pct = ((spy_end / spy_start) - 1) * 100 if spy_start > 0 else 0
                    dax_pct = ((dax_end / dax_start) - 1) * 100 if dax_start > 0 else 0
                    pv_pct  = ((pv_end  / pv_start)  - 1) * 100 if pv_start  > 0 else 0
                    lines += ["", "## 📊 Benchmark Vergleich", "",
                              f"*Periode: {start_date} → {end_date}*", "",
                              "| | Diese Woche |",
                              "|-|-------------|",
                              f"| 💼 Portfolio | **{pv_pct:+.2f}%** |",
                              f"| 🇺🇸 SPY      | {spy_pct:+.2f}% |",
                              f"| 🇩🇪 DAX      | {dax_pct:+.2f}% |",
                              ""]
                    alpha_spy = pv_pct - spy_pct
                    alpha_dax = pv_pct - dax_pct
                    lines.append(f"*Alpha vs SPY: {alpha_spy:+.2f}% | Alpha vs DAX: {alpha_dax:+.2f}%*")
        except Exception as e:
            lines += ["", "## 📊 Benchmark Vergleich", "", f"*Fehler beim Laden: {e}*"]

    WEEKLY_REPORT.write_text('\n'.join(lines) + '\n')
    print(f"  ✅ Wöchentlicher Report: {WEEKLY_REPORT}")
    return '\n'.join(lines)


def validate_backtest_vs_live() -> dict:
    """P1.6 — Backtest WR vs Live WR vergleichen, Downgrade-Flag setzen.

    Wenn live-WR > 15pp schlechter als backtest-WR → downgrade=True
    Conviction-Scorer reduziert Bonus dann um -5pt.
    """
    bt_file = WORKSPACE / 'data' / 'backtest_results.json'
    live_file = LEARNINGS_JSON
    out_file = WORKSPACE / 'data' / 'backtest_validation_status.json'
    if not bt_file.exists() or not live_file.exists():
        return {}
    try:
        bt = json.loads(bt_file.read_text(encoding='utf-8'))
        live = json.loads(live_file.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"  ⚠️  Backtest-Validation parse error: {e}")
        return {}

    live_scores = live.get('strategy_scores', {})
    out: dict = {}
    for sid, bt_entry in bt.items():
        if isinstance(bt_entry, dict):
            bt_orig = bt_entry.get('original', bt_entry)
            bt_wr = bt_orig.get('wr', bt_orig.get('win_rate'))
        else:
            continue
        live_entry = live_scores.get(sid, {})
        live_wr = live_entry.get('win_rate')
        live_trades = live_entry.get('trades', 0)
        if bt_wr is None or live_wr is None or live_trades < 5:
            continue
        gap = live_wr - bt_wr  # negativ = live schlechter
        downgrade = gap < -0.15
        out[sid] = {
            'backtest_wr': round(bt_wr, 3),
            'live_wr': round(live_wr, 3),
            'gap': round(gap, 3),
            'live_trades': live_trades,
            'downgrade': downgrade,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
    try:
        atomic_write_json(out_file, out)
    except Exception as e:
        print(f"  ⚠️  Backtest-Validation write error: {e}")
    return out


def run_all():
    """Vollständige Analyse: Learnings + Strategy Score Update."""
    print("[Paper Learning Engine] Start...")

    print("\n[1/3] Close Feedback Loop → trading_learnings.json")
    learnings = close_feedback_loop()

    print("\n[2/3] Update Strategy Scores → strategies.json")
    changes = update_strategy_scores()
    if changes:
        for c in changes:
            print(f"  → {c}")
    else:
        print("  Keine Score-Änderungen (zu wenig Daten oder Scores bereits aktuell)")

    print("\n[2b/3] Backtest-Validation (P1.6)")
    val = validate_backtest_vs_live()
    if val:
        downgraded = [s for s, v in val.items() if v.get('downgrade')]
        print(f"  ✅ Validiert: {len(val)} Strategien, {len(downgraded)} downgraded")
        for sid in downgraded[:5]:
            v = val[sid]
            print(f"     {sid}: bt={v['backtest_wr']:.0%} live={v['live_wr']:.0%} (gap {v['gap']:+.0%})")
    else:
        print("  ℹ️  Keine Backtest-Validation möglich")

    print("\n[3/3] Strategie-Übersicht:")
    for strat_id, s in sorted(learnings['strategy_scores'].items()):
        trades = s['trades']
        wr     = s['win_rate']
        rec    = s['recommendation']
        print(f"  {strat_id:10s} | {trades:3d} Trades | WR {wr:.0%} | {rec}")

    print("\n✅ Learning Engine fertig.")
    return learnings


if __name__ == '__main__':
    args = sys.argv[1:]

    if '--weekly-report' in args:
        print("[Paper Learning Engine] Erstelle Wöchentlichen Report...")
        # Immer auch Learnings aktualisieren
        close_feedback_loop()
        generate_weekly_report()
    elif '--update-scores' in args:
        print("[Paper Learning Engine] Update Strategy Scores...")
        changes = update_strategy_scores()
        for c in changes:
            print(f"  → {c}")
        if not changes:
            print("  Keine Änderungen.")
    else:
        run_all()
