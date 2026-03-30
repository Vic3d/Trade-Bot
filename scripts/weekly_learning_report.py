#!/usr/bin/env python3
"""
Schicht 4 — Weekly Learning Report
Wird per Cron-Job sonntags um 20:00 ausgeführt.
Cron-Agent schickt das Ergebnis als Discord-Nachricht an Victor.
"""
import os, sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'trading.db')

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from post_trade_analyzer import generate_summary, analyze_new_closed_trades

    # Zuerst neue Trades analysieren
    try:
        analyze_new_closed_trades(DB_PATH)
    except Exception as e:
        print(f"[WARNUNG] analyze_new_closed_trades: {e}")

    # Bericht generieren
    report = generate_summary(DB_PATH, days=7)
    print(report)
    return report


if __name__ == '__main__':
    main()
