#!/usr/bin/env python3
"""
ceo_tools.py — Phase 37: Echtes Tool-Calling für CEO-Brain.

Statt pre-computed Bundles bekommt der CEO eine TOOLBOX die er
selbständig aufruft. Pseudo-Tool-Use via JSON-Protocol im Prompt
(funktioniert mit OAuth-CLI, kein API-Geld nötig).

Verfügbare Tools:
  - get_correlation(ticker_a, ticker_b, days=30)
  - get_recent_news(ticker, hours=12)
  - simulate_position_impact(ticker, eur_size)
  - get_sector_exposure()
  - get_recent_trades(ticker_or_strategy, n=5)
  - web_search(query)  (via Tavily/Brave/Yahoo-RSS Fallback)

Tool-Loop:
  1. CEO bekommt Prompt + Tool-Definitions
  2. CEO antwortet entweder:
     - {"tool_call": {"name": "...", "args": {...}}}  → execute, feed back
     - {"final_decision": {...}}                      → done
  3. Max 6 Iterations (sonst Loop-Stop)

Plus Pydantic-Models für strukturierte Outputs (CEODecision, ToolCall).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'

MAX_TOOL_ITERATIONS = 6
WEB_SEARCH_MAX_RESULTS = 3


# ═══════════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════════

def tool_get_correlation(ticker_a: str, ticker_b: str, days: int = 30) -> dict:
    """Pearson-Korrelation der Tagesreturns zwischen 2 Tickers."""
    try:
        from portfolio_risk import _get_price_series, _pct_returns, _pearson
        a_series = _get_price_series(ticker_a, days=days)
        b_series = _get_price_series(ticker_b, days=days)
        if not a_series or not b_series or len(a_series) < 5 or len(b_series) < 5:
            return {'ticker_a': ticker_a, 'ticker_b': ticker_b,
                    'correlation': None, 'note': 'insufficient_data'}
        corr = _pearson(_pct_returns(a_series), _pct_returns(b_series))
        return {
            'ticker_a': ticker_a, 'ticker_b': ticker_b,
            'days': days,
            'correlation': round(corr, 3) if corr is not None else None,
            'samples_a': len(a_series), 'samples_b': len(b_series),
        }
    except Exception as e:
        return {'error': str(e)[:200]}


def tool_get_recent_news(ticker: str, hours: int = 12) -> dict:
    """Holt letzte news_events Einträge für einen Ticker (DB)."""
    try:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT created_at, headline, source FROM news_events
            WHERE (tickers LIKE ? OR headline LIKE ?) AND created_at >= ?
            ORDER BY created_at DESC LIMIT 10
        """, (f'%{ticker}%', f'%{ticker}%', cutoff)).fetchall()
        c.close()
        return {
            'ticker': ticker, 'hours_window': hours,
            'count': len(rows),
            'headlines': [{'ts': r['created_at'][:16],
                            'headline': r['headline'][:200],
                            'source': r['source']}
                          for r in rows],
        }
    except Exception as e:
        return {'error': str(e)[:200]}


def tool_simulate_position_impact(ticker: str, eur_size: float) -> dict:
    """Simuliert wie sich Portfolio-Risk durch neue Position verändert."""
    try:
        from portfolio_risk import _get_open_positions, get_sector, _get_fund_value
        opens = _get_open_positions()
        fund = _get_fund_value()
        new_sector = get_sector(ticker)
        sector_eur_now = sum(p.get('position_size_eur', 0) for p in opens
                              if get_sector(p.get('ticker', '')) == new_sector)
        sector_pct_now = sector_eur_now / fund * 100 if fund else 0
        sector_pct_after = (sector_eur_now + eur_size) / fund * 100 if fund else 0
        n_strategies_open = len({p.get('strategy') for p in opens})
        return {
            'ticker': ticker, 'sector': new_sector,
            'eur_size': eur_size,
            'fund_value': fund,
            'open_positions_now': len(opens),
            'sector_pct_now': round(sector_pct_now, 1),
            'sector_pct_after': round(sector_pct_after, 1),
            'sector_cap_violation': sector_pct_after > 30,
            'n_strategies_active': n_strategies_open,
        }
    except Exception as e:
        return {'error': str(e)[:200]}


def tool_get_sector_exposure() -> dict:
    """Aktuelle Sektor-Verteilung des Portfolios."""
    try:
        from portfolio_risk import get_exposure_breakdown
        b = get_exposure_breakdown()
        return {
            'by_sector': b.get('by_sector', {}),
            'total_eur': b.get('total_eur', 0),
            'herfindahl': b.get('herfindahl'),
        }
    except Exception as e:
        return {'error': str(e)[:200]}


def tool_get_recent_trades(filter_value: str, n: int = 5) -> dict:
    """Letzte N closed Trades für Ticker ODER Strategy."""
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT ticker, strategy, pnl_eur, pnl_pct, exit_type,
                   entry_date, close_date
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND (ticker = ? OR strategy = ?)
            ORDER BY close_date DESC LIMIT ?
        """, (filter_value, filter_value, n)).fetchall()
        c.close()
        return {
            'filter': filter_value,
            'count': len(rows),
            'trades': [{
                'ticker': r['ticker'], 'strategy': r['strategy'],
                'pnl_eur': r['pnl_eur'], 'pnl_pct': r['pnl_pct'],
                'exit': r['exit_type'],
                'closed': str(r['close_date'])[:16],
            } for r in rows],
        }
    except Exception as e:
        return {'error': str(e)[:200]}


def tool_web_search(query: str) -> dict:
    """Web-Search via Tavily wenn Key vorhanden, sonst Yahoo News-Feed Fallback."""
    # Try Tavily first
    tavily_key = os.environ.get('TAVILY_API_KEY')
    if tavily_key:
        try:
            req = urllib.request.Request(
                'https://api.tavily.com/search',
                data=json.dumps({
                    'api_key': tavily_key,
                    'query': query,
                    'max_results': WEB_SEARCH_MAX_RESULTS,
                    'search_depth': 'basic',
                    'include_answer': True,
                }).encode(),
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            return {
                'query': query,
                'source': 'tavily',
                'answer': data.get('answer', '')[:500],
                'results': [{
                    'title': x.get('title', '')[:150],
                    'url': x.get('url', ''),
                    'snippet': x.get('content', '')[:300],
                } for x in data.get('results', [])[:WEB_SEARCH_MAX_RESULTS]],
            }
        except Exception as e:
            return {'error': f'tavily failed: {e}', 'fallback': 'try_yahoo'}

    # Fallback: Yahoo News RSS
    try:
        url = f'https://news.search.yahoo.com/rss?p={urllib.parse.quote(query)}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            xml_text = r.read().decode(errors='replace')
        # Crude RSS parse
        import re
        items = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL)[:5]
        results = []
        for item in items:
            title = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
            link = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
            desc = re.search(r'<description>(.*?)</description>', item, re.DOTALL)
            results.append({
                'title': (title.group(1) if title else '')[:150],
                'url': link.group(1) if link else '',
                'snippet': re.sub(r'<[^>]+>', '', desc.group(1) if desc else '')[:200],
            })
        return {'query': query, 'source': 'yahoo_news_rss',
                'count': len(results), 'results': results}
    except Exception as e:
        return {'error': f'web_search failed: {e}'}


# Tool-Registry
TOOLS = {
    'get_correlation':           tool_get_correlation,
    'get_recent_news':           tool_get_recent_news,
    'simulate_position_impact':  tool_simulate_position_impact,
    'get_sector_exposure':       tool_get_sector_exposure,
    'get_recent_trades':         tool_get_recent_trades,
    'web_search':                tool_web_search,
}


def execute_tool(name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if not fn:
        return {'error': f'Unknown tool: {name}', 'available': list(TOOLS.keys())}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {'error': f'Bad args for {name}: {e}'}
    except Exception as e:
        return {'error': str(e)[:200]}


def get_tool_definitions_for_prompt() -> str:
    """Markdown-Block der Tool-Verfügbarkeit für LLM-Prompt."""
    return """═══ VERFÜGBARE TOOLS ═══
Du kannst diese Tools selbst aufrufen wenn du mehr Daten brauchst:

1. get_correlation(ticker_a, ticker_b, days=30)
   → Pearson-Korrelation zwischen 2 Tickers

2. get_recent_news(ticker, hours=12)
   → Letzte News-Headlines aus DB für Ticker

3. simulate_position_impact(ticker, eur_size)
   → Wie verändert sich Sektor-Exposure durch neue Position?

4. get_sector_exposure()
   → Aktuelle Sektor-Verteilung des Portfolios

5. get_recent_trades(filter_value, n=5)
   → Letzte N closed Trades für einen Ticker ODER Strategy

6. web_search(query)
   → Live-Web-Search (für aktuelle Events außerhalb unserer DB)

Nutze Tools sparsam — nur wenn relevant für aktuelle Decision.

ANTWORT-PROTOKOLL (strikt):
- Wenn du ein Tool aufrufen willst, antworte NUR mit:
  {"tool_call": {"name": "tool_name", "args": {...}}}
- Wenn du fertig bist mit Reasoning, antworte mit:
  {"final_decision": <dein Output-JSON>}
"""


def run_tool_loop(initial_prompt: str, max_iterations: int = MAX_TOOL_ITERATIONS,
                   model_hint: str = 'sonnet', max_tokens: int = 2500) -> dict:
    """
    Tool-Loop: LLM kann iterativ Tools aufrufen bis es ein final_decision liefert.
    Returns: dict mit 'final_decision' (oder 'error' bei Loop-Stop).
    """
    from core.llm_client import call_llm

    conversation = initial_prompt
    iterations = []

    for i in range(max_iterations):
        try:
            text, _usage = call_llm(conversation, model_hint=model_hint,
                                     max_tokens=max_tokens)
        except Exception as e:
            return {'error': f'LLM call failed at iteration {i}: {e}',
                    'iterations': iterations}

        # Parse response
        text_clean = (text or '').strip()
        if text_clean.startswith('```'):
            text_clean = text_clean.split('\n', 1)[1] if '\n' in text_clean else text_clean
            if text_clean.endswith('```'):
                text_clean = text_clean.rsplit('```', 1)[0]
        i1, j1 = text_clean.find('{'), text_clean.rfind('}')
        if i1 < 0 or j1 < 0:
            return {'error': 'no JSON in response', 'raw': text_clean[:500],
                    'iterations': iterations}

        try:
            parsed = json.loads(text_clean[i1:j1+1])
        except json.JSONDecodeError as e:
            return {'error': f'JSON parse failed: {e}', 'raw': text_clean[:500],
                    'iterations': iterations}

        # Final?
        if 'final_decision' in parsed:
            return {
                'final_decision': parsed['final_decision'],
                'iterations': iterations,
                'tool_calls_made': len(iterations),
            }

        # Tool call?
        if 'tool_call' in parsed:
            tc = parsed['tool_call']
            tool_name = tc.get('name')
            tool_args = tc.get('args', {})
            result = execute_tool(tool_name, tool_args)
            iterations.append({
                'iter': i + 1,
                'tool': tool_name,
                'args': tool_args,
                'result_summary': str(result)[:200],
            })
            # Append to conversation
            conversation += (
                f'\n\n[ITERATION {i+1}] Tool-Call: {tool_name}({json.dumps(tool_args)})'
                f'\nTool-Result: {json.dumps(result)[:1500]}'
                f'\n\nWenn du genug Info hast, antworte mit final_decision. '
                f'Sonst nächster tool_call.'
            )
            continue

        # Neither — return raw
        return {'error': 'response is neither tool_call nor final_decision',
                'raw': parsed, 'iterations': iterations}

    return {'error': f'Loop-Stop nach {max_iterations} iterations ohne final_decision',
            'iterations': iterations}


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic Models (für strukturierte Outputs)
# ═══════════════════════════════════════════════════════════════════════════

PYDANTIC_AVAILABLE = False
_CEOFinalDecision = None
try:
    from pydantic import BaseModel, Field, ValidationError
    from typing import Literal, Optional, List

    class CEODecisionItem(BaseModel):
        ticker: str
        strategy: str
        action: Literal['EXECUTE', 'SKIP', 'WATCH']
        confidence: float = Field(ge=0.0, le=1.0)
        bull_case: str = ''
        bear_case: str = ''
        reasoning: str
        expected_outcome_pct: float = 0.0
        memory_reference: str = ''

    class CEOFinalDecision(BaseModel):
        market_assessment: str
        portfolio_assessment: str
        decisions: List[CEODecisionItem]
        tool_calls_used: Optional[List[str]] = None

    _CEOFinalDecision = CEOFinalDecision
    PYDANTIC_AVAILABLE = True
except Exception as _pyd_err:
    # ImportError ODER AttributeError (gebrochenes system-inspect) → manual fallback
    print(f'[ceo_tools] Pydantic nicht verfügbar ({_pyd_err}) — manual validation',
          file=sys.stderr)


def validate_decision(payload: dict) -> tuple[bool, dict]:
    """Returns (is_valid, validated_dict_or_errors)."""
    if PYDANTIC_AVAILABLE and _CEOFinalDecision is not None:
        try:
            obj = _CEOFinalDecision(**payload)
            return True, obj.model_dump()
        except Exception as e:
            return False, {'errors': str(e)[:500]}
    # Manual best-effort
    if not isinstance(payload, dict):
        return False, {'error': 'not a dict'}
    if 'decisions' not in payload:
        return False, {'error': 'missing decisions field'}
    # Sanity-check decisions
    for d in payload.get('decisions', []):
        if not isinstance(d, dict):
            return False, {'error': 'decision item not dict'}
        if 'ticker' not in d or 'action' not in d:
            return False, {'error': f'decision missing ticker/action: {d}'}
        action = str(d.get('action', '')).upper()
        if action not in ('EXECUTE', 'SKIP', 'WATCH'):
            d['action'] = 'WATCH'  # coerce
        try:
            conf = float(d.get('confidence', 0.5))
            d['confidence'] = max(0.0, min(1.0, conf))
        except Exception:
            d['confidence'] = 0.5
    return True, payload


if __name__ == '__main__':
    # Smoke test
    print('=== Tool-Tests ===')
    print(json.dumps(tool_get_sector_exposure(), indent=2)[:500])
    print(json.dumps(tool_get_recent_news('UNH', hours=24), indent=2)[:500])
    print('=== Pydantic available:', PYDANTIC_AVAILABLE)
