#!/usr/bin/env python3
"""
research_intake.py — Phase 44j: Externe Research-Quellen → Learnings.

Wenn Victor ein Transkript / Artikel / Video-Notes uebergibt, soll das
System NICHT den Rohtext speichern, sondern strukturierte Learnings
extrahieren und dauerhaft ablegen:

  - Trade-Thesen (Ticker, Direction, Rationale, Timeframe, Catalyst)
  - Methodiken (z.B. Capex-Breakeven, FCF-Sensitivity, R:R-Regel)
  - Risk-Principles (Stop-Setting, Position-Sizing)
  - Style-Insights (Trend-Following vs Mean-Reversion etc.)

Persistente Speicher:
  memory/research-learnings.md       Narrative-Log (lesbar fuer Mensch + LLM)
  data/external_theses.jsonl         Structured Theses (Hunter-readable)
  data/research_methods.jsonl        Trading-Methodiken & Frameworks

Run:
  python3 scripts/research_intake.py --source "Tradermacher: Shell" \
                                     --text "..."
  python3 scripts/research_intake.py --file path/to/transcript.txt \
                                     --source "Tradermacher Webinar"
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

LEARNINGS_MD   = WS / 'memory' / 'research-learnings.md'
EXT_THESES     = WS / 'data' / 'external_theses.jsonl'
RES_METHODS    = WS / 'data' / 'research_methods.jsonl'


SYSTEM_PROMPT = """Du bist Albert, der TradeMind-CEO. Du erhaeltst ein Transkript,
einen Artikel oder Notizen aus einer externen Trading-Quelle (YouTube, Twitter,
Webinar, Podcast). Deine Aufgabe ist NICHT den Rohtext zu speichern, sondern
die Learnings strukturiert zu extrahieren.

Antworte ausschliesslich mit JSON in diesem Schema:

{
  "summary": "1-2 Saetze worum es geht",
  "theses": [
    {
      "ticker": "EQNR.OL",
      "direction": "long|short|neutral",
      "thesis": "Kurze These max 200 Zeichen",
      "timeframe": "intraday|swing|position|long",
      "catalyst": "Was muss passieren",
      "rationale": "Warum es funktioniert",
      "confidence": "low|med|high"
    }
  ],
  "methods": [
    {
      "name": "Capex-Breakeven-Framework",
      "category": "valuation|risk|sizing|timing|psychology",
      "description": "Wie es funktioniert in 1-2 Saetzen",
      "applicable_to": ["energy", "commodities"]
    }
  ],
  "principles": [
    "Klare Aussage wie 'Stop nie enger als 1.5x ATR' oder 'Cut losers fast'"
  ],
  "warnings": [
    "Was schief gehen kann, was zu vermeiden ist"
  ],
  "verdict": "Wertvoll | Bekannt | Skeptisch — kurze Begruendung"
}

Sei nuechtern. Wenn die Quelle Werbung/Sales-Pitch enthaelt, ignoriere die.
Wenn eine These nicht prueffaehig ist, lasse sie weg.
Wenn nichts Neues drinsteht, gib kurze theses=[] und sage es im verdict."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_learnings(text: str, source: str) -> dict:
    """Ruft LLM auf, parst JSON, faengt Errors ab."""
    prompt = (
        f"Quelle: {source}\n"
        f"Datum: {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"Transkript / Inhalt:\n---\n{text}\n---\n\n"
        f"Extrahiere die Learnings als JSON."
    )
    try:
        from core.llm_client import call_llm
        resp, meta = call_llm(prompt, model_hint='sonnet',
                              max_tokens=2000, system=SYSTEM_PROMPT)
        # Parse JSON aus response
        import re
        m = re.search(r'\{.*\}', resp, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        print(f'[research_intake] LLM-Fehler: {e}', file=sys.stderr)
    return {'summary': '(LLM-fail)', 'theses': [], 'methods': [],
            'principles': [], 'warnings': [], 'verdict': 'extraction_failed'}


def persist(learnings: dict, source: str) -> dict:
    """Schreibt Learnings nach research-learnings.md + external_theses.jsonl + research_methods.jsonl."""
    ts = _now()
    today = datetime.now().strftime('%Y-%m-%d')

    # ── 1) Markdown narrative ────────────────────────────────────────
    LEARNINGS_MD.parent.mkdir(parents=True, exist_ok=True)
    if not LEARNINGS_MD.exists():
        LEARNINGS_MD.write_text(
            "# Research Learnings\n\n"
            "Strukturierte Lerneintraege aus externen Quellen "
            "(Transkripte, Artikel, Videos). Generiert von "
            "`scripts/research_intake.py`.\n\n",
            encoding='utf-8'
        )
    md_block = [
        f'\n## {today} — {source}\n',
        f'**Summary:** {learnings.get("summary","")}\n',
        f'**Verdict:** {learnings.get("verdict","-")}\n',
    ]
    if learnings.get('theses'):
        md_block.append('\n### Thesen\n')
        for t in learnings['theses']:
            md_block.append(
                f'- **{t.get("ticker","?")}** ({t.get("direction","?")}, '
                f'{t.get("timeframe","?")}, conf={t.get("confidence","?")}) — '
                f'{t.get("thesis","")}\n'
                f'  - *Catalyst:* {t.get("catalyst","-")}\n'
                f'  - *Rationale:* {t.get("rationale","-")}\n'
            )
    if learnings.get('methods'):
        md_block.append('\n### Methoden / Frameworks\n')
        for m in learnings['methods']:
            md_block.append(
                f'- **{m.get("name","?")}** ({m.get("category","?")}) — '
                f'{m.get("description","")} '
                f'[anwendbar: {", ".join(m.get("applicable_to",[]))}]\n'
            )
    if learnings.get('principles'):
        md_block.append('\n### Prinzipien\n')
        for p in learnings['principles']:
            md_block.append(f'- {p}\n')
    if learnings.get('warnings'):
        md_block.append('\n### Warnungen\n')
        for w in learnings['warnings']:
            md_block.append(f'- ⚠️ {w}\n')
    with open(LEARNINGS_MD, 'a', encoding='utf-8') as f:
        f.write(''.join(md_block))

    # ── 2) JSONL: Thesen ─────────────────────────────────────────────
    EXT_THESES.parent.mkdir(parents=True, exist_ok=True)
    n_theses = 0
    with open(EXT_THESES, 'a', encoding='utf-8') as f:
        for t in learnings.get('theses', []):
            row = {'ts': ts, 'source': source, **t}
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
            n_theses += 1

    # ── 3) JSONL: Methoden ──────────────────────────────────────────
    n_methods = 0
    with open(RES_METHODS, 'a', encoding='utf-8') as f:
        for m in learnings.get('methods', []):
            row = {'ts': ts, 'source': source, **m}
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
            n_methods += 1

    return {'n_theses': n_theses, 'n_methods': n_methods,
            'n_principles': len(learnings.get('principles', [])),
            'verdict': learnings.get('verdict', '-')}


def process(text: str, source: str) -> dict:
    """Public Entry — von Discord oder CLI aufgerufen."""
    learnings = extract_learnings(text, source)
    persisted = persist(learnings, source)
    return {'ts': _now(), 'source': source,
            'learnings': learnings, 'persisted': persisted}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, help='Quellen-Bezeichnung')
    ap.add_argument('--text', help='Inhalt direkt')
    ap.add_argument('--file', help='Dateipfad (alternativ zu --text)')
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding='utf-8')
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    if not text.strip():
        print('No text provided.', file=sys.stderr)
        return 1

    result = process(text, args.source)
    print(json.dumps({
        'source': result['source'],
        'verdict': result['learnings'].get('verdict'),
        'persisted': result['persisted'],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
