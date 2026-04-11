#!/usr/bin/env python3
"""
Risk Manager — Portfolio-Risiko-Analyse
========================================
Sector Exposure, Korrelation, Drawdown Monitor,
Pre-Trade Risk Gates.

Sprint 4 | TradeMind Bauplan
"""

import sqlite3, json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))


DB_PATH = WS / 'data/trading.db'

# Ticker → Sektor Mapping
SECTOR_MAP = {
    'EQNR.OL': 'Energy', 'OXY': 'Energy', 'TTE.PA': 'Energy',
    'FRO': 'Energy/Tanker', 'DHT': 'Energy/Tanker',
    'NVDA': 'Tech/AI', 'MSFT': 'Tech/AI', 'PLTR': 'Tech/AI', 'ASML.AS': 'Tech/Semi',
    'RHM.DE': 'Defense', 'HO.PA': 'Defense', 'KTOS': 'Defense', 'HII': 'Defense',
    'BAYN.DE': 'Pharma', 'NOVO-B.CO': 'Pharma',
    'RIO.L': 'Mining', 'BHP.L': 'Mining', 'GLEN.L': 'Mining',
    'HL': 'Precious', 'PAAS': 'Precious', 'AG': 'Precious',
    'MOS': 'Agriculture',
}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def sector_exposure():
    """Berechnet Sektor-Konzentration offener Positionen."""
    conn = get_db()
    trades = conn.execute("""
        SELECT ticker, position_size_eur, entry_price, shares
        FROM trades WHERE status='OPEN'
    """).fetchall()
    conn.close()
    
    sectors = defaultdict(lambda: {'tickers': [], 'total_eur': 0, 'count': 0})
    total_portfolio = 0
    
    for t in trades:
        ticker = t['ticker']
        pos_eur = t['position_size_eur'] or (t['entry_price'] * (t['shares'] or 1))
        sector = SECTOR_MAP.get(ticker, 'Other')
        
        sectors[sector]['tickers'].append(ticker)
        sectors[sector]['total_eur'] += pos_eur
        sectors[sector]['count'] += 1
        total_portfolio += pos_eur
    
    # Prozentuale Verteilung
    result = {}
    for sector, data in sectors.items():
        pct = (data['total_eur'] / total_portfolio * 100) if total_portfolio > 0 else 0
        over_concentrated = pct > 25
        result[sector] = {
            'tickers': data['tickers'],
            'total_eur': round(data['total_eur'], 2),
            'count': data['count'],
            'pct': round(pct, 1),
            'over_concentrated': over_concentrated,
        }
    
    return result, total_portfolio


def portfolio_drawdown():
    """Berechnet aktuellen Drawdown basierend auf geschlossenen Trades."""
    conn = get_db()
    trades = conn.execute("""
        SELECT pnl_eur, exit_date FROM trades 
        WHERE status IN ('WIN','LOSS') AND pnl_eur IS NOT NULL
        ORDER BY exit_date
    """).fetchall()
    conn.close()
    
    if not trades:
        return {'current_dd': 0, 'max_dd': 0, 'peak_equity': 0, 'current_equity': 0}
    
    equity = 0
    peak = 0
    max_dd = 0
    max_dd_date = ''
    
    for t in trades:
        equity += t['pnl_eur']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_date = t['exit_date']
    
    current_dd = peak - equity
    
    return {
        'current_equity': round(equity, 2),
        'peak_equity': round(peak, 2),
        'current_dd': round(current_dd, 2),
        'max_dd': round(max_dd, 2),
        'max_dd_date': max_dd_date,
    }


def position_count_check(max_positions=5):
    """Prüft ob Positions-Limit erreicht ist."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
    conn.close()
    return {
        'open_positions': count,
        'max_allowed': max_positions,
        'can_open': count < max_positions,
    }


def correlation_risk():
    """Portfolio-Korrelationsrisiko."""
    corr_path = WS / 'data/correlations.json'
    if not corr_path.exists():
        return {'avg_correlation': 0, 'high_corr_pairs': []}
    
    data = json.loads(corr_path.read_text(encoding="utf-8"))
    
    conn = get_db()
    open_tickers = [r['ticker'] for r in conn.execute(
        "SELECT DISTINCT ticker FROM trades WHERE status='OPEN'"
    ).fetchall()]
    conn.close()
    
    high_pairs = []
    correlations = []
    
    for i, t1 in enumerate(open_tickers):
        for t2 in open_tickers[i+1:]:
            key = f"{t1}_{t2}"
            key2 = f"{t2}_{t1}"
            corr = data.get(key, data.get(key2))
            if corr is not None:
                correlations.append(abs(corr))
                if abs(corr) > 0.7:
                    high_pairs.append({
                        'pair': f"{t1} ↔ {t2}",
                        'correlation': round(corr, 3)
                    })
    
    avg_corr = sum(correlations) / len(correlations) if correlations else 0
    
    return {
        'avg_correlation': round(avg_corr, 3),
        'high_corr_pairs': high_pairs,
        'diversified': avg_corr < 0.5,
    }


def full_risk_report():
    """Kompletter Risiko-Report."""
    sectors, total = sector_exposure()
    dd = portfolio_drawdown()
    pos = position_count_check()
    corr = correlation_risk()
    
    # Gesamtrisiko-Score (0-100, niedrig = sicher)
    risk_score = 0
    
    # Sektor-Konzentration
    max_sector_pct = max(s['pct'] for s in sectors.values()) if sectors else 0
    if max_sector_pct > 30: risk_score += 30
    elif max_sector_pct > 25: risk_score += 20
    elif max_sector_pct > 20: risk_score += 10
    
    # Drawdown
    if dd['current_dd'] > 500: risk_score += 30
    elif dd['current_dd'] > 200: risk_score += 20
    elif dd['current_dd'] > 100: risk_score += 10
    
    # Positions
    if pos['open_positions'] >= 5: risk_score += 20
    elif pos['open_positions'] >= 4: risk_score += 10
    
    # Korrelation
    if corr['avg_correlation'] > 0.6: risk_score += 20
    elif corr['avg_correlation'] > 0.4: risk_score += 10
    
    risk_label = 'LOW' if risk_score < 30 else ('MEDIUM' if risk_score < 60 else 'HIGH')
    
    return {
        'risk_score': risk_score,
        'risk_label': risk_label,
        'total_portfolio_eur': round(total, 2),
        'sector_exposure': sectors,
        'drawdown': dd,
        'positions': pos,
        'correlation': corr,
    }


if __name__ == '__main__':
    report = full_risk_report()
    
    emoji = '🟢' if report['risk_label'] == 'LOW' else ('🟡' if report['risk_label'] == 'MEDIUM' else '🔴')
    print(f"═══ Risk Report ═══")
    print(f"  {emoji} Risk Score: {report['risk_score']}/100 ({report['risk_label']})")
    print(f"  Portfolio: {report['total_portfolio_eur']:.0f}€")
    print(f"  Positionen: {report['positions']['open_positions']}/{report['positions']['max_allowed']}")
    
    print(f"\n── Sektor-Exposure ──")
    for sector, data in sorted(report['sector_exposure'].items(), key=lambda x: x[1]['pct'], reverse=True):
        warn = ' ⚠️ OVER' if data['over_concentrated'] else ''
        print(f"  {sector:18} {data['pct']:5.1f}% | {data['total_eur']:8.0f}€ | {', '.join(data['tickers'])}{warn}")
    
    print(f"\n── Drawdown ──")
    dd = report['drawdown']
    print(f"  Equity: {dd['current_equity']:+.0f}€ | Peak: {dd['peak_equity']:.0f}€ | Max DD: {dd['max_dd']:.0f}€")
    
    print(f"\n── Korrelation ──")
    c = report['correlation']
    print(f"  Avg: {c['avg_correlation']:.3f} | Diversifiziert: {'✅' if c['diversified'] else '❌'}")
    for pair in c['high_corr_pairs']:
        print(f"  ⚠️ {pair['pair']}: {pair['correlation']}")
