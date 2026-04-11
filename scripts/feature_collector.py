#!/usr/bin/env python3.14
"""
Feature Collector — Phase 1 des ML-Bauplans
=============================================
Sammelt Marktdaten zum Zeitpunkt jedes Trade-Entries.
Wird bei jedem neuen Trade aufgerufen (Integration in paper_trade_engine.py).

Gespeicherte Features:
  rsi_at_entry     — RSI(14) zum Einstiegszeitpunkt
  volume_ratio     — Volumen / Ø 20-Tage-Volumen
  vix_at_entry     — VIX-Level bei Entry
  atr_pct_at_entry — ATR(14) als % des Kurses
  ma50_distance    — % über/unter dem 50-Tage-MA
  day_of_week      — 0=Montag, 4=Freitag
  hour_of_entry    — Stunde des Eintrags (UTC)
  sector_momentum  — 5-Tage-Return des Sektor-ETF
  spy_5d_return    — 5-Tage-Return S&P 500 (Marktkontext)

Usage:
  from feature_collector import collect_features, backfill_open_positions
  features = collect_features("NVDA")   → dict mit allen Features
  backfill_open_positions()              → bestehende Trades anreichern
"""

import sqlite3
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

PYTHON = "/usr/local/bin/python3.14"
WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'

# Sektor-ETF Mapping (Ticker → Sektor-ETF)
SECTOR_ETF = {
    # Energy
    'OXY': 'XLE', 'EQNR': 'XLE', 'EQNR.OL': 'XLE', 'TTE.PA': 'XLE',
    'FRO': 'BOAT', 'DHT': 'BOAT', 'ZIM': 'BOAT',
    # Defense
    'HAG.DE': 'ITA', 'KTOS': 'ITA', 'HII': 'ITA', 'RHM.DE': 'ITA',
    # Tech
    'NVDA': 'QQQ', 'MSFT': 'QQQ', 'PLTR': 'QQQ', 'ASML': 'QQQ',
    # Metals/Mining
    'RIO.L': 'XME', 'BHP.L': 'XME', 'AG': 'SIL', 'HL': 'SIL',
    'PAAS': 'SIL', 'WPM': 'GDX', 'MOS': 'MOO',
    # Steel
    'STLD': 'SLX', 'NUE': 'SLX', 'CLF': 'SLX',
    # Pharma
    'BAYN.DE': 'XPH', 'NOVO-B.CO': 'XPH',
    # Autos
    'BMW.DE': 'CARZ',
    # Default
    'DEFAULT': 'SPY'
}


def _yahoo(ticker: str, period: str = '60d', interval: str = '1d') -> list[dict] | None:
    """Holt OHLCV-Daten von Yahoo Finance. Gibt Liste von Bars zurück."""
    try:
        enc = urllib.parse.quote(ticker)
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{enc}"
               f"?interval={interval}&range={period}")
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 (compatible; AlbertFeatures/1.0)'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        ohlcv = result['indicators']['quote'][0]
        closes = ohlcv.get('close', [])
        volumes = ohlcv.get('volume', [])

        bars = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            v = volumes[i] if i < len(volumes) else None
            if c is not None and c > 0:
                bars.append({'ts': ts, 'close': float(c), 'volume': v or 0})
        # Mindestens 5 Bars (für VIX/SPY am Wochenende ausreichend)
        return bars if len(bars) >= 5 else None
    except Exception as e:
        return None


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    """Berechnet RSI(14) aus Schlusskursen."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _calc_atr(bars: list[dict], period: int = 14) -> float | None:
    """Berechnet ATR(14) als % des aktuellen Kurses."""
    if len(bars) < period + 1:
        return None
    # Vereinfacht: nur Close-to-Close Ranges (kein High/Low in unserer API)
    closes = [b['close'] for b in bars[-period-1:]]
    ranges = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
    atr = sum(ranges) / len(ranges)
    current = closes[-1]
    return round(atr / current * 100, 3) if current > 0 else None


def collect_features(ticker: str) -> dict:
    """
    Haupt-Funktion: sammelt alle Features für einen Ticker.
    Gibt dict zurück — fehlende Features sind None (kein Abbruch).
    """
    # Phase 5: HMM-Regime als Feature
    hmm_regime_score = 1.0  # Default: NEUTRAL
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from regime_detector import get_regime_feature
        hmm_regime_score = get_regime_feature()
    except Exception:
        pass

    features = {
        'rsi_at_entry': None,
        'volume_ratio': None,
        'vix_at_entry': None,
        'atr_pct_at_entry': None,
        'ma50_distance': None,
        'day_of_week': datetime.now(timezone.utc).weekday(),
        'hour_of_entry': datetime.now(timezone.utc).hour,
        'sector_momentum': None,
        'spy_5d_return': None,
        'hmm_regime': hmm_regime_score,   # Phase 5: 0=BULL, 1=NEUTRAL, 2=RISK_OFF, 3=CRASH
        'feature_version': 2,             # Version bump: HMM hinzugefügt
    }

    # ── Ticker-Daten (60 Tage für MA50 + RSI + ATR) ──
    bars = _yahoo(ticker, period='60d')
    if bars and len(bars) >= 15:
        closes = [b['close'] for b in bars]
        volumes = [b['volume'] for b in bars]

        # RSI(14)
        features['rsi_at_entry'] = _calc_rsi(closes)

        # ATR(14) als %
        features['atr_pct_at_entry'] = _calc_atr(bars)

        # MA50 Distanz
        if len(closes) >= 50:
            ma50 = sum(closes[-50:]) / 50
            current = closes[-1]
            features['ma50_distance'] = round((current - ma50) / ma50 * 100, 2)

        # Volume Ratio (heute vs. Ø 20 Tage)
        if len(volumes) >= 21:
            avg_vol = sum(volumes[-21:-1]) / 20
            today_vol = volumes[-1]
            if avg_vol > 0:
                features['volume_ratio'] = round(today_vol / avg_vol, 2)

    # ── VIX ──
    vix_bars = _yahoo('^VIX', period='10d')
    if vix_bars:
        features['vix_at_entry'] = round(vix_bars[-1]['close'], 2)

    # ── SPY 5-Tage-Return ──
    spy_bars = _yahoo('SPY', period='10d')
    if spy_bars and len(spy_bars) >= 6:
        spy_closes = [b['close'] for b in spy_bars]
        spy_5d = (spy_closes[-1] - spy_closes[-6]) / spy_closes[-6] * 100
        features['spy_5d_return'] = round(spy_5d, 3)

    # ── Sektor-Momentum ──
    sector_etf = SECTOR_ETF.get(ticker, SECTOR_ETF.get(ticker.split('.')[0], 'SPY'))
    sector_bars = _yahoo(sector_etf, period='10d')
    if sector_bars and len(sector_bars) >= 6:
        s_closes = [b['close'] for b in sector_bars]
        s_5d = (s_closes[-1] - s_closes[-6]) / s_closes[-6] * 100
        features['sector_momentum'] = round(s_5d, 3)

    return features


def save_features(trade_id: int, features: dict) -> bool:
    """Speichert Features für einen Trade in der DB."""
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("""
            UPDATE paper_portfolio SET
                rsi_at_entry = ?,
                volume_ratio = ?,
                vix_at_entry = ?,
                atr_pct_at_entry = ?,
                ma50_distance = ?,
                day_of_week = ?,
                hour_of_entry = ?,
                sector_momentum = ?,
                spy_5d_return = ?,
                feature_version = ?
            WHERE id = ?
        """, (
            features.get('rsi_at_entry'),
            features.get('volume_ratio'),
            features.get('vix_at_entry'),
            features.get('atr_pct_at_entry'),
            features.get('ma50_distance'),
            features.get('day_of_week'),
            features.get('hour_of_entry'),
            features.get('sector_momentum'),
            features.get('spy_5d_return'),
            features.get('feature_version', 1),
            trade_id
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"  ⚠️  Feature save Fehler (Trade #{trade_id}): {e}")
        return False


def collect_and_save(trade_id: int, ticker: str) -> dict:
    """Kombiniert collect + save. Wird aus paper_trade_engine aufgerufen."""
    features = collect_features(ticker)
    save_features(trade_id, features)
    filled = sum(1 for v in features.values() if v is not None)
    total = len(features) - 1  # feature_version nicht zählen
    print(f"  🔬 Features: {filled}/{total} gesammelt für {ticker} (Trade #{trade_id})")
    return features


def backfill_open_positions() -> int:
    """
    Reichert alle offenen Trades ohne Feature-Daten nach.
    Nützlich für bestehende Positionen die vor Phase 1 eröffnet wurden.
    """
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    missing = conn.execute("""
        SELECT id, ticker FROM paper_portfolio
        WHERE status = 'OPEN'
          AND rsi_at_entry IS NULL
        ORDER BY entry_date DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    if not missing:
        print("Backfill: Alle offenen Positionen haben bereits Features.")
        return 0

    print(f"Backfill: {len(missing)} Positionen ohne Features → anreichern...")
    updated = 0
    for row in missing:
        features = collect_features(row['ticker'])
        if save_features(row['id'], features):
            filled = sum(1 for v in features.values() if v is not None)
            print(f"  ✅ {row['ticker']} (ID {row['id']}): {filled} Features gespeichert")
            updated += 1
        else:
            print(f"  ❌ {row['ticker']} (ID {row['id']}): Fehler")

    return updated


def feature_coverage_report() -> str:
    """Gibt Übersicht wie viele Trades Features haben."""
    conn = sqlite3.connect(str(DB))
    total = conn.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
    with_features = conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN' AND rsi_at_entry IS NOT NULL"
    ).fetchone()[0]
    closed_with = conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE status IN ('WIN','CLOSED','LOSS') AND rsi_at_entry IS NOT NULL"
    ).fetchone()[0]
    closed_total = conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE status IN ('WIN','CLOSED','LOSS')"
    ).fetchone()[0]
    conn.close()
    return (
        f"Feature Coverage: "
        f"Offen {with_features}/{total} | "
        f"Geschlossen {closed_with}/{closed_total} | "
        f"Für Feature-Importance brauchen wir 150+ geschlossene Trades mit Features"
    )


if __name__ == '__main__':
    import sys
    args = sys.argv[1:]

    if '--backfill' in args:
        n = backfill_open_positions()
        print(f"\n✅ {n} Positionen aktualisiert")
        print(feature_coverage_report())

    elif '--report' in args:
        print(feature_coverage_report())

    elif '--test' in args:
        ticker = args[args.index('--test') + 1] if len(args) > args.index('--test') + 1 else 'NVDA'
        print(f"[Feature Collector] Test für {ticker}...")
        f = collect_features(ticker)
        for k, v in f.items():
            status = '✅' if v is not None else '❌'
            print(f"  {status} {k:25s} = {v}")
    else:
        # Standard: Backfill + Report
        backfill_open_positions()
        print(feature_coverage_report())
