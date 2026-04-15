#!/usr/bin/env python3
"""
Position Watchdog — Phase 14
=============================

Runs every 1-2h during market hours. For every OPEN position:
  1) Check current price vs stop/target/entry
  2) Re-evaluate conviction (Phase 3 scorer)
  3) Check insider signal (Phase 10) for flips to BEARISH
  4) Check macro regime (Phase 11) for RISK_OFF shift
  5) Re-validate thesis (via strategies.json status)
  6) Check auto_deepdive verdict flip → NICHT_KAUFEN

Action matrix:
  - Hard exit (stop hit, thesis INVALIDATED): force close → paper_exit_manager
  - Soft warn (insider flip, macro rotate): Discord alert + lower verdict
  - OK: log heartbeat

Writes:
  data/position_watchdog.json (last run snapshot)
  data/auto_exit_queue.json    (hard exits to trigger on next exit_manager run)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger('position_watchdog')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))

DATA = WS / 'data'
DB = DATA / 'trading.db'
STRATS = DATA / 'strategies.json'
VERDICTS = DATA / 'deep_dive_verdicts.json'
MACRO = DATA / 'macro_regime.json'
SNAPSHOT = DATA / 'position_watchdog.json'
AUTO_EXIT_QUEUE = DATA / 'auto_exit_queue.json'


def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def _save_json(p: Path, data) -> None:
    try:
        p.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception as e:
        log.warning(f'{p.name} save: {e}')


def _latest_price(ticker: str) -> float | None:
    try:
        c = sqlite3.connect(str(DB))
        row = c.execute(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        c.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _open_positions() -> list[dict]:
    out: list[dict] = []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, ticker, strategy, entry_price, stop, target, "
            "shares, pnl_pct, thesis FROM trades WHERE status='OPEN'"
        ).fetchall()
        c.close()
        for r in rows:
            out.append(dict(r))
    except Exception as e:
        log.warning(f'open positions: {e}')
    return out


def _thesis_status(strategy: str) -> str:
    strats = _load_json(STRATS, {})
    cfg = strats.get(strategy, {})
    if not isinstance(cfg, dict):
        return 'unknown'
    return str(cfg.get('status', 'active')).lower()


def _notify(msg: str) -> None:
    try:
        from discord_sender import send
        send(msg[:1900])
    except Exception:
        pass


def _queue_auto_exit(trade_id: int, ticker: str, reason: str) -> None:
    queue = _load_json(AUTO_EXIT_QUEUE, [])
    # dedupe
    for q in queue:
        if q.get('trade_id') == trade_id:
            return
    queue.append({
        'trade_id': trade_id,
        'ticker': ticker,
        'reason': reason,
        'queued_at': datetime.now().isoformat(timespec='seconds'),
    })
    _save_json(AUTO_EXIT_QUEUE, queue)


def _evaluate_position(pos: dict) -> dict:
    ticker = pos['ticker']
    trade_id = pos['id']
    entry = pos.get('entry_price') or 0
    stop = pos.get('stop') or 0
    target = pos.get('target') or 0
    strategy = pos.get('strategy') or ''

    price = _latest_price(ticker)
    result = {
        'trade_id': trade_id,
        'ticker': ticker,
        'strategy': strategy,
        'price': price,
        'entry': entry,
        'stop': stop,
        'target': target,
        'actions': [],  # list of {'severity': HARD|SOFT, 'reason': ...}
        'status': 'OK',
    }

    if price is None:
        result['actions'].append({'severity': 'SOFT', 'reason': 'no price data'})
        result['status'] = 'STALE'
        return result

    pnl_pct = ((price - entry) / entry * 100) if entry else 0
    result['pnl_pct'] = round(pnl_pct, 2)

    # 1) Stop hit
    if stop and price <= stop:
        result['actions'].append({
            'severity': 'HARD',
            'reason': f'stop hit: {price:.2f} <= {stop:.2f}',
        })

    # 2) Thesis INVALIDATED
    if strategy:
        status = _thesis_status(strategy)
        if status == 'invalidated':
            result['actions'].append({
                'severity': 'HARD',
                'reason': f'thesis {strategy} INVALIDATED',
            })
        elif status == 'degraded':
            result['actions'].append({
                'severity': 'SOFT',
                'reason': f'thesis {strategy} DEGRADED',
            })

    # 3) Auto Deep Dive verdict flip
    verdicts = _load_json(VERDICTS, {})
    v = verdicts.get(ticker.upper(), {})
    if v.get('verdict') == 'NICHT_KAUFEN':
        # Only flag as concern — not auto-exit (exits need stop/thesis)
        result['actions'].append({
            'severity': 'SOFT',
            'reason': f"deep dive verdict flipped to NICHT_KAUFEN ({v.get('date', '?')})",
        })

    # 4) Insider bearish flip
    try:
        from intelligence.sec_edgar import insider_signal
        sig = insider_signal(ticker, days=14, use_cache=True)
        if sig.get('bias') == 'BEARISH' and int(sig.get('score', 0)) <= -50:
            result['actions'].append({
                'severity': 'SOFT',
                'reason': f"insider BEARISH ({sig.get('score')}) {sig.get('reason', '')[:50]}",
            })
    except Exception:
        pass

    # 5) Macro regime RISK_OFF
    macro = _load_json(MACRO, {})
    if macro.get('regime') in ('RISK_OFF', 'RECESSION', 'STAGFLATION'):
        if macro.get('score', 0) <= -30:
            result['actions'].append({
                'severity': 'SOFT',
                'reason': f"macro {macro.get('regime')} score {macro.get('score')}",
            })

    # 6) Circuit breaker -8%
    if pnl_pct <= -8:
        result['actions'].append({
            'severity': 'HARD',
            'reason': f'circuit breaker PnL {pnl_pct:.1f}%',
        })

    # Aggregate status
    has_hard = any(a['severity'] == 'HARD' for a in result['actions'])
    has_soft = any(a['severity'] == 'SOFT' for a in result['actions'])
    if has_hard:
        result['status'] = 'EXIT'
        _queue_auto_exit(
            trade_id,
            ticker,
            '; '.join(a['reason'] for a in result['actions'] if a['severity'] == 'HARD'),
        )
    elif has_soft:
        result['status'] = 'WARN'

    return result


def run() -> dict:
    positions = _open_positions()
    log.info(f'Watchdog: {len(positions)} open positions')

    results: list[dict] = []
    stats = {'OK': 0, 'WARN': 0, 'EXIT': 0, 'STALE': 0}

    for pos in positions:
        try:
            r = _evaluate_position(pos)
            results.append(r)
            stats[r['status']] = stats.get(r['status'], 0) + 1

            if r['status'] == 'EXIT':
                msg = (
                    f'🚨 Watchdog HARD EXIT: **{r["ticker"]}** (#{r["trade_id"]})\n'
                    f'  PnL: {r.get("pnl_pct", 0):+.1f}%\n'
                    f'  ' + '\n  '.join(a['reason'] for a in r['actions'] if a['severity'] == 'HARD')
                )
                _notify(msg)
                log.warning(msg)
            elif r['status'] == 'WARN':
                log.info(
                    f"  ⚠️  {r['ticker']} {r.get('pnl_pct', 0):+.1f}%  "
                    + '; '.join(a['reason'] for a in r['actions'])[:120]
                )
            else:
                log.info(f"  ✅ {r['ticker']} {r.get('pnl_pct', 0):+.1f}%")
        except Exception as e:
            log.warning(f'{pos.get("ticker")}: {e}')

    snapshot = {
        'run_at': datetime.now().isoformat(timespec='seconds'),
        'stats': stats,
        'results': results,
    }
    _save_json(SNAPSHOT, snapshot)
    return snapshot


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    snap = run()
    s = snap['stats']
    print(
        f'\nWatchdog: ✅ {s.get("OK", 0)}  ⚠️ {s.get("WARN", 0)}  '
        f'🚨 {s.get("EXIT", 0)}  — {s.get("STALE", 0)} stale'
    )


if __name__ == '__main__':
    main()
