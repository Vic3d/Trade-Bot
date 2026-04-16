#!/usr/bin/env python3
"""
Honesty Report — Phase 6.9
============================
Tägliche 22:00 CET "Wahrheits-Report" via Discord.

Vergleicht:
  - paper_fund (key-value cache) vs fund_truth (live berechnet)
  - Gemeldete vs tatsächliche Win-Rate
  - Gemeldete vs tatsächliche P&L
  - Offene Positionen mit Mark-to-Market

Ziel: Keine heimlichen Diskrepanzen mehr. Alles was falsch läuft MUSS
hier sichtbar werden.

Nutzt:
  - scripts/fund_truth.py   ← Live-Truth
  - data/trading.db         ← paper_fund cache
  - data/ceo_decisions      ← heutige Entscheidungen

Usage:
  python3 scripts/honesty_report.py              # Send via Discord
  python3 scripts/honesty_report.py --dry-run    # Nur print
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
DB = WS / 'data' / 'trading.db'
DATA = WS / 'data'

DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '')


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _get_reported_cash(conn) -> float | None:
    row = conn.execute(
        "SELECT value FROM paper_fund WHERE key='current_cash'"
    ).fetchone()
    return float(row[0]) if row else None


def _winrate_stats(conn) -> dict:
    rows = conn.execute("""
        SELECT status, pnl_eur, strategy
        FROM paper_portfolio
        WHERE UPPER(status)='CLOSED'
    """).fetchall()
    total = len(rows)
    if total == 0:
        return {'total': 0, 'wins': 0, 'losses': 0, 'wr': 0.0, 'avg_pnl': 0.0}
    wins = sum(1 for r in rows if (r[1] or 0) > 0)
    losses = total - wins
    avg = sum((r[1] or 0) for r in rows) / total
    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'wr': wins / total * 100,
        'avg_pnl': avg,
    }


def _todays_ceo_decisions(conn) -> list[dict]:
    today = datetime.now(_BERLIN).date().isoformat()
    try:
        rows = conn.execute("""
            SELECT ts, decision, rationale
            FROM ceo_decisions
            WHERE ts LIKE ? || '%'
            ORDER BY ts DESC
        """, (today,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{'ts': r[0], 'decision': r[1], 'rationale': (r[2] or '')[:120]} for r in rows]


def _todays_trades(conn) -> dict:
    today = datetime.now(_BERLIN).date().isoformat()
    opened = conn.execute("""
        SELECT ticker, strategy, entry_price, shares
        FROM paper_portfolio
        WHERE entry_date LIKE ? || '%'
    """, (today,)).fetchall()
    closed = conn.execute("""
        SELECT ticker, strategy, pnl_eur, exit_reason
        FROM paper_portfolio
        WHERE UPPER(status)='CLOSED' AND exit_date LIKE ? || '%'
    """, (today,)).fetchall()
    return {
        'opened': [{'ticker': r[0], 'strategy': r[1], 'entry': r[2], 'shares': r[3]}
                   for r in opened],
        'closed': [{'ticker': r[0], 'strategy': r[1], 'pnl': r[2], 'reason': r[3]}
                   for r in closed],
    }


def _queue_depth() -> int:
    q = _load(DATA / 'deepdive_requests.json', [])
    return len(q) if isinstance(q, list) else 0


def _stale_flag() -> dict | None:
    f = _load(DATA / 'stale_data_flag.json', None)
    return f if isinstance(f, dict) else None


def build_report() -> str:
    from fund_truth import get_truth
    t = get_truth()

    conn = sqlite3.connect(str(DB))
    reported_cash = _get_reported_cash(conn)
    wr = _winrate_stats(conn)
    ceo = _todays_ceo_decisions(conn)
    trades = _todays_trades(conn)
    conn.close()

    stale = _stale_flag()
    qdepth = _queue_depth()

    # Discrepancy
    discr = (reported_cash - t['cash']) if reported_cash is not None else 0.0
    discr_flag = '🟢' if abs(discr) < 5 else ('🟡' if abs(discr) < 50 else '🔴')

    now = datetime.now(_BERLIN).strftime('%d.%m.%Y %H:%M')
    lines = [
        f'🧾 **Honesty Report — {now}**',
        '',
        '**Fund Truth vs Cache:**',
        f'  Reported cash (paper_fund):  {reported_cash:>10.2f}€' if reported_cash is not None else '  Reported cash: (fehlt)',
        f'  True cash (paper_portfolio): {t["cash"]:>10.2f}€',
        f'  Diskrepanz:                  {discr:>+10.2f}€ {discr_flag}',
        '',
        '**Portfolio:**',
        f'  Starting Capital:  {t["starting_capital"]:>10.2f}€',
        f'  Realized P&L:      {t["realized_pnl"]:>+10.2f}€ ({t["closed_trades"]} trades)',
        f'  Open Positions:    {t["open_positions"]}',
        f'    Entry-Wert:      {t["open_positions_entry_val"]:>10.2f}€',
        f'    MTM-Wert:        {t["open_positions_mtm_val"]:>10.2f}€',
        f'    Unrealized P&L:  {t["open_positions_unrealized_pnl"]:>+10.2f}€',
        f'  ─────',
        f'  Total Equity:      {t["total_equity"]:>10.2f}€',
        f'  Return:            {t["total_return_eur"]:>+10.2f}€ ({t["total_return_pct"]:+.2f}%)',
        '',
        '**Win-Rate (alle Trades CLOSED):**',
        f'  {wr["wins"]}/{wr["total"]} = {wr["wr"]:.1f}% (avg P&L {wr["avg_pnl"]:+.2f}€)',
    ]

    if trades['opened'] or trades['closed']:
        lines.append('')
        lines.append('**Heute:**')
        for o in trades['opened']:
            lines.append(f'  ↗️ OPEN {o["ticker"]:8} {o["strategy"]:10} '
                         f'{o["shares"]}×{o["entry"]:.2f}')
        for c in trades['closed']:
            em = '✅' if (c["pnl"] or 0) > 0 else '❌'
            lines.append(f'  {em} CLOSE {c["ticker"]:7} {c["strategy"]:10} '
                         f'{c["pnl"]:+7.2f}€ ({c["reason"]})')

    if ceo:
        lines.append('')
        lines.append(f'**CEO-Entscheidungen heute:** {len(ceo)}')
        for d in ceo[:4]:
            ts = d['ts'][11:16] if len(d['ts']) > 15 else d['ts']
            lines.append(f'  {ts} {d["decision"]:10} — {d["rationale"][:80]}')

    lines.append('')
    lines.append('**System-Status:**')
    lines.append(f'  Deep-Dive-Queue:   {qdepth} Tickers warten')
    if stale:
        sev = stale.get('severity', '?')
        issues = stale.get('issues', [])
        emoji = '🚨' if sev == 'critical' else '⚠️'
        lines.append(f'  {emoji} Stale-Data-Flag: {sev} ({len(issues)} Probleme)')
    else:
        lines.append('  ✅ Daten aktuell')

    # Open positions detail
    if t['positions']:
        lines.append('')
        lines.append('**Offene Positionen (MTM):**')
        for p in sorted(t['positions'], key=lambda x: x['unrealized_pnl'], reverse=True):
            arrow = '▲' if p['unrealized_pnl'] > 0 else ('▼' if p['unrealized_pnl'] < 0 else '–')
            lines.append(
                f'  {arrow} {p["ticker"]:10} {p["strategy"]:10} '
                f'{p["shares"]:>5.1f}×{p["entry"]:>7.2f}→{p["current"]:>7.2f} '
                f'{p["unrealized_pnl"]:>+7.2f}€ ({p["unrealized_pct"]:+.1f}%)'
            )

    return '\n'.join(lines)


def send_discord(msg: str) -> bool:
    if not DISCORD_WEBHOOK:
        print('⚠️  DISCORD_WEBHOOK_URL nicht gesetzt — skip send')
        return False
    # Discord hat 2000-char Limit, ggf. splitten
    chunks = []
    current = ''
    for line in msg.split('\n'):
        if len(current) + len(line) + 1 > 1900:
            chunks.append(current)
            current = line
        else:
            current = current + '\n' + line if current else line
    if current:
        chunks.append(current)

    for chunk in chunks:
        payload = json.dumps({'content': chunk}).encode('utf-8')
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=payload,
            headers={'Content-Type': 'application/json'},
        )
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            print(f'❌ Discord send failed: {e}')
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='Nur print, kein Discord')
    args = ap.parse_args()

    report = build_report()
    print(report)

    if not args.dry_run:
        ok = send_discord(report)
        print(f'\n{"✅" if ok else "❌"} Discord-Send: {"OK" if ok else "FAILED"}')


if __name__ == '__main__':
    main()
