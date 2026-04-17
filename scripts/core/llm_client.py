#!/usr/bin/env python3
"""
Dual-LLM Client — Phase 22.1
===============================
Wrapper um Anthropic Claude mit OpenAI-Fallback.

Call:
  from core.llm_client import call_llm
  text, usage = call_llm(
      prompt='...',
      model_hint='sonnet',      # 'sonnet' | 'opus' | 'haiku' | 'gpt-4o'
      max_tokens=4000,
  )

Verhalten:
  1. Versuche Anthropic (claude-sonnet-4-5 / opus / haiku) je nach Hint
  2. Bei Overload/RateLimit/5xx/Timeout → wechsle zu OpenAI (gpt-4o / gpt-4o-mini)
  3. Logge Fallback in data/llm_fallback_log.jsonl
  4. Budget-Check via data/daily_llm_budget.json (HARD $15/Tag Cap)

ENV:
  ANTHROPIC_API_KEY  (Primary)
  OPENAI_API_KEY     (Fallback)
  LLM_DAILY_BUDGET_USD=15
  LLM_FALLBACK_MODEL=gpt-4o
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
BUDGET_FILE = WS / 'data' / 'daily_llm_budget.json'
FALLBACK_LOG = WS / 'data' / 'llm_fallback_log.jsonl'

DEFAULT_BUDGET_USD = float(os.getenv('LLM_DAILY_BUDGET_USD', '15.0'))

ANTHROPIC_MODEL_MAP = {
    'sonnet': 'claude-sonnet-4-5',
    'opus':   'claude-opus-4-5',
    'haiku':  'claude-haiku-4-5',
}
OPENAI_MODEL_MAP = {
    'sonnet': 'gpt-4o',
    'opus':   'gpt-4o',
    'haiku':  'gpt-4o-mini',
}

# Anthropic-Preise pro 1M Tokens (In/Out) — grobe Schaetzung
PRICE_ANTHROPIC = {
    'claude-sonnet-4-5': (3.0, 15.0),
    'claude-opus-4-5':   (15.0, 75.0),
    'claude-haiku-4-5':  (0.8, 4.0),
}
PRICE_OPENAI = {
    'gpt-4o':      (2.5, 10.0),
    'gpt-4o-mini': (0.15, 0.6),
}


# ──────────────────────────────────────────────────────────────────────────
# Budget Controls
# ──────────────────────────────────────────────────────────────────────────

def _today_key() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _load_budget() -> dict:
    if BUDGET_FILE.exists():
        try:
            return json.loads(BUDGET_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _save_budget(d: dict):
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_FILE.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _check_budget() -> tuple[bool, float]:
    """Return (ok, spent_today_usd)."""
    b = _load_budget()
    today = _today_key()
    spent = float(b.get(today, {}).get('spent_usd', 0.0))
    return spent < DEFAULT_BUDGET_USD, spent


def _add_cost(cost_usd: float, provider: str):
    b = _load_budget()
    today = _today_key()
    entry = b.setdefault(today, {'spent_usd': 0.0, 'calls': 0, 'by_provider': {}})
    entry['spent_usd'] = round(entry.get('spent_usd', 0.0) + cost_usd, 4)
    entry['calls'] = entry.get('calls', 0) + 1
    entry['by_provider'][provider] = round(
        entry.get('by_provider', {}).get(provider, 0.0) + cost_usd, 4
    )
    # Keep last 30 days only
    cutoff = sorted(b.keys())[-30:]
    b = {k: v for k, v in b.items() if k in cutoff}
    _save_budget(b)


def _log_fallback(reason: str, provider_from: str, provider_to: str):
    FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FALLBACK_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'from': provider_from,
            'to': provider_to,
            'reason': reason[:200],
        }) + '\n')


# ──────────────────────────────────────────────────────────────────────────
# Provider-Calls
# ──────────────────────────────────────────────────────────────────────────

def _call_anthropic(prompt: str, model: str, max_tokens: int) -> tuple[str, dict]:
    import anthropic
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY fehlt')
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = resp.content[0].text if resp.content else ''
    in_tok = resp.usage.input_tokens if resp.usage else 0
    out_tok = resp.usage.output_tokens if resp.usage else 0
    price_in, price_out = PRICE_ANTHROPIC.get(model, (3.0, 15.0))
    cost = (in_tok * price_in + out_tok * price_out) / 1_000_000
    return text, {
        'provider': 'anthropic', 'model': model,
        'input_tokens': in_tok, 'output_tokens': out_tok,
        'cost_usd_est': round(cost, 4),
    }


def _call_openai(prompt: str, model: str, max_tokens: int) -> tuple[str, dict]:
    try:
        import openai
    except ImportError:
        raise RuntimeError('openai SDK fehlt — pip install openai')
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY fehlt (Fallback nicht verfuegbar)')
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = resp.choices[0].message.content if resp.choices else ''
    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    price_in, price_out = PRICE_OPENAI.get(model, (2.5, 10.0))
    cost = (in_tok * price_in + out_tok * price_out) / 1_000_000
    return text, {
        'provider': 'openai', 'model': model,
        'input_tokens': in_tok, 'output_tokens': out_tok,
        'cost_usd_est': round(cost, 4),
    }


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def call_llm(prompt: str, model_hint: str = 'sonnet', max_tokens: int = 4000,
             allow_fallback: bool = True) -> tuple[str, dict]:
    """
    Ruft primaer Anthropic, faellt bei Fehler auf OpenAI zurueck.
    Respektiert Tages-Budget (default $15).
    """
    ok, spent = _check_budget()
    if not ok:
        raise RuntimeError(
            f'LLM-Tagesbudget ueberschritten: ${spent:.2f} >= ${DEFAULT_BUDGET_USD}'
        )

    anth_model = ANTHROPIC_MODEL_MAP.get(model_hint, 'claude-sonnet-4-5')
    oai_model = OPENAI_MODEL_MAP.get(model_hint, 'gpt-4o')

    # Versuch 1: Anthropic mit 2 Retries
    last_err = None
    for attempt in range(2):
        try:
            text, usage = _call_anthropic(prompt, anth_model, max_tokens)
            _add_cost(usage['cost_usd_est'], 'anthropic')
            return text, usage
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            # Bei Overload/RateLimit/5xx sofort zu OpenAI springen
            if any(k in err_str for k in ('overload', 'rate_limit', 'rate limit',
                                           '529', '503', '502', '500', 'timeout')):
                break
            if attempt < 1:
                time.sleep(1.5 ** attempt)

    # Fallback: OpenAI
    if not allow_fallback:
        raise last_err or RuntimeError('LLM call failed, fallback disabled')

    _log_fallback(str(last_err)[:200], 'anthropic', 'openai')
    print(f"[llm] ⚠️  Anthropic-Fehler → Fallback OpenAI ({oai_model}): {str(last_err)[:100]}")

    try:
        text, usage = _call_openai(prompt, oai_model, max_tokens)
        _add_cost(usage['cost_usd_est'], 'openai')
        usage['fallback_from'] = 'anthropic'
        usage['fallback_reason'] = str(last_err)[:120]
        return text, usage
    except Exception as fe:
        raise RuntimeError(
            f'Beide LLM-Provider gescheitert: anthropic={last_err} openai={fe}'
        )


def get_budget_status() -> dict:
    ok, spent = _check_budget()
    return {
        'today': _today_key(),
        'spent_usd': round(spent, 4),
        'budget_usd': DEFAULT_BUDGET_USD,
        'remaining_usd': round(DEFAULT_BUDGET_USD - spent, 4),
        'halted': not ok,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--test', action='store_true')
    args = ap.parse_args()
    if args.status:
        print(json.dumps(get_budget_status(), indent=2))
    elif args.test:
        text, usage = call_llm('Sag "hallo" auf deutsch.', model_hint='haiku', max_tokens=50)
        print(f"[{usage['provider']}/{usage['model']}] {text}")
        print(json.dumps(usage, indent=2))
