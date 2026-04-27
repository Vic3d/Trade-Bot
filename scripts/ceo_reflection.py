#!/usr/bin/env python3
"""
ceo_reflection.py — Phase 32c: Post-Trade Reflection.

Läuft täglich 23:15 (nach allen Trade-Closes).

Logik:
  1. Holt heute geschlossene Trades (status WIN/LOSS/CLOSED, close_date today)
  2. Pro Trade: Lookup CEO-Decision (war es EXECUTE? mit welcher Confidence?)
  3. Match Decision-Erwartung vs reales Outcome:
     - Falls EXECUTE mit confidence > 0.7 aber LOSS → Lesson "Overconfident bias"
     - Falls SKIP/WATCH aber Ticker stieg deutlich → Lesson "Missed Alpha"
     - Falls EXECUTE mit confidence < 0.6 und Win → "Vorsichtige Calls performten"
  4. LLM extrahiert pro Mismatch eine Pattern-Lesson
  5. Schreibt in ceo_lessons.jsonl (max 100 Lessons total, älteste rausrotieren)

Diese Lessons werden vom CEO-Brain im nächsten Run als Kontext geladen
→ er lernt über Wochen aus eigenen Decisions.
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

DB             = WS / 'data' / 'trading.db'
DECISIONS_LOG  = WS / 'data' / 'ceo_decisions.jsonl'
LESSONS_LOG    = WS / 'data' / 'ceo_lessons.jsonl'

MAX_LESSONS = 100
LOOKBACK_DAYS = 1


def _load_decisions_for_window(days: int = LOOKBACK_DAYS) -> list[dict]:
    if not DECISIONS_LOG.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    out = []
    for ln in DECISIONS_LOG.read_text(encoding='utf-8').strip().split('\n'):
        try:
            d = json.loads(ln)
            if d.get('ts', '') >= cutoff:
                out.append(d)
        except Exception:
            continue
    return out


def _today_closed_trades() -> list[dict]:
    today = datetime.now().strftime('%Y-%m-%d')
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT id, ticker, strategy, pnl_eur, pnl_pct, exit_type,
               entry_date, close_date
        FROM paper_portfolio
        WHERE status IN ('WIN','LOSS','CLOSED')
          AND substr(close_date, 1, 10) = ?
    """, (today,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _trade_today_for_ticker_strategy(ticker: str, strategy: str) -> dict | None:
    """Wenn ein Ticker heute getradet wurde aber CEO sagte SKIP/WATCH → Missed-Alpha-Check."""
    today = datetime.now().strftime('%Y-%m-%d')
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    row = c.execute("""
        SELECT pnl_eur, pnl_pct FROM paper_portfolio
        WHERE ticker=? AND strategy=?
          AND substr(entry_date,1,10) = ?
        ORDER BY entry_date DESC LIMIT 1
    """, (ticker, strategy, today)).fetchone()
    c.close()
    return dict(row) if row else None


def _extract_lessons_via_llm(mismatches: list[dict]) -> list[str]:
    """LLM extrahiert generalisierte Patterns aus Mismatches."""
    if not mismatches:
        return []
    cases = '\n'.join(
        f"  - {m['type']}: {m['ticker']} ({m['strategy']}), "
        f"Decision={m['decision']} conf={m.get('confidence','?')} → "
        f"Outcome={m['outcome']}"
        for m in mismatches[:20]
    )
    prompt = f"""Du bist Albert. Folgende Trade-Decisions vs Outcomes von HEUTE haben ein
Mismatch erzeugt. Extrahiere 1-3 generalisierte Lessons (Patterns, keine Einzelfälle).

CASES:
{cases}

ANTWORT — STRIKT JSON:
{{"lessons": [
  {{"category": "overconfidence|missed_alpha|...", "lesson": "1-2 Sätze"}}
]}}"""
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='haiku', max_tokens=500)
        text = (text or '').strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text
            if text.endswith('```'):
                text = text.rsplit('```', 1)[0]
        i, j = text.find('{'), text.rfind('}')
        if i < 0 or j < 0:
            return []
        data = json.loads(text[i:j+1])
        return [l for l in data.get('lessons', []) if isinstance(l, dict)]
    except Exception as e:
        print(f'[reflection] LLM extract error: {e}', file=sys.stderr)
        return []


def _rotate_lessons() -> None:
    """Behält nur letzte MAX_LESSONS (älteste rausrotieren)."""
    if not LESSONS_LOG.exists():
        return
    lines = LESSONS_LOG.read_text(encoding='utf-8').strip().split('\n')
    if len(lines) > MAX_LESSONS:
        keep = lines[-MAX_LESSONS:]
        LESSONS_LOG.write_text('\n'.join(keep) + '\n', encoding='utf-8')


def main() -> int:
    print(f'─── CEO-Reflection @ {datetime.now().isoformat(timespec="seconds")} ───')
    decisions = _load_decisions_for_window(days=LOOKBACK_DAYS)
    closed = _today_closed_trades()
    print(f'Decisions today: {len(decisions)}, Closed today: {len(closed)}')

    if not decisions and not closed:
        print('Nichts zu reflektieren.')
        return 0

    # Map decisions by (ticker, strategy)
    dec_map = {}
    for d in decisions:
        key = (d.get('ticker', ''), d.get('strategy', ''))
        if key not in dec_map or d.get('ts', '') > dec_map[key].get('ts', ''):
            dec_map[key] = d

    mismatches = []

    # Type 1: EXECUTE → reales Outcome → Mismatch wenn Outcome != Erwartung
    for tr in closed:
        key = (tr['ticker'], tr['strategy'])
        d = dec_map.get(key)
        if not d:
            continue
        action = d.get('action', '?')
        conf = float(d.get('confidence', 0.5))
        pnl = tr.get('pnl_eur') or 0
        if action == 'EXECUTE' and pnl < 0 and conf > 0.7:
            mismatches.append({
                'type': 'overconfident_loss',
                'ticker': tr['ticker'], 'strategy': tr['strategy'],
                'decision': action, 'confidence': conf,
                'outcome': f'{pnl:+.0f}€ ({tr.get("pnl_pct",0):+.1f}%) {tr.get("exit_type","")}',
            })
        elif action == 'EXECUTE' and pnl > 0 and conf < 0.6:
            mismatches.append({
                'type': 'underconfident_win',
                'ticker': tr['ticker'], 'strategy': tr['strategy'],
                'decision': action, 'confidence': conf,
                'outcome': f'{pnl:+.0f}€ ({tr.get("pnl_pct",0):+.1f}%)',
            })

    # Type 2: SKIP / WATCH aber Ticker hat OPEN-Trade jetzt mit pos PnL → missed
    for d in decisions:
        if d.get('action') not in ('SKIP', 'WATCH'):
            continue
        actual = _trade_today_for_ticker_strategy(d.get('ticker', ''), d.get('strategy', ''))
        if actual and (actual.get('pnl_eur') or 0) > 50:
            mismatches.append({
                'type': 'missed_alpha',
                'ticker': d.get('ticker'), 'strategy': d.get('strategy'),
                'decision': d.get('action'), 'confidence': d.get('confidence'),
                'outcome': f'wäre +{actual["pnl_eur"]:.0f}€ gewesen',
            })

    if not mismatches:
        print('Keine signifikanten Mismatches → keine neuen Lessons.')
        return 0

    print(f'Mismatches: {len(mismatches)}')
    for m in mismatches[:5]:
        print(f'  · {m["type"]}: {m["ticker"]} {m["decision"]} → {m["outcome"]}')

    lessons = _extract_lessons_via_llm(mismatches)
    print(f'LLM-extracted lessons: {len(lessons)}')

    try:
        from ceo_intelligence import append_lesson
        for l in lessons:
            append_lesson(
                lesson=l.get('lesson', ''),
                category=l.get('category', 'general'),
                meta={'mismatch_count': len(mismatches),
                       'date': datetime.now().strftime('%Y-%m-%d')},
            )
            print(f'  + {l.get("category","?")}: {l.get("lesson","")[:100]}')
    except Exception as e:
        print(f'append_lesson error: {e}', file=sys.stderr)

    _rotate_lessons()

    # Discord-Push wenn Lessons neu
    if lessons:
        try:
            from discord_dispatcher import send_alert, TIER_LOW
            msg = (
                f'🧠 **CEO-Reflection** — {len(lessons)} neue Lesson{"s" if len(lessons)!=1 else ""} '
                f'aus {len(mismatches)} Mismatches heute:\n\n'
                + '\n'.join(f"  · `{l.get('category','?')}` {l.get('lesson','')}" for l in lessons)
            )
            send_alert(msg, tier=TIER_LOW, category='ceo_reflection',
                       dedupe_key=f'reflect_{datetime.now().strftime("%Y-%m-%d")}')
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
