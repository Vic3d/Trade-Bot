#!/usr/bin/env python3
"""
thesis_discovery.py — Autonome Thesen-Entdeckung
=================================================
Albert analysiert wöchentlich Makro-News und identifiziert
neue strukturelle Trading-Thesen.

Läuft jeden Sonntag 07:00 UTC via scheduler_daemon.py
"""

import json
import os
import re
import sqlite3
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_DE_DAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

def _berlin_now() -> datetime:
    return datetime.now(ZoneInfo('Europe/Berlin'))

def _de_weekday(dt: datetime) -> str:
    return _DE_DAYS[dt.weekday()]

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atomic_json import atomic_write_json

DATA = WS / 'data'
DB = DATA / 'trading.db'
STRATEGIES_JSON = DATA / 'strategies.json'
PENDING_THESES_JSON = DATA / 'pending_theses.json'

# RSS feeds — tried in order, failures silently skipped
RSS_FEEDS = [
    ('Reuters Business',   'https://feeds.reuters.com/reuters/businessNews'),
    ('Reuters Finance',    'https://feeds.reuters.com/reuters/financialsNews'),
    ('Yahoo Finance',      'https://finance.yahoo.com/news/rssindex'),
    ('WSJ Markets',        'https://feeds.a.dj.com/rss/RSSMarketsMain.xml'),
    ('Bloomberg Markets',  'https://feeds.bloomberg.com/markets/news.rss'),
    ('FT Markets',         'https://www.ft.com/rss/home/uk'),
]

MAX_HEADLINES = 60


# ── RSS Parsing ───────────────────────────────────────────────────────────────

def _parse_rss_xml(xml_text: str, source_name: str) -> list[dict]:
    """Parse RSS XML and return list of headline dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # Handle both RSS 2.0 and Atom feeds
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    # RSS 2.0: //channel/item
    for item in root.iter('item'):
        title_el = item.find('title')
        desc_el   = item.find('description')
        pub_el    = item.find('pubDate')

        title = title_el.text.strip() if title_el is not None and title_el.text else ''
        desc  = desc_el.text.strip()  if desc_el is not None  and desc_el.text  else ''
        pub   = pub_el.text.strip()   if pub_el is not None   and pub_el.text   else ''

        # Strip HTML tags from description
        desc = re.sub(r'<[^>]+>', '', desc).strip()
        if len(desc) > 200:
            desc = desc[:200] + '...'

        if title:
            items.append({
                'title':     title,
                'desc':      desc,
                'source':    source_name,
                'published': pub,
            })

    # Atom feeds: //entry
    for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
        title_el = entry.find('{http://www.w3.org/2005/Atom}title')
        sum_el   = entry.find('{http://www.w3.org/2005/Atom}summary')
        pub_el   = entry.find('{http://www.w3.org/2005/Atom}updated')

        title = title_el.text.strip() if title_el is not None and title_el.text else ''
        desc  = sum_el.text.strip()   if sum_el  is not None  and sum_el.text  else ''
        pub   = pub_el.text.strip()   if pub_el  is not None  and pub_el.text  else ''

        desc = re.sub(r'<[^>]+>', '', desc).strip()
        if len(desc) > 200:
            desc = desc[:200] + '...'

        if title:
            items.append({
                'title':     title,
                'desc':      desc,
                'source':    source_name,
                'published': pub,
            })

    return items


def fetch_macro_news() -> list[dict]:
    """
    Fetch RSS feeds from multiple free sources using stdlib only.
    Returns list of dicts: [{'title': '...', 'source': '...', 'published': '...'}]
    Max 60 headlines total. Handles failures gracefully (skips unavailable feeds).
    """
    all_headlines: list[dict] = []

    for source_name, url in RSS_FEEDS:
        if len(all_headlines) >= MAX_HEADLINES:
            break
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'TradeMind-Albert/1.0 (thesis discovery)',
                    'Accept': 'application/rss+xml, application/xml, text/xml',
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='replace')

            items = _parse_rss_xml(raw, source_name)
            remaining = MAX_HEADLINES - len(all_headlines)
            all_headlines.extend(items[:remaining])
            print(f'[thesis_discovery] {source_name}: {len(items)} headlines fetched', flush=True)

        except urllib.error.URLError as e:
            print(f'[thesis_discovery] {source_name}: skipped ({e.reason})', flush=True)
        except Exception as e:
            print(f'[thesis_discovery] {source_name}: skipped ({e})', flush=True)

    print(f'[thesis_discovery] Total headlines: {len(all_headlines)}', flush=True)
    return all_headlines


# ── Existing Theses ───────────────────────────────────────────────────────────

def get_existing_theses() -> list[dict]:
    """
    Read strategies.json and thesis_status table from DB.
    Returns list of active/watching theses with their thesis text.
    Passed to Claude so it doesn't suggest duplicates.
    """
    results: list[dict] = []

    # Load from strategies.json
    try:
        if STRATEGIES_JSON.exists():
            raw = json.loads(STRATEGIES_JSON.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                for sid, data in raw.items():
                    status = data.get('status', 'active')
                    if status not in ('active', 'watching', 'ACTIVE', 'WATCHING'):
                        continue
                    results.append({
                        'id':     sid,
                        'name':   data.get('name', sid),
                        'thesis': data.get('thesis', ''),
                        'status': status,
                    })
            elif isinstance(raw, list):
                for item in raw:
                    status = item.get('status', 'active')
                    if status not in ('active', 'watching', 'ACTIVE', 'WATCHING'):
                        continue
                    results.append({
                        'id':     item.get('id', '?'),
                        'name':   item.get('name', '?'),
                        'thesis': item.get('thesis', ''),
                        'status': status,
                    })
    except Exception as e:
        print(f'[thesis_discovery] strategies.json load error: {e}', flush=True)

    # Augment with DB status (PROPOSED theses also count as existing)
    try:
        if DB.exists():
            conn = sqlite3.connect(str(DB))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT thesis_id, status, notes FROM thesis_status WHERE status IN ('ACTIVE','WATCHING','PROPOSED','EVALUATING')"
                ).fetchall()
                # Add DB-only entries (not already in strategies.json)
                existing_ids = {r['id'] for r in results}
                for row in rows:
                    tid = row['thesis_id']
                    if tid not in existing_ids:
                        results.append({
                            'id':     tid,
                            'name':   tid,
                            'thesis': row['notes'] or '',
                            'status': row['status'],
                        })
            except sqlite3.OperationalError:
                pass  # Table may not exist yet
            finally:
                conn.close()
    except Exception as e:
        print(f'[thesis_discovery] DB load error: {e}', flush=True)

    return results


# ── Claude API Call ───────────────────────────────────────────────────────────

def discover_theses_with_claude(headlines: list[dict], existing: list[dict]) -> list[dict]:
    """
    Call Anthropic API (claude-opus-4-5) to identify 2-3 structural trades.
    Returns list of thesis dicts, empty list on error.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        print('[thesis_discovery] ANTHROPIC_API_KEY not set — skipping Claude call', flush=True)
        return []

    try:
        import anthropic
    except ImportError:
        print('[thesis_discovery] anthropic package not installed', flush=True)
        return []

    # Format headlines for prompt
    headlines_text = '\n'.join(
        f"- [{h.get('source','?')}] {h.get('title','')}"
        for h in headlines[:MAX_HEADLINES]
    )

    # Format existing theses for prompt
    existing_text = '\n'.join(
        f"- {t['id']}: {t['name']} — {t['thesis']}"
        for t in existing
    ) or '(keine aktiven Thesen)'

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # P2.10 — Aktuelles Regime + Velocity in Prompt einspeisen
    _regime_block = ''
    try:
        import json as _json, os as _os
        _here = _os.path.dirname(_os.path.abspath(__file__))
        _reg_path = _os.path.join(_here, '..', '..', 'data', 'current_regime.json')
        if _os.path.exists(_reg_path):
            with open(_reg_path, encoding='utf-8') as _rf:
                _rd = _json.load(_rf)
            _regime_block = (
                f"\n=== AKTUELLES REGIME (HMM/Macro Brain) ===\n"
                f"Regime: {_rd.get('regime','?')} | Velocity: {_rd.get('velocity','?')}\n"
                f"VIX: {(_rd.get('factors') or {}).get('vix','?')} | "
                f"DXY: {(_rd.get('factors') or {}).get('dxy','?')} | "
                f"US10Y: {(_rd.get('factors') or {}).get('us10y','?')} | "
                f"SP500 vs MA200: {(_rd.get('factors') or {}).get('sp500_vs_ma200','?')}\n"
                f"→ Thesen MÜSSEN regime-kompatibel sein. RISK_OFF/BEAR = nur defensive/short-Thesen.\n"
            )
    except Exception as _e:
        print(f'[thesis_discovery] regime injection failed: {_e}', flush=True)

    # Determine next available thesis ID
    # Count existing PS IDs and pick the next one
    existing_ps_ids = []
    for t in existing:
        tid = t.get('id', '')
        m = re.match(r'^PS(\d+)$', tid)
        if m:
            existing_ps_ids.append(int(m.group(1)))
    next_id_num = max(existing_ps_ids, default=20) + 1

    system_prompt = (
        "Du bist Albert, KI-CEO und Macro-Trading-Analyst bei TradeMind. "
        "Deine Aufgabe: aus aktuellen Makro-News strukturelle mittelfristige Trades identifizieren (2-8 Wochen Horizont). "
        "Du analysierst Themen nüchtern, datenbasiert und ohne Bias. "
        "Du schlägst nur Thesen vor, die sich klar von bestehenden unterscheiden. "
        "Antworte IMMER mit validem JSON — kein Markdown, kein erklärender Text außerhalb des JSON-Arrays."
    )

    user_prompt = f"""Heute ist {today}.
{_regime_block}
=== AKTUELLE MAKRO-NEWS HEADLINES ({len(headlines)} Stück) ===
{headlines_text}

=== BESTEHENDE AKTIVE THESEN (NICHT wiederholen) ===
{existing_text}

=== AUFGABE ===
Identifiziere 2-3 NEUE strukturelle Trading-Thesen, die sich aus den aktuellen Headlines ergeben.
Nächste verfügbare ID beginnt bei PS{next_id_num}.

Gib ausschließlich ein JSON-Array zurück (kein Markdown, keine Erklärung). Format:
[
  {{
    "id": "PS{next_id_num}",
    "name": "Kurzer Name der These",
    "thesis": "Ursachenkette: X → Y → Z (1-2 Sätze)",
    "entry_trigger": "Konkreter, messbarer Einstiegs-Trigger",
    "kill_trigger": ["Konkreter Kill-Trigger 1 (Preisniveau, Datum, Event)", "Kill-Trigger 2 (optional, max 3)"],
    "tickers": ["TICK1", "TICK2", "TICK3"],
    "direction": "LONG / SHORT / LONG defensive / etc.",
    "timeframe": "2-4 Wochen",
    "confidence": 70
  }}
]

Regeln:
- Nur Thesen, die sich klar von den bestehenden unterscheiden
- confidence zwischen 50-85 (realistisch, kein Hype)
- Tickers: 3-6 konkrete, handelbare US- oder EU-Ticker
- Zeitrahmen: 2-8 Wochen (strukturelle Trades, kein Day-Trading)
- Keine Thesen die aktuell im Markt "overcrowded" sind
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model='claude-haiku-4-5-20241022',
            max_tokens=2000,
            system=system_prompt,
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        raw_text = response.content[0].text.strip()
        print(f'[thesis_discovery] Claude response length: {len(raw_text)} chars', flush=True)
    except Exception as e:
        print(f'[thesis_discovery] Claude API error: {e}', flush=True)
        return []

    # Parse JSON — handle possible markdown code blocks
    json_text = raw_text
    # Strip ```json ... ``` or ``` ... ```
    md_match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', json_text)
    if md_match:
        json_text = md_match.group(1)
    # Find JSON array
    arr_match = re.search(r'\[[\s\S]*\]', json_text)
    if arr_match:
        json_text = arr_match.group(0)

    try:
        theses = json.loads(json_text)
        if not isinstance(theses, list):
            print('[thesis_discovery] Claude output is not a JSON array', flush=True)
            return []
        # Validate each thesis has required fields
        valid = []
        for t in theses:
            if isinstance(t, dict) and t.get('id') and t.get('thesis'):
                valid.append(t)
        print(f'[thesis_discovery] {len(valid)} valid theses from Claude', flush=True)
        return valid
    except json.JSONDecodeError as e:
        print(f'[thesis_discovery] JSON parse error: {e}', flush=True)
        print(f'[thesis_discovery] Raw text: {raw_text[:500]}', flush=True)
        return []


# ── Auto-Activate Thesis ─────────────────────────────────────────────────────

def _auto_activate_thesis(thesis: dict) -> bool:
    """
    Aktiviert eine These direkt ohne Bestätigung.
    Schreibt in strategies.json + setzt status ACTIVE.
    """
    thesis_id = thesis.get('id', '')
    if not thesis_id:
        print('[thesis_discovery] _auto_activate_thesis: missing id', flush=True)
        return False

    confidence = thesis.get('confidence', 0)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Read current strategies.json
    try:
        strategies: dict = {}
        if STRATEGIES_JSON.exists():
            try:
                strategies = json.loads(STRATEGIES_JSON.read_text(encoding='utf-8'))
            except Exception:
                strategies = {}

        # Build strategy entry from thesis dict
        # Phase 22: kill_trigger MUSS Liste sein (TQS + Kill-Engine erwarten Liste)
        kt_raw = thesis.get('kill_trigger', [])
        if isinstance(kt_raw, list):
            kt_norm = [str(x).strip() for x in kt_raw if str(x).strip()]
        elif isinstance(kt_raw, str) and kt_raw.strip():
            import re as _re
            kt_norm = [
                p.strip().strip('.,!?')
                for p in _re.split(r'\bODER\b|\bOR\b|\||;', kt_raw, flags=_re.IGNORECASE)
                if len(p.strip()) >= 4
            ]
        else:
            kt_norm = []

        new_entry = {
            'name':          thesis.get('name', thesis_id),
            'type':          'paper',
            'thesis':        thesis.get('thesis', ''),
            'entry_trigger': thesis.get('entry_trigger', ''),
            'kill_trigger':  kt_norm,
            'tickers':       thesis.get('tickers', []),
            'direction':     thesis.get('direction', 'LONG'),
            'timeframe':     thesis.get('timeframe', ''),
            'confidence':    confidence,
            'status':        'active',
            'genesis': {
                'created':         today,
                'trigger':         f'Albert auto-aktiviert (Konfidenz: {confidence}%)',
                'auto_discovered': True,
            },
        }
        strategies[thesis_id] = new_entry
        atomic_write_json(STRATEGIES_JSON, strategies)
        print(f'[thesis_discovery] {thesis_id} written to strategies.json', flush=True)
    except Exception as e:
        print(f'[thesis_discovery] strategies.json write error: {e}', flush=True)
        return False

    # Update DB status
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from core.thesis_engine import set_thesis_status
        set_thesis_status(thesis_id, 'ACTIVE', f'Albert auto-aktiviert (Konfidenz: {confidence}%)')
    except Exception as e:
        print(f'[thesis_discovery] set_thesis_status error: {e}', flush=True)

    return True


# ── Store Proposed Theses ─────────────────────────────────────────────────────

def store_proposed_theses(theses: list[dict]) -> int:
    """
    Insert each thesis into thesis_status table with status='PROPOSED'.
    Also write/merge to pending_theses.json.
    Returns count of stored theses.
    """
    if not theses:
        return 0

    stored = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    # Write to DB
    try:
        if DB.exists():
            conn = sqlite3.connect(str(DB))
            try:
                for t in theses:
                    tid = t.get('id', '')
                    if not tid:
                        continue
                    notes = json.dumps(t, ensure_ascii=False)
                    existing = conn.execute(
                        "SELECT id FROM thesis_status WHERE thesis_id = ?", (tid,)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            "UPDATE thesis_status SET status = 'PROPOSED', notes = ?, updated_at = ? WHERE thesis_id = ?",
                            (notes, now_iso, tid)
                        )
                    else:
                        conn.execute(
                            """INSERT INTO thesis_status
                               (thesis_id, status, health_score, kill_trigger_fired, last_checked, notes, updated_at)
                               VALUES (?, 'PROPOSED', 100, 0, ?, ?, ?)""",
                            (tid, now_iso, notes, now_iso)
                        )
                    stored += 1
                conn.commit()
            except sqlite3.OperationalError as e:
                print(f'[thesis_discovery] DB insert error: {e}', flush=True)
            finally:
                conn.close()
        else:
            print(f'[thesis_discovery] DB not found at {DB} — skipping DB write', flush=True)
    except Exception as e:
        print(f'[thesis_discovery] DB error: {e}', flush=True)

    # Write to pending_theses.json (merge with existing)
    try:
        existing_pending: dict = {}
        if PENDING_THESES_JSON.exists():
            try:
                raw = json.loads(PENDING_THESES_JSON.read_text(encoding='utf-8'))
                if isinstance(raw, dict):
                    existing_pending = raw
                elif isinstance(raw, list):
                    existing_pending = {t.get('id', str(i)): t for i, t in enumerate(raw)}
            except Exception:
                existing_pending = {}

        for t in theses:
            tid = t.get('id', '')
            if tid:
                existing_pending[tid] = {
                    **t,
                    'status': 'PROPOSED',
                    'proposed_at': now_iso,
                }

        PENDING_THESES_JSON.write_text(
            json.dumps(existing_pending, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        print(f'[thesis_discovery] pending_theses.json updated ({len(existing_pending)} total)', flush=True)
    except Exception as e:
        print(f'[thesis_discovery] pending_theses.json write error: {e}', flush=True)

    return stored


# ── Discord Report ────────────────────────────────────────────────────────────

def send_discovery_report(theses: list[dict], headlines_count: int) -> bool:
    """
    Format and send Discord report with Albert's autonomous thesis actions.
    Returns True on success.
    """
    try:
        from discord_sender import send
    except ImportError:
        print('[thesis_discovery] discord_sender not available', flush=True)
        return False

    # Partition theses by confidence
    auto_activated = [t for t in theses if t.get('confidence', 0) >= 65]
    watching       = [t for t in theses if 50 <= t.get('confidence', 0) <= 64]
    proposed_only  = [t for t in theses if t.get('confidence', 0) < 50]

    _now_berlin = _berlin_now()
    today = _now_berlin.strftime('%d.%m.%Y')
    weekday_name = _de_weekday(_now_berlin)
    lines = [
        f'🔍 **Albert | Wöchentliche Thesen-Analyse** ({today}, {weekday_name})',
        f'Analysierte Headlines: **{headlines_count}**',
        '',
    ]

    number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']

    # AUTO-AKTIVIERT section
    if auto_activated:
        lines.append('✅ **AUTO-AKTIVIERT (Konfidenz ≥ 65%):**')
        for i, t in enumerate(auto_activated):
            num_emoji  = number_emojis[i] if i < len(number_emojis) else f'{i+1}.'
            tid        = t.get('id', '?')
            name       = t.get('name', '?')
            confidence = t.get('confidence', '?')
            lines.append(f'{num_emoji} **{tid} — {name}** ({confidence}%) → AKTIV, Albert sucht Entries')
        lines.append('')

    # BEOBACHTUNG section
    if watching:
        lines.append('👁️ **BEOBACHTUNG (Konfidenz 50-64%):**')
        offset = len(auto_activated)
        for i, t in enumerate(watching):
            num_emoji  = number_emojis[offset + i] if (offset + i) < len(number_emojis) else f'{offset+i+1}.'
            tid        = t.get('id', '?')
            name       = t.get('name', '?')
            confidence = t.get('confidence', '?')
            lines.append(f'{num_emoji} **{tid} — {name}** ({confidence}%) → WATCHING')
        lines.append('')

    # PROPOSED ONLY section
    if proposed_only:
        lines.append('📋 **VORGESCHLAGEN (Konfidenz < 50%):**')
        offset = len(auto_activated) + len(watching)
        for i, t in enumerate(proposed_only):
            num_emoji  = number_emojis[offset + i] if (offset + i) < len(number_emojis) else f'{offset+i+1}.'
            tid        = t.get('id', '?')
            name       = t.get('name', '?')
            confidence = t.get('confidence', '?')
            lines.append(f'{num_emoji} **{tid} — {name}** ({confidence}%) → gespeichert, kein Entry')
        lines.append('')

    if not theses:
        lines.append('_(Keine neuen Thesen identifiziert)_')
        lines.append('')

    lines.append('─' * 30)
    lines.append('ℹ️ Albert handelt autonom. Keine Bestätigung nötig.')
    lines.append('Zum Stoppen einer These: `Stopp: PS21`')

    full_message = '\n'.join(lines)

    # Discord has 2000 char limit — send in chunks if needed
    if len(full_message) <= 1900:
        return send(full_message)
    else:
        # Split at paragraph boundaries
        ok = True
        chunk = ''
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                ok = send(chunk) and ok
                chunk = line + '\n'
            else:
                chunk += line + '\n'
        if chunk:
            ok = send(chunk.rstrip()) and ok
        return ok


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_discovery() -> dict:
    """
    Main entry point called by scheduler or CLI.
    Returns summary dict: headlines_fetched, theses_proposed, theses_stored, errors.
    """
    errors: list[str] = []
    summary = {
        'headlines_fetched': 0,
        'theses_proposed':   0,
        'theses_stored':     0,
        'errors':            errors,
        'timestamp':         datetime.now(timezone.utc).isoformat(),
    }

    print(f'[thesis_discovery] === Weekly Thesis Discovery started ===', flush=True)

    # Step 1: Fetch news
    try:
        headlines = fetch_macro_news()
        summary['headlines_fetched'] = len(headlines)
    except Exception as e:
        errors.append(f'fetch_macro_news: {e}')
        print(f'[thesis_discovery] Error fetching news: {e}', flush=True)
        headlines = []

    if not headlines:
        errors.append('No headlines fetched — aborting discovery')
        print('[thesis_discovery] No headlines — aborting', flush=True)
        return summary

    # Step 2: Load existing theses
    try:
        existing = get_existing_theses()
        print(f'[thesis_discovery] {len(existing)} existing theses loaded', flush=True)
    except Exception as e:
        errors.append(f'get_existing_theses: {e}')
        existing = []

    # Step 3: Ask Claude
    try:
        theses = discover_theses_with_claude(headlines, existing)
        summary['theses_proposed'] = len(theses)
    except Exception as e:
        errors.append(f'discover_theses_with_claude: {e}')
        print(f'[thesis_discovery] Claude error: {e}', flush=True)
        theses = []

    # Step 4: Store proposed theses + auto-activate based on confidence
    if theses:
        try:
            stored = store_proposed_theses(theses)
            summary['theses_stored'] = stored
        except Exception as e:
            errors.append(f'store_proposed_theses: {e}')
            print(f'[thesis_discovery] Store error: {e}', flush=True)

        # Auto-activate or set watching status immediately — no confirmation needed
        for t in theses:
            confidence = t.get('confidence', 0)
            tid = t.get('id', '?')
            try:
                if confidence >= 65:
                    # Activate: write to strategies.json + set ACTIVE in DB
                    ok = _auto_activate_thesis(t)
                    print(f'[thesis_discovery] {tid} AUTO-AKTIVIERT (Konfidenz {confidence}%) — ok={ok}', flush=True)
                elif confidence >= 50:
                    # Watching: DB status only, no strategies.json entry yet
                    try:
                        import sys as _sys
                        _sys.path.insert(0, str(WS / 'scripts'))
                        from core.thesis_engine import set_thesis_status
                        set_thesis_status(tid, 'WATCHING', f'Albert: Konfidenz {confidence}% — beobachtet')
                    except Exception as e:
                        print(f'[thesis_discovery] set_thesis_status WATCHING error: {e}', flush=True)
                    print(f'[thesis_discovery] {tid} → WATCHING (Konfidenz {confidence}%)', flush=True)
                else:
                    # Below threshold — stays PROPOSED, already stored
                    print(f'[thesis_discovery] {tid} → PROPOSED only (Konfidenz {confidence}% < 50)', flush=True)
            except Exception as e:
                errors.append(f'auto_activate {tid}: {e}')
                print(f'[thesis_discovery] Auto-activate error for {tid}: {e}', flush=True)

    # Step 5: Send Discord report
    try:
        sent = send_discovery_report(theses, summary['headlines_fetched'])
        if not sent:
            errors.append('Discord report send failed')
    except Exception as e:
        errors.append(f'send_discovery_report: {e}')
        print(f'[thesis_discovery] Discord report error: {e}', flush=True)

    print(f'[thesis_discovery] === Done: {summary} ===', flush=True)
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    result = run_discovery()
    print(json.dumps(result, indent=2, ensure_ascii=False))
