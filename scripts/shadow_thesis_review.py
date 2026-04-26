#!/usr/bin/env python3
"""
shadow_thesis_review.py — Wöchentlicher Thesen-Vergleich (Mo 08:30 CEST).

Liest shadow_trades der letzten 30 Tage, gruppiert nach Strategie, und
postet einen Vergleichs-Report nach Discord:

  📊 Thesen-Performance (Shadow + Real, letzte 30 Tage)

  🥇 PS_AUTO_RARE_EARTH:    +18.5% cum (8 Setups, WR 75%, exec 50%)
  🥈 PS1:                   +12.3% cum (12 Setups, WR 67%, exec 83%)
  🥉 PS_NVO:                 +5.1% cum (4 Setups, WR 50%, exec 100%)
  ❌ PM_X:                   -8.2% cum (6 Setups, WR 17%, exec 83%) → SUSPEND-Kandidat

  💔 Verschenktes Alpha (gut gescort, selten ausgeführt):
    PS_AUTO_RARE_EARTH:  +18.5% cum, exec nur 50% — mehr durchlassen?

  ⚠️ Konsequent schlecht:
    PM_X: 6 Setups, 5 LOSS — überdenken
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from shadow_trades import stats_per_strategy

WINDOW_DAYS = 30
MEMORY_OUT  = WS / 'memory' / 'shadow-thesis-report.md'


def _format_discord(stats: list[dict]) -> str:
    if not stats:
        return ('📊 **Thesen-Performance (Shadow)**\n\n'
                '_Noch keine Setups in den letzten 30d. Scanner war inaktiv?_')

    # Nur Strategien mit min. 2 Setups + min. 1 closed
    qualified = [s for s in stats if s['n_total'] >= 2
                 and (s['wins'] + s['losses'] + s['expired']) >= 1]
    if not qualified:
        return ('📊 **Thesen-Performance (Shadow)**\n\n'
                f'_{len(stats)} Strategien mit Setups, aber noch keine geschlossen. '
                f'Warte auf Preisentwicklung._')

    lines = [f'📊 **Thesen-Performance** (Shadow + Real, letzte {WINDOW_DAYS}d)']
    lines.append('')

    medals = ['🥇', '🥈', '🥉']
    for i, s in enumerate(qualified[:8]):
        # Top 3 Medaillen, danach Bullets
        prefix = medals[i] if i < 3 else '·'
        # Negative cum_pnl bekommt 'X' statt Medaille
        if s['cum_pnl_pct'] < 0:
            prefix = '❌'
        lines.append(
            f"{prefix} `{s['strategy']:<22s}` "
            f"**{s['cum_pnl_pct']:+.1f}%** cum | "
            f"{s['n_total']} Setups | "
            f"WR {s['win_rate']:.0f}% | "
            f"exec {s['execution_rate']:.0f}%"
        )

    # Insights: verschenktes Alpha (gut performt aber selten ausgeführt)
    missed = [s for s in qualified
              if s['cum_pnl_pct'] > 5 and s['execution_rate'] < 60]
    if missed:
        lines.append('')
        lines.append('💔 **Verschenktes Alpha** (gut gescort, selten ausgeführt):')
        for s in missed[:3]:
            lines.append(f"  · `{s['strategy']}` — {s['cum_pnl_pct']:+.1f}% cum, "
                         f"exec nur {s['execution_rate']:.0f}%. Mehr durchlassen?")

    # Konsequent schlecht
    bad = [s for s in qualified if s['cum_pnl_pct'] < -5 and s['n_total'] >= 3]
    if bad:
        lines.append('')
        lines.append('⚠️ **Konsequent schlecht** (SUSPEND-Kandidaten):')
        for s in bad[:3]:
            lines.append(f"  · `{s['strategy']}` — {s['n_total']} Setups, "
                         f"WR {s['win_rate']:.0f}%, cum {s['cum_pnl_pct']:+.1f}%")

    return '\n'.join(lines)


def _write_memory(stats: list[dict]) -> None:
    MEMORY_OUT.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    lines = [f'# Shadow-Thesis Review — {today}', '',
             f'Fenster: {WINDOW_DAYS}d | {len(stats)} Strategien aktiv', '']
    lines.append('| Strategy | n | WR | cum PnL% | exec% |')
    lines.append('|---|---|---|---|---|')
    for s in stats:
        lines.append(f"| {s['strategy']} | {s['n_total']} | "
                     f"{s['win_rate']:.0f}% | {s['cum_pnl_pct']:+.1f}% | "
                     f"{s['execution_rate']:.0f}% |")
    MEMORY_OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    stats = stats_per_strategy(WINDOW_DAYS)
    msg = _format_discord(stats)
    print(msg)
    _write_memory(stats)
    try:
        from discord_dispatcher import send_alert, TIER_MEDIUM
        send_alert(msg, tier=TIER_MEDIUM, category='shadow_thesis_review',
                   dedupe_key=f'shadow_thesis_{datetime.now().strftime("%Y-W%U")}')
    except Exception as e:
        print(f'[shadow-review] Discord-Send-Fehler: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
