#!/usr/bin/env python3.13
"""
evening_report.py — Tägliches Abend-Briefing für Victor
========================================================
Läuft täglich 22:00 CET via scheduler_daemon.py
Sendet Zusammenfassung der Paper Trades per Discord.

Albert | TradeMind v2 | 2026-04-10
"""

import sqlite3
import sys
import os
from datetime import datetime, timezone, date
from pathlib import Path

WS  = Path('/data/.openclaw/workspace')
DB  = WS / 'data' / 'trading.db'
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))


# ─── DB ──────────────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


# ─── Preise holen ─────────────────────────────────────────────────────────────

def _get_price(ticker: str) -> float | None:
    """Holt aktuellen Kurs via yfinance. Gibt None bei Fehler zurück."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period='1d', interval='1m')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        info = t.fast_info
        return float(info.last_price) if hasattr(info, 'last_price') else None
    except Exception:
        return None


def _get_fx(pair: str) -> float:
    """Holt FX-Kurs (z.B. EURUSD=X). Fallback auf Schätzwert."""
    defaults = {'EURUSD=X': 1.10, 'EURNOK=X': 11.5, 'EURGBP=X': 0.86, 'EURDK=X': 7.46}
    try:
        import yfinance as yf
        t = yf.Ticker(pair)
        hist = t.history(period='1d', interval='1m')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        return defaults.get(pair, 1.0)
    except Exception:
        return defaults.get(pair, 1.0)


def _to_eur(price: float, ticker: str, fx: dict) -> float:
    """Konvertiert Preis in EUR basierend auf Ticker-Endung."""
    if price is None:
        return None
    t = ticker.upper()
    if t.endswith('.DE') or t.endswith('.AS') or t.endswith('.PA') or t.endswith('.BR') or t.endswith('.MC'):
        return price  # bereits EUR
    if t.endswith('.L'):
        return (price / 100) / fx.get('EURGBP=X', 0.86)  # GBp → EUR
    if t.endswith('.OL'):
        return price / fx.get('EURNOK=X', 11.5)  # NOK → EUR
    if t.endswith('.CO'):
        return price / fx.get('EURDK=X', 7.46)   # DKK → EUR
    # US-Ticker → USD → EUR
    return price / fx.get('EURUSD=X', 1.10)


# ─── Report-Abschnitte ────────────────────────────────────────────────────────

def _portfolio_section(conn, fx: dict) -> str:
    """Listet alle offenen Positionen mit aktuellem PnL."""
    rows = conn.execute("""
        SELECT ticker, strategy, entry_price, shares, stop_price,
               target_price, conviction, entry_date
        FROM paper_portfolio
        WHERE status = 'OPEN'
        ORDER BY entry_date DESC
    """).fetchall()

    fund = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM paper_fund").fetchall()}
    cash       = float(fund.get('current_cash', 0))
    start_cap  = float(fund.get('starting_capital', 25000))
    realized   = float(fund.get('total_realized_pnl', 0))

    if not rows:
        perf_pct = ((cash - start_cap) / start_cap * 100) if start_cap else 0
        return (
            f"💼 **PORTFOLIO**\n"
            f"  Cash: {cash:.0f}€ | Realisierter PnL: {realized:+.0f}€ | Performance: {perf_pct:+.1f}%\n"
            f"  📭 Keine offenen Positionen."
        )

    lines = []
    position_value = 0.0

    for r in rows:
        ticker     = r['ticker']
        strategy   = r['strategy'] or '—'
        entry_eur  = float(r['entry_price']) if r['entry_price'] else None
        shares     = float(r['shares']) if r['shares'] else None
        stop       = float(r['stop_price']) if r['stop_price'] else None
        target     = float(r['target_price']) if r['target_price'] else None
        conviction = r['conviction'] or 0
        entry_date = str(r['entry_date'])[:10]

        curr_raw = _get_price(ticker)
        curr_eur = _to_eur(curr_raw, ticker, fx) if curr_raw else None

        if curr_eur and entry_eur and shares:
            pnl_eur = (curr_eur - entry_eur) * shares
            pnl_pct = ((curr_eur - entry_eur) / entry_eur) * 100
            position_value += curr_eur * shares
            pnl_icon = "📈" if pnl_eur >= 0 else "📉"
            pnl_str  = f"{pnl_icon} {pnl_eur:+.0f}€ ({pnl_pct:+.1f}%)"
            # Stop-Abstand warnen
            if stop and curr_eur:
                stop_dist_pct = ((curr_eur - stop) / curr_eur) * 100
                stop_warn = f" ⚠️ Stop nur {stop_dist_pct:.1f}% weg!" if stop_dist_pct < 4 else ""
            else:
                stop_warn = ""
        elif entry_eur and shares:
            position_value += entry_eur * shares
            pnl_str  = "⏳ Kurs nicht verfügbar"
            stop_warn = ""
        else:
            pnl_str  = "⏳ Daten fehlen"
            stop_warn = ""

        stop_str = f"Stop {stop:.2f}" if stop else "⚠️ Kein Stop"
        tgt_str  = f"Ziel {target:.2f}" if target else ""

        lines.append(
            f"  **{ticker}** [{strategy}] seit {entry_date} | Conviction: {conviction}\n"
            f"    Entry: {entry_eur:.2f}€ | {stop_str} | {tgt_str}\n"
            f"    {pnl_str}{stop_warn}"
        )

    total_value = cash + position_value
    perf_pct    = ((total_value - start_cap) / start_cap) * 100 if start_cap else 0

    header = (
        f"💼 **OFFENE POSITIONEN ({len(rows)})**\n"
        f"  Portfolio-Wert: **{total_value:.0f}€** ({perf_pct:+.1f}%) | "
        f"Cash: {cash:.0f}€ | Realisiert: {realized:+.0f}€\n"
    )
    return header + "\n".join(lines)


def _closed_today_section(conn) -> str:
    """Zeigt heute geschlossene Trades."""
    today = date.today().isoformat()
    rows = conn.execute("""
        SELECT ticker, strategy, entry_price, close_price, pnl_eur, pnl_pct, exit_type
        FROM paper_portfolio
        WHERE status = 'CLOSED'
          AND close_date >= ?
        ORDER BY close_date DESC
    """, (today,)).fetchall()

    if not rows:
        return "📋 Heute keine Trades geschlossen."

    lines = [f"📋 **HEUTE GESCHLOSSEN ({len(rows)}):**"]
    total_pnl = 0.0
    for r in rows:
        pnl = float(r['pnl_eur']) if r['pnl_eur'] else 0
        pct = float(r['pnl_pct']) if r['pnl_pct'] else 0
        total_pnl += pnl
        icon = "✅" if pnl >= 0 else "❌"
        exit_type = r['exit_type'] or 'manuell'
        lines.append(
            f"  {icon} **{r['ticker']}** [{r['strategy']}] "
            f"→ {pnl:+.0f}€ ({pct:+.1f}%) | {exit_type}"
        )
    lines.append(f"\n  **Tages-PnL gesamt: {total_pnl:+.0f}€**")
    return "\n".join(lines)


def _win_rate_section(conn) -> str:
    """Win-Rate und Statistiken der letzten 30 Tage."""
    rows = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_eur <= 0 THEN 1 ELSE 0 END) as losses,
            COALESCE(SUM(pnl_eur), 0) as total_pnl,
            AVG(CASE WHEN pnl_eur > 0 THEN pnl_eur END) as avg_win,
            AVG(CASE WHEN pnl_eur <= 0 THEN pnl_eur END) as avg_loss
        FROM paper_portfolio
        WHERE status = 'CLOSED'
          AND close_date >= date('now', '-30 days')
    """).fetchone()

    if not rows or not rows['total']:
        return "📊 Noch keine abgeschlossenen Trades in den letzten 30 Tagen."

    total    = rows['total']
    wins     = rows['wins'] or 0
    losses   = rows['losses'] or 0
    wr       = (wins / total * 100) if total else 0
    tot_pnl  = rows['total_pnl'] or 0
    avg_win  = rows['avg_win'] or 0
    avg_loss = rows['avg_loss'] or 0
    wr_icon  = "🟢" if wr >= 55 else "🟡" if wr >= 40 else "🔴"

    crv_str = ""
    if avg_loss and avg_loss != 0:
        crv = abs(avg_win / avg_loss)
        crv_str = f" | Ø CRV: {crv:.1f}"

    return (
        f"📊 **STATISTIK (letzte 30 Tage)**\n"
        f"  {wr_icon} Win-Rate: **{wr:.0f}%** ({wins}W / {losses}L aus {total} Trades)\n"
        f"  Gesamt-PnL: {tot_pnl:+.0f}€ | Ø Gewinn: {avg_win:+.0f}€ | Ø Verlust: {avg_loss:+.0f}€{crv_str}"
    )


def _active_theses_section(conn) -> str:
    """Aktive Thesen aus thesis_status."""
    try:
        rows = conn.execute("""
            SELECT thesis_id, status, health_score
            FROM thesis_status
            WHERE status IN ('ACTIVE', 'DEGRADED', 'WATCHING')
            ORDER BY status, thesis_id
        """).fetchall()
    except Exception:
        return ""

    if not rows:
        return ""

    lines = ["🧠 **AKTIVE THESEN:**"]
    icons = {"ACTIVE": "🟢", "DEGRADED": "🟡", "WATCHING": "👁️"}
    for r in rows:
        icon   = icons.get(r['status'], "⚪")
        health = f" (Health: {r['health_score']})" if r['health_score'] is not None else ""
        lines.append(f"  {icon} {r['thesis_id']} — {r['status']}{health}")

    return "\n".join(lines)


# ─── Haupt-Funktion ───────────────────────────────────────────────────────────

def build_report() -> str:
    """Erstellt den kompletten Abend-Briefing Text."""
    now_str = datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')

    fx = {}
    for pair in ['EURUSD=X', 'EURNOK=X', 'EURGBP=X']:
        fx[pair] = _get_fx(pair)

    conn = _conn()

    portfolio_text = _portfolio_section(conn, fx)
    closed_text    = _closed_today_section(conn)
    stats_text     = _win_rate_section(conn)
    theses_text    = _active_theses_section(conn)

    conn.close()

    sep = "━" * 34
    sections = [
        f"🌙 **ABEND-BRIEFING — {now_str} UTC**",
        sep,
        portfolio_text,
        sep,
        closed_text,
        sep,
        stats_text,
    ]

    if theses_text:
        sections += [sep, theses_text]

    sections += [
        sep,
        "💬 Fragen? Schreib mir einfach hier in Discord.",
        "— Albert (TradeMind)",
    ]

    return "\n".join(sections)


def send_report():
    """Baut Report und sendet ihn an Victors Discord-DM-Kanal."""
    report = build_report()

    try:
        from discord_sender import send
        channel_id = os.environ.get('DISCORD_VICTOR_CHANNEL', '1492225799062032484')
        send(report, channel_id=channel_id)
        print(f"[evening_report] Discord-Briefing gesendet ({len(report)} Zeichen)")
    except Exception as e:
        print(f"[evening_report] Discord-Fehler: {e}")
        print(report)  # Fallback: in Log ausgeben

    # Letzte Version speichern
    try:
        log_path = WS / 'data' / 'evening_report_last.txt'
        log_path.write_text(report, encoding='utf-8')
    except Exception:
        pass

    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--print-only', action='store_true',
                        help='Nur ausgeben, nicht per Discord senden')
    args = parser.parse_args()

    if args.print_only:
        print(build_report())
    else:
        send_report()
