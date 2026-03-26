#!/usr/bin/env python3
"""
Paper Trade Monitor — Automatisches Stop/Target Tracking
==========================================================
Prüft alle offenen Paper Trades gegen Live-Kurse.
Stop Hit → LOSS | Target Hit → WIN | Weder → P&L Update

Schreibt Ergebnisse in:
1. SQLite DB (trades Tabelle) 
2. data/dna.json (Dashboard-Feed)

Läuft alle 30 Min via Cron (zusammen mit signal_tracker).
"""

import sqlite3, json, urllib.request, urllib.parse, subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path('/data/.openclaw/workspace')
DB_PATH = WORKSPACE / 'data/trading.db'
DNA_JSON = WORKSPACE / 'data/dna.json'
SIGNALS_JSON = WORKSPACE / 'data/signals.json'

# ─── Yahoo Finance ────────────────────────────────────────────────────

def yahoo_price(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        meta = d['chart']['result'][0]['meta']
        price = meta['regularMarketPrice']
        currency = meta.get('currency', 'USD')
        return price, currency
    except Exception as e:
        print(f"  ⚠️ Yahoo-Fehler {ticker}: {e}")
        return None, None

def to_eur(price, currency):
    """Konvertiert in EUR wenn nötig."""
    if not price:
        return None
    if currency == 'EUR':
        return price
    
    fx_map = {
        'USD': 'EURUSD=X',
        'GBP': 'GBPEUR=X',  
        'GBp': 'GBPEUR=X',  # Pence
        'NOK': 'NOKEUR=X',
        'DKK': 'DKKEUR=X',
        'SEK': 'SEKEUR=X',
        'JPY': 'JPYEUR=X',
    }
    
    if currency == 'GBp':
        price = price / 100  # Pence → Pounds
        currency = 'GBP'
    
    fx_ticker = fx_map.get(currency)
    if not fx_ticker:
        # Fallback: USD
        eurusd, _ = yahoo_price('EURUSD=X')
        return round(price / eurusd, 2) if eurusd else None
    
    if currency == 'GBP':
        gbpusd, _ = yahoo_price('GBPUSD=X')
        eurusd, _ = yahoo_price('EURUSD=X')
        if gbpusd and eurusd:
            return round(price * gbpusd / eurusd, 2)
        return None
    
    if currency in ('NOK', 'DKK', 'SEK'):
        pair = f'{currency}EUR=X'
        rate, _ = yahoo_price(pair)
        if not rate:
            # Try inverse
            pair = f'EUR{currency}=X'
            rate, _ = yahoo_price(pair)
            if rate:
                return round(price / rate, 2)
            return None
        return round(price * rate, 2)
    
    # USD default
    eurusd, _ = yahoo_price('EURUSD=X')
    return round(price / eurusd, 2) if eurusd else None


# ─── DB ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def close_paper_trade(trade_id, exit_price, status, ticker):
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not trade:
        conn.close()
        return
    
    entry = trade['entry_price']
    shares = trade['shares'] or 1
    direction = trade['direction'] or 'LONG'
    entry_date = trade['entry_date']
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    if direction == 'LONG':
        pnl = (exit_price - entry) * shares
        pnl_pct = (exit_price / entry - 1) * 100
    else:
        pnl = (entry - exit_price) * shares
        pnl_pct = (entry / exit_price - 1) * 100
    
    holding = 0
    if entry_date:
        try:
            ed = datetime.strptime(entry_date[:10], '%Y-%m-%d')
            holding = (datetime.now() - ed).days
        except:
            pass
    
    conn.execute("""
        UPDATE trades SET 
            exit_price=?, exit_date=?, pnl_eur=?, pnl_pct=?, 
            status=?, holding_days=?
        WHERE id=?
    """, (round(exit_price, 2), now, round(pnl, 2), round(pnl_pct, 2), 
          status, holding, trade_id))
    conn.commit()
    conn.close()
    
    emoji = "✅" if status == 'WIN' else "❌"
    print(f"  {emoji} {ticker} CLOSED: {entry:.2f} → {exit_price:.2f} ({pnl_pct:+.1f}%) [{status}]")


# ─── DNA Report Generator ────────────────────────────────────────────

def _get_strategy_name(strategy_id):
    """Map strategy ID (PS1, S3, DT1...) to human-readable name from strategies.json."""
    try:
        strat_path = WORKSPACE / 'data/strategies.json'
        if strat_path.exists():
            import json as _json
            with open(strat_path) as f:
                strats = _json.load(f)
            if strategy_id in strats and isinstance(strats[strategy_id], dict):
                return strats[strategy_id].get('name', strategy_id)
    except Exception:
        pass
    return strategy_id


def generate_dna_json():
    """Generiert data/dna.json aus allen Trades (paper + real)."""
    conn = get_db()
    
    # Alle Trades
    all_trades = conn.execute("SELECT * FROM trades ORDER BY entry_date").fetchall()
    closed = [t for t in all_trades if t['status'] in ('WIN', 'LOSS')]
    open_trades = [t for t in all_trades if t['status'] == 'OPEN']
    
    # Per Strategy
    strategies = {}
    for t in all_trades:
        s = t['strategy'] or 'unknown'
        if s not in strategies:
            strategies[s] = {'total': 0, 'open': 0, 'closed': 0, 'wins': 0, 'losses': 0,
                           'pnl_sum': 0, 'crv_sum': 0, 'hold_sum': 0, 'pnl_values': []}
        strategies[s]['total'] += 1
        if t['status'] == 'OPEN':
            strategies[s]['open'] += 1
        elif t['status'] in ('WIN', 'LOSS'):
            strategies[s]['closed'] += 1
            if t['status'] == 'WIN':
                strategies[s]['wins'] += 1
            else:
                strategies[s]['losses'] += 1
            strategies[s]['pnl_sum'] += (t['pnl_pct'] or 0)
            strategies[s]['pnl_values'].append(t['pnl_pct'] or 0)
            strategies[s]['hold_sum'] += (t['holding_days'] or 0)
            # CRV
            if t['entry_price'] and t['stop'] and t['target']:
                risk = abs(t['entry_price'] - t['stop'])
                reward = abs(t['target'] - t['entry_price'])
                if risk > 0:
                    strategies[s]['crv_sum'] += reward / risk
    
    strategy_list = []
    for name, st in sorted(strategies.items(), key=lambda x: -x[1]['total']):
        c = st['closed']
        wr = round(st['wins'] / c * 100, 1) if c > 0 else 0
        avg_pnl = round(st['pnl_sum'] / c, 2) if c > 0 else 0
        avg_crv = round(st['crv_sum'] / st['total'], 1) if st['total'] > 0 else 0
        avg_hold = round(st['hold_sum'] / c, 1) if c > 0 else 0
        
        # Kill warning: 3+ consecutive losses
        kill = False
        if c >= 3 and st['wins'] == 0:
            kill = True
        
        # Consecutive losses check
        consec_losses = 0
        max_consec = 0
        for v in st['pnl_values']:
            if v < 0:
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
            else:
                consec_losses = 0
        if max_consec >= 3:
            kill = True
        
        # Map strategy ID to name from strategies.json
        strat_name = _get_strategy_name(name)
        strategy_list.append({
            'id': name,
            'strategy': name,
            'strategy_name': strat_name,
            'total': st['total'],
            'open': st['open'],
            'closed': c,
            'wins': st['wins'],
            'losses': st['losses'],
            'win_rate': wr,
            'avg_pnl': avg_pnl,
            'avg_crv': avg_crv,
            'avg_hold_days': avg_hold,
            'kill_warning': kill,
            'max_consecutive_losses': max_consec,
        })
    
    # Trader Profile
    all_closed_sorted = sorted(closed, key=lambda t: t['exit_date'] or '')
    max_consec_loss = 0
    current_streak = 0
    revenge_trades = 0
    stops_set = sum(1 for t in all_trades if t['stop'])
    
    for i, t in enumerate(all_closed_sorted):
        if t['status'] == 'LOSS':
            current_streak += 1
            max_consec_loss = max(max_consec_loss, current_streak)
            # Revenge trade: nächster Trade innerhalb 2h nach Loss
            if i + 1 < len(all_closed_sorted):
                try:
                    loss_date = t['exit_date']
                    next_entry = all_closed_sorted[i+1]['entry_date']
                    if loss_date and next_entry and loss_date[:10] == next_entry[:10]:
                        revenge_trades += 1
                except:
                    pass
        else:
            current_streak = 0
    
    # Per Regime (wenn vorhanden)
    regime_stats = {}
    for t in closed:
        try:
            regime = t['regime_at_entry'] or 'UNKNOWN'
        except (IndexError, KeyError):
            regime = 'UNKNOWN'
        if regime not in regime_stats:
            regime_stats[regime] = {'total': 0, 'wins': 0, 'pnl_sum': 0}
        regime_stats[regime]['total'] += 1
        if t['status'] == 'WIN':
            regime_stats[regime]['wins'] += 1
        regime_stats[regime]['pnl_sum'] += (t['pnl_pct'] or 0)
    
    regime_list = []
    for name, rs in regime_stats.items():
        regime_list.append({
            'regime': name,
            'total': rs['total'],
            'win_rate': round(rs['wins'] / rs['total'] * 100, 1) if rs['total'] > 0 else 0,
            'avg_pnl': round(rs['pnl_sum'] / rs['total'], 2) if rs['total'] > 0 else 0,
        })
    
    # Paper vs Real split
    paper_count = sum(1 for t in all_trades if t['trade_type'] == 'paper')
    real_count = sum(1 for t in all_trades if t['trade_type'] == 'real')
    paper_closed = sum(1 for t in closed if t['trade_type'] == 'paper')
    real_closed = sum(1 for t in closed if t['trade_type'] == 'real')
    
    total_pnl = sum(t['pnl_eur'] or 0 for t in closed)
    
    dna = {
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stats': {
            'total': len(all_trades),
            'open': len(open_trades),
            'closed': len(closed),
            'wins': sum(1 for t in closed if t['status'] == 'WIN'),
            'losses': sum(1 for t in closed if t['status'] == 'LOSS'),
            'win_rate': round(sum(1 for t in closed if t['status'] == 'WIN') / len(closed) * 100, 1) if closed else 0,
            'total_pnl': round(total_pnl, 2),
            'expectancy': round(sum(t['pnl_pct'] or 0 for t in closed) / len(closed), 2) if closed else 0,
            'paper_trades': paper_count,
            'real_trades': real_count,
            'paper_closed': paper_closed,
            'real_closed': real_closed,
        },
        'strategies': strategy_list,
        'regime_performance': regime_list,
        'trader_profile': {
            'max_consecutive_losses': max_consec_loss,
            'revenge_trades': revenge_trades,
            'stop_discipline_pct': round(stops_set / len(all_trades) * 100, 1) if all_trades else 0,
            'avg_hold_days': round(sum(t['holding_days'] or 0 for t in closed) / len(closed), 1) if closed else 0,
        },
        'open_positions': [{
            'ticker': t['ticker'],
            'strategy': t['strategy'],
            'entry': t['entry_price'],
            'stop': t['stop'],
            'target': t['target'],
            'trade_type': t['trade_type'],
            'entry_date': t['entry_date'],
        } for t in open_trades],
    }
    
    DNA_JSON.write_text(json.dumps(dna, indent=2))
    conn.close()
    print(f"  📊 DNA Report: {len(all_trades)} Trades ({len(closed)} closed, WR {dna['stats']['win_rate']}%)")
    return dna


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] Paper Monitor läuft...")
    
    conn = get_db()
    open_papers = conn.execute("""
        SELECT id, ticker, strategy, entry_price, stop, target, direction, trade_type
        FROM trades WHERE status='OPEN' AND trade_type='paper'
    """).fetchall()
    conn.close()
    
    print(f"  {len(open_papers)} offene Paper Trades")
    
    closed_any = False
    eurusd_cache = {}
    
    for t in open_papers:
        ticker = t['ticker']
        yahoo = ticker
        
        price, currency = yahoo_price(yahoo)
        if not price:
            continue
        
        price_eur = to_eur(price, currency)
        if not price_eur:
            continue
        
        entry = t['entry_price']
        stop = t['stop']
        target = t['target']
        direction = t['direction'] or 'LONG'
        
        pnl_pct = (price_eur / entry - 1) * 100 if direction == 'LONG' else (entry / price_eur - 1) * 100
        
        # Stop Hit?
        if stop:
            if direction == 'LONG' and price_eur <= stop:
                close_paper_trade(t['id'], price_eur, 'LOSS', ticker)
                closed_any = True
                continue
            elif direction == 'SHORT' and price_eur >= stop:
                close_paper_trade(t['id'], price_eur, 'LOSS', ticker)
                closed_any = True
                continue
        
        # Target Hit?
        if target:
            if direction == 'LONG' and price_eur >= target:
                close_paper_trade(t['id'], price_eur, 'WIN', ticker)
                closed_any = True
                continue
            elif direction == 'SHORT' and price_eur <= target:
                close_paper_trade(t['id'], price_eur, 'WIN', ticker)
                closed_any = True
                continue
        
        # Noch offen — P&L anzeigen
        emoji = "🟢" if pnl_pct > 0 else "🔴"
        print(f"  {emoji} {ticker:12s} {price_eur:8.2f}€ ({pnl_pct:+.1f}%) | Stop: {stop or '—'} | Target: {target or '—'}")
    
    # DNA Report immer regenerieren
    generate_dna_json()
    
    # Git push wenn sich was geändert hat
    if closed_any:
        push_to_git()


def push_to_git():
    try:
        subprocess.run(['git', 'add', str(DNA_JSON)], cwd=str(WORKSPACE), capture_output=True, timeout=10)
        result = subprocess.run(
            ['git', 'commit', '-m', f'📊 DNA update {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} [skip ci]'],
            cwd=str(WORKSPACE), capture_output=True, timeout=10
        )
        if result.returncode == 0:
            subprocess.run(['git', 'push'], cwd=str(WORKSPACE), capture_output=True, timeout=30)
            print("  📤 dna.json gepusht → Vercel")
    except Exception as e:
        print(f"  Git push fehlgeschlagen: {e}")


if __name__ == '__main__':
    main()
    # Dashboard sync: Paper Trades → GitHub
    import subprocess
    subprocess.run(['python3', '/data/.openclaw/workspace/scripts/sync_dashboard.py', 'paper'],
                   capture_output=True, timeout=60)
