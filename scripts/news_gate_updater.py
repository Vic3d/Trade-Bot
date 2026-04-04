#!/usr/bin/env python3
"""
News Gate Updater
=================
Liest frische Events aus newswire.db, matched sie gegen aktive Strategien
und schreibt data/news_gate.json.

Wird alle 4h vom Scheduler Daemon aufgerufen (direkt nach newswire_analyst.py).
Kein LLM, keine Token-Kosten.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

WS = Path('/data/.openclaw/workspace')

# ── Thesis-Keywords pro Strategie ──────────────────────────────────────────────
THESIS_KEYWORDS = {
    # ── Bestehende Thesen ──────────────────────────────────────────────────────
    'S1_Iran':    ['iran', 'hormuz', 'houthi', 'strait', 'irgc', 'tehran', 'persian gulf'],
    'S2_Rüstung': ['rheinmetall', 'rüstung', 'defense', 'nato', 'bundeswehr', 'military spending', 'weapons'],
    'S3_KI':      ['nvidia', 'ai', 'artificial intelligence', 'semiconductor', 'chip', 'gpu', 'palantir'],
    'S4_Silver':  ['silber', 'silver', 'gold', 'edelmetall', 'precious metal', 'gsr', 'gold silver'],
    'S5_Rohstoff':['copper', 'kupfer', 'cobalt', 'lithium', 'rio tinto', 'bhp', 'iron ore', 'mining'],
    'PS1_Oil':    ['öl', 'oil', 'brent', 'crude', 'wti', 'opec', 'equinor', 'totalenergies', 'tte', 'eqnr'],
    'PS2_Tanker': ['tanker', 'vlcc', 'frontline', 'dht', 'fro', 'suezmax', 'aframax'],
    'PS3_Defense':['ktos', 'hii', 'rheinmetall', 'saab', 'bae systems', 'leonardo'],
    'PS4_Metals': ['silver', 'hl', 'paas', 'first majestic', 'pan american', 'miner'],
    'PS5_Agrar':  ['mosaic', 'mos', 'dünger', 'fertilizer', 'potash', 'agrar', 'wheat', 'corn'],
    'PS11_DefEU': ['rheinmetall', 'saab', 'bae systems', 'european defense', 'eu rüstung', 'thales', 'leonardo'],
    'PS14_Ship':  ['shipping', 'zim', 'matx', 'sblk', 'containerschiff', 'container ship', 'freight'],

    # ── Neue Thesen (autonome Entdeckung 04.04.2026) ──────────────────────────
    'PS_Copper':  ['copper', 'kupfer', 'freeport', 'fcx', 'southern copper', 'scco', 'teck',
                   'copper demand', 'green transition', 'ev battery', 'grid'],
    'PS_China':   ['china recovery', 'chinese economy', 'stimulus', 'pboc', 'kweb', 'fxi',
                   'alibaba', 'baba', 'jd.com', 'baidu', 'bidu', 'hang seng', 'shanghai'],
    'PS_AIInfra': ['super micro', 'smci', 'data center', 'power consumption', 'cooling',
                   'applied materials', 'amat', 'micron', 'memory', 'hbm', 'vertiv', 'vrt'],
}

# Strategien die aktuell AKTIV sind (Status > testing)
ACTIVE_STRATEGIES = {
    'S1_Iran', 'S2_Rüstung', 'S3_KI', 'S4_Silver', 'S5_Rohstoff',
    'PS1_Oil', 'PS2_Tanker', 'PS3_Defense', 'PS4_Metals', 'PS5_Agrar',
    'PS11_DefEU', 'PS14_Ship',
    # Neue
    'PS_Copper', 'PS_China', 'PS_AIInfra',
}


def load_strategies():
    """Lade Ticker-Listen aus strategies.json für erweiterte Keyword-Generierung."""
    try:
        strats = json.loads((WS / 'data/strategies.json').read_text())
        return strats
    except Exception:
        return {}


def get_recent_events(hours: int = 24) -> list[dict]:
    """Lese Events der letzten N Stunden aus trading.db (news_events Tabelle)."""
    db_path = WS / 'data/trading.db'
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cutoff = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

    try:
        cur.execute("""
            SELECT id, headline, source, tickers, sentiment_score, sentiment_label, created_at
            FROM news_events
            WHERE created_at > ?
            ORDER BY id DESC
        """, (cutoff,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f'DB-Fehler: {e}')
        return []
    finally:
        conn.close()


def match_thesis(headline: str, tickers_str: str) -> list[str]:
    """Matched Headline + Ticker gegen aktive Thesen."""
    text = (headline or '').lower()
    tickers = (tickers_str or '').lower()
    combined = text + ' ' + tickers

    matches = []
    for thesis, keywords in THESIS_KEYWORDS.items():
        if thesis not in ACTIVE_STRATEGIES:
            continue
        if any(kw in combined for kw in keywords):
            matches.append(thesis)
    return matches


def update_news_gate():
    """Hauptfunktion: Events matchen + news_gate.json schreiben."""
    events = get_recent_events(hours=24)

    if not events:
        print('Keine Events in den letzten 24h — news_gate nicht aktualisiert')
        return

    top_hits = []
    hit_count = 0

    for ev in events:
        headline = ev.get('headline', '')
        tickers_raw = ev.get('tickers', '') or ''
        # tickers kann JSON-Array sein
        try:
            import json as _json
            tickers = ' '.join(_json.loads(tickers_raw)) if tickers_raw.startswith('[') else tickers_raw
        except Exception:
            tickers = tickers_raw

        matches = match_thesis(headline, tickers)

        if not matches:
            continue

        hit_count += 1
        # Nur Top 10 Hits speichern
        if len(top_hits) < 10:
            top_hits.append({
                'thesis': matches[0],
                'all_theses': matches,
                'headline': headline[:120],
                'ticker': tickers or '',
                'score': ev.get('sentiment_score', 0),
                'direction': ev.get('sentiment_label', 'NEUTRAL'),
                'source': ev.get('source', ''),
                'ts': ev.get('created_at', '')
            })

    relevant = hit_count > 0

    result = {
        'timestamp': datetime.now().isoformat(),
        'relevant': relevant,
        'hit_count': hit_count,
        'events_scanned': len(events),
        'window_hours': 24,
        'top_hits': top_hits,
        'theses_hit': list(set(
            h['thesis'] for h in top_hits
        ))
    }

    (WS / 'data/news_gate.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )

    print(f'news_gate aktualisiert: relevant={relevant}, hits={hit_count}/{len(events)} Events, Thesen: {result["theses_hit"]}')


if __name__ == '__main__':
    update_news_gate()
