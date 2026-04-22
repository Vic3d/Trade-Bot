#!/usr/bin/env python3
"""
Scenario Mapper — Phase 22
============================
Fuer jedes Top-Catalyst (importance >= 4) in den naechsten 14 Tagen:
  - Claude generiert 3 Szenarien (bull / base / bear) mit Wahrscheinlichkeiten
  - Fuer jedes Szenario: Winners + Losers + Size-Empfehlung
  - Aggregation zu data/scenario_map.json

Gekoppelt an Deep-Dive-Prompt: auto_deep_dive.py liest die Map und reichert
jeden Ticker-Deep-Dive mit passendem Szenario-Kontext an.

Laeuft: tgl. 06:30 CET (nach Catalyst Calendar 06:20).
CLI:
  python3 scripts/scenario_mapper.py
  python3 scripts/scenario_mapper.py --top 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
CAT_FILE = WS / 'data' / 'catalyst_calendar.json'
OUT = WS / 'data' / 'scenario_map.json'

sys.path.insert(0, str(WS / 'scripts'))


def _load_catalysts(top_n: int = 5, horizon_days: int = 14) -> list[dict]:
    if not CAT_FILE.exists():
        print('[scenario] catalyst_calendar.json fehlt — Catalyst Calendar erst laufen lassen')
        return []
    data = json.loads(CAT_FILE.read_text(encoding='utf-8'))
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=horizon_days)
    eligible = []
    for e in data.get('events', []):
        try:
            dt = datetime.strptime(e['date'], '%Y-%m-%d').date()
            if today <= dt <= horizon and e.get('importance', 3) >= 4:
                eligible.append(e)
        except Exception:
            continue
    eligible.sort(key=lambda r: (-r.get('importance', 3), r['date']))
    return eligible[:top_n]


def _get_regime_context() -> str:
    try:
        ceo_path = WS / 'data' / 'ceo_directive.json'
        if ceo_path.exists():
            d = json.loads(ceo_path.read_text(encoding='utf-8'))
            return (
                f"Regime: {d.get('regime','?')} | VIX: {d.get('vix','?')} | "
                f"Geo-Score: {d.get('geo_score','?')} | Mode: {d.get('mode','?')}"
            )
    except Exception:
        pass
    return 'Regime: unbekannt'


def _get_recent_news(limit: int = 15) -> list[str]:
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.execute("""
          SELECT title, source, published_at
          FROM news_events
          WHERE published_at > datetime('now','-1 day')
          ORDER BY published_at DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [f"[{r[1]}] {r[0][:120]}" for r in rows]
    except Exception:
        return []


def build_prompt(catalysts: list[dict], regime: str, news: list[str]) -> str:
    cat_lines = []
    for c in catalysts:
        cat_lines.append(
            f"- {c['date']} [{c['type']}] {c.get('ticker') or '-'}: "
            f"{c.get('description','')[:140]} (imp={c.get('importance')})"
        )
    cat_block = '\n'.join(cat_lines) if cat_lines else '(keine)'
    news_block = '\n'.join(f"- {n}" for n in news[:12]) if news else '(keine)'

    return f"""Du bist Albert, Senior Macro-Strategist bei TradeMind.
Dein Auftrag: Fuer jeden der Top-Katalysatoren unten erstelle ein 3-Szenarien-Mapping
(bull / base / bear) im Stil eines Pro-Hedge-Funds.

### MARKT-KONTEXT
{regime}

### TOP-KATALYSATOREN (naechste 14 Tage)
{cat_block}

### RECENT NEWS (letzte 24h, fuer Positionierung)
{news_block}

### DEINE AUFGABE
Fuer JEDEN Katalysator liefere:
- 3 Szenarien mit Wahrscheinlichkeiten (P bull + P base + P bear = 1.0)
- Fuer jedes Szenario: 3-5 Winner-Ticker + 3-5 Loser-Ticker (US + EU)
- Erwartete Rendite in % fuer Winners/Losers (14-Tage-Horizont)
- Consensus-Positionierung (wo steht der Markt bereits?)
- Pain-Trade-Direction (wo ist der Konsens falsch positioniert?)

### OUTPUT-FORMAT (streng JSON, keine Markdown)
{{
  "generated_at": "<iso>",
  "regime_context": "{regime}",
  "top_catalysts": [
    {{
      "id": "<catalyst-id oder make_id>",
      "date": "YYYY-MM-DD",
      "type": "FOMC|EARNINGS|...",
      "name": "<kurz>",
      "summary": "<2 saetze, worum es geht>",
      "scenarios": [
        {{
          "label": "bull",
          "probability": 0.40,
          "description": "<was passiert>",
          "winners": [{{"ticker":"MSFT","expected_pct":5.0,"rationale":"<kurz>"}}, ...],
          "losers":  [{{"ticker":"OXY","expected_pct":-6.0,"rationale":"<kurz>"}}, ...]
        }},
        {{"label":"base","probability":0.35, ...}},
        {{"label":"bear","probability":0.25, ...}}
      ],
      "consensus_position": "<crowded_long_tech|crowded_short_oil|neutral|...>",
      "pain_trade": "<long_gold|short_spy|...>"
    }}
  ],
  "portfolio_implications": {{
    "currently_holding": "<kurze einschaetzung aktueller Positionen>",
    "hedge_recommendations": ["<einzelner trade-vorschlag>", ...],
    "to_avoid": ["<sektor/ticker>", ...]
  }}
}}

WICHTIG: Sei KONKRET mit Tickern (nicht 'Tech-Sektor' sondern 'MSFT, NVDA, GOOGL').
Keine weichen Aussagen — jedes Szenario braucht quantifizierte Probability + Payoff.

### JSON-STRIKT-REGELN (CRITICAL)
- Nur ASCII-Doppel-Quotes "..." in JSON. KEINE typografischen „deutschen" Anfuehrungszeichen.
- Keine Kommentare (// oder /* */), keine trailing Kommas, keine Markdown-Fences.
- Innerhalb von Strings: Doppel-Quotes mit \\ escapen. Kein Apostroph-Problem.
- Antworte AUSSCHLIESSLICH mit valide JSON. Kein Text davor/danach.
"""


def call_claude(prompt: str) -> tuple[str, dict]:
    """Dual-LLM (Anthropic primaer, OpenAI-Fallback)."""
    try:
        from core.llm_client import call_llm
    except ImportError:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parent))
        from core.llm_client import call_llm  # type: ignore
    _m = (os.getenv('ANTHROPIC_MODEL') or 'sonnet').lower()
    hint = 'opus' if 'opus' in _m else ('haiku' if 'haiku' in _m else 'sonnet')
    # Bug P (2026-04-22): 4000 tokens reichten nicht für 4+ Catalysts × 3 Szenarien
    # mit Winners/Losers. Output wurde mitten im JSON abgeschnitten → Parse-Fehler.
    # Auf 8000 erhöht (Sonnet/Opus unterstützen >>8k).
    return call_llm(prompt, model_hint=hint, max_tokens=8000)


def parse_json(text: str) -> dict:
    # Trim zu ```json fences
    t = text.strip()
    if '```' in t:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', t)
        if m:
            t = m.group(1).strip()
    m = re.search(r'\{[\s\S]*\}', t)
    if not m:
        # Bug P: Truncation erkennen — kein schließendes } gefunden.
        if t.lstrip().startswith('{') and not t.rstrip().endswith('}'):
            raise ValueError(f'JSON truncated (max_tokens?) — {len(t)} chars, '
                             f'tail: ...{t[-80:]!r}')
        raise ValueError('Kein JSON im Claude-Output')
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Heuristische Repair: Trailing commas entfernen
        fixed = re.sub(r',(\s*[\]}])', r'\1', raw)
        # Typografische Quotes -> ASCII
        fixed = fixed.replace('„', '"').replace('"', '"').replace('"', '"').replace(''', "'").replace(''', "'")
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e2:
            # Letzter Versuch: Debug-Dump schreiben
            try:
                Path('/tmp/scenario_raw.json').write_text(raw, encoding='utf-8')
            except Exception:
                pass
            raise


def run(top_n: int = 5) -> dict:
    catalysts = _load_catalysts(top_n=top_n)
    if not catalysts:
        print('[scenario] Keine passenden Katalysatoren — nichts zu mappen')
        # Leere Map schreiben damit DD nicht crasht
        OUT.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'top_catalysts': []}, indent=2))
        return {'status': 'ok', 'mapped': 0}

    regime = _get_regime_context()
    news = _get_recent_news()
    prompt = build_prompt(catalysts, regime, news)

    print(f'[scenario] Mapping {len(catalysts)} Katalysatoren via Claude...')
    try:
        text, usage = call_claude(prompt)
    except Exception as e:
        print(f'[scenario] Claude-Fehler: {e}')
        return {'status': 'error', 'error': str(e)}

    try:
        parsed = parse_json(text)
    except Exception as e:
        print(f'[scenario] Parse-Fehler: {e}\nRaw:\n{text[:500]}')
        return {'status': 'error', 'error': f'parse: {e}'}

    parsed['generated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    parsed['catalysts_mapped'] = len(catalysts)
    parsed['claude_usage'] = usage

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"[scenario] ✅ {len(parsed.get('top_catalysts',[]))} Szenarien geschrieben → {OUT}")
    print(f"[scenario] Kosten: ${usage.get('cost_usd_est',0):.3f}")

    # Kurzuebersicht
    for c in parsed.get('top_catalysts', [])[:3]:
        print(f"\n  ▸ {c.get('date')} {c.get('name','?')}")
        for s in c.get('scenarios', []):
            winners = ','.join(w.get('ticker','?') for w in s.get('winners', [])[:4])
            print(f"     · {s.get('label','?')} P={s.get('probability')}: Winners {winners}")

    return {'status': 'ok', 'mapped': len(catalysts), 'cost_usd': usage.get('cost_usd_est', 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=5)
    args = ap.parse_args()
    r = run(top_n=args.top)
    sys.exit(0 if r.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
