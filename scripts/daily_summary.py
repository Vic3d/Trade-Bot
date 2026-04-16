#!/usr/bin/env python3
"""
Daily Summary — schreibt DB-Zusammenfassung in die tägliche memory-Datei.
Wird vom Tagesabschluss-Cron (23:00) aufgerufen.
Damit liest Albert beim nächsten Session-Start automatisch was gestern passiert ist.
"""

import sqlite3, os, time
from datetime import datetime, timezone, timedelta

DB_PATH   = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
MEM_DIR   = os.path.join(os.path.dirname(__file__), "..", "memory")

def _conn():
    return sqlite3.connect(DB_PATH)

def today_str():
    return datetime.now(tz=timezone(timedelta(hours=1))).strftime("%Y-%m-%d")

def _safe_query(conn, sql, params=()):
    """Execute a query, return [] if the table doesn't exist."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def generate_summary() -> str:
    conn = _conn()
    today_ts = int(time.time()) - 86400  # letzte 24h
    lines = []

    # ── NewsWire Events heute ──────────────────────────────────────────────────
    events = _safe_query(conn, """
        SELECT strategy_id, direction, COUNT(*) as n
        FROM events
        WHERE ts > ? AND score >= 2
        GROUP BY strategy_id, direction
        ORDER BY strategy_id, direction
    """, (today_ts,))

    STRAT = {1:"Iran/Öl", 2:"Rüstung", 3:"KI/Tech", 4:"Silber", 5:"Rohstoffe", None:"Makro"}
    if events:
        lines.append("## NewsWire — Events heute (score≥2)")
        for sid, direction, n in events:
            emoji = "✅" if direction == "bullish" else "⚠️" if direction == "bearish" else "—"
            lines.append(f"  {emoji} S{sid or '-'} {STRAT.get(sid,'?'):10} {direction:8}: {n}×")

    # ── Top Headlines heute ────────────────────────────────────────────────────
    top = _safe_query(conn, """
        SELECT ticker, direction, headline, score
        FROM events
        WHERE ts > ? AND score >= 2
        ORDER BY score DESC, ts DESC
        LIMIT 8
    """, (today_ts,))

    if top:
        lines.append("\n## Top Headlines heute")
        for ticker, direction, headline, score in top:
            emoji = "✅" if direction == "bullish" else "⚠️" if direction == "bearish" else "—"
            t = f"[{ticker}]" if ticker else ""
            lines.append(f"  {emoji} score={score} {t} {headline[:90]}")

    # ── Offene Trades (legacy — Tabelle existiert ggf. nicht) ─────────────────
    trades = _safe_query(conn, """
        SELECT ticker, direction, entry_price, stop_price, conviction_score, notes
        FROM trades WHERE outcome = 'open'
        ORDER BY ts_entry DESC
    """)

    if trades:
        lines.append("\n## Offene Positionen (Trade Journal)")
        for ticker, direction, entry, stop, conv, notes in trades:
            stop_str = f"Stop {stop}€" if stop else "KEIN STOP ⚠️"
            lines.append(f"  {ticker}: {direction.upper()} @ {entry}€ | {stop_str} | Conviction {conv or '?'}/5")

    # ── Empfehlungen heute ─────────────────────────────────────────────────────
    recs = _safe_query(conn, """
        SELECT ticker, direction, conviction_score, reasoning, correct_4h
        FROM recommendations
        WHERE ts > ?
        ORDER BY ts DESC
    """, (today_ts,))

    if recs:
        lines.append("\n## Alberts Empfehlungen heute")
        for ticker, direction, score, reasoning, correct_4h in recs:
            outcome = "✅ richtig" if correct_4h == 1 else "❌ falsch" if correct_4h == 0 else "⏳ offen"
            lines.append(f"  {ticker} {direction} (Conv {score}/5): {outcome}")
            if reasoning:
                lines.append(f"    Begründung: {reasoning[:100]}")

    # ── Accuracy-Snapshot ─────────────────────────────────────────────────────
    acc_rows = _safe_query(conn, """
        SELECT COUNT(*) as n,
               SUM(correct_4h) as correct,
               ROUND(100.0 * SUM(correct_4h) / COUNT(*), 0) as pct
        FROM recommendations
        WHERE correct_4h IS NOT NULL
    """)
    acc = acc_rows[0] if acc_rows else None

    if acc and acc[0] and acc[0] >= 5:
        lines.append(f"\n## Alberts Accuracy (gesamt)")
        lines.append(f"  4h-Trefferquote: {acc[2]:.0f}% ({acc[1]}/{acc[0]} Empfehlungen ausgewertet)")

    # ── Makro-Kontext ──────────────────────────────────────────────────────────
    macro_rows = _safe_query(conn, """
        SELECT vix, dxy, brent, regime
        FROM macro_context
        ORDER BY ts DESC LIMIT 1
    """)
    macro = macro_rows[0] if macro_rows else None

    if macro:
        vix, dxy, brent, regime = macro
        emoji = {"green":"🟢","yellow":"🟡","orange":"🟠","red":"🔴"}.get(regime,"⚪")
        lines.append(f"\n## Makro-Kontext (letzter Stand)")
        lines.append(f"  VIX: {vix:.1f} {emoji} ({regime}) | DXY: {dxy:.1f} | Brent: ${brent:.2f}")

    conn.close()
    return "\n".join(lines) if lines else "Keine relevanten Events heute."


def append_to_daily(summary: str):
    """Hängt Summary an die tägliche memory-Datei an."""
    date = today_str()
    path = os.path.join(MEM_DIR, f"{date}.md")
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    section = f"\n## Tagesabschluss-Zusammenfassung ({ts})\n\n{summary}\n"

    if os.path.exists(path):
        with open(path, "a") as f:
            f.write(section)
    else:
        with open(path, "w") as f:
            f.write(f"# {date}\n{section}")

    return path


if __name__ == "__main__":
    summary = generate_summary()
    print(summary)
    path = append_to_daily(summary)
    print(f"\n→ Gespeichert in: {path}")
