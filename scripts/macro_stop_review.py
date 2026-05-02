#!/usr/bin/env python3
"""
macro_stop_review.py — Phase 44n: LLM-Bewertung von Macro-Notifications.

Liest data/macro_position_notifications.jsonl (geschrieben vom ceo_daemon-
Reactor) und laesst Albert pro Notification entscheiden:

  - HOLD   : Stop bleibt unveraendert (Default bei Unsicherheit)
  - TRAIL  : Stop nachziehen via Chandelier (Brent steigt + EQNR long → trail)
  - LOCK   : Profit-Lock auf Breakeven (Bearish-Event + grueme Position)
  - EXIT   : Sofort-Exit-Empfehlung (These eindeutig invalidiert)
  - WIDEN  : Stop weiten (Position rot, aber These intakt — News ist Rauschen)

Output:
  - data/macro_stop_decisions.jsonl  (LLM-Entscheidungen + Audit-Trail)
  - Discord-Push wenn Reco != HOLD
  - KEINE Auto-Anwendung — Victor approved via Discord ('approve N')
    oder System wendet bei explizit aktivierter Auto-Approve an.

Run:
  python3 scripts/macro_stop_review.py            # echte Reviews
  python3 scripts/macro_stop_review.py --auto     # auto-apply
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
NOTIF = WS / 'data' / 'macro_position_notifications.jsonl'
DECISIONS = WS / 'data' / 'macro_stop_decisions.jsonl'
COMMODITY_CACHE = WS / 'data' / 'commodity_prices.json'


SYSTEM = """Du bist Albert, der TradeMind-CEO. Du bekommst eine Macro-Event-
Notification fuer eine offene Paper-Trade-Position. Bewerte:

1. Ist das Event bullish, bearish oder neutral fuer die These?
2. Wie steht die Position (gruen/rot, wie weit entfernt vom Stop)?
3. Was ist die richtige Aktion?

Optionen:
  HOLD   = Stop unveraendert lassen (Default bei Unsicherheit, kostet nichts)
  TRAIL  = Stop nach oben mit Chandelier (HWM - 2.5x ATR) nachziehen
  LOCK   = Profit-Lock auf Breakeven (Bearish-Event + Position gruen)
  EXIT   = Sofort-Exit (These eindeutig invalidiert)
  WIDEN  = Stop weiten (Position rot aber These intakt, News ist Rauschen)

Defaults:
- WENN UNSICHER → HOLD (Stop wurde mit voller Kontext-Analyse gesetzt)
- KEIN Tightening unter den aktuellen Stop ohne starken Grund
- NIE auf -2% vom Entry tightening (das war der EQNR-Bug — Mikro-Stops sind toedlich)

Antworte ausschliesslich mit JSON:
{"decision": "HOLD|TRAIL|LOCK|EXIT|WIDEN", "reason": "max 150 char", "confidence": 0.0-1.0}"""


def _commodity_context() -> str:
    """Brent/Gold/VIX/Copper Snapshot fuer LLM."""
    try:
        if COMMODITY_CACHE.exists():
            d = json.loads(COMMODITY_CACHE.read_text(encoding='utf-8'))
            p = d.get('prices', {})
            picks = []
            for sym in ['BZ=F', 'CL=F', 'GC=F', 'HG=F', '^VIX']:
                if sym in p:
                    pp = p[sym]
                    picks.append(f"{pp.get('name')}: {pp.get('spot')} "
                                  f"(24h {pp.get('chg_24h_pct',0):+.1f}%, 7d {pp.get('chg_7d_pct',0):+.1f}%)")
            return ' | '.join(picks)
    except Exception: pass
    return '(no commodity context)'


def _review_one(notif: dict, ctx: str) -> dict:
    prompt = (
        f"Notification:\n"
        f"  Ticker: {notif.get('ticker')}\n"
        f"  Strategy: {notif.get('strategy')}\n"
        f"  Event-Type: {notif.get('event_type')}\n"
        f"  Entry: {notif.get('entry_price')}, Live: {notif.get('live_price')}\n"
        f"  Unrealized: {notif.get('unrealized_pct',0):+.2f}%\n"
        f"  Current Stop: {notif.get('current_stop')} "
        f"({notif.get('stop_distance_pct',0):+.2f}% von Live)\n\n"
        f"Markt-Context:\n  {ctx}\n\n"
        f"Welche Aktion empfiehlst du? Antwort als JSON."
    )
    try:
        from core.llm_client import call_llm
        text, _ = call_llm(prompt, model_hint='sonnet', max_tokens=300, system=SYSTEM)
        import re
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            j = json.loads(m.group(0))
            return {
                'decision': str(j.get('decision','HOLD')).upper(),
                'reason': str(j.get('reason',''))[:150],
                'confidence': float(j.get('confidence', 0.5)),
                'source': 'llm',
            }
    except Exception as e:
        return {'decision': 'HOLD', 'reason': f'LLM-fail ({e})',
                'confidence': 0.0, 'source': 'fallback'}
    return {'decision': 'HOLD', 'reason': 'no parse', 'confidence': 0.0, 'source': 'fallback'}


def _apply_decision(decision: dict, notif: dict) -> dict:
    """Wendet die Entscheidung an. Schreibt nach paper_portfolio."""
    if not DB.exists():
        return {'applied': False, 'reason': 'no_db'}
    tid = notif.get('trade_id')
    if not tid:
        return {'applied': False, 'reason': 'no_tid'}
    act = decision.get('decision', 'HOLD')
    if act == 'HOLD':
        return {'applied': False, 'reason': 'HOLD-no-action'}

    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    r = c.execute(
        "SELECT entry_price, stop_price, shares FROM paper_portfolio WHERE id=?",
        (tid,)
    ).fetchone()
    if not r:
        c.close()
        return {'applied': False, 'reason': 'tid_not_found'}
    entry = float(r['entry_price'] or 0)
    stop = float(r['stop_price'] or 0)
    live = float(notif.get('live_price', 0) or 0)
    new_stop = stop  # Default

    if act == 'TRAIL':
        # Reuse stop_manager_daily Logik (vereinfacht hier)
        from stop_manager_daily import _vix_multiplier, _compute_atr_pct, _compute_hwm
        _, mult = _vix_multiplier()
        atr = _compute_atr_pct(c, notif['ticker'])
        hwm = _compute_hwm(c, notif['ticker'], notif.get('ts','')) or live
        if atr:
            new_stop = max(stop, hwm * (1 - mult * atr))
            new_stop = min(new_stop, live * 0.97)
    elif act == 'LOCK':
        new_stop = max(stop, entry)
    elif act == 'WIDEN':
        # Stop um 2% weiter (atemluft fuer Vola-Spike)
        new_stop = stop * 0.98
    elif act == 'EXIT':
        try:
            from paper_exit_manager import close_position
            close_position(tid, exit_reason='MACRO_LLM_EXIT')
            c.close()
            return {'applied': True, 'reason': 'EXIT executed', 'tid': tid}
        except Exception as e:
            c.close()
            return {'applied': False, 'reason': f'EXIT fail: {e}'}

    new_stop = round(new_stop, 4)
    if abs(new_stop - stop) < 0.01:
        c.close()
        return {'applied': False, 'reason': 'no-change'}

    c.execute(
        "UPDATE paper_portfolio SET stop_price=?, "
        "  notes=COALESCE(notes,'') || ? WHERE id=?",
        (new_stop,
         f' | LLM-{act} stop {stop:.2f}->{new_stop:.2f} ({decision.get("reason","")[:60]})',
         tid))
    c.commit()
    c.close()
    return {'applied': True, 'reason': f'{act}: {stop}→{new_stop}', 'tid': tid}


def review_pending(auto_apply: bool = False, hours_back: int = 6) -> dict:
    if not NOTIF.exists():
        return {'reviewed': 0, 'note': 'no_notifications'}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    notifs = []
    with open(NOTIF, encoding='utf-8') as f:
        for line in f:
            try:
                n = json.loads(line)
                ts = datetime.fromisoformat(n['ts'].replace('Z','+00:00'))
                if ts < cutoff:
                    continue
                notifs.append(n)
            except: pass

    # Dedupe pro (trade_id, event_type) — letzte Nachricht zaehlt
    by_key = {}
    for n in notifs:
        key = (n.get('trade_id'), n.get('event_type'))
        by_key[key] = n
    unique = list(by_key.values())

    ctx = _commodity_context()
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for n in unique:
        d = _review_one(n, ctx)
        applied = {'applied': False, 'reason': 'auto-apply disabled'}
        if auto_apply and d.get('decision') != 'HOLD' and d.get('confidence', 0) >= 0.6:
            applied = _apply_decision(d, n)
        rec = {'ts': datetime.now(timezone.utc).isoformat(),
                'notif': n, 'decision': d, 'applied': applied}
        with open(DECISIONS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.append(rec)

    # Discord-Push fuer non-HOLD Entscheidungen
    non_hold = [r for r in out if r['decision'].get('decision') != 'HOLD']
    if non_hold:
        try:
            from discord_dispatcher import send_alert, TIER_MEDIUM
            lines = ['🧠 **Macro-Stop-Review** (LLM-Empfehlungen):\n']
            for r in non_hold[:8]:
                d = r['decision']; n = r['notif']
                applied = ' ✅ applied' if r['applied'].get('applied') else ' ⏳ pending'
                lines.append(
                    f"  · `{n.get('ticker')}` ({n.get('event_type')}) → "
                    f"**{d['decision']}** (conf {d['confidence']:.0%}) — "
                    f"{d['reason'][:80]}{applied}"
                )
            send_alert('\n'.join(lines), tier=TIER_MEDIUM,
                       category='macro_stop_review',
                       dedupe_key=f'macro_review_{datetime.now().strftime("%Y%m%d_%H")}')
        except Exception: pass

    return {'reviewed': len(unique),
            'by_decision': {d: sum(1 for r in out if r['decision'].get('decision')==d)
                              for d in ('HOLD','TRAIL','LOCK','EXIT','WIDEN')},
            'records': out}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--auto', action='store_true', help='Auto-apply non-HOLD bei conf>=0.6')
    ap.add_argument('--hours', type=int, default=6)
    args = ap.parse_args()
    r = review_pending(auto_apply=args.auto, hours_back=args.hours)
    print(f'═══ Macro-Stop-Review ═══')
    print(f'  Reviewed: {r.get("reviewed", 0)}')
    print(f'  By decision: {r.get("by_decision", {})}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
