#!/usr/bin/env python3
"""
macro_event_detector.py — Phase 42b: Breaking-Macro-Detector.

Scant news_events der letzten 30min nach Macro-Schock-Patterns.
Bei Match → severity-Klassifikation + Discord-Push + DB-Marker.

Trigger-Bundles (Kombinationen die zusammen feuern müssen):
  ENERGY_SHOCK:    {OPEC, Saudi, exit/cut/raise/freeze}
  FED_SHOCK:       {Fed, rate/cut/hike, surprise/unexpected/emergency}
  TARIFF_SHOCK:    {Trump|Biden|tariff, China|EU|imposed}
  WAR_SHOCK:       {Russia|Iran|Israel, ceasefire/strike/invasion}
  CHINA_SHOCK:     {China, lockdown|stimulus|crash|devaluation}
  PHARMA_SHOCK:    {FDA, approval|rejection|recall, [pharma_ticker]}
  CRYPTO_SHOCK:    {Bitcoin, crash|halt|exchange-fail}

Output:
  - Schreibt severity in news_events.relevance_score (>= 0.95 = CRITICAL)
  - Pusht Critical-Events an Discord via webhook
  - Markiert in commodity_kill_events tabelle (für Auto-Reeval-Trigger)

Run:
  python3 scripts/macro_event_detector.py            # last 30min
  python3 scripts/macro_event_detector.py --hours 6  # last 6h
  python3 scripts/macro_event_detector.py --test     # dry-run, no push
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'

# ═══════════════════════════════════════════════════════════════════════════
# Macro-Event-Bundles — jeweils {required_keywords + at_least_one}
# ═══════════════════════════════════════════════════════════════════════════
EVENT_BUNDLES = {
    'ENERGY_SHOCK': {
        'required':       ['opec', 'saudi'],         # Mindestens 1 davon
        'at_least_one':   ['exit', 'leave', 'cut', 'raise', 'freeze', 'production',
                            'embargo', 'sanction', 'price war', 'surprise'],
        'severity':       'CRITICAL',
        'impact_tickers': ['XOM', 'CVX', 'EQNR.OL', 'TTE.PA', 'BP.L', 'SHEL.L',
                            'OXY', 'COP', 'ENI', 'OMV.VI', 'REP.MC'],
        'sectors':        ['energy', 'oil', 'gas'],
    },
    'FED_SHOCK': {
        'required':       ['fed', 'federal reserve', 'powell', 'fomc'],
        'at_least_one':   ['rate cut', 'rate hike', 'emergency', 'surprise',
                            'unexpected', 'pause', 'unscheduled', 'inflation'],
        'severity':       'CRITICAL',
        'impact_tickers': ['SPY', 'QQQ', 'TLT', 'GLD', 'DXY'],
        'sectors':        ['financial', 'banks', 'real_estate'],
    },
    'TARIFF_SHOCK': {
        'required':       ['tariff', 'trade war', 'trump', 'biden'],
        'at_least_one':   ['china', 'eu', 'imposed', 'announce', 'increase',
                            'retaliate', 'sanction', 'mexico', 'canada'],
        'severity':       'HIGH',
        'impact_tickers': ['AAPL', 'NVDA', 'TSLA', 'KO', 'WMT', 'CAT'],
        'sectors':        ['tech', 'consumer', 'industrials'],
    },
    'WAR_SHOCK': {
        'required':       ['russia', 'ukraine', 'israel', 'iran', 'gaza',
                            'taiwan', 'china military'],
        'at_least_one':   ['ceasefire', 'strike', 'invasion', 'attack',
                            'missile', 'troops', 'war', 'escalation'],
        'severity':       'HIGH',
        'impact_tickers': ['RTX', 'LMT', 'NOC', 'GD', 'BA', 'RHM.DE',
                            'TKA.DE', 'BAE.L'],
        'sectors':        ['defense', 'energy'],
    },
    'CHINA_SHOCK': {
        'required':       ['china', 'beijing', 'pboc'],
        'at_least_one':   ['lockdown', 'stimulus', 'crash', 'devaluation',
                            'property crisis', 'evergrande', 'collapse'],
        'severity':       'HIGH',
        'impact_tickers': ['BABA', 'BIDU', 'JD', 'NIO', 'PDD'],
        'sectors':        ['tech', 'consumer'],
    },
    'PHARMA_SHOCK': {
        'required':       ['fda', 'ema'],
        'at_least_one':   ['approval', 'rejection', 'recall', 'warning',
                            'phase 3', 'breakthrough'],
        'severity':       'MEDIUM',
        'impact_tickers': ['NVO', 'LLY', 'PFE', 'MRK', 'JNJ', 'BAYN.DE'],
        'sectors':        ['pharma', 'biotech'],
    },
    'CRYPTO_SHOCK': {
        'required':       ['bitcoin', 'crypto', 'ethereum'],
        'at_least_one':   ['crash', 'halt', 'exchange', 'hacked', 'collapse',
                            'sec', 'etf approved'],
        'severity':       'MEDIUM',
        'impact_tickers': ['COIN', 'MSTR', 'MARA', 'RIOT'],
        'sectors':        ['crypto', 'fintech'],
    },
}

SEVERITY_SCORE = {'CRITICAL': 0.98, 'HIGH': 0.90, 'MEDIUM': 0.75}


def fetch_recent_news(hours: int = 1) -> list[dict]:
    """News-Events der letzten N Stunden."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, headline, source, published_at, created_at, sector, "
        "       sentiment_label, relevance_score, url "
        "FROM news_events "
        "WHERE created_at >= ? "
        "ORDER BY created_at DESC",
        (cutoff,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def detect_bundle(headline: str) -> list[dict]:
    """Liefere alle Bundles die headline matcht."""
    h = headline.lower()
    matches = []
    for bundle_name, cfg in EVENT_BUNDLES.items():
        # Erforderliche Keyword-Klasse trifft?
        if not any(rk in h for rk in cfg['required']):
            continue
        # Mindestens 1 sekundäres Keyword?
        if not any(ak in h for ak in cfg['at_least_one']):
            continue
        matches.append({
            'bundle':         bundle_name,
            'severity':       cfg['severity'],
            'severity_score': SEVERITY_SCORE[cfg['severity']],
            'impact_tickers': cfg['impact_tickers'],
            'sectors':        cfg['sectors'],
        })
    return matches


def mark_event_in_db(event_id: int, bundle_name: str, severity_score: float,
                       impact_tickers: list[str]) -> None:
    """Update news_events relevance + insert in commodity_kill_events."""
    c = sqlite3.connect(str(DB))
    # Höhere Relevance-Score setzen
    c.execute(
        "UPDATE news_events SET relevance_score=? WHERE id=? AND relevance_score < ?",
        (severity_score, event_id, severity_score),
    )
    # Phase 42b — Eigene Tabelle macro_events (commodity_kill_events war
    # bereits durch alte Commodity-Threshold-Logik belegt mit anderem Schema).
    c.execute("""CREATE TABLE IF NOT EXISTS macro_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT, severity REAL,
        impact_tickers TEXT, news_event_id INTEGER,
        detected_at TEXT,
        UNIQUE(event_type, news_event_id)
    )""")
    c.execute(
        "INSERT OR IGNORE INTO macro_events "
        "(event_type, severity, impact_tickers, news_event_id, detected_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (bundle_name, severity_score, json.dumps(impact_tickers),
         event_id, datetime.utcnow().isoformat()),
    )
    c.commit()
    c.close()


def push_discord_alert(matches: list[dict]) -> bool:
    """Sende Critical/High-Events an Discord (via vorhandenen Bot/Webhook)."""
    try:
        from discord_chat import send_message_to_user
    except Exception:
        try:
            from discord_chat import _send_to_user as send_message_to_user
        except Exception:
            print('[macro_detector] Discord push not available', file=sys.stderr)
            return False

    text_parts = ['🚨 **BREAKING MACRO EVENT DETECTED** 🚨\n']
    for m in matches[:5]:
        text_parts.append(
            f"\n**[{m['severity']}] {m['bundle']}**\n"
            f"   📰 {m['headline'][:140]}\n"
            f"   📍 Source: {m['source']}\n"
            f"   🎯 Impact-Tickers: {', '.join(m['impact_tickers'][:6])}\n"
            f"   🏭 Sectors: {', '.join(m['sectors'])}"
        )
    text_parts.append('\n\n💡 Soll Albert die betroffenen Open-Positions reviewen?')

    text = '\n'.join(text_parts)
    try:
        send_message_to_user(text)
        return True
    except Exception as e:
        print(f'[macro_detector] Discord push failed: {e}', file=sys.stderr)
        return False


def trigger_auto_reeval(impact_tickers: list[str]) -> dict:
    """Markiere Open-Positions zur Re-Evaluation durch Albert."""
    c = sqlite3.connect(str(DB))
    placeholders = ','.join('?' * len(impact_tickers))
    affected = c.execute(
        f"SELECT id, ticker, strategy FROM paper_portfolio "
        f"WHERE status='OPEN' AND ticker IN ({placeholders})",
        impact_tickers,
    ).fetchall()
    c.close()

    if not affected:
        return {'affected': 0}

    # Schreibe Re-Eval-Marker für Thesis-Engine (next monitor pass picks it up)
    marker_file = WS / 'data' / 'macro_reeval_queue.json'
    queue = []
    if marker_file.exists():
        try:
            queue = json.loads(marker_file.read_text())
        except Exception:
            queue = []
    for r in affected:
        queue.append({
            'trade_id': r[0], 'ticker': r[1], 'strategy': r[2],
            'queued_at': datetime.utcnow().isoformat(),
            'reason': 'macro_event_auto_reeval',
        })
    marker_file.write_text(json.dumps(queue[-50:], indent=2))  # cap at 50
    return {'affected': len(affected), 'tickers': [r[1] for r in affected]}


def run(hours: int = 1, test_mode: bool = False) -> dict:
    """Hauptlauf: scan, detect, alert."""
    news = fetch_recent_news(hours=hours)
    all_matches: list[dict] = []
    seen_ids: set[int] = set()

    for n in news:
        bundles = detect_bundle(n['headline'])
        for b in bundles:
            if n['id'] in seen_ids:
                continue
            match = {
                'event_id':       n['id'],
                'headline':       n['headline'],
                'source':         n['source'],
                'bundle':         b['bundle'],
                'severity':       b['severity'],
                'severity_score': b['severity_score'],
                'impact_tickers': b['impact_tickers'],
                'sectors':        b['sectors'],
                'created_at':     n.get('created_at'),
            }
            all_matches.append(match)
            seen_ids.add(n['id'])
            if not test_mode:
                mark_event_in_db(n['id'], b['bundle'],
                                  b['severity_score'], b['impact_tickers'])

    # Push critical/high to Discord
    critical_high = [m for m in all_matches if m['severity'] in ('CRITICAL', 'HIGH')]
    pushed = False
    reeval_result = {'affected': 0}
    if critical_high and not test_mode:
        # Dedup: erstmal nicht 2x dasselbe Bundle in 6h pushen
        marker = WS / 'data' / 'macro_push_log.json'
        log_data = {}
        if marker.exists():
            try:
                log_data = json.loads(marker.read_text())
            except Exception:
                log_data = {}
        cutoff = (datetime.utcnow() - timedelta(hours=6)).isoformat()
        log_data = {k: v for k, v in log_data.items() if v > cutoff}
        new_to_push = []
        for m in critical_high:
            key = m['bundle']
            if key not in log_data:
                new_to_push.append(m)
                log_data[key] = datetime.utcnow().isoformat()
        if new_to_push:
            pushed = push_discord_alert(new_to_push)
            # Auto-Re-Eval triggern
            all_impact = list({t for m in new_to_push for t in m['impact_tickers']})
            reeval_result = trigger_auto_reeval(all_impact)
            marker.write_text(json.dumps(log_data, indent=2))

    return {
        'scanned_news': len(news),
        'matches':      len(all_matches),
        'critical_high': len(critical_high),
        'pushed_to_discord': pushed,
        'reeval_queued': reeval_result.get('affected', 0),
        'matches_detail': all_matches[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=0.5,
                     help='Lookback-Window in Stunden (default 0.5)')
    ap.add_argument('--test', action='store_true', help='Dry-run, kein DB-Update/Discord')
    args = ap.parse_args()

    print(f'[macro_detector] scanning last {args.hours}h ...')
    result = run(hours=args.hours, test_mode=args.test)
    print(f'  News scanned:      {result["scanned_news"]}')
    print(f'  Matches found:     {result["matches"]}')
    print(f'  Critical/High:     {result["critical_high"]}')
    print(f'  Discord-Pushed:    {result["pushed_to_discord"]}')
    print(f'  Re-Eval queued:    {result["reeval_queued"]}')
    if result['matches_detail']:
        print('\n  Top matches:')
        for m in result['matches_detail'][:5]:
            print(f"    [{m['severity']}] {m['bundle']:<14} {m['headline'][:80]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
