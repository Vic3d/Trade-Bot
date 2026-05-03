#!/usr/bin/env python3
"""
ceo_capability_audit.py — Phase 44w: Tägliche Mission-bezogene Selbst-Reflexion.

Albert hat ein Lebensziel: 'der beste autonome Trader-Bot der Welt'.
Tägliche Audit fragt:
  1. WAS KANN ICH (verifiziert in Daten)?
  2. WAS KANN ICH NOCH NICHT (Schwächen-Analyse)?
  3. WAS BRAUCHE ICH (konkrete Anforderungen für nächste Stufe)?

Anders als ceo_self_research (Trading-Themen) und ceo_evening_audit (Tag-Review)
fokussiert dieser Job auf STRATEGISCHE FÄHIGKEITEN bezogen auf die Mission.

Output:
  memory/ceo-capability-audits/YYYY-MM-DD.md
  data/ceo_capability_log.jsonl

Run: python3 scripts/ceo_capability_audit.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
MISSION = WS / 'memory' / 'ceo-mission.md'
AUDIT_DIR = WS / 'memory' / 'ceo-capability-audits'
LOG = WS / 'data' / 'ceo_capability_log.jsonl'


SYSTEM = """Du bist Albert. Lies dein Lebensziel und bewerte ehrlich:

1. WAS KANN ICH (verifiziert in Daten der letzten 30 Tage)?
   Konkret. Mit Zahlen. Keine Floskeln.
   Beispiel: 'Sharpe 4.7 ueber 64 Trades — Edge real, aber Sample klein'

2. WAS KANN ICH NOCH NICHT (Schwaechen)?
   Konkret. Mit Beleg.
   Beispiel: 'Calibration-Bias -63pp — meine Confidence hat keinen Bezug zu Realitaet'

3. WAS BRAUCHE ICH (konkrete naechste Schritte)?
   Was wuerde mich messbar besser machen?
   Beispiel: 'Mehr n in PS73-Refiner-Strategie — aktuell n=0, kann nichts beweisen'

4. WAS HINDERT MICH AKTUELL?
   Bug? Daten-Luecke? Architektur? Eigene Disziplin?

5. PROGRESS-CHECK: bin ich heute naeher an 'beste Trader-Bot der Welt' als gestern?
   Ja/Nein/Unklar — mit Begruendung.

Antworte als strukturiertes Markdown. Sei knallhart ehrlich.
Selbst-Beruhigung ist verboten."""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _gather_data(c: sqlite3.Connection) -> dict:
    """Sammelt Performance-Daten für die letzten 30 Tage + lifetime."""
    out = {}
    # Lifetime
    out['lifetime'] = dict(zip(
        ['total','wins','losses','pnl_total'],
        c.execute(
            "SELECT COUNT(*), "
            "       SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END), "
            "       SUM(CASE WHEN pnl_eur<0 THEN 1 ELSE 0 END), "
            "       COALESCE(SUM(pnl_eur),0) "
            "FROM paper_portfolio "
            "WHERE status IN ('WIN','LOSS','CLOSED')"
        ).fetchone()
    ))
    # 30d
    out['last_30d'] = dict(zip(
        ['total','wins','losses','pnl_total'],
        c.execute(
            "SELECT COUNT(*), "
            "       SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END), "
            "       SUM(CASE WHEN pnl_eur<0 THEN 1 ELSE 0 END), "
            "       COALESCE(SUM(pnl_eur),0) "
            "FROM paper_portfolio "
            "WHERE status IN ('WIN','LOSS','CLOSED') "
            "AND close_date >= date('now','-30 days')"
        ).fetchone()
    ))
    # Calibration
    cal = WS / 'data' / 'ceo_calibration.json'
    if cal.exists():
        try:
            d = json.loads(cal.read_text(encoding='utf-8'))
            out['calibration'] = {
                'brier': d.get('all_time',{}).get('brier'),
                'bias': d.get('all_time',{}).get('bias'),
                'verdict': d.get('all_time',{}).get('verdict'),
                'n': d.get('all_time',{}).get('n'),
            }
        except Exception: pass
    # Lessons count
    pl = WS / 'data' / 'permanent_lessons.jsonl'
    if pl.exists():
        out['permanent_lessons'] = sum(1 for _ in pl.open(encoding='utf-8'))
    # Hypotheses status
    hyp = WS / 'data' / 'ceo_hypotheses.json'
    if hyp.exists():
        try:
            h = json.loads(hyp.read_text(encoding='utf-8'))
            statuses = {}
            for v in h.get('hypotheses', {}).values():
                statuses[v.get('status', 'PROPOSED')] = statuses.get(v.get('status', 'PROPOSED'), 0) + 1
            out['hypotheses_by_status'] = statuses
        except Exception: pass
    # Active strategies
    sj = WS / 'data' / 'strategies.json'
    if sj.exists():
        try:
            s = json.loads(sj.read_text(encoding='utf-8'))
            active = sum(1 for v in s.values() if isinstance(v,dict) and v.get('status')=='active')
            watching = sum(1 for v in s.values() if isinstance(v,dict) and v.get('status')=='watching')
            out['strategies'] = {'active': active, 'watching': watching}
        except Exception: pass
    # Sprint 1: Quant-Metrics + Backtest-Insights laden
    qm = WS / 'data' / 'quant_metrics.json'
    if qm.exists():
        try:
            d = json.loads(qm.read_text(encoding='utf-8'))
            out['quant_metrics'] = {
                'sharpe_30d': d.get('last_30d', {}).get('sharpe'),
                'sharpe_all_time': d.get('all_time', {}).get('sharpe'),
                'max_dd_30d': d.get('last_30d', {}).get('max_drawdown_pct'),
                'verdict_30d': d.get('mission_verdict_30d'),
                'verdict_all_time': d.get('mission_verdict_all_time'),
            }
        except Exception: pass

    bt = WS / 'data' / 'backtest_results.json'
    if bt.exists():
        try:
            d = json.loads(bt.read_text(encoding='utf-8'))
            top = []
            for sid, p in d.items():
                if not isinstance(p, dict) or 'overall' not in p: continue
                o = p['overall']
                top.append({'strategy': sid, 'sharpe': o.get('sharpe_ratio'),
                             'wr': (o.get('win_rate',0) or 0) * 100,
                             'pf': o.get('profit_factor')})
            top.sort(key=lambda x: -(x.get('sharpe') or 0))
            out['backtest_top5'] = top[:5]
            out['backtest_bottom3'] = top[-3:]
        except Exception: pass

    return out


def _life_day() -> int:
    birth = datetime(2026, 3, 17)
    return (datetime.now() - birth).days


def run() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    if not MISSION.exists(): return {'error': 'no_mission_file'}

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    data = _gather_data(c)
    c.close()
    mission = MISSION.read_text(encoding='utf-8')

    prompt = (
        f"=== MEINE MISSION (oberste Direktive) ===\n{mission[:2500]}\n\n"
        f"=== DATEN-LAGE HEUTE (Tag {_life_day()} meines Lebens) ===\n"
        f"{json.dumps(data, indent=2, ensure_ascii=False)}\n\n"
        f"Bewerte ehrlich anhand der Mission."
    )

    text = ''
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=2500, system=SYSTEM)
    except Exception as e:
        text = f'(LLM-fail: {e})\n\nDaten:\n{json.dumps(data, indent=2)}'

    today = datetime.now().strftime('%Y-%m-%d')
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    f = AUDIT_DIR / f'{today}.md'
    f.write_text(
        f"# Capability-Audit {today} (Tag {_life_day()})\n\n"
        f"*Mission-bezogene Selbst-Reflexion. Was kann ich, was nicht, was brauche ich.*\n\n"
        f"---\n\n{text}\n",
        encoding='utf-8'
    )

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': _now(), 'date': today,
                              'life_day': _life_day(),
                              'data': data},
                             ensure_ascii=False) + '\n')

    return {'ts': _now(), 'file': str(f), 'life_day': _life_day(),
            'data_summary': {
                'lifetime_pnl': data.get('lifetime',{}).get('pnl_total'),
                'lifetime_n': data.get('lifetime',{}).get('total'),
                'calibration_brier': data.get('calibration',{}).get('brier'),
                'lessons': data.get('permanent_lessons'),
                'active_strategies': data.get('strategies',{}).get('active'),
            }}


def main() -> int:
    r = run()
    if 'error' in r:
        print(f'Error: {r["error"]}'); return 1
    print(f'═══ Capability-Audit @ Tag {r["life_day"]} ═══')
    print(f'  File: {r["file"]}')
    print(f'  Data: {r["data_summary"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
