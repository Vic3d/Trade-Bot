#!/usr/bin/env python3
"""
Benchmark Tracker — Verbesserung 4: Schlägt Paper Labs Buy&Hold SPY?
====================================================================
Vergleicht Albert's Fund Performance mit:
  - SPY (S&P 500 ETF) Buy & Hold
  - 60/40 Portfolio (SPY + TLT)
Täglich aktualisiert. Output → data/benchmark.json
"""
import sqlite3, json, urllib.request
from pathlib import Path
from datetime import datetime, date

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
BENCH_JSON = WS / 'data/benchmark.json'
CAPITAL = 25000.0

def yahoo_price(ticker):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=90d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        result = d['chart']['result'][0]
        closes = [c for c in result['indicators']['quote'][0]['close'] if c]
        timestamps = result['timestamp']
        meta = result['meta']
        return {
            'current': meta.get('regularMarketPrice'),
            'closes': closes,
            'start_price': closes[0] if closes else None
        }
    except:
        return None

def get_paper_stats():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    closed = db.execute("""
        SELECT pnl_eur, close_date FROM paper_portfolio
        WHERE status='CLOSED' AND pnl_eur IS NOT NULL AND pnl_eur != 0
        ORDER BY close_date
    """).fetchall()
    total_pnl = sum(r['pnl_eur'] for r in closed)
    trades = len(closed)
    wins = sum(1 for r in closed if r['pnl_eur'] > 0)
    db.close()
    return total_pnl, trades, wins

def run():
    spy = yahoo_price('SPY')
    tlt = yahoo_price('TLT')
    eurusd_data = yahoo_price('EURUSD=X')
    eurusd = eurusd_data['current'] if eurusd_data else 1.15

    paper_pnl, paper_trades, paper_wins = get_paper_stats()
    paper_return_pct = paper_pnl / CAPITAL * 100

    result = {
        'date': date.today().isoformat(),
        'paper_fund': {
            'pnl_eur': round(paper_pnl, 2),
            'return_pct': round(paper_return_pct, 2),
            'trades': paper_trades,
            'win_rate': round(paper_wins / paper_trades * 100, 1) if paper_trades > 0 else 0,
        },
        'benchmarks': {}
    }

    if spy and spy['start_price']:
        spy_return = (spy['current'] - spy['start_price']) / spy['start_price'] * 100
        spy_eur_pnl = CAPITAL * spy_return / 100
        result['benchmarks']['SPY_buyhold'] = {
            'return_pct': round(spy_return, 2),
            'pnl_eur': round(spy_eur_pnl / eurusd, 2),
            'vs_paper': round(paper_return_pct - spy_return, 2)
        }

    if spy and tlt and spy['start_price'] and tlt['start_price']:
        spy_r = (spy['current'] - spy['start_price']) / spy['start_price'] * 100
        tlt_r = (tlt['current'] - tlt['start_price']) / tlt['start_price'] * 100
        mix_r = spy_r * 0.6 + tlt_r * 0.4
        result['benchmarks']['60_40'] = {
            'return_pct': round(mix_r, 2),
            'vs_paper': round(paper_return_pct - mix_r, 2)
        }

    with open(BENCH_JSON, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"📊 Benchmark Report {result['date']}")
    print(f"  Albert's Fund:  {paper_return_pct:+.2f}% ({paper_pnl:+.0f}€) | {paper_trades} Trades | {result['paper_fund']['win_rate']:.0f}% WR")
    for name, b in result['benchmarks'].items():
        diff = b['vs_paper']
        icon = '🟢' if diff > 0 else '🔴'
        print(f"  {icon} vs {name:15} {b['return_pct']:+.2f}% | Albert {'besser' if diff > 0 else 'schlechter'} um {abs(diff):.2f}%")

    return result

if __name__ == '__main__':
    run()
