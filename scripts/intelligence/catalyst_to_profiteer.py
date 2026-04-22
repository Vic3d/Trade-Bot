#!/usr/bin/env python3
"""
Catalyst-to-Profiteer Engine — Phase 23
========================================
Liest die letzten 24h aus news_events, matched gegen SIGNAL_MAP,
schreibt Treffer in data/catalyst_signals.json und füttert
candidate_tickers.json (für Auto-Deep-Dive Pipeline).

Output:
  data/catalyst_signals.json  — Audit-Trail aller Treffer (90 Tage rolling)
  candidate_tickers.json      — neue Tickers mit source='catalyst_<rule_id>'

Discord:
  HIGH-Confidence-Signale → MEDIUM-Queue (4x täglich gebündelt)

Logik:
  1. Hole news_events der letzten WINDOW_HOURS (default 24h)
  2. Für jede Headline: prüfe alle SIGNAL_MAP Regeln
     - Match = mind. 1 Keyword in Headline (case-insensitive)
     - direction_up Match → BULLISH HIGH
     - direction_down Match → BEARISH HIGH
     - kein Modifier → base_confidence ('medium' oder 'high')
  3. Dedup: gleiche (rule_id, headline) nur 1x
  4. Bei BULLISH+HIGH → tickers in candidate_tickers.json
     Bei BEARISH+HIGH → short_tickers in candidate_tickers.json (mit Markierung)

CLI:
  python3 scripts/intelligence/catalyst_to_profiteer.py
  python3 scripts/intelligence/catalyst_to_profiteer.py --hours 48 --dry
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))

from signal_map import SIGNAL_MAP  # noqa: E402

try:
    from candidates import add_candidate, is_new_ticker  # noqa: E402
except Exception:
    add_candidate = None
    is_new_ticker = None

try:
    from discord_queue import queue_event  # noqa: E402
except Exception:
    queue_event = None

DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'catalyst_signals.json'

WINDOW_HOURS = 24
KEEP_DAYS = 90
SCORE_HIGH = 0.85
SCORE_MEDIUM = 0.60


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_existing() -> list[dict]:
    if not OUT.exists():
        return []
    try:
        return json.loads(OUT.read_text(encoding='utf-8'))
    except Exception:
        return []


def _save(signals: list[dict]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    pruned = [s for s in signals if s.get('detected_at', '') >= cutoff]
    OUT.write_text(json.dumps(pruned, indent=2, ensure_ascii=False), encoding='utf-8')


def _signature(rule_id: str, headline: str) -> str:
    """Dedup-Key: gleiche Regel + gleiche Headline = ein Signal."""
    return f"{rule_id}::{headline[:100].lower().strip()}"


def _fetch_recent_news(hours: int) -> list[dict]:
    if not DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row
        cutoff = f"-{hours} hours"
        rows = conn.execute(
            "SELECT id, headline, source, published_at, sentiment_score "
            "FROM news_events "
            "WHERE published_at >= datetime('now', ?) "
            "ORDER BY published_at DESC",
            (cutoff,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f'[catalyst] DB read fail: {e}')
        return []


# ── Matching ─────────────────────────────────────────────────────────────────

def match_rule(headline: str, rule: dict) -> dict | None:
    """
    Prüft ob eine Headline ein Mapping triggert.
    Returns dict mit direction/confidence oder None.
    """
    hl = headline.lower()

    # Keyword-Match (mind. 1)
    matched_kw = None
    for kw in rule.get('keywords', []):
        if kw.lower() in hl:
            matched_kw = kw
            break
    if not matched_kw:
        return None

    # Direction-Modifier
    for d in rule.get('direction_up', []):
        if d.lower() in hl:
            return {'direction': 'BULLISH', 'confidence': 'high', 'modifier': d}
    for d in rule.get('direction_down', []):
        if d.lower() in hl:
            return {'direction': 'BEARISH', 'confidence': 'high', 'modifier': d}

    # Kein Modifier → base_confidence + UNCLEAR direction
    base = rule.get('base_confidence', 'medium')
    return {'direction': 'UNCLEAR', 'confidence': base, 'modifier': None}


def detect_signals(news: list[dict]) -> list[dict]:
    """Gibt liste neuer Signale zurück (deduped)."""
    existing = _load_existing()
    seen = {_signature(s.get('rule_id', ''), s.get('headline', '')) for s in existing}

    new_signals: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for n in news:
        headline = n.get('headline', '') or ''
        if len(headline) < 10:
            continue

        for rule in SIGNAL_MAP:
            m = match_rule(headline, rule)
            if not m:
                continue

            sig_key = _signature(rule['id'], headline)
            if sig_key in seen:
                continue
            seen.add(sig_key)

            # Score: high → 0.85, medium → 0.60
            score = SCORE_HIGH if m['confidence'] == 'high' else SCORE_MEDIUM

            sig = {
                'rule_id': rule['id'],
                'sector': rule['sector'],
                'tickers': rule.get('tickers', []),
                'short_tickers': rule.get('short_tickers', []),
                'direction': m['direction'],
                'confidence': m['confidence'],
                'modifier': m['modifier'],
                'headline': headline,
                'source': n.get('source', ''),
                'news_published': n.get('published_at', ''),
                'news_id': n.get('id'),
                'detected_at': now_iso,
                'score': score,
                'note': rule.get('note', ''),
            }
            new_signals.append(sig)
            break  # Pro Headline max 1 Regel matchen (der erste Treffer gewinnt)

    return new_signals


# ── Output: Candidate Pipeline ───────────────────────────────────────────────

def feed_candidates(signals: list[dict], dry: bool = False) -> int:
    """Schreibt Tickers in candidate_tickers.json. Returns # added."""
    if dry or add_candidate is None:
        return 0
    added = 0
    for s in signals:
        if s['confidence'] != 'high':
            continue  # Nur HIGH triggert Auto-DD
        if s['direction'] == 'BULLISH':
            target_tickers = s.get('tickers', [])
            tag_prefix = 'catalyst'
        elif s['direction'] == 'BEARISH':
            target_tickers = s.get('short_tickers', [])
            tag_prefix = 'catalyst_short'
        else:
            continue
        for tk in target_tickers:
            try:
                ok = add_candidate(
                    tk,
                    f'{tag_prefix}_{s["rule_id"]}',
                    f'{s["sector"]} | {s["headline"][:120]}',
                    score=s['score'],
                )
                if ok:
                    added += 1
            except Exception:
                pass
    return added


# ── Output: Discord Notification ─────────────────────────────────────────────

def notify_discord(signals: list[dict]) -> None:
    if not signals or queue_event is None:
        return
    high = [s for s in signals if s['confidence'] == 'high']
    if not high:
        return
    body = ''
    for s in high[:8]:
        arrow = '📈' if s['direction'] == 'BULLISH' else ('📉' if s['direction'] == 'BEARISH' else '❓')
        tickers = ', '.join((s.get('tickers') or s.get('short_tickers') or [])[:5]) or '—'
        body += f'\n{arrow} **{s["sector"]}** ({tickers})\n'
        body += f'   {s["headline"][:120]}\n'
        if s.get('modifier'):
            body += f'   Trigger: "{s["modifier"]}"\n'
    if len(high) > 8:
        body += f'\n… und {len(high)-8} weitere Signale'
    try:
        queue_event(
            priority='medium',
            title=f'Catalyst-Signale: {len(high)} HIGH-Confidence',
            body=body,
            source='catalyst_to_profiteer',
        )
    except Exception as e:
        print(f'[catalyst] discord queue fail: {e}')


# ── Main ─────────────────────────────────────────────────────────────────────

def run(hours: int = WINDOW_HOURS, dry: bool = False) -> dict:
    print(f'── Catalyst-to-Profiteer ({hours}h Fenster) ──')
    news = _fetch_recent_news(hours)
    print(f'News-Pool: {len(news)} Headlines')

    if not news:
        return {'news': 0, 'signals': 0, 'candidates_added': 0}

    new_signals = detect_signals(news)
    print(f'Neue Signale: {len(new_signals)}')

    by_conf = {}
    for s in new_signals:
        by_conf[s['confidence']] = by_conf.get(s['confidence'], 0) + 1
    if by_conf:
        print(f'  Verteilung: {by_conf}')

    # Sample-Output
    for s in new_signals[:5]:
        arrow = '↑' if s['direction'] == 'BULLISH' else ('↓' if s['direction'] == 'BEARISH' else '?')
        tickers = ','.join((s.get('tickers') or s.get('short_tickers') or [])[:3])
        print(f'  {arrow} [{s["confidence"]:6}] {s["sector"][:25]:25} → {tickers:25} | {s["headline"][:60]}')

    if not dry and new_signals:
        existing = _load_existing()
        existing.extend(new_signals)
        _save(existing)

    cand_added = feed_candidates(new_signals, dry=dry)
    print(f'Neue Candidates: {cand_added}')

    if not dry:
        notify_discord(new_signals)

    return {
        'news': len(news),
        'signals': len(new_signals),
        'candidates_added': cand_added,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=WINDOW_HOURS)
    ap.add_argument('--dry', action='store_true', help='Keine DB/Disk-Writes')
    args = ap.parse_args()
    r = run(hours=args.hours, dry=args.dry)
    print(f'\n✅ done: {r}')


if __name__ == '__main__':
    main()
