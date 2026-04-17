#!/usr/bin/env python3
"""
Thesis Generator — Phase 22 (AUTONOMER KERN)
==============================================
Alle 12h: Claude bekommt
  - Top-Katalysatoren (naechste 14 Tage)
  - Scenario-Map (3-Szenarien pro Katalysator)
  - Pain-Trade-Positionierung
  - Aktuelle Portfolio-Exposure
  - Recent News (Top-30)
  - Bereits geprueft & abgelehnt (Thesis Graveyard)

und generiert 5 neue Trade-Thesen mit vollstaendigem Setup:
  - Ticker, Catalyst-Date, Scenario-Trigger
  - Entry, Stop, Target, EV, Skew
  - Falsifikations-Kriterium
  - Portfolio-Diversifikations-Check

Die Thesen werden:
  1. In data/generated_theses.jsonl archiviert
  2. Als candidate_tickers mit priority=1.2 + source_type='generated_thesis' geaddet
  3. Von auto_deep_dive_runner automatisch durchgeprueft
  4. Bei EV>+€10 und Deep-Dive KAUFEN → Probation-Strategy in strategies.json

Laeuft: 07:15 + 19:15 CET
CLI:
  python3 scripts/thesis_generator.py
  python3 scripts/thesis_generator.py --count 3 --dry
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DB = WS / 'data' / 'trading.db'
OUT_JSONL = WS / 'data' / 'generated_theses.jsonl'
SCEN_FILE = WS / 'data' / 'scenario_map.json'
POS_FILE = WS / 'data' / 'positioning.json'
CAT_FILE = WS / 'data' / 'catalyst_calendar.json'
GRAVE_FILE = WS / 'data' / 'thesis_graveyard.json'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))


def _read_json(p: Path, default=None):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def _portfolio_snapshot() -> dict:
    """Aktuelle Portfolio-Exposure aus DB + strategies.json."""
    snap = {'open_positions': [], 'active_strategies': [], 'sector_exposure': {}}
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.execute("""
          SELECT ticker, strategy_id, entry_price, entry_date, position_size_eur
          FROM paper_trades WHERE status='OPEN'
        """)
        for r in cur.fetchall():
            snap['open_positions'].append({
                'ticker': r[0], 'strategy': r[1], 'entry_price': r[2],
                'entry_date': r[3], 'size_eur': r[4],
            })
        conn.close()
    except Exception:
        pass
    try:
        strats = _read_json(WS / 'data' / 'strategies.json', {})
        for sid, s in strats.items():
            if isinstance(s, dict) and s.get('status') == 'active':
                snap['active_strategies'].append({
                    'id': sid, 'name': s.get('name', '')[:60],
                    'sector': s.get('sector'), 'tickers': s.get('tickers', [])[:3],
                })
    except Exception:
        pass
    return snap


def _recent_news(limit: int = 25) -> list[str]:
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.execute("""
          SELECT title, source, published_at FROM news_events
          WHERE published_at > datetime('now','-2 days')
          ORDER BY published_at DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [f"[{r[1][:20]}] {r[0][:140]}" for r in rows]
    except Exception:
        return []


def _graveyard_entries(days: int = 30) -> list[str]:
    g = _read_json(GRAVE_FILE, {'entries': []}) or {'entries': []}
    entries = g.get('entries', []) if isinstance(g, dict) else []
    return [f"{e.get('ticker')} ({e.get('reason','?')[:50]})" for e in entries[-15:]]


def _existing_candidates() -> list[str]:
    try:
        from candidates import load_candidates
        cands = load_candidates()
        return sorted(cands.keys())
    except Exception:
        return []


def build_prompt(count: int) -> str:
    scen = _read_json(SCEN_FILE, {}) or {}
    pos = _read_json(POS_FILE, {}) or {}
    cats = _read_json(CAT_FILE, {}) or {}
    port = _portfolio_snapshot()
    news = _recent_news()
    grave = _graveyard_entries()
    existing = _existing_candidates()

    scen_block = json.dumps({
        'top_catalysts': [
            {
                'date': c.get('date'),
                'name': c.get('name'),
                'scenarios': [
                    {'label': s.get('label'), 'p': s.get('probability'),
                     'winners': [w.get('ticker') for w in s.get('winners', [])[:4]],
                     'losers': [l.get('ticker') for l in s.get('losers', [])[:4]]}
                    for s in c.get('scenarios', [])
                ],
            }
            for c in scen.get('top_catalysts', [])[:4]
        ],
    }, ensure_ascii=False, indent=1)[:3500]

    pos_block = json.dumps({
        'regime': pos.get('regime'),
        'vix_structure': pos.get('vix_structure'),
        'fear_greed': pos.get('fear_greed_score'),
        'crowded_longs': pos.get('crowded_longs', []),
        'underowned': pos.get('underowned_sectors', []),
    }, ensure_ascii=False)

    port_block = json.dumps({
        'open': [p['ticker'] for p in port['open_positions']],
        'active_strategies': [s['id'] for s in port['active_strategies'][:15]],
    }, ensure_ascii=False)

    return f"""Du bist Albert, Senior Portfolio Manager bei TradeMind.
Dein Auftrag: Generiere {count} NEUE Trade-Thesen im Stil eines Pro-Hedge-Funds.

### VERFUEGBARE KONTEXT-DATEN

#### Top-Katalysatoren + Scenario-Map
{scen_block}

#### Positionierung (Pain-Trade-Layer)
{pos_block}

#### Aktuelles Portfolio
{port_block}

#### Letzte News (Top-25, 48h)
{chr(10).join('- ' + n for n in news[:20])}

#### Bereits im Candidate-Pool (nicht nochmal vorschlagen)
{', '.join(existing[:30])}

#### Thesis-Graveyard (letzte 15 Ablehnungen — daraus lernen)
{chr(10).join('- ' + g for g in grave)}

### DEINE REGELN (Hard Constraints)

1. **Jede These MUSS einen Katalysator mit Datum in den naechsten 14 Tagen haben.**
2. **EV muss > +€50 sein** bei €1500 Position (= EV_pct > +3.3%).
3. **Skew >= 2.0** (bullish_case_pct / abs(bearish_case_pct)).
4. **Diversification:** Keine neue Position in einem Sektor, in dem Portfolio schon >30% exponiert ist.
5. **Pain-Trade-Bevorzugung:** Thesen die gegen den Konsens gehen bekommen +20% Ranking-Bonus.
6. **Kein Re-Try:** Nicht wieder Tickers vorschlagen die im Graveyard stehen (letzte 30 Tage).
7. **US + EU Mix:** Max 70% US-Tickers, mind. 1 EU-Ticker in den Vorschlaegen.

### DENK-RAHMEN (intern, nicht ausgeben)
- Welcher Katalysator hat die asymmetrischste Payoff-Struktur?
- Wer profitiert wenn bull-Szenario trifft (P>=30%)? Hat er bereits eingepreist?
- Gibt es einen Pain-Trade Kontext (crowded short der short-gesqueezed wird)?
- Welche 2 Positionen wuerden mein Portfolio am besten diversifizieren (vs aktuelle Exposure)?
- Wo fehlt mir noch Exposure zu einem wichtigen Szenario?

### OUTPUT (streng JSON, keine Markdown)
{{
  "generated_at": "<iso>",
  "theses": [
    {{
      "ticker": "MSFT",
      "name": "Microsoft — AI-Peace-Hedge",
      "direction": "long|short",
      "catalyst": "Fed-Pause + Iran-Deal",
      "catalyst_date": "2026-04-22",
      "scenario_trigger": "bull",
      "thesis_one_liner": "<1 satz, warum jetzt>",
      "entry_hint_pct": 0.0,
      "stop_pct": -6.0,
      "target_pct": 12.0,
      "horizon_days": 14,
      "probability_bull": 0.45,
      "return_bull_pct": 8.0,
      "probability_bear": 0.40,
      "return_bear_pct": -4.0,
      "probability_side": 0.15,
      "return_side_pct": 0.0,
      "ev_pct": 2.0,
      "ev_eur_at_1500": 30.0,
      "payoff_skew": 2.0,
      "pain_trade_flag": false,
      "consensus_position": "crowded_long|neutral|contrarian",
      "diversifier_role": "<was das zum Portfolio beitraegt>",
      "falsification": "<welches einzelne Event killt die These>",
      "sector": "Tech|Energy|...",
      "region": "US|EU|Asia",
      "priority_score": 0.85
    }}
  ],
  "portfolio_recommendations": {{
    "add": ["<ticker1>", ...],
    "reduce": ["<strategie_id>", ...],
    "hedge": "<globaler hedge-vorschlag>"
  }}
}}

Quality matters mehr als Quantity — wenn nur 2 wirklich gute Setups existieren,
generiere nur 2 statt 5 schwache.
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
    return call_llm(prompt, model_hint=hint, max_tokens=5000)


def parse_json(text: str) -> dict:
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError('Kein JSON im Claude-Output')
    return json.loads(m.group(0))


def promote_to_candidates(theses: list[dict]) -> int:
    """Fuegt Thesen zu candidate_tickers.json als discovery-candidates hinzu.
    Bypasst is_new_ticker() weil der Thesis-Generator auch bekannte Tickers
    mit neuen Setups vorschlagen darf."""
    try:
        from candidates import load_candidates, save_candidates
    except Exception:
        print('[thesis-gen] candidates-Modul nicht importierbar — skip')
        return 0

    try:
        from atomic_json import atomic_write_json
        _writer = atomic_write_json
    except Exception:
        _writer = None

    data = load_candidates()
    now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds')
    added = 0

    for t in theses:
        ticker = (t.get('ticker') or '').upper().strip()
        if not ticker or len(ticker) > 10:
            continue
        ev = float(t.get('ev_eur_at_1500', 0) or 0)
        skew = float(t.get('payoff_skew', 0) or 0)
        if ev < 10 or skew < 1.3:
            continue

        entry = data.get(ticker) or {
            'discovered_at': now_iso,
            'last_seen_at': now_iso,
            'sources': [],
            'priority': 0.0,
            'status': 'pending',
        }
        source = {
            'type': 'generated_thesis',
            'detail': (t.get('thesis_one_liner') or '')[:160],
            'score': round(min(1.0, 0.5 + ev / 200.0), 2),
            'ev_eur': ev,
            'payoff_skew': skew,
            'catalyst_date': t.get('catalyst_date'),
            'pain_trade_flag': t.get('pain_trade_flag', False),
            'ts': now_iso,
        }
        entry['sources'].append(source)
        entry['last_seen_at'] = now_iso
        entry['priority'] = min(2.0, 1.2 + ev / 200.0)
        if entry.get('status') in ('rejected', 'expired'):
            entry['status'] = 'pending'  # Re-Try bei neuer Thesis
        data[ticker] = entry
        added += 1

    # Atomic schreiben
    cand_file = WS / 'data' / 'candidate_tickers.json'
    try:
        if _writer:
            _writer(cand_file, data)
        else:
            cand_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f'[thesis-gen] candidates-write failed: {e}')
        return 0

    return added


def run(count: int = 5, dry: bool = False) -> dict:
    prompt = build_prompt(count)
    print(f'[thesis-gen] Generiere {count} Thesen via Claude...')
    if dry:
        print(prompt[:3000])
        return {'status': 'ok', 'dry': True}

    try:
        text, usage = call_claude(prompt)
    except Exception as e:
        print(f'[thesis-gen] Claude-Fehler: {e}')
        return {'status': 'error', 'error': str(e)}

    try:
        parsed = parse_json(text)
    except Exception as e:
        print(f'[thesis-gen] Parse-Fehler: {e}')
        return {'status': 'error', 'error': f'parse: {e}'}

    theses = parsed.get('theses', [])
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    # Archiv: JSONL
    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSONL.open('a', encoding='utf-8') as f:
        for t in theses:
            t['_generated_at'] = ts
            f.write(json.dumps(t, ensure_ascii=False) + '\n')

    # Promote zu candidate_tickers.json
    added = promote_to_candidates(theses)

    print(f"[thesis-gen] ✅ {len(theses)} Thesen generiert, {added} in candidate-pool")
    print(f"[thesis-gen] Kosten: ${usage.get('cost_usd_est', 0):.3f}")

    for t in theses[:3]:
        print(f"  ▸ {t.get('ticker')} — {t.get('thesis_one_liner','')[:100]}")
        print(f"     EV={t.get('ev_eur_at_1500','?')}€ Skew={t.get('payoff_skew','?')} "
              f"Cat={t.get('catalyst_date','?')} {t.get('direction','?').upper()}")

    return {
        'status': 'ok',
        'generated': len(theses),
        'candidates_added': added,
        'cost_usd': usage.get('cost_usd_est', 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=5)
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    r = run(count=args.count, dry=args.dry)
    sys.exit(0 if r.get('status') == 'ok' else 2)


if __name__ == '__main__':
    main()
