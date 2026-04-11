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

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
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
    try:
        conn = get_db()
        r = conn.execute("SELECT value FROM paper_fund WHERE key='cash'").fetchone()
        conn.close()
        return r['value'] if r else 5000.0
    except Exception:
        return 5000.0


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
                  target: float, thesis: str) -> dict:
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
            source='autonomous_scanner_v2',
        )
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ─── Markt-Check ─────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    """Prüft ob mindestens eine der gehandelten Börsen heute offen ist."""
    try:
        from market_hours import is_any_trading_day
        all_tickers = [t for t, _, _ in UNIVERSE]
        return is_any_trading_day(all_tickers)
    except Exception:
        return datetime.now(timezone.utc).weekday() < 5


# ─── Haupt-Scan ──────────────────────────────────────────────────────────────

MAX_NEW_TRADES_PER_RUN = 6  # erhöht von 3 für schnellere Datensammlung


def run_scan(max_new_trades: int = MAX_NEW_TRADES_PER_RUN) -> list:
    """
    Neuer Dual-Gate Scanner.
    Max 6 neue Trades pro Lauf (erhöht von 3 für schnellere Datensammlung).

    VIX ist kein Hard-Block mehr — wird als Multiplikator für
    Position-Sizing in paper_trade_engine gehandhabt.
    """
    if not is_market_open():
        print(
            f"Markt geschlossen "
            f"(heute: {datetime.now().strftime('%A')}) — kein Scan."
        )
        return []

    # ── CEO-Modus-Enforcement ────────────────────────────────────────────
    try:
        import json as _json
        _directive_path = WS / 'data' / 'ceo_directive.json'
        if _directive_path.exists():
            _directive = _json.loads(_directive_path.read_text(encoding='utf-8'))
            _mode = _directive.get('mode', 'NORMAL')
            if _mode == 'SHUTDOWN':
                print(f"CEO-Modus: SHUTDOWN — keine neuen Trades erlaubt.")
                return []
            elif _mode == 'DEFENSIVE':
                max_new_trades = min(max_new_trades, 2)
                print(f"CEO-Modus: DEFENSIVE — max {max_new_trades} Trades pro Lauf.")
            # Check blocked strategies
            _rules = _directive.get('trading_rules', {})
            _blocked = set(_rules.get('blocked_strategies', []))
            if _blocked:
                print(f"CEO blockiert {len(_blocked)} Strategien: {_blocked}")
    except Exception as _e:
        print(f"CEO-Direktive nicht lesbar: {_e} — Scanner läuft im Normalmodus.")

    # Dynamic universe from strategies.json
    dynamic_entries = load_universe_from_strategies()
    full_universe = list(UNIVERSE) + dynamic_entries
    if dynamic_entries:
        print(f"[scanner] {len(dynamic_entries)} dynamische Ticker aus strategies.json geladen")

    results = []
    new_trades = 0

    for ticker, strategy, description in full_universe:
        if new_trades >= max_new_trades:
            break

        # CEO-blockierte Strategie überspringen
        if '_blocked' in dir() and strategy in _blocked:
            results.append({'ticker': ticker, 'status': 'blocked_by_ceo', 'strategy': strategy})
            continue

        if has_open(ticker):
            results.append({'ticker': ticker, 'status': 'already_open'})
            continue

        if open_count() >= 15:
            results.append({'ticker': ticker, 'status': 'max_positions'})
            break

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
