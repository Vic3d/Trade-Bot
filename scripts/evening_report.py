#!/usr/bin/env python3
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

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))
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
        WHERE status IN ('CLOSED','WIN','LOSS')
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
        WHERE status IN ('CLOSED','WIN','LOSS')
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


def _format_source_name(raw_source: str) -> str:
    """Formatiert rohe Source-IDs zu lesbaren Namen.

    Beispiele:
        bloomberg_markets → Bloomberg Markets
        yahoo_EQNR       → Yahoo EQNR
        google_news       → Google News
    """
    if not raw_source:
        return "Unbekannt"
    return raw_source.replace('_', ' ').title()


def _news_section(conn) -> str:
    """Zeigt die wichtigsten News-Headlines des Tages mit Quelle und Datum."""
    try:
        rows = conn.execute("""
            SELECT headline, source, published_at, sentiment_label
            FROM news_events
            WHERE created_at >= date('now', '-1 day')
            ORDER BY relevance_score DESC, created_at DESC
            LIMIT 10
        """).fetchall()
    except Exception:
        return ""

    if not rows:
        return ""

    lines = ["📰 **TOP NEWS HEUTE:**"]
    sentiment_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "〰️"}
    for r in rows:
        headline = r['headline']
        source = _format_source_name(r['source'])
        pub = str(r['published_at'] or '')[:16]
        icon = sentiment_icon.get(r['sentiment_label'], "〰️")
        lines.append(f"  {icon} {headline}")
        lines.append(f"    [{source}, {pub}]")

    return "\n".join(lines)


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
    try:
        from core.timezones import fmt_cet, tz_label
        now_str = fmt_cet(fmt='%d.%m.%Y %H:%M')
        _tz = tz_label()
    except Exception:
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        _tz = 'CEST'

    fx = {}
    for pair in ['EURUSD=X', 'EURNOK=X', 'EURGBP=X']:
        fx[pair] = _get_fx(pair)

    conn = _conn()

    portfolio_text = _portfolio_section(conn, fx)
    closed_text    = _closed_today_section(conn)
    stats_text     = _win_rate_section(conn)
    news_text      = _news_section(conn)
    theses_text    = _active_theses_section(conn)

    # Phase 45p (Victor 2026-05-05): gut/schlecht/Outlook-Block
    summary_text = _today_summary_block(conn)

    conn.close()

    sep = "━" * 34
    sections = [
        f"🌙 **ABEND-BRIEFING — {now_str} {_tz}**",
        sep,
        portfolio_text,
        sep,
        closed_text,
        sep,
        stats_text,
        sep,
        summary_text,
    ]

    if news_text:
        sections += [sep, news_text]

    if theses_text:
        sections += [sep, theses_text]

    sections += [
        sep,
        "💬 Fragen? Schreib mir einfach hier in Discord.",
        "— Albert (TradeMind)",
    ]

    return "\n".join(sections)


def _today_summary_block(conn) -> str:
    """Phase 45p: Was lief gut / was schlecht / Ausblick.

    Datenbasis: heutige Closed-Trades, offene Position-Performance,
    Strategy-Verdicts, Mission-KPIs.
    """
    today = date.today().isoformat()
    good, bad, outlook = [], [], []

    # 1. Closed Trades heute
    rows = conn.execute(
        "SELECT ticker, strategy, ROUND(pnl_eur,1) pnl, ROUND(pnl_pct,1) pct, exit_type "
        "FROM paper_portfolio WHERE substr(close_date,1,10)=? "
        "AND pnl_eur IS NOT NULL", (today,)
    ).fetchall()
    wins = [r for r in rows if r['pnl'] > 0]
    losses = [r for r in rows if r['pnl'] < 0]
    for r in wins[:3]:
        good.append(f"✅ {r['ticker']} ({r['strategy']}) +{r['pnl']}€ ({r['pct']:+.1f}%)")
    for r in losses[:3]:
        bad.append(f"❌ {r['ticker']} ({r['strategy']}) {r['pnl']}€ ({r['pct']:+.1f}%) → {r['exit_type'] or 'n/a'}")

    # 2. Offene Positionen mit Live-MTM
    open_rows = conn.execute(
        "SELECT ticker, strategy, entry_price, shares FROM paper_portfolio "
        "WHERE status='OPEN'"
    ).fetchall()
    for o in open_rows:
        pr = conn.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (o['ticker'],)
        ).fetchone()
        if not pr or not o['entry_price'] or not o['shares']:
            continue
        pnl_eur = (pr[0] - o['entry_price']) * o['shares']
        pnl_pct = (pr[0]/o['entry_price'] - 1) * 100
        if pnl_pct >= 5:
            good.append(f"📈 {o['ticker']} ({o['strategy']}) unrealized +{pnl_eur:.0f}€ / {pnl_pct:+.1f}%")
        elif pnl_pct <= -3:
            bad.append(f"📉 {o['ticker']} ({o['strategy']}) unrealized {pnl_eur:+.0f}€ / {pnl_pct:+.1f}%")

    # 3. Mission-KPI-Status fuer Ausblick
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from strategy_verdict import all_verdicts  # type: ignore
        verdicts = all_verdicts()
        n_strong = sum(1 for v in verdicts if v['verdict'] == 'STRONG_EDGE')
        n_ok = sum(1 for v in verdicts if v['verdict'] == 'OK')
        n_weak = sum(1 for v in verdicts if v['verdict'] == 'WEAK')
        n_neg = sum(1 for v in verdicts if v['verdict'] == 'NEGATIVE')
        if n_strong >= 1:
            outlook.append(f"🎯 {n_strong} Strategien mit STRONG_EDGE — voll handelbar.")
        if n_ok >= 1:
            outlook.append(f"👍 {n_ok} OK-Strategien — laufen.")
        if n_weak >= 3:
            outlook.append(f"⚠️ {n_weak} WEAK-Strategien — Position-Size reduziert.")
        if n_neg >= 1:
            outlook.append(f"🚫 {n_neg} NEGATIVE_EDGE — Retire-Kandidaten naechste Woche.")
    except Exception: pass

    # Sharpe-Trend
    try:
        qf = WS / 'data' / 'quant_metrics.json'
        if qf.exists():
            import json as _json
            q = _json.loads(qf.read_text(encoding='utf-8'))
            s_lt = (q.get('all_time') or {}).get('sharpe')
            s_30d = (q.get('last_30d') or {}).get('sharpe')
            if s_lt is not None and s_30d is not None:
                arrow = '📈' if s_30d > 0 else '📉'
                outlook.append(f"{arrow} Sharpe lifetime {s_lt:.2f} / 30d {s_30d:+.2f}")
                if s_30d < -0.5:
                    outlook.append("→ 30d-Trend schwach. Naechste Woche: konservative Sizing.")
    except Exception: pass

    # Naechste Catalysts (aus calendar_service falls verfuegbar)
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from calendar_service import upcoming_events  # type: ignore
        events = upcoming_events(days_ahead=3) or []
        if events:
            outlook.append(f"📅 Naechste 3 Tage: {len(events)} Catalysts (Earnings/Fed/CPI etc.)")
    except Exception: pass

    if not good: good.append("— heute keine herausragenden Gewinner")
    if not bad:  bad.append("— heute keine signifikanten Verlierer")
    if not outlook: outlook.append("— keine spezifischen Signale fuer kommende Tage")

    out = ['📊 **TAGES-FAZIT**', '', '**Was gut lief:**']
    out.extend(good)
    out.extend(['', '**Was schlecht lief:**'])
    out.extend(bad)
    out.extend(['', '**Ausblick naechste Tage:**'])
    out.extend(outlook)

    # Phase 45r (Victor 2026-05-06): Narrativ-Block — Fliesstext
    # zusammenhaengend, was passierte heute + Learnings.
    narrative = _build_evening_narrative(rows, open_rows, conn)
    if narrative:
        out.extend(['', '📖 **TAGES-NARRATIV & LEARNINGS:**', narrative])

    return '\n'.join(out)


def _build_evening_narrative(closed_today, open_rows, conn) -> str:
    """LLM-generiertes 4-6 Saetze Narrativ ueber den Tag + Learnings.
    Faellt auf strukturiertes Bullet-Backup zurueck wenn LLM nicht
    verfuegbar."""
    facts: list[str] = []

    # 1. Closed today
    if closed_today:
        facts.append(f"CLOSED HEUTE: {len(closed_today)} Trades")
        for r in closed_today[:6]:
            facts.append(f"  {r['ticker']} ({r['strategy']}) {r['pnl']:+.1f}EUR ({r['pct']:+.1f}%) via {r['exit_type'] or 'n/a'}")
    else:
        facts.append("CLOSED HEUTE: keine")

    # 2. Open positions snapshot
    if open_rows:
        for o in open_rows:
            pr = conn.execute("SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (o['ticker'],)).fetchone()
            if pr and o['entry_price'] and o['shares']:
                pnl_eur = (pr[0] - o['entry_price']) * o['shares']
                pnl_pct = (pr[0]/o['entry_price'] - 1) * 100
                facts.append(f"OPEN: {o['ticker']} ({o['strategy']}) entry {o['entry_price']:.2f}, last {pr[0]:.2f}, unrealized {pnl_eur:+.0f}EUR ({pnl_pct:+.1f}%)")

    # 3. Verdict-Distribution
    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from strategy_verdict import all_verdicts as _av  # type: ignore
        v = _av()
        from collections import Counter as _C
        c_v = _C(x['verdict'] for x in v)
        facts.append(f"VERDICTS: {dict(c_v)}")
    except Exception: pass

    # 4. Quant-Sharpe
    try:
        import json as _j
        qf = WS / 'data' / 'quant_metrics.json'
        if qf.exists():
            q = _j.loads(qf.read_text(encoding='utf-8'))
            facts.append(f"SHARPE: lifetime {(q.get('all_time') or {}).get('sharpe')}, 30d {(q.get('last_30d') or {}).get('sharpe')}")
    except Exception: pass

    # 5. Halluzinations-Audit heute (CLI + Albert)
    try:
        from datetime import datetime as _dt
        today_iso = _dt.now().date().isoformat()
        for log_name in ('cli_audit_violations.jsonl', 'halluzination_log.jsonl'):
            p = WS / 'data' / log_name
            if not p.exists(): continue
            n_today = 0
            with open(p, encoding='utf-8', errors='replace') as f:
                for line in f:
                    if today_iso in line[:50]:
                        n_today += 1
            if n_today:
                facts.append(f"AUDIT {log_name}: {n_today} Events heute")
    except Exception: pass

    # 6. Lessons-Trigger: alle Stop-Outs heute mit pnl<-50
    big_losses = [r for r in (closed_today or []) if r['pnl'] < -50]
    for r in big_losses:
        facts.append(f"BIG LOSS HEUTE: {r['ticker']} {r['pnl']}EUR — Lesson-Kandidat")

    facts_block = '\n'.join(facts)

    try:
        import sys as _sys
        _sys.path.insert(0, str(WS / 'scripts'))
        from core.llm_client import call_llm  # type: ignore
        prompt = (
            "Du bist Albert, der CEO eines autonomen Trading-Bots. Schreibe einen "
            "kurzen, zusammenhaengenden Tagesabschluss-Text (4-6 Saetze, KEIN Bullet-List) "
            "an Victor:\n\n"
            "Struktur:\n"
            "1. Wie lief der Tag konkret (Trades, Performance, was passierte)\n"
            "2. Was haben wir HEUTE gelernt (Pattern, Bugs, Insights)\n"
            "3. Wenn relevant: was passt nicht und sollte korrigiert werden\n\n"
            "Schreib in Du-Form. Keine Floskeln. Sei ehrlich auch bei Fehlern. "
            "Nimm NUR die Fakten unten. Wenn nichts passierte, sag das auch so.\n\n"
            "FAKTEN:\n"
            f"{facts_block}\n"
        )
        text, _usage = call_llm(prompt, model_hint='haiku', max_tokens=600,
                                audit_context='evening_narrative')
        return (text or '').strip()
    except Exception:
        return "(LLM unavailable, Fakten-Backup):\n" + facts_block


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
