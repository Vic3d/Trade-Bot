#!/usr/bin/env python3
"""
Trade Journal Logger — strukturiertes Trade-Logging mit NewsWire-Verknüpfung.

Usage (als Modul von Albert/Cron aufgerufen):

  log_entry(ticker, direction, entry_price, stop_price, strategy_id, notes)
  log_exit(ticker, exit_price, rule_violation=None)
  get_open_trades()
  get_stats(ticker=None)
  get_conviction_score(ticker)   ← Multi-Faktor-Scoring
"""

import sqlite3, time, json, os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")

# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _conn():
    return sqlite3.connect(DB_PATH)

def now_ts():
    return int(time.time())

def fmt_ts(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# ── Multi-Faktor Conviction Score ──────────────────────────────────────────────

def get_conviction_score(ticker: str, lookback_minutes: int = 120) -> dict:
    """
    Berechnet einen Multi-Faktor Conviction Score (1-5) für einen Ticker.

    Factor 1: Direct keyword match in letzten 2h
    Factor 2: Mehrere bestätigende Quellen (Bloomberg + Google = +1)
    Factor 3: Leading-Indicator-Bewegung (Shell für EQNR etc.)
    Factor 4: News-Frequenz (>3 Events zum Ticker in 2h = +1)
    Factor 5: (extern) VIX-Regime — muss manuell übergeben werden
    """
    LEADING_INDICATORS = {
        "EQNR":    ["SHEL"],
        "DR0.DE":  ["SHEL", "CL=F"],
        "PLTR":    ["BAH"],
        "NVDA":    ["AMD", "ASML"],
        "MSFT":    ["AMD"],
        "RHM.DE":  ["BAH"],
        "RIO.L":   ["BHP"],
        "AG":      ["GC=F"],
    }

    conn = _conn()
    cutoff = now_ts() - (lookback_minutes * 60)

    # Alle Events für diesen Ticker in letzten 2h
    events = conn.execute("""
        SELECT id, source, direction, score, headline, ts
        FROM events
        WHERE (ticker LIKE ? OR ticker LIKE ?)
          AND ts > ?
        ORDER BY score DESC, ts DESC
    """, (f"%{ticker}%", f"%{ticker.split('.')[0]}%", cutoff)).fetchall()

    conn.close()

    if not events:
        return {"score": 0, "factors": [], "direction": None, "events": []}

    factors = []
    score = 0

    # Factor 1: Direct match mit score >= 2
    high_score = [e for e in events if e[3] >= 2]
    if high_score:
        score += 1
        factors.append(f"F1: {len(high_score)} relevante Events (score≥2)")

    # Factor 2: Mehrere Quellen bestätigen
    sources = set(e[1] for e in events)
    if len(sources) >= 2:
        score += 1
        factors.append(f"F2: {len(sources)} Quellen bestätigen ({', '.join(sources)})")

    # Factor 3: Leading Indicator
    leaders = LEADING_INDICATORS.get(ticker, [])
    if leaders:
        conn2 = _conn()
        for leader in leaders:
            leader_events = conn2.execute("""
                SELECT COUNT(*) FROM events
                WHERE ticker LIKE ? AND ts > ? AND score >= 2
            """, (f"%{leader}%", cutoff)).fetchone()[0]
            if leader_events > 0:
                score += 1
                factors.append(f"F3: Leading indicator {leader} hat {leader_events} Event(s)")
                break
        conn2.close()

    # Factor 4: News-Frequenz (>3 Events = Momentum)
    if len(events) >= 3:
        score += 1
        factors.append(f"F4: News-Momentum ({len(events)} Events in {lookback_minutes}min)")

    # Factor 5: VIX-Regime aus macro_context-Tabelle (Risk-Strategie)
    try:
        conn_vix = _conn()
        vix_row = conn_vix.execute(
            "SELECT vix, regime, regime_score FROM macro_context ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        conn_vix.close()
        if vix_row:
            vix_val, vix_regime, regime_score = vix_row
            score += regime_score  # +1 grün, 0 gelb, -1 orange, -2 rot
            if regime_score >= 0:
                factors.append(f"F5: VIX {vix_val:.1f} ({vix_regime}) — Markt-Regime OK")
            else:
                factors.append(f"F5: ⚠️ VIX {vix_val:.1f} ({vix_regime}) — Signal abgewertet")
    except Exception:
        pass  # macro_context noch nicht befüllt

    # Factor 6: Technischer Trend — EMA50/200 Status aus Kursdaten
    # (Wird extern gesetzt wenn bekannt; hier als Placeholder für manuelle Eingabe)
    # log_recommendation() kann technical_trend="bullish/bearish/neutral" übergeben

    # Factor 7: Sektor-Alignment — läuft der Sektor-ETF in die gleiche Richtung?
    # XLE für Oil/Energy, ITA für Defense, SOXX für Semis
    # Placeholder — wird aus macro_context befüllt wenn ETF-Tracking aktiv

    # Direction bestimmen (Mehrheit)
    directions = [e[2] for e in events if e[2] in ("bullish", "bearish")]
    if directions:
        bull = directions.count("bullish")
        bear = directions.count("bearish")
        dominant_direction = "bullish" if bull >= bear else "bearish"
    else:
        dominant_direction = "neutral"

    final_score = min(score, 5)
    return {
        "score": final_score,
        "direction": dominant_direction,
        "factors": factors,
        "events_count": len(events),
        "signal": "HIGH" if final_score >= 4 else "MEDIUM" if final_score >= 2 else "LOW",
        "event_ids": [e[0] for e in events],
        "top_headline": events[0][4] if events else None,
    }


# ── Trade Logging ──────────────────────────────────────────────────────────────

def log_entry(ticker: str, direction: str, entry_price: float,
              stop_price: float = None, strategy_id: int = None,
              notes: str = None) -> dict:
    """
    Loggt einen neuen Trade-Entry.
    Verknüpft automatisch mit den letzten NewsWire-Events für diesen Ticker.
    """
    conviction = get_conviction_score(ticker)

    # CRV berechnen wenn Stop vorhanden
    crv = None
    if stop_price and entry_price:
        risk = abs(entry_price - stop_price)
        # Ziel: 2× Risk als Minimum
        target_price = entry_price + (risk * 2) if direction == "long" else entry_price - (risk * 2)
        crv = round(risk * 2 / risk, 1) if risk > 0 else None

    event_ids = ",".join(str(i) for i in conviction.get("event_ids", [])[:5])
    trigger_headline = conviction.get("top_headline", "")[:200] if conviction.get("top_headline") else None

    conn = _conn()
    cursor = conn.execute("""
        INSERT INTO trades (
            ts_entry, ticker, direction, entry_price, stop_price,
            strategy_id, conviction_score, triggering_event_ids,
            trigger_headline, notes, outcome
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
    """, (
        now_ts(), ticker.upper(), direction.lower(),
        entry_price, stop_price, strategy_id,
        conviction["score"], event_ids, trigger_headline, notes
    ))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "conviction": conviction,
        "linked_events": len(conviction.get("event_ids", [])),
        "message": f"✅ Trade #{trade_id} geloggt: {direction.upper()} {ticker} @ {entry_price}€ | Conviction: {conviction['score']}/5 ({conviction['signal']})",
    }


def log_exit(ticker: str, exit_price: float, rule_violation: str = None) -> dict:
    """Loggt den Exit für den zuletzt offenen Trade eines Tickers."""
    conn = _conn()
    trade = conn.execute("""
        SELECT id, entry_price, direction, stop_price
        FROM trades
        WHERE ticker = ? AND outcome = 'open'
        ORDER BY ts_entry DESC LIMIT 1
    """, (ticker.upper(),)).fetchone()

    if not trade:
        conn.close()
        return {"error": f"Kein offener Trade für {ticker} gefunden"}

    trade_id, entry_price, direction, stop_price = trade
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    if direction == "short":
        pnl_pct = -pnl_pct

    outcome = "win" if pnl_pct > 0 else ("stopped" if stop_price and
              abs(exit_price - stop_price) < abs(exit_price - entry_price) * 0.1
              else "loss")

    conn.execute("""
        UPDATE trades
        SET ts_exit=?, exit_price=?, pnl_pct=?, outcome=?, rule_violation=?
        WHERE id=?
    """, (now_ts(), exit_price, round(pnl_pct, 2), outcome, rule_violation, trade_id))
    conn.commit()
    conn.close()

    emoji = "✅" if outcome == "win" else "❌"
    return {
        "trade_id": trade_id,
        "outcome": outcome,
        "pnl_pct": round(pnl_pct, 2),
        "rule_violation": rule_violation,
        "message": f"{emoji} Exit #{trade_id}: {ticker} @ {exit_price}€ | P&L: {pnl_pct:+.1f}% | {outcome.upper()}"
                   + (f" | ⚠️ Regel verletzt: {rule_violation}" if rule_violation else ""),
    }


def get_open_trades() -> list:
    conn = _conn()
    rows = conn.execute("""
        SELECT id, ts_entry, ticker, direction, entry_price, stop_price,
               strategy_id, conviction_score, trigger_headline
        FROM trades WHERE outcome = 'open'
        ORDER BY ts_entry DESC
    """).fetchall()
    conn.close()
    return rows


def get_stats(ticker: str = None) -> dict:
    """Zusammenfassung der Trading-Performance."""
    conn = _conn()
    where = "WHERE ticker = ? AND outcome != 'open'" if ticker else "WHERE outcome != 'open'"
    params = (ticker.upper(),) if ticker else ()

    rows = conn.execute(f"""
        SELECT ticker, direction, pnl_pct, outcome, conviction_score, rule_violation
        FROM trades {where}
    """, params).fetchall()
    conn.close()

    if not rows:
        return {"message": "Noch keine abgeschlossenen Trades"}

    wins   = [r for r in rows if r[3] == "win"]
    losses = [r for r in rows if r[3] in ("loss", "stopped")]
    violations = [r for r in rows if r[5]]

    avg_win  = sum(r[2] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r[2] for r in losses) / len(losses) if losses else 0
    win_rate = len(wins) / len(rows) * 100 if rows else 0

    # Conviction-Score Korrelation
    high_conv = [r for r in rows if r[4] and r[4] >= 4]
    high_conv_wr = sum(1 for r in high_conv if r[3] == "win") / len(high_conv) * 100 if high_conv else 0

    return {
        "total_trades": len(rows),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "rule_violations": len(violations),
        "high_conviction_win_rate": round(high_conv_wr, 1),
        "summary": (
            f"📊 {len(rows)} Trades | WR: {win_rate:.0f}% | "
            f"Avg Win: +{avg_win:.1f}% | Avg Loss: {avg_loss:.1f}% | "
            f"Regelverletzungen: {len(violations)} | "
            f"High-Conviction WR: {high_conv_wr:.0f}%"
        ),
    }


# ── Quick-Analyse: Wie gut funktioniert NewsWire als Signal? ──────────────────

def signal_accuracy_report() -> str:
    conn = _conn()
    rows = conn.execute("""
        SELECT
            direction,
            COUNT(*) as total,
            SUM(CASE WHEN outcome=1 THEN 1 ELSE 0 END) as correct,
            AVG(CASE WHEN price_at_event > 0
                     THEN ABS((price_4h_later - price_at_event) / price_at_event * 100)
                     ELSE NULL END) as avg_move_pct
        FROM events
        WHERE score >= 2
          AND outcome IS NOT NULL
          AND price_at_event IS NOT NULL
          AND price_4h_later IS NOT NULL
        GROUP BY direction
    """).fetchall()
    conn.close()

    if not rows:
        return "Noch keine Outcome-Daten — in ~4h nach heute Morgen verfügbar"

    lines = ["📈 NewsWire Signal-Accuracy (4h-Fenster):"]
    for direction, total, correct, avg_move in rows:
        acc = (correct / total * 100) if total > 0 else 0
        lines.append(f"  {direction:8}: {acc:.0f}% richtig ({correct}/{total}) | Avg Move: {avg_move:.1f}%")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== CONVICTION SCORES (letzte 2h) ===\n")
    for ticker in ["EQNR", "PLTR", "NVDA", "MSFT", "RHM.DE", "BAYN.DE", "AG"]:
        c = get_conviction_score(ticker)
        if c["score"] > 0:
            print(f"{ticker:10} Score: {c['score']}/5 [{c['signal']:6}] {c['direction']:8} | {c['events_count']} Events")
            for f in c["factors"]:
                print(f"           → {f}")
            if c.get("top_headline"):
                print(f"           Top: {c['top_headline'][:80]}")
            print()

    print("\n=== OFFENE TRADES ===")
    trades = get_open_trades()
    if trades:
        for t in trades:
            print(f"  #{t[0]} {t[3].upper()} {t[2]} @ {t[4]}€ | Stop: {t[5]}€ | Conviction: {t[7]}/5")
    else:
        print("  Keine offenen Trades geloggt")

    print(f"\n{signal_accuracy_report()}")
