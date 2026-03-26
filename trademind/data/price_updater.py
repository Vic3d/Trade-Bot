#!/usr/bin/env python3
"""
TradeMind — Price Updater (Phase 1.1)
======================================
Backfill + täglicher Update aller Ticker via yfinance.

Standalone-Cron: 30 23 * * 1-5 python3 /data/.openclaw/workspace/trademind/data/price_updater.py
"""

import sqlite3
import time
import sys
import logging
from datetime import datetime, date
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("yfinance nicht installiert. Bitte: pip install yfinance")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = "/data/.openclaw/workspace/data/trading.db"
RATE_LIMIT_SLEEP = 0.5   # Sekunden zwischen Tickern
BACKFILL_PERIOD = "2y"   # 2 Jahre History für Erstbefüllung

# Immer backfillen (Basis-Referenz)
BASE_TICKERS = ["^VIX", "SPY", "^GDAXI", "^GSPC"]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("trademind.price_updater")


# ── DB-Helpers ────────────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_tickers(conn: sqlite3.Connection) -> list[str]:
    """Alle Ticker aus ticker_meta + offenen Positionen aus trades + paper_portfolio."""
    tickers = set(BASE_TICKERS)

    cur = conn.cursor()

    # ticker_meta
    cur.execute("SELECT DISTINCT ticker FROM ticker_meta")
    for row in cur.fetchall():
        tickers.add(row[0])

    # Offene trades
    cur.execute("SELECT DISTINCT ticker FROM trades WHERE status = 'open'")
    for row in cur.fetchall():
        tickers.add(row[0])

    # Paper-Portfolio
    cur.execute("SELECT DISTINCT ticker FROM paper_portfolio")
    for row in cur.fetchall():
        tickers.add(row[0])

    return sorted(tickers)


def get_latest_price_date(conn: sqlite3.Connection, ticker: str) -> str | None:
    """Letztes Datum für einen Ticker in der prices-Tabelle."""
    cur = conn.cursor()
    cur.execute("SELECT MAX(date) FROM prices WHERE ticker = ?", (ticker,))
    result = cur.fetchone()
    return result[0] if result else None


def upsert_prices(conn: sqlite3.Connection, ticker: str, df) -> int:
    """Upsert OHLCV-Daten in prices-Tabelle. Gibt Anzahl neuer Zeilen zurück."""
    if df is None or df.empty:
        return 0

    cur = conn.cursor()
    inserted = 0

    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        try:
            cur.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    open   = excluded.open,
                    high   = excluded.high,
                    low    = excluded.low,
                    close  = excluded.close,
                    volume = excluded.volume
                """,
                (
                    ticker,
                    date_str,
                    float(row.get("Open", 0) or 0),
                    float(row.get("High", 0) or 0),
                    float(row.get("Low", 0) or 0),
                    float(row.get("Close", 0) or 0),
                    int(row.get("Volume", 0) or 0),
                ),
            )
            inserted += 1
        except Exception as e:
            log.warning(f"  Upsert-Fehler {ticker} {date_str}: {e}")

    conn.commit()
    return inserted


# ── Preis-Download ────────────────────────────────────────────────────────────
def fetch_ticker_data(ticker: str, period: str = BACKFILL_PERIOD):
    """Download via yfinance. Gibt DataFrame oder None zurück."""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, auto_adjust=True)
        if df.empty:
            log.warning(f"  {ticker}: Keine Daten von yfinance (leerer DataFrame)")
            return None
        return df
    except Exception as e:
        log.error(f"  {ticker}: yfinance-Fehler: {e}")
        return None


def needs_backfill(latest_date: str | None) -> bool:
    """True wenn kein Datum oder älter als 2 Tage."""
    if not latest_date:
        return True
    try:
        latest = datetime.strptime(latest_date, "%Y-%m-%d").date()
        delta = (date.today() - latest).days
        return delta > 1
    except Exception:
        return True


# ── Ensure UNIQUE constraint ──────────────────────────────────────────────────
def ensure_prices_unique_index(conn: sqlite3.Connection):
    """Sicherstellen dass (ticker, date) UNIQUE Index existiert."""
    cur = conn.cursor()
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date)"
        )
        conn.commit()
    except Exception as e:
        log.warning(f"Index-Fehler (harmlos wenn schon vorhanden): {e}")


# ── Haupt-Funktion ────────────────────────────────────────────────────────────
def run_price_update(backfill: bool = False) -> dict:
    """
    Führt Preis-Update durch.
    backfill=True: immer 2 Jahre holen (auch wenn aktuell)
    backfill=False: nur wenn veraltet
    """
    conn = get_connection()
    ensure_prices_unique_index(conn)

    tickers = get_all_tickers(conn)
    log.info(f"Preis-Update gestartet: {len(tickers)} Ticker")

    updated = 0
    failed = []
    new_rows_total = 0
    skipped = 0

    for ticker in tickers:
        latest = get_latest_price_date(conn, ticker)

        if not backfill and not needs_backfill(latest):
            log.debug(f"  {ticker}: aktuell ({latest}), übersprungen")
            skipped += 1
            time.sleep(0.1)
            continue

        log.info(f"  {ticker}: Lade Daten (letztes Datum: {latest or 'nie'})...")
        df = fetch_ticker_data(ticker, period=BACKFILL_PERIOD)

        if df is None:
            failed.append(ticker)
            time.sleep(RATE_LIMIT_SLEEP)
            continue

        new_rows = upsert_prices(conn, ticker, df)
        new_rows_total += new_rows
        updated += 1
        log.info(f"  {ticker}: {new_rows} Zeilen upserted")

        time.sleep(RATE_LIMIT_SLEEP)

    conn.close()

    summary = {
        "tickers_total": len(tickers),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "new_rows": new_rows_total,
        "timestamp": datetime.now().isoformat(),
    }

    log.info("=" * 60)
    log.info(f"ZUSAMMENFASSUNG Preis-Update {summary['timestamp']}")
    log.info(f"  Ticker gesamt: {summary['tickers_total']}")
    log.info(f"  Updated:       {summary['updated']}")
    log.info(f"  Übersprungen:  {summary['skipped']}")
    log.info(f"  Fehlgeschlagen:{len(summary['failed'])}")
    if summary["failed"]:
        log.warning(f"  Fehlende Ticker: {', '.join(summary['failed'])}")
    log.info(f"  Neue Preiszeilen: {summary['new_rows']}")
    log.info("=" * 60)

    return summary


# ── VIX + Regime Backfill ─────────────────────────────────────────────────────
def run_vix_regime_backfill() -> dict:
    """
    Phase 1.2: VIX + Regime für alle 180 Trades nachfüllen.
    Quellen: macro_daily (VIX indicator) + regime_history
    """
    conn = get_connection()
    cur = conn.cursor()

    # VIX lookup: macro_daily WHERE indicator='VIX'
    cur.execute("SELECT date, value FROM macro_daily WHERE indicator = 'VIX'")
    vix_macro = {row[0]: row[1] for row in cur.fetchall()}

    # VIX fallback: prices WHERE ticker='^VIX'
    cur.execute("SELECT date, close FROM prices WHERE ticker = '^VIX'")
    vix_prices = {row[0]: row[1] for row in cur.fetchall()}

    # Merged VIX: macro_daily hat Priorität
    vix_data = {**vix_prices, **vix_macro}  # macro überschreibt prices

    # Regime lookup
    cur.execute("SELECT date, regime FROM regime_history")
    regime_data = {row[0]: row[1] for row in cur.fetchall()}

    def get_vix(d: str) -> float | None:
        """VIX für ein Datum holen. Sucht auch ±3 Tage."""
        if not d:
            return None
        date_only = d[:10]
        if date_only in vix_data:
            return vix_data[date_only]
        # ±3 Tage suchen (Wochenenden, Feiertage)
        try:
            base = datetime.strptime(date_only, "%Y-%m-%d")
            for delta in [1, -1, 2, -2, 3, -3]:
                from datetime import timedelta
                candidate = (base + timedelta(days=delta)).strftime("%Y-%m-%d")
                if candidate in vix_data:
                    return vix_data[candidate]
        except Exception:
            pass
        return None

    def get_regime(d: str) -> str | None:
        """Regime für ein Datum holen. Sucht auch ±3 Tage."""
        if not d:
            return None
        date_only = d[:10]
        if date_only in regime_data:
            return regime_data[date_only]
        try:
            base = datetime.strptime(date_only, "%Y-%m-%d")
            from datetime import timedelta
            for delta in [1, -1, 2, -2, 3, -3]:
                candidate = (base + timedelta(days=delta)).strftime("%Y-%m-%d")
                if candidate in regime_data:
                    return regime_data[candidate]
        except Exception:
            pass
        return None

    # Alle Trades laden
    cur.execute(
        "SELECT id, entry_date, exit_date, vix_at_entry, vix_at_exit, regime_at_entry, regime_at_exit FROM trades"
    )
    trades = cur.fetchall()

    vix_entry_filled = 0
    vix_exit_filled = 0
    regime_entry_filled = 0
    regime_exit_filled = 0
    already_had_vix = 0

    for trade in trades:
        trade_id, entry_date, exit_date, vix_entry, vix_exit, regime_entry, regime_exit = trade
        updates = {}

        # VIX Entry
        if vix_entry is None:
            v = get_vix(entry_date)
            if v is not None:
                updates["vix_at_entry"] = v
                vix_entry_filled += 1
        else:
            already_had_vix += 1

        # VIX Exit
        if vix_exit is None and exit_date:
            v = get_vix(exit_date)
            if v is not None:
                updates["vix_at_exit"] = v
                vix_exit_filled += 1

        # Regime Entry
        if regime_entry is None:
            r = get_regime(entry_date)
            if r is not None:
                updates["regime_at_entry"] = r
                regime_entry_filled += 1

        # Regime Exit
        if regime_exit is None and exit_date:
            r = get_regime(exit_date)
            if r is not None:
                updates["regime_at_exit"] = r
                regime_exit_filled += 1

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            cur.execute(
                f"UPDATE trades SET {set_clause} WHERE id = ?",
                list(updates.values()) + [trade_id],
            )

    conn.commit()

    # Validierung
    cur.execute("SELECT COUNT(*) FROM trades WHERE vix_at_entry IS NULL")
    still_null_vix = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades WHERE regime_at_entry IS NULL")
    still_null_regime = cur.fetchone()[0]

    conn.close()

    summary = {
        "vix_entry_filled": vix_entry_filled,
        "vix_exit_filled": vix_exit_filled,
        "regime_entry_filled": regime_entry_filled,
        "regime_exit_filled": regime_exit_filled,
        "already_had_vix": already_had_vix,
        "still_null_vix_entry": still_null_vix,
        "still_null_regime_entry": still_null_regime,
    }

    log.info("=" * 60)
    log.info("ZUSAMMENFASSUNG VIX + Regime Backfill")
    log.info(f"  VIX Entry gefüllt:    {vix_entry_filled}")
    log.info(f"  VIX Exit gefüllt:     {vix_exit_filled}")
    log.info(f"  Regime Entry gefüllt: {regime_entry_filled}")
    log.info(f"  Regime Exit gefüllt:  {regime_exit_filled}")
    log.info(f"  Bereits hatte VIX:    {already_had_vix}")
    log.info(f"  Noch NULL (VIX Entry):    {still_null_vix}")
    log.info(f"  Noch NULL (Regime Entry): {still_null_regime}")
    log.info("=" * 60)

    return summary


# ── CRV Backfill ──────────────────────────────────────────────────────────────
def run_crv_backfill() -> dict:
    """
    Phase 1.3: CRV für alle Trades berechnen wo NULL.
    crv = (target - entry) / (entry - stop)
    Wenn kein target: crv = 3.0 (Default)
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, entry_price, stop, target FROM trades WHERE crv IS NULL"
    )
    trades = cur.fetchall()

    crv_calculated = 0
    crv_default = 0
    crv_skipped = 0

    for trade in trades:
        trade_id, entry_price, stop, target = trade

        if not entry_price or not stop:
            crv_skipped += 1
            continue

        risk = entry_price - stop
        if abs(risk) < 0.0001:
            # Stop = Entry → kein sinnvoller CRV
            crv_skipped += 1
            continue

        if target and target != entry_price:
            reward = target - entry_price
            crv = reward / risk
            crv_calculated += 1
        else:
            crv = 3.0
            crv_default += 1

        cur.execute("UPDATE trades SET crv = ? WHERE id = ?", (round(crv, 4), trade_id))

    conn.commit()

    # Validierung
    cur.execute("SELECT COUNT(*) FROM trades WHERE crv IS NULL")
    still_null = cur.fetchone()[0]

    conn.close()

    summary = {
        "crv_calculated": crv_calculated,
        "crv_default": crv_default,
        "crv_skipped": crv_skipped,
        "still_null_crv": still_null,
    }

    log.info("=" * 60)
    log.info("ZUSAMMENFASSUNG CRV Backfill")
    log.info(f"  CRV berechnet (aus Target): {crv_calculated}")
    log.info(f"  CRV Default (3.0):          {crv_default}")
    log.info(f"  Übersprungen (kein Stop):   {crv_skipped}")
    log.info(f"  Noch NULL:                  {still_null}")
    log.info("=" * 60)

    return summary


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TradeMind Price Updater")
    parser.add_argument(
        "--mode",
        choices=["full", "prices", "vix-regime", "crv", "daily"],
        default="daily",
        help=(
            "full = alles (backfill + vix + crv) | "
            "prices = nur Preis-Backfill | "
            "vix-regime = nur VIX+Regime | "
            "crv = nur CRV | "
            "daily = täglicher Cron (Preise aktualisieren)"
        ),
    )
    parser.add_argument(
        "--force-backfill",
        action="store_true",
        help="2-Jahres-Backfill auch wenn Daten aktuell sind",
    )
    args = parser.parse_args()

    results = {}

    if args.mode in ("full", "prices"):
        log.info("▶ Phase 1.1: Preis-Backfill (2 Jahre)")
        results["prices"] = run_price_update(backfill=True)

    elif args.mode == "daily":
        log.info("▶ Täglicher Preis-Update (nur veraltete Ticker)")
        results["prices"] = run_price_update(backfill=args.force_backfill)

    if args.mode in ("full", "vix-regime"):
        log.info("▶ Phase 1.2: VIX + Regime Backfill")
        results["vix_regime"] = run_vix_regime_backfill()

    if args.mode in ("full", "crv"):
        log.info("▶ Phase 1.3: CRV Backfill")
        results["crv"] = run_crv_backfill()

    # Finale Zusammenfassung
    print("\n" + "=" * 60)
    print("🎩 TradeMind Phase 1 — ABGESCHLOSSEN")
    print("=" * 60)
    if "prices" in results:
        p = results["prices"]
        print(f"  Preise: {p['updated']} Ticker updated, {p['new_rows']} neue Zeilen, {len(p['failed'])} fehlgeschlagen")
        if p["failed"]:
            print(f"  Fehlende Ticker: {', '.join(p['failed'])}")
    if "vix_regime" in results:
        v = results["vix_regime"]
        print(f"  VIX:    {v['vix_entry_filled']} Entry + {v['vix_exit_filled']} Exit gefüllt | Noch NULL: {v['still_null_vix_entry']}")
        print(f"  Regime: {v['regime_entry_filled']} Entry + {v['regime_exit_filled']} Exit gefüllt | Noch NULL: {v['still_null_regime_entry']}")
    if "crv" in results:
        c = results["crv"]
        print(f"  CRV:    {c['crv_calculated']} berechnet + {c['crv_default']} Default | Noch NULL: {c['still_null_crv']}")
    print("=" * 60)
