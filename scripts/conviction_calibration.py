#!/usr/bin/env python3
"""
conviction_calibration.py — Phase 44p: Conviction → Win-Probability Mapping.

Problem (vom calibration_tracker entdeckt): conviction-Score (0-100) wurde
linear als P(win) interpretiert — das stimmt nicht. Conviction ist Setup-
Quality, nicht direkt Wahrscheinlichkeit.

  Trades mit conviction 0-10 hatten ACTUAL WR 68% (Bias -63pp = Underconfidence)

Loesung: Logistische Regression learnt das echte Mapping aus closed Trades.

  predicted_win_prob = sigmoid(a + b * conviction/100)

Output:
  data/conviction_calibration.json  {a, b, n_samples, brier_after, fitted_at}

Wird vom calibration_tracker eingelesen statt linearer Interpretation.
Wird vom paper_trade_engine optional genutzt (für realistischere Sizing).

Run: python3 scripts/conviction_calibration.py
"""
from __future__ import annotations
import json, math, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'conviction_calibration.json'


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _outcome(status: str, pnl: float | None) -> int | None:
    s = (status or '').upper()
    p = pnl or 0
    if s == 'WIN' or (s == 'CLOSED' and p > 0): return 1
    if s == 'LOSS' or (s == 'CLOSED' and p < 0): return 0
    return None


def _sigmoid(x: float) -> float:
    if x > 50: return 1.0
    if x < -50: return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _fit_logistic(xs: list[float], ys: list[int],
                   lr: float = 0.05, epochs: int = 2000) -> tuple[float, float]:
    """Mini-Gradient-Descent fuer Logistic Regression.
    Liefert (a, b): predicted = sigmoid(a + b*x).
    Pure Python, keine sklearn-Abhaengigkeit."""
    a, b = 0.0, 0.0
    n = len(xs)
    if n == 0: return 0.0, 0.0
    for _ in range(epochs):
        ga, gb = 0.0, 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(a + b * x)
            err = p - y
            ga += err
            gb += err * x
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def _brier(xs: list[float], ys: list[int], a: float, b: float) -> float:
    n = len(xs)
    if n == 0: return float('nan')
    return sum((_sigmoid(a + b*x) - y)**2 for x, y in zip(xs, ys)) / n


def fit() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT conviction, status, pnl_eur FROM paper_portfolio "
        "WHERE conviction IS NOT NULL AND status IN ('WIN','LOSS','CLOSED')"
    ).fetchall()
    c.close()

    samples = []
    for conv, status, pnl in rows:
        try:
            x = float(conv) / 100.0  # normalize to [0,1]
            y = _outcome(status, pnl)
            if y is None: continue
            samples.append((x, y))
        except: pass

    if len(samples) < 10:
        return {'error': f'insufficient_samples ({len(samples)})'}

    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]

    # Linear-Baseline (wie calibration_tracker es vorher annahm)
    brier_linear = sum((x - y)**2 for x, y in samples) / len(samples)

    # Logistische Eichung
    a, b = _fit_logistic(xs, ys)
    brier_logistic = _brier(xs, ys, a, b)

    # Sample-Buckets (zur Visualisierung)
    buckets = {}
    from collections import defaultdict
    bk = defaultdict(lambda: {'n': 0, 'wins': 0, 'pred_sum': 0.0})
    for x, y in samples:
        bin_id = min(int(x * 10), 9)
        bk[bin_id]['n'] += 1
        bk[bin_id]['wins'] += y
        bk[bin_id]['pred_sum'] += _sigmoid(a + b*x)
    for bin_id in sorted(bk):
        d = bk[bin_id]
        buckets[f'{bin_id*10}-{(bin_id+1)*10}'] = {
            'n': d['n'], 'wr_actual': round(d['wins']/d['n'], 3),
            'wr_predicted_logistic': round(d['pred_sum']/d['n'], 3),
            'wr_predicted_linear': round(bin_id*0.1 + 0.05, 3),
        }

    out = {
        'fitted_at': _now(),
        'n_samples': len(samples),
        'a': round(a, 4), 'b': round(b, 4),
        'formula': 'predicted_win_prob = sigmoid(a + b * conviction/100)',
        'brier_linear': round(brier_linear, 4),
        'brier_logistic': round(brier_logistic, 4),
        'improvement_pct': round((brier_linear - brier_logistic) / brier_linear * 100, 1)
                           if brier_linear > 0 else 0,
        'buckets': buckets,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding='utf-8')
    return out


def predict(conviction_0_100: float) -> float:
    """Public API: gib echte Win-Probability fuer einen Conviction-Score zurueck."""
    if not OUT.exists():
        return conviction_0_100 / 100.0  # Fallback linear
    try:
        cal = json.loads(OUT.read_text(encoding='utf-8'))
        a = cal.get('a', 0.0)
        b = cal.get('b', 1.0)
        return _sigmoid(a + b * (conviction_0_100 / 100.0))
    except Exception:
        return conviction_0_100 / 100.0


def main() -> int:
    r = fit()
    if 'error' in r:
        print(f'Error: {r["error"]}')
        return 1
    print(f'═══ Conviction-Calibration @ {r["fitted_at"][:16]} ═══')
    print(f'  N samples: {r["n_samples"]}')
    print(f'  Formula: {r["formula"]}')
    print(f'  a = {r["a"]:.4f}, b = {r["b"]:.4f}')
    print(f'  Brier (linear assumption):    {r["brier_linear"]}')
    print(f'  Brier (logistic calibrated):  {r["brier_logistic"]}')
    print(f'  Verbesserung: {r["improvement_pct"]}%')
    print()
    print('  Bucket-Vergleich:')
    print(f'  {"Bucket":<10} {"n":>4} {"actual":>8} {"linear":>8} {"logistic":>10}')
    for bk, bv in r['buckets'].items():
        print(f'  {bk+"%":<10} {bv["n"]:>4} {bv["wr_actual"]*100:>7.1f}% '
              f'{bv["wr_predicted_linear"]*100:>7.1f}% {bv["wr_predicted_logistic"]*100:>9.1f}%')
    return 0


if __name__ == '__main__':
    sys.exit(main())
