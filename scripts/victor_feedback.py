#!/usr/bin/env python3
"""
K1 — Victor Feedback Consumer
==============================
Liest data/victor_feedback.json (befüllt von discord_chat.poll_reactions)
und berechnet pro Strategie + Ticker einen Trust-Score aus ✅/❌-Reactions.

Output:
- data/victor_trust.json
  {
    "strategies": {"PS5": {"score": -0.35, "confirms": 2, "rejects": 7, ...}},
    "tickers":    {"NVDA": {"score": 0.5, "confirms": 5, "rejects": 0, ...}},
    "computed_at": ISO
  }

Konsumenten:
- conviction_scorer.py → Malus wenn Trust negativ
- discord_chat.load_context() → Albert sieht was Victor (nicht) mag
"""
import json, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

WS = Path(__file__).resolve().parent.parent
FEEDBACK = WS / 'data' / 'victor_feedback.json'
TRUST = WS / 'data' / 'victor_trust.json'

# Strategie-Tags (z.B. "PS5", "PT", "PM", "AR-HALB")
STRATEGY_RE = re.compile(r'\b(PS\d+|PT\d*|PM\d*|S\d+|DT\d+|AR-[A-Z]+|PS_[A-Z]+)\b')
# Ticker (2-5 Großbuchstaben, optional .XX)
TICKER_RE = re.compile(r'\b([A-Z]{2,5}(?:\.[A-Z]{1,3})?)\b')
TICKER_BLACKLIST = {
    'AND','THE','FOR','BUT','NOT','EUR','USD','VIX','CEO','CET','OK','HQ','AI',
    'ML','RL','DB','API','LLM','URL','CPI','GDP','OPEN','WIN','LOSS','CRV','ATR',
    'EMA','RSI','SMA','PNL','WR','PT','PM','PS','S','DT','AR','US','EU',
}


def compute_trust(max_age_days: int = 30) -> dict:
    if not FEEDBACK.exists():
        out = {'strategies': {}, 'tickers': {}, 'computed_at': datetime.now(timezone.utc).isoformat(),
               'total_reactions': 0}
        TRUST.write_text(json.dumps(out, indent=2))
        return out

    try:
        data = json.loads(FEEDBACK.read_text(encoding='utf-8'))
    except Exception:
        return {'strategies': {}, 'tickers': {}, 'error': 'parse failed'}

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    strat_counts: dict[str, dict] = {}
    tick_counts: dict[str, dict] = {}

    for r in data.get('reactions', []):
        ts = r.get('recorded_at', '')
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue
        except Exception:
            pass  # keep without date filter

        label = r.get('label', '')
        excerpt = r.get('message_excerpt', '')

        # Identifier extraction
        strats = set(STRATEGY_RE.findall(excerpt))
        raw_tickers = set(TICKER_RE.findall(excerpt))
        tickers = {t for t in raw_tickers if t not in TICKER_BLACKLIST and len(t) >= 2}

        weight = {'CONFIRM': +1, 'LIKE': +0.5, 'REJECT': -1, 'DISLIKE': -0.5, 'CAUTION': -0.25}.get(label, 0)
        if weight == 0:
            continue

        for sid in strats:
            d = strat_counts.setdefault(sid, {'confirms': 0, 'rejects': 0, 'weight_sum': 0.0})
            if weight > 0:
                d['confirms'] += 1
            else:
                d['rejects'] += 1
            d['weight_sum'] += weight

        for t in tickers:
            d = tick_counts.setdefault(t, {'confirms': 0, 'rejects': 0, 'weight_sum': 0.0})
            if weight > 0:
                d['confirms'] += 1
            else:
                d['rejects'] += 1
            d['weight_sum'] += weight

    # Score = weight_sum / max(n,3) → Range ca. -1..+1
    def _score(d: dict) -> float:
        n = d['confirms'] + d['rejects']
        return round(d['weight_sum'] / max(n, 3), 3)

    strat_out = {sid: {**d, 'score': _score(d), 'n': d['confirms'] + d['rejects']}
                 for sid, d in strat_counts.items()}
    tick_out = {t: {**d, 'score': _score(d), 'n': d['confirms'] + d['rejects']}
                for t, d in tick_counts.items()}

    out = {
        'strategies': strat_out,
        'tickers': tick_out,
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'total_reactions': sum(d['confirms'] + d['rejects'] for d in strat_counts.values()),
        'window_days': max_age_days,
    }
    TRUST.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def get_trust_malus(strategy: str = '', ticker: str = '') -> tuple[float, str]:
    """Für conviction_scorer: Gibt (malus_points, reason) zurück.
    malus ist negativ = Abzug vom Score. Range ca. -10 bis 0.
    Bei strong positive feedback auch +bonus bis +5."""
    try:
        if not TRUST.exists():
            return 0.0, ''
        data = json.loads(TRUST.read_text(encoding='utf-8'))
    except Exception:
        return 0.0, ''

    malus = 0.0
    reasons = []
    sid = (strategy or '').upper()
    tk = (ticker or '').upper()

    if sid and sid in data.get('strategies', {}):
        s = data['strategies'][sid]
        if s['n'] >= 3:
            # score in [-1, +1] → malus in [-8, +4]
            m = s['score'] * (8 if s['score'] < 0 else 4)
            malus += m
            reasons.append(f"strat {sid}: {s['confirms']}✅/{s['rejects']}❌ ({m:+.1f})")

    if tk and tk in data.get('tickers', {}):
        t = data['tickers'][tk]
        if t['n'] >= 3:
            m = t['score'] * (6 if t['score'] < 0 else 3)
            malus += m
            reasons.append(f"tick {tk}: {t['confirms']}✅/{t['rejects']}❌ ({m:+.1f})")

    return round(malus, 2), '; '.join(reasons)


if __name__ == '__main__':
    out = compute_trust()
    print(f"[victor_feedback] {out.get('total_reactions', 0)} reactions in {out.get('window_days', 30)}d")
    if out.get('strategies'):
        print('  Strategies:')
        for sid, d in sorted(out['strategies'].items(), key=lambda kv: kv[1]['score']):
            print(f"    {sid}: score={d['score']:+.2f} ({d['confirms']}✅/{d['rejects']}❌)")
    if out.get('tickers'):
        print('  Tickers (worst 5):')
        for t, d in sorted(out['tickers'].items(), key=lambda kv: kv[1]['score'])[:5]:
            print(f"    {t}: score={d['score']:+.2f} ({d['confirms']}✅/{d['rejects']}❌)")
