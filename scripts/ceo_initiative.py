#!/usr/bin/env python3
"""
ceo_initiative.py — Phase 43 Pillar D: Eigeninitiative.

CEO darf basierend auf News/Macro-Events selbst:
  · Tickers zu bestehenden Strategien hinzufügen
  · Neue Strategie-Hypothesen vorschlagen (zum Review, nicht auto-aktiviert)
  · Lifecycle-State-Vorschläge für stagnierende Strategien

Sicherheits-Guardrails:
  · KEINE permanenten Blacklist-Aufhebungen (AR-AGRA bleibt geblockt)
  · KEINE neuen Strategien ohne Review (vorschlagen, nicht aktivieren)
  · Ticker-Adds: max 3 pro Tag pro Strategie, max 5 Strategien pro Tag
  · Alle Aktionen geloggt in data/ceo_initiative_log.jsonl

Usage:
  from ceo_initiative import propose_initiatives
  result = propose_initiatives()  # Daemon ruft das täglich
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
STRATEGIES_FILE = WS / 'data' / 'strategies.json'
INITIATIVE_LOG  = WS / 'data' / 'ceo_initiative_log.jsonl'

# Permanent geblockte Strategien — NIE anfassen
PERMANENT_BLOCKED = {'AR-AGRA', 'AR-HALB', 'DT1', 'DT2', 'DT3', 'DT4', 'DT5'}
MAX_TICKER_ADDS_PER_STRAT = 3
MAX_STRATS_TOUCHED_PER_DAY = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_initiative(action: str, payload: dict) -> None:
    INITIATIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(INITIATIVE_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': _now_iso(), 'action': action, **payload
        }, ensure_ascii=False) + '\n')


def _load_strategies() -> dict:
    if not STRATEGIES_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_strategies(strats: dict) -> None:
    STRATEGIES_FILE.write_text(
        json.dumps(strats, indent=2, ensure_ascii=False), encoding='utf-8'
    )


def _strats_touched_today() -> int:
    """Wie viele Strategien wurden heute schon angefasst?"""
    if not INITIATIVE_LOG.exists():
        return 0
    today = datetime.utcnow().strftime('%Y-%m-%d')
    seen = set()
    try:
        with open(INITIATIVE_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('ts', '').startswith(today):
                        seen.add(d.get('strategy_id', ''))
                except Exception:
                    continue
    except Exception:
        pass
    seen.discard('')
    return len(seen)


def gather_initiative_context() -> dict:
    """Sammle Kontext für CEO-Initiative-Run."""
    import sqlite3
    ctx = {'recent_macro': [], 'recent_news_tickers': [], 'active_strategies': []}

    try:
        c = sqlite3.connect(str(DB))
        # Macro events letzte 24h
        try:
            macro = c.execute(
                "SELECT event_type, severity, impact_tickers, detected_at "
                "FROM macro_events "
                "WHERE detected_at >= datetime('now','-24 hours') "
                "ORDER BY severity DESC LIMIT 10"
            ).fetchall()
            ctx['recent_macro'] = [
                {'type': r[0], 'severity': r[1], 'impact_tickers': r[2],
                 'detected_at': r[3]} for r in macro
            ]
        except Exception:
            pass

        # News letzte 24h mit hohen relevance scores → tickers extrahieren
        from collections import Counter
        rows = c.execute(
            "SELECT tickers FROM news_events "
            "WHERE created_at >= datetime('now','-24 hours') "
            "AND relevance_score >= 0.6 AND tickers IS NOT NULL"
        ).fetchall()
        ticker_count = Counter()
        for (t,) in rows:
            try:
                tlist = json.loads(t) if isinstance(t, str) else []
                for tk in tlist:
                    ticker_count[tk] += 1
            except Exception:
                pass
        ctx['recent_news_tickers'] = ticker_count.most_common(20)
        c.close()
    except Exception:
        pass

    strats = _load_strategies()
    for sid, s in strats.items():
        if not isinstance(s, dict) or sid in PERMANENT_BLOCKED:
            continue
        if s.get('status') != 'active':
            continue
        ctx['active_strategies'].append({
            'id': sid,
            'name': s.get('name', '')[:50],
            'sector': s.get('sector', ''),
            'tickers': s.get('tickers', []),
            'thesis': str(s.get('thesis', ''))[:120],
        })

    return ctx


INITIATIVE_PROMPT_TEMPLATE = """Du bist Albert (CEO Phase 43 Pillar D — Eigeninitiative).
Du darfst BEHUTSAM Tickers zu bestehenden Strategien ergänzen wenn:
  · Eine Macro-Event-Story die Strategie-These DIREKT unterstützt
  · Ein Ticker mehrfach in News genannt wird UND zur Strategy-Sector passt
  · Maximal 3 Adds pro Strategie, max 5 Strategien insgesamt heute
  · KEIN Add zu permanent geblockten Strategien

═══ AKTIVE MACRO-EVENTS LETZTE 24H ═══
{macro_str}

═══ TOP-NEWS-TICKERS LETZTE 24H ═══
{news_str}

═══ AKTIVE STRATEGIEN ═══
{strats_str}

Wenn DIREKTER Match (Strategy-Thesis + Macro-Event + News-Ticker): adde.
Sonst: keine Action.

ANTWORT STRIKT JSON:
{{
  "thinking": "1-2 Sätze",
  "ticker_adds": [
    {{
      "strategy_id": "PS5",
      "tickers": ["NTR"],   // max 3 pro Strategie
      "reason": "1 Satz: warum passt der Ticker zur These"
    }}
  ]
}}

Keine Action = ticker_adds: []."""


def call_initiative_llm(ctx: dict) -> dict | None:
    macro_lines = []
    for m in ctx['recent_macro'][:5]:
        macro_lines.append(
            f"  · [{m['severity']}] {m['type']} → {m['impact_tickers'][:60]}"
        )
    macro_str = '\n'.join(macro_lines) or '  (keine)'

    news_lines = [f"  · {t}: {n}x" for t, n in ctx['recent_news_tickers'][:15]]
    news_str = '\n'.join(news_lines) or '  (keine)'

    strats_lines = []
    for s in ctx['active_strategies'][:20]:
        strats_lines.append(
            f"  · {s['id']:<10} [{s['sector']:<10}] tickers={s['tickers']} "
            f"| thesis: {s['thesis']}"
        )
    strats_str = '\n'.join(strats_lines) or '  (keine)'

    prompt = INITIATIVE_PROMPT_TEMPLATE.format(
        macro_str=macro_str, news_str=news_str, strats_str=strats_str
    )

    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=1200)
    except Exception as e:
        print(f'[initiative] LLM err: {e}', file=sys.stderr)
        return None

    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
    i, j = text.find('{'), text.rfind('}')
    if i < 0:
        return None
    try:
        return json.loads(text[i:j+1])
    except Exception as e:
        print(f'[initiative] JSON err: {e}', file=sys.stderr)
        return None


def apply_ticker_adds(adds: list[dict]) -> dict:
    """Wende Ticker-Adds an, mit allen Guardrails."""
    result = {'attempted': len(adds), 'applied': 0, 'skipped': []}
    if _strats_touched_today() >= MAX_STRATS_TOUCHED_PER_DAY:
        result['skipped'].append('daily_max_strategies_touched')
        return result

    strats = _load_strategies()
    for a in adds:
        sid = a.get('strategy_id')
        new_tickers = a.get('tickers', [])
        reason = a.get('reason', '')
        if sid in PERMANENT_BLOCKED:
            result['skipped'].append(f'{sid}: permanent_blocked')
            continue
        if sid not in strats:
            result['skipped'].append(f'{sid}: unknown')
            continue
        if not isinstance(new_tickers, list) or not new_tickers:
            result['skipped'].append(f'{sid}: empty tickers')
            continue
        new_tickers = new_tickers[:MAX_TICKER_ADDS_PER_STRAT]

        existing = strats[sid].get('tickers', []) or []
        added_now = []
        for tk in new_tickers:
            if not tk or tk in existing:
                continue
            existing.append(tk)
            added_now.append(tk)
        if not added_now:
            result['skipped'].append(f'{sid}: no_new_tickers')
            continue
        strats[sid]['tickers'] = existing
        strats[sid].setdefault('genesis', {}).setdefault('feedback_history', []).append({
            'date': datetime.utcnow().strftime('%Y-%m-%d'),
            'action': 'ceo_initiative_ticker_add',
            'reason': reason,
            'added_tickers': added_now,
        })
        _log_initiative('ticker_add', {
            'strategy_id': sid, 'tickers': added_now, 'reason': reason,
        })
        result['applied'] += 1

    if result['applied']:
        _save_strategies(strats)
    return result


def propose_initiatives(dry_run: bool = False) -> dict:
    """Hauptfunktion: gather → LLM → apply."""
    ctx = gather_initiative_context()
    if not ctx['active_strategies']:
        return {'error': 'no_active_strategies'}

    response = call_initiative_llm(ctx)
    if not response:
        return {'error': 'llm_failed'}

    adds = response.get('ticker_adds', [])
    thinking = str(response.get('thinking', ''))[:300]

    if dry_run:
        return {
            'thinking': thinking,
            'proposed_adds': adds,
            'dry_run': True,
        }

    apply_result = apply_ticker_adds(adds)
    return {
        'thinking': thinking,
        'proposed_adds': adds,
        'apply_result': apply_result,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print(f'═══ CEO Initiative @ {_now_iso()} ═══')
    r = propose_initiatives(dry_run=args.dry_run)
    if r.get('error'):
        print(f'❌ {r["error"]}')
        return 1
    print(f'Thinking: {r["thinking"]}')
    print(f'Proposed adds: {len(r["proposed_adds"])}')
    for a in r['proposed_adds']:
        print(f"  · {a.get('strategy_id', '?')} += {a.get('tickers', [])} "
              f"({a.get('reason', '')[:80]})")
    if not args.dry_run:
        ar = r.get('apply_result', {})
        print(f'\nApplied: {ar.get("applied", 0)} / {ar.get("attempted", 0)}')
        for sk in ar.get('skipped', []):
            print(f'  skipped: {sk}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
