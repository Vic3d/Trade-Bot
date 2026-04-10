#!/usr/bin/env python3.13
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

# ─── Tier-spezifische Haltezeiten ────────────────────────────────────
# Tier C (aggressiv/Pokern): 3 Tage max ohne Fortschritt
# Tier B (moderat): 7 Tage
# Tier A (Thesis): 21 Tage (Earnings-Zyklus)
# Default (kein Tier-Tag): 10 Tage

HOLD_LIMITS = {
    'TIER_C':   3,   # Pokern → schnell raus wenn kein Move
    'TIER_B':   7,
    'TIER_A':   21,  # Thesis braucht Zeit
    'DEFAULT':  10,
}

MIN_MOVE_FOR_HOLD     = 0.03  # Mindestens +3% nach halber Haltezeit → sonst Flag
TRAILING_TRIGGER      = 0.05  # Bei +5% Stop auf Breakeven ziehen
PROGRESS_THRESHOLD    = 0.30  # Muss nach 50% der Haltezeit 30% Richtung Ziel gelaufen sein

def yahoo(ticker):
    """→ live_data.get_price_eur(). Gibt immer EUR zurück. Kein direkter Yahoo-Aufruf."""
    import sys as _sys
    _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
    from live_data import get_price_eur
    return get_price_eur(ticker)

def get_eurusd():
    """→ live_data.get_eurusd(). Single Source of Truth."""
    import sys as _sys
    _sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
    from live_data import get_eurusd as _fx
    return _fx()

def close_position(db, row_id, close_price, exit_type, entry_price, shares, fees):
    pnl_pct = (close_price - entry_price) / entry_price * 100 if entry_price else 0

    # ── Plausibilitäts-Check: > 50% Verlust ist verdächtig ──────────
    if pnl_pct < -50:
        print(f"⚠️ VERDÄCHTIGER EXIT: PnL {pnl_pct:.1f}% für Trade {row_id} (Entry {entry_price:.2f} → Close {close_price:.2f}) — möglicher Preis-/Währungsfehler")
        db.execute(
            "UPDATE paper_portfolio SET notes = notes || ? WHERE id=?",
            (f' [SUSPECT: PnL {pnl_pct:.1f}% @ {close_price:.2f}]', row_id)
        )
        db.commit()
        return 0  # Kein PnL buchen, Trade bleibt offen zur manuellen Prüfung
    # ────────────────────────────────────────────────────────────────

    pnl = (close_price - entry_price) * shares - fees

    # Ticker holen bevor wir schließen
    ticker_row = db.execute(
        "SELECT ticker FROM paper_portfolio WHERE id=?", (row_id,)
    ).fetchone()
    ticker = ticker_row[0] if ticker_row else None

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

    # Pending Setup für diesen Ticker zurücksetzen (WATCHING → EXPIRED nach Exit)
    if ticker:
        db.execute(
            "UPDATE pending_setups SET status='EXPIRED', updated_at=datetime('now') "
            "WHERE ticker=? AND status IN ('WATCHING','TRIGGERED')",
            (ticker,)
        )
        db.commit()

    return pnl

def is_market_open() -> bool:
    """Prüft ob mindestens eine relevante Börse heute handelt."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / 'core'))
        from market_hours import is_any_trading_day
        # Repräsentative Tickers für alle genutzten Börsen
        probe = ['AAPL', 'RHM.DE', 'EQNR.OL', 'BA.L', 'TTE.PA', 'ASML.AS']
        return is_any_trading_day(probe)
    except Exception:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).weekday() < 5


def run():
    if not is_market_open():
        from datetime import datetime
        print(f"📅 Markt geschlossen ({datetime.now().strftime('%A')}) — kein Exit-Check.")
        return

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
        price = yahoo(t['ticker'])  # bereits in EUR via live_data.get_price_eur()
        if not price:
            continue
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

        move_pct   = (price - entry) / entry
        total_range = abs(target - entry)
        progress   = (price - entry) / total_range if total_range > 0 else 0  # 0.0–1.0 Richtung Ziel

        # Tier aus notes extrahieren (z.B. '[TIER_C LEARN]' oder '[TIER_A]')
        notes = t['notes'] or ''
        if 'TIER_C' in notes: tier = 'TIER_C'
        elif 'TIER_B' in notes: tier = 'TIER_B'
        elif 'TIER_A' in notes: tier = 'TIER_A'
        else: tier = 'DEFAULT'

        max_hold = HOLD_LIMITS.get(tier, HOLD_LIMITS['DEFAULT'])
        half_hold = max_hold // 2

        # ── Day Trade: Zwangsschluss bei 21:50 CET ───────────────────
        trade_style = t['style'] or 'swing'
        if trade_style == 'day':
            from datetime import timezone as _tz
            import zoneinfo
            now_berlin = datetime.now(zoneinfo.ZoneInfo('Europe/Berlin'))
            # Prüfe ob Entry heute war (Day Trade = selber Tag)
            try:
                entry_dt_aware = datetime.fromisoformat(str(t['entry_date'])).astimezone(
                    zoneinfo.ZoneInfo('Europe/Berlin'))
                same_day = entry_dt_aware.date() == now_berlin.date()
            except Exception:
                same_day = True

            force_close = (
                same_day and
                (now_berlin.hour > 21 or (now_berlin.hour == 21 and now_berlin.minute >= 50))
            ) or (not same_day)  # Übernacht-Day-Trade → sofort schließen

            if force_close:
                pnl = close_position(db, t['id'], price, 'DAY_TRADE_CLOSE', entry, shares, fees)
                closed.append(
                    f"🕘 DAYCLS {t['ticker']:8} | {entry:.2f}→{price:.2f}€ | P&L: {pnl:+.2f}€ [DAY]"
                )
                continue

        # 1. STOP getroffen
        if price <= stop:
            pnl = close_position(db, t['id'], price, 'STOP', entry, shares, fees)
            closed.append(f"🔴 STOP  {t['ticker']:8} | {entry:.2f}→{price:.2f}€ | P&L: {pnl:+.2f}€ [{tier}]")
            continue

        # 2. TARGET getroffen
        if price >= target:
            pnl = close_position(db, t['id'], price, 'TARGET', entry, shares, fees)
            closed.append(f"🟢 TARGET {t['ticker']:8} | {entry:.2f}→{price:.2f}€ | P&L: {pnl:+.2f}€ [{tier}]")
            continue

        # 3. TIME EXIT — tier-spezifisch
        # Day Trade: max 1 Tag (oben behandelt)
        # Regel: max_hold Tage erreicht + weniger als MIN_MOVE → raus
        if hold_days >= max_hold and move_pct < MIN_MOVE_FOR_HOLD:
            pnl = close_position(db, t['id'], price, f'TIME_{hold_days}d', entry, shares, fees)
            closed.append(
                f"⏰ TIME  {t['ticker']:8} | {hold_days}d/{max_hold}d | {move_pct:+.1%} | P&L: {pnl:+.2f}€ [{tier}]"
            )
            continue

        # 4. FORTSCHRITTS-EXIT — nach halber Haltezeit unter 30% Richtung Ziel
        # Verhindert ewiges Festhalten an stagnierenden Trades
        if hold_days >= half_hold and hold_days >= 2:
            if progress < PROGRESS_THRESHOLD and move_pct < 0:
                # Unter Einstand UND kein Fortschritt nach halber Zeit → early cut
                pnl = close_position(db, t['id'], price, f'NO_PROGRESS_{hold_days}d', entry, shares, fees)
                closed.append(
                    f"✂️ CUT   {t['ticker']:8} | {hold_days}d | Fortschritt {progress:.0%} | P&L: {pnl:+.2f}€ [{tier}]"
                )
                continue

        # 5. TIER C SONDERREGEL: nach 2 Tagen unter Einstand → sofort raus
        # Aggressiv-Pokern heißt auch: schnell Verluste begrenzen
        if tier == 'TIER_C' and hold_days >= 2 and move_pct < -0.03:
            pnl = close_position(db, t['id'], price, 'TIER_C_QUICKCUT', entry, shares, fees)
            closed.append(
                f"✂️ QUICK {t['ticker']:8} | Tier C 2d -3% Rule | P&L: {pnl:+.2f}€"
            )
            continue

        # 6. TRAILING STOP: +5% → Stop auf Breakeven
        if move_pct >= TRAILING_TRIGGER and stop < entry:
            new_stop = round(entry * 1.005, 2)  # Breakeven + 0.5% Puffer
            db.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (new_stop, t['id']))
            db.commit()
            trailing_updates.append(
                f"🔄 TRAIL {t['ticker']:8} | Stop: {stop:.2f}→{new_stop:.2f}€ (+{move_pct:.1%}) [{tier}]"
            )

        # 7. TRAILING STOP: +10% → Stop auf +5%
        elif move_pct >= 0.10 and stop < entry * 1.05:
            new_stop = round(entry * 1.05, 2)
            db.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (new_stop, t['id']))
            db.commit()
            trailing_updates.append(
                f"🔄 TRAIL+ {t['ticker']:8} | Stop: {stop:.2f}→{new_stop:.2f}€ (+{move_pct:.1%}) [{tier}]"
            )

    if closed or trailing_updates:
        print(f"Exit Manager: {len(closed)} geschlossen, {len(trailing_updates)} Trailing-Updates")
        for c in closed: print(f"  {c}")
        for u in trailing_updates: print(f"  {u}")
    else:
        print("Exit Manager: Keine Aktionen")

    open_now = db.execute("SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'").fetchone()[0]
    print(f"Offene Positionen: {open_now}")
    return closed, trailing_updates

def trigger_online_learning(closed_trades: list):
    """
    Phase 4: Online Model nach jedem Trade-Close updaten.
    Lernt sofort aus dem Ergebnis — kein Batch, kein Warten.
    """
    if not closed_trades:
        return
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from online_model import learn_from_closed_trade
        import sqlite3 as _sql
        conn = _sql.connect(str(WS / 'data/trading.db'))
        # Letzte geschlossene Trades holen (die gerade geschlossen wurden)
        recent = conn.execute("""
            SELECT id FROM paper_portfolio
            WHERE status IN ('WIN','CLOSED','LOSS')
              AND rsi_at_entry IS NOT NULL
              AND close_date >= datetime('now', '-5 minutes')
            ORDER BY close_date DESC LIMIT 10
        """).fetchall()
        conn.close()
        for row in recent:
            learn_from_closed_trade(row[0])
    except Exception as e:
        print(f"  ⚠️  Online Learning Fehler (nicht kritisch): {e}")


def trigger_learning_if_needed(closed_count: int):
    """
    Triggert den Learning Engine automatisch wenn Trades geschlossen wurden.
    Kein manuelles 'python3 learning_system.py' mehr nötig.
    """
    if closed_count == 0:
        return

    import subprocess, sys
    learning_script = WS / 'scripts/paper_learning_engine.py'
    if not learning_script.exists():
        print("  ⚠️  Learning Engine nicht gefunden — skip")
        return

    try:
        result = subprocess.run(
            [sys.executable, str(learning_script), '--update-scores'],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                print(f"  🧠 {line}")
        if result.returncode != 0 and result.stderr:
            print(f"  ⚠️  Learning Engine Fehler: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("  ⚠️  Learning Engine Timeout — wird beim nächsten Cron nachgeholt")
    except Exception as e:
        print(f"  ⚠️  Learning Engine Exception: {e}")


if __name__ == '__main__':
    result = run()
    if result is None:
        exit(0)  # Markt geschlossen
    closed, trailing = result
    trigger_online_learning(closed)        # Phase 4: sofort lernen
    trigger_learning_if_needed(len(closed))  # Phase 1-3: Scores updaten
