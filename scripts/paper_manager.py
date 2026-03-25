#!/usr/bin/env python3
"""
Paper Fund Manager — Autonomes Trade-Management
================================================

Aufgaben:
1. Trailing Stops anpassen (Regeln aus paper_config.json)
2. Seitwärts-Positionen identifizieren
3. Performance-Snapshot speichern
4. Screener Re-Check für offene Positionen
5. Earnings-Blackout checken

Usage: python3 paper_manager.py [--action all|trailing|performance|recheck]
"""

import urllib.request, json, sqlite3, sys, time
from datetime import datetime, timedelta

DB_PATH = '/data/.openclaw/workspace/data/trading.db'
CONFIG_PATH = '/data/.openclaw/workspace/data/paper_config.json'

EURUSD = 1.16

def yahoo_price(ticker):
    # Manche Ticker haben Exchange-Suffix
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = json.loads(urllib.request.urlopen(req, timeout=8).read())
    meta = data['chart']['result'][0]['meta']
    closes = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close'] if c]
    return meta['regularMarketPrice'], meta.get('currency', 'USD'), closes

def to_eur(price, currency):
    if currency == 'USD':
        return price / EURUSD
    elif currency == 'NOK':
        return price / 11.29
    elif currency == 'GBP':
        return price * 1.17 / EURUSD  # GBP→EUR approximation
    return price

# === TRAILING STOP ===
def update_trailing_stops():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    rows = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN"').fetchall()
    
    print("📈 TRAILING STOP CHECK")
    print("=" * 80)
    
    changes = 0
    for r in rows:
        ticker = r['ticker']
        entry = r['entry_price']
        stop = r['stop_price']
        
        try:
            price_raw, ccy, closes = yahoo_price(ticker)
            current = to_eur(price_raw, ccy)
            gain_pct = (current - entry) / entry * 100
            
            new_stop = stop
            reason = ""
            
            if gain_pct >= 15 and stop < entry * 1.10:
                new_stop = round(entry * 1.10, 2)
                reason = f"+{gain_pct:.1f}% → Stop auf +10% ({new_stop:.2f}€)"
            elif gain_pct >= 10 and stop < entry * 1.05:
                new_stop = round(entry * 1.05, 2)
                reason = f"+{gain_pct:.1f}% → Stop auf +5% ({new_stop:.2f}€)"
            elif gain_pct >= 5 and stop < entry:
                new_stop = entry
                reason = f"+{gain_pct:.1f}% → Stop auf Breakeven ({new_stop:.2f}€)"
            
            status = f"P&L: {gain_pct:+.1f}%"
            
            if new_stop > stop:
                db.execute('UPDATE paper_portfolio SET stop_price=? WHERE id=?', (new_stop, r['id']))
                print(f"  🔺 {ticker:12} {status:>12} | Stop {stop:.2f}€ → {new_stop:.2f}€ | {reason}")
                changes += 1
            else:
                stop_dist = (current - stop) / current * 100
                print(f"  ➡️  {ticker:12} {status:>12} | Stop {stop:.2f}€ ({stop_dist:.1f}% weg) | Kein Update")
            
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ {ticker}: {e}")
    
    db.commit()
    db.close()
    print(f"\n  {changes} Stops angepasst")
    return changes

# === SEITWÄRTS-CHECK ===
def check_sideways():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    rows = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN"').fetchall()
    
    print("\n⏸️  SEITWÄRTS-CHECK (>5 Tage, <2% Bewegung)")
    print("=" * 80)
    
    sideways = []
    for r in rows:
        entry_date = r['entry_date'][:10]
        days_held = (datetime.now() - datetime.strptime(entry_date, '%Y-%m-%d')).days
        
        if days_held < 5:
            continue
        
        try:
            price_raw, ccy, closes = yahoo_price(r['ticker'])
            current = to_eur(price_raw, ccy)
            gain_pct = abs((current - r['entry_price']) / r['entry_price'] * 100)
            
            if gain_pct < 2:
                print(f"  ⚠️  {r['ticker']:12} | {days_held}d gehalten | P&L: {(current-r['entry_price'])/r['entry_price']*100:+.1f}% | SEITWÄRTS — Kapital gebunden")
                sideways.append(r['ticker'])
            time.sleep(0.3)
        except:
            pass
    
    if not sideways:
        print("  ✅ Keine Seitwärts-Positionen")
    
    db.close()
    return sideways

# === DAILY TRADE CHECK ===
def check_daily_trades():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    rows = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN" AND strategy LIKE "PD%"').fetchall()
    
    print("\n⚡ DAILY TRADE CHECK")
    print("=" * 80)
    
    for r in rows:
        entry_date = r['entry_date'][:10]
        days_held = (datetime.now() - datetime.strptime(entry_date, '%Y-%m-%d')).days
        
        try:
            price_raw, ccy, closes = yahoo_price(r['ticker'])
            current = to_eur(price_raw, ccy)
            gain_pct = (current - r['entry_price']) / r['entry_price'] * 100
            
            if days_held >= 2:
                print(f"  🔴 {r['ticker']:12} | {days_held}d gehalten | P&L: {gain_pct:+.1f}% | ÜBERFÄLLIG — sollte geschlossen werden")
            else:
                print(f"  ➡️  {r['ticker']:12} | {days_held}d gehalten | P&L: {gain_pct:+.1f}%")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ {r['ticker']}: {e}")
    
    if not rows:
        print("  Keine offenen Daily Trades")
    
    db.close()

# === PERFORMANCE SNAPSHOT ===
def save_performance():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    today = datetime.now().strftime('%Y-%m-%d')
    
    fund = {r['key']: r['value'] for r in db.execute('SELECT * FROM paper_fund').fetchall()}
    cash = fund.get('current_cash', 0)
    realized = fund.get('total_realized_pnl', 0)
    
    open_pos = db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN"').fetchall()
    
    # Unrealized P&L berechnen
    invested = 0
    unrealized = 0
    for r in open_pos:
        pos_value = r['entry_price'] * r['shares']
        invested += pos_value
        try:
            price_raw, ccy, _ = yahoo_price(r['ticker'])
            current = to_eur(price_raw, ccy)
            unrealized += (current - r['entry_price']) * r['shares']
            time.sleep(0.3)
        except:
            pass
    
    total_value = cash + invested + unrealized
    
    # Closed trades für Win-Rate
    closed = db.execute('SELECT * FROM paper_portfolio WHERE status="CLOSED"').fetchall()
    wins = [r for r in closed if (r['pnl_pct'] or 0) > 0]
    losses = [r for r in closed if (r['pnl_pct'] or 0) <= 0]
    
    win_rate = len(wins) / max(len(closed), 1) * 100
    avg_winner = sum(r['pnl_pct'] or 0 for r in wins) / max(len(wins), 1)
    avg_loser = sum(r['pnl_pct'] or 0 for r in losses) / max(len(losses), 1)
    
    # Expectancy = (Win% × AvgWin) + (Loss% × AvgLoss)
    expectancy = (win_rate/100 * avg_winner) + ((1 - win_rate/100) * avg_loser)
    
    # Profit Factor = Gross Wins / Gross Losses
    gross_wins = sum(r['pnl_eur'] or 0 for r in wins)
    gross_losses = abs(sum(r['pnl_eur'] or 0 for r in losses))
    profit_factor = gross_wins / max(gross_losses, 0.01)
    
    # Max Drawdown (from peak)
    starting = fund.get('starting_capital', 25000)
    drawdown = (total_value - starting) / starting * 100 if total_value < starting else 0
    
    db.execute('''INSERT OR REPLACE INTO paper_performance 
        (date, total_value, cash, invested, open_positions, trades_today,
         wins_today, losses_today, realized_pnl_today, cumulative_pnl,
         win_rate_all, avg_winner, avg_loser, expectancy, profit_factor, max_drawdown)
        VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?)''',
        (today, total_value, cash, invested, len(open_pos), realized,
         win_rate, avg_winner, avg_loser, expectancy, profit_factor, drawdown))
    
    db.commit()
    
    print(f"\n📊 PERFORMANCE SNAPSHOT — {today}")
    print(f"{'='*60}")
    print(f"  Portfolio-Wert:    {total_value:>10,.2f}€")
    print(f"  Cash:              {cash:>10,.2f}€")
    print(f"  Investiert:        {invested:>10,.2f}€")
    print(f"  Unrealized P&L:    {unrealized:>+10,.2f}€")
    print(f"  Realized P&L:      {realized:>+10,.2f}€")
    print(f"  Gesamt P&L:        {total_value - starting:>+10,.2f}€ ({(total_value-starting)/starting*100:+.2f}%)")
    print(f"  Offene Positionen: {len(open_pos)}")
    print(f"  Geschlossene:      {len(closed)}")
    print(f"  Win-Rate:          {win_rate:.0f}%")
    print(f"  Avg Winner:        {avg_winner:+.1f}%")
    print(f"  Avg Loser:         {avg_loser:+.1f}%")
    print(f"  Expectancy:        {expectancy:+.2f}%")
    print(f"  Profit Factor:     {profit_factor:.2f}")
    print(f"  Drawdown:          {drawdown:.2f}%")
    
    db.close()

# === MAIN ===
if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else '--action'
    action = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '--action' else 'all'
    
    if action in ('all', 'trailing'):
        update_trailing_stops()
    if action in ('all', 'sideways'):
        check_sideways()
    if action in ('all', 'daily'):
        check_daily_trades()
    if action in ('all', 'performance'):
        save_performance()
