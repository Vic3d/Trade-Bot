#!/usr/bin/env python3
"""
API Quota Tracker — Sub-8 #5
=============================
Persistent Logger für externe API-Calls (Anthropic, Yahoo, NewsAPI).
Schlankes Modul: andere Scripts rufen `track(provider, kind, tokens=None,
status='ok', cost_usd=0.0)` auf, dieses Modul schreibt nach SQLite.

CLI-Modus zeigt Tages-Reports:
    python3 scripts/api_quota_tracker.py             # heute
    python3 scripts/api_quota_tracker.py --days 7    # 7-Tage-Übersicht
    python3 scripts/api_quota_tracker.py --discord   # heute + Discord-Push

Tabelle wird on-demand erstellt:
    api_quota_log(ts, provider, kind, tokens, status, cost_usd, note)
"""
from __future__ import annotations

import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

_SCHEMA_INIT = False


def _init_schema(conn) -> None:
    global _SCHEMA_INIT
    if _SCHEMA_INIT:
        return
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_quota_log (
            ts TEXT NOT NULL,
            provider TEXT NOT NULL,
            kind TEXT,
            tokens INTEGER,
            status TEXT,
            cost_usd REAL DEFAULT 0,
            note TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_quota_ts ON api_quota_log(ts, provider)"
    )
    conn.commit()
    _SCHEMA_INIT = True


def track(
    provider: str,
    kind: str = '',
    tokens: int | None = None,
    status: str = 'ok',
    cost_usd: float = 0.0,
    note: str = '',
) -> None:
    """Schreibt 1 API-Call-Event. Schlägt nie hart fehl (Tracking ist best-effort)."""
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        _init_schema(conn)
        conn.execute(
            "INSERT INTO api_quota_log (ts, provider, kind, tokens, status, cost_usd, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec='seconds'),
             provider, kind, tokens, status, cost_usd, note[:200]),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # Best effort — tracking darf nie den Caller killen
        print(f'api_quota.track failed: {e}', file=sys.stderr)


def report(days: int = 1) -> dict:
    """Aggregiert nach provider/status für die letzten N Tage."""
    conn = sqlite3.connect(str(DB))
    _init_schema(conn)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')
    rows = conn.execute("""
        SELECT provider, status,
               COUNT(*) as calls,
               COALESCE(SUM(tokens), 0) as tokens,
               COALESCE(SUM(cost_usd), 0) as cost
        FROM api_quota_log
        WHERE ts >= ?
        GROUP BY provider, status
        ORDER BY provider, status
    """, (cutoff,)).fetchall()
    conn.close()
    out: dict = {'days': days, 'cutoff': cutoff, 'providers': {}}
    for prov, status, calls, tokens, cost in rows:
        p = out['providers'].setdefault(prov, {
            'calls': 0, 'tokens': 0, 'cost_usd': 0.0, 'errors': 0,
        })
        p['calls'] += calls
        p['tokens'] += int(tokens or 0)
        p['cost_usd'] += float(cost or 0)
        if status not in ('ok', '200', 'success'):
            p['errors'] += calls
    return out


def format_report(rep: dict) -> str:
    lines = [f"📊 API Quota Report (letzte {rep['days']}d)"]
    if not rep['providers']:
        lines.append('  (keine Calls erfasst)')
        return '\n'.join(lines)
    total_cost = 0.0
    for prov, p in sorted(rep['providers'].items()):
        err_rate = (p['errors'] / p['calls'] * 100) if p['calls'] else 0
        lines.append(
            f"  {prov:12s}: {p['calls']:5d} calls, "
            f"{p['tokens']:>9,} tok, ${p['cost_usd']:.3f}"
            + (f" ⚠️ {err_rate:.0f}% errors" if err_rate > 5 else '')
        )
        total_cost += p['cost_usd']
    lines.append(f"  ─ Total Cost: ${total_cost:.3f}")
    return '\n'.join(lines)


def main():
    days = 1
    discord = False
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--days' and i + 1 < len(args):
            days = int(args[i + 1])
        if a == '--discord':
            discord = True
    rep = report(days=days)
    text = format_report(rep)
    print(text)
    if discord:
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from discord_sender import send
            send('```\n' + text + '\n```')
        except Exception as e:
            print(f'discord push fail: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
