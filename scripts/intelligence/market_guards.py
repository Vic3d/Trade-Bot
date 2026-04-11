#!/usr/bin/env python3
"""
Market Guards — Drei Bausteine für professionelles Paper Trading
================================================================

1. EARNINGS GUARD    — Kein Entry 5 Tage vor Earnings
2. THESIS GUARD      — Erkennt wenn News eine These invalidieren
3. SECTOR MOMENTUM   — Ist der Sektor gerade stark oder schwach?

Werden in conviction_scorer.py und autonomous_scanner.py eingebunden.

Albert 🎩 | v1.0 | 29.03.2026
"""

import sqlite3, json, urllib.request, os
from datetime import datetime, timedelta, date
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data' / 'trading.db'

# Finnhub Key
try:
    for line in (WS / '.env').read_text(encoding="utf-8").splitlines():
        if line.startswith('FINNHUB_KEY='):
            FINNHUB_KEY = line.split('=', 1)[1].strip()
            break
    else:
        FINNHUB_KEY = ''
except Exception:
    FINNHUB_KEY = ''


# ─── SEKTOR-ETF PROXIES ──────────────────────────────────────────────
# Welche ETFs repräsentieren welche Sektoren?
# Conviction_scorer kann damit echtes Sektor-Momentum messen.

SECTOR_ETFS = {
    # Ticker → Sektor-ETF
    'STLD':    'SLX',    # Steel → VanEck Steel ETF
    'NUE':     'SLX',
    'CLF':     'SLX',
    'NVDA':    'SOXX',   # Semiconductors
    'MSFT':    'QQQ',    # Tech
    'PLTR':    'QQQ',
    'ASML.AS': 'SOXX',
    'OXY':     'XLE',    # Energy
    'EQNR.OL': 'XLE',
    'XOM':     'XLE',
    'PSX':     'XLE',
    'DINO':    'XLE',
    'TTE.PA':  'XLE',
    'FRO':     'BDRY',   # Shipping / Dry Bulk
    'DHT':     'BDRY',
    'RIO.L':   'PICK',   # Mining
    'BHP.L':   'PICK',
    'GLEN.L':  'PICK',
    'AG':      'SIL',    # Silver Miners
    'PAAS':    'SIL',
    'HL':      'SIL',
    'LHA.DE':  'JETS',   # Airlines
    'BAYN.DE': 'XPH',    # Pharma
    'NVO':     'XPH',
    'SAP.DE':  'IGV',    # Software
    # Default: keine Zuordnung → SPY (Markt-Proxy)
}

def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def _yahoo(ticker: str, days: int = 25) -> list[float]:
    """Holt Schlusskurse aus DB, fallback Yahoo."""
    conn = get_db()
    rows = conn.execute(
        "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
        (ticker, days)
    ).fetchall()
    conn.close()
    closes = [r['close'] for r in rows if r['close']]
    if len(closes) >= 5:
        return closes
    # Fallback: Yahoo
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        q = data['chart']['result'][0]['indicators']['quote'][0]
        return [c for c in (q.get('close') or []) if c]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
# 1. EARNINGS GUARD
# ══════════════════════════════════════════════════════════════════════

def get_next_earnings(ticker: str) -> date | None:
    """
    Schätzt nächstes Earnings-Datum.
    Strategie: letztes bekanntes Datum + 91 Tage (Quartals-Zyklus).
    Cached in earnings_calendar Tabelle (24h TTL).
    """
    conn = get_db()

    # Tabelle anlegen falls nicht vorhanden
    conn.execute("""
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            ticker TEXT PRIMARY KEY,
            next_date TEXT,
            updated TEXT
        )
    """)
    conn.commit()

    # Cache prüfen (24h)
    row = conn.execute(
        "SELECT next_date, updated FROM earnings_calendar WHERE ticker=?",
        (ticker,)
    ).fetchone()

    if row and row['next_date']:
        updated = datetime.fromisoformat(row['updated'])
        if datetime.now() - updated < timedelta(hours=24):
            conn.close()
            try:
                return date.fromisoformat(row['next_date'])
            except Exception:
                pass

    conn.close()

    # Finnhub: letztes Earnings-Datum holen
    if not FINNHUB_KEY:
        return None

    try:
        url = f'https://finnhub.io/api/v1/stock/earnings?symbol={ticker}&token={FINNHUB_KEY}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)

        if not data:
            return None

        # Neuestes Quartal
        last = max(data, key=lambda x: x.get('period', ''))
        last_date = date.fromisoformat(last['period'])
        # Nächstes Quartal = +91 Tage
        next_earnings = last_date + timedelta(days=91)

        # Cache speichern
        conn = get_db()
        conn.execute("""
            INSERT OR REPLACE INTO earnings_calendar (ticker, next_date, updated)
            VALUES (?, ?, ?)
        """, (ticker, next_earnings.isoformat(), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        return next_earnings

    except Exception:
        return None


def get_vix_modifier(vix: float | None) -> int:
    """
    Phase 2: VIX is a conviction score modifier only — no hard block.
    Returns score adjustment that feeds into conviction scorer Market Context factor.
    VIX < 20:  +0 (handled in conviction_scorer as full 15 pts)
    VIX 20-25: -5 modifier hint (conviction scorer awards 10/15)
    VIX 25-30: -10 modifier hint (conviction scorer awards 5/15)
    VIX > 30:  -15 modifier hint (conviction scorer awards 0/15)
    Note: actual scoring is done in conviction_scorer._score_market_context().
    """
    if vix is None:
        return 0
    if vix < 20:
        return 0
    elif vix < 25:
        return -5
    elif vix < 30:
        return -10
    else:
        return -15


def check_earnings_safe(ticker: str, days_buffer: int = 5) -> tuple[bool, str]:
    """
    Returns (safe_to_enter, reason).
    safe=False wenn Earnings in den nächsten `days_buffer` Tagen.
    """
    next_e = get_next_earnings(ticker)
    if next_e is None:
        return True, "Earnings-Datum unbekannt — kein Block"

    days_until = (next_e - date.today()).days

    if days_until < 0:
        # Earnings waren kürzlich — nächstes schätzen
        next_e = next_e + timedelta(days=91)
        days_until = (next_e - date.today()).days

    if days_until <= days_buffer:
        return False, f"⚠️ Earnings in {days_until} Tagen ({next_e}) — Entry BLOCKIERT"

    return True, f"Earnings in {days_until} Tagen ({next_e}) — OK"


# ══════════════════════════════════════════════════════════════════════
# 2. THESIS GUARD
# ══════════════════════════════════════════════════════════════════════

def load_watchlist_config() -> dict:
    """Lädt trading_config.json und gibt Ticker→Thesis-Config zurück."""
    cfg_path = WS / 'trading_config.json'
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return {w['ticker']: w for w in cfg.get('watchlist', [])}
    except Exception:
        return {}


def get_recent_news_texts(hours: int = 48) -> list[str]:
    """Holt News-Texte der letzten N Stunden aus der DB."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT headline, summary FROM news
            WHERE datetime(fetched_at) >= datetime('now', ?)
            ORDER BY fetched_at DESC LIMIT 200
        """, (f'-{hours} hours',)).fetchall()
        texts = []
        for r in rows:
            if r['headline']:
                texts.append(r['headline'])
            if r['summary']:
                texts.append(r['summary'])
        return texts
    except Exception:
        return []
    finally:
        conn.close()


def check_thesis_intact(ticker: str) -> tuple[bool, str]:
    """
    Prüft ob recent News eine Kill-Trigger-Kondition aktiviert haben.
    Returns (intact, reason).
    intact=False wenn Kill-Trigger-Keywords in News gefunden.
    """
    watchlist = load_watchlist_config()
    config = watchlist.get(ticker, {})

    kill_trigger = config.get('kill_trigger', '')
    if not kill_trigger:
        return True, "Kein Kill-Trigger definiert"

    # Keywords aus kill_trigger extrahieren (komma-separiert oder Freitext)
    kill_words = [w.strip().lower() for w in kill_trigger.replace(';', ',').split(',') if len(w.strip()) > 3]
    if not kill_words:
        return True, "Kill-Trigger leer"

    news_texts = get_recent_news_texts(48)
    if not news_texts:
        return True, "Keine News-Daten"

    combined = ' '.join(news_texts).lower()
    triggered = [kw for kw in kill_words if kw in combined]

    if triggered:
        return False, f"⚠️ Kill-Trigger aktiv: '{', '.join(triggered[:3])}' in News"

    # Entry-Trigger prüfen (Bonus: erhöht Conviction wenn Entry-Bedingung erfüllt)
    entry_trigger = config.get('entry_trigger', '')
    if entry_trigger:
        entry_words = [w.strip().lower() for w in entry_trigger.replace(';', ',').split(',') if len(w.strip()) > 4]
        confirmed = [kw for kw in entry_words if kw in combined]
        if confirmed:
            return True, f"✅ Entry-Signal aktiv: '{', '.join(confirmed[:2])}'"

    return True, "These intakt (keine Kill-Trigger in News)"


def thesis_conviction_modifier(ticker: str) -> int:
    """
    Returns score adjustment (-20 bis +10) basierend auf Thesis-Check.
    Kill-Trigger aktiv → -20 | Entry-Trigger aktiv → +10 | Neutral → 0
    """
    intact, reason = check_thesis_intact(ticker)
    if not intact:
        return -20
    if "Entry-Signal aktiv" in reason:
        return +10
    return 0


# ══════════════════════════════════════════════════════════════════════
# 3. SECTOR MOMENTUM
# ══════════════════════════════════════════════════════════════════════

def get_sector_etf(ticker: str) -> str:
    """Gibt Sektor-ETF für Ticker zurück, fallback SPY."""
    return SECTOR_ETFS.get(ticker, 'SPY')


def score_sector_momentum(ticker: str, days: int = 20) -> int:
    """
    Echter Sektor-Momentum Score (0-100) basierend auf Sektor-ETF.
    0 = Sektor schwächelt, 50 = neutral, 100 = Sektor heiss.
    """
    etf = get_sector_etf(ticker)
    closes = _yahoo(etf, days + 1)

    if len(closes) < 5:
        return 50  # Kein Signal

    current = closes[0]
    past    = closes[-1]
    if not past:
        return 50

    change_pct = (current / past - 1) * 100

    # Mapping: -15% = 0, 0% = 50, +15% = 100
    score = max(0, min(100, int(change_pct * (50/15) + 50)))
    return score


def sector_momentum_label(ticker: str) -> str:
    score = score_sector_momentum(ticker)
    etf   = get_sector_etf(ticker)
    if score >= 65:
        return f"🟢 Sektor stark ({etf}: {score}/100)"
    elif score >= 40:
        return f"🟡 Sektor neutral ({etf}: {score}/100)"
    else:
        return f"🔴 Sektor schwach ({etf}: {score}/100)"


# ══════════════════════════════════════════════════════════════════════
# CLI — Test-Modus
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['STLD', 'NUE', 'NVDA', 'PLTR', 'LHA.DE', 'NVO']

    print(f"\n{'═'*60}")
    print(f"  Market Guards Check — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'═'*60}\n")

    for t in tickers:
        print(f"  📊 {t}")

        # 1. Earnings
        safe, reason = check_earnings_safe(t)
        print(f"     Earnings:  {'✅' if safe else '🔴'} {reason}")

        # 2. Thesis
        intact, treason = check_thesis_intact(t)
        print(f"     Thesis:    {'✅' if intact else '⚠️ '} {treason}")

        # 3. Sector
        print(f"     Sektor:    {sector_momentum_label(t)}")
        print()
