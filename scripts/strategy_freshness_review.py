#!/usr/bin/env python3
"""
strategy_freshness_review.py — Phase 45bb (Victor 2026-05-14).

Victor: "Es kann nicht sein, dass Albert nach Strategien von MÄRZ immer noch
handelt. Eine Strategie hat eine Lebensdauer — wenn die erreicht ist, MUSS
sie neu verifiziert werden."

Problem: Strategien wurden bisher nur auf PERFORMANCE geprüft (Lifecycle-Audit,
alpha_decay). Niemand prüft, ob die THESE inhaltlich noch aktuell ist. Eine
Iran-Eskalations-These vom 01.03. kann längst überholt sein — das System
handelt sie trotzdem weiter.

Dieses Skript = inhaltliche Haltbarkeits-Prüfung:
  1. Jede aktive Strategie hat eine Lebensdauer (LIFESPAN_DAYS).
  2. Stichtag = last_verified, sonst genesis.created. Kein Datum → sofort fällig.
  3. Überfällige Strategien werden gebündelt an Opus gegeben mit aktuellem
     Markt-/Macro-Kontext. Verdict pro Strategie:
       STILL_VALID    → last_verified = heute, bleibt aktiv
       NEEDS_REVISION → status = paused (Strategist kann überarbeiten)
       OUTDATED       → status = retired (These ist tot)
  4. Report → strategy_freshness_log.jsonl + ceo_inbox.

Run: täglich 05:30 (vor Genesis 06:20 — Genesis sieht den bereinigten Stand).
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime, timezone, date
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
STRATS_FILE = WS / 'data' / 'strategies.json'
MARKET_PULSE = WS / 'data' / 'market_pulse_latest.json'
MACRO_REGIME = WS / 'data' / 'macro_regime.json'
LOG = WS / 'data' / 'strategy_freshness_log.jsonl'

LIFESPAN_DAYS = 30          # nach 30 Tagen muss eine These neu verifiziert werden
DEAD_STATUSES = {'paused', 'retired', 'auto_deprecated', 'ARCHIVED', 'DRAFT'}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _parse_date(s) -> date | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S%z'):
        try:
            return datetime.strptime(s[:len(fmt) + 6 if '%z' in fmt else len(fmt)], fmt).date()
        except Exception:
            continue
    # ISO-Fallback
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).date()
    except Exception:
        return None


def _stichtag(meta: dict) -> date | None:
    """last_verified gewinnt, sonst genesis.created."""
    d = _parse_date(meta.get('last_verified'))
    if d:
        return d
    g = meta.get('genesis')
    if isinstance(g, dict):
        return _parse_date(g.get('created'))
    return None


def _find_stale(strats: dict, today: date) -> list[tuple[str, dict, int]]:
    """Returns [(sid, meta, age_days)] für überfällige aktive Strategien."""
    stale = []
    for sid, meta in strats.items():
        if not isinstance(meta, dict):
            continue
        if sid in ('_config', 'emerging_themes'):
            continue
        if meta.get('status') in DEAD_STATUSES:
            continue
        st = _stichtag(meta)
        if st is None:
            age = 9999  # kein Datum → sofort fällig
        else:
            age = (today - st).days
        if age >= LIFESPAN_DAYS:
            stale.append((sid, meta, age))
    return stale


def _market_context() -> str:
    pulse = _load(MARKET_PULSE, {})
    regime = _load(MACRO_REGIME, {})
    parts = []
    if regime:
        parts.append(f"Macro-Regime: {json.dumps(regime, ensure_ascii=False)[:300]}")
    top = pulse.get('top_5d', [])[:6]
    bot = pulse.get('bottom_5d', [])[:6]
    if top:
        parts.append("Top-Sektoren 5d: " + ', '.join(
            f"{e.get('ticker')} {e.get('chg_5d')}%" for e in top if isinstance(e, dict)))
    if bot:
        parts.append("Schwächste 5d: " + ', '.join(
            f"{e.get('ticker')} {e.get('chg_5d')}%" for e in bot if isinstance(e, dict)))
    return '\n'.join(parts) or '(kein Markt-Kontext verfügbar)'


def _build_prompt(stale: list, ctx: str, today: date) -> str:
    lines = []
    for sid, meta, age in stale:
        g = meta.get('genesis') or {}
        trig = g.get('trigger', '') if isinstance(g, dict) else ''
        lines.append(
            f"### {sid} (Alter: {age}d)\n"
            f"Name: {meta.get('name', sid)}\n"
            f"These: {(meta.get('thesis') or '')[:600]}\n"
            f"Ursprünglicher Auslöser: {str(trig)[:300]}\n"
        )
    strat_block = '\n'.join(lines)
    return f"""Du bist Albert, AI-CEO eines Trading-Systems. Heute ist {today.isoformat()}.

Die folgenden Strategien sind älter als {LIFESPAN_DAYS} Tage und müssen auf
INHALTLICHE Aktualität geprüft werden — NICHT auf Performance, sondern: "Ist
die These angesichts der heutigen Weltlage überhaupt noch gültig?"

AKTUELLER MARKT-/MACRO-KONTEXT:
{ctx}

ZU PRÜFENDE STRATEGIEN:
{strat_block}

Für JEDE Strategie ein Verdict:
- STILL_VALID    — These trägt heute noch, Markt bestätigt sie oder sie ist neutral-gültig
- NEEDS_REVISION — Kern-Idee ok, aber Auslöser/Ticker/Timing veraltet — gehört überarbeitet
- OUTDATED       — These ist überholt, das auslösende Ereignis ist vorbei/widerlegt — tot

Sei streng. Eine geopolitische These, deren Ereignis vor 2 Monaten war und
nicht mehr in den Nachrichten ist, ist OUTDATED, nicht STILL_VALID.

Antworte AUSSCHLIESSLICH mit einem JSON-Array, nichts davor/danach:
[{{"strategy": "PS2", "verdict": "STILL_VALID|NEEDS_REVISION|OUTDATED", "reason": "1-2 Sätze, konkret"}}]
"""


def _llm_verdicts(prompt: str) -> list[dict]:
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        sys.path.insert(0, str(WS / 'scripts' / 'core'))
        from llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='opus', max_tokens=3000,
                           audit_context='strategy_freshness')
    except Exception as e:
        return [{'_error': f'llm_fail: {e}'}]
    m = re.search(r'\[.*\]', text, re.S)
    if not m:
        return [{'_error': 'no_json_array_in_response'}]
    try:
        return json.loads(m.group(0))
    except Exception as e:
        return [{'_error': f'json_parse_fail: {e}'}]


def review() -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    strats = _load(STRATS_FILE, {})
    if not isinstance(strats, dict):
        return {'error': 'strategies.json kein dict'}

    stale = _find_stale(strats, today)
    if not stale:
        return {'ts': now.isoformat(timespec='seconds'), 'stale_found': 0,
                'message': 'Alle aktiven Strategien innerhalb der Lebensdauer.'}

    verdicts = _llm_verdicts(_build_prompt(stale, _market_context(), today))
    if verdicts and verdicts[0].get('_error'):
        return {'ts': now.isoformat(timespec='seconds'), 'stale_found': len(stale),
                'error': verdicts[0]['_error'],
                'stale': [s[0] for s in stale]}

    vmap = {v.get('strategy'): v for v in verdicts if isinstance(v, dict) and v.get('strategy')}

    results = {'still_valid': [], 'needs_revision': [], 'outdated': [], 'no_verdict': []}
    for sid, meta, age in stale:
        v = vmap.get(sid)
        if not v:
            results['no_verdict'].append(sid)
            continue
        verdict = str(v.get('verdict', '')).upper()
        reason = (v.get('reason') or '')[:400]
        fresh = {'verdict': verdict, 'reason': reason,
                 'reviewed_at': now.isoformat(timespec='seconds'), 'age_days': age}
        if verdict == 'STILL_VALID':
            meta['last_verified'] = today.isoformat()
            meta['freshness'] = fresh
            results['still_valid'].append(sid)
        elif verdict == 'NEEDS_REVISION':
            meta['status'] = 'paused'
            meta['freshness'] = fresh
            results['needs_revision'].append({'sid': sid, 'reason': reason})
        elif verdict == 'OUTDATED':
            meta['status'] = 'retired'
            meta['freshness'] = fresh
            results['outdated'].append({'sid': sid, 'reason': reason})
        else:
            results['no_verdict'].append(sid)

    # Persist
    changed = (results['still_valid'] or results['needs_revision']
               or results['outdated'])
    if changed:
        try:
            from atomic_json import atomic_write_json  # type: ignore
            atomic_write_json(STRATS_FILE, strats)
        except Exception:
            tmp = STRATS_FILE.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(strats, ensure_ascii=False, indent=1),
                           encoding='utf-8')
            tmp.replace(STRATS_FILE)

    record = {
        'ts': now.isoformat(timespec='seconds'),
        'stale_found': len(stale),
        'still_valid': results['still_valid'],
        'needs_revision': results['needs_revision'],
        'outdated': results['outdated'],
        'no_verdict': results['no_verdict'],
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    # CEO-Inbox
    try:
        from ceo_inbox import write_event
        n_killed = len(results['outdated']) + len(results['needs_revision'])
        msg = (f'Strategie-Haltbarkeitsprüfung: {len(stale)} überfällig — '
               f'{len(results["still_valid"])} bestätigt, '
               f'{len(results["needs_revision"])} pausiert (Revision nötig), '
               f'{len(results["outdated"])} retired (These tot).')
        write_event(
            event_type='strategy.freshness_review',
            message=msg,
            severity='warning' if n_killed else 'info',
            category='health', user_pinged=False,
            payload=record,
        )
    except Exception:
        pass

    return record


def main() -> int:
    r = review()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
