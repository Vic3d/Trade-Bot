#!/usr/bin/env python3
"""
Paper Trade Manager — Autonomer Trading-Loop
=============================================
Tägliche Routine:
1. Trailing Stops updaten
2. Daily Trades schließen (max 2 Tage Haltezeit)
3. Sideways-Positionen evaluieren (>5 Tage flat)
4. Sektor-Momentum checken (Montags: volles Ranking)
5. Top-Sektoren screenen → neue Trades eröffnen
6. Performance tracken

Usage: python3 paper_trade_manager.py [--action all|stops|close_dailies|performance|rescreen]
"""

import sqlite3, json, sys, os, time
import urllib.request
from datetime import datetime, timedelta

DB_PATH = '/data/.openclaw/workspace/data/trading.db'
CONFIG_PATH = '/data/.openclaw/workspace/data/paper_config.json'
SCREENER_PATH = '/data/.openclaw/workspace/scripts/stock_screener.py'

EURUSD = 1.16
EURNOK = 11.29
EURGBP = 0.85

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def yahoo_price(ticker):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = json.loads(urllib.request.urlopen(req, timeout=8).read())
    meta = data['chart']['result'][0]['meta']
    price = meta['regularMarketPrice']
    ccy = meta.get('currency', 'USD')
    return price, ccy

def to_eur(price, ccy):
    if ccy == 'EUR': return price
    if ccy == 'USD': return price / EURUSD
    if ccy == 'NOK': return price / EURNOK
    if ccy == 'GBp': return price / (EURGBP * 100)  # GBp = pence
    if ccy == 'GBP': return price / EURGBP
    if ccy == 'DKK': return price / 7.46
    return price / EURUSD  # Fallback

# === 1. TRAILING STOPS ===

def update_trailing_stops():
    """Zieht Stops nach bei Gewinnen"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    config = load_config()
    
    rows = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN"').fetchall()
    
    print("\n🔄 TRAILING STOP CHECK")
    print("-" * 70)
    
    changes = []
    for r in rows:
        ticker = r['ticker']
        entry = r['entry_price']
        current_stop = r['stop_price']
        
        try:
            price_raw, ccy = yahoo_price(ticker)
            current_price = to_eur(price_raw, ccy)
        except:
            continue
        
        pnl_pct = (current_price - entry) / entry * 100
        
        new_stop = current_stop
        reason = ""
        
        # Trailing Stop Regeln
        if pnl_pct >= 15:
            target_stop = entry * 1.10  # Stop auf +10%
            if current_stop < target_stop:
                new_stop = target_stop
                reason = f"+{pnl_pct:.1f}% → Stop auf +10% ({target_stop:.2f}€)"
        elif pnl_pct >= 10:
            target_stop = entry * 1.05  # Stop auf +5%
            if current_stop < target_stop:
                new_stop = target_stop
                reason = f"+{pnl_pct:.1f}% → Stop auf +5% ({target_stop:.2f}€)"
        elif pnl_pct >= 5:
            target_stop = entry  # Stop auf Breakeven
            if current_stop < target_stop:
                new_stop = target_stop
                reason = f"+{pnl_pct:.1f}% → Stop auf Breakeven ({target_stop:.2f}€)"
        
        if new_stop > current_stop:
            db.execute('UPDATE paper_portfolio SET stop_price=? WHERE id=?', (new_stop, r['id']))
            changes.append((ticker, current_stop, new_stop, reason))
            print(f"  ✅ {ticker}: Stop {current_stop:.2f}€ → {new_stop:.2f}€ ({reason})")
        
        # Stop getroffen?
        if current_price <= current_stop:
            shares = r['shares']
            pnl_eur = (current_price - entry) * shares - r['fees']
            db.execute('''UPDATE paper_portfolio SET status='CLOSED', close_price=?, close_date=?, 
                pnl_eur=?, pnl_pct=?, notes=notes||' | STOP HIT bei '||? WHERE id=?''',
                (current_price, datetime.now().strftime('%Y-%m-%d %H:%M'), pnl_eur, pnl_pct, 
                 f'{current_price:.2f}€', r['id']))
            
            # Cash updaten
            cash = db.execute('SELECT value FROM paper_fund WHERE key="current_cash"').fetchone()['value']
            db.execute('UPDATE paper_fund SET value=? WHERE key="current_cash"', (cash + current_price * shares - 1,))
            realized = db.execute('SELECT value FROM paper_fund WHERE key="total_realized_pnl"').fetchone()['value']
            db.execute('UPDATE paper_fund SET value=? WHERE key="total_realized_pnl"', (realized + pnl_eur,))
            
            print(f"  🔴 {ticker}: STOP HIT @ {current_price:.2f}€ | P&L: {pnl_pct:+.1f}% ({pnl_eur:+.2f}€)")
        else:
            if not reason:
                print(f"  ⚪ {ticker}: {current_price:.2f}€ | P&L: {pnl_pct:+.1f}% | Stop {current_stop:.2f}€ ({(current_price-current_stop)/current_price*100:.1f}% weg)")
    
    db.commit()
    db.close()
    return changes

# === 2. DAILY TRADES SCHLIEßEN ===

def close_expired_dailies():
    """Schließt Momentum Trades die ihre Haltezeit überschritten haben (7 Tage)"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    rows = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN" AND strategy="PM"').fetchall()
    
    print("\n⚡ DAILY TRADE CHECK")
    print("-" * 70)
    
    now = datetime.now()
    closed = []
    
    for r in rows:
        entry_date = datetime.strptime(r['entry_date'][:10], '%Y-%m-%d')
        days_held = (now - entry_date).days
        
        if days_held >= 7:  # Momentum Swings: max 7 Tage
            try:
                price_raw, ccy = yahoo_price(r['ticker'])
                current_price = to_eur(price_raw, ccy)
            except:
                continue
            
            pnl_pct = (current_price - r['entry_price']) / r['entry_price'] * 100
            pnl_eur = (current_price - r['entry_price']) * r['shares'] - r['fees']
            
            db.execute('''UPDATE paper_portfolio SET status='CLOSED', close_price=?, close_date=?,
                pnl_eur=?, pnl_pct=?, notes=notes||' | Daily expired nach '||?||' Tagen' WHERE id=?''',
                (current_price, now.strftime('%Y-%m-%d %H:%M'), pnl_eur, pnl_pct, days_held, r['id']))
            
            cash = db.execute('SELECT value FROM paper_fund WHERE key="current_cash"').fetchone()['value']
            db.execute('UPDATE paper_fund SET value=? WHERE key="current_cash"', (cash + current_price * r['shares'] - 1,))
            realized = db.execute('SELECT value FROM paper_fund WHERE key="total_realized_pnl"').fetchone()['value']
            db.execute('UPDATE paper_fund SET value=? WHERE key="total_realized_pnl"', (realized + pnl_eur,))
            
            closed.append(r['ticker'])
            print(f"  ✅ {r['ticker']} geschlossen nach {days_held}d | P&L: {pnl_pct:+.1f}% ({pnl_eur:+.2f}€)")
        else:
            print(f"  ⏳ {r['ticker']}: Tag {days_held+1}/2")
    
    db.commit()
    db.close()
    return closed

# === 3. SIDEWAYS CHECK ===

def check_sideways():
    """Markiert Thesis-Positionen die >5 Tage seitwärts laufen"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    rows = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN" AND strategy="PT"').fetchall()
    
    print("\n📊 SIDEWAYS CHECK (>5 Tage flat)")
    print("-" * 70)
    
    now = datetime.now()
    flagged = []
    
    for r in rows:
        entry_date = datetime.strptime(r['entry_date'][:10], '%Y-%m-%d')
        days_held = (now - entry_date).days
        
        if days_held >= 5:
            try:
                price_raw, ccy = yahoo_price(r['ticker'])
                current_price = to_eur(price_raw, ccy)
            except:
                continue
            
            pnl_pct = (current_price - r['entry_price']) / r['entry_price'] * 100
            
            # "Sideways" = weniger als ±3% Bewegung nach 5+ Tagen
            if abs(pnl_pct) < 3:
                flagged.append((r['ticker'], days_held, pnl_pct))
                print(f"  ⚠️ {r['ticker']}: {days_held} Tage, nur {pnl_pct:+.1f}% → RE-EVALUATE")
            else:
                print(f"  ✅ {r['ticker']}: {days_held} Tage, {pnl_pct:+.1f}% (bewegt sich)")
        else:
            print(f"  ⏳ {r['ticker']}: Tag {days_held+1} (< 5 Tage)")
    
    db.close()
    return flagged

# === 4. PERFORMANCE TRACKING ===

def track_performance():
    """Berechnet und speichert tägliche Performance-Metriken"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Alle geschlossenen Trades
    closed = db.execute('SELECT * FROM paper_portfolio WHERE status="CLOSED"').fetchall()
    open_pos = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN"').fetchall()
    
    winners = [r for r in closed if (r['pnl_pct'] or 0) > 0]
    losers = [r for r in closed if (r['pnl_pct'] or 0) <= 0]
    
    total_trades = len(closed)
    win_rate = len(winners) / total_trades * 100 if total_trades > 0 else 0
    avg_winner = sum(r['pnl_pct'] for r in winners) / len(winners) if winners else 0
    avg_loser = sum(r['pnl_pct'] for r in losers) / len(losers) if losers else 0
    
    # Expectancy = (Win% × Avg Win) + (Loss% × Avg Loss)
    expectancy = (win_rate/100 * avg_winner) + ((1 - win_rate/100) * avg_loser)
    
    # Profit Factor = Gross Profits / Gross Losses
    gross_profit = sum(r['pnl_eur'] for r in winners if r['pnl_eur']) if winners else 0
    gross_loss = abs(sum(r['pnl_eur'] for r in losers if r['pnl_eur'])) if losers else 1
    profit_factor = gross_profit / max(gross_loss, 0.01)
    
    # Fund Value
    fund = {r['key']: r['value'] for r in db.execute('SELECT * FROM paper_fund').fetchall()}
    cash = fund.get('current_cash', 0)
    
    invested = 0
    for r in open_pos:
        try:
            price_raw, ccy = yahoo_price(r['ticker'])
            current_price = to_eur(price_raw, ccy)
            invested += current_price * r['shares']
        except:
            invested += r['entry_price'] * r['shares']
        time.sleep(0.2)
    
    total_value = cash + invested
    starting = fund.get('starting_capital', 25000)
    total_return = (total_value - starting) / starting * 100
    
    # Max Drawdown (vereinfacht: vom Startkapital)
    max_dd = min(0, total_return)
    
    # Heute geschlossene Trades
    today_closed = [r for r in closed if (r['close_date'] or '').startswith(today)]
    
    print("\n📈 PERFORMANCE REPORT")
    print("=" * 70)
    print(f"  Portfolio-Wert: {total_value:.0f}€ (Start: {starting:.0f}€)")
    print(f"  Return: {total_return:+.1f}%")
    print(f"  Cash: {cash:.0f}€ | Investiert: {invested:.0f}€")
    print(f"  Offene Positionen: {len(open_pos)}")
    print(f"\n  Trades gesamt: {total_trades} geschlossen")
    print(f"  Win Rate: {win_rate:.0f}% ({len(winners)}W / {len(losers)}L)")
    print(f"  Avg Winner: {avg_winner:+.1f}%")
    print(f"  Avg Loser: {avg_loser:+.1f}%")
    print(f"  Expectancy: {expectancy:+.2f}% pro Trade")
    print(f"  Profit Factor: {profit_factor:.2f}x")
    print(f"  Realisiert: {fund.get('total_realized_pnl', 0):+.2f}€")
    
    # In DB speichern
    db.execute('''INSERT OR REPLACE INTO paper_performance 
        (date, total_value, cash, invested, open_positions, trades_today,
         wins_today, losses_today, realized_pnl_today, cumulative_pnl,
         win_rate_all, avg_winner, avg_loser, expectancy, profit_factor, max_drawdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (today, total_value, cash, invested, len(open_pos), len(today_closed),
         len([r for r in today_closed if (r['pnl_pct'] or 0) > 0]),
         len([r for r in today_closed if (r['pnl_pct'] or 0) <= 0]),
         sum(r['pnl_eur'] or 0 for r in today_closed),
         fund.get('total_realized_pnl', 0),
         win_rate, avg_winner, avg_loser, expectancy, profit_factor, max_dd))
    
    db.commit()
    db.close()
    
    return {
        'total_value': total_value,
        'return_pct': total_return,
        'win_rate': win_rate,
        'expectancy': expectancy,
        'profit_factor': profit_factor,
    }

# === 5. EARNINGS BLACKOUT CHECK ===

def check_earnings_blackout(ticker):
    """Prüft ob Earnings in den nächsten 3 Tagen anstehen"""
    try:
        url = f'https://finnhub.io/api/v1/calendar/earnings?symbol={ticker}&from={datetime.now().strftime("%Y-%m-%d")}&to={(datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")}'
        
        finnhub_key = None
        for line in open('/data/.openclaw/workspace/.env'):
            if line.startswith('FINNHUB_KEY='):
                finnhub_key = line.strip().split('=', 1)[1]
        
        if finnhub_key:
            url += f'&token={finnhub_key}'
            data = json.loads(urllib.request.urlopen(url, timeout=8).read())
            earnings = data.get('earningsCalendar', [])
            return len(earnings) > 0
    except:
        pass
    return False

# === MAIN ===

def run_all():
    print(f"\n{'='*70}")
    print(f"  🤖 PAPER TRADE MANAGER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")
    
    update_trailing_stops()
    close_expired_dailies()
    check_sideways()
    track_performance()

if __name__ == '__main__':
    action = 'all'
    if len(sys.argv) > 1:
        for i, a in enumerate(sys.argv):
            if a == '--action' and i+1 < len(sys.argv):
                action = sys.argv[i+1]
    
    if action == 'all':
        run_all()
    elif action == 'stops':
        update_trailing_stops()
    elif action == 'close_dailies':
        close_expired_dailies()
    elif action == 'performance':
        track_performance()
    elif action == 'rescreen':
        check_sideways()
    else:
        print(f"Unknown action: {action}")
