#!/usr/bin/env python3
"""
Daily Snapshot — schreibt täglich einen vollständigen State-Snapshot.
Läuft als Cron 23:00. Überschreibt memory/state-snapshot.md.

Zweck: Albert liest diese Datei am Session-Start und weiß sofort
       wo er war, was offen ist, was gerade läuft.
"""

import sqlite3, os, json, time
from datetime import datetime, timezone

DB_PATH   = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
OUT_PATH  = os.path.join(os.path.dirname(__file__), "..", "memory", "state-snapshot.md")
ANALYSIS  = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire-analysis.md")

def run():
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"# State Snapshot — {ts}", "*Automatisch generiert um 23:00. Nicht manuell bearbeiten.*\n"]

    # ── 1. Offene Trades — SINGLE SOURCE OF TRUTH: trading_config.json ─────────
    lines.append("## Offene Positionen")
    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from portfolio import Portfolio
        portfolio = Portfolio()
        real_positions = [p for p in portfolio.real_positions() if p.is_open]
        if real_positions:
            for pos in real_positions:
                stop_str = f"Stop {pos.stop_eur}€" if pos.stop_eur else "⚠️ KEIN STOP"
                lines.append(f"- **{pos.ticker}** LONG @ {pos.entry_eur}€ | {stop_str} | {pos.strategy or 'S?'}")
                if pos.notes:
                    lines.append(f"  _{pos.notes}_")
        else:
            lines.append("_Keine offenen Positionen_")
        trades = real_positions  # für Zähler unten
    except Exception as e:
        # Fallback auf newswire.db wenn portfolio.py nicht verfügbar
        trades = conn.execute("""
            SELECT ticker, direction, entry_price, stop_price, strategy_id, notes
            FROM trades WHERE outcome='open' ORDER BY ts_entry ASC
        """).fetchall()
        if trades:
            for ticker, direction, entry, stop, strat, notes in trades:
                stop_str = f"Stop {stop}€" if stop else "⚠️ KEIN STOP"
                lines.append(f"- **{ticker}** {direction.upper()} @ {entry}€ | {stop_str} | S{strat or '-'}")
                if notes:
                    lines.append(f"  _{notes}_")
        else:
            lines.append("_Keine offenen Positionen_")

    # ── 2. Makro-Kontext ──────────────────────────────────────────────────────
    lines.append("\n## Makro-Kontext (letzter Stand)")
    macro = conn.execute(
        "SELECT vix, dxy, brent, regime FROM macro_context ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if macro:
        vix, dxy, brent, regime = macro
        regime_emoji = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}.get(regime, "⚪")
        lines.append(f"- VIX: {vix:.1f} {regime_emoji} ({regime})")
        lines.append(f"- DXY: {dxy:.2f}" if dxy else "- DXY: N/A")
        lines.append(f"- Brent: ${brent:.2f}" if brent else "- Brent: N/A")
    else:
        lines.append("_Noch kein Makro-Kontext_")

    # ── 3. NewsWire Stats ─────────────────────────────────────────────────────
    lines.append("\n## NewsWire — Letzte 24h")
    today_cutoff = int(time.time()) - 86400
    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) as bull,
            SUM(CASE WHEN direction='bearish' THEN 1 ELSE 0 END) as bear,
            SUM(CASE WHEN score >= 3 THEN 1 ELSE 0 END) as high_score
        FROM events WHERE ts > ?
    """, (today_cutoff,)).fetchone()

    if stats and stats[0]:
        total, bull, bear, high = stats
        lines.append(f"- {total} Events | {bull} bullish | {bear} bearish | {high} high-score (≥3)")

    # Top Events
    top = conn.execute("""
        SELECT ticker, direction, headline, score
        FROM events
        WHERE ts > ? AND score >= 2
        ORDER BY score DESC, ts DESC
        LIMIT 5
    """, (today_cutoff,)).fetchall()
    if top:
        lines.append("- **Top Events:**")
        for ticker, direction, headline, score in top:
            emoji = "✅" if direction == "bullish" else "⚠️" if direction == "bearish" else "—"
            lines.append(f"  {emoji} [{ticker or '—'}] score={score} | {headline[:80]}")

    # ── 4. Empfehlungen ausstehend ────────────────────────────────────────────
    lines.append("\n## Empfehlungen — Offene Auswertungen")
    pending = conn.execute("""
        SELECT id, ticker, direction, conviction_score, price_at_rec, ts
        FROM recommendations
        WHERE evaluated = 0
        ORDER BY ts DESC LIMIT 10
    """).fetchall()

    if pending:
        for rec_id, ticker, direction, score, price, ts_rec in pending:
            age_h = (int(time.time()) - ts_rec) // 3600
            rec_time = datetime.fromtimestamp(ts_rec, tz=timezone.utc).strftime("%d.%m %H:%M")
            lines.append(f"- #{rec_id} {ticker} {direction} @ {price}€ | Score {score}/5 | {rec_time} ({age_h}h ago) | Outcome ausstehend")
    else:
        lines.append("_Keine offenen Empfehlungen_")

    # Accuracy wenn vorhanden
    evaluated = conn.execute(
        "SELECT COUNT(*), SUM(correct_4h) FROM recommendations WHERE correct_4h IS NOT NULL"
    ).fetchone()
    if evaluated and evaluated[0] >= 3:
        n, correct = evaluated
        wr = (correct / n * 100) if n else 0
        lines.append(f"\n**Bisherige Accuracy (4h):** {wr:.0f}% ({correct}/{n} richtig)")

    # ── 5. Letzte Analyse ─────────────────────────────────────────────────────
    lines.append("\n## Letzte NewsWire Analyse")
    try:
        with open(ANALYSIS) as f:
            content = f.read()
        # Letzten Eintrag extrahieren (alles nach dem letzten ## Zeitstempel)
        import re
        entries = re.split(r'\n## \d{4}-\d{2}-\d{2}', content)
        if len(entries) > 1:
            last = entries[-1].strip()[:600]
            lines.append(f"```\n{last}\n```")
    except FileNotFoundError:
        lines.append("_Noch keine Analyse geschrieben_")

    # ── 6. Offene TODOs ───────────────────────────────────────────────────────
    lines.append("\n## ⚠️ Offene Aufgaben (beim nächsten Session-Start prüfen)")

    # Trades ohne Stop
    no_stop = conn.execute("""
        SELECT ticker, entry_price FROM trades
        WHERE outcome='open' AND (stop_price IS NULL OR stop_price = 0)
    """).fetchall()
    if no_stop:
        for ticker, entry in no_stop:
            lines.append(f"- 🔴 **{ticker}**: Kein Stop gesetzt! Entry {entry}€ — SOFORT in TR setzen")

    # Empfehlungen die auswertbar wären aber noch nicht evaluated
    overdue = conn.execute("""
        SELECT COUNT(*) FROM recommendations
        WHERE evaluated=0 AND ts < ? AND correct_4h IS NULL
    """, (int(time.time()) - 86400,)).fetchone()[0]
    if overdue:
        lines.append(f"- 📊 {overdue} Empfehlungen >24h alt ohne Outcome — evaluate_pending() laufen lassen")

    lines.append("\n---")
    lines.append(f"_Nächster Snapshot: morgen 23:00 | DB: memory/newswire.db_")

    conn.close()

    with open(OUT_PATH, "w") as f:
        f.write("\n".join(lines))

    print(f"Snapshot geschrieben: {OUT_PATH}")
    print(f"Offene Positionen: {len(trades)}")
    print(f"VIX: {macro[0] if macro else '?'} ({macro[3] if macro else '?'})")

if __name__ == "__main__":
    run()
