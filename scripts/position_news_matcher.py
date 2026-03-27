"""
position_news_matcher.py — Zweistufiger News-Alert für aktive Positionen + Watchlist

Features:
  - Stufe 1: Keyword-Filter (schnell, kein LLM)
  - Deduplication: gesendete Headlines werden gecacht (TTL 48h)
  - Severity: CRITICAL / IMPORTANT / INFO
  - Watchlist-Monitoring (Entry-Signal-relevante Events)

Output:
  KEIN_SIGNAL                      — nichts Neues
  CANDIDATES: [json]               — neue Keyword-Treffer für LLM-Check im Cron
"""

import json
import hashlib
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
CACHE_PATH = WS / 'memory/news-alert-cache.json'
CACHE_TTL_H = 48  # Stunden bis eine Headline wieder gemeldet werden darf

# ─── Severity-Keywords ────────────────────────────────────────────────────────
# CRITICAL: sofortiger Alert, egal wann
# IMPORTANT: Alert im nächsten Check
# INFO: Tagessammlung, kein Einzelalert
SEVERITY_KEYWORDS = {
    "CRITICAL": [
        "ceasefire", "waffenstillstand", "peace deal", "friedensvertrag",
        "hormuz closed", "hormuz blockade", "strait closed",
        "oil embargo", "sanctions lifted", "sanktionen aufgehoben",
        "ground troops", "bodentruppen", "boots on the ground", "invasion begins",
        "nuclear", "atomar", "dirty bomb",
        "market halt", "trading suspended", "circuit breaker",
        "fda breakthrough", "fda fast track", "fda approved",
        "major contract", "billion contract"
    ],
    "IMPORTANT": [
        "marines", "aircraft carrier", "amphibious", "military strike",
        "oil +5", "oil -5", "brent +5", "brent -5",
        "opec cut", "opec increase", "production cut",
        "de-escalat", "escalat", "troop",
        "earnings beat", "earnings miss", "revenue surprise",
        "phase 3", "clinical trial results", "drug approved",
        "government contract", "defense contract"
    ]
    # Alles andere = INFO → wird gesammelt aber kein Einzelalert
}

# ─── Position-Konfiguration ───────────────────────────────────────────────────
POSITION_CONFIG = {
    "PLTR": {
        "name": "Palantir",
        "thesis": "US-Regierungsaufträge + KI-Defense profitiert von Militärausgaben",
        "keywords": [
            "palantir", "pltr", "alex karp", "government contract", "defense ai",
            "ai surveillance", "military ai", "doge spending", "us defense budget",
            "pentagon ai", "nato ai", "anduril", "ai software contract"
        ],
        "queries": ["Palantir PLTR contract defense AI", "Palantir government AI military"]
    },
    "EQNR": {
        "name": "Equinor ASA",
        "thesis": "Ölpreis steigt durch Iran-Krise / Hormuz — Equinor als europäischer Öl-Profiteur",
        "keywords": [
            "equinor", "eqnr", "iran", "hormuz", "strait of hormuz",
            "opec", "oil price", "brent crude", "crude oil", "wti",
            "oil sanction", "oil embargo", "marines", "bodentruppen", "ground troops",
            "ceasefire", "waffenstillstand", "de-escalat", "peace talks",
            "aircraft carrier", "amphibious", "iran attack", "iran war",
            "iran nuclear", "military strike iran"
        ],
        "queries": ["Iran Hormuz oil military troops", "Equinor EQNR oil price OPEC"]
    },
    "A3D42Y": {
        "name": "VanEck Oil Services ETF",
        "thesis": "Öl-Services profitieren von hohem Ölpreis + Explorationsausgaben",
        "keywords": [
            "oil services", "oilfield", "halliburton", "schlumberger", "slb",
            "baker hughes", "oil rig", "drilling", "offshore oil", "upstream",
            "oil capex", "exploration", "opec production",
            "iran", "hormuz", "brent", "crude oil"
        ],
        "queries": ["oil services drilling OPEC upstream", "oilfield services exploration"]
    },
    "A2DWAW": {
        "name": "iShares Biotech ETF",
        "thesis": "Biotech-Aufholpotenzial — FDA-Approvals als Katalysator",
        "keywords": [
            "biotech", "fda approval", "fda approves", "drug approval", "fda cleared",
            "biopharmaceutical", "clinical trial", "phase 3", "breakthrough therapy",
            "nasdaq biotech", "healthcare regulation", "medicare drug",
            "gene therapy", "immunotherapy"
        ],
        "queries": ["biotech FDA approval drug clinical", "NASDAQ biotech ETF biopharma"]
    }
}

# ─── Watchlist-Konfiguration ──────────────────────────────────────────────────
WATCHLIST_CONFIG = {
    "RHM.DE": {
        "name": "Rheinmetall AG",
        "thesis": "Re-Entry bei >1.626€ + Volumen — Rüstungsausgaben Europa",
        "keywords": [
            "rheinmetall", "rhm", "rüstung", "defense spending", "nato budget",
            "germany defense", "bundeswehr", "ukraine weapons", "european rearmament"
        ],
        "queries": ["Rheinmetall defense Germany NATO"]
    },
    "AG": {
        "name": "First Majestic Silver",
        "thesis": "Silberpreis-Rebound — Entry nur nach Reversal-Kerze",
        "keywords": [
            "first majestic", "silver price", "silberpreis", "silver rally",
            "silver demand", "gold silver", "precious metals", "ag stock"
        ],
        "queries": ["silver price gold precious metals rally"]
    },
    "ASML.AS": {
        "name": "ASML Holding",
        "thesis": "EMA50-Rücklauf ~1.160€ als Entry — Chip-Monopol",
        "keywords": [
            "asml", "euv lithography", "chip equipment", "semiconductor equipment",
            "export ban chips", "china chips", "tsmc production"
        ],
        "queries": ["ASML semiconductor chip equipment EUV"]
    },
    "LHA.DE": {
        "name": "Lufthansa AG (S10 — Post-War Watch)",
        "thesis": "KEIN KAUF JETZT. Entry nur bei: Iran-Waffenstillstand + Brent < 75$ + EMA-Ausbruch. KGV 6 = antizyklisch günstig.",
        "keywords": [
            "iran ceasefire", "iran waffenstillstand", "iran peace", "iran deal",
            "hormuz reopened", "middle east peace", "iran nuclear agreement",
            "brent falls below 75", "oil price drop", "crude oil plunge",
            "lufthansa recovery", "airline stocks rally", "lufthansa earnings",
            "kerosene price drop", "jet fuel falls"
        ],
        "queries": [
            "Iran ceasefire peace deal Hormuz",
            "Lufthansa Aktie Erholung",
            "oil price drop Brent 75"
        ]
    }
}


def load_cache():
    """Cache laden (headline_hash → timestamp)."""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache):
    """Cache speichern."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Abgelaufene Einträge bereinigen
    now = time.time()
    cache = {k: v for k, v in cache.items() if now - v < CACHE_TTL_H * 3600}
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def headline_hash(headline):
    """Stabiler Hash für eine Headline."""
    return hashlib.md5(headline.lower().strip().encode()).hexdigest()[:12]


def is_new(headline, cache):
    """True wenn die Headline noch nicht im Cache ist."""
    h = headline_hash(headline)
    return h not in cache


def mark_seen(headline, cache):
    """Headline als gesehen markieren."""
    h = headline_hash(headline)
    cache[h] = time.time()


def get_severity(headline):
    """Severity-Stufe für eine Headline bestimmen."""
    hl = headline.lower()
    for kw in SEVERITY_KEYWORDS["CRITICAL"]:
        if kw.lower() in hl:
            return "CRITICAL"
    for kw in SEVERITY_KEYWORDS["IMPORTANT"]:
        if kw.lower() in hl:
            return "IMPORTANT"
    return "INFO"


def fetch_rss(query, max_items=8):
    """Google News RSS abrufen."""
    q = urllib.parse.quote(query)
    url = f'https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.findall('.//item')[:max_items]:
            title = item.findtext('title', '').strip()
            source = item.findtext('source', '').strip()
            pub = item.findtext('pubDate', '').strip()
            if title:
                items.append({'title': title, 'source': source, 'pubDate': pub})
        return items
    except Exception:
        return []


def scan_config(config_dict, kind='position'):
    """Konfiguration scannen und Kandidaten sammeln."""
    cache = load_cache()
    candidates = []
    seen_titles = set()

    for key, cfg in config_dict.items():
        headlines = []
        for query in cfg['queries']:
            headlines.extend(fetch_rss(query, max_items=6))

        for item in headlines:
            title = item['title']
            if title in seen_titles:
                continue
            seen_titles.add(title)

            # Keyword-Match
            title_lower = title.lower()
            matched = [kw for kw in cfg['keywords'] if kw.lower() in title_lower]
            if not matched:
                continue

            # Deduplication
            if not is_new(title, cache):
                continue

            severity = get_severity(title)

            candidates.append({
                'kind': kind,
                'ticker': key,
                'name': cfg['name'],
                'thesis': cfg['thesis'],
                'headline': title,
                'source': item.get('source', ''),
                'pub': item.get('pubDate', ''),
                'matched_keywords': matched[:3],
                'severity': severity
            })

    # Cache erst nach erfolgreicher Verarbeitung speichern
    # (wird im Cron nach dem LLM-Check aufgerufen)
    return candidates, cache


def mark_all_seen(candidates, cache):
    """Alle Kandidaten als gesehen markieren und Cache speichern."""
    for c in candidates:
        mark_seen(c['headline'], cache)
    save_cache(cache)


def run_matcher():
    """Hauptfunktion: Positionen + Watchlist scannen."""
    position_candidates, cache = scan_config(POSITION_CONFIG, kind='position')
    watchlist_candidates, _ = scan_config(WATCHLIST_CONFIG, kind='watchlist')

    # Watchlist nutzt denselben Cache
    all_candidates = position_candidates + watchlist_candidates

    # Cache aktualisieren (alle gefundenen Kandidaten als gesehen markieren)
    if all_candidates:
        mark_all_seen(all_candidates, cache)

    return all_candidates


if __name__ == '__main__':
    candidates = run_matcher()

    if candidates:
        # Severity-Statistik
        crit = [c for c in candidates if c['severity'] == 'CRITICAL']
        imp = [c for c in candidates if c['severity'] == 'IMPORTANT']
        info = [c for c in candidates if c['severity'] == 'INFO']

        print(f"CANDIDATES: {json.dumps(candidates, ensure_ascii=False)}")
        print(f"\n--- {len(candidates)} neue Kandidaten ---")
        print(f"  🔴 CRITICAL: {len(crit)}")
        print(f"  🟡 IMPORTANT: {len(imp)}")
        print(f"  ⚪ INFO: {len(info)}")
        for c in candidates:
            sev_icon = {'CRITICAL': '🔴', 'IMPORTANT': '🟡', 'INFO': '⚪'}.get(c['severity'], '⚪')
            kind_label = f"[{c['kind'].upper()}]"
            print(f"  {sev_icon} {kind_label} {c['ticker']}: {c['headline'][:70]}")
    else:
        print("KEIN_SIGNAL")
