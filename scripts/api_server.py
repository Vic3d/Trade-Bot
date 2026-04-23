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

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
DATA = WS / 'data'
PORT = 8765

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

    return {
        **market,
        'fund':            fund,
        'theses':          theses['theses'],
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
    '/api/dashboard-data':  lambda q: api_dashboard_data(),
}


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

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
