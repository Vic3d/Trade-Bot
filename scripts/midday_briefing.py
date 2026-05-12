#!/usr/bin/env python3
"""
midday_briefing.py — Phase 45as (Victor 2026-05-12).

Volles Mid-Day EU-Briefing 13:00 CEST. Schließt die Lücke zwischen Morgen-
Briefing (08:00) und US-Open (16:30). Form wie Morgen-Briefing:
  - Markt-Snapshot (DAX live, Brent, VIX, EUR/USD)
  - Open-Positions live-PnL (FX-sicher via position_pnl)
  - Was passierte in EU heute Vormittag (Top-Mover, Sektor-Heat)
  - Catalysts heute Nachmittag (US-Open + Macro)
  - Narrativ-Block (4-6 Sätze Fließtext)

Output via stdout — wird vom Scheduler discord=True an Discord gepusht.
Volltext bleibt im scheduler.log archiviert.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
sys.path.insert(0, str(WS / 'scripts'))
sys.path.insert(0, str(WS / 'scripts' / 'core'))


def _fetch(t: str, period: str = '5d'):
    try:
        import yfinance as yf
        return yf.Ticker(t).history(period=period)
    except Exception:
        return None


def _market_snapshot() -> list[str]:
    facts = []
    # DAX live
    dax = _fetch('^GDAXI', '5d')
    if dax is not None and len(dax) >= 2:
        last = float(dax['Close'].iloc[-1])
        prev = float(dax['Close'].iloc[-2])
        chg = (last - prev) / prev * 100
        facts.append(f"DAX: {last:.0f} ({chg:+.2f}%)")
    # Brent
    brent = _fetch('BZ=F', '5d')
    if brent is not None and len(brent) >= 2:
        last = float(brent['Close'].iloc[-1])
        prev = float(brent['Close'].iloc[-2])
        chg = (last - prev) / prev * 100
        facts.append(f"Brent: {last:.2f} USD ({chg:+.2f}%)")
    # VIX
    vix = _fetch('^VIX', '5d')
    if vix is not None and len(vix) >= 1:
        last = float(vix['Close'].iloc[-1])
        facts.append(f"VIX: {last:.2f}")
    # EUR/USD
    eu = _fetch('EURUSD=X', '5d')
    if eu is not None and len(eu) >= 1:
        last = float(eu['Close'].iloc[-1])
        facts.append(f"EUR/USD: {last:.4f}")
    # Gold/Silber
    gold = _fetch('GC=F', '5d')
    sil = _fetch('SI=F', '5d')
    if gold is not None and len(gold) >= 2:
        last = float(gold['Close'].iloc[-1])
        prev = float(gold['Close'].iloc[-2])
        chg = (last - prev) / prev * 100
        facts.append(f"Gold: {last:.0f} ({chg:+.2f}%)")
    if sil is not None and len(sil) >= 2:
        last = float(sil['Close'].iloc[-1])
        prev = float(sil['Close'].iloc[-2])
        chg = (last - prev) / prev * 100
        facts.append(f"Silver: {last:.2f} ({chg:+.2f}%)")
    return facts


def _open_positions() -> list[str]:
    if not DB.exists(): return []
    facts = []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        from position_pnl import get_position_pnl
        for r in c.execute(
            "SELECT id, ticker, strategy, entry_price, shares, stop_price, target_price "
            "FROM paper_portfolio WHERE status='OPEN'"
        ).fetchall():
            d = dict(r)
            if not d['entry_price'] or not d['shares']: continue
            pnl = get_position_pnl(d['ticker'], d['entry_price'], d['shares'])
            if pnl.get('valid'):
                facts.append(
                    f"OPEN: {d['ticker']} ({d['strategy']}) entry {d['entry_price']:.2f}EUR, "
                    f"live {pnl['live_eur']:.2f}EUR (native {pnl['live_native']}, fx={pnl['fx_factor']}), "
                    f"unr {pnl['pnl_eur']:+.1f}EUR ({pnl['pnl_pct']:+.2f}%), "
                    f"stop {d['stop_price']:.2f}, target {d['target_price']:.2f}"
                )
        c.close()
    except Exception as e:
        facts.append(f"position-block error: {e}")
    return facts


def _eu_sector_heat() -> list[str]:
    """Top 3 Sektor-ETFs heute (EU-relevant)."""
    facts = []
    tickers = {'EXSA.DE': 'EuroStoxx', 'XDWT.DE': 'Tech-Welt',
               '^STOXX50E': 'Euro Stoxx 50', '^FCHI': 'CAC', '^FTSE': 'FTSE 100'}
    moves = []
    for t, name in tickers.items():
        h = _fetch(t, '5d')
        if h is not None and len(h) >= 2:
            last = float(h['Close'].iloc[-1])
            prev = float(h['Close'].iloc[-2])
            chg = (last - prev) / prev * 100
            moves.append((name, t, chg))
    moves.sort(key=lambda x: x[2], reverse=True)
    if moves:
        facts.append("EU-Indizes: " + ', '.join(f"{m[0]} {m[2]:+.1f}%" for m in moves[:5]))
    return facts


def _morning_news_summary() -> list[str]:
    """News der letzten 6h aus news_reactor_log."""
    facts = []
    nl = WS / 'data' / 'news_reactor_log.jsonl'
    if not nl.exists(): return facts
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    recent = []
    try:
        with open(nl, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = e.get('ts') or e.get('timestamp', '')
                    if ts > cutoff:
                        recent.append(e)
                except Exception: pass
    except Exception: pass
    if recent:
        facts.append(f"NEWS-EVENTS letzte 6h: {len(recent)}")
        for ev in recent[-5:]:
            headline = (ev.get('news') or ev.get('headline') or '')[:140]
            tk = ev.get('ticker', '')
            facts.append(f"  [{tk}] {headline}")
    return facts


def _catalysts_today() -> list[str]:
    """Earnings + Macro-Events heute."""
    facts = []
    ce = WS / 'data' / 'upcoming_events.json'
    if not ce.exists(): return facts
    try:
        events = json.loads(ce.read_text(encoding='utf-8')).get('events', [])
        today = datetime.now().date().isoformat()
        today_events = [e for e in events if (e.get('date') or '').startswith(today)]
        if today_events:
            facts.append(f"CATALYSTS HEUTE: {len(today_events)}")
            for ev in today_events[:5]:
                facts.append(f"  {ev.get('type','?')} {ev.get('ticker','')}: {ev.get('description','')[:100]}")
    except Exception: pass
    return facts


def _macro_regime() -> list[str]:
    p = WS / 'data' / 'macro_regime.json'
    if not p.exists(): return []
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        return [f"REGIME: {d.get('regime','?')} (score={d.get('score','?')}, conf={d.get('confidence','?')})"]
    except Exception: return []


def generate_briefing() -> str:
    """Volltext-Briefing — wird vom Scheduler an Discord narrativ extrahiert."""
    now = datetime.now()
    lines = [f"=== MID-DAY EU-BRIEFING {now.strftime('%d.%m.%Y %H:%M')} CEST ===\n"]
    lines.append("━━ MARKT-LAGE ━━")
    lines.extend("  " + l for l in _market_snapshot())
    lines.append("")
    lines.append("━━ EU-INDIZES ━━")
    lines.extend("  " + l for l in _eu_sector_heat())
    lines.append("")
    lines.append("━━ OPEN POSITIONS (FX-sicher) ━━")
    pos = _open_positions()
    if pos:
        lines.extend("  " + l for l in pos)
    else:
        lines.append("  KEINE")
    lines.append("")
    lines.append("━━ REGIME ━━")
    lines.extend("  " + l for l in _macro_regime())
    lines.append("")
    lines.append("━━ NEWS letzte 6h ━━")
    nf = _morning_news_summary()
    if nf:
        lines.extend("  " + l for l in nf)
    else:
        lines.append("  Keine Events.")
    lines.append("")
    lines.append("━━ CATALYSTS HEUTE ━━")
    cf = _catalysts_today()
    if cf:
        lines.extend("  " + l for l in cf)
    else:
        lines.append("  Keine bekannten Catalysts.")
    lines.append("")
    # Narrativ via Generator
    facts_for_narrative = (
        _market_snapshot() + _eu_sector_heat() + _open_positions()
        + _macro_regime() + _morning_news_summary()[:5] + _catalysts_today()
    )
    narrative = ''
    try:
        from narrative_generator import build_narrative
        narrative = build_narrative(facts_for_narrative, briefing_type='midday')
    except Exception as e:
        narrative = f'(narrative_generator unavailable: {e})'

    lines.append("📖 **MID-DAY-NARRATIV:**")
    lines.append(narrative)
    return '\n'.join(lines)


def main() -> int:
    print(generate_briefing())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
