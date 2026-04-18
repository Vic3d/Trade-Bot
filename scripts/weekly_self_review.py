#!/usr/bin/env python3
"""
Weekly Self-Review — Albert analysiert jede Woche seine Performance.
Läuft Sonntags 21:00 CET. Generiert strukturierten Report, speichert in
memory/weekly_review_YYYY-WW.md und sendet Zusammenfassung an Discord.

Verwendung:
  python3 scripts/weekly_self_review.py          # Vollständiger Review
  python3 scripts/weekly_self_review.py --dry    # Kontext ausgeben, kein API-Call
"""

import json
import logging
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

WS              = Path("/opt/trademind")
TRADING_DB      = WS / "data/trading.db"
INTELLIGENCE_DB = WS / "data/intelligence.db"
LEARNINGS_FILE  = WS / "data/trading_learnings.json"
CEO_DIRECTIVE   = WS / "data/ceo_directive.json"
STRATEGIES_FILE = WS / "data/strategies.json"
MEMORY_DIR      = WS / "memory"
LOG_PATH        = WS / "data/weekly_review.log"

DISCORD_CHANNEL = "1492225799062032484"
OPENCLAW_CFG    = Path("/data/.openclaw/openclaw.json")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("weekly_self_review")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _safe_json(path: Path, default=None):
    """JSON-Datei lesen — gibt default zurück bei Fehler."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("_safe_json %s: %s", path, exc)
    return default if default is not None else {}


def _get_db(path: Path) -> sqlite3.Connection | None:
    """SQLite-Verbindung öffnen."""
    try:
        if not path.exists():
            log.warning("DB nicht gefunden: %s", path)
            return None
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as exc:
        log.error("_get_db %s: %s", path, exc)
        return None


def _isoweek_label(dt: datetime) -> str:
    """Gibt 'YYYY-WW' zurück, z.B. '2026-15'."""
    return f"{dt.year}-{dt.isocalendar()[1]:02d}"


def _week_range_str(dt: datetime) -> str:
    """Gibt 'DD.MM. – DD.MM.YYYY' für die ISO-Woche des übergebenen Datums zurück."""
    iso_year, iso_week, iso_day = dt.isocalendar()
    monday = dt - timedelta(days=iso_day - 1)
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%d.%m.')} – {sunday.strftime('%d.%m.%Y')}"


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def _send_discord(message: str) -> bool:
    """Sendet Nachricht an Victor via Discord Bot API."""
    try:
        cfg = json.loads(OPENCLAW_CFG.read_text())
        token = cfg["channels"]["discord"]["token"]
        url  = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
        payload = json.dumps({"content": message[:2000]}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "TradeMind-Scheduler/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        log.error("_send_discord: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Kontext-Sammlung
# ---------------------------------------------------------------------------

def build_review_context() -> str:
    """
    Sammelt alle relevanten Daten für die Wochenanalyse und gibt
    einen formatierten Kontext-String zurück.

    Enthält:
      1. Trades diese Woche (letzte 7 Tage, geschlossen)
      2. Strategy Scores aus trading_learnings.json
      3. Quellen-Zuverlässigkeit aus source_scores
      4. Kandidaten-Queue Top 10
      5. Kill-Signale diese Woche
      6. CEO Directive aktueller Status
      7. Portfolio-Status (offene Positionen, Cash)
    """
    parts: list[str] = []
    now   = datetime.now(timezone.utc)

    # ── 1. Trades diese Woche ────────────────────────────────────────────────
    try:
        conn = _get_db(TRADING_DB)
        if conn:
            week_trades = []
            for table, status_col, status_vals in [
                ("paper_portfolio", "status", ("CLOSED",)),
                ("trades",          "status", ("WIN", "LOSS")),
            ]:
                try:
                    placeholders = ",".join("?" for _ in status_vals)
                    rows = conn.execute(f"""
                        SELECT ticker, strategy, entry_price, close_price,
                               pnl_eur, pnl_pct, close_date
                        FROM {table}
                        WHERE {status_col} IN ({placeholders})
                          AND pnl_eur IS NOT NULL
                          AND close_date >= date('now', '-7 days')
                        ORDER BY close_date DESC
                    """, status_vals).fetchall()
                    week_trades.extend(rows)
                except Exception:
                    pass

            if week_trades:
                total_pnl  = sum(float(t["pnl_eur"] or 0) for t in week_trades)
                wins       = sum(1 for t in week_trades if (t["pnl_eur"] or 0) > 0)
                wr_pct     = int(wins / len(week_trades) * 100) if week_trades else 0
                trade_lines = []
                for t in week_trades:
                    pnl    = float(t["pnl_eur"] or 0)
                    icon   = "+" if pnl > 0 else "-"
                    date   = str(t["close_date"] or "")[:10]
                    trade_lines.append(
                        f"  [{icon}] {t['ticker']:<8} {t['strategy'] or '?':<10} "
                        f"PnL: {pnl:+.0f}€ ({float(t['pnl_pct'] or 0):+.1f}%)  {date}"
                    )
                parts.append(
                    f"=== TRADES DIESE WOCHE ({len(week_trades)} Trades, "
                    f"WR: {wr_pct}%, Gesamt-PnL: {total_pnl:+.0f}€) ===\n"
                    + "\n".join(trade_lines)
                )
            else:
                parts.append("=== TRADES DIESE WOCHE ===\n(Keine geschlossenen Trades)")

            # ── 7. Portfolio-Status (offene Positionen) ──────────────────────
            try:
                open_pos = []
                for table, status_col, status_val in [
                    ("paper_portfolio", "status", "OPEN"),
                    ("trades",          "status", "OPEN"),
                ]:
                    try:
                        rows = conn.execute(f"""
                            SELECT ticker, strategy, entry_price, shares,
                                   entry_date, stop_price, target_price
                            FROM {table}
                            WHERE {status_col} = ?
                            ORDER BY entry_date DESC
                        """, (status_val,)).fetchall()
                        open_pos.extend(rows)
                    except Exception:
                        pass

                if open_pos:
                    pos_lines = []
                    for p in open_pos:
                        pos_value = float(p["entry_price"] or 0) * float(p["shares"] or 0)
                        pos_lines.append(
                            f"  {p['ticker']:<8} {p['strategy'] or '?':<10} "
                            f"Entry: {float(p['entry_price'] or 0):.2f}€  "
                            f"Pos-Wert: {pos_value:.0f}€  "
                            f"seit {str(p['entry_date'] or '')[:10]}"
                        )
                    parts.append(
                        f"=== OFFENE POSITIONEN ({len(open_pos)}) ===\n"
                        + "\n".join(pos_lines)
                    )
                else:
                    parts.append("=== OFFENE POSITIONEN ===\n(Keine)")

                # Cash
                try:
                    cash_row = conn.execute(
                        "SELECT cash FROM portfolio_state ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                    if cash_row:
                        parts.append(f"=== CASH ===\n{float(cash_row[0]):.0f}€")
                except Exception:
                    pass

            except Exception as exc:
                log.warning("Portfolio-Status: %s", exc)

            conn.close()

    except Exception as exc:
        log.error("Trades/Portfolio Kontext: %s", exc)
        parts.append("=== TRADES DIESE WOCHE ===\n(Fehler beim Laden)")

    # ── 2. Strategy Scores ───────────────────────────────────────────────────
    try:
        learnings = _safe_json(LEARNINGS_FILE, {})
        if learnings:
            score_lines = []
            # Sortiert nach win_rate absteigend
            strategies_sorted = sorted(
                learnings.items(),
                key=lambda x: float(x[1].get("win_rate", 0)),
                reverse=True
            )
            for strat_id, data in strategies_sorted[:15]:
                wr     = float(data.get("win_rate", 0)) * 100
                pnl    = float(data.get("total_pnl_eur", 0))
                trades = int(data.get("total_trades", 0))
                rec    = data.get("recommendation", "?")
                score  = data.get("score", "?")
                score_lines.append(
                    f"  {strat_id:<15} WR: {wr:4.0f}%  PnL: {pnl:+7.0f}€  "
                    f"Trades: {trades:2d}  Rec: {rec:<8} Score: {score}"
                )
            parts.append(
                "=== STRATEGY SCORES (Top 15 nach WR) ===\n"
                + "\n".join(score_lines)
            )
        else:
            parts.append("=== STRATEGY SCORES ===\n(trading_learnings.json leer)")
    except Exception as exc:
        log.error("Strategy Scores Kontext: %s", exc)
        parts.append("=== STRATEGY SCORES ===\n(Fehler)")

    # ── 3. Quellen-Zuverlässigkeit ───────────────────────────────────────────
    try:
        intel_conn = _get_db(INTELLIGENCE_DB)
        if intel_conn:
            source_rows = intel_conn.execute("""
                SELECT source, signals_led_to_trade, winning_trades,
                       losing_trades, win_rate, avg_pnl_eur
                FROM source_scores
                WHERE signals_led_to_trade >= 3
                ORDER BY win_rate DESC
            """).fetchall()
            intel_conn.close()

            if source_rows:
                src_lines = []
                for r in source_rows:
                    wr_pct  = int(float(r["win_rate"]) * 100)
                    avg_pnl = float(r["avg_pnl_eur"])
                    sign    = "+" if avg_pnl >= 0 else ""
                    src_lines.append(
                        f"  {str(r['source'])[:14]:<14} WR: {wr_pct:2d}%  "
                        f"Ø PnL: {sign}{avg_pnl:.1f}€  Signals: {r['signals_led_to_trade']}"
                    )
                parts.append(
                    "=== QUELLEN-ZUVERLÄSSIGKEIT ===\n"
                    + "\n".join(src_lines)
                )
            else:
                parts.append("=== QUELLEN-ZUVERLÄSSIGKEIT ===\n(Noch keine ausreichenden Daten)")
        else:
            parts.append("=== QUELLEN-ZUVERLÄSSIGKEIT ===\n(intelligence.db nicht erreichbar)")
    except Exception as exc:
        log.error("Quellen-Zuverlässigkeit Kontext: %s", exc)
        parts.append("=== QUELLEN-ZUVERLÄSSIGKEIT ===\n(Fehler)")

    # ── 4. Kandidaten-Queue Top 10 ───────────────────────────────────────────
    try:
        conn = _get_db(TRADING_DB)
        if conn:
            try:
                candidates = conn.execute("""
                    SELECT ticker, strategy, conviction_score, created_at, notes
                    FROM candidate_queue
                    WHERE status = 'PENDING'
                    ORDER BY conviction_score DESC
                    LIMIT 10
                """).fetchall()
                conn.close()

                if candidates:
                    cand_lines = [
                        f"  {c['ticker']:<8} {c['strategy'] or '?':<12} "
                        f"Conviction: {c['conviction_score'] or '?'}  "
                        f"  {str(c['notes'] or '')[:60]}"
                        for c in candidates
                    ]
                    parts.append(
                        "=== KANDIDATEN-QUEUE (Top 10) ===\n"
                        + "\n".join(cand_lines)
                    )
                else:
                    parts.append("=== KANDIDATEN-QUEUE ===\n(Leer)")
            except Exception:
                # Tabelle existiert möglicherweise nicht
                conn.close()
                parts.append("=== KANDIDATEN-QUEUE ===\n(Nicht verfügbar)")
        else:
            parts.append("=== KANDIDATEN-QUEUE ===\n(DB nicht erreichbar)")
    except Exception as exc:
        log.error("Kandidaten-Queue Kontext: %s", exc)
        parts.append("=== KANDIDATEN-QUEUE ===\n(Fehler)")

    # ── 5. Kill-Signale diese Woche ──────────────────────────────────────────
    try:
        conn = _get_db(TRADING_DB)
        if conn:
            try:
                kills = conn.execute("""
                    SELECT ticker, strategy, kill_reason, triggered_at
                    FROM kill_signals
                    WHERE triggered_at >= date('now', '-7 days')
                    ORDER BY triggered_at DESC
                """).fetchall()
                conn.close()

                if kills:
                    kill_lines = [
                        f"  {k['ticker']:<8} {k['strategy'] or '?':<12} "
                        f"Grund: {k['kill_reason'] or '?'}  "
                        f"  {str(k['triggered_at'] or '')[:16]}"
                        for k in kills
                    ]
                    parts.append(
                        f"=== KILL-SIGNALE DIESE WOCHE ({len(kills)}) ===\n"
                        + "\n".join(kill_lines)
                    )
                else:
                    parts.append("=== KILL-SIGNALE DIESE WOCHE ===\n(Keine)")
            except Exception:
                conn.close()
                parts.append("=== KILL-SIGNALE DIESE WOCHE ===\n(Tabelle nicht gefunden)")
        else:
            parts.append("=== KILL-SIGNALE ===\n(DB nicht erreichbar)")
    except Exception as exc:
        log.error("Kill-Signale Kontext: %s", exc)
        parts.append("=== KILL-SIGNALE ===\n(Fehler)")

    # ── 6. CEO Directive ─────────────────────────────────────────────────────
    try:
        directive = _safe_json(CEO_DIRECTIVE, {})
        bias      = directive.get("bias", "UNBEKANNT")
        reason    = directive.get("reason", "—")
        updated   = directive.get("updated_at", "—")
        parts.append(
            f"=== CEO DIRECTIVE ===\n"
            f"  Bias: {bias}\n"
            f"  Grund: {reason}\n"
            f"  Aktualisiert: {str(updated)[:19]}"
        )
    except Exception as exc:
        log.error("CEO Directive Kontext: %s", exc)
        parts.append("=== CEO DIRECTIVE ===\n(Fehler beim Laden)")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Wöchentlicher Review
# ---------------------------------------------------------------------------

def run_weekly_review() -> str:
    """
    Hauptfunktion. Baut Kontext, ruft Claude API auf, speichert Review als
    Markdown-Datei und sendet Zusammenfassung an Discord.

    Returns:
        Den generierten Review-Text.
    """
    now       = datetime.now(timezone.utc)
    week_label = _isoweek_label(now)
    week_range = _week_range_str(now)
    week_num   = now.isocalendar()[1]

    log.info("Starte wöchentlichen Review — Woche %s (%s)", week_label, week_range)

    # 1. Kontext sammeln
    try:
        context = build_review_context()
        log.info("Kontext gesammelt: %d Zeichen", len(context))
    except Exception as exc:
        log.error("build_review_context fehlgeschlagen: %s", exc)
        context = f"(Fehler beim Sammeln des Kontexts: {exc})"

    # 2. Claude API aufrufen
    review_text = ""
    try:
        import anthropic  # type: ignore

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.error("ANTHROPIC_API_KEY nicht gesetzt")
            review_text = "(Fehler: ANTHROPIC_API_KEY fehlt)"
        else:
            client = anthropic.Anthropic(api_key=api_key)

            prompt = f"""Du bist Albert, AI-CEO von TradeMind. Schreibe deinen wöchentlichen Selbst-Review.

KONTEXT DER LETZTEN WOCHE:
{context}

Strukturiere deinen Review so:

## Woche {week_num} — {week_range}

### Was lief gut
[3-5 konkrete Punkte mit Zahlen]

### Was lief schlecht / Fehler
[Ehrliche Analyse, keine Ausreden. Was hätte ich früher sehen müssen?]

### Quellen-Qualität
[Welche News-Quellen und Trader-Signale haben sich bewährt? Welche waren Lärm?]

### Strategie-Anpassungen für nächste Woche
[Konkrete Änderungen: Welche Strategien höher/niedriger gewichten? Neue Thesen?]

### Sektor-Fokus nächste Woche
[Wo liegen die besten Opportunities? Begründung.]

### Ziele nächste Woche
[Max 3, messbar und konkret]

Sei direkt, selbstkritisch und konkret. Victor liest das."""

            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            review_text = message.content[0].text
            log.info("Claude Review erhalten: %d Zeichen", len(review_text))

    except ImportError:
        log.error("anthropic-Paket nicht installiert")
        review_text = "(Fehler: anthropic-Paket nicht verfügbar)"
    except Exception as exc:
        log.error("Claude API Fehler: %s", exc)
        review_text = f"(Fehler beim Generieren des Reviews: {exc})"

    # 3. Markdown-Datei speichern
    output_file = MEMORY_DIR / f"weekly_review_{week_label}.md"
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Weekly Self-Review — Woche {week_label}\n"
            f"**Generiert:** {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
        )
        output_file.write_text(header + review_text, encoding="utf-8")
        log.info("Review gespeichert: %s", output_file)
    except Exception as exc:
        log.error("Review speichern fehlgeschlagen: %s", exc)

    # 4. Discord-Zusammenfassung senden (max 1500 Zeichen + Datei-Hinweis)
    try:
        preview = review_text[:1500]
        if len(review_text) > 1500:
            preview += "..."

        discord_msg = (
            f"**Albert's Weekly Self-Review — Woche {week_label}**\n"
            f"*{week_range}*\n\n"
            f"{preview}\n\n"
            f"Vollstaendiger Review: `memory/weekly_review_{week_label}.md`"
        )
        ok = _send_discord(discord_msg)
        if ok:
            log.info("Discord-Nachricht gesendet")
        else:
            log.warning("Discord-Nachricht konnte nicht gesendet werden")
    except Exception as exc:
        log.error("Discord send: %s", exc)

    return review_text


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry" in sys.argv

    if dry_run:
        print("=== DRY RUN — Nur Kontext, kein API-Call ===\n")
        ctx = build_review_context()
        print(ctx)
        print(f"\n[Kontext: {len(ctx)} Zeichen]")
    else:
        review = run_weekly_review()
        if review:
            print(review)
        else:
            print("(Kein Review generiert — siehe Log)")
            sys.exit(1)
