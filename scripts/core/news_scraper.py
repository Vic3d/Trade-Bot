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
    """
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
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
# Module self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing search_news for 'NVIDIA earnings' ...")
    arts = search_news("NVIDIA earnings", tickers=["NVDA"], days=7, max_results=5)
    for a in arts:
        print(f"  [{a.get('published', '?')}] {a.get('title', '(no title)')} — tickers: {a.get('tickers_found')}")
