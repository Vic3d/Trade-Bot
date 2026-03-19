#!/usr/bin/env python3
"""
TradeMind Dashboard Server — Lokaler FastAPI Backend
=====================================================
Port 8080 | Schreibt direkt in workspace-Dateien

Starten:
  python3 scripts/dashboard_server.py

Starten via PM2:
  pm2 start scripts/dashboard_server.py --name tradevind-dashboard --interpreter python3

Autor: Albert 🎩 | v1.0 | 19.03.2026
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# ─── Pfade ───────────────────────────────────────────────────────────
WORKSPACE          = Path('/data/.openclaw/workspace')
PRICES_PATH        = WORKSPACE / 'memory' / 'latest-prices.json'
CONFIG_PATH        = WORKSPACE / 'trading_config.json'
TRADE_LOG_PATH     = WORKSPACE / 'memory' / 'trade-log.json'
SCREENER_LOG_PATH  = WORKSPACE / 'memory' / 'screener-log.json'
SCREENER_CAND_PATH = WORKSPACE / 'memory' / 'screener-candidates.json'
PREDICTIONS_PATH   = WORKSPACE / 'memory' / 'dirk-predictions.md'
PRED_RESULTS_PATH  = WORKSPACE / 'memory' / 'prediction-results.json'
TRADE_DECISIONS_PATH = WORKSPACE / 'memory' / 'trade-decisions.md'
DASHBOARD_HTML     = WORKSPACE / 'trading-dashboard' / 'dashboard.html'

# ─── App ─────────────────────────────────────────────────────────────
app = FastAPI(title="TradeMind Dashboard", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Helpers ─────────────────────────────────────────────────────────

def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Pydantic Models ─────────────────────────────────────────────────

class TradeEntry(BaseModel):
    ticker: str
    action: str          # BUY | SELL
    price_eur: float
    stop_eur: Optional[float] = None
    target_eur: Optional[float] = None
    strategy: str = ""
    notes: str = ""


class ScreenerFeedback(BaseModel):
    candidate: str
    date: str            # YYYY-MM-DD
    action: str          # TRADED | SKIPPED | WATCHING
    reason: str = ""


class PredictionResult(BaseModel):
    prediction_id: str   # Titel der Prediction (erster Satz)
    result: str          # WON | LOST
    notes: str = ""


# ─── Routes ──────────────────────────────────────────────────────────

@app.get("/")
def serve_dashboard():
    if DASHBOARD_HTML.exists():
        return FileResponse(DASHBOARD_HTML)
    raise HTTPException(status_code=404, detail="Dashboard HTML nicht gefunden")


# ── Portfolio / Preise ──

@app.get("/api/prices")
def get_prices():
    """Live-Preise aus latest-prices.json (alle 15 Min vom Monitor befüllt)."""
    data = load_json(PRICES_PATH, {})
    if not data:
        raise HTTPException(status_code=503, detail="Keine Preisdaten — Monitor läuft?")
    return data


@app.get("/api/config")
def get_config():
    """Ticker-Liste aus trading_config.json (für Dropdowns)."""
    cfg = load_json(CONFIG_PATH, {})
    return {
        "positions": {
            k: {
                "name": v.get("name", k),
                "currency": v.get("currency", "EUR"),
                "entry_eur": v.get("entry_eur"),
                "stop_eur": v.get("stop_eur"),
                "status": v.get("status", "OPEN"),
            }
            for k, v in cfg.get("positions", {}).items()
            if v.get("status") != "CLOSED"
        },
        "watchlist": {
            k: {"name": v.get("name", k)}
            for k, v in cfg.get("watchlist", {}).items()
        },
    }


# ── Trade Log ──

@app.post("/api/trade")
def log_trade(trade: TradeEntry):
    """
    Logt einen Trade in trade-log.json + schreibt in trade-decisions.md.
    Victor tippt Kauf/Verkauf hier — Albert liest und trackt alles.
    """
    entry = {
        "ts": now_str(),
        "ticker": trade.ticker.upper(),
        "action": trade.action,
        "price_eur": trade.price_eur,
        "stop_eur": trade.stop_eur,
        "target_eur": trade.target_eur,
        "strategy": trade.strategy,
        "notes": trade.notes,
    }

    # trade-log.json
    log = load_json(TRADE_LOG_PATH, [])
    log.append(entry)
    save_json(TRADE_LOG_PATH, log)

    # trade-decisions.md (append)
    now_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    action_label = "KAUF" if trade.action == "BUY" else "VERKAUF"
    stop_str = f" | Stop: {trade.stop_eur}€" if trade.stop_eur else " | ⚠️ kein Stop!"
    target_str = f" | Ziel: {trade.target_eur}€" if trade.target_eur else ""
    strat_str = f" | Strategie: {trade.strategy}" if trade.strategy else ""

    md_entry = (
        f"\n### {now_dt} — {action_label} {trade.ticker.upper()} @ {trade.price_eur:.2f}€"
        f"{stop_str}{target_str}{strat_str}\n"
    )
    if trade.notes:
        md_entry += f"*{trade.notes}*\n"

    with open(TRADE_DECISIONS_PATH, 'a', encoding='utf-8') as f:
        f.write(md_entry)

    return {"status": "ok", "entry": entry}


@app.get("/api/trades")
def get_trades():
    """Letzten 50 geloggten Trades."""
    trades = load_json(TRADE_LOG_PATH, [])
    return trades[-50:]


# ── Screener ──

@app.get("/api/screener")
def get_screener():
    """Heutige Screener-Kandidaten aus screener-candidates.json."""
    return load_json(SCREENER_CAND_PATH, [])


@app.post("/api/screener")
def log_screener_feedback(fb: ScreenerFeedback):
    """
    Logt Victors Reaktion auf einen Screener-Kandidaten.
    TRADED / SKIPPED / WATCHING
    """
    entry = {
        "ts": now_str(),
        "candidate": fb.candidate,
        "date": fb.date,
        "action": fb.action,
        "reason": fb.reason,
    }
    log = load_json(SCREENER_LOG_PATH, [])
    log.append(entry)
    save_json(SCREENER_LOG_PATH, log)
    return {"status": "ok", "entry": entry}


# ── Dirk Predictions ──

@app.get("/api/predictions")
def get_predictions():
    """Offene Dirk-Predictions aus dirk-predictions.md + prediction-results.json."""
    try:
        content = PREDICTIONS_PATH.read_text(encoding='utf-8')
    except FileNotFoundError:
        return []

    results = load_json(PRED_RESULTS_PATH, {})
    predictions = []

    # Prediction-Blöcke parsen (### Titel)
    blocks = re.split(r'\n### ', content)
    for block in blocks[1:]:
        lines = block.strip().split('\n')
        title = lines[0].strip()

        # Ergebnis aus MD
        result_match = re.search(r'\*\*Ergebnis:\*\*\s*(.+)', block)
        result_raw = result_match.group(1).strip() if result_match else "🟡 Offen"

        # Datum aus Titel (format: 07.03.2026 — ...)
        date_match = re.match(r'(\d{2}\.\d{2}\.\d{4})', title)
        date_str = date_match.group(1) if date_match else "?"

        # Ticker aus Titel
        ticker_match = re.search(r'—\s*([A-Z0-9.^]+)\s*—', title)
        ticker = ticker_match.group(1) if ticker_match else "?"

        is_open = '🟡' in result_raw or 'Offen' in result_raw
        manual_result = results.get(title)

        predictions.append({
            "id": title,
            "title": title,
            "date": date_str,
            "ticker": ticker,
            "result_raw": result_raw,
            "is_open": is_open and not manual_result,
            "manual_result": manual_result,
        })

    # Offene zuerst
    predictions.sort(key=lambda x: (not x["is_open"], x["date"]))
    return predictions


@app.post("/api/predictions")
def close_prediction(result: PredictionResult):
    """
    Markiert eine Prediction als WON oder LOST.
    Schreibt in prediction-results.json (MD-Datei bleibt unverändert).
    """
    results = load_json(PRED_RESULTS_PATH, {})
    results[result.prediction_id] = {
        "result": result.result,
        "notes": result.notes,
        "ts": now_str(),
    }
    save_json(PRED_RESULTS_PATH, results)
    return {"status": "ok", "id": result.prediction_id, "result": result.result}


# ── Screener-Kandidaten schreiben (für Morning Briefing) ──

class ScreenerCandidatesList(BaseModel):
    candidates: list


@app.post("/api/screener/candidates")
def set_screener_candidates(payload: ScreenerCandidatesList):
    candidates = payload.candidates
    """
    Das Morning Briefing / Albert schreibt hier heutige Kandidaten rein.
    Victor sieht sie im Dashboard und gibt Feedback.
    """
    save_json(SCREENER_CAND_PATH, candidates)
    return {"status": "ok", "count": len(candidates)}



# ─── Start ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🎩 TradeMind Dashboard Server startet auf http://0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False, log_level="warning")
