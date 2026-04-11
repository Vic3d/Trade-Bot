#!/usr/bin/env python3.14
"""
watchlist_tracker.py — Preis-Snapshots für alle Watchlist-Ticker
=================================================================
Läuft alle 30 Minuten während Marktzeiten.
Speichert für jeden Ticker: Kurs, RSI, MA20/50/200, Volumen, ATR.
Prüft pending_setups auf ausgelöste Trigger.

Start: python3.14 watchlist_tracker.py
"""

import sqlite3
import sys
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
CONFIG = WS / 'trading_config.json'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts/core'))


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_all_tracked_tickers() -> list:
    """Alle Ticker: Scanner-Universe + offene Positionen + Watchlist aus Config."""
    tickers = set()

    # Scanner-Universe aus DB
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT ticker FROM paper_portfolio WHERE status='OPEN'").fetchall()
    for r in rows:
        tickers.add(r['ticker'])

    # Pending Setups
    rows = conn.execute("SELECT DISTINCT ticker FROM pending_setups WHERE status='WATCHING'").fetchall()
    for r in rows:
        tickers.add(r['ticker'])
    conn.close()

    # Config-Watchlist
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text())
            for w in cfg.get('watchlist', []):
                t = w.get('yahoo') or w.get('ticker')
                if t:
                    tickers.add(t)
            # Scanner Universe
            for w in cfg.get('scanner_universe', []):
                t = w.get('ticker')
                if t:
                    tickers.add(t)
        except Exception:
            pass

    # Fallback: bekannte Ticker
    defaults = [
        'PLTR', 'NVDA', 'MSFT', 'EQNR.OL', 'RIO.L', 'BAYN.DE',
        'RHM.DE', 'FCX', 'SCCO', 'FXI', 'BABA', 'AMAT', 'MU',
        'OXY', 'TTE.PA', 'DHT', 'ZIM', 'WPM', 'AG',
    ]
    for t in defaults:
        tickers.add(t)

    return list(tickers)


def compute_indicators(ticker: str, prices: list) -> dict:
    """Berechnet RSI, MA20/50/200, ATR, Trend aus historischen Preisen."""
    closes = [p['close'] for p in prices if p.get('close')]
    volumes = [p.get('volume', 0) for p in prices]

    if len(closes) < 5:
        return {}

    result = {}

    # MA20, MA50, MA200
    if len(closes) >= 20:
        result['ma20'] = round(sum(closes[-20:]) / 20, 4)
    if len(closes) >= 50:
        result['ma50'] = round(sum(closes[-50:]) / 50, 4)
    if len(closes) >= 200:
        result['ma200'] = round(sum(closes[-200:]) / 200, 4)

    # RSI (14)
    if len(closes) >= 15:
        gains, losses = [], []
        for i in range(1, 15):
            diff = closes[-15+i] - closes[-15+i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            result['rsi'] = 100.0
        else:
            rs = avg_gain / avg_loss
            result['rsi'] = round(100 - 100 / (1 + rs), 1)

    # ATR (14)
    if len(prices) >= 15:
        trs = []
        for i in range(-14, 0):
            h = prices[i].get('high', closes[i])
            l = prices[i].get('low', closes[i])
            prev_c = closes[i-1] if i > -len(closes) else closes[i]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        result['atr'] = round(sum(trs) / 14, 4)

    # Trend (% Änderung)
    if len(closes) >= 6:
        result['trend_5d'] = round((closes[-1] / closes[-6] - 1) * 100, 2)
    if len(closes) >= 21:
        result['trend_20d'] = round((closes[-1] / closes[-21] - 1) * 100, 2)

    # Volume Ratio (aktuell vs. 20-Tage Durchschnitt)
    if len(volumes) >= 20 and volumes[-1]:
        avg_vol = sum(volumes[-20:]) / 20
        if avg_vol > 0:
            result['volume_ratio'] = round(volumes[-1] / avg_vol, 2)

    return result


def save_snapshot(ticker: str, price_eur: float, indicators: dict):
    """Speichert Preis-Snapshot in watchlist_prices."""
    conn = get_db()
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')
    try:
        conn.execute('''
            INSERT OR REPLACE INTO watchlist_prices
                (ticker, timestamp, price_eur, rsi, ma20, ma50, ma200,
                 volume_ratio, atr, trend_5d, trend_20d)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ticker, ts, price_eur,
            indicators.get('rsi'), indicators.get('ma20'), indicators.get('ma50'),
            indicators.get('ma200'), indicators.get('volume_ratio'), indicators.get('atr'),
            indicators.get('trend_5d'), indicators.get('trend_20d'),
        ))
        conn.commit()
    except Exception as e:
        print(f"[{ticker}] Snapshot-Fehler: {e}")
    conn.close()


def check_triggers(current_prices: dict):
    """Prüft ob pending_setups ihren Entry-Trigger erreicht haben."""
    conn = get_db()
    setups = conn.execute(
        "SELECT * FROM pending_setups WHERE status='WATCHING'"
    ).fetchall()
    conn.close()

    triggered = []
    for s in setups:
        ticker = s['ticker']
        price = current_prices.get(ticker)
        if not price:
            continue

        trigger = s['entry_trigger']
        ttype = s['trigger_type'] or 'ABOVE'

        hit = False
        if ttype == 'ABOVE' and price >= trigger:
            hit = True
        elif ttype == 'BELOW' and price <= trigger:
            hit = True

        if hit:
            conn = get_db()
            conn.execute(
                "UPDATE pending_setups SET status='TRIGGERED', updated_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), s['id'])
            )
            conn.commit()
            conn.close()
            triggered.append({
                'id': s['id'],
                'ticker': ticker,
                'strategy': s['strategy'],
                'conviction': s['conviction'],
                'price': price,
                'trigger': trigger,
                'stop': s['stop_suggestion'],
                'target': s['target_suggestion'],
            })

    return triggered


def send_trigger_alerts(triggered: list):
    """Discord-Alerts für ausgelöste Trigger."""
    if not triggered:
        return
    try:
        from discord_sender import send
        for t in triggered:
            crv = ''
            if t.get('stop') and t.get('target') and t['stop'] < t['price']:
                risk = t['price'] - t['stop']
                reward = t['target'] - t['price']
                if risk > 0:
                    crv = f" | CRV {reward/risk:.1f}:1"
            send(
                f"🎯 **Entry-Trigger ausgelöst** — {t['ticker']} ({t['strategy']})\n"
                f"Kurs: {t['price']:.2f}€ | Trigger: {t['trigger']:.2f}€\n"
                f"Conviction: {t['conviction']} | Stop: {t.get('stop','?')}€{crv}\n"
                f"→ Scanner öffnet Position automatisch"
            )
    except Exception as e:
        print(f"[Alert] {e}")


def run_snapshot():
    """Haupt-Funktion: Snapshot für alle Ticker."""
    from live_data import get_price_eur
    from market_hours import is_any_trading_day

    # Wochenende — einfacher Check
    today = datetime.now()
    if today.weekday() >= 5:  # Sa=5, So=6
        print("Wochenende — kein Snapshot")
        return

    tickers = get_all_tracked_tickers()
    print(f"[WatchlistTracker] {len(tickers)} Ticker | {datetime.now().strftime('%H:%M:%S')}")

    # Preisdaten aus DB holen (für Indikatoren)
    conn = get_db()
    current_prices = {}
    updated = 0

    import time as _time
    for ticker in sorted(tickers):
        # Aktuelle Preis aus live_data
        price = get_price_eur(ticker)
        if not price:
            continue

        current_prices[ticker] = price

        # Historische Preise aus DB für Indikatoren
        rows = conn.execute('''
            SELECT date, open, high, low, close, volume
            FROM prices WHERE ticker=?
            ORDER BY date DESC LIMIT 250
        ''', (ticker,)).fetchall()

        prices_hist = [dict(r) for r in reversed(rows)]
        indicators = compute_indicators(ticker, prices_hist)
        save_snapshot(ticker, price, indicators)
        updated += 1

    conn.close()

    # Trigger prüfen
    triggered = check_triggers(current_prices)
    if triggered:
        send_trigger_alerts(triggered)
        print(f"⚡ {len(triggered)} Trigger ausgelöst: {[t['ticker'] for t in triggered]}")

    print(f"✅ {updated} Snapshots gespeichert")
    return updated, triggered


if __name__ == '__main__':
    run_snapshot()
