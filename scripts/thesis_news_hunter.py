#!/usr/bin/env python3
"""
Thesis News Hunter — Aktive Nachrichtensuche für offene Thesen
==============================================================
Sucht PROAKTIV nach Nachrichten zu jeder aktiven Strategie.
Bewertet mit Claude API: Neues Katalysator? Eingepreist? Kill-Trigger?

Anders als overnight_collector (passiv, RSS-Feeds):
→ Dieser Script sucht gezielt für jede These nach spezifischen Themen
→ Bewertet Relevanz und "priced-in"-Status mit KI
→ Erkennt Gegenbewegungen und Thesis-Invalidierungen frühzeitig

Datenquellen: Google News RSS (kostenlos, kein API-Key)

Läuft: alle 4h (09:00, 13:00, 17:00, 21:00 CET)

Usage:
  python3 thesis_news_hunter.py              # normaler Run
  python3 thesis_news_hunter.py --dry-run    # ohne DB-Writes
  python3 thesis_news_hunter.py --thesis PS1 # nur eine These
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS      = Path('/data/.openclaw/workspace')
DATA    = WS / 'data'
SCRIPTS = WS / 'scripts'
sys.path.insert(0, str(SCRIPTS))

CLAUDE_MODEL = 'claude-opus-4-5'
LOG_FILE     = DATA / 'thesis_hunter.log'


def log(msg: str):
    ts   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ── News-Suche via Google News RSS ───────────────────────────────────────────

def fetch_google_news(query: str, hours: int = 8, max_results: int = 8) -> list[dict]:
    """
    Sucht Google News RSS nach query.
    Gibt Liste von {title, description, published, link} zurück.
    """
    encoded  = urllib.parse.quote(query)
    url      = f'https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en'
    articles = []

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; TradeMind/1.0)',
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            xml_data = r.read()

        root  = ET.fromstring(xml_data)
        items = root.findall('.//item')
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        for item in items[:max_results * 2]:
            title = item.findtext('title', '')
            desc  = item.findtext('description', '')
            link  = item.findtext('link', '')
            pub   = item.findtext('pubDate', '')

            # Datum parsen
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub)
                if pub_dt < cutoff:
                    continue
                pub_str = pub_dt.strftime('%Y-%m-%d %H:%M')
            except Exception:
                pub_str = pub[:16]

            # HTML-Tags aus description entfernen
            import re
            clean_desc = re.sub(r'<[^>]+>', '', desc)[:200]

            articles.append({
                'title':       title[:120],
                'description': clean_desc,
                'published':   pub_str,
                'link':        link,
            })

            if len(articles) >= max_results:
                break

    except Exception as e:
        log(f'  Google News Fehler ({query[:30]}): {e}')

    return articles


def build_search_queries(thesis_id: str, strategy: dict) -> list[str]:
    """
    Baut gezielte Suchanfragen aus der Strategie-Konfiguration.
    Kombiniert: keywords_bullish + kill_trigger + entry_trigger + Ticker
    """
    queries = []
    name    = strategy.get('name', thesis_id)

    # 1. Haupt-Suche: Thesis-Name + aktuelle Lage
    thesis_text = strategy.get('thesis', '')
    trigger     = strategy.get('entry_trigger', '')

    # Keywords aus der Strategie
    kw_bullish  = strategy.get('keywords_bullish', [])
    kw_bearish  = strategy.get('keywords_bearish', [])
    kill        = strategy.get('kill_trigger', '')
    tickers     = strategy.get('tickers', [])

    # Spezifische Queries aus Kill-Trigger Begriffen
    if kill:
        # Kill-Trigger Schlüsselbegriffe extrahieren
        kill_words = [w.strip() for w in kill.replace('ODER', 'OR').split('OR')
                      if len(w.strip()) > 4]
        for kw in kill_words[:2]:
            # Bereinigen: nur erste 3 Wörter
            clean = ' '.join(kw.split()[:4]).strip('*').strip()
            if clean:
                queries.append(clean)

    # Queries aus bullish keywords (erste 3)
    if kw_bullish:
        core = ' '.join(kw_bullish[:3])
        queries.append(core)

    # Ticker-spezifische Suche (erste 2)
    for ticker in tickers[:2]:
        # Xetra/Oslo Suffix entfernen für bessere Suche
        clean_ticker = ticker.replace('.DE', '').replace('.PA', '').replace('.OL', '').replace('.L', '')
        queries.append(f'{clean_ticker} stock news')

    # Fallback: Thesis-Name
    if not queries:
        queries.append(name)

    return list(dict.fromkeys(queries))[:4]  # Max 4 Queries, keine Duplikate


# ── Aktuellen Preis holen ────────────────────────────────────────────────────

def get_price_context(tickers: list[str]) -> str:
    """Holt aktuelle Preise + 30-Tage-Trend für Thesis-Tickers."""
    results = []
    for ticker in tickers[:3]:
        try:
            url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.load(r)
            res    = data['chart']['result'][0]
            meta   = res['meta']
            closes = [c for c in res['indicators']['quote'][0].get('close', []) if c]
            price  = meta.get('regularMarketPrice', closes[-1] if closes else 0)
            if closes and len(closes) >= 20:
                trend_30d = (closes[-1] / closes[0] - 1) * 100
                trend_str = f'{trend_30d:+.1f}% (30T)'
            else:
                trend_str = 'n/a'
            results.append(f'{ticker}: {price:.2f} | Trend {trend_str}')
            time.sleep(0.2)
        except Exception:
            results.append(f'{ticker}: Preis n/v')
    return '\n'.join(results)


# ── KI-Bewertung ─────────────────────────────────────────────────────────────

HUNTER_PROMPT = """Du bist Albert, Trading-CEO. Bewerte folgende Nachrichten für eine aktive Handelsstrategie.

STRATEGIE: {thesis_id} — {name}
THESE: {thesis}
KILL-TRIGGER: {kill_trigger}
ENTRY-TRIGGER: {entry_trigger}

AKTUELLE PREISE (30-Tage-Trend):
{price_context}

GEFUNDENE NACHRICHTEN (letzte {hours}h):
{articles}

DEINE AUFGABE:
1. Ist das neue Information oder bereits eingepreist?
2. Stärkt oder schwächt das die These?
3. Wurde ein Kill-Trigger angedeutet?
4. Wie verändert sich die Conviction (stark/leicht erhöhen, halten, leicht/stark senken)?

ANTWORTE MIT DIESEM JSON (NUR JSON, kein anderer Text):
{{
  "new_information": true/false,
  "priced_in_assessment": "Kurze Einschätzung ob Markt das bereits reflektiert",
  "thesis_impact": "STRENGTHENED" | "NEUTRAL" | "WEAKENED" | "KILL_TRIGGER_NEAR",
  "conviction_change": "STRONG_UP" | "UP" | "HOLD" | "DOWN" | "STRONG_DOWN",
  "key_finding": "1-2 Sätze: Was ist das Wichtigste aus diesen Nachrichten?",
  "action_needed": "NONE" | "MONITOR" | "REDUCE" | "EXIT" | "ADD",
  "relevant_headlines": ["headline1", "headline2"]
}}
"""


def evaluate_with_ai(thesis_id: str, strategy: dict, articles: list[dict],
                     price_context: str, hours: int = 8) -> dict | None:
    """Lässt Albert die gefundenen Artikel bewerten."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not articles:
        return None

    # Artikel formatieren
    articles_text = ''
    for i, a in enumerate(articles, 1):
        articles_text += f"{i}. [{a['published']}] {a['title']}\n"
        if a.get('description'):
            articles_text += f"   {a['description'][:120]}\n"

    prompt = HUNTER_PROMPT.format(
        thesis_id     = thesis_id,
        name          = strategy.get('name', thesis_id),
        thesis        = strategy.get('thesis', '')[:200],
        kill_trigger  = strategy.get('kill_trigger', 'nicht definiert')[:150],
        entry_trigger = strategy.get('entry_trigger', '')[:100],
        price_context = price_context,
        articles      = articles_text,
        hours         = hours,
    )

    try:
        import anthropic
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        log(f'  KI-Bewertung Fehler ({thesis_id}): {e}')
        return None


# ── Ergebnis in DB speichern ─────────────────────────────────────────────────

def save_to_db(thesis_id: str, assessment: dict, articles: list[dict], dry_run: bool = False):
    """
    Speichert wichtige Findings in overnight_events + updated thesis_status.
    """
    if dry_run or not assessment:
        return

    impact    = assessment.get('thesis_impact', 'NEUTRAL')
    key_finding = assessment.get('key_finding', '')
    action    = assessment.get('action_needed', 'NONE')
    headlines = assessment.get('relevant_headlines', [])

    # Impact-Direction mappen
    direction_map = {
        'STRENGTHENED':       'bullish_thesis',
        'WEAKENED':           'bearish_thesis',
        'KILL_TRIGGER_NEAR':  'kill_trigger_warning',
        'NEUTRAL':            'neutral',
    }
    impact_dir = direction_map.get(impact, 'neutral')

    try:
        db_path = DATA / 'trading.db'
        conn    = sqlite3.connect(str(db_path))
        now_str = datetime.now(timezone.utc).isoformat()

        # Wichtige Findings als overnight_event speichern
        if impact != 'NEUTRAL' or assessment.get('new_information'):
            headline = headlines[0] if headlines else key_finding[:100]
            conn.execute("""
                INSERT OR IGNORE INTO overnight_events
                    (headline, impact_direction, strategies_affected, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                f'[HUNTER:{thesis_id}] {headline}'[:200],
                impact_dir,
                json.dumps([thesis_id]),
                now_str,
            ))

        # thesis_status updaten
        conviction_map = {
            'STRONG_UP':   10,
            'UP':           5,
            'HOLD':         0,
            'DOWN':        -5,
            'STRONG_DOWN': -10,
        }
        conv_delta = conviction_map.get(assessment.get('conviction_change', 'HOLD'), 0)

        try:
            existing = conn.execute(
                "SELECT health_score, status FROM thesis_status WHERE thesis_id=?",
                (thesis_id,)
            ).fetchone()

            if existing:
                new_health = max(0, min(100, (existing[0] or 100) + conv_delta))
                new_status = existing[1]
                if impact == 'KILL_TRIGGER_NEAR':
                    new_status = 'DEGRADED'
                elif new_health < 30:
                    new_status = 'DEGRADED'
                conn.execute("""
                    UPDATE thesis_status
                    SET health_score=?, status=?, last_checked=?
                    WHERE thesis_id=?
                """, (new_health, new_status, now_str, thesis_id))
            else:
                health = max(0, min(100, 80 + conv_delta))
                status = 'DEGRADED' if impact == 'KILL_TRIGGER_NEAR' else 'ACTIVE'
                conn.execute("""
                    INSERT OR IGNORE INTO thesis_status
                        (thesis_id, status, health_score, last_checked)
                    VALUES (?, ?, ?, ?)
                """, (thesis_id, status, health, now_str))
        except Exception:
            pass  # thesis_status Tabelle existiert möglicherweise nicht

        conn.commit()
        conn.close()

    except Exception as e:
        log(f'  DB-Fehler ({thesis_id}): {e}')


# ── Haupt-Run ────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, only_thesis: str | None = None, hours: int = 8) -> list[dict]:
    """
    Hauptfunktion: durchsucht alle aktiven Thesen nach relevanten News.
    """
    log(f'=== Thesis News Hunter {"[DRY-RUN]" if dry_run else ""} ===')

    # Strategien laden
    strats_file = DATA / 'strategies.json'
    if not strats_file.exists():
        log('strategies.json nicht gefunden')
        return []

    strategies = json.loads(strats_file.read_text(encoding='utf-8'))
    if not isinstance(strategies, dict):
        log('strategies.json hat unerwartetes Format')
        return []

    # Nur aktive Strategien
    active = {
        sid: s for sid, s in strategies.items()
        if isinstance(s, dict)
        and s.get('status', 'active').lower() not in ('inactive', 'blocked', 'suspended')
        and (only_thesis is None or sid == only_thesis.upper())
    }

    log(f'{len(active)} aktive Thesen zu prüfen')
    all_results = []

    for thesis_id, strategy in active.items():
        log(f'\n── {thesis_id}: {strategy.get("name", "")} ──')

        # Suchanfragen bauen
        queries = build_search_queries(thesis_id, strategy)
        log(f'  Queries: {queries}')

        # Artikel sammeln (alle Queries, Duplikate entfernen)
        all_articles = []
        seen_titles  = set()
        for query in queries:
            articles = fetch_google_news(query, hours=hours)
            for a in articles:
                title_key = a['title'][:50].lower()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_articles.append(a)
            time.sleep(0.5)  # Rate-Limit

        log(f'  {len(all_articles)} Artikel gefunden')
        if not all_articles:
            log(f'  → Keine News gefunden — These unverändert')
            continue

        # Preis-Kontext holen
        tickers       = strategy.get('tickers', [])
        price_context = get_price_context(tickers) if tickers else 'Keine Ticker definiert'

        # KI-Bewertung
        assessment = evaluate_with_ai(thesis_id, strategy, all_articles, price_context, hours)

        if assessment:
            impact  = assessment.get('thesis_impact', 'NEUTRAL')
            finding = assessment.get('key_finding', '')
            action  = assessment.get('action_needed', 'NONE')
            priced  = assessment.get('priced_in_assessment', '')
            new_info = assessment.get('new_information', False)

            icon = {'STRENGTHENED': '🟢', 'WEAKENED': '🔴',
                    'KILL_TRIGGER_NEAR': '🚨', 'NEUTRAL': '⚪'}.get(impact, '⚪')
            log(f'  {icon} Impact: {impact} | Action: {action} | Neu: {new_info}')
            log(f'  Finding: {finding[:100]}')
            log(f'  Eingepreist: {priced[:80]}')

            # In DB speichern
            save_to_db(thesis_id, assessment, all_articles, dry_run=dry_run)

            all_results.append({
                'thesis_id':  thesis_id,
                'assessment': assessment,
                'articles':   len(all_articles),
            })
        else:
            log(f'  KI-Bewertung nicht verfügbar (kein API-Key?)')

        time.sleep(1)  # Zwischen Thesen kurz pausieren

    # Zusammenfassung
    critical = [r for r in all_results
                if r['assessment'].get('thesis_impact') in ('KILL_TRIGGER_NEAR', 'WEAKENED')]
    strengthened = [r for r in all_results
                    if r['assessment'].get('thesis_impact') == 'STRENGTHENED']

    log(f'\n=== Hunter fertig: {len(all_results)} Thesen bewertet | '
        f'{len(strengthened)} gestärkt | {len(critical)} kritisch ===')

    # Kritische Findings in Discord-freundliches Summary schreiben
    if all_results:
        _write_summary(all_results)

    return all_results


def _write_summary(results: list[dict]):
    """Schreibt Summary in data/thesis_hunter_summary.json für Discord-Kontext."""
    summary = {
        'updated_at': datetime.now().isoformat(),
        'findings': [],
    }
    for r in results:
        a = r['assessment']
        if a.get('thesis_impact') != 'NEUTRAL' or a.get('new_information'):
            summary['findings'].append({
                'thesis_id':   r['thesis_id'],
                'impact':      a.get('thesis_impact'),
                'key_finding': a.get('key_finding', '')[:150],
                'action':      a.get('action_needed'),
                'priced_in':   a.get('priced_in_assessment', '')[:100],
                'new_info':    a.get('new_information', False),
            })

    output_file = DATA / 'thesis_hunter_summary.json'
    output_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False))


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    dry_run     = '--dry-run' in sys.argv
    only_thesis = None
    hours       = 8

    # --thesis PS1
    if '--thesis' in sys.argv:
        idx = sys.argv.index('--thesis')
        if idx + 1 < len(sys.argv):
            only_thesis = sys.argv[idx + 1]

    # --hours 24
    if '--hours' in sys.argv:
        idx = sys.argv.index('--hours')
        if idx + 1 < len(sys.argv):
            hours = int(sys.argv[idx + 1])

    run(dry_run=dry_run, only_thesis=only_thesis, hours=hours)
