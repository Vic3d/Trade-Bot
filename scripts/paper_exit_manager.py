#!/usr/bin/env python3
"""
Paper Exit Manager — Verbesserung 1: Time-based Exits + saubere Exit-Typen
=========================================================================
Läuft im Albert's Fund Cron + täglich 22:00 eigenständig.
Schließt Positionen nach Regeln: Stop / Target / Zeit / Thesis-Invalid
"""
import sqlite3, json, urllib.request
from pathlib import Path
from datetime import datetime, date, timedelta

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'

MAX_HOLD_DAYS_SWING   = 10   # Swing: nach 10 Tagen ohne +5% → Exit
MIN_MOVE_FOR_HOLD     = 0.05 # Muss mindestens +5% gelaufen sein um zu bleiben
TRAILING_TRIGGER      = 0.05 # Bei +5% Stop auf Breakeven ziehen

def yahoo(ticker):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        return d['chart']['result'][0]['meta'].get('regularMarketPrice')
    except:
        return None

def get_eurusd():
    return yahoo('EURUSD=X') or 1.15

def close_position(db, row_id, close_price, exit_type, entry_price, shares, fees):
    pnl = (close_price - entry_price) * shares - fees
    pnl_pct = (close_price - entry_price) / entry_price * 100
    db.execute("""
        UPDATE paper_portfolio
        SET status=?, close_price=?, close_date=datetime('now'),
            pnl_eur=?, pnl_pct=?, notes = notes || ?
        WHERE id=?
    """, (
        'WIN' if pnl > 0 else 'CLOSED',
        round(close_price, 2),
        round(pnl, 2),
        round(pnl_pct, 2),
        f' [EXIT:{exit_type} {date.today().isoformat()}]',
        row_id
    ))
    db.commit()
    return pnl

def run():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    eurusd = get_eurusd()

    open_trades = db.execute("""
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               shares, fees, entry_date, notes, style
        FROM paper_portfolio WHERE status='OPEN'
    """).fetchall()

    closed = []
    trailing_updates = []

    for t in open_trades:
        price_raw = yahoo(t['ticker'])
        if not price_raw:
            continue

        # EUR-Konvertierung
        price = price_raw / eurusd if not any(t['ticker'].endswith(s) for s in ['.DE','.PA','.AS','.L','.OL','.CO']) else price_raw
        entry = t['entry_price']
        stop  = t['stop_price'] or (entry * 0.93)
        target = t['target_price'] or (entry * 1.15)
        shares = t['shares'] or 1
        fees   = t['fees'] or 1.0
        
        # Haltezeit
        try:
            entry_dt = datetime.fromisoformat(str(t['entry_date'])[:19])
            hold_days = (datetime.now() - entry_dt).days
        except:
            hold_days = 0

        move_pct = (price - entry) / entry

        # 1. STOP getroffen
        if price <= stop:
            pnl = close_position(db, t['id'], price, 'STOP', entry, shares, fees)
            closed.append(f"🔴 STOP  {t['ticker']:8} | {entry:.2f}→{price:.2f}€ | P&L: {pnl:+.2f}€")
            continue

        # 2. TARGET getroffen
        if price >= target:
            pnl = close_position(db, t['id'], price, 'TARGET', entry, shares, fees)
            closed.append(f"🟢 TARGET {t['ticker']:8} | {entry:.2f}→{price:.2f}€ | P&L: {pnl:+.2f}€")
            continue

        # 3. TIME EXIT: zu lange seitwärts
        if hold_days >= MAX_HOLD_DAYS_SWING and move_pct < MIN_MOVE_FOR_HOLD:
            pnl = close_position(db, t['id'], price, f'TIME_{hold_days}d', entry, shares, fees)
            closed.append(f"⏰ TIME  {t['ticker']:8} | {hold_days}d | {move_pct:+.1%} | P&L: {pnl:+.2f}€")
            continue

        # 4. TRAILING STOP: +5% → Stop auf Breakeven
        if move_pct >= TRAILING_TRIGGER and stop < entry:
            new_stop = round(entry * 1.005, 2)  # Breakeven + 0.5% Puffer
            db.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (new_stop, t['id']))
            db.commit()
            trailing_updates.append(f"🔄 TRAIL {t['ticker']:8} | Stop: {stop:.2f}→{new_stop:.2f}€ (+{move_pct:.1%})")

    if closed or trailing_updates:
        print(f"Exit Manager: {len(closed)} geschlossen, {len(trailing_updates)} Trailing-Updates")
        for c in closed: print(f"  {c}")
        for u in trailing_updates: print(f"  {u}")
    else:
        print("Exit Manager: Keine Aktionen")

    open_now = db.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
    print(f"Offene Positionen: {open_now}")
    return closed, trailing_updates

if __name__ == '__main__':
    run()
