#!/usr/bin/env python3
"""
quant_metrics.py — Phase 45a (Sprint 0): Mission-KPIs taeglich berechnen.

Albert hat in seinem Capability-Audit selbst identifiziert: 'Sharpe-Ratio
existiert nicht. Drawdown nicht getrackt. Vollstaendige Blindheit auf
Mission-KPI #1 und #2.'

Dieser Job loest das. Berechnet taeglich:
  - Sharpe-Ratio (annualisiert) — Mission-Ziel: > 2.0
  - Sortino-Ratio (downside-only) — schaerfer als Sharpe
  - Calmar-Ratio (Return/MaxDD) — Mission-Ziel: > 3.0
  - Max-Drawdown rolling (7d/30d/90d) — Mission-Ziel: < 10%
  - Profit-Faktor (sum_wins / abs(sum_losses))
  - Trade-Expectancy (avg_win × WR - avg_loss × LR)
  - Per-Strategy Stats (gleiche KPIs pro Strategy)

Output:
  data/quant_metrics.json (rolling state, last 90d)
  data/quant_metrics_log.jsonl (Audit, taegliche Snapshots)
  Dashboard-Tile liest direkt aus json

Run: python3 scripts/quant_metrics.py
"""
from __future__ import annotations
import json, math, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
DB = WS / 'data' / 'trading.db'
OUT = WS / 'data' / 'quant_metrics.json'
LOG = WS / 'data' / 'quant_metrics_log.jsonl'

# Annualisierungs-Faktor: Trading-Tage pro Jahr
TRADING_DAYS_PER_YEAR = 252


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _safe_div(a, b, default=0.0):
    return a / b if b else default


def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2: return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def _compute_sharpe(daily_returns: list[float], rf_rate: float = 0.0) -> float:
    """Sharpe = (mean_return - rf) / stdev * sqrt(252)
    daily_returns als pct (0.01 = 1%)"""
    if len(daily_returns) < 2: return 0.0
    excess = [r - rf_rate / TRADING_DAYS_PER_YEAR for r in daily_returns]
    mean = sum(excess) / len(excess)
    sd = _stdev(excess)
    if sd == 0: return 0.0
    return (mean / sd) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _compute_sortino(daily_returns: list[float], rf_rate: float = 0.0) -> float:
    """Sortino = mean_excess / downside_stdev * sqrt(252) — penalty nur fuer downside."""
    if len(daily_returns) < 2: return 0.0
    excess = [r - rf_rate / TRADING_DAYS_PER_YEAR for r in daily_returns]
    mean = sum(excess) / len(excess)
    downside = [min(0, e) for e in excess]
    if not any(downside): return float('inf') if mean > 0 else 0.0
    dsd = math.sqrt(sum(d ** 2 for d in downside) / len(downside))
    if dsd == 0: return 0.0
    return (mean / dsd) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _compute_max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    """Returns (max_dd_pct, current_dd_pct).
    equity_curve = cumulative balance over time."""
    if not equity_curve: return 0.0, 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
    current_peak = max(equity_curve)
    current_dd = (current_peak - equity_curve[-1]) / current_peak * 100 if current_peak > 0 else 0
    return round(max_dd, 2), round(current_dd, 2)


def _compute_calmar(annualized_return_pct: float, max_dd_pct: float) -> float:
    """Calmar = Annualized Return / Max Drawdown"""
    if max_dd_pct <= 0: return 0.0
    return annualized_return_pct / max_dd_pct


def _build_equity_curve(c: sqlite3.Connection, days: int) -> list[tuple[str, float]]:
    """Rekonstruiert die Equity-Curve aus closed Trades.
    Returns [(date, cumulative_balance)] — startet bei 25.000 Paper-Capital.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    rows = c.execute(
        "SELECT close_date, pnl_eur FROM paper_portfolio "
        "WHERE status IN ('WIN','LOSS','CLOSED') AND close_date >= ? "
        "AND pnl_eur IS NOT NULL ORDER BY close_date ASC",
        (cutoff,)
    ).fetchall()
    if not rows: return []
    # Aggregate per day
    daily_pnl = defaultdict(float)
    for r in rows:
        date = (r[0] or '')[:10]
        if date: daily_pnl[date] += float(r[1] or 0)
    # Build cumulative curve
    starting_capital = 25000.0
    equity = starting_capital
    curve = []
    for date in sorted(daily_pnl):
        equity += daily_pnl[date]
        curve.append((date, equity))
    return curve


def _daily_returns_from_curve(curve: list[tuple[str, float]]) -> list[float]:
    """Returns als pct vom Vortag."""
    if len(curve) < 2: return []
    out = []
    for i in range(1, len(curve)):
        prev = curve[i-1][1]
        curr = curve[i][1]
        if prev > 0:
            out.append((curr - prev) / prev)
    return out


def _compute_window(c: sqlite3.Connection, days: int) -> dict:
    """Berechnet KPIs fuer ein Zeitfenster."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    rows = c.execute(
        "SELECT pnl_eur, status FROM paper_portfolio "
        "WHERE status IN ('WIN','LOSS','CLOSED') AND close_date >= ? "
        "AND pnl_eur IS NOT NULL", (cutoff,)
    ).fetchall()
    if not rows: return {'n': 0}

    pnls = [float(r[0] or 0) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    n_wins, n_losses = len(wins), len(losses)
    sum_w = sum(wins); sum_l = abs(sum(losses))

    wr = _safe_div(n_wins, n) * 100
    avg_win = _safe_div(sum_w, n_wins)
    avg_loss = _safe_div(abs(sum(losses)), n_losses)
    profit_factor = _safe_div(sum_w, sum_l, default=float('inf') if sum_w > 0 else 0)
    expectancy = (wr / 100) * avg_win - (n_losses / n if n else 0) * avg_loss

    # Equity-Curve + Sharpe/Sortino/Drawdown
    curve = _build_equity_curve(c, days)
    daily_rets = _daily_returns_from_curve(curve)
    sharpe = _compute_sharpe(daily_rets)
    sortino = _compute_sortino(daily_rets)
    max_dd, current_dd = _compute_max_drawdown([v for _, v in curve])

    # Annualized Return
    if len(curve) >= 2:
        start_eq, end_eq = curve[0][1], curve[-1][1]
        period_return_pct = (end_eq - start_eq) / start_eq * 100 if start_eq else 0
        days_span = len(curve)
        annualized_pct = period_return_pct * (TRADING_DAYS_PER_YEAR / max(days_span, 1))
    else:
        period_return_pct = 0; annualized_pct = 0

    calmar = _compute_calmar(annualized_pct, max_dd)

    return {
        'n_trades': n, 'wins': n_wins, 'losses': n_losses,
        'win_rate_pct': round(wr, 1),
        'avg_win': round(avg_win, 2), 'avg_loss': round(avg_loss, 2),
        'pnl_total_eur': round(sum(pnls), 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
        'expectancy_eur': round(expectancy, 2),
        'sharpe': round(sharpe, 2),
        'sortino': round(sortino, 2) if sortino != float('inf') else 'inf',
        'calmar': round(calmar, 2),
        'max_drawdown_pct': max_dd,
        'current_drawdown_pct': current_dd,
        'period_return_pct': round(period_return_pct, 2),
        'annualized_return_pct': round(annualized_pct, 2),
    }


def _compute_per_strategy(c: sqlite3.Connection) -> list[dict]:
    """Stats pro Strategy (lifetime)."""
    rows = c.execute(
        "SELECT strategy, COUNT(*) as n, "
        "       SUM(CASE WHEN pnl_eur>0 THEN 1 ELSE 0 END) as wins, "
        "       SUM(pnl_eur) as pnl_total, "
        "       SUM(CASE WHEN pnl_eur>0 THEN pnl_eur ELSE 0 END) as sum_wins, "
        "       SUM(CASE WHEN pnl_eur<0 THEN pnl_eur ELSE 0 END) as sum_losses "
        "FROM paper_portfolio "
        "WHERE status IN ('WIN','LOSS','CLOSED') "
        "GROUP BY strategy HAVING n >= 2 ORDER BY pnl_total DESC"
    ).fetchall()
    out = []
    for r in rows:
        n, wins, pnl_total, sw, sl = r[1], r[2], r[3], r[4], r[5]
        wr = (100 * wins / n) if n else 0
        pf = abs(sw / sl) if sl else (float('inf') if sw > 0 else 0)
        avg_win = sw / wins if wins else 0
        n_losses = n - wins
        avg_loss = abs(sl) / n_losses if n_losses else 0
        expect = (wr/100) * avg_win - ((n_losses/n) if n else 0) * avg_loss
        out.append({
            'strategy': r[0], 'n_trades': n, 'wins': wins, 'losses': n - wins,
            'win_rate_pct': round(wr, 1),
            'pnl_total_eur': round(pnl_total or 0, 2),
            'profit_factor': round(pf, 2) if pf != float('inf') else 'inf',
            'expectancy_eur': round(expect, 2),
            'verdict': _verdict_for_strategy(n, wr, pnl_total, expect, pf),
        })
    return out


def _verdict_for_strategy(n, wr, pnl, expect, pf) -> str:
    if n < 5: return 'INSUFFICIENT_DATA'
    if pnl < -100 and expect < 0: return 'NEGATIVE_EDGE'
    if wr < 35: return 'LOW_WR'
    if pf == 'inf' or pf >= 2.0: return 'STRONG_EDGE'
    if pf >= 1.3: return 'MODERATE_EDGE'
    if pf >= 1.0: return 'MARGINAL'
    return 'NEGATIVE_EDGE'


def _verdict_for_overall(metrics: dict) -> str:
    """Mission-bezogenes Verdict basierend auf Sharpe + DD."""
    sharpe = metrics.get('sharpe', 0)
    max_dd = metrics.get('max_drawdown_pct', 100)
    if metrics.get('n_trades', 0) < 10:
        return f'INSUFFICIENT_DATA (n={metrics.get("n_trades",0)})'
    if sharpe >= 2.0 and max_dd < 10:
        return f'MISSION_TARGET_MET (Sharpe {sharpe}, DD {max_dd}%)'
    if sharpe >= 1.5:
        return f'GOOD_BUT_BELOW_MISSION (Sharpe {sharpe}/2.0)'
    if sharpe >= 1.0:
        return f'OK_PROGRESS (Sharpe {sharpe})'
    if sharpe > 0:
        return f'WEAK (Sharpe {sharpe})'
    return f'POOR (Sharpe {sharpe})'


def run() -> dict:
    if not DB.exists(): return {'error': 'no_db'}
    c = sqlite3.connect(str(DB))

    out = {
        'ts': _now(),
        'mission_targets': {
            'sharpe_min': 2.0,
            'max_drawdown_max_pct': 10.0,
            'win_rate_min_pct': 55.0,
            'calmar_min': 3.0,
        },
        'last_30d': _compute_window(c, 30),
        'last_90d': _compute_window(c, 90),
        'all_time': _compute_window(c, 9999),
        'per_strategy': _compute_per_strategy(c),
    }
    out['mission_verdict_30d'] = _verdict_for_overall(out['last_30d'])
    out['mission_verdict_all_time'] = _verdict_for_overall(out['all_time'])
    c.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(),
                              'sharpe_30d': out['last_30d'].get('sharpe'),
                              'sharpe_all_time': out['all_time'].get('sharpe'),
                              'max_dd_30d': out['last_30d'].get('max_drawdown_pct'),
                              'max_dd_all_time': out['all_time'].get('max_drawdown_pct'),
                              'verdict_30d': out['mission_verdict_30d'],
                              'verdict_all_time': out['mission_verdict_all_time']},
                             ensure_ascii=False) + '\n')

    return out


def main() -> int:
    r = run()
    if 'error' in r:
        print(f'Error: {r["error"]}'); return 1
    print(f'═══ Quant-Metrics @ {r["ts"][:16]} ═══')
    print(f'\nMISSION-VERDICT:')
    print(f'  30d:      {r["mission_verdict_30d"]}')
    print(f'  All-time: {r["mission_verdict_all_time"]}')
    for w_name in ('last_30d','last_90d','all_time'):
        m = r[w_name]
        print(f'\n{w_name}:')
        if m.get('n_trades', 0) == 0:
            print('  (keine Trades in Fenster)'); continue
        print(f'  Trades: {m["n_trades"]} ({m["wins"]}W/{m["losses"]}L), WR {m["win_rate_pct"]}%')
        print(f'  PnL:    {m["pnl_total_eur"]:+.0f}EUR, AvgWin {m["avg_win"]:+.0f}, AvgLoss {m["avg_loss"]:.0f}')
        print(f'  Sharpe: {m["sharpe"]} | Sortino: {m["sortino"]} | Calmar: {m["calmar"]}')
        print(f'  MaxDD:  {m["max_drawdown_pct"]}% | CurrentDD: {m["current_drawdown_pct"]}%')
        print(f'  Profit-Factor: {m["profit_factor"]} | Expectancy: {m["expectancy_eur"]:+.2f}EUR/Trade')
    print(f'\nPer-Strategy ({len(r["per_strategy"])} mit n>=2):')
    for s in r['per_strategy'][:15]:
        print(f"  {s['strategy']:<14} n={s['n_trades']:>3} WR {s['win_rate_pct']:>5.1f}% "
              f"PnL {s['pnl_total_eur']:>+8.0f} PF {str(s['profit_factor']):>5} "
              f"Exp {s['expectancy_eur']:>+7.0f} → {s['verdict']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
