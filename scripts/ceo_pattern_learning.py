#!/usr/bin/env python3
"""
ceo_pattern_learning.py — Phase 38: Empirische Pattern-Daten für CEO-Brain.

3 Funktionen:

1. find_similar_setup_history(strategy, ticker, conviction, vix_at_entry, sector, days=90)
   → Pattern-Match in historischen Trades. Gibt WR, avg_pnl, n_samples, top-3 outcomes.
   CEO sieht "ähnliche Setups (n=12) hatten WR 67%, avg +4.2%".

2. compute_strategy_hour_heatmap(days=60)
   → Per Strategy × Entry-Hour → WR + avg_pnl.
   Zeigt versteckte Edges (z.B. "PS_CCJ läuft Mi 17h besonders gut").
   Output: dict + Markdown-Table für Discord.

3. detect_anti_patterns(min_occurrences=3, min_loss_rate=0.7, days=120)
   → Scannt closed trades nach Pattern (rsi_bucket, vix_bucket, hour, sector)
     mit hoher Loss-Rate. Schreibt data/ceo_anti_patterns.json.
   CEO-Brain liest und VERMEIDET diese Patterns automatisch.

CLI:
  python3 scripts/ceo_pattern_learning.py heatmap
  python3 scripts/ceo_pattern_learning.py patterns
  python3 scripts/ceo_pattern_learning.py similar PS_CCJ CCJ
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
ANTI_PATTERNS_FILE = WS / 'data' / 'ceo_anti_patterns.json'


# ═══════════════════════════════════════════════════════════════════════════
# 1. find_similar_setup_history
# ═══════════════════════════════════════════════════════════════════════════

def _bucket_rsi(rsi: float | None) -> str:
    if rsi is None: return 'unk'
    if rsi < 30: return '<30'
    if rsi < 50: return '30-50'
    if rsi < 70: return '50-70'
    if rsi < 80: return '70-80'
    return '>80'

def _bucket_vix(vix: float | None) -> str:
    if vix is None: return 'unk'
    if vix < 15: return '<15'
    if vix < 20: return '15-20'
    if vix < 25: return '20-25'
    return '>25'

def _bucket_conviction(c: int | None) -> str:
    if c is None: return 'unk'
    if c < 40: return '<40'
    if c < 60: return '40-60'
    if c < 75: return '60-75'
    return '>75'


def find_similar_setup_history(
    strategy: str,
    ticker: str,
    conviction: int | None = None,
    vix_at_entry: float | None = None,
    sector: str | None = None,
    days: int = 90,
) -> dict:
    """Pattern-Match in closed Trades. Returns dict mit Stats für CEO-Decision."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        # Match-Kriterien (gestufte Suche: strict → fuzzy)
        # 1) Selbe strategy + ticker
        rows_exact = c.execute("""
            SELECT pnl_eur, pnl_pct, exit_type FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND strategy = ? AND ticker = ?
              AND COALESCE(close_date, entry_date) >= ?
        """, (strategy, ticker, cutoff)).fetchall()

        # 2) Selbe strategy (anderer ticker)
        rows_strat = c.execute("""
            SELECT pnl_eur, pnl_pct, exit_type, ticker FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND strategy = ?
              AND COALESCE(close_date, entry_date) >= ?
        """, (strategy, cutoff)).fetchall()

        # 3) Selbes sector (sehr ungenau)
        rows_sector = []
        if sector:
            rows_sector = c.execute("""
                SELECT pnl_eur, pnl_pct, exit_type, strategy, ticker FROM paper_portfolio
                WHERE status IN ('WIN','LOSS','CLOSED')
                  AND sector = ?
                  AND COALESCE(close_date, entry_date) >= ?
            """, (sector, cutoff)).fetchall()
        c.close()
    except Exception as e:
        return {'error': str(e)[:200]}

    def _agg(rows, label):
        rows = [r for r in rows if r['pnl_eur'] is not None]
        if not rows:
            return {'label': label, 'n': 0}
        wins = sum(1 for r in rows if (r['pnl_eur'] or 0) > 0)
        return {
            'label': label,
            'n': len(rows),
            'win_rate': round(wins / len(rows) * 100, 1),
            'avg_pnl_eur': round(mean(r['pnl_eur'] for r in rows), 2),
            'avg_pnl_pct': round(mean(r['pnl_pct'] or 0 for r in rows), 2),
            'sum_pnl_eur': round(sum(r['pnl_eur'] for r in rows), 0),
            'top_3_outcomes': sorted([
                {'pnl_eur': r['pnl_eur'], 'pct': r['pnl_pct'], 'exit': r['exit_type']}
                for r in rows
            ], key=lambda x: x['pnl_eur'], reverse=True)[:3],
        }

    return {
        'strategy': strategy,
        'ticker': ticker,
        'window_days': days,
        'context': {
            'conviction_bucket': _bucket_conviction(conviction),
            'vix_bucket': _bucket_vix(vix_at_entry),
            'sector': sector,
        },
        'exact_match': _agg(rows_exact, f'{strategy}+{ticker}'),
        'strategy_match': _agg(rows_strat, f'{strategy} (any ticker)'),
        'sector_match': _agg(rows_sector, f'sector={sector}') if sector else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. Strategy × Hour Heatmap
# ═══════════════════════════════════════════════════════════════════════════

def compute_strategy_hour_heatmap(days: int = 60) -> dict:
    """Per Strategy × hour_of_entry: WR + avg_pnl + n_trades."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT strategy, entry_date, pnl_eur, pnl_pct
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND COALESCE(close_date, entry_date) >= ?
              AND entry_date IS NOT NULL
              AND pnl_eur IS NOT NULL
        """, (cutoff,)).fetchall()
        c.close()
    except Exception as e:
        return {'error': str(e)[:200]}

    # Bucket: per (strategy, hour)
    buckets: dict[tuple, list] = {}
    for r in rows:
        try:
            edt = str(r['entry_date'])[:19]
            dt = datetime.fromisoformat(edt)
            hour = dt.hour
            key = (r['strategy'], hour)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(r['pnl_eur'])
        except Exception:
            continue

    # Aggregate
    matrix = {}
    for (strat, hour), pnls in buckets.items():
        wins = sum(1 for p in pnls if p > 0)
        matrix.setdefault(strat, {})[hour] = {
            'n': len(pnls),
            'win_rate': round(wins / len(pnls) * 100, 1),
            'avg_pnl': round(mean(pnls), 2),
            'sum_pnl': round(sum(pnls), 0),
        }

    # Best hour per strategy
    best_hours = {}
    for strat, hours in matrix.items():
        # Min 2 Trades pro Bucket
        qualified = {h: d for h, d in hours.items() if d['n'] >= 2}
        if qualified:
            best = max(qualified.items(), key=lambda x: x[1]['avg_pnl'])
            worst = min(qualified.items(), key=lambda x: x[1]['avg_pnl'])
            best_hours[strat] = {'best_hour': best[0], 'best_avg_pnl': best[1]['avg_pnl'],
                                  'worst_hour': worst[0], 'worst_avg_pnl': worst[1]['avg_pnl']}

    return {
        'window_days': days,
        'matrix': {s: dict(sorted(h.items())) for s, h in matrix.items()},
        'best_hours': best_hours,
        'computed_at': datetime.now().isoformat(timespec='seconds'),
    }


def heatmap_to_markdown(heatmap: dict, top_n: int = 10) -> str:
    """Discord-tauglicher Markdown-Table."""
    matrix = heatmap.get('matrix', {})
    best_hours = heatmap.get('best_hours', {})
    if not matrix:
        return '_Keine Daten für Heatmap (zu wenig closed Trades)._'

    lines = [f"📊 **Strategy×Hour Heatmap** ({heatmap.get('window_days', 60)}d)"]
    lines.append('')
    lines.append("**Best/Worst Hours per Strategy** (min 2 trades/bucket):")

    # Sort by total trade-count
    strat_totals = {s: sum(d['n'] for d in h.values()) for s, h in matrix.items()}
    top_strats = sorted(strat_totals.items(), key=lambda x: -x[1])[:top_n]

    for strat, total_n in top_strats:
        bh = best_hours.get(strat, {})
        if bh:
            lines.append(
                f"  · `{strat:<22}` n={total_n:3d} | "
                f"best @ **{bh['best_hour']:02d}h** ({bh['best_avg_pnl']:+.0f}€) | "
                f"worst @ {bh['worst_hour']:02d}h ({bh['worst_avg_pnl']:+.0f}€)"
            )
        else:
            lines.append(f"  · `{strat:<22}` n={total_n} (zu wenig pro hour-bucket)")

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Anti-Pattern Detection
# ═══════════════════════════════════════════════════════════════════════════

def detect_anti_patterns(min_occurrences: int = 3, min_loss_rate: float = 0.7,
                           days: int = 120) -> dict:
    """Scannt closed Trades nach Patterns mit hoher Loss-Rate.
    Pattern-Dimensionen: (strategy, sector, hour_bucket, exit_type)."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT strategy, sector, ticker, entry_date, pnl_eur, pnl_pct, exit_type,
                   rsi_at_entry, vix_at_entry
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND COALESCE(close_date, entry_date) >= ?
              AND pnl_eur IS NOT NULL
        """, (cutoff,)).fetchall()
        c.close()
    except Exception as e:
        return {'error': str(e)[:200], 'patterns': []}

    # Bucket nach mehreren Dimensionen
    pattern_buckets: dict[str, list] = {}
    for r in rows:
        try:
            hour = datetime.fromisoformat(str(r['entry_date'])[:19]).hour
            hour_bucket = (
                'morning_06-11' if 6 <= hour < 12
                else 'afternoon_12-17' if 12 <= hour < 18
                else 'evening_18-22' if 18 <= hour < 22
                else 'night_22-06'
            )
        except Exception:
            hour_bucket = 'unk'

        rsi_b = _bucket_rsi(r['rsi_at_entry'])
        vix_b = _bucket_vix(r['vix_at_entry'])
        sector = r['sector'] or 'unk'
        strat = r['strategy'] or 'unk'

        # Pattern: 6 Dimensionen
        ticker_id = (r['ticker'] if 'ticker' in r.keys() else 'unk') if hasattr(r, 'keys') else 'unk'
        keys = [
            ('strategy_x_hour', f'{strat}|{hour_bucket}'),
            ('sector_x_vix',    f'{sector}|vix={vix_b}'),
            ('strategy_x_rsi',  f'{strat}|rsi={rsi_b}'),
            ('strategy_x_sector', f'{strat}|{sector}'),
            ('rsi_x_vix',       f'rsi={rsi_b}|vix={vix_b}'),
            # NEU Phase 38c: strategy×ticker — fängt "Strategy X läuft generell aber bei Ticker Y nicht"
            ('strategy_x_ticker', f'{strat}|{ticker_id}'),
        ]
        for ptype, pkey in keys:
            full_key = f'{ptype}::{pkey}'
            pattern_buckets.setdefault(full_key, []).append(r['pnl_eur'])

    # Filter: nur Patterns mit min_occurrences AND high loss-rate
    anti_patterns = []
    for full_key, pnls in pattern_buckets.items():
        # Phase 38c: strategy_x_ticker → niedrigere Schwelle (n>=2, loss>=100%)
        # weil hier ein 2/2-Verlust schon klares Signal ist
        if 'strategy_x_ticker' in full_key:
            min_n = 2
            min_lr = 1.0
        else:
            min_n = min_occurrences
            min_lr = min_loss_rate
        if len(pnls) < min_n:
            continue
        losses = sum(1 for p in pnls if p <= 0)
        loss_rate = losses / len(pnls)
        if loss_rate < min_lr:
            continue
        avg_pnl = mean(pnls)
        ptype, pkey = full_key.split('::', 1)
        anti_patterns.append({
            'pattern_type': ptype,
            'pattern_key': pkey,
            'n_occurrences': len(pnls),
            'loss_rate': round(loss_rate, 2),
            'avg_pnl_eur': round(avg_pnl, 2),
            'sum_pnl_eur': round(sum(pnls), 0),
            'severity': 'critical' if loss_rate >= 0.85 and len(pnls) >= 5 else 'warning',
        })

    # Sortiere nach worst (avg_pnl ascending)
    anti_patterns.sort(key=lambda x: x['avg_pnl_eur'])

    payload = {
        'computed_at': datetime.now().isoformat(timespec='seconds'),
        'window_days': days,
        'min_occurrences': min_occurrences,
        'min_loss_rate': min_loss_rate,
        'total_patterns_found': len(anti_patterns),
        'patterns': anti_patterns,
    }

    # Phase 38b: Diff vs vorheriger Detection (für Realtime-Alert bei NEUEN critical)
    previous_patterns = []
    if ANTI_PATTERNS_FILE.exists():
        try:
            old = json.loads(ANTI_PATTERNS_FILE.read_text(encoding='utf-8'))
            previous_patterns = old.get('patterns', [])
        except Exception:
            pass

    # Persist
    try:
        ANTI_PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ANTI_PATTERNS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                       encoding='utf-8')
    except Exception:
        pass

    # Phase 38b: Sofort-Alert bei NEUEN critical
    new_critical = detect_new_critical_patterns(previous_patterns=previous_patterns)
    if new_critical:
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from discord_dispatcher import send_alert, TIER_HIGH
            lines = [f'🚨 **{len(new_critical)} NEUE critical Anti-Pattern{"s" if len(new_critical)>1 else ""}!**']
            for ap in new_critical[:5]:
                lines.append(f"  · `{ap['pattern_type']}` `{ap['pattern_key']}` "
                             f"n={ap['n_occurrences']} loss-rate={ap['loss_rate']:.0%} "
                             f"avg {ap['avg_pnl_eur']:+.0f}€"
                             + (f' ({ap["_change"]})' if ap.get('_change') else ''))
            lines.append('\n_CEO-Brain wird diese Patterns ab nächstem Run automatisch enforcen._')
            send_alert('\n'.join(lines), tier=TIER_HIGH, category='anti_pattern_critical',
                       dedupe_key=f'apcrit_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception as e:
            print(f'[anti-pattern] alert error: {e}', file=sys.stderr)

    return payload


def load_anti_patterns() -> list[dict]:
    """Liest aktuelle Anti-Patterns für CEO-Brain Pre-Fetch."""
    if not ANTI_PATTERNS_FILE.exists():
        return []
    try:
        d = json.loads(ANTI_PATTERNS_FILE.read_text(encoding='utf-8'))
        return d.get('patterns', [])
    except Exception:
        return []


def check_proposal_against_patterns(proposal: dict, current_hour: int | None = None) -> list[dict]:
    """Returns Liste matchender Anti-Patterns für ein Proposal.
    Phase 38b: jetzt mit current_hour für strategy_x_hour-Match.
    CEO sollte EXECUTE blockieren wenn ≥1 critical match."""
    patterns = load_anti_patterns()
    if not patterns:
        return []

    matches = []
    strat = proposal.get('strategy', '')
    sector = proposal.get('sector', '') or 'unk'
    ticker = proposal.get('ticker', '')

    if current_hour is None:
        current_hour = datetime.now().hour
    cur_hour_bucket = (
        'morning_06-11' if 6 <= current_hour < 12
        else 'afternoon_12-17' if 12 <= current_hour < 18
        else 'evening_18-22' if 18 <= current_hour < 22
        else 'night_22-06'
    )

    for ap in patterns:
        ptype = ap.get('pattern_type', '')
        pkey = ap.get('pattern_key', '')

        if ptype == 'strategy_x_hour':
            expected_key = f'{strat}|{cur_hour_bucket}'
            if pkey == expected_key:
                matches.append({**ap, '_match_reason': f'now is {cur_hour_bucket}'})
        elif ptype == 'strategy_x_sector' and pkey == f'{strat}|{sector}':
            matches.append(ap)
        elif ptype == 'sector_x_vix' and pkey.startswith(sector + '|'):
            matches.append(ap)
        # Phase 38c: strategy_x_ticker — exakter Ticker+Strategy Match
        elif ptype == 'strategy_x_ticker' and ticker and pkey == f'{strat}|{ticker}':
            matches.append({**ap, '_match_reason': f'historical loss-pattern for {ticker}+{strat}'})

    return matches


def get_hour_multiplier(strategy: str, current_hour: int | None = None) -> dict:
    """Phase 38b: Position-Size-Multiplier basierend auf Strategy×Hour Heatmap.
    Best-Hour: 1.2x, Worst-Hour: 0.5x, Standard: 1.0x.
    Returns: {multiplier, reason, best_hour, worst_hour, current_avg_pnl}
    """
    if current_hour is None:
        current_hour = datetime.now().hour

    try:
        h = compute_strategy_hour_heatmap(days=60)
        matrix = h.get('matrix', {})
        best_hours = h.get('best_hours', {})
    except Exception:
        return {'multiplier': 1.0, 'reason': 'no_heatmap_data'}

    strat_data = matrix.get(strategy)
    if not strat_data:
        return {'multiplier': 1.0, 'reason': f'no_history_for_{strategy}'}

    bh = best_hours.get(strategy, {})
    best_hour = bh.get('best_hour')
    worst_hour = bh.get('worst_hour')
    current_data = strat_data.get(current_hour, strat_data.get(str(current_hour)))

    multiplier = 1.0
    reason = 'standard'

    # Aktuelle Stunde im Heatmap?
    if current_data and current_data.get('n', 0) >= 2:
        avg_pnl = current_data.get('avg_pnl', 0)
        if avg_pnl > 50:
            multiplier = 1.2
            reason = f'positive_hour ({avg_pnl:+.0f}€ avg, n={current_data["n"]})'
        elif avg_pnl < -20:
            multiplier = 0.5
            reason = f'losing_hour ({avg_pnl:+.0f}€ avg, n={current_data["n"]})'
    elif current_hour == best_hour:
        multiplier = 1.2
        reason = f'best_hour_for_{strategy}'
    elif current_hour == worst_hour:
        multiplier = 0.5
        reason = f'worst_hour_for_{strategy}'

    return {
        'multiplier': multiplier,
        'reason': reason,
        'current_hour': current_hour,
        'best_hour': best_hour,
        'worst_hour': worst_hour,
        'current_avg_pnl': current_data.get('avg_pnl') if current_data else None,
    }


def detect_new_critical_patterns(previous_patterns: list[dict] | None = None) -> list[dict]:
    """Phase 38b: Detection von NEUEN critical patterns seit letztem Run.
    Returns Liste die NEU oder schlimmer geworden sind."""
    current = load_anti_patterns()
    new_critical = []

    if previous_patterns is None:
        # Default: erste Run, alle critical sind 'neu' im Sinne "bis jetzt unbekannt"
        return [p for p in current if p.get('severity') == 'critical']

    prev_keys = {f"{p['pattern_type']}::{p['pattern_key']}" for p in previous_patterns}
    for p in current:
        if p.get('severity') != 'critical':
            continue
        key = f"{p['pattern_type']}::{p['pattern_key']}"
        if key not in prev_keys:
            new_critical.append(p)
        else:
            # Schon bekannt — schauen ob worse geworden
            old = next((x for x in previous_patterns
                        if f"{x['pattern_type']}::{x['pattern_key']}" == key), None)
            if old and p['n_occurrences'] > old.get('n_occurrences', 0):
                p['_change'] = f'worsened: n {old["n_occurrences"]} → {p["n_occurrences"]}'
                new_critical.append(p)

    return new_critical


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: heatmap | patterns | similar <strategy> <ticker>')
        return 1

    cmd = sys.argv[1]

    if cmd == 'heatmap':
        h = compute_strategy_hour_heatmap(days=60)
        print(heatmap_to_markdown(h))
        print('\n=== RAW ===')
        print(json.dumps(h, indent=2, ensure_ascii=False)[:3000])
        return 0

    if cmd == 'patterns':
        p = detect_anti_patterns()
        print(f'Found {p["total_patterns_found"]} anti-patterns')
        for ap in p['patterns'][:20]:
            print(f"  [{ap['severity']:<8}] {ap['pattern_type']:<22} {ap['pattern_key']:<30} "
                  f"n={ap['n_occurrences']:2d} loss_rate={ap['loss_rate']:.0%} "
                  f"avg_pnl={ap['avg_pnl_eur']:+.0f}€")
        return 0

    if cmd == 'similar' and len(sys.argv) >= 4:
        result = find_similar_setup_history(
            strategy=sys.argv[2], ticker=sys.argv[3],
            sector=sys.argv[4] if len(sys.argv) > 4 else None,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f'Unknown cmd: {cmd}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
