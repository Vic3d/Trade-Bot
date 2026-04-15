#!/usr/bin/env python3
"""
source_scorer.py — Verfolgt, welche News-Quellen und Trader-Signale
zu erfolgreichen Trades geführt haben.

Nach dem Schliessen eines Trades wird nachgeschlagen, welche Signale
in den 7 Tagen vor dem Entry-Datum diesen Ticker erwähnt haben.
Daraus wird ein Zuverlässigkeits-Score je Quelle berechnet.

DB: /opt/trademind/data/intelligence.db (source_scores Tabelle)
    /opt/trademind/data/trading.db      (paper_portfolio Tabelle)

Verwendung:
  python3 scripts/core/source_scorer.py          # Update + Report
  python3 scripts/core/source_scorer.py --report # Nur Report
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

TRADING_DB      = Path("/opt/trademind/data/trading.db")
INTELLIGENCE_DB = Path("/opt/trademind/data/intelligence.db")
LOG_PATH        = Path("/opt/trademind/data/source_scorer.log")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("source_scorer")


# ---------------------------------------------------------------------------
# DB-Verbindungen
# ---------------------------------------------------------------------------

def _get_trading_conn() -> sqlite3.Connection | None:
    """Verbindung zur trading.db öffnen."""
    try:
        if not TRADING_DB.exists():
            log.warning("trading.db nicht gefunden: %s", TRADING_DB)
            return None
        conn = sqlite3.connect(str(TRADING_DB))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as exc:
        log.error("_get_trading_conn: %s", exc)
        return None


def _get_intel_conn() -> sqlite3.Connection | None:
    """Verbindung zur intelligence.db öffnen und Schema anlegen falls nötig."""
    try:
        INTELLIGENCE_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(INTELLIGENCE_DB))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_scores (
                source              TEXT PRIMARY KEY,
                total_signals       INTEGER DEFAULT 0,
                signals_led_to_trade INTEGER DEFAULT 0,
                winning_trades      INTEGER DEFAULT 0,
                losing_trades       INTEGER DEFAULT 0,
                total_pnl_eur       REAL    DEFAULT 0.0,
                win_rate            REAL    DEFAULT 0.0,
                avg_pnl_eur         REAL    DEFAULT 0.0,
                last_updated        TEXT
            )
        """)
        conn.commit()
        return conn
    except Exception as exc:
        log.error("_get_intel_conn: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Kern-Logik
# ---------------------------------------------------------------------------

def update_from_closed_trades() -> dict:
    """
    Liest kürzlich geschlossene Trades aus trading.db (letzte 30 Tage).
    Für jeden Trade wird in intelligence.db trader_signals nach Signalen
    gesucht, die diesen Ticker innerhalb von 7 Tagen vor dem Entry erwähnt
    haben. Die source_scores Tabelle wird entsprechend aktualisiert.

    Returns:
        dict mit Zusammenfassung: trades_processed, sources_updated, errors
    """
    summary = {
        "trades_processed": 0,
        "signals_matched":  0,
        "sources_updated":  0,
        "errors":           [],
    }

    trading_conn = _get_trading_conn()
    if trading_conn is None:
        summary["errors"].append("Keine Verbindung zu trading.db")
        return summary

    intel_conn = _get_intel_conn()
    if intel_conn is None:
        summary["errors"].append("Keine Verbindung zu intelligence.db")
        trading_conn.close()
        return summary

    try:
        # 1. Geschlossene Trades der letzten 30 Tage laden
        # Beide Trade-Tabellen abfragen: paper_portfolio (Swing) + trades (Paper Engine)
        closed_trades = []

        for table, status_col, status_vals, close_col in [
            ("paper_portfolio", "status", ("CLOSED",),     "close_date"),
            ("trades",          "status", ("WIN", "LOSS"),  "close_date"),
        ]:
            try:
                placeholders = ",".join("?" for _ in status_vals)
                rows = trading_conn.execute(f"""
                    SELECT ticker, entry_date, {close_col} AS close_date, pnl_eur
                    FROM {table}
                    WHERE {status_col} IN ({placeholders})
                      AND pnl_eur IS NOT NULL
                      AND {close_col} >= date('now', '-30 days')
                """, status_vals).fetchall()
                closed_trades.extend(rows)
            except Exception as exc:
                # Tabelle existiert möglicherweise nicht — kein harter Fehler
                log.debug("Tabelle %s: %s", table, exc)

        log.info("update_from_closed_trades: %d geschlossene Trades gefunden", len(closed_trades))

        # 2. Je Trade passende Signale suchen
        # Accumulator: source -> {winning, losing, total_pnl, signal_count}
        accumulator: dict[str, dict] = {}

        for trade in closed_trades:
            ticker     = trade["ticker"]
            entry_date = trade["entry_date"]
            pnl_eur    = float(trade["pnl_eur"] or 0.0)

            if not ticker or not entry_date:
                continue

            # entry_date kann ISO-String mit Zeit oder nur Datum sein
            entry_day = str(entry_date)[:10]

            try:
                signals = intel_conn.execute("""
                    SELECT source, tickers_mentioned
                    FROM trader_signals
                    WHERE fetched_at >= date(?, '-7 days')
                      AND fetched_at <= date(?, '+1 day')
                """, (entry_day, entry_day)).fetchall()
            except Exception as exc:
                log.warning("trader_signals-Abfrage für %s fehlgeschlagen: %s", ticker, exc)
                summary["errors"].append(f"Signal-Abfrage {ticker}: {exc}")
                continue

            for signal in signals:
                source = signal["source"] or "unknown"

                # Prüfen ob dieser Ticker im tickers_mentioned JSON vorkommt
                try:
                    tickers_raw = signal["tickers_mentioned"] or "[]"
                    tickers_list = json.loads(tickers_raw)
                    # tickers_list kann Liste von Strings oder Dicts sein
                    if isinstance(tickers_list, list):
                        matched = any(
                            (t.upper() == ticker.upper() if isinstance(t, str)
                             else str(t.get("ticker", "")).upper() == ticker.upper())
                            for t in tickers_list
                        )
                    else:
                        matched = False
                except Exception:
                    matched = False

                if not matched:
                    continue

                # In Accumulator eintragen
                if source not in accumulator:
                    accumulator[source] = {
                        "winning_trades": 0,
                        "losing_trades":  0,
                        "total_pnl_eur":  0.0,
                        "signal_count":   0,
                    }

                acc = accumulator[source]
                acc["signal_count"] += 1
                acc["total_pnl_eur"] += pnl_eur
                if pnl_eur > 0:
                    acc["winning_trades"] += 1
                else:
                    acc["losing_trades"] += 1

                summary["signals_matched"] += 1

            summary["trades_processed"] += 1

        # 3. source_scores updaten (INSERT OR REPLACE mit kumulierten Werten)
        now_str = datetime.now(timezone.utc).isoformat()

        for source, acc in accumulator.items():
            try:
                # Vorhandene Werte laden um korrekt zu akkumulieren
                existing = intel_conn.execute(
                    "SELECT * FROM source_scores WHERE source = ?", (source,)
                ).fetchone()

                if existing:
                    new_winning = existing["winning_trades"] + acc["winning_trades"]
                    new_losing  = existing["losing_trades"]  + acc["losing_trades"]
                    new_pnl     = existing["total_pnl_eur"]  + acc["total_pnl_eur"]
                    new_total   = existing["total_signals"]
                    new_led     = existing["signals_led_to_trade"] + acc["signal_count"]
                else:
                    new_winning = acc["winning_trades"]
                    new_losing  = acc["losing_trades"]
                    new_pnl     = acc["total_pnl_eur"]
                    new_total   = acc["signal_count"]
                    new_led     = acc["signal_count"]

                total_decided = new_winning + new_losing
                win_rate  = (new_winning / total_decided) if total_decided > 0 else 0.0
                avg_pnl   = (new_pnl / new_led)           if new_led > 0       else 0.0

                intel_conn.execute("""
                    INSERT OR REPLACE INTO source_scores
                        (source, total_signals, signals_led_to_trade,
                         winning_trades, losing_trades,
                         total_pnl_eur, win_rate, avg_pnl_eur, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    source,
                    new_total,
                    new_led,
                    new_winning,
                    new_losing,
                    new_pnl,
                    win_rate,
                    avg_pnl,
                    now_str,
                ))

                summary["sources_updated"] += 1

            except Exception as exc:
                log.error("source_scores Update für %s: %s", source, exc)
                summary["errors"].append(f"Update {source}: {exc}")

        intel_conn.commit()
        log.info(
            "update_from_closed_trades abgeschlossen: %d Trades, %d Signale, %d Quellen",
            summary["trades_processed"], summary["signals_matched"], summary["sources_updated"],
        )

    except Exception as exc:
        log.error("update_from_closed_trades (outer): %s", exc)
        summary["errors"].append(str(exc))
    finally:
        try:
            trading_conn.close()
        except Exception:
            pass
        try:
            intel_conn.close()
        except Exception:
            pass

    return summary


def get_source_reliability_block() -> str:
    """
    Gibt einen formatierten String für den CEO-Kontext zurück.

    Format:
        --- QUELLEN-ZUVERLÄSSIGKEIT (letzte 30 Tage) ---
        Reuters      WR: 73%  Ø PnL: +4.2€  Signals: 12
        Tradermacher WR: 65%  Ø PnL: +2.8€  Signals: 8
        [Quellen mit <3 Signalen werden nicht angezeigt]

    Returns:
        Formatierter String, oder Fallback-Text bei Fehler.
    """
    try:
        sources = get_top_sources(min_signals=3)
        if not sources:
            return "--- QUELLEN-ZUVERLÄSSIGKEIT ---\n(Noch keine ausreichenden Daten)\n"

        lines = ["--- QUELLEN-ZUVERLÄSSIGKEIT (letzte 30 Tage) ---"]
        for s in sources:
            name     = s["source"][:14].ljust(14)
            wr_pct   = int(s["win_rate"] * 100)
            avg_pnl  = s["avg_pnl_eur"]
            signals  = s["signals_led_to_trade"]
            sign     = "+" if avg_pnl >= 0 else ""
            lines.append(f"  {name} WR: {wr_pct:2d}%  Ø PnL: {sign}{avg_pnl:.1f}€  Signals: {signals}")

        return "\n".join(lines) + "\n"

    except Exception as exc:
        log.error("get_source_reliability_block: %s", exc)
        return "--- QUELLEN-ZUVERLÄSSIGKEIT ---\n(Fehler beim Laden)\n"


def get_top_sources(min_signals: int = 3) -> list[dict]:
    """
    Gibt Liste der Quellen sortiert nach win_rate (absteigend) zurück.
    Nur Quellen mit mindestens min_signals Signalen werden einbezogen.

    Args:
        min_signals: Minimale Anzahl an Signalen die zu Trades geführt haben.

    Returns:
        Liste von dicts mit source, win_rate, avg_pnl_eur, signals_led_to_trade etc.
    """
    try:
        conn = _get_intel_conn()
        if conn is None:
            return []

        rows = conn.execute("""
            SELECT source, total_signals, signals_led_to_trade,
                   winning_trades, losing_trades,
                   total_pnl_eur, win_rate, avg_pnl_eur, last_updated
            FROM source_scores
            WHERE signals_led_to_trade >= ?
            ORDER BY win_rate DESC, avg_pnl_eur DESC
        """, (min_signals,)).fetchall()

        conn.close()
        return [dict(r) for r in rows]

    except Exception as exc:
        log.error("get_top_sources: %s", exc)
        return []


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    report_only = "--report" in sys.argv

    if not report_only:
        print("Aktualisiere source_scores aus geschlossenen Trades...")
        result = update_from_closed_trades()
        print(f"  Trades verarbeitet : {result['trades_processed']}")
        print(f"  Signale gematcht   : {result['signals_matched']}")
        print(f"  Quellen aktualisiert: {result['sources_updated']}")
        if result["errors"]:
            print(f"  Fehler: {len(result['errors'])}")
            for e in result["errors"][:5]:
                print(f"    - {e}")
        print()

    print(get_source_reliability_block())
