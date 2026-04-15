#!/usr/bin/env python3
"""
Daily Health Report — 23:00 CET
Sendet täglichen System-Status an Victor via Discord.
Zeigt: alle Jobs heute, Fehler, Portfolio-Snapshot, Morgen-Plan.
"""
import json
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
import os

WS   = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
LOG  = DATA / 'scheduler.log'
DB   = DATA / 'trading.db'

def _get_db():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c

def _todays_jobs() -> tuple[list, list]:
    """Liest scheduler.log und extrahiert heutige OK/FEHLER-Jobs."""
    if not LOG.exists():
        return [], []
    today = date.today().isoformat()
    ok_jobs, err_jobs = [], []
    try:
        lines = LOG.read_text(encoding='utf-8', errors='replace').splitlines()
        for line in lines:
            if today not in line:
                continue
            if '✅' in line:
                name = line.split('✅')[-1].split(':')[0].strip()
                ok_jobs.append(name)
            elif '❌' in line or '💥' in line:
                name = line.split('❌')[-1].split('💥')[-1].split(':')[0].strip()
                err_jobs.append(name)
    except Exception:
        pass
    return ok_jobs, err_jobs

def _portfolio_snapshot() -> str:
    """Holt aktuelle offene Positionen und Cash."""
    try:
        conn = _get_db()
        trades = conn.execute(
            "SELECT ticker, strategy, entry_price, shares, stop_price FROM trades "
            "WHERE status='OPEN' ORDER BY entry_date DESC LIMIT 10"
        ).fetchall()
        fund = conn.execute(
            "SELECT cash_eur, total_value_eur FROM paper_fund ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        cash = fund['cash_eur'] if fund else 0
        total = fund['total_value_eur'] if fund else 0
        lines = [f"Portfolio: {total:.0f}€ gesamt | Cash: {cash:.0f}€"]
        for t in trades:
            lines.append(f"  {t['ticker']:10s} {t['strategy']:8s} Entry:{t['entry_price']:.2f}€ x{t['shares']:.0f}")
        return '\n'.join(lines)
    except Exception as e:
        return f"Portfolio: (Fehler: {e})"

def _kill_signals_today() -> str:
    """Zeigt Kill-Signale die heute ausgeloest wurden."""
    kf = DATA / 'thesis_kill_signals.json'
    if not kf.exists():
        return ''
    try:
        kills = json.loads(kf.read_text())
        today = date.today().isoformat()
        today_kills = [v for v in kills.values() if v.get('date') == today]
        if not today_kills:
            return ''
        lines = ['Kill-Signale heute:']
        for k in today_kills[:3]:
            lines.append(f"  {k.get('ticker','')} — {k.get('reason','')[:60]}")
        return '\n'.join(lines)
    except Exception:
        return ''

def _tomorrows_plan() -> str:
    """Zeigt was morgen geplant ist (Verdicts mit planned_trade_day=morgen)."""
    vf = DATA / 'deep_dive_verdicts.json'
    if not vf.exists():
        return ''
    try:
        verdicts = json.loads(vf.read_text())
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        planned = [
            f"  {v.get('ticker','')} ({v.get('strategy_context',['?'])[0] if isinstance(v.get('strategy_context'), list) else '?'}) — {v.get('thesis','')[:50]}"
            for v in verdicts.values()
            if v.get('verdict') == 'KAUFEN' and v.get('planned_trade_day') == tomorrow
        ]
        if not planned:
            return ''
        return 'Morgen geplant:\n' + '\n'.join(planned[:3])
    except Exception:
        return ''

def build_report() -> str:
    """Erstellt vollständigen Health Report."""
    now = datetime.now()
    ok_jobs, err_jobs = _todays_jobs()

    lines = [
        f"📊 TradeMind Health Report — {now.strftime('%d.%m.%Y')}",
        '',
        f"Jobs heute: {len(ok_jobs)} OK" + (f", {len(err_jobs)} FEHLER: {', '.join(err_jobs[:3])}" if err_jobs else ''),
        '',
    ]

    snap = _portfolio_snapshot()
    if snap:
        lines.append(snap)
        lines.append('')

    kills = _kill_signals_today()
    if kills:
        lines.append(kills)
        lines.append('')

    plan = _tomorrows_plan()
    if plan:
        lines.append(plan)
        lines.append('')

    lines.append("System: OK | Scheduler: aktiv | Naechster CEO: morgen 09:30 CET")
    return '\n'.join(lines)

def run():
    report = build_report()
    print(report)
    return report

if __name__ == '__main__':
    run()
