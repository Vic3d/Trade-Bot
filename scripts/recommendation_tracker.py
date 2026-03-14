#!/usr/bin/env python3
"""
Recommendation Tracker — loggt Alberts Empfehlungen und wertet sie retrospektiv aus.

Wird aufgerufen:
  - Von Briefing-Crons: log_recommendation(...)
  - Von Price-Tracker-Cron: evaluate_pending()
  - Von Albert direkt: accuracy_report()
"""

import sqlite3, time, json, os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "albert-accuracy.md")

def _conn():
    return sqlite3.connect(DB_PATH)

def now_ts():
    return int(time.time())

# ── Empfehlung loggen ──────────────────────────────────────────────────────────

def log_recommendation(
    ticker: str,
    direction: str,           # bullish / bearish / neutral
    reasoning: str,           # Warum — in 1-2 Sätzen
    key_factors: list,        # z.B. ["hormuz_direct", "brent_100", "vix_orange"]
    conviction_score: int,    # 1-5
    price_at_rec: float,
    strategy_id: int = None,
    source: str = "briefing", # briefing / analyst_cron / manual
) -> int:
    """Loggt eine neue Empfehlung. Gibt die ID zurück."""
    conn = _conn()

    # Aktuellen VIX holen
    vix_row = conn.execute(
        "SELECT vix FROM macro_context ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    vix = vix_row[0] if vix_row else None

    cursor = conn.execute("""
        INSERT INTO recommendations (
            ts, ticker, direction, reasoning, key_factors,
            conviction_score, vix_at_rec, price_at_rec, strategy_id, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now_ts(), ticker.upper(), direction,
        reasoning, json.dumps(key_factors),
        conviction_score, vix, price_at_rec,
        strategy_id, source
    ))
    rec_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return rec_id


# ── Auswertung: Preis nachschreiben + Outcome bewerten ────────────────────────

def evaluate_pending():
    """
    Prüft offene Empfehlungen und schreibt Outcomes wenn genug Zeit vergangen ist.
    Läuft als Teil des Price-Tracker-Crons.
    """
    conn = _conn()
    pending = conn.execute("""
        SELECT id, ts, ticker, direction, price_at_rec,
               price_4h, price_1d, price_1w, evaluated
        FROM recommendations
        WHERE evaluated = 0
        ORDER BY ts ASC
        LIMIT 50
    """).fetchall()

    updated = 0
    for rec_id, ts, ticker, direction, price_at, p4h, p1d, p1w, _ in pending:
        age = now_ts() - ts
        changed = False

        # Preis holen (vereinfacht — aus letztem Price-Tracker-Lauf)
        # Hier nehmen wir den letzten bekannten Kurs aus events-Tabelle
        price_row = conn.execute("""
            SELECT price_at_event FROM events
            WHERE ticker LIKE ? AND price_at_event IS NOT NULL
            ORDER BY ts DESC LIMIT 1
        """, (f"%{ticker}%",)).fetchone()

        current_price = price_row[0] if price_row else None

        if current_price and price_at:
            move = (current_price - price_at) / price_at

            # 4h Outcome
            if p4h is None and age >= 14400:
                outcome = _calc_outcome(direction, move)
                correct = 1 if outcome == "correct" else 0
                conn.execute("""
                    UPDATE recommendations
                    SET price_4h=?, outcome_4h=?, correct_4h=?
                    WHERE id=?
                """, (round(current_price, 3), outcome, correct, rec_id))
                changed = True

            # 1d Outcome
            if p1d is None and age >= 86400:
                outcome = _calc_outcome(direction, move)
                correct = 1 if outcome == "correct" else 0
                conn.execute("""
                    UPDATE recommendations
                    SET price_1d=?, outcome_1d=?, correct_1d=?
                    WHERE id=?
                """, (round(current_price, 3), outcome, correct, rec_id))
                changed = True

            # 1w Outcome — als "evaluated" markieren
            if p1w is None and age >= 604800:
                outcome = _calc_outcome(direction, move)
                correct = 1 if outcome == "correct" else 0
                conn.execute("""
                    UPDATE recommendations
                    SET price_1w=?, outcome_1w=?, correct_1w=?, evaluated=1
                    WHERE id=?
                """, (round(current_price, 3), outcome, correct, rec_id))
                changed = True

        if changed:
            updated += 1

    conn.commit()
    conn.close()
    return updated


def _calc_outcome(direction: str, move: float) -> str:
    threshold = 0.005  # 0.5% Mindestbewegung
    if direction == "bullish":
        return "correct" if move > threshold else "wrong" if move < -threshold else "neutral"
    elif direction == "bearish":
        return "correct" if move < -threshold else "wrong" if move > threshold else "neutral"
    return "neutral"


# ── Accuracy Report ───────────────────────────────────────────────────────────

def accuracy_report(min_recs: int = 5) -> str:
    """Zeigt Alberts Trefferquote nach Strategie, Conviction, VIX-Regime."""
    conn = _conn()

    total = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
    if total < min_recs:
        conn.close()
        return f"Noch zu wenig Daten ({total} Empfehlungen, min {min_recs} nötig)"

    lines = [f"# Alberts Empfehlungs-Accuracy ({total} total)\n"]

    # Nach Strategie
    lines.append("## Nach Strategie (4h-Fenster)")
    rows = conn.execute("""
        SELECT strategy_id,
               COUNT(*) as n,
               SUM(correct_4h) as correct,
               AVG(ABS((price_4h - price_at_rec) / price_at_rec * 100)) as avg_move
        FROM recommendations
        WHERE correct_4h IS NOT NULL
        GROUP BY strategy_id
        ORDER BY strategy_id
    """).fetchall()
    STRAT_NAMES = {1:"Iran/Öl", 2:"Rüstung", 3:"KI/Tech", 4:"Silber/Gold", 5:"Rohstoffe", None:"Kein Tag"}
    for sid, n, correct, avg_move in rows:
        wr = (correct/n*100) if n else 0
        name = STRAT_NAMES.get(sid, f"S{sid}")
        lines.append(f"  S{sid or '-'} {name:12}: {wr:.0f}% ({correct}/{n}) | Avg Move: {avg_move:.1f}%")

    # Nach Conviction Score
    lines.append("\n## Nach Conviction Score (4h-Fenster)")
    rows = conn.execute("""
        SELECT conviction_score,
               COUNT(*) as n,
               SUM(correct_4h) as correct
        FROM recommendations
        WHERE correct_4h IS NOT NULL
        GROUP BY conviction_score
        ORDER BY conviction_score DESC
    """).fetchall()
    for score, n, correct in rows:
        wr = (correct/n*100) if n else 0
        bar = "█" * int(wr/10) + "░" * (10 - int(wr/10))
        lines.append(f"  Score {score}/5: {wr:.0f}% [{bar}] ({n} Empfehlungen)")

    # Nach VIX-Regime
    lines.append("\n## Nach VIX-Regime (4h-Fenster)")
    rows = conn.execute("""
        SELECT
            CASE
                WHEN vix_at_rec < 20 THEN 'green (<20)'
                WHEN vix_at_rec < 25 THEN 'yellow (20-25)'
                WHEN vix_at_rec < 30 THEN 'orange (25-30)'
                ELSE 'red (>30)'
            END as regime,
            COUNT(*) as n,
            SUM(correct_4h) as correct
        FROM recommendations
        WHERE correct_4h IS NOT NULL AND vix_at_rec IS NOT NULL
        GROUP BY regime
        ORDER BY vix_at_rec ASC
    """).fetchall()
    for regime, n, correct in rows:
        wr = (correct/n*100) if n else 0
        lines.append(f"  {regime:18}: {wr:.0f}% ({n} Empfehlungen)")

    # Gesamtbilanz
    overall = conn.execute("""
        SELECT
            COUNT(*) as n,
            SUM(correct_4h) as c4h,
            SUM(correct_1d) as c1d,
            SUM(correct_1w) as c1w
        FROM recommendations
        WHERE correct_4h IS NOT NULL
    """).fetchone()
    conn.close()
    if overall and overall[0]:
        n, c4h, c1d, c1w = overall
        lines.append(f"\n## Gesamtbilanz")
        lines.append(f"  4h:  {(c4h or 0)/n*100:.0f}% richtig ({n} Empfehlungen)")
        if c1d: lines.append(f"  1d:  {c1d/n*100:.0f}% richtig")
        if c1w: lines.append(f"  1w:  {c1w/n*100:.0f}% richtig")

    return "\n".join(lines)


def write_accuracy_report():
    """Schreibt aktuellen Accuracy Report in Datei."""
    report = accuracy_report(min_recs=1)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    with open(REPORT_PATH, "w") as f:
        f.write(f"# Albert Accuracy Report\n*Letzte Aktualisierung: {ts}*\n\n")
        f.write(report)
    return REPORT_PATH


if __name__ == "__main__":
    print(accuracy_report(min_recs=1))
    print(f"\nPending evaluations: {evaluate_pending()} aktualisiert")
