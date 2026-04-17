#!/usr/bin/env python3
"""
Market Scanner — Phase 7.15 Discovery Source 2
================================================
Scannt ein liquides Universum (S&P 500 + DAX 40 + STOXX 50 large caps) nach:
  - Top Gainers / Losers (abs. 1-Day-Change > 5%)
  - Volume-Spikes (Volume > 1.5x 20-Tage-Durchschnitt)
  - Gap-Ups (Open > Previous Close * 1.03)

Neue Tickers (nicht in UNIVERSE/strategies) werden zu candidate_tickers.json
hinzugefuegt mit source_type='market_move'.

CLI:
  python3 scripts/discovery/market_scanner.py
  python3 scripts/discovery/market_scanner.py --dry
  python3 scripts/discovery/market_scanner.py --top 30
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'discovery'))

from candidates import add_candidate, is_new_ticker  # noqa: E402

# ─── Scan-Universum (liquide Large-Caps, curated) ───────────────────────────
# Nicht 100% vollstaendig — Fokus auf liquide Titel die News-relevant sind.

SP500_LARGE = [
    # Mega-Cap Tech
    'AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'TSLA', 'NVDA', 'AVGO', 'ORCL', 'CRM',
    'ADBE', 'AMD', 'INTC', 'QCOM', 'CSCO', 'IBM', 'TXN', 'MU', 'AMAT', 'LRCX',
    'KLAC', 'MRVL', 'PANW', 'SNPS', 'CDNS', 'NOW', 'UBER', 'PYPL', 'SQ', 'SHOP',
    # Financials
    'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW', 'AXP', 'V',
    'MA', 'COF', 'USB', 'PNC', 'TFC', 'SPGI', 'ICE', 'CME', 'MCO',
    # Healthcare/Pharma
    'UNH', 'JNJ', 'LLY', 'ABBV', 'PFE', 'MRK', 'TMO', 'ABT', 'DHR', 'BMY',
    'AMGN', 'GILD', 'CVS', 'CI', 'HUM', 'ELV', 'ISRG', 'MDT', 'SYK', 'REGN',
    'VRTX', 'BIIB', 'MRNA',
    # Energy
    'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'PSX', 'MPC', 'VLO', 'OXY', 'PXD',
    'HES', 'DVN', 'FANG', 'APA', 'HAL', 'BKR',
    # Industrials / Defense
    'BA', 'CAT', 'DE', 'GE', 'HON', 'LMT', 'RTX', 'NOC', 'GD', 'LHX',
    'TDG', 'MMM', 'UPS', 'FDX', 'UNP', 'CSX', 'NSC', 'WM',
    # Consumer
    'WMT', 'HD', 'COST', 'TGT', 'LOW', 'MCD', 'SBUX', 'NKE', 'DIS', 'NFLX',
    'CMG', 'YUM', 'ABNB', 'BKNG', 'MAR', 'HLT',
    # Staples / Defensive
    'PG', 'KO', 'PEP', 'PM', 'MO', 'MDLZ', 'CL', 'KMB', 'GIS', 'HSY',
    # Materials / Mining
    'FCX', 'NEM', 'GOLD', 'NUE', 'STLD', 'AA', 'SCCO', 'LIN',
    # Utilities
    'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'SRE', 'XEL',
    # Real Estate
    'PLD', 'AMT', 'EQIX', 'CCI', 'PSA',
    # Communication
    'T', 'VZ', 'TMUS', 'CMCSA',
    # Autos & EV
    'F', 'GM', 'RIVN', 'LCID',
    # Biotech watchlist
    'NBIX', 'INCY', 'EXAS',
    # Growth / Hot
    'PLTR', 'SNOW', 'NET', 'DDOG', 'CRWD', 'ZS', 'MDB', 'TEAM',
    # China ADRs
    'BABA', 'PDD', 'JD', 'BIDU', 'NIO', 'LI', 'XPEV',
]

DAX_40 = [
    'SAP.DE', 'SIE.DE', 'ALV.DE', 'DTE.DE', 'MUV2.DE', 'BAS.DE', 'BAYN.DE',
    'BMW.DE', 'MBG.DE', 'DB1.DE', 'DBK.DE', 'CBK.DE', 'VOW3.DE', 'LIN.DE',
    'IFX.DE', 'HEI.DE', 'HEN3.DE', 'ADS.DE', 'MRK.DE', 'PUM.DE', 'RHM.DE',
    'HAG.DE', 'EOAN.DE', 'RWE.DE', 'FRE.DE', 'CON.DE', 'MTX.DE', 'FME.DE',
    'BEI.DE', 'SY1.DE', 'HNR1.DE', 'PAH3.DE', '1COV.DE', 'AIR.DE', 'DHL.DE',
    'VNA.DE', 'ENR.DE', 'SHL.DE', 'P911.DE', 'ZAL.DE',
]

STOXX_LIQUID = [
    'ASML.AS', 'AIR.PA', 'SAF.PA', 'BNP.PA', 'OR.PA', 'MC.PA', 'SAN.PA',
    'TTE.PA', 'EL.PA', 'KER.PA', 'HO.PA', 'STLAP.PA', 'CAP.PA', 'ACA.PA',
    'DSY.PA', 'ENGI.PA', 'SGO.PA',  'RI.PA', 'BN.PA', 'VIE.PA',
    'NESN.SW', 'NOVN.SW', 'ROG.SW', 'ABBN.SW', 'ZURN.SW', 'UBSG.SW',
    'ISP.MI', 'UCG.MI', 'ENI.MI', 'ENEL.MI', 'STLAM.MI', 'RACE.MI',
    'IBE.MC', 'SAN.MC', 'BBVA.MC', 'ITX.MC',
    'NOVO-B.CO', 'MAERSK-B.CO', 'DSV.CO',
    'ERIC-B.ST', 'ATCO-A.ST', 'VOLV-B.ST', 'HM-B.ST', 'INVE-B.ST',
    'SHEL.L', 'BP.L', 'HSBA.L', 'GSK.L', 'AZN.L', 'ULVR.L', 'RIO.L',
    'BA.L', 'LLOY.L', 'BARC.L', 'PRU.L', 'DGE.L', 'NG.L', 'VOD.L',
]

UNIVERSE = list(dict.fromkeys(SP500_LARGE + DAX_40 + STOXX_LIQUID))

# Thresholds
MIN_ABS_CHANGE_PCT = 5.0     # 5% move ist Signal
MIN_VOLUME_RATIO = 1.5       # 1.5x Avg-Volume
GAP_UP_PCT = 3.0             # Open > PrevClose * 1.03
MIN_PRICE_USD = 3.0          # Penny-Stocks raus


def fetch_bulk_ohlcv(tickers: list[str], days: int = 25) -> dict:
    """Bulk-Download OHLCV fuer alle Tickers. Return {ticker: [{date, o, h, l, c, v}, ...]}."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError('yfinance nicht installiert')

    batch_size = 50
    result: dict[str, list[dict]] = {}

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        symbols = ' '.join(batch)
        try:
            df = yf.download(
                tickers=symbols,
                period=f'{days}d',
                interval='1d',
                group_by='ticker',
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception as e:
            print(f'[scanner] Batch-Fehler ({batch[0]}...): {e}')
            continue

        if df is None or df.empty:
            continue

        for tk in batch:
            try:
                sub = df[tk] if len(batch) > 1 else df
                if sub is None or sub.empty:
                    continue
                bars = []
                for dt, row in sub.dropna().iterrows():
                    try:
                        bars.append({
                            'date': dt.strftime('%Y-%m-%d'),
                            'o': float(row['Open']),
                            'h': float(row['High']),
                            'l': float(row['Low']),
                            'c': float(row['Close']),
                            'v': int(row['Volume']) if row['Volume'] == row['Volume'] else 0,
                        })
                    except Exception:
                        continue
                if len(bars) >= 5:
                    result[tk] = bars
            except Exception:
                continue

    return result


def analyze_ticker(ticker: str, bars: list[dict]) -> dict | None:
    """Berechnet 1-Day-Change, Volume-Ratio, Gap. Return None wenn kein Signal."""
    if len(bars) < 5:
        return None

    last = bars[-1]
    prev = bars[-2]

    if last['c'] < MIN_PRICE_USD:
        return None

    change_pct = (last['c'] - prev['c']) / prev['c'] * 100.0 if prev['c'] > 0 else 0.0

    avg_vol = sum(b['v'] for b in bars[:-1]) / max(1, len(bars) - 1)
    vol_ratio = last['v'] / avg_vol if avg_vol > 0 else 0.0

    gap_pct = (last['o'] - prev['c']) / prev['c'] * 100.0 if prev['c'] > 0 else 0.0

    signals = []
    if abs(change_pct) >= MIN_ABS_CHANGE_PCT:
        signals.append('gainer' if change_pct > 0 else 'loser')
    if vol_ratio >= MIN_VOLUME_RATIO:
        signals.append('volume_spike')
    if gap_pct >= GAP_UP_PCT:
        signals.append('gap_up')
    elif gap_pct <= -GAP_UP_PCT:
        signals.append('gap_down')

    if not signals:
        return None

    return {
        'ticker': ticker,
        'close': last['c'],
        'change_pct': round(change_pct, 2),
        'vol_ratio': round(vol_ratio, 2),
        'gap_pct': round(gap_pct, 2),
        'signals': signals,
    }


def compute_score(result: dict) -> float:
    """Scoring fuer Priority: Gainer = bullish, Loser = bearish but interesting."""
    base = min(abs(result['change_pct']) / 15.0, 1.0)  # 15% = max score from move
    if result['vol_ratio'] >= 3.0:
        base = min(1.0, base + 0.2)
    if 'gap_up' in result['signals']:
        base = min(1.0, base + 0.1)
    # Gainer slightly higher priority (bullish bias for entries)
    if result['change_pct'] > 0:
        base = min(1.0, base + 0.05)
    return round(base, 2)


def run(dry: bool = False, top_n: int = 20) -> dict:
    print(f'[scanner] Universum: {len(UNIVERSE)} Tickers')
    ohlcv = fetch_bulk_ohlcv(UNIVERSE)
    print(f'[scanner] Daten erhalten fuer {len(ohlcv)}/{len(UNIVERSE)} Tickers')

    signals = []
    for tk, bars in ohlcv.items():
        r = analyze_ticker(tk, bars)
        if r:
            signals.append(r)

    # Sort by abs change descending
    signals.sort(key=lambda x: abs(x['change_pct']), reverse=True)
    signals = signals[:top_n]

    print(f'[scanner] {len(signals)} Signale (Top {top_n}):')
    for s in signals[:10]:
        print(f"  {s['ticker']:12s} {s['change_pct']:+6.2f}%  vol={s['vol_ratio']:.1f}x  {','.join(s['signals'])}")

    if dry:
        return {'status': 'dry', 'signals': signals}

    new_count = 0
    for s in signals:
        tk = s['ticker']
        if not is_new_ticker(tk):
            continue
        score = compute_score(s)
        source_type = 'gainer' if s['change_pct'] > 0 else 'loser'
        detail = (
            f"{s['change_pct']:+.1f}% @ {s['close']:.2f}  "
            f"vol={s['vol_ratio']:.1f}x  {','.join(s['signals'])}"
        )
        if add_candidate(tk, source_type, detail, score=score):
            new_count += 1
            print(f'  + {tk} score={score:.2f} — {detail}')

    print(f'[scanner] {new_count} neue Kandidaten')
    return {
        'status': 'ok',
        'scanned': len(ohlcv),
        'signals': len(signals),
        'new_candidates': new_count,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--top', type=int, default=20)
    args = ap.parse_args()
    result = run(dry=args.dry, top_n=args.top)
    sys.exit(0 if result.get('status') in ('ok', 'dry') else 2)


if __name__ == '__main__':
    main()
