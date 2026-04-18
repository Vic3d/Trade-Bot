#!/usr/bin/env python3
"""
Strategy DNA — Lernende Strategie-Analyse
==========================================
Per-Strategy & Per-Regime Metriken, Trader-Profil,
Kill-Trigger, Evolution Tracking.

Sprint 3 | TradeMind Bauplan
"""

import sqlite3, json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def check_dna_gate(strategy: str, regime: str = '') -> dict:
    """P2.11 — DNA-Gate für Pre-Trade Validierung.

    Returns: {
        'score': 0-100,           # DNA-Score (höher = besser)
        'verdict': 'PASS|HALVE|BLOCK',
        'reason': str,
        'trades': int,
    }

    Logik:
      - <10 closed trades → PASS (zu wenig Daten, score=50)
      - WR ≥ 45% & Expectancy > 0 → PASS (score=70+)
      - WR 30-45% oder Expectancy <= 0 → HALVE (size_factor=0.5)
      - WR < 30% mit 10+ trades → BLOCK
      - Falls regime gegeben: Regime-Mismatch (regime-WR < 25%, ≥4 trades) → BLOCK
    """
    sid = (strategy or '').upper()
    if not sid:
        return {'score': 50, 'verdict': 'PASS', 'reason': 'no strategy', 'trades': 0}
    try:
        conn = get_db()
        row = conn.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) AS losses,
                   AVG(CASE WHEN status='WIN' THEN pnl_pct END) AS avg_win,
                   AVG(CASE WHEN status='LOSS' THEN pnl_pct END) AS avg_loss,
                   SUM(CASE WHEN status IN ('WIN','LOSS') THEN pnl_eur ELSE 0 END) AS pnl_eur
            FROM trades
            WHERE UPPER(strategy)=? AND status IN ('WIN','LOSS')
        """, (sid,)).fetchone()
        regime_row = None
        if regime:
            regime_row = conn.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) AS wins
                FROM trades
                WHERE UPPER(strategy)=? AND UPPER(regime_at_entry)=?
                  AND status IN ('WIN','LOSS')
            """, (sid, regime.upper())).fetchone()
        conn.close()
    except Exception as e:
        return {'score': 50, 'verdict': 'PASS', 'reason': f'dna db error: {e}', 'trades': 0}

    closed = (row['total'] or 0) if row else 0
    if closed < 10:
        return {'score': 50, 'verdict': 'PASS',
                'reason': f'insufficient history ({closed}<10 trades)', 'trades': closed}

    wins = row['wins'] or 0
    wr = wins / closed if closed else 0
    avg_win = row['avg_win'] or 0
    avg_loss = row['avg_loss'] or 0
    expectancy = avg_win * wr + avg_loss * (1 - wr)
    pnl = row['pnl_eur'] or 0

    # Score-Komposition: WR (60pt) + Expectancy (25pt) + PnL-Sign (15pt)
    score = round(min(100, max(0, wr * 100 * 0.6 + max(-25, min(25, expectancy * 10)) + (15 if pnl > 0 else -10))))

    # Regime-Mismatch Hard-Block
    if regime_row and (regime_row['total'] or 0) >= 4:
        rwr = (regime_row['wins'] or 0) / regime_row['total']
        if rwr < 0.25:
            return {'score': score, 'verdict': 'BLOCK',
                    'reason': f"DNA: regime '{regime}' WR {rwr:.0%} < 25% (n={regime_row['total']})",
                    'trades': closed}

    if wr < 0.30:
        return {'score': score, 'verdict': 'BLOCK',
                'reason': f'DNA: WR {wr:.0%} < 30% (n={closed}, PnL {pnl:+.0f}€)', 'trades': closed}
    if wr < 0.45 or expectancy <= 0 or pnl < 0:
        return {'score': score, 'verdict': 'HALVE',
                'reason': f'DNA: WR {wr:.0%}, Exp {expectancy:+.2f}%, PnL {pnl:+.0f}€', 'trades': closed}
    return {'score': score, 'verdict': 'PASS',
            'reason': f'DNA: WR {wr:.0%}, Exp {expectancy:+.2f}%, PnL {pnl:+.0f}€', 'trades': closed}


def strategy_metrics():
    """Berechnet Metriken pro Strategie."""
    conn = get_db()
    strategies = conn.execute("""
        SELECT strategy, 
               COUNT(*) as total,
               SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) as losses,
               SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open_count,
               AVG(CASE WHEN status IN ('WIN','LOSS') THEN pnl_pct END) as avg_pnl,
               AVG(CASE WHEN status='WIN' THEN pnl_pct END) as avg_win,
               AVG(CASE WHEN status='LOSS' THEN pnl_pct END) as avg_loss,
               SUM(CASE WHEN status IN ('WIN','LOSS') THEN pnl_eur ELSE 0 END) as total_pnl,
               AVG(crv) as avg_crv,
               AVG(holding_days) as avg_hold
        FROM trades
        GROUP BY strategy
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    
    results = []
    for s in strategies:
        closed = (s['wins'] or 0) + (s['losses'] or 0)
        wr = (s['wins'] / closed * 100) if closed > 0 else 0
        
        # Expectancy
        avg_win = s['avg_win'] or 0
        avg_loss = s['avg_loss'] or 0
        expectancy = avg_win * wr/100 + avg_loss * (1 - wr/100) if closed > 0 else 0
        
        # Kill Trigger: WR < 35% über 10+ Trades
        kill_warning = closed >= 10 and wr < 35
        
        results.append({
            'strategy': s['strategy'] or 'unknown',
            'total': s['total'],
            'open': s['open_count'] or 0,
            'closed': closed,
            'wins': s['wins'] or 0,
            'losses': s['losses'] or 0,
            'win_rate': round(wr, 1),
            'avg_pnl': round(s['avg_pnl'] or 0, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'total_pnl': round(s['total_pnl'] or 0, 2),
            'expectancy': round(expectancy, 2),
            'avg_crv': round(s['avg_crv'] or 0, 1),
            'avg_hold_days': round(s['avg_hold'] or 0, 1),
            'kill_warning': kill_warning,
        })
    
    return results


def regime_strategy_matrix():
    """Win-Rate Matrix: Strategie × Regime."""
    conn = get_db()
    rows = conn.execute("""
        SELECT strategy, regime_at_entry,
               COUNT(*) as total,
               SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
               AVG(pnl_pct) as avg_pnl
        FROM trades
        WHERE status IN ('WIN','LOSS') AND regime_at_entry IS NOT NULL
        GROUP BY strategy, regime_at_entry
    """).fetchall()
    conn.close()
    
    matrix = defaultdict(dict)
    for r in rows:
        wr = r['wins'] / r['total'] * 100 if r['total'] > 0 else 0
        matrix[r['strategy']][r['regime_at_entry']] = {
            'trades': r['total'],
            'win_rate': round(wr, 1),
            'avg_pnl': round(r['avg_pnl'] or 0, 2),
        }
    
    return dict(matrix)


def trader_profile():
    """Analysiert Trader-Verhalten: Timing, Revenge Trading, Disziplin."""
    conn = get_db()
    
    # Konsekutive Verluste
    trades = conn.execute("""
        SELECT id, ticker, pnl_eur, status, entry_date, exit_date 
        FROM trades WHERE status IN ('WIN','LOSS') ORDER BY exit_date
    """).fetchall()
    
    max_consecutive_losses = 0
    current_streak = 0
    revenge_trades = 0
    
    for i, t in enumerate(trades):
        if t['status'] == 'LOSS':
            current_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_streak)
            # Revenge Trade: neuer Trade innerhalb 1 Tag nach Verlust
            if i + 1 < len(trades):
                next_t = trades[i + 1]
                if next_t['entry_date'] == t['exit_date'] and next_t['status'] == 'LOSS':
                    revenge_trades += 1
        else:
            current_streak = 0
    
    # Avg Holding Time für Wins vs Losses
    win_hold = conn.execute(
        "SELECT AVG(holding_days) FROM trades WHERE status='WIN' AND holding_days IS NOT NULL"
    ).fetchone()[0]
    loss_hold = conn.execute(
        "SELECT AVG(holding_days) FROM trades WHERE status='LOSS' AND holding_days IS NOT NULL"
    ).fetchone()[0]
    
    # Disziplin: wie oft wird Stop eingehalten?
    stop_exits = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE exit_type='STOP_HIT'"
    ).fetchone()[0]
    manual_exits = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE exit_type='MANUAL'"
    ).fetchone()[0]
    total_exits = stop_exits + manual_exits
    stop_discipline = (stop_exits / total_exits * 100) if total_exits > 0 else 0
    
    conn.close()
    
    return {
        'max_consecutive_losses': max_consecutive_losses,
        'revenge_trades': revenge_trades,
        'avg_win_hold_days': round(win_hold or 0, 1),
        'avg_loss_hold_days': round(loss_hold or 0, 1),
        'stop_discipline_pct': round(stop_discipline, 1),
        'total_closed': len(trades),
    }


def full_dna_report():
    """Kompletter Strategy DNA Report."""
    return {
        'strategies': strategy_metrics(),
        'regime_matrix': regime_strategy_matrix(),
        'trader_profile': trader_profile(),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


if __name__ == '__main__':
    report = full_dna_report()
    
    print("═══ Strategy DNA Report ═══\n")
    
    print("── Strategien ──")
    for s in report['strategies']:
        emoji = '🔴' if s['kill_warning'] else ('🟢' if s['win_rate'] >= 50 else '🟡')
        print(f"  {emoji} {s['strategy'] or 'unknown':6} | {s['total']:2}T ({s['open']}o/{s['closed']}c) | WR: {s['win_rate']:5.1f}% | E[]: {s['expectancy']:+.2f}% | PnL: {s['total_pnl']:+.0f}€ | CRV: {s['avg_crv']:.1f} | Hold: {s['avg_hold_days']:.0f}d")
        if s['kill_warning']:
            print(f"      ⚠️  KILL WARNING: WR < 35% über {s['closed']}+ Trades!")
    
    print("\n── Regime × Strategie ──")
    for strat, regimes in report['regime_matrix'].items():
        for regime, data in regimes.items():
            emoji = '✅' if data['win_rate'] >= 50 else '❌'
            print(f"  {emoji} {strat:6} × {regime:16} | {data['trades']}T | WR: {data['win_rate']}% | avg: {data['avg_pnl']:+.1f}%")
    
    print("\n── Trader-Profil ──")
    p = report['trader_profile']
    print(f"  Max Consecutive Losses: {p['max_consecutive_losses']}")
    print(f"  Revenge Trades: {p['revenge_trades']}")
    print(f"  Avg Hold (Win): {p['avg_win_hold_days']}d | Avg Hold (Loss): {p['avg_loss_hold_days']}d")
    print(f"  Stop-Disziplin: {p['stop_discipline_pct']}%")
