#!/usr/bin/env python3
"""
historical_data_seeder.py — Befüllt impact_magnitude_history mit echten Preisdaten.
Nutzt Yahoo Finance um historische Kurse rund um Events zu holen.
Berechnet anschließend magnitude_estimates (Aggregation pro event_type).
"""
import sys
import json
import sqlite3
import math
from datetime import datetime, timedelta
from pathlib import Path

WS = Path('/data/.openclaw/workspace')
DB = WS / 'data/trading.db'
SEED_FILE = WS / 'data/historical_events_seed.json'

try:
    import yfinance as yf
except ImportError:
    print("❌ yfinance nicht installiert. Installiere mit: pip3 install yfinance")
    sys.exit(1)


def get_prices(ticker: str, event_date_str: str):
    """
    Holt Preise rund um ein Event-Datum.
    Returns: (price_before, price_24h, price_1week) oder (None, None, None)
    """
    event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
    start = event_date - timedelta(days=7)
    end = event_date + timedelta(days=14)

    try:
        df = yf.download(
            ticker,
            start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'),
            progress=False,
            auto_adjust=True
        )
    except Exception as e:
        print(f"    ⚠️  Download-Fehler für {ticker}: {e}")
        return None, None, None

    if df.empty:
        return None, None, None

    # Flatten MultiIndex falls vorhanden
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)

    event_date_str_norm = event_date.strftime('%Y-%m-%d')

    # Price before = letzter Schlusskurs VOR event_date
    before_df = df[df.index < event_date_str_norm]
    if before_df.empty:
        return None, None, None
    price_before = float(before_df['Close'].iloc[-1])

    # Price 24h = Schlusskurs am event_date oder nächsten verfügbaren Tag
    on_day_df = df[df.index >= event_date_str_norm]
    if on_day_df.empty:
        return price_before, None, None
    price_24h = float(on_day_df['Close'].iloc[0])

    # Price 1week = Schlusskurs nach 5 Handelstagen
    if len(on_day_df) >= 5:
        price_1week = float(on_day_df['Close'].iloc[4])
    elif len(on_day_df) > 0:
        price_1week = float(on_day_df['Close'].iloc[-1])
    else:
        price_1week = None

    return price_before, price_24h, price_1week


def seed_history(conn: sqlite3.Connection, events: list) -> list:
    """Seeded impact_magnitude_history mit echten Preisdaten."""
    seeded = []
    skipped = 0
    errors = 0

    print(f"\n📥 Seeding {len(events)} Events in impact_magnitude_history...\n")

    for i, ev in enumerate(events):
        ticker = ev['ticker']
        event_date = ev['date']
        event_type = ev['type']
        strategy = ev['strategy']
        direction = ev['direction']
        headline = ev['headline']

        print(f"  [{i+1:02d}/{len(events)}] {event_date} {event_type} ({ticker})")

        price_before, price_24h, price_1week = get_prices(ticker, event_date)

        if price_before is None or price_24h is None:
            print(f"         ⚠️  Keine Preisdaten — übersprungen")
            skipped += 1
            continue

        pct_24h = (price_24h - price_before) / price_before * 100
        pct_1week = (price_1week - price_before) / price_before * 100 if price_1week else None

        print(f"         Before: {price_before:.2f} | +24h: {price_24h:.2f} ({pct_24h:+.2f}%)"
              + (f" | +1W: {price_1week:.2f} ({pct_1week:+.2f}%)" if pct_1week else ""))

        try:
            conn.execute("""
                INSERT OR REPLACE INTO impact_magnitude_history
                (event_type, strategy, impact_direction, proxy_ticker, event_date,
                 headline, price_before, price_24h, price_1week,
                 pct_change_24h, pct_change_1week, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'historical_seed', 0.8)
            """, (
                event_type, strategy, direction, ticker, event_date,
                headline, price_before, price_24h, price_1week,
                round(pct_24h, 4), round(pct_1week, 4) if pct_1week else None
            ))
            seeded.append({
                "type": event_type,
                "strategy": strategy,
                "direction": direction,
                "ticker": ticker,
                "pct_24h": pct_24h,
                "pct_1week": pct_1week,
            })
        except Exception as e:
            print(f"         ❌ Insert-Fehler: {e}")
            errors += 1

    conn.commit()
    print(f"\n✅ Seeded: {len(seeded)} | Übersprungen: {skipped} | Fehler: {errors}")
    return seeded


def compute_magnitude_estimates(conn: sqlite3.Connection):
    """Aggregiert impact_magnitude_history → magnitude_estimates."""
    print("\n📊 Berechne magnitude_estimates...\n")

    rows = conn.execute("""
        SELECT event_type, strategy, impact_direction, proxy_ticker,
               pct_change_24h, pct_change_1week
        FROM impact_magnitude_history
        WHERE pct_change_24h IS NOT NULL
    """).fetchall()

    # Gruppiere nach (event_type, strategy, impact_direction)
    groups = {}
    for event_type, strategy, direction, ticker, pct_24h, pct_1week in rows:
        key = (event_type, strategy, direction)
        if key not in groups:
            groups[key] = {"ticker": ticker, "pcts_24h": [], "pcts_1week": []}
        groups[key]["pcts_24h"].append(pct_24h)
        if pct_1week is not None:
            groups[key]["pcts_1week"].append(pct_1week)

    now = datetime.now().isoformat()
    inserted = 0

    for (event_type, strategy, direction), data in groups.items():
        pcts = data["pcts_24h"]
        pcts_w = data["pcts_1week"]
        n = len(pcts)

        avg_24h = sum(pcts) / n
        avg_1week = sum(pcts_w) / len(pcts_w) if pcts_w else None
        min_pct = min(pcts)
        max_pct = max(pcts)

        # Standard-Abweichung
        if n > 1:
            variance = sum((x - avg_24h) ** 2 for x in pcts) / (n - 1)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0.0

        # Konfidenz: steigt mit mehr Events, max 0.95
        confidence = min(0.95, 0.5 + (n * 0.05))

        conn.execute("""
            INSERT OR REPLACE INTO magnitude_estimates
            (event_type, strategy, impact_direction, proxy_ticker,
             avg_pct_24h, avg_pct_1week, min_pct, max_pct,
             std_dev, n_events, confidence, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_type, strategy, direction, data["ticker"],
            round(avg_24h, 4),
            round(avg_1week, 4) if avg_1week is not None else None,
            round(min_pct, 4),
            round(max_pct, 4),
            round(std_dev, 4),
            n,
            round(confidence, 3),
            now
        ))
        inserted += 1

    conn.commit()
    print(f"✅ {inserted} Einträge in magnitude_estimates berechnet")
    return inserted


def print_summary(conn: sqlite3.Connection, seeded_events: list):
    """Zeigt interessante Statistiken nach dem Seeding."""
    print("\n" + "="*65)
    print("📈 MAGNITUDE SUMMARY — HISTORISCHE IMPACT-STATISTIKEN")
    print("="*65)

    rows = conn.execute("""
        SELECT event_type, impact_direction, avg_pct_24h, avg_pct_1week,
               min_pct, max_pct, std_dev, n_events, confidence
        FROM magnitude_estimates
        ORDER BY ABS(avg_pct_24h) DESC
    """).fetchall()

    if not rows:
        print("Keine Daten.")
        return

    # Gruppiert nach Impact-Direction
    by_direction = {}
    for row in rows:
        d = row[1]
        if d not in by_direction:
            by_direction[d] = []
        by_direction[d].append(row)

    for direction, events in by_direction.items():
        print(f"\n  ── {direction.upper()} ──")
        for (event_type, dir_, avg24, avg1w, mn, mx, std, n, conf) in events:
            sign = "+" if avg24 >= 0 else ""
            w_str = f" | +1W: {sign}{avg1w:.1f}%" if avg1w else ""
            print(f"  {event_type:<35} {sign}{avg24:+.1f}% (Range: {mn:+.1f}–{mx:+.1f}%{w_str}, n={n}, σ={std:.1f}%)")

    # Top-Mover
    print(f"\n  ── TOP 5 GRÖSSTE MOVES (24h ∅) ──")
    top5 = sorted(rows, key=lambda x: abs(x[2]), reverse=True)[:5]
    for (event_type, dir_, avg24, avg1w, mn, mx, std, n, conf) in top5:
        sign = "+" if avg24 >= 0 else ""
        print(f"  {event_type:<35} {sign}{avg24:+.1f}% ({dir_})")

    total = conn.execute("SELECT COUNT(*) FROM impact_magnitude_history").fetchone()[0]
    print(f"\n  📦 Total in impact_magnitude_history: {total} Events")
    print(f"  📊 Total in magnitude_estimates: {len(rows)} Aggregationen")
    print("="*65)


def main():
    print("🚀 historical_data_seeder.py — Albert's Magnitude Database Builder")
    print(f"   DB: {DB}")
    print(f"   Seed-File: {SEED_FILE}")

    # Seed-Datei laden
    with open(SEED_FILE) as f:
        events = json.load(f)
    print(f"   Events geladen: {len(events)}")

    conn = sqlite3.connect(str(DB))

    # Seeding
    seeded = seed_history(conn, events)

    # Aggregation
    compute_magnitude_estimates(conn)

    # Summary
    print_summary(conn, seeded)

    conn.close()
    print("\n✅ Seeding abgeschlossen.")


if __name__ == "__main__":
    main()
