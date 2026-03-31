#!/usr/bin/env python3
"""
Sektor-Momentum-Ranking
Rankt alle Sektor-ETFs nach Performance + Volumen-Trend.
Gibt die Top-N Sektoren aus die als nächstes gescreent werden sollen.

Usage: python3 sector_momentum.py [--top 3]
"""

import urllib.request, json, sys, sqlite3, time
from datetime import datetime

DB_PATH = '/data/.openclaw/workspace/data/trading.db'

SECTOR_ETFS = {
    'XLE': 'Energy',
    'XLF': 'Financials', 
    'XLK': 'Technology',
    'XLV': 'Healthcare',
    'XLI': 'Industrials',
    'XLB': 'Materials',
    'XLU': 'Utilities',
    'XLP': 'Consumer Staples',
    'XLY': 'Consumer Discretionary',
    'XLC': 'Communication',
    'XLRE': 'Real Estate',
    'GDX': 'Gold Miners',
    'SIL': 'Silver Miners',
    'URA': 'Uranium',
    'OIH': 'Oil Services',
    'ITA': 'Defense/Aerospace',
    'HACK': 'Cybersecurity',
    'LIT': 'Lithium/Battery',
    'COPX': 'Copper Miners',
    'MOO': 'Agribusiness',
}

def yahoo_perf(ticker):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = json.loads(urllib.request.urlopen(req, timeout=8).read())
    result = data['chart']['result'][0]
    meta = result['meta']
    closes = [c for c in result['indicators']['quote'][0]['close'] if c]
    volumes = [v for v in result['indicators']['quote'][0]['volume'] if v]
    
    price = meta['regularMarketPrice']
    perf_1w = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    perf_1m = (closes[-1] - closes[-22]) / closes[-22] * 100 if len(closes) >= 22 else 0
    perf_3m = (closes[-1] - closes[0]) / closes[0] * 100
    
    # Volumen-Trend: letzte 10d vs vorherige 10d
    if len(volumes) >= 20:
        recent = sum(volumes[-10:]) / 10
        prev = sum(volumes[-20:-10]) / 10
        vol_trend = (recent - prev) / prev * 100
    else:
        vol_trend = 0
    
    return price, perf_1w, perf_1m, perf_3m, vol_trend

def rank_sectors(top_n=5):
    today = datetime.now().strftime('%Y-%m-%d')
    db = sqlite3.connect(DB_PATH)
    
    results = []
    
    print(f"📊 SEKTOR-MOMENTUM-RANKING — {today}")
    print(f"{'='*90}")
    print(f"  {'ETF':<6} {'Sektor':<22} {'Kurs':>8} {'1W':>7} {'1M':>7} {'3M':>7} {'Vol.Trend':>10}")
    print(f"  {'-'*85}")
    
    for etf, sector in SECTOR_ETFS.items():
        try:
            price, p1w, p1m, p3m, vol = yahoo_perf(etf)
            
            # Composite Score: 40% 1W + 30% 1M + 20% 3M + 10% Vol-Trend
            score = p1w * 0.4 + p1m * 0.3 + p3m * 0.2 + min(vol, 50) * 0.1
            
            results.append((etf, sector, price, p1w, p1m, p3m, vol, score))
            
            # In DB speichern
            db.execute('''INSERT OR REPLACE INTO sector_momentum 
                (date, etf, sector, price, perf_1w, perf_1m, perf_3m, volume_trend, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)''',
                (today, etf, sector, price, p1w, p1m, p3m, vol))
            
            time.sleep(0.3)
        except Exception as e:
            print(f"  {etf:<6} {sector:<22} ERROR: {e}")
    
    # Sortiere nach Score
    results.sort(key=lambda x: -x[7])
    
    # Ränge vergeben und ausgeben
    for rank, (etf, sector, price, p1w, p1m, p3m, vol, score) in enumerate(results, 1):
        marker = "🔥" if rank <= top_n else "  "
        print(f"  {marker}{etf:<6} {sector:<22} ${price:>7.2f} {p1w:>+6.1f}% {p1m:>+6.1f}% {p3m:>+6.1f}% {vol:>+8.1f}%  Score: {score:+.1f}")
        
        db.execute('UPDATE sector_momentum SET rank=? WHERE date=? AND etf=?', (rank, today, etf))
    
    db.commit()
    db.close()
    
    print(f"\n{'='*90}")
    print(f"  🔥 TOP {top_n} SEKTOREN zum Screenen:")
    for rank, (etf, sector, price, p1w, p1m, p3m, vol, score) in enumerate(results[:top_n], 1):
        print(f"    {rank}. {sector} ({etf}) — 1W: {p1w:+.1f}%, 1M: {p1m:+.1f}%, Score: {score:+.1f}")
    
    return results[:top_n]

if __name__ == '__main__':
    top_n = 5
    for i, arg in enumerate(sys.argv):
        if arg == '--top' and i + 1 < len(sys.argv):
            top_n = int(sys.argv[i + 1])
    
    rank_sectors(top_n)
