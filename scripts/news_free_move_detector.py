#!/usr/bin/env python3
"""
news_free_move_detector.py — Phase 45z (Victor 2026-05-07).

Edge-Detection-Klasse J1: Erkennt anomale Preis-Moves OHNE News-Trigger.

Hintergrund (06.05.2026): Trump-Iran-Deal-Ankuendigung crashte Oel −7,95%.
~70 Min davor wurden $920–950M Oel-Futures geshortet. Pattern:
Insider-Front-Running zeigt sich oft als grosser Move OHNE oeffentliche
News-Begleitung. Wenn unser news_reactor in den letzten 30 Min keinen
Tier-1/2-Event fuer den Sektor hatte — und der Preis bewegt sich >2% —
ist das ein Verdachts-Signal.

Mechanik:
  Pro Asset (open positions + commodity_prices):
    1. Zieht Preis-Snapshots (10/30/60 min Fenster)
    2. Prueft ob Move >THRESHOLD ohne News-Reactor-Event
    3. Bei Match: Discord-HIGH (category=anomalous_move)

Run: alle 10min via scheduler. Output: data/anomalous_moves_log.jsonl
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
NEWS_LOG = WS / 'data' / 'news_reactor_log.jsonl'
COMMODITIES = WS / 'data' / 'commodity_prices.json'
OUT_LOG = WS / 'data' / 'anomalous_moves_log.jsonl'

# Schwellenwerte
MOVE_THRESHOLD_10MIN_PCT = 1.5
MOVE_THRESHOLD_30MIN_PCT = 2.5
NEWS_LOOKBACK_MIN = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _news_events_for_ticker(ticker: str, since_min: int) -> list[dict]:
    """Liest news_reactor_log: Events die diesen Ticker (oder Sektor) erwaehnen."""
    if not NEWS_LOG.exists(): return []
    cutoff = _now() - timedelta(minutes=since_min)
    out = []
    try:
        with open(NEWS_LOG, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    o = json.loads(line)
                    ts = o.get('ts')
                    if not ts: continue
                    t = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                    if t.tzinfo is None: t = t.replace(tzinfo=timezone.utc)
                    if t < cutoff: continue
                    # Match: ticker direkt oder im news-text
                    if (o.get('ticker', '').upper() == ticker.upper() or
                        ticker.upper() in (o.get('news') or '').upper()):
                        out.append(o)
                except Exception: continue
    except Exception: pass
    return out


def _commodity_moves() -> list[dict]:
    """Liest commodity_prices.json: alle Symbole mit chg_24h_pct."""
    if not COMMODITIES.exists(): return []
    try:
        d = json.loads(COMMODITIES.read_text(encoding='utf-8'))
        out = []
        for sym, p in (d.get('prices') or {}).items():
            if not isinstance(p, dict): continue
            out.append({
                'ticker': sym, 'name': p.get('name', sym),
                'sector': p.get('sector', '?'),
                'spot': p.get('spot'),
                'chg_24h_pct': p.get('chg_24h_pct'),
                'chg_7d_pct': p.get('chg_7d_pct'),
            })
        return out
    except Exception: return []


def _open_position_moves() -> list[dict]:
    """Open positions mit aktuellem MTM-Drift gegen letzten DB-Close."""
    if not DB.exists(): return []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        out = []
        for r in c.execute(
            "SELECT ticker, entry_price, shares FROM paper_portfolio "
            "WHERE status='OPEN'"
        ):
            d = dict(r)
            pr = c.execute(
                "SELECT date, close FROM prices WHERE ticker=? "
                "ORDER BY date DESC LIMIT 2",
                (d['ticker'],)
            ).fetchall()
            if len(pr) < 2: continue
            chg_pct = (pr[0]['close'] - pr[1]['close']) / pr[1]['close'] * 100
            out.append({
                'ticker': d['ticker'],
                'last_close': pr[0]['close'],
                'prev_close': pr[1]['close'],
                'chg_pct': round(chg_pct, 2),
            })
        c.close()
        return out
    except Exception: return []


def detect() -> list[dict]:
    """Findet anomale Moves ohne News-Begleitung."""
    suspicious: list[dict] = []

    # 1. Commodities — Brent/WTI/Gold/Silver
    for c in _commodity_moves():
        chg = c.get('chg_24h_pct')
        if chg is None or abs(chg) < 3.0: continue  # Commodities-Threshold
        # Suche Sector-News in letzten 60min (Commodities haben oft Sector-News)
        sector_news = _news_events_for_ticker(c['ticker'], 60)
        # Auch Suchworte: 'oil', 'crude', 'gold' etc
        kw = {'BZ=F': 'oil', 'CL=F': 'crude', 'GC=F': 'gold',
              'SI=F': 'silver', 'NG=F': 'natural gas'}.get(c['ticker'])
        if kw:
            sector_news += [e for e in _news_events_for_ticker(kw, 60)
                            if e not in sector_news]
        if not sector_news:
            suspicious.append({
                'kind': 'news_free_commodity_move',
                'ticker': c['ticker'], 'name': c['name'],
                'chg_24h_pct': chg,
                'reason': f'{abs(chg):.1f}% Bewegung ohne News-Trigger in letzten 60min',
            })

    # 2. Open positions — kleinere Schwelle weil intraday relevanter
    for p in _open_position_moves():
        if abs(p['chg_pct']) < MOVE_THRESHOLD_30MIN_PCT: continue
        news = _news_events_for_ticker(p['ticker'], NEWS_LOOKBACK_MIN)
        if not news:
            suspicious.append({
                'kind': 'news_free_position_move',
                'ticker': p['ticker'],
                'chg_pct': p['chg_pct'],
                'reason': f'{abs(p["chg_pct"]):.1f}% Bewegung ohne News in letzten {NEWS_LOOKBACK_MIN}min',
            })

    return suspicious


def main() -> int:
    findings = detect()
    out = {
        'ts': _now().isoformat(timespec='seconds'),
        'n_suspicious': len(findings),
        'findings': findings,
    }
    if findings:
        OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(out, default=str) + '\n')
        # Discord-Alert (Emergency-Whitelist)
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from discord_dispatcher import send_alert, TIER_HIGH
            msg = (f"🚨 **News-Free-Anomalie** ({len(findings)} Verdaechtige):\n"
                   + '\n'.join(
                       f"  - {f['ticker']}: {f['reason']}"
                       for f in findings[:5]))
            send_alert(msg[:1900], tier=TIER_HIGH, category='system_error',
                        dedupe_key=f'news_free_move_{datetime.now().strftime("%Y%m%d_%H")}')
        except Exception: pass
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
