#!/usr/bin/env python3
"""
strategy_auto_deprecate.py — Phase 44A2b: Autonome Karteileichen-Bereinigung.

Folgt Regel #1: System entscheidet selbst, kein User-Touchpoint.

Logik:
  Strategie-Status = active
  AND opened_60d = 0
  AND lifetime_trades = 0
  AND entry_gate_log_60d = 0   (= kein Trigger ist je gefeuert)
  → auto_deprecated

Reaktivierung (automatisch):
  Wenn Hunter ein Setup für eine deprecated Strategie findet:
  → status zurück auf active

Reversibilität:
  - Auto-deprecated Strategien bleiben in strategies.json
  - Genesis + Definition bleiben unverändert
  - Nur status='auto_deprecated' (kann zurück auf 'active')
  - Audit-Trail in genesis.feedback_history

Run:
  python3 scripts/strategy_auto_deprecate.py            # auto-run + Discord
  python3 scripts/strategy_auto_deprecate.py --dry-run  # nur Liste, kein Update
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
LOG_FILE        = WS / 'data' / 'auto_deprecate_log.jsonl'

# Strategien die auch ohne Trade aktiv bleiben sollen (z.B. Crash-Hedges)
KEEP_DESPITE_DORMANT = set()  # leer; kann erweitert werden

# Permanent geblockte Strategien — gar nicht erst anfassen
PERMANENT_BLOCKED = {'AR-AGRA', 'AR-HALB', 'DT1', 'DT2', 'DT3', 'DT4', 'DT5'}

DORMANT_DAYS = 60  # 60 Tage ohne Aktivität → deprecated


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_action(action: str, payload: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': _now_iso(), 'action': action, **payload
        }, ensure_ascii=False) + '\n')


def find_deprecation_candidates() -> list[dict]:
    """Identifiziert Strategien die nach Regel deprecated werden sollten."""
    if not STRATEGIES_FILE.exists():
        return []
    strats = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))

    c = sqlite3.connect(str(DB))
    candidates = []

    for sid, meta in strats.items():
        if not isinstance(meta, dict):
            continue
        # Phase 44g: alle "lebenden" Status checken (active, None, watchlist, watching, EVALUATING)
        _st = meta.get('status')
        if _st in ('paused', 'retired', 'auto_deprecated', 'ARCHIVED', 'DRAFT'):
            continue
        if sid in PERMANENT_BLOCKED:
            continue
        if sid in KEEP_DESPITE_DORMANT:
            continue

        # Lifetime Trade Count
        n_lifetime = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE strategy=?", (sid,)
        ).fetchone()[0]

        # Trades letzte 60d
        n_60d = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio "
            "WHERE strategy=? AND substr(entry_date,1,10) >= date('now', '-60 days')",
            (sid,)
        ).fetchone()[0]

        # Entry-Gate-Log Einträge letzte 60d (= Trigger gefeuert)
        try:
            n_gate = c.execute(
                "SELECT COUNT(*) FROM entry_gate_log "
                "WHERE strategy=? AND substr(timestamp,1,10) >= date('now', '-60 days')",
                (sid,)
            ).fetchone()[0]
        except Exception:
            n_gate = 0

        # Genesis-Datum (Schutz: ganz neue Strategien nicht sofort deprecaten)
        try:
            genesis_date = (meta.get('genesis') or {}).get('created', '')
            if genesis_date:
                genesis_dt = datetime.fromisoformat(genesis_date[:10])
                age_days = (datetime.now() - genesis_dt).days
            else:
                age_days = 999
        except Exception:
            age_days = 999

        # Trades letzte 30d (für aggressive Regel)
        n_30d = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio "
            "WHERE strategy=? AND substr(entry_date,1,10) >= date('now', '-30 days')",
            (sid,)
        ).fetchone()[0]

        # Lifetime PnL
        try:
            pnl_row = c.execute(
                "SELECT COALESCE(SUM(pnl_eur),0) FROM paper_portfolio WHERE strategy=?",
                (sid,)
            ).fetchone()
            lifetime_pnl = float(pnl_row[0] or 0)
        except Exception:
            lifetime_pnl = 0.0

        # Aggressive Regeln (Phase 44g):
        # A) Klassisch: 0 lifetime AND 0 60d AND 0 gate-fires AND age>=60d  → tot
        # B) Schwach: lifetime<=2 AND 0 30d trades AND age>=30d  → keine Edge nachweisbar
        # C) Verlust: lifetime>2 AND PnL<0 AND 0 30d trades  → negative Edge
        # D) Tot+old: lifetime<=1 AND 0 60d AND age>=45d  → erweiterte Karteileiche
        deprec_reason = None
        if n_lifetime == 0 and n_60d == 0 and n_gate == 0 and age_days >= DORMANT_DAYS:
            deprec_reason = (f'Klassisch: 0 lifetime, 0 trades 60d, 0 gate-fires 60d, age {age_days}d')
        elif n_lifetime <= 2 and n_30d == 0 and age_days >= 30:
            deprec_reason = (f'Schwach: lifetime {n_lifetime}<=2 trades, 0 in 30d, age {age_days}d → keine Edge')
        elif n_lifetime > 2 and lifetime_pnl < 0 and n_30d == 0:
            deprec_reason = (f'Negativ: lifetime {n_lifetime} trades PnL {lifetime_pnl:+.0f}€, 0 in 30d')
        elif n_lifetime <= 1 and n_60d == 0 and age_days >= 45:
            deprec_reason = (f'Karteileiche: lifetime {n_lifetime}, 0 in 60d, age {age_days}d')

        if deprec_reason:
            candidates.append({
                'strategy_id': sid,
                'name': meta.get('name', sid),
                'sector': meta.get('sector', ''),
                'genesis_date': genesis_date or '?',
                'age_days': age_days,
                'lifetime_trades': n_lifetime,
                'lifetime_pnl': round(lifetime_pnl, 2),
                'trades_30d': n_30d,
                'trades_60d': n_60d,
                'gate_fires_60d': n_gate,
                'reason': deprec_reason,
            })

    c.close()
    return candidates


def find_reactivation_candidates() -> list[dict]:
    """Strategien die deprecated sind aber jetzt wieder Trigger feuern."""
    if not STRATEGIES_FILE.exists():
        return []
    strats = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))

    c = sqlite3.connect(str(DB))
    candidates = []

    for sid, meta in strats.items():
        if not isinstance(meta, dict):
            continue
        if meta.get('status') != 'auto_deprecated':
            continue

        # Trigger letzte 7d gefeuert?
        try:
            n_gate = c.execute(
                "SELECT COUNT(*) FROM entry_gate_log "
                "WHERE strategy=? AND substr(timestamp,1,10) >= date('now', '-7 days')",
                (sid,)
            ).fetchone()[0]
        except Exception:
            n_gate = 0

        if n_gate > 0:
            candidates.append({
                'strategy_id': sid,
                'gate_fires_7d': n_gate,
            })

    c.close()
    return candidates


def apply_deprecation(candidates: list[dict], dry_run: bool = False) -> int:
    if not candidates:
        return 0
    if dry_run:
        return len(candidates)

    strats = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    now = _now_iso()
    today = datetime.now().strftime('%Y-%m-%d')

    for c in candidates:
        sid = c['strategy_id']
        if sid not in strats:
            continue
        strats[sid]['status'] = 'auto_deprecated'
        strats[sid]['_deprecated_at'] = now
        strats[sid]['_deprecated_reason'] = (
            f'Auto-Deprecation Regel #1: 0 lifetime trades, 0 Trades 60d, '
            f'0 Gate-Fires 60d, age {c["age_days"]}d'
        )
        strats[sid].setdefault('genesis', {}).setdefault('feedback_history', []).append({
            'date': today,
            'action': 'auto_deprecated',
            'reason': strats[sid]['_deprecated_reason'],
        })
        _log_action('deprecate', c)

    STRATEGIES_FILE.write_text(json.dumps(strats, indent=2, ensure_ascii=False),
                                 encoding='utf-8')
    return len(candidates)


def apply_reactivation(candidates: list[dict], dry_run: bool = False) -> int:
    if not candidates:
        return 0
    if dry_run:
        return len(candidates)

    strats = json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    now = _now_iso()
    today = datetime.now().strftime('%Y-%m-%d')

    for c in candidates:
        sid = c['strategy_id']
        if sid not in strats:
            continue
        strats[sid]['status'] = 'active'
        strats[sid]['_reactivated_at'] = now
        strats[sid]['_reactivation_reason'] = (
            f'Auto-Reaktivierung: {c["gate_fires_7d"]} Trigger gefeuert in 7d'
        )
        strats[sid].setdefault('genesis', {}).setdefault('feedback_history', []).append({
            'date': today,
            'action': 'auto_reactivated',
            'reason': strats[sid]['_reactivation_reason'],
        })
        _log_action('reactivate', c)

    STRATEGIES_FILE.write_text(json.dumps(strats, indent=2, ensure_ascii=False),
                                 encoding='utf-8')
    return len(candidates)


def push_discord_summary(deprecated: list[dict], reactivated: list[dict]) -> None:
    """Post-fact Info, kein Approval-Request."""
    if not deprecated and not reactivated:
        return
    try:
        from discord_dispatcher import send_alert, TIER_LOW
        lines = ['🗂️ **Strategy Auto-Lifecycle (Regel #1)**\n']
        if deprecated:
            lines.append(f'**Auto-Deprecated** ({len(deprecated)} Strategien):')
            for c in deprecated[:15]:
                lines.append(f"  · `{c['strategy_id']}` ({c['name'][:30]}) — "
                              f"age {c['age_days']}d, 0 trades, 0 gate-fires")
            if len(deprecated) > 15:
                lines.append(f'  · …und {len(deprecated)-15} weitere')
        if reactivated:
            lines.append(f'\n**Auto-Reactivated** ({len(reactivated)} Strategien):')
            for c in reactivated:
                lines.append(f"  · `{c['strategy_id']}` — "
                              f"{c['gate_fires_7d']} Trigger gefeuert")
        lines.append(f'\n_Reversibel: Reaktivierung erfolgt automatisch wenn Hunter Setup findet._')
        send_alert('\n'.join(lines), tier=TIER_LOW,
                    category='strategy_auto_lifecycle',
                    dedupe_key='strategy_auto_deprecate_daily')
    except Exception as e:
        print(f'discord push err: {e}', file=sys.stderr)


def run(dry_run: bool = False) -> dict:
    deprecation_candidates = find_deprecation_candidates()
    reactivation_candidates = find_reactivation_candidates()

    n_deprecated = apply_deprecation(deprecation_candidates, dry_run=dry_run)
    n_reactivated = apply_reactivation(reactivation_candidates, dry_run=dry_run)

    if not dry_run:
        push_discord_summary(deprecation_candidates, reactivation_candidates)

    return {
        'ts': _now_iso(),
        'dry_run': dry_run,
        'deprecation_candidates': len(deprecation_candidates),
        'reactivation_candidates': len(reactivation_candidates),
        'deprecated': n_deprecated,
        'reactivated': n_reactivated,
        'deprecated_list': [c['strategy_id'] for c in deprecation_candidates],
        'reactivated_list': [c['strategy_id'] for c in reactivation_candidates],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='Nur Liste, kein Update')
    args = ap.parse_args()

    r = run(dry_run=args.dry_run)
    print(f'═══ Strategy Auto-Deprecate @ {r["ts"][:16]} ═══')
    print(f'  Deprecation candidates: {r["deprecation_candidates"]}')
    print(f'  Reactivation candidates: {r["reactivation_candidates"]}')
    if r['dry_run']:
        print(f'  [DRY RUN — nichts geändert]')
    else:
        print(f'  ✅ Deprecated: {r["deprecated"]}')
        print(f'  ✅ Reactivated: {r["reactivated"]}')
    if r['deprecated_list']:
        print(f'\nDeprecated: {", ".join(r["deprecated_list"])}')
    if r['reactivated_list']:
        print(f'Reactivated: {", ".join(r["reactivated_list"])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
