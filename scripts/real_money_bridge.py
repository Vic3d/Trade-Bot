#!/usr/bin/env python3
"""
real_money_bridge.py — Phase 45i (Sprint 8): Brueck zum echten Broker.

PRE-PRODUCTION-MODE: Wenn enabled, schreibt Albert Trade-Vorschlaege
nach data/real_money_pending.jsonl statt direkt zu paper_portfolio.
Victor approved per Discord, dann erst geht es zu Trade Republic
(via API wenn verfuegbar, sonst manueller Trigger).

Modes:
  PAPER_ONLY   (default)    — alles bleibt Paper, Bridge ist inaktiv
  PRE_PRODUCTION            — Trade-Vorschlaege landen in Pending-Queue
  GRADUAL_ROLLOUT           — definierter Anteil (1-25%) geht echt
  FULL                      — alle Trades echt (NICHT empfohlen ohne extensive Live-Tests)

Konfiguration: data/real_money_config.json
{
  "mode": "PAPER_ONLY",
  "rollout_pct": 0,
  "max_real_money_per_trade_eur": 500,
  "max_real_money_per_day_eur": 2000,
  "approved_strategies": [],
  "broker_api": "trade_republic"  // (api-stub)
}

Output:
  data/real_money_pending.jsonl   pending Trades
  data/real_money_executed.jsonl  echte Trades
  data/real_money_rejected.jsonl  abgelehnt
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
CONFIG = WS / 'data' / 'real_money_config.json'
PENDING = WS / 'data' / 'real_money_pending.jsonl'
EXECUTED = WS / 'data' / 'real_money_executed.jsonl'
REJECTED = WS / 'data' / 'real_money_rejected.jsonl'


def _default_config() -> dict:
    return {
        'mode': 'PAPER_ONLY',
        'rollout_pct': 0,
        'max_real_money_per_trade_eur': 500,
        'max_real_money_per_day_eur': 2000,
        'approved_strategies': [],
        'broker_api': None,  # 'trade_republic_unofficial' wenn aktiviert
        'last_changed': datetime.now(timezone.utc).isoformat(),
    }


def get_config() -> dict:
    if CONFIG.exists():
        try: return json.loads(CONFIG.read_text(encoding='utf-8'))
        except Exception: pass
    cfg = _default_config()
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding='utf-8')


def submit_for_real_money_approval(trade: dict) -> dict:
    """Speichert Trade-Vorschlag in Pending-Queue. Discord-Push fuer Victor."""
    cfg = get_config()
    if cfg['mode'] == 'PAPER_ONLY':
        return {'success': False, 'reason': 'PAPER_ONLY mode',
                'config': cfg['mode']}

    trade['ts_submitted'] = datetime.now(timezone.utc).isoformat()
    trade['status'] = 'PENDING_APPROVAL'

    # Risk-Checks
    if trade.get('position_eur', 0) > cfg['max_real_money_per_trade_eur']:
        trade['status'] = 'REJECTED'
        trade['rejection_reason'] = f'exceeds max_per_trade {cfg["max_real_money_per_trade_eur"]}EUR'
        REJECTED.parent.mkdir(parents=True, exist_ok=True)
        with open(REJECTED, 'a', encoding='utf-8') as f:
            f.write(json.dumps(trade, ensure_ascii=False) + '\n')
        return {'success': False, 'reason': trade['rejection_reason']}

    if cfg['approved_strategies'] and trade.get('strategy') not in cfg['approved_strategies']:
        trade['status'] = 'REJECTED'
        trade['rejection_reason'] = f'strategy {trade.get("strategy")} not in approved list'
        with open(REJECTED, 'a', encoding='utf-8') as f:
            f.write(json.dumps(trade, ensure_ascii=False) + '\n')
        return {'success': False, 'reason': trade['rejection_reason']}

    PENDING.parent.mkdir(parents=True, exist_ok=True)
    with open(PENDING, 'a', encoding='utf-8') as f:
        f.write(json.dumps(trade, ensure_ascii=False) + '\n')

    # Discord-Push
    try:
        from discord_dispatcher import send_alert, TIER_HIGH
        msg = (f'💰 **REAL-MONEY-APPROVAL NEEDED**\n'
                f'Trade: {trade.get("ticker")} ({trade.get("strategy")})\n'
                f'Entry: {trade.get("entry_price")} | Stop: {trade.get("stop_price")} | '
                f'Target: {trade.get("target_price")}\n'
                f'Position: {trade.get("position_eur")}EUR\n'
                f'Reply: `approve real {trade.get("ticker")}` oder `reject real {trade.get("ticker")}`')
        send_alert(msg, tier=TIER_HIGH, category='real_money_approval')
    except Exception: pass

    return {'success': True, 'status': 'PENDING_APPROVAL', 'trade': trade}


def execute_approved_trade(trade: dict) -> dict:
    """Wuerde echten Broker-Call machen. Aktuell nur Logging."""
    cfg = get_config()
    if cfg.get('broker_api'):
        # TODO: real broker integration
        result = {'broker': cfg['broker_api'], 'simulated': True,
                  'reason': 'broker_integration_not_implemented'}
    else:
        result = {'broker': None, 'simulated': True,
                  'reason': 'no broker configured'}

    trade['ts_executed'] = datetime.now(timezone.utc).isoformat()
    trade['execution_result'] = result
    EXECUTED.parent.mkdir(parents=True, exist_ok=True)
    with open(EXECUTED, 'a', encoding='utf-8') as f:
        f.write(json.dumps(trade, ensure_ascii=False) + '\n')
    return {'success': True, 'execution': result}


def main():
    cfg = get_config()
    print(f'═══ Real-Money-Bridge ═══')
    print(f'  Mode: {cfg["mode"]}')
    print(f'  Rollout-Pct: {cfg["rollout_pct"]}%')
    print(f'  Max per Trade: {cfg["max_real_money_per_trade_eur"]}EUR')
    print(f'  Max per Day:   {cfg["max_real_money_per_day_eur"]}EUR')
    print(f'  Approved Strategies: {cfg["approved_strategies"]}')
    print(f'  Broker API: {cfg["broker_api"]}')
    print(f'\n  Status: {"PAPER ONLY (kein Real-Money)" if cfg["mode"]=="PAPER_ONLY" else "ACTIVE"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
