#!/usr/bin/env python3
"""
Anomaly Brake — Sub-8 #4
=========================
Risiko-Bremse die sofort reagiert wenn das Portfolio in Schwierigkeiten gerät:

  TRIGGER 1: 5 Stop-Loss Exits in Folge (chronologisch nach close_date)
  TRIGGER 2: Tages-PnL realisiert < -500€
  TRIGGER 3: 3 OPEN Positionen alle gleichzeitig > -5% unrealized
  TRIGGER 4: Drawdown vom 30d-Hoch > 10%

Bei Trigger:
  - Setzt CEO-Directive auf 'HALT' für 24h (data/ceo_directive.json)
  - Sendet sofortigen Discord-Alert
  - Schreibt Anomaly-Log nach data/anomaly_brake_log.jsonl

Läuft alle 30min während Marktzeiten via scheduler_daemon.

USAGE:
    python3 scripts/anomaly_brake.py [--dry-run] [--test]
"""
from __future__ import annotations

import json
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
CEO_FILE = WS / 'data' / 'ceo_directive.json'
LOG_FILE = WS / 'data' / 'anomaly_brake_log.jsonl'
LAST_HALT = WS / 'data' / 'anomaly_brake_last_halt.txt'

CONSEC_SL_THRESHOLD = 5
DAILY_LOSS_THRESHOLD = -500.0
OPEN_DRAWDOWN_COUNT = 3
OPEN_DRAWDOWN_PCT = -5.0
PORTFOLIO_DRAWDOWN_PCT = -15.0  # Bear-Markt-tolerant; market-relativ siehe _portfolio_drawdown
HALT_DURATION_HOURS = 24
HALT_COOLDOWN_HOURS = 12


def _consec_sl(conn) -> tuple[bool, str]:
    rows = conn.execute("""
        SELECT exit_type, ticker, close_date FROM paper_portfolio
        WHERE status = 'CLOSED' AND close_date IS NOT NULL
        ORDER BY close_date DESC LIMIT ?
    """, (CONSEC_SL_THRESHOLD,)).fetchall()
    if len(rows) < CONSEC_SL_THRESHOLD:
        return False, ''
    sl_count = sum(1 for r in rows if (r[0] or '').upper() in ('SL', 'STOP_LOSS', 'STOP'))
    if sl_count >= CONSEC_SL_THRESHOLD:
        tickers = ','.join(r[1] for r in rows)
        return True, f'{CONSEC_SL_THRESHOLD} SL in Folge: {tickers}'
    return False, ''


def _daily_loss(conn) -> tuple[bool, str]:
    today = datetime.now().strftime('%Y-%m-%d')
    r = conn.execute("""
        SELECT COALESCE(SUM(pnl_eur), 0) FROM paper_portfolio
        WHERE status = 'CLOSED' AND close_date LIKE ?
    """, (f'{today}%',)).fetchone()
    pnl_today = float(r[0])
    if pnl_today < DAILY_LOSS_THRESHOLD:
        return True, f'Tages-PnL realisiert {pnl_today:+.0f}€ (< {DAILY_LOSS_THRESHOLD:.0f}€)'
    return False, ''


def _open_drawdown(conn) -> tuple[bool, str]:
    """Mehrere offene Positionen tief im Minus = Korrelations-Crash."""
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        sys.path.insert(0, str(WS / 'scripts/core'))
        from live_data import get_price_eur
    except Exception:
        return False, ''
    rows = conn.execute("""
        SELECT id, ticker, entry_price, shares FROM paper_portfolio
        WHERE status = 'OPEN'
    """).fetchall()
    deep_red = []
    for rid, ticker, entry, shares in rows:
        try:
            cur = get_price_eur(ticker)
            if not cur or cur <= 0:
                continue
            pct = (cur - entry) / entry * 100
            if pct < OPEN_DRAWDOWN_PCT:
                deep_red.append(f'{ticker}({pct:.1f}%)')
        except Exception:
            continue
    if len(deep_red) >= OPEN_DRAWDOWN_COUNT:
        return True, f'{len(deep_red)} Positionen tief im Minus: ' + ','.join(deep_red[:5])
    return False, ''


def _portfolio_drawdown(conn) -> tuple[bool, str]:
    """30d-Equity-Hoch vs aktuelle Equity, market-relativ.

    In starkem Bear-Markt (SPY -15%) wäre absolutes -10% Portfolio-DD normal.
    Daher: Trigger nur wenn Portfolio-DD den SPY-DD um >5pp unterschreitet
    (= echtes Underperformance-Signal). Fallback auf absolut wenn kein SPY.
    """
    fund = dict(conn.execute("SELECT key, value FROM paper_fund").fetchall())
    starting = float(fund.get('starting_capital', 25000))
    realized = float(fund.get('total_realized_pnl', 0))
    current_equity = starting + realized
    cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    closes = conn.execute("""
        SELECT pnl_eur FROM paper_portfolio
        WHERE status='CLOSED' AND close_date >= ?
        ORDER BY close_date ASC
    """, (cutoff,)).fetchall()
    equity = current_equity
    peak = current_equity
    for (pnl,) in reversed(closes):
        equity -= float(pnl or 0)
        if equity > peak:
            peak = equity
    if peak <= 0:
        return False, ''
    dd_pct = (current_equity - peak) / peak * 100

    # Markt-Baseline aus macro_daily.SPY
    spy_dd = None
    try:
        spy_rows = conn.execute("""
            SELECT value FROM macro_daily
            WHERE indicator='SPY' AND date >= ?
            ORDER BY date ASC
        """, (cutoff,)).fetchall()
        if len(spy_rows) >= 5:
            vals = [float(r[0]) for r in spy_rows if r[0]]
            spy_peak = max(vals)
            spy_now = vals[-1]
            spy_dd = (spy_now - spy_peak) / spy_peak * 100
    except Exception:
        pass

    if spy_dd is not None:
        # Underperformance-Trigger: Portfolio mind. 5pp schlechter als SPY
        if dd_pct < spy_dd - 5.0 and dd_pct < PORTFOLIO_DRAWDOWN_PCT:
            return True, (
                f'Underperformance: PF={dd_pct:.1f}% vs SPY={spy_dd:.1f}% '
                f'(peak={peak:.0f}€, jetzt={current_equity:.0f}€)'
            )
        return False, ''

    # Fallback ohne SPY: absoluter Threshold
    if dd_pct < PORTFOLIO_DRAWDOWN_PCT:
        return True, f'Drawdown vom 30d-Peak: {dd_pct:.1f}% (peak={peak:.0f}€)'
    return False, ''


def _set_halt(reason: str, dry_run: bool) -> None:
    if dry_run:
        print(f'[DRY] Würde CEO HALT setzen: {reason}')
        return
    try:
        existing = {}
        if CEO_FILE.exists():
            existing = json.loads(CEO_FILE.read_text())
        existing.update({
            'trading_halt': True,
            'halt_reason': f'Anomaly Brake: {reason}',
            'halt_until': (datetime.now(timezone.utc) + timedelta(hours=HALT_DURATION_HOURS)).isoformat(),
            'halt_set_by': 'anomaly_brake',
            'halt_set_at': datetime.now(timezone.utc).isoformat(),
        })
        CEO_FILE.write_text(json.dumps(existing, indent=2))
        LAST_HALT.write_text(datetime.now(timezone.utc).isoformat())
    except Exception as e:
        print(f'CEO HALT setzen fail: {e}', file=sys.stderr)


def _halt_cooldown_ok() -> bool:
    if not LAST_HALT.exists():
        return True
    try:
        last = datetime.fromisoformat(LAST_HALT.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds() / 3600 >= HALT_COOLDOWN_HOURS
    except Exception:
        return True


def _log_event(triggers: list[tuple[str, str]]) -> None:
    try:
        with LOG_FILE.open('a') as f:
            f.write(json.dumps({
                'ts': datetime.now(timezone.utc).isoformat(),
                'triggers': [{'name': n, 'detail': d} for n, d in triggers],
            }) + '\n')
    except Exception:
        pass


def _send_alert(msg: str) -> None:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_sender import send
        send(msg)
    except Exception as e:
        print(f'Discord-Alert failed: {e}', file=sys.stderr)


def run(dry_run: bool = False, test: bool = False) -> int:
    conn = sqlite3.connect(str(DB))
    triggers: list[tuple[str, str]] = []
    try:
        for name, fn in (
            ('consec_sl', _consec_sl),
            ('daily_loss', _daily_loss),
            ('open_drawdown', _open_drawdown),
            ('portfolio_drawdown', _portfolio_drawdown),
        ):
            try:
                fired, detail = fn(conn)
                if fired:
                    triggers.append((name, detail))
            except Exception as e:
                print(f'{name} crashed: {e}', file=sys.stderr)
    finally:
        conn.close()

    if test:
        triggers.append(('test_trigger', 'TEST mode'))

    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not triggers:
        print(f'[{ts}] Anomaly Brake ✅ keine Trigger')
        return 0

    _log_event(triggers)
    msg_lines = [f'🛑 **Anomaly Brake gefeuert** ({len(triggers)} Trigger):']
    for n, d in triggers:
        msg_lines.append(f'  • [{n}] {d}')

    if _halt_cooldown_ok():
        reason = '; '.join(f'{n}: {d}' for n, d in triggers)
        _set_halt(reason, dry_run)
        msg_lines.append(f'→ CEO HALT für {HALT_DURATION_HOURS}h gesetzt')
    else:
        msg_lines.append('→ HALT-Cooldown aktiv, kein neuer HALT')

    full = '\n'.join(msg_lines)
    print(full)
    if not dry_run:
        _send_alert(full)
    return 1


def main():
    sys.exit(run(dry_run='--dry-run' in sys.argv, test='--test' in sys.argv))


if __name__ == '__main__':
    main()
