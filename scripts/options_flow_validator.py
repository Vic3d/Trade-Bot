#!/usr/bin/env python3
"""
Options Flow Validator — Phase 2
==================================
Prüft täglich ob options-flow-getriggerte Paper Trades ihr Ziel erreicht haben.
Läuft täglich 22:00 CET nach Xetra + NYSE Schluss.

Logik:
  1. Lade alle PENDING Signale aus signals.json mit source=options_flow
  2. Prüfe ob Horizont (lag_hours) seit created_at abgelaufen ist
  3. Hole aktuellen EQNR.OL Kurs
  4. Bewerte: +1.5% = WIN | -1.5% = LOSS | dazwischen = NEUTRAL
  5. Update lag_knowledge.json (accuracy_pct, wins, losses, sample_count)
  6. Discord Summary wenn >0 neue Ergebnisse
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE    = Path('/data/.openclaw/workspace')
LAG_DB_PATH  = WORKSPACE / 'data/lag_knowledge.json'
SIGNALS_PATH = WORKSPACE / 'data/signals.json'

WIN_THRESHOLD  =  1.5   # % für WIN
LOSS_THRESHOLD = -1.5   # % für LOSS (negativ)

DISCORD_TARGET = "452053147620343808"


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def load_lag_knowledge():
    with open(LAG_DB_PATH) as f:
        return json.load(f)

def save_lag_knowledge(data):
    with open(LAG_DB_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def load_signals():
    if SIGNALS_PATH.exists():
        with open(SIGNALS_PATH) as f:
            return json.load(f)
    return {"signals": [], "stats": {}, "updated": ""}

def save_signals(data):
    data["updated"] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(SIGNALS_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def get_eqnr_eur():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/EQNR.OL?interval=1d&range=2d"
        req = urllib.request.Request(url, headers=headers)
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        nok = d['chart']['result'][0]['meta']['regularMarketPrice']

        url2 = "https://query2.finance.yahoo.com/v8/finance/chart/EURNOK=X?interval=1d&range=2d"
        req2 = urllib.request.Request(url2, headers=headers)
        d2 = json.loads(urllib.request.urlopen(req2, timeout=8).read())
        eurnok = d2['chart']['result'][0]['meta']['regularMarketPrice']

        return round(nok / eurnok, 4)
    except Exception as e:
        print(f"  ⚠️ EQNR.OL Kursfehler: {e}")
        return None

def recalc_accuracy(pair: dict) -> float | None:
    wins   = pair.get("wins", 0)
    losses = pair.get("losses", 0)
    total  = wins + losses
    if total == 0:
        return None
    return round((wins / total) * 100, 1)

def send_discord_summary(results: list[dict]):
    """Schreibt Summary auf stdout — Cron-Wrapper liest und sendet."""
    if not results:
        return

    lines = [f"📊 **Options Flow Validator — {datetime.now().strftime('%d.%m.%Y')}**\n"]

    wins   = sum(1 for r in results if r["outcome"] == "WIN")
    losses = sum(1 for r in results if r["outcome"] == "LOSS")
    neutral = sum(1 for r in results if r["outcome"] == "NEUTRAL")

    lines.append(f"Heute bewertet: {len(results)} Signale | ✅ {wins} WIN | ❌ {losses} LOSS | ⚪ {neutral} NEUTRAL\n")

    for r in results[:10]:
        emoji = {"WIN": "✅", "LOSS": "❌", "NEUTRAL": "⚪"}.get(r["outcome"], "?")
        lines.append(
            f"{emoji} **{r['pair_id']}** | {r['lag_ticker']} | "
            f"Entry {r['entry']:.2f}€ → Jetzt {r['current_price']:.2f}€ | "
            f"{r['change_pct']:+.1f}% | Horizont {r['lag_hours']}h"
        )

    # Accuracy-Updates anzeigen
    lines.append("\n**Accuracy-Update:**")
    seen = set()
    for r in results:
        pid = r["pair_id"]
        if pid not in seen:
            seen.add(pid)
            acc = r.get("new_accuracy")
            samp = r.get("new_samples", 0)
            if acc is not None:
                lines.append(f"  {pid}: {acc:.0f}% ({samp} Samples)")
            else:
                lines.append(f"  {pid}: {samp} Samples (noch zu wenig für Accuracy)")

    print("DISCORD_SUMMARY:" + json.dumps({
        "target": DISCORD_TARGET,
        "message": "\n".join(lines)
    }))


# ── Kern-Validierung ─────────────────────────────────────────────────────────

def validate_signal(sig: dict, current_price: float, lk: dict) -> dict:
    """Bewertet ein einzelnes Signal."""
    entry      = sig.get("lag_price_at_signal", 0)
    created_at = sig.get("created_at", "")
    lag_hours  = sig.get("lag_hours", 24)
    direction  = sig.get("direction", "same")
    pair_id    = sig.get("pair_id", "")

    if not entry or entry == 0:
        return None

    change_pct = ((current_price - entry) / entry) * 100

    # Bei inverse (Put-Flow) ist die Erwartung: Preis fällt
    if direction == "inverse":
        change_pct = -change_pct

    if change_pct >= WIN_THRESHOLD:
        outcome = "WIN"
    elif change_pct <= LOSS_THRESHOLD:
        outcome = "LOSS"
    else:
        outcome = "NEUTRAL"

    # Pair in lag_knowledge updaten
    pair = lk["pairs"].get(pair_id, {})
    if outcome == "WIN":
        pair["wins"] = pair.get("wins", 0) + 1
    elif outcome == "LOSS":
        pair["losses"] = pair.get("losses", 0) + 1

    new_accuracy = recalc_accuracy(pair)
    pair["accuracy_pct"] = new_accuracy
    if pair_id in lk["pairs"]:
        lk["pairs"][pair_id] = pair

    return {
        "pair_id":       pair_id,
        "lag_ticker":    sig.get("lag_ticker", "EQNR.OL"),
        "entry":         entry,
        "current_price": current_price,
        "change_pct":    round(((current_price - sig.get("lag_price_at_signal", entry)) / entry) * 100, 2),
        "lag_hours":     lag_hours,
        "outcome":       outcome,
        "new_accuracy":  new_accuracy,
        "new_samples":   pair.get("sample_count", 0),
    }


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main():
    print(f"[Options Flow Validator] {datetime.now().strftime('%Y-%m-%d %H:%M')} CET")

    lk      = load_lag_knowledge()
    signals = load_signals()
    now_utc = datetime.now(timezone.utc)

    # PENDING signals mit options_flow source finden
    pending = [
        s for s in signals.get("signals", [])
        if s.get("outcome") == "PENDING"
        and s.get("pair_id", "").startswith("OPTIONS_FLOW")
    ]

    if not pending:
        print("Keine offenen Options-Flow-Signale zu bewerten.")
        return

    print(f"  {len(pending)} offene Signale gefunden.")

    # Fällige Signale filtern (Horizont abgelaufen)
    due = []
    for sig in pending:
        try:
            created = datetime.fromisoformat(sig["created_at"].replace('Z', '+00:00'))
            lag_h   = sig.get("lag_hours", 24)
            due_at  = created + timedelta(hours=lag_h)
            if now_utc >= due_at:
                due.append(sig)
        except Exception:
            continue

    if not due:
        print("  Kein Signal hat seinen Bewertungs-Horizont noch erreicht.")
        return

    print(f"  {len(due)} Signal(e) fällig.")

    # Aktuellen Kurs holen (einmal für alle)
    current_price = get_eqnr_eur()
    if not current_price:
        print("  ⚠️ Kein EQNR.OL Kurs — abbruch")
        return
    print(f"  EQNR.OL = {current_price} EUR")

    results = []
    for sig in due:
        result = validate_signal(sig, current_price, lk)
        if not result:
            continue

        # Signal in signals.json updaten
        for s in signals["signals"]:
            if s.get("created_at") == sig.get("created_at") and s.get("pair_id") == sig.get("pair_id"):
                s["outcome"]          = result["outcome"]
                s["actual_change_pct"] = result["change_pct"]
                s["lag_price_after"]   = current_price
                s["resolved_at"]       = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                break

        emoji = {"WIN": "✅", "LOSS": "❌", "NEUTRAL": "⚪"}[result["outcome"]]
        print(f"  {emoji} {result['pair_id']} | {result['change_pct']:+.1f}% | {result['outcome']}")
        results.append(result)

    # Speichern
    save_lag_knowledge(lk)
    save_signals(signals)

    # Stats neu berechnen
    all_sigs   = signals.get("signals", [])
    opts_sigs  = [s for s in all_sigs if s.get("pair_id", "").startswith("OPTIONS_FLOW")]
    wins       = sum(1 for s in opts_sigs if s.get("outcome") == "WIN")
    losses     = sum(1 for s in opts_sigs if s.get("outcome") == "LOSS")
    pending_ct = sum(1 for s in opts_sigs if s.get("outcome") == "PENDING")
    total      = wins + losses
    acc        = round(wins/total*100, 1) if total else None

    print(f"\n📊 Gesamt Options-Flow: {wins} WIN / {losses} LOSS / {pending_ct} PENDING", end="")
    print(f" | Accuracy: {acc}%" if acc else " | Accuracy: n/a (zu wenig Daten)")

    if results:
        send_discord_summary(results)

    print("✅ Validator abgeschlossen")


if __name__ == "__main__":
    main()
