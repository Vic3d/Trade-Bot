#!/usr/bin/env python3
"""
Options Flow Bridge — Phase 1
================================
Verbindet options_flow_scanner.py mit dem Paper-Trading-System.
Bei jedem Scanner-Alarm → automatisch Paper Trade auf EQNR.OL eröffnen
                        → Signal in lag_knowledge.json registrieren
                        → Signal in signals.json eintragen

Wird vom Cron-Wrapper nach dem Scanner aufgerufen.
Kann auch standalone laufen: python3 options_flow_bridge.py
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Workspace-Pfade
WORKSPACE    = Path('/data/.openclaw/workspace')
LAG_DB_PATH  = WORKSPACE / 'data/lag_knowledge.json'
SIGNALS_PATH = WORKSPACE / 'data/signals.json'
STATE_PATH   = WORKSPACE / 'data/options_flow_state.json'
BRIDGE_STATE = WORKSPACE / 'data/options_flow_bridge_state.json'

# Mapping: Options-Ticker → Pair-ID + Lag-Ticker
OIL_PROXY = {
    # Kurzläufer (<7 Tage) → SHORT-Pair
    "USO": {"pair_id": "OPTIONS_FLOW_OIL_SHORT", "lag_ticker": "EQNR.OL"},
    "XOM": {"pair_id": "OPTIONS_FLOW_OIL_SHORT", "lag_ticker": "EQNR.OL"},
    "OXY": {"pair_id": "OPTIONS_FLOW_OIL_SHORT", "lag_ticker": "EQNR.OL"},
    # Mittelfristig (7-30 Tage) → MEDIUM-Pair (überschrieben in get_pair_id)
    "XLE": {"pair_id": "OPTIONS_FLOW_OIL_MEDIUM", "lag_ticker": "EQNR.OL"},
    "BNO": {"pair_id": "OPTIONS_FLOW_OIL_MEDIUM", "lag_ticker": "EQNR.OL"},
    "CVX": {"pair_id": "OPTIONS_FLOW_OIL_SHORT",  "lag_ticker": "EQNR.OL"},
}

PUT_TICKERS = {"USO", "XOM", "OXY", "XLE", "BNO", "CVX"}  # Put-Flow → inverse pair


# ── Daten laden / speichern ───────────────────────────────────────────────────

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

def load_bridge_state():
    if BRIDGE_STATE.exists():
        with open(BRIDGE_STATE) as f:
            return json.load(f)
    return {"processed_keys": {}}

def save_bridge_state(state):
    with open(BRIDGE_STATE, 'w') as f:
        json.dump(state, f, indent=2)

def load_scanner_state():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"alerted": {}}


# ── Yahoo Finance ─────────────────────────────────────────────────────────────

def get_eqnr_eur():
    """Aktuellen EQNR.OL Kurs in EUR holen."""
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # EQNR.OL in NOK
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/EQNR.OL?interval=1d&range=2d"
        req = urllib.request.Request(url, headers=headers)
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        nok_price = d['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        print(f"  ⚠️ EQNR.OL Kurs Fehler: {e}")
        return None

    # EURNOK
    try:
        url2 = "https://query2.finance.yahoo.com/v8/finance/chart/EURNOK=X?interval=1d&range=2d"
        req2 = urllib.request.Request(url2, headers=headers)
        d2 = json.loads(urllib.request.urlopen(req2, timeout=8).read())
        eurnok = d2['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        print(f"  ⚠️ EURNOK Fehler: {e}")
        return None

    return round(nok_price / eurnok, 4)


# ── Paper Trade erstellen (direkt in paper-trades.md) ────────────────────────

def create_paper_trade(ticker, direction, entry, stop, target1, target2, strategy, note):
    """Ruft paper_trading.open_paper_trade auf."""
    sys.path.insert(0, str(WORKSPACE / 'scripts'))
    try:
        import paper_trading as pt
        trade_id = pt.open_paper_trade(
            ticker=ticker,
            direction=direction,
            entry=entry,
            stop=stop,
            target1=target1,
            target2=target2,
            strategy=strategy,
            conviction=60,
            note=note
        )
        return trade_id
    except Exception as e:
        print(f"  ⚠️ Paper Trade Fehler: {e}")
        return None


# ── Signal Quality Filter ─────────────────────────────────────────────────────

def signal_quality_ok(pair_id: str, lk: dict) -> tuple[bool, str]:
    """
    Gibt zurück ob ein Signal gut genug für einen Paper Trade ist.
    In der Lernphase (<10 Samples): immer True.
    Danach: nur wenn Accuracy >= 55%.
    """
    pair = lk.get("pairs", {}).get(pair_id)
    if not pair:
        return True, "NEU"

    samples  = pair.get("sample_count", 0)
    accuracy = pair.get("accuracy_pct") or 0
    min_s    = lk.get("min_samples_to_trust", 20)
    min_acc  = lk.get("min_accuracy_to_trade", 60.0)

    if samples < 10:
        return True, f"LERNEND ({samples}/10 Samples)"
    if accuracy >= 55:
        label = "STARK" if accuracy >= min_acc and samples >= min_s else f"BEWÄHRT ({accuracy:.0f}%)"
        return True, label
    return False, f"GESPERRT ({accuracy:.0f}% < 55%)"


# ── Kerlogik: Flow → Paper Trade ─────────────────────────────────────────────

def process_hit(hit: dict, lk: dict, signals: dict, bridge_state: dict, eqnr_eur: float) -> bool:
    """
    Verarbeitet einen einzelnen Flow-Treffer.
    Returns True wenn Paper Trade erstellt wurde.
    """
    ticker    = hit["ticker"]
    strike    = hit["strike"]
    expiry    = hit["expiry"]
    days      = hit["days"]
    volume    = hit["volume"]
    oi        = hit["oi"]
    is_fresh  = hit.get("fresh", False)
    is_put    = hit.get("side", "CALL") == "PUT"

    # Pair-ID bestimmen
    if is_put:
        pair_id = "OPTIONS_FLOW_PUT_OIL"
    elif days <= 7:
        pair_id = OIL_PROXY.get(ticker, {}).get("pair_id", "OPTIONS_FLOW_OIL_SHORT")
    else:
        pair_id = OIL_PROXY.get(ticker, {}).get("pair_id", "OPTIONS_FLOW_OIL_MEDIUM")

    # Dedup: diesen Flow bereits heute verarbeitet?
    bridge_key = f"{ticker}_{strike}_{expiry}_{pair_id}"
    if bridge_key in bridge_state.get("processed_keys", {}):
        old_vol = bridge_state["processed_keys"][bridge_key]
        if volume <= old_vol * 1.5:  # weniger als 50% mehr → überspringen
            return False

    # Signal-Qualität prüfen
    quality_ok, quality_label = signal_quality_ok(pair_id, lk)
    if not quality_ok:
        print(f"  ⏭️  {ticker} {strike}$ — Signal {quality_label} (kein Trade)")
        return False

    # EQNR.OL Kurs
    if not eqnr_eur:
        print("  ⚠️ Kein EQNR.OL Kurs — überspringe")
        return False

    # Trade-Parameter berechnen
    direction = "SHORT" if is_put else "LONG"
    if direction == "LONG":
        stop    = round(eqnr_eur * 0.95, 2)   # 5% Stop
        target1 = round(eqnr_eur * 1.08, 2)   # 8% Ziel → CRV 1.6
        target2 = round(eqnr_eur * 1.15, 2)   # 15% Extended
    else:
        stop    = round(eqnr_eur * 1.05, 2)
        target1 = round(eqnr_eur * 0.92, 2)
        target2 = round(eqnr_eur * 0.85, 2)

    lag_h = lk["pairs"][pair_id]["lag_hours"]
    side_label = "PUT-Flow" if is_put else "CALL-Flow"
    note = (
        f"OptionsFlow | {side_label} {ticker} Strike${strike} {expiry} ({days}d) | "
        f"Vol:{volume:,} OI:{oi} {'FRISCH' if is_fresh else 'HOCH'} | "
        f"Pair:{pair_id} | Horizont:{lag_h}h | Qualität:{quality_label}"
    )

    trade_id = create_paper_trade(
        ticker="EQNR.OL",
        direction=direction,
        entry=eqnr_eur,
        stop=stop,
        target1=target1,
        target2=target2,
        strategy="S1 Öl",
        note=note
    )

    if not trade_id:
        return False

    print(f"  ✅ Paper Trade {trade_id}: {direction} EQNR.OL @ {eqnr_eur}€ | Stop {stop}€ | Ziel {target1}€ | [{quality_label}]")

    # Signal in lag_knowledge registrieren (Sample-Zähler erhöhen)
    pair = lk["pairs"][pair_id]
    pair["sample_count"] = pair.get("sample_count", 0) + 1
    # accuracy_pct bleibt None bis Validator läuft

    # Signal in signals.json eintragen
    sig_entry = {
        "pair_id":           pair_id,
        "lead_ticker":       ticker,
        "lead_name":         f"Options Flow {ticker}",
        "lag_ticker":        "EQNR.OL",
        "lag_name":          "Equinor ASA",
        "signal_value":      f"Vol:{volume:,}/OI:{oi}",
        "signal_pct":        round(volume / max(oi, 1), 1),
        "lead_price":        float(strike),
        "lag_price_at_signal": eqnr_eur,
        "lag_hours":         lag_h,
        "direction":         lk["pairs"][pair_id]["direction"],
        "outcome":           "PENDING",
        "paper_trade_id":    trade_id,
        "issue_id":          None,
        "issue_key":         None,
        "confidence":        f"{pair['sample_count']}/{lk.get('min_samples_to_trust', 20)} samples",
        "quality_label":     quality_label,
        "options_ticker":    ticker,
        "options_strike":    strike,
        "options_expiry":    expiry,
        "options_days":      days,
        "options_fresh":     is_fresh,
        "created_at":        datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }
    signals["signals"].append(sig_entry)

    # Bridge-State updaten
    bridge_state.setdefault("processed_keys", {})[bridge_key] = volume

    return True


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main():
    print(f"[Options Flow Bridge] {datetime.now().strftime('%Y-%m-%d %H:%M')} CET")

    # Scanner-State lesen (enthält die letzten Treffer)
    scanner_state = load_scanner_state()
    alerted = scanner_state.get("alerted", {})

    if not alerted:
        print("Keine aktuellen Scanner-Treffer in options_flow_state.json.")
        return

    print(f"  {len(alerted)} aktive Treffer im Scanner-State gefunden.")

    # EQNR.OL Kurs einmal holen
    print("  Hole EQNR.OL Kurs...")
    eqnr_eur = get_eqnr_eur()
    if eqnr_eur:
        print(f"  EQNR.OL = {eqnr_eur} EUR")
    else:
        print("  ⚠️ Kein Kurs — abbruch")
        return

    lk           = load_lag_knowledge()
    signals      = load_signals()
    bridge_state = load_bridge_state()

    # Jeden Treffer aus dem Scanner-State als Hit-Objekt rekonstruieren
    created = 0
    for key, volume in alerted.items():
        # Key-Format: TICKER_SIDE_STRIKE_EXPIRY
        parts = key.split("_")
        if len(parts) < 4:
            continue
        ticker = parts[0]
        side   = parts[1]
        strike = float(parts[2])
        expiry = "_".join(parts[3:])

        if ticker not in OIL_PROXY:
            continue

        from datetime import datetime as dt
        try:
            exp_dt = dt.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days   = max(0, (exp_dt - datetime.now(timezone.utc)).days)
        except Exception:
            days = 999

        hit = {
            "ticker":  ticker,
            "strike":  strike,
            "expiry":  expiry,
            "days":    days,
            "volume":  volume,
            "oi":      0,
            "fresh":   True,
            "side":    side,
        }

        if process_hit(hit, lk, signals, bridge_state, eqnr_eur):
            created += 1

    # Speichern
    save_lag_knowledge(lk)
    save_signals(signals)
    save_bridge_state(bridge_state)

    print(f"\n✅ Bridge abgeschlossen: {created} Paper Trade(s) erstellt")


if __name__ == "__main__":
    main()
