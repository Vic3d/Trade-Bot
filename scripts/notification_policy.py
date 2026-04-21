#!/usr/bin/env python3
"""
Notification Policy — Phase 22
===============================
Zentrale Mapping-Tabelle: Welches Event -> welcher Discord-Tier.

Victor will Minimum-Ping: nur wenn (a) etwas schiefgelaufen ist oder
(b) er entscheiden muss. Alles andere sammelt sich im Morgen-Digest.

Import-Pattern:
  from notification_policy import notify
  notify('trade.entry_full_auto', 'STLD gekauft 10x @ $209', category='trade')

Statt:
  send_alert('STLD gekauft', tier='HIGH', ...)

Das Policy-Dict ist die Single Source of Truth — wenn Victor ein
Event leiser/lauter will, aendert man NUR hier.
"""
from __future__ import annotations
from typing import Literal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM, TIER_LOW
except Exception:
    # Fallback fuer dry-run / test
    TIER_HIGH, TIER_MEDIUM, TIER_LOW = 'HIGH', 'MEDIUM', 'LOW'
    def send_alert(msg, tier=TIER_HIGH, category='general', **kw):
        print(f'[{tier}/{category}] {msg}')
        return True


Tier = Literal['HIGH', 'MEDIUM', 'LOW', 'SILENT']

# HIGH = sofort ping
# MEDIUM = Batch 4x/Tag
# LOW = nur Abend/Morgen-Digest
# SILENT = gar kein Discord, nur Log
POLICY: dict[str, Tier] = {
    # ── Trading ──
    'trade.entry_full_auto':       'LOW',      # Full-Auto Entry: Info in Digest
    'trade.entry_semi_auto_prompt':'HIGH',     # wartet auf deine Entscheidung
    'trade.entry_executed':        'LOW',      # nach Ausfuehrung
    'trade.exit_target_hit':       'LOW',      # Tranche +5/+10%
    'trade.exit_stop_hit':         'HIGH',     # Stop-Loss ausgeloest (sollte Victor wissen)
    'trade.exit_kill_trigger':     'HIGH',     # Kill-Trigger gefeuert + Exit
    'trade.exit_thesis_invalid':   'HIGH',     # These kaputt, Position raus
    'trade.exit_max_hold':         'LOW',      # Max-Hold-Zeit erreicht

    # ── Katalysator ──
    'catalyst.fired':              'LOW',      # PENDING -> FRESH
    'catalyst.stale':              'LOW',      # Horizon ueberschritten
    'catalyst.secondary_near':     'LOW',      # Earnings in <14d

    # ── Watchlist / Thesen ──
    'thesis.new_draft':            'LOW',      # neue Kandidat-These
    'thesis.upgraded_to_active':   'LOW',      # DRAFT -> ACTIVE_WATCH
    'thesis.trigger_hit':          'LOW',      # T1/T2/T3 erreicht — Digest
    'thesis.quality_degraded':     'LOW',      # TQS gefallen

    # ── Political Risk ──
    'political_risk.new_flag':     'HIGH',     # neues Flag auf aktiver Position
    'political_risk.flag_cleared': 'LOW',      # Flag aufgeloest

    # ── System ──
    'system.scheduler_crash':      'HIGH',     # Scheduler gestorben
    'system.heartbeat_lost':       'HIGH',
    'system.commodity_refresh_fail':'MEDIUM',
    'system.deploy_success':       'LOW',

    # ── Regime ──
    'regime.shift':                'MEDIUM',   # BULLISH -> BEARISH etc.
    'regime.vix_spike':            'MEDIUM',   # VIX > 30

    # ── Discovery / Digest ──
    'digest.morning':              'HIGH',     # 08:00 — ist der tatsaechliche Daily-Ping
    'digest.evening':              'LOW',      # 22:00 — optional

    # ── Debug / Tests ──
    'debug':                       'LOW',
}


def tier_for(event: str) -> str:
    """Event-Name -> Tier. Unbekannt = LOW (defensive, kein Spam)."""
    # Support Hierarchie: 'trade.exit_stop_hit' oder 'trade.*'
    if event in POLICY:
        return POLICY[event]
    prefix = event.split('.')[0] + '.*'
    if prefix in POLICY:
        return POLICY[prefix]
    return 'LOW'


def notify(event: str, message: str, category: str = 'general', **kwargs) -> bool:
    """
    Haupt-API: sendet Nachricht mit Policy-basiertem Tier.

    event:    z.B. 'trade.exit_stop_hit'
    message:  der Discord-Text
    category: logische Gruppe fuer Digest-Aggregation
    """
    tier = tier_for(event)
    if tier == 'SILENT':
        return False
    return send_alert(message, tier=tier, category=category, event=event, **kwargs)


def policy_dump() -> str:
    """CLI-Hilfe: aktuelle Policy ausgeben."""
    lines = ['=== Notification Policy ===']
    by_tier = {}
    for k, v in POLICY.items():
        by_tier.setdefault(v, []).append(k)
    for tier in ('HIGH', 'MEDIUM', 'LOW', 'SILENT'):
        items = by_tier.get(tier, [])
        if not items:
            continue
        lines.append(f'\n── {tier} ({len(items)}) ──')
        for ev in sorted(items):
            lines.append(f'  {ev}')
    return '\n'.join(lines)


if __name__ == '__main__':
    print(policy_dump())
