#!/usr/bin/env python3
"""
trade_lifecycle_pusher.py — Phase 44q: Bewusste Trade-Kommunikation.

Ein einziger Helper fuer Discord-Pushes bei Trade-Lifecycle-Events.
3 Zeilen pro Push, KEINE Floskel, IMMER mit "Why".

Ziel: Victor weiss bei jedem Trade was passiert UND warum — ohne dass er
fragt, ohne 30s-Veto-Wartezeit, ohne Spam.

Format Entry:
  🟢 ENTRY EQNR.OL @ 34.08€  [S1, Conv 85, R:R 2.1]
     Stop 31.66 (-7%) | Target 39.19 (+15%) | Position 1.227€
     Why: Iran-Hormuz Druck haelt Brent strukturell hoch (+12.8% 7d)

Format Close:
  🔴 STOP EQNR.OL @ 33.74€  [S1, hold 21h, -1.6€/-0.05%]
     Plan war: Stop bei 31.66 — wurde durch Macro-Reactor auf 34.08 hochgezogen
     Lehre: Mikro-Stop ausgeloest durch normale Tagesvolatilitaet

  ✅ TARGET PAAS @ 51.81€  [PS4, hold 36h, +176€/+15.7%]
     Plan war: Target bei 51.52 — sauber erreicht
     Lehre: Gold/USD-Schwaeche-These hat in 36h getragen

Optional: WIN ohne Target (Manual close, etc.) — nutze passenden Block.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))


def push_entry(*, ticker: str, strategy: str, entry: float, stop: float,
                target: float, position_eur: float, conviction: float,
                thesis: str, regime: str | None = None) -> None:
    """3-Zeilen Entry-Push. Wird vom paper_trade_engine nach erfolgreichem
    Insert gerufen."""
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = (reward / risk) if risk > 0 else 0
    stop_pct = ((stop - entry) / entry) * 100 if entry else 0
    target_pct = ((target - entry) / entry) * 100 if entry else 0
    why = (thesis or '').strip()
    if len(why) > 140:
        why = why[:137] + '...'
    if not why:
        why = f'Strategy {strategy} Setup-Match'

    msg = (
        f"🟢 **ENTRY {ticker}** @ {entry:.2f}€  "
        f"[{strategy}, Conv {conviction:.0f}, R:R {rr:.1f}]\n"
        f"   Stop {stop:.2f} ({stop_pct:+.1f}%) | "
        f"Target {target:.2f} ({target_pct:+.1f}%) | Position {position_eur:.0f}€\n"
        f"   Why: {why}"
    )
    _send(msg)


def push_close(*, ticker: str, strategy: str, entry: float, exit_price: float,
                pnl_eur: float, pnl_pct: float, exit_type: str,
                hold_hours: float, original_stop: float | None = None,
                original_target: float | None = None,
                lesson: str | None = None) -> None:
    """3-Zeilen Close-Push. Wird vom paper_exit_manager bei jeder Position-
    Schliessung gerufen — egal ob Stop, Target, Time, Manual."""
    icon = '✅' if pnl_eur > 0 else ('🔴' if pnl_eur < 0 else '➖')
    label = _close_label(exit_type)
    hold_str = _format_hold(hold_hours)

    plan_line = ''
    if original_stop and original_target:
        plan_line = (f'   Plan war: Stop {original_stop:.2f} | Target {original_target:.2f} → '
                     f'{label}')
    elif original_stop:
        plan_line = f'   Plan war: Stop {original_stop:.2f} → {label}'
    else:
        plan_line = f'   Exit-Type: {exit_type}'

    lesson = (lesson or _auto_lesson(exit_type, pnl_pct)).strip()
    if len(lesson) > 140:
        lesson = lesson[:137] + '...'

    msg = (
        f"{icon} **{label} {ticker}** @ {exit_price:.2f}€  "
        f"[{strategy}, hold {hold_str}, {pnl_eur:+.1f}€/{pnl_pct:+.2f}%]\n"
        f"{plan_line}\n"
        f"   Lehre: {lesson}"
    )
    # Phase 44u: HIGH nur bei signifikantem PnL-Move
    force_high = abs(pnl_eur) >= 200 or label in ('CRASH-EXIT', 'EVENT-EXIT')
    _send(msg, force_high=force_high)


def _close_label(exit_type: str) -> str:
    et = (exit_type or '').upper()
    if 'TARGET' in et: return 'TARGET'
    if 'STOP' in et: return 'STOP'
    if 'TIME' in et: return 'TIME-EXIT'
    if 'CRASH' in et: return 'CRASH-EXIT'
    if 'EVENT' in et or 'MACRO' in et: return 'EVENT-EXIT'
    if 'TRANCHE' in et: return 'TRANCHE'
    if 'RESET' in et: return 'RESET-CLOSED'
    if 'MANUAL' in et: return 'MANUAL'
    return et or 'CLOSE'


def _format_hold(hours: float) -> str:
    if hours < 1: return f'{int(hours*60)}min'
    if hours < 24: return f'{hours:.1f}h'
    return f'{hours/24:.1f}d'


def _auto_lesson(exit_type: str, pnl_pct: float) -> str:
    et = (exit_type or '').upper()
    if 'TARGET' in et:
        return f'Target erreicht — Strategy-Mechanik bestaetigt ({pnl_pct:+.1f}%)'
    if 'STOP' in et and abs(pnl_pct) < 2:
        return 'Mikro-Stop ausgeloest — Stop war moeglicherweise zu eng fuer normale Vola'
    if 'STOP' in et:
        return f'Stop gehalten ({pnl_pct:+.1f}%) — These war zu frueh oder falsch'
    if 'TIME' in et:
        return 'Time-Stop nach 14d flat — These hat nicht innerhalb Hold-Window getragen'
    if 'CRASH' in et:
        return 'Crash-Safety -10% — echtes Risk-Event, nicht Vola'
    if 'EVENT' in et:
        return 'Macro/News-Event hat These invalidiert'
    if 'TRANCHE' in et:
        return f'Tranche-Exit ({pnl_pct:+.1f}%) — Profit-Lock-Mechanik aktiv'
    return f'Exit ({pnl_pct:+.1f}%) — Lehre noch zu kondensieren'


def _send(msg: str, force_high: bool = False) -> None:
    """Push via discord_dispatcher.
    Phase 44u: Default MEDIUM (in Digest), HIGH nur bei Big-Loss/Big-Win."""
    try:
        from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM
        tier = TIER_HIGH if force_high else TIER_MEDIUM
        send_alert(msg[:1900], tier=tier, category='trade_lifecycle')
    except Exception as e:
        print(f'[trade_lifecycle] push fail: {e}', flush=True)


# ═══════════════════════════════════════════════════════════════════════════
# CLI: kann man manuell triggern fuer Smoke-Test
# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke-entry', action='store_true')
    ap.add_argument('--smoke-close', action='store_true')
    args = ap.parse_args()
    if args.smoke_entry:
        push_entry(ticker='TEST.X', strategy='SMOKE', entry=100.0, stop=93.0,
                    target=115.0, position_eur=1000.0, conviction=85,
                    thesis='Smoke-Test der Lifecycle-Push-Pipeline')
        print('Smoke entry pushed.')
    if args.smoke_close:
        push_close(ticker='TEST.X', strategy='SMOKE', entry=100.0,
                    exit_price=115.0, pnl_eur=150.0, pnl_pct=15.0,
                    exit_type='TARGET', hold_hours=18.5,
                    original_stop=93.0, original_target=115.0)
        print('Smoke close pushed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
