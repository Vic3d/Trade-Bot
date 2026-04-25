#!/usr/bin/env python3
"""
Net Liquidity Tracker — Phase 23
=================================
Pulls Fed-Bilanz-Daten + Repo-Indikatoren von FRED (St. Louis Fed, kein API-Key noetig)
und berechnet die 3 Liquiditaets-Kanaele aus dem Eriksen-Framework:

  1) ZENTRALBANK-LIQUIDITAET   = WALCL  − WTREGEN − RRPONTSYD
                                 (Fed Total Assets − TGA − Reverse Repo)
  2) PRIVATE KREDITSCHOEPFUNG  = BUSLOANS YoY Change %
  3) REPO-STRESS-LEVEL         = SOFR − IORB Spread in bps

Schreibt `data/macro_liquidity.json` mit:
  { net_liquidity_usd, net_liq_30d_change_pct, credit_creation_yoy_pct,
    sofr_iorb_bps, repo_stress, regime, components }

Discord-Alarm bei:
  - sofr_iorb_bps > 10  (Repo-Stress beginnt)
  - sofr_iorb_bps > 25  (Repo-Crisis)

Run:
  python3 -m scripts.macro.net_liquidity_tracker          # daily refresh
  python3 -m scripts.macro.net_liquidity_tracker --status # show last result
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', Path(__file__).resolve().parent.parent.parent))
OUT_FILE = WS / 'data' / 'macro_liquidity.json'

# FRED-Series die wir ziehen
FRED_SERIES = {
    'WALCL':       'Fed Total Assets (Mrd USD, weekly Wed)',
    'WTREGEN':     'Treasury General Account (Mrd USD, weekly)',
    'RRPONTSYD':   'Reverse Repo Operations (Mrd USD, daily)',
    'SOFR':        'Secured Overnight Financing Rate (%, daily)',
    'IORB':        'Interest on Reserve Balances (%, daily)',
    'BUSLOANS':    'C&I Loans (Mrd USD, weekly)',
    'TOTBKCR':     'Total Bank Credit (Mrd USD, weekly)',
}

FRED_CSV_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'

# Stress-Schwellen (Basispunkte)
SOFR_SPREAD_ELEVATED_BPS = 10
SOFR_SPREAD_CRISIS_BPS   = 25


# ──────────────────────────────────────────────────────────────────────────
# FRED-Pull (ohne API-Key, freier CSV-Endpoint)
# ──────────────────────────────────────────────────────────────────────────

def _fetch_fred(series: str, timeout: int = 30) -> list[tuple[str, float]]:
    """Returnt Liste von (date_str, value) absteigend sortiert (neueste zuerst)."""
    url = FRED_CSV_URL.format(series=series)
    req = urllib.request.Request(url, headers={'User-Agent': 'TradeMind/1.0 (+macro-tracker)'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise RuntimeError(f'FRED fetch fehlgeschlagen ({series}): {e}')

    rows: list[tuple[str, float]] = []
    for line in raw.splitlines()[1:]:  # skip header
        parts = line.split(',')
        if len(parts) < 2:
            continue
        date_s = parts[0].strip()
        val_s = parts[1].strip()
        if not val_s or val_s == '.':
            continue
        try:
            rows.append((date_s, float(val_s)))
        except ValueError:
            continue
    # sort descending (newest first)
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def _latest(rows: list[tuple[str, float]], default: float = 0.0) -> tuple[str | None, float]:
    if not rows:
        return None, default
    return rows[0]


def _value_at_offset(rows: list[tuple[str, float]], days_ago: int) -> tuple[str | None, float | None]:
    """Findet Wert ungefaehr N Tage in der Vergangenheit (nimmt naechsten verfuegbaren)."""
    if not rows:
        return None, None
    try:
        latest_date = datetime.fromisoformat(rows[0][0])
    except ValueError:
        return None, None
    target = latest_date.toordinal() - days_ago
    best = None
    best_diff = 9999
    for date_s, val in rows:
        try:
            d = datetime.fromisoformat(date_s).toordinal()
        except ValueError:
            continue
        diff = abs(d - target)
        if diff < best_diff:
            best_diff = diff
            best = (date_s, val)
        if d <= target:
            break
    return best if best else (None, None)


# ──────────────────────────────────────────────────────────────────────────
# Liquidity Computation
# ──────────────────────────────────────────────────────────────────────────

def compute_liquidity_snapshot() -> dict:
    """Zieht alle Series, berechnet die 3 Kanaele + Regime-Score."""
    data: dict[str, list] = {}
    errors: list[str] = []
    for series in FRED_SERIES:
        try:
            data[series] = _fetch_fred(series)
        except Exception as e:
            errors.append(f'{series}: {e}')
            data[series] = []

    # ─── Kanal 1: Zentralbank-Liquiditaet ───
    walcl_date, walcl = _latest(data['WALCL'])
    _, tga = _latest(data['WTREGEN'])
    _, rrp = _latest(data['RRPONTSYD'])
    # FRED-Einheiten: WALCL & WTREGEN in Mrd USD; RRPONTSYD in Mrd USD
    net_liq_bn = walcl - tga - rrp  # in Mrd USD

    # 30-Tage-Aenderung
    _, walcl_30d = _value_at_offset(data['WALCL'], 30)
    _, tga_30d = _value_at_offset(data['WTREGEN'], 30)
    _, rrp_30d = _value_at_offset(data['RRPONTSYD'], 30)
    net_liq_30d_change_pct = None
    if walcl_30d and tga_30d is not None and rrp_30d is not None:
        prev = walcl_30d - tga_30d - rrp_30d
        if prev != 0:
            net_liq_30d_change_pct = round(((net_liq_bn - prev) / abs(prev)) * 100, 2)

    cb_regime = 'neutral'
    if net_liq_30d_change_pct is not None:
        if net_liq_30d_change_pct > 1.5:
            cb_regime = 'expanding'
        elif net_liq_30d_change_pct < -1.5:
            cb_regime = 'contracting'

    # ─── Kanal 2: Private Kreditschoepfung (YoY %) ───
    _, busloans_now = _latest(data['BUSLOANS'])
    _, busloans_yoy = _value_at_offset(data['BUSLOANS'], 365)
    credit_yoy_pct = None
    if busloans_yoy:
        credit_yoy_pct = round(((busloans_now - busloans_yoy) / busloans_yoy) * 100, 2)

    credit_regime = 'stable'
    if credit_yoy_pct is not None:
        if credit_yoy_pct > 5:
            credit_regime = 'expanding'
        elif credit_yoy_pct < -1:
            credit_regime = 'contracting'

    # ─── Kanal 3: Repo-Stress (SOFR − IORB Spread) ───
    sofr_date, sofr = _latest(data['SOFR'])
    _, iorb = _latest(data['IORB'])
    sofr_iorb_bps = None
    if sofr and iorb:
        sofr_iorb_bps = round((sofr - iorb) * 100, 1)  # %-Diff → bps

    repo_stress = 'low'
    if sofr_iorb_bps is not None:
        if sofr_iorb_bps >= SOFR_SPREAD_CRISIS_BPS:
            repo_stress = 'crisis'
        elif sofr_iorb_bps >= SOFR_SPREAD_ELEVATED_BPS:
            repo_stress = 'elevated'

    # ─── Composite-Regime ───
    # 3-Channel-Score: each contributes -1/0/+1
    score = 0
    score += {'expanding': 1, 'neutral': 0, 'contracting': -1}.get(cb_regime, 0)
    score += {'expanding': 1, 'stable': 0, 'contracting': -1}.get(credit_regime, 0)
    score += {'low': 1, 'elevated': -1, 'crisis': -2}.get(repo_stress, 0)

    if score >= 2:
        composite = 'BULLISH'
    elif score >= 1:
        composite = 'CONSTRUCTIVE'
    elif score == 0:
        composite = 'NEUTRAL'
    elif score >= -1:
        composite = 'CAUTIOUS'
    else:
        composite = 'BEARISH'

    return {
        'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'composite_regime': composite,
        'composite_score': score,
        # Kanal 1
        'central_bank': {
            'regime': cb_regime,
            'net_liquidity_bn_usd': round(net_liq_bn, 1),
            'net_liq_30d_change_pct': net_liq_30d_change_pct,
            'walcl_bn': round(walcl, 1),
            'tga_bn': round(tga, 1),
            'rrp_bn': round(rrp, 1),
            'as_of': walcl_date,
        },
        # Kanal 2
        'credit_creation': {
            'regime': credit_regime,
            'busloans_yoy_pct': credit_yoy_pct,
            'busloans_now_bn': round(busloans_now, 1) if busloans_now else None,
        },
        # Kanal 3 — Wichtigster fuer kurzfristige Bewegungen
        'repo_stress': {
            'level': repo_stress,
            'sofr_iorb_bps': sofr_iorb_bps,
            'sofr_pct': sofr,
            'iorb_pct': iorb,
            'as_of': sofr_date,
            'thresholds': {
                'elevated_bps': SOFR_SPREAD_ELEVATED_BPS,
                'crisis_bps': SOFR_SPREAD_CRISIS_BPS,
            },
        },
        'fetch_errors': errors,
    }


def write_snapshot(snap: dict) -> Path:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding='utf-8')
    return OUT_FILE


def load_snapshot() -> dict | None:
    if not OUT_FILE.exists():
        return None
    try:
        return json.loads(OUT_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# Discord-Alert bei Stress
# ──────────────────────────────────────────────────────────────────────────

def maybe_alert(snap: dict, prev: dict | None) -> str | None:
    """Sendet Discord-Alert bei Repo-Stress-Eskalation. Returnt Alert-Text falls
    gesendet, sonst None."""
    repo_now = snap.get('repo_stress', {}).get('level', 'low')
    repo_prev = (prev or {}).get('repo_stress', {}).get('level', 'low')
    bps_now = snap.get('repo_stress', {}).get('sofr_iorb_bps')

    severity = {'low': 0, 'elevated': 1, 'crisis': 2}
    if severity.get(repo_now, 0) <= severity.get(repo_prev, 0):
        # Keine Eskalation → kein Alert (Stress kann sich auch normalisieren)
        if repo_now == 'crisis':
            # Crisis → trotzdem taeglich erinnern (dedupe key macht Discord-Spam-Schutz)
            pass
        else:
            return None

    if repo_now == 'low':
        return None

    icon = '⚠️' if repo_now == 'elevated' else '🚨'
    msg = (
        f'{icon} **REPO-STRESS: {repo_now.upper()}** (SOFR−IORB Spread = {bps_now}bps)\n'
        f'Composite-Regime: **{snap.get("composite_regime")}** (Score {snap.get("composite_score")})\n'
        f'CB-Liquiditaet: {snap["central_bank"]["regime"]} '
        f'({snap["central_bank"]["net_liq_30d_change_pct"]}% 30d)\n'
        f'Kredit: {snap["credit_creation"]["regime"]} '
        f'(YoY {snap["credit_creation"]["busloans_yoy_pct"]}%)\n'
    )
    if repo_now == 'crisis':
        msg += '→ **Repo-Crisis = Margin-Calls wahrscheinlich.** Korrelations-Override aktiv.'

    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM
        tier = TIER_HIGH if repo_now == 'crisis' else TIER_MEDIUM
        send_alert(msg, tier=tier, category='macro_repo_stress',
                   dedupe_key=f'repo_{repo_now}_{datetime.now().strftime("%Y-%m-%d")}')
    except Exception as e:
        print(f'[macro] Discord-Alert fehlgeschlagen: {e}', flush=True)
    return msg


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', action='store_true', help='Letzten Snapshot zeigen')
    ap.add_argument('--no-alert', action='store_true', help='Discord-Alert ueberspringen')
    args = ap.parse_args()

    if args.status:
        snap = load_snapshot()
        if not snap:
            print('Noch kein Snapshot. Run ohne --status.')
            return 1
        print(json.dumps(snap, indent=2, ensure_ascii=False))
        return 0

    print('[macro] Pulling FRED series ...', flush=True)
    prev = load_snapshot()
    snap = compute_liquidity_snapshot()
    write_snapshot(snap)

    rs = snap['repo_stress']
    cb = snap['central_bank']
    cr = snap['credit_creation']
    print(f"[macro] Composite: {snap['composite_regime']} (score {snap['composite_score']})")
    print(f"[macro]   CB-Liq:  {cb['regime']:13s} net={cb['net_liquidity_bn_usd']}bn USD "
          f"(30d: {cb['net_liq_30d_change_pct']}%)")
    print(f"[macro]   Credit:  {cr['regime']:13s} BUSLOANS YoY {cr['busloans_yoy_pct']}%")
    print(f"[macro]   Repo:    {rs['level']:13s} SOFR-IORB {rs['sofr_iorb_bps']}bps")
    if snap.get('fetch_errors'):
        for err in snap['fetch_errors']:
            print(f"[macro] WARN: {err}", flush=True)

    if not args.no_alert:
        alerted = maybe_alert(snap, prev)
        if alerted:
            print('[macro] Discord-Alert gesendet')
    return 0


if __name__ == '__main__':
    sys.exit(main())
