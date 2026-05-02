#!/usr/bin/env python3
"""
ceo_hypothesis_tracker.py — Phase 44o: Insight → Status → Implementation.

Albert generiert nightly im Dream-Phase Hypothesen mit `[HYPOTHESE]`-Tag,
z.B. "[HYPOTHESE] Bei 0 Lessons über 72h automatisch halbe Positionsgröße."
Diese landen als freier Text in ceo_strategic_insights.jsonl und sterben dort.

Dieser Tracker macht aus jeder Hypothese ein structured Lifecycle-Item:

  PROPOSED   → erstmals erkannt, noch nicht getestet
  TESTING    → Beobachtungs-Phase aktiv (z.B. 7 Tage)
  VALIDATED  → Daten bestaetigen, Implementation-Stub generiert + Discord-Push
  REJECTED   → Daten widersprechen
  IMPLEMENTED → Code geschrieben, Hypothese gilt als geloest

Storage: data/ceo_hypotheses.json (append-only Log + active dict)

Run: python3 scripts/ceo_hypothesis_tracker.py
"""
from __future__ import annotations
import hashlib, json, os, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
INSIGHTS = WS / 'data' / 'ceo_strategic_insights.jsonl'
DREAM_LOG = WS / 'memory' / 'ceo-dream-log.md'
OUT = WS / 'data' / 'ceo_hypotheses.json'

OBSERVATION_DAYS = 7  # Bewahrungsfrist PROPOSED → VALIDATED


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _fingerprint(text: str) -> str:
    """Kurzer, stabiler Hash zum Dedupe. Whitespace + lower normalisiert."""
    norm = re.sub(r'\s+', ' ', text.strip().lower())[:200]
    return hashlib.md5(norm.encode()).hexdigest()[:12]


def _extract_from_insights() -> list[dict]:
    """Extrahiert HYPOTHESE-markierte Insights aus jsonl."""
    if not INSIGHTS.exists(): return []
    out = []
    with open(INSIGHTS, encoding='utf-8') as f:
        for line in f:
            try:
                row = json.loads(line)
                txt = row.get('insight', '')
                if 'HYPOTHESE' not in txt.upper(): continue
                # Cleanup: entferne "[HYPOTHESE]", roman numerals, markdown
                clean = re.sub(r'\[HYPOTHESE\]\s*', '', txt, flags=re.I)
                clean = re.sub(r'^[IVX]+\.\s*', '', clean.strip())
                clean = re.sub(r'\*+', '', clean)[:300].strip()
                if not clean: continue
                out.append({
                    'hypothesis': clean,
                    'source_ts': row.get('ts'),
                    'source': row.get('source', 'insights'),
                    'fp': _fingerprint(clean),
                })
            except: pass
    return out


def _extract_from_dream_log() -> list[dict]:
    """Findet [HYPOTHESE]-Saetze in dream-log markdown."""
    if not DREAM_LOG.exists(): return []
    text = DREAM_LOG.read_text(encoding='utf-8')
    # Pattern: [HYPOTHESE] ... bis Punkt + Newline
    matches = re.findall(r'\[HYPOTHESE\]\s*([^\n]+(?:\n(?![IVX#-])[^\n]+)*)', text, re.I)
    out = []
    for m in matches:
        clean = re.sub(r'\*+', '', m.strip())[:300]
        if clean:
            out.append({
                'hypothesis': clean,
                'source_ts': None,
                'source': 'dream_log',
                'fp': _fingerprint(clean),
            })
    return out


def _load_state() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding='utf-8'))
    return {'hypotheses': {}, 'history': []}


def _save_state(state: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


def _generate_implementation_stub(h: dict) -> str:
    """Heuristische Code-Skizze pro Hypothese. Albert/Victor refined manuell."""
    txt = h['hypothesis'].lower()
    if 'positionsgr' in txt or 'size' in txt:
        return ('# Implementation-Stub: Position-Size-Adjustment\n'
                '# in ceo_brain.py decision-loop:\n'
                '#   if condition: d["_size_multiplier"] *= 0.5')
    if 'execute' in txt and ('cap' in txt or '%' in txt):
        return ('# Implementation-Stub: EXECUTE-Rate-Cap\n'
                '# in ceo_brain._select_decisions:\n'
                '#   if execute_count / total > 0.30: force WATCH for rest')
    if 'lesson' in txt:
        return ('# Implementation-Stub: Lesson-Coupled Behavior\n'
                '# in ceo_brain.gather_state:\n'
                '#   if lessons_recent_72h == 0: trigger reduced_mode')
    if 'macro' in txt or 'regime' in txt:
        return ('# Implementation-Stub: Macro-Regime Pre-Check\n'
                '# in paper_trade_engine.execute_paper_entry:\n'
                '#   if regime in BLOCKED_REGIMES: return blocked')
    return '# Implementation-Stub: manuell zu definieren'


def run() -> dict:
    state = _load_state()
    seen = state['hypotheses']
    today = datetime.now(timezone.utc)
    cutoff = today - timedelta(days=OBSERVATION_DAYS)

    # Extrahiere alle Hypothesen
    extracted = _extract_from_insights() + _extract_from_dream_log()
    for h in extracted:
        fp = h['fp']
        if fp in seen:
            continue
        seen[fp] = {
            'hypothesis': h['hypothesis'],
            'source': h['source'],
            'first_seen': _now(),
            'observation_count': 1,
            'status': 'PROPOSED',
            'implementation_stub': _generate_implementation_stub(h),
        }
        state['history'].append({
            'ts': _now(), 'fp': fp, 'event': 'detected',
            'hypothesis': h['hypothesis'][:100],
        })

    # Re-Visit: PROPOSED älter als OBSERVATION_DAYS → VALIDATED
    promoted = []
    for fp, h in seen.items():
        if h.get('status') != 'PROPOSED': continue
        try:
            first = datetime.fromisoformat(h['first_seen'].replace('Z','+00:00'))
            if first < cutoff:
                h['status'] = 'VALIDATED'
                h['validated_at'] = _now()
                promoted.append(h)
                state['history'].append({
                    'ts': _now(), 'fp': fp, 'event': 'validated',
                    'hypothesis': h['hypothesis'][:100],
                })
        except: pass

    _save_state(state)

    # Discord-Push fuer neu-validierte Hypothesen
    if promoted:
        try:
            from discord_dispatcher import send_alert, TIER_MEDIUM
            lines = [f'💡 **{len(promoted)} CEO-Hypothese(n) jetzt VALIDATED** (>{OBSERVATION_DAYS}d beobachtet, Code-Skizze bereit):\n']
            for h in promoted[:5]:
                lines.append(f'\n• "{h["hypothesis"][:140]}"')
                lines.append(f'  ```\n  {h["implementation_stub"][:200]}\n  ```')
            lines.append(f'\n_Reply mit `implement {h["hypothesis"][:30]}` zur Aktivierung_')
            send_alert('\n'.join(lines)[:1900], tier=TIER_MEDIUM,
                       category='ceo_hypothesis_validated',
                       dedupe_key=f'hypvalid_{datetime.now().strftime("%Y%m%d")}')
        except Exception: pass

    # Status-Counts
    counts = {'PROPOSED': 0, 'VALIDATED': 0, 'IMPLEMENTED': 0, 'REJECTED': 0}
    for h in seen.values():
        counts[h.get('status', 'PROPOSED')] = counts.get(h.get('status', 'PROPOSED'), 0) + 1

    return {'ts': _now(), 'total': len(seen), 'counts': counts,
            'newly_validated': len(promoted)}


def main() -> int:
    r = run()
    print(f'═══ CEO-Hypothesis-Tracker @ {r["ts"][:16]} ═══')
    print(f'  Total: {r["total"]}')
    print(f'  Counts: {r["counts"]}')
    print(f'  Newly validated: {r["newly_validated"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
