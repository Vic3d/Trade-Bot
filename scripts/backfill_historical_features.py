#!/usr/bin/env python3
"""
Sub-7 #4: Historischer Backfill für Snapshot-Features in paper_portfolio.

Füllt sector_momentum, spy_5d_return, hmm_regime für alte CLOSED-Trades
deren entry_date vor der Aktivierung dieser Features lag (~10/50 fehlten
laut Audit 2026-04-23).

Ansatz: Yahoo gibt Bars für jedes Ticker bis 2 Jahre zurück. Wir holen
für jeden lückigen Trade die Bars um den entry_date herum (period=60d
ab entry_date) und berechnen die Features wie zur Entry-Zeit.

USAGE:
    python3 scripts/backfill_historical_features.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
DB = WS / 'data' / 'trading.db'

# ETF-Mapping aus feature_collector.py
SECTOR_ETF = {
    'AAPL': 'XLK', 'MSFT': 'XLK', 'NVDA': 'XLK', 'GOOGL': 'XLK', 'GOOG': 'XLK',
    'META': 'XLK', 'AMZN': 'XLY', 'TSLA': 'XLY', 'NFLX': 'XLC',
    'JPM': 'XLF', 'BAC': 'XLF', 'GS': 'XLF',
    'XOM': 'XLE', 'CVX': 'XLE', 'OXY': 'XLE',
    'JNJ': 'XLV', 'PFE': 'XLV', 'UNH': 'XLV',
    'CAT': 'XLI', 'BA': 'XLI', 'GE': 'XLI',
    'KO': 'XLP', 'PG': 'XLP', 'WMT': 'XLP',
    'NEE': 'XLU', 'DUK': 'XLU',
    'AMT': 'XLRE', 'PLD': 'XLRE',
    'DEFAULT': 'SPY',
}


def _yahoo_historical(ticker: str, end_date: str, days_back: int = 60) -> list[dict] | None:
    """Holt Bars für `ticker` bis `end_date` (ISO oder YYYY-MM-DD)."""
    try:
        end_dt = datetime.fromisoformat(end_date[:10])
        start_dt = end_dt - timedelta(days=days_back)
        period1 = int(start_dt.timestamp())
        period2 = int(end_dt.timestamp())
        enc = urllib.parse.quote(ticker)
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{enc}"
               f"?interval=1d&period1={period1}&period2={period2}")
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 (Backfill/1.0)'}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        closes = result['indicators']['quote'][0].get('close', [])
        bars = [
            {'ts': ts, 'close': float(c)}
            for ts, c in zip(timestamps, closes)
            if c is not None and c > 0
        ]
        return bars if len(bars) >= 5 else None
    except Exception as e:
        print(f"    yahoo error {ticker}: {e}")
        return None


def _compute_at_entry(ticker: str, entry_date: str) -> dict:
    """Berechnet sector_momentum, spy_5d_return, hmm_regime zum Entry-Zeitpunkt."""
    out = {'sector_momentum': None, 'spy_5d_return': None, 'hmm_regime': None}

    # SPY 5-Tage-Return (1 Woche vor entry_date bis entry_date)
    spy_bars = _yahoo_historical('SPY', entry_date, days_back=10)
    if spy_bars and len(spy_bars) >= 6:
        sc = [b['close'] for b in spy_bars]
        out['spy_5d_return'] = round((sc[-1] - sc[-6]) / sc[-6] * 100, 3)

    # Sektor-ETF Momentum
    base = ticker.split('.')[0]
    sector_etf = SECTOR_ETF.get(ticker, SECTOR_ETF.get(base, 'SPY'))
    sec_bars = _yahoo_historical(sector_etf, entry_date, days_back=10)
    if sec_bars and len(sec_bars) >= 6:
        sc = [b['close'] for b in sec_bars]
        out['sector_momentum'] = round((sc[-1] - sc[-6]) / sc[-6] * 100, 3)

    # hmm_regime: Approximation aus VIX-Level zum Entry
    # 0=BULL (VIX<15), 1=NEUTRAL (15-22), 2=RISK_OFF (22-30), 3=CRASH (>30)
    vix_bars = _yahoo_historical('^VIX', entry_date, days_back=5)
    if vix_bars:
        vix = vix_bars[-1]['close']
        if vix < 15: out['hmm_regime'] = 0.0
        elif vix < 22: out['hmm_regime'] = 1.0
        elif vix < 30: out['hmm_regime'] = 2.0
        else: out['hmm_regime'] = 3.0

    return out


def main():
    dry_run = '--dry-run' in sys.argv
    limit = 100
    for i, arg in enumerate(sys.argv):
        if arg == '--limit' and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, ticker, entry_date,
               sector_momentum, spy_5d_return, hmm_regime
        FROM paper_portfolio
        WHERE status = 'CLOSED'
          AND (sector_momentum IS NULL
               OR spy_5d_return IS NULL
               OR hmm_regime IS NULL)
        ORDER BY entry_date DESC
        LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        print("✅ Alle CLOSED-Trades haben bereits sector/spy/hmm-Features.")
        return

    print(f"📊 {len(rows)} Trades mit Lücken gefunden (DRY-RUN={dry_run})")
    updated = 0
    failed = 0

    for row in rows:
        ticker = row['ticker']
        entry_date = row['entry_date']
        if not entry_date:
            continue
        print(f"  {ticker} (id={row['id']}, entry={entry_date[:10]})...", end='')
        feats = _compute_at_entry(ticker, entry_date)
        # Nur Felder updaten die NULL sind
        sets = []
        params = []
        for col in ('sector_momentum', 'spy_5d_return', 'hmm_regime'):
            if row[col] is None and feats[col] is not None:
                sets.append(f'{col} = ?')
                params.append(feats[col])
        if not sets:
            print(' (keine Daten)')
            failed += 1
            continue
        if dry_run:
            print(f' DRY: {feats}')
            updated += 1
        else:
            params.append(row['id'])
            try:
                conn.execute(
                    f"UPDATE paper_portfolio SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
                updated += 1
                print(f' ✅ {len(sets)} Felder')
            except Exception as e:
                print(f' ❌ {e}')
                failed += 1
        time.sleep(0.3)  # Rate-Limit für Yahoo

    conn.close()
    print(f"\n✅ Fertig: {updated} updated, {failed} failed/skipped")


if __name__ == '__main__':
    main()
