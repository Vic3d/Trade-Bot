#!/usr/bin/env python3.13
"""
Paper Exit Manager v2 — Tranche-based Partial Exits + ATR Trailing
===================================================================
Phase 3 rewrite. New logic:

PARTIAL EXIT SYSTEM (tranche-based):
  Tranche 1 (1/3 position): Exit at +5% gain — lock in profit
  Tranche 2 (1/3 position): Exit at +10% gain — lock in more profit
  Tranche 3 (1/3 position): Trail with 2x ATR trailing stop — let winners run

THESIS-AWARE HOLD TIMES:
  S2   (EU Defense):          14-60 days
  PS17 (Energy Transition):   14-45 days
  PS18/PS19 (Dollar weakness): 7-30 days
  PS16 (AI Infrastructure):   10-45 days
  PS4  (Healthcare):          14-60 days
  DEFAULT:                    10-45 days

HARD STOPS (immediate exit):
  1. Stop-loss hit (stop_price from entry)
  2. Thesis INVALIDATED (kill trigger fired) → exit ALL tranches immediately
  3. Max hold time exceeded for strategy
  4. Single-day loss > 8% (circuit breaker)

Albert | TradeMind v3 | 2026-04-10
"""

import sqlite3
import json
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data' / 'trading.db'

# ─── Thesis-aware hold times (min_days, max_days) ────────────────────────────

HOLD_LIMITS = {
    'S2':      (14, 60),
    'PS17':    (14, 45),
    'PS18':    (7,  30),
    'PS19':    (7,  30),
    'PS16':    (10, 45),
    'PS4':     (14, 60),
    'PS13':    (10, 45),
    'PS20':    (10, 45),
    'DEFAULT': (10, 45),
}

# Tranche exit triggers
TRANCHE1_TARGET_PCT = 0.05   # +5%  → exit tranche 1
TRANCHE2_TARGET_PCT = 0.10   # +10% → exit tranche 2
CIRCUIT_BREAKER_PCT = -0.08  # -8%  single-day circuit breaker

# ATR trailing multiplier for tranche 3
ATR_TRAIL_MULT = 2.0


# ─── DB Helper ────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


# ─── Price helper ─────────────────────────────────────────────────────────────

def get_price(ticker: str) -> float | None:
    """Get current price via live_data (EUR). Falls back to DB last close."""
    import sys as _sys
    _sys.path.insert(0, str(WS / 'scripts' / 'core'))
    try:
        from live_data import get_price_eur
        p = get_price_eur(ticker)
        if p:
            return p
    except Exception:
        pass
    # Fallback: last close from prices table
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        conn.close()
        return row['close'] if row else None
    except Exception:
        return None


def get_eurusd() -> float:
    import sys as _sys
    _sys.path.insert(0, str(WS / 'scripts' / 'core'))
    try:
        from live_data import get_eurusd as _fx
        return _fx() or 1.10
    except Exception:
        return 1.10


# ─── ATR Helper ───────────────────────────────────────────────────────────────

def get_atr(ticker: str, period: int = 14) -> float | None:
    """Compute ATR from prices table. Returns None if insufficient data."""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT high, low, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker, period + 2)
        ).fetchall()
        conn.close()
        if len(rows) < period + 1:
            return None

        true_ranges = []
        for i in range(len(rows) - 1):
            h = rows[i]['high'] or 0
            l = rows[i]['low']  or 0
            pc = rows[i + 1]['close'] or 0
            tr = max(h - l, abs(h - pc), abs(l - pc))
            true_ranges.append(tr)

        if not true_ranges:
            return None
        return sum(true_ranges[:period]) / period
    except Exception:
        return None


# ─── Conviction-based Stop ───────────────────────────────────────────────────

def _get_conviction_stop_pct(trade_id: int) -> float:
    """
    Dynamischer Circuit-Breaker basierend auf Conviction-Score.
    Schwache Setups bekommen engere Stops → weniger Verlust bei Fehlsignalen.

    Conviction 45-55 (niedrig): -5% Stop
    Conviction 55-65 (mittel):  -7% Stop
    Conviction 65+   (hoch):    -8% Stop (bestehende Logik)
    Fallback:                   -8% wenn conviction nicht vorhanden
    """
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT conviction FROM paper_portfolio WHERE id = ?",
            (trade_id,)
        ).fetchone()
        conn.close()

        if row and row['conviction'] is not None:
            conv = row['conviction']
            if conv < 55:
                return -0.05   # Enge Stops für schwache Setups
            elif conv < 65:
                return -0.07   # Moderate Stops
            else:
                return -0.08   # Weite Stops für starke Setups
    except Exception:
        pass
    return CIRCUIT_BREAKER_PCT  # Fallback: -8%


# ─── Thesis status check ──────────────────────────────────────────────────────

def is_thesis_invalidated(strategy: str) -> bool:
    """Returns True if thesis for this strategy is INVALIDATED in thesis_status table."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT status FROM thesis_status WHERE thesis_id = ?",
            (strategy,)
        ).fetchone()
        conn.close()
        if row and row['status'] == 'INVALIDATED':
            return True
        return False
    except Exception:
        return False


# ─── Tranche helpers ──────────────────────────────────────────────────────────

def get_trade_tranches(conn: sqlite3.Connection, trade_id: int) -> list[dict]:
    """
    Returns tranche records for a trade from trade_tranches table.
    If no tranches found (legacy trade), synthesizes a single full-size tranche.
    """
    try:
        rows = conn.execute(
            """
            SELECT id, trade_id, tranche_num, shares, status,
                   exit_price, exit_date, exit_type, notes
            FROM trade_tranches
            WHERE trade_id = ? AND status = 'OPEN'
            ORDER BY tranche_num ASC
            """,
            (trade_id,)
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]
    except Exception:
        pass
    return []  # No tranches → handled by caller as legacy single-tranche


def _ensure_tranche_table(conn: sqlite3.Connection) -> bool:
    """
    Erstellt trade_tranches Tabelle falls sie nicht existiert.
    Kritisch: Wenn diese Tabelle fehlt, fallen ALLE Trades in Legacy-Modus
    und die Tranche-Exits (+5%/+10%) feuern nie.
    Returns True wenn Tabelle vorhanden oder erstellt.
    """
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_tranches (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id      INTEGER NOT NULL,
                tranche_num   INTEGER NOT NULL,   -- 1, 2, oder 3
                shares        REAL    NOT NULL,
                status        TEXT    DEFAULT 'OPEN',  -- OPEN / CLOSED
                exit_price    REAL,
                exit_date     TEXT,
                exit_type     TEXT,
                notes         TEXT,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tranches_trade ON trade_tranches(trade_id, status)"
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[exit_manager] trade_tranches table error: {e}")
        return False


def ensure_tranches_exist(conn: sqlite3.Connection, trade_id: int, total_shares: float) -> bool:
    """
    Creates 3 tranche records for a trade if none exist.
    Splits shares into 3 roughly equal thirds.
    Returns True if created, False if already existed.

    BUG FIX: Stellt sicher dass Tabelle existiert bevor COUNT ausgeführt wird.
    Vorher: fehlende Tabelle → Exception → return False → Legacy-Modus für alle Trades.
    """
    # Sicherstellen dass Tabelle existiert (kritischer Fix)
    _ensure_tranche_table(conn)

    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM trade_tranches WHERE trade_id = ?",
            (trade_id,)
        ).fetchone()[0]
        if existing > 0:
            return False

        tranche1 = round(total_shares / 3, 4)
        tranche2 = round(total_shares / 3, 4)
        tranche3 = round(total_shares - tranche1 - tranche2, 4)
        for i, sh in enumerate([tranche1, tranche2, tranche3], 1):
            conn.execute(
                """
                INSERT INTO trade_tranches
                    (trade_id, tranche_num, shares, status, created_at)
                VALUES (?, ?, ?, 'OPEN', datetime('now'))
                """,
                (trade_id, i, sh)
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"[exit_manager] ensure_tranches_exist({trade_id}): {e}")
        return False


def close_tranche(
    conn: sqlite3.Connection,
    tranche_id: int,
    exit_price: float,
    exit_type: str,
) -> None:
    """Marks a tranche as closed in trade_tranches."""
    try:
        conn.execute(
            """
            UPDATE trade_tranches
            SET status='CLOSED', exit_price=?, exit_date=datetime('now'), exit_type=?
            WHERE id = ?
            """,
            (round(exit_price, 4), exit_type, tranche_id)
        )
        conn.commit()
    except Exception as e:
        print(f"[exit_manager] close_tranche({tranche_id}): {e}")


def count_open_tranches(conn: sqlite3.Connection, trade_id: int) -> int:
    """Returns number of open tranches for a trade."""
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM trade_tranches WHERE trade_id=? AND status='OPEN'",
            (trade_id,)
        ).fetchone()[0]
    except Exception:
        return 0


# ─── Discord alert ────────────────────────────────────────────────────────────

def send_alert(message: str) -> None:
    """Send Discord alert via Dispatcher (Phase 22.4 Priority-Tiering).
    Auto-Tier nach Keyword-Heuristik:
      HIGH   — STOP HIT, CIRCUIT BREAKER, EVENT-AUTO-EXIT, THESIS KILL,
               AUTO-DD EXIT (alle alpha-relevanten Exits)
      MEDIUM — TRANCHE-Exits (teilweise Gewinnmitnahme)
      LOW    — Rest (MAX_HOLD, Debug)
    """
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from discord_dispatcher import send_alert as _dispatch, TIER_HIGH, TIER_MEDIUM, TIER_LOW
        m_up = message.upper()
        if any(k in m_up for k in ('STOP HIT', 'CIRCUIT BREAKER', 'EVENT-AUTO-EXIT',
                                    'THESIS KILL', 'AUTO-DD EXIT', '🚨')):
            tier = TIER_HIGH
        elif 'TRANCHE' in m_up:
            tier = TIER_MEDIUM
        else:
            tier = TIER_LOW
        _dispatch(message, tier=tier, category='exit')
    except Exception as e:
        print(f"[exit_manager] alert error: {e}")


# ─── Position close helpers ───────────────────────────────────────────────────

def close_position(
    conn: sqlite3.Connection,
    row_id: int,
    close_price: float,
    exit_type: str,
    entry_price: float,
    shares: float,
    fees: float,
) -> float:
    """Fully closes a position and returns realized PnL."""
    pnl_pct = (close_price - entry_price) / entry_price * 100 if entry_price else 0

    # Plausibility check
    if pnl_pct < -50:
        print(f"[exit_manager] SUSPECT EXIT: PnL {pnl_pct:.1f}% for trade {row_id} — skipping")
        conn.execute(
            "UPDATE paper_portfolio SET notes = notes || ? WHERE id=?",
            (f' [SUSPECT: PnL {pnl_pct:.1f}% @ {close_price:.2f}]', row_id)
        )
        conn.commit()
        return 0

    pnl = (close_price - entry_price) * shares - fees

    ticker_row = conn.execute(
        "SELECT ticker FROM paper_portfolio WHERE id=?", (row_id,)
    ).fetchone()
    ticker = ticker_row['ticker'] if ticker_row else None

    # ── Phase 19a: compute NET PnL (after realistic costs) ──────────────────
    net_note = ''
    try:
        from execution.transaction_costs import net_pnl as _net_pnl
        if ticker and entry_price and close_price and shares:
            rt = _net_pnl(
                ticker=ticker,
                entry_price=entry_price,
                exit_price=close_price,
                shares=shares,
                fx_rate=1.0,  # already-EUR world here; sizer handles FX
            )
            net_note = (
                f' [NET:{rt["net_pnl_eur"]:+.0f}€ '
                f'drag:{rt["cost_drag_pct"]:.2f}%]'
            )
    except Exception as e:
        print(f"[exit_manager] net_pnl calc failed: {e}")

    conn.execute(
        """
        UPDATE paper_portfolio
        SET status=?, close_price=?, close_date=datetime('now'),
            pnl_eur=?, pnl_pct=?, exit_type=?, notes = notes || ?
        WHERE id=?
        """,
        (
            'WIN' if pnl > 0 else 'LOSS',
            round(close_price, 4),
            round(pnl, 2),
            round(pnl_pct, 2),
            exit_type or 'UNKNOWN',
            f' [EXIT:{exit_type} {date.today().isoformat()}]' + net_note,
            row_id
        )
    )
    conn.commit()

    if ticker:
        conn.execute(
            "UPDATE pending_setups SET status='EXPIRED', updated_at=datetime('now') "
            "WHERE ticker=? AND status IN ('WATCHING','TRIGGERED')",
            (ticker,)
        )
        conn.commit()

    return pnl


# ─── Market open check ────────────────────────────────────────────────────────

def is_market_open() -> bool:
    try:
        import sys
        sys.path.insert(0, str(WS / 'scripts' / 'core'))
        from market_hours import is_any_trading_day
        probe = ['AAPL', 'RHM.DE', 'EQNR.OL', 'BA.L', 'TTE.PA', 'ASML.AS']
        return is_any_trading_day(probe)
    except Exception:
        return datetime.now(timezone.utc).weekday() < 5


# ─── Main exit logic ──────────────────────────────────────────────────────────

def run() -> tuple[list, list]:
    """
    Main exit manager run.
    Returns: (closed_records, trailing_updates)
    """
    if not is_market_open():
        print(f"[exit_manager] Market closed ({datetime.now(ZoneInfo('Europe/Berlin')).strftime('%A')}) — skipping.")
        return [], []

    conn = get_db()

    # Sicherstellen dass trade_tranches Tabelle existiert (einmaliger Fix beim Start)
    _ensure_tranche_table(conn)

    open_trades = conn.execute(
        """
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               shares, fees, entry_date, notes, style
        FROM paper_portfolio WHERE status='OPEN'
        """
    ).fetchall()

    closed_records  = []
    trailing_updates = []

    for t in open_trades:
        ticker  = t['ticker']
        entry   = t['entry_price'] or 0
        stop    = t['stop_price'] or (entry * 0.93)
        target  = t['target_price'] or (entry * 1.15)
        shares  = t['shares'] or 1
        fees    = t['fees'] or 1.0
        strategy = t['strategy'] or 'DEFAULT'
        trade_id = t['id']

        price = get_price(ticker)
        if not price:
            continue

        # Hold time
        try:
            entry_dt = datetime.fromisoformat(str(t['entry_date'])[:19])
            hold_days = (datetime.now() - entry_dt).days
        except Exception:
            hold_days = 0

        move_pct = (price - entry) / entry if entry > 0 else 0

        # Hold limits for this strategy
        hold_cfg = HOLD_LIMITS.get(strategy, HOLD_LIMITS['DEFAULT'])
        max_hold = hold_cfg[1]

        # ATR for this ticker
        atr = get_atr(ticker)

        # ── DAY TRADE: force close at 21:50 CET ──────────────────────────
        if (t['style'] or 'swing') == 'day':
            try:
                import zoneinfo
                now_berlin = datetime.now(zoneinfo.ZoneInfo('Europe/Berlin'))
                entry_dt_tz = datetime.fromisoformat(str(t['entry_date'])).replace(
                    tzinfo=zoneinfo.ZoneInfo('UTC')
                ).astimezone(zoneinfo.ZoneInfo('Europe/Berlin'))
                same_day = entry_dt_tz.date() == now_berlin.date()
                force = (same_day and (now_berlin.hour > 21 or
                         (now_berlin.hour == 21 and now_berlin.minute >= 50))) or (not same_day)
                if force:
                    pnl = close_position(conn, trade_id, price, 'DAY_TRADE_CLOSE', entry, shares, fees)
                    closed_records.append(f"DAY_CLOSE {ticker} | {entry:.2f}->{price:.2f} | PnL: {pnl:+.2f}EUR")
                    continue
            except Exception:
                pass

        # ══════════════════════════════════════════════════════════════════
        # HARD STOP 1: Stop-loss hit
        # ══════════════════════════════════════════════════════════════════
        if price <= stop:
            pnl = close_position(conn, trade_id, price, 'STOP', entry, shares, fees)
            closed_records.append(f"STOP {ticker} | {entry:.2f}->{price:.2f} | PnL: {pnl:+.2f}EUR | hold={hold_days}d")
            send_alert(f"STOP HIT: {ticker} exited at {price:.2f} (entry={entry:.2f}) | PnL: {pnl:+.2f}EUR")
            continue

        # ══════════════════════════════════════════════════════════════════
        # HARD STOP 2: Thesis INVALIDATED
        # ══════════════════════════════════════════════════════════════════
        if is_thesis_invalidated(strategy):
            pnl = close_position(conn, trade_id, price, 'THESIS_INVALIDATED', entry, shares, fees)
            closed_records.append(
                f"THESIS_KILL {ticker} | Strategy={strategy} INVALIDATED | PnL: {pnl:+.2f}EUR"
            )
            send_alert(
                f"THESIS KILL EXIT: {ticker} — strategy {strategy} INVALIDATED.\n"
                f"Entry={entry:.2f} | Close={price:.2f} | PnL: {pnl:+.2f}EUR"
            )
            continue

        # ══════════════════════════════════════════════════════════════════
        # HARD STOP 3: Max hold time exceeded
        # ══════════════════════════════════════════════════════════════════
        if hold_days >= max_hold:
            pnl = close_position(conn, trade_id, price, f'MAX_HOLD_{hold_days}d', entry, shares, fees)
            closed_records.append(
                f"MAX_HOLD {ticker} | {hold_days}d/{max_hold}d | PnL: {pnl:+.2f}EUR"
            )
            continue

        # ══════════════════════════════════════════════════════════════════
        # HARD STOP 4: Conviction-based circuit breaker (variable -5% bis -8%)
        # ══════════════════════════════════════════════════════════════════
        _cb_pct = _get_conviction_stop_pct(trade_id)
        if move_pct <= _cb_pct:
            pnl = close_position(conn, trade_id, price, f'CIRCUIT_BREAKER_{abs(_cb_pct)*100:.0f}PCT', entry, shares, fees)
            closed_records.append(
                f"CIRCUIT_BRK {ticker} | {move_pct:.1%} loss (limit {_cb_pct:.0%}) | PnL: {pnl:+.2f}EUR"
            )
            send_alert(
                f"CIRCUIT BREAKER: {ticker} {_cb_pct:.0%} circuit breaker triggered.\n"
                f"Entry={entry:.2f} | Close={price:.2f} | PnL: {pnl:+.2f}EUR"
            )
            continue

        # ══════════════════════════════════════════════════════════════════
        # TRANCHE-BASED PARTIAL EXITS
        # ══════════════════════════════════════════════════════════════════

        # Ensure tranches are created (creates 3 tranches on first run for this trade)
        created = ensure_tranches_exist(conn, trade_id, shares)
        if created:
            print(f"[exit_manager] Created 3 tranches for trade {trade_id} ({ticker})")

        tranches = get_trade_tranches(conn, trade_id)

        if not tranches:
            # Pure legacy trade without tranche support — apply old-style trailing
            _apply_legacy_trailing(conn, t, price, entry, stop, move_pct, trailing_updates)
            continue

        open_tranche_nums = {tr['tranche_num'] for tr in tranches}

        # ── Tranche 1: Exit at +5% ────────────────────────────────────────
        if 1 in open_tranche_nums and move_pct >= TRANCHE1_TARGET_PCT:
            t1 = next(tr for tr in tranches if tr['tranche_num'] == 1)
            t1_shares = t1['shares']
            t1_pnl = (price - entry) * t1_shares
            pnl_pct_val = move_pct * 100
            close_tranche(conn, t1['id'], price, 'TRANCHE1_+5PCT')
            closed_records.append(
                f"TRANCHE1 {ticker} | +{pnl_pct_val:.1f}% | "
                f"shares={t1_shares:.2f} | locked {t1_pnl:+.2f}EUR"
            )
            send_alert(
                f"TRANCHE 1 EXIT: {ticker} at +{pnl_pct_val:.1f}% — "
                f"locking in {t1_pnl:+.2f}EUR"
            )
            # After T1 exits, raise stop to breakeven
            if stop < entry:
                new_stop = round(entry * 1.002, 4)  # breakeven + 0.2% buffer
                conn.execute(
                    "UPDATE paper_portfolio SET stop_price=? WHERE id=?",
                    (new_stop, trade_id)
                )
                conn.commit()
                trailing_updates.append(
                    f"STOP->BREAKEVEN {ticker} | {stop:.2f}->{new_stop:.2f} (T1 exit)"
                )
            continue

        # ── Tranche 2: Exit at +10% ───────────────────────────────────────
        if 2 in open_tranche_nums and move_pct >= TRANCHE2_TARGET_PCT:
            # Only exit T2 if T1 is already closed (tranche_num 1 not in open set)
            if 1 not in open_tranche_nums:
                t2 = next(tr for tr in tranches if tr['tranche_num'] == 2)
                t2_shares = t2['shares']
                t2_pnl = (price - entry) * t2_shares
                pnl_pct_val = move_pct * 100
                close_tranche(conn, t2['id'], price, 'TRANCHE2_+10PCT')
                closed_records.append(
                    f"TRANCHE2 {ticker} | +{pnl_pct_val:.1f}% | "
                    f"shares={t2_shares:.2f} | locked {t2_pnl:+.2f}EUR"
                )
                send_alert(
                    f"TRANCHE 2 EXIT: {ticker} at +{pnl_pct_val:.1f}% — "
                    f"locking in {t2_pnl:+.2f}EUR"
                )
                # After T2 exits, begin ATR trailing for T3
                if atr and atr > 0:
                    new_stop = round(price - ATR_TRAIL_MULT * atr, 4)
                    if new_stop > stop:
                        conn.execute(
                            "UPDATE paper_portfolio SET stop_price=? WHERE id=?",
                            (new_stop, trade_id)
                        )
                        conn.commit()
                        trailing_updates.append(
                            f"ATR_TRAIL_START {ticker} | stop={new_stop:.2f} "
                            f"(price-2xATR={ATR_TRAIL_MULT}x{atr:.2f}) (T2 exit)"
                        )
                continue

        # ── Tranche 3: ATR Trailing stop update ───────────────────────────
        # Only for T3 (T1+T2 are closed), update trailing stop daily
        if (1 not in open_tranche_nums and 2 not in open_tranche_nums
                and 3 in open_tranche_nums):
            if atr and atr > 0 and move_pct > 0:
                new_trail_stop = round(price - ATR_TRAIL_MULT * atr, 4)
                if new_trail_stop > stop:
                    conn.execute(
                        "UPDATE paper_portfolio SET stop_price=? WHERE id=?",
                        (new_trail_stop, trade_id)
                    )
                    conn.commit()
                    trailing_updates.append(
                        f"ATR_TRAIL {ticker} | {stop:.2f}->{new_trail_stop:.2f} | "
                        f"price={price:.2f} 2x ATR={atr:.2f}"
                    )

        # ── Full position target hit (no tranches used / all T3) ──────────
        if price >= target and not tranches:
            # Legacy: target hit on full position
            pnl = close_position(conn, trade_id, price, 'TARGET', entry, shares, fees)
            closed_records.append(
                f"TARGET {ticker} | {entry:.2f}->{price:.2f} | PnL: {pnl:+.2f}EUR"
            )

    if closed_records or trailing_updates:
        print(f"[exit_manager] {len(closed_records)} exits, {len(trailing_updates)} trail updates")
        for c in closed_records:
            print(f"  {c}")
        for u in trailing_updates:
            print(f"  {u}")
    else:
        print("[exit_manager] No actions.")

    open_now = conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'"
    ).fetchone()[0]
    print(f"[exit_manager] Open positions: {open_now}")
    conn.close()
    return closed_records, trailing_updates


def _apply_legacy_trailing(
    conn, trade_row, price: float, entry: float, stop: float,
    move_pct: float, trailing_updates: list
) -> None:
    """
    Legacy trailing stop for trades with no tranche records.
    Mimics old behavior: +5% → breakeven stop, +10% → +5% stop.
    """
    trade_id = trade_row['id']
    ticker   = trade_row['ticker']

    TRAILING_TRIGGER = 0.05
    if move_pct >= TRAILING_TRIGGER and stop < entry:
        new_stop = round(entry * 1.005, 4)
        conn.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (new_stop, trade_id))
        conn.commit()
        trailing_updates.append(
            f"LEGACY_TRAIL {ticker} | {stop:.2f}->{new_stop:.2f} (+{move_pct:.1%})"
        )
    elif move_pct >= 0.10 and stop < entry * 1.05:
        new_stop = round(entry * 1.05, 4)
        conn.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (new_stop, trade_id))
        conn.commit()
        trailing_updates.append(
            f"LEGACY_TRAIL+ {ticker} | {stop:.2f}->{new_stop:.2f} (+{move_pct:.1%})"
        )


# ─── Online learning integration ──────────────────────────────────────────────

def trigger_online_learning(closed_trades: list) -> None:
    """Trigger online model learning after exits."""
    if not closed_trades:
        return
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from online_model import learn_from_closed_trade
        import sqlite3 as _sql
        conn2 = _sql.connect(str(WS / 'data/trading.db'))
        recent = conn2.execute(
            """
            SELECT id FROM paper_portfolio
            WHERE status IN ('WIN','CLOSED','LOSS')
              AND rsi_at_entry IS NOT NULL
              AND close_date >= datetime('now', '-5 minutes')
            ORDER BY close_date DESC LIMIT 10
            """
        ).fetchall()
        conn2.close()
        for row in recent:
            learn_from_closed_trade(row[0])
    except Exception as e:
        print(f"[exit_manager] Online learning error (non-critical): {e}")


def trigger_learning_if_needed(closed_count: int) -> None:
    """Trigger learning engine if any trades were closed."""
    if closed_count == 0:
        return
    import subprocess
    import sys
    learning_script = WS / 'scripts/paper_learning_engine.py'
    if not learning_script.exists():
        return
    try:
        result = subprocess.run(
            [sys.executable, str(learning_script), '--update-scores'],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                print(f"  [learning] {line}")
        if result.returncode != 0 and result.stderr:
            print(f"  [learning] error: {result.stderr[:200]}")
    except Exception as e:
        print(f"  [learning] exception: {e}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    result = run()
    if result is None:
        exit(0)
    closed, trailing = result
    trigger_online_learning(closed)
    trigger_learning_if_needed(len(closed))
