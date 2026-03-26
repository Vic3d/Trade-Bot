#!/usr/bin/env python3
"""
Paper Trade Checker — wird vom Trading Monitor alle 15 Min aufgerufen.
Prüft alle offenen Paper Trades gegen aktuelle Kurse.
Standalone nutzbar: python3 paper_trade_checker.py
"""

import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

WORKSPACE = "/data/.openclaw/workspace"

# Import aus paper_trading.py (gleicher Ordner)
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paper_trading import (
    _read_file,
    _write_file,
    _parse_active_trades,
    get_price,
    check_paper_trades,
    PAPER_TRADES_FILE,
    ALERT_QUEUE_FILE,
)


def check_all_paper_trades() -> list[dict]:
    """
    Wird vom Trading Monitor alle 15 Min aufgerufen.
    1. Liest paper-trades.md
    2. Holt aktuelle Kurse (Yahoo/Onvista)
    3. Prüft Stops + Ziele
    4. Aktualisiert paper-trades.md
    5. Gibt Alerts zurück (für alert-queue.json)
    """
    content = _read_file(PAPER_TRADES_FILE)
    if not content:
        print("  [INFO] Keine paper-trades.md gefunden — nichts zu prüfen.")
        return []

    active = _parse_active_trades(content)
    if not active:
        print("  [INFO] Keine offenen Paper Trades.")
        return []

    print(f"  📋 {len(active)} offene Paper Trades gefunden.")

    # Unique tickers holen
    tickers = list({t["ticker"] for t in active})
    prices: dict[str, Optional[float]] = {}

    for ticker in tickers:
        price = get_price(ticker)
        prices[ticker] = price
        status = f"{price:.2f}€" if price else "N/A"
        print(f"    {ticker}: {status}")

    # Paper Trades prüfen
    alerts = check_paper_trades(prices)

    if alerts:
        print(f"\n  🚨 {len(alerts)} Alert(s) ausgelöst:")
        for a in alerts:
            print(f"    → {a['message']}")
    else:
        print("  ✅ Keine Stops/Ziele ausgelöst.")

    return alerts


def run_check_and_report() -> dict:
    """
    Führt Check durch und gibt strukturierten Report zurück.
    Nützlich für Integration in Trading Monitor.
    """
    ts = datetime.now().isoformat()
    print(f"\n[{ts}] Paper Trade Check...")

    try:
        alerts = check_all_paper_trades()
        return {
            "timestamp": ts,
            "alerts":    alerts,
            "status":    "ok",
        }
    except Exception as e:
        print(f"  [ERROR] Paper Trade Check fehlgeschlagen: {e}")
        return {
            "timestamp": ts,
            "alerts":    [],
            "status":    "error",
            "error":     str(e),
        }


if __name__ == "__main__":
    result = run_check_and_report()
    print(f"\n✅ Paper Trade Check abgeschlossen: {len(result['alerts'])} Alert(s)")
    if result["alerts"]:
        print("\nAlerts:")
        for a in result["alerts"]:
            print(f"  {a['message']}")
