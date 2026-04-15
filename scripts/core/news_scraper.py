"""
news_scraper.py — Multi-tier news scraper for TradeMind autonomous trading bot.

Tier 1: curl_cffi with Chrome TLS fingerprint (fast, no browser)
Tier 2: Playwright + playwright_stealth (JS-heavy / Cloudflare-protected sites)
Auto-tier: tries Tier 1 first, falls back to Tier 2 if blocked.

Cache: SQLite at /opt/trademind/data/news_cache.db (7-day TTL)
Rate limit: 1 req per 2-4s per domain, rotating user-agents.
"""

import json
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, urlencode, quote_plus

# --- Optional heavy deps — graceful degradation ---
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = "/opt/trademind/data/news_cache.db"
LOG_PATH = "/opt/trademind/data/scraper.log"
CACHE_TTL_DAYS = 7
MIN_DELAY = 2.0   # seconds between requests to same domain
MAX_DELAY = 4.0

# Domain → preferred tier (1 = curl_cffi, 2 = playwright)
DOMAINS = {
    "bloomberg.com": 2,
    "reuters.com": 1,
    "ft.com": 2,
    "wsj.com": 2,
    "cnbc.com": 1,
    "marketwatch.com": 1,
    "investing.com": 1,
    "yahoo.com": 1,
    "finanzen.net": 1,
    "boerse-frankfurt.de": 1,
    "ariva.de": 1,
    "handelsblatt.com": 2,
    "nikkei.com": 2,
    "scmp.com": 1,
    "finnhub.io": 1,
    "macrotrends.net": 1,
    "stockanalysis.com": 1,
    "sec.gov": 1,
}

USER_AGENTS = [
    # Chrome 124 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox 125 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Safari 17 Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Known tickers to scan for — extend at runtime via scraper config
DEFAULT_TICKERS = [
    # US large cap
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC",
    "JPM", "BAC", "GS", "MS", "V", "MA", "PFE", "NVO", "LLY", "ABBV",
    "PLTR", "SMCI", "ARM", "ASML",
    # German / European
    "SIE.DE", "RHM.DE", "SAP.DE", "BMW.DE", "MBG.DE", "BAYN.DE",
    "ALV.DE", "DBK.DE", "VOW3.DE", "ADS.DE", "IFX.DE",
    # ETFs / indices
    "QQQ", "SPY", "KWEB", "EWJ", "EWZ",
    # Crypto proxies
    "COIN", "MSTR", "MARA",
]

# Google News RSS base
GNEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# Domains protected by DataDome → fetch via Google Cache instead
CACHE_DOMAINS = {'reuters.com', 'cnbc.com', 'wsj.com'}

# Bing News RSS searches for Reuters — extract real reuters.com URLs from Bing redirect
# feeds.reuters.com is discontinued; Bing News encodes actual Reuters URLs in &url= param
REUTERS_BING_QUERIES = [
    "site:reuters.com markets finance",
    "site:reuters.com business economy",
    "site:reuters.com technology",
]

# Thematic keyword → ticker mapping (for headline-only enrichment)
KEYWORD_TICKER_MAP: dict[str, list[str]] = {
    'hormuz': ['OXY', 'FRO', 'DHT', 'EURN'],
    'iran': ['OXY', 'FRO', 'DHT'],
    'oil': ['OXY', 'XOM', 'CVX', 'TTE.PA', 'EQNR', 'SHEL.L'],
    'tanker': ['FRO', 'DHT', 'EURN', 'TK'],
    'lng': ['EQNR', 'CVX', 'TTE.PA'],
    'crude': ['OXY', 'XOM', 'CVX'],
    'opec': ['OXY', 'XOM', 'CVX', 'EQNR'],
    'ruestung': ['RHM.DE', 'AIR.PA', 'LMT', 'RTX'],
    'verteidigung': ['RHM.DE', 'AIR.PA', 'LMT', 'RTX'],
    'defense': ['RHM.DE', 'LMT', 'RTX', 'NOC', 'GD'],
    'ukraine': ['RHM.DE', 'AIR.PA'],
    'halbleiter': ['NVDA', 'AMD', 'INTC', 'ASML', 'IFX.DE'],
    'semiconductor': ['NVDA', 'AMD', 'INTC', 'ASML'],
    'chip': ['NVDA', 'AMD', 'INTC', 'ASML', 'IFX.DE'],
    'ki': ['NVDA', 'MSFT', 'GOOGL', 'META'],
    'artificial intelligence': ['NVDA', 'MSFT', 'GOOGL', 'META', 'AMD'],
    'pharma': ['NVO', 'LLY', 'ABBV', 'PFE', 'BAYN.DE'],
    'trump': ['OXY', 'NVO', 'LLY'],
    'zoll': ['BMW.DE', 'MBG.DE', 'VOW3.DE'],
    'tariff': ['BMW.DE', 'MBG.DE', 'TSLA'],
    'bitcoin': ['COIN', 'MSTR', 'MARA'],
    'crypto': ['COIN', 'MSTR', 'MARA'],
    'china': ['KWEB', 'BABA', 'JD', 'NIO'],
    'fed': ['JPM', 'BAC', 'GS'],
    'zinsen': ['JPM', 'BAC', 'ALV.DE'],
    'interest rate': ['JPM', 'BAC', 'GS'],
}


def get_filtered_keyword_map() -> dict[str, list[str]]:
    """
    Phase 20: Gibt KEYWORD_TICKER_MAP zurück, gefiltert gegen das Universum.
    Dormant/blocked Tickers werden aus dem Mapping entfernt — verhindert
    dass News-Events sie immer wieder triggern.

    Fallback: wenn Universum nicht ladbar → unveränderte Original-Map.
    """
    try:
        import sys as _s
        from pathlib import Path as _P
        _scripts = _P(__file__).resolve().parent.parent
        if str(_scripts) not in _s.path:
            _s.path.insert(0, str(_scripts))
        from core.universe import load_universe, SCANNABLE_STATUSES
        u = load_universe()
        if not u:
            return dict(KEYWORD_TICKER_MAP)
        allowed = {t for t, v in u.items() if v.get('status') in SCANNABLE_STATUSES}
        filtered: dict[str, list[str]] = {}
        for kw, tickers in KEYWORD_TICKER_MAP.items():
            keep = [t for t in tickers if t in allowed or t not in u]
            if keep:
                filtered[kw] = keep
        return filtered
    except Exception:
        return dict(KEYWORD_TICKER_MAP)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("news_scraper")


# ---------------------------------------------------------------------------
# Rate limiter — per-domain last-request timestamp
# ---------------------------------------------------------------------------

_last_request: dict[str, float] = {}


def _rate_limit(domain: str) -> None:
    """Block until the per-domain rate limit window has elapsed."""
    now = time.monotonic()
    wait_until = _last_request.get(domain, 0) + random.uniform(MIN_DELAY, MAX_DELAY)
    sleep_for = wait_until - now
    if sleep_for > 0:
        time.sleep(sleep_for)
    _last_request[domain] = time.monotonic()


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return a connection to the article cache DB, creating schema if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_cache (
            url           TEXT PRIMARY KEY,
            fetched_at    TEXT,
            title         TEXT,
            text          TEXT,
            published     TEXT,
            source        TEXT,
            tickers_found TEXT
        )
    """)
    conn.commit()
    return conn


def get_cached(url: str) -> Optional[dict]:
    """
    Return cached article dict if it exists and is within the 7-day TTL.
    Returns None if missing or expired.
    """
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM article_cache WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at > timedelta(days=CACHE_TTL_DAYS):
            conn.execute("DELETE FROM article_cache WHERE url = ?", (url,))
            conn.commit()
            return None
        return {
            "url": row["url"],
            "fetched_at": row["fetched_at"],
            "title": row["title"],
            "text": row["text"],
            "published": row["published"],
            "source": row["source"],
            "tickers_found": json.loads(row["tickers_found"] or "[]"),
        }
    except Exception as exc:
        log.error("get_cached(%s): %s", url, exc)
        return None


def _save_cache(article: dict) -> None:
    """Upsert an article dict into the cache."""
    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO article_cache
                (url, fetched_at, title, text, published, source, tickers_found)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.get("url", ""),
                article.get("fetched_at", datetime.now(timezone.utc).isoformat()),
                article.get("title", ""),
                article.get("text", ""),
                article.get("published", ""),
                article.get("source", ""),
                json.dumps(article.get("tickers_found", [])),
            ),
        )
        conn.commit()
    except Exception as exc:
        log.error("_save_cache: %s", exc)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text_trafilatura(html: str) -> str:
    """Use trafilatura for main-content extraction."""
    if not HAS_TRAFILATURA:
        return ""
    try:
        result = trafilatura.extract(html, include_comments=False, include_tables=False)
        return result or ""
    except Exception as exc:
        log.warning("trafilatura extract failed: %s", exc)
        return ""


def _extract_text_bs4(html: str) -> str:
    """Fallback: strip tags with BeautifulSoup."""
    if not HAS_BS4:
        # Minimal regex strip
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except Exception as exc:
        log.warning("bs4 extract failed: %s", exc)
        return ""


def _extract_text(html: str) -> str:
    """Try trafilatura first, then bs4 fallback."""
    text = _extract_text_trafilatura(html)
    if len(text) < 200:
        text = _extract_text_bs4(html)
    return text


def _extract_title(html: str) -> str:
    """Pull <title> tag from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    if HAS_BS4:
        try:
            soup = BeautifulSoup(html, "html.parser")
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                return og["content"].strip()
        except Exception:
            pass
    return ""


def _extract_published(html: str) -> str:
    """Best-effort publish date extraction from meta tags."""
    patterns = [
        r'<meta[^>]+(?:name|property)=["\'](?:article:published_time|publishedDate|date)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# Ticker detection
# ---------------------------------------------------------------------------

def find_tickers(text: str, ticker_list: list[str] = None) -> list[str]:
    """
    Scan text for known ticker symbols.
    Handles US tickers (NVDA) and German format (SIE.DE).
    Returns deduplicated list of matched tickers.
    """
    tickers = ticker_list or DEFAULT_TICKERS
    found = set()
    for ticker in tickers:
        # For German tickers like SIE.DE, match "SIE.DE" literally
        # For US tickers, match as standalone word (\b boundary)
        escaped = re.escape(ticker)
        pattern = r"\b" + escaped + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            found.add(ticker.upper())
    return sorted(found)


# ---------------------------------------------------------------------------
# Tier 1: curl_cffi fetch
# ---------------------------------------------------------------------------

def fetch(url: str, ticker_list: list[str] = None) -> dict:
    """
    Fetch a URL using curl_cffi with Chrome TLS fingerprint (Tier 1).

    Returns dict with keys: url, title, text, published, source, fetched_at, tickers_found.
    Returns empty dict on any error — never raises.
    """
    cached = get_cached(url)
    if cached:
        return cached

    if not HAS_CURL_CFFI:
        log.warning("curl_cffi not available, falling back to fetch_stealth for %s", url)
        return fetch_stealth(url, ticker_list=ticker_list)

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    _rate_limit(domain)

    try:
        resp = cffi_requests.get(
            url,
            impersonate="chrome124",
            headers={"User-Agent": _random_ua(), "Accept-Language": "en-US,en;q=0.9,de;q=0.8"},
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code in (403, 429, 503):
            log.info("Tier 1 blocked (%s) for %s — trying stealth", resp.status_code, url)
            return fetch_stealth(url, ticker_list=ticker_list)

        html = resp.text
        title = _extract_title(html)
        text = _extract_text(html)
        published = _extract_published(html)
        tickers_found = find_tickers(text + " " + title, ticker_list)

        article = {
            "url": url,
            "title": title,
            "text": text,
            "published": published,
            "source": domain,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "tickers_found": tickers_found,
        }
        _save_cache(article)
        return article

    except Exception as exc:
        log.error("fetch(%s): %s", url, exc)
        return {}


# ---------------------------------------------------------------------------
# Tier 2: Playwright stealth fetch
# ---------------------------------------------------------------------------

def fetch_stealth(url: str, ticker_list: list[str] = None) -> dict:
    """
    Fetch a URL using Playwright + playwright_stealth (Tier 2).
    Suitable for JS-heavy / Cloudflare-protected sites.

    Returns dict with same keys as fetch(). Returns empty dict on error.
    """
    cached = get_cached(url)
    if cached:
        return cached

    if not HAS_PLAYWRIGHT:
        log.error("Playwright not installed — cannot stealth-fetch %s", url)
        return {}

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    _rate_limit(domain)

    try:
        # Import stealth plugin — optional
        try:
            from playwright_stealth import stealth_sync
            has_stealth = True
        except ImportError:
            has_stealth = False

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(
                user_agent=_random_ua(),
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9,de;q=0.8"},
            )
            page = ctx.new_page()
            if has_stealth:
                stealth_sync(page)

            page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            # Extra wait for JS-rendered content
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass

            html = page.content()
            browser.close()

        title = _extract_title(html)
        text = _extract_text(html)
        published = _extract_published(html)
        tickers_found = find_tickers(text + " " + title, ticker_list)

        article = {
            "url": url,
            "title": title,
            "text": text,
            "published": published,
            "source": domain,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "tickers_found": tickers_found,
        }
        _save_cache(article)
        return article

    except Exception as exc:
        log.error("fetch_stealth(%s): %s", url, exc)
        return {}


# ---------------------------------------------------------------------------
# Auto-tier dispatcher
# ---------------------------------------------------------------------------

def _auto_fetch(url: str, ticker_list: list[str] = None) -> dict:
    """
    Choose tier based on domain whitelist, auto-fallback to Tier 2 if Tier 1 blocked.
    DataDome-protected sites (reuters.com, cnbc.com, wsj.com) go via Google Cache (Tier 3).
    """
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    # Tier 3: Google Cache for DataDome-protected domains
    for cache_domain in CACHE_DOMAINS:
        if domain.endswith(cache_domain):
            return fetch_via_google_cache(url, ticker_list=ticker_list)

    # Match against known domain entries (check if any key is suffix of domain)
    preferred = 1
    for known_domain, tier in DOMAINS.items():
        if domain.endswith(known_domain):
            preferred = tier
            break

    if preferred == 2:
        return fetch_stealth(url, ticker_list=ticker_list)
    else:
        return fetch(url, ticker_list=ticker_list)


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def scrape_domain(domain: str, path: str, ticker_list: list[str] = None) -> dict:
    """
    Convenience wrapper — constructs full URL from domain + path and fetches it.

    Example:
        scrape_domain('reuters.com', '/business/finance/some-article')
    """
    if not path.startswith("/"):
        path = "/" + path
    url = f"https://{domain}{path}"
    return _auto_fetch(url, ticker_list=ticker_list)


# ---------------------------------------------------------------------------
# Google News RSS search
# ---------------------------------------------------------------------------

def search_news(
    query: str,
    tickers: list[str] = None,
    days: int = 3,
    max_results: int = 20,
) -> list[dict]:
    """
    Search Google News RSS for query, return list of article dicts.

    Each dict contains: url, title, published, source, tickers_found, text.
    Text is fetched lazily — only articles whose domain is in DOMAINS whitelist
    get full-text fetched; others return with empty text to stay within rate limits.

    Args:
        query:      Search query string.
        tickers:    Optional ticker list to scan for (defaults to DEFAULT_TICKERS).
        days:       Only return articles published within last N days.
        max_results: Cap on number of articles returned.
    """
    import xml.etree.ElementTree as ET

    rss_url = GNEWS_RSS.format(query=quote_plus(query))
    results = []

    try:
        if HAS_CURL_CFFI:
            resp = cffi_requests.get(
                rss_url,
                impersonate="chrome124",
                headers={"User-Agent": _random_ua()},
                timeout=15,
            )
            rss_text = resp.text
        else:
            import urllib.request
            with urllib.request.urlopen(rss_url, timeout=15) as r:
                rss_text = r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("search_news RSS fetch failed (%s): %s", query, exc)
        return []

    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError as exc:
        log.error("search_news RSS parse failed: %s", exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for item in root.iter("item"):
        if len(results) >= max_results:
            break

        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        source_el = item.find("source")

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        pub_raw = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
        source = source_el.text.strip() if source_el is not None and source_el.text else ""

        if not link:
            continue

        # Parse publish date
        pub_dt = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                pub_dt = datetime.strptime(pub_raw, fmt)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

        if pub_dt and pub_dt < cutoff:
            continue

        # Resolve Google News redirect URL — the link in RSS is a Google redirect
        # We keep it as-is; fetch() will follow redirects.
        parsed = urlparse(link)
        domain = parsed.netloc.replace("www.", "")

        # Only full-text fetch whitelisted domains
        in_whitelist = any(domain.endswith(d) for d in DOMAINS)
        tickers_in_title = find_tickers(title, tickers)

        article = {
            "url": link,
            "title": title,
            "published": pub_dt.isoformat() if pub_dt else pub_raw,
            "source": source or domain,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "tickers_found": tickers_in_title,
            "text": "",
        }

        if in_whitelist:
            full = _auto_fetch(link, ticker_list=tickers)
            if full:
                article.update(full)

        results.append(article)

    log.info("search_news('%s'): %d results (days=%d)", query, len(results), days)
    return results


# ---------------------------------------------------------------------------
# Keyword-based ticker enrichment
# ---------------------------------------------------------------------------

def _enrich_tickers_from_keywords(text: str, existing: list[str]) -> list[str]:
    """Adds tickers found via KEYWORD_TICKER_MAP to an existing ticker list.
    Phase 20: Nutzt get_filtered_keyword_map() — dormant Tickers werden
    ausgefiltert."""
    found = set(existing)
    text_lower = text.lower()
    kw_map = get_filtered_keyword_map()
    for keyword, tickers in kw_map.items():
        if keyword in text_lower:
            found.update(tickers)
    return sorted(found)


# ---------------------------------------------------------------------------
# Tier 3: Google Cache (for DataDome-protected sites like Reuters/CNBC)
# ---------------------------------------------------------------------------

def _fetch_via_wayback(url: str) -> tuple[str, str]:
    """
    Fetch most recent Wayback Machine snapshot of a URL.
    Returns (html, final_url) or ("", "") on failure.
    No EU consent wall unlike Google Cache.
    """
    if not HAS_CURL_CFFI:
        return "", ""
    try:
        # Check for available snapshot first (CDX API)
        cdx_url = (
            "https://archive.org/wayback/available?url=" + url
        )
        _rate_limit("archive.org")
        cdx_resp = cffi_requests.get(
            cdx_url, impersonate="chrome124", timeout=10
        )
        if cdx_resp.status_code == 200:
            import json as _j
            cdx_data = _j.loads(cdx_resp.text)
            snap = cdx_data.get("archived_snapshots", {}).get("closest", {})
            if snap.get("available") and snap.get("url"):
                snap_url = snap["url"]
                log.info("Wayback snapshot: %s", snap_url)
                _rate_limit("web.archive.org")
                resp = cffi_requests.get(
                    snap_url,
                    impersonate="chrome124",
                    headers={"User-Agent": _random_ua()},
                    timeout=20,
                    allow_redirects=True,
                )
                if resp.status_code == 200 and len(resp.text) > 2000:
                    return resp.text, snap_url
    except Exception as exc:
        log.warning("_fetch_via_wayback(%s): %s", url, exc)
    return "", ""


def fetch_via_google_cache(url: str, ticker_list: list[str] = None) -> dict:
    """
    Fetch a Reuters/CNBC/WSJ article bypassing DataDome.

    Strategy:
    1. Google Cache (webcache.googleusercontent.com) — fast but shows EU consent from DE IPs
    2. Wayback Machine (archive.org) — no consent wall, has most major Reuters articles

    Falls back to empty dict if both fail.
    """
    cached = get_cached(url)
    if cached:
        return cached

    if not HAS_CURL_CFFI:
        log.error("curl_cffi not available for cache fetch of %s", url)
        return {}

    html = ""
    fetch_source = ""

    # --- Strategy 1: Google Cache with consent cookie ---
    cache_url = "https://webcache.googleusercontent.com/search?q=cache:" + url
    _rate_limit("webcache.googleusercontent.com")

    try:
        resp = cffi_requests.get(
            cache_url,
            impersonate="chrome124",
            headers={
                "User-Agent": _random_ua(),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/",
                # Bypass EU GDPR consent wall
                "Cookie": "SOCS=CAI; CONSENT=YES+DE.en+20230811-14-0; NID=511=test",
            },
            timeout=20,
            allow_redirects=True,
        )

        if resp.status_code == 200 and len(resp.text) > 2000:
            # Check if we got the consent wall instead of the article
            consent_markers = [
                "Bevor Sie zu Google weitergehen",
                "Before you continue to Google",
                "consent.google.com",
                "accounts.google.com/signin",
                "trouble accessing Google Search",
                "Hilfe zur Barrierefreiheit",
                "Feedback zur Barrierefreiheit",
                "google.com/sorry",
            ]
            is_consent_wall = any(m in resp.text for m in consent_markers)
            if not is_consent_wall:
                html = resp.text
                fetch_source = "google_cache"
                log.info("Google Cache OK: %d bytes for %s", len(html), url)
            else:
                log.info("Google Cache consent wall — trying Wayback for %s", url)
        else:
            log.warning("Google Cache HTTP %s for %s", resp.status_code, url)

    except Exception as exc:
        log.warning("Google Cache attempt failed for %s: %s", url, exc)

    # --- Strategy 2: 12ft.io paywall proxy ---
    if not html:
        try:
            proxy_url = "https://12ft.io/proxy?q=" + url
            _rate_limit("12ft.io")
            pr = cffi_requests.get(
                proxy_url,
                impersonate="chrome124",
                headers={"User-Agent": _random_ua()},
                timeout=20,
                allow_redirects=True,
            )
            if pr.status_code == 200 and len(pr.text) > 3000:
                # 12ft.io wraps content in an iframe or directly serves it
                blocking_markers = [
                    "trouble accessing", "Error", "blocked", "captcha",
                    "Bevor Sie", "Before you continue",
                ]
                if not any(m.lower() in pr.text[:500].lower() for m in blocking_markers):
                    html = pr.text
                    fetch_source = "12ft"
                    log.info("12ft.io OK: %d bytes for %s", len(html), url)
        except Exception as exc:
            log.warning("12ft.io failed for %s: %s", url, exc)

    # --- Strategy 3: Wayback Machine (last resort) ---
    if not html:
        wb_html, wb_url = _fetch_via_wayback(url)
        if wb_html:
            html = wb_html
            fetch_source = "wayback"
            log.info("Wayback Machine OK: %d bytes for %s", len(html), url)

    if not html:
        log.warning("All cache strategies failed for %s", url)
        return {}

    try:
        # Extract real article title — prefer og:title over <title> (which shows "cache:URL")
        title = ""
        if HAS_BS4:
            try:
                soup_t = BeautifulSoup(html, "html.parser")
                og = soup_t.find("meta", property="og:title")
                if og and og.get("content"):
                    title = og["content"].strip()
                if not title:
                    h1 = soup_t.find("h1")
                    if h1:
                        title = h1.get_text(strip=True)
            except Exception:
                pass
        if not title:
            raw_title = _extract_title(html)
            # Strip "cache:URL - Google Suche" prefix from title
            if raw_title.startswith("cache:"):
                raw_title = ""
            title = raw_title

        text = _extract_text(html)
        published = _extract_published(html)

        # Strip Google Cache banner/header from text
        # The banner appears at the very top; article content starts after it
        # Markers (EN/DE): "Klicke hier", "It is a snapshot", "This is Google's cache"
        for banner_marker in [
            "It is a snapshot of the page",
            "This is Google's cache",
            "Klicke hier , wenn du",
            "Click here for the current page",
        ]:
            idx = text.find(banner_marker)
            if idx != -1:
                # Skip past the banner — find next sentence/paragraph
                end_banner = text.find("\n", idx + len(banner_marker) + 30)
                if end_banner != -1:
                    text = text[end_banner:].strip()
                else:
                    text = text[idx + len(banner_marker) + 80:].strip()
                break

        # Additional cleanup: remove leading "cache:URL" line if present
        if text.startswith("cache:"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl:].strip()

        tickers_found = find_tickers(text + " " + title, ticker_list)
        tickers_found = _enrich_tickers_from_keywords(text + " " + title, tickers_found)

        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")

        article = {
            "url": url,
            "title": title,
            "text": text[:3000],  # Cap at 3KB for DB efficiency
            "published": published,
            "source": domain,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "tickers_found": tickers_found,
            "via_cache": True,
        }
        _save_cache(article)
        log.info("Cache fetch OK (%s): %d chars for %s — tickers: %s",
                 fetch_source, len(text), url, tickers_found)
        return article

    except Exception as exc:
        log.error("fetch_via_google_cache(%s): %s", url, exc)
        return {}


# ---------------------------------------------------------------------------
# Reuters RSS — direct article URLs (bypasses Google News redirect problem)
# ---------------------------------------------------------------------------

def fetch_reuters_rss(max_items: int = 15, ticker_list: list[str] = None) -> list[dict]:
    """
    Fetch Reuters articles via Bing News RSS → extract direct reuters.com URLs →
    fetch full article via Google Cache.

    Why Bing? feeds.reuters.com is discontinued (DNS fails). Google News RSS gives
    Google-redirect URLs that hit consent.google.com (blocked from Hetzner).
    Bing News RSS encodes real reuters.com URLs in the &url= query param of its
    redirect links, which we decode directly — no HTTP redirect needed.
    """
    import xml.etree.ElementTree as ET
    from urllib.parse import urlparse as _uparse, parse_qs as _pqs, unquote as _uq

    all_items: list[dict] = []
    seen_urls: set[str] = set()

    bing_rss_base = "https://www.bing.com/news/search?q={query}&format=rss"

    for query in REUTERS_BING_QUERIES:
        if len(all_items) >= max_items:
            break
        try:
            rss_url = bing_rss_base.format(query=quote_plus(query))
            _rate_limit("www.bing.com")
            if HAS_CURL_CFFI:
                resp = cffi_requests.get(
                    rss_url,
                    impersonate="chrome124",
                    headers={"User-Agent": _random_ua()},
                    timeout=15,
                )
                rss_text = resp.text
            else:
                import urllib.request
                with urllib.request.urlopen(rss_url, timeout=15) as r:
                    rss_text = r.read().decode("utf-8", errors="replace")

            if not rss_text or "<item>" not in rss_text:
                log.warning("Bing News Reuters RSS empty: %s", query)
                continue

            try:
                root = ET.fromstring(rss_text)
            except ET.ParseError as exc:
                log.error("Bing News RSS parse error: %s", exc)
                continue

            cutoff = datetime.now(timezone.utc) - timedelta(days=3)

            for item in root.iter("item"):
                if len(all_items) >= max_items:
                    break

                title_el = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                desc_el = item.find("description")

                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                bing_link = link_el.text.strip() if link_el is not None and link_el.text else ""
                pub_raw = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
                desc_raw = desc_el.text or "" if desc_el is not None else ""

                if not bing_link:
                    continue

                # Decode real Reuters URL from Bing redirect (&url= param)
                try:
                    parsed_link = _uparse(bing_link)
                    params = _pqs(parsed_link.query)
                    real_url = params.get("url", [""])[0]
                    if not real_url and "url=" in bing_link:
                        real_url = _uq(bing_link.split("url=")[-1].split("&")[0])
                except Exception:
                    real_url = ""

                if not real_url or "reuters.com" not in real_url:
                    continue
                if real_url in seen_urls:
                    continue
                seen_urls.add(real_url)

                # Parse publish date
                pub_dt = None
                for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"):
                    try:
                        pub_dt = datetime.strptime(pub_raw, fmt)
                        if pub_dt.tzinfo is None:
                            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue

                if pub_dt and pub_dt < cutoff:
                    continue

                # Clean description HTML
                desc_clean = re.sub(r"<[^>]+>", " ", desc_raw).strip()[:500]

                # Quick ticker scan of title + description
                tickers_in_title = find_tickers(title + " " + desc_clean, ticker_list)
                tickers_in_title = _enrich_tickers_from_keywords(
                    title + " " + desc_clean, tickers_in_title
                )

                # Fetch full article via Google Cache
                article = fetch_via_google_cache(real_url, ticker_list=ticker_list)
                if not article:
                    # Fallback: headline-only entry
                    article = {
                        "url": real_url,
                        "title": title,
                        "text": desc_clean,
                        "published": pub_dt.isoformat() if pub_dt else pub_raw,
                        "source": "reuters.com",
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "tickers_found": tickers_in_title,
                    }
                else:
                    if not article.get("title"):
                        article["title"] = title
                    if not article.get("published") and pub_dt:
                        article["published"] = pub_dt.isoformat()
                    merged = list(set(article.get("tickers_found", []) + tickers_in_title))
                    article["tickers_found"] = sorted(merged)

                all_items.append(article)

        except Exception as exc:
            log.error("fetch_reuters_rss (query=%s): %s", query, exc)
            continue

    log.info("fetch_reuters_rss: %d Reuters items via Bing News", len(all_items))
    return all_items


# ---------------------------------------------------------------------------
# Module self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    if "--reuters" in sys.argv:
        print("\n=== Testing Reuters RSS + Google Cache ===")
        items = fetch_reuters_rss(max_items=5)
        for a in items:
            text_preview = (a.get('text') or '')[:120].replace('\n', ' ')
            print(f"  [{a.get('published', '?')[:10]}] {a.get('title', '(no title)')[:80]}")
            print(f"    Tickers: {a.get('tickers_found')} | Text: {text_preview or '(empty)'}...")
            print()
    else:
        print("Testing search_news for 'NVIDIA earnings' ...")
        arts = search_news("NVIDIA earnings", tickers=["NVDA"], days=7, max_results=5)
        for a in arts:
            print(f"  [{a.get('published', '?')}] {a.get('title', '(no title)')} — tickers: {a.get('tickers_found')}")
        print("\nTip: run with --reuters to test Reuters RSS feed")
