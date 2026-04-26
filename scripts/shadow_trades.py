#!/usr/bin/env python3
"""
shadow_trades.py — Counterfactual Trade-Tracking für Thesen-Vergleich.

Idee:
  Jedes vom Scanner gescorte Setup (entry/stop/target) wird hier als
  hypothetischer Trade geloggt — auch wenn es real NICHT ausgeführt wurde
  (weil Limit, weil Guards blockten, weil cash voll, weil A/B-Lottery, ...).

  Täglich um 23:30 CEST evaluiert ein Job ob die offenen shadow_trades
  ihren Stop oder Target getroffen hätten (basierend auf prices-Tabelle).
  Schließt Shadows als WIN/LOSS mit hypothetischer PnL.

  Wöchentlich vergleicht shadow_thesis_review.py die kumulierte
  Shadow-Performance pro Strategie. So siehst Du:
    - Welche Thesen wären am besten gelaufen (auch ohne Trade)
    - Wo wir Alpha verschenkt haben (gut gescort, nie ausgeführt)
    - Welche Thesen konsequent SCHLECHT scoren — Kandidaten für SUSPEND

Tabelle:
  shadow_trades(id, ts_created, ticker, strategy, entry, stop, target,
                executed_real INT (0/1), real_trade_id INT,
                status TEXT (OPEN/WIN/LOSS/EXPIRED),
                exit_price, exit_date, pnl_pct, hold_days, source TEXT)

Public API:
  record_setup(...)   — Scanner ruft das nach evaluate_setup
  evaluate_open()     — Cron-Job 23:30 CEST
  cleanup_expired()   — räumt OPEN-Shadows älter als 30d auf

Sicherheit:
  - shadow_trades hat KEINEN Kapital-Effekt (nur Reporting)
  - Fehler im Logging werfen NIE (silent fail to stderr)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'

MAX_HOLD_DAYS_DEFAULT = 30  # Nach 30d Open → EXPIRED


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def _ensure_table() -> None:
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shadow_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_created    TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            strategy      TEXT NOT NULL,
            entry         REAL NOT NULL,
            stop          REAL NOT NULL,
            target        REAL NOT NULL,
            executed_real INTEGER DEFAULT 0,
            real_trade_id INTEGER,
            status        TEXT DEFAULT 'OPEN',
            exit_price    REAL,
            exit_date     TEXT,
            pnl_pct       REAL,
            hold_days     INTEGER,
            source        TEXT,
            blocked_reason TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shadow_status
        ON shadow_trades(status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shadow_strategy
        ON shadow_trades(strategy)
    """)
    conn.commit()
    conn.close()


def record_setup(
    ticker: str, strategy: str,
    entry: float, stop: float, target: float,
    source: str = 'autonomous_scanner',
    executed_real: bool = False,
    real_trade_id: int | None = None,
    blocked_reason: str | None = None,
) -> int | None:
    """
    Loggt ein Scanner-Setup als shadow_trade. Returns die neue id oder None.
    Idempotent für (ticker, strategy, today) — verhindert Duplikate vom gleichen
    Scan-Run wenn der Scanner mehrfach läuft.
    """
    try:
        _ensure_table()
        conn = _conn()
        today = datetime.now().strftime('%Y-%m-%d')

        # Idempotenz: gibt es heute schon ein OPEN-Shadow für (ticker,strategy)?
        existing = conn.execute("""
            SELECT id FROM shadow_trades
            WHERE ticker = ? AND strategy = ?
              AND status = 'OPEN'
              AND substr(ts_created, 1, 10) = ?
        """, (ticker, strategy, today)).fetchone()

        if existing:
            # Update executed_real falls jetzt anders
            if executed_real:
                conn.execute("""
                    UPDATE shadow_trades
                    SET executed_real = 1, real_trade_id = ?, blocked_reason = NULL
                    WHERE id = ?
                """, (real_trade_id, existing['id']))
                conn.commit()
            conn.close()
            return existing['id']

        cursor = conn.execute("""
            INSERT INTO shadow_trades
            (ts_created, ticker, strategy, entry, stop, target,
             executed_real, real_trade_id, source, blocked_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec='seconds'),
            ticker, strategy, entry, stop, target,
            1 if executed_real else 0,
            real_trade_id,
            source,
            blocked_reason,
        ))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return new_id
    except Exception as e:
        print(f'[shadow] record_setup error: {e}', file=sys.stderr)
        return None


def _get_price_range_since(ticker: str, since_date: str) -> tuple[float | None, float | None, str | None]:
    """
    Returns (min_low, max_high, latest_date) seit since_date aus prices-Tabelle.
    Verwendet close als Approximation für high/low wenn nur close verfügbar ist.
    """
    try:
        conn = _conn()
        # Versuche high/low (falls vorhanden), sonst close
        cols = [r[1] for r in conn.execute('PRAGMA table_info(prices)').fetchall()]
        has_hl = 'high' in cols and 'low' in cols
        if has_hl:
            row = conn.execute("""
                SELECT MIN(low) as min_low, MAX(high) as max_high,
                       MAX(date) as latest_date
                FROM prices
                WHERE ticker = ? AND date >= ?
            """, (ticker, since_date)).fetchone()
        else:
            row = conn.execute("""
                SELECT MIN(close) as min_low, MAX(close) as max_high,
                       MAX(date) as latest_date
                FROM prices
                WHERE ticker = ? AND date >= ?
            """, (ticker, since_date)).fetchone()
        conn.close()
        if not row or row['min_low'] is None:
            return None, None, None
        return float(row['min_low']), float(row['max_high']), row['latest_date']
    except Exception as e:
        print(f'[shadow] price-range error {ticker}: {e}', file=sys.stderr)
        return None, None, None


def evaluate_open(max_hold_days: int = MAX_HOLD_DAYS_DEFAULT) -> dict:
    """
    Geht alle OPEN shadow_trades durch und prüft ob sie ihr Target/Stop
    getroffen hätten. Schließt entsprechend.

    Logik (vereinfacht — long-only):
      - low <= stop  → LOSS at stop_price
      - high >= target → WIN at target_price
      - both: LOSS (konservativ — wir nehmen an Stop wurde zuerst getroffen)
      - keiner: bleibt OPEN
      - älter als max_hold_days und beide nicht getroffen: EXPIRED at last close
    """
    _ensure_table()
    conn = _conn()
    opens = conn.execute("""
        SELECT * FROM shadow_trades WHERE status = 'OPEN'
    """).fetchall()
    conn.close()

    closed_win = 0
    closed_loss = 0
    expired = 0

    for row in opens:
        since = row['ts_created'][:10]
        min_low, max_high, latest = _get_price_range_since(row['ticker'], since)
        if min_low is None:
            continue  # keine Preisdaten

        days_open = (datetime.now() - datetime.fromisoformat(row['ts_created'][:19])).days

        new_status = None
        exit_price = None
        if min_low <= row['stop']:
            new_status = 'LOSS'
            exit_price = row['stop']
        elif max_high >= row['target']:
            new_status = 'WIN'
            exit_price = row['target']
        elif days_open >= max_hold_days:
            new_status = 'EXPIRED'
            # Nimm letzten Close als Exit
            try:
                c = _conn()
                last_close = c.execute(
                    "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
                    (row['ticker'],)
                ).fetchone()
                c.close()
                exit_price = float(last_close[0]) if last_close else row['entry']
            except Exception:
                exit_price = row['entry']

        if new_status:
            pnl_pct = (exit_price - row['entry']) / row['entry'] * 100
            try:
                c = _conn()
                c.execute("""
                    UPDATE shadow_trades
                    SET status = ?, exit_price = ?, exit_date = ?,
                        pnl_pct = ?, hold_days = ?
                    WHERE id = ?
                """, (new_status, round(exit_price, 4),
                      latest or datetime.now().strftime('%Y-%m-%d'),
                      round(pnl_pct, 2), days_open, row['id']))
                c.commit()
                c.close()
                if new_status == 'WIN':
                    closed_win += 1
                elif new_status == 'LOSS':
                    closed_loss += 1
                else:
                    expired += 1
            except Exception as e:
                print(f'[shadow] update error id={row["id"]}: {e}', file=sys.stderr)

    return {
        'open_checked': len(opens),
        'closed_win': closed_win,
        'closed_loss': closed_loss,
        'expired': expired,
    }


def stats_per_strategy(window_days: int = 30) -> list[dict]:
    """Returns per-strategy aggregated stats für die letzten N Tage."""
    _ensure_table()
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime('%Y-%m-%d')
    conn = _conn()
    rows = conn.execute("""
        SELECT
            strategy,
            COUNT(*) as n_total,
            SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN status='EXPIRED' THEN 1 ELSE 0 END) as expired,
            SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open_n,
            SUM(CASE WHEN executed_real=1 THEN 1 ELSE 0 END) as executed,
            AVG(CASE WHEN status IN ('WIN','LOSS','EXPIRED') THEN pnl_pct END) as avg_pnl_pct,
            SUM(CASE WHEN status IN ('WIN','LOSS','EXPIRED') THEN pnl_pct ELSE 0 END) as cum_pnl_pct
        FROM shadow_trades
        WHERE ts_created >= ?
        GROUP BY strategy
        ORDER BY cum_pnl_pct DESC
    """, (cutoff,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        closed = (d['wins'] or 0) + (d['losses'] or 0) + (d['expired'] or 0)
        d['win_rate'] = (d['wins'] / closed * 100) if closed else 0
        d['execution_rate'] = (d['executed'] / d['n_total'] * 100) if d['n_total'] else 0
        out.append(d)
    return out


def cleanup_expired(older_than_days: int = 90) -> int:
    """Löscht shadow_trades älter als N Tage (auch closed)."""
    cutoff = (datetime.now() - timedelta(days=older_than_days)).strftime('%Y-%m-%d')
    try:
        conn = _conn()
        cur = conn.execute("DELETE FROM shadow_trades WHERE ts_created < ?", (cutoff,))
        conn.commit()
        n = cur.rowcount
        conn.close()
        return n
    except Exception as e:
        print(f'[shadow] cleanup error: {e}', file=sys.stderr)
        return 0


if __name__ == '__main__':
    # CLI für manuelles Testen
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['eval', 'stats', 'cleanup', 'init'])
    ap.add_argument('--days', type=int, default=30)
    args = ap.parse_args()

    if args.cmd == 'init':
        _ensure_table()
        print('shadow_trades table ensured.')
    elif args.cmd == 'eval':
        r = evaluate_open()
        print(r)
    elif args.cmd == 'stats':
        for s in stats_per_strategy(args.days):
            print(f"{s['strategy']:20s} n={s['n_total']:3d} "
                  f"WR={s['win_rate']:5.1f}% cum={s['cum_pnl_pct']:+6.1f}% "
                  f"exec={s['execution_rate']:4.0f}%")
    elif args.cmd == 'cleanup':
        n = cleanup_expired(args.days)
        print(f'Cleaned {n} rows.')
