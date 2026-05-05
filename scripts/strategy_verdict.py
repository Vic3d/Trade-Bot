#!/usr/bin/env python3
"""
strategy_verdict.py — Single Source of Truth for strategy status.

Problem (Victor 2026-05-05):
  Wir haben 4 Quellen die unabhaengig urteilen koennen ob eine Strategie
  funktioniert. Wenn sie widersprechen, koennen LLM-Calls (Albert) und
  CLI-Claude unterschiedliche Aussagen machen — das war bei PS5 der Fall.

  Quellen:
    1. data/strategies.json          → status (active/watching/retired)
    2. data/trading_learnings.json   → recommendation + WR + PnL (organisch)
    3. data/backtest_v2_results.json → backtest by_strategy (synthetisch)
    4. data/quant_metrics.json       → per_strategy mission-verdict (Sharpe etc.)

Loesung:
  EINE Funktion strategy_verdict(sid) die alle 4 Quellen liest, ein
  konsolidiertes Verdict ausgibt UND Konflikte zwischen den Quellen
  explizit aufzeigt.

  Verwendet von:
    - current_truth.py (Auto-Inject in alle LLM-Prompts)
    - daily_digest.py
    - ceo_active_hunter.py
    - CLI fuer Adhoc-Queries

Verdict-Klassen:
  STRONG_EDGE     — alle Quellen positiv, klares Greenlight
  OK              — Mehrheit positiv, kein Veto
  INSUFFICIENT    — n zu klein um zu urteilen
  CONFLICT        — Quellen widersprechen sich → manueller Review
  WEAK            — Mehrheit negativ, aber nicht schlimm
  NEGATIVE        — alle Quellen negativ, Retire-Empfehlung
  RETIRED         — strategies.json sagt explizit retired/paused

CLI:
  python3 scripts/strategy_verdict.py PS5
  python3 scripts/strategy_verdict.py --all
"""
from __future__ import annotations
import json, os, sqlite3, sys
from pathlib import Path
from typing import Any

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
STRATEGIES = WS / 'data' / 'strategies.json'
LEARNINGS  = WS / 'data' / 'trading_learnings.json'
BACKTEST   = WS / 'data' / 'backtest_v2_results.json'
QUANT      = WS / 'data' / 'quant_metrics.json'
LOG        = WS / 'data' / 'strategy_verdict_conflicts.jsonl'


# ─────────────────────────────────────────────────────────────────────────
# Single source readers (each returns dict or None — never throws)
# ─────────────────────────────────────────────────────────────────────────

def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
    except Exception:
        return None


def _src_strategies(sid: str) -> dict | None:
    """strategies.json — authoritative status."""
    s = _read_json(STRATEGIES)
    if not isinstance(s, dict):
        return None
    v = s.get(sid)
    if not isinstance(v, dict):
        return None
    return {
        'status': v.get('status'),  # active|watching|retired|paused
        'thesis': (v.get('thesis') or '')[:140],
        'sector': v.get('sector'),
    }


def _src_learnings(sid: str) -> dict | None:
    """trading_learnings.json strategy_scores — organische Performance."""
    l = _read_json(LEARNINGS)
    if not isinstance(l, dict):
        return None
    s = (l.get('strategy_scores') or {}).get(sid)
    if not isinstance(s, dict):
        return None
    return {
        'n_trades': s.get('trades'),
        'win_rate': s.get('win_rate'),
        'total_pnl_eur': s.get('total_pnl_eur'),
        'risk_adj_return': s.get('risk_adj_return'),
        'recommendation': s.get('recommendation'),
    }


def _src_backtest(sid: str) -> dict | None:
    """backtest_v2_results.json by_strategy."""
    b = _read_json(BACKTEST)
    if not isinstance(b, dict):
        return None
    bs = (b.get('by_strategy') or {}).get(sid)
    if not isinstance(bs, dict):
        return None
    return {
        'n_trades': bs.get('n_trades') or bs.get('trades'),
        'sharpe': bs.get('sharpe'),
        'win_rate': bs.get('win_rate') or bs.get('wr'),
        'total_return': bs.get('total_return') or bs.get('total_pnl'),
        'verdict': bs.get('verdict'),
    }


def _src_quant(sid: str) -> dict | None:
    """quant_metrics.json per_strategy — Sprint 0 Quant-Layer."""
    q = _read_json(QUANT)
    if not isinstance(q, dict):
        return None
    ps = (q.get('per_strategy') or {}).get(sid)
    if not isinstance(ps, dict):
        return None
    return {
        'sharpe_30d': ps.get('sharpe_30d'),
        'sharpe_90d': ps.get('sharpe_90d'),
        'sharpe_all': ps.get('sharpe_all') or ps.get('sharpe_lifetime'),
        'mission_verdict': ps.get('mission_verdict'),
        'edge_verdict': ps.get('edge_verdict') or ps.get('verdict'),
    }


# ─────────────────────────────────────────────────────────────────────────
# Verdict consolidation
# ─────────────────────────────────────────────────────────────────────────

POSITIVE_TAGS = {'STRONG_EDGE', 'MODERATE', 'GOOD', 'MISSION_TARGET_MET',
                 'OK', 'ELEVATE', 'POSITIVE'}
NEGATIVE_TAGS = {'NEGATIVE_EDGE', 'NEGATIVE', 'POOR', 'WEAK', 'SUSPEND',
                 'REDUCE', 'RETIRE'}


def _bucket(value: str | None) -> str:
    """Klassifiziert eine Verdict-String in pos/neg/neutral/none."""
    if not value:
        return 'none'
    v = str(value).upper()
    if v in POSITIVE_TAGS:
        return 'pos'
    if v in NEGATIVE_TAGS:
        return 'neg'
    if 'INSUFFICIENT' in v or 'NO_DATA' in v:
        return 'insufficient'
    return 'neutral'


def strategy_verdict(sid: str) -> dict:
    """
    Konsolidiertes Verdict ueber alle 4 Quellen.

    Returns dict mit:
      sid, verdict, confidence, sources, conflicts, recommendation

    verdict ∈ {STRONG_EDGE, OK, INSUFFICIENT, CONFLICT, WEAK, NEGATIVE, RETIRED, UNKNOWN}
    """
    sid = (sid or '').upper()
    sources = {
        'strategies': _src_strategies(sid),
        'learnings':  _src_learnings(sid),
        'backtest':   _src_backtest(sid),
        'quant':      _src_quant(sid),
    }

    # 1. RETIRED / PAUSED short-circuit (strategies.json wins)
    st = sources['strategies']
    if st and st.get('status') in ('retired', 'paused'):
        return {
            'sid': sid,
            'verdict': 'RETIRED',
            'confidence': 'high',
            'sources': sources,
            'conflicts': [],
            'recommendation': f"Strategie ist {st.get('status')} — keine neuen Entries.",
        }

    if not st:
        return {
            'sid': sid,
            'verdict': 'UNKNOWN',
            'confidence': 'high',
            'sources': sources,
            'conflicts': [],
            'recommendation': 'Strategie existiert nicht in strategies.json.',
        }

    # 2. Sammle Buckets aus den 3 Performance-Quellen
    perf_buckets = []
    if sources['learnings']:
        perf_buckets.append(('learnings', _bucket(sources['learnings'].get('recommendation'))))
    if sources['backtest']:
        perf_buckets.append(('backtest', _bucket(sources['backtest'].get('verdict'))))
    if sources['quant']:
        perf_buckets.append(('quant', _bucket(
            sources['quant'].get('edge_verdict') or sources['quant'].get('mission_verdict'))))

    pos = [n for n, b in perf_buckets if b == 'pos']
    neg = [n for n, b in perf_buckets if b == 'neg']
    insuf = [n for n, b in perf_buckets if b == 'insufficient']
    have_data = pos + neg + [n for n, b in perf_buckets if b == 'neutral']

    conflicts = []
    if pos and neg:
        conflicts.append(f'positiv: {pos} vs negativ: {neg}')

    # 3. Verdict ableiten
    if not have_data and not insuf:
        verdict = 'INSUFFICIENT'
        confidence = 'low'
        rec = 'Keine Performance-Daten in irgendeiner Quelle. Mehr Trades sammeln.'
    elif insuf and not pos and not neg:
        verdict = 'INSUFFICIENT'
        confidence = 'medium'
        rec = f'Quellen {insuf} sagen INSUFFICIENT_DATA — n zu klein. Weiter handeln, beobachten.'
    elif pos and neg:
        verdict = 'CONFLICT'
        confidence = 'low'
        rec = (f'Quellen widersprechen sich ({pos} vs {neg}). '
               f'Manueller Review noetig. Default: Status quo halten.')
    elif len(neg) >= 2:
        verdict = 'NEGATIVE'
        confidence = 'high'
        rec = f'{len(neg)} Quellen sagen negativ. Retire-Kandidat.'
    elif neg:
        verdict = 'WEAK'
        confidence = 'medium'
        rec = f'{neg[0]} sagt negativ, andere neutral. Position-Size reduzieren.'
    elif len(pos) >= 2:
        verdict = 'STRONG_EDGE'
        confidence = 'high'
        rec = f'{len(pos)} Quellen positiv. Voll handelbar.'
    elif pos:
        verdict = 'OK'
        confidence = 'medium'
        rec = f'{pos[0]} positiv, andere neutral. Normal handelbar.'
    else:
        verdict = 'OK'
        confidence = 'low'
        rec = 'Keine starken Signale, neutral. Default: handeln.'

    # 4. Konflikt-Logging fuer spaetere Audit
    if conflicts:
        try:
            from datetime import datetime, timezone
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'sid': sid,
                    'verdict': verdict,
                    'conflicts': conflicts,
                    'sources': {k: v for k, v in sources.items() if v},
                }, default=str) + '\n')
        except Exception:
            pass

    return {
        'sid': sid,
        'verdict': verdict,
        'confidence': confidence,
        'sources': sources,
        'conflicts': conflicts,
        'recommendation': rec,
    }


def all_verdicts() -> list[dict]:
    """Liefert Verdict fuer ALLE Strategien aus strategies.json."""
    s = _read_json(STRATEGIES)
    if not isinstance(s, dict):
        return []
    return [strategy_verdict(sid) for sid in sorted(s.keys()) if isinstance(s.get(sid), dict)]


def format_verdict(v: dict, verbose: bool = False) -> str:
    """Compact eine Verdict-Zeile fuer Dashboard / current_truth."""
    icons = {
        'STRONG_EDGE': '✓✓', 'OK': '✓', 'INSUFFICIENT': '?',
        'CONFLICT': '!?', 'WEAK': '~', 'NEGATIVE': '✗',
        'RETIRED': '■', 'UNKNOWN': '?',
    }
    icon = icons.get(v['verdict'], '·')
    line = f"  {icon} {v['sid']:14s} {v['verdict']:12s} ({v['confidence']:6s})  {v['recommendation']}"
    if verbose and v.get('conflicts'):
        line += f"\n     CONFLICT: {'; '.join(v['conflicts'])}"
    return line


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: strategy_verdict.py <SID>|--all|--conflicts", file=sys.stderr)
        return 2

    if args[0] == '--all':
        verdicts = all_verdicts()
        # Gruppieren nach Verdict-Klasse
        buckets: dict[str, list[dict]] = {}
        for v in verdicts:
            buckets.setdefault(v['verdict'], []).append(v)
        order = ['STRONG_EDGE', 'OK', 'INSUFFICIENT', 'CONFLICT', 'WEAK',
                 'NEGATIVE', 'RETIRED', 'UNKNOWN']
        for k in order:
            if k not in buckets:
                continue
            print(f"\n=== {k} ({len(buckets[k])}) ===")
            for v in buckets[k]:
                print(format_verdict(v))
        return 0

    if args[0] == '--conflicts':
        verdicts = [v for v in all_verdicts() if v['conflicts']]
        if not verdicts:
            print('Keine Konflikte zwischen Quellen.')
            return 0
        for v in verdicts:
            print(format_verdict(v, verbose=True))
        return 0

    sid = args[0].upper()
    v = strategy_verdict(sid)
    print(json.dumps(v, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
