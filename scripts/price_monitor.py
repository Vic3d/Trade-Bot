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

# Sub-8 V3-fix: Line-buffered stdout — ohne das war der Log >17h "stale"
# obwohl der Prozess lief. Block-Buffering haelt Print-Output 4KB lang
# zurueck wenn stdout kein TTY ist (Direct-Start in Datei).
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

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
# Phase 44w: Significant-Move-Trigger fuer News-Reactor
SIGNIFICANT_MOVE_PCT   = 2.0   # >=2% intraday → trigger news_reactor sofort
_move_triggered_today  = {}    # ticker → date des letzten Triggers


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def is_market_hours(ticker: str | None = None) -> bool:
    """Phase 45j (Bug-Fix 04.05): Ticker-aware Markt-Stunden.
    Vorher war 08:00-22:00 CET zu breit — Pre-Market-Ticks (vor 15:30 CEST
    fuer NYSE) haben Stops getriggert. Bug-Beleg: MOS+PAAS am Mo 04.05 08:00
    durch Pre-Market-Gap-Down ausgestoppt obwohl regulaerer NYSE noch geschlossen.

    Returns True NUR waehrend regulaerer Handelszeit der Heimat-Boerse.
    """
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo('Europe/Berlin'))
        if now.weekday() >= 5:  # Sa=5, So=6
            return False

        h = now.hour + now.minute / 60.0
        if not ticker:
            # Default: alle Maerkte als "gemeinsamer Korridor" 09:00-22:00 CEST
            return 9 <= h < 22

        tu = ticker.upper()
        # EU-Tickers (Suffix-basiert): 09:00-17:30 CEST
        if any(tu.endswith(s) for s in ('.DE', '.PA', '.AS', '.MI', '.MC',
                                          '.OL', '.VI', '.SW', '.L', '.ST', '.CO')):
            return 9 <= h < 17.5
        # UK (.L): 09:00-17:30 CEST (London-Time +1h von CEST nicht relevant fuer Range)
        if tu.endswith('.L'):
            return 9 <= h < 17.5
        # Asia (.HK, .T, .SS, .SZ): 02:00-09:00 CEST (vereinfacht)
        if any(tu.endswith(s) for s in ('.HK', '.T', '.SS', '.SZ')):
            return 2 <= h < 9
        # Default = US (NYSE/NASDAQ): regulaer 15:30-22:00 CEST
        # (Pre-Market ab 10:00 wird NICHT als Markt-Open gewertet — kein Stop-Hit
        #  auf Pre-Market-Ticks weil zu illiquide)
        return 15.5 <= h < 22
    except Exception:
        return True  # Fallback: immer aktiv (defensive)


def send_alert(msg: str, dedupe_key: str | None = None):
    """Discord-Alert via Dispatcher.
    Phase 44u-fix: 'Stop sehr nah' Warnungen sind SILENT (nur Inbox)
    weil sie Information sind, keine Action.
    """
    try:
        from discord_dispatcher import send_alert as _dispatch, TIER_HIGH, TIER_MEDIUM, TIER_LOW, TIER_SILENT
        m = msg.upper()
        if any(k in m for k in ('STOP GETROFFEN', 'TARGET ERREICHT', 'VIX-SPIKE', '🔴', '🟢', '🎯')):
            tier = TIER_HIGH
        elif 'STOP SEHR NAH' in m or 'STOP NAH' in m:
            tier = TIER_SILENT  # Information, nicht Action
        elif 'TRAILING' in m or '🔄' in m:
            tier = TIER_LOW  # Digest abends, nicht sofort
        elif 'CURRENCY-MISMATCH' in m or 'ENTRY-TRIGGER' in m:
            tier = TIER_MEDIUM
        else:
            tier = TIER_LOW
        _dispatch(msg, tier=tier, category='trade', dedupe_key=dedupe_key)
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
    _currency_warned_ids = set()  # Trade-IDs für die Currency-Mismatch Alert gesendet wurde
    check_count = 0
    last_heartbeat = 0.0

    while True:
        try:
            market_open = is_market_hours()
            interval = POLL_INTERVAL_MARKET if market_open else POLL_INTERVAL_OFFHOURS

            # Sub-8 V3-fix: Heartbeat alle 10min auch off-hours, damit
            # meta_health Stale-Log-Detection nicht False-Positive feuert.
            now_ts = time.time()
            if now_ts - last_heartbeat > 600:
                state = 'OPEN' if market_open else 'CLOSED'
                print(f"[PriceMonitor] heartbeat market={state} checks={check_count}")
                last_heartbeat = now_ts

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

                # Phase 45j: Pro-Ticker Markt-Open-Check.
                # Stops nur waehrend regulaerer Handelszeit der Heimat-Boerse.
                # Verhindert Pre-Market/After-Hours-Stop-Hits auf duennem Volumen.
                if not is_market_hours(ticker):
                    continue

                # ── Currency-Mismatch Sanity Check (Bug-Fix 2026-04-27) ──
                # entry/stop kommen aus DB in Original-Currency (NOK, DKK, GBp),
                # price kommt via get_price_eur immer in EUR. Wenn die Werte
                # mehr als 50% auseinander liegen, ist es vermutlich ein
                # Currency-Mismatch — kein Stop/Target feuern lassen!
                # Realer Tages-Move >50% ist praktisch nie ohne Halt der Aktie.
                if entry and entry > 0:
                    ratio = price / entry
                    if ratio < 0.5 or ratio > 2.0:
                        if tid not in _currency_warned_ids:
                            send_alert(
                                f"⚠️ **Currency-Mismatch verdächtig** — {ticker} ({strat})\n"
                                f"Entry (DB): {entry:.2f} | Price (EUR): {price:.2f} | Ratio: {ratio:.2f}x\n"
                                f"Stop/Target-Check übersprungen — manueller Check nötig.\n"
                                f"Vermutlich Original-Currency (z.B. NOK/DKK/GBp) vs EUR."
                            )
                            _currency_warned_ids.add(tid)
                        continue  # SKIP — kein Stop, kein Target, keine Aktion

                move_pct = (price - entry) / entry * 100

                # Phase 44w: Significant-Move-Trigger
                # Wenn Position |move| >= 2% intraday (gegen letztes Bewertungs-Niveau)
                # → trigger news_reactor sofort, max 1x/Ticker/Tag
                if abs(move_pct) >= SIGNIFICANT_MOVE_PCT:
                    today_key = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    if _move_triggered_today.get(ticker) != today_key:
                        _move_triggered_today[ticker] = today_key
                        try:
                            import subprocess
                            print(f"[PRICE_MONITOR] {ticker} move {move_pct:+.1f}% → trigger news_reactor")
                            subprocess.Popen(
                                ['python3', str(WS / 'scripts' / 'news_reactor.py')],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                        except Exception as _e:
                            print(f"[PRICE_MONITOR] trigger fail: {_e}")

                # STOP getroffen
                if stop and price <= stop:
                    # Phase 45v (Victor 2026-05-06): Phantom-Tick-Sanity-Check.
                    # PYPL-Bug 06.05: Yahoo lieferte 39.49 zur NYSE-Eroeffnung
                    # obwohl Tagesrange 46-50 war. Stop wurde auf Phantom-Preis
                    # ausgeloest. Schutz: wenn live-price > 8% vom letzten
                    # DB-Close abweicht, NICHT sofort schliessen — log + skip.
                    is_phantom = False
                    try:
                        _c = get_db()
                        _row = _c.execute(
                            "SELECT close FROM prices WHERE ticker=? "
                            "ORDER BY date DESC LIMIT 1", (ticker,)
                        ).fetchone()
                        _c.close()
                        if _row and _row[0]:
                            _last_close = float(_row[0])
                            _dev_pct = abs(price - _last_close) / _last_close * 100
                            if _dev_pct > 8.0:
                                print(f"[PRICE_MONITOR] ⚠ PHANTOM-CHECK {ticker}: "
                                      f"price {price:.2f} vs last_close {_last_close:.2f} "
                                      f"= {_dev_pct:.1f}% Abweichung — Stop NICHT ausgeloest, "
                                      f"warte auf naechsten Tick")
                                is_phantom = True
                    except Exception as _e:
                        print(f"[PRICE_MONITOR] phantom-check failed: {_e}")
                    if is_phantom:
                        continue
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
                # Phase 44u-fix: nur 1x pro Ticker pro Tag, nicht per 0.1%-Bucket
                if stop and price > stop:
                    dist_pct = (price - stop) / price * 100
                    if dist_pct < 1.5:
                        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                        alert_key = f"near_{tid}_{today}"
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
