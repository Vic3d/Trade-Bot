#!/usr/bin/env python3
"""
fact_audit.py — Phase 44b: Fact-Audit-Layer (Regel #0 enforcement im System).

Vor jeder LLM-Decision-Execution wird hier geprüft:
  1. Sind die nötigen Fakten vorhanden (live_price, strategy_stats, etc.)?
  2. Enthält das reasoning Speculation-Phrasen ('vermutlich', 'könnte', etc.)?

Bei Mismatch: Decision wird auf WATCH degradiert + Audit-Log.

Im Gegensatz zu Regel #0 in Sessions: hier wird die Regel SYSTEM-SEITIG
durchgesetzt — selbst wenn der LLM-Output spekuliert, kommt der Trade
nicht durch.

Usage:
  from fact_audit import audit_decision
  result = audit_decision(decision_dict, required_facts=['live_price', 'strategy_n_trades'])
  if result.status == 'BLOCK':
      decision['action'] = 'WATCH'
      decision['blocked_by_audit'] = result.reason
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
AUDIT_LOG = WS / 'data' / 'fact_audit_log.jsonl'

# Verbotene Phrasen — wenn diese in reasoning auftauchen ohne Fakten-Backing,
# ist die Decision spekulativ
BANNED_PHRASES = [
    # Hedge-Wörter
    r'\bvermutlich\b', r'\bwahrscheinlich\b', r'\btendenziell\b',
    r'\büblicherweise\b', r'\bin der regel\b',
    r'\bgrob\b', r'\bca\.\s', r'\bungefähr\b', r'\betwa\s',
    r'\bich schätze\b', r'\bich denke\b',
    r'\bmöglicherweise\b',
    # Schein-Empirie
    r'historisch\s*[~≈]\s*\d',          # "historisch ~30%"
    r'historisch\s+\d+\s*[-–]\s*\d',    # "historisch 60-70%"
    r'\bempirisch belegt\b',
    r'\bforschung zeigt\b',
    r'\bprofis machen\b',
    r'\bquants nutzen\b',
    # Bandbreiten ohne Quelle
    r'sharpe\s*[~≈]\s*\d',
    r'sharpe\s+\d+\s*[-–]\s*\d',
    r'wr\s*[~≈]\s*\d',
    r'wr\s+\d+\s*[-–]\s*\d',
    # Schwächere Hedges (nur wenn ohne fakten-feld)
    r'\bkönnte\s+(zu|x|ein|den)',
    r'\bdürfte\b',
    r'\bsollte\s+(zu|den|ein)',
]

# Kompiliere für Performance
_BANNED_RE = [re.compile(p, re.IGNORECASE) for p in BANNED_PHRASES]


@dataclass
class AuditResult:
    status:         str   # 'PASS' | 'BLOCK' | 'WARN'
    reason:         str
    speculation:    list  # gefundene verbotene Phrasen
    missing_facts:  list  # fehlende required facts


def _detect_speculation(text: str) -> list[str]:
    """Finde verbotene Phrasen in Text."""
    if not text:
        return []
    found = []
    for pat in _BANNED_RE:
        m = pat.search(text)
        if m:
            found.append(m.group(0))
    return found


def _check_required_facts(decision: dict, required_facts: list[str]) -> list[str]:
    """Prüfe ob alle required facts im decision-dict vorhanden sind.

    Akzeptiert sowohl 'facts' Sub-Field als auch direkte Felder.
    """
    facts = decision.get('facts', {}) or {}
    missing = []
    for f in required_facts:
        # Prüfe in facts und auf Top-Level
        if f not in facts and f not in decision:
            missing.append(f)
        else:
            v = facts.get(f, decision.get(f))
            if v is None:
                missing.append(f'{f}=null')
    return missing


def audit_decision(decision: dict,
                     required_facts: list[str] | None = None,
                     log: bool = True) -> AuditResult:
    """Pflicht-Audit vor execute.

    Args:
      decision: dict mit 'action', 'reason', 'reasoning', 'ticker', 'facts'
      required_facts: liste an Pflicht-Fakten. Default: minimal sinnvolle.

    Returns: AuditResult
    """
    if required_facts is None:
        # Minimal-Set für Trade-Decisions
        required_facts = []  # konservativ: erstmal nur Speculation-Check, Fact-Check optional

    # 1. Speculation-Check in reasoning
    reasoning_text = ' '.join(filter(None, [
        decision.get('reason', ''),
        decision.get('reasoning', ''),
        decision.get('bull_case', ''),
        decision.get('bear_case', ''),
    ]))
    spec = _detect_speculation(reasoning_text)

    # 2. Required-Facts-Check
    missing = _check_required_facts(decision, required_facts) if required_facts else []

    # 3. Verdict
    if spec:
        result = AuditResult(
            status='BLOCK',
            reason=f'speculation_phrases: {spec[:5]}',
            speculation=spec, missing_facts=missing,
        )
    elif missing:
        result = AuditResult(
            status='BLOCK',
            reason=f'missing_facts: {missing}',
            speculation=spec, missing_facts=missing,
        )
    else:
        result = AuditResult(status='PASS', reason='clean',
                              speculation=[], missing_facts=[])

    if log:
        _write_audit_log(decision, result)
    return result


def _write_audit_log(decision: dict, result: AuditResult) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        'ts':            datetime.now(timezone.utc).isoformat(),
        'ticker':        decision.get('ticker', '?'),
        'strategy':      decision.get('strategy', '?'),
        'action':        decision.get('action', '?'),
        'audit_status':  result.status,
        'audit_reason':  result.reason,
        'speculation':   result.speculation,
        'missing_facts': result.missing_facts,
    }
    try:
        with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def get_audit_summary(hours: int = 24) -> dict:
    """Zusammenfassung der letzten Audit-Aktivität."""
    if not AUDIT_LOG.exists():
        return {'total': 0, 'window_hours': hours}
    from collections import Counter
    cutoff = (datetime.now(timezone.utc).timestamp() - hours * 3600)
    by_status = Counter()
    by_reason = Counter()
    total = 0
    try:
        with open(AUDIT_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = datetime.fromisoformat(e.get('ts', '').replace('Z', '+00:00'))
                    if ts.timestamp() < cutoff:
                        continue
                except Exception:
                    continue
                total += 1
                by_status[e.get('audit_status', '?')] += 1
                if e.get('audit_status') == 'BLOCK':
                    by_reason[e.get('audit_reason', '?')[:60]] += 1
    except Exception:
        pass
    return {
        'total':          total,
        'window_hours':   hours,
        'by_status':      dict(by_status),
        'top_block_reasons': dict(by_reason.most_common(10)),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--test', action='store_true', help='Test mit Beispiel-Decisions')
    args = ap.parse_args()

    if args.summary:
        print(json.dumps(get_audit_summary(), indent=2))
        return 0

    if args.test:
        # Test-Decisions
        examples = [
            {'ticker': 'TEST1', 'action': 'EXECUTE',
             'reason': 'Vermutlich gute Idee, Sharpe ~0.7 historisch'},
            {'ticker': 'TEST2', 'action': 'EXECUTE',
             'reason': 'PS1 hat 12 Trades, WR 56%, conv 0.65'},
            {'ticker': 'TEST3', 'action': 'EXECUTE',
             'reason': 'Forschung zeigt empirisch belegt'},
        ]
        for d in examples:
            r = audit_decision(d, log=False)
            icon = '✅' if r.status == 'PASS' else '🔴'
            print(f"{icon} {d['ticker']}: {r.status} — {r.reason}")
        return 0

    print('Usage: --summary | --test')
    return 1


if __name__ == '__main__':
    sys.exit(main())
