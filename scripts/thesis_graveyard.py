#!/usr/bin/env python3
"""
Thesis Graveyard — Phase 22
=============================
Tracked jede abgelehnte These (NICHT_KAUFEN / WARTEN / rejected candidate)
und prueft nach 14/30 Tagen ob wir Recht hatten.

Datenbasis:
  - data/deep_dive_verdicts.json  (NICHT_KAUFEN, WARTEN Verdicts)
  - data/candidate_tickers.json   (rejected/expired Kandidaten)
  - data/generated_theses.jsonl   (nicht promotete Thesen)

Output:
  data/thesis_graveyard.json mit Eintraegen:
  {
    "ticker": "XYZ",
    "rejected_at": "<iso>",
    "reason": "<warum abgelehnt>",
    "entry_price_hint": 100.00,
    "thesis_summary": "<2 saetze>",
    "checks": [
      {"days": 14, "price_then": 95.0, "return_pct": -5.0, "would_have_won": false}
    ]
  }

CLI:
  python3 scripts/thesis_graveyard.py                 # Neue Eintraege anlegen + alte checken
  python3 scripts/thesis_graveyard.py --report         # Zusammenfassung
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
VERDICTS = WS / 'data' / 'deep_dive_verdicts.json'
CANDS = WS / 'data' / 'candidate_tickers.json'
GRAVE = WS / 'data' / 'thesis_graveyard.json'

sys.path.insert(0, str(WS / 'scripts'))


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
    except Exception:
        return default


def _save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def _get_price(ticker: str) -> float | None:
    try:
        import yfinance as yf
        d = yf.download(ticker, period='2d', progress=False, auto_adjust=True)
        if d is None or d.empty:
            return None
        return float(d['Close'].iloc[-1])
    except Exception:
        return None


def ingest_rejections() -> int:
    """Neue Rejections aus Verdicts + Candidates ins Graveyard."""
    grave = _load_json(GRAVE, {})
    added = 0

    # 1. Deep-Dive Verdicts: NICHT_KAUFEN / WARTEN
    verdicts = _load_json(VERDICTS, {})
    for tk, v in verdicts.items():
        final = v.get('final_verdict') or v.get('verdict') or ''
        if final not in ('NICHT_KAUFEN', 'WARTEN'):
            continue
        key = f"{tk}:{v.get('timestamp', v.get('analyzed_at',''))[:10]}"
        if key in grave:
            continue
        grave[key] = {
            'ticker': tk,
            'rejected_at': v.get('timestamp') or v.get('analyzed_at') or datetime.now(timezone.utc).isoformat(),
            'reason': f"DD-Verdict: {final}",
            'source': 'deep_dive',
            'entry_price_hint': v.get('entry_price_hint') or v.get('current_price'),
            'thesis_summary': (v.get('thesis_summary') or v.get('summary') or '')[:240],
            'checks': [],
        }
        added += 1

    # 2. Expired/rejected Candidates
    cands = _load_json(CANDS, {})
    for tk, c in cands.items():
        if c.get('status') not in ('rejected', 'expired'):
            continue
        key = f"{tk}:cand:{c.get('last_seen_at','')[:10]}"
        if key in grave:
            continue
        grave[key] = {
            'ticker': tk,
            'rejected_at': c.get('last_seen_at') or datetime.now(timezone.utc).isoformat(),
            'reason': f"Candidate {c.get('status')}",
            'source': 'candidate',
            'entry_price_hint': None,
            'thesis_summary': '; '.join(s.get('detail','')[:80] for s in c.get('sources', [])[-2:]),
            'checks': [],
        }
        added += 1

    _save_json(GRAVE, grave)
    return added


def check_old_rejections() -> int:
    """Preis-Check 14d + 30d nach Rejection."""
    grave = _load_json(GRAVE, {})
    now = datetime.now(timezone.utc)
    checked = 0

    for key, e in grave.items():
        try:
            rej = datetime.fromisoformat(e['rejected_at'].replace('Z','+00:00'))
        except Exception:
            continue
        age_days = (now - rej).days
        done_checks = {c['days'] for c in e.get('checks', [])}

        for window in (14, 30):
            if window in done_checks:
                continue
            if age_days < window:
                continue
            entry_hint = e.get('entry_price_hint')
            now_price = _get_price(e['ticker'])
            if not now_price:
                continue
            ret_pct = None
            if entry_hint:
                try:
                    ret_pct = (now_price / float(entry_hint) - 1) * 100
                except Exception:
                    pass
            e.setdefault('checks', []).append({
                'days': window,
                'checked_at': now.isoformat(timespec='seconds'),
                'price_then': round(now_price, 2),
                'return_pct': round(ret_pct, 2) if ret_pct is not None else None,
                'would_have_won': (ret_pct is not None and ret_pct > 5.0),
            })
            checked += 1

    _save_json(GRAVE, grave)
    return checked


def report() -> dict:
    grave = _load_json(GRAVE, {})
    total = len(grave)
    wins_14 = losses_14 = wins_30 = losses_30 = 0
    missed_opportunities = []

    for key, e in grave.items():
        for c in e.get('checks', []):
            if c.get('return_pct') is None:
                continue
            if c['days'] == 14:
                if c['would_have_won']: wins_14 += 1
                else: losses_14 += 1
            if c['days'] == 30:
                if c['would_have_won']: wins_30 += 1
                else: losses_30 += 1
                if c.get('return_pct', 0) > 10.0:
                    missed_opportunities.append({
                        'ticker': e['ticker'],
                        'return_30d': c['return_pct'],
                        'reason': e.get('reason',''),
                    })

    missed_opportunities.sort(key=lambda x: -x['return_30d'])
    total_14 = wins_14 + losses_14
    total_30 = wins_30 + losses_30
    return {
        'total_rejections': total,
        'accuracy_14d': round(losses_14 / total_14 * 100, 1) if total_14 else None,
        'accuracy_30d': round(losses_30 / total_30 * 100, 1) if total_30 else None,
        'would_have_won_14d': wins_14,
        'would_have_won_30d': wins_30,
        'top_missed_opportunities': missed_opportunities[:10],
    }


def build_calibration_block(max_missed: int = 3) -> str:
    """
    Generiert einen Prompt-Block fuer den Auto-DD-Claude-Aufruf.
    Teilt Claude mit, wie gut/schlecht seine bisherigen Rejections waren
    und zwingt ihn zur Re-Kalibrierung.

    Returns empty string wenn noch keine Alt-Checks vorhanden sind.
    """
    r = report()
    acc_30 = r.get('accuracy_30d')
    acc_14 = r.get('accuracy_14d')
    missed = r.get('top_missed_opportunities', [])[:max_missed]

    if acc_30 is None and acc_14 is None:
        return ''  # Noch keine Datenbasis

    lines = ['\n### KALIBRIERUNG (aus Thesis-Graveyard)']
    if acc_30 is not None:
        lines.append(f"Deine 30d-Ablehn-Accuracy: **{acc_30}%** "
                     f"(= {100-acc_30:.0f}% der abgelehnten Thesen haetten gewonnen > +5%)")
    if acc_14 is not None:
        lines.append(f"Deine 14d-Ablehn-Accuracy: **{acc_14}%**")

    # Verhaltens-Anweisung basierend auf Accuracy
    if acc_30 is not None:
        if acc_30 < 50:
            lines.append(
                "\n⚠️ WARNSIGNAL: Du bist ZU KONSERVATIV. Mehr als die Haelfte deiner "
                "Ablehnungen haette Geld gemacht. BEVORZUGE im Zweifel KAUFEN gegenueber "
                "WARTEN. Senke die mentale EV-Schwelle um ~20%."
            )
        elif acc_30 > 80:
            lines.append(
                "\n✅ Dein Filter ist gut kalibriert. Bleib diszipliniert — NICHT laxer werden."
            )
        else:
            lines.append(
                "\nDein Filter ist okay kalibriert. Kein systematisches Tuning noetig."
            )

    if missed:
        lines.append("\nTop verpasste Chancen (was du faelschlich abgelehnt hast):")
        for m in missed:
            lines.append(f"  - {m['ticker']}: +{m['return_30d']:.1f}% in 30d (Grund war: {m.get('reason','?')[:60]})")
        lines.append(
            "→ Lerne aus dem Muster: Waren diese abgelehnten Kandidaten alle aus demselben "
            "Sektor/Setup-Typ? Dann ist dort dein Filter zu streng."
        )

    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    if args.report:
        r = report()
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return
    added = ingest_rejections()
    checked = check_old_rejections()
    print(f"[graveyard] {added} neue Eintraege, {checked} Alt-Checks")
    r = report()
    print(f"[graveyard] Total: {r['total_rejections']}, "
          f"Accuracy 14d: {r.get('accuracy_14d')}%, 30d: {r.get('accuracy_30d')}%")
    if r['top_missed_opportunities']:
        print(f"[graveyard] ⚠️  Top verpasste Chancen (30d):")
        for m in r['top_missed_opportunities'][:3]:
            print(f"   - {m['ticker']}: +{m['return_30d']:.1f}%  ({m['reason']})")


if __name__ == '__main__':
    main()
