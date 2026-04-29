#!/usr/bin/env python3
"""
strategy_auditor.py — Phase 44A2: Strategy-Graveyard-Auditor.

Quelle: Albert's Self-Improvement Proposal #4 (27.04.2026)
Verifiziert 29.04.2026: 36 von 41 aktiven Strategien sind dormant
(0 Trades letzte 30 Tage). Das ist eine echte Lücke.

Was es tut:
  1. Analysiert alle aktiven Strategien aus strategies.json
  2. Kategorisiert nach Trade-Aktivität letzte 30 Tage:
     - LIVE (>=3 Trades)
     - WEAK (1-2 Trades, neg. PnL)
     - DORMANT (0 Trades)
  3. Generiert Audit-Report
  4. Schreibt Vorschläge nach data/strategy_audit_report.json

Wichtig: KEINE automatische Suspendierung. Nur Review-Vorschläge.
Strategien die für seltene Regimes designed sind (z.B. Crash-Hedges)
sollen nicht abgewertet werden.

Run:
  python3 scripts/strategy_auditor.py            # Analyse + Report
  python3 scripts/strategy_auditor.py --discord  # + Discord-Push (Sonntag)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
STRATEGIES_FILE = WS / 'data' / 'strategies.json'
REPORT_FILE     = WS / 'data' / 'strategy_audit_report.json'

# Permanent geblockte Strategien — werden NICHT als WEAK/DORMANT gewertet
PERMANENT_BLOCKED = {'AR-AGRA', 'AR-HALB', 'DT1', 'DT2', 'DT3', 'DT4', 'DT5'}

# Strategien die explizit für seltene Regimes designed sind — als 'STANDBY' markieren
RARE_REGIME_STRATEGIES = set()  # leer; bei Bedarf hier eintragen


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_active_strategies() -> dict:
    """Lade alle aktiven Strategien aus strategies.json."""
    if not STRATEGIES_FILE.exists():
        return {}
    try:
        d = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}
    active = {}
    for sid, s in d.items():
        if not isinstance(s, dict):
            continue
        if s.get('status') != 'active':
            continue
        if sid in PERMANENT_BLOCKED:
            continue
        active[sid] = s
    return active


def get_trade_activity(strategy_id: str, days: int = 30) -> dict:
    """Aktivität einer Strategie in letzten N Tagen."""
    c = sqlite3.connect(str(DB))
    cutoff_date = (datetime.now() - __import__('datetime').timedelta(days=days)).strftime('%Y-%m-%d')

    # Closed in den letzten N Tagen
    closed = c.execute(
        "SELECT COUNT(*), SUM(pnl_eur), AVG(pnl_eur), "
        "       SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END) "
        "FROM paper_portfolio WHERE strategy=? "
        "AND substr(close_date,1,10) >= ? "
        "AND status IN ('CLOSED','WIN','LOSS')",
        (strategy_id, cutoff_date)
    ).fetchone()
    n_closed = closed[0] or 0
    pnl_closed = closed[1] or 0.0
    avg_closed = closed[2] or 0.0
    wins = closed[3] or 0

    # Geöffnet in den letzten N Tagen (auch noch open)
    opened = c.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE strategy=? "
        "AND substr(entry_date,1,10) >= ?",
        (strategy_id, cutoff_date)
    ).fetchone()
    n_opened = opened[0] or 0

    # Lebenslange Stats
    lifetime = c.execute(
        "SELECT COUNT(*), SUM(pnl_eur), AVG(pnl_eur) "
        "FROM paper_portfolio WHERE strategy=? "
        "AND status IN ('CLOSED','WIN','LOSS')",
        (strategy_id,)
    ).fetchone()
    n_lifetime = lifetime[0] or 0
    pnl_lifetime = lifetime[1] or 0.0
    c.close()

    return {
        'strategy_id': strategy_id,
        'opened_30d': n_opened,
        'closed_30d': n_closed,
        'pnl_30d': round(pnl_closed, 2),
        'avg_pnl_30d': round(avg_closed, 2),
        'wins_30d': wins,
        'win_rate_30d': round(wins / n_closed * 100, 1) if n_closed else None,
        'lifetime_trades': n_lifetime,
        'lifetime_pnl': round(pnl_lifetime, 2),
    }


def categorize(activity: dict) -> str:
    """Kategorisierung basierend auf Aktivität."""
    n = activity['opened_30d']
    n_lifetime = activity['lifetime_trades']
    pnl_30d = activity['pnl_30d']

    if n >= 3:
        return 'LIVE'
    if n == 0 and n_lifetime == 0:
        return 'NEVER_TRADED'
    if n == 0:
        return 'DORMANT'
    # 1-2 Trades letzte 30d
    if pnl_30d < 0:
        return 'WEAK'
    return 'LIGHT'  # 1-2 Trades, positiv


def audit() -> dict:
    """Hauptanalyse. Returns volle Audit-Daten."""
    strategies = load_active_strategies()
    results = {
        'audit_ts': _now_iso(),
        'total_active_strategies': len(strategies),
        'categories': {
            'LIVE': [], 'LIGHT': [], 'WEAK': [],
            'DORMANT': [], 'NEVER_TRADED': []
        },
        'strategies': {},
    }

    for sid, meta in strategies.items():
        activity = get_trade_activity(sid)
        category = categorize(activity)
        activity['category'] = category
        activity['name']     = meta.get('name', sid)
        activity['sector']   = meta.get('sector', '')
        results['strategies'][sid] = activity
        results['categories'][category].append(sid)

    # Cross-Stats
    results['summary'] = {
        'live_count':         len(results['categories']['LIVE']),
        'light_count':        len(results['categories']['LIGHT']),
        'weak_count':         len(results['categories']['WEAK']),
        'dormant_count':      len(results['categories']['DORMANT']),
        'never_traded_count': len(results['categories']['NEVER_TRADED']),
        'pct_dormant':        round(
            len(results['categories']['DORMANT']) /
            max(1, results['total_active_strategies']) * 100, 1
        ),
    }

    # Empfehlungen (NUR Review-Vorschläge, kein auto-action)
    results['recommendations'] = []
    for sid in results['categories']['DORMANT']:
        a = results['strategies'][sid]
        if a['lifetime_trades'] == 0:
            continue  # Cold-Start, nicht dormant
        results['recommendations'].append({
            'strategy_id': sid,
            'category': 'DORMANT',
            'action_suggested': 'review_or_disable',
            'reason': f"0 Trades letzte 30d trotz {a['lifetime_trades']} lifetime trades",
            'lifetime_pnl': a['lifetime_pnl'],
        })
    for sid in results['categories']['WEAK']:
        a = results['strategies'][sid]
        results['recommendations'].append({
            'strategy_id': sid,
            'category': 'WEAK',
            'action_suggested': 'monitor_or_reduce',
            'reason': f"{a['opened_30d']} Trades, PnL {a['pnl_30d']:+.0f}€",
            'lifetime_pnl': a['lifetime_pnl'],
        })

    return results


def format_report(audit_data: dict) -> str:
    s = audit_data['summary']
    cats = audit_data['categories']
    lines = [
        '═══ STRATEGY AUDIT — ' + audit_data['audit_ts'][:16] + ' ═══',
        '',
        f'Total aktive Strategien: {audit_data["total_active_strategies"]}',
        '',
        f'  🟢 LIVE         ({s["live_count"]:>3}): >=3 Trades letzte 30d',
        f'  🟡 LIGHT        ({s["light_count"]:>3}): 1-2 Trades, positiv',
        f'  🟠 WEAK         ({s["weak_count"]:>3}): 1-2 Trades, negativ',
        f'  🔴 DORMANT      ({s["dormant_count"]:>3}): 0 Trades 30d (lifetime > 0)',
        f'  ⚪ NEVER_TRADED ({s["never_traded_count"]:>3}): kein einziger Trade ever',
        '',
        f'Dormant-Prozentsatz: {s["pct_dormant"]:.1f}%',
    ]

    if cats['LIVE']:
        lines.append('')
        lines.append('━━ LIVE-Strategien (aktiv tradend) ━━')
        for sid in cats['LIVE']:
            a = audit_data['strategies'][sid]
            wr_str = f'WR{a["win_rate_30d"]:.0f}%' if a['win_rate_30d'] is not None else ''
            lines.append(f'  · {sid:<12} {a["opened_30d"]:>2} opened | {a["closed_30d"]:>2} closed | '
                          f'PnL {a["pnl_30d"]:+6.0f}€ {wr_str}')

    if cats['DORMANT']:
        lines.append('')
        lines.append(f'━━ DORMANT-Strategien (Top-15 nach lifetime PnL) ━━')
        sorted_dormant = sorted(
            cats['DORMANT'],
            key=lambda x: -audit_data['strategies'][x]['lifetime_pnl']
        )
        for sid in sorted_dormant[:15]:
            a = audit_data['strategies'][sid]
            lines.append(f'  · {sid:<12} lifetime: {a["lifetime_trades"]:>2}T '
                          f'{a["lifetime_pnl"]:+7.0f}€')

    if cats['NEVER_TRADED']:
        lines.append('')
        lines.append(f'━━ NEVER_TRADED ({len(cats["NEVER_TRADED"])} Strategien) ━━')
        lines.append(f'  {", ".join(cats["NEVER_TRADED"][:20])}')

    if audit_data['recommendations']:
        lines.append('')
        lines.append('━━ EMPFEHLUNGEN (review only, kein auto-action) ━━')
        for r in audit_data['recommendations'][:20]:
            lines.append(f'  · {r["strategy_id"]:<12} ({r["category"]}): '
                          f'{r["action_suggested"]} — {r["reason"]}')

    return '\n'.join(lines)


def push_discord(report_text: str) -> bool:
    try:
        from discord_dispatcher import send_alert, TIER_LOW
        msg = '🗂️ **Wöchentlicher Strategy-Audit**\n```\n' + report_text[:1700] + '\n```'
        return send_alert(msg, tier=TIER_LOW, category='strategy_audit',
                           dedupe_key='strategy_audit_weekly')
    except Exception as e:
        print(f'discord push err: {e}', file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--discord', action='store_true', help='Push report to Discord')
    args = ap.parse_args()

    data = audit()
    REPORT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                             encoding='utf-8')
    report = format_report(data)
    print(report)

    if args.discord:
        push_discord(report)

    return 0


if __name__ == '__main__':
    sys.exit(main())
