#!/usr/bin/env python3
"""
Entry Signal Engine — Verbesserung 3: Echte Chart-Setups statt "blind kaufen"
===========================================================================
Prüft für jeden Ticker ob ein technisches Entry-Signal vorliegt:
  - RSI-Oversold Bounce (RSI < 40 dreht nach oben)
  - Support-Hold (Kurs hält wichtiges Level)
  - Momentum-Break (Kurs bricht über EMA20)
  - VIX-Spike-Recovery (VIX war >30, fällt zurück)

P1.2 Update: VIX-Regime als Conviction-Faktor
  VIX < 20:    +1 (grünes Licht)
  VIX 20–25:    0 (neutral)
  VIX 25–30:   −1 (Vorsicht)
  VIX > 30:    −2 (Signal-Unterdrückung — kein Entry empfohlen)

P1.4 Update: Sentiment-Magnitude-Bonus
  magnitude 3 (Strong): +1 zusätzlich
"""
import urllib.request, json
from pathlib import Path
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
MARKET_REGIME_FILE = WS / 'memory/market-regime.json'


# ── CEO-Direktive ─────────────────────────────────────────────────────────────

def load_ceo_directive() -> dict | None:
    """
    Lädt die aktuelle CEO-Direktive aus data/ceo_directive.json.
    Returns None wenn nicht vorhanden, zu alt (>24h) oder beim Lesen fehlgeschlagen.
    """
    path = WS / 'data/ceo_directive.json'
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(d['timestamp'])
        if (datetime.now(_BERLIN) - ts).total_seconds() < 86400:
            return d
    except Exception:
        pass
    return None

# ── VIX-Regime ────────────────────────────────────────────────────────────────

def get_vix() -> float | None:
    """
    Liest VIX aus memory/market-regime.json.
    Fallback: Yahoo Finance ^VIX direkt holen wenn Datei fehlt oder >2h alt.
    Returns: VIX-Wert (float) oder None bei Fehler.
    """
    # Versuch 1: market-regime.json lesen
    if MARKET_REGIME_FILE.exists():
        try:
            data = json.loads(MARKET_REGIME_FILE.read_text(encoding="utf-8"))
            updated_str = data.get('updated', '')
            vix_val = data.get('indicators', {}).get('vix')
            if vix_val is not None and updated_str:
                # Stale-Check: älter als 2 Stunden?
                try:
                    updated_dt = datetime.strptime(updated_str, '%Y-%m-%d %H:%M')
                    age_hours = (datetime.now(_BERLIN) - updated_dt).total_seconds() / 3600
                    if age_hours <= 2.0:
                        return float(vix_val)
                    # Datei zu alt → Fallback auf Yahoo
                except ValueError:
                    return float(vix_val)  # Parse-Fehler beim Datum → Wert trotzdem nutzen
        except Exception:
            pass

    # Fallback: Yahoo Finance ^VIX
    try:
        url = 'https://query2.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        vix_live = d['chart']['result'][0]['meta']['regularMarketPrice']
        return float(vix_live)
    except Exception:
        return None


def vix_conviction_adjustment(vix: float | None) -> tuple[int, str, bool]:
    """
    Berechnet VIX-Conviction-Adjustment und ob Signal unterdrückt werden soll.

    Args:
        vix: VIX-Wert (oder None wenn nicht verfügbar)

    Returns:
        (score_delta, reason_string, suppress_signal)
        suppress_signal = True wenn VIX > 30 → kein Entry empfohlen
    """
    if vix is None:
        return 0, 'VIX: N/A', False

    if vix < 20:
        return +1, f'VIX {vix:.1f} < 20 (grünes Licht)', False
    elif vix < 25:
        return  0, f'VIX {vix:.1f} 20–25 (neutral)', False
    elif vix < 30:
        return -1, f'VIX {vix:.1f} 25–30 (Vorsicht)', False
    else:
        return -2, f'VIX {vix:.1f} > 30 (Signal-Unterdrückung)', True


def fetch_closes(ticker: str, days: int = 30) -> list:
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        closes = d['chart']['result'][0]['indicators']['quote'][0].get('close', [])
        return [c for c in closes if c][-days:]
    except:
        return []

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)

def calc_ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return round(ema, 4)

def check_entry_signal(ticker: str, current_price: float, magnitude: int = 1, paper_mode: bool = False) -> dict:
    """
    Prüft Entry-Signal für einen Ticker.

    Args:
        ticker: Ticker-Symbol (z.B. 'EQNR.OL', 'NVDA')
        current_price: Aktueller Kurs
        magnitude: Sentiment-Magnitude aus newswire_analyst (1–3). magnitude=3 → +1 Bonus.
        paper_mode: Wenn True → Paper Lab Experimental Mode:
                    - Kein CEO-Block (blocked_strategies ignoriert)
                    - Kein VIX-Unterdrückungslimit
                    - Score-Minimum: 0 (alles durch)
                    - Fügt 'paper_experimental': True zum Result hinzu

    Returns:
        dict mit signal, score, vix, vix_suppressed, reasons, ...
    """
    # CEO-Direktive prüfen (zuerst — CEO hat Vorrang, außer im Paper Mode)
    directive = load_ceo_directive()
    if directive and not paper_mode:
        trading_rules = directive.get('trading_rules', {})
        mode = directive.get('mode', 'NORMAL')

        # SHUTDOWN: Keine neuen Entries
        if mode == 'SHUTDOWN':
            return {
                'signal': 'CEO_BLOCKED',
                'score': 0,
                'reason': f'CEO SHUTDOWN: {directive.get("mode_reason", "System im Shutdown")}',
                'reasons': [f'CEO SHUTDOWN: {directive.get("mode_reason", "")}'],
                'vix': directive.get('vix'),
                'vix_suppressed': True,
            }

        # Strategy-Blockierung prüfen (wenn strategy_id übergeben)
        # Konvention: ticker kann "TICKER|STRATEGY_ID" sein oder nur Ticker
        strategy_id = None
        if '|' in ticker:
            ticker, strategy_id = ticker.split('|', 1)
        if strategy_id and strategy_id in trading_rules.get('blocked_strategies', []):
            return {
                'signal': 'CEO_BLOCKED',
                'score': 0,
                'reason': f'Strategie {strategy_id} von CEO geblockt',
                'reasons': [f'Strategie {strategy_id} geblockt ({mode})'],
                'vix': directive.get('vix'),
                'vix_suppressed': False,
            }

        # VIX-Adjustment vom CEO übernehmen
        _ceo_vix_adj = trading_rules.get('vix_conviction_adjustment', 0)
    elif paper_mode:
        # Paper Mode: CEO-Blocks ignorieren, ticker ggf. splitten
        if '|' in ticker:
            ticker, _ = ticker.split('|', 1)
        _ceo_vix_adj = 0
    else:
        _ceo_vix_adj = 0

    closes = fetch_closes(ticker, 30)
    if len(closes) < 15:
        return {'signal': 'NO_DATA', 'score': 0, 'reasons': [], 'vix': None, 'vix_suppressed': False}

    rsi = calc_rsi(closes)
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50) if len(closes) >= 50 else ema20

    prev_rsi = calc_rsi(closes[:-1]) if len(closes) > 15 else rsi
    price_vs_ema20 = (current_price - ema20) / ema20 * 100
    price_vs_ema50 = (current_price - ema50) / ema50 * 100

    score = 0
    reasons = []

    # Signal 1: RSI Oversold Bounce (RSI war <40, steigt wieder)
    # F4-Kalibrierung: war +3, jetzt max +2 — News-getriebene Bounces wurden überschätzt
    if prev_rsi < 40 and rsi > prev_rsi and rsi < 55:
        score += 2
        reasons.append(f'RSI Bounce: {prev_rsi:.0f}→{rsi:.0f}')

    # Signal 2: EMA20-Ausbruch (Kurs bricht von unten über EMA20)
    if -2 < price_vs_ema20 < 3:
        score += 2
        reasons.append(f'EMA20-Break: {price_vs_ema20:+.1f}%')
    elif price_vs_ema20 > 3:
        score += 1
        reasons.append(f'Über EMA20: +{price_vs_ema20:.1f}%')

    # Signal 3: Trend intact (über EMA50)
    if price_vs_ema50 > 0:
        score += 1
        reasons.append(f'Über EMA50: +{price_vs_ema50:.1f}%')

    # Signal 4: Momentum (letzte 3 Tage positiv)
    if len(closes) >= 4:
        momentum_3d = (closes[-1] - closes[-4]) / closes[-4] * 100
        if 0 < momentum_3d < 8:
            score += 1
            reasons.append(f'3d-Momentum: +{momentum_3d:.1f}%')
        elif momentum_3d >= 8:
            score -= 1
            reasons.append(f'Überkauft 3d: +{momentum_3d:.1f}%')

    # Malus: RSI überkauft
    if rsi > 70:
        score -= 2
        reasons.append(f'RSI überkauft: {rsi:.0f}')

    # P1.4 — Sentiment-Magnitude-Bonus
    if magnitude >= 3:
        score += 1
        reasons.append(f'Magnitude STRONG: +1')

    # P2.0 — Geopolitik-Boost (cap +2, war unkalibriert)
    # Lese geo_alert_level aus ceo_directive wenn vorhanden
    _geo_boost = 0
    if directive:
        geo_level = directive.get('geo_alert_level', 'LOW')
        if geo_level == 'HIGH':
            _geo_boost = 2
        elif geo_level == 'MEDIUM':
            _geo_boost = 1
        _geo_boost = min(_geo_boost, 2)  # Hard cap bei +2
        if _geo_boost > 0:
            score += _geo_boost
            reasons.append(f'Geopolitik {geo_level}: +{_geo_boost} (cap 2)')

    # P2.0 — Regime-Penalty: kein Regime bekannt → Score −1
    # Verhindert dass Entries bei unbekanntem Marktregime zu hoch bewertet werden
    _regime_known = False
    try:
        if MARKET_REGIME_FILE.exists():
            _rdata = json.loads(MARKET_REGIME_FILE.read_text(encoding="utf-8"))
            _regime_val = _rdata.get('regime', None)
            if _regime_val and _regime_val not in ('None', '', 'UNKNOWN'):
                _regime_known = True
    except Exception:
        pass
    if not _regime_known:
        score -= 1
        reasons.append('Regime=None: −1 (kein Marktregime bekannt)')

    # P1.2 — VIX-Regime
    vix = get_vix()
    vix_delta, vix_reason, vix_suppressed = vix_conviction_adjustment(vix)
    score += vix_delta
    reasons.append(vix_reason)

    # CEO VIX-Adjustment (zusätzlich zu P1.2)
    if _ceo_vix_adj != 0:
        score += _ceo_vix_adj
        reasons.append(f'CEO-Adjustment: {_ceo_vix_adj:+d}')

    # Signal-Unterdrückung bei VIX > 30 (nur Real-Mode, nicht Paper Lab)
    if vix_suppressed and not paper_mode:
        return {
            'signal': 'SUPPRESSED',
            'score': score,
            'rsi': rsi,
            'ema20': round(ema20, 2),
            'ema50': round(ema50, 2),
            'price_vs_ema20': round(price_vs_ema20, 1),
            'vix': vix,
            'vix_suppressed': True,
            'reasons': reasons,
        }

    # Paper Lab: Score-Minimum 0 — alles durch (auch negative Scores)
    if paper_mode:
        signal_type = 'STRONG' if score >= 5 else 'MODERATE' if score >= 3 else 'WEAK' if score >= 1 else 'PAPER_TEST'
        return {
            'signal': signal_type,
            'score': score,
            'rsi': rsi,
            'ema20': round(ema20, 2),
            'ema50': round(ema50, 2),
            'price_vs_ema20': round(price_vs_ema20, 1),
            'vix': vix,
            'vix_suppressed': False,
            'reasons': reasons,
            'paper_experimental': True,
        }

    signal_type = 'STRONG' if score >= 5 else 'MODERATE' if score >= 3 else 'WEAK' if score >= 1 else 'NO_SIGNAL'

    return {
        'signal': signal_type,
        'score': score,
        'rsi': rsi,
        'ema20': round(ema20, 2),
        'ema50': round(ema50, 2),
        'price_vs_ema20': round(price_vs_ema20, 1),
        'vix': vix,
        'vix_suppressed': False,
        'reasons': reasons,
    }

if __name__ == '__main__':
    import sys
    eurusd = 1.15
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['FCX', 'SMCI', 'LHA.DE', 'ANET', 'ZIM']

    # VIX einmalig holen und anzeigen
    vix = get_vix()
    vix_delta, vix_label, vix_suppress = vix_conviction_adjustment(vix)
    print(f"VIX: {vix:.1f} → {vix_label} (Δ{vix_delta:+d}, suppress={vix_suppress})\n")

    for t in tickers:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range=5d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=8) as r: d = json.load(r)
            price_raw = d['chart']['result'][0]['meta']['regularMarketPrice']
            is_usd = not any(t.endswith(x) for x in ['.DE','.PA','.AS','.L','.OL'])
            price = price_raw / eurusd if is_usd else price_raw
            sig = check_entry_signal(t, price)
            suppress_label = ' ⛔SUPPRESSED' if sig.get('vix_suppressed') else ''
            print(f"{t:12} {sig['signal']:10} Score:{sig['score']} RSI:{sig['rsi']:.0f} "
                  f"EMA20:{sig['price_vs_ema20']:+.1f}%{suppress_label} | {' | '.join(sig['reasons'])}")
        except Exception as e:
            print(f"{t}: {e}")
