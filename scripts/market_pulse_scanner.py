#!/usr/bin/env python3
"""
market_pulse_scanner.py — Phase 45ao Layer 1+2 (Victor 2026-05-11).

Täglich 06:00 vor dem Strategist-Slot. Scannt:
  - Sektor-ETFs + Spezial-ETFs (XLE, GDX, SLV, ITA, KRE, XBI, ...)
  - Relative Strength vs SPY
  - 1d/5d/30d Performance
  - Volume-Anomalien
  - Trend-Klassifikation pro ETF

Für die Top-3 Out-Performer + Top-3 Beschleuniger:
  - Drilldown auf die 8 größten Komponenten
  - Liquidity-Filter (Marketcap, Volume)
  - Setup-Klassifikation (Breakout / Pullback / Konsolidierung / Falling Knife)

Output: data/market_pulse_latest.json + data/market_pulse_latest.md (lesbar).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))

# Sektor-ETFs + Themen-ETFs (alle US-listed, hochliquide)
SECTOR_UNIVERSE = {
    'XLE':  'Energy',
    'XLF':  'Financials',
    'XLK':  'Technology',
    'XLI':  'Industrials',
    'XLU':  'Utilities',
    'XLP':  'Staples',
    'XLV':  'Healthcare',
    'XLY':  'Consumer Discretionary',
    'XLB':  'Materials',
    'XLRE': 'Real Estate',
    'XLC':  'Communications',
    # Themen
    'GDX':  'Gold Miners',
    'GDXJ': 'Junior Gold Miners',
    'SLV':  'Silver',
    'GLD':  'Gold',
    'URA':  'Uranium',
    'COPX': 'Copper Miners',
    'LIT':  'Lithium',
    'ITA':  'Defense',
    'KRE':  'Regional Banks',
    'XBI':  'Biotech',
    'ARKK': 'Innovation',
    'SMH':  'Semiconductors',
    'TAN':  'Solar',
    'IBIT': 'Bitcoin ETF',
    'IGV':  'Software (Bottom-Fishing Pool)',
    # Broad
    'SPY':  'S&P 500',
    'QQQ':  'NASDAQ',
    'IWM':  'Russell 2000',
    'DIA':  'DJIA',
}

# Komponenten pro Sektor (top 8-10 Holdings)
SECTOR_COMPONENTS = {
    'GDX':  ['NEM', 'GOLD', 'AEM', 'WPM', 'FNV', 'KGC', 'GFI', 'AU', 'AGI', 'PAAS'],
    'GDXJ': ['HMY', 'EQX', 'PAAS', 'HL', 'FSM', 'AG', 'CDE', 'EXK'],
    'SLV':  ['SLV', 'PAAS', 'HL', 'AG', 'FSM', 'CDE', 'EXK', 'SVM'],
    'XLE':  ['XOM', 'CVX', 'COP', 'EOG', 'SLB', 'OXY', 'PSX', 'MPC', 'PXD', 'VLO'],
    'XLF':  ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW'],
    'XLK':  ['AAPL', 'MSFT', 'NVDA', 'AVGO', 'AMD', 'CRM', 'ORCL', 'CSCO'],
    'XLI':  ['CAT', 'GE', 'UNP', 'BA', 'HON', 'UPS', 'RTX', 'LMT', 'DE', 'ETN'],
    'XLU':  ['NEE', 'DUK', 'SO', 'D', 'AEP', 'SRE', 'XEL', 'PEG'],
    'XLP':  ['PG', 'KO', 'WMT', 'COST', 'PEP', 'PM', 'MDLZ', 'CL'],
    'XLV':  ['LLY', 'JNJ', 'UNH', 'ABBV', 'MRK', 'TMO', 'ABT', 'PFE', 'BMY'],
    'XLY':  ['AMZN', 'TSLA', 'HD', 'MCD', 'NKE', 'LOW', 'BKNG', 'TJX'],
    'XLB':  ['LIN', 'SHW', 'FCX', 'ECL', 'NEM', 'APD', 'CTVA', 'DOW'],
    'ITA':  ['RTX', 'LMT', 'GE', 'BA', 'NOC', 'GD', 'TDG', 'LHX', 'HII'],
    'XBI':  ['REGN', 'VRTX', 'GILD', 'AMGN', 'BIIB', 'MRNA', 'EXEL', 'NBIX'],
    'SMH':  ['NVDA', 'TSM', 'AVGO', 'ASML', 'AMD', 'QCOM', 'TXN', 'AMAT', 'LRCX'],
    'COPX': ['FCX', 'SCCO', 'TECK', 'BHP', 'RIO', 'IVN', 'ANTO'],
    'LIT':  ['ALB', 'SQM', 'LAC', 'PLL', 'LTHM'],
    'KRE':  ['ZION', 'PNC', 'KEY', 'CFG', 'FITB', 'RF', 'TFC', 'HBAN'],
    'TAN':  ['ENPH', 'FSLR', 'SEDG', 'RUN', 'SHLS', 'CSIQ', 'JKS'],
    'URA':  ['CCJ', 'KAP.IL', 'PALAF', 'UEC', 'DNN', 'NXE'],
    # Phase 45av: Software-Bottom-Fishing aus IGV (iShares Software ETF Proxy)
    'IGV':  ['NET', 'RBRK', 'TEAM', 'APP', 'FSLY', 'CRWD', 'ZS', 'DDOG', 'SNOW',
              'MDB', 'PANW', 'OKTA', 'TWLO', 'CFLT'],
}


def _classify_trend(highs: list, lows: list, closes: list) -> str:
    """Klassifiziere Trend basierend auf letzten 20 Bars."""
    if len(closes) < 5: return 'INSUFFICIENT_DATA'
    last = closes[-1]
    week_ago = closes[-min(5, len(closes))]
    month_ago = closes[-min(20, len(closes))]
    high_20 = max(highs[-min(20, len(highs)):]) if highs else last
    low_20  = min(lows[-min(20, len(lows)):]) if lows else last
    range_pct = (high_20 - low_20) / low_20 * 100 if low_20 > 0 else 0
    chg_5d  = (last - week_ago) / week_ago * 100 if week_ago > 0 else 0
    chg_30d = (last - month_ago) / month_ago * 100 if month_ago > 0 else 0
    # Position in 20d-range
    rng_pos = (last - low_20) / max(high_20 - low_20, 0.01)

    # Klassifikation
    if chg_5d > 5 and rng_pos > 0.85:
        return 'BREAKOUT'  # neues Hoch + Momentum
    if chg_5d < -3 and chg_30d < -5:
        return 'FALLING_KNIFE'
    if chg_5d > 2 and chg_5d < 5 and rng_pos > 0.6 and rng_pos < 0.9:
        return 'PULLBACK_OPPORTUNITY'  # in Uptrend, leichter Rücksetzer
    if range_pct < 5:
        return 'CONSOLIDATION'  # eng eingegrenzt
    if chg_5d > 0 and chg_30d > 5:
        return 'UPTREND'
    if chg_5d < 0 and chg_30d < 0:
        return 'DOWNTREND'
    return 'RANGE'


def scan_etfs() -> list[dict]:
    """Scan alle Sektor-ETFs auf Performance + Trend."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    out = []
    spy_30d_chg = 0.0

    # Erst SPY für Relative-Strength
    try:
        spy = yf.Ticker('SPY').history(period='35d')
        if len(spy) > 0:
            spy_30d_chg = (spy['Close'].iloc[-1] - spy['Close'].iloc[0]) / spy['Close'].iloc[0] * 100
    except Exception: pass

    for ticker, sector in SECTOR_UNIVERSE.items():
        try:
            t = yf.Ticker(ticker)
            h = t.history(period='35d')
            if len(h) < 5: continue
            closes = h['Close'].tolist()
            highs  = h['High'].tolist()
            lows   = h['Low'].tolist()
            volumes = h['Volume'].tolist()

            last = closes[-1]
            chg_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0
            chg_5d = (closes[-1] - closes[-min(5, len(closes))]) / closes[-min(5, len(closes))] * 100
            chg_30d = (closes[-1] - closes[0]) / closes[0] * 100
            rs_vs_spy_30d = chg_30d - spy_30d_chg

            avg_vol_20d = sum(volumes[-20:]) / min(20, len(volumes))
            today_vol = volumes[-1]
            vol_ratio = today_vol / avg_vol_20d if avg_vol_20d > 0 else 1.0

            out.append({
                'ticker': ticker,
                'sector': sector,
                'last': round(last, 2),
                'chg_1d': round(chg_1d, 2),
                'chg_5d': round(chg_5d, 2),
                'chg_30d': round(chg_30d, 2),
                'rs_vs_spy_30d': round(rs_vs_spy_30d, 2),
                'vol_ratio': round(vol_ratio, 2),
                'trend': _classify_trend(highs, lows, closes),
            })
        except Exception as e:
            print(f'  WARN: {ticker}: {e}', file=sys.stderr)
    return out


def drilldown(top_etfs: list[str], min_marketcap: float = 1e9) -> dict:
    """Für Top-Sektor-ETFs: Komponenten-Performance + Liquidity + Setup."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    result = {}
    for etf in top_etfs:
        components = SECTOR_COMPONENTS.get(etf, [])
        if not components: continue
        comp_data = []
        for c in components[:10]:
            try:
                tk = yf.Ticker(c)
                h = tk.history(period='30d')
                if len(h) < 5: continue
                closes = h['Close'].tolist()
                highs  = h['High'].tolist()
                lows   = h['Low'].tolist()
                last = closes[-1]
                chg_5d  = (closes[-1] - closes[-min(5, len(closes))]) / closes[-min(5, len(closes))] * 100
                chg_30d = (closes[-1] - closes[0]) / closes[0] * 100
                try:
                    mc = float(tk.fast_info.market_cap or 0)
                except Exception:
                    mc = 0
                if mc < min_marketcap and mc > 0: continue
                trend = _classify_trend(highs, lows, closes)
                # ADR (Average Daily Range)
                ranges = [(highs[i] - lows[i]) / closes[i] * 100
                          for i in range(len(closes)) if closes[i] > 0]
                adr = sum(ranges[-20:]) / min(20, len(ranges)) if ranges else 0
                comp_data.append({
                    'ticker': c,
                    'last': round(last, 2),
                    'chg_5d': round(chg_5d, 2),
                    'chg_30d': round(chg_30d, 2),
                    'mc_bn': round(mc / 1e9, 1) if mc else None,
                    'adr_pct': round(adr, 2),
                    'trend': trend,
                })
            except Exception: pass
        # Sortiere Komponenten nach 5d-Performance
        comp_data.sort(key=lambda x: x.get('chg_5d', 0), reverse=True)
        result[etf] = comp_data
    return result


def build_report(etfs: list[dict], drilldowns: dict) -> dict:
    """Strukturiere Top-Lists + Drilldown."""
    etfs_sorted_5d = sorted([e for e in etfs if e['ticker'] not in ('SPY','QQQ','IWM','DIA')],
                            key=lambda x: x['chg_5d'], reverse=True)
    etfs_sorted_30d = sorted([e for e in etfs if e['ticker'] not in ('SPY','QQQ','IWM','DIA')],
                             key=lambda x: x['chg_30d'], reverse=True)
    etfs_sorted_rs = sorted([e for e in etfs if e['ticker'] not in ('SPY','QQQ','IWM','DIA')],
                            key=lambda x: x['rs_vs_spy_30d'], reverse=True)
    accel = [e for e in etfs if e['chg_5d'] > 0 and e['chg_30d'] > 0
             and e['chg_5d']/5 > e['chg_30d']/30]
    accel.sort(key=lambda x: x['chg_5d'] - x['chg_30d']/6, reverse=True)
    return {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'all_etfs': etfs,
        'top_5d': etfs_sorted_5d[:5],
        'bottom_5d': etfs_sorted_5d[-3:],
        'top_30d': etfs_sorted_30d[:5],
        'top_rs_vs_spy': etfs_sorted_rs[:5],
        'accelerating': accel[:5],
        'drilldowns': drilldowns,
        'spy_proxy': next((e for e in etfs if e['ticker'] == 'SPY'), {}),
    }


def to_markdown(report: dict) -> str:
    lines = [
        f"# Markt-Puls — {report['ts'][:16]} UTC",
        '',
        f"_Layer 1+2 Phase 45ao. SPY: {report['spy_proxy'].get('chg_5d', '?')}% / 5d, "
        f"{report['spy_proxy'].get('chg_30d', '?')}% / 30d._",
        '',
        '## TOP-5 OUT-PERFORMER (5d)',
        '',
        '| ETF | Sektor | 5d | 30d | RS vs SPY | Trend |',
        '|---|---|---|---|---|---|',
    ]
    for e in report['top_5d']:
        lines.append(f"| {e['ticker']} | {e['sector']} | {e['chg_5d']:+}% | {e['chg_30d']:+}% | "
                     f"{e['rs_vs_spy_30d']:+}% | {e['trend']} |")
    lines += ['', '## TOP-5 BESCHLEUNIGER (5d-Mom > 30d-Mom)', '',
              '| ETF | Sektor | 5d | 30d | Trend |', '|---|---|---|---|---|']
    for e in report['accelerating']:
        lines.append(f"| {e['ticker']} | {e['sector']} | {e['chg_5d']:+}% | {e['chg_30d']:+}% | {e['trend']} |")

    lines += ['', '## DRILLDOWN — Komponenten der Top-3', '']
    for etf, comps in list(report['drilldowns'].items())[:5]:
        lines.append(f"### {etf} ({SECTOR_UNIVERSE.get(etf, '?')})")
        lines.append('')
        lines.append('| Ticker | Preis | 5d | 30d | MC (Mrd) | ADR | Trend |')
        lines.append('|---|---|---|---|---|---|---|')
        for c in comps[:8]:
            lines.append(f"| {c['ticker']} | {c['last']} | {c['chg_5d']:+}% | "
                         f"{c['chg_30d']:+}% | {c.get('mc_bn','?')} | "
                         f"{c.get('adr_pct','?')}% | {c['trend']} |")
        lines.append('')
    return '\n'.join(lines)


def main() -> int:
    print('Scanning sector ETFs...')
    etfs = scan_etfs()
    if not etfs:
        print('ERROR: No ETF data')
        return 1
    print(f'  {len(etfs)} ETFs scanned.')

    # Top-3 outperformer 5d → drilldown
    etfs_sorted = sorted([e for e in etfs if e['ticker'] not in ('SPY','QQQ','IWM','DIA')],
                        key=lambda x: x['chg_5d'], reverse=True)
    top_3 = [e['ticker'] for e in etfs_sorted[:3]]
    print(f'  Top-3 outperformer: {top_3}')

    print('Drilldown components...')
    dd = drilldown(top_3)
    print(f'  {sum(len(v) for v in dd.values())} components analyzed.')

    report = build_report(etfs, dd)

    # Persist
    out_json = WS / 'data' / 'market_pulse_latest.json'
    out_md   = WS / 'data' / 'market_pulse_latest.md'
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    out_md.write_text(to_markdown(report), encoding='utf-8')
    print(f'Saved: {out_json}, {out_md}')

    # Top-3 console-Output
    print('\n=== TOP-3 5d ===')
    for e in report['top_5d'][:3]:
        print(f"  {e['ticker']}: {e['chg_5d']:+}% (5d), {e['chg_30d']:+}% (30d), trend={e['trend']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
