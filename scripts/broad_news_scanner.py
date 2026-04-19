#!/usr/bin/env python3
"""
Broad News Scanner — Breaking News Frühwarnsystem
==================================================
Läuft alle 30 Min (09-21h Mo-Fr) und überwacht ALLE aktiven Thesen.

KEIN Claude API Call (Kostengründe) — rein keyword-basiert.
Sobald ein potentieller Treffer gefunden wird:
  → speichert in overnight_events (für CEO + Thesis Hunter)
  → sendet Discord-Alert wenn Score hoch genug
  → flaggt unbekannte Themen für thesis_discovery

Anders als thesis_news_hunter (der stündlich mit AI arbeitet):
→ Dieser Scanner läuft alle 30 Min mit ZERO API-Kosten
→ Erste Verteidigungslinie für Breaking News
→ Thesis Hunter übernimmt die KI-Bewertung beim nächsten Lauf

Usage:
  python3 broad_news_scanner.py            # normaler Run
  python3 broad_news_scanner.py --dry-run  # kein DB-Write, kein Discord
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

WS      = Path('/data/.openclaw/workspace')
DATA    = WS / 'data'
SCRIPTS = WS / 'scripts'
sys.path.insert(0, str(SCRIPTS))

LOG_FILE    = DATA / 'broad_scanner.log'
SEEN_FILE   = DATA / 'broad_scanner_seen.json'   # URL-Hashes der bereits gesehenen Headlines
DISCORD_MIN_SCORE = 3  # Mindest-Score für Discord-Alert


def log(msg: str):
    ts = datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ── Breaking News Quellen ─────────────────────────────────────────────────────

BREAKING_FEEDS = [
    # Getestet & funktional auf Hetzner VPS (April 2026)
    ('WSJ Markets',    'https://feeds.a.dj.com/rss/RSSMarketsMain.xml'),
    ('NYT Business',   'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml'),
    ('Sky News World', 'https://feeds.skynews.com/feeds/rss/world.xml'),         # Geopolitik
    ('Al Jazeera',     'https://www.aljazeera.com/xml/rss/all.xml'),              # Nahost-Fokus
    ('Investing.com',  'https://www.investing.com/rss/news.rss'),
    ('MarketWatch',    'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ('Fortune',        'https://fortune.com/feed/'),
    ('Handelsblatt',   'https://www.handelsblatt.com/contentexport/feed/top-themen'),  # DE
]


def fetch_feed(name: str, url: str, max_age_hours: int = 2) -> list[dict]:
    """Holt RSS-Feed, filtert auf max_age_hours."""
    from email.utils import parsedate_to_datetime
    results = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (TradeMind/2.0)'})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read()

        root    = ET.fromstring(raw)
        cutoff  = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        for item in root.findall('.//item'):
            title = item.findtext('title', '').strip()
            link  = item.findtext('link', '')
            pub   = item.findtext('pubDate', '')
            if not title:
                continue
            try:
                pub_dt = parsedate_to_datetime(pub)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
                pub_str = pub_dt.isoformat()
            except Exception:
                pub_str = datetime.now(timezone.utc).isoformat()

            results.append({
                'source':    name,
                'title':     title[:200],
                'link':      link,
                'published': pub_str,
            })
    except Exception as e:
        log(f'  Feed-Fehler {name}: {e}')
    return results


# ── Seen-State Management ─────────────────────────────────────────────────────

def load_seen() -> set:
    """Lädt bereits gesehene URL-Hashes (letzte 4h werden behalten)."""
    try:
        data = json.loads(SEEN_FILE.read_text())
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        # Nur Einträge der letzten 4h behalten
        fresh = {k: v for k, v in data.items() if v > cutoff}
        return set(fresh.keys())
    except Exception:
        return set()


def save_seen(seen: set):
    """Speichert gesehene Hashes mit aktuellem Timestamp."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        try:
            existing = json.loads(SEEN_FILE.read_text())
        except Exception:
            existing = {}
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        fresh = {k: v for k, v in existing.items() if v > cutoff}
        for h in seen:
            fresh[h] = now
        SEEN_FILE.write_text(json.dumps(fresh))
    except Exception:
        pass


def headline_hash(title: str) -> str:
    import hashlib
    return hashlib.md5(title.lower().strip()[:80].encode()).hexdigest()[:12]


# ── Keyword Matching gegen aktive Strategien ──────────────────────────────────

def load_strategy_keywords() -> dict:
    """
    Lädt alle Keywords aus aktiven Strategien.
    Returns: {thesis_id: {keywords: [...], kill_trigger: str, sector: str, score_threshold: int}}
    """
    strats_file = DATA / 'strategies.json'
    if not strats_file.exists():
        return {}

    strategies = json.loads(strats_file.read_text(encoding='utf-8'))
    result = {}

    for sid, s in strategies.items():
        if not isinstance(s, dict):
            continue
        status = s.get('status', 'active').lower()
        if status in ('inactive', 'blocked', 'suspended'):
            continue

        keywords = []
        # Bullish keywords
        keywords.extend(s.get('keywords_bullish', []))
        # Bearish keywords
        keywords.extend(s.get('keywords_bearish', []))
        # Kill-Trigger Wörter
        kill = s.get('kill_trigger', '')
        if kill:
            kill_words = re.findall(r'\b[a-zA-ZäöüÄÖÜ]{4,}\b', kill.lower())
            keywords.extend(kill_words[:8])
        # Tickers als Keywords
        for t in s.get('tickers', []):
            clean = t.replace('.DE', '').replace('.PA', '').replace('.OL', '').replace('.L', '').lower()
            keywords.append(clean)

        result[sid] = {
            'keywords':   list(set(kw.lower() for kw in keywords if len(kw) > 3)),
            'kill_trigger': kill.lower(),
            'sector':     s.get('sector', ''),
            'name':       s.get('name', sid),
        }

    return result


# Sektor-Makro-Keywords (für unknown-topic detection)
SECTOR_MACRO = {
    'energy':    ['opec', 'iran', 'oil', 'crude', 'hormuz', 'wti', 'brent', 'gas', 'lng', 'petroleum'],
    'defense':   ['nato', 'ukraine', 'war', 'military', 'defense', 'missile', 'troops', 'sanctions'],
    'pharma':    ['fda', 'drug', 'trial', 'approval', 'biotech', 'pharma', 'clinical', 'therapy'],
    'tech':      ['ai', 'chip', 'nvidia', 'semiconductor', 'taiwan', 'export controls', 'quantum'],
    'macro':     ['fed', 'federal reserve', 'ecb', 'interest rate', 'inflation', 'recession', 'gdp'],
    'precious':  ['gold', 'silver', 'copper', 'mining', 'commodities'],
    'shipping':  ['red sea', 'shipping', 'freight', 'tanker', 'container', 'suez', 'strait'],
    'china':     ['china', 'xi jinping', 'beijing', 'taiwan', 'trade war', 'tariffs'],
}


def score_headline(title: str, strategy_keywords: dict) -> list[dict]:
    """
    Bewertet eine Headline gegen alle Strategie-Keywords.
    Returns: list of {thesis_id, score, matched_keywords, is_kill_trigger}
    """
    title_lower = title.lower()
    matches = []

    for sid, config in strategy_keywords.items():
        score = 0
        matched = []

        for kw in config['keywords']:
            if kw in title_lower:
                score += 1
                matched.append(kw)

        # Kill-Trigger check
        is_kill = False
        if config['kill_trigger'] and score > 0:
            kill_words = config['kill_trigger'].split()[:4]
            kill_matches = sum(1 for w in kill_words if w in title_lower and len(w) > 3)
            if kill_matches >= 2:
                is_kill = True
                score += 5  # Kill-Trigger boosten

        if score >= 2:
            matches.append({
                'thesis_id': sid,
                'name':      config['name'],
                'score':     score,
                'matched':   matched[:5],
                'is_kill':   is_kill,
            })

    return sorted(matches, key=lambda x: x['score'], reverse=True)


def detect_unknown_sector(title: str) -> str | None:
    """Erkennt Sektor-Treffer auch wenn keine aktive Strategie existiert."""
    title_lower = title.lower()
    for sector, keywords in SECTOR_MACRO.items():
        if sum(1 for kw in keywords if kw in title_lower) >= 2:
            return sector
    return None


# ── DB + Discord ──────────────────────────────────────────────────────────────

def save_to_db(title: str, source: str, thesis_ids: list[str], impact_dir: str,
               published: str, dry_run: bool = False):
    """Speichert Treffer in overnight_events."""
    if dry_run:
        return
    try:
        conn = sqlite3.connect(str(DATA / 'trading.db'))
        conn.execute("""
            INSERT OR IGNORE INTO overnight_events
                (headline, impact_direction, strategies_affected, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            f'[BROAD:{source}] {title}'[:200],
            impact_dir,
            json.dumps(thesis_ids),
            published,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f'  DB-Fehler: {e}')


def send_discord(msg: str, dry_run: bool = False):
    """Sendet Discord-Alert."""
    if dry_run:
        log(f'  [DRY] Discord: {msg[:80]}')
        return
    try:
        from discord_sender import send
        send(msg)
    except Exception as e:
        log(f'  Discord-Fehler: {e}')


# ── Phase 3: Deep-Dive-Queue (News → Albert) ──────────────────────────────────

DEEPDIVE_QUEUE_FILE = DATA / 'deepdive_requests.json'
VERDICTS_FILE       = DATA / 'deep_dive_verdicts.json'


def _queue_deepdives_from_news(high_priority: list[dict]) -> None:
    """
    Phase 3: Für Tickers in high_priority News ohne frischen KAUFEN-Verdict
    einen Deep-Dive-Request in die Queue legen. Der autonomous_ceo liest diese
    Queue und schlägt entsprechend DEEP_DIVE-Actions vor.

    Queue-Format: list[{ticker, reason, ts, source, score, thesis_id}]
    Auto-Purge: Einträge älter als 3 Tage oder Ticker mit frischem Verdict.
    """
    if not high_priority:
        return

    # Strategies laden — Tickers pro thesis_id
    strats_file = DATA / 'strategies.json'
    try:
        strategies = json.loads(strats_file.read_text(encoding='utf-8'))
    except Exception:
        strategies = {}

    # Aktuelle Verdicts laden — Ticker mit frischem KAUFEN skippen
    try:
        verdicts = json.loads(VERDICTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        verdicts = {}

    def _has_fresh_verdict(ticker: str) -> bool:
        v = verdicts.get(ticker.upper(), {})
        if not v or v.get('verdict') != 'KAUFEN':
            return False
        try:
            age = (datetime.now(_BERLIN) - datetime.fromisoformat(v['date'])).days
            return age <= 14
        except Exception:
            return False

    # Queue laden + purgen
    try:
        queue = json.loads(DEEPDIVE_QUEUE_FILE.read_text(encoding='utf-8'))
        if not isinstance(queue, list):
            queue = []
    except Exception:
        queue = []

    now_berlin = datetime.now(_BERLIN)
    cutoff_3d  = (now_berlin - timedelta(days=3)).isoformat()
    queue = [
        q for q in queue
        if isinstance(q, dict)
        and q.get('ts', '') > cutoff_3d
        and not _has_fresh_verdict(q.get('ticker', ''))
    ]

    # Bereits in Queue → kein Duplikat (pro Ticker)
    in_queue = {q['ticker'].upper() for q in queue if q.get('ticker')}
    added    = 0

    for item in high_priority:
        headline = item.get('title', '')[:180]
        for m in item.get('matches', [])[:2]:
            thesis_id = m.get('thesis_id')
            score     = m.get('score', 0)
            if not thesis_id:
                continue
            strat = strategies.get(thesis_id, {})
            if not isinstance(strat, dict):
                continue
            for ticker in strat.get('tickers', []):
                tup = ticker.upper()
                if not tup or tup in in_queue:
                    continue
                if _has_fresh_verdict(tup):
                    continue
                queue.append({
                    'ticker':    tup,
                    'thesis_id': thesis_id,
                    'reason':    headline,
                    'source':    item.get('source', ''),
                    'score':     score,
                    'is_kill':   m.get('is_kill', False),
                    'ts':        now_berlin.isoformat(timespec='seconds'),
                })
                in_queue.add(tup)
                added += 1

    # Atomic write — nur die 50 neuesten behalten
    try:
        DEEPDIVE_QUEUE_FILE.write_text(
            json.dumps(queue[-150:], indent=2, ensure_ascii=False),  # Phase 24 aggressive: 50→150
            encoding='utf-8',
        )
    except Exception as e:
        log(f'  deepdive_requests.json write failed: {e}')
        return

    if added:
        log(f'  Deep-Dive-Queue: {added} neue Tickers (Queue-Size: {len(queue)})')


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    log(f'=== Broad News Scanner {"[DRY-RUN]" if dry_run else ""} ===')

    # Strategie-Keywords laden
    strategy_keywords = load_strategy_keywords()
    log(f'{len(strategy_keywords)} aktive Strategien geladen')

    # Bereits gesehene Headlines laden
    seen_hashes = load_seen()
    new_seen    = set()

    # Alle Breaking-News-Feeds abrufen
    all_articles = []
    for name, url in BREAKING_FEEDS:
        articles = fetch_feed(name, url, max_age_hours=2)
        log(f'  {name}: {len(articles)} Artikel')
        all_articles.extend(articles)
        time.sleep(0.3)

    log(f'{len(all_articles)} Artikel total geladen')

    # Treffer sammeln
    high_priority = []   # Score >= 4 oder Kill-Trigger → Discord + DB
    medium_priority = [] # Score 2-3 → nur DB
    unknown_sectors = [] # Kein Match aber Sektor-Treffer → thesis_discovery flag

    new_count = 0

    for article in all_articles:
        title = article['title']
        h = headline_hash(title)

        # Bereits gesehen?
        if h in seen_hashes:
            continue
        new_seen.add(h)
        new_count += 1

        # Against strategies
        matches = score_headline(title, strategy_keywords)

        if matches:
            best = matches[0]
            thesis_ids = [m['thesis_id'] for m in matches[:3]]
            impact_dir = 'kill_trigger_warning' if best['is_kill'] else 'broad_scan_match'

            if best['score'] >= 4 or best['is_kill']:
                high_priority.append({**article, 'matches': matches[:2]})
                save_to_db(title, article['source'], thesis_ids, impact_dir,
                           article['published'], dry_run=dry_run)
            elif best['score'] >= 2:
                medium_priority.append({**article, 'matches': matches[:1]})
                save_to_db(title, article['source'], thesis_ids, impact_dir,
                           article['published'], dry_run=dry_run)
        else:
            # Unknown topic?
            sector = detect_unknown_sector(title)
            if sector:
                unknown_sectors.append({'title': title, 'sector': sector,
                                        'source': article['source']})

    # Seen-State aktualisieren
    save_seen(seen_hashes | new_seen)

    log(f'{new_count} neue Headlines | {len(high_priority)} hoch | {len(medium_priority)} mittel | {len(unknown_sectors)} unbekannte Sektoren')

    # Discord-Alert für High-Priority
    if high_priority:
        lines = ['**Breaking News — Thesis-Alarm**']
        for a in high_priority[:4]:
            best_match = a['matches'][0]
            kill_tag = ' KILL-TRIGGER' if best_match['is_kill'] else ''
            lines.append(f"**{best_match['thesis_id']}**{kill_tag} (Score {best_match['score']})")
            lines.append(f"> {a['title'][:100]}")
            lines.append(f"  Quelle: {a['source']} | Keywords: {', '.join(best_match['matched'][:3])}")
        send_discord('\n'.join(lines), dry_run=dry_run)

        # Reaktiver CEO für kritische Events (score >= 4 oder Kill-Trigger)
        if not dry_run:
            try:
                _trigger_item = high_priority[0]  # Wichtigstes Event
                _trigger_match = _trigger_item.get('matches', [{}])[0]
                if _trigger_match.get('score', 0) >= 4 or _trigger_match.get('is_kill', False):
                    from autonomous_ceo import trigger_reactive_ceo
                    trigger_reactive_ceo({
                        'headline': _trigger_item.get('title', '')[:200],
                        'score': _trigger_match.get('score', 0),
                        'thesis_ids': [_trigger_match.get('thesis_id', '')],
                        'is_kill': _trigger_match.get('is_kill', False),
                    })
            except Exception as _ceo_err:
                log(f'Reaktiver CEO Trigger Fehler (nicht kritisch): {_ceo_err}')

        # Phase 3: Deep-Dive-Queue für Tickers mit hochrelevantem News-Event
        # und ohne frischen KAUFEN-Verdict. Wird vom nächsten autonomous_ceo
        # Cycle aufgegriffen (Action=DEEP_DIVE) — kein extra LLM-Call hier.
        if not dry_run:
            try:
                _queue_deepdives_from_news(high_priority)
            except Exception as _dq_err:
                log(f'Deep-Dive-Queue Fehler (nicht kritisch): {_dq_err}')

    # Unbekannte Sektoren → für thesis_discovery flaggen
    if unknown_sectors:
        unknown_file = DATA / 'broad_scanner_unknowns.json'
        existing = []
        try:
            existing = json.loads(unknown_file.read_text())
        except Exception:
            pass
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        existing = [x for x in existing if x.get('ts', '') > cutoff]
        for u in unknown_sectors[:5]:
            existing.append({**u, 'ts': datetime.now(timezone.utc).isoformat()})
        unknown_file.write_text(json.dumps(existing[-50:], indent=2, ensure_ascii=False))
        log(f'  {len(unknown_sectors)} unbekannte Sektoren -> broad_scanner_unknowns.json')

    return {
        'new_articles': new_count,
        'high_priority': len(high_priority),
        'medium_priority': len(medium_priority),
        'unknown_sectors': len(unknown_sectors),
    }


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    run(dry_run=dry_run)
