#!/usr/bin/env python3
"""
Daily Digest — Phase 12-15 Integration
========================================

Sendet zweimal täglich eine gebündelte Zusammenfassung an Discord:

  08:30 CET — Morgen-Digest (gestern noch eingetroffene Events + Portfolio-Stand)
  20:00 CET — Abend-Digest  (Tages-Events + heutige geschlossene Trades + Lernloop)

Quellen:
  - discord_queue.json  ← Events aus Watchdog / DeepDive / ProposalExecutor
  - trading.db          ← Offene Positionen + heute geschlossene Trades
  - signal_alpha.json   ← Aktuelles Signal-Learning (falls vorhanden)
  - autonomy_config.json ← Autonomie-Modus

Kein LLM — rein regelbasiert.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))

DATA = WS / 'data'
DB = DATA / 'trading.db'


def _load(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def _send(msg: str) -> None:
    try:
        from discord_sender import send
        send(msg[:1900])
    except Exception as e:
        print(f'Discord send: {e}')


def _portfolio_block() -> str:
    """Portfolio-Status: Cash + offene Positionen mit P&L."""
    lines: list[str] = []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        cash_row = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
        cash = float(cash_row['value']) if cash_row else 0.0

        open_pos = c.execute("""
            SELECT ticker, strategy, entry_price, stop, position_size_eur,
                   entry_date, thesis_alive
            FROM trades WHERE status='OPEN'
            ORDER BY entry_date DESC
        """).fetchall()

        # latest prices
        price_rows = c.execute("""
            SELECT ticker, close FROM prices
            WHERE (ticker, date) IN (
                SELECT ticker, MAX(date) FROM prices GROUP BY ticker
            )
        """).fetchall()
        c.close()
        prices = {r['ticker']: r['close'] for r in price_rows}

        lines.append(f'💼 **Portfolio** — Cash: **{cash:,.0f}€**')
        if open_pos:
            for p in open_pos:
                t = p['ticker']
                ep = p['entry_price'] or 0
                cp = prices.get(t)
                if cp and ep:
                    pnl_pct = (cp - ep) / ep * 100
                    pnl_str = f'{pnl_pct:+.1f}%'
                else:
                    pnl_str = '—'
                alive = '' if p['thesis_alive'] else ' ⚠️thesis'
                lines.append(f'  {t} ({p["strategy"]}) {pnl_str}{alive}')
        else:
            lines.append('  _Keine offenen Positionen_')
    except Exception as e:
        lines.append(f'_Portfolio-Daten nicht verfügbar: {e}_')
    return '\n'.join(lines)


def _closed_today_block() -> str:
    """Zeigt heute geschlossene Trades mit Ergebnis und Lernlektion."""
    today = date.today().isoformat()
    lines: list[str] = []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        closed = c.execute("""
            SELECT ticker, strategy, entry_price, exit_price, pnl_eur, pnl_pct,
                   exit_type, holding_days, lessons
            FROM trades
            WHERE status='CLOSED' AND exit_date LIKE ?
            ORDER BY exit_date DESC
        """, (f'{today}%',)).fetchall()
        c.close()

        if not closed:
            return ''

        lines.append(f'\n📚 **Trades heute geschlossen** ({len(closed)})')
        for t in closed:
            pnl = t['pnl_eur'] or 0
            pct = t['pnl_pct'] or 0
            icon = '🟢' if pnl >= 0 else '🔴'
            exit_t = t['exit_type'] or '—'
            lesson = t['lessons'] or ''
            lines.append(
                f'  {icon} **{t["ticker"]}** ({t["strategy"]}) '
                f'{pct:+.1f}% / {pnl:+.0f}€ | Exit: {exit_t} | {t["holding_days"] or "?"}d'
            )
            if lesson:
                lines.append(f'    _↳ {lesson[:120]}_')
    except Exception as e:
        lines.append(f'_Closed-Trade-Daten: {e}_')
    return '\n'.join(lines)


def _cost_drag_block() -> str:
    """
    Phase 19a: aggregate transaction costs of this month's closed trades.
    Surfaces the total friction drag so Victor sees if trading
    frequency is killing the edge.
    """
    try:
        from datetime import date as _date
        today = _date.today()
        month_prefix = today.strftime('%Y-%m')

        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT ticker, entry_price, close_price, shares
            FROM paper_portfolio
            WHERE status IN ('WIN', 'CLOSED')
              AND close_date LIKE ?
        """, (f'{month_prefix}%',)).fetchall()
        c.close()

        if not rows:
            return ''

        sys.path.insert(0, str(WS / 'scripts'))
        from execution.transaction_costs import net_pnl as _net_pnl

        total_cost = 0.0
        total_gross = 0.0
        n = 0
        for r in rows:
            try:
                rt = _net_pnl(
                    ticker=r['ticker'],
                    entry_price=r['entry_price'] or 0,
                    exit_price=r['close_price'] or 0,
                    shares=r['shares'] or 0,
                    fx_rate=1.0,
                )
                total_cost += rt['total_costs_eur']
                total_gross += abs(rt['gross_pnl_eur'])
                n += 1
            except Exception:
                continue

        if n == 0:
            return ''

        lines = [
            f'\n💸 **Trading-Gebühren {month_prefix}**',
            f'  Trades geschlossen: {n}',
            f'  Gesamtkosten: **{total_cost:.0f}€** '
            f'({(total_cost/25000*100):.2f}% vom Startkapital)',
        ]
        if total_gross > 0:
            drag_pct = total_cost / total_gross * 100
            lines.append(f'  Kosten / Brutto-Bewegung: {drag_pct:.1f}%')
        return '\n'.join(lines)
    except Exception as e:
        return f'_Cost-Drag: {e}_'


def _learning_block() -> str:
    """Holt aktuellen Strategy-Performance-Snapshot aus trading_learnings.json."""
    lines: list[str] = []
    try:
        learnings = _load(DATA / 'trading_learnings.json', {})
        scores = learnings.get('strategy_scores', {})
        if not scores:
            return ''
        lines.append('\n📊 **Strategy Scores (Top / Bottom)**')
        ranked = sorted(scores.items(), key=lambda x: x[1].get('pnl_eur', 0), reverse=True)
        # Top 3
        for strat, s in ranked[:3]:
            wr = s.get('win_rate', 0) * 100
            pnl = s.get('pnl_eur', 0)
            n = s.get('trades', 0)
            rec = s.get('recommendation', '').replace('_', ' ')
            lines.append(f'  🟢 {strat}: WR {wr:.0f}% | {pnl:+.0f}€ | n={n} | {rec}')
        # Bottom 1 if negative
        if len(ranked) > 3:
            worst = ranked[-1]
            if worst[1].get('pnl_eur', 0) < 0:
                s = worst[1]
                lines.append(
                    f'  🔴 {worst[0]}: WR {s.get("win_rate", 0)*100:.0f}% '
                    f'| {s.get("pnl_eur", 0):+.0f}€ | {s.get("recommendation", "")}'
                )
    except Exception as e:
        lines.append(f'_Learning-Daten: {e}_')
    return '\n'.join(lines)


def _autonomy_block() -> str:
    cfg = _load(DATA / 'autonomy_config.json', {})
    mode = cfg.get('mode', '?')
    phase = cfg.get('phase', '?')
    icons = {'SHADOW': '👁️', 'LIVE': '🤖', 'OFF': '💤'}
    icon = icons.get(mode, '❓')
    return f'{icon} Autonomie: **{mode}** (Phase {phase})'


def morning_digest() -> None:
    """08:30 CET — Morgen-Digest."""
    from discord_queue import flush_and_send, queue_size

    n = queue_size()
    header = f'🌅 **Morgen-Digest** {date.today().isoformat()}'

    msg_parts = [header, '', _portfolio_block(), '', _autonomy_block()]
    preamble = '\n'.join(msg_parts)

    if n > 0:
        print(f'Flushing {n} queued events in morning digest...')
        flush_and_send(header=preamble, clear=True)
    else:
        _send(preamble)
    print('Morning digest sent')


def evening_digest() -> None:
    """20:00 CET — Abend-Digest."""
    from discord_queue import flush_and_send, queue_size

    n = queue_size()
    header = f'🌆 **Abend-Digest** {date.today().isoformat()}'

    msg_parts = [
        header,
        '',
        _portfolio_block(),
        _closed_today_block(),
        _cost_drag_block(),
        _learning_block(),
        '',
        _autonomy_block(),
    ]
    preamble = '\n'.join(p for p in msg_parts if p is not None)

    if n > 0:
        print(f'Flushing {n} queued events in evening digest...')
        flush_and_send(header=preamble, clear=True)
    else:
        _send(preamble)
    print('Evening digest sent')


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'evening'
    if mode == 'morning':
        morning_digest()
    else:
        evening_digest()


if __name__ == '__main__':
    main()
