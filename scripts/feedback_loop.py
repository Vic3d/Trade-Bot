#!/usr/bin/env python3
"""
feedback_loop.py — Signal-Kalibrierung für overnight_events
Misst Preis-Reaktion nach 30min / 2h / 24h und kalibriert Impact-Scores.

Verwendung:
  python3 feedback_loop.py          → run_feedback_loop() + Report ausgeben
  python3 feedback_loop.py --init   → DB-Migration (neue Spalten + Tabelle)
"""
import sqlite3
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB = WS / 'data/trading.db'

# Strategie → Yahoo Finance Ticker (Preis-Proxy)
STRATEGY_PRICE_PROXY = {
    "S1":  "BZ=F",       # Brent Crude
    "S2":  "^STOXX50E",  # EuroStoxx 50 / Defense-Proxy
    "S3":  "QQQ",        # Tech ETF
    "S4":  "PHAG.L",     # Silber ETC
    "S5":  "HG=F",       # Kupfer
    "S8":  "FRO",        # Tanker (Frontline)
    "S9":  "BZ=F",       # Kuba → Öl-Proxy
    "S10": "LHA.DE",     # Lufthansa
    "S11": "AG",         # First Majestic Silver
}

# Welche Preisbewegung gilt als "korrekt" für eine Impact-Direction?
# Format: (direction, proxy_symbol, min_pct_change, check_field)
# Positive min_pct → Preis soll steigen; Negative → soll fallen
DIRECTION_THRESHOLDS = {
    "bullish_oil":       ("BZ=F",       +1.0),
    "bearish_oil":       ("BZ=F",       -1.0),
    "bullish_defense":   ("^STOXX50E",  +0.5),
    "bullish_tech":      ("QQQ",        +0.5),
    "bullish_metals":    ("HG=F",       +0.5),
    "bearish_airlines":  ("LHA.DE",     -0.5),
    "geopolitical_watchlist": ("BZ=F",  +0.5),
    "watchlist":         ("BZ=F",       +0.0),
    "watchlist_S9":      ("BZ=F",       +0.5),
}


# ── DB MIGRATION ─────────────────────────────────────────────────────────────

def migrate_db(conn: sqlite3.Connection):
    """Fügt neue Spalten + Tabelle hinzu, falls noch nicht vorhanden."""
    cur = conn.cursor()

    # Bestehende Spalten der overnight_events Tabelle
    existing = {row[1] for row in cur.execute("PRAGMA table_info(overnight_events)").fetchall()}

    new_cols = {
        "price_at_flag":    "REAL",
        "price_30min":      "REAL",
        "price_2h":         "REAL",
        "price_24h":        "REAL",
        "actual_direction": "TEXT",
        "prediction_correct": "INTEGER",
    }

    for col, dtype in new_cols.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE overnight_events ADD COLUMN {col} {dtype}")
                print(f"  ✓ Spalte hinzugefügt: overnight_events.{col}")
            except Exception as e:
                print(f"  ⚠️  {col}: {e}")

    # impact_calibration Tabelle
    cur.execute("""
        CREATE TABLE IF NOT EXISTS impact_calibration (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy          TEXT,
            impact_direction  TEXT,
            keyword_pattern   TEXT,
            total_predictions INTEGER DEFAULT 0,
            correct_predictions INTEGER DEFAULT 0,
            accuracy          REAL DEFAULT 0.5,
            last_updated      TEXT
        )
    """)

    conn.commit()


# ── PREIS-ABRUF ──────────────────────────────────────────────────────────────

def fetch_price(ticker: str) -> float | None:
    """Holt aktuellen Kurs via Yahoo Finance yfinance API."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
        if price and price > 0:
            return round(float(price), 4)
    except Exception:
        pass

    # Fallback: Yahoo Finance Chart-API
    try:
        enc = urllib.parse.quote(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?interval=1d&range=1d"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AlbertFeedback/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return round(float(price), 4)
    except Exception as e:
        print(f"    ⚠️  Preis-Abruf {ticker} fehlgeschlagen: {e}")
        return None


def get_proxy_for_strategies(strategies: list) -> str | None:
    """Gibt den Preis-Proxy-Ticker für eine Liste von Strategien zurück."""
    for s in strategies:
        key = s.split("_")[0] if "_" in s else s  # S1_Iran_Oil → S1
        if key in STRATEGY_PRICE_PROXY:
            return STRATEGY_PRICE_PROXY[key]
    return None


# ── PREISCHECK-LOGIK ─────────────────────────────────────────────────────────

def set_price_at_flag(conn: sqlite3.Connection, event_id: int,
                       strategies: list, timestamp: str):
    """Setzt price_at_flag für ein neues Event (wird beim INSERT aufgerufen)."""
    ticker = get_proxy_for_strategies(strategies)
    if not ticker:
        return

    price = fetch_price(ticker)
    if price:
        conn.execute(
            "UPDATE overnight_events SET price_at_flag = ? WHERE id = ?",
            (price, event_id)
        )
        print(f"    💰 price_at_flag={price} ({ticker}) für Event #{event_id}")


def run_price_checks(conn: sqlite3.Connection) -> int:
    """
    Führt 30min / 2h / 24h Preis-Checks für alle ausstehenden Events durch.
    Gibt Anzahl der aktualisierten Events zurück.
    """
    now = datetime.now(timezone.utc)
    updated = 0

    # Events mit price_at_flag aber fehlenden Follow-up-Preisen
    rows = conn.execute("""
        SELECT id, timestamp, strategies_affected, impact_direction,
               price_at_flag, price_30min, price_2h, price_24h
        FROM overnight_events
        WHERE price_at_flag IS NOT NULL
          AND (price_30min IS NULL OR price_2h IS NULL OR price_24h IS NULL)
        ORDER BY timestamp ASC
        LIMIT 100
    """).fetchall()

    for row in rows:
        ev_id, ts_str, strategies_json, impact_dir, p_flag, p_30, p_2h, p_24h = row

        try:
            strategies = json.loads(strategies_json or "[]")
        except Exception:
            strategies = []

        ticker = get_proxy_for_strategies(strategies)
        if not ticker:
            continue

        # Parse timestamp
        try:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"]:
                try:
                    ev_time = datetime.strptime(ts_str[:19], fmt[:len(ts_str[:19])])
                    ev_time = ev_time.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                continue
        except Exception:
            continue

        age_minutes = (now - ev_time).total_seconds() / 60

        # Aktuellen Preis holen (einmal pro Event, mehrfach nutzen)
        current_price = None

        if p_30 is None and age_minutes >= 30:
            current_price = current_price or fetch_price(ticker)
            if current_price:
                conn.execute(
                    "UPDATE overnight_events SET price_30min = ? WHERE id = ?",
                    (current_price, ev_id)
                )
                updated += 1

        if p_2h is None and age_minutes >= 120:
            current_price = current_price or fetch_price(ticker)
            if current_price:
                conn.execute(
                    "UPDATE overnight_events SET price_2h = ? WHERE id = ?",
                    (current_price, ev_id)
                )
                updated += 1

        if p_24h is None and age_minutes >= 1440:
            current_price = current_price or fetch_price(ticker)
            if current_price:
                conn.execute(
                    "UPDATE overnight_events SET price_24h = ? WHERE id = ?",
                    (current_price, ev_id)
                )
                updated += 1

    conn.commit()
    return updated


# ── KALIBRIERUNG ─────────────────────────────────────────────────────────────

def _calc_direction(price_flag: float, price_24h: float) -> str:
    """Berechnet tatsächliche Preisrichtung aus Preis-Delta."""
    if price_flag and price_24h:
        pct = (price_24h - price_flag) / price_flag * 100
        if pct >= 1.0:
            return "up"
        elif pct <= -1.0:
            return "down"
    return "flat"


def _is_prediction_correct(impact_direction: str, actual_dir: str) -> int:
    """Gibt 1 zurück wenn Prediction korrekt, 0 wenn falsch."""
    if impact_direction in ("bullish_oil", "bullish_defense", "bullish_tech",
                            "bullish_metals", "geopolitical_watchlist", "watchlist_S9"):
        return 1 if actual_dir == "up" else 0
    elif impact_direction in ("bearish_oil", "bearish_airlines"):
        return 1 if actual_dir == "down" else 0
    elif impact_direction == "watchlist":
        return 1 if actual_dir in ("up", "down") else 0
    return 0


def update_calibration(conn: sqlite3.Connection) -> int:
    """
    Berechnet actual_direction + prediction_correct für Events mit price_24h.
    Updated impact_calibration Tabelle.
    Gibt Anzahl der neu kalibrierten Events zurück.
    """
    # Events mit price_24h aber ohne actual_direction
    rows = conn.execute("""
        SELECT id, impact_direction, strategies_affected,
               price_at_flag, price_24h
        FROM overnight_events
        WHERE price_24h IS NOT NULL
          AND actual_direction IS NULL
    """).fetchall()

    calibrated = 0
    for ev_id, impact_dir, strategies_json, p_flag, p_24h in rows:
        if not p_flag or not p_24h:
            continue

        actual_dir = _calc_direction(p_flag, p_24h)
        correct = _is_prediction_correct(impact_dir, actual_dir)

        conn.execute("""
            UPDATE overnight_events
            SET actual_direction = ?, prediction_correct = ?
            WHERE id = ?
        """, (actual_dir, correct, ev_id))

        # impact_calibration updaten
        strategies = json.loads(strategies_json or "[]")
        strategy = strategies[0].split("_")[0] if strategies else "unknown"

        existing = conn.execute("""
            SELECT id, total_predictions, correct_predictions
            FROM impact_calibration
            WHERE strategy = ? AND impact_direction = ?
        """, (strategy, impact_dir)).fetchone()

        now_str = datetime.now().isoformat()
        if existing:
            cal_id, total, correct_count = existing
            new_total = total + 1
            new_correct = correct_count + correct
            new_acc = new_correct / new_total if new_total > 0 else 0.5
            conn.execute("""
                UPDATE impact_calibration
                SET total_predictions = ?, correct_predictions = ?,
                    accuracy = ?, last_updated = ?
                WHERE id = ?
            """, (new_total, new_correct, new_acc, now_str, cal_id))
        else:
            conn.execute("""
                INSERT INTO impact_calibration
                (strategy, impact_direction, total_predictions,
                 correct_predictions, accuracy, last_updated)
                VALUES (?, ?, 1, ?, ?, ?)
            """, (strategy, impact_dir, correct, float(correct), now_str))

        calibrated += 1

    conn.commit()
    return calibrated


# ── REPORT ────────────────────────────────────────────────────────────────────

def generate_calibration_report(conn: sqlite3.Connection) -> str:
    """Generiert Kalibrierungs-Report für das Morgen-Briefing."""
    rows = conn.execute("""
        SELECT strategy, impact_direction, total_predictions,
               correct_predictions, accuracy
        FROM impact_calibration
        WHERE total_predictions >= 3
        ORDER BY total_predictions DESC
        LIMIT 15
    """).fetchall()

    if not rows:
        return "📊 Signal-Kalibrierung: Noch keine ausreichenden Daten (mind. 3 Events pro Signal nötig)."

    lines = ["📊 **Signal-Kalibrierung** (abgeschlossene Events):"]
    for strategy, direction, total, correct, acc in rows:
        pct = round(acc * 100)
        badge = "✅" if pct >= 60 else "⚠️" if pct >= 45 else "❌"
        lines.append(f"  {badge} {strategy} {direction}: {pct}% korrekt ({correct}/{total})")

    return "\n".join(lines)


# ── NEWS-TRADE KORRELATION ───────────────────────────────────────────────────

def correlate_news_to_trades():
    """
    Korreliert overnight_events mit paper_portfolio Trades.
    Schreibt Ergebnis nach data/news_trade_correlation.json.
    """
    try:
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row

        # Events der letzten 30 Tage mit strategies_affected
        events = conn.execute("""
            SELECT id, headline, timestamp, impact_direction, strategies_affected
            FROM overnight_events
            WHERE datetime(timestamp) >= datetime('now', '-30 days')
              AND strategies_affected IS NOT NULL
              AND strategies_affected != '[]'
              AND strategies_affected != ''
            ORDER BY timestamp DESC
        """).fetchall()

        correlations = []
        aggregated = {}

        for ev in events:
            try:
                strats = json.loads(ev['strategies_affected'] or '[]')
            except Exception:
                strats = []
            if not strats:
                continue

            ev_ts = ev['timestamp'] or ''
            impact_dir = ev['impact_direction'] or 'unknown'
            headline = ev['headline'] or ''

            for strat_raw in strats:
                strategy = strat_raw.split('_')[0] if '_' in strat_raw else strat_raw

                # Find CLOSED trades with matching strategy, entry within 4h of event
                trades = conn.execute("""
                    SELECT id, ticker, strategy, pnl_eur, pnl_pct, entry_date
                    FROM paper_portfolio
                    WHERE status IN ('WIN', 'CLOSED', 'LOSS')
                      AND strategy = ?
                      AND abs(julianday(entry_date) - julianday(?)) <= (4.0/24.0)
                """, (strategy, ev_ts)).fetchall()

                for t in trades:
                    pnl = float(t['pnl_eur'] or 0)
                    won = 1 if pnl > 0 else 0
                    correlations.append({
                        'event_headline': headline,
                        'impact_direction': impact_dir,
                        'strategy': strategy,
                        'trade_pnl': round(pnl, 2),
                        'trade_won': won,
                    })

                    key = (strategy, impact_dir)
                    if key not in aggregated:
                        aggregated[key] = {'wins': 0, 'total_pnl': 0.0, 'count': 0}
                    aggregated[key]['count'] += 1
                    aggregated[key]['wins'] += won
                    aggregated[key]['total_pnl'] += pnl

        conn.close()

        # Build summary
        summary = []
        for (strategy, impact_dir), stats in aggregated.items():
            n = stats['count']
            summary.append({
                'strategy': strategy,
                'impact_direction': impact_dir,
                'win_rate': round(stats['wins'] / n, 3) if n > 0 else 0,
                'avg_pnl': round(stats['total_pnl'] / n, 2) if n > 0 else 0,
                'sample_size': n,
            })

        output = {
            'generated': datetime.now().isoformat(),
            'correlations': correlations,
            'aggregated': summary,
        }

        out_path = WS / 'data' / 'news_trade_correlation.json'
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"  news_trade_correlation.json: {len(correlations)} Korrelationen, {len(summary)} Aggregate")

    except Exception as e:
        print(f"  correlate_news_to_trades Fehler (nicht kritisch): {e}")


# ── HAUPTFUNKTION ─────────────────────────────────────────────────────────────

def run_feedback_loop() -> str:
    """
    Führt alle Feedback-Loop-Schritte aus:
    1. DB migrieren (idempotent)
    2. Ausstehende Preis-Checks abarbeiten
    3. Kalibrierung berechnen
    4. Report zurückgeben
    """
    conn = sqlite3.connect(str(DB))
    migrate_db(conn)

    updated = run_price_checks(conn)
    calibrated = update_calibration(conn)
    report = generate_calibration_report(conn)

    conn.close()

    if updated > 0 or calibrated > 0:
        print(f"  🔁 Feedback-Loop: {updated} Preise aktualisiert, {calibrated} Events kalibriert")

    correlate_news_to_trades()

    return report


# ── STANDALONE ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--init" in sys.argv:
        conn = sqlite3.connect(str(DB))
        migrate_db(conn)
        conn.close()
        print("✅ DB Migration abgeschlossen")
    else:
        print("🔁 Starte Feedback-Loop...")
        report = run_feedback_loop()
        print("\n" + report)
