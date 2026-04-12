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

WS = Path('/data/.openclaw/workspace')
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


# ── P6: NEWS-TRADE-KORRELATION ────────────────────────────────────────────────

def correlate_news_to_trades() -> dict:
    """
    Verknüpft overnight_events mit paper_portfolio Trades.
    Zeitfenster: Trades die 0-4h nach dem Event eröffnet wurden.
    Schreibt data/news_trade_correlation.json.
    Returns: dict mit Korrelations-Statistiken.
    """
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Events der letzten 7 Tage
    events = conn.execute("""
        SELECT id, headline, impact_direction, strategies_affected, timestamp
        FROM overnight_events
        WHERE timestamp >= datetime('now', '-7 days')
        ORDER BY timestamp DESC
        LIMIT 300
    """).fetchall()

    correlations = []
    for ev in events:
        ev_time = ev['timestamp']
        strategies_raw = ev['strategies_affected'] or '[]'
        try:
            strategies = json.loads(strategies_raw)
        except Exception:
            strategies = []

        if not strategies:
            continue

        # Trades die 0–4h nach dem Event eröffnet wurden, mit passender Strategie
        placeholders = ','.join(['?' for _ in strategies])
        trades = conn.execute(f"""
            SELECT id, ticker, strategy, entry_price, pnl_eur, pnl_pct,
                   entry_date, status
            FROM paper_portfolio
            WHERE entry_date >= ?
              AND entry_date <= datetime(?, '+4 hours')
              AND strategy IN ({placeholders})
        """, [ev_time, ev_time] + strategies).fetchall()

        for t in trades:
            correlations.append({
                'event_id':       ev['id'],
                'headline':       (ev['headline'] or '')[:120],
                'impact_direction': ev['impact_direction'],
                'trade_id':       t['id'],
                'ticker':         t['ticker'],
                'strategy':       t['strategy'],
                'pnl_eur':        t['pnl_eur'],
                'pnl_pct':        t['pnl_pct'],
                'trade_status':   t['status'],
                'event_time':     ev_time,
                'trade_time':     t['entry_date'],
            })

    conn.close()

    # Aggregierte Statistiken
    closed = [c for c in correlations if c['trade_status'] in ('WIN', 'LOSS', 'CLOSED')]
    profitable = sum(1 for c in closed if (c['pnl_eur'] or 0) > 0)
    losing     = sum(1 for c in closed if (c['pnl_eur'] or 0) < 0)
    avg_pnl    = (sum(c['pnl_eur'] or 0 for c in closed) / len(closed)) if closed else 0.0

    # Beste/schlechteste Impact-Directions nach Ergebnis
    direction_stats: dict[str, dict] = {}
    for c in closed:
        d = c['impact_direction'] or 'unknown'
        if d not in direction_stats:
            direction_stats[d] = {'trades': 0, 'wins': 0, 'pnl': 0.0}
        direction_stats[d]['trades'] += 1
        direction_stats[d]['wins']   += 1 if (c['pnl_eur'] or 0) > 0 else 0
        direction_stats[d]['pnl']    += (c['pnl_eur'] or 0)

    stats = {
        'total_correlations': len(correlations),
        'closed_trades':      len(closed),
        'profitable':         profitable,
        'losing':             losing,
        'avg_pnl_eur':        round(avg_pnl, 2),
        'direction_stats':    direction_stats,
        'updated_at':         datetime.now(timezone.utc).isoformat(),
        'correlations':       correlations[:100],  # Letzte 100 Matches
    }

    output_file = WS / 'data' / 'news_trade_correlation.json'
    output_file.write_text(json.dumps(stats, indent=2, ensure_ascii=False))
    return stats


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

    # ── P6: News-Trade-Korrelation ─────────────────────────────────────
    try:
        corr = correlate_news_to_trades()
        if corr['total_correlations'] > 0:
            print(f"  🔗 News-Trade-Korrelation: {corr['total_correlations']} Matches, "
                  f"{corr['closed_trades']} abgeschl., avg P&L {corr['avg_pnl_eur']:+.2f}€")
    except Exception as e:
        print(f"  ⚠️  News-Trade-Korrelation Fehler: {e}")

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
