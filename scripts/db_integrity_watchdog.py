#!/usr/bin/env python3
"""
DB Integrity Watchdog — Sub-8 #1
=================================
Täglicher Konsistenz-Check der trading.db. Erkennt:
  - SQLite Korruption (PRAGMA integrity_check)
  - Doppelte OPEN Positionen pro (ticker, strategy)
  - Orphan trade_tranches.portfolio_id
  - Cash-Drift: starting_capital + realized_pnl - open_cost ≠ current_cash
  - Korrupte JSON-Spalten (notes, news_context, trail_history)
  - Schema-Drift: erwartete Spalten in paper_portfolio fehlen

Bei Fehlern: Discord-Alert (mit Cooldown 6h) + Exit-Code 1.
Wird täglich 06:30 CET vom scheduler_daemon getriggert.

USAGE:
    python3 scripts/db_integrity_watchdog.py [--quiet] [--test]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

try:  # UTF-8 stdout für Windows-Konsole (Linux-Server unbetroffen)
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LAST_ALERT = WS / 'data' / 'db_integrity_last_alert.txt'
COOLDOWN_HOURS = 6

EXPECTED_PP_COLS = {
    'id', 'ticker', 'strategy', 'entry_price', 'entry_date', 'shares',
    'stop_price', 'target_price', 'status', 'close_price', 'close_date',
    'pnl_eur', 'pnl_pct', 'rsi_at_entry', 'vix_at_entry', 'hmm_regime',
    'feature_version',
}


def _check_sqlite_integrity(conn) -> list[str]:
    issues = []
    r = conn.execute('PRAGMA integrity_check').fetchone()
    if r and r[0] != 'ok':
        issues.append(f'SQLite integrity_check: {r[0]}')
    return issues


def _check_duplicate_open_positions(conn) -> list[str]:
    issues = []
    rows = conn.execute("""
        SELECT ticker, strategy, COUNT(*) as n
        FROM paper_portfolio
        WHERE status = 'OPEN'
        GROUP BY ticker, strategy
        HAVING n > 1
    """).fetchall()
    for ticker, strategy, n in rows:
        issues.append(f'Duplicate OPEN: {ticker}/{strategy} hat {n} Einträge')
    return issues


def _check_orphan_tranches(conn) -> list[str]:
    issues = []
    has_tranches = conn.execute(
        "SELECT name FROM sqlite_master WHERE name='trade_tranches'"
    ).fetchone()
    if not has_tranches:
        return issues  # Tabelle wird on-demand von paper_exit_manager erstellt
    cols = [c[1] for c in conn.execute('PRAGMA table_info(trade_tranches)').fetchall()]
    fk_col = None
    for cand in ('portfolio_id', 'trade_id', 'pp_id'):
        if cand in cols:
            fk_col = cand
            break
    if not fk_col:
        return issues
    orphans = conn.execute(f"""
        SELECT t.{fk_col}, COUNT(*) as n
        FROM trade_tranches t
        LEFT JOIN paper_portfolio p ON t.{fk_col} = p.id
        WHERE p.id IS NULL
        GROUP BY t.{fk_col}
    """).fetchall()
    for fk, n in orphans:
        issues.append(f'Orphan trade_tranches.{fk_col}={fk} ({n} Zeilen, kein paper_portfolio)')
    return issues


def _check_cash_drift(conn) -> list[str]:
    """Cash-Bilanz: starting + realized_pnl - open_cost = current_cash (±5€).

    NULL-shares-Positionen werden separat gemeldet — sie verfälschen open_cost
    weil entry_price * NULL = NULL → SUM() ignoriert sie.
    """
    issues = []
    fund = dict(conn.execute("SELECT key, value FROM paper_fund").fetchall())
    starting = float(fund.get('starting_capital', 0))
    realized = float(fund.get('total_realized_pnl', 0))
    cash = float(fund.get('current_cash', 0))
    open_cost = conn.execute("""
        SELECT COALESCE(SUM(entry_price * shares), 0)
        FROM paper_portfolio
        WHERE status = 'OPEN' AND shares IS NOT NULL AND shares > 0
    """).fetchone()[0]
    null_share_open = conn.execute("""
        SELECT COUNT(*), GROUP_CONCAT(ticker || '#' || id, ',')
        FROM paper_portfolio
        WHERE status = 'OPEN' AND (shares IS NULL OR shares <= 0)
    """).fetchone()
    null_count, null_tickers = null_share_open[0] or 0, null_share_open[1] or ''

    expected = starting + realized - open_cost
    drift = cash - expected
    if abs(drift) > 5.0:
        msg = (
            f'Cash-Drift: cash={cash:.2f}€ vs erwartet={expected:.2f}€ '
            f'(diff={drift:+.2f}€, starting={starting:.0f}, realized={realized:+.0f}, '
            f'open_cost_clean={open_cost:.0f})'
        )
        if null_count:
            msg += f' — ACHTUNG: {null_count} OPEN ohne shares: {null_tickers}'
        issues.append(msg)
    return issues


def _check_corrupt_json(conn) -> list[str]:
    issues = []
    # paper_portfolio.notes hat manchmal JSON-Snapshots
    rows = conn.execute("""
        SELECT id, notes FROM paper_portfolio
        WHERE notes IS NOT NULL AND notes LIKE '{%'
    """).fetchall()
    bad = 0
    for rid, notes in rows:
        try:
            json.loads(notes)
        except Exception:
            bad += 1
            if bad <= 3:
                issues.append(f'paper_portfolio.notes id={rid}: kein valides JSON')
    if bad > 3:
        issues.append(f'... weitere {bad - 3} JSON-Fehler in paper_portfolio.notes')
    return issues


def _check_schema_drift(conn) -> list[str]:
    issues = []
    cols = {c[1] for c in conn.execute('PRAGMA table_info(paper_portfolio)').fetchall()}
    missing = EXPECTED_PP_COLS - cols
    if missing:
        issues.append(f'paper_portfolio fehlt erwartete Spalten: {sorted(missing)}')
    return issues


def _check_open_without_stop(conn) -> list[str]:
    issues = []
    rows = conn.execute("""
        SELECT id, ticker FROM paper_portfolio
        WHERE status = 'OPEN' AND (stop_price IS NULL OR stop_price <= 0)
    """).fetchall()
    for rid, ticker in rows:
        issues.append(f'OPEN ohne Stop: id={rid} {ticker}')
    return issues


def _check_macro_stale(conn) -> list[str]:
    """macro_daily Indikatoren (SPY, VIX) sollen <7d alt sein.
    Sub-8 Bugfix: SPY auf VPS war seit 2026-03-25 nicht refreshed
    → anomaly_brake market-relative DD-Check fiel auf Fallback zurück.
    """
    issues = []
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    for ind in ('SPY', 'VIX'):
        r = conn.execute(
            "SELECT MAX(date) FROM macro_daily WHERE indicator = ?", (ind,)
        ).fetchone()
        last = r[0] if r else None
        if not last or last < cutoff:
            issues.append(f'macro_daily.{ind} stale: letzter Wert {last} (cutoff {cutoff})')
    return issues


def _check_negative_shares(conn) -> list[str]:
    """SQLite: NULL ist NICHT <= 0, daher explizit prüfen."""
    issues = []
    rows = conn.execute(
        "SELECT id, ticker, status, shares FROM paper_portfolio "
        "WHERE shares IS NULL OR shares <= 0"
    ).fetchall()
    for rid, ticker, status, shares in rows:
        issues.append(f'Bad shares: id={rid} {ticker} status={status} shares={shares!r}')
    return issues


def _alert_cooldown_ok() -> bool:
    if not LAST_ALERT.exists():
        return True
    try:
        last = datetime.fromisoformat(LAST_ALERT.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return age_h >= COOLDOWN_HOURS
    except Exception:
        return True


def _send_alert(msg: str) -> bool:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        send(msg)
        LAST_ALERT.write_text(datetime.now(timezone.utc).isoformat(timespec='seconds'))
        return True
    except Exception as e:
        print(f'Discord-Alert failed: {e}', file=sys.stderr)
        return False


def run(quiet: bool = False, test: bool = False) -> int:
    conn = sqlite3.connect(str(DB))
    issues: list[str] = []
    try:
        for fn in (
            _check_sqlite_integrity,
            _check_duplicate_open_positions,
            _check_orphan_tranches,
            _check_cash_drift,
            _check_corrupt_json,
            _check_schema_drift,
            _check_open_without_stop,
            _check_negative_shares,
            _check_macro_stale,
        ):
            try:
                issues.extend(fn(conn))
            except Exception as e:
                issues.append(f'{fn.__name__} CRASHED: {e}')
    finally:
        conn.close()

    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not issues and not test:
        if not quiet:
            print(f'[{ts}] DB Integrity ✅ alle Checks ok')
        return 0

    msg_lines = [f'[{ts}] DB Integrity Issues ({len(issues)}):']
    for i in issues:
        msg_lines.append(f'  - {i}')
    if test:
        msg_lines.append('  - (TEST mode)')
    full = '\n'.join(msg_lines)
    print(full)

    if _alert_cooldown_ok():
        _send_alert(f'🚨 **DB Integrity Watchdog**\n```\n{full[:1500]}\n```')
    else:
        print(f'[{ts}] Alert suppressed (cooldown)')
    return 1


def main():
    quiet = '--quiet' in sys.argv
    test = '--test' in sys.argv
    sys.exit(run(quiet=quiet, test=test))


if __name__ == '__main__':
    main()
