#!/usr/bin/env python3
"""
ceo_week_ahead_briefing.py — Phase 44v: Sonntag-Vorbereitung auf neue Woche.

Laeuft Sonntag 18:00 (vor Mo-Open). Ohne Trading-Latency-Druck nimmt sich
Albert Zeit fuer:

1. WEEK-RECAP letzte 5 Trading-Tage:
   - Open Positions: PnL-Entwicklung
   - Trades-Statistik: Wins/Losses/Avg
   - Was hat funktioniert / was nicht
2. CATALYST-CALENDAR naechste 7 Tage:
   - Earnings unsere Tickers + Watch-List
   - Macro-Events (FOMC, CPI, NFP, ECB, BOJ)
   - Politische Events (SCOTUS, Trump-Deadlines)
3. THESES-CHECK fuer offene Positionen:
   - Pro Position: ist These noch valide nach Wochenend-News?
   - Aenderungen seit Eintritt
4. WEEK-AHEAD-DIREKTIVE:
   - Bias: Cautious/Neutral/Aggressive mit Begruendung
   - 3-5 konkrete Regeln fuer die Woche
   - Watch-Themen
   - Verbote

Output:
  memory/ceo-week-briefings/YYYY-WW.md   Vollstaendiges Briefing
  memory/ceo-today-directive.md          Mo-Direktive (wird Mo morgens vom
                                          ceo_self_research aktualisiert)

Discord: 1 MEDIUM-Push am Sonntag Abend mit Kurz-Summary (Digest-Slot).

Run: python3 scripts/ceo_week_ahead_briefing.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
BRIEFINGS_DIR = WS / 'memory' / 'ceo-week-briefings'
TODAY_DIRECTIVE = WS / 'memory' / 'ceo-today-directive.md'


SYSTEM = """Du bist Albert, der TradeMind-CEO. Es ist Sonntag abend.
Du hast Zeit, ohne Trading-Latency. Bereite die kommende Woche vor.

Liefere ein strukturiertes Briefing mit diesen Sektionen:

# WEEK-RECAP
Was lief letzte Woche? (1-2 Saetze pro KPI: PnL, WR, getriggerte Strategies)

# OFFENE POSITIONEN — These-Check
Pro Position: ist These noch valide? Was hat sich geaendert seit Eintritt?

# CATALYST-WOCHE
Was kommt diese Woche an Earnings/Macro/Politik?

# DIREKTIVE FUER MONTAG
- BIAS: AGGRESSIVE/NEUTRAL/CAUTIOUS mit 1 Satz Begruendung
- 3-5 konkrete REGELN fuer Mo-Fr
- WATCH-Themen (was beobachten?)
- VERBOTE (was nicht tun?)

Sei nuechtern, kein Hype. Daten > Bauchgefuehl. Markdown-Format."""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _gather_week_recap(c: sqlite3.Connection) -> dict:
    """Letzte 7 Tage: PnL, WR, Trades, Top/Bottom-Performer."""
    rows = c.execute(
        "SELECT id, ticker, strategy, status, pnl_eur, exit_type, "
        "       entry_date, close_date FROM paper_portfolio "
        "WHERE entry_date >= date('now','-8 days') OR "
        "      close_date >= date('now','-8 days')"
    ).fetchall()
    closed = [r for r in rows if r[3] in ('WIN','LOSS','CLOSED')]
    pnl_total = sum(r[4] or 0 for r in closed)
    wins = sum(1 for r in closed if (r[4] or 0) > 0)
    n = len(closed)
    wr = (100*wins/n) if n else 0
    return {'closed_count': n, 'pnl_total': round(pnl_total,2),
            'wr_pct': round(wr,1),
            'top': sorted(closed, key=lambda r: -(r[4] or 0))[:3],
            'bottom': sorted(closed, key=lambda r: (r[4] or 0))[:3]}


def _gather_open_positions(c: sqlite3.Connection) -> list[dict]:
    rows = c.execute(
        "SELECT id, ticker, strategy, entry_price, stop_price, target_price, "
        "       entry_date FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(zip(['id','ticker','strategy','entry','stop','target','entry_date'], r))
        # Live-Preis
        try:
            lr = c.execute("SELECT close FROM prices WHERE ticker=? "
                            "ORDER BY date DESC LIMIT 1", (d['ticker'],)).fetchone()
            d['last_close'] = float(lr[0]) if lr else None
        except: d['last_close'] = None
        out.append(d)
    return out


def _gather_catalysts(c: sqlite3.Connection) -> list[dict]:
    """Earnings + Macro fuer naechste 7 Tage."""
    out = []
    today = datetime.now().strftime('%Y-%m-%d')
    until = (datetime.now() + timedelta(days=8)).strftime('%Y-%m-%d')
    try:
        rows = c.execute(
            "SELECT date, ticker, type FROM earnings_calendar "
            "WHERE date >= ? AND date <= ? ORDER BY date",
            (today, until)
        ).fetchall()
        for r in rows:
            out.append({'kind': 'earnings', 'date': r[0],
                        'ticker': r[1], 'type': r[2] or 'EARNINGS'})
    except Exception: pass
    # Catalyst-Calendar (FOMC etc.)
    try:
        rows = c.execute(
            "SELECT date, ticker, event_type FROM catalyst_calendar "
            "WHERE date >= ? AND date <= ? ORDER BY date",
            (today, until)
        ).fetchall()
        for r in rows:
            out.append({'kind': 'catalyst', 'date': r[0],
                        'ticker': r[1] or 'macro', 'type': r[2]})
    except Exception: pass
    # Bekannte Catalyst-Termine (hardcoded)
    try:
        from calendar_service import FED_MEETINGS_2026
        for d in FED_MEETINGS_2026:
            if today <= d <= until:
                out.append({'kind': 'fed', 'date': d, 'ticker': 'macro', 'type': 'FOMC'})
    except Exception: pass
    return sorted(out, key=lambda x: x.get('date',''))


def _gather_macro_events(c: sqlite3.Connection) -> list[dict]:
    try:
        rows = c.execute(
            "SELECT event_type, severity, detected_at FROM macro_events "
            "WHERE substr(detected_at,1,10) >= date('now','-7 days') "
            "ORDER BY detected_at DESC LIMIT 20"
        ).fetchall()
        return [{'event_type': r[0], 'severity': r[1], 'date': r[2]} for r in rows]
    except Exception: return []


def _build_briefing(recap: dict, opens: list[dict], catalysts: list[dict],
                     macro: list[dict]) -> str:
    """Ruft LLM auf mit allen Daten."""
    # Compact text fuer Prompt
    txt = []
    txt.append(f"## Woche-Recap (letzte 7 Tage)")
    txt.append(f"Geschlossen: {recap['closed_count']} Trades | "
               f"PnL: {recap['pnl_total']:+.0f} EUR | WR: {recap['wr_pct']}%")
    if recap['top']:
        txt.append("Top-Performer:")
        for r in recap['top']:
            txt.append(f"  - {r[1]} ({r[2]}): {r[4]:+.0f} EUR via {r[5] or 'CLOSE'}")
    if recap['bottom']:
        txt.append("Worst:")
        for r in recap['bottom']:
            txt.append(f"  - {r[1]} ({r[2]}): {r[4]:+.0f} EUR via {r[5] or 'CLOSE'}")

    txt.append(f"\n## Open Positions ({len(opens)})")
    for p in opens:
        live = p['last_close']
        unr_pct = ((live - p['entry']) / p['entry'] * 100) if live and p['entry'] else 0
        txt.append(f"  - {p['ticker']} ({p['strategy']}): "
                   f"entry {p['entry']:.2f}, live {live or '?'}, "
                   f"stop {p['stop']:.2f}, target {p['target']:.2f}, "
                   f"unr {unr_pct:+.1f}%")

    txt.append(f"\n## Catalyst-Kalender (naechste 7 Tage)")
    if catalysts:
        for c in catalysts[:15]:
            txt.append(f"  - {c['date']}: {c['kind']} {c['ticker']} {c.get('type','')}")
    else:
        txt.append("  (keine spezifischen Catalysts in Calendar — nur Macro)")

    txt.append(f"\n## Macro-Events letzte 7 Tage")
    counts = {}
    for e in macro: counts[e['event_type']] = counts.get(e['event_type'],0)+1
    for et, n in sorted(counts.items(), key=lambda x: -x[1]):
        txt.append(f"  - {et}: {n}x")

    prompt = '\n'.join(txt) + "\n\nGeneriere jetzt das strukturierte Briefing."

    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=2000, system=SYSTEM)
        return text
    except Exception as e:
        return f'(LLM-fail: {e})\n\nRaw-Daten:\n' + '\n'.join(txt)


def _extract_directive(briefing: str) -> str:
    """Extrahiert die DIREKTIVE-Sektion fuer ceo-today-directive.md."""
    import re
    m = re.search(r'#\s*DIREKTIVE.*?(?=\n#|\Z)', briefing, re.S | re.I)
    if m: return m.group(0)
    return briefing[:1500]


def run() -> dict:
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    recap = _gather_week_recap(c)
    opens = _gather_open_positions(c)
    catalysts = _gather_catalysts(c)
    macro = _gather_macro_events(c)
    c.close()

    briefing = _build_briefing(recap, opens, catalysts, macro)

    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    week = datetime.now().strftime('%Y-W%W')
    file = BRIEFINGS_DIR / f'{week}.md'
    full = (f"# Week-Ahead-Briefing {week}\n"
            f"*Geschrieben Sonntag {datetime.now().strftime('%d.%m.%Y %H:%M')} CET. "
            f"Vorbereitung auf neue Trading-Woche.*\n\n"
            f"---\n\n{briefing}")
    file.write_text(full, encoding='utf-8')

    # Directive extrahieren -> separate File die Mo-Hunter liest
    directive = _extract_directive(briefing)
    today = datetime.now().strftime('%Y-%m-%d')
    TODAY_DIRECTIVE.parent.mkdir(parents=True, exist_ok=True)
    TODAY_DIRECTIVE.write_text(
        f"# Heute-Direktive (von Sonntag-Briefing {today})\n\n{directive}\n",
        encoding='utf-8'
    )

    # Discord MEDIUM (in Digest)
    try:
        from discord_dispatcher import send_alert, TIER_MEDIUM
        # Kurz-Zusammenfassung
        short = (f'📅 **Week-Ahead {week}** geschrieben.\n'
                  f'Letzte Woche: {recap["closed_count"]} Trades, '
                  f'PnL {recap["pnl_total"]:+.0f}EUR, WR {recap["wr_pct"]}%\n'
                  f'Open: {len(opens)} | Catalysts naechste 7d: {len(catalysts)}\n'
                  f'_Volle Notiz: memory/ceo-week-briefings/{week}.md_')
        send_alert(short[:1900], tier=TIER_MEDIUM, category='week_ahead',
                    dedupe_key=f'week_ahead_{week}')
    except Exception: pass

    return {'ts': _now(), 'week': week, 'file': str(file),
            'recap': recap, 'opens': len(opens),
            'catalysts': len(catalysts), 'macro_events': len(macro)}


def main() -> int:
    r = run()
    print(f'═══ Week-Ahead-Briefing @ {r["ts"][:16]} ═══')
    print(f'  Week: {r["week"]}')
    print(f'  Recap: {r["recap"]["closed_count"]} trades, PnL {r["recap"]["pnl_total"]:+.0f}€, WR {r["recap"]["wr_pct"]}%')
    print(f'  Open positions: {r["opens"]}')
    print(f'  Catalysts: {r["catalysts"]}')
    print(f'  Macro events: {r["macro_events"]}')
    print(f'  File: {r["file"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
