#!/usr/bin/env python3
"""
Thesis Quality Score (TQS) — Phase 22
======================================
Bewertet jede These 0-100 basierend auf:

  - 6 Pflicht-Felder vollstaendig    (max 40pt)
  - Kill-Trigger quantifiziert        (max 15pt)
  - Commodity-Daten frisch (<=7d)     (max 15pt)
  - Katalysator datiert               (max 15pt)
  - Political-Risk-Flag NICHT gesetzt (max 15pt; bei Flag -20)

Gates:
  TQS >= 80 → Full-Auto Entry erlaubt
  TQS 50-79 → Semi-Auto (Discord-Push noetig)
  TQS <  50 → DRAFT, nicht tradebar

API:
  score_thesis(strategy: dict) -> dict
    { 'tqs': int, 'grade': 'A'|'B'|'C'|'D', 'mode': 'FULL_AUTO'|'SEMI_AUTO'|'DRAFT',
      'breakdown': {...}, 'missing': [...] }
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
DB = WS / 'data' / 'trading.db'

# Die 6 Pflicht-Felder aus thesis-workflow.md
REQUIRED_FIELDS = [
    ('catalyst.date', 'Katalysator-Datum'),
    ('catalyst.event', 'Katalysator-Event'),
    ('genesis.logical_chain', 'Logische Kette 5-6 Schritte'),
    ('kill_trigger', 'Kill-Trigger Array'),
    ('catalyst.commodities', 'Commodity-Hebel'),
    ('eps_scenarios', 'EPS Bear/Base/Bull'),
]


def _get(d: dict, path: str):
    """Dot-path lookup."""
    cur = d
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _commodity_freshness(commodities: list) -> tuple[int, str]:
    """Wie frisch sind die Commodity-Preise? max 15pt."""
    if not commodities or not DB.exists():
        return 0, 'keine commodity-daten'
    try:
        conn = sqlite3.connect(str(DB))
        today = date.today()
        stale_count = 0
        missing_count = 0
        for c in commodities:
            r = conn.execute('''
                SELECT MAX(date) FROM commodity_prices WHERE commodity=?
            ''', (c,)).fetchone()
            if not r or not r[0]:
                missing_count += 1
                continue
            last = datetime.fromisoformat(r[0][:10]).date()
            if (today - last).days > 7:
                stale_count += 1
        conn.close()
        if missing_count == len(commodities):
            return 0, f'alle {missing_count} commodity-daten fehlen'
        if stale_count + missing_count == 0:
            return 15, 'alle commodity-preise frisch'
        if stale_count + missing_count <= len(commodities) / 2:
            return 8, f'{stale_count+missing_count}/{len(commodities)} commodity-daten alt/fehlen'
        return 3, f'mehrheitlich alte commodity-daten'
    except Exception as e:
        return 0, f'commodity-check err: {e}'


def _quantified_kill_triggers(kill_triggers) -> tuple[int, str]:
    """Sind Kill-Trigger quantifiziert? max 15pt."""
    if not kill_triggers:
        return 0, 'keine kill-trigger'
    if isinstance(kill_triggers, str):
        kill_triggers = [kill_triggers]
    if not isinstance(kill_triggers, list):
        return 0, 'kill-trigger falsches format'
    quantified = 0
    for kt in kill_triggers:
        s = str(kt)
        # heuristisch: enthaelt Zahl + Symbol/Operator oder Datum
        has_number = any(ch.isdigit() for ch in s)
        has_operator = any(op in s for op in ['<', '>', 'unter', 'ueber', 'below', 'above', '=', '%', '$', '€'])
        if has_number and has_operator:
            quantified += 1
    if quantified == 0:
        return 0, 'kill-trigger nicht quantifiziert (nur Text)'
    if quantified >= len(kill_triggers) * 0.75:
        return 15, f'{quantified}/{len(kill_triggers)} quantifiziert'
    if quantified >= len(kill_triggers) * 0.5:
        return 10, f'{quantified}/{len(kill_triggers)} quantifiziert'
    return 5, f'nur {quantified}/{len(kill_triggers)} quantifiziert'


def _catalyst_dated(cat) -> tuple[int, str]:
    """Ist der Katalysator datiert und plausibel? max 15pt."""
    if not cat or not isinstance(cat, dict):
        return 0, 'kein catalyst'
    date_s = cat.get('date')
    if not date_s:
        return 0, 'catalyst.date fehlt'
    try:
        d = datetime.fromisoformat(str(date_s)[:10]).date()
        today = date.today()
        diff = abs((d - today).days)
        horizon = int(cat.get('horizon_days', 60))
        # Bonus wenn innerhalb eines sinnvollen Zeitfensters
        if cat.get('fired') and diff <= horizon:
            return 15, f'gefeuert vor {diff}d, im horizon'
        if not cat.get('fired') and diff <= 90:
            return 15, f'datum {diff}d entfernt, plausibel'
        return 8, f'datum {diff}d — grenzwertig'
    except Exception:
        return 0, 'catalyst.date nicht parsebar'


def _required_fields(strategy: dict) -> tuple[int, list, int]:
    """6 Pflicht-Felder. max 40pt. Returns (points, missing, filled_count)."""
    filled = 0
    missing = []
    for path, human in REQUIRED_FIELDS:
        v = _get(strategy, path)
        if v is None or (isinstance(v, (list, str, dict)) and len(v) == 0):
            missing.append(human)
        else:
            filled += 1
    points = int((filled / len(REQUIRED_FIELDS)) * 40)
    return points, missing, filled


def _political_risk_penalty(strategy: dict) -> tuple[int, str]:
    """Political-Risk-Flag gesetzt? max 15pt, bei Flag -20 (kann negativ werden)."""
    flag = strategy.get('political_risk_flag', False)
    reason = strategy.get('political_risk_reason', '')
    if flag:
        return -20, f'POLITICAL RISK: {reason}'
    return 15, 'kein political-risk-flag'


def score_thesis(strategy: dict) -> dict:
    """Haupt-API."""
    req_pts, missing, filled = _required_fields(strategy)
    kill_pts, kill_note = _quantified_kill_triggers(strategy.get('kill_trigger'))
    commodities = (strategy.get('catalyst') or {}).get('commodities') or []
    comm_pts, comm_note = _commodity_freshness(commodities)
    cat_pts, cat_note = _catalyst_dated(strategy.get('catalyst') or {})
    pol_pts, pol_note = _political_risk_penalty(strategy)

    total = req_pts + kill_pts + comm_pts + cat_pts + pol_pts
    total = max(0, min(100, total))

    if total >= 80:
        mode, grade = 'FULL_AUTO', 'A'
    elif total >= 65:
        mode, grade = 'SEMI_AUTO', 'B'
    elif total >= 50:
        mode, grade = 'SEMI_AUTO', 'C'
    else:
        mode, grade = 'DRAFT', 'D'

    return {
        'tqs': total,
        'grade': grade,
        'mode': mode,
        'breakdown': {
            'required_fields': f'{req_pts}/40 ({filled}/{len(REQUIRED_FIELDS)} gefuellt)',
            'kill_trigger': f'{kill_pts}/15 — {kill_note}',
            'commodity_freshness': f'{comm_pts}/15 — {comm_note}',
            'catalyst_dated': f'{cat_pts}/15 — {cat_note}',
            'political_risk': f'{pol_pts}/15 — {pol_note}',
        },
        'missing': missing,
    }


if __name__ == '__main__':
    # CLI: score aller Strategien
    path = WS / 'data' / 'strategies.json'
    if not path.exists():
        print('strategies.json fehlt')
        raise SystemExit(1)
    strats = json.loads(path.read_text(encoding='utf-8'))
    print(f'{"ID":12} {"TQS":>4} {"MODE":10}  MISSING')
    print('-' * 80)
    for sid, cfg in strats.items():
        if not isinstance(cfg, dict) or sid.startswith('_') or sid == 'emerging_themes':
            continue
        sc = score_thesis(cfg)
        miss = ','.join(sc['missing'][:3]) if sc['missing'] else '—'
        print(f'{sid:12} {sc["tqs"]:>4} {sc["mode"]:10}  {miss}')
