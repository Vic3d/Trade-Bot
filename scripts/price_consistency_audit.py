#!/usr/bin/env python3
"""
price_consistency_audit.py — Phase 45x (D1).

Cross-Check: paper_portfolio.close_price vs prices-Tabelle Tagesschluss.
Bei Abweichung > 5%: Alert + Eintrag in data/price_consistency_log.jsonl.

Hätte den heutigen PYPL-Bug (close_price 39.49 vs Tagesschluss 46.31)
sofort beim naechsten Run gefangen statt nach 6h zufaelliger Entdeckung
durch User.

Run: taeglich 23:30 (vor Auto-Deprecate). CLI: python3 ... [--dry-run]
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'price_consistency_log.jsonl'

THRESHOLD_PCT = 5.0  # Abweichung > 5% -> verdaechtig


def audit(days: int = 14, dry_run: bool = False) -> dict:
    """Prueft alle CLOSED-Trades der letzten N Tage gegen prices-Tabelle."""
    if not DB.exists():
        return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    issues = []
    rows = c.execute(
        "SELECT id, ticker, close_price, close_date, exit_type, pnl_eur "
        "FROM paper_portfolio "
        "WHERE close_price IS NOT NULL "
        "  AND close_date >= date('now', ?) "
        "  AND (exit_type IS NULL OR exit_type NOT LIKE 'BUG_ROLLBACK%') "
        "ORDER BY close_date DESC",
        (f'-{days} days',)
    ).fetchall()
    for r in rows:
        d = dict(r)
        ticker = d['ticker']
        close_price = float(d['close_price'])
        close_date = (d['close_date'] or '')[:10]
        # Hole prices-Eintrag fuer den Tag (oder naechstgelegen)
        pr = c.execute(
            "SELECT date, close FROM prices WHERE ticker=? "
            "AND date <= ? ORDER BY date DESC LIMIT 1",
            (ticker, close_date)
        ).fetchone()
        if not pr or not pr[1]: continue
        market_close = float(pr[1])
        if market_close == 0: continue
        dev_pct = abs(close_price - market_close) / market_close * 100
        if dev_pct > THRESHOLD_PCT:
            issues.append({
                'trade_id': d['id'],
                'ticker': ticker,
                'close_price_db': round(close_price, 2),
                'market_close_same_day': round(market_close, 2),
                'deviation_pct': round(dev_pct, 1),
                'close_date': close_date,
                'exit_type': d['exit_type'],
                'pnl_eur': d['pnl_eur'],
            })
    c.close()

    result = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'days_analyzed': days,
        'trades_checked': len(rows),
        'issues_found': len(issues),
        'issues': issues,
        'threshold_pct': THRESHOLD_PCT,
    }

    if not dry_run and issues:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(result, default=str) + '\n')
        # Discord-Alert (Emergency-Category)
        try:
            sys.path.insert(0, str(WS / 'scripts'))
            from discord_dispatcher import send_alert, TIER_HIGH
            msg = (f"⚠ **Price-Consistency-Audit** — {len(issues)} Issues:\n"
                   + '\n'.join(
                       f"  - #{i['trade_id']} {i['ticker']} {i['close_date']}: "
                       f"DB {i['close_price_db']} vs Markt {i['market_close_same_day']} "
                       f"({i['deviation_pct']}% Abweichung)"
                       for i in issues[:5]))
            send_alert(msg[:1900], tier=TIER_HIGH, category='system_error',
                        dedupe_key=f'price_audit_{datetime.now().date()}')
        except Exception: pass
    return result


def main() -> int:
    dry = '--dry-run' in sys.argv
    r = audit(days=14, dry_run=dry)  # Phase 45ab: 7d -> 14d (MOS+PAAS schluepften durch)
    print(json.dumps(r, indent=2, default=str))
    return 0 if r.get('issues_found', 0) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
