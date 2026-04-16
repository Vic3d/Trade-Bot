#!/usr/bin/env python3
"""
Weekly Summary — Phase 7.11
============================
Fette Wochen-Zusammenfassung — Sonntag 21:00 CET.

Drei Sektionen:
  1. ZAHLEN     — P&L, Trades, Win-Rate, Fund-Value-Chart
  2. TOP & FLOP — bester + schlechtester Trade, aktivste Strategie
  3. LEHREN     — Learning-Engine Recommendations, Observation-Flags, Fokus nächste Woche

Output: EIN langer Discord-Block. Kopierfreundlich.

Cron via scheduler_daemon.py (Sonntag 21:00).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data' / 'trading.db'
LEARNINGS = WS / 'data' / 'trading_learnings.json'
OBS_LOG = WS / 'data' / 'observation_log.jsonl'
RUN_START = WS / 'data' / 'run_start.txt'

sys.path.insert(0, str(WS / 'scripts'))
BERLIN = ZoneInfo('Europe/Berlin')


def _conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def _week_range() -> tuple[date, date]:
    """Letzte 7 Tage (heute zurück). Montag bis Sonntag wenn heute So."""
    today = date.today()
    start = today - timedelta(days=6)
    return start, today


def _closed_in_range(start: date, end: date) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT ticker, strategy, entry_price, close_price, shares, pnl_eur as pnl, "
        "exit_type, entry_date, close_date "
        "FROM paper_portfolio "
        "WHERE status IN ('WIN','LOSS','CLOSED') "
        "AND close_date BETWEEN ? AND ? "
        "ORDER BY pnl_eur DESC",
        (start.isoformat(), end.isoformat() + ' 23:59:59'),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _opened_in_range(start: date, end: date) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT ticker, strategy, entry_date "
        "FROM paper_portfolio "
        "WHERE entry_date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat() + ' 23:59:59'),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _open_positions() -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT ticker, strategy, entry_price, shares, entry_date "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _fund_value_now() -> float | None:
    try:
        c = _conn()
        cash = c.execute(
            "SELECT value FROM paper_fund WHERE key='current_cash'"
        ).fetchone()
        cash_val = float(cash[0]) if cash else 0.0
        rows = c.execute(
            "SELECT shares, entry_price FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        pos_val = sum(float(r[0] or 0) * float(r[1] or 0) for r in rows)
        c.close()
        return round(cash_val + pos_val, 2)
    except Exception:
        return None


def _fund_sparkline() -> tuple[str, float | None, float | None]:
    """ASCII-Sparkline des fund_value der letzten 7 Tage (1 Sample/Tag, Median)."""
    if not OBS_LOG.exists():
        return '', None, None
    samples: dict[date, list[float]] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        with open(OBS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    o = json.loads(line)
                    ts = datetime.fromisoformat(o['ts'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                    fv = o.get('fund_value_eur')
                    if fv is None:
                        continue
                    d = ts.astimezone(BERLIN).date()
                    samples.setdefault(d, []).append(float(fv))
                except Exception:
                    continue
    except Exception:
        return '', None, None
    if not samples:
        return '', None, None
    days = sorted(samples.keys())
    medians = [sorted(samples[d])[len(samples[d]) // 2] for d in days]
    lo, hi = min(medians), max(medians)
    bars = '▁▂▃▄▅▆▇█'
    if hi == lo:
        spark = bars[0] * len(medians)
    else:
        spark = ''.join(bars[min(7, int((v - lo) / (hi - lo) * 7))] for v in medians)
    return f'{lo:.0f}€ {spark} {hi:.0f}€', medians[0], medians[-1]


def _obs_flags_week() -> dict[str, int]:
    counts: dict[str, int] = {}
    if not OBS_LOG.exists():
        return counts
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        with open(OBS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    o = json.loads(line)
                    ts = datetime.fromisoformat(o['ts'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                    for fl in o.get('flags', []):
                        counts[fl] = counts.get(fl, 0) + 1
                except Exception:
                    continue
    except Exception:
        pass
    return counts


def _learning_snapshot() -> list[str]:
    try:
        d = json.loads(LEARNINGS.read_text(encoding='utf-8'))
    except Exception:
        return []
    scores = d.get('strategy_scores') or d.get('scores') or {}
    lines = []
    for sid, s in scores.items():
        if not isinstance(s, dict):
            continue
        rec = s.get('recommendation') or s.get('status')
        wr = s.get('win_rate')
        pnl = s.get('total_pnl') or s.get('pnl')
        n = s.get('total_trades') or s.get('trades')
        if rec in ('SUSPEND', 'REDUCE', 'ELEVATE') and n and n >= 5:
            emoji = {'SUSPEND': '🛑', 'REDUCE': '⚠️', 'ELEVATE': '⬆️'}[rec]
            lines.append(
                f'{emoji} {sid}: {rec} — WR {wr*100 if wr else 0:.0f}%, '
                f'P&L {pnl or 0:+.0f}€, {n} Trades'
            )
    return lines[:8]


def _week_number() -> int | None:
    if not RUN_START.exists():
        return None
    try:
        start = date.fromisoformat(RUN_START.read_text().strip())
        days = (date.today() - start).days
        return days // 7 + 1
    except Exception:
        return None


def _render_message() -> str:
    start, end = _week_range()
    closed = _closed_in_range(start, end)
    opened = _opened_in_range(start, end)
    open_pos = _open_positions()
    fund_now = _fund_value_now()
    spark, fund_start, fund_end = _fund_sparkline()
    flags = _obs_flags_week()
    learn = _learning_snapshot()

    wins = [t for t in closed if (t.get('pnl') or 0) > 0]
    losses = [t for t in closed if (t.get('pnl') or 0) < 0]
    total_pnl = sum(float(t.get('pnl') or 0) for t in closed)
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win = (sum(float(t['pnl']) for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum(float(t['pnl']) for t in losses) / len(losses)) if losses else 0
    wk = _week_number()

    head = f"📋 **Wochen-Review"
    if wk:
        head += f" — Woche {wk}"
    head += f" ({start.strftime('%d.%m')} – {end.strftime('%d.%m.%Y')})**"

    lines = [head, "━" * 35]

    # ── 1. Zahlen ──
    lines.append("\n**🔢 ZAHLEN**")
    lines.append(f"  Fund-Value:  {fund_now if fund_now else '?'}€")
    if spark:
        lines.append(f"  7-Tage-Chart: {spark}")
    if fund_start and fund_end:
        wk_delta = fund_end - fund_start
        wk_delta_pct = wk_delta / fund_start * 100
        lines.append(f"  Wochen-Δ:    {wk_delta:+.0f}€ ({wk_delta_pct:+.2f}%)")
    lines.append(f"  Closed:      {len(closed)} Trades  (P&L {total_pnl:+.0f}€)")
    lines.append(f"  Win-Rate:    {win_rate:.0f}%  ({len(wins)}W / {len(losses)}L)")
    if wins:
        lines.append(f"  Ø Winner:    {avg_win:+.0f}€")
    if losses:
        lines.append(f"  Ø Loser:     {avg_loss:+.0f}€")
    if wins and losses:
        rr = abs(avg_win / avg_loss)
        lines.append(f"  R:R:         {rr:.2f}")
    lines.append(f"  Opened:      {len(opened)} Trades")
    lines.append(f"  Offen jetzt: {len(open_pos)} Positionen")

    # ── 2. Top & Flop ──
    lines.append("\n**🏆 TOP & FLOP**")
    if closed:
        best = max(closed, key=lambda t: t.get('pnl') or 0)
        worst = min(closed, key=lambda t: t.get('pnl') or 0)
        lines.append(f"  🥇 Bester:  {best['ticker']} ({best['strategy']}) {best['pnl']:+.0f}€  via {best.get('exit_type') or '?'}")
        lines.append(f"  💀 Schlechtester: {worst['ticker']} ({worst['strategy']}) {worst['pnl']:+.0f}€  via {worst.get('exit_type') or '?'}")
    else:
        lines.append("  (keine geschlossenen Trades diese Woche)")

    # Strategie-Aktivität
    strat_count: dict[str, int] = {}
    for t in closed:
        strat_count[t['strategy']] = strat_count.get(t['strategy'], 0) + 1
    if strat_count:
        top_strat = sorted(strat_count.items(), key=lambda x: -x[1])[:3]
        lines.append(f"  Aktivste Strategien: " + ', '.join(f'{s} ({n})' for s, n in top_strat))

    # ── 3. Lehren ──
    lines.append("\n**📚 LEHREN & STATUS**")
    if learn:
        for l in learn:
            lines.append(f"  {l}")
    else:
        lines.append("  · keine auffälligen Recommendations diese Woche")

    if flags:
        crit = {f: n for f, n in flags.items()
                if f in ('heartbeat_stale', 'systemd_inactive', 'disk_low', 'scheduler_errors')}
        if crit:
            lines.append(f"\n  ⚠️ Health-Flags: " + ', '.join(f'{f}×{n}' for f, n in crit.items()))
        else:
            lines.append(f"\n  ✅ System 7 Tage ohne kritische Flags")

    # ── 4. Fokus nächste Woche ──
    lines.append("\n**🎯 FOKUS NÄCHSTE WOCHE**")
    focus = []
    if total_pnl < 0:
        focus.append("Negative Woche — Entry-Quality prüfen, CRV enger ziehen?")
    if len(losses) >= 3:
        focus.append("Mehrere Stops gezogen — gemeinsamer Nenner? (Sektor? Strategie? Zeitfenster?)")
    if len(opened) == 0:
        focus.append("Keine neuen Entries — Markt-Regime prüfen, Gates zu restriktiv?")
    if len(opened) >= 5:
        focus.append("Viele Entries — Qualität vor Quantität, 3/Woche Ziel einhalten")
    if len(open_pos) >= 8:
        focus.append("Viele offene Positionen — Exit-Disziplin?")
    if not focus:
        focus.append("System läuft sauber — Kurs halten, Disziplin")
    for f in focus:
        lines.append(f"  · {f}")

    lines.append("\n_Albert 🎩 — bis Montag._")
    return "\n".join(lines)


def send_summary() -> bool:
    msg = _render_message()
    try:
        from discord_sender import send
        ok = send(msg)
        print(f"Weekly Summary sent: {bool(ok)}")
        return bool(ok)
    except Exception as e:
        print(f"Weekly Summary send failed: {e}")
        print("---")
        print(msg)
        return False


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='Nur printen, nicht senden')
    args = ap.parse_args()
    if args.dry:
        print(_render_message())
    else:
        send_summary()
