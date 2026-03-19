#!/usr/bin/env python3
"""
Trade Proposal System — Strukturierte Trade-Empfehlungen
=========================================================
Signal Engine → Conviction Score → Risk Check → Proposal
Victor genehmigt oder lehnt ab.

Sprint 4 | TradeMind Bauplan
"""

import sqlite3, json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'intelligence'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))

DB_PATH = Path('/data/.openclaw/workspace/data/trading.db')
PROPOSALS_PATH = Path('/data/.openclaw/workspace/data/proposals.json')


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def check_risk_gates(ticker, entry_price, stop, position_size_eur, portfolio_value=14000):
    """Pre-Trade Risk Gates. Returns: (passed, reasons)"""
    conn = get_db()
    issues = []
    
    # Gate 1: Max 5 offene Positionen
    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
    if open_count >= 5:
        issues.append(f"⚠️ {open_count}/5 Positionen offen — Maximum erreicht")
    
    # Gate 2: Max 2% Risiko pro Trade
    risk_per_share = abs(entry_price - stop)
    max_risk = portfolio_value * 0.02
    if position_size_eur and risk_per_share * (position_size_eur / entry_price) > max_risk:
        issues.append(f"⚠️ Risiko {risk_per_share:.2f}€/Share überschreitet 2%-Regel ({max_risk:.0f}€)")
    
    # Gate 3: Kein Duplikat (gleicher Ticker schon offen)
    existing = conn.execute(
        "SELECT id FROM trades WHERE ticker=? AND status='OPEN'", (ticker.upper(),)
    ).fetchone()
    if existing:
        issues.append(f"⚠️ {ticker} bereits offen (Trade #{existing['id']})")
    
    # Gate 4: Regime-Check
    regime = conn.execute(
        "SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if regime and regime['regime'] in ('BEAR', 'CRISIS'):
        issues.append(f"⚠️ Regime {regime['regime']} — nur Hedges/Gold erlaubt")
    
    conn.close()
    return len(issues) == 0, issues


def generate_proposal(ticker, strategy, direction, entry_price, stop, target,
                      thesis='', signal_sources=None):
    """
    Generiert einen strukturierten Trade Proposal.
    
    Returns: dict mit Proposal-Daten für Discord-Nachricht
    """
    # Conviction Score
    try:
        from conviction_scorer import calculate_conviction
        conviction = calculate_conviction(ticker, strategy, entry_price, stop, target)
    except:
        conviction = {'score': 50, 'recommendation': 'MANUAL', 'factors': {}, 'weakest': [], 'strongest': []}
    
    # TRA-143: Position Sizing
    # size_eur = (portfolio × 0.02) / ((entry - stop) / entry)
    # Lese Startkapital aus trading_config.json wenn verfügbar
    config_path = Path('/data/.openclaw/workspace/trading_config.json')
    try:
        cfg = json.loads(config_path.read_text())
        portfolio_value = cfg.get('settings', {}).get('start_capital', 10000)
    except:
        portfolio_value = 10000
    
    risk_per_share = abs(entry_price - stop)
    if risk_per_share > 0 and entry_price > 0:
        risk_fraction = risk_per_share / entry_price
        position_eur = round((portfolio_value * 0.02) / risk_fraction, 2)
        shares = int(position_eur / entry_price)
        risk_eur = shares * risk_per_share
    else:
        shares = 0
        position_eur = 0
        risk_eur = 0
    
    # CRV
    reward_per_share = abs(target - entry_price)
    crv = round(reward_per_share / risk_per_share, 1) if risk_per_share > 0 else 0
    
    # Risk Gates
    passed, risk_issues = check_risk_gates(ticker, entry_price, stop, position_eur)
    
    # Regime
    conn = get_db()
    regime_row = conn.execute("SELECT regime, vix FROM regime_history ORDER BY date DESC LIMIT 1").fetchone()
    regime = regime_row['regime'] if regime_row else 'UNKNOWN'
    vix = regime_row['vix'] if regime_row else 0
    conn.close()
    
    # Proposal-ID (fortlaufend)
    proposals = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
    proposal_id = f"TP-{len(proposals) + 1}"
    
    proposal = {
        'id': proposal_id,
        'ticker': ticker.upper(),
        'strategy': strategy,
        'direction': direction.upper(),
        'entry_price': entry_price,
        'stop': stop,
        'target': target,
        'crv': crv,
        'shares': shares,
        'position_eur': round(position_eur, 2),
        'risk_eur': round(risk_eur, 2),
        'max_loss_eur': round(risk_eur + 2, 2),  # +2€ TR Gebühren
        'conviction': conviction['score'],
        'recommendation': conviction['recommendation'],
        'regime': regime,
        'vix': vix,
        'thesis': thesis,
        'signal_sources': signal_sources or [],
        'risk_passed': passed,
        'risk_issues': risk_issues,
        'factor_breakdown': conviction['factors'],
        'weakest_factors': conviction['weakest'],
        'strongest_factors': conviction['strongest'],
        'status': 'PENDING',
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    
    # Speichern
    proposals.append(proposal)
    PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
    
    return proposal


def format_discord_proposal(p):
    """Formatiert Proposal für Discord."""
    risk_emoji = '✅' if p['risk_passed'] else '⚠️'
    conv_emoji = '🟢' if p['conviction'] >= 65 else ('🟡' if p['conviction'] >= 50 else '🔴')
    
    lines = [
        f"📊 **TRADE PROPOSAL — {p['id']}**",
        f"",
        f"**{p['direction']} {p['ticker']}** | Strategy: {p['strategy']}",
        f"Entry: {p['entry_price']:.2f}€ | Stop: {p['stop']:.2f}€ | Target: {p['target']:.2f}€",
        f"CRV: **{p['crv']}:1** | Shares: {p['shares']} | Position: {p['position_eur']:.0f}€",
        f"",
        f"{conv_emoji} Conviction: **{p['conviction']:.0f}/100** → {p['recommendation']}",
        f"Regime: {p['regime']} | VIX: {p['vix']:.1f}",
    ]
    
    # Top/Bottom Faktoren
    if p['strongest_factors']:
        strong = ' | '.join(f"{f['factor']}={f['score']}" for f in p['strongest_factors'])
        lines.append(f"💪 Stark: {strong}")
    if p['weakest_factors']:
        weak = ' | '.join(f"{f['factor']}={f['score']}" for f in p['weakest_factors'])
        lines.append(f"⚡ Schwach: {weak}")
    
    lines.append(f"")
    lines.append(f"{risk_emoji} Risk: {p['risk_eur']:.0f}€ ({p['risk_eur']/140:.1f}%) | Max Loss: {p['max_loss_eur']:.0f}€")
    
    if p['risk_issues']:
        for issue in p['risk_issues']:
            lines.append(f"  {issue}")
    
    if p['thesis']:
        lines.append(f"")
        lines.append(f"📝 {p['thesis']}")
    
    lines.append(f"")
    lines.append(f"→ **APPROVE** / **REJECT**")
    
    return '\n'.join(lines)


def approve_proposal(proposal_id):
    """Genehmigt einen Proposal und loggt den Trade."""
    proposals = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
    
    for p in proposals:
        if p['id'] == proposal_id and p['status'] == 'PENDING':
            p['status'] = 'APPROVED'
            p['approved_at'] = datetime.now(timezone.utc).isoformat()
            PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
            
            # Trade öffnen
            from trade_journal import open_trade
            trade_id = open_trade(
                p['ticker'], p['strategy'], p['direction'],
                p['entry_price'], p['stop'], p['target'],
                shares=p['shares'], thesis=p['thesis'],
                trade_type='paper', conviction=int(p['conviction'])
            )
            return trade_id
    
    return None


def reject_proposal(proposal_id, reason=''):
    """Lehnt einen Proposal ab."""
    proposals = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
    
    for p in proposals:
        if p['id'] == proposal_id and p['status'] == 'PENDING':
            p['status'] = 'REJECTED'
            p['rejected_at'] = datetime.now(timezone.utc).isoformat()
            p['reject_reason'] = reason
            PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
            return True
    
    return False


if __name__ == '__main__':
    if len(sys.argv) >= 6:
        ticker = sys.argv[1]
        strategy = sys.argv[2]
        entry = float(sys.argv[3])
        stop = float(sys.argv[4])
        target = float(sys.argv[5])
        thesis = sys.argv[6] if len(sys.argv) > 6 else ''
        
        p = generate_proposal(ticker, strategy, 'LONG', entry, stop, target, thesis)
        print(format_discord_proposal(p))
    else:
        print("Usage: trade_proposal.py TICKER STRATEGY ENTRY STOP TARGET [THESIS]")
        print("Example: trade_proposal.py EQNR.OL S1 28.40 27.00 35.00 'Öl-These + Iran-Eskalation'")
