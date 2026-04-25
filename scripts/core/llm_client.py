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
import shutil
import subprocess
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

# Claude Code CLI (Max-Subscription) — Mapping zu Modell-Aliassen
CLI_MODEL_MAP = {
    'sonnet': 'sonnet',
    'opus':   'opus',
    'haiku':  'haiku',
}

# Provider-Reihenfolge (kann via ENV gesetzt werden)
# Default: cli (Abo) → anthropic (API) → openai (Fallback)
PROVIDER_ORDER = os.getenv('LLM_PROVIDER_ORDER', 'cli,anthropic,openai').split(',')

# Welche model_hints duerfen ueberhaupt CLI nutzen?
# Default: alle. Setze z.B. 'sonnet,opus' um Haiku-Bulk-Jobs auf API zu lassen.
CLI_ALLOWED_HINTS = set(os.getenv('LLM_CLI_HINTS', 'sonnet,opus,haiku').split(','))

# Rate-Limit-Tracking: Wenn CLI 429/quota meldet, paar Minuten Cooldown
_CLI_COOLDOWN_UNTIL = 0.0
CLI_COOLDOWN_SECONDS = int(os.getenv('LLM_CLI_COOLDOWN_S', '300'))  # 5 min


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

def _cli_available() -> bool:
    """Check ob claude CLI installiert + authentifiziert ist.
    Auth via OAuth-Token (CLAUDE_CODE_OAUTH_TOKEN env) ODER credentials.json."""
    if not shutil.which('claude'):
        return False
    if os.getenv('CLAUDE_CODE_OAUTH_TOKEN', '').strip():
        return True
    home = Path(os.path.expanduser('~'))
    creds = home / '.claude' / '.credentials.json'
    return creds.exists()


def _call_claude_cli(prompt: str, model_alias: str, max_tokens: int) -> tuple[str, dict]:
    """
    Ruft Claude Code CLI im headless mode (`claude -p`).
    Rechnet gegen Claude.ai-Subscription (Pro/Max), NICHT gegen API-Credits.

    Args:
        prompt: User-Prompt
        model_alias: 'sonnet' | 'opus' | 'haiku'
        max_tokens: ignoriert (CLI managed selber, nur fuer Konsistenz)
    """
    global _CLI_COOLDOWN_UNTIL
    if time.time() < _CLI_COOLDOWN_UNTIL:
        raise RuntimeError(f'CLI im Cooldown bis {datetime.fromtimestamp(_CLI_COOLDOWN_UNTIL)}')

    if not shutil.which('claude'):
        raise RuntimeError('claude CLI nicht installiert')

    cmd = [
        'claude',
        '-p',                          # print mode (headless, no interactive)
        '--model', model_alias,
        '--output-format', 'json',     # JSON-Antwort fuer einfaches Parsing
        '--no-session-persistence',    # Keine Session-Files anlegen
        '--bare',                      # minimal mode: kein CLAUDE.md auto-discovery, keine hooks
    ]

    # bare-Mode setzt CLAUDE_CODE_SIMPLE=1 und liest OAuth nicht aus keychain.
    # Wir wollen aber OAuth! Also OHNE --bare arbeiten und stattdessen ein temp cwd nutzen.
    cmd = [
        'claude',
        '-p',
        '--model', model_alias,
        '--output-format', 'json',
        '--disable-slash-commands',    # keine skills laden
        '--setting-sources', 'user',   # nur user settings, keine project/local
    ]

    # Stage 3 — Volle Fusion: optional eine Shared Session zwischen Albert
    # und Claude Code CLI. Wenn LLM_SHARED_SESSION_ID gesetzt ist, hängen
    # alle Albert-Antworten an dieselbe Session an, die ich (CLI) auch
    # via `claude --resume <id>` benutzen kann → echte gemeinsame History.
    # Default: --no-session-persistence (jede Antwort isoliert, billiger).
    _shared_sid = os.getenv('LLM_SHARED_SESSION_ID', '').strip()
    if _shared_sid:
        cmd.extend(['--resume', _shared_sid])
    else:
        cmd.append('--no-session-persistence')

    # WICHTIG: ANTHROPIC_API_KEY wird vom CLI bevorzugt vor OAuth-Token!
    # Wir wollen aber Subscription-Billing → API_KEY unsetzen fuer den Subprocess.
    cli_env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}
    cli_env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=cli_env,
        )
        # Stage 3 Fallback: --resume gegen nicht-existente Session → retry ohne
        if (result.returncode != 0 and '--resume' in cmd and
                'No conversation found' in (result.stderr + result.stdout)):
            try:
                _idx = cmd.index('--resume')
                _cmd_fb = cmd[:_idx] + cmd[_idx+2:] + ['--no-session-persistence']
            except ValueError:
                _cmd_fb = [c for c in cmd if c != '--resume']
            result = subprocess.run(
                _cmd_fb, input=prompt, capture_output=True, text=True,
                timeout=120, check=False, env=cli_env,
            )
    except subprocess.TimeoutExpired:
        raise RuntimeError('claude CLI timeout (120s)')

    if result.returncode != 0:
        err = (result.stderr or result.stdout or '').strip()[:300]
        err_low = err.lower()
        # Rate-Limit/Quota → Cooldown setzen
        if any(k in err_low for k in ('rate limit', 'quota', 'usage limit', '429', 'too many')):
            _CLI_COOLDOWN_UNTIL = time.time() + CLI_COOLDOWN_SECONDS
            raise RuntimeError(f'CLI rate-limited → Cooldown {CLI_COOLDOWN_SECONDS}s: {err}')
        if 'auth' in err_low or 'login' in err_low or 'token' in err_low or 'unauthor' in err_low:
            raise RuntimeError(f'CLI auth error (token abgelaufen?): {err}')
        raise RuntimeError(f'CLI exit {result.returncode}: {err}')

    # JSON-Output parsen
    raw = (result.stdout or '').strip()
    text = ''
    in_tok = 0
    out_tok = 0
    cost_usd = 0.0
    try:
        data = json.loads(raw)
        # JSON-Format: {"type":"result","subtype":"success","result":"...","usage":{...},"total_cost_usd":...}
        text = data.get('result') or data.get('content') or ''
        usage = data.get('usage') or {}
        in_tok = usage.get('input_tokens', 0)
        out_tok = usage.get('output_tokens', 0)
        cost_usd = float(data.get('total_cost_usd', 0.0))
    except (json.JSONDecodeError, ValueError, AttributeError):
        # Fallback: roher Text
        text = raw

    return text, {
        'provider': 'claude_cli',
        'model': model_alias,
        'input_tokens': in_tok,
        'output_tokens': out_tok,
        'cost_usd_est': 0.0,            # via Subscription, kein API-Cost
        'cli_reported_cost_usd': round(cost_usd, 4),
        'billing': 'subscription',
    }


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

class LLMBudgetExceeded(RuntimeError):
    """Raised wenn Tages-LLM-Budget aufgebraucht ist."""


def call_llm(prompt: str, model_hint: str = 'sonnet', max_tokens: int = 4000,
             allow_fallback: bool = True) -> tuple[str, dict]:
    """
    Provider-Reihenfolge (default): Claude CLI (Abo) → Anthropic API → OpenAI.
    CLI bevorzugt → kostet nichts (Subscription), Fallback bei Rate-Limit/Auth-Fail.
    Respektiert API-Tages-Budget nur fuer kostenpflichtige Provider (anthropic/openai).
    """
    anth_model = ANTHROPIC_MODEL_MAP.get(model_hint, 'claude-sonnet-4-5')
    oai_model = OPENAI_MODEL_MAP.get(model_hint, 'gpt-4o')
    cli_alias = CLI_MODEL_MAP.get(model_hint, 'sonnet')

    last_err: Exception | None = None
    tried: list[str] = []

    for provider in PROVIDER_ORDER:
        provider = provider.strip().lower()

        # ---- 1) Claude CLI (Subscription) ----
        if provider == 'cli':
            if model_hint not in CLI_ALLOWED_HINTS:
                continue
            if not _cli_available():
                continue
            try:
                text, usage = _call_claude_cli(prompt, cli_alias, max_tokens)
                # Kein _add_cost — laeuft ueber Abo
                tried.append('cli')
                return text, usage
            except Exception as e:
                last_err = e
                err_low = str(e).lower()
                tried.append(f'cli({str(e)[:60]})')
                if not allow_fallback:
                    raise
                # Auth-Fehler oder Rate-Limit → silently fallback
                _log_fallback(str(e)[:200], 'claude_cli', 'next')
                if 'auth' in err_low or 'token' in err_low:
                    print(f"[llm] ⚠️  Claude CLI auth fail → Fallback: {str(e)[:120]}")
                else:
                    print(f"[llm] ⚠️  Claude CLI nicht verfuegbar → Fallback: {str(e)[:120]}")
                continue

        # ---- 2) Anthropic API ----
        if provider == 'anthropic':
            ok, spent = _check_budget()
            if not ok:
                last_err = LLMBudgetExceeded(
                    f'API-Budget aufgebraucht: ${spent:.2f}/${DEFAULT_BUDGET_USD}'
                )
                tried.append('anthropic(budget)')
                continue
            # Soft-Cap auf 80%: auf haiku runter
            local_anth_model = anth_model
            if spent >= DEFAULT_BUDGET_USD * 0.80 and model_hint != 'haiku':
                local_anth_model = ANTHROPIC_MODEL_MAP['haiku']
                print(f"[llm] ⚠️  Soft-Cap (${spent:.2f}/${DEFAULT_BUDGET_USD}) → haiku")
            for attempt in range(2):
                try:
                    text, usage = _call_anthropic(prompt, local_anth_model, max_tokens)
                    _add_cost(usage['cost_usd_est'], 'anthropic')
                    tried.append('anthropic')
                    if 'cli' in ' '.join(tried[:-1]):
                        usage['fallback_from'] = 'claude_cli'
                    return text, usage
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    if any(k in err_str for k in ('overload', 'rate_limit', 'rate limit',
                                                   '529', '503', '502', '500', 'timeout',
                                                   'credit balance', 'low to access')):
                        break
                    if attempt < 1:
                        time.sleep(1.5 ** attempt)
            tried.append(f'anthropic({str(last_err)[:50]})')
            if not allow_fallback:
                raise last_err
            _log_fallback(str(last_err)[:200], 'anthropic', 'openai')
            continue

        # ---- 3) OpenAI Fallback ----
        if provider == 'openai':
            try:
                text, usage = _call_openai(prompt, oai_model, max_tokens)
                _add_cost(usage['cost_usd_est'], 'openai')
                usage['fallback_from'] = tried[0] if tried else 'unknown'
                usage['fallback_reason'] = str(last_err)[:120] if last_err else ''
                tried.append('openai')
                return text, usage
            except Exception as e:
                last_err = e
                tried.append(f'openai({str(e)[:50]})')
                continue

    raise RuntimeError(f'Alle LLM-Provider gescheitert. Tried: {tried}. Last: {last_err}')


def safe_call_llm(prompt: str, model_hint: str = 'sonnet', max_tokens: int = 4000,
                  allow_fallback: bool = True) -> tuple[str | None, dict]:
    """
    Wie call_llm, aber raised NIE — bei Fehler (Budget, Provider down) returnt
    (None, {'error': '...', 'degraded': True}) damit Caller graceful weiter
    koennen (z.B. Job skippt statt crasht).
    """
    try:
        return call_llm(prompt, model_hint=model_hint, max_tokens=max_tokens,
                        allow_fallback=allow_fallback)
    except LLMBudgetExceeded as e:
        return None, {'error': str(e), 'degraded': True, 'reason': 'budget'}
    except Exception as e:
        return None, {'error': str(e)[:300], 'degraded': True, 'reason': 'provider'}


def get_budget_status() -> dict:
    ok, spent = _check_budget()
    return {
        'today': _today_key(),
        'spent_usd': round(spent, 4),
        'budget_usd': DEFAULT_BUDGET_USD,
        'remaining_usd': round(DEFAULT_BUDGET_USD - spent, 4),
        'halted': not ok,
        'cli_available': _cli_available(),
        'cli_cooldown_remaining_s': max(0, int(_CLI_COOLDOWN_UNTIL - time.time())),
        'provider_order': PROVIDER_ORDER,
    }


def cli_heartbeat() -> dict:
    """
    Health-Check fuer claude CLI.
    Macht einen Mini-Call ('ping') und prueft ob CLI/Auth noch laeuft.
    Returnt {ok: bool, latency_ms: int, error?: str}.
    Gedacht fuer taegliche Prufung im scheduler_daemon.
    """
    if not _cli_available():
        return {'ok': False, 'error': 'CLI nicht installiert oder nicht authentifiziert'}
    t0 = time.time()
    try:
        text, usage = _call_claude_cli('Antworte exakt mit dem Wort: pong', 'haiku', max_tokens=20)
        ok = 'pong' in (text or '').lower()
        return {
            'ok': ok,
            'latency_ms': int((time.time() - t0) * 1000),
            'response': (text or '')[:50],
            'model': usage.get('model'),
        }
    except Exception as e:
        return {'ok': False, 'latency_ms': int((time.time() - t0) * 1000), 'error': str(e)[:200]}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--test', action='store_true')
    ap.add_argument('--heartbeat', action='store_true', help='CLI health check')
    ap.add_argument('--cli-only', action='store_true', help='Test nur CLI-Provider')
    args = ap.parse_args()
    if args.status:
        print(json.dumps(get_budget_status(), indent=2))
    elif args.heartbeat:
        print(json.dumps(cli_heartbeat(), indent=2))
    elif args.test:
        if args.cli_only:
            os.environ['LLM_PROVIDER_ORDER'] = 'cli'
        text, usage = call_llm('Sag "hallo" auf deutsch.', model_hint='haiku', max_tokens=50)
        print(f"[{usage['provider']}/{usage['model']}] {text}")
        print(json.dumps(usage, indent=2))
