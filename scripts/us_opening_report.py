#!/usr/bin/env python3
"""
us_opening_report.py — Opening Check (Xetra ODER US)

Bugfix 2026-04-23: Skript wurde zweimal aus Scheduler aufgerufen
  - 09:30 CET als "Xetra Opening"
  - 16:30 CET als "US Opening"
…aber holte in beiden Fällen NUR US-Ticker. Der 09:30-Run lieferte
Yahoo-`regularMarketPrice` für US-Ticker bei geschlossener NYSE
(= gestriger Close), gelabelt als "Opening" → irreführend.

Jetzt mit `--mode {xetra,us}`:
  xetra → DAX-Index + alle EU-Ticker (.DE/.AS/.PA/.L/.MI/.OL/.ST/.CO/.HE/.BR/.LS/.VI/.SW)
  us    → S&P 500 (^GSPC) + EURUSD + VIX + alle US-Ticker (kein Suffix)

Default: us (Backwards-Compat).
"""
import argparse, json, sys, time, urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))

EU_SUFFIXES = ('.DE', '.AS', '.PA', '.L', '.MI', '.OL', '.ST', '.CO', '.HE', '.BR', '.LS', '.VI', '.SW')


def yahoo(ticker, timeout=8):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        meta = d['chart']['result'][0]['meta']
        price = meta['regularMarketPrice']
        prev  = meta.get('chartPreviousClose', price)
        chg   = ((price - prev) / prev * 100) if prev else 0
        ccy   = meta.get('currency', 'USD')
        # Stale-Check: marketState in ('REGULAR','PRE','POST','CLOSED','PREPRE','POSTPOST')
        market_state = meta.get('marketState', 'UNKNOWN')
        return price, round(chg, 2), ccy, market_state
    except Exception:
        return None, 0, 'USD', 'ERROR'


def is_eu_ticker(ticker: str) -> bool:
    return any(ticker.upper().endswith(s) for s in EU_SUFFIXES)


def is_us_ticker(ticker: str) -> bool:
    # US = kein bekanntes EU/Asia-Suffix
    return not is_eu_ticker(ticker)


def report(mode: str) -> int:
    mode = mode.lower()
    if mode not in ('xetra', 'us'):
        print(f'unknown mode: {mode}', file=sys.stderr)
        return 2

    # ─── Index + FX ────────────────────────────────────────────────────────
    eurusd, _, _, _ = yahoo('EURUSD=X')
    eurusd = eurusd or 1.15
    time.sleep(0.15)

    if mode == 'xetra':
        idx_ticker, idx_label = '^GDAXI', 'DAX'
        title = 'XETRA OPENING'
        ticker_filter = is_eu_ticker
    else:
        idx_ticker, idx_label = '^GSPC', 'S&P500'
        title = 'US OPENING'
        ticker_filter = is_us_ticker

    idx_price, idx_chg, _, idx_state = yahoo(idx_ticker)
    time.sleep(0.15)
    vix, _, _, _ = yahoo('^VIX')
    vix = vix or 25.0
    time.sleep(0.15)

    market_warn = ''
    if idx_state and idx_state not in ('REGULAR', 'UNKNOWN'):
        market_warn = f' ⚠️ MarketState={idx_state} (nicht REGULAR — Daten ggf. stale!)'

    # ─── Portfolio ─────────────────────────────────────────────────────────
    try:
        from portfolio import Portfolio
        positions = Portfolio().real_positions()
    except Exception as e:
        print(f'Portfolio-Fehler: {e}', file=sys.stderr)
        return 1

    lines = []
    warnings = []
    for pos in positions:
        ticker = pos.ticker
        if not ticker_filter(ticker):
            continue

        price, chg, ccy, mstate = yahoo(ticker)
        time.sleep(0.15)
        if price is None:
            continue

        price_eur = price / eurusd if ccy == 'USD' else price
        stop      = pos.stop_eur
        name      = pos.name or ticker

        stop_dist = ''
        warn = ''
        if stop and stop > 0 and price_eur:
            dist_pct = (price_eur - stop) / price_eur * 100
            stop_dist = f' | Stop {stop:.2f}€ → {dist_pct:.1f}% weg'
            if dist_pct < 3:
                warn = ' ⚠️'
                warnings.append(f'{name} ({ticker}): Stop nur {dist_pct:.1f}% entfernt!')

        arrow = '▲' if chg >= 0 else '▼'
        ccy_sym = '$' if ccy == 'USD' else '€' if ccy == 'EUR' else (ccy + ' ')
        stale = '' if mstate == 'REGULAR' else f' [{mstate}]'
        lines.append(f'• {name} ({ticker}): {ccy_sym}{price:.2f} = {price_eur:.2f}€ ({arrow}{abs(chg):.1f}%){stop_dist}{warn}{stale}')

    # ─── CEO Direktive ─────────────────────────────────────────────────────
    ceo = {}
    try:
        ceo = json.loads((WS/'data/ceo_directive.json').read_text(encoding="utf-8"))
    except Exception:
        pass

    # ─── Output ────────────────────────────────────────────────────────────
    print(f"=== {title} REPORT {datetime.now(_BERLIN).strftime('%d.%m.%Y %H:%M')} ===")
    idx_p_str = f"{idx_price:.0f}" if idx_price else "n/a"
    print(f"{idx_label}: {idx_p_str} ({'+' if idx_chg >= 0 else ''}{idx_chg:.1f}%) | VIX: {vix:.1f} | EURUSD: {eurusd:.4f}{market_warn}")
    print(f"Mode: {ceo.get('mode','?')} | Regime: {ceo.get('regime','?')}")
    print()
    if not lines:
        print(f"(keine offenen {'EU' if mode=='xetra' else 'US'}-Positionen)")
    for l in lines:
        print(l)
    if warnings:
        print()
        print("STOP-WARNINGS:")
        for w in warnings:
            print(f"  ⚠️ {w}")

    # Phase 45r (Victor 2026-05-06): Narrativ-Block fuer US-Mode
    # Fliesstext-Zusammenfassung: was passierte uebernacht, wie ist der Plan.
    if mode == 'us':
        narrative = _build_overnight_narrative(eurusd, vix, idx_label, idx_chg, ceo)
        if narrative:
            print()
            print("📖 ÜBERNACHT & TAGESPLAN:")
            print(narrative)
    return 0


def _build_overnight_narrative(eurusd: float, vix: float,
                               idx_label: str, idx_chg: float, ceo: dict) -> str:
    """LLM-generiertes 3-6 Saetze Narrativ ueber Uebernacht-Geschehnisse +
    Tagesplan. Faellt auf strukturiertes Bullet-Backup zurueck wenn LLM
    nicht verfuegbar."""
    import sqlite3 as _sql
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    facts: list[str] = []
    # 1. Open positions mit Live-MTM
    try:
        c = _sql.connect(str(WS / 'data' / 'trading.db'))
        c.row_factory = _sql.Row
        for r in c.execute("SELECT ticker, strategy, entry_price, shares, stop_price, target_price FROM paper_portfolio WHERE status='OPEN'"):
            d = dict(r)
            pr = c.execute("SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (d['ticker'],)).fetchone()
            if pr and d['entry_price'] and d['shares']:
                pnl_eur = (pr[0] - d['entry_price']) * d['shares']
                pnl_pct = (pr[0]/d['entry_price'] - 1) * 100
                facts.append(f"OPEN: {d['ticker']} ({d['strategy']}) entry {d['entry_price']:.2f}, last {pr[0]:.2f}, unrealized {pnl_eur:+.0f}EUR ({pnl_pct:+.1f}%), stop {d['stop_price']:.2f}, target {d['target_price']:.2f}")
        # 2. Closed gestern
        for r in c.execute("SELECT ticker, strategy, ROUND(pnl_eur,1) pnl, exit_type FROM paper_portfolio WHERE close_date >= date('now','-1 day') AND pnl_eur IS NOT NULL"):
            d = dict(r)
            facts.append(f"GESTERN GESCHLOSSEN: {d['ticker']} ({d['strategy']}) {d['pnl']:+.1f}EUR via {d['exit_type'] or 'n/a'}")
        c.close()
    except Exception as e:
        facts.append(f"DB-Fehler: {e}")

    # 3. Markt-Snapshot
    facts.append(f"MARKT: {idx_label} {idx_chg:+.1f}%, VIX {vix:.1f}, EURUSD {eurusd:.4f}")
    facts.append(f"CEO-DIREKTIVE: Mode={ceo.get('mode','?')} Regime={ceo.get('regime','?')}")

    # 4. Letzte 12h News-Reactor-Events (Tier 1/2)
    try:
        nr_log = WS / 'data' / 'news_reactor_log.jsonl'
        if nr_log.exists():
            cutoff = _dt.now(_tz.utc) - _td(hours=12)
            recent = []
            with open(nr_log, encoding='utf-8') as f:
                for line in f:
                    try:
                        obj = _json.loads(line)
                        ts = obj.get('ts') or obj.get('timestamp')
                        if not ts: continue
                        t = _dt.fromisoformat(str(ts).replace('Z','+00:00'))
                        if t.tzinfo is None: t = t.replace(tzinfo=_tz.utc)
                        if t < cutoff: continue
                        recent.append(obj)
                    except Exception: continue
            if recent:
                facts.append(f"OVERNIGHT NEWS-REACTOR: {len(recent)} Events letzte 12h")
                for ev in recent[-3:]:
                    facts.append(f"  - {(ev.get('headline') or ev.get('title') or 'event')[:120]}")
    except Exception: pass

    # 5. Catalysts heute via calendar_service falls vorhanden
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from calendar_service import upcoming_events as _ue  # type: ignore
        events = _ue(days_ahead=1) or []
        if events:
            facts.append(f"CATALYSTS HEUTE: {len(events)}")
            for e in events[:5]:
                facts.append(f"  - {str(e)[:120]}")
    except Exception: pass

    facts_block = '\n'.join(facts)

    # LLM-Aufruf
    try:
        sys.path.insert(0, str(WS / 'scripts'))
        from core.llm_client import call_llm  # type: ignore
        prompt = (
            "Du bist Albert, der CEO eines autonomen Trading-Bots. Schreibe einen "
            "kurzen, zusammenhaengenden Text (4-6 Saetze, KEIN Bullet-List) der "
            "Victor zum US-Open einen klaren Ueberblick gibt:\n\n"
            "Struktur:\n"
            "1. Was uebernacht relevant passiert ist (News, Asia-Lead, Marktbewegung)\n"
            "2. Was das fuer unsere offene Position(en) bedeutet\n"
            "3. Was der Plan fuer den heutigen Handelstag ist (Catalysts, "
            "geplante Trades, Watchlist-Schwerpunkte, was wir vermeiden)\n\n"
            "Schreib in Du-Form an Victor. Keine Floskeln, kein Pathos. "
            "Nimm NUR die Fakten unten — erfinde NICHTS dazu.\n\n"
            "FAKTEN:\n"
            f"{facts_block}\n"
        )
        text, _usage = call_llm(prompt, model_hint='haiku', max_tokens=600,
                                audit_context='us_opening_narrative')
        return (text or '').strip()
    except Exception as e:
        # Fallback: strukturiertes Bullet-Backup
        return (
            "(LLM unavailable, Fakten-Backup):\n" + facts_block
        )


# Inline-Imports fuer das Narrativ
import json as _json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['xetra', 'us'], default='us',
                   help='xetra=DAX+EU-Ticker, us=S&P500+US-Ticker')
    a = p.parse_args()
    sys.exit(report(a.mode))


if __name__ == '__main__':
    main()
