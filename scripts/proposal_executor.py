#!/usr/bin/env python3
"""
Proposal Executor — Phase 15
=============================

Reads data/proposals.json, filters by trigger conditions, and calls
paper_trade_engine.execute_paper_entry() directly (honoring all guards).

A proposal is executable iff:
  - status == 'active' (or unset)
  - trigger condition met (price threshold, event date)
  - deep_dive_verdicts[ticker].verdict == 'KAUFEN' (fresh)
  - conviction score >= 45 at execution time
  - entry_gate passes

Dry-run mode (config.autonomy_mode=SHADOW) logs decision without trading.

Runs every 30 min during entry window (17-22h CET).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger('proposal_executor')

WS = Path(os.getenv('TRADEMIND_HOME', '/opt/trademind'))
sys.path.insert(0, str(WS / 'scripts'))

DATA = WS / 'data'
DB = DATA / 'trading.db'
PROPOSALS = DATA / 'proposals.json'
VERDICTS = DATA / 'deep_dive_verdicts.json'
CONFIG = DATA / 'autonomy_config.json'
EXECUTOR_LOG = DATA / 'proposal_executor_log.json'


def _load(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def _save(p: Path, data) -> None:
    try:
        p.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception as e:
        log.warning(f'{p.name}: {e}')


def _autonomy_mode() -> str:
    """SHADOW | LIVE — SHADOW logs but doesn't execute."""
    cfg = _load(CONFIG, {})
    return str(cfg.get('mode', 'SHADOW')).upper()


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


def _verdict_ok(ticker: str) -> tuple[bool, str]:
    verdicts = _load(VERDICTS, {})
    v = verdicts.get(ticker.upper(), {})
    if not v:
        return False, 'no verdict'
    if v.get('verdict') != 'KAUFEN':
        return False, f"verdict={v.get('verdict')}"
    try:
        age = (datetime.now() - datetime.fromisoformat(v['date'])).days
        if age > 14:
            return False, f'verdict {age}d old'
    except Exception:
        pass
    return True, 'ok'


def _trigger_met(proposal: dict) -> tuple[bool, str]:
    """Checks if proposal trigger condition is satisfied."""
    ticker = proposal.get('ticker', '')
    trigger = proposal.get('trigger') or ''

    # Proposals without explicit trigger: always ready (use entry_price)
    if not trigger:
        return True, 'no trigger — ready'

    price = _latest_price(ticker)
    if price is None:
        return False, 'no price data'

    # Simple numeric trigger parsing: "< 158" or "Alert@158$" etc.
    m = re.search(r'[<>]=?\s*([\d.]+)', str(trigger))
    if m:
        threshold = float(m.group(1))
        if '<' in trigger and price <= threshold:
            return True, f'{price:.2f} <= {threshold}'
        if '>' in trigger and price >= threshold:
            return True, f'{price:.2f} >= {threshold}'
        return False, f'not met: {price:.2f} vs {trigger}'

    # Text-only trigger (e.g. "Q1_EARNINGS_BEAT") → skip auto-exec
    return False, f'manual trigger: {trigger}'


def _log_decision(entry: dict) -> None:
    hist = _load(EXECUTOR_LOG, [])
    entry['ts'] = datetime.now().isoformat(timespec='seconds')
    hist.append(entry)
    _save(EXECUTOR_LOG, hist[-500:])


def _notify(msg: str) -> None:
    try:
        from discord_sender import send
        send(msg[:1900])
    except Exception:
        pass


def _execute(proposal: dict, mode: str) -> dict:
    ticker = proposal['ticker']
    strategy = proposal.get('strategy', 'PT')
    entry = float(proposal.get('entry_price') or 0)
    stop = float(proposal.get('stop') or 0)
    target = float(proposal.get('target_1') or proposal.get('target') or 0)
    thesis = proposal.get('thesis', '')

    if mode == 'SHADOW':
        decision = {
            'mode': 'SHADOW',
            'ticker': ticker,
            'action': 'would_execute',
            'entry': entry, 'stop': stop, 'target': target,
            'strategy': strategy,
        }
        _log_decision(decision)
        log.info(f'[SHADOW] would execute {ticker} {strategy} @ {entry}')
        return {'success': False, 'shadow': True, 'message': 'shadow mode — not executed'}

    try:
        from execution.paper_trade_engine import execute_paper_entry
    except Exception as e:
        return {'success': False, 'message': f'import failed: {e}'}

    result = execute_paper_entry(
        ticker=ticker,
        strategy=strategy,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        thesis=thesis,
        source='auto_proposal',
    )
    _log_decision({
        'mode': 'LIVE',
        'ticker': ticker,
        'success': result.get('success'),
        'trade_id': result.get('trade_id'),
        'message': result.get('message', '')[:200],
        'blocked_by': result.get('blocked_by'),
    })
    return result


def run() -> dict:
    proposals = _load(PROPOSALS, [])
    mode = _autonomy_mode()
    log.info(f'Proposal Executor: {len(proposals)} proposals, mode={mode}')

    stats = {'considered': 0, 'executed': 0, 'shadowed': 0, 'skipped': 0, 'failed': 0}
    updated: list[dict] = []

    for p in proposals:
        if not isinstance(p, dict):
            updated.append(p)
            continue
        if p.get('status', 'active') in ('closed', 'executed', 'cancelled'):
            updated.append(p)
            continue

        stats['considered'] += 1
        ticker = p.get('ticker', '')

        # Gate 1: verdict
        ok, reason = _verdict_ok(ticker)
        if not ok:
            log.info(f'  {ticker}: skip — verdict {reason}')
            stats['skipped'] += 1
            updated.append(p)
            continue

        # Gate 2: trigger condition
        ok, reason = _trigger_met(p)
        if not ok:
            log.info(f'  {ticker}: skip — trigger {reason}')
            stats['skipped'] += 1
            updated.append(p)
            continue

        log.info(f'  {ticker}: trigger met ({reason}) → attempting execution')
        result = _execute(p, mode)

        if result.get('shadow'):
            stats['shadowed'] += 1
            updated.append(p)
        elif result.get('success'):
            stats['executed'] += 1
            p['status'] = 'executed'
            p['executed_at'] = datetime.now().isoformat(timespec='seconds')
            p['trade_id'] = result.get('trade_id')
            _notify(
                f'✅ Proposal executed: {ticker} #{result.get("trade_id")} '
                f'({p.get("strategy")})'
            )
            updated.append(p)
        else:
            stats['failed'] += 1
            log.warning(
                f"  {ticker}: block — {result.get('blocked_by') or result.get('message', '')[:100]}"
            )
            updated.append(p)

    _save(PROPOSALS, updated)
    return stats


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    stats = run()
    print(f'\nProposal Executor: {stats}')


if __name__ == '__main__':
    main()
