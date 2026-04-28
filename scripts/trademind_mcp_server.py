#!/usr/bin/env python3
"""
trademind_mcp_server.py — Phase 40e: MCP-Server für TradeMind.

Macht TradeMind als MCP-Tool nutzbar von Claude Desktop, Cursor, OpenClaw.
Du kannst dann direkt aus Claude Desktop fragen:
  "Was hat TradeMind heute gemacht?"
  "Zeig mir die Heatmap"
  "Wie ist mein Portfolio?"

Setup für Claude Desktop (~/.claude/mcp.json):
  {
    "mcpServers": {
      "trademind": {
        "command": "python3",
        "args": ["/opt/trademind/scripts/trademind_mcp_server.py"]
      }
    }
  }

Implementiert minimales MCP-Protokoll via stdin/stdout JSON-RPC.
Keine Dependencies (kein fastmcp), kompakt und ausreichend.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))


# Tool-Definitions für MCP
TOOLS = [
    {
        'name': 'get_portfolio_state',
        'description': 'Aktueller Portfolio-Status: Cash, Open Positions, Realized PnL',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_today_activity',
        'description': 'Was hat TradeMind heute gemacht (Trades, Decisions, Errors)',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_heatmap',
        'description': 'Strategy×Hour Heatmap (Best/Worst Hours per Strategy)',
        'inputSchema': {'type': 'object', 'properties': {
            'days': {'type': 'integer', 'default': 60}
        }},
    },
    {
        'name': 'get_anti_patterns',
        'description': 'Aktive Anti-Patterns (Loss-Pattern die System vermeidet)',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_lifecycle_overview',
        'description': 'Strategy-Lifecycle: ACTIVE/PROBATION/SUSPENDED/RETIRED',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'explain_trade',
        'description': 'Warum hat das System einen Trade gemacht? Volle Decision-Reasoning.',
        'inputSchema': {'type': 'object', 'properties': {
            'ticker': {'type': 'string'}
        }, 'required': ['ticker']},
    },
    {
        'name': 'get_capabilities',
        'description': 'Was kann das TradeMind-System aktuell? Liste aller Features.',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
]


def execute_tool(name: str, args: dict) -> str:
    """Führt MCP-Tool aus."""
    try:
        if name == 'get_portfolio_state':
            import sqlite3
            c = sqlite3.connect(str(WS / 'data' / 'trading.db'))
            c.row_factory = sqlite3.Row
            opens = c.execute(
                "SELECT ticker, strategy, entry_price, shares FROM paper_portfolio WHERE status='OPEN'"
            ).fetchall()
            cash = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
            pnl = c.execute("SELECT value FROM paper_fund WHERE key='total_realized_pnl'").fetchone()
            c.close()
            return json.dumps({
                'cash_eur': float(cash[0]) if cash else 0,
                'realized_pnl_eur': float(pnl[0]) if pnl else 0,
                'n_open_positions': len(opens),
                'open_positions': [
                    {'ticker': r['ticker'], 'strategy': r['strategy'],
                     'eur': round((r['entry_price'] or 0) * (r['shares'] or 0), 0)}
                    for r in opens
                ],
            }, indent=2)

        elif name == 'get_today_activity':
            import sqlite3
            today = datetime.now().strftime('%Y-%m-%d')
            c = sqlite3.connect(str(WS / 'data' / 'trading.db'))
            opened = c.execute(
                "SELECT COUNT(*) FROM paper_portfolio WHERE substr(entry_date,1,10)=?",
                (today,)
            ).fetchone()[0]
            closed = c.execute(
                "SELECT COUNT(*), SUM(pnl_eur) FROM paper_portfolio WHERE substr(close_date,1,10)=?",
                (today,)
            ).fetchone()
            c.close()
            return json.dumps({
                'date': today,
                'trades_opened': opened,
                'trades_closed': closed[0] or 0,
                'closed_pnl_eur': round(closed[1] or 0, 2),
            }, indent=2)

        elif name == 'get_heatmap':
            from ceo_pattern_learning import compute_strategy_hour_heatmap, heatmap_to_markdown
            days = args.get('days', 60)
            h = compute_strategy_hour_heatmap(days=days)
            return heatmap_to_markdown(h, top_n=15)

        elif name == 'get_anti_patterns':
            from ceo_pattern_learning import load_anti_patterns
            patterns = load_anti_patterns()
            return json.dumps(patterns[:20], indent=2)

        elif name == 'get_lifecycle_overview':
            from strategy_lifecycle import get_lifecycle_overview
            return json.dumps(get_lifecycle_overview(), indent=2)

        elif name == 'explain_trade':
            from ceo_trade_reasoning import explain_trade
            return explain_trade(args.get('ticker', ''))

        elif name == 'get_capabilities':
            cap_file = WS / 'memory' / 'ceo-capabilities.md'
            if cap_file.exists():
                return cap_file.read_text(encoding='utf-8')
            return 'Capabilities-Doc noch nicht generiert'

        return f'Unknown tool: {name}'
    except Exception as e:
        return f'Tool execution error: {type(e).__name__}: {e}'


def handle_request(req: dict) -> dict:
    """JSON-RPC 2.0 handler."""
    method = req.get('method')
    req_id = req.get('id')

    if method == 'initialize':
        return {
            'jsonrpc': '2.0', 'id': req_id,
            'result': {
                'protocolVersion': '2024-11-05',
                'serverInfo': {'name': 'trademind', 'version': '40e.1'},
                'capabilities': {'tools': {}},
            },
        }

    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': req_id, 'result': {'tools': TOOLS}}

    if method == 'tools/call':
        params = req.get('params', {})
        tool_name = params.get('name')
        args = params.get('arguments', {})
        text = execute_tool(tool_name, args)
        return {
            'jsonrpc': '2.0', 'id': req_id,
            'result': {'content': [{'type': 'text', 'text': text}]},
        }

    return {
        'jsonrpc': '2.0', 'id': req_id,
        'error': {'code': -32601, 'message': f'Method not found: {method}'},
    }


def main() -> int:
    """stdin/stdout JSON-RPC loop."""
    print('TradeMind MCP-Server gestartet (stdin/stdout)', file=sys.stderr)
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            req = json.loads(line.strip())
            resp = handle_request(req)
            print(json.dumps(resp), flush=True)
        except (EOFError, KeyboardInterrupt):
            break
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f'Server error: {e}', file=sys.stderr)
            continue
    return 0


if __name__ == '__main__':
    sys.exit(main())
