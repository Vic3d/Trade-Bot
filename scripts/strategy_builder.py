#!/usr/bin/env python3
"""
Strategy Builder — Autonome Strategie-Entwicklung durch Albert
=============================================================
Analysiert Trade-History, News-Korrelationen und Marktregimes
→ entwickelt neue PS-Strategien aus Daten heraus (nicht aus Victor-Input)

Läuft 2x wöchentlich (Di + Fr 21:00).
Output: neue Strategien in data/strategies.json + Log in memory/strategy-research.md
"""

import sqlite3, json, urllib.request, re, sys
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')
from collections import defaultdict

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'
STRAT_JSON = WS / 'data/strategies.json'
RESEARCH_LOG = WS / 'memory/strategy-research.md'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_json import atomic_write_json

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def yahoo(ticker):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        result = d['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        timestamps = result['timestamp']
        meta = result['meta']
        return {
            'price': meta.get('regularMarketPrice'),
            'prev': meta.get('chartPreviousClose'),
            'closes': [c for c in closes if c],
            'change_1d': (meta.get('regularMarketPrice',0) - meta.get('chartPreviousClose',1)) / meta.get('chartPreviousClose',1) * 100
        }
    except:
        return None

def analyze_winning_patterns():
    """Analysiert welche Setups in der trades-Tabelle gewonnen haben."""
    conn = get_db()
    
    # Welche Strategien performen am besten?
    strat_perf = conn.execute("""
        SELECT strategy, 
               COUNT(*) as trades,
               SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) as losses,
               AVG(CASE WHEN pnl_eur IS NOT NULL THEN pnl_eur ELSE 0 END) as avg_pnl
        FROM trades
        WHERE status IN ('WIN','LOSS') AND entry_date > date('now', '-30 days')
        GROUP BY strategy
        HAVING trades >= 3
        ORDER BY avg_pnl DESC
    """).fetchall() if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'").fetchone() else []
    
    # Welche Ticker liefen gut?
    ticker_perf = conn.execute("""
        SELECT ticker,
               COUNT(*) as trades,
               SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
               AVG(CASE WHEN pnl_eur IS NOT NULL THEN pnl_eur ELSE 0 END) as avg_pnl
        FROM trades
        WHERE status IN ('WIN','LOSS') AND entry_date > date('now', '-14 days')
        GROUP BY ticker
        HAVING trades >= 3
        ORDER BY wins DESC
        LIMIT 10
    """).fetchall() if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'").fetchone() else []
    
    conn.close()
    return [dict(r) for r in strat_perf], [dict(r) for r in ticker_perf]

def scan_market_opportunities():
    """Scannt Markt auf neue Themen die noch nicht als Strategie existieren."""
    
    # Kandidaten: Sektoren die aktuell relevant sind aber noch keine PS haben
    candidates = {
        'Defense-EU-Small': {
            'tickers': ['SAAB-B.ST', 'RHM.DE', 'BA.L', 'AIR.PA'],
            'thesis': 'EU-Rüstung Nachholbedarf — Budget-Erhöhungen noch nicht eingepreist',
            'regime': 'Geopolitik-Eskalation, NATO-Ausgaben steigen',
            'trigger': 'Neuer NATO-Beschluss ODER EU-Haushaltserhöhung'
        },
        'AI-Infrastructure': {
            'tickers': ['SMCI', 'ANET', 'DELL', 'VRT'],
            'thesis': 'KI-Infrastruktur = picks & shovels für AI-Boom, weniger regulatorisches Risiko als pure-play AI',
            'regime': 'Risk-On, VIX <25, AI-Capex-Zyklus intact',
            'trigger': 'Hyper-Scaler Earnings bestätigen Capex-Erhöhung'
        },
        'Copper-Green-Transition': {
            'tickers': ['FCX', 'SCCO', 'TECK', 'GLEN.L'],
            'thesis': 'Kupfer = kritischer Rohstoff für EV + Grid + Offshore Wind, strukturell unterversorgt',
            'regime': 'China-Stimulus aktiv, US-Infrastruktur-Spend hoch',
            'trigger': 'Kupfer-Futures >$4.50/lb + China PMI >50'
        },
        'Shipping-Normalization': {
            'tickers': ['ZIM', 'MATX', 'SBLK'],
            'thesis': 'Container-Shipping normalisiert sich post-Suez-Krise, Raten stabilisieren',
            'regime': 'Rotes Meer entspannt ODER alternative Route etabliert',
            'trigger': 'Baltic Dry Index steigt >2000 konsistent'
        },
        'Biotech-Rate-Reversal': {
            'tickers': ['XBI', 'ARKG', 'IBB'],
            'thesis': 'Biotech-Sektor profitiert überproportional von Zinssenkungen (lange Laufzeit der Cash Flows)',
            'regime': 'Fed beginnt Zinssenkungszyklus, VIX <20',
            'trigger': 'Fed-Pivot + XBI über 200-Tage-MA'
        }
    }
    
    return candidates

def get_next_ps_id():
    """Findet nächste freie PS-Nummer."""
    strats = json.load(open(STRAT_JSON)) if STRAT_JSON.exists() else {}
    existing = [int(k[2:]) for k in strats if k.startswith('PS') and k[2:].isdigit()]
    return f'PS{max(existing, default=0) + 1}'

def propose_new_strategy(name, data):
    """Erstellt neuen PS-Eintrag."""
    ps_id = get_next_ps_id()
    
    strats = json.load(open(STRAT_JSON)) if STRAT_JSON.exists() else {}
    
    # Wähle besten Ticker aus Kandidaten-Liste
    tickers = data['tickers']
    
    strats[ps_id] = {
        'name': name,
        'thesis': data['thesis'],
        'regime': data['regime'],
        'trigger': data['trigger'],
        'tickers': tickers[:3],  # Top 3
        'health': 'testing',     # Neu: testing-Phase, nicht green/red
        'locked': False,
        'source': 'albert_autonomous',  # Markiert als Albert-generiert (nicht Victor)
        'created': date.today().isoformat(),
        'trades': 0,
        'wins': 0,
        'losses': 0,
        'pnl': 0.0
    }
    
    atomic_write_json(STRAT_JSON, strats, ensure_ascii=True)
    
    return ps_id

def get_existing_strategy_names():
    """Verhindert Duplikate."""
    strats = json.load(open(STRAT_JSON)) if STRAT_JSON.exists() else {}
    return [v.get('name','').lower() for v in strats.values()]

def log_research(entries):
    """Schreibt Research-Log."""
    if not RESEARCH_LOG.exists():
        RESEARCH_LOG.write_text('# Strategy Research Log — Albert\n\n', encoding="utf-8")
    
    ts = datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M')
    with open(RESEARCH_LOG, 'a') as f:
        f.write(f'\n## [{ts}] Autonomer Strategie-Scan\n\n')
        for e in entries:
            f.write(f'- {e}\n')
        f.write('\n---\n')

def run():
    print(f"[Strategy Builder {datetime.now(_BERLIN).strftime('%H:%M')}] Start...")
    
    # 1. Bestehende Performance analysieren
    strat_perf, ticker_perf = analyze_winning_patterns()
    print(f"  Analyse: {len(strat_perf)} Strategien, {len(ticker_perf)} Top-Ticker")
    
    if strat_perf:
        print("  Top-Strategien (letzte 30 Tage):")
        for s in strat_perf[:3]:
            wr = s['wins']/(s['wins']+s['losses'])*100 if (s['wins']+s['losses']) > 0 else 0
            print(f"    {s['strategy']}: {s['trades']} Trades, {wr:.0f}% WR, Ø{s['avg_pnl']:.1f}€")
    
    # 2. Neue Kandidaten scannen
    candidates = scan_market_opportunities()
    existing_names = get_existing_strategy_names()
    
    new_count = 0
    log_entries = []
    
    for name, data in candidates.items():
        name_lower = name.lower()
        # Nur neue Strategien hinzufügen (keine Duplikate)
        if not any(name_lower in n for n in existing_names):
            ps_id = propose_new_strategy(name, data)
            new_count += 1
            log_entries.append(f"NEU {ps_id}: {name} — {data['thesis'][:60]}...")
            print(f"  ✅ {ps_id} erstellt: {name}")
        else:
            log_entries.append(f"SKIP: {name} (bereits vorhanden)")
            print(f"  ⏭  {name}: bereits vorhanden")
    
    # 3. Top-Ticker aus Data in Research-Log
    if ticker_perf:
        log_entries.append(f"Top-Ticker (letzte 14 Tage):")
        for t in ticker_perf[:5]:
            wr = t['wins']/t['trades']*100 if t['trades'] > 0 else 0
            log_entries.append(f"  {t['ticker']}: {t['trades']} Trades, {wr:.0f}% WR, Ø{t['avg_pnl']:.1f}€")
    
    log_research(log_entries)
    
    print(f"  Fertig: {new_count} neue Strategien vorgeschlagen")
    if new_count > 0:
        print(f"NEUE_STRATEGIEN: {new_count}")
    else:
        print("KEIN_SIGNAL")

if __name__ == '__main__':
    run()
