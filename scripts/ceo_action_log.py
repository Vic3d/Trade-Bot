#!/usr/bin/env python3
"""
ceo_action_log.py — Phase 44ab: Albert ENTSCHEIDET autonom + meldet post-fact.

User-Korrektur (Victor 03.05): "Albert soll diese Fragen selbst autonom
beantworten. Dafür ist der CEO da."

Ersetzt das frühere ceo_action_requests-Konzept (Fragen an Victor) durch:

  AUTONOME DECISIONS + INFORMATIVES LOG

Pipeline:
1. Sammle gleichen Kontext wie action_requests (Capability-Audit, Self-Research,
   Lessons, Hypothesen, Strategy-Performance, Open-Positions)
2. LLM identifiziert was zu TUN ist (NICHT was zu fragen ist)
3. Pro Action: führt sie autonom aus (apply_action) oder markiert "needs_human"
   wenn sie wirklich strategischer Pivot ist
4. Discord-Push: post-fact Bericht mit ausgeführten Actions + Begründung
5. Victor kann via 'rollback Q1' eine Action zurückrollen — Default: alles bleibt

Action-Types die Albert AUTONOM ausführen darf:
- strategy_status_change (active → paused/retired)
- stop_price_fix (Bug-Reparatur, z.B. Stop auf entry zurück)
- conviction_recalibrate (Auto-Trigger ceo_calibration_tracker)
- signal_tracker_disable (Tool abschalten)
- portfolio_rebalance_bias (Hunter-Sektor-Hint setzen)
- position_close (nur bei klarer Bug-Lage, NICHT bei strategischem Trade-Exit)

Action-Types die NUR ALS DECISION_NEEDED markiert werden (echter Pivot):
- mission_change
- new_strategy_class (komplett neuer Strategie-Typ)
- real_money_activation
- system_architecture_change

Run: python3 scripts/ceo_action_log.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
ACTIONS_LOG = WS / 'data' / 'ceo_action_log.jsonl'
PENDING = WS / 'data' / 'ceo_action_pending.json'  # fuer Rollback-Window


SYSTEM = """Du bist Albert, der TradeMind-CEO. Du sitzt 24/7, leitest den Laden.

WICHTIG: Du STELLST KEINE FRAGEN. Du ENTSCHEIDEST. Victor wird informiert
ueber das was du getan hast — er kann widerrufen, aber er muss nicht
zustimmen damit du handelst.

Deine Mission: Werde der beste autonome Trader-Bot der Welt.

Heute morgen: identifiziere konkrete Aktionen die du AUTONOM ausfuehrst.
Pro Aktion:
- Was du tust
- WARUM (Daten + Begruendung)
- AUSFUEHRUNG (welcher action_type, welche params)

Action-Types AUTONOM:
- 'strategy_status' params {strategy_id, new_status: paused|retired|watching|active}
- 'stop_fix' params {trade_id, new_stop, reason}
- 'recalibrate' params {target: conviction|brier}
- 'tool_disable' params {tool_name, reason}
- 'sector_bias' params {sectors_to_prefer, sectors_to_avoid}

Action-Types DECISION_NEEDED (nicht autonom, nur als Frage markieren):
- 'mission_change'
- 'new_strategy_class'
- 'real_money_activation'

Trump-Signal-Bewertung (User-Direktive 03.05):
- Trump-Peace-Signale sind TRAEGE — kein realer Deal sichtbar
- Hormuz-bleibt-zu-These ist Default
- Keine Aktion auf 'Peace-Signal' Basis allein

Antworte als JSON:
{
  "summary": "max 200 char",
  "actions": [
    {
      "id": "A1",
      "type": "strategy_status|stop_fix|recalibrate|tool_disable|sector_bias|decision_needed",
      "topic": "kurzer Titel",
      "what": "was getan wird",
      "why": "Begruendung mit Daten",
      "params": {...},
      "rollback_window_h": 24
    }
  ]
}"""


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_recent_audits() -> dict:
    """Sammelt letzten Audits/Logs als Kontext."""
    out = {}
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    cap_dir = WS / 'memory' / 'ceo-capability-audits'
    for d in (today, yesterday):
        f = cap_dir / f'{d}.md'
        if f.exists():
            out[f'capability'] = f.read_text(encoding='utf-8')[:2000]
            break

    sr_dir = WS / 'memory' / 'ceo-daily-research'
    for d in (today, yesterday):
        f = sr_dir / f'{d}.md'
        if f.exists():
            out[f'self_research'] = f.read_text(encoding='utf-8')[:2500]
            break

    hf = WS / 'data' / 'ceo_hypotheses.json'
    if hf.exists():
        try:
            h = json.loads(hf.read_text(encoding='utf-8'))
            validated = [{'fp': fp, **v} for fp, v in h.get('hypotheses', {}).items()
                         if v.get('status') == 'VALIDATED']
            out['validated_hypotheses'] = validated[:5]
        except Exception: pass

    pl = WS / 'data' / 'permanent_lessons.jsonl'
    if pl.exists():
        try:
            lessons = []
            with open(pl, encoding='utf-8') as f:
                for line in f:
                    try: lessons.append(json.loads(line))
                    except: pass
            out['permanent_lessons'] = lessons[-5:]
        except Exception: pass

    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            opens = c.execute(
                "SELECT id, ticker, strategy, entry_price, stop_price, target_price "
                "FROM paper_portfolio WHERE status='OPEN'"
            ).fetchall()
            out['open_positions'] = [dict(r) for r in opens]
            c.close()
        except Exception: pass

    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT strategy, COUNT(*) as n, SUM(pnl_eur) as pnl "
                "FROM paper_portfolio WHERE status IN ('WIN','LOSS','CLOSED') "
                "GROUP BY strategy HAVING n >= 3 ORDER BY pnl DESC"
            ).fetchall()
            out['strategy_perf'] = [dict(r) for r in rows][:15]
            c.close()
        except Exception: pass

    # Phase 45b (Sprint 1): Backtest-Insights als Strategy-Edge-Datenquelle
    bt_file = WS / 'data' / 'backtest_results.json'
    if bt_file.exists():
        try:
            bt = json.loads(bt_file.read_text(encoding='utf-8'))
            bt_insights = []
            for sid, payload in bt.items():
                if not isinstance(payload, dict) or 'overall' not in payload: continue
                o = payload['overall']
                bt_insights.append({
                    'strategy': sid, 'sharpe': o.get('sharpe_ratio'),
                    'wr_pct': round((o.get('win_rate', 0) or 0) * 100, 1),
                    'pf': o.get('profit_factor'),
                    'max_dd_pct': o.get('max_drawdown_pct'),
                    'n': o.get('total_trades'),
                    'verdict': payload.get('verdict','?')
                })
            # Top 5 + Bottom 3
            bt_insights.sort(key=lambda x: -(x.get('sharpe') or 0))
            out['backtest_top5'] = bt_insights[:5]
            out['backtest_bottom3'] = bt_insights[-3:]
        except Exception: pass

    # Quant-Metrics Mission-Status
    qm_file = WS / 'data' / 'quant_metrics.json'
    if qm_file.exists():
        try:
            qm = json.loads(qm_file.read_text(encoding='utf-8'))
            out['mission_kpis'] = {
                '30d': qm.get('last_30d', {}),
                'all_time': qm.get('all_time', {}),
                'verdict_30d': qm.get('mission_verdict_30d'),
                'verdict_all_time': qm.get('mission_verdict_all_time'),
            }
        except Exception: pass

    return out


def _apply_strategy_status(params: dict) -> dict:
    sid = params.get('strategy_id')
    new_status = params.get('new_status')
    if not sid or new_status not in ('paused','retired','watching','active'):
        return {'ok': False, 'reason': 'bad_params'}
    sf = WS / 'data' / 'strategies.json'
    if not sf.exists(): return {'ok': False, 'reason': 'no_strategies_file'}
    strats = json.loads(sf.read_text(encoding='utf-8'))
    if sid not in strats: return {'ok': False, 'reason': f'unknown_sid:{sid}'}
    old = strats[sid].get('status', '?')
    strats[sid]['status'] = new_status
    strats[sid]['_ceo_action_at'] = _now()
    strats[sid]['_ceo_action_reason'] = params.get('reason','')[:200]
    sf.write_text(json.dumps(strats, indent=2, ensure_ascii=False), encoding='utf-8')
    return {'ok': True, 'old': old, 'new': new_status}


def _apply_stop_fix(params: dict) -> dict:
    tid = params.get('trade_id')
    new_stop = params.get('new_stop')
    if not tid or new_stop is None:
        return {'ok': False, 'reason': 'bad_params'}
    if not DB.exists(): return {'ok': False, 'reason': 'no_db'}
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT id, ticker, stop_price, status FROM paper_portfolio WHERE id=?",
                      (tid,)).fetchone()
        if not r: return {'ok': False, 'reason': 'no_trade'}
        if r['status'] != 'OPEN':
            return {'ok': False, 'reason': f'not_open:{r["status"]}'}
        old = r['stop_price']
        c.execute("UPDATE paper_portfolio SET stop_price=?, "
                  "notes=COALESCE(notes,'')||? WHERE id=?",
                  (new_stop,
                   f' | CEO-ACTION stop {old:.2f}->{new_stop:.2f}: {params.get("reason","")[:80]}',
                   tid))
        c.commit(); c.close()
        return {'ok': True, 'ticker': r['ticker'], 'old_stop': old, 'new_stop': new_stop}
    except Exception as e: return {'ok': False, 'reason': str(e)}


def _apply_action(action: dict) -> dict:
    t = action.get('type','')
    p = action.get('params', {})
    if t == 'strategy_status': return _apply_strategy_status(p)
    if t == 'stop_fix': return _apply_stop_fix(p)
    if t == 'recalibrate':
        # Trigger conviction_calibration als subprocess
        try:
            import subprocess
            subprocess.Popen(['python3', str(WS/'scripts'/'conviction_calibration.py')],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {'ok': True, 'note': 'recalibration triggered'}
        except Exception as e: return {'ok': False, 'reason': str(e)}
    if t == 'tool_disable':
        # Schreibt in data/disabled_tools.json (Tools koennen das lesen)
        df = WS / 'data' / 'disabled_tools.json'
        d = json.loads(df.read_text(encoding='utf-8')) if df.exists() else {}
        d[p.get('tool_name','?')] = {'disabled_at': _now(),
                                       'reason': p.get('reason','')[:200]}
        df.write_text(json.dumps(d, indent=2), encoding='utf-8')
        return {'ok': True, 'tool': p.get('tool_name')}
    if t == 'sector_bias':
        df = WS / 'data' / 'hunter_sector_bias.json'
        df.write_text(json.dumps({
            'updated_at': _now(),
            'prefer': p.get('sectors_to_prefer', []),
            'avoid': p.get('sectors_to_avoid', []),
        }, indent=2), encoding='utf-8')
        return {'ok': True, 'bias_set': p}
    if t == 'decision_needed':
        return {'ok': True, 'decision_pending': True}  # nur loggen, nicht ausführen
    return {'ok': False, 'reason': f'unknown_type:{t}'}


def run() -> dict:
    ctx = _load_recent_audits()
    if not ctx:
        return {'ts': _now(), 'note': 'no_context'}

    prompt = (
        f"Heute: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Kontext:\n{json.dumps(ctx, indent=2, default=str, ensure_ascii=False)[:6000]}\n\n"
        f"Welche AUTONOMEN AKTIONEN fuehrst du heute aus?"
    )

    actions = []
    summary = ''
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=1800,
                            system=SYSTEM, audit_context='ceo_action_log')
        import re
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            j = json.loads(m.group(0))
            actions = j.get('actions', [])
            summary = j.get('summary', '')
    except Exception as e:
        print(f'[action_log] LLM-fail: {e}')

    # Apply each action autonomously
    # Phase 45t: today_id mit Stunde — Albert laeuft 3x pro Tag,
    # damit Indizes nicht kollidieren und jeder Run eigene Discord-Push
    # hat (dedupe_key wird pro Run eindeutig).
    today_id = datetime.now().strftime('%Y%m%d_%H%M')
    executed = []
    for i, a in enumerate(actions):
        a['unique_id'] = f'{today_id}_A{i+1}'
        a['executed_at'] = _now()
        result = _apply_action(a)
        a['result'] = result
        a['rollback_available_until'] = (datetime.now(timezone.utc) +
                                         timedelta(hours=a.get('rollback_window_h',24))).isoformat()
        executed.append(a)

    # Audit-Log
    ACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ACTIONS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), 'summary': summary,
                              'actions': executed}, ensure_ascii=False) + '\n')

    # Pending fuer Rollback-Window
    try:
        existing = json.loads(PENDING.read_text(encoding='utf-8')) if PENDING.exists() else []
    except Exception: existing = []
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    existing = [x for x in existing if x.get('executed_at','') >= cutoff_ts]
    existing.extend(executed)
    PENDING.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')

    # Discord post-fact
    if executed:
        try:
            from discord_dispatcher import send_alert, TIER_HIGH
            lines = [f'🤖 **Albert hat heute autonom entschieden** ({len(executed)} Aktionen):']
            if summary:
                lines.append(f'_{summary}_\n')
            for a in executed:
                ok = a.get('result',{}).get('ok')
                icon = '✅' if ok else '❌'
                lines.append(f"\n{icon} **{a.get('unique_id','?')}** [{a.get('type','?')}]: {a.get('topic','?')}")
                lines.append(f"   → {a.get('what','')[:140]}")
                lines.append(f"   📊 {a.get('why','')[:140]}")
                if not ok and a.get('type') == 'decision_needed':
                    lines.append(f"   ⚠️ **DECISION NEEDED** (kein Auto-Apply): {a.get('result',{})}")
            lines.append(f"\n_Rollback (24h): `rollback {today_id}_A1` etc._")
            send_alert('\n'.join(lines)[:1900], tier=TIER_HIGH,
                        category='ceo_action_request',  # nutzt CRITICAL-Whitelist
                        dedupe_key=f'ceo_actions_{today_id}')
        except Exception as e: print(f'discord push err: {e}')

    return {'ts': _now(), 'n_actions': len(executed),
            'summary': summary,
            'by_type': {t: sum(1 for a in executed if a.get('type')==t)
                          for t in ('strategy_status','stop_fix','recalibrate',
                                    'tool_disable','sector_bias','decision_needed')}}


def main() -> int:
    r = run()
    print(f'═══ CEO Action-Log @ {r["ts"][:16]} ═══')
    print(f'  Actions: {r.get("n_actions",0)}')
    print(f'  By type: {r.get("by_type",{})}')
    print(f'  Summary: {r.get("summary","")[:200]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
