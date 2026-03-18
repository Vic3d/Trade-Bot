#!/usr/bin/env python3
"""
Strategy Learner — aggregiert Performance-Daten pro Strategie.

Beantwortet 3 Fragen:
  1. Welche Strategie (S1–S7) hat die beste P&L-Performance?
  2. Welche der 6 Analyse-Dimensionen hat die höchste Trefferquote?
  3. Was sind wiederkehrende Muster bei Gewinn- vs. Verlust-Trades?

Usage:
  python3 strategy_learner.py              → Voller Report
  python3 strategy_learner.py summary      → Kurzzusammenfassung
  python3 strategy_learner.py dimension    → Dimensionen-Accuracy
"""

import sqlite3, json, os, sys, time
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "strategy-learner-report.md")

STRATEGY_NAMES = {
    1: "S1 Iran/Öl",
    2: "S2 Rüstung",
    3: "S3 KI/Tech",
    4: "S4 Silber",
    5: "S5 Rohstoffe",
    6: "S6 Energie-Wende",
    7: "S7 Biotech",
}

DIMENSIONS = ["trend", "news", "macro", "mean_reversion", "event", "risk"]


def get_db():
    return sqlite3.connect(DB_PATH)


def ensure_tables(conn):
    """Stellt sicher dass alle benötigten Tabellen existieren."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dimension_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            strategy_id INTEGER,
            ts INTEGER,
            dimension TEXT,
            signal TEXT,
            price_at_signal REAL,
            price_4h REAL,
            price_24h REAL,
            outcome_4h TEXT,
            outcome_24h TEXT
        )
    """)
    conn.commit()


def log_dimension_signals(ticker: str, strategy_id: int, dimensions: dict, price: float):
    """
    Loggt alle 6 Dimensionssignale für einen Ticker.
    Outcome wird später von evaluate_signals() befüllt.
    """
    conn = get_db()
    ensure_tables(conn)
    ts = int(time.time())
    for dim_key, dim_data in dimensions.items():
        conn.execute("""
            INSERT INTO dimension_signals
            (ticker, strategy_id, ts, dimension, signal, price_at_signal)
            VALUES (?,?,?,?,?,?)
        """, (ticker, strategy_id, ts, dim_key, dim_data.get("signal","neutral"), price))
    conn.commit()
    conn.close()


def evaluate_signals():
    """
    Berechnet Outcomes für offene Signals (4h und 24h nach Signal).
    Outcome: 'correct' wenn Signal-Richtung mit Kursrichtung übereinstimmt.
    """
    import urllib.request
    conn = get_db()
    ensure_tables(conn)

    now = int(time.time())
    # 4h-Outcomes für Signals > 4h alt
    rows_4h = conn.execute("""
        SELECT id, ticker, signal, price_at_signal, ts
        FROM dimension_signals
        WHERE outcome_4h IS NULL AND ts < ? AND ts > ?
    """, (now - 4*3600, now - 7*24*3600)).fetchall()

    for row_id, ticker, signal, entry_price, ts in rows_4h:
        try:
            yahoo_sym = ticker if '.' in ticker or len(ticker) <= 5 else ticker
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1m&range=1d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.load(r)
            current = d["chart"]["result"][0]["meta"]["regularMarketPrice"]
            change_pct = (current - entry_price) / entry_price * 100

            if signal == "bullish":
                outcome = "correct" if change_pct > 0.5 else "wrong" if change_pct < -0.5 else "neutral"
            elif signal == "bearish":
                outcome = "correct" if change_pct < -0.5 else "wrong" if change_pct > 0.5 else "neutral"
            else:
                outcome = "neutral"

            conn.execute("UPDATE dimension_signals SET price_4h=?, outcome_4h=? WHERE id=?",
                        (current, outcome, row_id))
        except:
            pass

    conn.commit()
    conn.close()


def dimension_accuracy_report() -> str:
    """Trefferquote pro Analyse-Dimension."""
    conn = get_db()
    ensure_tables(conn)
    lines = ["## Dimensions-Trefferquote\n"]

    for dim in DIMENSIONS:
        rows = conn.execute("""
            SELECT outcome_4h, COUNT(*) FROM dimension_signals
            WHERE dimension=? AND outcome_4h IS NOT NULL
            GROUP BY outcome_4h
        """, (dim,)).fetchall()
        outcomes = {r[0]: r[1] for r in rows}
        total = sum(outcomes.values())
        if total == 0:
            lines.append(f"- **{dim}**: Noch keine Daten")
            continue
        correct = outcomes.get("correct", 0)
        rate = correct / total * 100
        lines.append(f"- **{dim}**: {rate:.0f}% korrekt ({correct}/{total})")

    conn.close()
    return "\n".join(lines)


def strategy_performance_report() -> str:
    """P&L-Performance und Trefferquote pro Strategie."""
    conn = get_db()
    lines = ["## Strategie-Performance\n"]

    for s_id, s_name in STRATEGY_NAMES.items():
        trades = conn.execute("""
            SELECT ticker, entry_price, exit_price, outcome, direction
            FROM trades WHERE strategy_id=?
        """, (s_id,)).fetchall()

        if not trades:
            continue

        open_trades = [(t, ep, None) for t, ep, xp, o, d in trades if o == 'open']
        closed = [(t, ep, xp, d) for t, ep, xp, o, d in trades if o in ('win', 'loss', 'closed')]

        pnls = []
        for t, ep, xp, d in closed:
            if ep and xp:
                pnl = (xp - ep) / ep * 100 if d == 'LONG' else (ep - xp) / ep * 100
                pnls.append(pnl)

        win_rate = len([p for p in pnls if p > 0]) / len(pnls) * 100 if pnls else None
        avg_pnl = sum(pnls) / len(pnls) if pnls else None

        status = []
        if pnls:
            status.append(f"{len(closed)} geschlossen | Win-Rate {win_rate:.0f}% | Avg P&L {avg_pnl:+.1f}%")
        if open_trades:
            status.append(f"{len(open_trades)} offen")
        if not status:
            status.append("keine Trades")

        lines.append(f"- **{s_name}**: {' | '.join(status)}")

    conn.close()
    return "\n".join(lines)


def pattern_analysis() -> str:
    """Welche Muster tauchen bei Gewinn- vs. Verlust-Trades auf?"""
    conn = get_db()
    lines = ["## Muster-Analyse (Gewinn vs. Verlust)\n"]

    # Welche Strategien performen bei welchem VIX-Regime?
    rows = conn.execute("""
        SELECT t.strategy_id, t.outcome, m.regime, COUNT(*)
        FROM trades t
        JOIN macro_context m ON ABS(t.ts_entry - m.ts) < 3600
        WHERE t.outcome IN ('win','loss')
        GROUP BY t.strategy_id, t.outcome, m.regime
    """).fetchall()

    if not rows:
        lines.append("_Noch zu wenig Daten für Muster-Analyse. Wird nach ersten geschlossenen Trades befüllt._")
    else:
        for s_id, outcome, regime, count in rows:
            lines.append(f"- {STRATEGY_NAMES.get(s_id, f'S{s_id}')} | {outcome} | VIX-Regime: {regime} | {count}×")

    conn.close()
    return "\n".join(lines)


def write_full_report():
    """Schreibt vollständigen Lern-Report in memory/strategy-learner-report.md"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = [
        f"# Strategy Learner Report\n*Generiert: {now}*\n",
        strategy_performance_report(),
        "",
        dimension_accuracy_report(),
        "",
        pattern_analysis(),
        "",
        "---",
        f"*Nächste Auswertung: sobald erste Trades geschlossen werden*",
    ]
    report = "\n".join(sections)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "evaluate":
        evaluate_signals()
        print("Outcomes aktualisiert.")
    elif mode == "dimension":
        print(dimension_accuracy_report())
    elif mode == "summary":
        print(strategy_performance_report())
    elif mode == "full":
        report = write_full_report()
        print(report)
