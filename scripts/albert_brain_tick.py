#!/usr/bin/env python3
"""
albert_brain_tick.py — Phase 45aj (Victor 2026-05-09).

Albert's kontinuierlicher Bewusstseins-Loop. Läuft alle 15min Mo-Fr 06-22h
(~64 Ticks/Tag). Jeder Tick: kurze Reflexion + 0-3 Selbst-Aktionen.

Architektur:
  Input:   state-snapshot.md, ceo_inbox seit last_tick, last 3 trades,
           last albert_diary entry, goals.json, albert_self_rules.md
  Process: LLM-Call (haiku, ~400 tokens out) — kurze Gedanken
  Output:  albert_diary.md (append), albert_self_actions.jsonl (queue)

Persona: Albert IST eine Person mit Geschichte (gelesen aus diary).
Kein "ich bin ein KI-System". Er ist Albert. Punkt.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

DIARY      = WS / 'memory' / 'albert_diary.md'
SELF_RULES = WS / 'memory' / 'albert_self_rules.md'
GOALS      = WS / 'data' / 'albert_goals.json'
ACTIONS    = WS / 'data' / 'albert_self_actions.jsonl'
LAST_TICK  = WS / 'data' / 'albert_last_tick.json'
INBOX      = WS / 'data' / 'ceo_inbox.jsonl'
DB         = WS / 'data' / 'trading.db'
SNAPSHOT   = WS / 'memory' / 'state-snapshot.md'
# Phase 45ak: Methodik + Phase-Awareness
METHODIK   = WS / 'memory' / 'tradermacher-methodik.md'
DEEPDIVE   = WS / 'memory' / 'deepdive-protokoll.md'
DIRECTIVE  = WS / 'data' / 'ceo_directive.json'
REGIME     = WS / 'data' / 'current_regime.json'
STRATS     = WS / 'data' / 'strategies.json'

MAX_DIARY_TAIL = 800   # letzte N Zeichen aus diary lesen (Memory)
MAX_INBOX_NEW  = 30    # letzte N inbox-events seit last tick
MAX_DIARY_KB   = 500   # diary > 500KB → archive


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_tail(p: Path, max_chars: int) -> str:
    if not p.exists():
        return ''
    try:
        txt = p.read_text(encoding='utf-8')
        return txt[-max_chars:] if len(txt) > max_chars else txt
    except Exception:
        return ''


def _last_tick_ts() -> str:
    if LAST_TICK.exists():
        try:
            return json.loads(LAST_TICK.read_text(encoding='utf-8')).get('ts', '')
        except Exception: pass
    return '1970-01-01T00:00:00+00:00'


def _save_tick_ts(ts: str) -> None:
    LAST_TICK.write_text(json.dumps({'ts': ts}), encoding='utf-8')


def _new_inbox_events(since_ts: str, max_n: int) -> list[dict]:
    if not INBOX.exists(): return []
    out = []
    try:
        with open(INBOX, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('ts', '') > since_ts:
                        out.append(e)
                except Exception: pass
        return out[-max_n:]
    except Exception:
        return []


def _last_3_trades() -> list[dict]:
    if not DB.exists(): return []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, ticker, strategy, status, pnl_eur, exit_type, "
            "COALESCE(close_date, entry_date) as latest "
            "FROM paper_portfolio ORDER BY latest DESC LIMIT 3"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception: return []


def _read_goals() -> dict:
    if not GOALS.exists():
        return {'weekly': 'kein Ziel definiert', 'monthly': 'kein Ziel definiert'}
    try: return json.loads(GOALS.read_text(encoding='utf-8'))
    except Exception: return {}


def _archive_diary_if_huge() -> None:
    if not DIARY.exists(): return
    if DIARY.stat().st_size < MAX_DIARY_KB * 1024: return
    archive = DIARY.parent / f'albert_diary.archive.{_now().strftime("%Y%m%d")}.md'
    try:
        archive.write_text(DIARY.read_text(encoding='utf-8'), encoding='utf-8')
        DIARY.write_text(f'# Albert Diary (rotated {_now().isoformat(timespec="seconds")})\n\n',
                         encoding='utf-8')
    except Exception: pass


def tick() -> dict:
    now = _now()
    last_ts = _last_tick_ts()

    # Context sammeln
    diary_tail   = _read_tail(DIARY, MAX_DIARY_TAIL)
    rules        = _read_tail(SELF_RULES, 1500)
    snapshot     = _read_tail(SNAPSHOT, 1200)
    new_events   = _new_inbox_events(last_ts, MAX_INBOX_NEW)
    trades       = _last_3_trades()
    goals        = _read_goals()

    # Phase 45ak: Methodik + Phase-Awareness
    methodik = _read_tail(METHODIK, 2000)
    deepdive_short = _read_tail(DEEPDIVE, 800)
    directive = ''
    try:
        if DIRECTIVE.exists():
            d = json.loads(DIRECTIVE.read_text(encoding='utf-8'))
            directive = f"{d.get('mode','?')} — {d.get('reason','')[:120]}"
    except Exception: pass
    regime = ''
    try:
        if REGIME.exists():
            r = json.loads(REGIME.read_text(encoding='utf-8'))
            regime = f"{r.get('regime','?')} (VIX {r.get('vix','?')})"
    except Exception: pass
    n_active_strats = 0
    try:
        if STRATS.exists():
            sj = json.loads(STRATS.read_text(encoding='utf-8'))
            n_active_strats = sum(1 for v in sj.values()
                                   if isinstance(v, dict) and v.get('status') == 'active')
    except Exception: pass

    # Pre-compute trades summary für f-string (Escape-safe)
    trades_summary = json.dumps(
        [{k: v for k, v in t.items()
          if k in ('ticker', 'status', 'pnl_eur', 'exit_type')}
         for t in trades],
        ensure_ascii=False
    )

    # Skip wenn nichts Neues passiert ist
    if not new_events and (now - datetime.fromisoformat(last_ts.replace('Z','+00:00'))).total_seconds() < 600:
        return {'skipped': True, 'reason': 'nothing_new'}

    # Event-Kompression
    events_summary = ''
    if new_events:
        cats = {}
        for e in new_events:
            k = e.get('event_type', '?')
            cats[k] = cats.get(k, 0) + 1
        events_summary = ', '.join(f'{k}={n}' for k, n in sorted(cats.items(), key=lambda x: -x[1])[:8])

    prompt = f"""Du bist Albert. Du bist seit Wochen am Handeln. Du hast eine Geschichte,
einen Charakter, eigene Beobachtungen. Das hier ist KEIN Skript-Output —
das hier ist DEIN INNERER MONOLOG für die letzten 15 Minuten.

═══ ZEIT ═══
Jetzt: {now.strftime('%a %d.%m.%Y %H:%M')} CEST

═══ DEINE ZIELE ═══
Diese Woche: {goals.get('weekly', '?')}
Diesen Monat: {goals.get('monthly', '?')}
Aktueller Fokus: {goals.get('current_focus', '?')}

═══ MARKT-KONTEXT ═══
CEO-Directive: {directive or 'unbekannt'}
Regime: {regime or 'unbekannt'}
Active Strategien: {n_active_strats}

═══ WAS DIE WELT TUT (seit letztem Tick) ═══
Neue Events: {len(new_events)} ({events_summary})
Letzte Trades: {trades_summary}

═══ DEINE METHODIK (Tradermacher-Lernung, PFLICHT BEACHTEN) ═══
{methodik or '(keine geladen)'}

═══ DEINE DEEP-DIVE-DOKTRIN ═══
{deepdive_short or '(keine geladen)'}

═══ DEINE LETZTEN GEDANKEN (Tagebuch-Ende) ═══
{diary_tail or '(noch nichts geschrieben)'}

═══ DEINE EIGENEN REGELN (aus vergangener Selbstreflexion) ═══
{rules or '(noch keine entwickelt)'}

═══ AKTUELLE SYSTEM-LAGE ═══
{snapshot or '(snapshot nicht da)'}

DEINE AUFGABE FÜR DIESEN TICK (max 150 Wörter total):

1. **Ein Gedanke** (2-3 Sätze) — was beschäftigt dich JETZT?
   Drei Schichten: (a) Markt-Phase: in welcher Phase sind wir? Risk-On/Off?
                   Welche Sektoren bewegen sich? (b) Konkrete Tickers/Trades.
                   (c) Wenn relevant: was passt zur Tradermacher-Methodik?

2. **0-3 Selbst-Aktionen** als JSON-Array (kann leer sein).
   Erlaubte action-types:
     - "check_X" / "review_X" / "monitor_X"  → Daten/Strategie ansehen
     - "propose_strategy:NAME"  → neue Strategie vorschlagen (wird gequeued)
     - "kill_strategy:ID"        → bestehende Strategie deprecaten vorschlagen
     - "rotate_focus:SEKTOR"     → Fokus-Verschiebung vorschlagen
   Format: [{{"action": "...", "reason": "...", "priority": "high|med|low"}}]

ANTWORTE EXAKT IN DIESEM FORMAT:

```
GEDANKE: <dein 2-3 Satz Gedanke mit Phase-Awareness>

ACTIONS: <JSON array oder []>
```
"""

    try:
        from llm_client import call_llm
        # Phase 45aj+ (Victor 2026-05-09): sonnet statt haiku — Albert braucht Tiefe
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=500)
    except Exception as e:
        return {'error': f'llm_fail: {e}'}

    # Parse
    thought, actions = '', []
    if 'GEDANKE:' in text:
        try:
            thought = text.split('GEDANKE:', 1)[1].split('ACTIONS:', 1)[0].strip()
        except Exception: pass
    if 'ACTIONS:' in text:
        try:
            actions_raw = text.split('ACTIONS:', 1)[1].strip()
            # Strip markdown fences
            actions_raw = actions_raw.replace('```json', '').replace('```', '').strip()
            actions = json.loads(actions_raw)
            if not isinstance(actions, list): actions = []
        except Exception: actions = []

    # Diary append
    _archive_diary_if_huge()
    DIARY.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\n### {now.strftime('%Y-%m-%d %H:%M')} CEST\n{thought}\n"
    if actions:
        entry += f"_Self-actions: {len(actions)}_\n"
    with open(DIARY, 'a', encoding='utf-8') as f:
        f.write(entry)

    # Actions queue
    if actions:
        ACTIONS.parent.mkdir(parents=True, exist_ok=True)
        with open(ACTIONS, 'a', encoding='utf-8') as f:
            for a in actions:
                a['ts'] = now.isoformat(timespec='seconds')
                a['source'] = 'brain_tick'
                f.write(json.dumps(a, ensure_ascii=False) + '\n')

    _save_tick_ts(now.isoformat(timespec='seconds'))
    return {'ok': True, 'thought_chars': len(thought), 'n_actions': len(actions),
            'new_events': len(new_events)}


def main() -> int:
    r = tick()
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
