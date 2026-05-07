#!/usr/bin/env python3
"""
api_heartbeat.py — Phase 45aa (Victor 2026-05-07).

Schliesst Klasse A6 'API-Quota / Yahoo-Outage'.

Pingt alle externen API-Endpoints alle 15min:
  - Yahoo Finance (via yfinance einfache Test-Anfrage)
  - Anthropic API (via call_llm minimal test)

Bei Fehler oder Timeout: Discord-HIGH (system_error) + Log.

Output: data/api_heartbeat_log.jsonl
Run: alle 15min via scheduler.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.request, urllib.error

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
LOG = WS / 'data' / 'api_heartbeat_log.jsonl'


def _check_yahoo() -> dict:
    """Test: Hole AAPL-Preis via Yahoo Finance."""
    try:
        url = ('https://query1.finance.yahoo.com/v8/finance/chart/AAPL'
               '?interval=1d&range=1d')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            chart = (data.get('chart') or {}).get('result') or []
            if not chart:
                return {'service': 'yahoo', 'status': 'fail',
                         'reason': 'empty_response'}
            meta = chart[0].get('meta') or {}
            price = meta.get('regularMarketPrice')
            if price is None:
                return {'service': 'yahoo', 'status': 'fail',
                         'reason': 'no_price'}
            return {'service': 'yahoo', 'status': 'ok',
                     'sample_price': price}
    except urllib.error.HTTPError as e:
        return {'service': 'yahoo', 'status': 'fail',
                 'reason': f'http_{e.code}'}
    except Exception as e:
        return {'service': 'yahoo', 'status': 'fail',
                 'reason': f'{type(e).__name__}: {str(e)[:80]}'}


def _check_anthropic() -> dict:
    """Test: Mini-LLM-Call. Nur falls API-Key gesetzt — sonst skip."""
    if not os.getenv('ANTHROPIC_API_KEY'):
        return {'service': 'anthropic', 'status': 'skip',
                 'reason': 'no_api_key'}
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from core.llm_client import call_llm  # type: ignore
        text, usage = call_llm('Sage genau: PONG', model_hint='haiku',
                                 max_tokens=10, audit_context='heartbeat',
                                 inject_truth=False)
        if 'PONG' in (text or '').upper():
            return {'service': 'anthropic', 'status': 'ok',
                     'provider': usage.get('provider', '?')}
        return {'service': 'anthropic', 'status': 'fail',
                 'reason': f'unexpected:{(text or "")[:50]}'}
    except Exception as e:
        return {'service': 'anthropic', 'status': 'fail',
                 'reason': f'{type(e).__name__}: {str(e)[:80]}'}


def main() -> int:
    results = [_check_yahoo(), _check_anthropic()]
    failures = [r for r in results if r['status'] == 'fail']
    out = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'results': results,
        'n_failures': len(failures),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(out, default=str) + '\n')
    if failures:
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from discord_dispatcher import send_alert, TIER_HIGH
            msg = (f"🚨 **API-Heartbeat-Failure** ({len(failures)}/{len(results)} Services down):\n"
                   + '\n'.join(f"  - {f['service']}: {f.get('reason','?')}"
                               for f in failures))
            send_alert(msg[:1900], tier=TIER_HIGH, category='api_quota_exceeded',
                        dedupe_key=f'api_hb_{datetime.now().strftime("%Y%m%d_%H")}')
        except Exception: pass
    print(json.dumps(out, indent=2, default=str))
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
