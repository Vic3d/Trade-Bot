#!/usr/bin/env python3
"""
Trade Journal v2 — Auto-Enrichment bei Entry + Exit
====================================================
Jeder Trade wird automatisch mit Kontext angereichert:
- VIX, Regime, Conviction bei Entry/Exit
- CRV, Position Size, Risk nach 2%-Regel
- Holding Days, Exit-Type bei Close
- News-Context (letzte 5 relevante News)

TRA-4 | Sprint 1 | TradeMind Bauplan
"""

import sqlite3, json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _get_vix(conn, date_str):
    """Holt VIX für ein Datum aus macro_daily."""
    r = conn.execute(
        "SELECT value FROM macro_daily WHERE indicator='VIX' AND date <= ? ORDER BY date DESC LIMIT 1",
        (date_str[:10],)
    ).fetchone()
    return r['value'] if r else None


def _get_regime(vix_val):
    """Leitet Regime aus VIX ab."""
    if not vix_val:
        return None
    if vix_val < 15: return 'BULL_CALM'
    if vix_val < 20: return 'BULL_VOLATILE'
    if vix_val < 25: return 'NEUTRAL'
    if vix_val < 30: return 'CORRECTION'
    if vix_val < 35: return 'BEAR'
    return 'CRISIS'


def _get_recent_news(conn, ticker, date_str, limit=5):
    """Holt die letzten News für einen Ticker."""
    rows = conn.execute("""
        SELECT headline, source, sentiment_label 
        FROM news_events 
        WHERE tickers LIKE ? AND created_at <= ?
        ORDER BY created_at DESC LIMIT ?
    """, (f'%{ticker}%', date_str, limit)).fetchall()
    if not rows:
        return None
    return json.dumps([{
        'headline': r['headline'],
        'source': r['source'],
        'sentiment': r['sentiment_label']
    } for r in rows])


def _calc_position_size(entry_price, stop_price, portfolio_value=14000, risk_pct=0.02):
    """2%-Regel: Max 2% Portfolio-Risiko pro Trade."""
    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0:
        return None, None
    max_risk = portfolio_value * risk_pct
    shares = int(max_risk / risk_per_share)
    position_eur = shares * entry_price
    return position_eur, max_risk


def open_trade(ticker, strategy, direction, entry_price, stop, target, shares=None,
               thesis='', trade_type='paper', conviction=None, signal_issue_id=None):
    """
    Eröffnet einen Trade mit automatischem Enrichment.
    
    Returns: trade_id
    """
    conn = get_db()
    now = datetime.now(timezone.utc)
    entry_date = now.strftime('%Y-%m-%d')
    
    # ─── Auto-Enrichment ───
    vix = _get_vix(conn, entry_date)
    regime = _get_regime(vix)
    
    # CRV
    crv = None
    risk_eur = None
    reward_eur = None
    if entry_price and stop and target:
        risk_per_share = abs(entry_price - stop)
        reward_per_share = abs(target - entry_price)
        if risk_per_share > 0:
            crv = round(reward_per_share / risk_per_share, 2)
            risk_eur = round(risk_per_share, 2)
            reward_eur = round(reward_per_share, 2)
    
    # Position Size (2%-Regel)
    position_size, max_risk = _calc_position_size(entry_price, stop)
    if shares is None and position_size:
        shares = int(position_size / entry_price)
    
    # News Context
    news_ctx = _get_recent_news(conn, ticker, entry_date)
    
    # ─── Insert ───
    c = conn.execute("""
        INSERT INTO trades (
            ticker, strategy, direction, entry_price, entry_date,
            stop, target, shares, status, thesis, trade_type,
            conviction_at_entry, regime_at_entry, vix_at_entry,
            crv, risk_eur, reward_eur, position_size_eur,
            signal_issue_id, news_context, fees_eur
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ticker.upper(), strategy, direction.upper(), entry_price, entry_date,
        stop, target, shares, 'OPEN', thesis, trade_type,
        conviction, regime, vix,
        crv, risk_eur, reward_eur, position_size,
        signal_issue_id, news_ctx, 1.0
    ))
    conn.commit()
    trade_id = c.lastrowid
    
    print(f"✅ Trade #{trade_id} eröffnet:")
    print(f"   {'📝 PAPER' if trade_type == 'paper' else '💰 REAL'} | {direction} {ticker} @ {entry_price:.2f}")
    print(f"   Stop: {stop:.2f} | Target: {target:.2f} | CRV: {crv or '?'}:1")
    print(f"   VIX: {vix or '?'} | Regime: {regime or '?'} | Conviction: {conviction or '?'}")
    if shares:
        print(f"   Shares: {shares} | Position: {position_size or '?'}€ | Max Risk: {max_risk or '?'}€")
    
    conn.close()
    return trade_id


def close_trade(trade_id, exit_price, result='', lessons='', exit_type=None):
    """
    Schließt einen Trade mit automatischem Enrichment.
    
    exit_type: STOP_HIT, TARGET, MANUAL, TRAILING (auto-detected wenn None)
    """
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade:
        print(f"❌ Trade #{trade_id} nicht gefunden")
        return None
    if trade['status'] != 'OPEN':
        print(f"⚠️  Trade #{trade_id} ist bereits {trade['status']}")
        return None
    
    now = datetime.now(timezone.utc)
    exit_date = now.strftime('%Y-%m-%d')
    entry_price = trade['entry_price']
    stop = trade['stop']
    target = trade['target']
    shares = trade['shares'] or 1
    direction = trade['direction']
    
    # ─── P&L ───
    if direction == 'LONG':
        pnl = (exit_price - entry_price) * shares
        pnl_pct = (exit_price / entry_price - 1) * 100
    else:
        pnl = (entry_price - exit_price) * shares
        pnl_pct = (1 - exit_price / entry_price) * 100
    
    # Gebühren abziehen (1€ Entry + 1€ Exit = 2€)
    pnl_after_fees = pnl - 2.0
    status = 'WIN' if pnl_after_fees > 0 else 'LOSS'
    
    # ─── Auto-Enrichment ───
    vix_exit = _get_vix(conn, exit_date)
    regime_exit = _get_regime(vix_exit)
    
    # Holding Days
    holding_days = None
    if trade['entry_date']:
        try:
            ed = datetime.strptime(trade['entry_date'][:10], '%Y-%m-%d')
            xd = datetime.strptime(exit_date[:10], '%Y-%m-%d')
            holding_days = (xd - ed).days
        except:
            pass
    
    # Exit Type Detection
    if not exit_type:
        if stop and exit_price <= stop * 1.005:
            exit_type = 'STOP_HIT'
        elif target and exit_price >= target * 0.995:
            exit_type = 'TARGET'
        else:
            exit_type = 'MANUAL'
    
    # ─── Update ───
    conn.execute("""
        UPDATE trades SET 
            exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?, status=?,
            result=?, lessons=?, exit_type=?, holding_days=?,
            vix_at_exit=?, regime_at_exit=?, fees_eur=2.0
        WHERE id=?
    """, (
        exit_price, exit_date, round(pnl_after_fees, 2), round(pnl_pct, 2), status,
        result, lessons, exit_type, holding_days,
        vix_exit, regime_exit, trade_id
    ))
    conn.commit()
    
    emoji = '🟢' if pnl_after_fees > 0 else '🔴'
    print(f"{emoji} Trade #{trade_id} geschlossen:")
    print(f"   {trade['ticker']} {direction}: {entry_price:.2f} → {exit_price:.2f}")
    print(f"   P&L: {pnl_after_fees:+.2f}€ ({pnl_pct:+.1f}%) | {status}")
    print(f"   Exit: {exit_type} | Hold: {holding_days}d | VIX: {vix_exit} | Regime: {regime_exit}")
    
    conn.close()
    return {
        'trade_id': trade_id,
        'ticker': trade['ticker'],
        'pnl_eur': round(pnl_after_fees, 2),
        'pnl_pct': round(pnl_pct, 2),
        'status': status,
        'exit_type': exit_type,
        'holding_days': holding_days,
        'regime_entry': trade['regime_at_entry'],
        'regime_exit': regime_exit
    }


def get_open_trades(trade_type=None):
    """Gibt offene Trades zurück."""
    conn = get_db()
    if trade_type:
        trades = conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' AND trade_type=? ORDER BY entry_date", 
            (trade_type,)
        ).fetchall()
    else:
        trades = conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date").fetchall()
    conn.close()
    return trades


def get_closed_trades(limit=50):
    """Gibt geschlossene Trades zurück."""
    conn = get_db()
    trades = conn.execute(
        "SELECT * FROM trades WHERE status IN ('WIN','LOSS') ORDER BY exit_date DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return trades


def trade_stats(trade_type=None):
    """Kompakte Trading-Statistik."""
    conn = get_db()
    where = "WHERE trade_type=?" if trade_type else ""
    params = (trade_type,) if trade_type else ()
    
    total = conn.execute(f"SELECT COUNT(*) FROM trades {where}", params).fetchone()[0]
    wins = conn.execute(f"SELECT COUNT(*) FROM trades {where} {'AND' if where else 'WHERE'} status='WIN'", params).fetchone()[0]
    losses = conn.execute(f"SELECT COUNT(*) FROM trades {where} {'AND' if where else 'WHERE'} status='LOSS'", params).fetchone()[0]
    
    pnl = conn.execute(f"SELECT COALESCE(SUM(pnl_eur),0) FROM trades {where} {'AND' if where else 'WHERE'} status IN ('WIN','LOSS')", params).fetchone()[0]
    
    avg_win = conn.execute(f"SELECT COALESCE(AVG(pnl_pct),0) FROM trades {where} {'AND' if where else 'WHERE'} status='WIN'", params).fetchone()[0]
    avg_loss = conn.execute(f"SELECT COALESCE(AVG(pnl_pct),0) FROM trades {where} {'AND' if where else 'WHERE'} status='LOSS'", params).fetchone()[0]
    
    # Per-Regime Stats
    regime_stats = conn.execute("""
        SELECT regime_at_entry, COUNT(*) as cnt,
               SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
               COALESCE(AVG(pnl_pct),0) as avg_pnl
        FROM trades WHERE status IN ('WIN','LOSS') AND regime_at_entry IS NOT NULL
        GROUP BY regime_at_entry
    """).fetchall()
    
    conn.close()
    
    closed = wins + losses
    wr = (wins / closed * 100) if closed > 0 else 0
    expectancy = (avg_win * wr/100 + avg_loss * (1 - wr/100)) if closed > 0 else 0
    
    return {
        'total': total, 'open': total - closed, 'closed': closed,
        'wins': wins, 'losses': losses, 'win_rate': round(wr, 1),
        'total_pnl': round(pnl, 2), 'avg_win': round(avg_win, 2), 'avg_loss': round(avg_loss, 2),
        'expectancy': round(expectancy, 2),
        'regime_stats': [{
            'regime': r[0], 'trades': r[1], 'wins': r[2], 'avg_pnl': round(r[3], 2)
        } for r in regime_stats]
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'stats':
        stats = trade_stats()
        print(f"═══ Trade Journal Stats ═══")
        print(f"  Trades: {stats['total']} ({stats['open']} offen, {stats['closed']} geschlossen)")
        print(f"  Win Rate: {stats['win_rate']}% ({stats['wins']}W / {stats['losses']}L)")
        print(f"  P&L: {stats['total_pnl']:+.2f}€ | Avg Win: {stats['avg_win']:+.1f}% | Avg Loss: {stats['avg_loss']:+.1f}%")
        print(f"  Expectancy: {stats['expectancy']:+.2f}%")
        if stats['regime_stats']:
            print(f"  Per Regime:")
            for r in stats['regime_stats']:
                print(f"    {r['regime']:16} | {r['trades']}T | {r['wins']}W | avg {r['avg_pnl']:+.1f}%")
    else:
        stats = trade_stats()
        print(json.dumps(stats, indent=2))
