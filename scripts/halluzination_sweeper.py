#!/usr/bin/env python3
"""
halluzination_sweeper.py — Phase 44ad: Aktive Halluzinations-Suche.

User-Direktive (Victor 03.05): 'CEO soll IMMER nach Halluzinationen suchen.'

Detector wird in call_llm bereits bei jedem Output ausgefuehrt. Dieser
Sweeper geht zusaetzlich aktiv durch RECENT LLM-OUTPUTS aus jsonl-Logs
und scant sie. Findet Halluzinationen die im Hot-Path uebersehen wurden
(z.B. wenn Detector zur Output-Zeit noch nicht aktiv war oder fehlte).

Quellen:
- data/news_reactor_log.jsonl
- data/ceo_action_log.jsonl
- data/ceo_self_research_log.jsonl
- data/ceo_capability_log.jsonl
- data/ceo_active_loop.jsonl
- data/macro_stop_decisions.jsonl

Output:
- data/halluzination_sweep_report.jsonl (aggregiert pro Sweep)
- Bei HIGH-Severity (>= 3 Halluzinationen in 30min): Discord-Push HIGH

Run: python3 scripts/halluzination_sweeper.py
"""
from __future__ import annotations
import json, os, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

LOGS_TO_SCAN = [
    'news_reactor_log.jsonl',
    'ceo_action_log.jsonl',
    'ceo_self_research_log.jsonl',
    'ceo_capability_log.jsonl',
    'ceo_active_loop.jsonl',
    'macro_stop_decisions.jsonl',
    'fact_audit_log.jsonl',
    # Phase 45l: CLI-Claude-Outputs (Stop-Hook audit_cli_response.py)
    'cli_audit_violations.jsonl',
]
SWEEP_REPORT = WS / 'data' / 'halluzination_sweep_report.jsonl'
LAST_SWEEP_STATE = WS / 'data' / 'halluzination_sweep_state.json'


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if LAST_SWEEP_STATE.exists():
        try: return json.loads(LAST_SWEEP_STATE.read_text(encoding='utf-8'))
        except Exception: pass
    return {'last_offsets': {}}


def _save_state(s: dict) -> None:
    LAST_SWEEP_STATE.parent.mkdir(parents=True, exist_ok=True)
    LAST_SWEEP_STATE.write_text(json.dumps(s, indent=2), encoding='utf-8')


def _extract_text_from_record(rec: dict) -> str:
    """Extrahiert relevante Text-Felder aus einem jsonl-Record."""
    parts = []
    for k in ('text','answer','reasoning','message','what','why',
              'observation','action','answer','obs','question','thesis',
              'reason','summary'):
        v = rec.get(k)
        if isinstance(v, str): parts.append(v)
        elif isinstance(v, dict):
            for sk, sv in v.items():
                if isinstance(sv, str): parts.append(sv)
    # Geschachtelte qa, eval, decision
    for nested in ('qa','eval','decision','reviews','actions'):
        nv = rec.get(nested)
        if isinstance(nv, list):
            for item in nv:
                if isinstance(item, dict):
                    parts.append(_extract_text_from_record(item))
                elif isinstance(item, str):
                    parts.append(item)
        elif isinstance(nv, dict):
            parts.append(_extract_text_from_record(nv))
    return '\n'.join(parts)


def run() -> dict:
    state = _load_state()
    try:
        from halluzination_detector import check_halluzinations
    except Exception as e:
        return {'error': f'detector_import_fail: {e}'}

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    findings = []

    for fname in LOGS_TO_SCAN:
        path = WS / 'data' / fname
        if not path.exists(): continue

        # Read inkrementell ab letztem Offset
        last_offset = state.get('last_offsets', {}).get(fname, 0)
        try:
            with open(path, encoding='utf-8') as f:
                f.seek(last_offset)
                new_lines = f.readlines()
                state.setdefault('last_offsets', {})[fname] = f.tell()
        except Exception:
            continue

        for line in new_lines[-100:]:  # max 100 neueste
            try:
                rec = json.loads(line)
                # Skip wenn aelter als 30min
                ts_str = rec.get('ts','') or rec.get('timestamp','')
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace('Z','+00:00'))
                        if ts < cutoff: continue
                    except Exception: pass

                text = _extract_text_from_record(rec)
                if not text or len(text) < 20: continue

                hr = check_halluzinations(text, context=f'sweep_{fname}')
                if hr.has_violations:
                    findings.append({
                        'source_file': fname, 'record_ts': ts_str,
                        'n_violations': len(hr.violations),
                        'violations': hr.violations[:3],
                    })
            except Exception: pass

    _save_state(state)

    # Aggregiert
    total_violations = sum(f['n_violations'] for f in findings)
    by_kind = Counter()
    by_source = Counter()
    for f in findings:
        by_source[f['source_file']] += f['n_violations']
        for v in f.get('violations', []):
            by_kind[v.get('kind','unknown')] += 1

    SWEEP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(SWEEP_REPORT, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': _now(),
            'total_violations': total_violations,
            'by_kind': dict(by_kind),
            'by_source': dict(by_source),
            'findings_sample': findings[:5],
        }, ensure_ascii=False) + '\n')

    # Discord nur bei HIGH (>=3 Halluzinationen)
    if total_violations >= 3:
        try:
            from discord_dispatcher import send_alert, TIER_HIGH
            lines = [f'🚨 **Halluzinations-Sweep ALARM** — {total_violations} Verstoesse in 30min']
            lines.append('Quellen:')
            for src, n in by_source.most_common(5):
                lines.append(f'  · {src}: {n}')
            lines.append('Typen:')
            for k, n in by_kind.most_common():
                lines.append(f'  · {k}: {n}')
            # Phase 45af: detector_finding → SILENT → ceo_inbox (kein Discord)
            send_alert('\n'.join(lines)[:1900], tier=TIER_HIGH,
                        category='detector_finding',
                        dedupe_key=f'halluz_sweep_{datetime.now().strftime("%Y%m%d_%H")}')
        except Exception: pass

    return {'ts': _now(),
            'scanned_files': len(LOGS_TO_SCAN),
            'total_violations': total_violations,
            'by_kind': dict(by_kind),
            'by_source': dict(by_source)}


def main() -> int:
    r = run()
    print(f'═══ Halluzinations-Sweep @ {r["ts"][:16]} ═══')
    print(f'  Total violations (30min): {r.get("total_violations",0)}')
    if r.get('by_source'):
        print(f'  By source: {r["by_source"]}')
    if r.get('by_kind'):
        print(f'  By kind:   {r["by_kind"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
