#!/usr/bin/env python3
"""
albert_improvement_digest.py — Phase 45ay (Victor 2026-05-14).

Täglich 10:00 — KURZE Discord-Zusammenfassung von Albert's Verbesserungs-
vorschlägen. Victor liest, sagt was Deep-Dive wert ist, Claude-CLI prüft + setzt um.

Sammelt:
  - Capability-Requests (PENDING) — strukturelle Vorschläge
  - Neue Self-Rules (letzte 24h)
  - CEO-Self-Audit-Findings (wenn neu)
  - Compliance-Rate (letzte 24h) — wie oft hält Albert eigene Regeln

Output: KURZ. Max ~15 Zeilen. Jeder Vorschlag 1-2 Zeilen. Keine Romane.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

CAP_FILE = WS / 'data' / 'albert_capability_requests.jsonl'
RULES_FILE = WS / 'memory' / 'albert_self_rules.md'
AUDIT_FILE = WS / 'data' / 'ceo_self_audit_latest.md'
COMPLIANCE_LOG = WS / 'data' / 'compliance_log.jsonl'


def _pending_capability_requests() -> list[dict]:
    if not CAP_FILE.exists(): return []
    out = []
    try:
        with open(CAP_FILE, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('status') == 'PENDING_REVIEW':
                        out.append(e)
                except Exception: pass
    except Exception: pass
    return out[-6:]  # max 6


def _recently_implemented_capabilities(days: int = 7) -> list[dict]:
    """Phase 45bh: Was wurde umgesetzt? Damit Albert nicht wiederholt vorschlägt.
    Zeigt nur Requests mit status=IMPLEMENTED + implemented_at <= N Tage alt."""
    if not CAP_FILE.exists(): return []
    cutoff = (datetime.now(timezone.utc).date()
              - timedelta(days=days)).isoformat()
    out = []
    try:
        with open(CAP_FILE, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if (e.get('status') == 'IMPLEMENTED'
                            and e.get('implemented_at', '') >= cutoff):
                        out.append(e)
                except Exception: pass
    except Exception: pass
    return out


def _compliance_24h() -> dict:
    if not COMPLIANCE_LOG.exists(): return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    total = first_ok = retried_ok = failed = 0
    try:
        with open(COMPLIANCE_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('ts', '') < cutoff: continue
                    total += 1
                    if e.get('retries', 0) == 0 and e.get('compliant'): first_ok += 1
                    elif e.get('compliant'): retried_ok += 1
                    else: failed += 1
                except Exception: pass
    except Exception: pass
    return {'total': total, 'first_ok': first_ok,
            'retried_ok': retried_ok, 'failed': failed}


def _new_self_rules_24h() -> str:
    """Self-Rules-File, nur wenn in letzten 24h aktualisiert."""
    if not RULES_FILE.exists(): return ''
    import time
    if (time.time() - RULES_FILE.stat().st_mtime) > 86400:
        return ''
    try:
        txt = RULES_FILE.read_text(encoding='utf-8')
        # Nur den "Neue Selbst-Regeln" Abschnitt
        if 'Neue Selbst-Regeln' in txt or 'NEUE' in txt.upper():
            return txt[-1500:]
        return txt[-800:]
    except Exception: return ''


def _audit_findings() -> str:
    """Letzte CEO-Self-Audit-Findings wenn frisch (< 48h)."""
    if not AUDIT_FILE.exists(): return ''
    import time
    if (time.time() - AUDIT_FILE.stat().st_mtime) > 172800:  # 48h
        return ''
    try:
        return AUDIT_FILE.read_text(encoding='utf-8')[:2000]
    except Exception: return ''


def build_digest() -> str:
    now = datetime.now()
    caps = _pending_capability_requests()
    done = _recently_implemented_capabilities(days=7)
    compliance = _compliance_24h()
    new_rules = _new_self_rules_24h()
    audit = _audit_findings()

    # Rohdaten sammeln für LLM-Komprimierung
    raw = []
    if done:
        raw.append("BEREITS UMGESETZT (letzte 7d) — NICHT WIEDER VORSCHLAGEN:")
        for d in done:
            raw.append(f"  ✓ {d.get('title','?')} ({d.get('implemented_phase','?')}, "
                       f"{d.get('implemented_at','?')}): "
                       f"{d.get('implementation_ref','')[:120]}")
    if caps:
        raw.append("CAPABILITY-REQUESTS (Albert will Architektur-Änderung):")
        for c in caps:
            raw.append(f"  [{c.get('prioritaet','?')}] {c.get('title','?')}: "
                       f"{c.get('problem','')[:150]} → {c.get('vorschlag','')[:150]}")
    if compliance.get('total', 0) > 0:
        t = compliance
        raw.append(f"COMPLIANCE 24h: {t['first_ok']}/{t['total']} sofort ok, "
                   f"{t['retried_ok']} nach Retry, {t['failed']} aufgegeben")
    if new_rules:
        raw.append(f"NEUE SELF-RULES (24h):\n{new_rules}")
    if audit:
        raw.append(f"CEO-SELF-AUDIT:\n{audit}")

    if not raw:
        return ('🔧 **ALBERT VERBESSERUNGS-DIGEST** ' + now.strftime('%d.%m.%Y') +
                '\n\nKeine neuen Vorschläge oder Findings in den letzten 24h.')

    raw_text = '\n'.join(raw)

    # LLM-Komprimierung — KURZ
    prompt = f"""Du bist ein Redaktions-Filter. Hier sind Albert's (AI-Trader)
Selbst-Analysen und Verbesserungsvorschläge der letzten 24h:

═══ ROHDATEN ═══
{raw_text}

DEINE AUFGABE: Schreibe eine KURZE Discord-Zusammenfassung für Victor.
- Max 15 Zeilen total
- Jeder Vorschlag/Finding: maximal 2 Zeilen (Was + Warum)
- Keine Romane, keine Floskeln, keine Wiederholungen
- Wenn mehrere Findings dasselbe sagen: zusammenfassen
- Priorisiere: Capability-Requests > Compliance-Probleme > neue Regeln
- Am Ende: "→ Antworte 'Deep-Dive [Thema]' für Detail-Analyse"

FORMAT:
🔧 **ALBERT VERBESSERUNGS-DIGEST** {now.strftime('%d.%m.%Y')}

**[Kategorie]:**
• Kurzer Punkt
• Kurzer Punkt

→ Antworte 'Deep-Dive [Thema]' für Detail-Analyse

Schreibe NUR die fertige Zusammenfassung, kein Drumherum."""

    try:
        sys.path.insert(0, str(WS / 'scripts' / 'core'))
        from llm_client import call_llm
        digest, _ = call_llm(prompt, model_hint='sonnet', max_tokens=600)
        return digest.strip()
    except Exception as e:
        # Fallback ohne LLM
        return (f"🔧 **ALBERT VERBESSERUNGS-DIGEST** {now.strftime('%d.%m.%Y')}\n\n"
                + raw_text[:1500])


def main() -> int:
    digest = build_digest()
    print(digest)  # Scheduler pusht stdout an Discord (discord=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
