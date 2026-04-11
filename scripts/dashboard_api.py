#!/usr/bin/env python3.14
"""
TradeMind Dashboard API
========================
Liefert JSON-Daten für das Dashboard (dashboard/index.html).
Kann als einfacher HTTP-Server laufen: python3.14 dashboard_api.py
"""

import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

WS   = Path('/data/.openclaw/workspace')
DB   = WS / 'data/trading.db'
DATA = WS / 'data'
PORT = 8765


def build_dashboard_data() -> dict:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # ── Stats ────────────────────────────────────────────────────────
    stats = conn.execute('''
        SELECT COUNT(*) total,
               SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) wins,
               SUM(pnl_eur) total_pnl
        FROM paper_portfolio WHERE status != "OPEN"
    ''').fetchone()
    total   = stats['total'] or 0
    wins    = stats['wins'] or 0
    win_rate = round(wins / total * 100) if total else 0
    total_pnl = round(stats['total_pnl'] or 0, 2)

    open_count = conn.execute('SELECT COUNT(*) FROM paper_portfolio WHERE status="OPEN"').fetchone()[0]

    # ── Regime / VIX ─────────────────────────────────────────────────
    regime_row = conn.execute('SELECT regime, vix FROM regime_history ORDER BY date DESC LIMIT 1').fetchone()
    regime = regime_row['regime'] if regime_row else 'UNKNOWN'
    vix    = round(regime_row['vix'], 1) if regime_row and regime_row['vix'] else None

    # ── Offene Positionen ────────────────────────────────────────────
    pos_rows = conn.execute('''
        SELECT ticker, strategy, entry_price, stop_price, target_price, conviction
        FROM paper_portfolio WHERE status="OPEN"
        ORDER BY entry_date DESC
    ''').fetchall()

    positions = []
    for p in pos_rows:
        price_row = conn.execute(
            'SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (p['ticker'],)
        ).fetchone()
        current = price_row['close'] if price_row else None
        pnl_pct = round((current - p['entry_price']) / p['entry_price'] * 100, 1) if current else None
        positions.append({
            'ticker': p['ticker'], 'strategy': p['strategy'],
            'entry': p['entry_price'], 'stop': p['stop_price'],
            'target': p['target_price'], 'conviction': p['conviction'],
            'pnl_pct': pnl_pct,
        })

    # ── Strategie-Performance ────────────────────────────────────────
    strat_rows = conn.execute('''
        SELECT strategy,
               COUNT(*) trades,
               SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) wins,
               SUM(pnl_eur) pnl
        FROM paper_portfolio WHERE status != "OPEN"
        GROUP BY strategy ORDER BY pnl DESC
    ''').fetchall()

    strategies = [
        {
            'id': r['strategy'],
            'trades': r['trades'],
            'wr': round(r['wins'] / r['trades'] * 100) if r['trades'] else 0,
            'pnl': round(r['pnl'] or 0, 1),
        }
        for r in strat_rows if r['trades'] >= 2
    ]

    # ── News Gate ────────────────────────────────────────────────────
    news_relevant = False
    active_theses = []
    news_hits = []
    try:
        gate = json.loads((DATA / 'news_gate.json').read_text())
        news_relevant = gate.get('relevant', False)
        for thesis_id in gate.get('theses_hit', []):
            active_theses.append({'id': thesis_id, 'name': thesis_id, 'active': True})
        news_hits = [
            {
                'headline': h.get('headline', ''),
                'thesis': h.get('thesis', ''),
                'source': h.get('source', ''),
            }
            for h in gate.get('top_hits', [])[:8]
        ]
    except Exception:
        pass

    conn.close()

    return {
        'total_pnl':       total_pnl,
        'win_rate':        win_rate,
        'open_positions':  open_count,
        'closed_trades':   total,
        'regime':          regime,
        'vix':             vix,
        'news_relevant':   news_relevant,
        'positions':       positions,
        'strategies':      strategies,
        'active_theses':   active_theses,
        'news_hits':       news_hits,
        'generated_at':    datetime.now(timezone.utc).isoformat(),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Kein Log-Spam

    def do_GET(self):
        if self.path == '/api/dashboard-data':
            try:
                data = build_dashboard_data()
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif self.path == '/' or self.path == '/index.html':
            html_path = WS / 'dashboard/index.html'
            if html_path.exists():
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    # Einmal-Ausgabe für Cron/Test
    import sys
    if '--once' in sys.argv:
        print(json.dumps(build_dashboard_data(), indent=2, ensure_ascii=False))
    else:
        print(f"TradeMind Dashboard API läuft auf http://localhost:{PORT}")
        HTTPServer(('0.0.0.0', PORT), DashboardHandler).serve_forever()
