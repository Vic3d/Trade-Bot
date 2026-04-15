#!/usr/bin/env python3
"""
Macro Brain — Phase 11

Kostenlose Macro-Regime-Erkennung via FRED (Federal Reserve St. Louis).
Kein API-Key nötig — FRED stellt CSV-Downloads öffentlich bereit.

Indikatoren:
- DGS10          10-Year Treasury Yield
- DGS2           2-Year Treasury Yield
- T10Y2Y         10Y-2Y Spread (Rezessions-Signal wenn < 0)
- VIXCLS         VIX Close
- DTWEXBGS       US Dollar Broad Index
- CPIAUCSL       CPI All Items (für YoY-Inflation)
- UNRATE         Unemployment Rate
- BAMLH0A0HYM2   High-Yield Credit Spread
- T10YIE         10Y Breakeven Inflation Expectation
- FEDFUNDS       Fed Funds Rate

Output: data/macro_regime.json
  {
    'regime': 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF' | 'STAGFLATION' | 'RECESSION',
    'score':  -100..+100  (+ = risk-on, - = risk-off),
    'components': {...alle roh-metriken...},
    'signals': [...erklärungen...],
    'bias': 'BULLISH' | 'NEUTRAL' | 'BEARISH',
    'updated_at': isoformat,
  }
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    HAS_CFFI = True
except Exception:
    HAS_CFFI = False
    import urllib.request

log = logging.getLogger('macro_brain')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
DATA = WS / 'data'
CACHE_DIR = DATA / 'fred_cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = DATA / 'macro_regime.json'

FRED_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
CACHE_TTL = 6 * 3600  # 6h


def _http_get(url: str, timeout: int = 20) -> str | None:
    try:
        if HAS_CFFI:
            r = cffi_requests.get(url, timeout=timeout, impersonate='chrome124')
            return r.text if r.status_code == 200 else None
        req = urllib.request.Request(url, headers={'User-Agent': 'TradeMind/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log.warning(f'FRED fetch {url} failed: {e}')
        return None


def _fetch_series(series_id: str) -> list[tuple[date, float]]:
    """Return list of (date, value) tuples, newest last, '.' entries skipped."""
    cache = CACHE_DIR / f'{series_id}.csv'
    if cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_TTL:
        csv_text = cache.read_text(encoding='utf-8')
    else:
        csv_text = _http_get(FRED_CSV.format(series_id=series_id))
        if csv_text:
            try:
                cache.write_text(csv_text, encoding='utf-8')
            except Exception:
                pass

    if not csv_text:
        return []

    out: list[tuple[date, float]] = []
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader, None)
    for row in reader:
        if len(row) < 2:
            continue
        date_str, val = row[0].strip(), row[1].strip()
        if val in ('.', '', 'ND'):
            continue
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            out.append((d, float(val)))
        except Exception:
            continue
    return out


def _latest(series: list[tuple[date, float]]) -> float | None:
    return series[-1][1] if series else None


def _value_at_or_before(series: list[tuple[date, float]], target_d: date) -> float | None:
    """Wert am oder vor einem Datum (für YoY-Berechnung)."""
    best: float | None = None
    for d, v in series:
        if d <= target_d:
            best = v
        else:
            break
    return best


# ─────────────────────── Regime Classifier ─────────────────────

def classify_regime(components: dict) -> dict:
    """
    Berechnet Macro-Score (-100..+100) und leitet Regime + Bias ab.

    Positive Punkte  = Risk-On (Aktien bullish)
    Negative Punkte  = Risk-Off (Aktien bearish)
    """
    score = 0
    signals: list[str] = []

    vix = components.get('vix')
    t10y2y = components.get('t10y2y')
    t10y = components.get('t10y')
    t2y = components.get('t2y')
    dxy = components.get('dxy')
    cpi_yoy = components.get('cpi_yoy')
    unrate = components.get('unrate')
    unrate_6m_ago = components.get('unrate_6m_ago')
    hy_spread = components.get('hy_spread')
    t10yie = components.get('t10yie')
    fedfunds = components.get('fedfunds')

    # 1) VIX Regime (±25)
    if vix is not None:
        if vix < 15:
            score += 20; signals.append(f'VIX {vix:.1f} complacent (+20)')
        elif vix < 18:
            score += 15; signals.append(f'VIX {vix:.1f} calm (+15)')
        elif vix < 22:
            signals.append(f'VIX {vix:.1f} neutral (0)')
        elif vix < 28:
            score -= 15; signals.append(f'VIX {vix:.1f} elevated (-15)')
        elif vix < 35:
            score -= 25; signals.append(f'VIX {vix:.1f} stressed (-25)')
        else:
            score -= 35; signals.append(f'VIX {vix:.1f} panic (-35)')

    # 2) Yield Curve (±25) — Rezessions-Signal bei Inversion
    if t10y2y is not None:
        if t10y2y >= 1.0:
            score += 10; signals.append(f'Curve +{t10y2y:.2f}pp steep (+10)')
        elif t10y2y >= 0.25:
            score += 5; signals.append(f'Curve +{t10y2y:.2f}pp normal (+5)')
        elif t10y2y >= 0:
            signals.append(f'Curve +{t10y2y:.2f}pp flat (0)')
        elif t10y2y >= -0.5:
            score -= 15; signals.append(f'Curve {t10y2y:.2f}pp inverted (-15)')
        else:
            score -= 25; signals.append(f'Curve {t10y2y:.2f}pp deeply inverted (-25)')

    # 3) High-Yield Credit Spread (±20)
    if hy_spread is not None:
        if hy_spread < 3.5:
            score += 15; signals.append(f'HY spread {hy_spread:.2f}% tight (+15)')
        elif hy_spread < 5.0:
            score += 5; signals.append(f'HY spread {hy_spread:.2f}% normal (+5)')
        elif hy_spread < 6.5:
            signals.append(f'HY spread {hy_spread:.2f}% neutral (0)')
        elif hy_spread < 8.0:
            score -= 10; signals.append(f'HY spread {hy_spread:.2f}% widening (-10)')
        else:
            score -= 20; signals.append(f'HY spread {hy_spread:.2f}% distressed (-20)')

    # 4) CPI YoY Inflation (±15) — hoch = Stagflation-Risiko
    if cpi_yoy is not None:
        if cpi_yoy < 1.5:
            score -= 5; signals.append(f'CPI YoY {cpi_yoy:.1f}% deflationary (-5)')
        elif cpi_yoy <= 2.5:
            score += 10; signals.append(f'CPI YoY {cpi_yoy:.1f}% on-target (+10)')
        elif cpi_yoy <= 3.5:
            signals.append(f'CPI YoY {cpi_yoy:.1f}% slightly hot (0)')
        elif cpi_yoy <= 5.0:
            score -= 10; signals.append(f'CPI YoY {cpi_yoy:.1f}% hot (-10)')
        else:
            score -= 20; signals.append(f'CPI YoY {cpi_yoy:.1f}% runaway (-20)')

    # 5) Unemployment Trend (±15) — steigend = rezessionsnah (Sahm-Rule lite)
    if unrate is not None and unrate_6m_ago is not None:
        delta = unrate - unrate_6m_ago
        if delta <= -0.2:
            score += 10; signals.append(f'Unemp -{abs(delta):.1f}pp improving (+10)')
        elif delta < 0.3:
            signals.append(f'Unemp {delta:+.1f}pp stable (0)')
        elif delta < 0.5:
            score -= 10; signals.append(f'Unemp {delta:+.1f}pp rising (-10)')
        else:
            score -= 20; signals.append(f'Unemp {delta:+.1f}pp SAHM-trigger (-20)')

    # 6) Breakeven Inflation (±5) — Erwartungs-Check
    if t10yie is not None:
        if 2.0 <= t10yie <= 2.5:
            score += 5; signals.append(f'Breakeven {t10yie:.2f}% anchored (+5)')
        elif t10yie > 3.0:
            score -= 10; signals.append(f'Breakeven {t10yie:.2f}% unanchored (-10)')

    # Clamp
    score = max(-100, min(100, score))

    # Regime ableiten
    inverted_curve = (t10y2y is not None and t10y2y < 0)
    high_inflation = (cpi_yoy is not None and cpi_yoy > 3.5)
    rising_unemp = (unrate is not None and unrate_6m_ago is not None
                    and (unrate - unrate_6m_ago) >= 0.3)

    if inverted_curve and rising_unemp:
        regime = 'RECESSION'
    elif high_inflation and rising_unemp:
        regime = 'STAGFLATION'
    elif score >= 25:
        regime = 'RISK_ON'
    elif score <= -25:
        regime = 'RISK_OFF'
    else:
        regime = 'NEUTRAL'

    if regime == 'RISK_ON':
        bias = 'BULLISH'
    elif regime in ('RISK_OFF', 'RECESSION', 'STAGFLATION'):
        bias = 'BEARISH'
    else:
        bias = 'NEUTRAL'

    return {
        'regime': regime,
        'score': score,
        'bias': bias,
        'signals': signals,
    }


# ─────────────────────── Main Job ──────────────────────────────

def run() -> dict:
    """Fetch all FRED series + classify + write output."""
    from datetime import timedelta

    series_ids = {
        'vix':       'VIXCLS',
        't10y':      'DGS10',
        't2y':       'DGS2',
        't10y2y':    'T10Y2Y',
        'dxy':       'DTWEXBGS',
        'cpi':       'CPIAUCSL',
        'unrate':    'UNRATE',
        'hy_spread': 'BAMLH0A0HYM2',
        't10yie':    'T10YIE',
        'fedfunds':  'FEDFUNDS',
    }

    raw: dict[str, list[tuple[date, float]]] = {}
    for key, sid in series_ids.items():
        raw[key] = _fetch_series(sid)

    components: dict[str, float | None] = {}
    for k, seq in raw.items():
        components[k] = _latest(seq)

    # CPI YoY berechnen (CPIAUCSL ist Level, nicht YoY)
    cpi_series = raw.get('cpi', [])
    cpi_yoy = None
    if cpi_series:
        latest_d, latest_v = cpi_series[-1]
        year_ago_d = date(latest_d.year - 1, latest_d.month, min(latest_d.day, 28))
        year_ago_v = _value_at_or_before(cpi_series, year_ago_d)
        if year_ago_v and year_ago_v > 0:
            cpi_yoy = round((latest_v / year_ago_v - 1.0) * 100, 2)
    components['cpi_yoy'] = cpi_yoy

    # Unemployment 6M ago
    unrate_series = raw.get('unrate', [])
    unrate_6m = None
    if unrate_series and len(unrate_series) > 6:
        latest_d, _ = unrate_series[-1]
        target = latest_d - timedelta(days=180)
        unrate_6m = _value_at_or_before(unrate_series, target)
    components['unrate_6m_ago'] = unrate_6m

    # Als-Dict runden für JSON Output
    rounded = {k: (round(v, 3) if isinstance(v, (int, float)) else v)
               for k, v in components.items()}

    verdict = classify_regime(components)

    result = {
        'regime': verdict['regime'],
        'score': verdict['score'],
        'bias': verdict['bias'],
        'signals': verdict['signals'],
        'components': rounded,
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'date': date.today().isoformat(),
    }

    try:
        OUTPUT_FILE.write_text(json.dumps(result, indent=2), encoding='utf-8')
    except Exception as e:
        log.warning(f'macro_regime.json write failed: {e}')

    # Nicht-destruktiver Merge in ceo_directive.json:
    # Wir touchen NUR den `macro`-Subkey, alle anderen Felder bleiben erhalten.
    try:
        directive_file = DATA / 'ceo_directive.json'
        if directive_file.exists():
            directive = json.loads(directive_file.read_text(encoding='utf-8'))
        else:
            directive = {}
        directive['macro'] = {
            'regime': result['regime'],
            'score': result['score'],
            'bias': result['bias'],
            'updated_at': result['updated_at'],
        }
        directive_file.write_text(json.dumps(directive, indent=2), encoding='utf-8')
    except Exception as e:
        log.warning(f'ceo_directive macro-merge failed: {e}')

    return result


def _print_result(r: dict) -> None:
    icon = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '⚪'}.get(r['bias'], '?')
    print(f'\n{icon} Macro Regime: {r["regime"]}  Score {r["score"]:+d}  [{r["bias"]}]')
    print(f'   Date: {r["date"]}')
    print('\n   Components:')
    for k, v in r['components'].items():
        print(f'     {k:14}  {v}')
    print('\n   Signals:')
    for s in r['signals']:
        print(f'     • {s}')


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    r = run()
    _print_result(r)


if __name__ == '__main__':
    main()
