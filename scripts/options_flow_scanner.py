#!/usr/bin/env python3
"""
Options Flow Scanner — Albert / TradeMind
==========================================
Erkennt ungewöhnlichen Call-Flow bei Öl/Energy-Tickern.
Alarm wenn: Vol/OI > Schwelle + OTM Call + Laufzeit < 30 Tage
Frische Positionen (OI=0, hohes Vol) werden extra gewertet.

Cron: alle 30 Min, 14:00-21:30 CET, Mo-Fr
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf

WORKSPACE    = Path('/data/.openclaw/workspace')
LAG_DB_PATH  = WORKSPACE / 'data/lag_knowledge.json'

# ── Signal Quality Filter ─────────────────────────────────────────────────────

def signal_quality_ok(pair_id: str) -> tuple[bool, str]:
    """Nur verlässliche Signale alertieren. Lernphase (<10 Samples): immer True."""
    try:
        with open(LAG_DB_PATH) as f:
            lk = json.load(f)
        pair = lk.get("pairs", {}).get(pair_id)
        if not pair:
            return True, "NEU"
        samples  = pair.get("sample_count", 0)
        accuracy = pair.get("accuracy_pct") or 0
        if samples < 10:
            return True, f"LERNEND ({samples}/10)"
        if accuracy >= 55:
            return True, f"BEWÄHRT ({accuracy:.0f}%)"
        return False, f"GESPERRT ({accuracy:.0f}%)"
    except Exception:
        return True, "UNBEKANNT"

# ── Konfiguration ─────────────────────────────────────────────────────────────

TICKERS = {
    "USO":  "US Oil Fund ETF",
    "XOM":  "ExxonMobil",
    "OXY":  "Occidental Petroleum",
    "XLE":  "Energy Select ETF",
    "CVX":  "Chevron",
    "BNO":  "Brent Oil ETF",
}

# Schwellenwerte
MIN_VOLUME       = 500     # Mindest-Volumen damit wir es beachten
RATIO_THRESHOLD  = 3.0     # Vol/OI > 3x = auffällig
FRESH_VOL_MIN    = 1000    # Bei OI=0: ab diesem Vol als "frisch" werten
MAX_DAYS_TO_EXP  = 30      # Nur Kontrakte die in <30 Tagen ablaufen
TOP_N            = 3       # Max. Alerts pro Ticker

DISCORD_TARGET   = "452053147620343808"  # Victor
STATE_FILE       = "/data/.openclaw/workspace/data/options_flow_state.json"

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"alerted": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def alert_key(ticker, strike, expiry, side):
    return f"{ticker}_{side}_{strike}_{expiry}"

def send_discord(message: str):
    """Sendet via OpenClaw message-Tool (subprocess-Trick)."""
    payload = {
        "action": "send",
        "channel": "discord",
        "target": DISCORD_TARGET,
        "message": message
    }
    # Schreibt JSON nach stdout für OpenClaw-Integration
    print(f"DISCORD_ALERT:{json.dumps(payload)}")

def format_ratio(vol, oi):
    if oi == 0:
        return f"NEU ({vol:,} Vol, OI=0)"
    return f"{vol/oi:.1f}x (Vol {vol:,} / OI {oi:,})"

# ── Kern-Scanner ──────────────────────────────────────────────────────────────

def scan_ticker(ticker: str, label: str, state: dict) -> list[dict]:
    """Scannt einen Ticker auf ungewöhnliche Call-Aktivität."""
    hits = []
    now = datetime.now(timezone.utc)

    try:
        tk = yf.Ticker(ticker)
        expiries = tk.options
    except Exception as e:
        print(f"  [{ticker}] Fehler beim Laden der Expiries: {e}", file=sys.stderr)
        return []

    for expiry in expiries:
        # Nur kurzfristige Kontrakte (< 30 Tage)
        try:
            exp_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        days_to_exp = (exp_dt - now).days
        if days_to_exp > MAX_DAYS_TO_EXP or days_to_exp < 0:
            continue

        try:
            chain = tk.option_chain(expiry)
        except Exception as e:
            print(f"  [{ticker}] Fehler bei Expiry {expiry}: {e}", file=sys.stderr)
            continue

        calls = chain.calls.copy()

        for _, row in calls.iterrows():
            raw_vol = row.get("volume", 0)
            raw_oi  = row.get("openInterest", 0)
            vol  = int(raw_vol) if raw_vol == raw_vol and raw_vol else 0  # NaN check
            oi   = int(raw_oi)  if raw_oi  == raw_oi  and raw_oi  else 0
            itm  = bool(row.get("inTheMoney", False))
            strike = float(row.get("strike", 0))

            # Nur OTM Calls
            if itm:
                continue

            # Frisch (OI=0, hohes Vol) ODER Vol/OI > Schwelle
            is_fresh = (oi == 0 and vol >= FRESH_VOL_MIN)
            ratio    = vol / oi if oi > 0 else None
            is_high  = (ratio is not None and ratio >= RATIO_THRESHOLD and vol >= MIN_VOLUME)

            if not (is_fresh or is_high):
                continue

            key = alert_key(ticker, strike, expiry, "CALL")

            # Dedup: gleichen Alert nicht zweimal schicken
            already = state["alerted"].get(key, 0)
            if vol <= already * 1.2:  # weniger als 20% mehr als letztes Mal → überspringen
                continue

            hits.append({
                "ticker":  ticker,
                "label":   label,
                "strike":  strike,
                "expiry":  expiry,
                "days":    days_to_exp,
                "volume":  vol,
                "oi":      oi,
                "fresh":   is_fresh,
                "ratio":   ratio,
                "key":     key,
            })

    # Top N nach Volumen sortiert
    hits.sort(key=lambda x: x["volume"], reverse=True)
    return hits[:TOP_N]

# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main():
    print(f"[Options Flow Scanner] {datetime.now().strftime('%Y-%m-%d %H:%M')} CET")
    state = load_state()
    all_hits = []

    for ticker, label in TICKERS.items():
        print(f"  Scanne {ticker} ({label})...")
        hits = scan_ticker(ticker, label, state)
        if hits:
            print(f"    → {len(hits)} Treffer")
        all_hits.extend(hits)

    if not all_hits:
        print("Keine ungewöhnliche Aktivität.")
        # Bridge + Score auch ohne Flow laufen lassen (für regelmäßiges Score-Update)
        _run_confidence_scorer()
        return

    # State updaten
    for h in all_hits:
        state["alerted"][h["key"]] = h["volume"]
    save_state(state)

    # Confidence Score berechnen
    score_data = _run_confidence_scorer()
    score_line = ""
    if score_data:
        score_line = f"\n**Konfidenz-Score: {score_data['score']}/10 — {score_data['label']}**"

    # Bridge ausführen (Flow → Paper Trade)
    _run_bridge()

    # Alert bauen — nur Signale die Quality-Filter bestehen
    qualifying = []
    for h in all_hits:
        # Pair-ID bestimmen für Quality-Check
        pair_id = "OPTIONS_FLOW_OIL_SHORT" if h["days"] <= 7 else "OPTIONS_FLOW_OIL_MEDIUM"
        if h["ticker"] in ("XLE", "BNO"):
            pair_id = "OPTIONS_FLOW_OIL_MEDIUM"
        ok, label = signal_quality_ok(pair_id)
        h["quality_label"] = label
        h["quality_ok"] = ok
        qualifying.append(h)

    alertable = [h for h in qualifying if h["quality_ok"]]

    if not alertable:
        print(f"  Alle {len(all_hits)} Treffer in Lernphase — kein Discord-Alert (Paper Trade erstellt)")
        return

    lines = ["🚨 **Ungewöhnlicher Options-Flow** (Öl/Energy)\n"]
    for h in alertable:
        tag = "🔥 FRISCH" if h["fresh"] else "📈 HOCH"
        ratio_str = format_ratio(h["volume"], h["oi"])
        lines.append(
            f"{tag} **{h['ticker']}** ({h['label']}) [{h['quality_label']}]\n"
            f"  Call Strike ${h['strike']:.0f} | Ablauf {h['expiry']} ({h['days']}d)\n"
            f"  Vol/OI: {ratio_str}"
        )

    if score_line:
        lines.append(score_line)
    lines.append(f"\n_Scan: {datetime.now().strftime('%H:%M')} CET — Quelle: Yahoo Finance_")
    message = "\n".join(lines)

    print("\n" + message)
    send_discord(message)

def _run_bridge():
    """Bridge nach dem Scanner starten."""
    import subprocess
    try:
        subprocess.run(
            ["python3", str(WORKSPACE / "scripts/options_flow_bridge.py")],
            timeout=30, capture_output=True
        )
    except Exception as e:
        print(f"  ⚠️ Bridge-Fehler: {e}")

def _run_confidence_scorer() -> dict | None:
    """Confidence Score berechnen und zurückgeben."""
    try:
        sys.path.insert(0, str(WORKSPACE / "scripts"))
        import confidence_scorer as cs
        return cs.calculate_score()
    except Exception as e:
        print(f"  ⚠️ Confidence-Scorer Fehler: {e}")
        return None

if __name__ == "__main__":
    main()
