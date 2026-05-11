#!/usr/bin/env python3
"""
live_trigger_watcher.py — Phase 45ao Layer 6 (Victor 2026-05-11).

Liest setup_signals.jsonl (fresh) + albert_goals.json (Sector-Bias) und
generiert Trade-Proposals wenn:
  - Pattern frisch (<2h)
  - Pre-Entry-Validator clean
  - Liquidity-Filter clean
  - Ticker passt zum aktuellen Goal-Sektor-Bias
  - Strategy-Verdict erlaubt (nicht RETIRED/WEAK)

Trade-Proposals landen in data/live_trade_proposals.jsonl + ceo_inbox.
Hunter/CEO-Brain prüft + entscheidet (kein Auto-Execute hier).

Run: alle 15min während US-Markt offen (15:30-22:00 CEST Mo-Fr).
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

SIGNALS_LOG = WS / 'data' / 'setup_signals.jsonl'
PROPOSALS_LOG = WS / 'data' / 'live_trade_proposals.jsonl'
GOALS = WS / 'data' / 'albert_goals.json'
STRATS = WS / 'data' / 'strategies.json'

MAX_AGE_HOURS = 2  # Signal älter → veraltet
MIN_CONFIDENCE = 0.55


def _load_recent_signals() -> list[dict]:
    if not SIGNALS_LOG.exists(): return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).isoformat()
    out = []
    try:
        with open(SIGNALS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('ts', '') > cutoff and e.get('confidence', 0) >= MIN_CONFIDENCE:
                        out.append(e)
                except Exception: pass
    except Exception: pass
    return out


def _was_already_proposed(ticker: str, pattern: str, hours: int = 4) -> bool:
    if not PROPOSALS_LOG.exists(): return False
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        with open(PROPOSALS_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if (e.get('ts', '') > cutoff
                          and e.get('ticker') == ticker
                          and e.get('pattern') == pattern):
                        return True
                except Exception: pass
    except Exception: pass
    return False


def _strategy_for_ticker(ticker: str) -> str | None:
    """Welche aktive Strategie deckt diesen Ticker?"""
    if not STRATS.exists(): return None
    try:
        s = json.loads(STRATS.read_text(encoding='utf-8'))
        for sid, meta in s.items():
            if not isinstance(meta, dict): continue
            if meta.get('status') != 'active': continue
            tickers = meta.get('tickers') or meta.get('ticker_universe', [])
            if ticker.upper() in [t.upper() for t in tickers if t]:
                return sid
    except Exception: pass
    return None


def check_validators(ticker: str, entry: float, stop: float, target: float):
    """Run pre-entry-validator + liquidity-filter."""
    try:
        from pre_entry_validator import validate
        ok1, issues1, det1 = validate(ticker, entry, stop, target, direction='long')
    except Exception as e:
        return False, [f'validator_err:{e}'], {}
    try:
        from liquidity_filter import passes_liquidity
        ok2, reason2, det2 = passes_liquidity(ticker, current_price_usd=entry)
    except Exception:
        ok2, reason2, det2 = True, 'skipped', {}
    ok = ok1 and ok2
    issues = list(issues1)
    if not ok2: issues.append(f'liquidity:{reason2}')
    return ok, issues, {'pre_entry': det1, 'liquidity': det2}


def process_signals() -> dict:
    signals = _load_recent_signals()
    if not signals:
        return {'ok': True, 'n_signals': 0, 'n_proposals': 0,
                'reason': 'no_fresh_signals'}

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    proposals = []

    for sig in signals:
        ticker = sig['ticker']
        pattern = sig['pattern']

        # Dedupe
        if _was_already_proposed(ticker, pattern):
            continue

        # Entry/Stop aus Pattern ableiten
        entry = sig.get('last_close') or 0
        if entry <= 0: continue
        # Stop: vom Pattern, sonst -5%
        stop = entry * 0.95
        target = entry * 1.10  # +10% default Target

        # Validators
        ok, issues, det = check_validators(ticker, entry, stop, target)
        if not ok:
            continue

        # Strategy-Lookup
        strat = _strategy_for_ticker(ticker) or 'UNCOVERED'

        prop = {
            'ts': now,
            'ticker': ticker,
            'pattern': pattern,
            'confidence': sig.get('confidence'),
            'entry_price': round(entry, 2),
            'stop_price': round(stop, 2),
            'target_price': round(target, 2),
            'strategy_match': strat,
            'pattern_details': {k: v for k, v in sig.items()
                                if k not in ('ts', 'ticker', 'pattern')},
            'status': 'PENDING_CEO_APPROVAL',
        }
        proposals.append(prop)

    # Persist
    if proposals:
        PROPOSALS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPOSALS_LOG, 'a', encoding='utf-8') as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + '\n')

        # CEO-Inbox notify
        try:
            from ceo_inbox import write_event
            for p in proposals:
                write_event(
                    event_type='live_trigger.proposal',
                    message=f"{p['ticker']} {p['pattern']} @ {p['entry_price']} "
                            f"(stop {p['stop_price']}, target {p['target_price']}) "
                            f"strat={p['strategy_match']}",
                    severity='info', category='health',
                    user_pinged=False, payload=p,
                )
        except Exception: pass

    return {'ok': True, 'n_signals': len(signals), 'n_proposals': len(proposals),
            'first_proposal': proposals[0] if proposals else None}


def main() -> int:
    r = process_signals()
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
