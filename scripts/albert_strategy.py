#!/usr/bin/env python3
"""
Strategie ALBERT — "Geopolitischer Kontra-Sniper"
Paper Trading Implementation

Usage:
  python3 albert_strategy.py scan          # Scan for setups (dry run)
  python3 albert_strategy.py trade         # Execute trades if setups found
  python3 albert_strategy.py monitor       # Check open SA positions
  python3 albert_strategy.py close TICKER  # Close position (thesis dead)
  python3 albert_strategy.py report        # Weekly performance report
"""

import sqlite3, json, os, sys, time, re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ═══ CONFIG ═══
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trading.db')
SCANNER_STATE = os.path.join(os.path.dirname(__file__), '..', 'memory', 'scanner-state.json')
SCANNER_DASHBOARD = os.path.join(os.path.dirname(__file__), '..', 'memory', 'scanner-dashboard-data.json')
REGIME_FILE = os.path.join(os.path.dirname(__file__), '..', 'memory', 'market-regime.json')
STRATEGY_FILE = os.path.join(os.path.dirname(__file__), '..', 'memory', 'strategie-albert.md')
LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'memory', 'albert-trades.md')

# Portfolio rules
PORTFOLIO_SIZE = 100000  # Virtual portfolio
MAX_RISK_PCT = {
    'low': 0.02,      # VIX <18
    'normal': 0.02,    # VIX 18-22
    'elevated': 0.015, # VIX 22-27
    'high': 0.01,      # VIX 27-35
    'extreme': 0.005   # VIX >35
}
MAX_POSITIONS = {
    'low': 5,
    'normal': 4,
    'elevated': 3,
    'high': 2,
    'extreme': 1
}
MIN_CRV = {
    'low': 3.0,
    'normal': 3.0,
    'elevated': 3.0,
    'high': 4.0,
    'extreme': 5.0
}
MAX_SECTOR_RISK_PCT = 0.04  # 4% max risk per sector
MAX_SAME_THEME = 2          # Max 2 positions in same geopolitical theme
MIN_CASH_PCT = 0.40         # Always keep 40% in cash

# Geopolitical themes and their tickers
THEMES = {
    'iran_hormuz': {
        'name': '🇮🇷 Iran/Hormuz',
        'tickers': {
            'OXY': {'name': 'Occidental Petroleum', 'sector': 'energy', 'currency': 'USD'},
            'EQNR.OL': {'name': 'Equinor ASA', 'sector': 'energy', 'currency': 'NOK'},
            'FRO': {'name': 'Frontline PLC', 'sector': 'tanker', 'currency': 'USD'},
            'DHT': {'name': 'DHT Holdings', 'sector': 'tanker', 'currency': 'USD'},
            'TTE.PA': {'name': 'TotalEnergies', 'sector': 'energy', 'currency': 'EUR'},
            'SHEL.L': {'name': 'Shell PLC', 'sector': 'energy', 'currency': 'GBP'},
        },
        'scanner_keywords': ['iran', 'hormuz', 'strait', 'persian gulf', 'kharg'],
        'min_score': 50,
    },
    'cuba_crisis': {
        'name': '🇨🇺 Kuba-Blockade',
        'tickers': {
            'S.TO': {'name': 'Sherritt International', 'sector': 'mining', 'currency': 'CAD'},
            'MP': {'name': 'MP Materials', 'sector': 'mining', 'currency': 'USD'},
            'CCL': {'name': 'Carnival Corp', 'sector': 'cruise', 'currency': 'USD'},
        },
        'scanner_keywords': ['cuba', 'kuba', 'havana', 'matanzas', 'coast guard'],
        'min_score': 40,
    },
    'silver_correction': {
        'name': '🥈 Silber-Korrektur',
        'tickers': {
            'AG': {'name': 'First Majestic Silver', 'sector': 'silver', 'currency': 'USD'},
            'PAAS': {'name': 'Pan American Silver', 'sector': 'silver', 'currency': 'USD'},
            'WPM': {'name': 'Wheaton Precious Metals', 'sector': 'silver', 'currency': 'USD'},
            'HL': {'name': 'Hecla Mining', 'sector': 'silver', 'currency': 'USD'},
            'EXK': {'name': 'Endeavour Silver', 'sector': 'silver', 'currency': 'USD'},
        },
        'scanner_keywords': ['silver', 'silber', 'precious metal'],
        'min_score': 20,
    },
    'china_tech': {
        'name': '🇨🇳 China Tech/Trade War',
        'tickers': {
            '9988.HK': {'name': 'Alibaba', 'sector': 'tech', 'currency': 'HKD'},
            '0700.HK': {'name': 'Tencent', 'sector': 'tech', 'currency': 'HKD'},
            'BABA': {'name': 'Alibaba (US)', 'sector': 'tech', 'currency': 'USD'},
            'KWEB': {'name': 'China Internet ETF', 'sector': 'tech', 'currency': 'USD'},
        },
        'scanner_keywords': ['china', 'trade war', 'tariff', 'taiwan'],
        'min_score': 40,
    }
}

# Setup types
SETUP_A = 'SHOCK'        # Geopolitischer Schock (reaktiv)
SETUP_B = 'CREEPING'     # Schleichende These (proaktiv)
SETUP_C = 'VIX_CONTRA'   # VIX-Kontra (contrarian)
SETUP_D = 'FLAG_BOTTOM'  # Fahnenstangen-Boden (Eriksen)


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    # Ensure SA columns exist
    try:
        db.execute("ALTER TABLE trades ADD COLUMN setup_type TEXT")
    except: pass
    try:
        db.execute("ALTER TABLE trades ADD COLUMN scanner_score REAL")
    except: pass
    try:
        db.execute("ALTER TABLE trades ADD COLUMN second_order_effect TEXT")
    except: pass
    try:
        db.execute("ALTER TABLE trades ADD COLUMN thesis_alive INTEGER DEFAULT 1")
    except: pass
    try:
        db.execute("ALTER TABLE trades ADD COLUMN thesis_killed_by TEXT")
    except: pass
    try:
        db.execute("ALTER TABLE trades ADD COLUMN geo_theme TEXT")
    except: pass
    db.commit()
    return db


def get_vix():
    """Get current VIX from Yahoo Finance."""
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(urlopen(req, timeout=10).read())
        close = data['chart']['result'][0]['meta']['regularMarketPrice']
        return float(close)
    except Exception as e:
        print(f"  ⚠️ VIX fetch failed: {e}")
        return 27.56  # Fallback to last known


def get_vix_zone(vix):
    if vix < 18: return 'low'
    if vix < 22: return 'normal'
    if vix < 27: return 'elevated'
    if vix < 35: return 'high'
    return 'extreme'


def get_price_yahoo(ticker):
    """Fetch current price from Yahoo Finance."""
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(urlopen(req, timeout=10).read())
        meta = data['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice', 0)
        currency = meta.get('currency', 'USD')
        return float(price), currency
    except Exception as e:
        print(f"  ⚠️ Price fetch failed for {ticker}: {e}")
        return None, None


def get_atr(ticker, period=14):
    """Fetch ATR(14) approximation from Yahoo Finance daily data."""
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(urlopen(req, timeout=10).read())
        result = data['chart']['result'][0]
        highs = result['indicators']['quote'][0]['high']
        lows = result['indicators']['quote'][0]['low']
        closes = result['indicators']['quote'][0]['close']
        
        trs = []
        for i in range(1, len(highs)):
            if highs[i] and lows[i] and closes[i-1]:
                tr = max(highs[i] - lows[i], 
                         abs(highs[i] - closes[i-1]),
                         abs(lows[i] - closes[i-1]))
                trs.append(tr)
        
        if len(trs) >= period:
            atr = sum(trs[-period:]) / period
            return round(atr, 4)
        elif trs:
            return round(sum(trs) / len(trs), 4)
        return None
    except Exception as e:
        print(f"  ⚠️ ATR fetch failed for {ticker}: {e}")
        return None


def to_eur(price, currency):
    """Convert to EUR using Yahoo Finance FX rates."""
    if currency == 'EUR':
        return price
    try:
        pair = f'{currency}EUR=X'
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{pair}?interval=1d&range=1d'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(urlopen(req, timeout=10).read())
        rate = data['chart']['result'][0]['meta']['regularMarketPrice']
        return round(price * rate, 2)
    except:
        # Fallback rates
        fallback = {'USD': 0.87, 'GBP': 1.16, 'NOK': 0.084, 'CAD': 0.64, 'HKD': 0.112}
        return round(price * fallback.get(currency, 1.0), 2)


def get_scanner_data():
    """Load latest scanner results."""
    try:
        with open(SCANNER_DASHBOARD) as f:
            data = json.load(f)
        if data.get('runs'):
            latest = data['runs'][-1]
            return {
                'score': latest.get('total_score', latest.get('score', 0)),
                'regions': latest.get('top_items', latest.get('top_regions', [])),
                'timestamp': latest.get('ts', latest.get('timestamp', '')),
                'tickers': latest.get('affected_tickers', []),
                'strategies': latest.get('affected_strategies', []),
            }
    except: pass
    return {'score': 0, 'regions': [], 'timestamp': ''}


def get_regime():
    """Load current market regime."""
    try:
        with open(REGIME_FILE) as f:
            return json.load(f)
    except:
        return {'regime': 'UNKNOWN'}


def is_growth_long_allowed(regime: dict, ticker: str) -> tuple[bool, str]:
    """
    S&P MA200 Gate — Strategien.md Pflichtprüfung (28.03.2026).
    Kein neuer Growth-Long solange S&P unter MA200 + VIX > 25.

    Returns (allowed: bool, reason: str)
    """
    GROWTH_TICKERS = {'NVDA', 'PLTR', 'MSFT', 'QQQ', 'AAPL', 'GOOGL', 'META', 'AMZN', 'AMD'}
    t_upper = ticker.upper().replace('.O', '').replace('.US', '')

    if t_upper not in GROWTH_TICKERS:
        return True, "non-growth ticker"

    regime_name = regime.get('regime', 'UNKNOWN')
    sp500_vs_ma200 = regime.get('factors', {}).get('sp500_vs_ma200')
    vix = regime.get('factors', {}).get('vix', 25)

    # Hard block: S&P unter MA200
    if sp500_vs_ma200 is not None and sp500_vs_ma200 < 0:
        return False, f"S&P unter MA200 ({sp500_vs_ma200:+.1f}%) — Kabelkahr-Regel aktiv. Erst Drei-Schritt-Bestätigung abwarten."

    # Hard block: CRASH oder TREND_DOWN Regime
    if regime_name in ('CRASH', 'TREND_DOWN'):
        return False, f"Regime {regime_name} — Growth-Longs verboten laut Strategien.md."

    # Asset-spezifische VIX-Sensitivität (ersetzt harten Binary-Switch)
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from vix_context import calculate_position_multiplier, get_vix_percentile
        vix_ctx = get_vix_percentile()
        percentile = vix_ctx.get('vix_percentile', 50)
        mult = calculate_position_multiplier(ticker, vix, percentile)
        if mult == 0.0:
            return False, f"VIX {vix:.1f} (P{percentile:.0f}%) — {ticker} stark VIX-sensitiv, Block aktiv."
        # Multiplikator wird an calculate_position weitergegeben (via vix_zone Anpassung)
    except Exception as e:
        # Fallback auf altes Verhalten wenn Modul fehlt
        if vix and vix > 35:
            return False, f"VIX {vix:.1f} > 35 — kein neuer Trade (Fallback)."

    return True, "ok"


def calculate_position(portfolio_value, vix_zone, price_eur, atr_eur):
    """Calculate position size based on ATR and VIX zone."""
    risk_pct = MAX_RISK_PCT[vix_zone]
    risk_budget = portfolio_value * risk_pct
    
    stop_distance = atr_eur * 2  # 2x ATR stop
    if stop_distance <= 0:
        return None
    
    shares = int(risk_budget / stop_distance)
    position_eur = shares * price_eur
    
    # Check max cash usage (keep 40% in reserve)
    max_position = portfolio_value * (1 - MIN_CASH_PCT)
    if position_eur > max_position:
        shares = int(max_position / price_eur)
        position_eur = shares * price_eur
    
    return {
        'shares': shares,
        'position_eur': round(position_eur, 2),
        'risk_budget': round(risk_budget, 2),
        'stop_distance': round(stop_distance, 2),
        'stop_price_eur': round(price_eur - stop_distance, 2),
        'risk_pct': risk_pct,
    }


# ═══ COMMANDS ═══

def cmd_scan():
    """Scan for SA setups — dry run, shows opportunities."""
    print("=" * 60)
    print("🎩 ALBERT STRATEGY — SCAN")
    print("=" * 60)
    
    vix = get_vix()
    zone = get_vix_zone(vix)
    scanner = get_scanner_data()
    regime = get_regime()
    
    print(f"\n📊 MARKTLAGE:")
    print(f"  VIX: {vix:.2f} → Zone: {zone.upper()}")
    print(f"  Max Positionen: {MAX_POSITIONS[zone]}")
    print(f"  Risiko/Trade: {MAX_RISK_PCT[zone]*100:.1f}%")
    print(f"  Min CRV: {MIN_CRV[zone]}:1")
    print(f"  Regime: {regime.get('regime', '?')}")
    print(f"  Scanner Score: {scanner['score']}")
    
    db = get_db()
    open_sa = db.execute(
        "SELECT ticker, strategy FROM trades WHERE status='OPEN' AND strategy='SA'"
    ).fetchall()
    print(f"\n📍 OFFENE SA-POSITIONEN: {len(open_sa)}/{MAX_POSITIONS[zone]}")
    for p in open_sa:
        print(f"  • {p['ticker']}")
    
    if len(open_sa) >= MAX_POSITIONS[zone]:
        print(f"\n⛔ MAX POSITIONEN ERREICHT ({len(open_sa)}/{MAX_POSITIONS[zone]}). Keine neuen Trades.")
        return
    
    print(f"\n🔍 SCANNING {sum(len(t['tickers']) for t in THEMES.values())} Ticker in {len(THEMES)} Themen...\n")
    
    setups = []
    
    for theme_id, theme in THEMES.items():
        # Check if theme has scanner activity
        theme_score = 0
        for region in scanner.get('regions', []):
            if isinstance(region, dict):
                name = (region.get('name', '') or region.get('region', '')).lower()
                score_val = region.get('score', 0)
                if isinstance(score_val, str):
                    try: score_val = int(score_val)
                    except: score_val = 0
                if any(kw in name for kw in theme['scanner_keywords']):
                    theme_score = max(theme_score, score_val)
        
        if theme_score < theme['min_score'] and theme_id != 'silver_correction':
            print(f"  ⏭️ {theme['name']}: Score {theme_score} < {theme['min_score']} → Skip")
            continue
        
        # Check max same-theme positions
        same_theme = [p for p in open_sa if any(
            p['ticker'] == t for t in theme['tickers']
        )]
        if len(same_theme) >= MAX_SAME_THEME:
            print(f"  ⏭️ {theme['name']}: Already {len(same_theme)} positions in this theme → Skip")
            continue
        
        print(f"  🔎 {theme['name']} (Score: {theme_score}):")
        
        for ticker, info in theme['tickers'].items():
            # Skip if already in position
            if any(p['ticker'] == ticker for p in open_sa):
                print(f"    ⏭️ {ticker}: Already in position")
                continue
            
            price, currency = get_price_yahoo(ticker)
            if not price:
                continue
            
            price_eur = to_eur(price, currency)
            atr = get_atr(ticker)
            if not atr:
                print(f"    ⚠️ {ticker}: No ATR data")
                continue
            
            atr_eur = to_eur(atr, currency)
            pos = calculate_position(PORTFOLIO_SIZE, zone, price_eur, atr_eur)
            if not pos:
                continue
            
            # Calculate potential CRV (3x risk as conservative target)
            potential_target = price_eur + (pos['stop_distance'] * MIN_CRV[zone])
            crv = MIN_CRV[zone]
            
            setup = {
                'ticker': ticker,
                'name': info['name'],
                'theme': theme_id,
                'theme_name': theme['name'],
                'sector': info['sector'],
                'price': price,
                'currency': currency,
                'price_eur': price_eur,
                'atr': atr,
                'atr_eur': atr_eur,
                'position': pos,
                'crv': crv,
                'target_eur': round(potential_target, 2),
                'scanner_score': theme_score,
            }
            setups.append(setup)
            
            print(f"    ✅ {ticker} ({info['name']})")
            print(f"       Kurs: {price:.2f} {currency} ({price_eur:.2f}€)")
            print(f"       ATR(14): {atr:.2f} {currency} ({atr_eur:.2f}€)")
            print(f"       Stop: {pos['stop_price_eur']:.2f}€ (ATR×2 = {pos['stop_distance']:.2f}€)")
            print(f"       Shares: {pos['shares']} | Position: {pos['position_eur']:.0f}€")
            print(f"       Risiko: {pos['risk_budget']:.0f}€ ({pos['risk_pct']*100:.1f}%)")
            print(f"       CRV: {crv}:1 | Target: {setup['target_eur']:.2f}€")
            print()
            
            time.sleep(0.5)  # Rate limit
    
    if setups:
        print(f"\n{'='*60}")
        print(f"📋 GEFUNDENE SETUPS: {len(setups)}")
        print(f"{'='*60}")
        for i, s in enumerate(setups, 1):
            print(f"  {i}. {s['ticker']} ({s['name']}) — {s['theme_name']}")
            print(f"     {s['price_eur']:.2f}€ | Stop {s['position']['stop_price_eur']:.2f}€ | CRV {s['crv']}:1")
    else:
        print(f"\n💤 Keine Setups gefunden. Cash halten. Geduld.")
    
    return setups


def cmd_trade(ticker=None, thesis=None, setup_type=SETUP_B, second_order=None, theme=None):
    """Open a new SA position."""
    if not ticker:
        print("Usage: albert_strategy.py trade TICKER 'These in einem Satz' [setup_type] [second_order_effect] [theme]")
        return
    
    if not thesis:
        print("❌ REGEL 1: Kein Trade ohne These! Bitte These angeben.")
        return
    
    db = get_db()
    vix = get_vix()
    zone = get_vix_zone(vix)
    
    # Check position limits
    open_sa = db.execute(
        "SELECT COUNT(*) as c FROM trades WHERE status='OPEN' AND strategy='SA'"
    ).fetchone()['c']
    
    if open_sa >= MAX_POSITIONS[zone]:
        print(f"❌ Max Positionen erreicht ({open_sa}/{MAX_POSITIONS[zone]} bei VIX {vix:.1f})")
        return
    
    # Check if already in this ticker
    existing = db.execute(
        "SELECT id FROM trades WHERE ticker=? AND strategy='SA' AND status='OPEN'", (ticker,)
    ).fetchone()
    if existing:
        print(f"❌ Bereits in Position: {ticker}")
        return

    # ── STRATEGIEN.MD GATE: S&P MA200 + Regime-Check ──────────────────
    regime = get_regime()
    allowed, gate_reason = is_growth_long_allowed(regime, ticker)
    if not allowed:
        print(f"🚫 STRATEGIEN.MD BLOCK — {ticker}: {gate_reason}")
        print(f"   → Drei-Schritt-Bestätigung abwarten (Ausbruch >6.670 → Pullback → neues Hoch)")
        return
    # ──────────────────────────────────────────────────────────────────

    # Fetch price + ATR
    price, currency = get_price_yahoo(ticker)
    if not price:
        print(f"❌ Konnte Preis für {ticker} nicht abrufen")
        return
    
    price_eur = to_eur(price, currency)
    
    # Realistic execution: add spread + slippage + commission
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from trademind.execution.simulator import simulate_fill
        fill = simulate_fill(price_eur, 'BUY', ticker, vix)
        fill_price = fill['fill_price']
        fill_cost = fill['total_cost']
        print(f"   Fill: {fill_price:.2f}€ (inkl. {fill['spread_cost']:.2f}€ Spread + {fill['slippage_cost']:.2f}€ Slippage + {fill['commission']:.0f}€ Gebühr)")
    except Exception as e:
        fill_price = price_eur
        fill_cost = 0
    price_eur = fill_price
    
    atr = get_atr(ticker)
    if not atr:
        print(f"❌ Konnte ATR für {ticker} nicht berechnen")
        return
    
    atr_eur = to_eur(atr, currency)
    pos = calculate_position(PORTFOLIO_SIZE, zone, price_eur, atr_eur)
    if not pos:
        print(f"❌ Position Sizing fehlgeschlagen")
        return
    
    # CRV check
    min_crv = MIN_CRV[zone]
    
    scanner = get_scanner_data()
    regime = get_regime()
    
    # Insert trade
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    target_eur = round(price_eur + pos['stop_distance'] * min_crv, 2)
    
    db.execute("""
        INSERT INTO trades (
            ticker, strategy, direction, entry_price, entry_date,
            stop, target, shares, status, thesis, trade_type,
            portfolio_type, position_size_eur, risk_eur,
            reward_eur, crv, vix_at_entry, regime_at_entry,
            style, setup_type, scanner_score, second_order_effect,
            thesis_alive, geo_theme, news_context
        ) VALUES (?, 'SA', 'LONG', ?, ?, ?, ?, ?, 'OPEN', ?, 'swing',
                  'paper', ?, ?, ?, ?, ?, ?, 'disciplined', ?, ?, ?, 1, ?, ?)
    """, (
        ticker, price_eur, now,
        pos['stop_price_eur'], target_eur, pos['shares'],
        thesis, pos['position_eur'], pos['risk_budget'],
        pos['risk_budget'] * min_crv, min_crv,
        vix, regime.get('regime', 'UNKNOWN'),
        setup_type, scanner.get('score', 0),
        second_order or '', theme or '',
        f"VIX:{vix:.1f} | Zone:{zone} | Scanner:{scanner.get('score',0)}"
    ))
    db.commit()
    
    # Log to file
    log_entry = f"""
## {now} — SA TRADE OPENED: {ticker}
- **Kurs:** {price:.2f} {currency} ({price_eur:.2f}€)
- **Stop:** {pos['stop_price_eur']:.2f}€ (ATR×2)
- **Target:** {target_eur:.2f}€ (CRV {min_crv}:1)
- **Shares:** {pos['shares']} | Position: {pos['position_eur']:.0f}€
- **Risiko:** {pos['risk_budget']:.0f}€ ({pos['risk_pct']*100:.1f}%)
- **VIX:** {vix:.2f} ({zone})
- **Setup:** {setup_type}
- **Theme:** {theme or 'N/A'}
- **These:** {thesis}
- **Zweitrundeneffekt:** {second_order or 'N/A'}
"""
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry)
    
    print(f"\n✅ SA TRADE OPENED: {ticker}")
    print(f"   Kurs: {price:.2f} {currency} ({price_eur:.2f}€)")
    print(f"   Stop: {pos['stop_price_eur']:.2f}€ | Target: {target_eur:.2f}€")
    print(f"   Shares: {pos['shares']} | Position: {pos['position_eur']:.0f}€")
    print(f"   Risiko: {pos['risk_budget']:.0f}€ | CRV: {min_crv}:1")
    print(f"   Setup: {setup_type} | Theme: {theme}")
    print(f"   These: {thesis}")


def cmd_monitor():
    """Monitor all open SA positions — check stops, trailing, thesis."""
    print("=" * 60)
    print("🎩 ALBERT STRATEGY — MONITOR")
    print("=" * 60)
    
    db = get_db()
    vix = get_vix()
    zone = get_vix_zone(vix)
    
    positions = db.execute("""
        SELECT * FROM trades WHERE strategy='SA' AND status='OPEN'
        ORDER BY entry_date
    """).fetchall()
    
    if not positions:
        print("\n💤 Keine offenen SA-Positionen.")
        return
    
    print(f"\n📊 VIX: {vix:.2f} ({zone}) | Positionen: {len(positions)}/{MAX_POSITIONS[zone]}")
    
    total_pnl = 0
    alerts = []
    
    for p in positions:
        ticker = p['ticker']
        price, currency = get_price_yahoo(ticker)
        if not price:
            print(f"\n  ⚠️ {ticker}: Preis nicht verfügbar")
            continue
        
        price_eur = to_eur(price, currency)
        entry = p['entry_price']
        stop = p['stop']
        pnl_eur = (price_eur - entry) * p['shares']
        pnl_pct = ((price_eur - entry) / entry) * 100 if entry else 0
        risk = p['risk_eur'] or (entry - stop) * p['shares']
        
        # Trailing stop logic
        new_stop = stop
        trail_phase = '🔴 Initial'
        
        if risk > 0:
            gain_ratio = pnl_eur / risk
            
            if gain_ratio >= 5:
                # Runner phase: stop at 70% of profit
                new_stop = max(stop, entry + (price_eur - entry) * 0.70)
                trail_phase = '🚀 Runner'
            elif gain_ratio >= 3:
                # Trailing phase: stop at 50% of profit
                new_stop = max(stop, entry + (price_eur - entry) * 0.50)
                trail_phase = '🟢 Trailing'
            elif gain_ratio >= 1.5:
                # Breakeven phase
                new_stop = max(stop, entry)
                trail_phase = '🟡 Breakeven'
        
        # Update stop if trailing
        if new_stop > stop:
            db.execute("UPDATE trades SET stop=?, trail_count=COALESCE(trail_count,0)+1 WHERE id=?",
                       (round(new_stop, 2), p['id']))
            alerts.append(f"  📈 {ticker}: Stop nachgezogen {stop:.2f}€ → {new_stop:.2f}€ ({trail_phase})")
            stop = new_stop
        
        # Update current price
        db.execute("UPDATE trades SET pnl_eur=?, pnl_pct=? WHERE id=?",
                   (round(pnl_eur, 2), round(pnl_pct, 2), p['id']))
        
        # Check stop hit
        if price_eur <= stop:
            alerts.append(f"  🔴 {ticker}: STOP HIT @ {price_eur:.2f}€ (Stop: {stop:.2f}€)")
        
        # Distance to stop
        stop_dist_pct = ((price_eur - stop) / price_eur) * 100 if price_eur > 0 else 0
        
        total_pnl += pnl_eur
        
        print(f"\n  {'─'*50}")
        print(f"  {ticker} ({p['geo_theme'] or '?'})")
        print(f"  Kurs: {price_eur:.2f}€ | Entry: {entry:.2f}€ | P&L: {pnl_eur:+.0f}€ ({pnl_pct:+.1f}%)")
        print(f"  Stop: {stop:.2f}€ ({stop_dist_pct:.1f}% weg) | Phase: {trail_phase}")
        print(f"  Setup: {p['setup_type'] or '?'} | Scanner: {p['scanner_score'] or 0:.0f}")
        print(f"  These: {(p['thesis'] or '')[:80]}...")
        
        time.sleep(0.3)
    
    db.commit()
    
    print(f"\n{'='*60}")
    print(f"  GESAMT P&L: {total_pnl:+.0f}€")
    print(f"{'='*60}")
    
    if alerts:
        print(f"\n🚨 ALERTS:")
        for a in alerts:
            print(a)
    
    return alerts


def cmd_close(ticker, reason='manual', thesis_correct=None, lesson=None, 
              what_worked=None, what_failed=None, would_repeat=None):
    """Close a SA position with mandatory post-mortem."""
    db = get_db()
    
    pos = db.execute(
        "SELECT * FROM trades WHERE ticker=? AND strategy='SA' AND status='OPEN'", (ticker,)
    ).fetchone()
    
    if not pos:
        print(f"❌ Keine offene SA-Position für {ticker}")
        return
    
    price, currency = get_price_yahoo(ticker)
    if not price:
        print(f"❌ Preis für {ticker} nicht verfügbar")
        return
    
    price_eur = to_eur(price, currency)
    pnl_eur = (price_eur - pos['entry_price']) * pos['shares']
    pnl_pct = ((price_eur - pos['entry_price']) / pos['entry_price']) * 100
    
    status = 'WIN' if pnl_eur > 0 else 'LOSS'
    now = datetime.now(tz=None).strftime('%Y-%m-%d %H:%M')
    
    entry_date = pos['entry_date'] or now
    try:
        days = (datetime.strptime(now, '%Y-%m-%d %H:%M') - datetime.strptime(entry_date, '%Y-%m-%d %H:%M')).days
    except:
        days = 0
    
    vix = get_vix()
    regime = get_regime()
    
    # Build post-mortem
    postmortem = {
        'thesis_correct': thesis_correct,
        'lesson': lesson,
        'what_worked': what_worked,
        'what_failed': what_failed,
        'would_repeat': would_repeat,
        'exit_vix': vix,
        'exit_regime': regime.get('regime', 'UNKNOWN'),
        'holding_days': days,
    }
    
    db.execute("""
        UPDATE trades SET 
            status=?, exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?,
            holding_days=?, exit_type=?, vix_at_exit=?, regime_at_exit=?,
            thesis_killed_by=?, thesis_alive=?,
            lessons=?, result=?
        WHERE id=?
    """, (
        status, price_eur, now, round(pnl_eur, 2), round(pnl_pct, 2),
        days, reason, vix, regime.get('regime', 'UNKNOWN'),
        reason if status == 'LOSS' else None,
        1 if thesis_correct else 0,
        lesson or '', json.dumps(postmortem, ensure_ascii=False),
        pos['id']
    ))
    db.commit()
    
    emoji = '✅' if pnl_eur > 0 else '❌'
    print(f"\n{emoji} SA TRADE CLOSED: {ticker}")
    print(f"   Entry: {pos['entry_price']:.2f}€ → Exit: {price_eur:.2f}€")
    print(f"   P&L: {pnl_eur:+.0f}€ ({pnl_pct:+.1f}%)")
    print(f"   Haltezeit: {days} Tage")
    print(f"   Grund: {reason}")
    if thesis_correct is not None:
        print(f"   These korrekt: {'✅ Ja' if thesis_correct else '❌ Nein'}")
    if lesson:
        print(f"   Lektion: {lesson}")
    
    # Write detailed post-mortem to learning log
    _write_postmortem(pos, price_eur, pnl_eur, pnl_pct, days, reason,
                      postmortem, vix, regime, emoji)
    
    # Update learning database
    _update_learnings(pos, pnl_eur, pnl_pct, postmortem)


def _write_postmortem(pos, exit_price, pnl_eur, pnl_pct, days, reason,
                      postmortem, vix, regime, emoji):
    """Write detailed post-mortem to albert-trades.md."""
    now = datetime.now(tz=None).strftime('%Y-%m-%d %H:%M')
    
    entry = f"""
## {now} — SA POST-MORTEM: {pos['ticker']} {emoji}

### Ergebnis
- **P&L:** {pnl_eur:+.0f}€ ({pnl_pct:+.1f}%)
- **Entry:** {pos['entry_price']:.2f}€ → **Exit:** {exit_price:.2f}€
- **Haltezeit:** {days} Tage
- **Exit-Grund:** {reason}
- **VIX bei Entry:** {pos['vix_at_entry']:.1f} → **Exit:** {vix:.1f}
- **Regime bei Entry:** {pos['regime_at_entry']} → **Exit:** {regime.get('regime', '?')}

### These
> {pos['thesis'] or 'Keine These dokumentiert'}

**These korrekt?** {'✅ Ja' if postmortem.get('thesis_correct') else '❌ Nein' if postmortem.get('thesis_correct') is not None else '❓ Nicht bewertet'}

### Zweitrundeneffekt
> {pos['second_order_effect'] or 'Keiner dokumentiert'}

### Was hat funktioniert?
{postmortem.get('what_worked') or '_(nicht dokumentiert)_'}

### Was hat NICHT funktioniert?
{postmortem.get('what_failed') or '_(nicht dokumentiert)_'}

### Lektion (was nehmen wir mit?)
{postmortem.get('lesson') or '_(nicht dokumentiert)_'}

### Würde ich den Trade wiederholen?
{postmortem.get('would_repeat') or '_(nicht dokumentiert)_'}

### Setup-Details
- **Setup-Typ:** {pos['setup_type'] or '?'}
- **Theme:** {pos['geo_theme'] or '?'}
- **Scanner-Score bei Entry:** {pos['scanner_score'] or 0:.0f}
- **CRV geplant:** {pos['crv'] or 0:.1f}:1
- **CRV realisiert:** {abs(pnl_pct) / abs((pos['entry_price'] - pos['stop']) / pos['entry_price'] * 100) if pos['stop'] and pos['entry_price'] != pos['stop'] else 0:.1f}:1

---
"""
    with open(LOG_FILE, 'a') as f:
        f.write(entry)


def _update_learnings(pos, pnl_eur, pnl_pct, postmortem):
    """Update the SA learning database (JSON) with aggregated insights."""
    learn_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sa_learnings.json')
    
    try:
        with open(learn_file) as f:
            learnings = json.load(f)
    except:
        learnings = {
            'total_trades': 0,
            'total_pnl': 0,
            'wins': 0,
            'losses': 0,
            'by_setup': {},
            'by_theme': {},
            'by_vix_zone': {},
            'thesis_accuracy': {'correct': 0, 'incorrect': 0, 'unknown': 0},
            'lessons': [],
            'patterns': {
                'best_setup': None,
                'worst_setup': None,
                'best_theme': None,
                'avg_winner_hold': 0,
                'avg_loser_hold': 0,
                'avg_crv_realized': 0,
            },
            'meta_insights': [],
        }
    
    # Update totals
    learnings['total_trades'] += 1
    learnings['total_pnl'] = round(learnings['total_pnl'] + pnl_eur, 2)
    if pnl_eur > 0:
        learnings['wins'] += 1
    else:
        learnings['losses'] += 1
    
    # By setup type
    setup = pos['setup_type'] or 'UNKNOWN'
    if setup not in learnings['by_setup']:
        learnings['by_setup'][setup] = {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0, 'avg_hold': 0}
    s = learnings['by_setup'][setup]
    s['trades'] += 1
    s['pnl'] = round(s['pnl'] + pnl_eur, 2)
    if pnl_eur > 0: s['wins'] += 1
    else: s['losses'] += 1
    hold = postmortem.get('holding_days', 0)
    s['avg_hold'] = round((s['avg_hold'] * (s['trades'] - 1) + hold) / s['trades'], 1)
    
    # By theme
    theme = pos['geo_theme'] or 'UNKNOWN'
    if theme not in learnings['by_theme']:
        learnings['by_theme'][theme] = {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
    t = learnings['by_theme'][theme]
    t['trades'] += 1
    t['pnl'] = round(t['pnl'] + pnl_eur, 2)
    if pnl_eur > 0: t['wins'] += 1
    else: t['losses'] += 1
    
    # By VIX zone
    vix_zone = get_vix_zone(pos['vix_at_entry'] or 20)
    if vix_zone not in learnings['by_vix_zone']:
        learnings['by_vix_zone'][vix_zone] = {'trades': 0, 'pnl': 0, 'wins': 0}
    v = learnings['by_vix_zone'][vix_zone]
    v['trades'] += 1
    v['pnl'] = round(v['pnl'] + pnl_eur, 2)
    if pnl_eur > 0: v['wins'] += 1
    
    # Thesis accuracy
    tc = postmortem.get('thesis_correct')
    if tc is True:
        learnings['thesis_accuracy']['correct'] += 1
    elif tc is False:
        learnings['thesis_accuracy']['incorrect'] += 1
    else:
        learnings['thesis_accuracy']['unknown'] += 1
    
    # Store lesson
    if postmortem.get('lesson'):
        learnings['lessons'].append({
            'date': datetime.now(tz=None).strftime('%Y-%m-%d'),
            'ticker': pos['ticker'],
            'setup': setup,
            'theme': theme,
            'pnl': round(pnl_eur, 0),
            'lesson': postmortem['lesson'],
        })
        # Keep last 50 lessons
        learnings['lessons'] = learnings['lessons'][-50:]
    
    # Compute patterns
    if learnings['total_trades'] >= 3:
        # Best/worst setup
        best_s = max(learnings['by_setup'].items(), key=lambda x: x[1]['pnl'])
        worst_s = min(learnings['by_setup'].items(), key=lambda x: x[1]['pnl'])
        learnings['patterns']['best_setup'] = f"{best_s[0]} ({best_s[1]['pnl']:+.0f}€, {best_s[1]['trades']} trades)"
        learnings['patterns']['worst_setup'] = f"{worst_s[0]} ({worst_s[1]['pnl']:+.0f}€, {worst_s[1]['trades']} trades)"
        
        # Best theme
        if learnings['by_theme']:
            best_t = max(learnings['by_theme'].items(), key=lambda x: x[1]['pnl'])
            learnings['patterns']['best_theme'] = f"{best_t[0]} ({best_t[1]['pnl']:+.0f}€)"
    
    # Meta-insights (auto-generated after 5+ trades)
    if learnings['total_trades'] >= 5:
        insights = []
        wr = learnings['wins'] / learnings['total_trades'] * 100
        if wr < 30:
            insights.append("⚠️ Win Rate unter 30% — Entry-Qualität überprüfen oder CRV erhöhen")
        if wr > 50:
            insights.append("✅ Win Rate über 50% — Strategie funktioniert, Positionsgrößen prüfen (zu konservativ?)")
        
        ta = learnings['thesis_accuracy']
        if ta['correct'] + ta['incorrect'] >= 5:
            thesis_wr = ta['correct'] / (ta['correct'] + ta['incorrect']) * 100
            if thesis_wr < 40:
                insights.append("⚠️ These-Trefferquote unter 40% — Analyse-Qualität verbessern")
            if thesis_wr > 60:
                insights.append("✅ These-Trefferquote über 60% — Informationsvorsprung bestätigt")
        
        # VIX zone insight
        for zone, data in learnings['by_vix_zone'].items():
            if data['trades'] >= 3:
                zone_wr = data['wins'] / data['trades'] * 100
                if zone_wr < 25:
                    insights.append(f"⚠️ VIX-Zone '{zone}': {zone_wr:.0f}% WR — in dieser Zone weniger traden")
        
        learnings['meta_insights'] = insights
    
    with open(learn_file, 'w') as f:
        json.dump(learnings, f, indent=2, ensure_ascii=False)
    
    print(f"\n📚 LEARNING UPDATE:")
    print(f"   Gesamt: {learnings['total_trades']} Trades | WR {learnings['wins']/learnings['total_trades']*100:.0f}% | P&L {learnings['total_pnl']:+.0f}€")
    if learnings.get('meta_insights'):
        print(f"   Insights:")
        for insight in learnings['meta_insights']:
            print(f"     {insight}")


def cmd_report():
    """Weekly SA performance report."""
    db = get_db()
    
    print("=" * 60)
    print("🎩 ALBERT STRATEGY — PERFORMANCE REPORT")
    print("=" * 60)
    
    # All SA trades
    all_trades = db.execute(
        "SELECT * FROM trades WHERE strategy='SA' ORDER BY entry_date"
    ).fetchall()
    
    closed = [t for t in all_trades if t['status'] in ('WIN', 'LOSS', 'STOPPED')]
    open_trades = [t for t in all_trades if t['status'] == 'OPEN']
    
    total_closed = len(closed)
    wins = sum(1 for t in closed if t['pnl_eur'] and t['pnl_eur'] > 0)
    losses = total_closed - wins
    total_pnl = sum(t['pnl_eur'] or 0 for t in closed)
    
    print(f"\n📊 GESAMT:")
    print(f"  Geschlossen: {total_closed} Trades")
    print(f"  Win Rate: {wins/total_closed*100:.0f}% ({wins}W / {losses}L)" if total_closed else "  Noch keine geschlossenen Trades")
    print(f"  Total P&L: {total_pnl:+.0f}€" if total_closed else "")
    print(f"  Offen: {len(open_trades)} Positionen")
    
    # By setup type
    if closed:
        print(f"\n📋 NACH SETUP-TYP:")
        for setup in [SETUP_A, SETUP_B, SETUP_C, SETUP_D]:
            subset = [t for t in closed if t['setup_type'] == setup]
            if subset:
                w = sum(1 for t in subset if t['pnl_eur'] and t['pnl_eur'] > 0)
                pnl = sum(t['pnl_eur'] or 0 for t in subset)
                wr = w / len(subset) * 100
                print(f"  {setup:15s}: {len(subset)} Trades | WR {wr:.0f}% | P&L {pnl:+.0f}€")
    
    # By theme
    if closed:
        print(f"\n🌍 NACH THEMA:")
        themes_seen = set(t['geo_theme'] for t in closed if t['geo_theme'])
        for theme in themes_seen:
            subset = [t for t in closed if t['geo_theme'] == theme]
            pnl = sum(t['pnl_eur'] or 0 for t in subset)
            print(f"  {theme:20s}: {len(subset)} Trades | P&L {pnl:+.0f}€")
    
    # Open positions
    if open_trades:
        print(f"\n📍 OFFENE POSITIONEN:")
        for t in open_trades:
            print(f"  {t['ticker']:10s} | Entry {t['entry_price']:.2f}€ | Stop {t['stop']:.2f}€ | {t['setup_type'] or '?'}")
    
    # Rule compliance
    print(f"\n📏 REGELCHECK:")
    print(f"  Trades mit These: {sum(1 for t in all_trades if t['thesis'])}/{len(all_trades)}")
    print(f"  CRV ≥ 3: {sum(1 for t in all_trades if t['crv'] and t['crv'] >= 3)}/{len(all_trades)}")
    print(f"  VIX erfasst: {sum(1 for t in all_trades if t['vix_at_entry'])}/{len(all_trades)}")
    
    # Learning insights
    learn_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sa_learnings.json')
    try:
        with open(learn_file) as f:
            learnings = json.load(f)
        
        print(f"\n📚 LEARNINGS (kumuliert):")
        print(f"  Gesamt P&L: {learnings['total_pnl']:+.0f}€")
        
        ta = learnings.get('thesis_accuracy', {})
        total_rated = ta.get('correct', 0) + ta.get('incorrect', 0)
        if total_rated > 0:
            thesis_wr = ta['correct'] / total_rated * 100
            print(f"  These-Trefferquote: {thesis_wr:.0f}% ({ta['correct']}✅ / {ta['incorrect']}❌)")
        
        if learnings.get('by_setup'):
            print(f"\n  Setup-Performance:")
            for setup, data in sorted(learnings['by_setup'].items(), key=lambda x: x[1]['pnl'], reverse=True):
                wr = data['wins'] / data['trades'] * 100 if data['trades'] else 0
                print(f"    {setup:15s}: {data['trades']} Tr | WR {wr:.0f}% | P&L {data['pnl']:+.0f}€ | Avg Hold {data['avg_hold']:.0f}d")
        
        if learnings.get('by_theme'):
            print(f"\n  Theme-Performance:")
            for theme, data in sorted(learnings['by_theme'].items(), key=lambda x: x[1]['pnl'], reverse=True):
                wr = data['wins'] / data['trades'] * 100 if data['trades'] else 0
                print(f"    {theme:20s}: {data['trades']} Tr | WR {wr:.0f}% | P&L {data['pnl']:+.0f}€")
        
        if learnings.get('meta_insights'):
            print(f"\n  🧠 Auto-Insights:")
            for insight in learnings['meta_insights']:
                print(f"    {insight}")
        
        if learnings.get('lessons'):
            print(f"\n  📝 Letzte Lektionen:")
            for l in learnings['lessons'][-5:]:
                print(f"    [{l['date']}] {l['ticker']} ({l['pnl']:+.0f}€): {l['lesson']}")
        
        # Patterns
        p = learnings.get('patterns', {})
        if p.get('best_setup'):
            print(f"\n  📊 Patterns:")
            print(f"    Bestes Setup: {p['best_setup']}")
            print(f"    Schlechtestes Setup: {p['worst_setup']}")
            if p.get('best_theme'):
                print(f"    Bestes Thema: {p['best_theme']}")
    except FileNotFoundError:
        print(f"\n📚 Noch keine Learnings — erster geschlossener Trade startet die Datenbank.")


def _auto_generate_thesis(ticker, info, theme_id, theme, scanner_score):
    """Auto-generate thesis + second-order effects based on theme and scanner data."""
    theses = {
        'iran_hormuz': {
            'OXY': (
                f"Öl profitiert von Iran-Eskalation (Scanner Score {scanner_score}). "
                "Hormuz-Risiko steigt, globale Ölversorgung unter Druck.",
                "Hormuz-Blockade → Tankerraten steigen → Versicherungskosten explodieren → Ölpreis-Premium bleibt"
            ),
            'EQNR.OL': (
                f"Equinor als europäischer Öl-Profiteur der Iran-Krise (Score {scanner_score}). "
                "Nordsee-Öl wird Premium wenn Hormuz-Route gefährdet.",
                "Iran-Eskalation → Europa braucht non-OPEC Öl → Nordsee-Premium steigt → EQNR Buybacks + Dividende"
            ),
            'FRO': (
                f"Tanker-Raten explodieren bei Hormuz-Eskalation (Score {scanner_score}). "
                "Frontline mit größter VLCC-Flotte direkt betroffen.",
                "Umleitung um Kap der Guten Hoffnung → Reise 40% länger → weniger verfügbare Tanker → Spot-Raten verdreifachen"
            ),
            'DHT': (
                f"DHT Holdings profitiert als VLCC-Betreiber von Hormuz-Risiko (Score {scanner_score}).",
                "Versicherungsprämien für Persischen Golf steigen → Kunden zahlen mehr → DHT Revenue up"
            ),
            'TTE.PA': (
                f"TotalEnergies als diversifizierter Energie-Major profitiert von Ölpreis-Spike (Score {scanner_score}).",
                "Iran-Krise → LNG-Nachfrage Europa steigt (Gasersatz) → TTE LNG-Portfolio gewinnt doppelt"
            ),
            'SHEL.L': (
                f"Shell als globaler Energie-Major mit LNG+Öl-Exposure profitiert von Krise (Score {scanner_score}).",
                "Hormuz-Risiko → Asien kauft mehr Atlantic Basin LNG → Shell Trading Desk verdient an Arbitrage"
            ),
        },
        'cuba_crisis': {
            'S.TO': (
                f"Sherritt als einziger westlicher Kuba-Investor ist Leading Indicator für Regime-Wechsel (Score {scanner_score}).",
                "Regime Change → Sanktionen fallen → Sherritts Moa-Nickel-Mine wird wieder profitabel → 10x Potential"
            ),
            'MP': (
                f"Kuba-Blockade stört Kobalt-Lieferkette — MP Materials als US-Domestic Alternative (Score {scanner_score}).",
                "Kobalt/Nickel aus Kuba fällt aus → US braucht domestic supply → MP als einziger US-Produzent"
            ),
            'CCL': (
                f"Carnival Cruise Lines verliert Kuba-Routen komplett bei Blockade (Score {scanner_score}). SHORT-Kandidat.",
                "Blockade → Kuba-Kreuzfahrten tot → Caribbean-Routen müssen umgeplant werden → Kosten steigen"
            ),
        },
        'silver_correction': {
            'AG': (
                f"First Majestic als purer Silberproduzent mit größtem Hebel auf Silber-Erholung.",
                "Silber Bodenbildung → Minen-Aktien outperformen physisches Silber um Faktor 1.5-2x"
            ),
            'PAAS': (
                f"Pan American Silver als größter Silberproduzent der Welt profitiert überproportional.",
                "Silber-Boden → Operating Leverage bei Minern → PAAS Marge expandiert überproportional"
            ),
            'WPM': (
                f"Wheaton als Streaming-Company mit niedrigsten Kosten profitiert ab Silber >$30 massiv.",
                "Streaming-Modell → fixe Kosten, variable Revenue → bei Silber-Rally ist WPM purer Profit-Hebel"
            ),
            'HL': (
                f"Hecla Mining als US-Silberproduzent profitiert von Silber-Erholung.",
                "US-Produktion → kein Länder-Risiko → bei Silber-Rally solide Mid-Tier Performance"
            ),
            'EXK': (
                f"Endeavour Silver als Junior-Miner mit höchstem Hebel auf Silber-Rebound.",
                "Junior-Miner → höchstes Risiko aber auch höchster Hebel → bei Silber +20% kann EXK +40% machen"
            ),
        },
        'china_tech': {
            '9988.HK': (
                f"Alibaba profitiert von China-Stimulus und Trade War De-Eskalation (Score {scanner_score}).",
                "Trade War Pause → Kapital fließt zurück nach China-Tech → Alibaba als Benchmark"
            ),
            '0700.HK': (
                f"Tencent als China-Gaming/Social-Giant bei Trade War Entspannung (Score {scanner_score}).",
                "Regulierungs-Lockerung + Trade War Pause → doppelter Rückenwind für Tencent"
            ),
            'BABA': (
                f"Alibaba US-ADR als liquidester China-Tech Trade (Score {scanner_score}).",
                "US-Investoren kaufen zuerst ADRs → BABA bewegt sich vor HK-Listing"
            ),
            'KWEB': (
                f"China Internet ETF als breites Exposure bei Trade War De-Eskalation (Score {scanner_score}).",
                "Breiter Basket → weniger Einzelrisiko → bei China-Rally steigt der gesamte Sektor"
            ),
        },
    }
    
    defaults = theses.get(theme_id, {}).get(ticker, (
        f"{info['name']} — Geopolitischer Setup via {theme['name']} (Score {scanner_score}).",
        "Zweitrundeneffekt noch zu analysieren."
    ))
    return defaults


def _auto_close_with_postmortem(db, pos, price_eur, reason, vix, regime):
    """Auto-close a position and generate post-mortem."""
    # Realistic exit: subtract spread + slippage + commission
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from trademind.execution.simulator import simulate_fill
        fill = simulate_fill(price_eur, 'SELL', pos['ticker'], vix)
        price_eur = fill['fill_price']
    except:
        pass
    pnl_eur = (price_eur - pos['entry_price']) * pos['shares']
    pnl_pct = ((price_eur - pos['entry_price']) / pos['entry_price']) * 100
    status = 'WIN' if pnl_eur > 0 else 'LOSS'
    now = datetime.now(tz=None).strftime('%Y-%m-%d %H:%M')
    
    entry_date = pos['entry_date'] or now
    try:
        days = (datetime.strptime(now, '%Y-%m-%d %H:%M') - datetime.strptime(entry_date, '%Y-%m-%d %H:%M')).days
    except:
        days = 0
    
    # Auto-generate post-mortem based on outcome
    if reason == 'stop_hit':
        thesis_correct = pnl_eur > 0  # If we made money even with stop, thesis was partly right
        what_worked = "Stop-Loss hat Verlust begrenzt" if pnl_eur < 0 else "Trailing Stop hat Gewinn gesichert"
        what_failed = f"Kurs hat Stop bei {pos['stop']:.2f}€ gerissen" if pnl_eur < 0 else "Kein Fehler — Trailing Stop korrekt ausgeführt"
        if pnl_eur < 0:
            lesson = f"Stop bei {abs(pnl_pct):.1f}% Verlust ausgelöst nach {days}d — war der Stop zu eng für VIX {pos['vix_at_entry']:.0f}?"
        else:
            lesson = f"Trailing Stop hat {pnl_eur:+.0f}€ gesichert nach {days}d — System funktioniert"
        would_repeat = "Ja, der Stop hat seine Arbeit gemacht" if pnl_eur >= 0 else f"Prüfen ob ATR×2 Stop bei VIX {pos['vix_at_entry']:.0f} ausreicht"
    elif reason == 'thesis_dead':
        thesis_correct = False
        what_worked = "Thesis-Kill erkannt bevor weiterer Verlust entstand"
        what_failed = f"Ursprüngliche These war falsch oder hat sich geändert"
        lesson = f"These war nicht haltbar nach {days}d — besser früh raus als stur halten"
        would_repeat = "Nein — die These war das Problem, nicht die Ausführung"
    elif reason == 'target_reached':
        thesis_correct = True
        what_worked = f"These war korrekt, Ziel nach {days}d erreicht"
        what_failed = "Nichts — Trade nach Plan"
        lesson = f"Geduld hat sich ausgezahlt: {pnl_eur:+.0f}€ nach {days}d"
        would_repeat = "Ja — exakt so wieder"
    elif reason == 'time_exit':
        thesis_correct = pnl_eur > 0
        what_worked = "Zeitlimit hat Position nicht ewig offen gelassen"
        what_failed = f"These hat sich nicht im geplanten Zeitraum materialisiert" if pnl_eur <= 0 else "Nichts"
        lesson = f"Nach {days}d {pnl_eur:+.0f}€ — Timing war {'gut' if pnl_eur > 0 else 'zu früh oder These zu langsam'}"
        would_repeat = f"{'Ja' if pnl_eur > 0 else 'Mit angepasstem Zeithorizont'}"
    elif 'home_run' in reason:
        thesis_correct = True
        what_worked = f"These voll aufgegangen — {pnl_pct:+.1f}% Gewinn realisiert nach {days}d"
        what_failed = "Nichts — Home Run"
        lesson = f"HOME RUN {pnl_eur:+.0f}€ in {days}d — Geduld + richtige These = maximaler Gewinn"
        would_repeat = "Exakt so — perfekter Trade"
    elif 'theme_cooling' in reason:
        thesis_correct = True
        what_worked = f"These war korrekt, Scanner-Rückgang erkannt = Event eingepreist → Gewinn mitgenommen"
        what_failed = "Nichts — sauberer Exit"
        lesson = f"Gewinn {pnl_eur:+.0f}€ realisiert als Scanner-Score fiel — Event ist im Preis, nicht warten bis es dreht"
        would_repeat = "Ja — Scanner als Exit-Signal nutzen ist smart"
    elif 'vix_normalized' in reason:
        thesis_correct = True
        what_worked = f"Einstieg bei hohem VIX, Exit bei normalem VIX — Vola-Premium abgeschöpft"
        what_failed = "Nichts — Vola-Trade nach Plan"
        lesson = f"VIX-Normalisierung = Geopolitik-Premium verschwindet → {pnl_eur:+.0f}€ realisiert. Nicht warten bis VIX wieder steigt."
        would_repeat = "Ja — VIX als Exit-Signal funktioniert"
    else:
        thesis_correct = pnl_eur > 0
        what_worked = f"{'Kursgewinn' if pnl_eur > 0 else 'Verlustbegrenzung'}"
        what_failed = f"{'—' if pnl_eur > 0 else 'Trade ging nicht auf'}"
        lesson = f"{pnl_eur:+.0f}€ nach {days}d — Grund: {reason}"
        would_repeat = "Zu analysieren"
    
    postmortem = {
        'thesis_correct': thesis_correct,
        'lesson': lesson,
        'what_worked': what_worked,
        'what_failed': what_failed,
        'would_repeat': would_repeat,
        'exit_vix': vix,
        'exit_regime': regime.get('regime', 'UNKNOWN'),
        'holding_days': days,
        'auto_generated': True,
    }
    
    db.execute("""
        UPDATE trades SET 
            status=?, exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?,
            holding_days=?, exit_type=?, vix_at_exit=?, regime_at_exit=?,
            thesis_killed_by=?, thesis_alive=?,
            lessons=?, result=?
        WHERE id=?
    """, (
        status, price_eur, now, round(pnl_eur, 2), round(pnl_pct, 2),
        days, reason, vix, regime.get('regime', 'UNKNOWN'),
        reason if status == 'LOSS' else None,
        1 if thesis_correct else 0,
        lesson, json.dumps(postmortem, ensure_ascii=False),
        pos['id']
    ))
    
    # Write post-mortem
    _write_postmortem(pos, price_eur, pnl_eur, pnl_pct, days, reason,
                      postmortem, vix, regime, '✅' if pnl_eur > 0 else '❌')
    _update_learnings(pos, pnl_eur, pnl_pct, postmortem)
    
    return pnl_eur, pnl_pct, status, postmortem


def cmd_auto():
    """
    AUTONOMOUS MODE — Full cycle: monitor → close stops → scan → open new trades.
    Designed for cron execution. No human input needed.
    """
    print("=" * 60)
    print("🎩 ALBERT STRATEGY — AUTONOMOUS CYCLE")
    print(f"   {datetime.now(tz=None).strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    db = get_db()
    vix = get_vix()
    zone = get_vix_zone(vix)
    scanner = get_scanner_data()
    regime = get_regime()
    
    print(f"\n📊 VIX: {vix:.2f} ({zone}) | Scanner: {scanner['score']} | Regime: {regime.get('regime', '?')}")
    
    alerts = []  # Collect alerts for output
    
    # ═══ PHASE 0: CIRCUIT BREAKER CHECK ═══
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from trademind.risk.circuit_breaker import check_circuit_breakers
        cb = check_circuit_breakers(db)
        if not cb['trading_allowed']:
            triggered = ', '.join(cb['breakers_triggered'])
            print(f"\n🚨 CIRCUIT BREAKER TRIGGERED: {triggered}")
            print(f"   Trading gesperrt bis: {cb.get('resume_at', 'manuell')}")
            alerts.append(f"🚨 CIRCUIT BREAKER: {triggered} — keine neuen Trades")
            # Still monitor existing positions (Phase 1), but skip Phase 2 (new trades)
            cb_blocked = True
        else:
            cb_blocked = False
            print(f"\n✅ Circuit Breakers: OK")
    except Exception as e:
        print(f"\n⚠️ Circuit Breaker Check fehlgeschlagen: {e}")
        cb_blocked = False
    
    # ═══ PHASE 1: MONITOR + AUTO-CLOSE ═══
    print(f"\n{'─'*60}")
    print("📍 PHASE 1: Monitor offene Positionen")
    
    positions = db.execute(
        "SELECT * FROM trades WHERE strategy='SA' AND status='OPEN' ORDER BY entry_date"
    ).fetchall()
    
    closed_this_run = []
    
    for p in positions:
        ticker = p['ticker']
        price, currency = get_price_yahoo(ticker)
        if not price:
            print(f"  ⚠️ {ticker}: Preis nicht verfügbar — überspringe")
            continue
        
        price_eur = to_eur(price, currency)
        entry = p['entry_price']
        stop = p['stop']
        pnl_pct = ((price_eur - entry) / entry) * 100 if entry else 0
        risk = p['risk_eur'] or ((entry - stop) * p['shares']) if stop else 0
        
        # === CHECK 0: PROFIT-TAKING (realisierte Gewinne!) ===
        pnl_eur_now = (price_eur - entry) * p['shares']
        risk = p['risk_eur'] or ((entry - stop) * p['shares']) if stop else 0
        gain_ratio = pnl_eur_now / risk if risk and risk > 0 else 0
        
        try:
            entry_dt = datetime.strptime(p['entry_date'], '%Y-%m-%d %H:%M')
            days_held = (datetime.now(tz=None) - entry_dt).days
        except:
            days_held = 0
        
        # Rule A: Take 50% at 3x Risk (CRV 3:1 erreicht = Kernziel)
        # Rule B: Take 30% more at 5x Risk
        # Rule C: Close remaining at 7x Risk (Home Run = Buch zu)
        # Rule D: If up >8% after 2+ days and scanner score dropping → full close
        # Rule E: If up >5% and VIX dropping below 22 → theme cooling, take profit
        
        profit_exit = False
        profit_reason = ''
        
        # C: Home Run — 7x Risk = Buch komplett zu
        if gain_ratio >= 7:
            profit_exit = True
            profit_reason = f'home_run_7x (Gain {gain_ratio:.1f}x Risk, +{pnl_pct:+.1f}%)'
        
        # D: Theme cooling — up >8% but scanner score dropped significantly
        elif pnl_pct >= 8 and days_held >= 2:
            # Check if theme score is dropping
            current_theme_score = 0
            for region in scanner.get('regions', []):
                if isinstance(region, dict):
                    rname = (region.get('name', '') or region.get('region', '')).lower()
                    theme_kws = []
                    for tid, tdata in THEMES.items():
                        if tid == p['geo_theme']:
                            theme_kws = tdata.get('scanner_keywords', [])
                    if any(kw in rname for kw in theme_kws):
                        s = region.get('score', 0)
                        if isinstance(s, str):
                            try: s = int(s)
                            except: s = 0
                        current_theme_score = max(current_theme_score, s)
            
            entry_score = p['scanner_score'] or 0
            if entry_score > 0 and current_theme_score < entry_score * 0.5:
                profit_exit = True
                profit_reason = f'theme_cooling (+{pnl_pct:.1f}%, Scanner {entry_score:.0f}→{current_theme_score:.0f})'
        
        # E: VIX normalisiert sich + wir sind im Plus → Risiko-Appetit sinkt = Event eingepreist
        elif pnl_pct >= 5 and days_held >= 3 and vix < 22 and (p['vix_at_entry'] or 0) > 25:
            profit_exit = True
            profit_reason = f'vix_normalized (+{pnl_pct:.1f}%, VIX {p["vix_at_entry"]:.0f}→{vix:.0f})'
        
        if profit_exit:
            print(f"  💰 {ticker}: PROFIT TAKE @ {price_eur:.2f}€ ({pnl_pct:+.1f}%) — {profit_reason}")
            pnl, pct, status, pm = _auto_close_with_postmortem(db, p, price_eur, profit_reason, vix, regime)
            closed_this_run.append((ticker, pnl, pct, profit_reason, pm.get('lesson', '')))
            alerts.append(f"💰 {ticker} PROFIT TAKE: {pnl:+.0f}€ ({pct:+.1f}%) — {profit_reason}")
            continue
        
        # === CHECK 1: Stop Hit ===
        if price_eur <= stop:
            print(f"  🔴 {ticker}: STOP HIT @ {price_eur:.2f}€ (Stop: {stop:.2f}€)")
            pnl, pct, status, pm = _auto_close_with_postmortem(db, p, price_eur, 'stop_hit', vix, regime)
            closed_this_run.append((ticker, pnl, pct, 'stop_hit', pm.get('lesson', '')))
            alerts.append(f"🔴 {ticker} STOP HIT: {pnl:+.0f}€ ({pct:+.1f}%) — {pm.get('lesson', '')}")
            continue
        
        # === CHECK 2: Trailing Stops ===
        new_stop = stop
        trail_phase = '🔴 Initial'
        
        if risk and risk > 0:
            pnl_eur = (price_eur - entry) * p['shares']
            gain_ratio = pnl_eur / risk
            
            if gain_ratio >= 5:
                new_stop = max(stop, entry + (price_eur - entry) * 0.70)
                trail_phase = '🚀 Runner'
                # Auto partial close: 30% at 5x risk
                if not p.get('trail_count') or p['trail_count'] < 5:
                    pass  # TODO: partial close logic
            elif gain_ratio >= 3:
                new_stop = max(stop, entry + (price_eur - entry) * 0.50)
                trail_phase = '🟢 Trailing'
            elif gain_ratio >= 1.5:
                new_stop = max(stop, entry)
                trail_phase = '🟡 Breakeven'
        
        if new_stop > stop:
            db.execute("UPDATE trades SET stop=?, trail_count=COALESCE(trail_count,0)+1 WHERE id=?",
                       (round(new_stop, 2), p['id']))
            print(f"  📈 {ticker}: Stop {stop:.2f}€ → {new_stop:.2f}€ ({trail_phase})")
            alerts.append(f"📈 {ticker} Stop nachgezogen → {new_stop:.2f}€ ({trail_phase})")
            stop = new_stop
        
        # === CHECK 3: Time Exit (max 30 Tage) ===
        try:
            entry_dt = datetime.strptime(p['entry_date'], '%Y-%m-%d %H:%M')
            days_held = (datetime.now(tz=None) - entry_dt).days
            if days_held > 30:
                print(f"  ⏰ {ticker}: 30-Tage-Limit erreicht ({days_held}d)")
                pnl, pct, status, pm = _auto_close_with_postmortem(db, p, price_eur, 'time_exit', vix, regime)
                closed_this_run.append((ticker, pnl, pct, 'time_exit', pm.get('lesson', '')))
                alerts.append(f"⏰ {ticker} TIME EXIT nach {days_held}d: {pnl:+.0f}€ ({pct:+.1f}%)")
                continue
        except:
            pass
        
        # Update current price in DB
        pnl_eur_current = (price_eur - entry) * p['shares']
        db.execute("UPDATE trades SET pnl_eur=?, pnl_pct=? WHERE id=?",
                   (round(pnl_eur_current, 2), round(pnl_pct, 2), p['id']))
        
        stop_dist = ((price_eur - stop) / price_eur) * 100 if price_eur > 0 else 0
        print(f"  {'✅' if pnl_pct > 0 else '⚠️'} {ticker}: {price_eur:.2f}€ ({pnl_pct:+.1f}%) | Stop {stop:.2f}€ ({stop_dist:.1f}% weg) | {trail_phase}")
        
        time.sleep(0.3)
    
    db.commit()
    
    # ═══ PHASE 2: SCAN + AUTO-OPEN ═══
    open_count = db.execute(
        "SELECT COUNT(*) as c FROM trades WHERE strategy='SA' AND status='OPEN'"
    ).fetchone()['c']
    
    max_pos = MAX_POSITIONS[zone]
    slots_free = max_pos - open_count
    
    print(f"\n{'─'*60}")
    print(f"📍 PHASE 2: Neue Setups suchen ({slots_free} Slots frei)")
    
    if cb_blocked:
        print(f"  🚨 Circuit Breaker aktiv — keine neuen Trades.")
        slots_free = 0
    
    if slots_free <= 0:
        print(f"  ⛔ Alle {max_pos} Slots belegt. Keine neuen Trades.")
    else:
        # Scan themes
        best_setups = []
        
        for theme_id, theme in THEMES.items():
            theme_score = 0
            for region in scanner.get('regions', []):
                if isinstance(region, dict):
                    name = (region.get('name', '') or region.get('region', '')).lower()
                    score_val = region.get('score', 0)
                    if isinstance(score_val, str):
                        try: score_val = int(score_val)
                        except: score_val = 0
                    if any(kw in name for kw in theme['scanner_keywords']):
                        theme_score = max(theme_score, score_val)
            
            if theme_score < theme['min_score'] and theme_id != 'silver_correction':
                continue
            
            # Check same-theme limit
            same_theme_count = db.execute(
                "SELECT COUNT(*) as c FROM trades WHERE strategy='SA' AND status='OPEN' AND geo_theme=?",
                (theme_id,)
            ).fetchone()['c']
            if same_theme_count >= MAX_SAME_THEME:
                continue
            
            for ticker, info in theme['tickers'].items():
                # Skip if already in position
                existing = db.execute(
                    "SELECT id FROM trades WHERE ticker=? AND strategy='SA' AND status='OPEN'", (ticker,)
                ).fetchone()
                if existing:
                    continue
                
                price, currency = get_price_yahoo(ticker)
                if not price:
                    continue
                
                price_eur = to_eur(price, currency)
                atr = get_atr(ticker)
                if not atr:
                    continue
                
                atr_eur = to_eur(atr, currency)
                pos = calculate_position(PORTFOLIO_SIZE, zone, price_eur, atr_eur)
                if not pos:
                    continue
                
                # Score: theme_score * (position_quality)
                # Prefer higher scanner scores and better CRV
                quality = theme_score * MIN_CRV[zone]
                
                best_setups.append({
                    'ticker': ticker,
                    'info': info,
                    'theme_id': theme_id,
                    'theme': theme,
                    'price': price,
                    'currency': currency,
                    'price_eur': price_eur,
                    'atr_eur': atr_eur,
                    'position': pos,
                    'theme_score': theme_score,
                    'quality': quality,
                })
                
                time.sleep(0.3)
        
        # Sort by quality (highest scanner score × CRV first)
        best_setups.sort(key=lambda x: x['quality'], reverse=True)
        
        # Open top N trades (up to slots_free)
        opened = 0
        for setup in best_setups:
            if opened >= slots_free:
                break
            
            ticker = setup['ticker']
            info = setup['info']
            theme_id = setup['theme_id']
            theme = setup['theme']
            theme_score = setup['theme_score']
            
            # Generate thesis
            thesis, second_order = _auto_generate_thesis(ticker, info, theme_id, theme, theme_score)
            
            # Determine setup type
            if theme_score >= 60:
                setup_type = SETUP_A  # High score = reactive shock
            elif theme_score >= 30:
                setup_type = SETUP_B  # Medium = creeping thesis
            else:
                setup_type = SETUP_D  # Low = bottom fishing (silver etc)
            
            # Risk checks before opening
            try:
                from trademind.risk.correlation import check_correlation
                from trademind.risk.portfolio import get_portfolio_exposure
                
                open_tickers = [p['ticker'] for p in db.execute(
                    "SELECT ticker FROM trades WHERE strategy='SA' AND status='OPEN'"
                ).fetchall()]
                
                # Correlation check
                corr = check_correlation(ticker, open_tickers)
                if corr.get('suggested_action') == 'reject':
                    print(f"  ❌ {ticker}: Korrelation {corr['max_correlation']:.2f} mit {corr.get('correlated_with','')} → ABGELEHNT")
                    continue
                elif corr.get('suggested_action') == 'half_size':
                    print(f"  ⚠️ {ticker}: Korrelation {corr['max_correlation']:.2f} → halbe Positionsgröße")
                
                # Exposure check
                all_positions = db.execute(
                    "SELECT * FROM trades WHERE strategy='SA' AND status='OPEN'"
                ).fetchall()
                exposure = get_portfolio_exposure([dict(p) for p in all_positions])
                if exposure.get('violations'):
                    # Check if this trade would make it worse
                    from trademind.risk.portfolio import SECTOR_MAP
                    new_sector = SECTOR_MAP.get(ticker, 'Other')
                    sector_pct = exposure['by_sector'].get(new_sector, {}).get('pct', 0)
                    if sector_pct > 40:
                        print(f"  ❌ {ticker}: Sektor {new_sector} bereits bei {sector_pct:.0f}% (Limit 40%) → ABGELEHNT")
                        continue
            except Exception as e:
                print(f"  ⚠️ Risk Check fehlgeschlagen: {e} — Trade wird fortgesetzt")
            
            print(f"  🎯 Opening: {ticker} ({info['name']}) — {theme['name']} (Score {theme_score})")
            
            cmd_trade(ticker, thesis, setup_type, second_order, theme_id)
            opened += 1
            alerts.append(f"🎯 NEW TRADE: {ticker} ({setup_type}) — {thesis[:80]}...")
            
            time.sleep(0.5)
        
        if not best_setups:
            print(f"  💤 Keine qualifizierten Setups. Cash halten.")
    
    # ═══ PHASE 3: SUMMARY ═══
    print(f"\n{'─'*60}")
    print(f"📍 PHASE 3: Zusammenfassung")
    
    final_open = db.execute(
        "SELECT COUNT(*) as c FROM trades WHERE strategy='SA' AND status='OPEN'"
    ).fetchone()['c']
    total_closed = db.execute(
        "SELECT COUNT(*) as c FROM trades WHERE strategy='SA' AND status IN ('WIN','LOSS','STOPPED')"
    ).fetchone()['c']
    total_pnl = db.execute(
        "SELECT COALESCE(SUM(pnl_eur), 0) as p FROM trades WHERE strategy='SA' AND status IN ('WIN','LOSS','STOPPED')"
    ).fetchone()['p']
    
    print(f"  Offen: {final_open}/{max_pos} | Geschlossen: {total_closed} | P&L: {total_pnl:+.0f}€")
    if closed_this_run:
        print(f"  Heute geschlossen: {len(closed_this_run)}")
        for t, pnl, pct, reason, lesson in closed_this_run:
            print(f"    {'✅' if pnl > 0 else '❌'} {t}: {pnl:+.0f}€ ({pct:+.1f}%) — {reason} — {lesson[:60]}")
    
    if alerts:
        print(f"\n🚨 ALERTS ({len(alerts)}):")
        for a in alerts:
            print(f"  {a}")
    
    print(f"\n{'='*60}")
    
    # Return alerts for cron to pick up
    return alerts


# ═══ MAIN ═══

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1].lower()
    
    if cmd == 'scan':
        cmd_scan()
    elif cmd == 'trade':
        ticker = sys.argv[2] if len(sys.argv) > 2 else None
        thesis = sys.argv[3] if len(sys.argv) > 3 else None
        setup = sys.argv[4] if len(sys.argv) > 4 else SETUP_B
        second = sys.argv[5] if len(sys.argv) > 5 else None
        theme = sys.argv[6] if len(sys.argv) > 6 else None
        cmd_trade(ticker, thesis, setup, second, theme)
    elif cmd == 'monitor':
        cmd_monitor()
    elif cmd == 'close':
        ticker = sys.argv[2] if len(sys.argv) > 2 else None
        if not ticker:
            print("Usage: albert_strategy.py close TICKER [reason]")
            print("  Post-mortem wird interaktiv oder via JSON abgefragt.")
            print("  Oder: albert_strategy.py close TICKER reason --json '{...}'")
            sys.exit(1)
        reason = sys.argv[3] if len(sys.argv) > 3 else 'manual'
        
        # Check for JSON post-mortem
        pm = {}
        for i, arg in enumerate(sys.argv):
            if arg == '--json' and i + 1 < len(sys.argv):
                try:
                    pm = json.loads(sys.argv[i + 1])
                except:
                    print("⚠️ JSON parse error, continuing without post-mortem data")
        
        cmd_close(ticker, reason,
                  thesis_correct=pm.get('thesis_correct'),
                  lesson=pm.get('lesson'),
                  what_worked=pm.get('what_worked'),
                  what_failed=pm.get('what_failed'),
                  would_repeat=pm.get('would_repeat'))
    elif cmd == 'report':
        cmd_report()
    elif cmd == 'auto':
        cmd_auto()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
