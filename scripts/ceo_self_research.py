#!/usr/bin/env python3
"""
ceo_self_research.py — Phase 44s: Aktive Research-Fragen-Generation.

Albert war passiv: er bekommt News, reflektiert. Neu: er fragt SELBER.

Daily-Cycle (06:00 vor Hunt):
1. Self-Question-Generator (LLM)
   Schaut Open-Positions + Active-Strategies + Macro-Watch + Calendar.
   Generiert 5-7 konkrete Fragen die heute relevant sind.
   Beispiel: "Was sind die juengsten Brent-Forecasts?"
            "Bayer-Glyphosat: gibt es neue Settlement-Updates?"
            "Wo steht der Iran-Konflikt diese Woche?"

2. News-DB-Scan + Synthesis (LLM)
   Pro Frage: filtere matching news_events der letzten 48h.
   Wenn N>=3 Treffer: synthesisiere Antwort.
   Wenn N<3: markiere als 'BLIND_SPOT — manuell pruefen'

3. Impact-Bewertung (LLM)
   Pro Antwort: 'aendert das meine Positionen?' (HOLD/REVIEW/ACT)

Output:
  memory/ceo-daily-research/YYYY-MM-DD.md  Strukturierte Research-Notiz
  data/ceo_self_research_log.jsonl         Audit
  Discord-Push wenn HIGH-Impact-Findings

Run: python3 scripts/ceo_self_research.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
RESEARCH_DIR = WS / 'memory' / 'ceo-daily-research'
LOG = WS / 'data' / 'ceo_self_research_log.jsonl'


SYSTEM_QGEN = """Du bist Albert, der TradeMind-CEO. Generiere 5-7 KONKRETE
Research-Fragen, die heute fuer das Trading relevant sind. Basis:

  - Open Positions (welche Macro/Sektor-Faktoren beeinflussen sie?)
  - Active Strategies (welche Catalysts stehen an?)
  - Bekannte Catalyst-Termine (z.B. SCOTUS, Fed, Earnings)
  - Bekannte Watch-Themen (z.B. Iran-Hormuz, Trump-Tariffs)

Regeln:
  - Spezifisch, nicht generisch. KEIN 'wie laeuft Tech?' sondern 'gab es neue NVDA-Aussagen zu Datacenter-Capex letzte Woche?'
  - Jede Frage muss durch News/Daten beantwortbar sein
  - Mindestens 1 Frage zu OPEN POSITIONS (was koennte sie heute kippen?)
  - Mindestens 1 Frage zu CATALYSTS (was steht in 1-7 Tagen an?)
  - Mindestens 1 Frage zu BLINDEN FLECKEN (was wuerde meine These widerlegen?)

Antwort als JSON-Array:
[
  {"question": "...", "category": "position|catalyst|blindspot|macro|sector",
   "related_to": "TICKER oder THEMA", "priority": "high|med|low"}
]"""


SYSTEM_SYNTH = """Du bist Albert. Beantworte die Research-Frage anhand
der gelieferten News-Headlines. Sei nuechtern, keine Spekulation.

Wenn die News reichen → 2-3 Saetze Antwort + 'Impact: HOLD/REVIEW/ACT'
Wenn die News nicht reichen → 'BLIND_SPOT' + was zu pruefen waere

Antwort als JSON:
{"answer": "...", "impact": "HOLD|REVIEW|ACT|BLIND_SPOT",
 "evidence_count": N, "key_headline": "die wichtigste Headline"}"""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _gather_context() -> dict:
    """Open positions, active strategies, upcoming catalysts."""
    if not DB.exists(): return {}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    opens = c.execute(
        "SELECT ticker, strategy, entry_price, stop_price, pnl_eur "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    c.close()

    strats = []
    sf = WS / 'data' / 'strategies.json'
    if sf.exists():
        d = json.loads(sf.read_text(encoding='utf-8'))
        for sid, s in d.items():
            if isinstance(s, dict) and s.get('status') == 'active':
                strats.append({'id': sid, 'thesis': (s.get('thesis','') or '')[:120]})

    # Macro events 7d (best effort, fail soft)
    macro = []
    try:
        c2 = sqlite3.connect(str(DB))
        c2.row_factory = sqlite3.Row
        macro = [dict(r) for r in c2.execute(
            "SELECT event_type, severity, detected_at FROM macro_events "
            "WHERE substr(detected_at,1,10) >= date('now','-7 days') "
            "ORDER BY detected_at DESC LIMIT 10"
        ).fetchall()]
        c2.close()
    except Exception: pass

    return {
        'open_positions': [dict(r) for r in opens],
        'active_strategies': strats[:15],
        'recent_macro_events': macro,
        'today': datetime.now().strftime('%Y-%m-%d'),
    }


def _generate_questions(ctx: dict) -> list[dict]:
    prompt = (
        f"Heute: {ctx['today']}\n\n"
        f"Open Positions ({len(ctx['open_positions'])}):\n"
        + '\n'.join(f"  - {p['ticker']} ({p['strategy']}): "
                     f"entry {p['entry_price']:.2f}, stop {p['stop_price']:.2f}, "
                     f"PnL {p.get('pnl_eur', 0) or 0:.0f}EUR"
                     for p in ctx['open_positions'][:10])
        + f"\n\nActive Strategies (Top {min(15, len(ctx['active_strategies']))}):\n"
        + '\n'.join(f"  - {s['id']}: {s['thesis']}" for s in ctx['active_strategies'][:15])
        + f"\n\nMacro Events 7d ({len(ctx['recent_macro_events'])}):\n"
        + '\n'.join(f"  - {e['event_type']} (sev {e.get('severity','?')})"
                     for e in ctx['recent_macro_events'][:8])
        + "\n\nGeneriere die Research-Fragen als JSON-Array."
    )
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=900,
                            system=SYSTEM_QGEN)
        import re
        m = re.search(r'\[.*\]', text, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        print(f'[research] qgen err: {e}', file=sys.stderr)
    return []


def _find_news(question: dict, hours: int = 48) -> list[dict]:
    """Heuristik: extrahiere Schluesselwoerter aus question + related_to,
    suche in news_events letzter N Stunden."""
    if not DB.exists(): return []
    keywords = []
    related = (question.get('related_to') or '').lower()
    if related: keywords.append(related)
    # Aus Frage-Text: alle Woerter mit Grossbuchstaben (Tickers, Eigennamen)
    import re
    for w in re.findall(r'\b[A-Z][A-Z0-9.]{1,8}\b', question.get('question', '')):
        keywords.append(w.lower())
    # Aus Frage: ein paar wichtige Substantive
    for w in ['brent', 'oil', 'iran', 'fed', 'opec', 'glyphosat', 'roundup',
                'tariff', 'china', 'crypto', 'gold', 'copper', 'tanker',
                'earnings', 'fomc', 'cpi', 'nfp', 'scotus']:
        if w in question.get('question', '').lower():
            keywords.append(w)
    if not keywords: return []

    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        clauses = ' OR '.join(['lower(headline) LIKE ?'] * len(keywords))
        params = [f'%{k}%' for k in keywords]
        rows = c.execute(
            f"SELECT id, headline, source, created_at FROM news_events "
            f"WHERE created_at >= datetime('now', '-{hours} hours') "
            f"AND ({clauses}) ORDER BY created_at DESC LIMIT 12",
            params
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _synthesize(question: dict, news: list[dict]) -> dict:
    if not news:
        return {'answer': f'Keine News in 48h zu diesem Thema gefunden.',
                'impact': 'BLIND_SPOT', 'evidence_count': 0, 'key_headline': ''}
    prompt = (
        f"Frage: {question['question']}\n"
        f"Kontext: {question.get('related_to','')}\n\n"
        f"News-Headlines (letzte 48h, {len(news)} Stueck):\n"
        + '\n'.join(f"  - [{n['source']}] {n['headline']}" for n in news[:10])
        + "\n\nBeantworte als JSON."
    )
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=400,
                            system=SYSTEM_SYNTH)
        import re
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception: pass
    return {'answer': '(LLM-Fehler)', 'impact': 'BLIND_SPOT',
            'evidence_count': len(news), 'key_headline': news[0]['headline'] if news else ''}


def _persist(questions: list[dict], answers: list[dict]) -> Path:
    today = datetime.now().strftime('%Y-%m-%d')
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    md_file = RESEARCH_DIR / f'{today}.md'
    lines = [
        f'# CEO Daily Research — {today}',
        '',
        '*Albert hat sich heute morgen folgende Fragen gestellt und sie '
        'mit aktuellen News-Daten beantwortet. KEIN Victor-Input.*',
        '',
    ]
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        impact_icon = {'ACT': '🚨', 'REVIEW': '⚠️', 'HOLD': '✅',
                        'BLIND_SPOT': '❓'}.get(a.get('impact', '?'), '?')
        lines.append(f'## {i}. {q.get("question","?")}')
        lines.append(f'*Kategorie: {q.get("category","?")} | '
                      f'Bezug: {q.get("related_to","?")} | '
                      f'Prio: {q.get("priority","?")}*')
        lines.append('')
        lines.append(f'{impact_icon} **{a.get("impact","?")}**: {a.get("answer","")}')
        if a.get('key_headline'):
            lines.append(f'> {a["key_headline"]}')
        lines.append(f'*Evidence: {a.get("evidence_count",0)} News-Treffer*')
        lines.append('')
    md_file.write_text('\n'.join(lines), encoding='utf-8')

    # Audit-Log
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), 'date': today,
                              'n_questions': len(questions),
                              'qa': [{'q': q, 'a': a}
                                     for q, a in zip(questions, answers)]},
                             ensure_ascii=False) + '\n')
    return md_file


def run() -> dict:
    ctx = _gather_context()
    questions = _generate_questions(ctx)
    if not questions:
        return {'ts': _now(), 'error': 'no_questions_generated'}
    answers = []
    for q in questions:
        news = _find_news(q, hours=48)
        a = _synthesize(q, news)
        answers.append(a)

    md_file = _persist(questions, answers)

    # Discord-Push fuer ACT-Findings
    acts = [(q, a) for q, a in zip(questions, answers) if a.get('impact') == 'ACT']
    reviews = [(q, a) for q, a in zip(questions, answers) if a.get('impact') == 'REVIEW']
    if acts or reviews:
        try:
            from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM
            tier = TIER_HIGH if acts else TIER_MEDIUM
            msg_lines = ['🧭 **Albert Self-Research** — Findings:']
            for q, a in acts[:5]:
                msg_lines.append(f"\n🚨 **ACT** — {q['question'][:100]}")
                msg_lines.append(f"   → {a['answer'][:140]}")
            for q, a in reviews[:5]:
                msg_lines.append(f"\n⚠️ **REVIEW** — {q['question'][:100]}")
                msg_lines.append(f"   → {a['answer'][:140]}")
            msg_lines.append(f'\n_Volle Notiz: memory/ceo-daily-research/{datetime.now().strftime("%Y-%m-%d")}.md_')
            send_alert('\n'.join(msg_lines)[:1900], tier=tier,
                        category='self_research',
                        dedupe_key=f'self_research_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception as e: print(f'discord push err: {e}')

    return {
        'ts': _now(), 'n_questions': len(questions),
        'by_impact': {k: sum(1 for a in answers if a.get('impact') == k)
                       for k in ('ACT', 'REVIEW', 'HOLD', 'BLIND_SPOT')},
        'md_file': str(md_file),
    }


def main() -> int:
    r = run()
    print(f'═══ CEO Self-Research @ {r.get("ts","")[:16]} ═══')
    if 'error' in r:
        print(f'  Error: {r["error"]}')
        return 1
    print(f'  Questions: {r["n_questions"]}')
    print(f'  By Impact: {r["by_impact"]}')
    print(f'  File: {r["md_file"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
