#!/usr/bin/env python3
"""
ceo_self_reflection.py — Phase 43 Pillar C: Self-Reflection des CEO.

Frage: Hat Albert die letzten 30 Tage zu vorsichtig gewatcht?
Was hat ihn das gekostet?

Loop:
  1. Sammle alle WATCH-Decisions der letzten 30d aus ceo_decisions.jsonl
  2. Für jede: was wäre passiert wenn er EXECUTE'd hätte?
     (resolve via paper_portfolio: Trade hat tatsächlich stattgefunden später?
      Oder Backtesting: Preis-Bewegung seit Watch-Decision)
  3. Aggregiere: missed_eur, false_watches_pct, avoided_losses_eur
  4. Schreibt insights nach data/ceo_self_reflection.json
  5. Wenn missed_eur > 200€: Alert + Confidence-Schwelle automatisch tunen

Output (data/ceo_self_reflection.json):
  {
    "ts": "...",
    "window_days": 30,
    "n_watches": 45,
    "n_validatable": 23,        // wo wir post-Watch-Preise haben
    "missed_wins_eur": 850,     // hätte ich EXECUTE'd, hätte ich gewonnen
    "avoided_losses_eur": 320,  // gut dass ich WATCH'd
    "net_bias_cost_eur": 530,   // missed - avoided
    "false_watch_pct": 65,      // % der Watches die ein Win waren
    "recommendation": "lower confidence threshold by 0.05"
  }

Run:
  python3 scripts/ceo_self_reflection.py [--days 30]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
DECISIONS_LOG   = WS / 'data' / 'ceo_decisions.jsonl'
REFLECTION_FILE = WS / 'data' / 'ceo_self_reflection.json'


def load_watch_decisions(days: int = 30) -> list[dict]:
    """Lese alle WATCH-Decisions aus ceo_decisions.jsonl letzte N Tage."""
    if not DECISIONS_LOG.exists():
        return []
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    watches = []
    try:
        with open(DECISIONS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('event') != 'watch':
                    continue
                if (d.get('ts') or '') < cutoff:
                    continue
                watches.append(d)
    except Exception as e:
        print(f'[reflection] read err: {e}', file=sys.stderr)
    return watches


def estimate_outcome(watch: dict) -> dict | None:
    """Schätze was passiert wäre wenn EXECUTE statt WATCH.

    Methoden in Reihenfolge:
      1. Wurde der Trade später wirklich gemacht (paper_portfolio)? → real outcome
      2. Sonst: Preis-Bewegung von watch_ts bis +7d (typische PS_-Haltezeit)
         aus prices-Tabelle
    """
    ticker = watch.get('ticker')
    strategy = watch.get('strategy')
    entry_price = float(watch.get('entry') or 0)
    stop_price = float(watch.get('stop') or 0)
    target_price = float(watch.get('target') or 0)
    watch_ts = watch.get('ts', '')
    if not ticker or not entry_price:
        return None

    c = sqlite3.connect(str(DB))

    # 1. Echter Trade nach watch_ts?
    try:
        row = c.execute(
            "SELECT pnl_eur, pnl_pct, status, close_date "
            "FROM paper_portfolio WHERE ticker=? AND strategy=? "
            "AND status IN ('CLOSED','WIN','LOSS') "
            "AND entry_date >= ? "
            "ORDER BY entry_date ASC LIMIT 1",
            (ticker, strategy, watch_ts[:10]),
        ).fetchone()
        if row:
            c.close()
            return {'method': 'real_trade', 'pnl_eur': float(row[0] or 0),
                    'pnl_pct': float(row[1] or 0), 'status': row[2],
                    'close_date': row[3]}
    except Exception:
        pass

    # 2. Preis-Bewegung simulieren von watch_ts +7d
    try:
        watch_date = watch_ts[:10]
        end_date = (datetime.fromisoformat(watch_ts.replace('Z', '')[:19])
                     + timedelta(days=7)).strftime('%Y-%m-%d')
        prices = c.execute(
            "SELECT date, high, low, close FROM prices "
            "WHERE ticker=? AND date >= ? AND date <= ? "
            "ORDER BY date ASC",
            (ticker, watch_date, end_date),
        ).fetchall()
        c.close()
        if not prices or len(prices) < 2:
            return None
        # Simuliere Trade: Stop-hit oder Target-hit oder Close nach 7d
        for date, high, low, close in prices[1:]:  # ab nächstem Tag
            if stop_price and float(low) <= stop_price:
                pnl_pct = ((stop_price - entry_price) / entry_price) * 100
                return {'method': 'simulated', 'pnl_pct': round(pnl_pct, 2),
                        'pnl_eur': round(pnl_pct * 10, 0),  # ~1000€ Position
                        'status': 'STOP_HIT', 'close_date': date}
            if target_price and float(high) >= target_price:
                pnl_pct = ((target_price - entry_price) / entry_price) * 100
                return {'method': 'simulated', 'pnl_pct': round(pnl_pct, 2),
                        'pnl_eur': round(pnl_pct * 10, 0),
                        'status': 'TARGET_HIT', 'close_date': date}
        # Time-Exit: letzter Close
        last_close = float(prices[-1][3])
        pnl_pct = ((last_close - entry_price) / entry_price) * 100
        return {'method': 'simulated_time_exit',
                'pnl_pct': round(pnl_pct, 2),
                'pnl_eur': round(pnl_pct * 10, 0),
                'status': 'WIN' if pnl_pct > 0 else 'LOSS',
                'close_date': prices[-1][0]}
    except Exception as e:
        print(f'[reflection] sim err {ticker}: {e}', file=sys.stderr)
        return None
    finally:
        try: c.close()
        except Exception: pass


def reflect(days: int = 30) -> dict:
    """Führe Self-Reflection durch."""
    watches = load_watch_decisions(days=days)
    print(f'[reflection] {len(watches)} watch-decisions in last {days}d', file=sys.stderr)

    n_validatable = 0
    missed_wins_eur = 0.0
    avoided_losses_eur = 0.0
    by_strategy = {}
    high_conf_misses = []  # WATCH mit conf>=0.55 die WIN waren

    for w in watches:
        outcome = estimate_outcome(w)
        if not outcome:
            continue
        n_validatable += 1
        pnl = outcome['pnl_eur']
        strat = w.get('strategy', '?')
        by_strategy.setdefault(strat, {'n': 0, 'pnl_total': 0.0, 'wins': 0})
        by_strategy[strat]['n'] += 1
        by_strategy[strat]['pnl_total'] += pnl
        if pnl > 0:
            missed_wins_eur += pnl
            by_strategy[strat]['wins'] += 1
            conf = float(w.get('confidence') or w.get('_raw_confidence') or 0)
            if conf >= 0.55:
                high_conf_misses.append({
                    'ticker': w.get('ticker'),
                    'strategy': strat,
                    'confidence': conf,
                    'estimated_pnl_eur': pnl,
                    'reason': str(w.get('reason', ''))[:120],
                    'watch_ts': w.get('ts', '')[:16],
                })
        else:
            avoided_losses_eur += abs(pnl)

    n_wins = sum(1 for w in watches if (estimate_outcome(w) or {}).get('pnl_eur', 0) > 0)
    false_watch_pct = round(n_wins / max(1, n_validatable) * 100, 1)
    net_bias_cost = round(missed_wins_eur - avoided_losses_eur, 0)

    # Recommendation
    if net_bias_cost > 200:
        recommendation = (
            f'CEO ist zu vorsichtig. Net-Bias-Kosten: {net_bias_cost:+.0f}€ '
            f'in {days}d. Empfehlung: confidence-Schwelle senken oder '
            f'Macro-Boost erhöhen. {len(high_conf_misses)} High-Conf-Watches '
            f'(>=0.55) wurden zu Wins.'
        )
    elif net_bias_cost < -200:
        recommendation = (
            f'CEO ist zu aggressiv (würde EXECUTE-Phase mehr Verluste bringen). '
            f'Net-Bias-Bonus: {-net_bias_cost:.0f}€ vermieden. '
            f'WATCH-Verhalten okay.'
        )
    else:
        recommendation = f'Net-Bias neutral ({net_bias_cost:+.0f}€). Keine Tuning-Aktion nötig.'

    result = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'window_days': days,
        'n_watches': len(watches),
        'n_validatable': n_validatable,
        'missed_wins_eur': round(missed_wins_eur, 0),
        'avoided_losses_eur': round(avoided_losses_eur, 0),
        'net_bias_cost_eur': net_bias_cost,
        'false_watch_pct': false_watch_pct,
        'recommendation': recommendation,
        'by_strategy': by_strategy,
        'high_confidence_misses_top10': sorted(
            high_conf_misses, key=lambda x: x['estimated_pnl_eur'], reverse=True
        )[:10],
    }

    REFLECTION_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                encoding='utf-8')
    return result


def get_latest_insights() -> dict | None:
    """Lese letzte Reflection (für decide_llm prompt-injection)."""
    if not REFLECTION_FILE.exists():
        return None
    try:
        return json.loads(REFLECTION_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    args = ap.parse_args()

    print(f'═══ CEO Self-Reflection (last {args.days}d) ═══')
    r = reflect(days=args.days)
    print()
    print(f'Watches:           {r["n_watches"]}')
    print(f'Validatable:       {r["n_validatable"]}')
    print(f'Missed Wins:       +{r["missed_wins_eur"]:.0f}€')
    print(f'Avoided Losses:    -{r["avoided_losses_eur"]:.0f}€')
    print(f'NET BIAS COST:     {r["net_bias_cost_eur"]:+.0f}€')
    print(f'False-Watch-Pct:   {r["false_watch_pct"]}%')
    print()
    print(f'Recommendation: {r["recommendation"]}')
    if r['high_confidence_misses_top10']:
        print()
        print('Top High-Confidence-Misses (conf >= 0.55, war ein Win):')
        for m in r['high_confidence_misses_top10']:
            print(f'  · {m["ticker"]:<8} {m["strategy"]:<10} conf={m["confidence"]:.2f} '
                  f'→ +{m["estimated_pnl_eur"]:.0f}€ ({m["watch_ts"]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
