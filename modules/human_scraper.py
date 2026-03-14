"""
HumanScraper — Humanisierter Web Scraper
=========================================
Verwendung: TradeMind (Trading Tool) + NextJob (Umschulungsplattform)
Angelegt: 2026-03-08

Techniken:
  - User-Agent Rotation (echte Browser-Strings)
  - Vollständige Browser-Header (kein Scraper-Fingerprint)
  - Zufällige Delays (Normalverteilung, kein Maschinenrhythmus)
  - Session Persistence (Cookies wie echter Browser)
  - Rate Limiting per Domain
  - Playwright + Stealth für JS-heavy Sites / Cloudflare
  - Browser Fingerprint Randomisierung
  - Retry-Logik mit Backoff

Installation:
  pip install requests playwright playwright-stealth beautifulsoup4 lxml
  playwright install chromium
"""

import time
import random
import threading
import logging
from collections import defaultdict
from urllib.parse import urlparse
from typing import Optional
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# KONSTANTEN
# ─────────────────────────────────────────────

# Echte Browser User-Agents (Stand März 2026)
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    # Firefox Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

# Realistische Viewport-Auflösungen
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 800},
    {"width": 1536, "height": 864},
]

# Sprachen nach Häufigkeit
ACCEPT_LANGUAGES = [
    "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "de-DE,de;q=0.9,en;q=0.8",
    "de-AT,de;q=0.9,en-US;q=0.8",
    "de-CH,de;q=0.9,en;q=0.8",
]


# ─────────────────────────────────────────────
# RATE LIMITER
# ─────────────────────────────────────────────

class RateLimiter:
    """
    Verhindert zu viele Requests an dieselbe Domain.
    Default: max 8 Requests pro Minute pro Domain.
    """

    def __init__(self, max_per_minute: int = 8):
        self.max = max_per_minute
        self.counts: dict = defaultdict(list)
        self.lock = threading.Lock()

    def wait_if_needed(self, domain: str):
        with self.lock:
            now = time.time()
            # Alte Einträge (>60s) entfernen
            self.counts[domain] = [
                t for t in self.counts[domain]
                if now - t < 60
            ]
            if len(self.counts[domain]) >= self.max:
                oldest = self.counts[domain][0]
                sleep_time = 60 - (now - oldest)
                if sleep_time > 0:
                    jitter = random.uniform(1.0, 3.0)
                    logger.debug(
                        f"Rate limit für {domain}: warte {sleep_time:.1f}s + {jitter:.1f}s Jitter"
                    )
                    time.sleep(sleep_time + jitter)
            self.counts[domain].append(time.time())


# ─────────────────────────────────────────────
# DELAY UTILITIES
# ─────────────────────────────────────────────

def human_delay(min_sec: float = 1.5, max_sec: float = 4.5):
    """
    Normalverteilter Delay — simuliert menschliches Leseverhalten.
    Kein gleichmäßiger Maschinenrhythmus.
    """
    mu = (min_sec + max_sec) / 2
    sigma = (max_sec - min_sec) / 4
    delay = random.gauss(mu=mu, sigma=sigma)
    delay = max(min_sec, min(max_sec, delay))
    time.sleep(delay)


def occasional_long_pause(probability: float = 0.12):
    """
    Gelegentlich längere Pause — wie Mensch der etwas liest.
    12% Wahrscheinlichkeit einer 8-20s Pause.
    """
    if random.random() < probability:
        pause = random.uniform(8, 20)
        logger.debug(f"Lange Pause: {pause:.1f}s")
        time.sleep(pause)


# ─────────────────────────────────────────────
# HEADER FACTORY
# ─────────────────────────────────────────────

def build_headers(referer: Optional[str] = None, ua: Optional[str] = None) -> dict:
    """
    Baut vollständige Browser-Headers — nicht erkennbar als Scraper.
    Optional: spezifischer Referer und User-Agent.
    """
    user_agent = ua or random.choice(USER_AGENTS)
    accept_language = random.choice(ACCEPT_LANGUAGES)

    headers = {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    if referer:
        headers["Referer"] = referer

    # Chrome-spezifische Headers wenn Chrome UA
    if "Chrome" in user_agent and "Edg" not in user_agent:
        headers["sec-ch-ua"] = (
            '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"'
        )
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"Windows"'

    return headers


# ─────────────────────────────────────────────
# RESULT DATACLASS
# ─────────────────────────────────────────────

@dataclass
class ScrapeResult:
    url: str
    status_code: int
    html: str
    text: str          # Bereinigter Text (ohne HTML-Tags)
    success: bool
    error: Optional[str] = None
    used_playwright: bool = False

    def soup(self) -> BeautifulSoup:
        """BeautifulSoup-Objekt für einfaches Parsen."""
        return BeautifulSoup(self.html, "lxml")


# ─────────────────────────────────────────────
# HAUPT-KLASSE: HumanScraper
# ─────────────────────────────────────────────

class HumanScraper:
    """
    Humanisierter Web Scraper.

    Verwendung:
        scraper = HumanScraper()

        # Einfacher Request (requests-basiert)
        result = scraper.fetch("https://example.com")

        # JS-heavy Site (Playwright)
        result = scraper.fetch("https://iran.liveuamap.com/", use_browser=True)

        # Text direkt
        print(result.text)

        # HTML parsen
        soup = result.soup()
        title = soup.find("h1").text
    """

    def __init__(
        self,
        max_requests_per_minute: int = 8,
        max_retries: int = 3,
        use_proxy: Optional[str] = None,
    ):
        self.limiter = RateLimiter(max_per_minute=max_requests_per_minute)
        self.max_retries = max_retries
        self.proxy = use_proxy

        # Persistente Session (Cookies + Connection Reuse)
        self.session = requests.Session()
        if use_proxy:
            self.session.proxies = {
                "http": use_proxy,
                "https": use_proxy,
            }

        # Fester UA pro Session-Instanz (realistischer als jedes Mal wechseln)
        self._session_ua = random.choice(USER_AGENTS)

    # ── ÖFFENTLICHE API ──────────────────────

    def fetch(
        self,
        url: str,
        use_browser: bool = False,
        scroll: bool = False,
        wait_for_selector: Optional[str] = None,
    ) -> ScrapeResult:
        """
        Haupt-Methode. Fetcht eine URL humanisiert.

        Args:
            url:                Ziel-URL
            use_browser:        True = Playwright (für JS-heavy / Cloudflare)
            scroll:             True = Seite runterscrollen (simuliert Lesen)
            wait_for_selector:  CSS-Selector auf den gewartet wird (Playwright)
        """
        domain = urlparse(url).netloc

        # Rate-Limit prüfen
        self.limiter.wait_if_needed(domain)

        if use_browser:
            return self._fetch_playwright(url, scroll=scroll, wait_for=wait_for_selector)
        else:
            return self._fetch_requests(url)

    def fetch_many(
        self,
        urls: list[str],
        use_browser: bool = False,
        delay_between: tuple = (2.0, 5.0),
    ) -> list[ScrapeResult]:
        """
        Mehrere URLs nacheinander fetchen — mit Pausen dazwischen.
        """
        results = []
        for i, url in enumerate(urls):
            result = self.fetch(url, use_browser=use_browser)
            results.append(result)

            # Zwischen URLs pausieren (außer letzter)
            if i < len(urls) - 1:
                human_delay(*delay_between)
                occasional_long_pause(probability=0.10)

        return results

    # ── REQUESTS-BACKEND ─────────────────────

    def _fetch_requests(self, url: str) -> ScrapeResult:
        """Standard requests — für einfache Sites ohne JS-Rendering."""
        domain = urlparse(url).netloc
        last_error = None

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    backoff = (2 ** attempt) + random.uniform(1, 3)
                    logger.info(f"Retry {attempt+1}/{self.max_retries} für {url} (warte {backoff:.1f}s)")
                    time.sleep(backoff)

                # Referer = Hauptdomain (als wäre man schon auf der Site)
                referer = f"https://{domain}/"
                headers = build_headers(referer=referer, ua=self._session_ua)

                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                )

                # Kurze Post-Request Pause
                human_delay(0.8, 2.0)

                if response.status_code == 429:
                    # Too Many Requests → länger warten
                    wait = int(response.headers.get("Retry-After", 30))
                    logger.warning(f"429 Too Many Requests — warte {wait}s")
                    time.sleep(wait + random.uniform(5, 15))
                    continue

                if response.status_code == 403:
                    logger.warning(f"403 Forbidden — Site blockiert uns. Playwright versuchen.")
                    return self._fetch_playwright(url)

                response.raise_for_status()

                html = response.text
                text = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True)

                return ScrapeResult(
                    url=url,
                    status_code=response.status_code,
                    html=html,
                    text=text,
                    success=True,
                )

            except requests.exceptions.RequestException as e:
                last_error = str(e)
                logger.warning(f"Request-Fehler (Versuch {attempt+1}): {e}")

        return ScrapeResult(
            url=url, status_code=0, html="", text="",
            success=False, error=last_error
        )

    # ── PLAYWRIGHT-BACKEND ───────────────────

    def _fetch_playwright(
        self,
        url: str,
        scroll: bool = True,
        wait_for: Optional[str] = None,
    ) -> ScrapeResult:
        """
        Playwright mit Stealth — für JS-heavy Sites und Cloudflare.
        Benötigt: pip install playwright playwright-stealth && playwright install chromium
        """
        try:
            from playwright.sync_api import sync_playwright
            try:
                from playwright_stealth import stealth_sync
                has_stealth = True
            except ImportError:
                has_stealth = False
                logger.warning("playwright-stealth nicht installiert — eingeschränkte Tarnung")

            viewport = random.choice(VIEWPORTS)

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        f"--window-size={viewport['width']},{viewport['height']}",
                    ],
                )

                context = browser.new_context(
                    user_agent=self._session_ua,
                    viewport=viewport,
                    locale="de-DE",
                    timezone_id="Europe/Berlin",
                    java_script_enabled=True,
                    extra_http_headers={
                        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
                        "DNT": "1",
                    },
                )

                page = context.new_page()

                # Stealth: entfernt navigator.webdriver und andere Bot-Fingerprints
                if has_stealth:
                    stealth_sync(page)

                # Seite laden
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)

                # Auf spezifischen Selector warten (falls angegeben)
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=10_000)
                else:
                    human_delay(2.0, 4.0)

                # Scrollen simulieren
                if scroll:
                    self._simulate_scroll(page)

                html = page.content()
                browser.close()

            text = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True)

            return ScrapeResult(
                url=url,
                status_code=200,
                html=html,
                text=text,
                success=True,
                used_playwright=True,
            )

        except ImportError:
            logger.error("Playwright nicht installiert. Fallback auf requests.")
            return self._fetch_requests(url)
        except Exception as e:
            logger.error(f"Playwright-Fehler für {url}: {e}")
            return ScrapeResult(
                url=url, status_code=0, html="", text="",
                success=False, error=str(e), used_playwright=True
            )

    def _simulate_scroll(self, page):
        """Menschliches Scrollverhalten — nicht roboterhaft gleichmäßig."""
        scroll_steps = random.randint(3, 7)
        for _ in range(scroll_steps):
            # Zufällige Scroll-Distanz (wie Mensch mit Mausrad)
            distance = random.randint(150, 600)
            page.mouse.wheel(0, distance)
            human_delay(0.4, 1.2)

        # Manchmal kurz hochscrollen (wie jemand der nochmal liest)
        if random.random() < 0.3:
            page.mouse.wheel(0, -random.randint(100, 300))
            human_delay(0.5, 1.0)


# ─────────────────────────────────────────────
# SPEZIALISIERTE SCRAPER
# ─────────────────────────────────────────────

class LivemapScraper(HumanScraper):
    """
    Spezialisiert für liveuamap.com.
    Verwendet: TradeMind Geopolitik-Radar
    """

    BASE_URLS = {
        "iran":     "https://iran.liveuamap.com/",
        "ukraine":  "https://liveuamap.com/",
        "israel":   "https://israelpalestine.liveuamap.com/",
        "lebanon":  "https://lebanon.liveuamap.com/",
        "china":    "https://china.liveuamap.com/",
        "taiwan":   "https://taiwan.liveuamap.com/",
        "venezuela":"https://venezuela.liveuamap.com/",
    }

    def __init__(self):
        super().__init__(max_requests_per_minute=6)

    def fetch_region(self, region: str) -> list[dict]:
        """
        Fetcht aktuelle Meldungen für eine Region.
        Gibt Liste von {time, text} zurück.
        """
        url = self.BASE_URLS.get(region)
        if not url:
            raise ValueError(f"Unbekannte Region: {region}. Verfügbar: {list(self.BASE_URLS.keys())}")

        result = self.fetch(url, use_browser=False)

        if not result.success:
            logger.error(f"Livemap fetch fehlgeschlagen für {region}: {result.error}")
            return []

        return self._parse_livemap(result.html)

    def fetch_tier1(self) -> dict[str, list[dict]]:
        """Tier 1 Regionen: Iran, Ukraine, Israel, Lebanon"""
        regions = ["iran", "ukraine", "israel", "lebanon"]
        results = {}
        for region in regions:
            results[region] = self.fetch_region(region)
            human_delay(2.0, 4.0)
        return results

    def fetch_all(self) -> dict[str, list[dict]]:
        """Alle 7 Regionen (Wochenend-Sammlung)"""
        results = {}
        for region in self.BASE_URLS:
            results[region] = self.fetch_region(region)
            human_delay(2.5, 5.0)
        return results

    def _parse_livemap(self, html: str) -> list[dict]:
        """
        Extrahiert Meldungen aus liveuamap.
        Liveuamap lädt Events per JS — wir parsen den Text-Content
        der im initialen HTML als Klartext enthalten ist.
        """
        import re
        soup = BeautifulSoup(html, "lxml")

        # Methode 1: JS-gerenderte Event-Divs (nur wenn Playwright verwendet)
        events = []
        for item in soup.find_all("div", class_=lambda c: c and "event" in str(c).lower())[:30]:
            time_el = item.find(class_=lambda c: c and "time" in str(c).lower())
            text_el = item.find("p") or item.find(class_=lambda c: c and "text" in str(c).lower())
            if text_el:
                events.append({
                    "time": time_el.get_text(strip=True) if time_el else "",
                    "text": text_el.get_text(strip=True),
                })

        if events:
            return events

        # Methode 2: Text-Parsing (für requests ohne JS-Rendering)
        # liveuamap Struktur im HTML-Text:
        # Zeile N:   "2 hour ago"       ← Zeitstempel
        # Zeile N+1: "Riyadh, Saudi..." ← Ort (überspringen)
        # Zeile N+2: "Saudi Arabia's Ministry..." ← eigentlicher Nachrichtentext
        lines = soup.get_text(separator="\n", strip=True).split("\n")
        time_re = re.compile(
            r'^\d+\s+(?:hour|minute|second)s?\s+ago$', re.IGNORECASE
        )

        i = 0
        while i < len(lines) - 2:
            if time_re.match(lines[i].strip()):
                time_str = lines[i].strip()
                # N+1 = Ort (kurze Zeile, kein Satzzeichen → überspringen)
                # N+2 = Nachrichtentext (längere Zeile mit echtem Inhalt)
                news_text = lines[i + 2].strip() if i + 2 < len(lines) else ""
                if len(news_text) > 30:
                    events.append({"time": time_str, "text": news_text})
                i += 3
            else:
                i += 1

        return events[:30]


class YahooFinanceScraper(HumanScraper):
    """
    Spezialisiert für Yahoo Finance Kursdaten.
    Verwendet: TradeMind Portfolio-Tracking
    Note: Yahoo Finance API (query2) ist stabiler als HTML-Scraping.
    """

    def __init__(self):
        super().__init__(max_requests_per_minute=10)

    def fetch_quote(self, ticker: str) -> dict:
        """Kurs + Meta für einen Ticker."""
        import json
        import urllib.request

        url = (
            f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?interval=1d&range=1d"
        )
        headers = build_headers(
            referer="https://finance.yahoo.com/",
            ua=self._session_ua
        )

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)

        meta = data["chart"]["result"][0]["meta"]
        return {
            "ticker": ticker,
            "price": meta.get("regularMarketPrice"),
            "prev_close": meta.get("previousClose"),
            "currency": meta.get("currency"),
            "volume": meta.get("regularMarketVolume"),
            "avg_volume_10d": meta.get("averageDailyVolume10Day"),
        }

    def fetch_portfolio(self, tickers: list[str]) -> dict[str, dict]:
        """Mehrere Ticker auf einmal — mit Delays."""
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.fetch_quote(ticker)
                human_delay(0.5, 1.5)
            except Exception as e:
                logger.error(f"Yahoo Finance Fehler für {ticker}: {e}")
                results[ticker] = {"error": str(e)}
        return results


class JobBoardScraper(HumanScraper):
    """
    Spezialisiert für Job-Boards.
    Verwendet: NextJob — Marktbedarf-Analyse + Job-Matching
    Unterstützt: Bundesagentur für Arbeit, Indeed, StepStone
    """

    def __init__(self):
        # Job-Boards sind empfindlicher → weniger Requests
        super().__init__(max_requests_per_minute=4)

    def search_bundesagentur(self, job_title: str, location: str = "Deutschland") -> list[dict]:
        """
        Bundesagentur für Arbeit API (offiziell, kein Scraping nötig!).
        API-Docs: https://jobsuche.api.bund.dev/
        """
        import urllib.request, json, urllib.parse

        params = urllib.parse.urlencode({
            "was": job_title,
            "wo": location,
            "umkreis": 25,
            "size": 25,
        })
        url = f"https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs?{params}"

        headers = {
            "User-Agent": self._session_ua,
            "OAuthAccessToken": "jobboerse-jobsuche",  # Öffentlicher Token BA-API
            "Accept": "application/json",
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)

        jobs = []
        for job in data.get("stellenangebote", []):
            jobs.append({
                "title": job.get("titel"),
                "employer": job.get("arbeitgeber"),
                "location": job.get("arbeitsort", {}).get("ort"),
                "posted": job.get("eintrittsdatum"),
                "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{job.get('hashId')}",
            })

        human_delay(1.0, 2.0)
        return jobs

    def scrape_indeed(self, job_title: str, location: str = "Deutschland") -> list[dict]:
        """Indeed scrapen — benötigt Playwright wegen JS-Rendering."""
        import urllib.parse
        query = urllib.parse.urlencode({"q": job_title, "l": location})
        url = f"https://de.indeed.com/jobs?{query}"

        result = self.fetch(url, use_browser=True, scroll=True)
        if not result.success:
            return []

        soup = result.soup()
        jobs = []

        for card in soup.find_all("div", class_=lambda c: c and "job_seen_beacon" in str(c))[:20]:
            title = card.find("h2", class_=lambda c: c and "jobTitle" in str(c))
            company = card.find("span", class_=lambda c: c and "companyName" in str(c))
            location_el = card.find("div", class_=lambda c: c and "companyLocation" in str(c))

            if title:
                jobs.append({
                    "title": title.get_text(strip=True),
                    "company": company.get_text(strip=True) if company else "",
                    "location": location_el.get_text(strip=True) if location_el else "",
                })

        return jobs


class EscoScraper(HumanScraper):
    """
    ESCO API — EU Skills/Competences Framework.
    Verwendet: NextJob — Skills-Mapping, Karrierepfad-Analyse
    API ist offiziell + kostenlos, kein echtes Scraping nötig.
    """

    BASE = "https://ec.europa.eu/esco/api"

    def __init__(self):
        super().__init__(max_requests_per_minute=15)

    def search_occupation(self, title: str, language: str = "de") -> list[dict]:
        """Sucht ESCO-Beruf nach Titel."""
        import urllib.request, json, urllib.parse

        params = urllib.parse.urlencode({
            "text": title,
            "type": "occupation",
            "language": language,
            "limit": 5,
        })
        url = f"{self.BASE}/search?{params}"

        headers = build_headers(ua=self._session_ua)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)

        occupations = []
        for item in data.get("_embedded", {}).get("results", []):
            occupations.append({
                "uri": item.get("uri"),
                "title": item.get("title"),
                "type": item.get("className"),
            })

        human_delay(0.5, 1.0)
        return occupations

    def get_skills_for_occupation(self, occupation_uri: str, language: str = "de") -> dict:
        """Gibt Essential + Optional Skills für einen ESCO-Beruf zurück."""
        import urllib.request, json, urllib.parse

        params = urllib.parse.urlencode({"uri": occupation_uri, "language": language})
        url = f"{self.BASE}/resource/occupation?{params}"

        headers = build_headers(ua=self._session_ua)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)

        relations = data.get("_links", {})
        essential = [
            s.get("title") for s in
            relations.get("hasEssentialSkill", {}).get("href", [])
            if isinstance(s, dict)
        ]
        optional = [
            s.get("title") for s in
            relations.get("hasOptionalSkill", {}).get("href", [])
            if isinstance(s, dict)
        ]

        human_delay(0.5, 1.0)
        return {
            "occupation_uri": occupation_uri,
            "essential_skills": essential,
            "optional_skills": optional,
        }


# ─────────────────────────────────────────────
# FACTORY FUNCTION
# ─────────────────────────────────────────────

def create_scraper(purpose: str = "general") -> HumanScraper:
    """
    Factory für den richtigen Scraper je nach Verwendungszweck.

    Args:
        purpose: "livemap" | "finance" | "jobs" | "esco" | "general"
    """
    scrapers = {
        "livemap":  LivemapScraper,
        "finance":  YahooFinanceScraper,
        "jobs":     JobBoardScraper,
        "esco":     EscoScraper,
        "general":  HumanScraper,
    }
    cls = scrapers.get(purpose, HumanScraper)
    return cls()


# ─────────────────────────────────────────────
# QUICK-TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Test: Yahoo Finance ===")
    finance = create_scraper("finance")
    quotes = finance.fetch_portfolio(["NVDA", "MSFT", "PLTR"])
    for ticker, q in quotes.items():
        print(f"  {ticker}: {q.get('price')} {q.get('currency')}")

    print("\n=== Test: Livemap Iran ===")
    livemap = create_scraper("livemap")
    events = livemap.fetch_region("iran")
    for e in events[:3]:
        print(f"  [{e['time']}] {e['text'][:80]}...")

    print("\n=== Test: Bundesagentur Jobs ===")
    jobs = create_scraper("jobs")
    results = jobs.search_bundesagentur("Buchhalter", "München")
    for j in results[:3]:
        print(f"  {j['title']} @ {j['employer']} ({j['location']})")

    print("\n✅ HumanScraper Module OK")
