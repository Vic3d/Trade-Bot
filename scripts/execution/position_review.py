#!/usr/bin/env python3
"""
Active Position Review — Albert als echter Portfolio-Manager
============================================================
Läuft täglich 16:45 (nach US-Open, vor EU-Close).

PHILOSOPHIE (Victor, 29.03.2026):
  Paper Labs ist Training für echtes autonomes Trading.
  Albert setzt eigene Stops — nicht passiv warten bis Kurs den Stop trifft.
  Täglich aktiv fragen: "Läuft diese These noch? Oder ist das gestorben?"

Review-Dimensionen pro Position:
  1. PREIS-MOMENTUM: Bewegt sich der Trade in die richtige Richtung?
  2. THESE-INTEGRITÄT: Hat sich etwas verändert das die These invalidiert?
  3. OPPORTUNITY COST: Ist das Kapital hier besser als in einem neuen Setup?
  4. STOP-MANAGEMENT: Muss der Stop angepasst werden (enger/weiter)?

Exit-Entscheidung ist ALBERTS VERANTWORTUNG — nicht des Stop-Loss Preises.

Albert 🎩 | v1.0 | 29.03.2026
"""

import sqlite3, json, sys, urllib.request, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo('Europe/Berlin')

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    # scripts/subdir/ -> go up 2 levels to reach WS root
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB  = WS / 'data' / 'trading.db'
sys.path.insert(0, str(WS / 'scripts' / 'execution'))
sys.path.insert(0, str(WS / 'scripts' / 'intelligence'))

ALERT_QUEUE = WS / 'memory' / 'alert-queue.json'


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def yahoo(ticker: str) -> dict | None:
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        res  = data['chart']['result'][0]
        meta = res['meta']
        q    = res['indicators']['quote'][0]
        closes  = [c for c in (q.get('close')  or []) if c]
        volumes = [v for v in (q.get('volume') or []) if v]
        price   = meta.get('regularMarketPrice', closes[-1] if closes else 0)
        prev    = meta.get('chartPreviousClose', closes[-2] if len(closes) > 1 else price)
        high52  = meta.get('fiftyTwoWeekHigh')
        low52   = meta.get('fiftyTwoWeekLow')
        avg_vol = sum(volumes[-10:]) / min(len(volumes), 10) if volumes else 0
        curr_vol = volumes[-1] if volumes else 0
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
        return {
            'price': price,
            'change': (price - prev) / prev * 100 if prev else 0,
            'closes': closes,
            'high52': high52,
            'low52': low52,
            'vol_ratio': vol_ratio,
        }
    except Exception:
        return None


def _rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    ag, al = sum(gains) / period, sum(losses) / period
    return round(100 - 100 / (1 + ag / al), 1) if al > 0 else 100.0


def _ema(prices: list, period: int) -> float | None:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 2)


def get_vix() -> float:
    conn = get_db()
    r = conn.execute(
        "SELECT value FROM macro_daily WHERE indicator='VIX' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return r['value'] if r else 25.0


def close_position(conn, row_id: int, price: float, exit_type: str,
                   entry: float, shares: float, fees: float) -> float:
    pnl = (price - entry) * shares - fees
    pnl_pct = (price - entry) / entry * 100
    conn.execute("""
        UPDATE paper_portfolio
        SET status=?, close_price=?, close_date=datetime('now'),
            pnl_eur=?, pnl_pct=?, notes = notes || ?, exit_type=?
        WHERE id=?
    """, (
        'WIN' if pnl > 0 else ('LOSS' if pnl < 0 else 'CLOSED'),
        round(price, 2),
        round(pnl, 2), round(pnl_pct, 2),
        f' [REVIEW_EXIT:{exit_type} {datetime.now(_BERLIN).date()}]',
        exit_type, row_id
    ))
    conn.execute("UPDATE paper_fund SET value = value + ? WHERE key='cash'",
                 (shares * price - fees,))
    conn.commit()
    return pnl


def adjust_stop(conn, row_id: int, new_stop: float):
    conn.execute("UPDATE paper_portfolio SET stop_price=? WHERE id=?", (new_stop, row_id))
    conn.commit()


def queue_alert(msg: str):
    q = []
    if ALERT_QUEUE.exists():
        try:
            q = json.loads(ALERT_QUEUE.read_text(encoding="utf-8"))
        except Exception:
            q = []
    q.append({'message': msg, 'target': '452053147620343808',
               'ts': datetime.now(timezone.utc).isoformat()})
    ALERT_QUEUE.write_text(json.dumps(q, indent=2))


# ─── Kern-Entscheidungslogik ─────────────────────────────────────────

def review_position(t: dict, data: dict, vix: float) -> dict:
    """
    Bewertet eine offene Position aktiv.
    Returns: {'action': 'HOLD'|'EXIT'|'TIGHTEN_STOP'|'WIDEN_STOP', 'reason': str, 'new_stop': float|None}
    """
    price   = data['price']
    closes  = data['closes']
    entry   = t['entry_price']
    stop    = t['stop_price'] or (entry * 0.92)
    target  = t['target_price'] or (entry * 1.15)
    notes   = t['notes'] or ''
    shares  = t['shares'] or 1

    try:
        entry_dt  = datetime.fromisoformat(str(t['entry_date'])[:19])
        hold_days = (datetime.now(_BERLIN).replace(tzinfo=None) - entry_dt).days
    except Exception:
        hold_days = 0

    move_pct = (price - entry) / entry
    total_range = abs(target - entry)
    progress = (price - entry) / total_range if total_range > 0 else 0

    rsi   = _rsi(closes) or 50
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    # Tier bestimmen
    if 'TIER_C' in notes: tier = 'TIER_C'
    elif 'TIER_B' in notes: tier = 'TIER_B'
    elif 'TIER_A' in notes: tier = 'TIER_A'
    else: tier = 'DEFAULT'

    # ── AKTIVE EXIT-ENTSCHEIDUNGEN ───────────────────────────────────

    # 1. Stop wurde erreicht → immer raus
    if price <= stop:
        return {'action': 'EXIT', 'exit_type': 'STOP_HIT',
                'reason': f'Stop ${stop:.2f} getroffen bei ${price:.2f}'}

    # 2. Ziel erreicht → immer raus (Gewinne mitnehmen)
    if price >= target:
        return {'action': 'EXIT', 'exit_type': 'TARGET_HIT',
                'reason': f'Ziel ${target:.2f} erreicht — Gewinne mitnehmen'}

    # 3. RSI überkauft + im Gewinn → Teilgewinn schützen
    if rsi > 75 and move_pct > 0.05:
        new_stop = round(price * 0.97, 2)  # Stop auf 3% unter aktuellem Preis
        if new_stop > stop:
            return {'action': 'TIGHTEN_STOP', 'new_stop': new_stop,
                    'reason': f'RSI={rsi:.0f} überkauft + {move_pct:.1%} im Gewinn → Stop auf {new_stop:.2f} hochziehen'}

    # 4. Trend gebrochen: Preis fällt unter EMA50 nach vorherigem Aufwärtstrend
    if ema50 and price < ema50 * 0.98 and move_pct < -0.03:
        return {'action': 'EXIT', 'exit_type': 'TREND_BROKEN',
                'reason': f'Preis ${price:.2f} unter EMA50 ${ema50:.2f} — Trend gebrochen, These obsolet'}

    # 5. Tier C: 2 Tage, nichts passiert oder im Minus → selbst raus
    if tier == 'TIER_C' and hold_days >= 2:
        if move_pct < -0.02:
            return {'action': 'EXIT', 'exit_type': 'TIER_C_ACTIVE_CUT',
                    'reason': f'Tier C: {hold_days}d, {move_pct:.1%} — kein Fortschritt, Albert beendet selbst'}
        if move_pct < 0.01 and rsi < 45:
            return {'action': 'EXIT', 'exit_type': 'TIER_C_STAGNATION',
                    'reason': f'Tier C: {hold_days}d seitwärts, RSI={rsi:.0f} schwach — Kapital freigeben'}

    # 6. Stagnation mit nachlassendem Momentum (alle Tiers)
    if hold_days >= 5 and progress < 0.15 and move_pct < 0:
        if rsi < 40 and data['vol_ratio'] < 0.7:
            return {'action': 'EXIT', 'exit_type': 'STAGNATION',
                    'reason': f'{hold_days}d | Fortschritt {progress:.0%} | RSI={rsi:.0f} | Volumen schwach — selbst raus'}

    # 7. Trailing Stop-Anpassungen (im Gewinn)
    if move_pct >= 0.10:  # +10% → Stop auf +5%
        new_stop = round(entry * 1.05, 2)
        if new_stop > stop:
            return {'action': 'TIGHTEN_STOP', 'new_stop': new_stop,
                    'reason': f'+{move_pct:.1%} Gewinn → Stop auf +5% ({new_stop:.2f}) sichern'}
    elif move_pct >= 0.05:  # +5% → Stop auf Breakeven
        new_stop = round(entry * 1.005, 2)
        if new_stop > stop:
            return {'action': 'TIGHTEN_STOP', 'new_stop': new_stop,
                    'reason': f'+{move_pct:.1%} Gewinn → Stop auf Breakeven ({new_stop:.2f})'}

    # 8. VIX gestiegen (Markt volatiler) → Stop weiten um Whipsaw zu vermeiden
    if vix > 30 and move_pct > 0.03:
        wider = round(price * 0.94, 2)
        if wider < stop:
            return {'action': 'WIDEN_STOP', 'new_stop': wider,
                    'reason': f'VIX={vix:.1f} erhöht → Stop von {stop:.2f} auf {wider:.2f} weiten'}

    # Default: halten
    return {'action': 'HOLD',
            'reason': f'{hold_days}d | {move_pct:+.1%} | RSI={rsi:.0f} | Progress {progress:.0%}'}


# ─── Main Review Loop ────────────────────────────────────────────────

def run_review() -> list:
    conn = get_db()
    vix  = get_vix()

    trades = conn.execute("""
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               shares, fees, entry_date, notes, style
        FROM paper_portfolio WHERE status='OPEN'
    """).fetchall()

    actions = []

    for t in trades:
        ticker = t['ticker']
        data   = yahoo(ticker)
        if data is None:
            actions.append({'ticker': ticker, 'action': 'SKIP', 'reason': 'Kein Preis'})
            time.sleep(0.2)
            continue

        decision = review_position(dict(t), data, vix)
        entry  = t['entry_price']
        stop   = t['stop_price'] or (entry * 0.92)
        shares = t['shares'] or 1
        fees   = t['fees'] or 1.0
        price  = data['price']

        if decision['action'] == 'EXIT':
            pnl = close_position(conn, t['id'], price, decision['exit_type'], entry, shares, fees)
            emoji = '🟢' if pnl > 0 else '🔴'
            msg = (f"{emoji} **POSITION GESCHLOSSEN** — {ticker}\n"
                   f"Exit: {decision['exit_type']} | P&L: {pnl:+.2f}€\n"
                   f"Grund: {decision['reason']}")
            queue_alert(msg)
            actions.append({'ticker': ticker, 'action': 'EXIT', 'pnl': pnl,
                            'reason': decision['reason'], 'exit_type': decision['exit_type']})

        elif decision['action'] in ('TIGHTEN_STOP', 'WIDEN_STOP'):
            new_stop = decision['new_stop']
            adjust_stop(conn, t['id'], new_stop)
            actions.append({'ticker': ticker, 'action': decision['action'],
                            'old_stop': stop, 'new_stop': new_stop,
                            'reason': decision['reason']})

        else:
            actions.append({'ticker': ticker, 'action': 'HOLD',
                            'reason': decision['reason']})

        time.sleep(0.25)

    conn.close()

    # Summary-Alert wenn Aktionen da
    exits    = [a for a in actions if a['action'] == 'EXIT']
    stops    = [a for a in actions if a['action'] in ('TIGHTEN_STOP', 'WIDEN_STOP')]
    holds    = [a for a in actions if a['action'] == 'HOLD']

    if exits or stops:
        lines = [f"📋 **Daily Position Review** | VIX {vix:.1f} | {len(exits)} Exit(s) | {len(stops)} Stop-Adjust(s)"]
        for a in exits:
            e = '✅' if a.get('pnl', 0) > 0 else '❌'
            lines.append(f"  {e} EXIT {a['ticker']}: {a['exit_type']} | P&L {a.get('pnl', 0):+.2f}€")
        for a in stops:
            lines.append(f"  🔄 {a['action']} {a['ticker']}: {a['old_stop']:.2f}→{a['new_stop']:.2f}")
        if holds:
            lines.append(f"  ⚪ {len(holds)} Positionen HOLD")
        queue_alert('\n'.join(lines))

    return actions


def print_review(actions: list):
    exits = [a for a in actions if a['action'] == 'EXIT']
    stops = [a for a in actions if 'STOP' in a['action']]
    holds = [a for a in actions if a['action'] == 'HOLD']

    print(f"\n═══ Active Position Review ═══")
    for a in exits:
        p = a.get('pnl', 0)
        print(f"  {'✅' if p > 0 else '❌'} EXIT   {a['ticker']:10} {a.get('exit_type','?'):25} P&L: {p:+.2f}€")
    for a in stops:
        print(f"  🔄 {a['action']:15} {a['ticker']:10} {a.get('old_stop',0):.2f} → {a.get('new_stop',0):.2f}")
    for a in holds:
        print(f"  ⚪ HOLD   {a['ticker']:10} {a['reason'][:60]}")


if __name__ == '__main__':
    print(f"🔍 Active Position Review läuft ({datetime.now(_BERLIN).strftime('%H:%M')})...")
    actions = run_review()
    print_review(actions)
