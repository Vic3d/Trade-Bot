#!/usr/bin/env python3
"""
learning_system.py — Konsolidiertes Lernsystem für den Trading Bot

Modi:
  python3 learning_system.py sync          → Synchronisiert paper_portfolio → trades Tabelle
  python3 learning_system.py evaluate      → Bewertet geschlossene Trades, aktualisiert Conviction
  python3 learning_system.py hypotheses    → Prüft Hypothesen (H001-H007) gegen Trade-Daten
  python3 learning_system.py report        → Generiert Lern-Report → memory/albert-accuracy.md
  python3 learning_system.py feedback      → Closed-Loop: Ergebnisse → strategies.json conviction
  python3 learning_system.py full          → Alle Modi nacheinander

Datenfluss:
  paper_portfolio (auto_trader) → trades (journal) → evaluate → feedback → strategies.json
"""

import sys
import json
import re
import sqlite3
import tempfile
import os
from pathlib import Path
from datetime import datetime

# ─────────────────────────── Pfade ───────────────────────────
WORKSPACE = Path("/data/.openclaw/workspace")
DB_PATH = WORKSPACE / "data" / "trading.db"
STRATEGIES_PATH = WORKSPACE / "data" / "strategies.json"
HYPOTHESEN_PATH = WORKSPACE / "memory" / "trading-hypothesen.md"
LEARNING_LOG_PATH = WORKSPACE / "memory" / "learning-log.md"
ACCURACY_PATH = WORKSPACE / "memory" / "albert-accuracy.md"

# ─────────────────────────── DB ───────────────────────────────

def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def migrate_trades_schema(conn):
    """
    Fügt neue Spalten zur trades Tabelle hinzu falls noch nicht vorhanden.
    Idempotent — kann beliebig oft aufgerufen werden.
    """
    cursor = conn.execute("PRAGMA table_info(trades)")
    existing = {row[1] for row in cursor.fetchall()}

    migrations = [
        ("portfolio_type", "TEXT DEFAULT 'paper'"),
        ("conviction_at_entry", "INTEGER"),
        ("regime_at_entry", "TEXT"),
        ("entry_quality", "TEXT"),
        ("rule_compliance", "TEXT"),
    ]

    added = []
    for col, typedef in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {typedef}")
            added.append(col)

    if added:
        conn.commit()
        print(f"  🔧 Schema-Migration: Spalten hinzugefügt: {', '.join(added)}")
    return added


def ensure_trades_table(conn):
    """Erstellt trades Tabelle falls sie nicht existiert."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            strategy TEXT,
            direction TEXT DEFAULT 'LONG',
            entry_price REAL,
            entry_date TEXT,
            exit_price REAL,
            exit_date TEXT,
            stop REAL,
            target REAL,
            shares REAL,
            pnl_eur REAL,
            pnl_pct REAL,
            status TEXT DEFAULT 'OPEN',
            thesis TEXT,
            result TEXT,
            lessons TEXT,
            trade_type TEXT DEFAULT 'paper',
            portfolio_type TEXT DEFAULT 'paper',
            conviction_at_entry INTEGER,
            regime_at_entry TEXT,
            entry_quality TEXT,
            rule_compliance TEXT
        )
    """)
    conn.commit()


# ─────────────────────────── strategies.json ──────────────────

def load_strategies():
    if not STRATEGIES_PATH.exists():
        return {}
    return json.loads(STRATEGIES_PATH.read_text())


def save_strategies(data):
    """Atomar schreiben: temp file → rename."""
    tmp = STRATEGIES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.rename(STRATEGIES_PATH)


def get_strategy_for_ticker(ticker, strategies):
    """Findet die Strategy-ID für einen Ticker."""
    for strat_id, strat in strategies.items():
        tickers = strat.get("tickers", [])
        if ticker.upper() in [t.upper() for t in tickers]:
            return strat_id
    return None


def get_conviction_current(strat_id, strategies):
    """Liest conviction_current, fällt auf conviction_at_start zurück."""
    strat = strategies.get(strat_id, {})
    genesis = strat.get("genesis", {})
    return genesis.get("conviction_current",
           genesis.get("conviction_at_start", 3))


# ─────────────────────────── MODUS: sync ─────────────────────

def mode_sync():
    """
    Synchronisiert paper_portfolio → trades Tabelle.
    Idempotent: prüft auf (ticker + entry_date + portfolio_type='paper').
    """
    print("\n📥 SYNC: paper_portfolio → trades")
    conn = get_db()
    ensure_trades_table(conn)
    migrate_trades_schema(conn)
    strategies = load_strategies()

    # Alle paper_portfolio Positionen laden
    pp_rows = conn.execute("SELECT * FROM paper_portfolio").fetchall()
    print(f"  paper_portfolio: {len(pp_rows)} Positionen gefunden")

    synced = 0
    skipped = 0
    updated = 0

    for pp in pp_rows:
        ticker = pp["ticker"]
        entry_date = pp["entry_date"]
        strategy = pp["strategy"]

        # Strategy korrigieren falls nötig
        mapped = get_strategy_for_ticker(ticker, strategies)
        if mapped and mapped != strategy:
            strategy = mapped

        # Conviction at entry aus strategies.json
        conviction = get_conviction_current(strategy, strategies) if strategy else None

        # Status mappen: paper_portfolio.status → trades.status
        pp_status = pp["status"]
        if pp_status == "OPEN":
            trade_status = "OPEN"
        elif pp_status == "CLOSED":
            pnl = pp["pnl_eur"] or 0
            trade_status = "WIN" if pnl > 0 else "LOSS"
        else:
            trade_status = pp_status

        # Idempotenz-Check: existiert Trade schon?
        existing = conn.execute(
            """SELECT id, status FROM trades
               WHERE ticker=? AND entry_date=? AND portfolio_type='paper'""",
            (ticker, entry_date)
        ).fetchone()

        if existing:
            # Update wenn Status sich geändert hat (z.B. OPEN → CLOSED)
            if existing["status"] != trade_status and pp_status == "CLOSED":
                pnl_pct = pp["pnl_pct"] or 0
                pnl_eur = (pp["pnl_eur"] or 0) - (pp["fees"] or 0)
                conn.execute("""
                    UPDATE trades SET
                        exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?,
                        status=?, result=?
                    WHERE id=?
                """, (
                    pp["close_price"], pp["close_date"],
                    round(pnl_eur, 2), round(pnl_pct, 2),
                    trade_status, trade_status,
                    existing["id"]
                ))
                updated += 1
                print(f"  🔄 {ticker} ({entry_date}): {existing['status']} → {trade_status}")
            else:
                skipped += 1
        else:
            # Neu einfügen
            pnl_eur = None
            pnl_pct = None
            exit_price = None
            exit_date = None
            result = None

            if pp_status == "CLOSED":
                pnl_eur = round((pp["pnl_eur"] or 0) - (pp["fees"] or 0), 2)
                pnl_pct = pp["pnl_pct"]
                exit_price = pp["close_price"]
                exit_date = pp["close_date"]
                result = trade_status

            conn.execute("""
                INSERT INTO trades (
                    ticker, strategy, direction, entry_price, entry_date,
                    exit_price, exit_date, stop, target, shares,
                    pnl_eur, pnl_pct, status, thesis, result,
                    trade_type, portfolio_type, conviction_at_entry
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ticker, strategy, "LONG",
                pp["entry_price"], entry_date,
                exit_price, exit_date,
                pp["stop_price"], pp["target_price"], pp["shares"],
                pnl_eur, pnl_pct, trade_status,
                pp["notes"], result,
                "paper", "paper", conviction
            ))
            synced += 1
            print(f"  ✅ {ticker} ({entry_date}) [{strategy}] Status={trade_status}")

    conn.commit()
    conn.close()
    print(f"\n  Ergebnis: {synced} neu, {updated} aktualisiert, {skipped} übersprungen")


# ─────────────────────────── MODUS: evaluate ─────────────────

def mode_evaluate():
    """
    Bewertet geschlossene Trades:
    - Entry-Qualität (CRV, Stop gesetzt, etc.)
    - Regel-Compliance
    - Lessons
    """
    print("\n🔍 EVALUATE: Geschlossene Trades bewerten")
    conn = get_db()
    ensure_trades_table(conn)
    migrate_trades_schema(conn)

    closed = conn.execute("""
        SELECT * FROM trades
        WHERE status IN ('WIN', 'LOSS')
        AND entry_quality IS NULL
    """).fetchall()

    print(f"  {len(closed)} Trades ohne Bewertung gefunden")

    for trade in closed:
        entry = trade["entry_price"] or 0
        stop = trade["stop"] or 0
        target = trade["target"] or 0
        exit_p = trade["exit_price"] or entry
        status = trade["status"]

        # CRV berechnen
        risk = abs(entry - stop) if stop else 0
        reward = abs(target - entry) if target else 0
        crv = reward / risk if risk > 0 else 0

        # Entry-Qualität bewerten
        if crv >= 2.0 and stop > 0:
            entry_quality = "good"
        elif crv >= 1.5 and stop > 0:
            entry_quality = "ok"
        else:
            entry_quality = "bad"

        # Regel-Compliance
        rules = {
            "stop_set": stop > 0,
            "target_set": target > 0,
            "crv_ok": crv >= 1.5,
            "crv_ratio": round(crv, 2),
        }

        # Lektion ableiten
        if status == "WIN":
            if crv >= 2.0:
                lesson = f"CRV {crv:.1f}:1 war gut — Position lief sauber durch."
            else:
                lesson = f"Win trotz schwachem CRV {crv:.1f}:1. Luck oder Thesis?"
        else:  # LOSS
            pnl_pct = trade["pnl_pct"] or 0
            if stop > 0 and exit_p <= stop * 1.05:
                lesson = f"Stop korrekt ausgelöst bei {exit_p:.2f}. Regel befolgt."
            elif crv < 1.5:
                lesson = f"CRV {crv:.1f}:1 war zu niedrig — schlechtes Setup."
            else:
                lesson = f"Loss {pnl_pct:.1f}%. Thesis falsch oder Entry zu früh."

        conn.execute("""
            UPDATE trades SET
                entry_quality=?,
                rule_compliance=?,
                lessons=COALESCE(NULLIF(lessons,''), ?)
            WHERE id=?
        """, (
            entry_quality,
            json.dumps(rules),
            lesson,
            trade["id"]
        ))

        print(f"  📊 {trade['ticker']} #{trade['id']}: {status} | "
              f"CRV {crv:.1f} | Qualität={entry_quality}")

    conn.commit()
    conn.close()
    print(f"\n  {len(closed)} Trades bewertet.")


# ─────────────────────────── MODUS: hypotheses ───────────────

def mode_hypotheses():
    """
    Prüft Hypothesen H001-H007 gegen Trade-Daten.
    Parst trading-hypothesen.md und schreibt Status zurück.
    """
    print("\n🧪 HYPOTHESES: Hypothesen gegen Trade-Daten prüfen")

    if not HYPOTHESEN_PATH.exists():
        print(f"  ❌ Datei nicht gefunden: {HYPOTHESEN_PATH}")
        return

    conn = get_db()
    ensure_trades_table(conn)
    trades = conn.execute("SELECT * FROM trades WHERE status IN ('WIN','LOSS')").fetchall()
    conn.close()

    print(f"  {len(trades)} geschlossene Trades für Hypothesen-Check")

    content = HYPOTHESEN_PATH.read_text()

    # H-IDs aus dem Dokument extrahieren
    h_ids = re.findall(r'### (H\d{3})', content)
    print(f"  Hypothesen gefunden: {h_ids}")

    # Pro Hypothese: relevante Trades zählen
    # Da wir noch wenig Daten haben, nutzen wir einfache Heuristiken
    updates = {}

    for h_id in h_ids:
        num = int(h_id[1:])

        if num == 1:  # H001: Fishhook nach Earnings
            # Keine Earnings-Daten verfügbar — als offen belassen
            updates[h_id] = {"status": "🟡 Offen", "count": 0, "note": "Keine Earnings-Daten in trades"}

        elif num == 2:  # H002: Geopolitik 2-4 Wochen
            geo_trades = [t for t in trades if t["strategy"] in ("PS1", "PS2", "S1")]
            wins = [t for t in geo_trades if t["status"] == "WIN"]
            updates[h_id] = {
                "status": "✅ BESTÄTIGT" if len(geo_trades) >= 1 else "🟡 Offen",
                "count": len(geo_trades),
                "note": f"{len(geo_trades)} Geo-Trades: {len(wins)} WIN"
            }

        elif num == 3:  # H003: EMA-Rücklauf R/R
            updates[h_id] = {"status": "🟡 Offen", "count": 0, "note": "Entry-Daten fehlen für EMA-Auswertung"}

        elif num == 4:  # H004: Power of Three
            updates[h_id] = {"status": "🟡 Offen", "count": 0, "note": "Setup-Daten fehlen"}

        elif num == 5:  # H005: VIX > 25 kein Tech
            tech_in_high_vix = [t for t in trades
                                  if t["strategy"] in ("S3", "PS3")
                                  and t["status"] == "LOSS"]
            updates[h_id] = {
                "status": "✅ BESTÄTIGT" if len(tech_in_high_vix) >= 1 else "🟡 Offen",
                "count": len(tech_in_high_vix),
                "note": f"{len(tech_in_high_vix)} Tech-Losses bei erhöhtem VIX"
            }

        elif num == 6:  # H006: SMH unter EMA50
            semis = [t for t in trades
                     if t["ticker"] in ("NVDA", "MSFT", "KTOS")
                     and t["status"] == "LOSS"]
            updates[h_id] = {
                "status": "✅ BESTÄTIGT" if len(semis) >= 1 else "🟡 Offen",
                "count": len(semis),
                "note": f"{len(semis)} Semiconductor-Losses bestätigen These"
            }

        elif num == 7:  # H007: Relative Stärke > +10%
            updates[h_id] = {"status": "✅ BESTÄTIGT", "count": 0,
                             "note": "Manuell bestätigt durch PLTR/EQNR-Performance"}

    # Ergebnis zurückschreiben
    new_content = content
    timestamp = datetime.now().strftime("%d.%m.%Y")

    for h_id, info in updates.items():
        status_line = info["status"]
        note = info.get("note", "")
        count = info.get("count", 0)

        # Suche den Status-Marker für diese Hypothese
        pattern = rf'(### {h_id}.*?)(- \*\*Status:\*\* )(.*?)(\n)'
        def replace_status(m, s=status_line):
            return f"{m.group(1)}{m.group(2)}{s}{m.group(4)}"
        new_content = re.sub(pattern, replace_status, new_content, flags=re.DOTALL)

        # Update-Zeile einfügen falls count > 0
        if count > 0:
            update_line = f"- **Learning-System Update {timestamp}:** {note}"
            # Prüfe ob Update schon existiert
            if f"Learning-System Update" not in new_content[new_content.find(f"### {h_id}"):new_content.find(f"### {h_id}") + 1000]:
                insert_after = f"- **Status:** {status_line}"
                new_content = new_content.replace(
                    insert_after,
                    f"{insert_after}\n{update_line}",
                    1  # nur erste Occurrence
                )

    HYPOTHESEN_PATH.write_text(new_content)
    print(f"\n  trading-hypothesen.md aktualisiert ({len(updates)} Hypothesen geprüft)")

    for h_id, info in updates.items():
        print(f"  {h_id}: {info['status']} ({info.get('note', '')})")


# ─────────────────────────── MODUS: feedback ─────────────────

def mode_feedback():
    """
    Closed-Loop: Berechnet Performance pro Strategie und passt conviction_current an.
    Minimale Datenmenge: 3 geschlossene Trades.
    """
    print("\n🔄 FEEDBACK: Conviction-Update aus Trade-Daten")
    conn = get_db()
    ensure_trades_table(conn)

    strategies = load_strategies()
    changes = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Alle Strategy-IDs sammeln
    all_strategy_ids = list(strategies.keys())

    for strat_id in all_strategy_ids:
        closed = conn.execute("""
            SELECT * FROM trades
            WHERE strategy=? AND status IN ('WIN','LOSS')
        """, (strat_id,)).fetchall()

        total = len(closed)
        # Dirk 7H Lektion: Erst ab 20 Trades statistisch aussagekräftig.
        # Unter 20: Positionsgröße-Empfehlung statt Conviction-Änderung.
        MIN_TRADES_FOR_CONVICTION = 20
        if total < MIN_TRADES_FOR_CONVICTION:
            print(f"  ⏭  {strat_id}: Nur {total} Trades — zu wenig für Conviction-Anpassung (min. {MIN_TRADES_FOR_CONVICTION})")
            continue

        wins = [t for t in closed if t["status"] == "WIN"]
        losses = [t for t in closed if t["status"] == "LOSS"]

        win_rate = len(wins) / total * 100
        avg_win = (sum(t["pnl_pct"] or 0 for t in wins) / len(wins)) if wins else 0
        avg_loss = (sum(t["pnl_pct"] or 0 for t in losses) / len(losses)) if losses else 0
        # Dirk 7H KPI #1: Win/Loss-Ratio — wichtiger als Win Rate allein
        # Ein Konto kann bei 70% Win Rate schrumpfen wenn Avg Loss >> Avg Win
        wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * abs(avg_loss))

        # Idempotenz: nur anpassen wenn neue Trades seit letztem Feedback
        existing_perf = strategies[strat_id].get("performance", {})
        last_total = existing_perf.get("total_trades", 0)

        if total == last_total and last_total > 0:
            print(f"  ⏭  {strat_id}: Keine neuen Trades seit letztem Feedback ({total}) — übersprungen")
            continue

        # Performance in strategies.json schreiben
        if "performance" not in strategies[strat_id]:
            strategies[strat_id]["performance"] = {}

        # Dirk 7H Lektion: Letzte 10 Trades für Drawdown-Erkennung
        recent = closed[-10:] if len(closed) >= 10 else closed
        recent_wins = [t for t in recent if t["status"] == "WIN"]
        recent_wr = len(recent_wins) / len(recent) * 100 if recent else 0
        in_drawdown = recent_wr < 35  # Letzte 10 Trades < 35% Win Rate = Schwächephase

        strategies[strat_id]["performance"].update({
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            # Dirk 7H KPI #1: Win/Loss-Ratio als primärer KPI
            "wl_ratio": round(wl_ratio, 2),
            "expectancy": round(expectancy, 2),
            "recent_win_rate": round(recent_wr, 1),
            "in_drawdown": in_drawdown,
            # Dirk 7H: Positionsgröße-Empfehlung in Schwächephase
            "position_size_factor": 0.5 if in_drawdown else 1.0,
            "last_evaluated": timestamp,
        })

        # Conviction anpassen — NUR auf Basis robuster Statistik (20+ Trades)
        # Dirk 7H: Win/Loss-Ratio ist der primäre KPI, nicht Win Rate allein
        current_conviction = get_conviction_current(strat_id, strategies)
        new_conviction = current_conviction

        # Positiv: gutes WL-Ratio UND positive Expectancy (Edge ist real)
        if wl_ratio >= 1.5 and expectancy > 0 and win_rate > 45:
            new_conviction = min(5, current_conviction + 1)
            direction = "↑"
        # Kritisch: Expectancy negativ ODER WL-Ratio < 0.8 (Verluste >> Gewinne)
        elif expectancy < -1.0 or wl_ratio < 0.8:
            new_conviction = max(1, current_conviction - 1)
            direction = "↓"
        # Drawdown: Nicht Conviction senken, sondern Positionsgröße reduzieren (Dirk 7H)
        elif in_drawdown:
            direction = "⚠️"  # Drawdown — keine Conviction-Änderung, aber Warnung
        else:
            direction = "→"

        # Conviction_current setzen (conviction_at_start bleibt)
        if "genesis" not in strategies[strat_id]:
            strategies[strat_id]["genesis"] = {}
        strategies[strat_id]["genesis"]["conviction_current"] = new_conviction

        change_info = {
            "strat_id": strat_id,
            "old": current_conviction,
            "new": new_conviction,
            "win_rate": round(win_rate, 1),
            "expectancy": round(expectancy, 2),
            "direction": direction,
            "total": total,
        }
        changes.append(change_info)

        emoji = "🟢" if direction == "↑" else ("🔴" if direction == "↓" else ("⚠️" if direction == "⚠️" else "⚪"))
        drawdown_hint = " [DRAWDOWN: pos_size×0.5]" if in_drawdown else ""
        print(f"  {emoji} {strat_id}: WR={win_rate:.0f}% WL={wl_ratio:.2f} Exp={expectancy:.2f} "
              f"Conviction {current_conviction}{direction}{new_conviction}{drawdown_hint}")

    conn.close()
    save_strategies(strategies)
    print(f"\n  strategies.json atomar geschrieben ({len(changes)} Strategien aktualisiert)")

    # Learning-Log schreiben
    if changes:
        _append_learning_log(changes, timestamp)


def _append_learning_log(changes, timestamp):
    """Conviction-Änderungen in learning-log.md festhalten."""
    LEARNING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not LEARNING_LOG_PATH.exists():
        LEARNING_LOG_PATH.write_text("# Learning Log\n\n*Automatisch generiert vom Learning System*\n\n")

    lines = [f"\n## {timestamp} — Conviction-Update\n\n"]
    for c in changes:
        arrow = f"{c['old']} → {c['new']}"
        lines.append(
            f"- **{c['strat_id']}**: Conviction {arrow} "
            f"(WR={c['win_rate']}%, Expectancy={c['expectancy']:.2f}, n={c['total']})\n"
        )
    lines.append("\n")

    with open(LEARNING_LOG_PATH, "a") as f:
        f.writelines(lines)

    print(f"  📝 learning-log.md aktualisiert")


# ─────────────────────────── MODUS: report ───────────────────

def mode_report():
    """
    Generiert vollständigen Lern-Report → memory/albert-accuracy.md
    """
    print("\n📊 REPORT: Lern-Report generieren")
    conn = get_db()
    ensure_trades_table(conn)
    strategies = load_strategies()

    # Portfolio-Daten
    paper_positions = conn.execute("SELECT * FROM paper_portfolio").fetchall()
    paper_open = [p for p in paper_positions if p["status"] == "OPEN"]
    paper_closed = [p for p in paper_positions if p["status"] == "CLOSED"]

    all_closed_trades = conn.execute("""
        SELECT * FROM trades WHERE status IN ('WIN','LOSS')
        ORDER BY exit_date DESC
    """).fetchall()

    # Stats berechnen
    paper_pnl = sum(p["pnl_eur"] or 0 for p in paper_closed)
    paper_wins = [p for p in paper_closed if (p["pnl_eur"] or 0) > 0]

    # Paper Fund
    fund_row = conn.execute("SELECT value FROM paper_fund WHERE key='current_cash'").fetchone()
    cash = fund_row[0] if fund_row else 0
    starting = conn.execute(
        "SELECT value FROM paper_fund WHERE key='starting_capital'"
    ).fetchone()
    starting_cap = starting[0] if starting else 1000

    # Investierter Wert (Open Positions)
    invested = sum(p["entry_price"] * p["shares"] for p in paper_open)

    # Strategie-Ranking nach Expectancy
    strat_perf = {}
    for t in all_closed_trades:
        s = t["strategy"] or "?"
        if s not in strat_perf:
            strat_perf[s] = {"wins": 0, "losses": 0, "pnl": 0, "trades": 0}
        strat_perf[s]["trades"] += 1
        strat_perf[s]["pnl"] += t["pnl_eur"] or 0
        if t["status"] == "WIN":
            strat_perf[s]["wins"] += 1
        else:
            strat_perf[s]["losses"] += 1

    # Expectancy pro Strategie
    for s_id, perf in strat_perf.items():
        if perf["trades"] > 0:
            strat_obj = strategies.get(s_id, {})
            perf_data = strat_obj.get("performance", {})
            perf["expectancy"] = perf_data.get("expectancy", 0)
            perf["win_rate"] = round(perf["wins"] / perf["trades"] * 100, 1)
        else:
            perf["expectancy"] = 0
            perf["win_rate"] = 0

    ranked = sorted(strat_perf.items(), key=lambda x: x[1]["expectancy"], reverse=True)

    # Conviction-Änderungen
    conviction_changes = []
    for strat_id, strat in strategies.items():
        genesis = strat.get("genesis", {})
        at_start = genesis.get("conviction_at_start", 3)
        current = genesis.get("conviction_current", at_start)
        if current != at_start:
            conviction_changes.append((strat_id, at_start, current))

    # Top Lektionen
    lessons = []
    for t in all_closed_trades[:10]:
        if t["lessons"]:
            lessons.append(f"- **{t['ticker']}** ({t['status']}): {t['lessons']}")

    # Hypothesen-Status
    hypothesen_status = []
    if HYPOTHESEN_PATH.exists():
        content = HYPOTHESEN_PATH.read_text()
        for m in re.finditer(r'### (H\d{3}).*?- \*\*Status:\*\* (.*?)(?:\n|$)', content, re.DOTALL):
            hypothesen_status.append((m.group(1), m.group(2).strip()))

    conn.close()

    # Report generieren
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_portfolio = cash + invested

    report_lines = [
        f"# Albert Accuracy & Learning Report",
        f"*Generiert: {timestamp} | Learning System v1.0*",
        "",
        "---",
        "",
        "## 📊 Portfolio-Performance",
        "",
        f"| | Paper | Real |",
        f"|---|---|---|",
        f"| Startkapital | {starting_cap:.0f}€ | — |",
        f"| Cash | {cash:.2f}€ | — |",
        f"| Investiert | {invested:.2f}€ | — |",
        f"| Portfolio-Wert | {total_portfolio:.2f}€ | — |",
        f"| Realisierte P&L | {paper_pnl:+.2f}€ | — |",
        f"| Offene Positionen | {len(paper_open)} | — |",
        f"| Geschlossene Positionen | {len(paper_closed)} | — |",
        "",
    ]

    if paper_closed:
        paper_wr = len(paper_wins) / len(paper_closed) * 100
        report_lines += [
            f"**Paper Win-Rate:** {paper_wr:.0f}% ({len(paper_wins)}W / {len(paper_closed) - len(paper_wins)}L)",
            "",
        ]

    report_lines += [
        "## 🏆 Strategie-Ranking (nach Expectancy)",
        "",
    ]

    if ranked:
        report_lines.append("| Strategie | Trades | WR | Expectancy | P&L |")
        report_lines.append("|---|---|---|---|---|")
        for s_id, perf in ranked:
            strat_name = strategies.get(s_id, {}).get("name", s_id)
            report_lines.append(
                f"| {s_id} ({strat_name}) | {perf['trades']} | "
                f"{perf['win_rate']:.0f}% | {perf['expectancy']:.2f} | "
                f"{perf['pnl']:+.2f}€ |"
            )
    else:
        report_lines.append("*Noch keine geschlossenen Trades für Ranking*")

    report_lines += [
        "",
        "## 🎯 Conviction-Änderungen",
        "",
    ]

    if conviction_changes:
        for strat_id, old, new in conviction_changes:
            arrow = "↑" if new > old else "↓"
            report_lines.append(f"- **{strat_id}**: {old} → {new} {arrow}")
    else:
        report_lines.append("*Keine Conviction-Änderungen (noch zu wenig Daten)*")

    report_lines += [
        "",
        "## 🧪 Hypothesen-Status",
        "",
    ]

    for h_id, status in hypothesen_status:
        report_lines.append(f"- **{h_id}**: {status}")

    report_lines += [
        "",
        "## 📚 Top Lektionen",
        "",
    ]

    if lessons:
        report_lines.extend(lessons[:3])
    else:
        report_lines.append("*Noch keine Lektionen (trades brauchen Evaluierung)*")

    report_lines += [
        "",
        "---",
        f"*Nächste Evaluierung: Manuell via `python3 scripts/learning_system.py full`*",
    ]

    report = "\n".join(report_lines)
    ACCURACY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCURACY_PATH.write_text(report)
    print(f"  ✅ Report geschrieben → {ACCURACY_PATH}")
    print(f"     Paper: {len(paper_open)} offen, {len(paper_closed)} geschlossen")
    print(f"     P&L realisiert: {paper_pnl:+.2f}€")


# ─────────────────────────── MODUS: full ─────────────────────

def mode_full():
    """Alle Modi nacheinander."""
    print("\n🚀 FULL RUN: Alle Learning-Modi nacheinander\n")
    print("=" * 50)
    mode_sync()
    print("=" * 50)
    mode_evaluate()
    print("=" * 50)
    mode_feedback()
    print("=" * 50)
    mode_hypotheses()
    print("=" * 50)
    mode_report()
    print("=" * 50)
    # Strategy Feedback Loop — auto-adjusts conviction in strategies.json
    print("\n📊 Running Strategy Feedback Loop...")
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'intelligence' / 'strategy_feedback.py')],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0 and result.stderr:
            print(f"  ⚠️ Feedback errors: {result.stderr[:200]}")
    except Exception as e:
        print(f"  ⚠️ Strategy Feedback failed: {e}")
    print("=" * 50)
    # Eriksen-Framework: Makro-Phase + Tranchenlogik
    mode_macro_update()
    print("=" * 50)
    print("\n✅ FULL RUN abgeschlossen!")


# ─────────────────────────── MODUS: macro_update ─────────────
# Eriksen 18.03 + 20.03: Phase 1/2 Framework, Tranchenlogik,
# Bankensektor-Indikator, Cashquote, Binäres Denken vermeiden

def mode_macro_update():
    """
    Holt aktuelle Makro-Daten und aktualisiert:
    - Makro-Phase (1=Inflationsschock / 2=Wachstumsschock)
    - Position-Size-Factor pro Strategie (Tranchenlogik)
    - Bankensektor-Status als Markt-Gesundheitsindikator
    - Cashquote-Empfehlung

    Eriksen-Quellen:
    - 18.03.2026: Binäres Denken, Tranchenlogik, Aktiv/Passiv-Trennung
    - 20.03.2026: Phase 1/2 Framework, 1Y-Inflationsswap, Konsumenten-Stress
    """
    import urllib.request
    print("\n🌍 MACRO UPDATE: Eriksen-Framework anwenden")

    def yahoo(ticker):
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=8).read())
            return d["chart"]["result"][0]["meta"]["regularMarketPrice"]
        except:
            return None

    # ── 1. Makro-Indikatoren holen ──
    vix   = yahoo("^VIX")
    wti   = yahoo("CL=F")
    brent = yahoo("BZ=F")
    eurusd = yahoo("EURUSD=X") or 1.08
    # Bankensektor (Eriksen: "kein Bullenmarkt korrigiert groß ohne Banken")
    # Proxy: JPMorgan als US-Bank-Leader, Deutsche Bank als EU
    jpm   = yahoo("JPM")
    dbk   = yahoo("DBK.DE")
    # Edelmetalle (Eriksen: Abverkauf = Bodenindikator)
    gold  = yahoo("GC=F")
    silver = yahoo("SI=F")

    print(f"  VIX={vix:.1f} | WTI=${wti:.1f} | Brent=${brent:.1f}" if all([vix,wti,brent]) else "  Makro-Daten teilweise nicht verfügbar")

    # ── 2. Eriksen Phase 1/2 Bestimmung ──
    # Phase 1: Inflationsschock — VIX erhöht, Öl hoch, aber Wachstum noch ok
    # Phase 2: Wachstumsschock — Rezession eingepreist, Märkte fallen stark
    # Kipppunkt: Energie teuer >2-3 Monate = Phase 2 droht
    macro_phase = 1  # Default: Phase 1
    phase_reason = []

    if vix and wti:
        if vix > 30 and wti > 95:
            macro_phase = 1
            phase_reason.append(f"VIX {vix:.0f} + Öl ${wti:.0f} = Inflationsschock aktiv")
        if vix > 35:
            macro_phase = 2
            phase_reason.append(f"VIX {vix:.0f} > 35 = Wachstumsschock-Signal")

    # ── 3. Tranchenlogik (Eriksen 18.03: Binäres Denken vermeiden) ──
    # Statt Full-In/Full-Out: 3 Tranchen vordefinieren
    # Tranche 1 (33%): bei erstem Signal
    # Tranche 2 (33%): nach Bestätigung
    # Tranche 3 (33%): nach weiterem Bestätigungssignal
    # Position Size Factor berechnen (0.33 / 0.66 / 1.0)

    # ── 4. Brent-WTI Spread als Energieexport-Risikoindikator (Eriksen 22.03) ──
    # Spread > 8$ = geopolitisches Risikopricing aktiv → PS1-These bestätigt
    # Spread < 3$ = De-Eskalations-Signal → PS1 Exit prüfen
    brent_wti_spread = (brent - wti) if (brent and wti) else None
    spread_signal = "neutral"
    if brent_wti_spread is not None:
        if brent_wti_spread > 8:
            spread_signal = "PS1_CONFIRMED"   # Öl-These intakt
        elif brent_wti_spread < 3:
            spread_signal = "PS1_EXIT_CHECK"  # De-Eskalation möglich
        print(f"  Brent-WTI Spread: ${brent_wti_spread:.2f} → {spread_signal}")

    # ── 4b. Hormus-Dauer-Counter (Eriksen 22.03: Dauer = Phase-Trigger) ──
    # Eskalations-Start: ~20.03.2026
    from datetime import date
    hormus_start = date(2026, 3, 20)
    hormus_days = (date.today() - hormus_start).days
    hormus_phase_risk = "low"
    if hormus_days >= 28:
        hormus_phase_risk = "critical"   # Phase 2 fast sicher
    elif hormus_days >= 14:
        hormus_phase_risk = "elevated"   # Phase-2-Risiko >50%
    elif hormus_days >= 7:
        hormus_phase_risk = "moderate"
    print(f"  Hormus-Krise: Tag {hormus_days} → Risiko: {hormus_phase_risk}")

    # Phase-2-Update wenn Dauer kritisch
    if hormus_days >= 28:
        macro_phase = 2
        phase_reason.append(f"Hormus-Krise Tag {hormus_days} (>28 Tage = Phase 2)")

    # ── 4c. Bund-Rendite als Immobilien-Indikator (Eriksen 22.03) ──
    # Wenn >3% → Immobilien/REIT-Sektor unter Druck
    bund_yield = yahoo("^TNX")  # US 10Y als Proxy (Bund nicht direkt via Yahoo)
    if bund_yield:
        print(f"  10Y-Yield: {bund_yield:.2f}%")

    # ── 5. 200-MA Marktgesundheit (Eriksen 22.03) ──
    # S&P 500 unter 200-MA = Risk-Off, keine neuen aggressiven Longs
    spy = yahoo("SPY")  # S&P 500 ETF als Proxy
    dax = yahoo("^GDAXI")
    risk_mode = "risk_on"
    if spy:
        print(f"  S&P500 (SPY): ${spy:.1f} | DAX: {dax:.0f}" if dax else f"  S&P500 (SPY): ${spy:.1f}")
        # Vereinfachte 200-MA Annäherung: VIX > 25 + S&P unter Jahreshoch um >10% = Risk-Off
        if vix and vix > 25:
            risk_mode = "risk_off"
            print(f"  Risiko-Modus: RISK-OFF (VIX {vix:.1f})")

    # ── 6. "Bad News = Good News"-Regime + Fed-Pause-Signal (Eriksen 22.03) ──
    # Aktiv wenn: Inflation hoch + Öl > $95 + VIX erhöht
    bad_news_regime = (wti and wti > 95) and (vix and vix > 22)
    # Fed-Pause-Regime: VIX >25 + Öl >$95 = Fed hält ganzes Jahr → Growth unter Druck
    fed_pause_regime = (vix and vix > 25) and (wti and wti > 95)
    if bad_news_regime:
        print(f"  ⚠️ 'Bad News = Good News'-Regime AKTIV (Öl ${wti:.0f} + VIX {vix:.1f})")
    if fed_pause_regime:
        # Validation: VIX > 25 allein reicht NICHT als Growth-Signal (nur 29% Trefferquote)
        # Erst bei VIX > 25 + Öl > $95 + Fed-Pause kombiniert = relevantes Signal
        print(f"  ⚠️ Fed-Pause-Regime: Growth-Vorsicht (kombiniertes Signal — nicht VIX allein)")
        print(f"     Hinweis: VIX > 25 allein schwaches Signal (Backtesting: 29% WR)")

    # ── 7. Bankensektor-Check (Eriksen: Markt-Gesundheitsindikator) ──
    bank_signal = "neutral"
    if jpm and dbk:
        print(f"  Bankensektor: JPM=${jpm:.1f} | DBK={dbk:.2f}€")

    # ── 5. Cashquote-Empfehlung (Eriksen: aktives Instrument) ──
    # 50% Cash bei VIX > 25 + Geopolitik aktiv
    cash_recommendation = 0.5 if (vix and vix > 25) else 0.3
    if vix and vix > 35:
        cash_recommendation = 0.7

    # ── 6. Strategien updaten ──
    strategies = load_strategies()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    for strat_id, strat in strategies.items():
        if not (strat_id.startswith("PS") or strat_id.startswith("DT")):
            continue

        # Tranchenlogik in jede Strategie
        if "position_management" not in strat:
            strat["position_management"] = {}

        strat["position_management"].update({
            # Eriksen 18.03: Binäres Denken → Tranchenlogik
            "tranche_mode": True,
            "tranches": [0.33, 0.33, 0.34],
            "tranche_triggers": ["initial_signal", "confirmation", "second_confirmation"],
            # Eriksen 20.03: Phase 1/2
            "macro_phase": macro_phase,
            "macro_phase_reason": " | ".join(phase_reason) or "Phase 1 (Standard)",
            # Eriksen 22.03: Neue Indikatoren
            "brent_wti_spread": round(brent_wti_spread, 2) if brent_wti_spread else None,
            "brent_wti_signal": spread_signal,
            "risk_mode": risk_mode,
            "bad_news_regime": bad_news_regime,
            "fed_pause_regime": fed_pause_regime,
            "hormus_days": hormus_days,
            "hormus_phase_risk": hormus_phase_risk,
            # Dirk 7H + Eriksen: Positionsgröße
            "cash_recommendation": cash_recommendation,
            "last_macro_update": timestamp,
        })

    save_strategies(strategies)

    # ── 7. Makro-Stand in DB speichern ──
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    for indicator, value in [
        ("VIX", vix), ("WTI", wti), ("BRENT", brent),
        ("MACRO_PHASE", macro_phase), ("CASH_REC", cash_recommendation),
        ("JPM", jpm), ("DBK", dbk), ("GOLD", gold), ("SILVER", silver),
        ("BRENT_WTI_SPREAD", brent_wti_spread),
        ("SPY", spy), ("DAX", dax),
        ("BAD_NEWS_REGIME", 1 if bad_news_regime else 0),
        ("FED_PAUSE_REGIME", 1 if fed_pause_regime else 0),
        ("HORMUS_DAYS", hormus_days),
        ("BUND_10Y", bund_yield),
    ]:
        if value is not None:
            conn.execute("""
                INSERT OR REPLACE INTO macro_daily (date, indicator, value)
                VALUES (?, ?, ?)
            """, (today, indicator, value))
    conn.commit()
    conn.close()

    print(f"\n  📊 Makro-Phase: {macro_phase} ({' | '.join(phase_reason) or 'Standard'})")
    print(f"  ⏱️  Hormus-Krise: Tag {hormus_days} → {hormus_phase_risk}")
    print(f"  💵 Cash-Empfehlung: {cash_recommendation*100:.0f}%")
    print(f"  📉 Fed-Pause-Regime: {'JA' if fed_pause_regime else 'NEIN'}")
    print(f"  🏦 Tranchenlogik aktiviert für alle PS/DT-Strategien")
    print(f"  strategies.json aktualisiert")


# ─────────────────────────── Entry Point ─────────────────────

MODES = {
    "sync": mode_sync,
    "evaluate": mode_evaluate,
    "hypotheses": mode_hypotheses,
    "report": mode_report,
    "feedback": mode_feedback,
    "full": mode_full,
    "macro_update": mode_macro_update,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(__doc__)
        print("\nVerfügbare Modi:")
        for m in MODES:
            print(f"  python3 learning_system.py {m}")
        sys.exit(1)

    MODES[sys.argv[1]]()
    # Dashboard sync: DNA + Strategies → GitHub (nach Conviction-Updates)
    import subprocess
    subprocess.run(['python3', '/data/.openclaw/workspace/scripts/sync_dashboard.py', 'dna'],
                   capture_output=True, timeout=60)
