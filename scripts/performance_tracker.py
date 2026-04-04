#!/usr/bin/env python3.13
"""
performance_tracker.py — Live Performance Metrics
===================================================
Berechnet täglich:
  - Drawdown (aktuell + max)
  - Sharpe Ratio
  - Calmar Ratio
  - Win-Rate (gleitend 20/50 Trades)
  - Trade Quality Score (war Entry-Logik richtig?)

Schreibt in trading.db:performance_metrics (täglich)
Sendet Discord-Alert wenn Drawdown > 15%
"""
import sqlite3
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'core'))

WS   = Path('/data/.openclaw/workspace')
DB   = WS / 'data/trading.db'


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


# ─── Schema ──────────────────────────────────────────────────────────────────

def ensure_schema():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS performance_metrics (
            date          TEXT PRIMARY KEY,
            total_pnl     REAL,
            drawdown_pct  REAL,
            max_drawdown  REAL,
            sharpe        REAL,
            calmar        REAL,
            win_rate_20   REAL,
            win_rate_50   REAL,
            win_rate_all  REAL,
            avg_quality   REAL,
            open_trades   INTEGER,
            closed_trades INTEGER,
            ts            TEXT
        )
    ''')
    conn.commit()
    conn.close()


# ─── Drawdown ─────────────────────────────────────────────────────────────────

def calc_drawdown(pnl_series: list[float]) -> tuple[float, float]:
    """
    Berechnet aktuellen und maximalen Drawdown aus P&L-Zeitreihe.
    Returns: (current_drawdown_pct, max_drawdown_pct)
    """
    if not pnl_series:
        return 0.0, 0.0

    capital = 25000.0
    equity = [capital + sum(pnl_series[:i+1]) for i in range(len(pnl_series))]

    peak = capital
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Aktueller Drawdown
    current_peak = max(equity)
    current_dd = (current_peak - equity[-1]) / current_peak * 100 if current_peak > 0 else 0

    return round(current_dd, 2), round(max_dd, 2)


# ─── Sharpe Ratio ─────────────────────────────────────────────────────────────

def calc_sharpe(returns: list[float], risk_free: float = 0.04) -> float:
    """
    Annualisierte Sharpe Ratio aus Trade-Returns.
    Returns: Sharpe Ratio (0.0 wenn zu wenig Daten)
    """
    if len(returns) < 5:
        return 0.0

    n = len(returns)
    avg = sum(returns) / n
    variance = sum((r - avg) ** 2 for r in returns) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance) if variance > 0 else 0

    if std == 0:
        return 0.0

    # Daily risk-free rate
    daily_rf = risk_free / 252
    sharpe = (avg - daily_rf) / std * math.sqrt(252)
    return round(sharpe, 2)


# ─── Calmar Ratio ─────────────────────────────────────────────────────────────

def calc_calmar(annualized_return: float, max_drawdown: float) -> float:
    """
    Calmar Ratio = Annualized Return / Max Drawdown
    > 1.0 = gut, > 2.0 = sehr gut
    """
    if max_drawdown <= 0:
        return 0.0
    return round(annualized_return / max_drawdown, 2)


# ─── Trade Quality Score ──────────────────────────────────────────────────────

def calc_trade_quality(trade: sqlite3.Row) -> float:
    """
    Bewertet ob die Entry-Logik korrekt war — unabhängig vom Ergebnis.
    
    Score 0-100:
    - Conviction >= 65: +25
    - RSI 30-60 bei Entry: +20 (nicht überkauft)
    - CRV >= 2.0: +20
    - Regime NEUTRAL/BULL: +20
    - Stop korrekt gesetzt (< Entry): +15
    
    Ein Trade kann eine gute Entry-Logik haben und trotzdem verlieren.
    Ein Trade kann eine schlechte Entry-Logik haben und trotzdem gewinnen.
    Nur gute Logik führt langfristig zu Gewinnen.
    """
    score = 0

    conviction = trade['conviction'] or 0
    rsi = trade['rsi_at_entry']
    regime = trade['regime_at_entry'] or 'UNKNOWN'
    entry = trade['entry_price'] or 0
    stop  = trade['stop_price'] or 0
    target = trade['target_price'] or 0

    # Conviction
    if conviction >= 65:
        score += 25
    elif conviction >= 50:
        score += 15
    elif conviction >= 35:
        score += 5

    # RSI-Qualität
    if rsi is not None:
        if 30 <= rsi <= 60:
            score += 20
        elif 25 <= rsi <= 70:
            score += 10

    # CRV
    if entry > 0 and stop > 0 and target > 0:
        risk   = abs(entry - stop)
        reward = abs(target - entry)
        crv = reward / risk if risk > 0 else 0
        if crv >= 2.0:
            score += 20
        elif crv >= 1.5:
            score += 12
        elif crv >= 1.0:
            score += 5

    # Regime
    if regime in ('BULL_CALM', 'BULL_VOLATILE'):
        score += 20
    elif regime in ('NEUTRAL', 'CORRECTION'):
        score += 15
    elif regime in ('BEAR', 'CRISIS'):
        score += 0  # In BEAR/CRISIS sollte man nicht kaufen

    # Stop gesetzt und korrekt
    if stop > 0 and entry > 0 and stop < entry:
        score += 15

    return round(min(score, 100), 1)


# ─── Hauptberechnung ──────────────────────────────────────────────────────────

def calculate_metrics() -> dict:
    conn = get_db()

    # Alle closed Trades chronologisch
    trades = conn.execute('''
        SELECT id, ticker, strategy, entry_price, stop_price, target_price,
               close_price, pnl_eur, pnl_pct, close_date, entry_date,
               conviction, rsi_at_entry, regime_at_entry, style
        FROM paper_portfolio
        WHERE status != 'OPEN' AND close_date IS NOT NULL
        ORDER BY close_date ASC
    ''').fetchall()

    open_count = conn.execute(
        "SELECT COUNT(*) FROM paper_portfolio WHERE status='OPEN'"
    ).fetchone()[0]

    conn.close()

    if not trades:
        return {'error': 'Keine closed Trades'}

    pnl_series = [t['pnl_eur'] for t in trades if t['pnl_eur'] is not None]
    returns    = [t['pnl_pct'] / 100 for t in trades if t['pnl_pct'] is not None]

    total_pnl = sum(pnl_series)
    n = len(trades)
    wins = sum(1 for t in trades if (t['pnl_eur'] or 0) > 0)

    # Drawdown
    dd_current, dd_max = calc_drawdown(pnl_series)

    # Sharpe
    sharpe = calc_sharpe(returns)

    # Annualisierte Rendite (approximiert)
    try:
        first = datetime.fromisoformat(str(trades[0]['close_date'])[:19])
        last  = datetime.fromisoformat(str(trades[-1]['close_date'])[:19])
        days  = max((last - first).days, 1)
        ann_return = (total_pnl / 25000) * (365 / days) * 100
    except Exception:
        ann_return = 0

    calmar = calc_calmar(ann_return, dd_max)

    # Rolling Win-Rate
    last_20 = [t for t in trades[-20:] if t['pnl_eur'] is not None]
    last_50 = [t for t in trades[-50:] if t['pnl_eur'] is not None]
    wr_20  = round(sum(1 for t in last_20 if t['pnl_eur'] > 0) / len(last_20) * 100, 1) if last_20 else 0
    wr_50  = round(sum(1 for t in last_50 if t['pnl_eur'] > 0) / len(last_50) * 100, 1) if last_50 else 0
    wr_all = round(wins / n * 100, 1)

    # Trade Quality
    qualities = [calc_trade_quality(t) for t in trades[-30:]]
    avg_quality = round(sum(qualities) / len(qualities), 1) if qualities else 0

    # Pending Setups (warte auf Trigger)
    try:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM pending_setups WHERE status='WATCHING'"
        ).fetchone()[0]
        triggered_today = conn.execute(
            "SELECT COUNT(*) FROM pending_setups WHERE status='TRIGGERED' "
            "AND DATE(updated_at)=DATE('now')"
        ).fetchone()[0]
    except Exception:
        pending_count = 0
        triggered_today = 0

    return {
        'date':             datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'total_pnl':        round(total_pnl, 2),
        'pending_setups':   pending_count,
        'triggered_today':  triggered_today,
        'drawdown_pct':     dd_current,
        'max_drawdown':  dd_max,
        'sharpe':        sharpe,
        'calmar':        calmar,
        'win_rate_20':   wr_20,
        'win_rate_50':   wr_50,
        'win_rate_all':  wr_all,
        'avg_quality':   avg_quality,
        'open_trades':   open_count,
        'closed_trades': n,
        'ann_return':    round(ann_return, 1),
    }


def save_metrics(m: dict):
    conn = get_db()
    ensure_schema()
    conn.execute('''
        INSERT OR REPLACE INTO performance_metrics
        (date, total_pnl, drawdown_pct, max_drawdown, sharpe, calmar,
         win_rate_20, win_rate_50, win_rate_all, avg_quality, open_trades, closed_trades, ts)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        m['date'], m['total_pnl'], m['drawdown_pct'], m['max_drawdown'],
        m['sharpe'], m['calmar'], m['win_rate_20'], m['win_rate_50'],
        m['win_rate_all'], m['avg_quality'], m['open_trades'], m['closed_trades'],
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()


def send_discord_alert(m: dict):
    """Sendet Alert wenn Drawdown kritisch oder Win-Rate fällt."""
    alerts = []

    if m['max_drawdown'] > 15:
        alerts.append(f"🚨 MAX DRAWDOWN {m['max_drawdown']:.1f}% — kritisch! Strategie überprüfen.")
    elif m['max_drawdown'] > 10:
        alerts.append(f"⚠️ Drawdown {m['max_drawdown']:.1f}% — erhöhtes Risiko.")

    if m['win_rate_20'] < 40 and m['closed_trades'] >= 20:
        alerts.append(f"⚠️ Win-Rate (letzte 20): {m['win_rate_20']}% — unter Alarmschwelle 40%!")

    if m['avg_quality'] < 50:
        alerts.append(f"⚠️ Trade-Qualität: {m['avg_quality']}/100 — Entry-Logik prüfen!")

    if not alerts:
        return

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from discord_sender import send
        msg = (
            f"📊 **Performance Alert**\n"
            + "\n".join(alerts)
            + f"\n\nStats: WR {m['win_rate_all']}% | P&L +{m['total_pnl']:.0f}€ | "
              f"DD {m['drawdown_pct']:.1f}% | Sharpe {m['sharpe']}"
        )
        send(msg)
    except Exception:
        pass


def print_report(m: dict):
    print(f"\n📊 TradeMind Performance — {m['date']}")
    print(f"{'─'*45}")
    print(f"  P&L gesamt:      +{m['total_pnl']:.0f}€ ({m['ann_return']:.1f}% ann.)")
    print(f"  Win-Rate:        {m['win_rate_all']}% (gesamt) | {m['win_rate_20']}% (letzte 20) | {m['win_rate_50']}% (letzte 50)")
    print(f"  Drawdown:        {m['drawdown_pct']:.1f}% aktuell | {m['max_drawdown']:.1f}% max")
    print(f"  Sharpe:          {m['sharpe']}")
    print(f"  Calmar:          {m['calmar']}")
    print(f"  Trade-Qualität:  {m['avg_quality']}/100 (letzte 30 Trades)")
    print(f"  Trades:          {m['closed_trades']} closed | {m['open_trades']} offen")

    # Bewertung
    score = 0
    if m['win_rate_all'] >= 60: score += 30
    elif m['win_rate_all'] >= 50: score += 20
    elif m['win_rate_all'] >= 45: score += 10
    if m['max_drawdown'] <= 10: score += 20
    elif m['max_drawdown'] <= 15: score += 10
    if m['sharpe'] >= 1.5: score += 20
    elif m['sharpe'] >= 1.0: score += 10
    if m['avg_quality'] >= 70: score += 15
    elif m['avg_quality'] >= 50: score += 8
    if m['closed_trades'] >= 200: score += 15
    elif m['closed_trades'] >= 100: score += 8

    status = "🟢 STARK" if score >= 70 else "🟡 ENTWICKLUNG" if score >= 45 else "🔴 SCHWACH"
    print(f"  System-Score:    {score}/100 — {status}")
    print()


if __name__ == '__main__':
    ensure_schema()
    m = calculate_metrics()
    if 'error' not in m:
        save_metrics(m)
        print_report(m)
        send_discord_alert(m)
    else:
        print(m['error'])
