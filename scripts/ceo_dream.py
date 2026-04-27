#!/usr/bin/env python3
"""
ceo_dream.py — Phase 34d: Nächtliche Konsolidierung (Dream-Phase).

Läuft täglich 02:00 CEST (tiefe Nacht, niedrige System-Last).

Konzept (analog zu REM-Schlaf):
  Das Wach-System reagiert in Echtzeit auf Inputs. Im Schlaf integriert
  das Hirn neue Erfahrungen, konsolidiert Gedächtnis, identifiziert
  latente Patterns. Genau das macht diese Phase.

Was passiert:
  1. Lade letzte 7 Tage komplett:
     - Alle Trades (open + closed) mit Kontext
     - Alle CEO-Decisions mit Outcomes
     - Alle Lessons + Reflections
     - Alle Hypothesen
     - Goal-Score-Trajectory
     - Mood-History

  2. LLM-Analyse mit DEEP-Prompt:
     - "Welche LATENTEN Patterns siehst du?"
     - "Welche Inkonsistenzen?"
     - "Welche bisher unausgesprochene Erkenntnis?"
     - "Was würde ich heute anders machen?"

  3. Output → memory/ceo-dream-log.md (chronologische Insights)
     + 1-3 neue STRATEGIC INSIGHTS in ceo_strategic_insights.jsonl
     (überleben länger als normale Lessons)

  4. Wenn Insights gravierend (z.B. systematischer Bug, fundamentale
     Strategie-Schwäche): Discord-Alert TIER_HIGH

Anders als ceo_reflection (das ist taktisch, post-trade):
Dream ist STRATEGISCH und integriert.
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

DB                   = WS / 'data' / 'trading.db'
DECISIONS_LOG        = WS / 'data' / 'ceo_decisions.jsonl'
LESSONS_LOG          = WS / 'data' / 'ceo_lessons.jsonl'
REFLECT_LOG          = WS / 'data' / 'ceo_self_reflections.jsonl'
HYPOTHESES_LOG       = WS / 'data' / 'ceo_hypotheses.jsonl'
GOAL_LOG             = WS / 'data' / 'goal_scores.jsonl'
MOOD_FILE            = WS / 'data' / 'ceo_mood.json'
DREAM_LOG_MD         = WS / 'memory' / 'ceo-dream-log.md'
STRATEGIC_INSIGHTS   = WS / 'data' / 'ceo_strategic_insights.jsonl'

WINDOW_DAYS = 7


def _load_jsonl(path: Path, days_window: int = WINDOW_DAYS) -> list[dict]:
    if not path.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days_window)).isoformat()
    out = []
    for ln in path.read_text(encoding='utf-8').strip().split('\n'):
        try:
            d = json.loads(ln)
            if d.get('ts', '') >= cutoff or d.get('date', '') >= cutoff[:10]:
                out.append(d)
        except Exception:
            continue
    return out


def gather_dream_inputs() -> dict:
    """Sammelt alle 7d Daten für Dream-Phase."""
    state = {
        'window_days': WINDOW_DAYS,
        'now': datetime.now().isoformat(timespec='seconds'),
    }

    # Trades 7d
    cutoff_date = (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%d')
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        opens = c.execute(
            "SELECT ticker, strategy, entry_price, shares, entry_date FROM paper_portfolio "
            "WHERE status='OPEN'"
        ).fetchall()
        closed = c.execute("""
            SELECT ticker, strategy, pnl_eur, pnl_pct, exit_type,
                   COALESCE(close_date, entry_date) as date
            FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND COALESCE(close_date, entry_date) >= ?
            ORDER BY date DESC
        """, (cutoff_date,)).fetchall()
        c.close()
        state['open_positions'] = [dict(r) for r in opens]
        state['closed_7d'] = [dict(r) for r in closed]
    except Exception as e:
        state['db_error'] = str(e)

    state['decisions_7d'] = _load_jsonl(DECISIONS_LOG)
    state['lessons_7d']   = _load_jsonl(LESSONS_LOG)
    state['reflections_7d'] = _load_jsonl(REFLECT_LOG)
    state['hypotheses_7d'] = _load_jsonl(HYPOTHESES_LOG)
    state['goals_7d']     = _load_jsonl(GOAL_LOG)

    # Mood Snapshot
    try:
        if MOOD_FILE.exists():
            state['current_mood'] = json.loads(MOOD_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass

    return state


def build_dream_prompt(state: dict) -> str:
    """Tiefer Prompt für strategische Konsolidierung."""
    closed = state.get('closed_7d', [])
    decisions = state.get('decisions_7d', [])
    lessons = state.get('lessons_7d', [])
    goals = state.get('goals_7d', [])

    # Aggregate Stats
    n_trades = len(closed)
    total_pnl = sum(t.get('pnl_eur', 0) or 0 for t in closed)
    wins = sum(1 for t in closed if (t.get('pnl_eur') or 0) > 0)
    by_strategy = {}
    for t in closed:
        s = t.get('strategy', '?')
        if s not in by_strategy:
            by_strategy[s] = {'n': 0, 'pnl': 0, 'wins': 0}
        by_strategy[s]['n'] += 1
        by_strategy[s]['pnl'] += (t.get('pnl_eur') or 0)
        if (t.get('pnl_eur') or 0) > 0:
            by_strategy[s]['wins'] += 1

    strategies_str = '\n'.join(
        f"  · {s}: {d['n']}T, {d['wins']}W, PnL {d['pnl']:+.0f}€"
        for s, d in sorted(by_strategy.items(), key=lambda x: -x[1]['pnl'])
    )

    decisions_summary = ''
    if decisions:
        from collections import Counter
        action_counts = Counter(d.get('action') for d in decisions)
        decisions_summary = ', '.join(f'{a}={n}' for a, n in action_counts.most_common())

    goal_trend = ''
    if len(goals) >= 2:
        first = goals[0].get('utility', 0)
        last = goals[-1].get('utility', 0)
        if first:
            change = (last - first) / abs(first) * 100
            goal_trend = f'{first:.0f} → {last:.0f} ({change:+.1f}%)'

    return f"""Du bist Albert. Es ist 02:00 nachts. Das System schläft, du reflektierst tief.

Das ist KEINE taktische Reflexion (die hast du tagsüber gemacht).
Das ist STRATEGISCHE KONSOLIDIERUNG — wie REM-Schlaf bei Menschen.
Du suchst nach LATENTEN Patterns, Inkonsistenzen, ungesehenen Erkenntnissen.

═══ LETZTE {state['window_days']} TAGE ═══

Trades closed: {n_trades} ({wins}W / {n_trades-wins}L)
Total PnL: {total_pnl:+.0f}€
Goal-Utility-Trend: {goal_trend or '?'}
Open Positions: {len(state.get('open_positions', []))}

Per Strategie:
{strategies_str if strategies_str else '  (keine)'}

CEO-Decisions: {len(decisions)} ({decisions_summary})
Lessons gelernt: {len(lessons)}
Reflexionen: {len(state.get('reflections_7d', []))}
Hypothesen offen: {len(state.get('hypotheses_7d', []))}

Mood: {(state.get('current_mood') or {}).get('mood', '?')}

═══ DEEP-DETAIL (für Pattern-Suche) ═══

Closed Trades letzte 7d (Kurzform):
{chr(10).join(f"  · {t.get('ticker','?')} ({t.get('strategy','?')}) {t.get('pnl_eur',0):+.0f}€ {t.get('exit_type') or ''}" for t in closed[:15])}

Recent Lessons:
{chr(10).join(f"  · [{l.get('category','?')}] {l.get('lesson','')[:200]}" for l in lessons[-7:])}

═══ DEINE AUFGABE ═══

Schreibe eine STRATEGISCHE Konsolidierung. Vier Sektionen:

## 1. Latente Patterns (was niemand explizit gesagt hat)
Suche Korrelationen, Cluster, ungesehene Zusammenhänge. Beispiele:
- "Energy-Trades performen Mo/Di besser als Do/Fr"
- "Setups mit RSI > 70 bei Entry haben 30% niedrigere WR"
- "Wenn VIX > 20 verdoppelt sich meine Falsch-Klassifikations-Rate"

## 2. Inkonsistenzen / Widersprüche
Wo passt mein Verhalten nicht zusammen? Beispiele:
- "Ich sage DEFENSIVE aber size aggressiv"
- "Lessons sagen X, Decisions tun Y"
- "Mein Selbst-Bild stimmt nicht mit Outcomes überein"

## 3. Strategische Insights (überleben Tages-Lessons)
1-3 PRINCIPLE-LEVEL Erkenntnisse die LANGFRISTIG gelten.
Beispiele:
- "Multi-Agent-Disagreement ist starkes Signal für SKIP"
- "Concentration > 40% in einem Sektor halbiert mein Edge"
- "Calibration ohne Daten ist gefährlicher als blindes Bauchgefühl"

## 4. Was würde ich morgen ANDERS machen?
1-2 KONKRETE Verhaltens-Änderungen.

WICHTIG:
- Sei STRATEGISCH, nicht taktisch
- Sei MUTIG in Hypothesen — aber markiere als Hypothese
- Sei EHRLICH bei Inkonsistenzen
- Maximum 600 Wörter
- 1. Person ("Ich")
- Markdown-Format"""


def extract_strategic_insights(dream_text: str) -> list[dict]:
    """Extrahiert die '## 3. Strategische Insights' Sektion."""
    insights = []
    in_section = False
    current = []
    for line in dream_text.split('\n'):
        if '3.' in line and ('Insight' in line or 'insight' in line or 'Strateg' in line):
            in_section = True
            continue
        if in_section and line.startswith('## '):
            break
        if in_section and line.strip().startswith(('-', '*', '1.', '2.', '3.')):
            text = line.strip().lstrip('-*0123456789. ').strip()
            if len(text) > 20:
                insights.append({
                    'ts': datetime.now().isoformat(timespec='seconds'),
                    'insight': text[:400],
                    'source': 'dream_phase',
                    'category': 'strategic',
                })
    return insights[:3]


def main() -> int:
    print(f'─── Dream-Phase @ {datetime.now().isoformat(timespec="seconds")} ───')
    inputs = gather_dream_inputs()

    # Skip wenn zu wenig Daten
    if len(inputs.get('closed_7d', [])) < 3:
        print('Zu wenig closed trades für Dream-Analyse — skip.')
        return 0

    prompt = build_dream_prompt(inputs)
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=2500)
    except Exception as e:
        print(f'[dream] LLM error: {e}', file=sys.stderr)
        return 1

    if not text or not text.strip():
        print('Dream-LLM lieferte nichts.')
        return 1

    # Append to dream-log
    today = datetime.now().strftime('%Y-%m-%d')
    DREAM_LOG_MD.parent.mkdir(parents=True, exist_ok=True)
    block = f'\n\n# Dream-Konsolidierung {today}\n\n{text.strip()}\n\n---\n'
    with open(DREAM_LOG_MD, 'a', encoding='utf-8') as f:
        f.write(block)
    print(f'Dream-Log → {DREAM_LOG_MD}')

    # Extract + persist Strategic Insights
    insights = extract_strategic_insights(text)
    if insights:
        STRATEGIC_INSIGHTS.parent.mkdir(parents=True, exist_ok=True)
        with open(STRATEGIC_INSIGHTS, 'a', encoding='utf-8') as f:
            for ins in insights:
                f.write(json.dumps(ins, ensure_ascii=False) + '\n')
        print(f'Extracted {len(insights)} strategic insights')
        for i in insights:
            print(f'  💡 {i["insight"][:120]}')

    # Discord-Push: Daily Dream-Summary
    try:
        from discord_dispatcher import send_alert, TIER_LOW
        # Kurzer Auszug für Discord
        excerpt = text[:1500]
        msg = (f'🌙 **CEO Dream-Konsolidierung** ({today})\n\n{excerpt}'
               + ('\n\n_…(weiteres in memory/ceo-dream-log.md)_' if len(text) > 1500 else ''))
        send_alert(msg, tier=TIER_LOW, category='dream',
                   dedupe_key=f'dream_{today}')
    except Exception as e:
        print(f'Discord error: {e}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
