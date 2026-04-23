#!/usr/bin/env python3.13
"""
price_monitor.py — Echtzeit-Preisüberwachung für offene Positionen
===================================================================
Läuft dauerhaft im Hintergrund. Prüft alle 60 Sekunden:
  - Stop-Loss getroffen?
  - Target erreicht?
  - VIX-Spike (+10% gegenüber letztem Check)?
  - Trailing Stop fällig (+5% Gewinn)?

Sendet sofort Discord-Alert bei Treffern.
Nur während Marktzeiten aktiv. Nachts/Wochenende: schläft 5 Min.

Start: python3.13 price_monitor.py
Daemon: wird von scheduler_daemon.py gestartet (background thread)
"""

import sqlite3
import time
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Sub-8 fix 2026-04-23: harter Pfad /data/.openclaw/ war Crash-Ursache (FileNotFoundError beim PID-Schreiben).
WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
if not WS.exists():
    WS = Path(__file__).resolve().parent.parent
DB = WS / 'data/trading.db'
PID_FILE = WS / 'data/price_monitor.pid'

sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts/core'))

# ── Konfiguration ─────────────────────────────────────────────────────────────
POLL_INTERVAL_MARKET   = 60    # Sekunden zwischen Checks (Marktzeiten)
POLL_INTERVAL_OFFHOURS = 300   # Sekunden zwischen Checks (außerhalb)
VIX_SPIKE_THRESHOLD    = 0.10  # 10% VIX-Änderung = Alert
TRAILING_TRIGGER_PCT   = 0.05  # 5% Gewinn = Trailing Stop vorschlagen


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def is_market_hours() -> bool:
    """True zwischen 08:00–22:00 CET Mo-Fr."""
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo('Europe/Berlin'))
        if now.weekday() >= 5:  # Sa=5, So=6
            return False
        return 8 <= now.hour < 22
    except Exception:
        return True  # Fallback: immer aktiv


def send_alert(msg: str):
    """Discord-Alert via Dispatcher (Phase 22.4 Priority-Tiering).
    Auto-Tier nach Keyword:
      HIGH   — STOP getroffen, TARGET erreicht, Entry-Trigger, VIX-Spike
      MEDIUM — Trailing Stop Anpassung
      LOW    — Stop sehr nah (Frühwarnung)
    """
    try:
        from discord_dispatcher import send_alert as _dispatch, TIER_HIGH, TIER_MEDIUM, TIER_LOW
        m = msg.upper()
        if any(k in m for k in ('STOP GETROFFEN', 'TARGET ERREICHT',
                                 'ENTRY-TRIGGER', 'VIX-SPIKE', '🔴', '🟢', '🎯', '⚡')):
            tier = TIER_HIGH
        elif 'TRAILING' in m or '🔄' in m:
            tier = TIER_MEDIUM
        else:
            tier = TIER_LOW
        _dispatch(msg, tier=tier, category='trade')
    except Exception as e:
        print(f"[ALERT FAIL] {e}: {msg[:80]}")


def get_open_positions() -> list:
    conn = get_db()
    rows = conn.execute('''
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               shares, style, conviction
        FROM paper_portfolio WHERE status='OPEN'
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_position_db(trade_id: int, price: float, exit_type: str,
                      entry: float, shares: float, fees: float = 1.0):
    """Schließt Position in DB — parallel zum Exit Manager."""
    conn = get_db()
    pnl = (price - entry) * shares - fees
    pnl_pct = (price - entry) / entry * 100
    now = datetime.now(timezone.utc).isoformat()
    conn.execute('''
        UPDATE paper_portfolio SET
            status='CLOSED', close_price=?, close_date=?,
            pnl_eur=?, pnl_pct=?, exit_type=?
        WHERE id=? AND status='OPEN'
    ''', (price, now, round(pnl, 2), round(pnl_pct, 2), exit_type, trade_id))
    conn.commit()
    conn.close()
    return round(pnl, 2)


def update_stop(trade_id: int, new_stop: float):
    conn = get_db()
    conn.execute(
        'UPDATE paper_portfolio SET stop_price=? WHERE id=?', (new_stop, trade_id)
    )
    conn.commit()
    conn.close()


def run_monitor():
    """Hauptschleife — läuft endlos."""
    print(f"[PriceMonitor] Gestartet (PID {os.getpid()})")
    PID_FILE.write_text(str(os.getpid()))

    last_vix = None
    alerted_ids = set()  # Trade-IDs für die bereits ein Alert gesendet wurde
    check_count = 0

    while True:
        try:
            market_open = is_market_hours()
            interval = POLL_INTERVAL_MARKET if market_open else POLL_INTERVAL_OFFHOURS

            if not market_open:
                time.sleep(interval)
                continue

            check_count += 1

            # ── Live-Preise holen ───────────────────────────────────────
            from live_data import get_price_eur, get_vix

            positions = get_open_positions()
            if not positions:
                time.sleep(interval)
                continue

            # ── VIX-Spike Check ─────────────────────────────────────────
            vix = get_vix()
            if vix and last_vix:
                vix_change = abs(vix - last_vix) / last_vix
                if vix_change >= VIX_SPIKE_THRESHOLD:
                    direction = "📈 GESTIEGEN" if vix > last_vix else "📉 GEFALLEN"
                    send_alert(
                        f"⚡ **VIX-Spike!** {last_vix:.1f} → {vix:.1f} "
                        f"({vix_change*100:.0f}% {direction})\n"
                        f"Alle Stops überprüfen — Volatilität erhöht!"
                    )
            if vix:
                last_vix = vix

            # ── Stop/Target Check für jede Position ─────────────────────
            for pos in positions:
                tid     = pos['id']
                ticker  = pos['ticker']
                entry   = pos['entry_price']
                stop    = pos['stop_price']
                target  = pos['target_price']
                shares  = pos['shares'] or 1
                strat   = pos['strategy']

                price = get_price_eur(ticker)
                if not price:
                    continue

                move_pct = (price - entry) / entry * 100

                # STOP getroffen
                if stop and price <= stop:
                    if tid not in alerted_ids:
                        pnl = close_position_db(tid, price, 'STOP_MONITOR', entry, shares)
                        send_alert(
                            f"🔴 **STOP getroffen** — {ticker} ({strat})\n"
                            f"Kurs: {price:.2f}€ | Stop: {stop:.2f}€\n"
                            f"P&L: {pnl:+.2f}€ | Entry: {entry:.2f}€\n"
                            f"→ Position automatisch geschlossen"
                        )
                        alerted_ids.add(tid)
                        continue

                # TARGET erreicht
                if target and price >= target:
                    if tid not in alerted_ids:
                        pnl = close_position_db(tid, price, 'TARGET_MONITOR', entry, shares)
                        send_alert(
                            f"🟢 **TARGET erreicht** — {ticker} ({strat})\n"
                            f"Kurs: {price:.2f}€ | Ziel: {target:.2f}€\n"
                            f"P&L: {pnl:+.2f}€ (+{move_pct:.1f}%)\n"
                            f"→ Position automatisch geschlossen 🎯"
                        )
                        alerted_ids.add(tid)
                        continue

                # TRAILING STOP vorschlagen
                if move_pct >= TRAILING_TRIGGER_PCT * 100 and stop and stop < entry:
                    new_stop = round(entry * 1.005, 2)  # Breakeven + 0.5%
                    if new_stop > stop:
                        update_stop(tid, new_stop)
                        if f"trail_{tid}" not in alerted_ids:
                            send_alert(
                                f"🔄 **Trailing Stop** — {ticker}\n"
                                f"Kurs +{move_pct:.1f}% | Stop: {stop:.2f}€ → {new_stop:.2f}€\n"
                                f"Breakeven gesichert ✅"
                            )
                            alerted_ids.add(f"trail_{tid}")

                # STOP SEHR NAH (<1.5% entfernt)
                if stop and price > stop:
                    dist_pct = (price - stop) / price * 100
                    if dist_pct < 1.5:
                        alert_key = f"near_{tid}_{int(dist_pct*10)}"
                        if alert_key not in alerted_ids:
                            send_alert(
                                f"⚠️ **Stop sehr nah** — {ticker}\n"
                                f"Kurs: {price:.2f}€ | Stop: {stop:.2f}€\n"
                                f"Noch {dist_pct:.1f}% Abstand — aufpassen!"
                            )
                            alerted_ids.add(alert_key)

            # ── Pending Setups: Trigger prüfen ──────────────────────────
            pending = conn2.execute(
                "SELECT * FROM pending_setups WHERE status='WATCHING'"
            ).fetchall() if (conn2 := get_db()) else []
            conn2.close()

            for s in pending:
                pticker = s['ticker']
                ptrigger = s['entry_trigger']
                ptype = s['trigger_type'] or 'ABOVE'
                pprice = get_price_eur(pticker)
                if not pprice:
                    continue

                hit = (ptype == 'ABOVE' and pprice >= ptrigger) or \
                      (ptype == 'BELOW' and pprice <= ptrigger * 1.02)

                if hit:
                    alert_key = f"trigger_{s['id']}"
                    if alert_key not in alerted_ids:
                        # Status updaten
                        conn3 = get_db()
                        conn3.execute(
                            "UPDATE pending_setups SET status='TRIGGERED', updated_at=? WHERE id=?",
                            (datetime.now(timezone.utc).isoformat(), s['id'])
                        )
                        conn3.commit()
                        conn3.close()

                        crv_str = ''
                        if s['stop_suggestion'] and s['target_suggestion']:
                            risk = pprice - s['stop_suggestion']
                            reward = s['target_suggestion'] - pprice
                            if risk > 0:
                                crv_str = f" | CRV {reward/risk:.1f}:1"

                        send_alert(
                            f"🎯 **Entry-Trigger** — {pticker} ({s['strategy']})\n"
                            f"Kurs: {pprice:.2f}€ | Trigger: {ptrigger:.2f}€\n"
                            f"Conviction war: {s['conviction']}{crv_str}\n"
                            f"→ Scanner öffnet Position beim nächsten Lauf"
                        )
                        alerted_ids.add(alert_key)

            # Gelegentlich alerted_ids aufräumen (geschlossene Trades entfernen)
            if check_count % 30 == 0:
                open_ids = {p['id'] for p in get_open_positions()}
                alerted_ids = {k for k in alerted_ids
                               if isinstance(k, str) or k in open_ids}

        except KeyboardInterrupt:
            print("[PriceMonitor] Gestoppt.")
            PID_FILE.unlink(missing_ok=True)
            break
        except Exception as e:
            print(f"[PriceMonitor] Fehler: {e}")

        time.sleep(interval)


if __name__ == '__main__':
    run_monitor()
