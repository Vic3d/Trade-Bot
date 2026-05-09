#!/usr/bin/env python3
"""
ceo_self_audit.py — Phase 45ai (Victor 2026-05-09).

CEO sucht ACTIVE nach Bugs, schlechten Entscheidungen und Verbesserungen.
Nicht regelbasiert (wie friday_improvement_briefing), sondern reflexiv —
LLM bekommt die Daten der Woche und stellt sich selbst kritische Fragen.

Output landet im Sonntags-Briefing (sichtbar) UND in
data/ceo_self_audit_log.jsonl (historisch).

Run: Sonntag 19:00 vor Week-Ahead-Briefing.

Direktive:
  Albert, Du hast diese Woche [X] Trades gemacht, [Y] Bugs sind aufgetreten,
  [Z] Hallus passiert. Sieh dir den Code, die Logik und die Daten an —
  was würdest Du als CEO an diesem System verbessern?
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'ceo_self_audit_log.jsonl'
OUT_MD = WS / 'data' / 'ceo_self_audit_latest.md'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))


def gather_context() -> dict:
    """Sammelt Daten der letzten 7 Tage als Audit-Material."""
    ctx: dict = {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    # Trades letzte 7d
    trades = db.execute(
        "SELECT id, ticker, strategy, entry_date, close_date, pnl_eur, pnl_pct, "
        "exit_type, status, notes "
        "FROM paper_portfolio "
        "WHERE entry_date >= ? OR close_date >= ? "
        "ORDER BY COALESCE(close_date, entry_date) DESC",
        (cutoff, cutoff)
    ).fetchall()
    ctx['trades_7d'] = [dict(r) for r in trades[:30]]
    ctx['n_trades_7d'] = len(trades)
    ctx['n_bug_rollbacks'] = sum(1 for r in trades
                                  if (r['exit_type'] or '').startswith('BUG_ROLLBACK'))

    # Halluzinations-Log
    hallu_file = WS / 'data' / 'halluzination_log.jsonl'
    if hallu_file.exists():
        hallu_count = 0
        hallu_types: dict = {}
        try:
            with open(hallu_file, encoding='utf-8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        ts = e.get('ts', '')
                        if ts < cutoff: continue
                        hallu_count += 1
                        for f_obj in e.get('findings', []):
                            k = f_obj.get('kind', '?')
                            hallu_types[k] = hallu_types.get(k, 0) + 1
                    except Exception:
                        pass
        except Exception:
            pass
        ctx['hallus_7d'] = hallu_count
        ctx['hallu_top'] = sorted(hallu_types.items(), key=lambda x: -x[1])[:5]

    # Audit-Violations (CLI-Claude)
    cli_file = WS / 'data' / 'cli_audit_violations.jsonl'
    ctx['cli_violations_7d'] = 0
    if cli_file.exists():
        try:
            with open(cli_file, encoding='utf-8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if e.get('ts', '') >= cutoff:
                            ctx['cli_violations_7d'] += 1
                    except Exception:
                        pass
        except Exception:
            pass

    # Detector-Findings (CEO-Inbox)
    inbox_file = WS / 'data' / 'ceo_inbox.jsonl'
    ctx['detector_findings_7d'] = 0
    detector_top: dict = {}
    if inbox_file.exists():
        try:
            with open(inbox_file, encoding='utf-8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if e.get('ts', '') < cutoff: continue
                        cat = e.get('category', '')
                        if cat in ('detector_finding', 'health'):
                            ctx['detector_findings_7d'] += 1
                            et = e.get('event_type', '?')
                            detector_top[et] = detector_top.get(et, 0) + 1
                    except Exception:
                        pass
        except Exception:
            pass
    ctx['detector_top'] = sorted(detector_top.items(), key=lambda x: -x[1])[:5]

    # Strategien-Status
    strats_file = WS / 'data' / 'strategies.json'
    if strats_file.exists():
        try:
            sj = json.loads(strats_file.read_text(encoding='utf-8'))
            ctx['n_active_strategies'] = sum(1 for v in sj.values()
                                              if isinstance(v, dict)
                                              and v.get('status') == 'active')
            ctx['n_archived'] = sum(1 for v in sj.values()
                                     if isinstance(v, dict)
                                     and v.get('status') == 'archived')
        except Exception:
            pass

    # Lifecycle-Audit
    lc_file = WS / 'data' / 'strategy_lifecycle.json'
    if lc_file.exists():
        try:
            lc = json.loads(lc_file.read_text(encoding='utf-8'))
            ctx['lifecycle_counts'] = lc.get('counts', {})
        except Exception:
            pass

    db.close()
    return ctx


def run_audit() -> dict:
    ctx = gather_context()
    try:
        from llm_client import call_llm
    except Exception as e:
        return {'error': f'llm_client_missing: {e}', 'ctx': ctx}

    prompt = f"""Du bist Albert, der AI-CEO von TradeMind. Heute ist Sonntag.
Du machst dein wöchentliches Selbst-Audit. Sei BRUTAL EHRLICH — Victor will
echte Verbesserungsvorschläge, keine Floskeln.

DATEN DIESER WOCHE:
- Trades 7d: {ctx.get('n_trades_7d', 0)} (davon {ctx.get('n_bug_rollbacks', 0)} BUG_ROLLBACK)
- Halluzinationen 7d: {ctx.get('hallus_7d', 0)} ({ctx.get('hallu_top', [])})
- CLI-Audit-Violations 7d: {ctx.get('cli_violations_7d', 0)}
- Detector-Findings 7d: {ctx.get('detector_findings_7d', 0)} ({ctx.get('detector_top', [])})
- Active Strategien: {ctx.get('n_active_strategies', '?')}
- Archived: {ctx.get('n_archived', '?')}
- Lifecycle: {ctx.get('lifecycle_counts', {})}

LETZTE TRADES (max 10):
{json.dumps([{k: v for k, v in t.items() if k in ('id','ticker','strategy','exit_type','pnl_eur')} for t in ctx.get('trades_7d', [])[:10]], indent=2, ensure_ascii=False)}

DEINE AUFGABE:
Beantworte als reflektierender CEO 4 Fragen. Denke laut, sei spezifisch,
zitiere Daten aus dem Block oben. Keine generischen Tipps.

1. **Was ist diese Woche schlecht gelaufen, das ich nicht gesehen habe?**
   (Suche nach Pattern in den Trades, Bugs, Hallus. Sei selbstkritisch.)

2. **Welche 3 konkreten Bugs/Schwachstellen siehst du im SYSTEM** (nicht im Markt)?
   Beispiele: "Guard X greift nicht weil Y", "Strategie Z hat keinen Scanner",
   "Daten-Quelle A liefert seit B Tagen veraltete Werte".
   Sei konkret. Nenne Dateien, Klassen, IDs wenn möglich.

3. **Was würdest du diese Woche persönlich verbessern, wenn du der Mensch wärst?**
   Top 3, priorisiert. Reversibel-zuerst, riskanter zuletzt.

4. **Welche Frage solltest du dir nächste Woche stellen, die du bisher nicht gestellt hast?**
   (Self-Awareness-Check: was sind deine eigenen Blind-Spots?)

FORMAT: Markdown, max 600 Wörter. Tabellen wo sinnvoll. Verwende KONKRETE
Zahlen aus dem Daten-Block oben — keine erfundenen Werte.
"""

    try:
        # Phase 45aj+ (Victor 2026-05-09): opus — strategischer Wochen-Audit
        text, meta = call_llm(prompt, model_hint='opus', max_tokens=2500)
    except Exception as e:
        return {'error': f'llm_call_failed: {e}', 'ctx': ctx}

    out = {
        'ts': ctx['ts'],
        'context_summary': {k: v for k, v in ctx.items()
                            if k not in ('trades_7d',)},
        'audit_text': text,
        'llm_meta': meta if isinstance(meta, dict) else {},
    }
    return out


def main() -> int:
    r = run_audit()
    if 'error' in r:
        print(json.dumps(r, indent=2, default=str))
        return 1

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(r, default=str, ensure_ascii=False) + '\n')

    md = (
        f"# CEO Self-Audit — {r['ts'][:10]}\n\n"
        f"_Reflexives Wochen-Audit. Albert sucht aktiv nach Bugs und Verbesserungen._\n\n"
        f"---\n\n"
        f"{r['audit_text']}\n"
    )
    OUT_MD.write_text(md, encoding='utf-8')
    print(md)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
