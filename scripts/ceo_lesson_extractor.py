#!/usr/bin/env python3
"""
ceo_lesson_extractor.py — Phase 44o: Trade-Outcome → permanent Lesson.

Albert hat 0 permanente Lessons nach 65 Trades. Selbst-erkanntes Versaeumnis.
Dieser Job laeuft nightly ueber alle Trades die seit letztem Run geschlossen
wurden und extrahiert pro Trade eine structured Lesson:

  Pro closed Trade:
    - Outcome: WIN/LOSS, PnL, hold_duration, exit_type
    - Pre-Trade-State: conviction, regime, sektor, news_tier
    - Post-Trade-Reflection: was hat funktioniert, was nicht
    - Pattern-Tag: zur Aggregation (z.B. "stop_too_tight", "thesis_invalid")

  Aggregation in permanent_lessons.jsonl wenn Pattern n>=3 wiederkehrend ist.

Output:
  data/permanent_lessons.jsonl   (kondensierte Patterns mit n>=3)
  data/lesson_extraction_log.jsonl  (pro Trade)

Run: python3 scripts/ceo_lesson_extractor.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'lesson_extraction_log.jsonl'
PERMANENT = WS / 'data' / 'permanent_lessons.jsonl'
STATE = WS / 'data' / 'lesson_extractor_state.json'


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _classify_trade(t: dict) -> list[str]:
    """Liefert Pattern-Tags pro Trade (kann mehrere haben)."""
    tags = []
    pnl = t.get('pnl_eur') or 0
    pct = t.get('pnl_pct') or 0
    exit_type = (t.get('exit_type') or '').upper()
    conv = t.get('conviction') or 0
    notes = (t.get('notes') or '').upper()

    # Stop-Pattern
    if 'STOP' in exit_type and abs(pct) < 2:
        tags.append('stop_too_tight')  # Kleine Bewegung hat Stop ausgeloest
    if 'MACRO_AUTO_EXIT' in exit_type:
        tags.append('macro_panic_exit')
    if 'MACRO-TIGHTENED' in notes or 'MACRO-BREAKEVEN' in notes:
        tags.append('macro_reactor_killed_trade')
    if 'CRASH_AUTO_EXIT' in exit_type:
        tags.append('crash_safety_triggered')

    # Conviction vs Outcome
    if conv >= 80 and pnl < 0:
        tags.append('high_conviction_loss')  # Overconfidence-Signal
    if conv <= 50 and pnl > 0:
        tags.append('low_conviction_win')   # Underconfidence-Signal

    # Time-Stops
    if 'TIME' in exit_type:
        tags.append('time_stop_hit')

    # Target-Hits
    if 'TARGET' in exit_type:
        tags.append('target_reached')

    # Tranche-Exits
    if 'TRANCHE' in exit_type:
        tags.append('tranche_partial')

    # PnL-Magnitude
    if pnl > 200: tags.append('big_win_200plus')
    if pnl < -200: tags.append('big_loss_200plus')

    return tags


def _per_trade_lesson(t: dict, tags: list[str]) -> dict:
    """Erzeugt die Trade-spezifische Lesson."""
    pnl = t.get('pnl_eur') or 0
    return {
        'ts': _now(),
        'trade_id': t['id'],
        'ticker': t['ticker'],
        'strategy': t['strategy'],
        'outcome': 'WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'FLAT',
        'pnl_eur': round(pnl, 2),
        'pnl_pct': round(t.get('pnl_pct') or 0, 2),
        'conviction': t.get('conviction'),
        'exit_type': t.get('exit_type'),
        'tags': tags,
    }


def _consolidate_to_permanent(state: dict) -> list[dict]:
    """Aggregiert Tags ueber alle gesehenen Trades.
    Wenn ein Tag n>=3x auftritt → schreibe als permanente Lesson."""
    counts = defaultdict(list)
    for entry in state.get('all_trades', []):
        for tag in entry.get('tags', []):
            counts[tag].append(entry)

    new_permanent = []
    existing_lessons = set()
    if PERMANENT.exists():
        with open(PERMANENT, encoding='utf-8') as f:
            for line in f:
                try:
                    existing_lessons.add(json.loads(line).get('pattern'))
                except: pass

    pattern_explanations = {
        'stop_too_tight': 'Stop wurde durch <2% Bewegung getriggert — Stop war zu eng fuer normale Vola.',
        'macro_reactor_killed_trade': 'Macro-Reactor hat Stop blind getightet, Trade wurde unnoetig gestoppt.',
        'macro_panic_exit': 'MACRO_AUTO_EXIT bei -5% — moeglicherweise zu reaktiv.',
        'high_conviction_loss': 'Conviction>=80 aber Verlust → Overconfidence-Signal, Calibration pruefen.',
        'low_conviction_win': 'Conviction<=50 aber Win → Underconfidence-Signal, Schwelle senken pruefen.',
        'time_stop_hit': 'Position wurde durch Time-Stop geschlossen — Edge-Hypothese hat nicht innerhalb Hold-Window getragen.',
        'target_reached': 'Vollst. Target-Hit — Strategy-Mechanik bestaetigt.',
        'big_loss_200plus': 'Verlust > 200EUR — Position-Sizing oder Stop-Distanz pruefen.',
    }

    for tag, entries in counts.items():
        if len(entries) >= 3 and tag not in existing_lessons:
            avg_pnl = sum(e.get('pnl_eur', 0) for e in entries) / len(entries)
            new_permanent.append({
                'ts': _now(),
                'pattern': tag,
                'occurrences': len(entries),
                'avg_pnl_eur': round(avg_pnl, 2),
                'explanation': pattern_explanations.get(tag, ''),
                'sample_trades': [e['trade_id'] for e in entries[:5]],
            })

    if new_permanent:
        PERMANENT.parent.mkdir(parents=True, exist_ok=True)
        with open(PERMANENT, 'a', encoding='utf-8') as f:
            for L in new_permanent:
                f.write(json.dumps(L, ensure_ascii=False) + '\n')

    return new_permanent


def _load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding='utf-8'))
    return {'last_processed_id': 0, 'all_trades': []}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


def run() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    state = _load_state()
    last_id = state.get('last_processed_id', 0)

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, ticker, strategy, conviction, pnl_eur, pnl_pct, "
        "       status, exit_type, notes "
        "FROM paper_portfolio "
        "WHERE id > ? AND status IN ('WIN','LOSS','CLOSED') "
        "ORDER BY id ASC", (last_id,)
    ).fetchall()
    c.close()

    new_lessons = []
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for r in rows:
        t = dict(r)
        tags = _classify_trade(t)
        lesson = _per_trade_lesson(t, tags)
        new_lessons.append(lesson)
        state['all_trades'].append(lesson)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(lesson, ensure_ascii=False) + '\n')
        if t['id'] > state['last_processed_id']:
            state['last_processed_id'] = t['id']

    permanent = _consolidate_to_permanent(state)
    _save_state(state)

    if permanent:
        try:
            from discord_dispatcher import send_alert, TIER_SILENT as TIER_LOW  # Phase 44u: silent
            msg = f'📚 **{len(permanent)} neue permanente Lesson(s)** kondensiert:\n'
            for L in permanent:
                msg += (f'\n• `{L["pattern"]}` (n={L["occurrences"]}, '
                        f'avg PnL {L["avg_pnl_eur"]:+.0f}EUR)\n'
                        f'  → {L["explanation"][:150]}')
            send_alert(msg[:1900], tier=TIER_LOW, category='permanent_lessons',
                       dedupe_key=f'lesson_{datetime.now().strftime("%Y%m%d")}')
        except Exception: pass

    return {'ts': _now(), 'new_trade_lessons': len(new_lessons),
            'new_permanent': len(permanent),
            'total_processed': len(state.get('all_trades', []))}


def main() -> int:
    r = run()
    print(f'═══ Lesson-Extractor @ {r.get("ts","")[:16]} ═══')
    print(f'  New trade lessons: {r.get("new_trade_lessons", 0)}')
    print(f'  New permanent lessons: {r.get("new_permanent", 0)}')
    print(f'  Total processed lifetime: {r.get("total_processed", 0)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
