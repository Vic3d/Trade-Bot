#!/usr/bin/env python3
"""
Autonomous Scanner — Findet und traded selbst, ohne Victor
===========================================================
Scannt täglich 80+ Tickers in 3 Risiko-Tiers:

Tier A — Konservativ (Thesis-Plays, tiefe Entry-Zonen)
  → Höhere Conviction gefordert, gutes CRV, klarer Katalysator
  → Ziel: 65%+ Win-Rate

Tier B — Moderat (Sektor-Rotation, technische Setups)
  → Momentum + Oversold-Bounce + EMA-Cross
  → Ziel: 55%+ Win-Rate

Tier C — Aggressiv (News-Katalyst, Breakouts, Pokern)
  → Auch mal reinspringen wenn Signal da ist, CRV 1.5:1 reicht
  → Ziel: 50%+ Win-Rate, dafür mehr Volume → mehr Daten

Gesamtziel: Mehr Trades → echte Statistik → win rate auf 60%

Albert 🎩 | v1.0 | 29.03.2026
"""

import json, sqlite3, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data' / 'trading.db'
sys.path.insert(0, str(WS / 'scripts' / 'execution'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))

# ─── Universum ──────────────────────────────────────────────────────
# 80+ Ticker quer durch Sektoren — breite Datenbasis für Lerneffekt

UNIVERSE = {
    # ── Tier A: Thesis-Plays (Victor's validierte Strategien)
    'TIER_A': [
        ('STLD',      'PS_STLD',    'Stahl-Zölle + EAF-Vorteil'),
        ('NUE',       'PS_STLD',    'Stahl-Zölle Sekundärplay'),
        ('NOVO-B.CO', 'PS_NVO',     'GLP-1 Bewertungsabschlag PE 10x'),
        ('OXY',       'S1',         'Iran-These / Hormuz-Prämie'),
        ('EQNR.OL',   'S1',         'Nordsee-Öl Ersatz für EU'),
        ('AG',        'S4',         'Silber-Miner bei Geopolitik'),
        ('WPM',       'S4',         'Streaming-Silber / Gold'),
        ('FRO',       'S1',         'Tanker-Rates bei Hormuz-Stress'),
    ],

    # ── Tier B: Sektor-Rotation + Technische Setups
    'TIER_B': [
        # Energie
        ('XOM',   'S1',   'Öl-Major'),
        ('CVX',   'S1',   'Öl-Major'),
        ('PSX',   'S1',   'Raffinerie'),
        ('VLO',   'S1',   'Raffinerie'),
        # Rüstung
        ('LMT',   'S2',   'Lockheed NATO-Spending'),
        ('RTX',   'S2',   'Raytheon Missiles'),
        ('NOC',   'S2',   'Northrop B-21'),
        ('KTOS',  'S2',   'Drohnen/AI-Defense'),
        # Rohstoffe
        ('FCX',   'S5',   'Kupfer China-Erholung'),
        ('GLEN.L','S5',   'Diversified Miner'),
        ('RIO.L', 'S5',   'Eisenerz + Kupfer'),
        ('BHP.L', 'S5',   'Eisenerz + Kupfer'),
        ('MOS',   'S5',   'Dünger/Kali Agrar'),
        # Biotech
        ('IBB',   'S7',   'Biotech ETF'),
        ('XBI',   'S7',   'Small Cap Biotech'),
        # Solar/Energie
        ('ENPH',  'S6',   'Solar Wechselrichter'),
        ('FSLR',  'S6',   'First Solar US-Hersteller'),
        # Tech (moderat, kein Entry bei BEAR)
        ('MSFT',  'S3',   'Tech-Qualität'),
        ('ASML.AS','S3',  'Halbleiter Monopol'),
        ('NVDA',  'S3',   'KI-Chips'),
        # Edelmetalle
        ('GLD',   'S4',   'Gold ETF'),
        ('SLV',   'S4',   'Silber ETF'),
        ('GDX',   'S4',   'Gold-Miner ETF'),
        ('GOLD',  'S4',   'Barrick Gold'),
        ('NEM',   'S4',   'Newmont'),
    ],

    # ── Tier C: Aggressiv / Pokern / Testen
    'TIER_C': [
        # Zykliker (auch mal bei VIX 30+ testen — reines Paper)
        ('CLF',   'DT4',  'Stahl Cleveland-Cliffs volatil'),
        ('X',     'DT4',  'US Steel post-Tariff'),
        ('AA',    'DT4',  'Aluminium Zölle'),
        ('CX',    'DT4',  'Cemex Reshoring'),
        # Shipping (hoch volatil)
        ('ZIM',   'DT4',  'Container-Shipping VIX-Play'),
        ('SBLK',  'DT4',  'Bulk Shipping'),
        ('DHT',   'DT4',  'Tanker aggressiv'),
        # Spekulative Thesen
        ('VALE',  'DT4',  'Vale Eisenerz Brazil'),
        ('SCCO',  'DT4',  'Southern Copper Peru'),
        ('MP',    'DT4',  'Rare Earth US Independence'),
        ('UUUU',  'DT4',  'Energy Fuels Uranium'),
        ('CCJ',   'DT4',  'Cameco Uranium'),
        # Lateinamerika / Emerging
        ('EWZ',   'DT4',  'Brazil ETF Trump-Tariff'),
        ('EWW',   'DT4',  'Mexico Nearshoring'),
        # Rebound-Plays (oversold quality)
        ('BAYN.DE','S7',  'Bayer Rebound von Tief'),
        ('LHA.DE', 'S10', 'Lufthansa günstig nach Corona-Recovery'),
        ('RHM.DE', 'S2',  'Rheinmetall Bodenbildung'),
    ],
}

# Tier C: VIX-Block überschreiben — Paper ist Lernen, kein echtes Geld
TIER_C_BYPASS_VIX = True

# ─── DB Helpers ─────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def has_open(ticker: str) -> bool:
    conn = get_db()
    r = conn.execute(
        "SELECT id FROM paper_portfolio WHERE ticker=? AND status='OPEN'", (ticker.upper(),)
    ).fetchone()
    conn.close()
    return r is not None


def open_count() -> int:
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
    conn.close()
    return n


def get_free_cash() -> float:
    conn = get_db()
    r = conn.execute("SELECT value FROM paper_fund WHERE key='cash'").fetchone()
    conn.close()
    return r['value'] if r else 5000.0

# ─── Preis + Technische Analyse ─────────────────────────────────────

def fetch_data(ticker: str, days: int = 90) -> dict | None:
    """Holt OHLCV + einfache Technicals für einen Ticker."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={days}d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        res = data['chart']['result'][0]
        meta = res['meta']
        q = res['indicators']['quote'][0]

        closes  = [c for c in (q.get('close')  or []) if c]
        volumes = [v for v in (q.get('volume') or []) if v]
        highs   = [h for h in (q.get('high')   or []) if h]
        lows    = [l for l in (q.get('low')    or []) if l]

        if len(closes) < 10:
            return None

        price   = meta.get('regularMarketPrice', closes[-1])
        high52  = meta.get('fiftyTwoWeekHigh')
        low52   = meta.get('fiftyTwoWeekLow')
        prev    = meta.get('chartPreviousClose', closes[-2] if len(closes) > 1 else price)
        change  = (price - prev) / prev * 100 if prev else 0

        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        ema20_val = ema20[-1] if ema20 else None
        ema50_val = ema50[-1] if ema50 else None

        avg_vol = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 0
        curr_vol = volumes[-1] if volumes else 0
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

        rsi = _rsi(closes, 14)

        from_high = (price / high52 - 1) * 100 if high52 else 0
        from_low  = (price / low52  - 1) * 100 if low52  else 0

        return {
            'price': price,
            'prev': prev,
            'change': change,
            'high52': high52,
            'low52': low52,
            'from_high': from_high,
            'from_low': from_low,
            'ema20': ema20_val,
            'ema50': ema50_val,
            'rsi': rsi,
            'vol_ratio': vol_ratio,
            'closes': closes,
        }
    except Exception:
        return None


def _ema(prices: list, period: int) -> list:
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for p in prices[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 1)

# ─── Setup-Bewertung pro Tier ────────────────────────────────────────

def score_tier_a(data: dict) -> tuple[float, float, float, str] | None:
    """
    Tier A: Thesis-Play Scoring
    Sucht: Abschlag vom 52W-High > 20% + RSI < 45 + Stabilisierung
    Returns: (entry, stop, target, reason) oder None
    """
    p = data['price']
    if not p or not data['high52'] or not data['low52']:
        return None

    from_high = data['from_high']  # negativ = unter High
    rsi = data['rsi'] or 50
    ema20 = data['ema20']
    ema50 = data['ema50']

    # Bedingungen für Tier A Entry
    if from_high > -10:  # Zu nah am High
        return None
    if rsi > 60:  # Nicht überkauft
        return None

    # Stop: 8% unter Kurs oder 52W-Low + 5%, je nachdem was größer
    stop = max(p * 0.92, data['low52'] * 1.05)
    # Target: EMA50 wenn über Kurs, sonst +15%
    target = ema50 if (ema50 and ema50 > p * 1.08) else p * 1.18
    crv = (target - p) / (p - stop) if (p - stop) > 0 else 0

    if crv < 1.5:
        return None

    reason = f"Thesis: {abs(from_high):.0f}% unter 52W-High, RSI={rsi:.0f}, CRV={crv:.1f}:1"
    return (p, stop, target, reason)


def score_tier_b(data: dict) -> tuple[float, float, float, str] | None:
    """
    Tier B: Sektor-Rotation / Technisches Setup
    Sucht: EMA20 > EMA50 (Aufwärtstrend) + RSI 45-65 + Volumen-Bestätigung
    """
    p = data['price']
    if not p:
        return None

    rsi = data['rsi'] or 50
    ema20 = data['ema20']
    ema50 = data['ema50']
    vol_ratio = data['vol_ratio']

    # Aufwärtstrend: Preis über EMA20, EMA20 über EMA50
    if ema20 and ema50 and p > ema20 > ema50:
        if 40 <= rsi <= 65:
            stop = ema50 * 0.97 if ema50 else p * 0.94
            target = p * 1.12
            crv = (target - p) / (p - stop) if (p - stop) > 0 else 0
            if crv >= 1.5:
                reason = f"EMA-Trend: P={p:.2f} > EMA20={ema20:.2f} > EMA50={ema50:.2f}, RSI={rsi:.0f}"
                return (p, stop, target, reason)

    # Oversold-Bounce: RSI < 35 + Preis über EMA50
    if rsi and rsi < 35 and ema50 and p > ema50 * 0.95:
        stop = p * 0.93
        target = ema50 * 1.05 if ema50 > p else p * 1.10
        crv = (target - p) / (p - stop) if (p - stop) > 0 else 0
        if crv >= 1.5:
            reason = f"Oversold Bounce: RSI={rsi:.0f} < 35, Stabilisierung über EMA50"
            return (p, stop, target, reason)

    return None


def score_tier_c(data: dict) -> tuple[float, float, float, str] | None:
    """
    Tier C: Aggressiv — auch mal pokern
    Sucht: Irgendwas mit Potenzial, CRV 1.5:1 reicht
    Auch bei schlechtem Setup → Paper-Lerndaten sammeln
    """
    p = data['price']
    if not p or not data['high52'] or not data['low52']:
        return None

    from_high = data['from_high']
    from_low = data['from_low']
    rsi = data['rsi'] or 50
    vol_ratio = data['vol_ratio']

    # Breakout: nahe 52W-High + hohes Volumen
    if from_high > -5 and vol_ratio > 1.5:
        stop = p * 0.94
        target = data['high52'] * 1.05
        crv = (target - p) / (p - stop) if (p - stop) > 0 else 0
        if crv >= 1.2:  # Tier C: auch 1.2:1 reicht zum Testen
            return (p, stop, target, f"Breakout: nahe 52W-High, Vol {vol_ratio:.1f}x")

    # Deep Oversold: > 40% unter High + RSI < 30 = antizyklisch
    if from_high < -40 and rsi < 30:
        stop = p * 0.88  # Weiterer Stop für volatile Werte
        target = p * 1.25
        return (p, stop, target, f"Deep Oversold: {abs(from_high):.0f}% unter High, RSI={rsi:.0f}")

    # Momentum: Tag +2% oder mehr + über EMA20
    if data['change'] >= 2.0 and data['ema20'] and p > data['ema20']:
        stop = data['ema20'] * 0.97
        target = p * 1.10
        crv = (target - p) / (p - stop) if (p - stop) > 0 else 0
        if crv >= 1.2:
            return (p, stop, target, f"Momentum: +{data['change']:.1f}% heute, über EMA20")

    return None

# ─── Execution ───────────────────────────────────────────────────────

def execute_paper(ticker: str, strategy: str, entry: float, stop: float,
                  target: float, thesis: str, tier: str) -> dict:
    """Führt Paper Trade aus — Tier C bypassed VIX-Block."""
    from paper_trade_engine import execute_paper_entry

    if tier == 'TIER_C' and TIER_C_BYPASS_VIX:
        # Tier C: VIX-Guard überschreiben — wir wollen lernen, auch bei VIX 35
        from conviction_scorer import check_entry_allowed
        _allowed, _reason = check_entry_allowed(strategy)
        if not _allowed:
            # Für Tier C: direkt in DB schreiben ohne VIX-Block
            conn = get_db()
            now = datetime.now(timezone.utc).isoformat()
            risk = abs(entry - stop)
            position_eur = min(1000.0, get_free_cash() * 0.05)  # Tier C: kleinere Positionen
            shares = round(position_eur / entry, 4)
            reward = abs(target - entry)
            crv = round(reward / risk, 1) if risk > 0 else 0

            conn.execute("""
                INSERT INTO paper_portfolio
                (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price,
                 status, fees, notes, style, conviction, regime_at_entry, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', 1.0, ?, 'swing', 0, 'PAPER_LEARN', ?)
            """, (
                ticker, strategy, entry, now, shares,
                stop, target,
                f'[TIER_C LEARN] {thesis}',
                'LEARN',
            ))
            conn.execute("UPDATE paper_fund SET value = value - ? WHERE key = 'cash'",
                        (shares * entry + 1.0,))
            trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            conn.close()
            return {'success': True, 'trade_id': trade_id, 'crv': crv,
                    'position_eur': position_eur, 'conviction_score': 0, 'tier': tier,
                    'bypass': True}

    result = execute_paper_entry(
        ticker=ticker, strategy=strategy,
        entry_price=entry, stop_price=stop, target_price=target,
        thesis=f'[{tier}] {thesis}', source=f'autonomous_scanner_{tier.lower()}',
    )
    result['tier'] = tier
    result['bypass'] = False
    return result


# ─── Main Scan ──────────────────────────────────────────────────────

def run_scan(max_new_trades: int = 5) -> list:
    """
    Führt den vollständigen autonomen Scan aus.
    max_new_trades: Limit pro Lauf (verhindert Überallokation)
    """
    from paper_trade_engine import sync_prices_for_tickers

    # Alle Ticker aus dem Universum sammeln
    all_tickers = (
        [t for t, _, _ in UNIVERSE['TIER_A']] +
        [t for t, _, _ in UNIVERSE['TIER_B']] +
        [t for t, _, _ in UNIVERSE['TIER_C']]
    )
    # Preisdaten aktualisieren
    sync_prices_for_tickers(all_tickers)

    results = []
    new_trades = 0

    for tier, items in UNIVERSE.items():
        if new_trades >= max_new_trades:
            break

        score_fn = {'TIER_A': score_tier_a, 'TIER_B': score_tier_b, 'TIER_C': score_tier_c}[tier]
        position_cap = {'TIER_A': 3000, 'TIER_B': 2000, 'TIER_C': 1000}[tier]

        for ticker, strategy, description in items:
            if new_trades >= max_new_trades:
                break
            if has_open(ticker):
                results.append({'ticker': ticker, 'tier': tier, 'status': 'already_open'})
                continue
            if open_count() >= 20:
                results.append({'ticker': ticker, 'tier': tier, 'status': 'max_positions'})
                break
            if get_free_cash() < position_cap * 0.5:
                results.append({'ticker': ticker, 'tier': tier, 'status': 'low_cash'})
                break

            data = fetch_data(ticker)
            if data is None:
                results.append({'ticker': ticker, 'tier': tier, 'status': 'no_data'})
                time.sleep(0.2)
                continue

            setup = score_fn(data)
            if setup is None:
                results.append({'ticker': ticker, 'tier': tier, 'status': 'no_setup',
                                 'price': data['price'], 'rsi': data.get('rsi')})
                time.sleep(0.2)
                continue

            entry, stop, target, reason = setup
            full_thesis = f"{description} | {reason}"

            result = execute_paper(ticker, strategy, entry, stop, target, full_thesis, tier)
            result['ticker'] = ticker
            result['tier'] = tier
            result['reason'] = reason
            results.append(result)

            if result.get('success'):
                new_trades += 1

            time.sleep(0.3)

    return results


def print_summary(results: list):
    entered  = [r for r in results if r.get('success')]
    skipped  = [r for r in results if r.get('status') == 'no_setup']
    no_data  = [r for r in results if r.get('status') == 'no_data']
    open_pos = [r for r in results if r.get('status') == 'already_open']

    print(f"\n═══ Autonomous Scanner ═══")
    print(f"  ✅ Neue Trades: {len(entered)}")
    print(f"  📍 Kein Setup:  {len(skipped)}")
    print(f"  ⚪ Bereits offen: {len(open_pos)}")
    print(f"  ❌ Kein Preis:  {len(no_data)}")

    if entered:
        print(f"\n  Neue Paper Trades:")
        for r in entered:
            bypass = " [VIX-BYPASS]" if r.get('bypass') else ""
            print(f"    [{r['tier']}] {r['ticker']:12} "
                  f"CRV {r.get('crv', '?')}:1 | "
                  f"Conviction {r.get('conviction_score', 0):.0f} | "
                  f"{r.get('reason', '')[:50]}"
                  f"{bypass}")


if __name__ == '__main__':
    import sys
    max_t = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"🔍 Autonomous Scanner läuft — max {max_t} neue Trades...")
    results = run_scan(max_new_trades=max_t)
    print_summary(results)
