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
    # ╔═══════════════════════════════════════════════════════════════════╗
    # ║ Phase 43e: Aggressive User-Whitelist (default-deny)               ║
    # ║ HIGH = sofort an Victor                                           ║
    # ║ MEDIUM = Batch (4x/Tag)                                           ║
    # ║ LOW = Morgen-Digest only                                          ║
    # ║ SILENT = nur ceo_inbox (CEO weiß, Victor nicht)                   ║
    # ║ DEFAULT für unbekannte Events = SILENT (default-deny).            ║
    # ╚═══════════════════════════════════════════════════════════════════╝

    # ── Trading: Position-Status (User MUSS wissen) ─────────────────────
    'trade.entry_executed':        'HIGH',     # Position offen
    'trade.exit_stop_hit':         'HIGH',     # Stop ausgelöst
    'trade.exit_kill_trigger':     'HIGH',     # Kill-Trigger
    'trade.exit_thesis_invalid':   'HIGH',     # These kaputt
    'trade.exit_target_hit':       'HIGH',     # Tranche/Target
    'trade.entry_semi_auto_prompt':'HIGH',     # Wartet auf Entscheidung
    'trade.entry_full_auto':       'SILENT',   # Auto-Entry → CEO-internal (executed pingt schon)
    'trade.exit_max_hold':         'SILENT',   # Time-Exit → kein Drama

    # ── Bodenbildung / Re-Entry-Signale (Watchlist) ────────────────────
    'bodenbildung.confirmed':      'HIGH',     # Re-Entry-Signal CONFIRMED
    'bodenbildung.early_signal':   'SILENT',   # nur EARLY → CEO-internal

    # ── Macro / Geo (echte Schocks) ────────────────────────────────────
    'macro.critical':              'HIGH',     # ENERGY/FED-SHOCK CRITICAL
    'macro.high':                  'SILENT',   # HIGH → CEO-internal
    'macro.medium':                'SILENT',
    'political_risk.new_flag':     'HIGH',     # Flag auf aktiver Position
    'political_risk.flag_cleared': 'SILENT',

    # ── Digest / Briefings (Daily-Anker) ───────────────────────────────
    'digest.morning':              'HIGH',     # 08:00 Briefing
    'digest.evening':              'SILENT',   # 22:00 → File, nicht Discord

    # ── System (nur echte persistente Probleme) ────────────────────────
    'system.scheduler_crash':      'SILENT',   # Auto-Restart funktioniert
    'system.scheduler_persistent': 'HIGH',     # >30min down trotz Restart
    'system.heartbeat_lost':       'SILENT',   # transient
    'system.commodity_refresh_fail':'SILENT',
    'system.deploy_success':       'SILENT',
    'system.db_integrity_fail':    'HIGH',     # echte DB-Korruption
    'system.anomaly_detected':     'HIGH',     # Anomalie-Brake feuert

    # ── Health / Watchdog (NIE Discord) ────────────────────────────────
    'health.heartbeat':            'SILENT',
    'health.recovered':            'SILENT',
    'health.warning':              'SILENT',
    'health.degraded':             'SILENT',
    'discord_send':                'SILENT',   # Recursion-Schutz
    'general':                     'SILENT',
    'debug':                       'SILENT',

    # ── Strategy-Lifecycle (CEO-internal) ──────────────────────────────
    'lifecycle.transition':        'SILENT',
    'lifecycle.suspended':         'SILENT',
    'lifecycle.elevated':          'SILENT',

    # ── Initiative / Discovery (CEO-internal) ──────────────────────────
    'initiative.ticker_added':     'SILENT',   # Albert addet selbständig
    'discovery.new_ticker':        'SILENT',
    'discovery.thesis_promoted':   'SILENT',

    # ── Catalyst / Watchlist (CEO-internal) ────────────────────────────
    'catalyst.fired':              'SILENT',
    'catalyst.stale':              'SILENT',
    'catalyst.secondary_near':     'SILENT',
    'thesis.new_draft':            'SILENT',
    'thesis.upgraded_to_active':   'SILENT',
    'thesis.trigger_hit':          'SILENT',
    'thesis.quality_degraded':     'SILENT',

    # ── Regime ──
    'regime.shift':                'HIGH',     # BULLISH → BEARISH = Victor wissen
    'regime.vix_spike':            'SILENT',
}


def tier_for(event: str) -> str:
    """Event-Name -> Tier.
    Phase 43e: Default = SILENT (default-deny, kein Spam).
    Wenn ein Event nicht explizit in POLICY ist → User sieht es nicht."""
    if event in POLICY:
        return POLICY[event]
    prefix = event.split('.')[0] + '.*'
    if prefix in POLICY:
        return POLICY[prefix]
    return 'SILENT'  # Phase 43e: default-deny


def notify(event: str, message: str, category: str = 'general', **kwargs) -> bool:
    """
    Haupt-API: sendet Nachricht mit Policy-basiertem Tier.

    event:    z.B. 'trade.exit_stop_hit'
    message:  der Discord-Text
    category: logische Gruppe fuer Digest-Aggregation
    """
    tier = tier_for(event)
    if tier == 'SILENT':
        # Phase 43e: SILENT trotzdem in ceo_inbox loggen (CEO-Sicht)
        try:
            from ceo_inbox import write_event
            write_event(event_type=event, message=message,
                         severity='info', category=category,
                         user_pinged=False)
        except Exception:
            pass
        return True  # "delivered" — to CEO inbox
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
