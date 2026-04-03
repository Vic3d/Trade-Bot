#!/usr/bin/env python3
"""
position_update.py — Single Source of Truth Updater

Wenn Victor eine Position-Änderung meldet, NUR dieses Script aufrufen.
Es updated trading_config.json + pushed zu GitHub + regeneriert Snapshot.

USAGE:
  python3 position_update.py close EQNR 34.20 "Stop ausgelöst"
  python3 position_update.py open STLD 165.00 155.00 "Liberation Day Trade"
  python3 position_update.py stop PLTR 125.00 "Stop nachgezogen"
  python3 position_update.py list
"""

import json, sys, subprocess
from pathlib import Path
from datetime import date

WS = Path('/data/.openclaw/workspace')
CFG = WS / 'trading_config.json'
SSH = 'ssh -i ~/.ssh/id_ed25519_vic3d -o StrictHostKeyChecking=no'

def load(): return json.loads(CFG.read_text())
def save(cfg):
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

def push(msg):
    subprocess.run(f'cd {WS} && git add trading_config.json', shell=True)
    subprocess.run(f'cd {WS} && git commit -m "{msg}"', shell=True)
    r = subprocess.run(
        f'cd {WS} && GIT_SSH_COMMAND="{SSH}" git push origin master',
        shell=True, capture_output=True, text=True
    )
    return r.returncode == 0

def sync_newswire_db(ticker, action, exit_eur=None, new_stop=None):
    """Hält newswire.db/trades synchron mit trading_config.json."""
    import sqlite3
    db_path = WS / 'memory/newswire.db'
    if not db_path.exists():
        return
    db = sqlite3.connect(str(db_path))
    if action == 'close':
        db.execute("UPDATE trades SET outcome='closed', stop_price=? WHERE ticker=? AND outcome='open'",
                   (exit_eur or 0, ticker))
    elif action == 'stop' and new_stop:
        db.execute("UPDATE trades SET stop_price=? WHERE ticker=? AND outcome='open'",
                   (new_stop, ticker))
    elif action == 'open':
        pass  # wird beim nächsten Snapshot-Run aufgenommen
    db.commit()

def regen_snapshot():
    subprocess.run(['python3', str(WS/'scripts/daily_snapshot.py')], capture_output=True)

def close(ticker, exit_eur, note=''):
    cfg = load()
    if ticker not in cfg['positions']:
        print(f'ERROR: {ticker} nicht in Config')
        return False
    p = cfg['positions'][ticker]
    entry = p.get('entry_eur', 0)
    pnl = (float(exit_eur) - entry) / entry * 100 if entry else 0
    p['status'] = 'CLOSED'
    p['exit_eur'] = float(exit_eur)
    p['exit_date'] = date.today().isoformat()
    if note: p['notes'] = note
    save(cfg)
    ok = push(f'{ticker} CLOSED @ {exit_eur}€ (PnL {pnl:+.1f}%) — {date.today()}')
    sync_newswire_db(ticker, 'close', exit_eur)
    regen_snapshot()
    print(f'✅ {ticker} geschlossen @ {exit_eur}€ | PnL {pnl:+.1f}% | GitHub: {"✅" if ok else "❌"}')
    return True

def update_stop(ticker, new_stop):
    cfg = load()
    if ticker not in cfg['positions']:
        print(f'ERROR: {ticker} nicht in Config')
        return False
    old_stop = cfg['positions'][ticker].get('stop_eur', 0)
    cfg['positions'][ticker]['stop_eur'] = float(new_stop)
    save(cfg)
    ok = push(f'{ticker} Stop {old_stop}€ → {new_stop}€')
    sync_newswire_db(ticker, 'stop', new_stop=float(new_stop))
    regen_snapshot()
    print(f'✅ {ticker} Stop {old_stop}€ → {new_stop}€ | GitHub: {"✅" if ok else "❌"}')
    return True

def open_position(ticker, entry_eur, stop_eur, note='', name=None, strategy=''):
    cfg = load()
    cfg['positions'][ticker] = {
        'name': name or ticker,
        'yahoo': ticker,
        'currency': 'USD',
        'entry_eur': float(entry_eur),
        'stop_eur': float(stop_eur),
        'targets_eur': [],
        'status': 'OPEN',
        'entry_date': date.today().isoformat(),
        'strategy': strategy,
        'notes': note,
        'size_eur': 2000,
        'conviction': 50,
    }
    save(cfg)
    ok = push(f'{ticker} OPEN @ {entry_eur}€ | Stop {stop_eur}€')
    regen_snapshot()
    print(f'✅ {ticker} eröffnet @ {entry_eur}€ | Stop {stop_eur}€ | GitHub: {"✅" if ok else "❌"}')
    return True

def list_positions():
    cfg = load()
    print(f'\n{"Ticker":<12} {"Name":<30} {"Entry":>8} {"Stop":>8} {"Status"}')
    print('-' * 75)
    for t, p in cfg['positions'].items():
        status = p.get('status', 'OPEN')
        if status == 'CLOSED': continue
        print(f'{t:<12} {p.get("name",""):<30} {p.get("entry_eur",0):>8.2f}€ {p.get("stop_eur",0) or 0:>7.2f}€  {status}')
    print()

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] == 'list':
        list_positions()
    elif args[0] == 'close' and len(args) >= 3:
        close(args[1], args[2], ' '.join(args[3:]))
    elif args[0] == 'stop' and len(args) >= 3:
        update_stop(args[1], args[2])
    elif args[0] == 'open' and len(args) >= 4:
        open_position(args[1], args[2], args[3], ' '.join(args[4:]))
    else:
        print(__doc__)
