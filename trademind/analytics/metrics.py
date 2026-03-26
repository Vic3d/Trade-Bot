"""
trademind/analytics/metrics.py — Professionelle Performance-Metriken

Berechnet für eine Liste von Trades:
    Sharpe, Sortino, Max Drawdown, Calmar, Profit Factor, Expected Value, ...

Alle Berechnungen basieren auf pnl_eur / pnl_pct aus den Trades.
"""
import math
from typing import Optional


def _max_drawdown(equity_curve: list[float]) -> tuple[float, float, int]:
    """
    Berechnet Max Drawdown in absoluten Werten und Prozent, plus Dauer in Tagen.
    
    Returns:
        (max_dd_eur, max_dd_pct, max_dd_duration_days)
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0, 0.0, 0

    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    
    # Duration tracking
    peak_idx = 0
    max_dd_duration = 0
    current_dd_start = 0

    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            peak_idx = i
            current_dd_start = i
        
        dd = peak - val
        if peak > 0:
            dd_pct = dd / peak
        else:
            dd_pct = 0.0
        
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
            # Duration = wie lange seit Peak
            max_dd_duration = i - peak_idx

    return max_dd, max_dd_pct * 100, max_dd_duration


def calculate_strategy_metrics(trades: list[dict]) -> dict:
    """
    Berechnet professionelle Metriken für eine Liste von Trades.
    
    Input: Liste von Trades mit mindestens:
        - pnl_eur (float): P&L in Euro
        - pnl_pct (float): P&L in Prozent (0.05 = 5% oder 5.0 = 5%)
        - entry_date (str): Entry-Datum
        - exit_date (str, optional): Exit-Datum
        - holding_days (int, optional): Haltezeit in Tagen
    
    Returns: Dict mit allen Metriken
    """
    if not trades:
        return _empty_metrics()

    # ── Daten extrahieren ────────────────────────────────────────────────────
    pnl_eur_list = []
    pnl_pct_list = []
    hold_days_list = []

    for t in trades:
        pnl_e = t.get("pnl_eur") or 0.0
        pnl_p = t.get("pnl_pct") or 0.0
        
        # Normalisierung: manche DBs speichern 0.05 statt 5.0
        # Wenn alle Werte < 1.0 und keine 0, nehmen wir an es sind Dezimal-Prozent
        if pnl_p != 0 and abs(pnl_p) < 0.5:
            pnl_p = pnl_p * 100  # 0.05 → 5%

        pnl_eur_list.append(float(pnl_e))
        pnl_pct_list.append(float(pnl_p))
        
        hd = t.get("holding_days") or 1
        hold_days_list.append(max(int(hd), 1))

    n = len(pnl_eur_list)
    
    # ── Basismetriken ────────────────────────────────────────────────────────
    wins    = [p for p in pnl_eur_list if p > 0]
    losses  = [p for p in pnl_eur_list if p < 0]
    
    win_rate   = len(wins) / n if n > 0 else 0.0
    avg_win    = sum(wins) / len(wins) if wins else 0.0
    avg_loss   = abs(sum(losses) / len(losses)) if losses else 0.0
    total_pnl  = sum(pnl_eur_list)
    avg_hold   = sum(hold_days_list) / n

    # ── Sharpe Ratio (annualisiert) ──────────────────────────────────────────
    # Annualisierung: avg_hold_days → Trades/Jahr schätzen
    mean_ret  = sum(pnl_pct_list) / n
    if n > 1:
        variance  = sum((r - mean_ret) ** 2 for r in pnl_pct_list) / (n - 1)
        std_ret   = math.sqrt(variance)
    else:
        std_ret = 0.0

    # Annualisierungsfaktor: Trades/Jahr
    avg_hold_safe = max(avg_hold, 1.0)
    trades_per_year = 252 / avg_hold_safe  # 252 Handelstage
    annualization   = math.sqrt(trades_per_year)

    sharpe = (mean_ret / std_ret * annualization) if std_ret > 0 else 0.0

    # ── Sortino Ratio ────────────────────────────────────────────────────────
    downside_returns = [r for r in pnl_pct_list if r < 0]
    if len(downside_returns) > 1:
        downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_var)
    elif len(downside_returns) == 1:
        downside_std = abs(downside_returns[0])
    else:
        downside_std = 0.0

    sortino = (mean_ret / downside_std * annualization) if downside_std > 0 else (
        float('inf') if mean_ret > 0 else 0.0
    )

    # ── Max Drawdown (Equity Curve in EUR) ───────────────────────────────────
    equity_curve = []
    running = 0.0
    for p in pnl_eur_list:
        running += p
        equity_curve.append(running)

    max_dd_eur, max_dd_pct, max_dd_dur = _max_drawdown(equity_curve)
    
    # ── Calmar Ratio ─────────────────────────────────────────────────────────
    # Annualisierte Rendite / Max Drawdown
    annual_return = mean_ret * trades_per_year
    calmar = (annual_return / max_dd_pct) if max_dd_pct > 0 else (
        float('inf') if annual_return > 0 else 0.0
    )

    # ── Profit Factor ────────────────────────────────────────────────────────
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
        float('inf') if gross_profit > 0 else 0.0
    )

    # ── Expected Value ────────────────────────────────────────────────────────
    expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # ── Win/Loss Ratio ────────────────────────────────────────────────────────
    win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else float('inf')

    return {
        'sharpe_ratio':       round(sharpe, 3),
        'sortino_ratio':      round(sortino, 3) if not math.isinf(sortino) else 99.99,
        'max_drawdown_eur':   round(max_dd_eur, 2),
        'max_drawdown_pct':   round(max_dd_pct, 2),
        'max_dd_duration_days': max_dd_dur,
        'calmar_ratio':       round(calmar, 3) if not math.isinf(calmar) else 99.99,
        'profit_factor':      round(profit_factor, 3) if not math.isinf(profit_factor) else 99.99,
        'expected_value':     round(expected_value, 2),
        'win_loss_ratio':     round(win_loss_ratio, 3) if not math.isinf(win_loss_ratio) else 99.99,
        'win_rate':           round(win_rate, 4),
        'total_trades':       n,
        'total_pnl':          round(total_pnl, 2),
        'avg_hold_days':      round(avg_hold, 1),
        'best_trade':         round(max(pnl_eur_list), 2),
        'worst_trade':        round(min(pnl_eur_list), 2),
    }


def _empty_metrics() -> dict:
    return {
        'sharpe_ratio': 0.0,
        'sortino_ratio': 0.0,
        'max_drawdown_eur': 0.0,
        'max_drawdown_pct': 0.0,
        'max_dd_duration_days': 0,
        'calmar_ratio': 0.0,
        'profit_factor': 0.0,
        'expected_value': 0.0,
        'win_loss_ratio': 0.0,
        'win_rate': 0.0,
        'total_trades': 0,
        'total_pnl': 0.0,
        'avg_hold_days': 0.0,
        'best_trade': 0.0,
        'worst_trade': 0.0,
    }
