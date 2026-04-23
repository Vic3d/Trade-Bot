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
DRIFT_STATE = WS / 'data' / 'drift_triage_state.json'
COOLDOWN_HOURS = 6
# Sub-8 V3 #3: Auto-Heal Schwellen
DRIFT_AUTOHEAL_MAX = 200.0   # > 200 EUR Drift → nie auto-heal (Mensch pruefen)
DRIFT_AUTOHEAL_PERSIST_HOURS = 4  # selber Drift muss 4h+ stabil sein
DRIFT_AUTOHEAL_COOLDOWN_H = 24  # nach Auto-Fix 24h Pause

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

    # Sub-8 V3 #6: Tranche-Reconciliation — schema-tolerant
    # Verschiedene Migrations-Stände nutzen tranche_num ODER tranche_nr,
    # exit_type ODER exit_reason. Dynamisch detecten.
    num_col = 'tranche_num' if 'tranche_num' in cols else (
        'tranche_nr' if 'tranche_nr' in cols else None)
    exit_type_col = 'exit_type' if 'exit_type' in cols else (
        'exit_reason' if 'exit_reason' in cols else None)
    has_created = 'created_at' in cols

    # 6a) OPEN-Tranchen deren paper_portfolio CLOSED ist → mit-schliessen
    stale = conn.execute(f"""
        SELECT t.id, t.{fk_col}, p.status, p.close_price, p.close_date
        FROM trade_tranches t
        JOIN paper_portfolio p ON t.{fk_col} = p.id
        WHERE t.status='OPEN' AND UPPER(p.status)='CLOSED'
    """).fetchall()
    if stale and exit_type_col:
        try:
            for tid, _fk, _st, cp, cd in stale:
                conn.execute(
                    f"UPDATE trade_tranches SET status='CLOSED', exit_price=?, "
                    f"exit_date=?, {exit_type_col}='AUTOHEAL_PARENT_CLOSED' WHERE id=?",
                    (cp, cd or datetime.now(timezone.utc).isoformat(timespec='seconds'), tid),
                )
            conn.commit()
            issues.append(
                f'Tranche-Reconcile: {len(stale)} OPEN-Tranchen geschlossen '
                f'(Parent paper_portfolio war CLOSED)'
            )
        except Exception as e:
            issues.append(f'Tranche-Reconcile FAIL: {e}')

    # 6b) OPEN paper_portfolio OHNE Tranchen → Trailing-Stops feuern nie
    if num_col:
        # NOT-NULL Spalten (außer id/PK) detecten — dynamisch befuellen
        notnull_cols = {c[1] for c in conn.execute(
            'PRAGMA table_info(trade_tranches)').fetchall() if c[3] == 1 and c[5] == 0}
        has_entry_price = 'entry_price' in cols
        missing = conn.execute(f"""
            SELECT p.id, p.ticker, p.shares, p.entry_price
            FROM paper_portfolio p
            LEFT JOIN (
                SELECT {fk_col} AS pid, COUNT(*) AS n
                FROM trade_tranches GROUP BY {fk_col}
            ) tc ON tc.pid = p.id
            WHERE UPPER(p.status)='OPEN' AND p.shares IS NOT NULL AND p.shares > 0
                  AND COALESCE(tc.n, 0) = 0
        """).fetchall()
        if missing:
            try:
                # Pflichtspalten — alle NOT NULL Spalten muessen befuellt werden
                cols_ins = [fk_col, num_col, 'shares', 'status']
                if has_entry_price:
                    cols_ins.append('entry_price')
                if has_created:
                    cols_ins.append('created_at')
                vals_ph_list = ['?'] * len(cols_ins)
                # created_at ist datetime('now')
                if has_created:
                    vals_ph_list[-1] = "datetime('now')"
                col_list = ', '.join(cols_ins)
                vals_ph = ', '.join(vals_ph_list)
                for pid, _tk, sh, ep in missing:
                    t1 = round(float(sh) / 3, 4)
                    t2 = round(float(sh) / 3, 4)
                    t3 = round(float(sh) - t1 - t2, 4)
                    ep_val = float(ep) if ep else 0.0
                    for i, s in enumerate([t1, t2, t3], 1):
                        params = [pid, i, s, 'OPEN']
                        if has_entry_price:
                            params.append(ep_val)
                        conn.execute(
                            f"INSERT INTO trade_tranches ({col_list}) VALUES ({vals_ph})",
                            tuple(params),
                        )
                conn.commit()
                tickers = ', '.join(t for _, t, _, _ in missing[:5])
                more = f' ...+{len(missing)-5}' if len(missing) > 5 else ''
                issues.append(
                    f'Tranche-Reconcile: {len(missing)} OPEN-Positionen ohne Tranchen '
                    f'erzeugt ({tickers}{more}) — Trailing-Stops jetzt aktiv'
                )
            except Exception as e:
                issues.append(f'Tranche-Backfill FAIL: {e}')

    # 6c) Klassische Orphan-Detection (FK zeigt auf nicht-existente paper_portfolio)
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
    # Sub-8 V2 (D): Fees auf OPEN Positionen mit einrechnen, falls Spalte existiert
    pp_cols = {c[1] for c in conn.execute('PRAGMA table_info(paper_portfolio)').fetchall()}
    fees_open = 0.0
    if 'fees' in pp_cols:
        r_fees = conn.execute("""
            SELECT COALESCE(SUM(fees), 0) FROM paper_portfolio
            WHERE status='OPEN' AND shares IS NOT NULL AND shares > 0
        """).fetchone()
        fees_open = float(r_fees[0] or 0)
    null_share_open = conn.execute("""
        SELECT COUNT(*), GROUP_CONCAT(ticker || '#' || id, ',')
        FROM paper_portfolio
        WHERE status = 'OPEN' AND (shares IS NULL OR shares <= 0)
    """).fetchone()
    null_count, null_tickers = null_share_open[0] or 0, null_share_open[1] or ''

    expected = starting + realized - open_cost - fees_open
    drift = cash - expected
    if abs(drift) > 5.0:
        msg = (
            f'Cash-Drift: cash={cash:.2f}€ vs erwartet={expected:.2f}€ '
            f'(diff={drift:+.2f}€, starting={starting:.0f}, realized={realized:+.0f}, '
            f'open_cost_clean={open_cost:.0f}, fees_open={fees_open:.0f})'
        )
        if null_count:
            msg += f' — ACHTUNG: {null_count} OPEN ohne shares: {null_tickers}'
        # Sub-8 V3 #3: Drift-Triage Auto-Heal
        heal_msg = _drift_triage_autoheal(drift, null_count)
        if heal_msg:
            msg += f'\n  → {heal_msg}'
        issues.append(msg)
    else:
        # Drift weg → State zuruecksetzen, Triage neu starten
        try:
            if DRIFT_STATE.exists():
                DRIFT_STATE.unlink()
        except Exception:
            pass
    return issues


def _drift_triage_autoheal(drift: float, null_count: int) -> str:
    """Sub-8 V3 #3: Versucht Cash-Drift automatisch zu reconcilen.

    Sicherheits-Regeln:
      - drift > DRIFT_AUTOHEAL_MAX (200 EUR): nie auto-heal (Bug-Symptom)
      - null_count > 0: nie auto-heal (echter Schema-Bug, kein Sync-Issue)
      - Nur heal wenn selber Drift (±5 EUR) >= PERSIST_HOURS stabil
      - Nach Heal 24h Cooldown
    """
    import subprocess
    now = datetime.now(timezone.utc)
    if abs(drift) > DRIFT_AUTOHEAL_MAX:
        return f'Auto-Heal SKIP — Drift |{drift:.0f}€| > {DRIFT_AUTOHEAL_MAX:.0f}€ (Mensch pruefen)'
    if null_count > 0:
        return f'Auto-Heal SKIP — {null_count} NULL-share Positionen (Schema-Bug, kein Sync-Issue)'

    state = {}
    try:
        if DRIFT_STATE.exists():
            state = json.loads(DRIFT_STATE.read_text())
    except Exception:
        state = {}

    last_fix_iso = state.get('last_autofix_at')
    if last_fix_iso:
        try:
            last_fix = datetime.fromisoformat(last_fix_iso)
            if last_fix.tzinfo is None:
                last_fix = last_fix.replace(tzinfo=timezone.utc)
            age_h = (now - last_fix).total_seconds() / 3600
            if age_h < DRIFT_AUTOHEAL_COOLDOWN_H:
                return f'Auto-Heal COOLDOWN — letzter Fix vor {age_h:.1f}h (<{DRIFT_AUTOHEAL_COOLDOWN_H}h)'
        except Exception:
            pass

    # Drift-Persistenz tracken
    first_seen_iso = state.get('first_seen_at')
    last_drift = state.get('last_drift')
    same = last_drift is not None and abs(float(last_drift) - drift) <= 5.0
    if same and first_seen_iso:
        try:
            first_seen = datetime.fromisoformat(first_seen_iso)
            if first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=timezone.utc)
            persist_h = (now - first_seen).total_seconds() / 3600
        except Exception:
            persist_h = 0
    else:
        persist_h = 0
        first_seen_iso = now.isoformat(timespec='seconds')

    if persist_h < DRIFT_AUTOHEAL_PERSIST_HOURS:
        # Persistenz noch nicht erreicht → State updaten und warten
        try:
            DRIFT_STATE.write_text(json.dumps({
                'first_seen_at': first_seen_iso,
                'last_drift': drift,
                'last_seen_at': now.isoformat(timespec='seconds'),
            }, indent=2))
        except Exception:
            pass
        return f'Auto-Heal WARTE — Drift {persist_h:.1f}h alt (braucht {DRIFT_AUTOHEAL_PERSIST_HOURS}h)'

    # Stabil + unter Limit + nicht im Cooldown → fix
    try:
        proc = subprocess.run(
            [sys.executable, str(WS / 'scripts' / 'fund_reconciliation.py'),
             '--fix', '--no-alert'],
            capture_output=True, text=True, timeout=60,
        )
        ok = proc.returncode == 0
        try:
            DRIFT_STATE.write_text(json.dumps({
                'first_seen_at': first_seen_iso,
                'last_drift': drift,
                'last_autofix_at': now.isoformat(timespec='seconds'),
                'last_autofix_drift': drift,
                'last_autofix_ok': ok,
            }, indent=2))
        except Exception:
            pass
        if ok:
            return f'Auto-Heal OK — fund_reconciliation --fix angewendet (drift {drift:+.2f}€)'
        return f'Auto-Heal FAIL — fund_reconciliation rc={proc.returncode}: {proc.stderr[:200]}'
    except Exception as e:
        return f'Auto-Heal FAIL — Exception: {e}'


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
    stale_inds = []
    for ind in ('SPY', 'VIX'):
        r = conn.execute(
            "SELECT MAX(date) FROM macro_daily WHERE indicator = ?", (ind,)
        ).fetchone()
        last = r[0] if r else None
        if not last or last < cutoff:
            issues.append(f'macro_daily.{ind} stale: letzter Wert {last} (cutoff {cutoff})')
            stale_inds.append(ind)
    # Sub-8 V2 (F): Auto-Heal — Refresh-Script ausführen wenn stale
    if stale_inds:
        try:
            import subprocess
            script = WS / 'scripts' / 'macro_indicator_refresh.py'
            if script.exists():
                r = subprocess.run(
                    [sys.executable, str(script), '--backfill-days', '14'],
                    timeout=60, capture_output=True, text=True
                )
                if r.returncode == 0:
                    issues.append(f'  → Auto-Heal: macro_indicator_refresh ausgeführt ({", ".join(stale_inds)})')
                else:
                    issues.append(f'  → Auto-Heal FAIL: rc={r.returncode} stderr={r.stderr[:200]}')
        except Exception as e:
            issues.append(f'  → Auto-Heal CRASH: {e}')
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


def _check_concentration(conn) -> list[str]:
    """Sub-8 V3 #2: Concentration-Watchdog.

    Warnt wenn eine Position >40% des Portfolio-Werts (open_cost) belegt
    oder Top-3 zusammen >70%. Ziel: ASML-style 51.9% Klumpenrisiko fruh
    sichtbar, bevor ein Earnings-Miss das Konto ueberproportional trifft.
    """
    issues: list[str] = []
    try:
        rows = conn.execute(
            "SELECT ticker, COALESCE(shares,0)*COALESCE(entry_price,0) AS cost "
            "FROM paper_portfolio WHERE status='open'"
        ).fetchall()
    except Exception as e:
        return [f'concentration query failed: {e}']
    costs = [(t, float(c)) for t, c in rows if c and c > 0]
    total = sum(c for _, c in costs)
    if total <= 0 or not costs:
        return issues
    costs.sort(key=lambda x: x[1], reverse=True)
    top1_t, top1_c = costs[0]
    top1_pct = top1_c / total * 100
    if top1_pct > 40.0:
        issues.append(
            f'CONCENTRATION single: {top1_t} = {top1_pct:.1f}% '
            f'({top1_c:.0f}EUR / {total:.0f}EUR portfolio) — Klumpenrisiko'
        )
    if len(costs) >= 3:
        top3_pct = sum(c for _, c in costs[:3]) / total * 100
        if top3_pct > 70.0:
            top3_names = ', '.join(t for t, _ in costs[:3])
            issues.append(
                f'CONCENTRATION top3: {top3_names} = {top3_pct:.1f}% — Diversifikation schwach'
            )
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
            _check_concentration,
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
