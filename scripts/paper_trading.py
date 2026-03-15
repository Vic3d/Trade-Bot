#!/usr/bin/env python3
"""
Paper Trading System — Virtuelle Trades für Statistik-Integration
Trades werden in memory/paper-trades.md getracked und in Gesamtstatistik einbezogen.
Kein pandas/numpy — nur stdlib
"""

import re
import json
import math
import urllib.request
import urllib.error
from datetime import datetime, date
from typing import Optional

WORKSPACE = "/data/.openclaw/workspace"
PAPER_TRADES_FILE = f"{WORKSPACE}/memory/paper-trades.md"
ALERT_QUEUE_FILE  = f"{WORKSPACE}/alert-queue.json"
ACCURACY_FILE     = f"{WORKSPACE}/memory/albert-accuracy.md"


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().strftime("%d.%m.%Y")


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _parse_active_trades(content: str) -> list[dict]:
    """
    Parst die Aktive-Tabelle aus paper-trades.md.
    Erwartet Zeilen wie: | P001 | 17.03.2026 | DR0.DE | LONG | 87.30€ | ...
    """
    trades = []
    in_active = False
    header_passed = False

    for line in content.split("\n"):
        if "## Aktive Paper Trades" in line:
            in_active = True
            header_passed = False
            continue
        if in_active and line.startswith("## "):
            break
        if not in_active:
            continue

        # Tabellen-Header + Separator überspringen
        if line.startswith("| #") or line.startswith("|---|"):
            header_passed = True
            continue
        if not header_passed:
            continue

        if not line.startswith("|"):
            continue

        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 10:
            continue

        def parse_price(s: str) -> Optional[float]:
            m = re.search(r"[\d.]+", s.replace(",", "."))
            return float(m.group()) if m else None

        trade = {
            "id":         parts[0],
            "date":       parts[1],
            "ticker":     parts[2],
            "direction":  parts[3],
            "entry":      parse_price(parts[4]),
            "stop":       parse_price(parts[5]),
            "target1":    parse_price(parts[6]),
            "target2":    parse_price(parts[7]),
            "strategy":   parts[8],
            "status":     parts[9],
            "conviction": parts[10] if len(parts) > 10 else "—",
            "note":       parts[11] if len(parts) > 11 else "",
        }
        trades.append(trade)

    return trades


def _parse_closed_trades(content: str) -> list[dict]:
    """Parst abgeschlossene Trades (für Statistik)."""
    trades = []
    in_closed = False
    header_passed = False

    for line in content.split("\n"):
        if "## Abgeschlossene Paper Trades" in line:
            in_closed = True
            header_passed = False
            continue
        if in_closed and line.startswith("## "):
            break
        if not in_closed:
            continue

        if line.startswith("| #") or line.startswith("|---|"):
            header_passed = True
            continue
        if not header_passed:
            continue
        if not line.startswith("|"):
            continue

        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 8:
            continue

        def parse_price(s: str) -> Optional[float]:
            m = re.search(r"-?[\d.]+", s.replace(",", "."))
            return float(m.group()) if m else None

        def parse_pnl(s: str) -> Optional[float]:
            m = re.search(r"([+-]?[\d.]+)%", s)
            return float(m.group(1)) if m else parse_price(s)

        trade = {
            "id":       parts[0],
            "date":     parts[1],
            "ticker":   parts[2],
            "entry":    parse_price(parts[3]),
            "exit":     parse_price(parts[4]),
            "pnl":      parse_pnl(parts[5]),
            "result":   parts[6],       # ✅ oder ❌
            "strategy": parts[7],
            "duration": parts[8] if len(parts) > 8 else "—",
            "note":     parts[9] if len(parts) > 9 else "",
        }
        trades.append(trade)

    return trades


def _next_trade_id(content: str) -> str:
    """Generiert nächste Paper-Trade-ID (P001, P002, …)."""
    ids = re.findall(r"\bP(\d+)\b", content)
    if not ids:
        return "P001"
    max_id = max(int(i) for i in ids)
    return f"P{max_id + 1:03d}"


def _rebuild_file(active: list[dict], closed: list[dict]) -> str:
    """Baut paper-trades.md aus aktiven + abgeschlossenen Trades neu auf."""
    lines = [
        "# Paper Trades — Simulierte Trades für Statistik",
        "",
        "## Aktive Paper Trades",
        "",
        "| # | Datum | Aktie | Richtung | Entry | Stop | Ziel 1 | Ziel 2 | Strategie | Status | Conviction | Notiz |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for t in active:
        entry_s = f"{t['entry']:.2f}€" if t["entry"] else "—"
        stop_s  = f"{t['stop']:.2f}€"  if t["stop"]  else "—"
        t1_s    = f"{t['target1']:.2f}€" if t["target1"] else "—"
        t2_s    = f"{t['target2']:.2f}€" if t["target2"] else "—"
        lines.append(
            f"| {t['id']} | {t['date']} | {t['ticker']} | {t['direction']} "
            f"| {entry_s} | {stop_s} | {t1_s} | {t2_s} "
            f"| {t['strategy']} | {t['status']} | {t['conviction']} | {t.get('note', '')} |"
        )

    lines += [
        "",
        "## Abgeschlossene Paper Trades",
        "",
        "| # | Datum | Aktie | Entry | Exit | P&L | ✅/❌ | Strategie | Dauer | Notiz |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for t in closed:
        entry_s = f"{t['entry']:.2f}€" if t["entry"] else "—"
        exit_s  = f"{t['exit']:.2f}€"  if t["exit"]  else "—"
        pnl_s   = f"{t['pnl']:+.1f}%" if t["pnl"] is not None else "—"
        lines.append(
            f"| {t['id']} | {t['date']} | {t['ticker']} "
            f"| {entry_s} | {exit_s} | {pnl_s} | {t['result']} "
            f"| {t['strategy']} | {t.get('duration', '—')} | {t.get('note', '')} |"
        )

    lines += ["", "## Paper-Trade Statistik", ""]
    stats = _compute_stats(closed)
    total  = stats["total"]
    wins   = stats["wins"]
    losses = stats["losses"]
    wp     = stats["win_pct"]
    lines.append(f"- Gesamt: {total} | ✅ {wins} ({wp:.0f}%) | ❌ {losses} ({100-wp:.0f}%)")
    avg_w = f"{stats['avg_win']:+.1f}%" if stats["avg_win"] is not None else "—"
    avg_l = f"{stats['avg_loss']:+.1f}%" if stats["avg_loss"] is not None else "—"
    crv   = f"{stats['crv']:.2f}" if stats["crv"] is not None else "—"
    lines.append(f"- Avg Win: {avg_w} | Avg Loss: {avg_l} | CRV: {crv}")
    lines.append("")

    return "\n".join(lines)


def _compute_stats(closed: list[dict]) -> dict:
    total  = len(closed)
    wins   = [t for t in closed if "✅" in t.get("result", "")]
    losses = [t for t in closed if "❌" in t.get("result", "")]
    win_pcts  = [t["pnl"] for t in wins   if t["pnl"] is not None]
    loss_pcts = [t["pnl"] for t in losses if t["pnl"] is not None]

    avg_win  = sum(win_pcts)  / len(win_pcts)  if win_pcts  else None
    avg_loss = sum(loss_pcts) / len(loss_pcts) if loss_pcts else None
    crv = None
    if avg_win is not None and avg_loss is not None and avg_loss != 0:
        crv = avg_win / abs(avg_loss)

    return {
        "total":    total,
        "wins":     len(wins),
        "losses":   len(losses),
        "win_pct":  (len(wins) / total * 100) if total > 0 else 0.0,
        "avg_win":  avg_win,
        "avg_loss": avg_loss,
        "crv":      crv,
    }


def _push_alert(alert: dict) -> None:
    """Fügt Alert in alert-queue.json ein."""
    try:
        with open(ALERT_QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        queue = []
    alert["timestamp"] = datetime.now().isoformat()
    queue.append(alert)
    with open(ALERT_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────
# PRICE FETCHING
# ─────────────────────────────────────────────────────────────────

def _fetch_yahoo_price(ticker: str) -> Optional[float]:
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range=5d"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        print(f"  [WARN] Yahoo price fetch failed für {ticker}: {e}")
        return None


def _fetch_onvista_price(isin: str, name: str) -> Optional[float]:
    url = f"https://www.onvista.de/aktien/{name}-Aktie-{isin}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(r'"last":\s*([0-9]+\.?[0-9]*)', html)
        return float(m.group(1)) if m else None
    except Exception as e:
        print(f"  [WARN] Onvista fetch failed für {isin}: {e}")
        return None


# Ticker → (source, identifier)
TICKER_MAP = {
    "DR0.DE":  ("onvista", "DE000A0XYG76", "Drägerwerk"),
    "EQNR.OL": ("yahoo",   "EQNR.OL"),
    "RIO.L":   ("yahoo",   "RIO.L"),
    "PLTR":    ("yahoo",   "PLTR"),
    "RHM.DE":  ("yahoo",   "RHM.DE"),
    "BAYN.DE": ("yahoo",   "BAYN.DE"),
}


def get_price(ticker: str) -> Optional[float]:
    if ticker in TICKER_MAP:
        info = TICKER_MAP[ticker]
        if info[0] == "onvista":
            price = _fetch_onvista_price(info[1], info[2])
            if price:
                return price
        # Fallback zu Yahoo
        return _fetch_yahoo_price(ticker)
    return _fetch_yahoo_price(ticker)


# ─────────────────────────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────────────────────────

def open_paper_trade(
    ticker: str,
    direction: str,
    entry: float,
    stop: float,
    target1: float,
    target2: float,
    strategy: str,
    conviction: int,
    note: str = "",
) -> str:
    """
    Öffnet neuen Paper Trade und schreibt in paper-trades.md.
    Returns: Trade-ID
    """
    content = _read_file(PAPER_TRADES_FILE)
    if not content:
        content = _rebuild_file([], [])

    trade_id = _next_trade_id(content)
    active = _parse_active_trades(content)
    closed = _parse_closed_trades(content)

    new_trade = {
        "id":         trade_id,
        "date":       _today(),
        "ticker":     ticker,
        "direction":  direction.upper(),
        "entry":      entry,
        "stop":       stop,
        "target1":    target1,
        "target2":    target2,
        "strategy":   strategy,
        "status":     "⏳ Offen",
        "conviction": f"{conviction}/100",
        "note":       note,
    }
    active.append(new_trade)

    new_content = _rebuild_file(active, closed)
    _write_file(PAPER_TRADES_FILE, new_content)

    print(f"  ✅ Paper Trade {trade_id} geöffnet: {ticker} {direction} @ {entry:.2f}€")
    return trade_id


def check_paper_trades(prices: dict) -> list[dict]:
    """
    Prüft offene Paper Trades gegen aktuelle Kurse.
    prices: {ticker: current_price}
    Returns: Liste von ausgelösten Alerts.
    """
    content = _read_file(PAPER_TRADES_FILE)
    if not content:
        return []

    active = _parse_active_trades(content)
    closed = _parse_closed_trades(content)
    alerts = []
    still_active = []

    for trade in active:
        ticker = trade["ticker"]
        price  = prices.get(ticker)

        if price is None:
            still_active.append(trade)
            continue

        direction = trade["direction"].upper()
        entry   = trade["entry"]
        stop    = trade["stop"]
        t1      = trade["target1"]
        t2      = trade["target2"]

        pnl_pct = ((price - entry) / entry * 100) if entry else 0
        if direction == "SHORT":
            pnl_pct = -pnl_pct

        # Stop gerissen?
        stop_hit = (direction == "LONG"  and stop  and price <= stop) or \
                   (direction == "SHORT" and stop  and price >= stop)

        # Ziel 2 erreicht?
        t2_hit = t2 and (
            (direction == "LONG"  and price >= t2) or
            (direction == "SHORT" and price <= t2)
        )

        # Ziel 1 erreicht?
        t1_hit = t1 and (
            (direction == "LONG"  and price >= t1) or
            (direction == "SHORT" and price <= t1)
        )

        if stop_hit:
            # Trade schließen als ❌
            alert_msg = f"[PAPER] 🛑 {ticker} Stop gerissen: {price:.2f}€ ({pnl_pct:+.1f}%) — {trade['id']}"
            alerts.append({
                "type":    "paper_alert",
                "ticker":  ticker,
                "message": alert_msg,
            })
            _push_alert(alerts[-1])
            closed.append({
                "id":       trade["id"],
                "date":     trade["date"],
                "ticker":   ticker,
                "entry":    entry,
                "exit":     price,
                "pnl":      pnl_pct,
                "result":   "❌",
                "strategy": trade["strategy"],
                "duration": f"geschlossen {_today()}",
                "note":     f"Stop @ {stop:.2f}€",
            })
            print(f"  ❌ {trade['id']} Stop: {ticker} @ {price:.2f}€")

        elif t2_hit and "Ziel 2" not in trade.get("status", ""):
            alert_msg = f"[PAPER] 🎯🎯 {ticker} Ziel 2 erreicht: {price:.2f}€ ({pnl_pct:+.1f}%) — {trade['id']}"
            alerts.append({
                "type":    "paper_alert",
                "ticker":  ticker,
                "message": alert_msg,
            })
            _push_alert(alerts[-1])
            closed.append({
                "id":       trade["id"],
                "date":     trade["date"],
                "ticker":   ticker,
                "entry":    entry,
                "exit":     price,
                "pnl":      pnl_pct,
                "result":   "✅",
                "strategy": trade["strategy"],
                "duration": f"geschlossen {_today()}",
                "note":     f"Ziel 2 @ {t2:.2f}€",
            })
            print(f"  ✅✅ {trade['id']} Ziel 2: {ticker} @ {price:.2f}€")

        elif t1_hit and "Ziel 1" not in trade.get("status", ""):
            # Ziel 1: Status updaten, 50% als geschlossen markieren
            alert_msg = f"[PAPER] 🎯 {ticker} Ziel 1 erreicht: {price:.2f}€ ({pnl_pct:+.1f}%) — {trade['id']}"
            alerts.append({
                "type":    "paper_alert",
                "ticker":  ticker,
                "message": alert_msg,
            })
            _push_alert(alerts[-1])
            trade["status"] = "🎯 Ziel 1 erreicht"
            still_active.append(trade)
            print(f"  🎯 {trade['id']} Ziel 1: {ticker} @ {price:.2f}€")

        else:
            still_active.append(trade)

    new_content = _rebuild_file(still_active, closed)
    _write_file(PAPER_TRADES_FILE, new_content)

    return alerts


def close_paper_trade(trade_id: str, exit_price: float, reason: str = "") -> bool:
    """Manuell schließen."""
    content = _read_file(PAPER_TRADES_FILE)
    if not content:
        print(f"  [WARN] {PAPER_TRADES_FILE} nicht gefunden.")
        return False

    active = _parse_active_trades(content)
    closed = _parse_closed_trades(content)

    trade = next((t for t in active if t["id"] == trade_id), None)
    if not trade:
        print(f"  [WARN] Trade {trade_id} nicht in aktiven Trades gefunden.")
        return False

    entry   = trade["entry"]
    pnl_pct = ((exit_price - entry) / entry * 100) if entry else 0
    if trade["direction"].upper() == "SHORT":
        pnl_pct = -pnl_pct

    result = "✅" if pnl_pct >= 0 else "❌"

    closed.append({
        "id":       trade_id,
        "date":     trade["date"],
        "ticker":   trade["ticker"],
        "entry":    entry,
        "exit":     exit_price,
        "pnl":      pnl_pct,
        "result":   result,
        "strategy": trade["strategy"],
        "duration": f"geschlossen {_today()}",
        "note":     reason,
    })

    still_active = [t for t in active if t["id"] != trade_id]
    new_content = _rebuild_file(still_active, closed)
    _write_file(PAPER_TRADES_FILE, new_content)
    print(f"  ✅ Trade {trade_id} geschlossen @ {exit_price:.2f}€ ({pnl_pct:+.1f}%) — {reason}")
    return True


def get_paper_statistics() -> dict:
    """Berechnet Statistik nur für Paper Trades."""
    content = _read_file(PAPER_TRADES_FILE)
    closed = _parse_closed_trades(content)
    stats = _compute_stats(closed)

    # Durchschnittliche Haltedauer (aus "duration"-Feld — grob)
    stats["avg_duration"] = None  # Exakt nur wenn Datum gespeichert

    # Per-Strategy
    strategy_map: dict[str, list[dict]] = {}
    for t in closed:
        s = t.get("strategy", "?")
        strategy_map.setdefault(s, []).append(t)

    per_strategy = {}
    for s, trades in strategy_map.items():
        per_strategy[s] = _compute_stats(trades)
    stats["per_strategy"] = per_strategy

    return stats


def get_combined_statistics() -> dict:
    """
    Kombiniert echte Trades (aus albert-accuracy.md) mit Paper Trades.
    Gibt combined win rate + per-strategy stats zurück.
    """
    # Paper Trades
    paper_content = _read_file(PAPER_TRADES_FILE)
    paper_closed  = _parse_closed_trades(paper_content)
    paper_stats   = _compute_stats(paper_closed)

    # Echte Trades aus albert-accuracy.md parsen
    accuracy_content = _read_file(ACCURACY_FILE)
    real_wins  = len(re.findall(r"✅", accuracy_content))
    real_loses = len(re.findall(r"❌", accuracy_content))
    real_total = real_wins + real_loses
    real_wp    = (real_wins / real_total * 100) if real_total > 0 else 0.0

    combined_total = real_total + paper_stats["total"]
    combined_wins  = real_wins  + paper_stats["wins"]
    combined_wp    = (combined_wins / combined_total * 100) if combined_total > 0 else 0.0

    return {
        "real":  {"total": real_total, "wins": real_wins, "win_pct": real_wp},
        "paper": paper_stats,
        "combined": {
            "total":   combined_total,
            "wins":    combined_wins,
            "win_pct": combined_wp,
        },
    }


# ─────────────────────────────────────────────────────────────────
# MAIN — Initialisierung
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    print("📝 Initialisiere Paper Trading System...")

    if os.path.exists(PAPER_TRADES_FILE):
        print(f"  ℹ️  {PAPER_TRADES_FILE} existiert bereits — wird nicht überschrieben.")
    else:
        initial = _rebuild_file([], [])
        _write_file(PAPER_TRADES_FILE, initial)
        print(f"  ✅ {PAPER_TRADES_FILE} erstellt (leer, bereit für Montag).")

    # Statistik anzeigen
    stats = get_paper_statistics()
    print(f"\n  Paper-Trade Statistik:")
    print(f"  Gesamt: {stats['total']} | ✅ {stats['wins']} | ❌ {stats['losses']}")

    combined = get_combined_statistics()
    print(f"\n  Kombinierte Statistik:")
    print(f"  Echte Trades: {combined['real']['total']} (Win: {combined['real']['win_pct']:.0f}%)")
    print(f"  Paper Trades: {combined['paper']['total']} (Win: {combined['paper']['win_pct']:.0f}%)")
    print(f"  Gesamt:       {combined['combined']['total']} (Win: {combined['combined']['win_pct']:.0f}%)")

    print(f"\n✅ Paper Trading System bereit.")
