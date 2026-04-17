#!/usr/bin/env python3
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
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
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


# ─── Auto-DD Exit-Signale (Phase 7.14) ────────────────────────────────────────

def load_auto_dd_exit_signals() -> dict:
    """
    Liest unconsumed Exit-Signale aus data/auto_dd_exit_signals.jsonl.
    Returns: {ticker: signal_record}

    Signale werden nach Verarbeitung auf consumed=True gesetzt via mark_signal_consumed().
    """
    import os as _os
    from pathlib import Path as _Path
    ws = _Path(_os.getenv('TRADEMIND_HOME', '/opt/trademind'))
    signals_path = ws / 'data' / 'auto_dd_exit_signals.jsonl'
    if not signals_path.exists():
        return {}

    out: dict = {}
    try:
        with open(signals_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('consumed'):
                    continue
                ticker = (rec.get('ticker') or '').upper()
                if ticker:
                    # Neueste Signal gewinnt bei Duplikaten
                    out[ticker] = rec
    except Exception as e:
        print(f"[exit_manager] Auto-DD Signale laden fehlgeschlagen: {e}")
    return out


def mark_auto_dd_signal_consumed(ticker: str, position_id: int | None) -> None:
    """Markiert ein Exit-Signal als verarbeitet (in-place Rewrite der JSONL)."""
    import os as _os
    from pathlib import Path as _Path
    ws = _Path(_os.getenv('TRADEMIND_HOME', '/opt/trademind'))
    signals_path = ws / 'data' / 'auto_dd_exit_signals.jsonl'
    if not signals_path.exists():
        return

    try:
        lines_out = []
        with open(signals_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    lines_out.append(line)
                    continue
                if ((rec.get('ticker') or '').upper() == ticker.upper()
                        and (position_id is None or rec.get('position_id') == position_id)
                        and not rec.get('consumed')):
                    rec['consumed'] = True
                    rec['consumed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                lines_out.append(json.dumps(rec, ensure_ascii=False))
        with open(signals_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines_out) + ('\n' if lines_out else ''))
    except Exception as e:
        print(f"[exit_manager] Auto-DD Signal mark-consumed fehlgeschlagen: {e}")


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


def ensure_tranches_exist(conn: sqlite3.Connection, trade_id: int, total_shares: float) -> bool:
    """
    Creates 3 tranche records for a trade if none exist.
    Splits shares into 3 roughly equal thirds.
    Returns True if created, False if already existed.
    """
    existing = conn.execute(
        "SELECT COUNT(*) FROM trade_tranches WHERE trade_id = ?",
        (trade_id,)
    ).fetchone()[0]
    if existing > 0:
        return False

    try:
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
    """Send Discord alert via alert-queue.json."""
    try:
        alert_queue = WS / 'memory' / 'alert-queue.json'
        queue = []
        if alert_queue.exists():
            try:
                queue = json.loads(alert_queue.read_text(encoding="utf-8"))
            except Exception:
                queue = []
        queue.append({
            'message': message,
            'target': '452053147620343808',
            'ts': datetime.utcnow().isoformat(),
        })
        alert_queue.write_text(json.dumps(queue, indent=2))
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

    conn.execute(
        """
        UPDATE paper_portfolio
        SET status=?, close_price=?, close_date=datetime('now'),
            pnl_eur=?, pnl_pct=?, notes = notes || ?
        WHERE id=?
        """,
        (
            'WIN' if pnl > 0 else ('LOSS' if pnl < 0 else 'CLOSED'),
            round(close_price, 4),
            round(pnl, 2),
            round(pnl_pct, 2),
            f' [EXIT:{exit_type} {date.today().isoformat()}]',
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
        return datetime.utcnow().weekday() < 5


# ─── Main exit logic ──────────────────────────────────────────────────────────

def run() -> tuple[list, list]:
    """
    Main exit manager run.
    Returns: (closed_records, trailing_updates)
    """
    if not is_market_open():
        print(f"[exit_manager] Market closed ({datetime.now().strftime('%A')}) — skipping.")
        return [], []

    conn = get_db()

    open_trades = conn.execute(
        """
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               shares, fees, entry_date, notes, style
        FROM paper_portfolio WHERE status='OPEN'
        """
    ).fetchall()

    closed_records  = []
    trailing_updates = []

    # Phase 7.14: Auto-DD Exit-Signale laden (Claude hat Leiche im Keller entdeckt)
    auto_dd_signals = load_auto_dd_exit_signals()

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
        # HARD STOP 1c (Phase 22.1): Event-Auto-Exit-Queue
        # Wenn dieser Ticker im force_exit_queue.json steht, sofort schliessen.
        # ══════════════════════════════════════════════════════════════════
        try:
            _queue_path = WS / 'data' / 'force_exit_queue.json'
            if _queue_path.exists():
                _q = json.loads(_queue_path.read_text(encoding='utf-8'))
                _entries = _q.get('entries', [])
                _hit = next((e for e in _entries
                             if e.get('ticker','').upper() == ticker.upper()
                             and not e.get('consumed')), None)
                if _hit:
                    _reason = _hit.get('reason', 'event_auto_exit')
                    pnl = close_position(conn, trade_id, price, _reason.upper(), entry, shares, fees)
                    closed_records.append(
                        f"EVENT_AUTO_EXIT {ticker} | {_reason} | PnL: {pnl:+.2f}EUR"
                    )
                    send_alert(
                        f"⚡ **EVENT-AUTO-EXIT**: {ticker}\n"
                        f"Grund: {_reason}\n"
                        f"Entry={entry:.2f} → Close={price:.2f} | PnL: {pnl:+.2f}EUR"
                    )
                    _hit['consumed'] = True
                    _hit['consumed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    _queue_path.write_text(json.dumps(_q, indent=2, ensure_ascii=False), encoding='utf-8')
                    continue
        except Exception as _qe:
            print(f"[exit-manager] force_exit_queue Fehler (skip): {_qe}")

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
        # HARD STOP 2b: Auto-DD hat Leiche im Keller entdeckt (Phase 7.14)
        # NICHT_KAUFEN + confidence >= 75 von Claude Hold-Check
        # ══════════════════════════════════════════════════════════════════
        _sig = auto_dd_signals.get(ticker.upper())
        if _sig and _sig.get('reason_code') == 'AUTO_DD_INVALIDATED':
            _conf = int(_sig.get('confidence') or 0)
            _reasoning = _sig.get('reasoning', '')[:200]
            pnl = close_position(conn, trade_id, price, 'AUTO_DD_INVALIDATED', entry, shares, fees)
            closed_records.append(
                f"AUTO_DD_EXIT {ticker} | conf={_conf} | PnL: {pnl:+.2f}EUR | hold={hold_days}d"
            )
            send_alert(
                f"🚨 AUTO-DD EXIT: **{ticker}** — Leiche im Keller entdeckt.\n"
                f"Claude-Verdict: NICHT_KAUFEN (conf={_conf})\n"
                f"Grund: {_reasoning}\n"
                f"Entry={entry:.2f} | Close={price:.2f} | PnL: {pnl:+.2f}EUR"
            )
            mark_auto_dd_signal_consumed(ticker, trade_id)
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
        # HARD STOP 4: Single-day circuit breaker (-8%)
        # ══════════════════════════════════════════════════════════════════
        if move_pct <= CIRCUIT_BREAKER_PCT:
            pnl = close_position(conn, trade_id, price, 'CIRCUIT_BREAKER', entry, shares, fees)
            closed_records.append(
                f"CIRCUIT_BRK {ticker} | {move_pct:.1%} loss | PnL: {pnl:+.2f}EUR"
            )
            send_alert(
                f"CIRCUIT BREAKER: {ticker} -8% circuit breaker triggered.\n"
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
