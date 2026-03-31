#!/usr/bin/env python3
"""
portfolio_summary.py — Zentraler Ticker-Discovery für alle Cron-Jobs

Löst das "Hardcoded Tickers"-Problem:
Statt: paper_tickers = ['OXY','FRO','DHT','KTOS',...]  # VERALTET!
Jetzt: python3 scripts/portfolio_summary.py --paper-tickers
       → gibt nur aktive Tickers zurück

USAGE:
  python3 portfolio_summary.py                  # Voller Report
  python3 portfolio_summary.py --real-tickers   # Nur echte aktive Tickers (comma-sep)
  python3 portfolio_summary.py --paper-tickers  # Nur Paper aktive Tickers
  python3 portfolio_summary.py --all-tickers    # Alle aktiven Tickers
  python3 portfolio_summary.py --yahoo          # Yahoo-Ticker (für Kursabfragen)
  python3 portfolio_summary.py --json           # Alles als JSON
  python3 portfolio_summary.py --cron-context   # Kompakte Zusammenfassung für Cron-Prompts

In Python:
  from portfolio import Portfolio
  p = Portfolio()
  p.is_active('RHM.DE')  # → False
  p.all_active_tickers()  # → ['NVDA', 'MSFT', 'OXY', ...]
"""

import sys, json, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from portfolio import Portfolio

# Yahoo-Ticker Mapping (für Kursabfragen)
YAHOO_MAP = {
    # Echtes Portfolio
    'NVDA': 'NVDA', 'MSFT': 'MSFT', 'PLTR': 'PLTR',
    'EQNR': 'EQNR.OL', 'RIO.L': 'RIO.L', 'BAYN.DE': 'BAYN.DE',
    'A14WU5': None,  # ETCs oft nicht auf Yahoo
    'A2DWAW': None,
    'A2QQ9R': None,
    'A3D42Y': None,
    # Paper Portfolio
    'OXY': 'OXY', 'FRO': 'FRO', 'DHT': 'DHT',
    'KTOS': 'KTOS', 'HII': 'HII', 'HL': 'HL',
    'PAAS': 'PAAS', 'MOS': 'MOS',
    'HAG.DE': 'HAG.DE', 'TTE.PA': 'TTE.PA',
}


def get_yahoo_tickers(tickers):
    """Konvertiert Ticker zu Yahoo Finance Tickers."""
    result = []
    for t in tickers:
        yahoo = YAHOO_MAP.get(t, t)
        if yahoo:
            result.append(yahoo)
    return result


def cron_context(p):
    """Kompakte Zusammenfassung die Cron-Prompts direkt einbetten können."""
    real = p.real_positions()
    paper = p.paper_positions()

    lines = ["=== AKTIVE POSITIONEN (automatisch generiert) ===\n"]

    if real:
        lines.append("ECHTES PORTFOLIO:")
        for pos in real:
            stop_str = f"Stop {pos.stop_eur}€" if pos.stop_eur else "⚠️ KEIN STOP"
            lines.append(f"  - {pos.name} ({pos.ticker}): Entry {pos.entry_eur}€ | {stop_str}")

    if paper:
        lines.append("\nPAPER PORTFOLIO:")
        for pos in paper:
            lines.append(f"  - {pos.ticker} ({pos.strategy}): Entry {pos.entry_eur}€ | Stop {pos.stop_eur}€")

    lines.append(f"\nGeschlossene (nicht mehr überwachen):")
    for pos in p.real_positions(include_closed=True):
        if pos.is_closed():
            lines.append(f"  ❌ {pos.ticker} — GESCHLOSSEN, KEINE ALERTS!")
    for pos in p.paper_positions(include_closed=True):
        if pos.is_closed():
            lines.append(f"  ❌ {pos.ticker} — GESCHLOSSEN, KEINE ALERTS!")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Portfolio Summary')
    parser.add_argument('--real-tickers', action='store_true')
    parser.add_argument('--paper-tickers', action='store_true')
    parser.add_argument('--all-tickers', action='store_true')
    parser.add_argument('--yahoo', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--cron-context', action='store_true')
    args = parser.parse_args()

    p = Portfolio()

    if args.real_tickers:
        print(",".join(p.real_active_tickers()))
    elif args.paper_tickers:
        print(",".join(p.paper_active_tickers()))
    elif args.all_tickers:
        print(",".join(p.all_active_tickers()))
    elif args.yahoo:
        all_t = p.all_active_tickers()
        yahoo = get_yahoo_tickers(all_t)
        print(",".join(yahoo))
    elif args.json:
        data = {
            'real': [{'ticker': pos.ticker, 'name': pos.name, 'entry': pos.entry_eur,
                       'stop': pos.stop_eur, 'strategy': pos.strategy, 'yahoo': pos.yahoo or YAHOO_MAP.get(pos.ticker, pos.ticker)}
                      for pos in p.real_positions()],
            'paper': [{'ticker': pos.ticker, 'entry': pos.entry_eur,
                        'stop': pos.stop_eur, 'target': pos.target_eur, 'strategy': pos.strategy}
                       for pos in p.paper_positions()],
            'closed_real': [pos.ticker for pos in p.real_positions(include_closed=True) if pos.is_closed()],
            'closed_paper': [pos.ticker for pos in p.paper_positions(include_closed=True) if pos.is_closed()],
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif args.cron_context:
        print(cron_context(p))
    else:
        # Voller Report
        s = p.summary()
        print(f"=== PORTFOLIO SUMMARY ===\n")
        print(f"Echtes Portfolio ({s['real_open']} Positionen):")
        for pos in p.real_positions():
            stop = f"Stop {pos.stop_eur}€" if pos.stop_eur else "⚠️ KEIN STOP"
            print(f"  ✅ {pos.name:20s} ({pos.ticker:10s}) Entry {pos.entry_eur:>8.2f}€ | {stop}")
        print(f"\nPaper Portfolio ({s['paper_open']} Positionen):")
        for pos in p.paper_positions():
            print(f"  🧪 {pos.ticker:10s} ({pos.strategy:4s}) Entry {pos.entry_eur:>8.2f}€ | Stop {pos.stop_eur:.2f}€ | Ziel {pos.target_eur:.2f}€")
        print(f"\nAlle aktiven Tickers: {', '.join(s['all_active'])}")

        # Geschlossene
        closed = [pos.ticker for pos in p.real_positions(include_closed=True) if pos.is_closed()]
        closed += [pos.ticker for pos in p.paper_positions(include_closed=True) if pos.is_closed()]
        if closed:
            print(f"\n❌ Geschlossen (KEINE Alerts): {', '.join(closed)}")


if __name__ == "__main__":
    main()
