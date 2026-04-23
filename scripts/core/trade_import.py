#!/usr/bin/env python3
"""
Trade Import — CSV/JSON Import für Trade Republic & Co.
========================================================
⚠️  LEGACY (Sub-7 Audit 2026-04-23):
    Schreibt in `trades` (Legacy-Archiv). Für neue Imports bitte direkt
    `paper_portfolio` befüllen. Siehe `data/SCHEMA.md`.

Importiert bestehende Trade-History in die DB.
Unterstützt: Trade Republic CSV, Custom JSON.

Sprint 6 | TradeMind Bauplan
"""

import csv, json, sqlite3, io
from datetime import datetime
from pathlib import Path

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def import_tr_csv(csv_path_or_text, trade_type='real'):
    """
    Importiert Trade Republic CSV Export.
    
    TR CSV Format (typisch):
    Datum;Typ;Titel;ISIN;Stück;Kurs;Betrag;Gebühr;Gesamtbetrag
    
    Oder neueres Format:
    Date;Type;Name;ISIN;Shares;Price;Amount;Fee;Total
    """
    conn = get_db()
    
    if Path(csv_path_or_text).exists():
        with open(csv_path_or_text, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    else:
        content = csv_path_or_text
    
    # Detect delimiter
    delimiter = ';' if ';' in content.split('\n')[0] else ','
    
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    
    imported = 0
    skipped = 0
    
    # TR CSV hat Käufe und Verkäufe — wir matchen sie zu Trades
    transactions = []
    
    for row in reader:
        # Normalize headers
        date = row.get('Datum') or row.get('Date') or row.get('date', '')
        typ = row.get('Typ') or row.get('Type') or row.get('type', '')
        name = row.get('Titel') or row.get('Name') or row.get('name', '')
        isin = row.get('ISIN') or row.get('isin', '')
        shares = row.get('Stück') or row.get('Shares') or row.get('shares', '0')
        price = row.get('Kurs') or row.get('Price') or row.get('price', '0')
        amount = row.get('Betrag') or row.get('Amount') or row.get('amount', '0')
        fee = row.get('Gebühr') or row.get('Fee') or row.get('fee', '1')
        
        # Parse
        try:
            shares = float(str(shares).replace(',', '.'))
            price = float(str(price).replace(',', '.').replace('€', '').strip())
            fee = float(str(fee).replace(',', '.').replace('€', '').strip() or '1')
        except:
            skipped += 1
            continue
        
        # Date parsing
        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
            try:
                dt = datetime.strptime(date.strip()[:10], fmt)
                date_str = dt.strftime('%Y-%m-%d')
                break
            except:
                continue
        else:
            skipped += 1
            continue
        
        is_buy = 'kauf' in typ.lower() or 'buy' in typ.lower()
        is_sell = 'verkauf' in typ.lower() or 'sell' in typ.lower()
        
        if is_buy or is_sell:
            transactions.append({
                'date': date_str,
                'type': 'BUY' if is_buy else 'SELL',
                'name': name,
                'isin': isin,
                'shares': shares,
                'price': price,
                'fee': fee,
            })
    
    # Match Buys → Sells (FIFO)
    buys = {}  # isin → list of buys
    for tx in sorted(transactions, key=lambda x: x['date']):
        isin = tx['isin']
        if tx['type'] == 'BUY':
            if isin not in buys:
                buys[isin] = []
            buys[isin].append(tx)
        elif tx['type'] == 'SELL' and isin in buys and buys[isin]:
            buy = buys[isin].pop(0)  # FIFO
            
            pnl = (tx['price'] - buy['price']) * tx['shares'] - buy['fee'] - tx['fee']
            pnl_pct = (tx['price'] / buy['price'] - 1) * 100 if buy['price'] > 0 else 0
            status = 'WIN' if pnl > 0 else 'LOSS'
            holding = (datetime.strptime(tx['date'], '%Y-%m-%d') - datetime.strptime(buy['date'], '%Y-%m-%d')).days
            
            # Check for duplicates
            existing = conn.execute("""
                SELECT id FROM trades WHERE ticker=? AND entry_date=? AND entry_price=?
            """, (buy['name'], buy['date'], buy['price'])).fetchone()
            
            if existing:
                skipped += 1
                continue
            
            conn.execute("""
                INSERT INTO trades (ticker, direction, entry_price, entry_date,
                    exit_price, exit_date, shares, pnl_eur, pnl_pct, status,
                    trade_type, fees_eur, holding_days)
                VALUES (?, 'LONG', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                buy['name'], buy['price'], buy['date'],
                tx['price'], tx['date'], tx['shares'],
                round(pnl, 2), round(pnl_pct, 2), status,
                trade_type, round(buy['fee'] + tx['fee'], 2), holding
            ))
            imported += 1
    
    # Offene Käufe (noch nicht verkauft) als OPEN Trades
    for isin, remaining_buys in buys.items():
        for buy in remaining_buys:
            existing = conn.execute("""
                SELECT id FROM trades WHERE ticker=? AND entry_date=? AND entry_price=?
            """, (buy['name'], buy['date'], buy['price'])).fetchone()
            
            if existing:
                skipped += 1
                continue
            
            conn.execute("""
                INSERT INTO trades (ticker, direction, entry_price, entry_date,
                    shares, status, trade_type, fees_eur)
                VALUES (?, 'LONG', ?, ?, ?, 'OPEN', ?, ?)
            """, (buy['name'], buy['price'], buy['date'], buy['shares'], trade_type, buy['fee']))
            imported += 1
    
    conn.commit()
    conn.close()
    
    return {'imported': imported, 'skipped': skipped, 'total_transactions': len(transactions)}


def import_json(json_path_or_data, trade_type='real'):
    """
    Importiert Trades aus JSON.
    Format: [{"ticker": "NVDA", "entry_price": 167.88, "entry_date": "2026-03-10", ...}]
    """
    conn = get_db()
    
    if isinstance(json_path_or_data, str) and Path(json_path_or_data).exists():
        data = json.loads(Path(json_path_or_data).read_text())
    elif isinstance(json_path_or_data, str):
        data = json.loads(json_path_or_data)
    else:
        data = json_path_or_data
    
    imported = 0
    for trade in data:
        ticker = trade.get('ticker', '')
        entry_price = trade.get('entry_price', trade.get('entry'))
        entry_date = trade.get('entry_date', trade.get('date'))
        
        if not ticker or not entry_price:
            continue
        
        # Check duplicate
        existing = conn.execute("""
            SELECT id FROM trades WHERE ticker=? AND entry_date=? AND entry_price=?
        """, (ticker, entry_date, entry_price)).fetchone()
        
        if existing:
            continue
        
        conn.execute("""
            INSERT INTO trades (ticker, strategy, direction, entry_price, entry_date,
                exit_price, exit_date, stop, target, shares, pnl_eur, pnl_pct,
                status, thesis, trade_type, fees_eur)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            trade.get('strategy'),
            trade.get('direction', 'LONG'),
            entry_price,
            entry_date,
            trade.get('exit_price'),
            trade.get('exit_date'),
            trade.get('stop'),
            trade.get('target'),
            trade.get('shares', 1),
            trade.get('pnl_eur'),
            trade.get('pnl_pct'),
            trade.get('status', 'OPEN'),
            trade.get('thesis'),
            trade_type,
            trade.get('fees', 1.0),
        ))
        imported += 1
    
    conn.commit()
    conn.close()
    return {'imported': imported}


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        trade_type = sys.argv[2] if len(sys.argv) > 2 else 'real'
        
        if path.endswith('.csv'):
            result = import_tr_csv(path, trade_type)
        else:
            result = import_json(path, trade_type)
        
        print(f"✅ Import abgeschlossen: {result}")
    else:
        print("Usage: trade_import.py <file.csv|file.json> [real|paper]")
        print("Formats: Trade Republic CSV, Custom JSON")
