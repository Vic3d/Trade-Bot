#!/usr/bin/env python3
"""
YouTube Channel-ID Resolver (6c)
Loest YouTube @handles zu UC... Channel-IDs auf via Playwright (JS-Rendering).
Speichert Ergebnisse in intelligence.db fuer trader_intel.py.

Einmalig oder bei neuem Kanal ausfuehren.
"""
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
import os

WS   = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
DB   = DATA / 'intelligence.db'

log = logging.getLogger('youtube_resolver')
logging.basicConfig(
    filename=str(DATA / 'youtube_resolver.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Bekannte Kanaele — Handle -> (Name, Channel-ID wenn bekannt)
# Channel-IDs werden automatisch aufgeloest und gecacht
CHANNELS_TO_RESOLVE = {
    '@Tradermacher':   ('tradermacher', None),
    '@finanzfluss':    ('finanzfluss', None),
    '@deraktionaer':   ('aktionaer_tv', None),
    '@markuskoch':     ('markus_koch', None),
}

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS youtube_channels (
        handle TEXT PRIMARY KEY,
        name TEXT,
        channel_id TEXT,
        resolved_at TEXT,
        last_video_id TEXT
    )""")
    conn.commit()
    return conn

def get_cached_channel_id(handle: str) -> str | None:
    """Gibt gecachte Channel-ID zurueck oder None."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT channel_id FROM youtube_channels WHERE handle=?", (handle,)
        ).fetchone()
        conn.close()
        return row['channel_id'] if row and row['channel_id'] else None
    except Exception:
        return None

def resolve_via_playwright(handle: str) -> str | None:
    """Oeffnet YouTube-Kanal mit Playwright und extrahiert Channel-ID."""
    try:
        from playwright.sync_api import sync_playwright
        import re
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                locale='de-DE',
            )
            page = ctx.new_page()
            url = f'https://www.youtube.com/{handle}/videos'
            log.info(f"Playwright: Oeffne {url}")
            page.goto(url, timeout=30000, wait_until='domcontentloaded')
            page.wait_for_timeout(3000)  # JS rendern lassen
            content = page.content()
            browser.close()

            # Channel-ID extrahieren
            m = re.search(r'"channelId":\s*"(UC[\w-]{22})"', content)
            if m:
                return m.group(1)
            # Alternate pattern
            m2 = re.search(r'"externalId":\s*"(UC[\w-]{22})"', content)
            if m2:
                return m2.group(1)
            # Video-IDs als Fallback
            videos = re.findall(r'"videoId":\s*"([\w-]{11})"', content)
            if videos:
                log.info(f"Channel-ID nicht gefunden, aber {len(videos)} Videos fuer {handle}")
                # Video-ID als Fallback speichern
                return None
            log.warning(f"Nichts gefunden fuer {handle}")
            return None
    except ImportError:
        log.warning("Playwright nicht installiert")
        return None
    except Exception as e:
        log.error(f"Playwright Fehler fuer {handle}: {e}")
        return None

def resolve_via_curl_cffi(handle: str) -> str | None:
    """Versucht Channel-ID via curl_cffi (schneller, kein Browser)."""
    try:
        from curl_cffi import requests
        import re
        url = f'https://www.youtube.com/{handle}'
        r = requests.get(url, impersonate='chrome124', timeout=15)
        patterns = [
            r'"channelId":\s*"(UC[\w-]{22})"',
            r'"externalId":\s*"(UC[\w-]{22})"',
            r'channel/(UC[\w-]{22})',
        ]
        for pat in patterns:
            m = re.search(pat, r.text)
            if m:
                return m.group(1)
        return None
    except Exception as e:
        log.warning(f"curl_cffi Fehler fuer {handle}: {e}")
        return None

def resolve_channel(handle: str, name: str) -> str | None:
    """Loest Channel-ID auf — versucht curl_cffi zuerst, dann Playwright."""
    cached = get_cached_channel_id(handle)
    if cached:
        log.info(f"{handle}: gecacht als {cached}")
        return cached

    log.info(f"{handle}: Starte Auflosung...")

    # Tier 1: curl_cffi
    cid = resolve_via_curl_cffi(handle)
    if not cid:
        # Tier 2: Playwright
        cid = resolve_via_playwright(handle)

    # In DB speichern
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO youtube_channels (handle, name, channel_id, resolved_at) VALUES (?,?,?,?)",
            (handle, name, cid, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"DB-Fehler beim Speichern von {handle}: {e}")

    if cid:
        log.info(f"{handle} -> {cid}")
    else:
        log.warning(f"{handle}: Nicht aufgeloest")
    return cid

def resolve_all() -> dict:
    """Loest alle konfigurierten Kanaele auf. Gibt {handle: channel_id} zurueck."""
    results = {}
    for handle, (name, _known_id) in CHANNELS_TO_RESOLVE.items():
        cid = resolve_channel(handle, name)
        results[handle] = cid
    return results

def get_all_resolved() -> dict:
    """Gibt alle gecachten Channel-IDs zurueck {name: channel_id}."""
    try:
        conn = _get_db()
        rows = conn.execute("SELECT handle, name, channel_id FROM youtube_channels WHERE channel_id IS NOT NULL").fetchall()
        conn.close()
        return {r['name']: r['channel_id'] for r in rows}
    except Exception:
        return {}

def patch_trader_intel_channels():
    """
    Aktualisiert YOUTUBE_CHANNELS in trader_intel.py mit aufgeloesten IDs.
    Wird nach resolve_all() aufgerufen.
    """
    resolved = get_all_resolved()
    if not resolved:
        log.warning("Keine aufgeloesten Channel-IDs vorhanden")
        return

    ti_file = WS / 'scripts/core/trader_intel.py'
    if not ti_file.exists():
        return

    s = ti_file.read_text(encoding='utf-8')

    # Baue neuen YOUTUBE_CHANNELS Dict
    new_dict_lines = ['YOUTUBE_CHANNELS = {\n']
    for name, cid in resolved.items():
        new_dict_lines.append(f"    '{name}': '{cid}',\n")
    new_dict_lines.append('}\n')
    new_dict = ''.join(new_dict_lines)

    import re
    # Ersetze bestehenden Dict
    s_new = re.sub(
        r'YOUTUBE_CHANNELS\s*=\s*\{[^}]+\}',
        new_dict.rstrip('\n'),
        s,
        count=1
    )
    if s_new != s:
        ti_file.write_text(s_new, encoding='utf-8')
        log.info(f"trader_intel.py aktualisiert mit {len(resolved)} Channel-IDs")
        print(f"trader_intel.py: {len(resolved)} Channel-IDs eingefuegt")
    else:
        log.warning("YOUTUBE_CHANNELS Pattern nicht gefunden in trader_intel.py")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--resolve', action='store_true', help='Alle Kanaele aufloesen')
    parser.add_argument('--show', action='store_true', help='Gecachte IDs anzeigen')
    parser.add_argument('--patch', action='store_true', help='trader_intel.py aktualisieren')
    args = parser.parse_args()

    if args.resolve or (not args.show and not args.patch):
        print("Loese YouTube Channel-IDs auf...")
        results = resolve_all()
        for handle, cid in results.items():
            print(f"  {handle:30s} -> {cid or 'NICHT GEFUNDEN'}")

    if args.patch:
        patch_trader_intel_channels()

    if args.show:
        cached = get_all_resolved()
        print("Gecachte Channel-IDs:")
        for name, cid in cached.items():
            print(f"  {name}: {cid}")
