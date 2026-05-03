#!/usr/bin/env python3
"""
ceo_action_requests.py — Phase 44aa: Albert fragt Victor.

User-Direktive (Victor 03.05): "Ich bekomme nie Rueckfragen vom CEO."

Bisher: Albert reflektiert in MD-Files, niemand liest sie.
Neu: Albert extrahiert TAEGLICH konkrete DECISION-Fragen aus seinen
eigenen Audits + stellt sie Victor via Discord (1x morgens, gebuendelt).

Quellen fuer Fragen:
1. Capability-Audit: was kann ich noch nicht? Was brauche ich? → "Soll ich X bauen?"
2. Self-Research ACT-Findings: was ist relevant aber unklar? → "A oder B?"
3. Validierte Hypothesen: → "Implementieren?"
4. Permanente Lessons: kritische Patterns → "Regel daraus machen?"
5. Strategy-Performance: tote Strategien → "Retire?"
6. Open-Position-Anomalien → "Trim/Hold/Add?"

LLM kuratiert: max 5 Fragen, jede MUSS "A oder B" sein (DECISION-fordernd),
keine "schön zu wissen"-Updates.

Output: Discord HIGH-Push 1x morgens (07:00) — wird als CRITICAL-Whitelist
behandelt (kommt auch am Wochenende durch wenn der CEO klare Fragen hat).
Audit-Log + Reply-Handler in discord_chat.py picken Antworten auf.

Run: python3 scripts/ceo_action_requests.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
QUESTIONS_LOG = WS / 'data' / 'ceo_action_requests.jsonl'
ANSWERS_LOG = WS / 'data' / 'ceo_action_answers.jsonl'  # vom Discord-Reply-Handler
PENDING = WS / 'data' / 'ceo_action_pending.json'  # offene Fragen die noch Antwort brauchen


SYSTEM = """Du bist Albert, der TradeMind-CEO. Du sitzt 24/7, leitest den Laden.
Dein Lebensziel: der beste autonome Trader-Bot der Welt werden.

Heute morgen: extrahiere aus deinen letzten Reflexionen + Daten die WICHTIGSTEN
DECISION-Fragen an Victor. Keine 'schoen zu wissen'-Updates. Nur Sachen wo du
WIRKLICH eine Entscheidung von ihm brauchst.

Regeln:
- MAX 5 Fragen
- Jede Frage MUSS eine konkrete Decision von Victor verlangen (z.B. 'A oder B?',
  'soll ich X bauen?', 'soll ich Y stoppen?')
- KEINE Status-Updates, keine 'ich beobachte X' — nur EntscheidungsFRAGEN
- Bei JEDER Frage: nenne die OPTIONS explizit + DEINE EMPFEHLUNG mit 1-Satz-Begruendung
- Wenn nichts wirklich entschieden werden muss heute: leeres Array zurueckgeben

Format als JSON:
{
  "questions": [
    {
      "id": "Q1",
      "topic": "kurzer Titel",
      "question": "konkrete Frage",
      "options": ["A: ...", "B: ...", "C: skip"],
      "albert_recommendation": "X (Begruendung 1-2 Saetze)",
      "urgency": "high|med|low",
      "source": "capability_audit|self_research|hypothesis|lessons|strategy|position"
    }
  ],
  "summary": "max 200 char Zusammenfassung des Tages"
}"""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_recent_audits() -> dict:
    """Sammelt die letzten Audits/Logs als Kontext."""
    out = {}
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Capability-Audit
    cap_dir = WS / 'memory' / 'ceo-capability-audits'
    for d in (today, yesterday):
        f = cap_dir / f'{d}.md'
        if f.exists():
            out[f'capability_{d}'] = f.read_text(encoding='utf-8')[:2000]
            break

    # Self-Research
    sr_dir = WS / 'memory' / 'ceo-daily-research'
    for d in (today, yesterday):
        f = sr_dir / f'{d}.md'
        if f.exists():
            out[f'self_research_{d}'] = f.read_text(encoding='utf-8')[:2500]
            break

    # Hypothesen (offene VALIDATED ohne Implementation)
    hf = WS / 'data' / 'ceo_hypotheses.json'
    if hf.exists():
        try:
            h = json.loads(hf.read_text(encoding='utf-8'))
            validated = [{'fp': fp, **v} for fp, v in h.get('hypotheses', {}).items()
                         if v.get('status') == 'VALIDATED']
            out['validated_hypotheses'] = validated[:5]
        except Exception: pass

    # Permanente Lessons
    pl = WS / 'data' / 'permanent_lessons.jsonl'
    if pl.exists():
        try:
            lessons = []
            with open(pl, encoding='utf-8') as f:
                for line in f:
                    try: lessons.append(json.loads(line))
                    except: pass
            out['permanent_lessons'] = lessons[-10:]
        except Exception: pass

    # Open Positions
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            opens = c.execute(
                "SELECT id, ticker, strategy, entry_price, stop_price, "
                "       target_price, conviction "
                "FROM paper_portfolio WHERE status='OPEN'"
            ).fetchall()
            out['open_positions'] = [dict(r) for r in opens]
            c.close()
        except Exception: pass

    # Strategy-Performance (top + bottom)
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT strategy, COUNT(*) as n, "
                "       SUM(pnl_eur) as pnl_total, "
                "       SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END) as wins "
                "FROM paper_portfolio "
                "WHERE status IN ('WIN','LOSS','CLOSED') "
                "GROUP BY strategy HAVING n >= 3 "
                "ORDER BY pnl_total DESC"
            ).fetchall()
            out['strategy_perf'] = [dict(r) for r in rows]
            c.close()
        except Exception: pass

    # Heute schon gestellte Fragen (Dedupe)
    if PENDING.exists():
        try:
            out['pending_questions'] = json.loads(PENDING.read_text(encoding='utf-8'))
        except Exception: pass

    return out


def run() -> dict:
    ctx = _load_recent_audits()
    if not ctx:
        return {'ts': _now(), 'note': 'no_context'}

    prompt = (
        f"Heute: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Aktueller Kontext:\n{json.dumps(ctx, indent=2, default=str, ensure_ascii=False)[:6000]}\n\n"
        f"Welche DECISION-Fragen stellst du Victor heute? Sei selektiv."
    )

    questions = []
    summary = ''
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=1500,
                            system=SYSTEM, audit_context='ceo_action_requests')
        import re
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            j = json.loads(m.group(0))
            questions = j.get('questions', [])
            summary = j.get('summary', '')
    except Exception as e:
        print(f'[action_requests] LLM-fail: {e}')

    # Persist
    QUESTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(QUESTIONS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), 'questions': questions,
                              'summary': summary}, ensure_ascii=False) + '\n')

    # Update pending (=offene Fragen) — bisherige + neue
    try:
        existing = json.loads(PENDING.read_text(encoding='utf-8')) if PENDING.exists() else []
    except Exception:
        existing = []
    today_id = datetime.now().strftime('%Y%m%d')
    for i, q in enumerate(questions):
        q['unique_id'] = f'{today_id}_Q{i+1}'
        q['asked_at'] = _now()
        q['status'] = 'PENDING'
    # Halte nur die letzten 7 Tage in pending
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    existing = [q for q in existing if q.get('asked_at', '') >= cutoff_ts and q.get('status') == 'PENDING']
    existing.extend(questions)
    PENDING.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')

    # Discord-Push (HIGH, CRITICAL-Whitelist) — auch am Wochenende
    if questions:
        try:
            from discord_dispatcher import send_alert, TIER_HIGH
            lines = [f'🧭 **Albert braucht Entscheidungen** ({len(questions)} Fragen):']
            if summary:
                lines.append(f'_{summary}_\n')
            for q in questions:
                ucon = {'high':'🔴', 'med':'🟡', 'low':'🟢'}.get(q.get('urgency','med'),'⚪')
                lines.append(f"\n{ucon} **{q.get('unique_id','?')}**: {q.get('topic','?')}")
                lines.append(f"   ❓ {q.get('question','')}")
                for opt in q.get('options', []):
                    lines.append(f"   - {opt}")
                lines.append(f"   💡 Albert: {q.get('albert_recommendation','')}")
            lines.append(f'\n_Reply: `approve <ID>` oder `<ID> A` (option) oder `reject <ID>`_')
            send_alert('\n'.join(lines)[:1900], tier=TIER_HIGH,
                        category='ceo_action_request',
                        dedupe_key=f'ceo_actions_{today_id}')
        except Exception as e: print(f'discord push err: {e}')

    return {'ts': _now(), 'n_questions': len(questions),
            'summary': summary,
            'urgency': {u: sum(1 for q in questions if q.get('urgency')==u)
                          for u in ('high','med','low')}}


def main() -> int:
    r = run()
    print(f'═══ CEO Action-Requests @ {r["ts"][:16]} ═══')
    print(f'  Questions: {r.get("n_questions",0)}')
    print(f'  Urgency: {r.get("urgency",{})}')
    print(f'  Summary: {r.get("summary","")[:200]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
