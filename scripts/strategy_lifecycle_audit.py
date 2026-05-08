#!/usr/bin/env python3
"""
strategy_lifecycle_audit.py — Phase 45ag

Klassifiziert alle aktiven Strategien in 4 Lifecycle-Stages:
  LIVING    — Scanner aktiv + Tickers definiert + Aktivität in 30d
  SLEEPING  — Scanner aktiv aber keine Trigger-Fires in 30d
  ORPHANED  — Tickers definiert aber kein Scanner referenziert sie
  DEAD      — weder Scanner noch Tickers (Hülsen)

Output: data/strategy_lifecycle.json + Console-Report.
"""
from __future__ import annotations
import json, os, sqlite3, subprocess
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
STRATEGIES = WS / 'data' / 'strategies.json'
OUT = WS / 'data' / 'strategy_lifecycle.json'


def _scanner_refs() -> set[str]:
    """Welche Strategy-IDs werden im Code referenziert?"""
    refs: set[str] = set()
    try:
        # grep über scripts/ nach 'PS\d+', 'S\d+', 'DT\d+', etc.
        result = subprocess.run(
            ['grep', '-rhoE', r"\b(PS_?[A-Z0-9_]+|S[0-9]+|DT[0-9]+|AR-[A-Z]+)\b",
             str(WS / 'scripts')],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            t = line.strip()
            if t and len(t) <= 30:
                refs.add(t)
    except Exception:
        pass
    return refs


def audit() -> dict:
    if not STRATEGIES.exists():
        return {'error': 'no_strategies_file'}
    strategies = json.loads(STRATEGIES.read_text(encoding='utf-8'))
    active_ids = [k for k, v in strategies.items()
                  if (v.get('status') == 'active' if isinstance(v, dict) else False)]

    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row

    # Welche Strategien haben überhaupt jemals einen Trade?
    traded = set(r['strategy'] for r in db.execute(
        "SELECT DISTINCT strategy FROM paper_portfolio WHERE strategy IS NOT NULL"
    ).fetchall())

    # Welche hatten Trade-Versuch (cli_audit_violations) oder Trigger-Fire in 30d?
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_traded = set(r['strategy'] for r in db.execute(
        "SELECT DISTINCT strategy FROM paper_portfolio WHERE entry_date >= ?",
        (cutoff,)
    ).fetchall())

    # Code-Scanner-References
    code_refs = _scanner_refs()

    classification = {
        'LIVING': [],
        'SLEEPING': [],
        'ORPHANED': [],
        'DEAD': [],
    }

    for sid in active_ids:
        meta = strategies[sid] if isinstance(strategies[sid], dict) else {}
        tickers = meta.get('tickers') or meta.get('ticker_universe') or []
        if isinstance(tickers, str):
            tickers = [tickers]
        has_tickers = bool(tickers)
        in_code = sid in code_refs
        recent = sid in recent_traded
        ever_traded = sid in traded

        entry = {
            'id': sid,
            'tickers_count': len(tickers),
            'has_tickers': has_tickers,
            'referenced_in_code': in_code,
            'ever_traded': ever_traded,
            'recent_30d': recent,
            'thesis': (meta.get('thesis') or meta.get('description') or '')[:80],
        }

        if recent or (in_code and has_tickers and ever_traded):
            classification['LIVING'].append(entry)
        elif in_code and has_tickers:
            classification['SLEEPING'].append(entry)
        elif has_tickers and not in_code:
            classification['ORPHANED'].append(entry)
        else:
            classification['DEAD'].append(entry)

    db.close()

    summary = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'total_active': len(active_ids),
        'counts': {k: len(v) for k, v in classification.items()},
        'by_stage': classification,
    }
    return summary


def main() -> int:
    r = audit()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=2), encoding='utf-8')

    print(f"=== Strategy Lifecycle Audit ===")
    print(f"Total active: {r['total_active']}")
    for stage, n in r['counts'].items():
        print(f"  {stage:10s}: {n}")
    print()
    for stage in ('LIVING', 'SLEEPING', 'ORPHANED', 'DEAD'):
        items = r['by_stage'][stage]
        if not items:
            continue
        print(f"--- {stage} ({len(items)}) ---")
        for it in items[:25]:
            flags = []
            if it['recent_30d']: flags.append('RECENT')
            if it['ever_traded']: flags.append('TRADED')
            if it['referenced_in_code']: flags.append('CODE')
            if it['has_tickers']: flags.append(f"T:{it['tickers_count']}")
            print(f"  {it['id']:25s} [{','.join(flags)}] {it['thesis'][:60]}")
        if len(items) > 25:
            print(f"  ... +{len(items)-25} more")
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
