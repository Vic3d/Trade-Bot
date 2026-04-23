#!/usr/bin/env python3
"""
api_server.py — TradeMind REST API + Dashboard
================================================
Öffentliche API für Dashboard + zukünftige Produkt-Integration.

Endpoints:
  GET /                       Dashboard HTML
  GET /api/dashboard-data     Alle Daten für Dashboard (ein Call)
  GET /api/portfolio          Offene Positionen
  GET /api/performance        Performance-Metriken
  GET /api/signals            Aktuelle Signale / Conviction-Scores
  GET /api/market             VIX, Regime, EUR/USD
  GET /api/strategies         Aktive Strategien + Win-Rates
  GET /api/theses             Alle Thesen aus strategies.json
  GET /api/health             Watchdogs + System-Status
  GET /api/risk               Risk Dashboard (Concentration, VaR, Korrelationen)
  GET /api/anomalies          Letzte Anomaly-Brake Trigger (24h)
  GET /api/recent-trades      Letzte 20 geschlossene Trades
  GET /api/discord-feed       Letzte 30 Discord-Messages (Albert + Victor)
  GET /api/jobs               Scheduler Job-Status (24h)
  GET /api/advisory/<id>      Trade-Erklärung für Trade-ID

Port: 8765 (lokal) oder via Hetzner/Vercel (Produkt)
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import base64
import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
DATA = WS / 'data'
PORT = 8765

# Optional: Basic-Auth. Wenn TRADEMIND_DASHBOARD_USER und _PASSWORD gesetzt sind,
# werden ALLE Requests (außer /favicon) mit HTTP Basic Auth geschützt.
AUTH_USER = _os.getenv('TRADEMIND_DASHBOARD_USER', '').strip()
AUTH_PASS = _os.getenv('TRADEMIND_DASHBOARD_PASSWORD', '').strip()
AUTH_REQUIRED = bool(AUTH_USER and AUTH_PASS)

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts/core'))


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def _safe_json(p: Path, default=None):
    if not p.exists():
        return default if default is not None else {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def _file_age_min(p: Path):
    if not p.exists():
        return None
    return round((datetime.now().timestamp() - p.stat().st_mtime) / 60, 1)


# ─── API Handler Funktionen ───────────────────────────────────────────────────

def api_portfolio(user_id='user_victor') -> dict:
    conn = get_db()
    rows = conn.execute('''
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               conviction, regime_at_entry, entry_date, style, shares
        FROM paper_portfolio
        WHERE UPPER(status)='OPEN' AND (user_id=? OR user_id IS NULL)
        ORDER BY entry_date DESC
    ''', (user_id,)).fetchall()

    positions = []
    for r in rows:
        price_row = conn.execute(
            'SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (r['ticker'],)
        ).fetchone()
        current = price_row['close'] if price_row else None
        pnl_pct = round((current - r['entry_price']) / r['entry_price'] * 100, 1) if current else None
        pnl_eur = round((current - r['entry_price']) * (r['shares'] or 0), 2) if current else None
        positions.append({
            'id':         r['id'],
            'ticker':     r['ticker'],
            'strategy':   r['strategy'],
            'shares':     r['shares'],
            'entry':      r['entry_price'],
            'stop':       r['stop_price'],
            'target':     r['target_price'],
            'conviction': r['conviction'],
            'regime':     r['regime_at_entry'],
            'style':      r['style'] or 'swing',
            'current':    current,
            'pnl_pct':    pnl_pct,
            'pnl_eur':    pnl_eur,
            'value_eur':  round((current or r['entry_price']) * (r['shares'] or 0), 2),
            'entry_date': r['entry_date'],
        })
    conn.close()
    return {'positions': positions, 'count': len(positions)}


def api_performance() -> dict:
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM performance_metrics ORDER BY date DESC LIMIT 1'
    ).fetchone()
    conn.close()
    if not row:
        return {}
    return dict(row)


def api_market() -> dict:
    conn = get_db()
    vix = conn.execute(
        "SELECT value, date FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    fx = conn.execute(
        "SELECT value FROM macro_daily WHERE indicator='EURUSD' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    spy = conn.execute(
        "SELECT value, date FROM macro_daily WHERE indicator='SPY' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    regime = conn.execute(
        'SELECT regime, date FROM regime_history ORDER BY date DESC LIMIT 1'
    ).fetchone()
    ceo = _safe_json(DATA / 'ceo_directive.json')
    conn.close()
    return {
        'vix':     {'value': vix['value'] if vix else None, 'date': vix['date'] if vix else None},
        'eurusd':  fx['value'] if fx else None,
        'spy':     {'value': spy['value'] if spy else None, 'date': spy['date'] if spy else None},
        'regime':  regime['regime'] if regime else 'UNKNOWN',
        'ceo_mode': ceo.get('mode', 'UNKNOWN'),
        'ceo_reason': ceo.get('mode_reason', ''),
        'ceo_regime': ceo.get('regime', ''),
        'ts':      datetime.now(timezone.utc).isoformat(),
    }


def api_strategies() -> dict:
    conn = get_db()
    rows = conn.execute('''
        SELECT strategy,
               COUNT(*) trades,
               SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) wins,
               SUM(pnl_eur) total_pnl,
               AVG(pnl_pct) avg_return
        FROM paper_portfolio
        WHERE UPPER(status) != 'OPEN'
        GROUP BY strategy
        HAVING trades >= 2
        ORDER BY total_pnl DESC
    ''').fetchall()
    conn.close()
    learnings = _safe_json(DATA / 'trading_learnings.json')
    learn_map = {}
    for k, v in (learnings.get('strategies') or {}).items():
        learn_map[k] = v.get('recommendation', 'OBSERVE')
    return {
        'strategies': [
            {
                'id':       r['strategy'],
                'trades':   r['trades'],
                'win_rate': round(r['wins'] / r['trades'] * 100, 1) if r['trades'] else 0,
                'pnl':      round(r['total_pnl'] or 0, 1),
                'avg_return': round(r['avg_return'] or 0, 1),
                'recommendation': learn_map.get(r['strategy'], 'OBSERVE'),
            }
            for r in rows
        ]
    }


def api_theses() -> dict:
    """Alle Thesen aus strategies.json mit Genesis + Status (Liste)."""
    s = _safe_json(DATA / 'strategies.json')
    out = []
    for sid, meta in s.items():
        if not isinstance(meta, dict):
            continue
        gen = meta.get('genesis', {}) or {}
        out.append({
            'id':       sid,
            'name':     meta.get('name', sid),
            'type':     meta.get('type', '?'),
            'status':   meta.get('status', 'active'),
            'health':   meta.get('health', ''),
            'sector':   meta.get('sector', ''),
            'created':  gen.get('created', ''),
            'trigger':  gen.get('trigger', ''),
            'logical_chain': gen.get('logical_chain', ''),
            'tickers':  meta.get('tickers') or meta.get('targets') or [],
            'conviction_current': gen.get('conviction_current'),
            'conviction_start':   gen.get('conviction_at_start'),
            'win_rate': meta.get('win_rate'),
            'n_trades': meta.get('n_trades'),
            'pnl':      meta.get('pnl'),
        })
    out.sort(key=lambda x: (x['status'] != 'active', x['id']))
    return {'theses': out, 'count': len(out)}


def api_thesis_detail(tid: str) -> dict:
    """Einzelne These mit allen Details (Genesis, Trigger, Sources, Counter-Args)."""
    s = _safe_json(DATA / 'strategies.json')
    meta = s.get(tid)
    if not isinstance(meta, dict):
        return {'error': f'Thesis {tid} not found'}
    gen = meta.get('genesis', {}) or {}
    perf = meta.get('performance', {}) or {}
    pmgmt = meta.get('position_management', {}) or {}
    return {
        'id':         tid,
        'name':       meta.get('name', tid),
        'type':       meta.get('type', '?'),
        'status':     meta.get('status', 'active'),
        'health':     meta.get('health', ''),
        'sector':     meta.get('sector', ''),
        'regime':     meta.get('regime', ''),
        'horizon_weeks': meta.get('horizon_weeks'),
        'thesis':     meta.get('thesis', ''),
        'entry_trigger': meta.get('entry_trigger', ''),
        'kill_trigger':  meta.get('kill_trigger', ''),
        'learning_question': meta.get('learning_question', ''),
        'catalyst':   meta.get('catalyst', ''),
        'tickers':    meta.get('tickers') or meta.get('targets') or [],
        'keywords_bullish': meta.get('keywords_bullish', []),
        'keywords_bearish': meta.get('keywords_bearish', []),
        'genesis': {
            'created':         gen.get('created', ''),
            'trigger':         gen.get('trigger', ''),
            'analysis_steps':  gen.get('analysis_steps', []),
            'logical_chain':   gen.get('logical_chain', ''),
            'counter_arguments_checked': gen.get('counter_arguments_checked', []),
            'sources':         gen.get('sources', []),
            'conviction_start': gen.get('conviction_at_start'),
            'conviction_current': gen.get('conviction_current'),
            'last_updated':    gen.get('last_updated', ''),
            'feedback_history': gen.get('feedback_history', []),
        },
        'performance': {
            'win_rate': meta.get('win_rate'),
            'n_trades': meta.get('n_trades'),
            'wins':     meta.get('wins'),
            'losses':   meta.get('losses'),
            'pnl':      meta.get('pnl'),
            'avg_pnl':  meta.get('avg_pnl'),
            'win_loss_ratio': meta.get('win_loss_ratio'),
        },
        'position_management': pmgmt,
        'last_evaluated': meta.get('last_evaluated', ''),
    }


def api_fund() -> dict:
    """Cash, Equity, Total Capital, P&L."""
    conn = get_db()
    fund = dict(conn.execute("SELECT key, value FROM paper_fund").fetchall())
    starting = float(fund.get('starting_capital', 25000))
    cash     = float(fund.get('current_cash', 0))
    realized = float(fund.get('total_realized_pnl', 0))
    # Equity = sum(market value of open positions)
    rows = conn.execute(
        "SELECT ticker, shares, entry_price FROM paper_portfolio WHERE UPPER(status)='OPEN'"
    ).fetchall()
    equity = 0.0
    unrealized = 0.0
    for r in rows:
        pr = conn.execute(
            'SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (r['ticker'],)
        ).fetchone()
        cur = pr['close'] if pr else r['entry_price']
        val = (cur or 0) * (r['shares'] or 0)
        equity += val
        unrealized += ((cur or r['entry_price']) - r['entry_price']) * (r['shares'] or 0)
    conn.close()
    total = cash + equity
    return {
        'starting_capital': round(starting, 2),
        'current_cash':     round(cash, 2),
        'equity_value':     round(equity, 2),
        'total_capital':    round(total, 2),
        'realized_pnl':     round(realized, 2),
        'unrealized_pnl':   round(unrealized, 2),
        'total_pnl':        round(total - starting, 2),
        'total_pnl_pct':    round((total - starting) / starting * 100, 2) if starting else 0,
        'cash_pct':         round(cash / total * 100, 1) if total else 0,
    }


def api_signals() -> dict:
    conn = get_db()
    gate = _safe_json(DATA / 'news_gate.json')
    positions = conn.execute('''
        SELECT ticker, strategy, conviction
        FROM paper_portfolio WHERE UPPER(status)='OPEN'
        ORDER BY conviction DESC NULLS LAST
    ''').fetchall()
    conn.close()
    return {
        'news_gate': {
            'relevant':    gate.get('relevant', False),
            'theses_hit':  gate.get('theses_hit', []),
            'hit_count':   gate.get('hit_count', 0),
        },
        'open_signals': [
            {'ticker': r['ticker'], 'strategy': r['strategy'], 'conviction': r['conviction']}
            for r in positions
        ],
    }


def api_health() -> dict:
    """Watchdog + Service Health."""
    def stat(p: Path, max_age_min: int):
        age = _file_age_min(p)
        if age is None:
            return {'status': 'MISSING', 'age_min': None, 'last_run': None}
        ok = age <= max_age_min
        last = None
        try:
            last = p.read_text(encoding='utf-8').strip()[:50]
        except Exception:
            pass
        return {'status': 'OK' if ok else 'STALE', 'age_min': age, 'last_run': last}

    return {
        'meta_health':   stat(DATA / 'meta_health_last_run.txt',   60),
        'anomaly_brake': stat(DATA / 'anomaly_brake_last_halt.txt', 24*60),
        'heartbeat':     stat(DATA / 'heartbeat_last.txt',          30),
        'scheduler_log': stat(DATA / 'scheduler.log',                5),
        'price_monitor': stat(DATA / 'price_monitor.log',           60),
        'last_db_alert': stat(DATA / 'db_integrity_last_alert.txt', 24*60),
        'ts':            datetime.now(timezone.utc).isoformat(),
    }


def api_risk() -> dict:
    """Concentration, Trim-Findings, Korrelations-Cluster, VaR (sofern verfügbar)."""
    conn = get_db()

    # Equity (cash + positions market value)
    rows = conn.execute(
        "SELECT ticker, shares, entry_price FROM paper_portfolio WHERE UPPER(status)='OPEN'"
    ).fetchall()
    total = 0.0
    breakdown = []
    for r in rows:
        pr = conn.execute(
            'SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (r['ticker'],)
        ).fetchone()
        cur = pr['close'] if pr else r['entry_price']
        val = (cur or 0) * (r['shares'] or 0)
        total += val
        breakdown.append({'ticker': r['ticker'], 'value': round(val, 2)})
    for b in breakdown:
        b['pct'] = round(b['value'] / total * 100, 1) if total else 0
    breakdown.sort(key=lambda x: -x['pct'])
    conn.close()

    trim_state = _safe_json(DATA / 'trim_advisor_state.json')
    correlations = _safe_json(DATA / 'correlations.json')

    findings = []
    for b in breakdown:
        if b['pct'] > 30:
            findings.append({
                'severity': 'HIGH',
                'kind':     'concentration_single',
                'msg':      f"{b['ticker']} = {b['pct']}% des Equity (Schwelle 30%)"
            })
    top3 = sum(b['pct'] for b in breakdown[:3])
    if top3 > 70:
        findings.append({
            'severity': 'MEDIUM',
            'kind':     'concentration_top3',
            'msg':      f"Top-3 = {top3:.1f}% (Schwelle 70%)"
        })

    return {
        'equity_eur':  round(total, 2),
        'breakdown':   breakdown,
        'findings':    findings,
        'trim_last':   trim_state,
        'correlations_updated': correlations.get('updated', 'n/a') if isinstance(correlations, dict) else 'n/a',
        'correlations_count':   len(correlations.get('tickers', [])) if isinstance(correlations, dict) else 0,
    }


def api_anomalies() -> dict:
    """Letzte 24h Anomaly-Brake Trigger."""
    p = DATA / 'anomaly_brake_log.jsonl'
    if not p.exists():
        return {'triggers': [], 'count': 0}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    out = []
    try:
        for line in p.read_text(encoding='utf-8').splitlines()[-200:]:
            try:
                e = json.loads(line)
                t = datetime.fromisoformat(e['ts'].replace('Z', '+00:00'))
                if t < cutoff:
                    continue
                out.append(e)
            except Exception:
                continue
    except Exception:
        pass
    return {'triggers': out[-30:], 'count': len(out)}


def api_recent_trades(limit: int = 20) -> dict:
    conn = get_db()
    rows = conn.execute(f'''
        SELECT id, ticker, strategy, shares, entry_price, close_price,
               pnl_eur, pnl_pct, exit_type, entry_date, close_date
        FROM paper_portfolio
        WHERE UPPER(status) != 'OPEN' AND close_date IS NOT NULL
        ORDER BY close_date DESC LIMIT {int(limit)}
    ''').fetchall()
    conn.close()
    return {
        'trades': [
            {
                'id':       r['id'],
                'ticker':   r['ticker'],
                'strategy': r['strategy'],
                'shares':   r['shares'],
                'entry':    r['entry_price'],
                'close':    r['close_price'],
                'pnl_eur':  round(r['pnl_eur'] or 0, 2),
                'pnl_pct':  round(r['pnl_pct'] or 0, 2),
                'exit_type': r['exit_type'],
                'entry_date': r['entry_date'],
                'close_date': r['close_date'],
            } for r in rows
        ]
    }


def api_discord_feed(limit: int = 30) -> dict:
    p = DATA / 'discord_chat_log.jsonl'
    if not p.exists():
        return {'messages': []}
    msgs = []
    try:
        for line in p.read_text(encoding='utf-8').splitlines()[-limit:]:
            try:
                msgs.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    return {'messages': msgs[::-1]}  # newest first


def api_jobs() -> dict:
    """Scheduler Job-Runs der letzten 24h aus scheduler.log."""
    p = DATA / 'scheduler.log'
    if not p.exists():
        return {'jobs': [], 'errors_24h': 0}
    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')
    errors = []
    okays = {}
    try:
        for ln in p.read_text(errors='replace').splitlines()[-3000:]:
            m = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(?:✅|❌|⏱️|💥)\s+([A-Za-z0-9 _\-/]+):\s+(.*)', ln)
            if not m:
                continue
            ts, name, msg = m.group(1), m.group(2).strip(), m.group(3)
            if ts[:16] < cutoff:
                continue
            if 'Fehler' in msg or 'Timeout' in msg or 'Exception' in msg:
                errors.append({'ts': ts, 'name': name, 'msg': msg})
            else:
                okays[name] = ts  # last-OK timestamp
    except Exception:
        pass
    return {
        'errors_24h': len(errors),
        'errors':     errors[-20:],
        'last_ok':    [{'name': k, 'ts': v} for k, v in sorted(okays.items())],
    }


def api_equity_curve(days: int = 90) -> dict:
    """Equity-Kurve synthetisch aus closed-trades cumsum + current fund."""
    conn = get_db()
    starting = 25000.0
    try:
        row = conn.execute("SELECT value FROM paper_fund WHERE key='starting_capital'").fetchone()
        if row: starting = float(row['value'])
    except Exception: pass

    # Cumsum realized P&L per day
    rows = conn.execute(f'''
        SELECT DATE(close_date) d, SUM(pnl_eur) pnl
        FROM paper_portfolio
        WHERE UPPER(status) != 'OPEN' AND close_date IS NOT NULL
          AND DATE(close_date) >= DATE('now', '-{int(days)} days')
        GROUP BY DATE(close_date) ORDER BY d
    ''').fetchall()
    conn.close()

    points = []
    cum = 0.0
    # Base point before the window to anchor
    if rows:
        for r in rows:
            cum += (r['pnl'] or 0)
            points.append({'date': r['d'], 'equity': round(starting + cum, 2), 'pnl_cum': round(cum, 2)})
    # Append today as current total
    fund = api_fund()
    today = datetime.now().strftime('%Y-%m-%d')
    if not points or points[-1]['date'] != today:
        points.append({'date': today, 'equity': fund['total_capital'], 'pnl_cum': round(fund['total_pnl'], 2)})
    return {'points': points, 'starting': starting, 'current': fund['total_capital']}


def api_price_history(ticker: str, days: int = 30) -> dict:
    conn = get_db()
    rows = conn.execute(f'''
        SELECT date, close FROM prices WHERE ticker=?
          AND date >= DATE('now', '-{int(days)} days')
        ORDER BY date
    ''', (ticker,)).fetchall()
    conn.close()
    return {'ticker': ticker, 'points': [{'date': r['date'], 'close': r['close']} for r in rows]}


def api_position_detail(pid: int) -> dict:
    conn = get_db()
    row = conn.execute('SELECT * FROM paper_portfolio WHERE id=?', (pid,)).fetchone()
    if not row:
        conn.close(); return {'error': f'Position {pid} nicht gefunden'}
    p = dict(row)
    # Advisory
    adv = conn.execute('SELECT * FROM trade_advisory WHERE trade_id=?', (pid,)).fetchone()
    p['advisory'] = dict(adv) if adv else None
    # Tranches
    try:
        tr = conn.execute('SELECT * FROM trade_tranches WHERE trade_id=? ORDER BY level', (pid,)).fetchall()
        p['tranches'] = [dict(r) for r in tr]
    except Exception:
        p['tranches'] = []
    # Price history (30d)
    hist = conn.execute('''
        SELECT date, close FROM prices WHERE ticker=?
          AND date >= DATE('now', '-60 days') ORDER BY date
    ''', (p['ticker'],)).fetchall()
    p['price_history'] = [{'date': r['date'], 'close': r['close']} for r in hist]
    # Aktueller Preis
    curr = conn.execute('SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (p['ticker'],)).fetchone()
    p['current'] = curr['close'] if curr else None
    if p['current'] and p.get('entry_price'):
        p['pnl_pct_now'] = round((p['current'] - p['entry_price']) / p['entry_price'] * 100, 2)
        p['pnl_eur_now'] = round((p['current'] - p['entry_price']) * (p.get('shares') or 0), 2)
    # News-Links
    try:
        nr = conn.execute('''
            SELECT n.headline, n.source, n.url, n.ts
            FROM trade_news_link l JOIN news_events n ON n.id = l.news_id
            WHERE l.trade_id=? ORDER BY n.ts DESC LIMIT 10
        ''', (pid,)).fetchall()
        p['news'] = [dict(r) for r in nr]
    except Exception:
        p['news'] = []
    # Target-ETA: simple velocity (last 7d avg daily move)
    p['target_eta_days'] = None
    if p.get('current') and p.get('target_price'):
        try:
            last7 = conn.execute('''
                SELECT close FROM prices WHERE ticker=?
                  AND date >= DATE('now', '-10 days') ORDER BY date
            ''', (p['ticker'],)).fetchall()
            closes = [r['close'] for r in last7 if r['close']]
            if len(closes) >= 3:
                daily_chg = (closes[-1] - closes[0]) / max(1, len(closes)-1)
                gap = p['target_price'] - p['current']
                if daily_chg != 0 and (gap > 0) == (daily_chg > 0):
                    p['target_eta_days'] = round(gap / daily_chg, 1)
        except Exception:
            pass
    conn.close()
    return p


def api_events_today() -> dict:
    """Chronologischer Event-Feed: Trades, Scheduler-Jobs, Anomalien, News."""
    events = []
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()
    # Trades today
    for r in conn.execute('''
        SELECT id, ticker, strategy, entry_date, close_date, pnl_eur, status, exit_type
        FROM paper_portfolio
        WHERE DATE(entry_date)=? OR DATE(close_date)=?
    ''', (today, today)).fetchall():
        if r['entry_date'] and r['entry_date'][:10] == today:
            events.append({'ts': r['entry_date'], 'kind': 'entry', 'icon': '🟢',
                           'msg': f"Entry: {r['ticker']} ({r['strategy']})"})
        if r['close_date'] and r['close_date'][:10] == today:
            pnl = r['pnl_eur'] or 0
            events.append({'ts': r['close_date'], 'kind': 'exit', 'icon': '🔴' if pnl<0 else '✅',
                           'msg': f"Exit: {r['ticker']} · {'+' if pnl>=0 else ''}{pnl:.0f}€ ({r['exit_type'] or '?'})"})
    conn.close()
    # Scheduler jobs today
    sched = DATA / 'scheduler.log'
    if sched.exists():
        try:
            for ln in sched.read_text(errors='replace').splitlines()[-1500:]:
                m = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(✅|❌|⏱️|💥)\s+([A-Za-z0-9 _\-/]+):\s+(.*)', ln)
                if not m: continue
                ts, sym, name, msg = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
                if not ts.startswith(today): continue
                events.append({'ts': ts, 'kind': 'job', 'icon': sym,
                               'msg': f"{name}: {msg[:80]}"})
        except Exception: pass
    events.sort(key=lambda e: e['ts'], reverse=True)
    return {'events': events[:100]}


def api_stats() -> dict:
    """Aggregierte Statistiken für Stats-Tab."""
    conn = get_db()
    # Monthly P&L
    monthly = conn.execute('''
        SELECT strftime('%Y-%m', close_date) m,
               SUM(pnl_eur) pnl,
               COUNT(*) n,
               SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) wins
        FROM paper_portfolio WHERE close_date IS NOT NULL AND UPPER(status)!='OPEN'
        GROUP BY m ORDER BY m
    ''').fetchall()
    # Sector breakdown (open + closed last 30d)
    sectors = conn.execute('''
        SELECT COALESCE(sector, 'unbekannt') s,
               COUNT(*) n, SUM(pnl_eur) pnl
        FROM paper_portfolio
        WHERE close_date IS NULL OR close_date >= DATE('now','-30 days')
        GROUP BY s ORDER BY n DESC
    ''').fetchall()
    # Exit-Type Verteilung
    exits = conn.execute('''
        SELECT COALESCE(exit_type, 'unbekannt') t, COUNT(*) n, SUM(pnl_eur) pnl
        FROM paper_portfolio WHERE UPPER(status)!='OPEN'
        GROUP BY t ORDER BY n DESC
    ''').fetchall()
    # Hold-Time Verteilung (Tage)
    holds = conn.execute('''
        SELECT CAST(julianday(close_date) - julianday(entry_date) AS INT) d, pnl_eur
        FROM paper_portfolio WHERE UPPER(status)!='OPEN' AND close_date IS NOT NULL
    ''').fetchall()
    bins = {'0-1': 0, '2-3': 0, '4-7': 0, '8-14': 0, '15-30': 0, '30+': 0}
    bins_pnl = {k: 0.0 for k in bins}
    for r in holds:
        d = r['d'] or 0
        k = '0-1' if d<=1 else '2-3' if d<=3 else '4-7' if d<=7 else '8-14' if d<=14 else '15-30' if d<=30 else '30+'
        bins[k] += 1
        bins_pnl[k] += (r['pnl_eur'] or 0)
    # Day-of-Week
    dow = conn.execute('''
        SELECT CAST(strftime('%w', close_date) AS INT) w,
               COUNT(*) n, SUM(pnl_eur) pnl
        FROM paper_portfolio WHERE UPPER(status)!='OPEN' AND close_date IS NOT NULL
        GROUP BY w
    ''').fetchall()
    dow_names = {0:'So',1:'Mo',2:'Di',3:'Mi',4:'Do',5:'Fr',6:'Sa'}
    # Winner vs Loser (expectancy)
    stats = conn.execute('''
        SELECT
            SUM(CASE WHEN pnl_eur > 0 THEN pnl_eur ELSE 0 END) total_wins,
            SUM(CASE WHEN pnl_eur < 0 THEN pnl_eur ELSE 0 END) total_losses,
            AVG(CASE WHEN pnl_eur > 0 THEN pnl_eur END) avg_win,
            AVG(CASE WHEN pnl_eur < 0 THEN pnl_eur END) avg_loss,
            COUNT(CASE WHEN pnl_eur > 0 THEN 1 END) n_wins,
            COUNT(CASE WHEN pnl_eur < 0 THEN 1 END) n_losses,
            MAX(pnl_eur) best,
            MIN(pnl_eur) worst
        FROM paper_portfolio WHERE UPPER(status)!='OPEN'
    ''').fetchone()
    conn.close()
    s = dict(stats) if stats else {}
    aw, al = s.get('avg_win') or 0, s.get('avg_loss') or 0
    nw, nl = s.get('n_wins') or 0, s.get('n_losses') or 0
    total = nw + nl
    wr = nw / total if total else 0
    expectancy = (wr * aw + (1-wr) * al) if total else 0
    profit_factor = abs((s.get('total_wins') or 0) / (s.get('total_losses') or -1)) if s.get('total_losses') else None

    return {
        'monthly':  [{'m': r['m'], 'pnl': round(r['pnl'] or 0, 2),
                      'trades': r['n'], 'win_rate': round((r['wins'] or 0)/max(1,r['n'])*100, 1)} for r in monthly],
        'sectors':  [{'sector': r['s'], 'n': r['n'], 'pnl': round(r['pnl'] or 0, 2)} for r in sectors],
        'exits':    [{'type': r['t'], 'n': r['n'], 'pnl': round(r['pnl'] or 0, 2)} for r in exits],
        'hold_bins': [{'bin': k, 'n': bins[k], 'pnl': round(bins_pnl[k], 2)} for k in bins],
        'dow':      [{'day': dow_names.get(r['w'],'?'), 'n': r['n'], 'pnl': round(r['pnl'] or 0, 2)} for r in dow],
        'summary': {
            'avg_win': round(aw, 2), 'avg_loss': round(al, 2),
            'n_wins': nw, 'n_losses': nl, 'win_rate': round(wr*100, 1),
            'expectancy': round(expectancy, 2),
            'profit_factor': round(profit_factor, 2) if profit_factor else None,
            'best': round(s.get('best') or 0, 2),
            'worst': round(s.get('worst') or 0, 2),
            'total_wins': round(s.get('total_wins') or 0, 2),
            'total_losses': round(s.get('total_losses') or 0, 2),
        }
    }


def api_risk_light() -> dict:
    """Ampel Grün/Gelb/Rot basierend auf DD, Konzentration, VIX, Cash-Ratio."""
    try:
        perf = api_performance()
        market = api_market()
        risk = api_risk()
        fund = api_fund()
        reasons = []
        level = 'green'
        dd = perf.get('drawdown_pct') or 0
        if dd > 15: level='red'; reasons.append(f'Drawdown {dd:.1f}% > 15%')
        elif dd > 10: level='yellow'; reasons.append(f'Drawdown {dd:.1f}% > 10%')
        vix = (market.get('vix') or {}).get('value') or 0
        if vix > 30:
            if level != 'red': level='red'
            reasons.append(f'VIX {vix:.1f} > 30 (Panik)')
        elif vix > 22 and level == 'green':
            level='yellow'; reasons.append(f'VIX {vix:.1f} > 22 (nervös)')
        high_findings = [f for f in (risk.get('findings') or []) if f.get('severity')=='HIGH']
        if high_findings:
            if level != 'red': level='red'
            reasons.append(f'{len(high_findings)} HIGH Konzentrations-Finding(s)')
        cash_pct = fund.get('cash_pct') or 0
        if cash_pct < 10:
            if level == 'green': level='yellow'
            reasons.append(f'Cash-Reserve {cash_pct:.1f}% < 10%')
        if not reasons: reasons.append('Alles im grünen Bereich')
        return {'level': level, 'reasons': reasons, 'drawdown_pct': dd, 'vix': vix, 'cash_pct': cash_pct}
    except Exception as e:
        return {'level': 'gray', 'reasons': [f'Fehler: {e}']}


def api_advisory(trade_id: int) -> dict:
    conn = get_db()
    row = conn.execute(
        'SELECT entry_reasoning FROM trade_advisory WHERE trade_id=?', (trade_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {'error': f'Keine Advisory für Trade {trade_id}'}
    return {'trade_id': trade_id, 'reasoning': row['entry_reasoning']}


def api_dashboard_data() -> dict:
    """Alle Daten in einem Request — für Dashboard-Frontend."""
    market     = api_market()
    portfolio  = api_portfolio()
    performance = api_performance()
    strategies = api_strategies()
    signals    = api_signals()
    health     = api_health()
    risk       = api_risk()
    anomalies  = api_anomalies()
    trades     = api_recent_trades(10)
    jobs       = api_jobs()
    fund       = api_fund()
    theses     = api_theses()
    risk_light = api_risk_light()

    return {
        **market,
        'fund':            fund,
        'theses':          theses['theses'],
        'risk_light':      risk_light,
        'total_pnl':       performance.get('total_pnl', 0),
        'win_rate':        performance.get('win_rate_all', 0),
        'open_positions':  portfolio['count'],
        'closed_trades':   performance.get('closed_trades', 0),
        'max_drawdown':    performance.get('max_drawdown', 0),
        'sharpe':          performance.get('sharpe', 0),
        'avg_quality':     performance.get('avg_quality', 0),
        'positions':       portfolio['positions'],
        'strategies':      strategies['strategies'],
        'health':          health,
        'risk':            risk,
        'anomalies_24h':   anomalies['count'],
        'recent_trades':   trades['trades'],
        'job_errors_24h':  jobs['errors_24h'],
        'news_relevant':   signals['news_gate']['relevant'],
        'active_theses':   [{'id': t, 'name': t, 'active': True}
                            for t in signals['news_gate'].get('theses_hit', [])],
        'generated_at':    datetime.now(timezone.utc).isoformat(),
    }


# ─── HTTP Server ──────────────────────────────────────────────────────────────

ROUTES = {
    '/api/portfolio':       lambda q: api_portfolio(q.get('user_id', ['user_victor'])[0]),
    '/api/performance':     lambda q: api_performance(),
    '/api/market':          lambda q: api_market(),
    '/api/strategies':      lambda q: api_strategies(),
    '/api/theses':          lambda q: api_theses(),
    '/api/signals':         lambda q: api_signals(),
    '/api/health':          lambda q: api_health(),
    '/api/risk':            lambda q: api_risk(),
    '/api/anomalies':       lambda q: api_anomalies(),
    '/api/recent-trades':   lambda q: api_recent_trades(int(q.get('limit', ['20'])[0])),
    '/api/discord-feed':    lambda q: api_discord_feed(int(q.get('limit', ['30'])[0])),
    '/api/jobs':            lambda q: api_jobs(),
    '/api/fund':            lambda q: api_fund(),
    '/api/equity-curve':    lambda q: api_equity_curve(int(q.get('days', ['90'])[0])),
    '/api/events-today':    lambda q: api_events_today(),
    '/api/stats':           lambda q: api_stats(),
    '/api/risk-light':      lambda q: api_risk_light(),
    '/api/dashboard-data':  lambda q: api_dashboard_data(),
}


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _check_auth(self) -> bool:
        if not AUTH_REQUIRED:
            return True
        hdr = self.headers.get('Authorization', '')
        if hdr.startswith('Basic '):
            try:
                raw = base64.b64decode(hdr[6:]).decode('utf-8', 'ignore')
                u, _, p = raw.partition(':')
                if u == AUTH_USER and p == AUTH_PASS:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="TradeMind"')
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Authentication required')
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/favicon.ico':
            self.send_response(204); self.end_headers(); return
        if not self._check_auth():
            return

        # Advisory: /api/advisory/42
        if path.startswith('/api/advisory/'):
            try:
                tid = int(path.split('/')[-1])
                self._json(api_advisory(tid))
            except Exception:
                self._json({'error': 'invalid id'}, 400)
            return

        # Thesis Detail: /api/thesis/PS_NVO
        if path.startswith('/api/thesis/'):
            tid = path.split('/', 3)[-1]
            try:
                self._json(api_thesis_detail(tid))
            except Exception as e:
                self._json({'error': str(e)}, 500)
            return

        # Position Detail: /api/position-detail/42
        if path.startswith('/api/position-detail/'):
            try:
                pid = int(path.split('/')[-1])
                self._json(api_position_detail(pid))
            except Exception as e:
                self._json({'error': str(e)}, 500)
            return

        # Price History: /api/price-history/NVDA?days=30
        if path.startswith('/api/price-history/'):
            ticker = path.split('/', 3)[-1]
            days = int(params.get('days', ['30'])[0])
            try:
                self._json(api_price_history(ticker, days))
            except Exception as e:
                self._json({'error': str(e)}, 500)
            return

        # Dashboard HTML — Priorität: dashboard/index.html → dashboard.html
        if path in ('/', '/index.html', '/dashboard'):
            for cand in (WS / 'dashboard/index.html', WS / 'dashboard.html'):
                if cand.exists():
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    self.wfile.write(cand.read_bytes())
                    return
            self._json({'error': 'dashboard html missing'}, 404)
            return

        # API Routes
        handler = ROUTES.get(path)
        if handler:
            try:
                data = handler(params)
                self._json(data)
            except Exception as e:
                self._json({'error': str(e)}, 500)
        else:
            self._json({'error': 'not found'}, 404)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    if '--once' in sys.argv:
        print(json.dumps(api_dashboard_data(), indent=2, ensure_ascii=False, default=str))
    else:
        print(f"TradeMind API läuft → http://0.0.0.0:{PORT}")
        for r in sorted(ROUTES.keys()):
            print(f"  {r}")
        HTTPServer(('0.0.0.0', PORT), APIHandler).serve_forever()
