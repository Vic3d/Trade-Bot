"""
trader_intel.py — Public trading content intelligence for TradeMind CEO context.

Pulls transcripts from YouTube trading channels (no API key required — uses
public RSS feeds + youtube_transcript_api), extracts ticker mentions and
buy/sell setups, caches results in SQLite.

DB: /opt/trademind/data/intelligence.db
Log: /opt/trademind/data/trader_intel.log
"""

import json
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

# --- Optional deps — graceful fallback ---
try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    HAS_TRANSCRIPT_API = True
except ImportError:
    HAS_TRANSCRIPT_API = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = "/opt/trademind/data/intelligence.db"
LOG_PATH = "/opt/trademind/data/trader_intel.log"

# YouTube public RSS — no API key needed
YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# Configured trading channels
YOUTUBE_CHANNELS = {
    "tradermacher": "UCjpfkdnQXxBCStIibNq3P0w",   # Dirk — German trading
    "finanzfluss": "UCeARcCUB00kxBkKQ8fXR3-A",     # German personal finance
    "aktionaer_tv": "UCmMLDRRSQdcN8eTMDyp2kZw",    # Der Aktionär TV
}

# Keywords that indicate a trading setup — German + English
BUY_KEYWORDS = [
    "kaufen", "kauf", "einsteigen", "einstieg", "nachkaufen",
    "buy", "long", "entry", "einsteigen", "einkaufen", "position aufbauen",
    "ich kaufe", "wir kaufen", "jetzt kaufen", "kaufchance",
    "bullish", "bullische", "aufwärtstrend", "kaufsignal",
]
SELL_KEYWORDS = [
    "verkaufen", "verkauf", "aussteigen", "ausstieg",
    "short", "sell", "exit", "absichern", "absicherung",
    "stopp", "stop-loss", "stoploss", "stopp loss", "stop loss",
    "bearish", "bärisch", "abwärtstrend", "verkaufssignal",
    "ich verkaufe", "wir verkaufen", "jetzt verkaufen",
]

# Known tickers — same list as news_scraper for consistency
DEFAULT_TICKERS = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC",
    "JPM", "BAC", "GS", "MS", "V", "MA", "PFE", "NVO", "LLY", "ABBV",
    "PLTR", "SMCI", "ARM", "ASML",
    "SIE.DE", "RHM.DE", "SAP.DE", "BMW.DE", "MBG.DE", "BAYN.DE",
    "ALV.DE", "DBK.DE", "VOW3.DE", "ADS.DE", "IFX.DE",
    "QQQ", "SPY", "KWEB", "EWJ", "EWZ",
    "COIN", "MSTR", "MARA",
]

HTTP_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("trader_intel")


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return connection to intelligence DB, creating schema if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trader_signals (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            source           TEXT,
            video_id         TEXT,
            fetched_at       TEXT,
            channel          TEXT,
            tickers_mentioned TEXT,
            setups           TEXT,
            raw_text         TEXT,
            summary          TEXT
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_video_source
        ON trader_signals (source, video_id)
    """)
    conn.commit()
    return conn


def _video_already_cached(source: str, video_id: str) -> bool:
    """Return True if this video has already been processed."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id FROM trader_signals WHERE source = ? AND video_id = ?",
            (source, video_id),
        ).fetchone()
        return row is not None
    except Exception as exc:
        log.error("_video_already_cached: %s", exc)
        return False


def _save_signal(signal: dict) -> None:
    """Upsert a trader signal into the DB."""
    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO trader_signals
                (source, video_id, fetched_at, channel, tickers_mentioned,
                 setups, raw_text, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.get("source", ""),
                signal.get("video_id", ""),
                signal.get("fetched_at", datetime.now(timezone.utc).isoformat()),
                signal.get("channel", ""),
                json.dumps(signal.get("tickers_mentioned", [])),
                json.dumps(signal.get("setups", [])),
                signal.get("raw_text", ""),
                signal.get("summary", ""),
            ),
        )
        conn.commit()
    except Exception as exc:
        log.error("_save_signal: %s", exc)


# ---------------------------------------------------------------------------
# YouTube transcript fetching
# ---------------------------------------------------------------------------

def get_youtube_transcript(video_id: str) -> str:
    """
    Fetch transcript for a YouTube video via youtube_transcript_api.

    Tries German first (de), then English (en), then any available language.
    Returns the full transcript as a single string, or empty string on failure.
    """
    if not HAS_TRANSCRIPT_API:
        log.warning("youtube_transcript_api not installed — cannot fetch transcript for %s", video_id)
        return ""

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try German first, then English, then first available
        transcript = None
        for lang in ("de", "en"):
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except NoTranscriptFound:
                continue

        if transcript is None:
            # Take whatever is available
            transcript = next(iter(transcript_list))

        entries = transcript.fetch()
        text = " ".join(entry["text"] for entry in entries)
        log.info("Transcript fetched: video=%s lang=%s chars=%d", video_id, transcript.language_code, len(text))
        return text

    except TranscriptsDisabled:
        log.info("Transcripts disabled for video %s", video_id)
        return ""
    except Exception as exc:
        log.error("get_youtube_transcript(%s): %s", video_id, exc)
        return ""


# ---------------------------------------------------------------------------
# YouTube RSS channel feed
# ---------------------------------------------------------------------------

def _fetch_rss(url: str) -> str:
    """Fetch raw RSS XML from URL, return as string. Returns '' on error."""
    try:
        req = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TradeMind/1.0)"},
        )
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as exc:
        log.error("_fetch_rss(%s): %s", url, exc)
        return ""
    except Exception as exc:
        log.error("_fetch_rss(%s): %s", url, exc)
        return ""


def fetch_channel_latest(channel_id: str, max_videos: int = 3) -> list[dict]:
    """
    Fetch the latest videos from a YouTube channel via public RSS feed.
    For each video, retrieves the transcript and extracts tickers and setups.

    No YouTube API key required — uses the public Atom feed.

    Args:
        channel_id: YouTube channel ID (e.g. 'UCjpfkdnQXxBCStIibNq3P0w')
        max_videos: Maximum number of recent videos to process.

    Returns:
        List of signal dicts, one per processed video.
    """
    rss_url = YOUTUBE_RSS_URL.format(channel_id=channel_id)
    rss_text = _fetch_rss(rss_url)
    if not rss_text:
        return []

    # Atom namespace
    NS = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }

    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError as exc:
        log.error("fetch_channel_latest RSS parse error (channel=%s): %s", channel_id, exc)
        return []

    channel_title = ""
    title_el = root.find("atom:title", NS)
    if title_el is not None and title_el.text:
        channel_title = title_el.text.strip()

    results = []
    entries = root.findall("atom:entry", NS)

    for entry in entries[:max_videos]:
        vid_el = entry.find("yt:videoId", NS)
        title_el = entry.find("atom:title", NS)
        published_el = entry.find("atom:published", NS)

        if vid_el is None or vid_el.text is None:
            continue

        video_id = vid_el.text.strip()
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        published = published_el.text.strip() if published_el is not None and published_el.text else ""

        # Skip if already cached
        if _video_already_cached(channel_id, video_id):
            log.info("Video already cached: %s / %s", channel_id, video_id)
            continue

        transcript = get_youtube_transcript(video_id)
        full_text = f"{title} {transcript}"

        tickers = extract_tickers(full_text)
        setups = extract_setups(full_text, tickers)
        summary = _build_summary(title, tickers, setups, published)

        signal = {
            "source": channel_id,
            "video_id": video_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "channel": channel_title,
            "tickers_mentioned": tickers,
            "setups": setups,
            "raw_text": transcript[:10_000],  # truncate to avoid huge DB rows
            "summary": summary,
        }
        _save_signal(signal)
        results.append(signal)
        log.info(
            "Processed video %s (%s): %d tickers, %d setups",
            video_id, title[:60], len(tickers), len(setups),
        )

    return results


# ---------------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------------

def extract_tickers(text: str, ticker_list: list[str] = None) -> list[str]:
    """
    Find ticker mentions in text.

    Handles US tickers (e.g. NVDA, AAPL) and German format (e.g. SIE.DE, RHM.DE).
    Also detects company names mapped to known tickers via a simple alias dict.

    Args:
        text:        Text to scan.
        ticker_list: Optional override of ticker list. Defaults to DEFAULT_TICKERS.

    Returns:
        Sorted, deduplicated list of matched tickers (uppercase).
    """
    tickers = ticker_list or DEFAULT_TICKERS
    found = set()
    text_upper = text.upper()

    for ticker in tickers:
        escaped = re.escape(ticker.upper())
        if re.search(r"\b" + escaped + r"\b", text_upper):
            found.add(ticker.upper())

    # Also detect common German company name aliases
    ALIASES = {
        "NVIDIA": "NVDA",
        "APPLE": "AAPL",
        "MICROSOFT": "MSFT",
        "ALPHABET": "GOOGL",
        "AMAZON": "AMZN",
        "TESLA": "TSLA",
        "SIEMENS": "SIE.DE",
        "RHEINMETALL": "RHM.DE",
        "SAP": "SAP.DE",
        "BAYER": "BAYN.DE",
        "ALLIANZ": "ALV.DE",
        "VOLKSWAGEN": "VOW3.DE",
        "PALANTIR": "PLTR",
    }
    for alias, ticker in ALIASES.items():
        if alias in text_upper:
            found.add(ticker)

    return sorted(found)


# ---------------------------------------------------------------------------
# Setup extraction
# ---------------------------------------------------------------------------

def extract_setups(text: str, tickers: list[str] = None) -> list[dict]:
    """
    Find buy/sell setup mentions in text.

    Uses a sliding window around keyword matches to associate nearby ticker
    mentions with the setup action. Returns list of setup dicts.

    Each dict has:
        ticker:      Ticker symbol (or 'GENERAL' if none found nearby)
        action:      'BUY' | 'SELL' | 'STOP'
        setup_type:  'keyword_match'
        context:     Short text snippet around the keyword match

    Args:
        text:    Full transcript / article text.
        tickers: Pre-extracted ticker list (optional — will re-extract if None).
    """
    if tickers is None:
        tickers = extract_tickers(text)

    setups = []
    seen = set()  # deduplicate (ticker, action) pairs
    text_lower = text.lower()

    def _nearby_ticker(pos: int, window: int = 150) -> Optional[str]:
        """Return first ticker found within ±window chars of position pos."""
        snippet = text[max(0, pos - window): pos + window].upper()
        for t in tickers:
            if re.search(r"\b" + re.escape(t) + r"\b", snippet):
                return t
        return None

    def _scan_keywords(keywords: list[str], action: str) -> None:
        for kw in keywords:
            for m in re.finditer(re.escape(kw), text_lower):
                pos = m.start()
                ticker = _nearby_ticker(pos) or "GENERAL"
                key = (ticker, action)
                if key in seen:
                    continue
                seen.add(key)
                start = max(0, pos - 60)
                end = min(len(text), pos + 60)
                context = re.sub(r"\s+", " ", text[start:end]).strip()
                setups.append({
                    "ticker": ticker,
                    "action": action,
                    "setup_type": "keyword_match",
                    "context": context,
                })

    _scan_keywords(BUY_KEYWORDS, "BUY")
    _scan_keywords(SELL_KEYWORDS, "SELL")

    # Deduplicate: if ticker has both BUY and SELL, keep both but flag it
    return setups


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(title: str, tickers: list[str], setups: list[dict], published: str) -> str:
    """Build a short human-readable summary for the CEO context."""
    buy_tickers = sorted({s["ticker"] for s in setups if s["action"] == "BUY" and s["ticker"] != "GENERAL"})
    sell_tickers = sorted({s["ticker"] for s in setups if s["action"] == "SELL" and s["ticker"] != "GENERAL"})
    parts = [f'"{title}"']
    if published:
        parts.append(f"({published[:10]})")
    if tickers:
        parts.append(f"Tickers: {', '.join(tickers)}")
    if buy_tickers:
        parts.append(f"BUY mentions: {', '.join(buy_tickers)}")
    if sell_tickers:
        parts.append(f"SELL mentions: {', '.join(sell_tickers)}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Run all sources
# ---------------------------------------------------------------------------

def run_all_sources() -> list[dict]:
    """
    Fetch and process the latest videos from all configured YOUTUBE_CHANNELS.

    Returns a flat list of signal dicts across all channels.
    Only processes videos not already in the DB cache.
    """
    all_signals = []
    for name, channel_id in YOUTUBE_CHANNELS.items():
        log.info("Fetching channel: %s (%s)", name, channel_id)
        try:
            signals = fetch_channel_latest(channel_id, max_videos=3)
            for s in signals:
                s.setdefault("channel_name", name)
            all_signals.extend(signals)
        except Exception as exc:
            log.error("run_all_sources channel=%s: %s", name, exc)
    log.info("run_all_sources complete: %d new signals", len(all_signals))
    return all_signals


# ---------------------------------------------------------------------------
# Daily intel summary for CEO
# ---------------------------------------------------------------------------

def get_daily_intel_summary() -> str:
    """
    Return a formatted string summarising the latest trader intelligence.

    Reads the most recent signals from the DB (last 24h) and formats them
    for injection into the CEO's context prompt.

    Returns plain text, empty string if no recent signals exist.
    """
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT source, channel, video_id, fetched_at, tickers_mentioned, setups, summary
            FROM trader_signals
            WHERE fetched_at >= datetime('now', '-1 day')
            ORDER BY fetched_at DESC
            LIMIT 20
            """,
        ).fetchall()
    except Exception as exc:
        log.error("get_daily_intel_summary DB read: %s", exc)
        return ""

    if not rows:
        # Also trigger a fresh fetch so the next call has data
        log.info("No recent intel — triggering fresh fetch")
        run_all_sources()
        return "Keine aktuellen Trader-Signale (letzter Fetch wurde ausgelöst)."

    lines = ["=== TRADER INTELLIGENCE (letzte 24h) ===", ""]

    all_buy: dict[str, int] = {}
    all_sell: dict[str, int] = {}

    for row in rows:
        summary = row["summary"] or ""
        channel = row["channel"] or row["source"]
        lines.append(f"• [{channel}] {summary}")

        try:
            setups = json.loads(row["setups"] or "[]")
            for setup in setups:
                ticker = setup.get("ticker", "")
                action = setup.get("action", "")
                if not ticker or ticker == "GENERAL":
                    continue
                if action == "BUY":
                    all_buy[ticker] = all_buy.get(ticker, 0) + 1
                elif action == "SELL":
                    all_sell[ticker] = all_sell.get(ticker, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    lines.append("")
    lines.append("--- Aggregierte Signale ---")

    if all_buy:
        buy_sorted = sorted(all_buy.items(), key=lambda x: -x[1])
        buy_str = ", ".join(f"{t}({n}x)" for t, n in buy_sorted)
        lines.append(f"BUY-Nennungen:  {buy_str}")

    if all_sell:
        sell_sorted = sorted(all_sell.items(), key=lambda x: -x[1])
        sell_str = ", ".join(f"{t}({n}x)" for t, n in sell_sorted)
        lines.append(f"SELL-Nennungen: {sell_str}")

    if not all_buy and not all_sell:
        lines.append("Keine konkreten Ticker-Setups erkannt.")

    lines.append("")
    lines.append(
        "HINWEIS: Trader-Signale sind Referenzpunkte, keine Handlungsanweisungen. "
        "Eigener Deep Dive bleibt Pflicht vor jedem Trade."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Running all sources ...")
    signals = run_all_sources()
    print(f"Got {len(signals)} new signals.")
    print()
    print(get_daily_intel_summary())
