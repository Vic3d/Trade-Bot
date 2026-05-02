#!/usr/bin/env python3
"""
bayer_catalyst_monitor.py — Phase 44r: Daily Watch Bayer-Glyphosat Catalyst.

Ueberwacht BAYN.DE-Tape + News-Sentiment + Volumen taeglich bis zur SCOTUS-
Decision (08.07.2026 erwartet). Discord-Push wenn:
  - Tape-Move +/- 3% in 1 Tag
  - Tape-Trend +/- 8% in 7 Tagen
  - Volumen-Anomalie (>2x avg)
  - Neue Headlines mit 'Bayer'/'Glyphosat'/'Roundup'/'Monsanto'
  - 7 Tage vor Decision: tgl. Status-Push (auch ohne Trigger)

Output:
  data/bayer_catalyst_state.jsonl  Audit-Trail
  Discord-Push bei Triggers
  data/bayer_catalyst_signals.json (last_state fuer Dedupe)

Run: python3 scripts/bayer_catalyst_monitor.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB = WS / 'data' / 'trading.db'
LOG = WS / 'data' / 'bayer_catalyst_state.jsonl'
STATE = WS / 'data' / 'bayer_catalyst_signals.json'

DECISION_DATE = date(2026, 7, 8)
OPTOUT_DATE = date(2026, 6, 4)


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding='utf-8'))
    return {'last_seen_news_ids': [], 'last_close': None}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2), encoding='utf-8')


def _fetch_tape() -> dict:
    try:
        import yfinance as yf
        h = yf.Ticker('BAYN.DE').history(period='30d')
        if h.empty:
            return {}
        last = float(h['Close'].iloc[-1])
        prev = float(h['Close'].iloc[-2]) if len(h) >= 2 else last
        chg_1d = (last - prev) / prev * 100 if prev else 0
        # 7d Trend
        d7_idx = max(0, len(h) - 8)
        d7 = float(h['Close'].iloc[d7_idx])
        chg_7d = (last - d7) / d7 * 100 if d7 else 0
        # 30d
        d30 = float(h['Close'].iloc[0])
        chg_30d = (last - d30) / d30 * 100 if d30 else 0
        # Volumen
        last_vol = float(h['Volume'].iloc[-1])
        avg_vol = float(h['Volume'].mean())
        vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1
        return {
            'live': round(last, 2),
            'chg_1d_pct': round(chg_1d, 2),
            'chg_7d_pct': round(chg_7d, 2),
            'chg_30d_pct': round(chg_30d, 2),
            'volume_ratio': round(vol_ratio, 2),
            'as_of': h.index[-1].strftime('%Y-%m-%d'),
        }
    except Exception as e:
        return {'error': str(e)}


def _fetch_news() -> list[dict]:
    """Letzte 24h Headlines die Bayer/Glyphosat erwaehnen."""
    if not DB.exists(): return []
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, headline, source, created_at FROM news_events "
            "WHERE created_at >= datetime('now', '-24 hours') "
            "AND (lower(headline) LIKE '%bayer%' "
            "  OR lower(headline) LIKE '%glyphosat%' "
            "  OR lower(headline) LIKE '%roundup%' "
            "  OR lower(headline) LIKE '%monsanto%') "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _days_to_decision() -> int:
    today = date.today()
    return (DECISION_DATE - today).days


def _classify(tape: dict, news: list[dict], state: dict) -> dict:
    triggers = []
    severity = 'INFO'
    if not tape or 'error' in tape:
        return {'severity': 'INFO', 'triggers': ['no_tape'], 'should_push': False}

    if abs(tape.get('chg_1d_pct', 0)) >= 3:
        triggers.append(f"1d-Move {tape['chg_1d_pct']:+.1f}%")
        severity = 'HIGH'
    if abs(tape.get('chg_7d_pct', 0)) >= 8:
        triggers.append(f"7d-Trend {tape['chg_7d_pct']:+.1f}%")
        severity = 'HIGH' if severity != 'HIGH' else severity
    if tape.get('volume_ratio', 1) >= 2.0:
        triggers.append(f"Volumen {tape['volume_ratio']:.1f}x")
        if severity != 'HIGH': severity = 'MEDIUM'

    # Neue News (nicht in last_seen)
    seen_ids = set(state.get('last_seen_news_ids', []))
    new_news = [n for n in news if n['id'] not in seen_ids]
    if new_news:
        triggers.append(f"{len(new_news)} neue Headlines")
        if severity == 'INFO': severity = 'MEDIUM'

    days_left = _days_to_decision()
    daily_window = days_left <= 7 and days_left >= 0  # letzte Woche immer pushen

    return {
        'severity': severity,
        'triggers': triggers,
        'should_push': len(triggers) > 0 or daily_window,
        'new_news': new_news[:5],
        'days_to_decision': days_left,
    }


def _build_message(tape: dict, news: list[dict], cls: dict) -> str:
    days = cls.get('days_to_decision', 0)
    days_str = f'{days}d bis Decision' if days > 0 else 'Decision-Day!'
    icon = {'HIGH': '🚨', 'MEDIUM': '⚠️', 'INFO': '📊'}.get(cls['severity'], '📊')
    lines = [
        f"{icon} **Bayer-Catalyst-Watch** ({days_str})",
        f"BAYN.DE: {tape.get('live')}€ "
        f"| 1d {tape.get('chg_1d_pct',0):+.1f}% "
        f"| 7d {tape.get('chg_7d_pct',0):+.1f}% "
        f"| 30d {tape.get('chg_30d_pct',0):+.1f}% "
        f"| Vol {tape.get('volume_ratio',1):.1f}x",
    ]
    if cls['triggers']:
        lines.append(f"Trigger: {', '.join(cls['triggers'])}")
    if cls.get('new_news'):
        lines.append('Neue Headlines:')
        for n in cls['new_news']:
            lines.append(f"  · {n['headline'][:120]} [{n['source']}]")
    # Pre-Decision-Pricing-In Indikator
    if days <= 14 and tape.get('chg_30d_pct', 0) < -5:
        lines.append('💡 Pre-Decision-Pricing-In sichtbar: Tape faellt, Markt erwartet bearish Outcome.')
    elif days <= 14 and tape.get('chg_30d_pct', 0) > 5:
        lines.append('💡 Pre-Decision-Pricing-In: Tape steigt, Markt erwartet bullish Outcome.')
    return '\n'.join(lines)[:1900]


def run() -> dict:
    state = _load_state()
    tape = _fetch_tape()
    news = _fetch_news()
    cls = _classify(tape, news, state)

    record = {'ts': _now(), 'tape': tape, 'cls': cls,
              'n_news_total': len(news), 'n_news_new': len(cls.get('new_news', []))}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    # State update
    state['last_close'] = tape.get('live')
    state['last_seen_news_ids'] = list(set(state.get('last_seen_news_ids', []))
                                         | set(n['id'] for n in news))[-200:]
    _save_state(state)

    if cls.get('should_push'):
        try:
            from discord_dispatcher import send_alert, TIER_HIGH, TIER_MEDIUM, TIER_LOW
            tier = TIER_HIGH if cls['severity'] == 'HIGH' else (
                   TIER_MEDIUM if cls['severity'] == 'MEDIUM' else TIER_LOW)
            msg = _build_message(tape, news, cls)
            send_alert(msg, tier=tier, category='bayer_catalyst',
                        dedupe_key=f'bayer_catalyst_{date.today().isoformat()}')
        except Exception as e:
            print(f'[bayer_monitor] discord push fail: {e}')

    return record


def main() -> int:
    r = run()
    print(f"═══ Bayer-Catalyst-Watch @ {r['ts'][:16]} ═══")
    if 'tape' in r and r['tape']:
        t = r['tape']
        print(f"  BAYN.DE: {t.get('live')}€ | 1d {t.get('chg_1d_pct',0):+.1f}% "
              f"| 7d {t.get('chg_7d_pct',0):+.1f}% | 30d {t.get('chg_30d_pct',0):+.1f}%")
        print(f"  Volumen: {t.get('volume_ratio',1):.1f}x avg")
    cls = r['cls']
    print(f"  Severity: {cls['severity']}, Days-to-Decision: {cls.get('days_to_decision','?')}")
    print(f"  Triggers: {cls.get('triggers', [])}")
    print(f"  News heute: {r['n_news_total']} ({r['n_news_new']} neu)")
    print(f"  Pushed: {cls['should_push']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
