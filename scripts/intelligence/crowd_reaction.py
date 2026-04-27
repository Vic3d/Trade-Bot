#!/usr/bin/env python3
"""
crowd_reaction.py — Leichtgewichtige Crowd-Reaktions-Simulation
===============================================================
Simuliert wie verschiedene Marktteilnehmer auf eine These/ein Szenario reagieren.
Inspiriert von MiroFish, aber: 1 Claude-Call statt 56 Agenten.

Gibt einen Crowd-Sentiment-Score zurück (0-100) der in den Conviction Scorer einfließt.

Albert | TradeMind v2 | 2026-04-10
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
STRATEGIES_PATH = WS / 'data' / 'strategies.json'
CACHE_PATH      = WS / 'data' / 'crowd_cache.json'

CACHE_TTL_SECONDS = 4 * 3600  # 4 hours

SYSTEM_PROMPT = """\
Du bist ein Marktstruktur-Analyst. Simuliere die Reaktion von 4 verschiedenen Marktteilnehmer-Typen auf ein Trading-Szenario.

Antworte NUR mit einem JSON-Objekt in diesem Format:
{
  "retail": {"sentiment": 0-100, "action": "KAUFT|WARTET|VERKAUFT", "reasoning": "kurz"},
  "institutional": {"sentiment": 0-100, "action": "AKKUMULIERT|BEOBACHTET|REDUZIERT", "reasoning": "kurz"},
  "algo": {"sentiment": 0-100, "action": "LONG_SIGNAL|NEUTRAL|SHORT_SIGNAL", "reasoning": "kurz"},
  "contrarian": {"sentiment": 0-100, "action": "FADE|NEUTRAL|FOLLOW", "reasoning": "kurz"}
}
sentiment: 0=sehr bearish, 50=neutral, 100=sehr bullish"""


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


def _cache_key(thesis_id: str, scenario: str) -> str:
    return f"{thesis_id}_{scenario[:50]}"


def _get_cached(key: str) -> dict | None:
    """Returns cached result if still fresh (< 4 hours old), else None."""
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    age = time.time() - entry.get('cached_at', 0)
    if age < CACHE_TTL_SECONDS:
        return entry.get('result')
    return None


def _set_cached(key: str, result: dict) -> None:
    cache = _load_cache()
    cache[key] = {
        'cached_at': time.time(),
        'result': result,
    }
    _save_cache(cache)


# ─── Thesis loader ────────────────────────────────────────────────────────────

def _load_thesis(thesis_id: str) -> dict:
    try:
        if STRATEGIES_PATH.exists():
            strategies = json.loads(STRATEGIES_PATH.read_text(encoding='utf-8'))
            return strategies.get(thesis_id, {})
    except Exception:
        pass
    return {}


# ─── Claude call ─────────────────────────────────────────────────────────────

def _call_claude(user_prompt: str) -> dict:
    """Single LLM call (CLI-First via OAuth). Returns parsed JSON dict or raises."""
    import sys as _llmsys
    from pathlib import Path as _LP
    _llmsys.path.insert(0, str(_LP(__file__).resolve().parent.parent))
    from core.llm_client import call_llm as _call_llm
    raw, _usage = _call_llm(user_prompt, model_hint='haiku',
                             max_tokens=512, system=SYSTEM_PROMPT)
    raw = (raw or '').strip()

    # Strip markdown code fences if present
    if raw.startswith('```'):
        lines = raw.split('\n')
        raw = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])

    return json.loads(raw)


# ─── Score calculation ────────────────────────────────────────────────────────

def _calculate_crowd_score(personas: dict) -> tuple[float, str]:
    """
    Weighted crowd score from 4 personas.
    Weights: retail 25%, institutional 35%, algo 25%, contrarian 15% (inverted).
    Returns (crowd_score 0-100, consensus label).
    """
    retail_s        = float(personas.get('retail', {}).get('sentiment', 50))
    institutional_s = float(personas.get('institutional', {}).get('sentiment', 50))
    algo_s          = float(personas.get('algo', {}).get('sentiment', 50))
    contrarian_s    = float(personas.get('contrarian', {}).get('sentiment', 50))

    # Contrarian is inverted: contrarian bullish (high) = slight negative signal
    contrarian_inverted = 100 - contrarian_s

    score = (
        retail_s        * 0.25
        + institutional_s * 0.35
        + algo_s          * 0.25
        + contrarian_inverted * 0.15
    )
    score = max(0.0, min(100.0, score))

    if score >= 65:
        consensus = 'BULLISH'
    elif score >= 40:
        consensus = 'MIXED'
    else:
        consensus = 'BEARISH'

    return round(score, 1), consensus


# ─── Main public function ─────────────────────────────────────────────────────

def simulate_crowd_reaction(
    thesis_id: str,
    scenario: str,
    current_price_context: dict,
) -> dict:
    """
    Simulates how 4 market participant types react to a thesis/scenario.

    Parameters
    ----------
    thesis_id : str
        e.g. "S2", "PS17"
    scenario : str
        Short description of the current market event/trigger.
        e.g. "EU erhöht Verteidigungsbudget auf 3% BIP"
    current_price_context : dict
        Keys: ticker, price, change_pct_1d, change_pct_5d (may be empty).

    Returns
    -------
    dict with keys:
        crowd_score (float, 0-100),
        breakdown (dict per persona),
        consensus ('BULLISH'|'MIXED'|'BEARISH'),
        reasoning (str summary),
        cached (bool),
        error (str or None)
    """
    key = _cache_key(thesis_id, scenario)

    # Check cache first
    cached_result = _get_cached(key)
    if cached_result is not None:
        cached_result['cached'] = True
        return cached_result

    # Load thesis
    thesis_cfg = _load_thesis(thesis_id)
    thesis_text = thesis_cfg.get('thesis', '')
    thesis_name = thesis_cfg.get('name', thesis_id)
    entry_trigger = thesis_cfg.get('entry_trigger', '')
    kt_raw = thesis_cfg.get('kill_trigger', '')
    # Phase 22: kill_trigger ist Liste — für Prompt zu Text konvertieren
    if isinstance(kt_raw, list):
        kill_trigger = ' | '.join(str(x) for x in kt_raw) if kt_raw else 'nicht definiert'
    else:
        kill_trigger = str(kt_raw) if kt_raw else 'nicht definiert'

    # Build price context string
    price_parts = []
    if current_price_context:
        ticker = current_price_context.get('ticker', '')
        price  = current_price_context.get('price', '')
        chg1d  = current_price_context.get('change_pct_1d', '')
        chg5d  = current_price_context.get('change_pct_5d', '')
        if ticker:
            price_parts.append(f"Ticker: {ticker}")
        if price:
            price_parts.append(f"Kurs: {price}")
        if chg1d != '':
            price_parts.append(f"1T-Performance: {chg1d}%")
        if chg5d != '':
            price_parts.append(f"5T-Performance: {chg5d}%")

    price_str = '\n'.join(price_parts) if price_parts else 'Keine Kursdaten verfügbar'

    user_prompt = f"""These ID: {thesis_id} — {thesis_name}
These: {thesis_text}
Entry-Trigger: {entry_trigger}
Kill-Trigger: {kill_trigger}

Aktuelles Szenario/Ereignis: {scenario}

Kursinformation:
{price_str}

Simuliere die Reaktion der 4 Marktteilnehmer-Typen:
1. Retail Trader (emotional, trend-following, liest Headlines)
2. Institutional Investor (fundamental, geduldig, denkt in Quartalen)
3. Algo/Quant Fund (momentum-getrieben, reagiert auf Preis-/Volumensignale)
4. Contrarian (faded überfüllte Trades, sucht Erschöpfung)"""

    try:
        personas = _call_claude(user_prompt)
    except Exception as e:
        return {
            'crowd_score': 50.0,
            'breakdown': {},
            'consensus': 'MIXED',
            'reasoning': f'Claude call failed: {e}',
            'cached': False,
            'error': str(e),
        }

    try:
        crowd_score, consensus = _calculate_crowd_score(personas)
    except Exception as e:
        return {
            'crowd_score': 50.0,
            'breakdown': personas,
            'consensus': 'MIXED',
            'reasoning': f'Score calculation failed: {e}',
            'cached': False,
            'error': str(e),
        }

    # Build reasoning summary
    reasoning_parts = []
    for persona, data in personas.items():
        if isinstance(data, dict):
            reasoning_parts.append(
                f"{persona.upper()} ({data.get('action','?')} sentiment={data.get('sentiment','?')}): "
                f"{data.get('reasoning', '')}"
            )
    reasoning = ' | '.join(reasoning_parts)

    result = {
        'crowd_score': crowd_score,
        'breakdown': personas,
        'consensus': consensus,
        'reasoning': reasoning,
        'cached': False,
        'error': None,
    }

    _set_cached(key, result)
    return result


# ─── Simplified modifier for conviction scorer ────────────────────────────────

def get_crowd_modifier(thesis_id: str, scenario: str) -> int:
    """
    Simplified wrapper returning an integer modifier for the conviction scorer.

    Returns
    -------
    int in range -15 to +15.
    BULLISH consensus (score >= 65): +10 to +15
    MIXED consensus (40-64):         -5 to +5
    BEARISH consensus (< 40):        -15 to -10
    Returns 0 on any error (fail silently).
    """
    try:
        result = simulate_crowd_reaction(thesis_id, scenario, {})

        if result.get('error'):
            return 0

        score     = result.get('crowd_score', 50.0)
        consensus = result.get('consensus', 'MIXED')

        if consensus == 'BULLISH':
            # Scale +10 to +15 based on score (65-100)
            modifier = int(round(10 + (score - 65) / 35 * 5))
            return max(10, min(15, modifier))

        elif consensus == 'BEARISH':
            # Scale -15 to -10 based on score (0-39)
            modifier = int(round(-15 + (score / 40) * 5))
            return max(-15, min(-10, modifier))

        else:
            # MIXED: scale -5 to +5 based on score (40-64)
            modifier = int(round(-5 + (score - 40) / 25 * 10))
            return max(-5, min(5, modifier))

    except Exception:
        return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    thesis_id = sys.argv[1] if len(sys.argv) > 1 else 'PS1'
    scenario  = sys.argv[2] if len(sys.argv) > 2 else 'Testlauf Crowd-Simulation'

    print(f'Simuliere Crowd-Reaktion für {thesis_id}: {scenario}')
    result = simulate_crowd_reaction(thesis_id, scenario, {})

    print(f'Crowd Score:  {result["crowd_score"]}/100')
    print(f'Consensus:    {result["consensus"]}')
    print(f'Cached:       {result["cached"]}')
    if result.get("error"):
        print(f'Error:        {result["error"]}')
    print()
    for persona, data in result.get('breakdown', {}).items():
        if isinstance(data, dict):
            print(f'  {persona:15} sentiment={data.get("sentiment"):3}  action={data.get("action","?"):15}  {data.get("reasoning","")}')

    modifier = get_crowd_modifier(thesis_id, scenario)
    print(f'\nConviction modifier: {modifier:+d}')
