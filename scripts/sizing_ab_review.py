#!/usr/bin/env python3
"""
sizing_ab_review.py — Wöchentlicher A/B-Test-Report (Mo 08:15 CEST).

Liest:
  - sizing_ab_log: welcher Mode wurde pro Trade verwendet, was hätte der andere ergeben
  - paper_portfolio: tatsächliche PnL pro Trade

Berechnet pro Mode:
  - n_trades, win_rate, avg_pnl_eur, total_pnl_eur, avg_position_eur
  - Counterfactual: Hätte Mode X auf den Trades von Mode Y ähnlich gut performt?

Discord-Output:
  📊 Sizing A/B-Test Status (Woche X)
  Conviction: 8 Trades, WR 50%, ∅ +45€, Total +360€, ∅ Pos 1200€
  Risk-Based: 7 Trades, WR 57%, ∅ +89€, Total +623€, ∅ Pos 1450€
  → Risk-Based führt aktuell mit +263€. Datenbasis noch zu klein für Conclusion.

Manuell triggern: python3 scripts/sizing_ab_review.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

sys.path.insert(0, str(WS / 'scripts'))


def _fetch_ab_with_pnl() -> list[dict]:
    """Joint sizing_ab_log mit paper_portfolio über (ticker, ~timestamp)."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Erst prüfen ob Tabelle existiert
    try:
        conn.execute('SELECT 1 FROM sizing_ab_log LIMIT 1').fetchone()
    except sqlite3.OperationalError:
        conn.close()
        return []

    rows = conn.execute("""
        SELECT
            ab.ticker,
            ab.strategy,
            ab.mode_used,
            ab.shares_used,
            ab.shares_conviction,
            ab.shares_risk_based,
            ab.position_eur_conviction,
            ab.position_eur_risk_based,
            ab.timestamp,
            pp.status,
            pp.pnl_eur,
            pp.pnl_pct,
            pp.entry_date,
            pp.close_date
        FROM sizing_ab_log ab
        LEFT JOIN paper_portfolio pp
            ON pp.ticker = ab.ticker
           AND pp.strategy = ab.strategy
           AND substr(pp.entry_date, 1, 10) = substr(ab.timestamp, 1, 10)
        ORDER BY ab.timestamp DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _compute_stats(trades: list[dict]) -> dict:
    """Stats pro Mode."""
    by_mode: dict[str, dict] = {}
    for t in trades:
        # Strip _fallback suffix für Stats
        mode = (t.get('mode_used') or '').replace('_fallback', '')
        if mode not in by_mode:
            by_mode[mode] = {'n': 0, 'closed': 0, 'wins': 0, 'pnl_eur': 0.0,
                             'pos_sum': 0.0, 'open': 0}
        s = by_mode[mode]
        s['n'] += 1
        # Position
        shares = t.get('shares_used') or 0
        if mode == 'conviction':
            s['pos_sum'] += t.get('position_eur_conviction') or 0
        elif mode == 'risk_based':
            s['pos_sum'] += t.get('position_eur_risk_based') or 0

        # PnL nur wenn closed
        if t.get('status') in ('WIN', 'LOSS', 'CLOSED'):
            s['closed'] += 1
            pnl = t.get('pnl_eur') or 0
            s['pnl_eur'] += pnl
            if pnl > 0:
                s['wins'] += 1
        else:
            s['open'] += 1

    # Kennzahlen ableiten
    for mode, s in by_mode.items():
        s['win_rate']   = (s['wins'] / s['closed'] * 100) if s['closed'] else 0
        s['avg_pnl']    = (s['pnl_eur'] / s['closed']) if s['closed'] else 0
        s['avg_pos']    = (s['pos_sum'] / s['n']) if s['n'] else 0
    return by_mode


def _format_discord(stats: dict, total_trades: int) -> str:
    if total_trades == 0:
        return ('📊 **Sizing A/B-Test Status**\n\n'
                '_Noch keine A/B-Trades registriert. Aktiviere mit:_\n'
                '`autonomy_config.json: {"sizing_mode": "ab_test"}`')

    lines = [f'📊 **Sizing A/B-Test Status** ({total_trades} Trades total)']
    lines.append('')

    for mode in ('conviction', 'risk_based'):
        s = stats.get(mode)
        if not s:
            lines.append(f'**{mode}:** _keine Trades_')
            continue
        lines.append(
            f'**{mode}:** {s["n"]} Trades '
            f'({s["closed"]} closed, {s["open"]} open)'
        )
        if s['closed']:
            lines.append(
                f'  · WR {s["win_rate"]:.0f}% | '
                f'∅ PnL **{s["avg_pnl"]:+.0f}€** | '
                f'Total **{s["pnl_eur"]:+.0f}€** | '
                f'∅ Pos {s["avg_pos"]:.0f}€'
            )
        else:
            lines.append(f'  · _Noch nichts geschlossen_ | ∅ Pos {s["avg_pos"]:.0f}€')

    # Verdict
    conv = stats.get('conviction', {})
    rb   = stats.get('risk_based', {})
    if conv.get('closed', 0) >= 3 and rb.get('closed', 0) >= 3:
        diff = rb.get('pnl_eur', 0) - conv.get('pnl_eur', 0)
        lead = 'Risk-Based' if diff > 0 else 'Conviction'
        lines.append('')
        lines.append(f'→ **{lead}** führt aktuell mit {abs(diff):+.0f}€ Differenz.')
        if conv.get('closed', 0) + rb.get('closed', 0) < 20:
            lines.append('_(Noch zu wenig Daten für Conclusion — min. 20 Trades empfohlen)_')
    else:
        lines.append('')
        lines.append('_Datenbasis zu klein — min. 3 closed Trades pro Mode nötig._')

    return '\n'.join(lines)


def main() -> int:
    trades = _fetch_ab_with_pnl()
    stats = _compute_stats(trades)
    msg = _format_discord(stats, len(trades))
    print(msg)
    try:
        from discord_dispatcher import send_alert, TIER_LOW
        send_alert(msg, tier=TIER_LOW, category='ab_test_review',
                   dedupe_key=f'ab_test_{datetime.now().strftime("%Y-W%U")}')
    except Exception as e:
        print(f'[ab-review] Discord-Send-Fehler: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
