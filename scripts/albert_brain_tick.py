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

# Phase 45bd (Victor 2026-05-15): Anti-Wiederholung + Verdict-Auto-Quote
RECENT_THOUGHTS_N    = 3      # letzte 3 Tagebuch-Gedanken als Anti-Repeat-Kontext
REPEAT_SIM_THRESHOLD = 0.30   # Jaccard-Token-Overlap > X → Wiederholung
                              # Kalibriert an realen 06:45-08:30 Repeats (~0.36)
                              # vs. verschiedene Themen (~0.00-0.03).
# Phase 45bi: zweiter Filter — semantische Konzept-Overlap (gegen Synonym-Umgehung)
CONCEPT_OVERLAP_THRESHOLD = 0.60  # >=60% der NEUEN (Ticker,Aktion)-Konzepte
                                  # tauchten schon in den letzten 3 Ticks auf
KNOWN_VERDICTS = {'STRONG_EDGE', 'OK', 'INSUFFICIENT', 'CONFLICT',
                  'WEAK', 'NEGATIVE', 'RETIRED', 'UNKNOWN'}


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


# ── Phase 45bd Helpers: Anti-Wiederholung + Verdict-Auto-Quote ───────────

def _last_n_thoughts(n: int = RECENT_THOUGHTS_N) -> list[str]:
    """Letzte N Tagebuch-Gedanken (Body zwischen `### TS CEST` Headern)."""
    if not DIARY.exists():
        return []
    try:
        text = DIARY.read_text(encoding='utf-8')
    except Exception:
        return []
    import re
    blocks = re.split(r'\n### \d{4}-\d{2}-\d{2} \d{2}:\d{2} CEST\n', text)
    # blocks[0] = vor erstem Header (Müll), Rest = Gedanken-Bodies
    bodies = [b.strip() for b in blocks[1:] if b.strip()]
    # Self-actions-Zeile rausstrippen
    out = []
    for b in bodies[-n:]:
        lines = [l for l in b.splitlines() if not l.startswith('_Self-actions:')]
        out.append('\n'.join(lines).strip())
    return out


def _word_set(s: str) -> set[str]:
    """Bag-of-words für Jaccard — Lowercase, Tokens ≥ 4 Zeichen, ohne Stopper."""
    import re
    stop = {'und', 'oder', 'das', 'ist', 'die', 'der', 'den', 'des', 'dem',
            'ein', 'eine', 'einer', 'einen', 'einem', 'noch', 'nicht', 'auch',
            'aber', 'mit', 'von', 'für', 'auf', 'als', 'sich', 'dass', 'wenn',
            'dann', 'dies', 'diese', 'dieser', 'dieses', 'sind', 'wird', 'werden',
            'kein', 'keine', 'mehr', 'sein', 'seine', 'hier', 'jetzt', 'heute',
            'ohne', 'sondern', 'beide', 'beiden'}
    toks = re.findall(r'[a-z0-9_äöüß]{4,}', s.lower())
    return {t for t in toks if t not in stop}


def _max_similarity(new_text: str, prior: list[str]) -> tuple[float, int]:
    """Max-Jaccard zu vorherigen Gedanken. Returns (max_sim, idx)."""
    if not prior or not new_text.strip():
        return 0.0, -1
    new_set = _word_set(new_text)
    if not new_set:
        return 0.0, -1
    best = (0.0, -1)
    for i, p in enumerate(prior):
        ps = _word_set(p)
        if not ps:
            continue
        inter = len(new_set & ps)
        union = len(new_set | ps)
        sim = inter / union if union else 0.0
        if sim > best[0]:
            best = (sim, i)
    return best


# Phase 45bi (Victor 2026-05-17): Semantischer Concept-Dedupe.
# Wort-Dedupe (Jaccard 0.30) wird durch Synonyme umgangen: "Entry-Level für
# NVDA" vs "Setup-Marker NVDA" haben fast keine gemeinsamen Tokens, aber
# meinen dasselbe. Lösung: Konzept-Signatur (Tickers + Strategy-IDs +
# Aktions-Stems) — wenn der gleiche Ticker mit der gleichen Aktions-Kategorie
# 2x in Folge auftaucht, ist es eine Wiederholung egal welche Worte drumherum.
_TICKER_RE = (r'(?:PS\d+|DT\d|S\d+|PT|AR-\w+|PS_[A-Z0-9_]+|'
              r'[A-Z]{2,5}(?:\.[A-Z]{1,3})?)')
ACTION_STEMS = [
    # (canonical_concept, [trigger_substrings])
    ('ENTRY',     ['entry', 'einstieg', 'kauf', 'breakout', 'ausbruch',
                   'reissline', 'setup', 'level', 'trigger', 'submit']),
    ('EXIT',      ['exit', 'verkauf', 'schliess', 'close', 'stop', 'retir']),
    ('SCAN',      ['scan', 'beobacht', 'monitor', 'watch']),
    ('NEIN',      ['nein ', ' nein', 'skip', 'ablehnen', 'verwerf',
                   'kein trade']),
    ('ANK',       ['ankünd', 'verspr', 'plan', 'todo', 'lesen']),
    ('SIZE',      ['sizing', 'notional', 'aggressi', 'auslastung', 'cash-quote']),
    ('REGIME',    ['bull_volat', 'bear_', 'risk-on', 'risk-off', 'vix']),
]


def _concept_signature(text: str) -> set[tuple[str, str]]:
    """
    Extrahiert (TICKER, ACTION_CONCEPT)-Paare aus einem Tick-Text.
    Wenn ein Ticker und eine Action im selben Tick erwähnt werden, wird
    die Kombination als ein Konzept zählt. Plus generische ('GLOBAL', ACT).
    """
    import re
    if not text or not text.strip():
        return set()
    t_lower = text.lower()
    tickers = set(re.findall(_TICKER_RE, text))
    # Heuristik: filtere Stopwörter die als ALL-CAPS auftauchen
    tickers = {x for x in tickers
               if x not in {'OK', 'CEST', 'CET', 'UTC', 'EUR', 'USD',
                            'WEAK', 'INSUFFICIENT', 'RETIRED', 'STRONG_EDGE',
                            'CONFLICT', 'UNKNOWN', 'NEGATIVE'}}
    actions = set()
    for concept, triggers in ACTION_STEMS:
        if any(tr in t_lower for tr in triggers):
            actions.add(concept)
    sig: set[tuple[str, str]] = set()
    if tickers and actions:
        for tk in tickers:
            for ac in actions:
                sig.add((tk, ac))
    elif actions:
        for ac in actions:
            sig.add(('GLOBAL', ac))
    return sig


def _max_concept_overlap(new_text: str, prior: list[str]) -> tuple[float, int, int]:
    """
    Returns (overlap_ratio, prior_idx, shared_count).
    overlap_ratio = |shared| / max(1, |new_sig|)  — wie viel der NEUEN
    Konzepte schon im prior auftauchten.
    """
    new_sig = _concept_signature(new_text)
    if not new_sig:
        return 0.0, -1, 0
    best = (0.0, -1, 0)
    for i, p in enumerate(prior):
        ps = _concept_signature(p)
        if not ps:
            continue
        shared = new_sig & ps
        ratio = len(shared) / len(new_sig)
        if ratio > best[0]:
            best = (ratio, i, len(shared))
    return best


def _extract_verdict_citations(text: str) -> list[tuple[str, str]]:
    """Findet '<STRAT_ID> [VERDICT]' und '[VERDICT] <STRAT_ID>' Zitate."""
    import re
    ID = r'(?:PS\d+|DT\d|S\d+|PT|AR-\w+|PS_[A-Z0-9_]+)'
    VR = r'\[(STRONG_EDGE|OK|INSUFFICIENT|CONFLICT|WEAK|NEGATIVE|RETIRED|UNKNOWN)\]'
    pairs = []
    for m in re.finditer(rf'({ID})\s*{VR}', text):
        pairs.append((m.group(1).upper(), m.group(2).upper()))
    for m in re.finditer(rf'{VR}\s+({ID})', text):
        pairs.append((m.group(2).upper(), m.group(1).upper()))
    # Dedupe
    seen = set()
    out = []
    for sid, vr in pairs:
        if (sid, vr) not in seen:
            seen.add((sid, vr))
            out.append((sid, vr))
    return out


def _check_verdict_quotes(text: str) -> list[str]:
    """Prüft alle zitierten Verdicts gegen Single-Source-of-Truth.
    Returns Liste der Mismatch-Strings (leer = alles korrekt)."""
    pairs = _extract_verdict_citations(text)
    if not pairs:
        return []
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from strategy_verdict import strategy_verdict as _sv
    except Exception:
        return []  # Fail-open: lieber nicht prüfen als hart fehlschlagen
    mismatches = []
    for sid, quoted in pairs:
        try:
            real = (_sv(sid).get('verdict') or '').upper()
        except Exception:
            continue
        if not real or real not in KNOWN_VERDICTS:
            continue
        if real != quoted:
            mismatches.append(f"{sid}: zitiert [{quoted}], real [{real}]")
    return mismatches


def _parse_thought(text: str) -> str:
    if 'GEDANKE:' in text:
        try:
            return text.split('GEDANKE:', 1)[1].split('ACTIONS:', 1)[0].strip()
        except Exception: pass
    return ''


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
    # Phase 45bd: letzte 3 Gedanken explizit als Anti-Repeat-Kontext
    recent_thoughts = _last_n_thoughts(RECENT_THOUGHTS_N)
    recent_block = '\n\n'.join(
        f'[Tick T-{len(recent_thoughts)-i}] {t}' for i, t in enumerate(recent_thoughts)
    ) if recent_thoughts else '(noch keine vorigen Ticks)'

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

    # Phase 45bi: Wochenend-Event-Gate. Brain-Tick läuft auch am Wochenende
    # weiter (Nachrichten passieren am Wochenende — Geopolitik, Fed-Reden,
    # Earnings-Leaks), aber LLM-Call nur wenn ECHTE Events anliegen.
    # Skip-Bedingung: Sa/So + keine hochwertigen Events (severity >= warning
    # oder bestimmte action-relevante Event-Types). Spart ~85% Wochenend-Ticks
    # ohne den Wachschutz aufzugeben.
    if now.weekday() >= 5:  # 5=Sa, 6=So
        _high_signal = False
        _HOT_TYPES = {
            'macro.breaking_event', 'silence.stale_signal',
            'detector_finding', 'pre_entry_block', 'concentration_block',
            'retired_position_exit_proposal', 'thesis_invalidated',
            'event_auto_exit', 'crash_safety_triggered',
            'strategy.freshness_review', 'ceo.directive_change',
        }
        for e in new_events:
            sev = str(e.get('severity', '')).lower()
            etype = str(e.get('event_type', ''))
            if sev in ('critical', 'warning') or etype in _HOT_TYPES:
                _high_signal = True; break
        if not _high_signal:
            _save_tick_ts(now.isoformat(timespec='seconds'))
            return {'skipped': True, 'reason': 'weekend_no_hot_events',
                    'low_events_seen': len(new_events)}

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

═══ DEINE LETZTEN {RECENT_THOUGHTS_N} TICK-GEDANKEN — NICHT WIEDERHOLEN ═══
{recent_block}

⚠️ HARTER FILTER: Wenn dieser Gedanke inhaltlich wiederholt, was oben
schon steht (gleiche Tickers, gleiche Ankündigungen, gleicher Frame),
wird er verworfen. Schreibe NUR wenn du etwas NEUES sagst — sonst
einen Satz "Nichts Neues, beobachte weiter" und Actions=[].

⚠️ VERDICT-PFLICHT: Wenn du einen STRATEGY-Verdict zitierst (z.B. "DT2 [OK]"
oder "PS4 [WEAK]"), MUSS der Verdict-String EXAKT mit der Single Source of
Truth (strategy_verdict.py) übereinstimmen. Bei Mismatch wird der Tick
hart verworfen. Im Zweifel kein Verdict zitieren.


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

    # Phase 45bd: Zwei-Pass — generate, validate (repeat + verdict),
    # bei Verstoß genau 1× nachschärfen, sonst Tick verwerfen.
    try:
        from self_rule_compliance import enforce_compliance
        text, compliance_meta = enforce_compliance(
            prompt=prompt, model_hint='sonnet', max_tokens=500,
            context='brain_tick'
        )
    except Exception as e:
        return {'error': f'llm_fail: {e}'}

    if compliance_meta.get('output_discarded') or not text:
        _save_tick_ts(now.isoformat(timespec='seconds'))
        return {
            'skipped': True,
            'reason': 'compliance_fail',
            'retries': compliance_meta.get('retries', 0),
            'violations': compliance_meta.get('violations_per_attempt', [])[-1].get('violations', []),
        }

    # Validate: Wiederholung + Verdict-Zitate
    candidate_thought = _parse_thought(text)
    sim, sim_idx = _max_similarity(candidate_thought, recent_thoughts)
    # Phase 45bi: semantische Konzept-Overlap zusätzlich prüfen
    co_ratio, co_idx, co_shared = _max_concept_overlap(candidate_thought, recent_thoughts)
    verdict_mismatches = _check_verdict_quotes(candidate_thought)
    bt_violations: list[str] = []
    if sim >= REPEAT_SIM_THRESHOLD:
        bt_violations.append(
            f'WIEDERHOLUNG: Jaccard {sim:.2f} mit Tick T-{len(recent_thoughts)-sim_idx} '
            f'(Schwelle {REPEAT_SIM_THRESHOLD}). Schreibe etwas NEUES oder "Nichts Neues, beobachte weiter".'
        )
    if co_ratio >= CONCEPT_OVERLAP_THRESHOLD and co_shared >= 2:
        bt_violations.append(
            f'KONZEPT-WIEDERHOLUNG: {co_ratio*100:.0f}% deiner Konzepte '
            f'(Ticker+Aktion) tauchten schon in Tick T-{len(recent_thoughts)-co_idx} auf '
            f'(Schwelle {CONCEPT_OVERLAP_THRESHOLD*100:.0f}%). Synonyme zaehlen nicht — '
            f'andere TICKER oder andere AKTION oder "Nichts Neues".'
        )
    if verdict_mismatches:
        bt_violations.append(
            'FALSCHE VERDICT-ZITATE: ' + '; '.join(verdict_mismatches)
            + '. Nutze die EXAKTEN Werte aus CURRENT TRUTH oder zitiere kein Verdict.'
        )

    # Retry: einmal mit klarer Korrektur-Anweisung
    if bt_violations:
        retry_prompt = (
            prompt
            + '\n\n⚠️ DEIN VORIGER VERSUCH WURDE VERWORFEN. Verstöße:\n'
            + '\n'.join(f'  - {v}' for v in bt_violations)
            + '\n\nSchreibe einen NEUEN Gedanken, der diese Verstöße vermeidet.'
        )
        try:
            text, compliance_meta = enforce_compliance(
                prompt=retry_prompt, model_hint='sonnet', max_tokens=500,
                context='brain_tick_retry'
            )
        except Exception as e:
            _save_tick_ts(now.isoformat(timespec='seconds'))
            return {'skipped': True, 'reason': 'brain_tick_retry_llm_fail',
                    'error': str(e)[:200], 'violations': bt_violations}
        if compliance_meta.get('output_discarded') or not text:
            _save_tick_ts(now.isoformat(timespec='seconds'))
            return {'skipped': True, 'reason': 'compliance_fail_after_retry',
                    'violations': bt_violations}
        # Re-check after retry — harte Diskard wenn immer noch verletzt
        candidate_thought = _parse_thought(text)
        sim2, _ = _max_similarity(candidate_thought, recent_thoughts)
        co2_ratio, _, co2_shared = _max_concept_overlap(candidate_thought, recent_thoughts)
        vm2 = _check_verdict_quotes(candidate_thought)
        final_violations: list[str] = []
        if sim2 >= REPEAT_SIM_THRESHOLD:
            final_violations.append(f'WIEDERHOLUNG bleibt (Jaccard {sim2:.2f})')
        if co2_ratio >= CONCEPT_OVERLAP_THRESHOLD and co2_shared >= 2:
            final_violations.append(f'KONZEPT-WIEDERHOLUNG bleibt ({co2_ratio*100:.0f}%)')
        if vm2:
            final_violations.append('VERDICT-MISMATCH bleibt: ' + '; '.join(vm2))
        if final_violations:
            _save_tick_ts(now.isoformat(timespec='seconds'))
            return {'skipped': True, 'reason': 'brain_tick_validation_fail',
                    'first_pass_violations': bt_violations,
                    'second_pass_violations': final_violations}

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
