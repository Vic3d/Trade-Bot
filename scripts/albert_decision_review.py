#!/usr/bin/env python3
"""
albert_decision_review.py — Phase 45al (Victor 2026-05-09).

Schließt Albert's Feedback-Loop: jede Strategist-Proposal hat ein
expected_outcome + evaluate_after_days. Dieser Job prüft fällige Entscheidungen
und lässt Albert (Opus) selbst entscheiden ob seine Decision richtig war.

Output: data/albert_decision_verdicts.jsonl mit Verdikten:
  - 'right'    : expected_outcome ist eingetreten
  - 'wrong'    : Gegenteil eingetreten
  - 'partial'  : teils richtig
  - 'no_data'  : zu früh / keine Evidenz

Track-Record fließt in nächsten Strategist-Run zurück → Albert lernt.

Run: täglich 22:00 (vor Goal-Tracker, vor Self-Review).
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

PROPOSALS_FILE = WS / 'data' / 'albert_strategist_proposals.jsonl'
VERDICTS_FILE  = WS / 'data' / 'albert_decision_verdicts.jsonl'
DB             = WS / 'data' / 'trading.db'
STRATS_FILE    = WS / 'data' / 'strategies.json'


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists(): return []
    out = []
    try:
        with open(p, encoding='utf-8') as f:
            for line in f:
                try: out.append(json.loads(line))
                except Exception: pass
    except Exception: pass
    return out


def _proposal_already_reviewed(prop_id: str, verdicts: list[dict]) -> bool:
    return any(v.get('proposal_id') == prop_id for v in verdicts)


def _gather_outcome_data(proposal: dict, days_passed: int) -> dict:
    """Sammelt Daten die Outcome-Verifikation erlauben."""
    target = proposal.get('target', '')
    tickers = proposal.get('tickers') or []
    out: dict = {'target': target, 'tickers': tickers, 'days_passed': days_passed}

    if not DB.exists(): return out
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row

    # Strategy-Performance seit Proposal-Datum
    if target and target not in ('ORPHANED_CLEANUP',):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_passed)).isoformat()
        rows = db.execute(
            "SELECT ticker, pnl_eur, exit_type, status FROM paper_portfolio "
            "WHERE strategy=? AND (entry_date >= ? OR close_date >= ?)",
            (target, cutoff, cutoff)
        ).fetchall()
        out['trades_since'] = [dict(r) for r in rows]
        pnl = sum((r['pnl_eur'] or 0) for r in rows
                   if not (r['exit_type'] or '').startswith('BUG_'))
        out['net_pnl_since'] = round(pnl, 2)

    # Aktueller Strategie-Status
    if STRATS_FILE.exists() and target:
        try:
            sj = json.loads(STRATS_FILE.read_text(encoding='utf-8'))
            if target in sj and isinstance(sj[target], dict):
                out['current_status'] = sj[target].get('status', '?')
        except Exception: pass

    # Ticker-Performance (für create-Proposals)
    if tickers and DB.exists():
        for t in tickers[:3]:
            try:
                row = db.execute(
                    "SELECT close FROM prices WHERE ticker=? "
                    "ORDER BY date DESC LIMIT 1", (t,)
                ).fetchone()
                if row: out[f'price_now_{t}'] = float(row['close'])
            except Exception: pass

    db.close()
    return out


def review_due_proposals() -> dict:
    now = datetime.now(timezone.utc)
    runs = _load_jsonl(PROPOSALS_FILE)
    verdicts = _load_jsonl(VERDICTS_FILE)

    new_verdicts = []
    skipped = 0
    for run in runs:
        run_ts = run.get('ts', '')
        try:
            run_dt = datetime.fromisoformat(run_ts.replace('Z', '+00:00'))
        except Exception: continue

        for proposal in run.get('proposals', []):
            if not isinstance(proposal, dict): continue
            evaluate_after_days = proposal.get('evaluate_after_days', 7)
            try: evaluate_after_days = int(evaluate_after_days)
            except Exception: evaluate_after_days = 7

            due_at = run_dt + timedelta(days=evaluate_after_days)
            if now < due_at: continue  # noch nicht fällig

            # Stable proposal_id
            target = proposal.get('target', '')
            action = proposal.get('action', '')
            prop_id = f"{run_ts}_{action}_{target}"

            if _proposal_already_reviewed(prop_id, verdicts):
                skipped += 1
                continue

            # Daten sammeln
            outcome_data = _gather_outcome_data(proposal, evaluate_after_days)

            # Opus bewerten lassen
            prompt = f"""Du bist Albert. Du hast vor {evaluate_after_days} Tagen folgende
Entscheidung getroffen. Heute ist Zeit, sie ehrlich zu bewerten.

═══ DEINE PROPOSAL VOM {run_ts[:10]} ═══
{json.dumps(proposal, ensure_ascii=False, indent=2)}

═══ WAS PASSIERT IST ({evaluate_after_days} Tage später) ═══
{json.dumps(outcome_data, ensure_ascii=False, indent=2, default=str)}

═══ DEINE AUFGABE ═══
Bewerte als reflektierender CEO. Sei brutal ehrlich.

1. **Verdict** (1 Wort): right | wrong | partial | no_data
2. **Begründung** (max 60 Wörter): Was ist tatsächlich passiert?
   Wurde dein expected_outcome erreicht? Falls nicht — warum?
3. **Lektion** (max 40 Wörter): Was lernst du daraus für zukünftige Decisions?

ANTWORT-FORMAT exakt:
```
VERDICT: <right|wrong|partial|no_data>

BEGRÜNDUNG: <max 60 Wörter>

LEKTION: <max 40 Wörter>
```
"""
            try:
                from llm_client import call_llm
                text, _ = call_llm(prompt, model_hint='opus', max_tokens=600)
            except Exception as e:
                text = f'VERDICT: no_data\nBEGRÜNDUNG: llm_fail {e}\nLEKTION: -'

            # Parse
            verdict = 'no_data'
            begruendung = ''
            lektion = ''
            if 'VERDICT:' in text:
                try:
                    verdict = text.split('VERDICT:', 1)[1].split('\n', 1)[0].strip().lower()
                    verdict = next((v for v in ('right', 'wrong', 'partial', 'no_data')
                                    if v in verdict), 'no_data')
                except Exception: pass
            if 'BEGRÜNDUNG:' in text:
                try:
                    begruendung = text.split('BEGRÜNDUNG:', 1)[1].split('LEKTION:', 1)[0].strip()
                except Exception: pass
            if 'LEKTION:' in text:
                try: lektion = text.split('LEKTION:', 1)[1].strip()
                except Exception: pass

            new_verdicts.append({
                'proposal_id': prop_id,
                'proposal_ts': run_ts,
                'reviewed_at': now.isoformat(timespec='seconds'),
                'days_elapsed': evaluate_after_days,
                'proposal': proposal,
                'outcome_data': outcome_data,
                'verdict': verdict,
                'reason': begruendung,
                'lesson': lektion,
                'full_text': text,
            })

    # Persist
    if new_verdicts:
        VERDICTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(VERDICTS_FILE, 'a', encoding='utf-8') as f:
            for v in new_verdicts:
                f.write(json.dumps(v, ensure_ascii=False, default=str) + '\n')

    return {
        'ts': now.isoformat(timespec='seconds'),
        'reviewed_now': len(new_verdicts),
        'skipped_already_reviewed': skipped,
        'verdicts': [{'verdict': v['verdict'], 'target': v['proposal'].get('target'),
                       'lesson': v.get('lesson', '')[:80]} for v in new_verdicts],
    }


def main() -> int:
    r = review_due_proposals()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
