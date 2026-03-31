#!/usr/bin/env python3
"""
sync_dashboard.py — Bridge: SQLite DB → GitHub (trade-log.json + dna.json + strategies.json)

Wird aufgerufen nach:
  - day_trader_v2.py (neue Day Trades)
  - paper_monitor.py (Paper Trades)
  - learning_system.py (Conviction-Updates)

Hält Dashboard (Vercel) immer aktuell.
"""
import sqlite3, json, subprocess, sys, os
from pathlib import Path
from datetime import datetime

WS   = Path('/data/.openclaw/workspace')
DB   = WS / 'data/trading.db'
DATA = WS / 'data'

# ── Helpers ──────────────────────────────────────────────

def load_json(path, default):
    try:
        p = Path(path)
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default

def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))

def git_commit_push(files, message):
    try:
        subprocess.run(['git', '-C', str(WS), 'add'] + [str(f) for f in files],
                       capture_output=True, check=True)
        result = subprocess.run(
            ['git', '-C', str(WS), 'diff', '--cached', '--quiet'],
            capture_output=True)
        if result.returncode == 0:
            print('sync_dashboard: Keine Änderungen — kein Commit nötig')
            return True
        # [skip ci] verhindert Vercel-Deploy bei Daten-Syncs (spart Hobby-Limit)
        ci_tag = '' if '[skip ci]' in message else ' [skip ci]'
        subprocess.run(
            ['git', '-C', str(WS), 'commit', '-m', message + ci_tag],
            capture_output=True, check=True)
        subprocess.run(
            ['git', '-C', str(WS), 'push', 'origin', 'master'],
            capture_output=True, check=True)
        print(f'sync_dashboard: Committed + pushed — {message}')
        return True
    except subprocess.CalledProcessError as e:
        print(f'sync_dashboard: Git error — {e}')
        return False

# ── 1. Paper Trades aus SQLite → trade-log.json ──────────

def sync_paper_trades():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute('''
        SELECT ticker, strategy, entry_price, entry_date, shares,
               stop_price, target_price, status,
               close_price, close_date, pnl_eur, pnl_pct, fees, notes
        FROM paper_portfolio
        ORDER BY entry_date ASC
    ''').fetchall()
    conn.close()

    entries = []
    for r in rows:
        d = dict(r)
        # BUY entry
        entries.append({
            'ts':         d['entry_date'],
            'ticker':     d['ticker'],
            'action':     'BUY',
            'price_eur':  d['entry_price'],
            'stop_eur':   d['stop_price'],
            'target_eur': d['target_price'],
            'strategy':   d['strategy'] or '',
            'notes':      d['notes'] or '',
            'shares':     d['shares'],
            'status':     d['status'],
            'paper':      True,
        })
        # SELL entry wenn geschlossen
        if d['status'] == 'CLOSED' and d['close_price']:
            entries.append({
                'ts':        d['close_date'] or '',
                'ticker':    d['ticker'],
                'action':    'SELL',
                'price_eur': d['close_price'],
                'pnl_eur':   d['pnl_eur'],
                'pnl_pct':   d['pnl_pct'],
                'strategy':  d['strategy'] or '',
                'notes':     f"Closed | P&L: {d['pnl_pct']:.1f}%" if d['pnl_pct'] else 'Closed',
                'paper':     True,
            })

    save_json(DATA / 'trade-log.json', entries)
    print(f'sync_dashboard: {len(entries)} trade-log Einträge geschrieben')
    return entries

# ── 2. DNA + Strategies aus lokalen Dateien sichern ──────

def sync_dna():
    """dna.json und strategies.json sind schon lokal aktuell — nur sicherstellen dass sie gepusht werden."""
    dna_path  = DATA / 'dna.json'
    strat_path = DATA / 'strategies.json'

    # Timestamp in dna.json updaten
    if dna_path.exists():
        dna = load_json(dna_path, {})
        dna['last_sync'] = datetime.utcnow().isoformat() + 'Z'
        save_json(dna_path, dna)
        print('sync_dashboard: dna.json timestamp updated')

    return dna_path, strat_path

# ── 3. Day Trades aus SQLite → dna.json open_positions ───

def sync_day_trades():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    open_dt = conn.execute('''
        SELECT ticker, strategy, entry_price, entry_date,
               stop, target, status, thesis
        FROM trades
        WHERE trade_type = 'day_trade' AND status = 'OPEN'
        ORDER BY entry_date DESC
    ''').fetchall()

    closed_dt = conn.execute('''
        SELECT ticker, strategy, entry_price, exit_price, entry_date, exit_date,
               pnl_pct, status
        FROM trades
        WHERE trade_type = 'day_trade' AND status != 'OPEN'
        ORDER BY exit_date DESC
        LIMIT 20
    ''').fetchall()
    conn.close()

    dna_path = DATA / 'dna.json'
    dna = load_json(dna_path, {})

    # Open Day Trades in DNA eintragen
    dna_open = dna.get('open_positions', [])
    # Bestehende Day Trades raus, neu rein
    dna_open = [p for p in dna_open if p.get('trade_type') != 'day_trade']
    for r in open_dt:
        d = dict(r)
        dna_open.append({
            'ticker':     d['ticker'],
            'strategy':   d['strategy'],
            'trade_type': 'day_trade',
            'entry':      d['entry_price'],
            'stop':       d['stop'],
            'target':     d['target'],
            'opened_at':  d['entry_date'],
            'status':     'OPEN',
        })
    dna['open_positions'] = dna_open

    # Recent closed Day Trades
    dna['recent_day_trades'] = [dict(r) for r in closed_dt]
    dna['last_sync'] = datetime.utcnow().isoformat() + 'Z'

    save_json(dna_path, dna)
    print(f'sync_dashboard: {len(open_dt)} offene Day Trades in dna.json')
    return dna_path

# ── Main ─────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    files_to_commit = []
    messages = []

    if mode in ('all', 'paper'):
        sync_paper_trades()
        files_to_commit.append(DATA / 'trade-log.json')
        messages.append('Paper Trades sync')

    if mode in ('all', 'dna'):
        dna_path, strat_path = sync_dna()
        files_to_commit += [dna_path, strat_path]
        messages.append('DNA + Strategies sync')

    if mode in ('all', 'daytrades'):
        dna_path = sync_day_trades()
        if dna_path not in files_to_commit:
            files_to_commit.append(dna_path)
        messages.append('Day Trades sync')

    if files_to_commit:
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        msg = f"Dashboard sync [{ts}]: {', '.join(messages)}"
        git_commit_push(files_to_commit, msg)

    print('sync_dashboard: Fertig')

if __name__ == '__main__':
    main()
