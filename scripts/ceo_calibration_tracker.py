#!/usr/bin/env python3
"""
ceo_calibration_tracker.py — Phase 44o: Brier-Score + Calibration-Buckets.

Albert hat 0 Calibration-Samples. Heisst: er weiss nicht ob seine Confidence-
Schaetzungen taugen. Dieser Job korrigiert das nightly:

  Pro closed Trade:
    predicted_win_prob = conviction / 100      # auf 0-1 normalisiert
    actual_outcome     = 1 if WIN/CLOSED+, 0 if LOSS/CLOSED-

  Brier-Score = mean((predicted - actual)^2)
    0.0  = perfekte Calibration
    0.25 = Coinflip
    > 0.25 = systematischer Bias

  Calibration-Buckets (10%-Bins):
    Bucket 60-70%:  N trades, actual_WR  → diff = bias
    Bucket 80-90%:  N trades, actual_WR  → diff = bias
    ...

Output:
  data/ceo_calibration.json    (rolling stats, last 30/90/all)
  Discord-Push wenn Bias > 0.15 (15pp Differenz zwischen claimed und actual)

Run: python3 scripts/ceo_calibration_tracker.py
"""
from __future__ import annotations
import json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'ceo_calibration.json'


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _outcome_binary(status: str, pnl: float | None) -> int | None:
    s = (status or '').upper()
    p = pnl or 0.0
    if s == 'WIN' or (s == 'CLOSED' and p > 0): return 1
    if s == 'LOSS' or (s == 'CLOSED' and p < 0): return 0
    return None  # offen oder reset_closed → ignorieren


def _compute_window(c: sqlite3.Connection, days: int | None) -> dict:
    """Berechnet Brier + Buckets fuer letzten N Tage. days=None → all-time."""
    where = "WHERE conviction IS NOT NULL AND status IN ('WIN','LOSS','CLOSED')"
    params = []
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        where += " AND substr(close_date,1,10) >= ?"
        params.append(cutoff)
    rows = c.execute(
        f"SELECT conviction, status, pnl_eur FROM paper_portfolio {where}",
        params
    ).fetchall()

    samples = []
    for conv, status, pnl in rows:
        try:
            p = float(conv) / 100.0  # conviction 0-100 → prob 0-1
            o = _outcome_binary(status, pnl)
            if o is None: continue
            samples.append((p, o))
        except: pass

    if not samples:
        return {'n': 0, 'brier': None, 'buckets': {}, 'bias': None}

    n = len(samples)
    brier = sum((p - o) ** 2 for p, o in samples) / n
    avg_predicted = sum(p for p, _ in samples) / n
    avg_actual = sum(o for _, o in samples) / n
    bias = avg_predicted - avg_actual  # >0 = overconfident, <0 = underconfident

    # Buckets in 10%-Bins
    buckets = defaultdict(lambda: {'n': 0, 'wins': 0})
    for p, o in samples:
        bin_id = min(int(p * 10), 9)  # 0-9 = [0%-10%, ..., 90%-100%]
        buckets[bin_id]['n'] += 1
        buckets[bin_id]['wins'] += o
    bucket_out = {}
    for bin_id in sorted(buckets):
        b = buckets[bin_id]
        wr_actual = (b['wins'] / b['n']) if b['n'] else 0
        wr_predicted = bin_id * 0.1 + 0.05  # mid-of-bucket
        bucket_out[f'{bin_id*10}-{(bin_id+1)*10}%'] = {
            'n': b['n'], 'wins': b['wins'],
            'wr_actual': round(wr_actual, 3),
            'wr_predicted': round(wr_predicted, 3),
            'bias_pp': round((wr_predicted - wr_actual) * 100, 1),
        }

    return {
        'n': n, 'brier': round(brier, 4),
        'avg_predicted': round(avg_predicted, 3),
        'avg_actual': round(avg_actual, 3),
        'bias': round(bias, 3),
        'buckets': bucket_out,
        'verdict': _verdict(brier, bias, n),
    }


def _verdict(brier: float, bias: float, n: int) -> str:
    if n < 10: return f'INSUFFICIENT_DATA (n={n}, need >=10)'
    if brier > 0.30: return f'POOR_CALIBRATION (Brier {brier:.3f} >> 0.25 coinflip)'
    if abs(bias) > 0.15: return f'BIASED ({"over" if bias>0 else "under"}confident by {abs(bias)*100:.0f}pp)'
    if brier < 0.20: return f'GOOD_CALIBRATION (Brier {brier:.3f}, bias {bias*100:+.0f}pp)'
    return f'OK_CALIBRATION (Brier {brier:.3f}, bias {bias*100:+.0f}pp)'


def run() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    out = {
        'ts': _now(),
        'last_30d': _compute_window(c, 30),
        'last_90d': _compute_window(c, 90),
        'all_time': _compute_window(c, None),
    }
    c.close()
    OUT.write_text(json.dumps(out, indent=2), encoding='utf-8')

    # Discord-Push bei Bias-Alarm
    bias_alarm = False
    for window_name in ('last_30d', 'all_time'):
        w = out[window_name]
        if w.get('n', 0) >= 10 and abs(w.get('bias', 0)) > 0.15:
            bias_alarm = True
    if bias_alarm:
        try:
            from discord_dispatcher import send_alert, TIER_MEDIUM
            w = out['last_30d'] if out['last_30d'].get('n',0) >= 10 else out['all_time']
            msg = (
                f'⚖️ **CEO-Calibration-Alarm** ({w["verdict"]})\n'
                f'30d: Brier {out["last_30d"]["brier"]} (n={out["last_30d"]["n"]}) | '
                f'all-time Brier {out["all_time"]["brier"]} (n={out["all_time"]["n"]})\n'
                f'Predicted-WR avg: {w["avg_predicted"]:.0%}, Actual-WR: {w["avg_actual"]:.0%}\n'
                f'_Albert ueberschaetzt sich um {abs(w["bias"])*100:.0f}pp_'
            )
            send_alert(msg, tier=TIER_MEDIUM, category='ceo_calibration',
                       dedupe_key=f'calibration_{datetime.now().strftime("%Y%W")}')
        except Exception: pass

    return out


def main() -> int:
    r = run()
    print(f'═══ CEO-Calibration @ {r.get("ts","")[:16]} ═══')
    for w_name in ('last_30d', 'last_90d', 'all_time'):
        w = r.get(w_name, {})
        print(f'\n{w_name}: n={w.get("n",0)}, Brier={w.get("brier","-")}, '
              f'bias={w.get("bias","-")} → {w.get("verdict","-")}')
        for bk, bv in (w.get('buckets') or {}).items():
            print(f'    {bk:>10}: n={bv["n"]:>3} actual={bv["wr_actual"]:.0%} '
                  f'predicted={bv["wr_predicted"]:.0%} bias={bv["bias_pp"]:+.0f}pp')
    return 0


if __name__ == '__main__':
    sys.exit(main())
