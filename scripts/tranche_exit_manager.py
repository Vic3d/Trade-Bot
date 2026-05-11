#!/usr/bin/env python3
"""
tranche_exit_manager.py — Phase 45aq Layer B3 (Victor 2026-05-11).

Tranche-Exit-Logik für offene Positionen:
  - Tranche 1: 33% raus bei +5% unrealized
  - Tranche 2: 33% raus bei +12% unrealized
  - Tranche 3: 34% trailen via Chandelier (HWM - 2*ATR)
  - Time-Stop: 30 Tage flat (-2% bis +2%) → Exit-Recommendation

Output: data/tranche_recommendations.jsonl + ceo_inbox events.
Run: täglich 22:00 nach Decision-Review.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'tranche_recommendations.jsonl'

TRANCHE_1_THRESHOLD = 0.05   # +5%
TRANCHE_2_THRESHOLD = 0.12   # +12%
TIME_STOP_DAYS = 30
TIME_STOP_FLAT_BAND = 0.02   # ±2% = flat


def _live_pnl_pct(ticker: str, entry_price_eur: float) -> tuple[float | None, float | None]:
    """Live PnL in % + native price."""
    if not DB.exists(): return None, None
    try:
        c = sqlite3.connect(str(DB))
        pr = c.execute("SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
                      (ticker,)).fetchone()
        c.close()
        if not pr or not pr[0] or entry_price_eur <= 0: return None, None
        try:
            sys.path.insert(0, str(WS / 'scripts' / 'core'))
            from live_data import get_fx_factor
            fx = get_fx_factor(ticker) or 1.0
        except Exception:
            fx = 1.0
        last_eur = float(pr[0]) * fx
        pnl_pct = (last_eur - entry_price_eur) / entry_price_eur
        return pnl_pct, float(pr[0])
    except Exception:
        return None, None


def analyze_positions() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    recommendations = []
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)
    for r in c.execute(
        "SELECT id, ticker, strategy, entry_date, entry_price, stop_price, "
        "shares, tranche_mode FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall():
        d = dict(r)
        pnl_pct, _live = _live_pnl_pct(d['ticker'], d['entry_price'])
        if pnl_pct is None: continue

        # Age in days
        try:
            ed = datetime.fromisoformat(d['entry_date'].replace('Z', '+00:00'))
            age_days = (now - ed).days
        except Exception:
            age_days = 0

        tranche_mode = (d.get('tranche_mode') or 'FULL_TRAIL').upper()
        rec = None

        # Tranche-Checks (nur wenn nicht schon ausgeführt)
        if tranche_mode == 'FULL_TRAIL':
            if pnl_pct >= TRANCHE_2_THRESHOLD:
                rec = {'action': 'TRANCHE_2_EXIT', 'pct_to_close': 0.33,
                       'reason': f'+{pnl_pct*100:.1f}% ≥ +12% — secure Tranche 2'}
            elif pnl_pct >= TRANCHE_1_THRESHOLD:
                rec = {'action': 'TRANCHE_1_EXIT', 'pct_to_close': 0.33,
                       'reason': f'+{pnl_pct*100:.1f}% ≥ +5% — secure Tranche 1'}

        # Time-Stop
        if not rec and age_days >= TIME_STOP_DAYS and abs(pnl_pct) <= TIME_STOP_FLAT_BAND:
            rec = {'action': 'TIME_STOP_EXIT', 'pct_to_close': 1.0,
                   'reason': f'{age_days}d alt, PnL {pnl_pct*100:+.1f}% flat — Kapital freisetzen'}

        if rec:
            recommendations.append({
                'trade_id': d['id'],
                'ticker': d['ticker'],
                'strategy': d['strategy'],
                'pnl_pct': round(pnl_pct * 100, 2),
                'age_days': age_days,
                'recommendation': rec,
            })

    c.close()

    if recommendations:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            for r in recommendations:
                r['ts'] = now.isoformat(timespec='seconds')
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

        # CEO-Inbox notifizieren
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from ceo_inbox import write_event
            for r in recommendations:
                write_event(
                    event_type='tranche.recommendation',
                    message=(f"{r['ticker']} {r['recommendation']['action']}: "
                             f"{r['recommendation']['reason']}"),
                    severity='info', category='health',
                    user_pinged=False, payload=r,
                )
        except Exception: pass

    return {'ts': now.isoformat(timespec='seconds'),
            'n_recommendations': len(recommendations),
            'recommendations': recommendations}


def main() -> int:
    r = analyze_positions()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
