#!/usr/bin/env python3
"""
Daily Review — Phase 7.11
==========================
Reflektierender Tages-Rückblick. Läuft 22:15 CET nach evening_report.py.

Anders als evening_report (pure Metriken) ist das hier die **Erzählebene**:
  - Was ist heute gut gelaufen?
  - Was ist heute schlecht gelaufen?
  - Welche Muster sehen wir?
  - Was beobachten wir morgen?

Output: Discord-Message in Victor's Kanal, Format:
  📅 Tag X — 17.04.2026
  ━━━━━━━━━━━━━━━━━━━━━━━
  ✅ Wins: …
  ❌ Losses: …
  📊 Portfolio: …
  🔍 Muster: …
  ⏭️ Morgen: …

Cron via scheduler_daemon.py (Mo-Fr 22:15).
Run-Start-Marker: data/run_start.txt (ISO-Datum) — Tag X wird relativ berechnet.
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
RUN_START = WS / 'data' / 'run_start.txt'
LEARNINGS = WS / 'data' / 'trading_learnings.json'
OBS_LOG = WS / 'data' / 'observation_log.jsonl'

sys.path.insert(0, str(WS / 'scripts'))

BERLIN = ZoneInfo('Europe/Berlin')


def _conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def _day_number() -> int:
    """Tag X seit Run-Start. Schreibt Marker beim ersten Aufruf."""
    try:
        if not RUN_START.exists():
            RUN_START.write_text(date.today().isoformat())
            return 1
        start = date.fromisoformat(RUN_START.read_text().strip())
        return (date.today() - start).days + 1
    except Exception:
        return 0


def _today_range() -> tuple[str, str]:
    """Start/End als ISO-Datum für heute (CET)."""
    now = datetime.now(BERLIN)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59)
    return start.isoformat(), end.isoformat()


def _closed_today() -> list[dict]:
    """Trades die heute geschlossen wurden."""
    try:
        c = _conn()
        today = date.today().isoformat()
        rows = c.execute(
            "SELECT ticker, strategy, entry_price, close_price, shares, pnl_eur as pnl, "
            "exit_type, close_date, status "
            "FROM paper_portfolio "
            "WHERE status IN ('WIN','LOSS','CLOSED') "
            "AND COALESCE(archived_pre_reset,0)=0 "
            "AND close_date LIKE ? "
            "ORDER BY close_date",
            (today + '%',),
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _opened_today() -> list[dict]:
    """Trades die heute neu eröffnet wurden (noch OPEN)."""
    try:
        c = _conn()
        today = date.today().isoformat()
        rows = c.execute(
            "SELECT ticker, strategy, entry_price, shares "
            "FROM paper_portfolio "
            "WHERE status='OPEN' AND COALESCE(archived_pre_reset,0)=0 "
            "AND entry_date LIKE ? "
            "ORDER BY entry_date",
            (today + '%',),
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _open_positions() -> list[dict]:
    try:
        c = _conn()
        rows = c.execute(
            "SELECT ticker, strategy, entry_price, shares, "
            "COALESCE(shares,0) * COALESCE(entry_price,0) as size_eur, "
            "entry_date, COALESCE(archived_pre_reset,0) as archived "
            "FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _fund_value() -> float | None:
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


def _fund_yesterday() -> float | None:
    """Observation-Log: fund_value vor 24h."""
    if not OBS_LOG.exists():
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    best: tuple[datetime, float] | None = None
    try:
        with open(OBS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    o = json.loads(line)
                    ts = datetime.fromisoformat(o['ts'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    fv = o.get('fund_value_eur')
                    if fv is None:
                        continue
                    # Nimm den ältesten Snapshot innerhalb ±30min vor 24h
                    delta = abs((ts - cutoff).total_seconds())
                    if delta < 1800 and (best is None or delta < abs((best[0] - cutoff).total_seconds())):
                        best = (ts, float(fv))
                except Exception:
                    continue
    except Exception:
        return None
    return best[1] if best else None


def _obs_flags_today() -> dict[str, int]:
    """Observation-Flags-Histogramm für heute."""
    counts: dict[str, int] = {}
    if not OBS_LOG.exists():
        return counts
    today_start = datetime.now(BERLIN).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with open(OBS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    o = json.loads(line)
                    ts = datetime.fromisoformat(o['ts'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts.astimezone(BERLIN) < today_start:
                        continue
                    for fl in o.get('flags', []):
                        counts[fl] = counts.get(fl, 0) + 1
                except Exception:
                    continue
    except Exception:
        pass
    return counts


def _learning_deltas() -> list[str]:
    """Neue/geänderte Strategy-Recommendations vs gestern (best-effort)."""
    try:
        d = json.loads(LEARNINGS.read_text(encoding='utf-8'))
    except Exception:
        return []
    scores = d.get('strategy_scores') or d.get('scores') or {}
    notable = []
    for sid, s in scores.items():
        if isinstance(s, dict):
            rec = s.get('recommendation') or s.get('status')
            pnl = s.get('total_pnl') or s.get('pnl')
            if rec in ('SUSPEND', 'REDUCE') and pnl is not None and pnl < -100:
                notable.append(f'{sid}: {rec} (P&L {pnl:+.0f}€)')
            elif rec == 'ELEVATE' and pnl is not None and pnl > 200:
                notable.append(f'{sid}: ELEVATE (P&L {pnl:+.0f}€)')
    return notable[:5]


def _render_message() -> str:
    day = _day_number()
    today_str = date.today().strftime('%d.%m.%Y')
    closed = _closed_today()
    opened = _opened_today()
    open_pos = _open_positions()
    fund_now = _fund_value()
    fund_yday = _fund_yesterday()
    flags = _obs_flags_today()
    learn = _learning_deltas()

    wins = [t for t in closed if (t.get('pnl') or 0) > 0]
    losses = [t for t in closed if (t.get('pnl') or 0) < 0]
    total_pnl = sum(float(t.get('pnl') or 0) for t in closed)

    lines = [
        f"📅 **Tag {day} — {today_str}**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # ── Heute geschlossen ──
    if closed:
        lines.append(f"\n**📊 Heute geschlossen:** {len(closed)} Trade(s), P&L {total_pnl:+.0f}€")
        for t in wins:
            lines.append(f"  ✅ {t['ticker']} ({t['strategy']}) — {t['pnl']:+.0f}€ via {t.get('exit_type') or '?'}")
        for t in losses:
            lines.append(f"  ❌ {t['ticker']} ({t['strategy']}) — {t['pnl']:+.0f}€ via {t.get('exit_type') or '?'}")
    else:
        lines.append("\n**📊 Heute geschlossen:** keine")

    # ── Neue Positionen ──
    if opened:
        lines.append(f"\n**🆕 Neu eröffnet:** {len(opened)}")
        for t in opened:
            size = float(t.get('shares') or 0) * float(t.get('entry_price') or 0)
            lines.append(f"  ➡️ {t['ticker']} ({t['strategy']}) — {size:.0f}€")
    else:
        lines.append("\n**🆕 Neu eröffnet:** keine")

    # ── Portfolio ──
    delta_line = ""
    if fund_now is not None and fund_yday is not None:
        delta = fund_now - fund_yday
        delta_pct = delta / fund_yday * 100
        delta_line = f"  Δ 24h: {delta:+.0f}€ ({delta_pct:+.2f}%)\n"
    lines.append(f"\n**💰 Portfolio**")
    lines.append(f"  Fund-Value: {fund_now if fund_now else '?'}€")
    if delta_line:
        lines.append(delta_line.rstrip())
    new_pos = [p for p in open_pos if not p.get('archived')]
    pre_pos = [p for p in open_pos if p.get('archived')]
    lines.append(f"  Offene Positionen: {len(new_pos)} (Run) + {len(pre_pos)} (pre-reset)")
    for p in new_pos[:5]:
        lines.append(f"    • {p['ticker']} ({p['strategy']}) — {p['size_eur']:.0f}€")
    for p in pre_pos[:3]:
        lines.append(f"    · (pre-reset) {p['ticker']} ({p['strategy']}) — {p['size_eur']:.0f}€")

    # ── Muster / Lessons ──
    patterns = []
    if len(wins) >= 2 and not losses:
        patterns.append(f"Sauberer Tag — {len(wins)}/{len(wins)} Winner")
    if len(losses) >= 2 and not wins:
        patterns.append(f"Verlierer-Tag — {len(losses)} Stops gezogen, Root-Cause prüfen")
    if total_pnl < -200:
        patterns.append(f"Tages-Verlust {total_pnl:.0f}€ — Drawdown-Check")
    if len(opened) >= 2:
        patterns.append(f"Viele Entries heute ({len(opened)}) — Qualität vor Quantität?")
    if flags:
        critical = [f for f in flags if f in ('heartbeat_stale', 'systemd_inactive', 'disk_low', 'scheduler_errors')]
        if critical:
            patterns.append(f"Health-Flags: {', '.join(critical)}")
    if learn:
        patterns.extend(learn)

    lines.append("\n**🔍 Muster & Signale**")
    if patterns:
        for p in patterns:
            lines.append(f"  · {p}")
    else:
        lines.append("  · nichts Auffälliges")

    # ── Morgen ──
    lines.append("\n**⏭️ Morgen im Blick**")
    wd = datetime.now(BERLIN).weekday()
    if wd == 4:  # Freitag → Wochenende
        lines.append("  · Markt zu am WE — Wochenend-Review Sonntag 21:00")
    else:
        lines.append("  · Entry-Fenster 17-22h CET")
        lines.append(f"  · Offene Thesen monitoren ({len(open_pos)} Positionen)")
        if len(open_pos) >= 4:
            lines.append("  · Position-Dichte hoch, wenig Spielraum für Neue")

    lines.append("\n_Albert 🎩_")
    return "\n".join(lines)


def send_review() -> bool:
    msg = _render_message()
    try:
        from discord_sender import send
        ok = send(msg)
        print(f"Daily Review sent: {bool(ok)}")
        return bool(ok)
    except Exception as e:
        print(f"Daily Review send failed: {e}")
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
        send_review()
