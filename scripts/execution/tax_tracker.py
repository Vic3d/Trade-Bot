#!/usr/bin/env python3
"""
Tax Tracker — Deutsche Abgeltungssteuer-Berechnung
====================================================
FIFO-Berechnung, 26.375% (25% + 5.5% Soli), Freistellungsauftrag,
Tax-Loss Harvesting Vorschläge, Jahresreport.

Sprint 6 | TradeMind Bauplan
"""

import sqlite3, json
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')

# Deutsche Abgeltungssteuer
STEUER_SATZ = 0.25       # 25% Kapitalertragssteuer
SOLI_SATZ = 0.055         # 5.5% Solidaritätszuschlag auf KESt
KIRCHENSTEUER_SATZ = 0.0  # 0% default (8-9% je Bundesland, hier 0)
EFFEKTIVER_SATZ = STEUER_SATZ * (1 + SOLI_SATZ) * (1 + KIRCHENSTEUER_SATZ)  # 26.375%

FREISTELLUNGSAUFTRAG = 1000.0  # 1.000€ Sparerpauschbetrag (Einzelperson 2024+)
TR_GEBUEHR = 1.0  # Trade Republic pro Trade


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def calculate_fifo_tax(year=None):
    """
    FIFO-basierte Steuerberechnung für alle geschlossenen Trades.
    Returns: dict mit Steuer-Details pro Trade + Zusammenfassung
    """
    conn = get_db()
    
    where = "WHERE status IN ('WIN','LOSS')"
    if year:
        where += f" AND exit_date LIKE '{year}%'"
    
    trades = conn.execute(f"""
        SELECT id, ticker, entry_price, exit_price, entry_date, exit_date,
               shares, pnl_eur, pnl_pct, fees_eur, trade_type, direction
        FROM trades {where} ORDER BY exit_date
    """).fetchall()
    conn.close()
    
    results = []
    total_gains = 0
    total_losses = 0
    total_fees = 0
    
    for t in trades:
        shares = t['shares'] or 1
        entry = t['entry_price'] or 0
        exit_p = t['exit_price'] or 0
        fees = t['fees_eur'] or 2.0  # 2× 1€ TR
        direction = t['direction'] or 'LONG'
        
        # Bruttogewinn
        if direction == 'LONG':
            brutto = (exit_p - entry) * shares
        else:
            brutto = (entry - exit_p) * shares
        
        # Nettogewinn (nach Gebühren)
        netto = brutto - fees
        
        if netto > 0:
            total_gains += netto
        else:
            total_losses += abs(netto)
        
        total_fees += fees
        
        results.append({
            'trade_id': t['id'],
            'ticker': t['ticker'],
            'entry': entry,
            'exit': exit_p,
            'shares': shares,
            'brutto': round(brutto, 2),
            'fees': round(fees, 2),
            'netto': round(netto, 2),
            'entry_date': t['entry_date'],
            'exit_date': t['exit_date'],
            'trade_type': t['trade_type'],
        })
    
    # Verlustvortrag: Verluste werden mit Gewinnen verrechnet
    verrechenbar = min(total_losses, total_gains)
    steuerpflichtig_brutto = total_gains - verrechenbar
    
    # Freistellungsauftrag
    nach_freibetrag = max(0, steuerpflichtig_brutto - FREISTELLUNGSAUFTRAG)
    
    # Steuer
    kest = nach_freibetrag * STEUER_SATZ
    soli = kest * SOLI_SATZ
    steuer_gesamt = round(kest + soli, 2)
    
    # After-Tax P&L
    gesamt_pnl = total_gains - total_losses
    after_tax_pnl = gesamt_pnl - steuer_gesamt
    
    # Verlustvortrag (nicht verrechnete Verluste)
    verlustvortrag = max(0, total_losses - total_gains)
    
    summary = {
        'year': year or 'Gesamt',
        'trades_count': len(results),
        'total_gains': round(total_gains, 2),
        'total_losses': round(total_losses, 2),
        'total_fees': round(total_fees, 2),
        'gesamt_pnl': round(gesamt_pnl, 2),
        'verlustvortrag': round(verlustvortrag, 2),
        'steuerpflichtig_brutto': round(steuerpflichtig_brutto, 2),
        'freistellungsauftrag': FREISTELLUNGSAUFTRAG,
        'nach_freibetrag': round(nach_freibetrag, 2),
        'kest': round(kest, 2),
        'soli': round(soli, 2),
        'steuer_gesamt': steuer_gesamt,
        'effektiver_steuersatz': f"{EFFEKTIVER_SATZ*100:.3f}%",
        'after_tax_pnl': round(after_tax_pnl, 2),
    }
    
    return {'trades': results, 'summary': summary}


def tax_loss_harvesting_suggestions():
    """Findet Positionen die für Tax-Loss Harvesting geeignet sind."""
    conn = get_db()
    open_trades = conn.execute("""
        SELECT id, ticker, entry_price, shares, entry_date, trade_type
        FROM trades WHERE status='OPEN'
    """).fetchall()
    
    # Aktuellen Gewinn für dieses Jahr berechnen
    year = datetime.now().strftime('%Y')
    ytd_gains = conn.execute(f"""
        SELECT COALESCE(SUM(pnl_eur), 0) FROM trades 
        WHERE status IN ('WIN','LOSS') AND exit_date LIKE '{year}%' AND pnl_eur > 0
    """).fetchone()[0]
    
    conn.close()
    
    suggestions = []
    # Für jede offene Position: wie viel Steuer würde Verkauf sparen?
    for t in open_trades:
        # Approximation: aktuellen Verlust schätzen wir hier nicht live
        # Das muss mit live-Preisen gefüttert werden
        suggestions.append({
            'trade_id': t['id'],
            'ticker': t['ticker'],
            'entry': t['entry_price'],
            'shares': t['shares'] or 1,
            'entry_date': t['entry_date'],
            'note': 'Live-Kurs benötigt für Berechnung'
        })
    
    return {
        'ytd_gains': round(ytd_gains, 2),
        'freibetrag_genutzt': round(min(ytd_gains, FREISTELLUNGSAUFTRAG), 2),
        'freibetrag_rest': round(max(0, FREISTELLUNGSAUFTRAG - ytd_gains), 2),
        'open_positions': suggestions,
    }


def generate_jahresreport(year=None):
    """Generiert einen Jahressteuerreport als Text."""
    if not year:
        year = datetime.now().strftime('%Y')
    
    data = calculate_fifo_tax(year)
    s = data['summary']
    
    lines = [
        f"═══ STEUERREPORT {s['year']} ═══",
        f"",
        f"Geschlossene Trades: {s['trades_count']}",
        f"",
        f"── Gewinne & Verluste ──",
        f"  Bruttogewinne:        {s['total_gains']:>10.2f}€",
        f"  Bruttoverluste:       {s['total_losses']:>10.2f}€  (verrechnet)",
        f"  Gebühren (TR):        {s['total_fees']:>10.2f}€",
        f"  Netto P&L:            {s['gesamt_pnl']:>10.2f}€",
        f"",
        f"── Steuerberechnung ──",
        f"  Steuerpflichtig:      {s['steuerpflichtig_brutto']:>10.2f}€",
        f"  − Freibetrag:         {s['freistellungsauftrag']:>10.2f}€",
        f"  = Bemessungsgrundlage:{s['nach_freibetrag']:>10.2f}€",
        f"",
        f"  KESt (25%):           {s['kest']:>10.2f}€",
        f"  Soli (5.5% auf KESt): {s['soli']:>10.2f}€",
        f"  ═══════════════════════════════",
        f"  STEUER GESAMT:        {s['steuer_gesamt']:>10.2f}€",
        f"  Effektiver Satz:      {s['effektiver_steuersatz']}",
        f"",
        f"── After-Tax ──",
        f"  P&L nach Steuer:      {s['after_tax_pnl']:>10.2f}€",
        f"  Verlustvortrag:       {s['verlustvortrag']:>10.2f}€",
    ]
    
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    year = sys.argv[1] if len(sys.argv) > 1 else None
    
    print(generate_jahresreport(year))
    
    print("\n── Tax-Loss Harvesting ──")
    tlh = tax_loss_harvesting_suggestions()
    print(f"  YTD Gewinne: {tlh['ytd_gains']:.2f}€")
    print(f"  Freibetrag genutzt: {tlh['freibetrag_genutzt']:.2f}€ / Rest: {tlh['freibetrag_rest']:.2f}€")
