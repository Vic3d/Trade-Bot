#!/usr/bin/env python3
"""
candidate_discovery.py — News/Intel → Ticker Kandidaten-Queue
=============================================================

Mappt frische News-Events und Trader-Intel auf Ticker-Kandidaten,
berechnet einen Score nach Quellen-Tier und Katalysatoren,
und schreibt die Kandidaten in eine SQLite-Queue (intelligence.db).

Füttert den autonomen CEO mit Stock-Kandidaten zum Deep Dive.

Verwendung:
  from scripts.core.candidate_discovery import (
      run_discovery, score_candidate, get_top_candidates,
      get_sector_balance, format_for_ceo
  )

Tabelle in /opt/trademind/data/intelligence.db:
  candidate_queue (ticker, score, sources, catalysts, first_seen,
                   last_updated, mention_count, sector, exchange, status)
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Pfade ────────────────────────────────────────────────────────────────────
WORKSPACE = Path('/opt/trademind')
INTEL_DB  = WORKSPACE / 'data' / 'intelligence.db'
TRADE_DB  = WORKSPACE / 'data' / 'trading.db'

# ─── Quellen-Tier Gewichte ────────────────────────────────────────────────────
SOURCE_TIERS: dict[str, float] = {
    # Tier 1 — höchste Vertrauenswürdigkeit
    'reuters.com':      1.0,
    'bloomberg.com':    1.0,
    'ft.com':           1.0,
    'sec.gov':          1.0,
    # Tier 2 — solide Finanzpresse
    'cnbc.com':         0.7,
    'marketwatch.com':  0.7,
    'handelsblatt.com': 0.7,
    'finanzfluss':      0.7,
    # Tier 3 — Community / Social
    'youtube':          0.4,
    'ariva.de':         0.4,
    'social':           0.4,
}

# Fallback-Gewicht für unbekannte Quellen
_DEFAULT_TIER_WEIGHT = 0.3

# ─── Katalysator-Keywords ─────────────────────────────────────────────────────
CATALYST_KEYWORDS: list[str] = [
    'earnings', 'upgrade', 'partnership', 'guidance',
    # Deutsche Synonyme
    'ergebnis', 'hochstufung', 'partnerschaft', 'ausblick',
    # Weitere starke Signale
    'beat', 'raised', 'record', 'acquisition', 'merger', 'spinoff',
    'fda approval', 'contract', 'buyback', 'dividend',
]

# ─── Ticker → (Sektor, Börse) ─────────────────────────────────────────────────
TICKER_META: dict[str, tuple[str, str]] = {
    # US Technology
    'NVDA':     ('Technology',  'US'),
    'MU':       ('Technology',  'US'),
    'MRVL':     ('Technology',  'US'),
    'ADBE':     ('Technology',  'US'),
    'ADSK':     ('Technology',  'US'),
    'MSFT':     ('Technology',  'US'),
    'AAPL':     ('Technology',  'US'),
    'GOOGL':    ('Technology',  'US'),
    'META':     ('Technology',  'US'),
    'AMZN':     ('Technology',  'US'),
    'ORCL':     ('Technology',  'US'),
    'CRM':      ('Technology',  'US'),
    'PLTR':     ('Technology',  'US'),
    'SNOW':     ('Technology',  'US'),
    # US Space / Defense
    'RKLB':     ('Space',       'US'),
    'ASTS':     ('Space',       'US'),
    'LMT':      ('Defense',     'US'),
    'RTX':      ('Defense',     'US'),
    'NOC':      ('Defense',     'US'),
    'BA':       ('Defense',     'US'),
    # US Energy / Oil
    'OXY':      ('Energy',      'US'),
    'XOM':      ('Energy',      'US'),
    'CVX':      ('Energy',      'US'),
    'PSX':      ('Energy',      'US'),
    'DINO':     ('Energy',      'US'),
    'MPC':      ('Energy',      'US'),
    # US Tanker
    'FRO':      ('Tanker',      'US'),
    'DHT':      ('Tanker',      'US'),
    'EURN':     ('Tanker',      'US'),
    'TK':       ('Tanker',      'US'),
    # US Finance
    'JPM':      ('Finance',     'US'),
    'GS':       ('Finance',     'US'),
    'MS':       ('Finance',     'US'),
    'BAC':      ('Finance',     'US'),
    # US Clean Energy
    'BE':       ('CleanEnergy', 'US'),
    'FSLR':     ('CleanEnergy', 'US'),
    'ENPH':     ('CleanEnergy', 'US'),
    # US Biotech / Pharma
    'NVO':      ('Pharma',      'US'),
    'LLY':      ('Pharma',      'US'),
    'PFE':      ('Pharma',      'US'),
    'UNH':      ('Healthcare',  'US'),
    # Frankfurt / XETRA
    'SIE.DE':   ('Industry',    'DE'),
    'SAP.DE':   ('Technology',  'DE'),
    'RHM.DE':   ('Defense',     'DE'),
    'ALV.DE':   ('Finance',     'DE'),
    'BMW.DE':   ('Auto',        'DE'),
    'MUV2.DE':  ('Finance',     'DE'),
    'BAS.DE':   ('Chemicals',   'DE'),
    'IFX.DE':   ('Technology',  'DE'),
    'DTE.DE':   ('Telecom',     'DE'),
    'VOW3.DE':  ('Auto',        'DE'),
    'MBG.DE':   ('Auto',        'DE'),
    'ADS.DE':   ('Consumer',    'DE'),
    'DBK.DE':   ('Finance',     'DE'),
    'HEN3.DE':  ('Consumer',    'DE'),
    # Euronext Paris / Amsterdam
    'AIR.PA':   ('Defense',     'EU'),
    'MC.PA':    ('Luxury',      'EU'),
    'BNP.PA':   ('Finance',     'EU'),
    'SAN.PA':   ('Finance',     'EU'),
    'TTE.PA':   ('Energy',      'EU'),
    'OR.PA':    ('Consumer',    'EU'),
    'ASML.AS':  ('Technology',  'EU'),
    'PHIA.AS':  ('Technology',  'EU'),
    # London
    'SHEL.L':   ('Energy',      'UK'),
    'AZN.L':    ('Pharma',      'UK'),
    'BP.L':     ('Energy',      'UK'),
    'HSBA.L':   ('Finance',     'UK'),
    'VOD.L':    ('Telecom',     'UK'),
    'RIO.L':    ('Mining',      'UK'),
    # Norway
    'EQNR':     ('Energy',      'NO'),
    # Asia — Japan
    '7203.T':   ('Auto',        'JP'),
    '6758.T':   ('Technology',  'JP'),
    '9984.T':   ('Technology',  'JP'),
    '8306.T':   ('Finance',     'JP'),
    # Asia — Hong Kong / China
    '9988.HK':  ('Technology',  'HK'),
    '0700.HK':  ('Technology',  'HK'),
    '9999.HK':  ('Technology',  'HK'),
    '2318.HK':  ('Finance',     'HK'),
    # Canada
    'SHOP.TO':  ('Technology',  'CA'),
    'CNQ.TO':   ('Energy',      'CA'),
    # Australia
    'BHP.AX':   ('Mining',      'AU'),
    'CBA.AX':   ('Finance',     'AU'),
}


# ─── DB-Initialisierung ───────────────────────────────────────────────────────

def _init_db(con: sqlite3.Connection) -> None:
    """Erstellt die candidate_queue Tabelle falls noch nicht vorhanden."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS candidate_queue (
            ticker        TEXT PRIMARY KEY,
            score         REAL,
            sources       TEXT,
            catalysts     TEXT,
            first_seen    TEXT,
            last_updated  TEXT,
            mention_count INTEGER,
            sector        TEXT,
            exchange      TEXT,
            status        TEXT DEFAULT 'NEW'
        )
    """)
    con.commit()


def _get_intel_con() -> sqlite3.Connection:
    """Gibt eine Verbindung zur intelligence.db zurück (erstellt DB falls nötig)."""
    INTEL_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(INTEL_DB)
    con.row_factory = sqlite3.Row
    _init_db(con)
    return con


# ─── Intel-Quellen: News aus trading.db ───────────────────────────────────────

def _fetch_recent_news_mentions(hours: int = 24) -> list[dict]:
    """
    Liest frische News-Events aus trading.db (news_events Tabelle).
    Gibt eine Liste von Dicts zurück mit: ticker, headline, source, published_at.
    """
    if not TRADE_DB.exists():
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    mentions: list[dict] = []

    try:
        with sqlite3.connect(TRADE_DB) as con:
            con.row_factory = sqlite3.Row
            # Tabelle news_events (ticker, headline, source, published_at)
            rows = con.execute("""
                SELECT ticker, headline, source, published_at
                FROM   news_events
                WHERE  published_at >= ?
                  AND  ticker IS NOT NULL
                  AND  ticker != ''
            """, (cutoff,)).fetchall()
            for row in rows:
                mentions.append({
                    'ticker':       row['ticker'].upper().strip(),
                    'headline':     row['headline'] or '',
                    'source':       (row['source'] or '').lower(),
                    'published_at': row['published_at'] or '',
                })
    except sqlite3.OperationalError:
        # Tabelle existiert noch nicht — kein Problem, leere Liste
        pass

    return mentions


def _group_by_ticker(mentions: list[dict]) -> dict[str, list[dict]]:
    """Gruppiert Mentions nach Ticker."""
    grouped: dict[str, list[dict]] = {}
    for m in mentions:
        ticker = m['ticker']
        grouped.setdefault(ticker, []).append(m)
    return grouped


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_candidate(ticker: str, mentions: list[dict]) -> dict:
    """
    Score a ticker based on mention frequency, source quality, catalysts.

    Scoring-Formel:
      Base    = sum(mention_count × source_weight) pro Quelle
      Catalyst= +0.3 wenn Katalysator-Keyword in Headlines
      Momentum= +0.2 wenn mehrere Quellen am selben Tag

    Max-Score: 1.0 (gecapped).

    Args:
        ticker:   Ticker-Symbol (z.B. 'NVDA', 'RHM.DE')
        mentions: Liste von Mention-Dicts (ticker, headline, source, published_at)

    Returns:
        Dict mit ticker, score, sources, catalysts, mention_count, sector, exchange
    """
    if not mentions:
        return {
            'ticker':        ticker,
            'score':         0.0,
            'sources':       [],
            'catalysts':     [],
            'mention_count': 0,
            'sector':        TICKER_META.get(ticker, ('Unknown', 'Unknown'))[0],
            'exchange':      TICKER_META.get(ticker, ('Unknown', 'Unknown'))[1],
        }

    # ── Quellen-Gewichtung ────────────────────────────────────────────────────
    source_weights: dict[str, float] = {}
    source_mention_count: dict[str, int] = {}

    for m in mentions:
        src = m.get('source', '')
        # Tier-Lookup: exakter Match zuerst, dann Substring-Match
        weight = _DEFAULT_TIER_WEIGHT
        for domain, w in SOURCE_TIERS.items():
            if domain in src:
                weight = w
                break
        source_weights[src] = weight
        source_mention_count[src] = source_mention_count.get(src, 0) + 1

    base_score = sum(
        source_mention_count[src] * source_weights[src]
        for src in source_mention_count
    )

    # ── Katalysator-Bonus ─────────────────────────────────────────────────────
    all_text = ' '.join(m.get('headline', '') for m in mentions).lower()
    detected_catalysts = [kw for kw in CATALYST_KEYWORDS if kw in all_text]
    catalyst_bonus = 0.3 if detected_catalysts else 0.0

    # ── Momentum-Bonus: mehrere unterschiedliche Quellen am selben Tag ────────
    unique_sources_today: set[str] = set()
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    for m in mentions:
        pub = m.get('published_at', '')
        if pub.startswith(today_str):
            unique_sources_today.add(m.get('source', ''))
    momentum_bonus = 0.2 if len(unique_sources_today) >= 2 else 0.0

    raw_score = base_score + catalyst_bonus + momentum_bonus
    final_score = min(round(raw_score, 4), 1.0)

    sector, exchange = TICKER_META.get(ticker, ('Unknown', 'Unknown'))

    return {
        'ticker':        ticker,
        'score':         final_score,
        'sources':       list(source_mention_count.keys()),
        'catalysts':     detected_catalysts,
        'mention_count': len(mentions),
        'sector':        sector,
        'exchange':      exchange,
    }


# ─── DB-Schreiben ─────────────────────────────────────────────────────────────

def _upsert_candidate(con: sqlite3.Connection, candidate: dict) -> None:
    """Insert oder Update eines Kandidaten in candidate_queue."""
    now = datetime.now(timezone.utc).isoformat()
    ticker = candidate['ticker']

    existing = con.execute(
        "SELECT first_seen FROM candidate_queue WHERE ticker = ?", (ticker,)
    ).fetchone()

    first_seen = existing['first_seen'] if existing else now

    con.execute("""
        INSERT INTO candidate_queue
            (ticker, score, sources, catalysts, first_seen, last_updated,
             mention_count, sector, exchange, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW')
        ON CONFLICT(ticker) DO UPDATE SET
            score         = excluded.score,
            sources       = excluded.sources,
            catalysts     = excluded.catalysts,
            last_updated  = excluded.last_updated,
            mention_count = excluded.mention_count,
            sector        = excluded.sector,
            exchange      = excluded.exchange
    """, (
        ticker,
        candidate['score'],
        json.dumps(candidate['sources'], ensure_ascii=False),
        json.dumps(candidate['catalysts'], ensure_ascii=False),
        first_seen,
        now,
        candidate['mention_count'],
        candidate['sector'],
        candidate['exchange'],
    ))
    con.commit()


# ─── Öffentliche API ──────────────────────────────────────────────────────────

def run_discovery() -> list[dict]:
    """
    Main entry: pull fresh intel, score candidates, write to DB.

    1. Holt frische News-Mentions aus trading.db (letzte 24h)
    2. Gruppiert nach Ticker
    3. Berechnet Score pro Ticker
    4. Schreibt Kandidaten (score >= 0.1) in intelligence.db
    5. Gibt Top-10 nach Score zurück

    Returns:
        Sortierte Liste der Top-Kandidaten als Dicts.
    """
    mentions = _fetch_recent_news_mentions(hours=24)
    if not mentions:
        return []

    grouped = _group_by_ticker(mentions)

    with _get_intel_con() as con:
        for ticker, ticker_mentions in grouped.items():
            candidate = score_candidate(ticker, ticker_mentions)
            # Nur relevante Kandidaten (score >= 0.1) in die DB
            if candidate['score'] >= 0.1:
                _upsert_candidate(con, candidate)

    return get_top_candidates(limit=10, min_score=0.3)


def get_top_candidates(limit: int = 10, min_score: float = 0.3) -> list[dict]:
    """
    Read top candidates from DB for CEO context.

    Args:
        limit:     Max. Anzahl Kandidaten
        min_score: Minimaler Score (0.0–1.0)

    Returns:
        Liste von Kandidaten-Dicts, sortiert nach score DESC.
    """
    with _get_intel_con() as con:
        rows = con.execute("""
            SELECT ticker, score, sources, catalysts, first_seen,
                   last_updated, mention_count, sector, exchange, status
            FROM   candidate_queue
            WHERE  score >= ?
              AND  status NOT IN ('REJECTED', 'DEEP_DIVE_DONE')
            ORDER  BY score DESC
            LIMIT  ?
        """, (min_score, limit)).fetchall()

    result = []
    for row in rows:
        result.append({
            'ticker':        row['ticker'],
            'score':         row['score'],
            'sources':       json.loads(row['sources'] or '[]'),
            'catalysts':     json.loads(row['catalysts'] or '[]'),
            'first_seen':    row['first_seen'],
            'last_updated':  row['last_updated'],
            'mention_count': row['mention_count'],
            'sector':        row['sector'],
            'exchange':      row['exchange'],
            'status':        row['status'],
        })
    return result


def get_sector_balance(current_positions: list[str] | None = None) -> str:
    """
    Check sector concentration of current open positions.

    Liest offene Positionen aus trading.db wenn current_positions=None.
    Warnt wenn ein Sektor mehr als 60% der Positionen ausmacht.

    Args:
        current_positions: Liste von Tickers (None = aus trading.db lesen)

    Returns:
        Warning-String wie '⚠️ 80% Energy (OXY+FRO+DHT) — diversify!'
        oder '' wenn gut diversifiziert.
    """
    if current_positions is None:
        current_positions = _get_open_tickers()

    if not current_positions:
        return ''

    # Sektor pro Ticker bestimmen
    sector_tickers: dict[str, list[str]] = {}
    unknown: list[str] = []

    for ticker in current_positions:
        t = ticker.upper().strip()
        meta = TICKER_META.get(t)
        if meta:
            sector = meta[0]
        else:
            sector = 'Unknown'
            unknown.append(t)
        sector_tickers.setdefault(sector, []).append(t)

    total = len(current_positions)
    if total == 0:
        return ''

    warnings: list[str] = []
    for sector, tickers in sector_tickers.items():
        pct = len(tickers) / total * 100
        if pct >= 60:
            tickers_str = '+'.join(tickers)
            warnings.append(
                f'⚠️ {pct:.0f}% {sector} ({tickers_str}) — diversify!'
            )

    return '  |  '.join(warnings) if warnings else ''


def _get_open_tickers() -> list[str]:
    """Liest offene Positionen aus trading.db."""
    if not TRADE_DB.exists():
        return []
    try:
        with sqlite3.connect(TRADE_DB) as con:
            rows = con.execute(
                "SELECT ticker FROM trades WHERE status = 'OPEN'"
            ).fetchall()
            return [r[0].upper().strip() for r in rows if r[0]]
    except sqlite3.OperationalError:
        return []


def format_for_ceo() -> str:
    """
    Returns formatted string block for CEO build_context().

    Format:
      --- KANDIDATEN-QUEUE (auto-discovered, nach Score) ---
      Score  Ticker     Sektor      Börse  Quellen  Katalysator
      0.85   ADBE       Technology  US     3        Earnings beat expected, upgrade
      ...
      Sector Balance: ⚠️ 60% Energy — nächster Trade sollte diversifizieren
    """
    candidates = get_top_candidates(limit=15, min_score=0.3)
    sector_warn = get_sector_balance()

    if not candidates:
        balance_line = f'Sector Balance: {sector_warn}' if sector_warn else 'Sector Balance: OK'
        return (
            '--- KANDIDATEN-QUEUE (auto-discovered, nach Score) ---\n'
            'Keine Kandidaten mit Score >= 0.3 in der Queue.\n'
            f'{balance_line}'
        )

    header = (
        '--- KANDIDATEN-QUEUE (auto-discovered, nach Score) ---\n'
        f'{"Score":<7} {"Ticker":<10} {"Sektor":<14} {"Börse":<6} '
        f'{"Quellen":<8} Katalysator'
    )

    rows: list[str] = []
    for c in candidates:
        score_str    = f"{c['score']:.2f}"
        ticker_str   = c['ticker']
        sector_str   = c['sector']
        exchange_str = c['exchange']
        src_count    = len(c['sources'])
        catalysts    = ', '.join(c['catalysts']) if c['catalysts'] else '—'

        rows.append(
            f"{score_str:<7} {ticker_str:<10} {sector_str:<14} {exchange_str:<6} "
            f"{src_count:<8} {catalysts}"
        )

    balance_line = (
        f'Sector Balance: {sector_warn}'
        if sector_warn
        else 'Sector Balance: OK — gut diversifiziert'
    )

    return '\n'.join([header] + rows + ['', balance_line])


# ─── CLI-Test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=== candidate_discovery: run_discovery() ===')
    top = run_discovery()
    if top:
        for c in top:
            print(f"  {c['score']:.2f}  {c['ticker']:<10}  {c['sector']}")
    else:
        print('  (keine Kandidaten gefunden)')
    print()
    print(format_for_ceo())
