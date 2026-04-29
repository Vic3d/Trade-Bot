#!/usr/bin/env python3
"""
bodenbildung_detector.py — Phase 43d: Multi-Kriterien Bodenbildung-Detektor.

Statt simpler "Preis > X"-Trigger checkt dieser Detektor 5 ehrliche
Bottom-Signale:

  1. Higher Low: aktuelles Tief > Tief vor 5 Handelstagen (kein neues Tief)
  2. EMA-Reclaim: Tagesschluss > 5-Tage-EMA (kurzer Trend dreht)
  3. RSI-Recovery: aktueller RSI > 35 nachdem er <30 war (oversold raus)
  4. Bullish Reversal Candle: Hammer / Bullish Engulfing / Piercing Pattern
  5. Volume-Bestätigung: heute Volume > 1.2 × 20-Tage-Avg

≥ 3 von 5 Kriterien = "Bodenbildung CONFIRMED" → Discord-Alert
2 von 5 = "EARLY SIGNAL" → Watch enger
< 2 = "Noch kein Boden"

Nutzung:
  python3 scripts/bodenbildung_detector.py --ticker BAYN.DE
  python3 scripts/bodenbildung_detector.py --all-watchlist  # alle pending_setups
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
ALERT_LOG = WS / 'data' / 'bodenbildung_alerts.jsonl'


def fetch_prices(ticker: str, days: int = 30) -> list[dict]:
    """Letzte N Trading-Tage OHLCV für ticker (neueste zuletzt)."""
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker=? ORDER BY date DESC LIMIT ?",
        (ticker, days)
    ).fetchall()
    c.close()
    if not rows:
        return []
    rows.reverse()  # ältester zuerst
    return [{'date': r[0], 'open': float(r[1]), 'high': float(r[2]),
             'low': float(r[3]), 'close': float(r[4]),
             'volume': int(r[5] or 0)} for r in rows]


def _ema(values: list[float], period: int) -> float:
    """EMA simpel (letzter Wert)."""
    if not values:
        return 0
    if len(values) < period:
        return sum(values) / len(values)
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI."""
    if len(closes) < period + 1:
        return 50
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_bullish_candle(prices: list[dict]) -> tuple[bool, str]:
    """Erkennt Bullish-Reversal-Candles im letzten Tag."""
    if len(prices) < 2:
        return False, ''
    today = prices[-1]
    yesterday = prices[-2]

    body = abs(today['close'] - today['open'])
    range_ = today['high'] - today['low']
    if range_ == 0:
        return False, ''

    # Hammer: kleiner Body oben, langer Lower-Shadow (>= 2x Body)
    if today['close'] > today['open']:  # bullish body
        body_high = today['close']
        body_low = today['open']
    else:
        body_high = today['open']
        body_low = today['close']
    lower_shadow = body_low - today['low']
    upper_shadow = today['high'] - body_high
    is_hammer = (body > 0 and lower_shadow >= 2 * body
                  and upper_shadow < body and today['close'] > today['open'])
    if is_hammer:
        return True, 'Hammer'

    # Bullish Engulfing: heute grün, gestern rot, heute Body deckt gestern Body
    is_bullish_engulfing = (
        today['close'] > today['open']
        and yesterday['close'] < yesterday['open']
        and today['close'] >= yesterday['open']
        and today['open'] <= yesterday['close']
    )
    if is_bullish_engulfing:
        return True, 'Bullish Engulfing'

    # Piercing Pattern: heute öffnet unter gestern low, schließt > 50% in gestern Body
    if (yesterday['close'] < yesterday['open']
            and today['open'] < yesterday['low']
            and today['close'] > today['open']
            and today['close'] > (yesterday['open'] + yesterday['close']) / 2):
        return True, 'Piercing'

    return False, ''


def analyze(ticker: str, days: int = 30) -> dict:
    """5-Kriterien-Bodenbildung-Check."""
    prices = fetch_prices(ticker, days=days)
    if len(prices) < 21:
        return {'error': f'too_few_data ({len(prices)} days)', 'ticker': ticker}

    today = prices[-1]
    five_days_ago = prices[-6]
    closes = [p['close'] for p in prices]
    volumes = [p['volume'] for p in prices]

    criteria = {}
    reasons = []

    # 1. Higher Low: today's low > 5-day-ago low
    higher_low = today['low'] > five_days_ago['low']
    criteria['higher_low'] = higher_low
    reasons.append(
        f"Higher-Low: {'✅' if higher_low else '❌'} "
        f"(heute {today['low']:.2f} vs vor 5d {five_days_ago['low']:.2f})"
    )

    # 2. EMA-Reclaim: close > 5-day-EMA
    ema5 = _ema(closes, 5)
    ema_reclaim = today['close'] > ema5
    criteria['ema_reclaim'] = ema_reclaim
    reasons.append(
        f"EMA5-Reclaim: {'✅' if ema_reclaim else '❌'} "
        f"(close {today['close']:.2f} vs EMA5 {ema5:.2f})"
    )

    # 3. RSI-Recovery: heute RSI > 35 UND irgendwann letzte 10d war <30
    rsi_now = _rsi(closes)
    rsi_was_oversold = False
    for i in range(max(0, len(closes)-10), len(closes)):
        rsi_at = _rsi(closes[:i+1])
        if rsi_at < 30:
            rsi_was_oversold = True
            break
    rsi_recovery = rsi_now > 35 and rsi_was_oversold
    criteria['rsi_recovery'] = rsi_recovery
    reasons.append(
        f"RSI-Recovery: {'✅' if rsi_recovery else '❌'} "
        f"(jetzt {rsi_now:.1f}, war oversold: {rsi_was_oversold})"
    )

    # 4. Bullish Reversal Candle
    candle_ok, candle_name = detect_bullish_candle(prices)
    criteria['bullish_candle'] = candle_ok
    reasons.append(
        f"Reversal-Candle: {'✅ ' + candle_name if candle_ok else '❌ keine'}"
    )

    # 5. Volume-Bestätigung: heute Vol > 1.2x 20-day-avg
    vol_avg_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes) / len(volumes)
    vol_confirm = today['volume'] > 1.2 * vol_avg_20
    criteria['volume_confirm'] = vol_confirm
    reasons.append(
        f"Volume-Spike: {'✅' if vol_confirm else '❌'} "
        f"(heute {today['volume']:,.0f} vs avg20 {vol_avg_20:,.0f})"
    )

    score = sum(1 for v in criteria.values() if v)
    if score >= 3:
        status = 'CONFIRMED'
    elif score == 2:
        status = 'EARLY_SIGNAL'
    else:
        status = 'NO_BOTTOM_YET'

    return {
        'ticker': ticker,
        'date': today['date'],
        'price': today['close'],
        'criteria': criteria,
        'score': score,
        'max_score': 5,
        'status': status,
        'reasons': reasons,
        'rsi': round(rsi_now, 1),
        'ema5': round(ema5, 2),
    }


def push_alert(result: dict) -> None:
    """Discord-Alert + JSON-Log."""
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(), **result
        }, ensure_ascii=False) + '\n')

    if result['status'] not in ('CONFIRMED', 'EARLY_SIGNAL'):
        return
    try:
        from discord_chat import _send_message
        from ticker_lookup import lookup as _lookup
        info = _lookup(result['ticker'])
        icon = '🎯' if result['status'] == 'CONFIRMED' else '🟡'
        msg = (
            f"{icon} **Bodenbildung-Signal: {info['name']} ({info['ticker']}, "
            f"WKN {info['wkn']})**\n"
            f"Status: **{result['status']}** ({result['score']}/5 Kriterien)\n"
            f"Kurs: {result['price']:.2f} | RSI: {result['rsi']} | EMA5: {result['ema5']}\n"
            + '\n'.join(f"  · {r}" for r in result['reasons'])
        )
        if result['status'] == 'CONFIRMED':
            msg += '\n\n💡 Re-Entry-Setup ist da — CEO sollte heute Decide.'
        else:
            msg += '\n\n⏳ Noch nicht — 1 Kriterium fehlt für CONFIRMED.'
        _send_message(msg)
    except Exception as e:
        print(f'[bodenbildung] discord push err: {e}', file=sys.stderr)


def upgrade_pending_to_decide(ticker: str, strategy: str) -> bool:
    """Bei CONFIRMED: Pending-Setup → Status TRIGGERED → CEO-Daemon picks up."""
    try:
        c = sqlite3.connect(str(DB))
        c.execute(
            "UPDATE pending_setups SET status='TRIGGERED', "
            "    updated_at=?, notes=COALESCE(notes,'') || ' | bodenbildung_confirmed' "
            "WHERE ticker=? AND status='WATCHING'",
            (datetime.now(timezone.utc).isoformat(), ticker)
        )
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def run_for_all_watchlist() -> list[dict]:
    """Alle WATCHING pending_setups durchgehen."""
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT DISTINCT ticker, strategy FROM pending_setups WHERE status='WATCHING'"
    ).fetchall()
    c.close()
    results = []
    for ticker, strategy in rows:
        r = analyze(ticker)
        if 'error' in r:
            continue
        r['strategy'] = strategy
        results.append(r)
        push_alert(r)
        if r['status'] == 'CONFIRMED':
            upgrade_pending_to_decide(ticker, strategy)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', help='Single-Ticker-Analyse')
    ap.add_argument('--all-watchlist', action='store_true',
                     help='Alle WATCHING pending_setups')
    ap.add_argument('--no-alert', action='store_true', help='Kein Discord-Push')
    args = ap.parse_args()

    if args.all_watchlist:
        results = run_for_all_watchlist()
        print(f'Analyzed {len(results)} watchlist-tickers')
        for r in results:
            icon = {'CONFIRMED': '🎯', 'EARLY_SIGNAL': '🟡',
                    'NO_BOTTOM_YET': '⚪'}[r['status']]
            print(f'  {icon} {r["ticker"]:<10} score={r["score"]}/5 — {r["status"]}')
        return 0

    if args.ticker:
        r = analyze(args.ticker)
        if 'error' in r:
            print(f'❌ {r["error"]}')
            return 1
        print(f'═══ Bodenbildung-Analyse {r["ticker"]} ═══')
        print(f'Datum: {r["date"]}')
        print(f'Kurs:  {r["price"]:.2f}')
        print(f'RSI:   {r["rsi"]} | EMA5: {r["ema5"]}')
        print(f'Score: {r["score"]}/5 → **{r["status"]}**')
        print()
        print('Kriterien:')
        for line in r['reasons']:
            print(f'  · {line}')
        if not args.no_alert:
            push_alert(r)
        return 0

    print('Usage: --ticker BAYN.DE  oder  --all-watchlist')
    return 1


if __name__ == '__main__':
    sys.exit(main())
