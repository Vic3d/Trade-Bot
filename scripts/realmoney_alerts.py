#!/usr/bin/env python3.14
"""
realmoney_alerts.py — Real-Money Alert System
===============================================
Wenn Albert ein Signal mit hoher Conviction findet:
  1. Strukturierten Alert nach Discord senden
  2. Victor bestätigt per Reaction (✅ = kaufen, ❌ = skip)
  3. Eintrag in realmoney_log.md für manuelle TR-Eingabe

Kein direkter Trade Republic API — halbautomatisch.
Victor gibt den Order selbst ein, Albert trackt ihn.
"""
import sqlite3, json, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
LOG = WS / 'memory/realmoney_log.md'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts/core'))


def send_realmoney_alert(ticker: str, strategy: str, entry: float,
                          stop: float, target: float, conviction: int,
                          reasoning: str, style: str = 'swing'):
    """
    Sendet strukturierten Real-Money Alert.
    Victor muss manuell in Trade Republic eingeben.
    """
    crv = round(abs(target - entry) / abs(entry - stop), 1) if entry != stop else 0
    risk_eur = round(abs(entry - stop) * (1000 / entry), 0)  # ca. 1000€ Position
    
    msg = (
        f"🔔 **REAL MONEY SIGNAL** — {ticker}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Strategie: {strategy} | Style: {style.upper()}\n"
        f"💰 Entry:  **{entry:.2f}€**\n"
        f"🛑 Stop:   **{stop:.2f}€** (−{abs(entry-stop)/entry*100:.1f}%)\n"
        f"🎯 Ziel:   **{target:.2f}€** (+{abs(target-entry)/entry*100:.1f}%)\n"
        f"📐 CRV:    {crv}:1 | Risiko ca. {risk_eur:.0f}€\n"
        f"🧠 Conviction: {conviction}/100\n"
        f"\n{reasoning}\n"
        f"\n**👉 Aktion in Trade Republic:**\n"
        f"1. {ticker} suchen\n"
        f"2. Market Order: Entry ~{entry:.2f}€\n"
        f"3. Stop-Loss sofort setzen: {stop:.2f}€\n"
        f"{'4. Zwangsschluss heute 21:45 — Day Trade!' if style == 'day' else f'4. Ziel: {target:.2f}€'}\n"
        f"\nReact ✅ wenn ausgeführt | ❌ wenn skip"
    )
    
    try:
        from discord_sender import send
        send(msg)
    except Exception as e:
        print(f"Discord send failed: {e}")
    
    # In Log schreiben
    _log_signal(ticker, strategy, entry, stop, target, conviction, reasoning, style)
    return msg


def _log_signal(ticker, strategy, entry, stop, target, conviction, reasoning, style):
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    entry_text = (
        f"\n## {today} — {ticker} ({strategy})\n"
        f"**Status:** ⏳ Pending Victor\n"
        f"**Entry:** {entry:.2f}€ | **Stop:** {stop:.2f}€ | **Ziel:** {target:.2f}€\n"
        f"**Style:** {style} | **Conviction:** {conviction}/100\n"
        f"**Reasoning:** {reasoning}\n"
        f"**Ausgeführt:** [ ] Ja / [ ] Nein — Victor bestätigt\n"
    )
    
    with open(str(LOG), 'a') as f:
        f.write(entry_text)


def mark_executed(ticker: str, actual_entry: float, user_id: str = 'user_victor'):
    """Victor hat den Trade ausgeführt — in real portfolio loggen."""
    conn = sqlite3.connect(str(DB))
    conn.execute('''
        INSERT OR IGNORE INTO realmoney_trades
        (ticker, actual_entry, logged_at, user_id, status)
        VALUES (?, ?, ?, ?, 'OPEN')
    ''', (ticker, actual_entry, datetime.now(timezone.utc).isoformat(), user_id))
    
    # Schema sicherstellen
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS realmoney_trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT,
                actual_entry REAL,
                stop_price   REAL,
                target_price REAL,
                logged_at    TEXT,
                user_id      TEXT DEFAULT 'user_victor',
                status       TEXT DEFAULT 'OPEN',
                pnl_eur      REAL,
                notes        TEXT
            )
        ''')
    except Exception:
        pass
    conn.commit()
    conn.close()
    print(f"✅ {ticker} als Real-Money Trade geloggt @ {actual_entry}€")


if __name__ == '__main__':
    # Test-Alert
    send_realmoney_alert(
        ticker='EQNR.OL', strategy='PS1',
        entry=35.50, stop=33.50, target=40.00,
        conviction=72,
        reasoning='**Warum EQNR.OL?** Starke News-Unterstützung für Öl & Iran-These. Iran-Spannungen treiben Nordsee-Öl-Premium.',
        style='swing'
    )
    print("Test-Alert gesendet")
