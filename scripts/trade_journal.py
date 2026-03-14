#!/usr/bin/env python3
"""
Trade Journal — Trades loggen, auswerten, Regeln prüfen.

Verwendung (Victor via Discord → Albert parsed es):
  Einstieg: "trade EQNR long 28.40 stop 24.00 [target 34.00] [size 500]"
  Ausstieg: "exit EQNR 31.20"
  Log view: python3 trade_journal.py --report

Albert kann auch direkt loggen:
  python3 trade_journal.py --entry EQNR long 28.40 24.00
  python3 trade_journal.py --exit EQNR 31.20
  python3 trade_journal.py --report [--days 30]
"""

import sqlite3, json, time, sys, os, argparse, urllib.request
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")

STRATEGY_MAP = {
    "EQNR": 1, "DR0.DE": 1,
    "RHM.DE": 2,
    "NVDA": 3, "MSFT": 3, "PLTR": 3,
    "AG": 4, "ISPA.DE": 4,
    "RIO.L": 5,
}

BENCHMARK_MAP = {
    1: "CL=F",      # S1 Öl: WTI Crude
    2: "^STOXX",    # S2 Rüstung: Stoxx 600
    3: "^NDX",      # S3 Tech: Nasdaq 100
    4: "GC=F",      # S4 Silber: Gold als Proxy
    5: "HG=F",      # S5 Rohstoffe: Copper Futures
}

def yahoo_price(ticker: str) -> float | None:
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        return d["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        return None

def get_recent_events(ticker: str, hours: int = 6) -> list:
    """Hole relevante NewsWire-Events der letzten N Stunden für diesen Ticker."""
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - (hours * 3600)
    rows = conn.execute("""
        SELECT id, headline, direction, score
        FROM events
        WHERE ts > ? AND (ticker LIKE ? OR ticker LIKE ?)
          AND score >= 2
        ORDER BY score DESC, ts DESC
        LIMIT 5
    """, (cutoff, f"%{ticker}%", f"{ticker}%")).fetchall()
    conn.close()
    return rows

def log_entry(ticker: str, direction: str, entry: float, stop: float,
              target: float = None, size_eur: float = None, notes: str = None) -> int:
    """Neuen Trade einloggen."""
    conn = sqlite3.connect(DB_PATH)
    now = int(time.time())

    strategy_id = STRATEGY_MAP.get(ticker)
    benchmark = BENCHMARK_MAP.get(strategy_id) if strategy_id else None

    # CRV berechnen
    crv = None
    if target and stop and entry:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        crv = round(reward / risk, 2) if risk > 0 else None

    # Letzte relevante Headlines verknüpfen
    recent = get_recent_events(ticker, hours=6)
    event_ids = ",".join(str(r[0]) for r in recent) if recent else None
    trigger = recent[0][1][:120] if recent else None

    # CRV-Regel prüfen
    rule_followed = 1
    violation = None
    if crv and crv < 2.0:
        rule_followed = 0
        violation = f"CRV {crv} < 2.0 (Mindestregel)"

    conn.execute("""
        INSERT INTO trades (ts_entry, ticker, direction, entry_price, stop_price,
                           target_price, size_eur, strategy_id, crv, rule_followed,
                           rule_violation, linked_event_ids, trigger_headline,
                           benchmark_ticker, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (now, ticker, direction, entry, stop, target, size_eur, strategy_id,
          crv, rule_followed, violation, event_ids, trigger, benchmark, notes))
    trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    print(f"✅ Trade #{trade_id} geloggt: {ticker} {direction} @ {entry}€")
    print(f"   Stop: {stop}€ | Target: {target or '—'}€ | CRV: {crv or '—'}")
    if violation:
        print(f"   ⚠️  Regelverstoß: {violation}")
    if trigger:
        print(f"   📰 Trigger: {trigger[:80]}...")
    if recent:
        print(f"   🔗 {len(recent)} NewsWire-Events verknüpft")
    return trade_id

def log_exit(ticker: str, exit_price: float, notes: str = None) -> None:
    """Offenen Trade schließen."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("""
        SELECT id, entry_price, stop_price, size_eur, direction, strategy_id, benchmark_ticker
        FROM trades WHERE ticker=? AND ts_exit IS NULL
        ORDER BY ts_entry DESC LIMIT 1
    """, (ticker,)).fetchone()

    if not row:
        print(f"❌ Kein offener Trade für {ticker} gefunden")
        conn.close()
        return

    tid, entry, stop, size, direction, strategy_id, bench = row
    now = int(time.time())

    # P&L berechnen
    if direction == "long":
        pnl_pct = (exit_price - entry) / entry * 100
    else:
        pnl_pct = (entry - exit_price) / entry * 100

    pnl_eur = (size * pnl_pct / 100) if size else None

    # Benchmark-Move holen
    bench_move = None
    outcome_vs_bench = None
    if bench:
        bench_price_now = yahoo_price(bench)
        # Vereinfacht: wir nehmen den aktuellen Benchmarkpreis
        # Für echte Auswertung brauchen wir Benchmark-Preis bei Entry — wird nachgetragen
        if bench_price_now:
            pass  # TODO: Benchmark-Entry-Preis bei Trade-Log mitspeichern

    conn.execute("""
        UPDATE trades SET ts_exit=?, exit_price=?, pnl_pct=?, pnl_eur=?,
                         benchmark_move_pct=?, outcome_vs_benchmark=?, notes=?
        WHERE id=?
    """, (now, exit_price, round(pnl_pct, 2), pnl_eur, bench_move, outcome_vs_bench,
          notes, tid))
    conn.commit()
    conn.close()

    emoji = "🟢" if pnl_pct > 0 else "🔴"
    print(f"{emoji} Trade #{tid} geschlossen: {ticker} @ {exit_price}€")
    print(f"   P&L: {pnl_pct:+.2f}%{f' = {pnl_eur:+.0f}€' if pnl_eur else ''}")

def report(days: int = 30) -> None:
    """Lernbericht ausgeben."""
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - (days * 86400)

    # Abgeschlossene Trades
    closed = conn.execute("""
        SELECT ticker, direction, entry_price, exit_price, pnl_pct, pnl_eur,
               crv, rule_followed, rule_violation, strategy_id, trigger_headline
        FROM trades WHERE ts_exit IS NOT NULL AND ts_entry > ?
        ORDER BY ts_entry DESC
    """, (cutoff,)).fetchall()

    # Offene Trades
    open_trades = conn.execute("""
        SELECT ticker, direction, entry_price, stop_price, target_price, crv, ts_entry
        FROM trades WHERE ts_exit IS NULL
        ORDER BY ts_entry DESC
    """).fetchall()

    # Regel-Verstöße
    violations = [r for r in closed if r[7] == 0]

    # Keyword Accuracy
    accuracy = conn.execute("""
        SELECT direction,
               COUNT(*) as total,
               SUM(outcome) as correct,
               ROUND(100.0 * SUM(outcome) / COUNT(*), 1) as pct
        FROM events
        WHERE outcome IS NOT NULL AND ts > ?
        GROUP BY direction
    """, (cutoff,)).fetchall()

    print(f"\n{'='*60}")
    print(f"TRADE JOURNAL REPORT — letzte {days} Tage")
    print(f"{'='*60}\n")

    print(f"📊 OFFENE POSITIONEN ({len(open_trades)})")
    for t in open_trades:
        age_h = (time.time() - t[6]) / 3600
        print(f"  {t[0]:10} {t[1]:5} @ {t[2]}€ | Stop {t[3]}€ | Target {t[4] or '—'}€ | CRV {t[5] or '—'} | seit {age_h:.0f}h")

    print(f"\n📈 ABGESCHLOSSENE TRADES ({len(closed)})")
    if closed:
        wins = [t for t in closed if (t[4] or 0) > 0]
        losses = [t for t in closed if (t[4] or 0) <= 0]
        avg_win = sum(t[4] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t[4] for t in losses) / len(losses) if losses else 0
        win_rate = len(wins) / len(closed) * 100 if closed else 0
        total_pnl = sum(t[5] or 0 for t in closed)

        print(f"  Win-Rate: {win_rate:.0f}% ({len(wins)}W / {len(losses)}L)")
        print(f"  Avg Win:  {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}%")
        print(f"  Total P&L: {total_pnl:+.0f}€")
        print(f"  Regel-Verstöße: {len(violations)}/{len(closed)} Trades")

        for t in closed:
            emoji = "🟢" if (t[4] or 0) > 0 else "🔴"
            viol = " ⚠️" if t[7] == 0 else ""
            print(f"  {emoji} {t[0]:10} {t[1]:5} {t[4]:+.1f}%{viol}")

    print(f"\n🎯 KEYWORD ACCURACY (NewsWire)")
    if accuracy:
        for row in accuracy:
            print(f"  {row[0]:8}: {row[2] or 0}/{row[1]} richtig = {row[3] or 0:.1f}%")
    else:
        print("  Noch keine validierten Events (braucht 4h-Preisdaten)")

    print(f"\n⚠️  REGEL-VERSTÖSSE")
    if violations:
        for v in violations:
            print(f"  {v[0]}: {v[8]}")
    else:
        print("  Keine Verstöße ✅")

    conn.close()

def log_missed_signal(ticker: str, direction: str, headline: str,
                      strategy_id: int, price: float, reason: str = None):
    """Missed Signal loggen — Signal feuerte, aber nicht gehandelt."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO missed_signals (ts, ticker, direction, trigger_headline,
                                   strategy_id, price_at_signal, reason_not_traded)
        VALUES (?,?,?,?,?,?,?)
    """, (int(time.time()), ticker, direction, headline, strategy_id, price, reason))
    conn.commit()
    conn.close()
    print(f"📋 Missed Signal geloggt: {ticker} {direction} @ {price}€")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", nargs="+", help="TICKER long/short ENTRY STOP [TARGET] [SIZE]")
    parser.add_argument("--exit", nargs="+", help="TICKER EXIT_PRICE")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    if args.entry:
        a = args.entry
        ticker = a[0].upper()
        direction = a[1].lower()
        entry = float(a[2])
        stop = float(a[3])
        target = float(a[4]) if len(a) > 4 else None
        size = float(a[5]) if len(a) > 5 else None
        log_entry(ticker, direction, entry, stop, target, size)

    elif args.exit:
        ticker = args.exit[0].upper()
        price = float(args.exit[1])
        log_exit(ticker, price)

    elif args.report:
        report(days=args.days)

    else:
        report(days=7)
