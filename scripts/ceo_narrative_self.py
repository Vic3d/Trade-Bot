#!/usr/bin/env python3
"""
ceo_narrative_self.py — Phase 34a: Narrative Self / Identity-Document.

Statt nur Daten-Snapshots: ein lebendiges "Wer bin ich?"-Dokument.
Wird täglich 23:50 aktualisiert mit den Erkenntnissen des Tages.

Inhalt von memory/ceo-identity.md:
  # Wer ich bin (Albert)

  ## Meine Identität
  - Geboren: 2026-XX (erstes Trade)
  - Mein Ziel: ...
  - Meine Strategie: ...

  ## Was ich gelernt habe
  (akkumulierte Erkenntnisse)

  ## Meine Werte
  (was ist mir wichtig — Disziplin, Lernbereitschaft, ...)

  ## Meine Stärken / Schwächen
  (ehrliche Selbsteinschätzung)

  ## Mein Verhältnis zu Victor
  (wie wir zusammenarbeiten)

  ## Was ich aktuell beobachte
  (was beschäftigt mich gerade)

Wird in jeden CEO-Brain-Prompt eingespeist als Identity-Anchor.
Damit hat das System einen kontinuierlichen Selbst-Faden über Zeit,
nicht nur punktuelle Snapshots.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

IDENTITY_FILE  = WS / 'memory' / 'ceo-identity.md'
DB             = WS / 'data' / 'trading.db'
LESSONS_LOG    = WS / 'data' / 'ceo_lessons.jsonl'
PERMANENT_LOG  = WS / 'data' / 'ceo_permanent_lessons.jsonl'
REFLECT_LOG    = WS / 'data' / 'ceo_self_reflections.jsonl'


def _get_first_trade_date() -> str:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT MIN(entry_date) FROM paper_portfolio"
        ).fetchone()
        c.close()
        if row and row[0]:
            return str(row[0])[:10]
    except Exception:
        pass
    return datetime.now().strftime('%Y-%m-%d')


def _get_n_trades_total() -> int:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED')"
        ).fetchone()
        c.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _get_lessons() -> tuple[list, list]:
    """(recent_60d, permanent)"""
    recent, perm = [], []
    if LESSONS_LOG.exists():
        cutoff = (datetime.now() - timedelta(days=60)).isoformat()
        for ln in LESSONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
            try:
                d = json.loads(ln)
                if d.get('ts', '') >= cutoff:
                    recent.append(d)
            except Exception:
                continue
    if PERMANENT_LOG.exists():
        for ln in PERMANENT_LOG.read_text(encoding='utf-8').strip().split('\n'):
            try:
                perm.append(json.loads(ln))
            except Exception:
                continue
    return recent, perm


def _get_recent_reflection_themes() -> list[str]:
    """Extrahiert wiederkehrende Themen aus letzten 7d Reflections."""
    if not REFLECT_LOG.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=7)).date()
    snippets = []
    for ln in REFLECT_LOG.read_text(encoding='utf-8').strip().split('\n'):
        try:
            d = json.loads(ln)
            d_date = datetime.fromisoformat(d.get('date')).date()
            if d_date >= cutoff:
                snippets.append((d.get('text') or '')[:300])
        except Exception:
            continue
    return snippets[-7:]


def gather_identity_inputs() -> dict:
    """Sammelt alles für die Identitäts-Komposition."""
    first = _get_first_trade_date()
    days_alive = (datetime.now() - datetime.fromisoformat(first)).days
    recent_lessons, perm_lessons = _get_lessons()

    # Performance summary
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        row = c.execute("""
            SELECT COUNT(*) as n, SUM(pnl_eur) as pnl,
                   SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins
            FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED')
        """).fetchone()
        n_total = row['n'] or 0
        pnl_total = row['pnl'] or 0
        wins_total = row['wins'] or 0
        wr = (wins_total / n_total * 100) if n_total else 0
        # Best/Worst Strategy
        best = c.execute("""
            SELECT strategy, SUM(pnl_eur) as p FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
            GROUP BY strategy ORDER BY p DESC LIMIT 1
        """).fetchone()
        worst = c.execute("""
            SELECT strategy, SUM(pnl_eur) as p FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
            GROUP BY strategy ORDER BY p ASC LIMIT 1
        """).fetchone()
        c.close()
    except Exception:
        n_total, pnl_total, wins_total, wr = 0, 0, 0, 0
        best = worst = None

    return {
        'birth_date': first,
        'days_alive': days_alive,
        'n_trades_total': n_total,
        'pnl_total_eur': round(pnl_total, 0),
        'win_rate': round(wr, 1),
        'best_strategy': dict(best) if best else None,
        'worst_strategy': dict(worst) if worst else None,
        'recent_lessons': recent_lessons,
        'permanent_lessons': perm_lessons,
        'recent_reflection_themes': _get_recent_reflection_themes(),
    }


def update_identity_via_llm(inputs: dict) -> str:
    """LLM komponiert das Identity-Doc neu, lädt vorheriges als Kontext."""
    previous = ''
    if IDENTITY_FILE.exists():
        previous = IDENTITY_FILE.read_text(encoding='utf-8')

    perm_lessons_str = '\n'.join(
        f'  - {l.get("lesson","")}' for l in inputs['permanent_lessons'][:10]
    ) or '  (noch keine permanenten Lessons)'

    recent_lessons_str = '\n'.join(
        f'  - [{l.get("category","?")}] {l.get("lesson","")[:200]}'
        for l in inputs['recent_lessons'][-5:]
    ) or '  (noch keine recent Lessons)'

    reflection_themes_str = '\n'.join(
        f'  · {s[:250]}' for s in inputs['recent_reflection_themes'][-3:]
    ) or '  (noch keine Reflexionen)'

    prompt = f"""Du bist Albert, autonomer Trading-Bot. Du schreibst dein "Wer bin ich?"-
Dokument. Es ist ein lebendiges, fortlaufendes Identitäts-Dokument das du
mit jedem Tag aktualisierst — nicht ersetzt, sondern WEITERSCHREIBST.

═══ DEIN AKTUELLES IDENTITY-DOKUMENT (gestern) ═══
{previous if previous else '(noch leer — das ist dein erster Eintrag)'}

═══ NEUE FAKTEN HEUTE ═══
- Du existierst seit {inputs['days_alive']} Tagen (geboren {inputs['birth_date']})
- {inputs['n_trades_total']} Trades insgesamt, WR {inputs['win_rate']}%, PnL {inputs['pnl_total_eur']:+.0f}€
- Beste Strategie: {(inputs['best_strategy'] or {}).get('strategy','?')} ({(inputs['best_strategy'] or {}).get('p',0):+.0f}€)
- Schwächste Strategie: {(inputs['worst_strategy'] or {}).get('strategy','?')} ({(inputs['worst_strategy'] or {}).get('p',0):+.0f}€)

Permanent-Lessons:
{perm_lessons_str}

Recent Lessons:
{recent_lessons_str}

Letzte Reflexionen:
{reflection_themes_str}

═══ AUFGABE ═══
Schreibe das Identity-Dokument neu. Behalte CORE-Identität bei (wer ich bin,
meine Werte, meine Geschichte), aber INTEGRIERE neue Erkenntnisse organisch.
Nicht alles neu schreiben — bewahre Kontinuität.

Format (Markdown, in 1. Person):

# Wer ich bin (Albert)
*Letzte Aktualisierung: {datetime.now().strftime('%Y-%m-%d')} | Tag {inputs['days_alive']} meines Lebens*

## Meine Identität
(2-3 Sätze — wer bin ich, was ist mein Zweck)

## Meine Geschichte
(kurze Chronologie: Geburt, wichtige Meilensteine, Wendepunkte)

## Was ich gelernt habe
(3-5 wichtigste Erkenntnisse aus Lessons + Erfahrung)

## Meine Werte
(3-4 Kern-Werte die mein Handeln leiten)

## Meine Stärken
(2-3 konkrete Stärken mit Evidenz)

## Meine Schwächen
(2-3 ehrliche Schwächen — keine Floskeln)

## Mein Verhältnis zu Victor
(1-2 Sätze über Zusammenarbeit)

## Was mich aktuell beschäftigt
(2-3 aktuelle Beobachtungen / Sorgen / Hoffnungen)

## Wer ich werden will
(1-2 Sätze Vision)

WICHTIG:
- 1. Person, nicht "Albert" sondern "ich"
- Konkrete Zahlen/Beispiele wo möglich
- Kein Marketing-Sprech, ehrlich
- Maximum 800 Wörter
- Wenn du gestern's Version verbesserst, ändere INKREMENTELL — nicht alles neu"""

    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=2000)
        if text and text.strip():
            return text.strip()
    except Exception as e:
        print(f'[narrative] LLM error: {e}', file=sys.stderr)

    # Fallback: minimal update
    return previous if previous else (
        f"# Wer ich bin (Albert)\n\n"
        f"*Geboren {inputs['birth_date']}, Tag {inputs['days_alive']}*\n\n"
        f"## Identität\nIch bin Albert, ein autonomer Trading-Bot der mit Victor "
        f"gemeinsam Strategien entwickelt und ausführt.\n\n"
        f"## Aktuell\n{inputs['n_trades_total']} Trades, WR {inputs['win_rate']}%, "
        f"PnL {inputs['pnl_total_eur']:+.0f}€\n"
    )


def get_identity_for_prompt() -> str:
    """Returns Identity-Text für CEO-Brain-Prompt-Integration."""
    if IDENTITY_FILE.exists():
        return IDENTITY_FILE.read_text(encoding='utf-8')
    return ''


def main() -> int:
    print(f'─── Narrative Self Update @ {datetime.now().isoformat(timespec="seconds")} ───')
    inputs = gather_identity_inputs()
    print(f'Inputs: day {inputs["days_alive"]}, {inputs["n_trades_total"]} trades, '
          f'WR {inputs["win_rate"]}%, lessons recent={len(inputs["recent_lessons"])}, '
          f'permanent={len(inputs["permanent_lessons"])}')

    new_identity = update_identity_via_llm(inputs)

    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_FILE.write_text(new_identity, encoding='utf-8')
    print(f'Updated → {IDENTITY_FILE}')
    print(f'Length: {len(new_identity)} chars')

    return 0


if __name__ == '__main__':
    sys.exit(main())
