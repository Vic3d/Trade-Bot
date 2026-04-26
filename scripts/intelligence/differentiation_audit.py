#!/usr/bin/env python3
"""
differentiation_audit.py — Quartalsweiser "Crowded Trade" Audit.

Idee (Phase 27, inspiriert von Erichsen-Vergleich):
Wenn unsere Thesen sich zu stark mit Mainstream-News-Frequenz decken,
sind wir nur "Index plus Latenz" — kein echter Edge.

Vorgehen:
  1. Für jede ACTIVE-Strategie: extrahiere Schlüsselbegriffe aus thesis-Text
  2. Zähle wie oft diese Begriffe in den letzten 30 Tagen in news_events erscheinen
  3. Differenzierungs-Score:
       hoch (>70):  Begriffe selten (<20 Erwähnungen) → echter Edge
       mittel (30-70): Begriffe normal (20-100 Erwähnungen)
       niedrig (<30): Begriffe inflationär (>100) → crowded trade

  4. Output:
     - memory/differentiation-report.md (Markdown-Report)
     - Discord-Push mit Top-3 crowded + Top-3 differentiated
     - Markiert crowded Strategien in strategies.json mit '_crowded': true
       (wird vom paper_trade_engine als Sizing-Halver gelesen)

Schwellen (anpassbar):
  CROWDED_THRESHOLD     = 100  News-Erwähnungen / 30d → score 0
  DIFFERENTIATED_THRESH = 20   → score 100
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
STRATEGIES_FILE = WS / 'data' / 'strategies.json'
REPORT_FILE     = WS / 'memory' / 'differentiation-report.md'

CROWDED_THRESHOLD       = 100
DIFFERENTIATED_THRESHOLD = 20
WINDOW_DAYS              = 30

# Stopwords + Generische Begriffe die nicht als "Edge" zählen
GENERIC_TERMS = {
    'aktie', 'aktien', 'unternehmen', 'firma', 'markt', 'börse', 'analyst',
    'studie', 'bericht', 'prozent', 'mio', 'mrd', 'dollar', 'euro',
    'company', 'stock', 'shares', 'market', 'analyst', 'percent',
    'million', 'billion', 'trillion', 'profit', 'revenue', 'earnings',
    'investor', 'investors', 'price', 'prices', 'high', 'low', 'today',
    'yesterday', 'week', 'month', 'year', 'quarter', 'group', 'corp',
    'inc', 'ltd', 'gmbh', 'plc', 'the', 'and', 'der', 'die', 'das',
    'mit', 'für', 'von', 'auf', 'eine', 'einer', 'wird', 'werden',
    'haben', 'sind', 'kann', 'wenn', 'aber', 'oder', 'auch', 'sich',
}


def _extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
    """Extrahiert die N längsten/distinktivsten Wörter aus thesis-Text."""
    if not text:
        return []
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{5,}\b', text.lower())
    # Dedupe + filter generic
    distinct = []
    seen = set()
    for w in words:
        if w in seen or w in GENERIC_TERMS:
            continue
        seen.add(w)
        distinct.append(w)
    # Sort by length descending, longer = more specific
    distinct.sort(key=lambda w: -len(w))
    return distinct[:max_keywords]


def _count_news_mentions(keywords: list[str], days: int = WINDOW_DAYS) -> dict:
    """Wie oft erscheinen die Keywords in news_events der letzten N Tage?"""
    if not keywords:
        return {}
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    counts = {}
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT headline FROM news_events WHERE created_at >= ? AND headline IS NOT NULL",
            (cutoff,)
        ).fetchall()
        conn.close()
        all_text = ' '.join(r[0].lower() for r in rows if r[0])
        for kw in keywords:
            counts[kw] = all_text.count(kw)
    except Exception as e:
        print(f'[diff-audit] DB-Fehler: {e}', file=sys.stderr)
    return counts


def _score_strategy(thesis: str) -> dict:
    """Returns {score: 0-100, keywords: [...], mentions: {...}, label: str}."""
    keywords = _extract_keywords(thesis)
    mentions = _count_news_mentions(keywords)
    if not mentions:
        return {'score': 50, 'keywords': keywords, 'mentions': {},
                'label': 'unknown', 'avg_mentions': 0}

    avg = sum(mentions.values()) / len(mentions)
    if avg >= CROWDED_THRESHOLD:
        score = 0
    elif avg <= DIFFERENTIATED_THRESHOLD:
        score = 100
    else:
        # Linear interpolation 100→0 over [DIFF, CROWDED]
        ratio = (avg - DIFFERENTIATED_THRESHOLD) / (CROWDED_THRESHOLD - DIFFERENTIATED_THRESHOLD)
        score = int(100 - ratio * 100)

    if score >= 70:
        label = 'differentiated'
    elif score >= 30:
        label = 'mainstream'
    else:
        label = 'crowded'

    return {
        'score': score,
        'keywords': keywords,
        'mentions': mentions,
        'avg_mentions': round(avg, 1),
        'label': label,
    }


def _load_strategies() -> dict:
    if not STRATEGIES_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGIES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_strategies(data: dict) -> None:
    STRATEGIES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _format_report(scores: dict) -> str:
    """Markdown-Report für memory/differentiation-report.md."""
    today = datetime.now().strftime('%Y-%m-%d')
    lines = [f'# Differenzierungs-Audit — {today}', '',
             f'**Fenster:** letzte {WINDOW_DAYS} Tage news_events',
             f'**Strategien analysiert:** {len(scores)}', '']

    by_label = {'differentiated': [], 'mainstream': [], 'crowded': [], 'unknown': []}
    for sid, s in scores.items():
        by_label[s['label']].append((sid, s))

    for label in ('differentiated', 'mainstream', 'crowded', 'unknown'):
        items = by_label[label]
        if not items:
            continue
        items.sort(key=lambda x: -x[1]['score'])
        lines.append(f'\n## {label.upper()} ({len(items)} Strategien)')
        for sid, s in items:
            top_kw = ', '.join(f'{k}({s["mentions"].get(k,0)})' for k in s['keywords'][:4])
            lines.append(f'- **{sid}** | Score {s["score"]} | avg {s["avg_mentions"]} mentions | KW: {top_kw}')

    lines.append('')
    lines.append('---')
    lines.append('_Crowded → Sizing wird halbiert. Differentiated → Conviction-Bonus._')
    return '\n'.join(lines)


def _format_discord(scores: dict) -> str:
    crowded = sorted(
        [(sid, s) for sid, s in scores.items() if s['label'] == 'crowded'],
        key=lambda x: x[1]['avg_mentions'], reverse=True
    )[:3]
    diff = sorted(
        [(sid, s) for sid, s in scores.items() if s['label'] == 'differentiated'],
        key=lambda x: -x[1]['score']
    )[:3]

    lines = [f'🔬 **Differenzierungs-Audit** ({len(scores)} Strategien geprüft)', '']
    if crowded:
        lines.append('🚦 **Crowded Trades** (Mainstream-Themen, Sizing wird halbiert):')
        for sid, s in crowded:
            lines.append(f'  · `{sid}` Score {s["score"]} (avg {s["avg_mentions"]} mentions)')
    if diff:
        lines.append('\n💎 **Echte Differenzierung** (Conviction-Bonus):')
        for sid, s in diff:
            lines.append(f'  · `{sid}` Score {s["score"]} (avg {s["avg_mentions"]} mentions)')

    if not crowded and not diff:
        lines.append('_Alle Strategien im Mainstream-Bereich (Score 30-70)._')

    lines.append('\n_Voller Report: `memory/differentiation-report.md`_')
    return '\n'.join(lines)


def main() -> int:
    strategies = _load_strategies()
    if not strategies:
        print('[diff-audit] Keine Strategien geladen.')
        return 1

    scores = {}
    crowded_ids = []
    for sid, sdata in strategies.items():
        if not isinstance(sdata, dict):
            continue
        if sdata.get('status') not in ('ACTIVE', 'STRENGTHENED'):
            continue
        thesis = sdata.get('thesis') or sdata.get('description') or sdata.get('name') or ''
        if not thesis:
            continue
        score = _score_strategy(thesis)
        scores[sid] = score
        if score['label'] == 'crowded':
            crowded_ids.append(sid)
            sdata['_crowded'] = True
            sdata['_diff_score'] = score['score']
        else:
            # Reset flag wenn nicht mehr crowded
            sdata.pop('_crowded', None)
            sdata['_diff_score'] = score['score']

    # Save flags back
    _save_strategies(strategies)

    # Write report
    report = _format_report(scores)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding='utf-8')
    print(f'[diff-audit] Report: {REPORT_FILE}')
    print(f'[diff-audit] Crowded: {len(crowded_ids)} ({", ".join(crowded_ids[:5])})')

    # Discord
    try:
        from discord_dispatcher import send_alert, TIER_MEDIUM
        send_alert(_format_discord(scores), tier=TIER_MEDIUM, category='diff_audit',
                   dedupe_key=f'diff_audit_{datetime.now().strftime("%Y-Q%q" if False else "%Y-%m")}')
    except Exception as e:
        print(f'[diff-audit] Discord-Send-Fehler: {e}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
