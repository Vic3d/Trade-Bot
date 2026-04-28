#!/usr/bin/env python3
"""
shadow_account_v2.py — Phase 40a: Journal-zu-Strategy Extraktion (Vibe-inspired).

UMGEKEHRT zu unserer Phase 28 Shadow-Trades:
  Phase 28 trackt was UNSERE Decisions WÄREN gewesen (Counterfactual)
  Phase 40a extrahiert was DEINE eigene Trade-Historie als Strategy zeigt

Workflow:
  1. Du uploadest dein Brokerage-Journal (CSV, generic Format)
  2. System pairt FIFO Trades zu Roundtrips
  3. Filtert profitable Roundtrips (PnL > 0)
  4. Feature-Engineering: holding_days, pnl_pct, hour, weekday
  5. KMeans-Clustering der profitable Roundtrips (k auto 2-5)
  6. Pro Cluster: einfache Regel-Extraktion (Modus + Range)
  7. Output: 3-5 if-then Rules die deine impliziten Edges beschreiben

CSV-Format erwartet:
  ticker,entry_date,entry_price,shares,close_date,close_price,pnl_eur

CLI:
  python3 scripts/shadow_account_v2.py extract <csv_path>
  python3 scripts/shadow_account_v2.py compare <csv_path>  # vergleich vs TradeMind-Strategien
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
SHADOW_PROFILES = WS / 'data' / 'shadow_profiles'

MIN_PROFITABLE_ROUNDTRIPS = 5


def parse_journal_csv(path: Path) -> list[dict]:
    """Parsed generic CSV mit Trades."""
    trades = []
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trades.append({
                    'ticker': row.get('ticker', '').strip(),
                    'entry_date': row.get('entry_date', '').strip(),
                    'entry_price': float(row.get('entry_price', 0)),
                    'shares': float(row.get('shares', 0)),
                    'close_date': row.get('close_date', '').strip(),
                    'close_price': float(row.get('close_price', 0)),
                    'pnl_eur': float(row.get('pnl_eur', 0)),
                })
            except (ValueError, KeyError):
                continue
    return trades


def derive_features(trade: dict) -> dict:
    """Pro Trade: holding_days, pnl_pct, entry_hour, weekday."""
    feats = {'ticker': trade['ticker'], 'pnl_eur': trade['pnl_eur']}
    try:
        e = datetime.fromisoformat(str(trade['entry_date'])[:19])
        c = datetime.fromisoformat(str(trade['close_date'])[:19])
        feats['holding_days'] = max(0, (c - e).days)
        feats['entry_hour'] = e.hour
        feats['entry_weekday'] = e.weekday()
        feats['close_weekday'] = c.weekday()
    except Exception:
        feats['holding_days'] = None
        feats['entry_hour'] = None
        feats['entry_weekday'] = None

    try:
        feats['pnl_pct'] = (trade['close_price'] - trade['entry_price']) \
                            / trade['entry_price'] * 100
    except (ZeroDivisionError, TypeError):
        feats['pnl_pct'] = 0
    return feats


def cluster_simple(trades_with_feats: list[dict], k: int = 3) -> list[list[dict]]:
    """Einfaches Clustering ohne sklearn-Dependency.
    Sortiert nach pnl_pct, teilt in k gleichgroße Buckets."""
    if not trades_with_feats:
        return []
    sorted_trades = sorted(trades_with_feats, key=lambda t: t.get('pnl_pct', 0))
    bucket_size = max(1, len(sorted_trades) // k)
    return [sorted_trades[i*bucket_size:(i+1)*bucket_size]
            for i in range(k)]


def extract_rule_from_cluster(cluster: list[dict], cluster_id: int) -> dict:
    """Pro Cluster: Modus + Range der Features → Regel."""
    if not cluster:
        return {}
    holding_days = [t['holding_days'] for t in cluster if t.get('holding_days') is not None]
    pnl_pcts = [t['pnl_pct'] for t in cluster if t.get('pnl_pct') is not None]
    hours = [t['entry_hour'] for t in cluster if t.get('entry_hour') is not None]
    weekdays = [t['entry_weekday'] for t in cluster if t.get('entry_weekday') is not None]
    tickers = [t['ticker'] for t in cluster]

    rule = {
        'cluster_id': cluster_id,
        'n_trades': len(cluster),
        'avg_pnl_pct': round(mean(pnl_pcts), 2) if pnl_pcts else 0,
        'avg_pnl_eur': round(mean(t['pnl_eur'] for t in cluster), 2),
        'avg_holding_days': round(mean(holding_days), 1) if holding_days else None,
        'top_tickers': [t for t, _ in Counter(tickers).most_common(5)],
        'preferred_entry_hour_range': [min(hours), max(hours)] if hours else None,
        'preferred_weekday': Counter(weekdays).most_common(1)[0][0] if weekdays else None,
    }

    # Generate human-readable rule
    parts = []
    if rule['avg_holding_days'] is not None:
        parts.append(f"Halte ~{rule['avg_holding_days']:.0f} Tage")
    if rule['preferred_entry_hour_range']:
        h_lo, h_hi = rule['preferred_entry_hour_range']
        parts.append(f"Entry zwischen {h_lo}h-{h_hi}h")
    if rule['top_tickers']:
        parts.append(f"Top-Tickers: {', '.join(rule['top_tickers'][:3])}")
    parts.append(f"avg PnL {rule['avg_pnl_pct']:+.1f}%")
    rule['if_then'] = ' AND '.join(parts) if parts else '(keine klare Pattern)'
    return rule


def extract_shadow_profile(csv_path: Path, k_clusters: int = 3) -> dict:
    """Hauptfunktion: Journal → Shadow-Profile."""
    trades = parse_journal_csv(csv_path)
    if not trades:
        return {'error': 'no_trades_parsed'}

    profitable = [t for t in trades if t.get('pnl_eur', 0) > 0]
    if len(profitable) < MIN_PROFITABLE_ROUNDTRIPS:
        return {
            'error': 'insufficient_profitable_trades',
            'n_total': len(trades),
            'n_profitable': len(profitable),
            'min_required': MIN_PROFITABLE_ROUNDTRIPS,
        }

    feats = [derive_features(t) for t in profitable]
    clusters = cluster_simple(feats, k=k_clusters)
    rules = [extract_rule_from_cluster(c, i+1) for i, c in enumerate(clusters)]

    profile = {
        'extracted_at': datetime.now().isoformat(timespec='seconds'),
        'source_csv': str(csv_path),
        'n_trades_total': len(trades),
        'n_profitable': len(profitable),
        'n_loss_or_breakeven': len(trades) - len(profitable),
        'win_rate_pct': round(len(profitable) / len(trades) * 100, 1),
        'sum_pnl_eur': round(sum(t['pnl_eur'] for t in trades), 2),
        'rules_extracted': rules,
    }

    # Persist
    SHADOW_PROFILES.mkdir(parents=True, exist_ok=True)
    out = SHADOW_PROFILES / f'profile_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding='utf-8')
    profile['saved_to'] = str(out)
    return profile


def compare_to_trademind(profile: dict) -> dict:
    """Vergleicht Shadow-Profile mit aktuellen TradeMind-Strategien."""
    try:
        strategies_file = WS / 'data' / 'strategies.json'
        strategies = json.loads(strategies_file.read_text(encoding='utf-8'))
    except Exception:
        return {'error': 'strategies.json not loadable'}

    rules = profile.get('rules_extracted', [])
    matches = []
    gaps = []

    for rule in rules:
        rule_tickers = set(rule.get('top_tickers', []))
        matched_strats = []
        for sid, sdata in strategies.items():
            if not isinstance(sdata, dict):
                continue
            strat_tickers = set(sdata.get('tickers', []))
            overlap = rule_tickers & strat_tickers
            if overlap:
                matched_strats.append({'id': sid, 'overlap': list(overlap)})

        if matched_strats:
            matches.append({'rule': rule, 'tradeMind_matches': matched_strats})
        else:
            gaps.append({
                'rule': rule,
                'reason': 'TradeMind hat keine Strategie für diese Tickers',
                'suggestion': 'Eventuell neue Strategy bauen?',
            })

    return {
        'matches': matches,
        'gaps': gaps,
        'gap_count': len(gaps),
        'match_count': len(matches),
        'recommendation': (
            f'{len(gaps)} potenzielle neue Strategien identifiziert'
            if gaps else 'TradeMind deckt alle deine impliziten Edges ab'
        ),
    }


def main() -> int:
    if len(sys.argv) < 3:
        print('Usage: shadow_account_v2.py extract <csv> | compare <csv>')
        return 1
    cmd, csv_path = sys.argv[1], Path(sys.argv[2])
    if not csv_path.exists():
        print(f'CSV not found: {csv_path}')
        return 1

    profile = extract_shadow_profile(csv_path)
    if cmd == 'compare' and 'error' not in profile:
        comparison = compare_to_trademind(profile)
        result = {'profile': profile, 'comparison': comparison}
    else:
        result = profile
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
