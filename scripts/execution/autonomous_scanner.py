#!/usr/bin/env python3
"""
Autonomous Scanner v2 — TradeMind Dual-Gate System
====================================================
Dual-Gate: Jeder Trade braucht BEIDE Gates:
  Gate 1: Thesen-Bestätigung  — These aktiv? Kill-Trigger still silent?
  Gate 2: Technische Bestätigung — Chart bestätigt die These?

Thesen-spezifische Entry-Kriterien pro Strategie.
ATR-basierte Stop/Target-Berechnung.
Max 3 neue Trades pro Lauf (konservativ).

Ziel: 60%+ Win-Rate (aktuell 15%).

Albert | TradeMind v2 | 2026-04-10
"""

import json, sqlite3, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data' / 'trading.db'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'execution'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))


# ─── Thesen-spezifische Entry-Kriterien ──────────────────────────────────────

THESIS_ENTRY_CRITERIA = {
    # EU Aufrüstung — Defense-Aktien im Aufwärtstrend
    'S2': {
        'trend':    lambda d: d['price'] > d['ema20'] > d['ema50'],
        'momentum': lambda d: 40 <= (d['rsi'] or 50) <= 72,
        'volume':   lambda d: d['vol_ratio'] >= 0.8,
        'stop_atr': 2.0,
        'target_r': 3.0,
        'hold_days': (14, 60),
    },
    # PS3: NATO Spending (Lockheed, Raytheon)
    'PS3': {
        'trend':    lambda d: d['price'] > d['ema20'] > d['ema50'],
        'momentum': lambda d: 40 <= (d['rsi'] or 50) <= 72,
        'volume':   lambda d: d['vol_ratio'] >= 0.8,
        'stop_atr': 2.0,
        'target_r': 3.0,
        'hold_days': (14, 60),
    },
    # EU Domestic Champions / Trade War
    'PS17': {
        'trend':    lambda d: d['price'] > d['ema20'],
        'momentum': lambda d: 35 <= (d['rsi'] or 50) <= 70,
        'volume':   lambda d: d['vol_ratio'] >= 0.7,
        'stop_atr': 2.5,
        'target_r': 3.0,
        'hold_days': (7, 45),
    },
    # Trade Dislocation
    'PS18': {
        'trend':    lambda d: d['price'] > d['ema20'],
        'momentum': lambda d: 35 <= (d['rsi'] or 50) <= 70,
        'volume':   lambda d: d['vol_ratio'] >= 0.8,
        'stop_atr': 2.0,
        'target_r': 3.0,
        'hold_days': (10, 45),
    },
    # Dollar-Schwäche — EU Unternehmen mit USD-Umsätzen
    'PS19': {
        'trend':    lambda d: d['price'] > d['ema50'],
        'momentum': lambda d: 40 <= (d['rsi'] or 50) <= 75,
        'volume':   lambda d: d['vol_ratio'] >= 0.7,
        'stop_atr': 2.5,
        'target_r': 3.5,
        'hold_days': (14, 60),
    },
    # Nuclear Renaissance
    'PS16': {
        'trend':    lambda d: d['price'] > d['ema20'] > d['ema50'],
        'momentum': lambda d: 40 <= (d['rsi'] or 50) <= 70,
        'volume':   lambda d: d['vol_ratio'] >= 1.0,
        'stop_atr': 2.0,
        'target_r': 4.0,
        'hold_days': (21, 90),
    },
    # Edelmetalle / Gold (ATH-Umfeld)
    'PS4': {
        'trend':    lambda d: d['price'] > d['ema20'],
        'momentum': lambda d: 45 <= (d['rsi'] or 50) <= 75,
        'volume':   lambda d: d['vol_ratio'] >= 0.8,
        'stop_atr': 2.0,
        'target_r': 3.0,
        'hold_days': (7, 30),
    },
    # Kupfer / Green Transition
    'PS13': {
        'trend':    lambda d: d['price'] > d['ema20'] > d['ema50'],
        'momentum': lambda d: 40 <= (d['rsi'] or 50) <= 68,
        'volume':   lambda d: d['vol_ratio'] >= 0.9,
        'stop_atr': 2.5,
        'target_r': 3.0,
        'hold_days': (14, 60),
    },
    # US Rezessionsabsicherung — Defensiv
    'PS20': {
        'trend':    lambda d: d['price'] > d['ema20'],
        'momentum': lambda d: 35 <= (d['rsi'] or 50) <= 65,
        'volume':   lambda d: d['vol_ratio'] >= 0.6,
        'stop_atr': 1.5,
        'target_r': 2.5,
        'hold_days': (7, 30),
    },
    # Fallback für unbekannte Strategien — konservativ
    'DEFAULT': {
        'trend':    lambda d: d['price'] > d['ema20'] > d['ema50'],
        'momentum': lambda d: 40 <= (d['rsi'] or 50) <= 65,
        'volume':   lambda d: d['vol_ratio'] >= 0.9,
        'stop_atr': 2.0,
        'target_r': 3.0,
        'hold_days': (7, 30),
    },
}


# ─── Dynamisches Universum aus strategies.json ──────────────────────────────

def load_universe_from_strategies():
    """Loads active strategies from strategies.json and returns additional UNIVERSE entries."""
    extra = []
    try:
        strats_path = WS / 'data' / 'strategies.json'
        if not strats_path.exists():
            return extra
        strats = json.loads(strats_path.read_text(encoding='utf-8'))
        if not isinstance(strats, dict):
            return extra
        # Existing tickers in hardcoded UNIVERSE
        existing = {t[0] for t in UNIVERSE}
        for sid, s in strats.items():
            if not isinstance(s, dict):
                continue
            status = s.get('status', '')
            if status not in ('active', 'experimental', 'watching'):
                continue
            tickers = s.get('tickers', [])
            name = s.get('name', sid)
            for ticker in tickers:
                if ticker not in existing:
                    extra.append((ticker, sid, name))
                    existing.add(ticker)
    except Exception as e:
        print(f"[scanner] strategies.json load error: {e}")
    return extra


# ─── Universum (aktive Strategien, PS1/S1 deaktiviert) ───────────────────────

UNIVERSE = [
    # EU Aufrüstung (S2/PS3) — stärkste These
    ('RHM.DE',  'S2',   'Rheinmetall — EU Defense Budget Leader'),
    ('HAG.DE',  'S2',   'Hensoldt — Sensor-Technologie EU Defense'),
    ('SAF.PA',  'S2',   'Safran — Triebwerke/Avionik EU'),
    ('BA.L',    'S2',   'BAE Systems — UK/EU Defense'),
    ('LMT',     'PS3',  'Lockheed Martin — NATO Spending'),
    ('RTX',     'PS3',  'Raytheon — Missiles/Defense'),
    # EU Domestic Champions / Trade War (PS17/PS18)
    ('SIE.DE',  'PS17', 'Siemens — EU Industrial Champion'),
    ('AIR.PA',  'PS17', 'Airbus — EU Domestic + Export'),
    ('SAP.DE',  'PS17', 'SAP — EU Software Champion'),
    ('MUV2.DE', 'PS17', 'Munich Re — EU Financials Domestic'),
    ('BAS.DE',  'PS18', 'BASF — EU Chemicals, Trade War Opfer/Profiteur'),
    # Dollar-Schwäche (PS19) — EU Aktien mit USD-Umsätzen
    ('ASML.AS', 'PS19', 'ASML — 70% USD-Umsaetze, starker Euro = Gegenwind/Bewertungsschub'),
    ('NVO',     'PS19', 'Novo Nordisk — USD-Umsaetze, guenstige Bewertung'),
    # Nuclear Renaissance (PS16)
    ('CCJ',     'PS16', 'Cameco — Uran Produzent #1 Weltweit'),
    ('UUUU',    'PS16', 'Energy Fuels — US Uran + Seltenerde'),
    ('CEG',     'PS16', 'Constellation Energy — Nuclear Power Plants'),
    # Edelmetalle (PS4) — Gold ATH
    ('GOLD',    'PS4',  'Barrick Gold — Gold ATH Profiteur'),
    ('NEM',     'PS4',  'Newmont — Gold Miner mit Hebel'),
    ('WPM',     'PS4',  'Wheaton PM — Royalty, weniger Kosten-Risiko'),
    # Kupfer (PS13)
    ('FCX',     'PS13', 'Freeport — Groesster US Kupfer-Produzent'),
    ('SCCO',    'PS13', 'Southern Copper — Guenstigste Kosten'),
    ('RIO.L',   'PS13', 'Rio Tinto — Diversified Copper + Iron'),
    # Defensive Rotation (PS20)
    ('XLP',     'PS20', 'Consumer Staples ETF — Defensiv'),
    ('XLU',     'PS20', 'Utilities ETF — AI Power Demand + Defensiv'),
    ('JNJ',     'PS20', 'Johnson und Johnson — Qualitaet Defensiv'),
    # ── Japan / Asien — Fruehindikatoren + Eigenstaendige Thesen ────────────
    ('8306.T',  'JP',   'Mitsubishi UFJ — Japans groesste Bank, BOJ-Zinswende'),
    ('7203.T',  'JP',   'Toyota — Japans Exportbarometer, Yen-Sensitivity'),
    ('8035.T',  'JP',   'Tokyo Electron — Halbleiter-Ausruestung, Tech-Bellwether Asia'),
    ('6758.T',  'JP',   'Sony — Consumer Tech + Gaming, Globaler Sentiment'),
    ('9984.T',  'JP',   'SoftBank — Tech-VC Barometer, AI-Exposure'),
    # ── China / Hongkong — Direkte Positionen + Signalgeber ────────────────
    ('9988.HK', 'CN',   'Alibaba HK — E-Commerce + Cloud, China Consumer Barometer'),
    ('0700.HK', 'CN',   'Tencent — Gaming + Fintech + AI, Chinas wertvollste Tech-Firma'),
    ('2318.HK', 'CN',   'Ping An Insurance — China Financials Bellwether'),
    ('3690.HK', 'CN',   'Meituan — China Local Services, Consumer Spending'),
    ('BABA',    'CN',   'Alibaba US-ADR — Liquidester China-Trade fuer US-Session'),
    ('PDD',     'CN',   'PDD Holdings (Temu) — China Export-Consumer, Wachstum'),
    ('JD',      'CN',   'JD.com — China E-Commerce #2, Logistik'),
    ('KWEB',    'CN',   'KraneShares China Internet ETF — Breitester China-Tech-Proxy'),
    # Asien-ETFs als Signalgeber
    ('EWJ',     'JP',   'iShares Japan ETF — Nikkei-Proxy fuer US-Handel'),
    ('FXI',     'CN',   'iShares China Large-Cap — China-Sentiment Proxy'),
    # ── Euronext Paris (.PA) ────────────────────────────────────────────────
    ('MC.PA',   'EU',   'LVMH — Luxus-Bellwether, China-Exposure'),
    ('OR.PA',   'EU',   'L Oreal — Konsumgueter, Emerging Markets'),
    ('SU.PA',   'EU',   'Schneider Electric — Energiewende + Industrie'),
    ('BNP.PA',  'EU',   'BNP Paribas — Europas groesste Bank'),
    # TotalEnergies (TTE.PA) ist schon ueber strategies.json dynamisch geladen
    # ── Euronext Amsterdam (.AS) ─────────────────────────────────────────────
    # ASML.AS ist schon im UNIVERSE (PS19)
    ('INGA.AS', 'EU',   'ING Group — Europaeische Banken, Zins-Sensitiv'),
    ('AD.AS',   'EU',   'Ahold Delhaize — EU Retail Defensiv'),
    # ── London Stock Exchange (.L) ───────────────────────────────────────────
    # BAE (BA.L) und Rio Tinto (RIO.L) sind schon im UNIVERSE
    ('SHEL.L',  'EU',   'Shell — Europas groesstes Oelunternehmen'),
    ('HSBA.L',  'EU',   'HSBC — Globale Bank, Asien-Exposure'),
    ('AZN.L',   'EU',   'AstraZeneca — Pharma + Biotech EU'),
    ('ULVR.L',  'EU',   'Unilever — Consumer Staples Defensiv'),
    # ── Mailand (.MI) ────────────────────────────────────────────────────────
    ('ISP.MI',  'EU',   'Intesa Sanpaolo — Italiens groesste Bank'),
    ('RACE.MI', 'EU',   'Ferrari — Luxus + Momentum'),
    ('ENEL.MI', 'EU',   'Enel — Europas groesster Versorger, Erneuerbare'),
    # ── Madrid (.MC) ─────────────────────────────────────────────────────────
    ('ITX.MC',  'EU',   'Inditex (Zara) — Fast Fashion, EU Consumer'),
    ('SAN.MC',  'EU',   'Banco Santander — EU + Latam Banken'),
    ('IBE.MC',  'EU',   'Iberdrola — Erneuerbare Energie EU'),
    # ── Nordics ──────────────────────────────────────────────────────────────
    # SAAB-B.ST und EQNR.OL sind schon ueber strategies.json
    ('ERIC-B.ST', 'EU', 'Ericsson — 5G/Telecom, Infrastruktur'),
    ('ATCO-A.ST', 'EU', 'Atlas Copco — Industrie-Kompressoren, Konjunktur-Barometer'),
    ('NOKIA.HE',  'EU', 'Nokia — 5G + Defense Networks'),
    ('NESTE.HE',  'EU', 'Neste — Nachhaltiger Treibstoff, Green Economy'),
    ('NOVO-B.CO', 'EU', 'Novo Nordisk — Diabetes/Ozempic, Pharma-Leader'),
    # ── Schweiz (.SW) ────────────────────────────────────────────────────────
    ('NESN.SW', 'EU',   'Nestle — Konsumgueter-Weltmarktfuehrer'),
    ('NOVN.SW', 'EU',   'Novartis — Pharma Global'),
    ('ABBN.SW', 'EU',   'ABB — Industrieautomation + E-Mobility'),
    # ── US Large Cap ─────────────────────────────────────────────────────────
    ('NVDA',    'TECH', 'Nvidia — AI-Bellwether'),
    ('MSFT',    'TECH', 'Microsoft — AI + Cloud Marktfuehrer'),
    ('AAPL',    'TECH', 'Apple — Consumer Tech Barometer'),
    ('AMZN',    'TECH', 'Amazon — E-Commerce + Cloud'),
    ('GOOGL',   'TECH', 'Alphabet — Search + AI'),
]


# ─── DB Helpers ──────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def has_open(ticker: str) -> bool:
    try:
        conn = get_db()
        r = conn.execute(
            "SELECT id FROM paper_portfolio WHERE ticker=? AND status='OPEN'",
            (ticker.upper(),)
        ).fetchone()
        conn.close()
        return r is not None
    except Exception:
        return False


def open_count() -> int:
    try:
        conn = get_db()
        n = conn.execute(
            "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'"
        ).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


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

# ─── ATR-Berechnung ──────────────────────────────────────────────────────────

def _atr(closes: list, highs: list, lows: list, period: int = 14) -> float:
    """Average True Range für Stop-Berechnung."""
    if len(closes) < period + 1:
        return closes[-1] * 0.03 if closes else 1.0
    trs = []
    for i in range(1, min(period + 1, len(closes))):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else closes[-1] * 0.03


# ─── EMA + RSI ───────────────────────────────────────────────────────────────

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
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 1)


# ─── Preis + Technische Analyse ──────────────────────────────────────────────

def fetch_data(ticker: str, days: int = 90) -> dict | None:
    """
    Holt OHLCV + Technicals für einen Ticker.
    Gibt highs und lows zurück (für ATR-Berechnung).
    Alle Preise in EUR.
    """
    import urllib.request
    url = (
        f'https://query2.finance.yahoo.com/v8/finance/chart/'
        f'{ticker}?interval=1d&range={days}d'
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)

        res  = data['chart']['result'][0]
        meta = res['meta']
        q    = res['indicators']['quote'][0]

        closes  = [c for c in (q.get('close')  or []) if c]
        volumes = [v for v in (q.get('volume') or []) if v]
        highs   = [h for h in (q.get('high')   or []) if h]
        lows    = [lo for lo in (q.get('low')   or []) if lo]

        if len(closes) < 10:
            return None

        price  = meta.get('regularMarketPrice', closes[-1])
        high52 = meta.get('fiftyTwoWeekHigh')
        low52  = meta.get('fiftyTwoWeekLow')
        prev   = meta.get('chartPreviousClose', closes[-2] if len(closes) > 1 else price)

        # FX-Konvertierung: Alles in EUR
        try:
            from live_data import get_fx_factor
            fx = get_fx_factor(ticker)
        except Exception:
            fx = 1.0

        price  = price * fx
        high52 = high52 * fx if high52 else None
        low52  = low52 * fx  if low52  else None
        prev   = prev * fx   if prev   else price
        closes = [c * fx for c in closes]
        highs  = [h * fx for h in highs]
        lows   = [lo * fx for lo in lows]

        change = (price - prev) / prev * 100 if prev else 0

        ema20     = _ema(closes, 20)
        ema50     = _ema(closes, 50)
        ema20_val = ema20[-1] if ema20 else None
        ema50_val = ema50[-1] if ema50 else None

        avg_vol   = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 0
        curr_vol  = volumes[-1] if volumes else 0
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

        rsi = _rsi(closes, 14)

        from_high = (price / high52 - 1) * 100 if high52 else 0
        from_low  = (price / low52  - 1) * 100 if low52  else 0

        return {
            'price':     price,
            'prev':      prev,
            'change':    change,
            'high52':    high52,
            'low52':     low52,
            'from_high': from_high,
            'from_low':  from_low,
            'ema20':     ema20_val,
            'ema50':     ema50_val,
            'rsi':       rsi,
            'vol_ratio': vol_ratio,
            'closes':    closes,
            'highs':     highs,
            'lows':      lows,
        }
    except Exception:
        return None


# ─── Gate 1: Thesen-Status prüfen ────────────────────────────────────────────

def _thesis_gate_ok(strategy: str) -> bool:
    """
    Gate 1: Prüft ob die These aktiv ist (nicht INVALIDATED oder PAUSED).
    Returns True wenn Entries erlaubt, False wenn blockiert.
    """
    try:
        from thesis_engine import get_thesis_status
        status_dict = get_thesis_status(strategy)
        if not status_dict:
            # Noch kein DB-Eintrag → These als aktiv betrachten (neu)
            return True
        blocked = {'INVALIDATED', 'PAUSED'}
        return status_dict.get('status', 'ACTIVE') not in blocked
    except Exception:
        # Wenn thesis_engine nicht verfügbar → erlauben (fail-open)
        return True


# ─── Gate 2: Technische Bestätigung + Setup-Berechnung ───────────────────────

def evaluate_setup(ticker: str, strategy: str, data: dict) -> dict | None:
    """
    Dual-Gate Bewertung: Thesis + Technical.

    Gate 1: Thesis aktiv? (thesis_status Tabelle)
    Gate 2: Technische Bestätigung (trend/momentum/volume)

    Returns: Setup-Dict mit entry/stop/target/reason oder None
    """
    # Gate 1: Thesis aktiv?
    if not _thesis_gate_ok(strategy):
        return None

    # Gate 2: Technische Bestätigung
    criteria = THESIS_ENTRY_CRITERIA.get(strategy, THESIS_ENTRY_CRITERIA['DEFAULT'])

    # EMA-Werte müssen vorhanden sein für Trend-Check
    if data.get('ema20') is None or data.get('ema50') is None:
        # Nur EMA20 nötig wenn criteria nur ema20 prüft
        pass

    if not criteria['trend'](data):
        return None

    if not criteria['momentum'](data):
        return None

    if not criteria['volume'](data):
        return None

    # Stop via ATR
    closes = data.get('closes', [])
    highs  = data.get('highs', [])
    lows   = data.get('lows', [])

    atr  = _atr(closes, highs, lows)
    stop = data['price'] - criteria['stop_atr'] * atr

    # Sanity-Check: Stop darf nicht negativ oder > 30% unter Preis sein
    min_stop = data['price'] * 0.70
    stop = max(stop, min_stop)

    # Stop-Floor: Swings brauchen mind. 4% Abstand (siehe trade_style.min_stop_pct).
    # Bei niedrig-volatilen Tickern (ATR ~1-2%) berechnet ATR*2 einen <2% Stop,
    # der vom Daily-Noise sofort getroffen wird. Hier Floor durchziehen statt
    # später im paper_trade_engine-Guard als Reject zu enden.
    try:
        from trade_style import classify_strategy as _cls, get_style_config as _gsc
        _min_pct = _gsc(_cls(strategy)).min_stop_pct
    except Exception:
        _min_pct = 4.0  # Fallback für Swings
    _stop_floor = data['price'] * (1 - _min_pct / 100)
    if stop > _stop_floor:
        stop = _stop_floor  # weiter weg (= kleinerer Stop-Preis)

    # Target via CRV
    risk   = data['price'] - stop
    if risk <= 0:
        return None

    target = data['price'] + criteria['target_r'] * risk
    crv    = (target - data['price']) / risk

    if crv < 2.0:
        return None

    rsi_val = data.get('rsi') or 50
    vix_val = data.get('vix') or 20

    # ── Strategy DNA Gate: Prüfe ob Entry-Bedingungen im optimalen Bereich ──
    dna_bonus = 0
    dna_note = ''
    try:
        _dna_path = WS / 'data' / 'dna.json'
        if _dna_path.exists():
            import json as _json
            _dna = _json.loads(_dna_path.read_text(encoding='utf-8'))
            _sdna = _dna.get(strategy, {})
            if _sdna:
                # RSI in optimalem Bereich?
                _rsi_range = _sdna.get('optimal_rsi_range')
                if _rsi_range and len(_rsi_range) == 2:
                    if _rsi_range[0] <= rsi_val <= _rsi_range[1]:
                        dna_bonus += 5
                        dna_note += f'DNA-RSI✓ '
                    else:
                        dna_bonus -= 5
                        dna_note += f'DNA-RSI✗({_rsi_range}) '

                # VIX in optimalem Bereich?
                _vix_range = _sdna.get('optimal_vix_range')
                if _vix_range and len(_vix_range) == 2:
                    if _vix_range[0] <= vix_val <= _vix_range[1]:
                        dna_bonus += 3
                        dna_note += f'DNA-VIX✓ '
                    else:
                        dna_bonus -= 3
                        dna_note += f'DNA-VIX✗({_vix_range}) '

                # Regime passt?
                _best_regime = _sdna.get('best_regime')
                _current_regime = data.get('regime', '')
                if _best_regime and _current_regime:
                    if _current_regime.upper() == str(_best_regime).upper():
                        dna_bonus += 3
                        dna_note += f'DNA-Regime✓ '
    except Exception:
        pass  # DNA-Check ist optional, kein Crash

    # ── RL Agent Konsultation (optional) ─────────────────────────────────────
    rl_bonus = 0
    rl_note = ''
    try:
        _rl_model_path = WS / 'data' / 'rl_best_model.pt'
        if _rl_model_path.exists():
            from rl_agent import predict_action
            _features = {
                'rsi': rsi_val, 'vix': vix_val,
                'vol_ratio': data.get('vol_ratio', 1.0),
                'crv': crv, 'atr_pct': (atr / data['price'] * 100) if data['price'] > 0 else 2.5,
            }
            _action, _confidence = predict_action(strategy, _features)
            if _action == 'BUY' and _confidence > 0.6:
                rl_bonus = int((_confidence - 0.5) * 20)
                rl_note = f'RL-BUY({_confidence:.0%}) '
            elif _action == 'SKIP' and _confidence > 0.7:
                rl_bonus = -int(_confidence * 15)
                rl_note = f'RL-SKIP({_confidence:.0%}) '
    except Exception:
        pass  # RL ist optional

    # ── Conviction zusammensetzen ────────────────────────────────────────────
    total_adjustment = dna_bonus + rl_bonus

    reason  = (
        f"Thesis+Tech: RSI={rsi_val:.0f}, Trend-OK, "
        f"Vol={data['vol_ratio']:.1f}x, CRV={crv:.1f}:1"
    )
    if dna_note or rl_note:
        reason += f" | {dna_note}{rl_note}(adj={total_adjustment:+d})"

    return {
        'entry':     data['price'],
        'stop':      round(stop, 4),
        'target':    round(target, 4),
        'crv':       round(crv, 2),
        'atr':       round(atr, 4),
        'hold_days': criteria['hold_days'],
        'reason':    reason,
        'dna_adjustment': dna_bonus,
        'rl_adjustment': rl_bonus,
    }


# ─── Paper Trade Ausführung ───────────────────────────────────────────────────

def execute_paper(ticker: str, strategy: str, entry: float, stop: float,
                  target: float, thesis: str, tier: str = 'TIER_B') -> dict:
    """Führt Paper Trade aus via paper_trade_engine."""
    try:
        from paper_trade_engine import execute_paper_entry
        result = execute_paper_entry(
            ticker=ticker,
            strategy=strategy,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            thesis=thesis,
            source=f'autonomous_scanner_v2:{tier}',
        )
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ─── Markt-Check ─────────────────────────────────────────────────────────────

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


# ─── Haupt-Scan ──────────────────────────────────────────────────────────────

MAX_NEW_TRADES_PER_RUN = 6  # erhöht von 3 für schnellere Datensammlung


def run_scan(max_new_trades: int = MAX_NEW_TRADES_PER_RUN) -> list:
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
        print(f"📅 Wochenende ({datetime.now(_BERLIN).strftime('%A')}) — kein Scan.")
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
    pending_added = 0  # Bugfix 2026-04-23: war nicht initialisiert → UnboundLocalError

    for tier, items in merged_universe.items():
        if new_trades >= max_new_trades:
            break

        # CEO-blockierte Strategie überspringen
        if '_blocked' in dir() and strategy in _blocked:
            results.append({'ticker': ticker, 'status': 'blocked_by_ceo', 'strategy': strategy})
            continue

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
            if get_free_cash() < 750:  # Fix: position_cap war undefined; 750 = halbes 1500€ Cap
                results.append({'ticker': ticker, 'tier': tier, 'status': 'low_cash'})
                break

            data = fetch_data(ticker)
            if data is None:
                results.append({'ticker': ticker, 'tier': tier, 'status': 'no_data'})
                time.sleep(0.2)
                continue

            setup = evaluate_setup(ticker, strategy, data)
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

            # evaluate_setup returns dict {entry, stop, target, reason, crv, atr, hold_days, ...}
            entry  = setup['entry']
            stop   = setup['stop']
            target = setup['target']
            reason = setup['reason']

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

        data = fetch_data(ticker)
        if data is None:
            results.append({'ticker': ticker, 'status': 'no_data'})
            time.sleep(0.3)
            continue

        setup = evaluate_setup(ticker, strategy, data)
        if setup is None:
            results.append({
                'ticker': ticker,
                'status': 'no_setup',
                'price':  data['price'],
                'rsi':    data.get('rsi'),
            })
            time.sleep(0.3)
            continue

        # DNA/RL-Adjustments auf Conviction anwenden
        _adj = setup.get('dna_adjustment', 0) + setup.get('rl_adjustment', 0)
        # Negativer Adjustment bei RL-SKIP → Trade überspringen
        if _adj <= -10:
            results.append({
                'ticker': ticker, 'status': 'skipped_by_learning',
                'reason': setup['reason'], 'adjustment': _adj,
            })
            time.sleep(0.3)
            continue

        thesis = f"[v2] {description} | {setup['reason']}"
        result = execute_paper(
            ticker, strategy,
            setup['entry'], setup['stop'], setup['target'],
            thesis
        )
        result['ticker']   = ticker
        result['strategy'] = strategy
        result['crv']      = setup['crv']
        result['reason']   = setup['reason']
        result['learning_adj'] = _adj
        results.append(result)

        if result.get('success'):
            new_trades += 1

        time.sleep(0.3)

    return results


# ─── Lab Mode ────────────────────────────────────────────────────────────────

ENTRY_THRESHOLD_LAB  = 35   # entspannter als normale 45
MAX_LAB_TRADES_PER_RUN = 4
LAB_RISK_PCT = 0.005         # 0.5% Risiko pro Trade (statt 2%)


def _thesis_gate_lab_ok(strategy: str) -> bool:
    """
    Gate 1 (Lab): ACTIVE und WATCHING erlaubt — nur INVALIDATED/PAUSED blockieren.
    """
    try:
        from thesis_engine import get_thesis_status
        status_dict = get_thesis_status(strategy)
        if not status_dict:
            return True
        blocked = {'INVALIDATED', 'PAUSED'}
        return status_dict.get('status', 'ACTIVE') not in blocked
    except Exception:
        return True


def execute_paper_lab(ticker: str, strategy: str, entry: float, stop: float,
                      target: float, thesis: str) -> dict:
    """
    Führt Lab-Trade direkt in DB aus — umgeht Conviction Guard.
    Verwendet LAB_RISK_PCT für Position-Sizing.
    """
    try:
        conn = get_db()

        # Duplikat-Check (inkl. LAB-Positionen)
        lab_strategy = strategy + '_LAB'
        r = conn.execute(
            "SELECT id FROM paper_portfolio WHERE ticker=? AND status='OPEN' AND strategy=?",
            (ticker.upper(), lab_strategy)
        ).fetchone()
        if r is not None:
            conn.close()
            return {'success': False, 'error': 'already_open_lab'}

        # Position-Sizing: LAB_RISK_PCT vom verfügbaren Cash
        free_cash = get_free_cash()
        portfolio_value = 25000.0
        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            conn.close()
            return {'success': False, 'error': 'invalid_stop'}

        shares = int(portfolio_value * LAB_RISK_PCT / risk_per_share)
        if shares <= 0:
            conn.close()
            return {'success': False, 'error': 'sizing_zero'}

        position_eur = shares * entry
        if position_eur > free_cash - 50:
            shares = max(1, int((free_cash - 50) / entry))
            position_eur = shares * entry

        if shares <= 0:
            conn.close()
            return {'success': False, 'error': 'insufficient_cash'}

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO paper_portfolio
            (ticker, strategy, entry_price, entry_date, shares, stop_price, target_price,
             status, fees, notes, style, conviction, regime_at_entry, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, 'swing', 35, 'LAB', 'UNKNOWN')
        """, (
            ticker.upper(), lab_strategy, entry, now, float(shares),
            stop, target, 0.5,
            f'LAB_MODE | {thesis}',
        ))

        conn.execute(
            "UPDATE paper_fund SET value = value - ? WHERE key = 'current_cash'",
            (position_eur + 0.5,)
        )

        trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        return {
            'success': True,
            'trade_id': trade_id,
            'position_eur': round(position_eur, 2),
            'shares': shares,
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def run_lab_scan() -> list:
    """
    Lab-Modus Scanner mit entspannten Parametern.
    - Gate 1: WATCHING erlaubt (nur INVALIDATED/PAUSED blockieren)
    - Gate 2: technische Kriterien identisch
    - Risiko: 0.5% statt 2%
    - Strategie in DB: strategy + '_LAB', notes = 'LAB_MODE'
    """
    if not is_market_open():
        print(
            f"Markt geschlossen "
            f"(heute: {datetime.now().strftime('%A')}) — kein Lab-Scan."
        )
        return []

    # Dynamic universe from strategies.json
    dynamic_entries = load_universe_from_strategies()
    full_universe = list(UNIVERSE) + dynamic_entries
    if dynamic_entries:
        print(f"[lab-scanner] {len(dynamic_entries)} dynamische Ticker aus strategies.json geladen")

    results = []
    new_trades = 0

    for ticker, strategy, description in full_universe:
        if new_trades >= MAX_LAB_TRADES_PER_RUN:
            break

        # Bereits offene LAB-Position für diesen Ticker?
        lab_strategy = strategy + '_LAB'
        try:
            conn = get_db()
            r = conn.execute(
                "SELECT id FROM paper_portfolio WHERE ticker=? AND status='OPEN' AND strategy=?",
                (ticker.upper(), lab_strategy)
            ).fetchone()
            conn.close()
            if r is not None:
                results.append({'ticker': ticker, 'status': 'already_open_lab'})
                continue
        except Exception:
            pass

        if open_count() >= 20:  # Lab hat höheres Limit
            results.append({'ticker': ticker, 'status': 'max_positions'})
            break

        data = fetch_data(ticker)
        if data is None:
            results.append({'ticker': ticker, 'status': 'no_data'})
            time.sleep(0.3)
            continue

        # Gate 1 (Lab): WATCHING erlaubt
        if not _thesis_gate_lab_ok(strategy):
            results.append({'ticker': ticker, 'status': 'thesis_blocked'})
            time.sleep(0.3)
            continue

        # Gate 2: technische Bestätigung (identisch mit Hauptscanner)
        criteria = THESIS_ENTRY_CRITERIA.get(strategy, THESIS_ENTRY_CRITERIA['DEFAULT'])

        if not criteria['trend'](data):
            results.append({'ticker': ticker, 'status': 'no_setup', 'price': data['price'], 'rsi': data.get('rsi')})
            time.sleep(0.3)
            continue

        if not criteria['momentum'](data):
            results.append({'ticker': ticker, 'status': 'no_setup', 'price': data['price'], 'rsi': data.get('rsi')})
            time.sleep(0.3)
            continue

        if not criteria['volume'](data):
            results.append({'ticker': ticker, 'status': 'no_setup', 'price': data['price'], 'rsi': data.get('rsi')})
            time.sleep(0.3)
            continue

        # Stop/Target berechnen
        closes = data.get('closes', [])
        highs  = data.get('highs', [])
        lows   = data.get('lows', [])
        atr    = _atr(closes, highs, lows)
        stop   = data['price'] - criteria['stop_atr'] * atr
        stop   = max(stop, data['price'] * 0.70)
        # Stop-Floor (min_stop_pct aus trade_style) — siehe Doku oben
        try:
            from trade_style import classify_strategy as _cls2, get_style_config as _gsc2
            _mp = _gsc2(_cls2(strategy)).min_stop_pct
        except Exception:
            _mp = 4.0
        _sf = data['price'] * (1 - _mp / 100)
        if stop > _sf:
            stop = _sf
        risk   = data['price'] - stop
        if risk <= 0:
            results.append({'ticker': ticker, 'status': 'no_setup'})
            time.sleep(0.3)
            continue

        target = data['price'] + criteria['target_r'] * risk
        crv    = (target - data['price']) / risk
        if crv < 2.0:
            results.append({'ticker': ticker, 'status': 'no_setup'})
            time.sleep(0.3)
            continue

        rsi_val = data.get('rsi') or 50
        thesis  = (
            f"[LAB] {description} | RSI={rsi_val:.0f}, "
            f"Vol={data['vol_ratio']:.1f}x, CRV={crv:.1f}:1"
        )

        result = execute_paper_lab(
            ticker, strategy,
            data['price'], round(stop, 4), round(target, 4),
            thesis
        )
        result['ticker']   = ticker
        result['strategy'] = lab_strategy
        result['crv']      = round(crv, 2)
        results.append(result)

        if result.get('success'):
            new_trades += 1

        time.sleep(0.3)

    return results


# ─── Summary ─────────────────────────────────────────────────────────────────

def print_summary(results: list):
    entered  = [r for r in results if r.get('success')]
    skipped  = [r for r in results if r.get('status') == 'no_setup']
    no_data  = [r for r in results if r.get('status') == 'no_data']
    open_pos = [r for r in results if r.get('status') == 'already_open']
    blocked  = [r for r in results if r.get('status') == 'max_positions']

    print("\n=== Autonomous Scanner v2 ===")
    print(f"  Neue Trades   : {len(entered)}")
    print(f"  Kein Setup    : {len(skipped)}")
    print(f"  Bereits offen : {len(open_pos)}")
    print(f"  Kein Preis    : {len(no_data)}")
    print(f"  Max Positionen: {len(blocked)}")

    if entered:
        print("\n  Neue Paper Trades:")
        for r in entered:
            print(
                f"    {r['ticker']:12} "
                f"CRV {r.get('crv', '?')}:1 | "
                f"Strat {r.get('strategy', '?'):6} | "
                f"{r.get('reason', '')[:60]}"
            )

    if skipped:
        print("\n  Kein Setup (Top 5):")
        for r in skipped[:5]:
            rsi_str = f"RSI={r['rsi']:.0f}" if r.get('rsi') else "RSI=n/a"
            print(
                f"    {r['ticker']:12} "
                f"Kurs={r.get('price', 0):.2f} | {rsi_str}"
            )


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys as _sys_cli
    if '--lab' in _sys_cli.argv:
        print(f"Lab-Scanner laeuft — max {MAX_LAB_TRADES_PER_RUN} neue Lab-Trades...")
        results = run_lab_scan()
        print_summary(results)
    else:
        max_t = int(_sys_cli.argv[1]) if len(_sys_cli.argv) > 1 and _sys_cli.argv[1].lstrip('-').isdigit() else MAX_NEW_TRADES_PER_RUN
        print(f"Autonomous Scanner v2 laeuft — max {max_t} neue Trades...")
        results = run_scan(max_new_trades=max_t)
        print_summary(results)
