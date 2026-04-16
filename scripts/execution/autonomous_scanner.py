#!/usr/bin/env python3.13
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
        # Thesis-Plays — von Victor validiert, Deep-Dive
        # ENTFERNT: PS_STLD (3 Trades, 0% WR, -788€), PS4/S4 (0% WR, -1070€)
        ('OXY',       'PS1',        'Iran-These / Hormuz-Prämie'),
        ('EQNR.OL',   'PS1',        'Nordsee-Öl Ersatz für EU'),
        ('FRO',       'PS2',        'Tanker-Rates bei Hormuz-Stress'),
        # Neu aus Discovery 04.04.2026
        ('FCX',       'PS_Copper',  'Kupfer — China-Erholung + grüne Transition'),
        ('SCCO',      'PS_Copper',  'Southern Copper — diversified Cu-Produzent'),
        ('RHM.DE',    'PS11',       'Rheinmetall — EU-Rüstungsbudgets'),
        ('BA.L',      'PS11',       'BAE Systems — UK/EU Defense'),
        ('LMT',       'PS3',        'Lockheed — NATO Spending Wachstum'),
    ],

    # ── Tier B: Sektor-Rotation + Technische Setups
    'TIER_B': [
        # Energie
        ('XOM',    'PS1',   'Öl-Major'),
        ('CVX',    'PS1',   'Öl-Major'),
        ('TTE.PA', 'PS1',   'TotalEnergies — EU-Öl'),
        ('PSX',    'PS1',   'Raffinerie'),
        ('VLO',    'PS1',   'Raffinerie'),
        # EU Defense (breiter)
        ('RTX',    'PS3',   'Raytheon Missiles'),
        ('NOC',    'PS3',   'Northrop B-21'),
        ('KTOS',   'PS3',   'Drohnen/AI-Defense'),
        ('SAF.PA', 'PS11',  'Safran — EU Aerospace/Defense'),
        ('HO.PA',  'PS11',  'Thales — EU Defense Electronics'),
        # Kupfer/Rohstoffe
        ('GLEN.L', 'PS_Copper', 'Glencore — Diversified Miner'),
        ('RIO.L',  'PS_Copper', 'Rio Tinto — Kupfer + Eisenerz'),
        ('BHP.L',  'PS_Copper', 'BHP — Kupfer + Eisenerz'),
        ('TECK',   'PS_Copper', 'Teck Resources — Steelmaking Coal + Kupfer'),
        # China Recovery
        ('FXI',    'PS_China', 'iShares China Large-Cap ETF'),
        ('KWEB',   'PS_China', 'KraneShares China Internet'),
        ('BABA',   'PS_China', 'Alibaba — China Consumer Recovery'),
        ('JD',     'PS_China', 'JD.com — China E-Commerce'),
        # Agrar
        ('MOS',    'PS5',   'Dünger/Kali — Agrar-Preis'),
        ('NTR',    'PS5',   'Nutrien — größter Dünger-Produzent'),
        # AI Infrastructure
        ('AMAT',   'PS_AIInfra', 'Applied Materials — Chip Equipment'),
        ('MU',     'PS_AIInfra', 'Micron — HBM Memory für AI'),
        ('VRT',    'PS_AIInfra', 'Vertiv — Datacenter Cooling/Power'),
        # ENTFERNT: PS4 Edelmetalle (2 Trades, 0% WR, -46€) — pausiert bis genug Daten
        # Tech selektiv (nur bei BULL/NEUTRAL)
        ('MSFT',   'S3',    'Microsoft — Tech-Qualität'),
        ('ASML.AS','S3',    'ASML — Halbleiter-Monopol'),
        ('NVDA',   'S3',    'Nvidia — KI-Chips'),
    ],

    # ── Tier C: Aggressiv / Lernen / Spekulative Thesen
    'TIER_C': [
        # Stahl/Metall Zykliker
        ('CLF',    'PS5',   'Cleveland-Cliffs — US Stahl'),
        ('X',      'PS5',   'US Steel post-Tariff'),
        ('AA',     'PS5',   'Alcoa — Aluminium Zölle'),
        # Shipping volatil
        ('ZIM',    'PS14',  'Container-Shipping Boom/Bust'),
        ('SBLK',   'PS14',  'Star Bulk — Dry Bulk Shipping'),
        ('DHT',    'PS2',   'DHT Holdings — Tanker aggressiv'),
        # Spekulative Rohstoff-Thesen
        ('VALE',   'PS_Copper', 'Vale — Eisenerz + Kupfer Brazil'),
        ('MP',     'S5',    'MP Materials — Rare Earth US'),
        # Uran (neue These — in Beobachtung)
        ('CCJ',    'PS_Uranium', 'Cameco — Uran Produzent #1'),
        ('UUUU',   'PS_Uranium', 'Energy Fuels — Uran + Seltenerde'),
        ('NXE',    'PS_Uranium', 'NexGen Energy — High-Grade Uran'),
        # China spekulative Plays
        ('EWZ',    'PS_China', 'Brazil ETF — China-Handels-Proxy'),
        # Rebound-Plays (oversold quality)
        ('BAYN.DE','S7',    'Bayer — Rebound nach Tief'),
        ('LHA.DE', 'PS17',  'Lufthansa — EU Domestic Champion'),
        ('SIE.DE', 'PS17',  'Siemens — EU Industrials'),
        ('BMW.DE', 'PS18',  'BMW — EU Auto Domestic'),
        # AI Infra spekulative
        ('SMCI',   'PS_AIInfra', 'Super Micro — AI Server (volatil)'),
        ('VST',    'PS_AIInfra', 'Vistra — AI Power Demand'),
    ],
}

# Tier C: VIX-Block überschreiben — Paper ist Lernen, kein echtes Geld
TIER_C_BYPASS_VIX = False  # Deaktiviert — Tier C muss durch alle Guards

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

# ─── P3: Dynamisches Universum aus strategies.json ──────────────────

def load_universe_from_strategies() -> dict:
    """
    Lädt aktive Strategien aus strategies.json und ordnet sie nach Conviction in Tiers.
    Conviction >= 3 → Tier A, >= 2 → Tier B, experimental → Tier C.
    Gibt nur Tickers zurück, die noch nicht im hardcoded UNIVERSE sind.
    """
    result: dict[str, list] = {'TIER_A': [], 'TIER_B': [], 'TIER_C': []}
    try:
        strats_file = WS / 'data' / 'strategies.json'
        if not strats_file.exists():
            return result
        strats = json.loads(strats_file.read_text(encoding='utf-8'))

        # Alle bereits bekannten Ticker aus UNIVERSE sammeln
        # Phase 20: robust gegen dict[tier,list] UND flat list
        known: set[str] = set()
        if isinstance(UNIVERSE, dict):
            _iter = [it for items in UNIVERSE.values() for it in items]
        else:
            _iter = list(UNIVERSE)
        for it in _iter:
            if isinstance(it, (tuple, list)) and len(it) >= 1:
                known.add(str(it[0]).upper())
            elif isinstance(it, str):
                known.add(it.upper())

        for sid, s in strats.items():
            if not isinstance(s, dict):
                continue
            status = s.get('status', 'active').lower()
            if status in ('inactive', 'blocked', 'suspended', 'invalidated'):
                continue

            # Conviction auslesen (int oder "3/5"-Format)
            raw_conv = s.get('conviction', 2)
            try:
                conviction = int(str(raw_conv).split('/')[0])
            except Exception:
                conviction = 2

            # Ticker aus watchlist-Feld extrahieren
            tickers_raw = s.get('tickers', s.get('watchlist', []))
            if isinstance(tickers_raw, str):
                tickers_list = [t.strip() for t in tickers_raw.split(',') if t.strip()]
            else:
                tickers_list = list(tickers_raw or [])

            if not tickers_list:
                continue

            # Tier-Zuordnung
            if status == 'experimental':
                tier = 'TIER_C'
            elif conviction >= 3:
                tier = 'TIER_A'
            elif conviction >= 2:
                tier = 'TIER_B'
            else:
                tier = 'TIER_C'

            strategy_name = str(s.get('name', sid))[:35]
            for ticker in tickers_list:
                ticker_upper = ticker.upper()
                if ticker_upper not in known:
                    result[tier].append((ticker_upper, sid, f'{strategy_name} [dyn]'))
                    known.add(ticker_upper)

    except Exception as e:
        print(f"  ⚠️  load_universe_from_strategies Fehler: {e}")

    return result


# ─── P8: RL-Agent Confidence ─────────────────────────────────────────

def _get_rl_confidence(data: dict, entry: float, stop: float,
                       target: float, tier: str) -> float:
    """
    Holt RL-Agent-Konfidenz (Action=BUY Wahrscheinlichkeit) für dieses Setup.
    State-Vektor: 12 Features aus Preisdaten + CRV + Tier.
    Returns: float 0.0–1.0 (0.5 = neutral/kein Modell vorhanden)
    """
    try:
        import torch
        import numpy as np
        best_model = WS / 'data' / 'rl_best_model.pt'
        if not best_model.exists():
            return 0.5

        sys.path.insert(0, str(WS / 'scripts'))
        from rl_agent import ActorCritic

        net = ActorCritic()
        ckpt = torch.load(str(best_model), map_location='cpu', weights_only=False)
        net.load_state_dict(ckpt['model_state'])
        net.eval()

        p     = data['price']
        rsi   = min(max((data.get('rsi') or 50.0), 0.0), 100.0) / 100.0
        ema20 = data.get('ema20') or p
        ema50 = data.get('ema50') or p
        vol_r = min((data.get('vol_ratio') or 1.0), 4.0) / 4.0
        f_hi  = max(min((data.get('from_high') or 0.0) / 100.0, 0.0), -1.0)
        risk  = max(entry - stop, 0.001)
        crv   = min((target - entry) / risk, 5.0) / 5.0
        tier_v = {'TIER_A': 1.0, 'TIER_B': 0.66, 'TIER_C': 0.33}.get(tier, 0.5)
        ema20r = max(min((p / ema20 - 1.0) * 10.0, 1.0), -1.0) if ema20 > 0 else 0.0
        ema50r = max(min((p / ema50 - 1.0) * 10.0, 1.0), -1.0) if ema50 > 0 else 0.0
        chg    = max(min((data.get('change') or 0.0) / 10.0, 1.0), -1.0)
        state  = [rsi, ema20r, ema50r, vol_r, f_hi, crv, tier_v, chg, 0.0, 0.0, 0.0, 0.0]

        with torch.no_grad():
            s     = torch.FloatTensor(state).unsqueeze(0)
            logits, _ = net(s)
            probs = torch.softmax(logits, dim=-1).squeeze().tolist()

        # Action 0 = BUY (rl_env.py Konvention)
        return float(probs[0]) if probs else 0.5

    except Exception:
        return 0.5  # Neutral fallback wenn Modell nicht vorhanden/geladen


# ─── Preis + Technische Analyse ─────────────────────────────────────

def fetch_data(ticker: str, days: int = 90) -> dict | None:
    """Holt OHLCV + einfache Technicals für einen Ticker. Alle Preise in EUR."""
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

        # ── FX-Konvertierung: Alles in EUR ──────────────────────────
        try:
            from live_data import get_fx_factor
            fx = get_fx_factor(ticker)
        except Exception:
            fx = 1.0
        price  = price * fx
        high52 = high52 * fx if high52 else None
        low52  = low52 * fx if low52 else None
        prev   = prev * fx if prev else price
        closes = [c * fx for c in closes]
        # Volumes bleiben unkonvertiert (Stückzahl, keine Währung)
        # ────────────────────────────────────────────────────────────

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

    if crv < 2.0:
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
            if crv >= 2.0:
                reason = f"EMA-Trend: P={p:.2f} > EMA20={ema20:.2f} > EMA50={ema50:.2f}, RSI={rsi:.0f}"
                return (p, stop, target, reason)

    # Oversold-Bounce: RSI < 35 + Preis über EMA50
    if rsi and rsi < 35 and ema50 and p > ema50 * 0.95:
        stop = p * 0.93
        target = ema50 * 1.05 if ema50 > p else p * 1.10
        crv = (target - p) / (p - stop) if (p - stop) > 0 else 0
        if crv >= 2.0:
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
        if crv >= 2.0:
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
        if crv >= 2.0:
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

def is_trading_day() -> bool:
    """Prüft ob heute überhaupt ein Handelstag ist (Wochentag)."""
    return datetime.now(timezone.utc).weekday() < 5


# ── Phase 18: Globale Börsen-Handelszeiten ──────────────────────────────────
# Jede Börse hat ihre eigenen Öffnungszeiten. Albert prüft pro Ticker
# ob die zugehörige Börse gerade offen ist.
# Format: (open_hour, close_hour, timezone_name, weekdays)
MARKET_HOURS: dict[str, tuple[int, int, str]] = {
    # US Markets: NYSE/NASDAQ 09:30-16:00 ET (= 15:30-22:00 CET)
    'US':    (9, 16, 'America/New_York'),
    # Deutschland: Xetra 09:00-17:30 CET
    'DE':    (9, 17, 'Europe/Berlin'),
    # Euronext (Paris, Amsterdam, Brüssel): 09:00-17:30 CET
    'EU':    (9, 17, 'Europe/Berlin'),
    # London: LSE 08:00-16:30 GMT/BST
    'UK':    (8, 16, 'Europe/London'),
    # Norwegen: Oslo Bors 09:00-16:20 CET
    'NO':    (9, 16, 'Europe/Berlin'),
    # Japan: TSE 09:00-15:00 JST (Lunch 11:30-12:30)
    'JP':    (9, 15, 'Asia/Tokyo'),
    # Hong Kong: HKEX 09:30-16:00 HKT
    'HK':    (9, 16, 'Asia/Hong_Kong'),
    # Kanada: TSX 09:30-16:00 ET
    'CA':    (9, 16, 'America/New_York'),
    # Australien: ASX 10:00-16:00 AEST
    'AU':    (10, 16, 'Australia/Sydney'),
    # Schweden/Dänemark/Kopenhagen
    'NORD':  (9, 17, 'Europe/Stockholm'),
}


def _ticker_to_market(ticker: str) -> str:
    """Bestimmt den Markt anhand des Ticker-Suffix."""
    t = ticker.upper()
    if '.DE' in t or '.F' in t:
        return 'DE'
    if '.PA' in t or '.AS' in t or '.BR' in t or '.MI' in t:
        return 'EU'
    if '.L' in t:
        return 'UK'
    if '.OL' in t:
        return 'NO'
    if '.T' in t:
        return 'JP'
    if '.HK' in t:
        return 'HK'
    if '.TO' in t or '.V' in t:
        return 'CA'
    if '.AX' in t:
        return 'AU'
    if '.CO' in t or '.ST' in t:
        return 'NORD'
    return 'US'  # Default: US-Ticker haben kein Suffix


def is_market_open(ticker: str) -> tuple[bool, str]:
    """
    Prüft ob die Börse für diesen Ticker gerade geöffnet ist.
    Returns: (is_open, reason_string)
    """
    market = _ticker_to_market(ticker)
    hours = MARKET_HOURS.get(market, MARKET_HOURS['US'])
    open_h, close_h, tz_name = hours

    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        # Fallback: immer erlaubt
        return True, f'{market} (tz fallback)'

    # Wochenende: Mo=0..So=6
    if now.weekday() >= 5:
        return False, f'{market} Wochenende'

    hour = now.hour
    if open_h <= hour < close_h:
        return True, f'{market} offen ({open_h}:00-{close_h}:00 {tz_name}, jetzt {now.strftime("%H:%M")})'
    else:
        return False, f'{market} geschlossen ({open_h}:00-{close_h}:00 {tz_name}, jetzt {now.strftime("%H:%M")})'


def is_any_market_open() -> tuple[bool, list[str]]:
    """Prüft ob irgendein Markt gerade offen ist. Gibt offene Märkte zurück."""
    open_markets = []
    for market, (open_h, close_h, tz_name) in MARKET_HOURS.items():
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz_name))
            if now.weekday() < 5 and open_h <= now.hour < close_h:
                open_markets.append(market)
        except Exception:
            continue
    return len(open_markets) > 0, open_markets


def is_optimal_entry_time() -> bool:
    """
    Phase 18: Globale Börsenzeiten statt fixem 17-22h Fenster.
    Ein Ticker darf gehandelt werden wenn seine Börse offen ist.
    Für den Scanner-Gesamtlauf: mindestens ein Markt muss offen sein.
    """
    any_open, markets = is_any_market_open()
    return any_open


def is_in_entry_zone(data: dict, entry: float, stop: float) -> tuple[bool, str]:
    """
    Prüft ob der aktuelle Kurs in einer sinnvollen Entry-Zone liegt.
    Returns: (ok, reason)

    Entry-Zone = eine der folgenden Bedingungen:
      1. Kurs innerhalb 2% des EMA50 (Rücklauf ans Niveau)
      2. Kurs bricht über letztes 5-Tage-Hoch (Ausbruch)
      3. RSI 30-50 (Rücklauf-Zone, nicht überkauft)
      4. Kurs an 52W-Low-Unterstützung (±5%)
    """
    p = data['price']
    ema50 = data.get('ema50')
    ema20 = data.get('ema20')
    rsi = data.get('rsi', 50) or 50
    high52 = data.get('high52')
    low52 = data.get('low52')
    closes = data.get('closes', [])

    # Zone 1: Kurs nahe EMA50 (Rücklauf)
    if ema50 and abs(p - ema50) / ema50 < 0.03:
        return True, f"Nahe EMA50 ({ema50:.2f}€, {((p/ema50)-1)*100:.1f}%)"

    # Zone 2: Ausbruch über 5-Tage-Hoch
    if closes and len(closes) >= 6:
        high_5d = max(closes[-6:-1])
        if p > high_5d * 1.002:
            return True, f"Ausbruch über 5-Tage-Hoch ({high_5d:.2f}€)"

    # Zone 3: RSI Rücklauf-Zone
    if 28 <= rsi <= 48:
        return True, f"RSI {rsi:.0f} — Rücklauf-Zone"

    # Zone 4: Nahe 52W-Low (Unterstützung)
    if low52 and p < low52 * 1.07:
        return True, f"Nahe 52W-Low ({low52:.2f}€) — Unterstützung"

    # Nicht in Zone — Kurs ist zu hoch oder zu trendlos
    zone_info = []
    if ema50:
        zone_info.append(f"EMA50 {((p/ema50)-1)*100:.1f}% entfernt")
    zone_info.append(f"RSI {rsi:.0f}")
    return False, f"Außerhalb Entry-Zone ({', '.join(zone_info)}) — warte auf Rücklauf"


def add_pending_setup(ticker: str, strategy: str, conviction: int,
                      entry: float, stop: float, target: float,
                      trigger_type: str, notes: str):
    """Fügt Setup zur Watchlist hinzu — warte auf Trigger."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Bestehenden Setup für diesen Ticker updaten statt neu anlegen
    existing = conn.execute(
        "SELECT id FROM pending_setups WHERE ticker=? AND status='WATCHING'",
        (ticker,)
    ).fetchone()

    if existing:
        conn.execute('''
            UPDATE pending_setups SET
                strategy=?, conviction=?, entry_trigger=?, trigger_type=?,
                current_price=?, stop_suggestion=?, target_suggestion=?,
                updated_at=?, notes=?
            WHERE id=?
        ''', (strategy, conviction, entry, trigger_type, entry,
              stop, target, now, notes, existing['id']))
    else:
        conn.execute('''
            INSERT INTO pending_setups
                (ticker, strategy, conviction, entry_trigger, trigger_type,
                 current_price, stop_suggestion, target_suggestion, created_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ticker, strategy, conviction, entry, trigger_type,
              entry, stop, target, now, notes))

    conn.commit()
    conn.close()


def run_scan(max_new_trades: int = 5) -> list:
    """
    Führt den vollständigen autonomen Scan aus.
    max_new_trades: Limit pro Lauf (verhindert Überallokation)

    NEU: Entry-Zone-Check + Pending Setups für Borderline-Conviction
    """
    if not is_trading_day():
        print(f"📅 Wochenende ({datetime.now().strftime('%A')}) — kein Scan.")
        return []

    # Phase 18: Globale Börsenzeiten — mindestens ein Markt muss offen sein
    any_open, open_markets = is_any_market_open()
    if not any_open:
        print(f"⏰ Keine Börse gerade offen — kein Scan. (Nächste Öffnung abwarten)")
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from watchlist_tracker import run_snapshot
            run_snapshot()
        except Exception as e:
            print(f"Watchlist-Update Fehler: {e}")
        return []
    print(f"🌍 Offene Märkte: {', '.join(open_markets)}")

    from paper_trade_engine import sync_prices_for_tickers

    # ── P3: Dynamisches Universum aus strategies.json laden ──────────
    dynamic = load_universe_from_strategies()
    merged_universe: dict[str, list] = {}

    # Phase 20: Adapter für unterschiedliche UNIVERSE-Formate
    # (Dict[tier,list] in manchen Branches, flat list in anderen)
    if isinstance(UNIVERSE, list):
        _universe_dict = {'TIER_A': list(UNIVERSE), 'TIER_B': [], 'TIER_C': []}
    else:
        _universe_dict = UNIVERSE

    for _tier in ('TIER_A', 'TIER_B', 'TIER_C'):
        _extra = dynamic.get(_tier, []) if isinstance(dynamic, dict) else []
        merged_universe[_tier] = list(_universe_dict.get(_tier, [])) + _extra
        if _extra:
            print(f"  ✅ {_tier}: +{len(_extra)} Ticker aus strategies.json")

    # ── Phase 20: Universe-Filter — dormant/blocked rauswerfen ──────
    # Ersetzt nicht die Tier-Logik, sondern überlagert sie: wenn der
    # zentrale Universum-Status `dormant` oder `blocked` ist, wird der
    # Ticker im Scan übersprungen. Das verhindert dass RHM.DE, NVDA etc.
    # täglich wieder auftauchen nur weil sie historisch hardcoded sind.
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from core.universe import load_universe as _load_u, SCANNABLE_STATUSES
        _u = _load_u()
        if _u:
            _allowed = {t for t, v in _u.items() if v.get('status') in SCANNABLE_STATUSES}
            _skipped = 0
            for _tier in ('TIER_A', 'TIER_B', 'TIER_C'):
                _before = len(merged_universe[_tier])
                merged_universe[_tier] = [
                    item for item in merged_universe[_tier]
                    if item[0] in _allowed or item[0] not in _u  # unknown → pass through
                ]
                _after = len(merged_universe[_tier])
                _skipped += (_before - _after)
            if _skipped > 0:
                print(f"  🚫 Universe filter: {_skipped} dormant/blocked Ticker übersprungen")
    except Exception as _ue:
        print(f"  ⚠️ Universe filter skipped: {_ue}")

    # Alle Ticker aus dem (erweiterten) Universum sammeln
    all_tickers = (
        [t for t, _, _ in merged_universe['TIER_A']] +
        [t for t, _, _ in merged_universe['TIER_B']] +
        [t for t, _, _ in merged_universe['TIER_C']]
    )
    # Preisdaten aktualisieren (via live_data)
    sync_prices_for_tickers(all_tickers)

    results = []
    new_trades = 0
    pending_added = 0

    for tier, items in merged_universe.items():
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
            # Phase 18: Per-Ticker Market-Hours-Check
            _mkt_open, _mkt_reason = is_market_open(ticker)
            if not _mkt_open:
                results.append({'ticker': ticker, 'tier': tier, 'status': 'market_closed',
                                'reason': _mkt_reason})
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
                # Phase 20: record signal (low conviction = no setup)
                try:
                    from core.universe import record_signal as _rec_sig
                    _rec_sig(ticker, 0.0)
                except Exception:
                    pass
                time.sleep(0.2)
                continue

            entry, stop, target, reason = setup

            # Phase 20: record signal (tier-based baseline conviction)
            try:
                from core.universe import record_signal as _rec_sig
                _baseline = {'TIER_A': 60.0, 'TIER_B': 50.0, 'TIER_C': 40.0}.get(tier, 45.0)
                _rec_sig(ticker, _baseline)
            except Exception:
                pass

            # ── NEU: Entry-Zone-Check ──────────────────────────────────
            in_zone, zone_reason = is_in_entry_zone(data, entry, stop)

            if not in_zone:
                # Kurs noch nicht am Entry-Punkt → Pending Setup anlegen
                # Trigger: wenn Kurs zurückkommt auf Entry-Level
                add_pending_setup(
                    ticker=ticker, strategy=strategy,
                    conviction=0,  # wird beim Trigger neu berechnet
                    entry=entry, stop=stop, target=target,
                    trigger_type='BELOW',  # Long: warte auf Rücklauf (unter aktuellen Preis)
                    notes=f"{description} | {reason} | Warte: {zone_reason}"
                )
                results.append({
                    'ticker': ticker, 'tier': tier, 'status': 'watching',
                    'price': data['price'], 'trigger': entry, 'zone_reason': zone_reason,
                })
                pending_added += 1
                time.sleep(0.2)
                continue
            # ── Ende Entry-Zone-Check ──────────────────────────────────

            # ── P8: RL-Agent Confidence ───────────────────────────────
            rl_conf = _get_rl_confidence(data, entry, stop, target, tier)
            rl_mult = round(0.5 + rl_conf, 2)  # 0.5 (low) … 1.5 (high)
            rl_note = f'RL={rl_conf:.2f}×{rl_mult}'

            full_thesis = f"{description} | {reason} | {zone_reason} | {rl_note}"

            result = execute_paper(ticker, strategy, entry, stop, target, full_thesis, tier)
            result['rl_confidence'] = rl_conf
            result['rl_multiplier'] = rl_mult
            result['ticker'] = ticker
            result['tier'] = tier
            result['reason'] = reason
            results.append(result)

            if result.get('success'):
                new_trades += 1
                # Phase 20: record trade in universe
                try:
                    from core.universe import record_trade as _rec_trade
                    _rec_trade(ticker)
                except Exception:
                    pass

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
