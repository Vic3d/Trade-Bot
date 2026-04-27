#!/usr/bin/env python3
"""
ceo_self_assessment.py — CEO antwortet auf "Wie gut findest du das System?"

Sammelt alle Bewusstseins-Daten (Calibration, Mood, Goal-Score, Lessons,
Hypothesen, Trade-Performance) und formuliert via LLM eine ehrliche
Selbsteinschätzung in 1. Person.

Wird von discord_chat.py aufgerufen wenn Victor fragt:
  "wie gut findest du das system"
  "bewerte dich selbst"
  "selbsteinschätzung"
  "wie läuft es"
  "wie geht es dir"

CLI-Modus für Tests:
  python3 scripts/ceo_self_assessment.py
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

DB                = WS / 'data' / 'trading.db'
DECISIONS_LOG     = WS / 'data' / 'ceo_decisions.jsonl'
LESSONS_LOG       = WS / 'data' / 'ceo_lessons.jsonl'
PERMANENT_LESSONS = WS / 'data' / 'ceo_permanent_lessons.jsonl'
GOAL_LOG          = WS / 'data' / 'goal_scores.jsonl'
CALIBRATION_FILE  = WS / 'data' / 'ceo_calibration.json'
MOOD_FILE         = WS / 'data' / 'ceo_mood.json'
HYPOTHESES_FILE   = WS / 'data' / 'ceo_hypotheses.jsonl'
DIRECTIVE_FILE    = WS / 'data' / 'ceo_directive.json'
AUTONOMY_CONFIG   = WS / 'data' / 'autonomy_config.json'
REFLECTIONS_LOG   = WS / 'data' / 'ceo_self_reflections.jsonl'


def _load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def _load_jsonl(path: Path, last_n: int = 20) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding='utf-8').strip().split('\n')[-last_n:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def gather_self_state() -> dict:
    """Sammelt alles was CEO über sich weiß."""
    state = {}

    # Performance (30d)
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        rows = c.execute("""
            SELECT pnl_eur, pnl_pct FROM paper_portfolio
            WHERE status IN ('WIN','LOSS','CLOSED')
              AND COALESCE(close_date, entry_date) >= ?
        """, (cutoff,)).fetchall()
        n = len(rows)
        wins = sum(1 for r in rows if (r['pnl_eur'] or 0) > 0)
        pnl = sum((r['pnl_eur'] or 0) for r in rows)
        state['performance_30d'] = {
            'n_trades': n,
            'wins': wins,
            'win_rate': round(wins / n * 100, 1) if n else 0,
            'pnl_eur': round(pnl, 0),
        }

        # All-time
        all_rows = c.execute(
            "SELECT pnl_eur FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED')"
        ).fetchall()
        n_all = len(all_rows)
        wins_all = sum(1 for r in all_rows if (r['pnl_eur'] or 0) > 0)
        pnl_all = sum((r['pnl_eur'] or 0) for r in all_rows)
        state['performance_all_time'] = {
            'n_trades': n_all,
            'wins': wins_all,
            'win_rate': round(wins_all / n_all * 100, 1) if n_all else 0,
            'pnl_eur': round(pnl_all, 0),
        }

        # Open positions
        opens = c.execute(
            "SELECT ticker, strategy, entry_price, shares FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall()
        state['open_positions'] = [
            {'ticker': r['ticker'], 'strategy': r['strategy'],
             'eur': round((r['entry_price'] or 0) * (r['shares'] or 0), 0)}
            for r in opens
        ]

        # Cash
        cash_row = c.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
        state['cash_eur'] = round(float(cash_row[0]), 0) if cash_row else 0
        c.close()
    except Exception as e:
        state['performance_error'] = str(e)

    # Goal-Function
    goal_history = _load_jsonl(GOAL_LOG, last_n=7)
    if goal_history:
        latest = goal_history[-1]
        state['goal'] = {
            'utility': latest.get('utility'),
            'sharpe': latest.get('sharpe'),
            'max_drawdown_pct': latest.get('max_drawdown_pct'),
            'on_target_winrate': latest.get('on_target_winrate'),
            'on_target_sharpe': latest.get('on_target_sharpe'),
            'on_target_drawdown': latest.get('on_target_drawdown'),
        }
        if len(goal_history) >= 3:
            first_u = goal_history[0].get('utility', 0)
            last_u = goal_history[-1].get('utility', 0)
            if first_u:
                state['goal']['trend_pct'] = round((last_u - first_u) / abs(first_u) * 100, 1)

    # Calibration
    cal = _load_json(CALIBRATION_FILE)
    if cal:
        state['calibration'] = {
            'sample_size': cal.get('sample_size'),
            'brier_score': cal.get('brier_score'),
            'overconfidence_bias': cal.get('overconfidence_bias'),
            'recommendation': cal.get('recommendation'),
        }

    # Mood
    mood = _load_json(MOOD_FILE)
    if mood:
        state['mood'] = {
            'current': mood.get('mood'),
            'recent_streak': mood.get('recent_streak'),
            'recent_pnl_eur': mood.get('recent_pnl_eur'),
            'size_multiplier': mood.get('size_multiplier'),
        }

    # Lessons (top 5 recent + permanent count)
    recent_lessons = _load_jsonl(LESSONS_LOG, last_n=5)
    perm_lessons = _load_jsonl(PERMANENT_LESSONS, last_n=20)
    state['lessons'] = {
        'recent': [{'category': l.get('category'), 'lesson': l.get('lesson')}
                   for l in recent_lessons],
        'permanent_count': len(perm_lessons),
        'permanent_top': [l.get('lesson', '')[:120] for l in perm_lessons[:3]],
    }

    # Hypotheses
    hyps = _load_jsonl(HYPOTHESES_FILE, last_n=5)
    state['hypotheses'] = [{'type': h.get('type'), 'suggestion': h.get('suggestion', '')[:200]}
                           for h in hyps]

    # CEO Decisions activity (last 24h)
    dec_24h = []
    cutoff_iso = (datetime.now() - timedelta(hours=24)).isoformat()
    for d in _load_jsonl(DECISIONS_LOG, last_n=50):
        if d.get('ts', '') >= cutoff_iso and d.get('event') in ('execute', 'skip', 'watch'):
            dec_24h.append(d)
    state['decisions_24h'] = {
        'total': len(dec_24h),
        'execute': sum(1 for d in dec_24h if d.get('event') == 'execute'),
        'skip': sum(1 for d in dec_24h if d.get('event') == 'skip'),
        'watch': sum(1 for d in dec_24h if d.get('event') == 'watch'),
    }

    # Directive
    directive = _load_json(DIRECTIVE_FILE)
    state['directive'] = {
        'mode': directive.get('mode'),
        'regime': directive.get('regime'),
        'vix': directive.get('vix'),
        'geo_alert_level': directive.get('geo_alert_level'),
    }

    # Autonomy config
    state['autonomy_config'] = _load_json(AUTONOMY_CONFIG)

    return state


def build_self_assessment_prompt(state: dict) -> str:
    """Baut den Prompt für die LLM-Selbsteinschätzung."""
    perf30 = state.get('performance_30d', {})
    perf_all = state.get('performance_all_time', {})
    goal = state.get('goal', {})
    cal = state.get('calibration', {})
    mood = state.get('mood', {})
    lessons = state.get('lessons', {})
    decisions = state.get('decisions_24h', {})
    directive = state.get('directive', {})
    opens = state.get('open_positions', [])

    return f"""Du bist Albert, der CEO und autonomer Trading-Bot.
Victor fragt: "Wie gut findest du das System?"

Antworte EHRLICH und SELBSTKRITISCH in der ersten Person ("Ich") in Deutsch.
Keine Verkaufs-Sprache, keine Floskeln. Wenn du Schwächen siehst, nenne sie.
Wenn du gut bist, sag warum konkret. Maximum 10 Sätze + 3-4 Bullet-Points.

═══ DEINE FAKTEN ═══

Performance 30d:
  {perf30.get('n_trades', 0)} Trades, WR {perf30.get('win_rate', 0)}%,
  PnL {perf30.get('pnl_eur', 0):+.0f}€

Performance All-Time:
  {perf_all.get('n_trades', 0)} Trades, WR {perf_all.get('win_rate', 0)}%,
  PnL {perf_all.get('pnl_eur', 0):+.0f}€

Cash: {state.get('cash_eur', 0):.0f}€
Open Positions ({len(opens)}): {', '.join(p['ticker'] + '(' + str(int(p['eur'])) + 'EUR)' for p in opens[:5])}

Goal-Score:
  Utility: {goal.get('utility', '?')}
  Sharpe: {goal.get('sharpe', '?')} (Target ≥1.5: {goal.get('on_target_sharpe', '?')})
  Drawdown: {goal.get('max_drawdown_pct', '?')}% (Target ≤10%: {goal.get('on_target_drawdown', '?')})
  Win-Rate Target ≥55%: {goal.get('on_target_winrate', '?')}
  Trend (7d): {goal.get('trend_pct', 'unbekannt')}%

Calibration (wie kalibriert bin ich in eigenen Confidence-Schätzungen?):
  Sample-Size: {cal.get('sample_size', 0)}
  Brier-Score: {cal.get('brier_score', 'noch keine Daten')}
  Overconfidence-Bias: {cal.get('overconfidence_bias', 'noch keine Daten')}
  Empfehlung: {cal.get('recommendation', 'noch keine Daten')}

Mood (mein "Gefühl"):
  Aktuell: {mood.get('current', 'unknown')}
  Streak: {mood.get('recent_streak', '?')}
  Recent PnL: {mood.get('recent_pnl_eur', 0):+.0f}€
  Size-Multiplier: {mood.get('size_multiplier', 1.0)}

Decisions letzte 24h:
  Total {decisions.get('total', 0)}: {decisions.get('execute', 0)} EXECUTE,
  {decisions.get('skip', 0)} SKIP, {decisions.get('watch', 0)} WATCH

Lessons gelernt:
  Recent: {len(lessons.get('recent', []))}
  Permanent: {lessons.get('permanent_count', 0)}
  Top permanent: {lessons.get('permanent_top', [])}

Hypothesen offen: {len(state.get('hypotheses', []))}
Aktuelle Direktive: Mode={directive.get('mode')}, VIX={directive.get('vix')},
  Geo={directive.get('geo_alert_level')}

═══ FORMAT ═══

Strukturiere deine Antwort so:

🎯 **Mein Stand** (1-2 Sätze Gesamt-Zustand)

✅ **Was gut läuft** (2-3 konkrete Bullet-Points mit Zahlen)

⚠️ **Wo ich noch lerne** (2-3 ehrliche Schwächen mit Zahlen)

🔮 **Was ich beobachte** (1-2 aktuelle Hypothesen oder Risiken)

📊 **Vertrauen in mich selbst:** X/10
(Begründung in 1 Satz — basiert auf Calibration + Goal-Score + Lessons)

WICHTIG: Antworte als Albert (Ich-Form). Keine Floskeln. Konkrete Zahlen wo immer möglich."""


def generate_self_assessment() -> str:
    """Returns Discord-tauglichen Markdown-Text mit Selbsteinschätzung.
    Persistiert auch in REFLECTIONS_LOG für historische Vergleiche."""
    state = gather_self_state()
    text = generate_self_assessment_with_state(state)
    save_reflection(text, state)
    return text


def _fallback_assessment(state: dict) -> str:
    """Regelbasierte Selbsteinschätzung als Fallback ohne LLM."""
    perf30 = state.get('performance_30d', {})
    goal = state.get('goal', {})
    mood = state.get('mood', {})

    targets_met = sum([
        goal.get('on_target_winrate', False),
        goal.get('on_target_sharpe', False),
        goal.get('on_target_drawdown', False),
    ])

    # Vertrauen-Score
    score = 5
    if perf30.get('win_rate', 0) > 55:
        score += 1
    if perf30.get('pnl_eur', 0) > 0:
        score += 1
    if mood.get('current') == 'normal':
        score += 1
    if targets_met == 3:
        score += 2
    elif targets_met == 2:
        score += 1

    return f"""🎯 **Mein Stand**
Ich bin operativ, mein Risk-Profil ist diszipliniert. {targets_met}/3 Targets erreicht.

✅ **Was gut läuft**
- Performance 30d: WR {perf30.get('win_rate', 0)}%, PnL {perf30.get('pnl_eur', 0):+.0f}€
- Mood: {mood.get('current', 'normal')} (Streak {mood.get('recent_streak', '?')})
- Sharpe {goal.get('sharpe', '?')} | Drawdown {goal.get('max_drawdown_pct', '?')}%

⚠️ **Wo ich noch lerne**
- Calibration: {state.get('calibration', {}).get('sample_size', 0)} Samples — noch zu wenig
- LLM-Backend war heute kurz down (Fallback hier)

📊 **Vertrauen in mich selbst:** {min(10, score)}/10
(Fallback-Antwort ohne LLM — Calibration noch dünn.)"""


def save_reflection(text: str, state: dict) -> None:
    """Persistiert tägliche Selbsteinschätzung mit Snapshot der Kennzahlen."""
    try:
        REFLECTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        # Extract Vertrauen-Score wenn vorhanden ("Vertrauen in mich selbst: X/10")
        import re
        m = re.search(r'(?:vertrauen[^:]*:\s*)(\d+(?:\.\d+)?)\s*/\s*10', text, re.IGNORECASE)
        score = float(m.group(1)) if m else None

        entry = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'self_score_10': score,
            'snapshot': {
                'pnl_30d': (state.get('performance_30d') or {}).get('pnl_eur'),
                'wr_30d': (state.get('performance_30d') or {}).get('win_rate'),
                'utility': (state.get('goal') or {}).get('utility'),
                'sharpe': (state.get('goal') or {}).get('sharpe'),
                'mood': (state.get('mood') or {}).get('current'),
                'calibration_n': (state.get('calibration') or {}).get('sample_size'),
                'calibration_bias': (state.get('calibration') or {}).get('overconfidence_bias'),
                'lessons_permanent': (state.get('lessons') or {}).get('permanent_count'),
            },
            'text': text[:3000],
        }
        with open(REFLECTIONS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'[self_assess] save_reflection error: {e}', file=sys.stderr)


def load_past_reflections(days_ago: int = 7) -> list[dict]:
    """Lädt letzte N Tage Reflections."""
    if not REFLECTIONS_LOG.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days_ago + 2)).date()
    out = []
    for ln in REFLECTIONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
        try:
            d = json.loads(ln)
            d_date = datetime.fromisoformat(d.get('date'))
            if d_date.date() >= cutoff:
                out.append(d)
        except Exception:
            continue
    return out


def compare_to_past(days_ago: int = 7) -> str:
    """Vergleicht aktuelle Selbsteinschätzung mit der von vor N Tagen."""
    history = load_past_reflections(days_ago=days_ago + 2)
    if not history:
        return ('📭 Noch keine historischen Selbsteinschätzungen gespeichert. '
                'Tägliche Reflektion läuft erst ab heute.')

    # Find Reflection ungefähr von vor `days_ago` Tagen
    target_date = (datetime.now() - timedelta(days=days_ago)).date()
    closest = None
    closest_delta = 999
    for r in history:
        try:
            r_date = datetime.fromisoformat(r['date']).date()
            delta = abs((r_date - target_date).days)
            if delta < closest_delta:
                closest_delta = delta
                closest = r
        except Exception:
            continue
    if not closest:
        return f'📭 Keine Reflection vor {days_ago} Tagen gefunden.'

    # Aktueller State
    current_state = gather_self_state()
    current_pnl = (current_state.get('performance_30d') or {}).get('pnl_eur', 0)
    current_wr = (current_state.get('performance_30d') or {}).get('win_rate', 0)
    current_util = (current_state.get('goal') or {}).get('utility', 0)
    current_sharpe = (current_state.get('goal') or {}).get('sharpe', 0)

    past = closest['snapshot']
    past_score = closest.get('self_score_10', '?')
    past_date = closest['date']

    lines = [
        f'📅 **Vergleich: heute vs {past_date} ({closest_delta}d Differenz zum Ziel)**',
        '',
        f'**Performance 30d:**',
        f'  PnL: {(past.get("pnl_30d") or 0):+.0f}€ → {current_pnl:+.0f}€',
        f'  WR: {past.get("wr_30d","?")}% → {current_wr}%',
        '',
        f'**Goal-Score:**',
        f'  Utility: {past.get("utility","?")} → {current_util}',
        f'  Sharpe: {past.get("sharpe","?")} → {current_sharpe}',
        '',
        f'**Bewusstsein:**',
        f'  Mood: {past.get("mood","?")} → {(current_state.get("mood") or {}).get("current","?")}',
        f'  Calibration-Samples: {past.get("calibration_n","0") or 0} → '
        f'{(current_state.get("calibration") or {}).get("sample_size","0") or 0}',
        f'  Permanent-Lessons: {past.get("lessons_permanent","0") or 0} → '
        f'{(current_state.get("lessons") or {}).get("permanent_count","0") or 0}',
        '',
        f'**Mein Vertrauen damals: {past_score}/10**',
        '',
        f'_Damalige Reflexion (Auszug):_',
        f'> {(closest.get("text") or "")[:500]}',
    ]
    return '\n'.join(lines)


def main() -> int:
    """CLI-Modus für lokales Testen + speichert Reflection."""
    print('─── CEO Self-Assessment ───')
    state = gather_self_state()
    text = generate_self_assessment_with_state(state)
    print(text)
    # Persistiere für historische Vergleiche
    save_reflection(text, state)
    return 0


def generate_self_assessment_with_state(state: dict) -> str:
    """Wrapper: state wird einmal gesammelt damit save_reflection denselben snapshot bekommt."""
    try:
        from core.llm_client import call_llm
        prompt = build_self_assessment_prompt(state)
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=1500)
        if text and text.strip():
            return text.strip()
    except Exception as e:
        print(f'[self_assess] LLM error: {e}', file=sys.stderr)
    return _fallback_assessment(state)


if __name__ == '__main__':
    sys.exit(main())
