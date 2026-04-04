#!/usr/bin/env python3.13
"""
api_server.py — TradeMind REST API
====================================
Öffentliche API für Dashboard + zukünftige Produkt-Integration.

Endpoints:
  GET /api/portfolio          Offene Positionen
  GET /api/performance        Performance-Metriken
  GET /api/signals            Aktuelle Signale / Conviction-Scores
  GET /api/market             VIX, Regime, EUR/USD
  GET /api/strategies         Aktive Strategien + Win-Rates
  GET /api/advisory/<id>      Trade-Erklärung für Trade-ID
  GET /api/dashboard-data     Alle Daten für Dashboard (ein Call)

Port: 8765 (lokal) oder via Hetzner/Vercel (Produkt)
Auth: X-API-Key Header (für Produkt-Phase)
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
PORT = 8765

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts/core'))


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


# ─── API Handler Funktionen ───────────────────────────────────────────────────

def api_portfolio(user_id='user_victor') -> dict:
    conn = get_db()
    rows = conn.execute('''
        SELECT ticker, strategy, entry_price, stop_price, target_price,
               conviction, regime_at_entry, entry_date, style, shares
        FROM paper_portfolio
        WHERE status='OPEN' AND (user_id=? OR user_id IS NULL)
        ORDER BY entry_date DESC
    ''', (user_id,)).fetchall()

    positions = []
    for r in rows:
        price_row = conn.execute(
            'SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (r['ticker'],)
        ).fetchone()
        current = price_row['close'] if price_row else None
        pnl_pct = round((current - r['entry_price']) / r['entry_price'] * 100, 1) if current else None
        positions.append({
            'ticker':    r['ticker'],
            'strategy':  r['strategy'],
            'entry':     r['entry_price'],
            'stop':      r['stop_price'],
            'target':    r['target_price'],
            'conviction': r['conviction'],
            'regime':    r['regime_at_entry'],
            'style':     r['style'] or 'swing',
            'current':   current,
            'pnl_pct':   pnl_pct,
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
        return {'error': 'Keine Performance-Daten'}
    return dict(row)


def api_market() -> dict:
    conn = get_db()
    vix = conn.execute(
        "SELECT value, date FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    fx = conn.execute(
        "SELECT value FROM macro_daily WHERE indicator='EURUSD' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    regime = conn.execute(
        'SELECT regime, date FROM regime_history ORDER BY date DESC LIMIT 1'
    ).fetchone()
    conn.close()
    return {
        'vix':     {'value': vix['value'] if vix else None, 'date': vix['date'] if vix else None},
        'eurusd':  fx['value'] if fx else None,
        'regime':  regime['regime'] if regime else 'UNKNOWN',
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
        WHERE status != 'OPEN'
        GROUP BY strategy
        HAVING trades >= 2
        ORDER BY total_pnl DESC
    ''').fetchall()
    conn.close()
    return {
        'strategies': [
            {
                'id':      r['strategy'],
                'trades':  r['trades'],
                'win_rate': round(r['wins'] / r['trades'] * 100, 1),
                'pnl':     round(r['total_pnl'] or 0, 1),
                'avg_return': round(r['avg_return'] or 0, 1),
            }
            for r in rows
        ]
    }


def api_signals() -> dict:
    conn = get_db()
    # Aktuelle news_gate Thesen
    gate_path = WS / 'data/news_gate.json'
    gate = {}
    if gate_path.exists():
        try:
            gate = json.loads(gate_path.read_text())
        except Exception:
            pass

    # Offene Positionen mit Conviction
    positions = conn.execute('''
        SELECT ticker, strategy, conviction, entry_price, stop_price
        FROM paper_portfolio WHERE status='OPEN'
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

    return {
        **market,
        'total_pnl':       performance.get('total_pnl', 0),
        'win_rate':        performance.get('win_rate_all', 0),
        'open_positions':  portfolio['count'],
        'closed_trades':   performance.get('closed_trades', 0),
        'max_drawdown':    performance.get('max_drawdown', 0),
        'sharpe':          performance.get('sharpe', 0),
        'avg_quality':     performance.get('avg_quality', 0),
        'positions':       portfolio['positions'],
        'strategies':      strategies['strategies'],
        'news_relevant':   signals['news_gate']['relevant'],
        'active_theses':   [{'id': t, 'name': t, 'active': True}
                            for t in signals['news_gate'].get('theses_hit', [])],
        'news_hits':       [],
        'generated_at':    datetime.now(timezone.utc).isoformat(),
    }


# ─── HTTP Server ──────────────────────────────────────────────────────────────

ROUTES = {
    '/api/portfolio':       lambda q: api_portfolio(q.get('user_id', ['user_victor'])[0]),
    '/api/performance':     lambda q: api_performance(),
    '/api/market':          lambda q: api_market(),
    '/api/strategies':      lambda q: api_strategies(),
    '/api/signals':         lambda q: api_signals(),
    '/api/dashboard-data':  lambda q: api_dashboard_data(),
}


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed   = urlparse(self.path)
        path     = parsed.path
        params   = parse_qs(parsed.query)

        # Advisory: /api/advisory/42
        if path.startswith('/api/advisory/'):
            try:
                tid = int(path.split('/')[-1])
                self._json(api_advisory(tid))
            except Exception:
                self._json({'error': 'invalid id'}, 400)
            return

        # Dashboard HTML
        if path in ('/', '/index.html'):
            html_path = WS / 'dashboard/index.html'
            if html_path.exists():
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html_path.read_bytes())
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
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    if '--once' in sys.argv:
        print(json.dumps(api_dashboard_data(), indent=2, ensure_ascii=False, default=str))
    else:
        print(f"TradeMind API läuft → http://localhost:{PORT}")
        print(f"  /api/dashboard-data")
        print(f"  /api/portfolio")
        print(f"  /api/performance")
        print(f"  /api/market")
        print(f"  /api/strategies")
        print(f"  /api/signals")
        HTTPServer(('0.0.0.0', PORT), APIHandler).serve_forever()
