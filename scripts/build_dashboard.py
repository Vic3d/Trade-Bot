#!/usr/bin/env python3
"""Build Trading Dashboard v2 — Tabs (Echt + Paper), klar & verständlich."""

import sqlite3, json
from pathlib import Path
from datetime import datetime

WS = Path('/data/.openclaw/workspace')
DATA = WS / 'data'
OUT = WS / 'trading-dashboard' / 'index.html'

def load_data():
    d = {}
    # Real portfolio
    d['real'] = json.loads((WS / 'trading_config.json').read_text()).get('positions', {})
    
    # Paper portfolio from SQLite
    db = sqlite3.connect(str(DATA / 'trading.db'))
    db.row_factory = sqlite3.Row
    
    try:
        d['open'] = [dict(r) for r in db.execute('SELECT * FROM paper_portfolio WHERE status="OPEN" ORDER BY ticker').fetchall()]
    except:
        d['open'] = []
    try:
        d['closed'] = [dict(r) for r in db.execute('SELECT * FROM paper_portfolio WHERE status="CLOSED" ORDER BY close_date DESC').fetchall()]
    except:
        d['closed'] = []
    try:
        d['fund'] = {r['key']: r['value'] for r in db.execute('SELECT * FROM paper_fund').fetchall()}
    except:
        d['fund'] = {'starting_capital': 1000, 'current_cash': 0, 'total_realized_pnl': 0}
    
    # JSON data
    for name in ['current_regime', 'sector_rotation', 'sentiment', 'correlations', 'backtest_results', 'auto_trader_last_run']:
        p = DATA / f'{name}.json'
        d[name] = json.loads(p.read_text()) if p.exists() else {}
    
    db.close()
    return d

def build_html(d):
    real = d['real']
    open_pos = d['open']
    closed = d['closed']
    fund = d['fund']
    regime = d.get('current_regime', {})
    trader = d.get('auto_trader_last_run', {})
    sector = d.get('sector_rotation', {})
    sentiment = d.get('sentiment', {})
    backtest = d.get('backtest_results', {})
    
    # Calculate paper fund value
    starting = fund.get('starting_capital', 1000)
    cash = fund.get('current_cash', 0)
    realized = fund.get('total_realized_pnl', 0)
    invested = sum(p['entry_price'] * p['shares'] for p in open_pos)
    total_value = cash + invested
    perf_pct = ((total_value - starting) / starting) * 100 if starting else 0
    
    total_closed = len(closed)
    wins = sum(1 for t in closed if (t.get('pnl_eur') or 0) > 0)
    losses = total_closed - wins
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
    total_profit = sum(t.get('pnl_eur', 0) or 0 for t in closed)
    
    # VIX info
    vix = regime.get('vix', trader.get('vix', '?'))
    regime_name = regime.get('regime', 'UNKNOWN')
    regime_colors = {'CALM': '#00ff88', 'NORMAL': '#3498db', 'ELEVATED': '#ffaa00', 'PANIC': '#ff4444'}
    regime_color = regime_colors.get(regime_name, '#888')
    
    # Strategy mapping
    strat_names = {
        'PS1': 'Iran/Öl', 'PS2': 'Tanker-Lag', 'PS3': 'NATO/Defense',
        'PS4': 'Edelmetalle', 'PS5': 'Dünger/Agrar'
    }
    strat_colors = {
        'PS1': '#3498db', 'PS2': '#e67e22', 'PS3': '#2ecc71',
        'PS4': '#f1c40f', 'PS5': '#8b4513'
    }
    
    # Build real portfolio rows
    real_rows = ""
    for ticker, pos in real.items():
        if pos.get('status') == 'CLOSED':
            continue
        name = pos.get('name', ticker)
        entry = pos.get('entry_eur', '?')
        stop = pos.get('stop_eur')
        targets = pos.get('targets_eur', [])
        target_str = f"{targets[0]}€" if targets else "—"
        notes = pos.get('notes', '')
        stop_str = f"{stop}€" if stop else '<span style="color:#ff4444;font-weight:bold">⚠️ KEIN STOP</span>'
        stop_class = '' if stop else 'style="background:rgba(255,68,68,0.1)"'
        real_rows += f"""<tr {stop_class}>
            <td><strong>{ticker}</strong></td>
            <td>{name}</td>
            <td>{entry}€</td>
            <td>{stop_str}</td>
            <td>{target_str}</td>
            <td style="font-size:0.85em;color:#888">{notes[:50]}</td>
        </tr>"""
    
    # Build open paper positions rows
    open_rows = ""
    for p in open_pos:
        s = p.get('strategy', '?')
        badge_color = strat_colors.get(s, '#888')
        sname = strat_names.get(s, s)
        entry = p.get('entry_price', 0)
        shares = p.get('shares', 0)
        stop = p.get('stop_price', 0)
        target = p.get('target_price', 0)
        vol = entry * shares
        open_rows += f"""<tr>
            <td><strong>{p['ticker']}</strong></td>
            <td><span class="badge" style="background:{badge_color}">{s}</span> {sname}</td>
            <td>{entry:.2f}€</td>
            <td>{shares:.4f}</td>
            <td>{stop:.2f}€</td>
            <td>{target:.2f}€</td>
            <td>{vol:.0f}€</td>
        </tr>"""
    
    # Build closed trades rows
    closed_rows = ""
    for i, t in enumerate(closed, 1):
        s = t.get('strategy', '?')
        badge_color = strat_colors.get(s, '#888')
        sname = strat_names.get(s, s)
        pnl = t.get('pnl_eur', 0) or 0
        pnl_pct = t.get('pnl_pct', 0) or 0
        pnl_color = '#00ff88' if pnl >= 0 else '#ff4444'
        pnl_icon = '✅' if pnl >= 0 else '❌'
        entry = t.get('entry_price', 0)
        exit_p = t.get('close_price', 0)
        shares = t.get('shares', 0)
        reason = t.get('notes', '').replace('TARGET HIT', '🎯 Ziel erreicht').replace('STOP HIT', '🛑 Stop ausgelöst')
        date = t.get('close_date', '?')
        closed_rows += f"""<tr>
            <td>{i}</td>
            <td><strong>{t['ticker']}</strong></td>
            <td><span class="badge" style="background:{badge_color}">{s}</span></td>
            <td>{entry:.2f}€</td>
            <td>{exit_p:.2f}€</td>
            <td>{shares:.4f}</td>
            <td style="color:{pnl_color};font-weight:bold">{pnl_icon} {pnl:+.2f}€</td>
            <td style="color:{pnl_color};font-weight:bold">{pnl_pct:+.1f}%</td>
            <td>{reason}</td>
            <td>{date}</td>
        </tr>"""
    
    # Strategy stats
    strat_stats = {}
    for t in closed:
        s = t.get('strategy', '?')
        if s not in strat_stats:
            strat_stats[s] = {'trades': 0, 'wins': 0, 'total_pnl': 0, 'win_pnls': [], 'loss_pnls': []}
        strat_stats[s]['trades'] += 1
        pnl_pct = t.get('pnl_pct', 0) or 0
        if pnl_pct > 0:
            strat_stats[s]['wins'] += 1
            strat_stats[s]['win_pnls'].append(pnl_pct)
        else:
            strat_stats[s]['loss_pnls'].append(pnl_pct)
        strat_stats[s]['total_pnl'] += (t.get('pnl_eur', 0) or 0)
    
    strat_rows = ""
    for s in ['PS1', 'PS2', 'PS3', 'PS4', 'PS5']:
        sname = strat_names.get(s, s)
        badge_color = strat_colors.get(s, '#888')
        st = strat_stats.get(s, {'trades': 0, 'wins': 0, 'total_pnl': 0, 'win_pnls': [], 'loss_pnls': []})
        trades = st['trades']
        w = st['wins']
        l = trades - w
        wr = (w / trades * 100) if trades > 0 else 0
        avg_win = (sum(st['win_pnls']) / len(st['win_pnls'])) if st['win_pnls'] else 0
        avg_loss = (sum(st['loss_pnls']) / len(st['loss_pnls'])) if st['loss_pnls'] else 0
        total = st['total_pnl']
        wr_color = '#00ff88' if wr >= 60 else ('#ffaa00' if wr >= 40 else '#ff4444')
        total_color = '#00ff88' if total >= 0 else '#ff4444'
        
        # Visual bar for win rate
        bar_width = max(wr, 5)
        
        strat_rows += f"""<tr>
            <td><span class="badge" style="background:{badge_color}">{s}</span></td>
            <td>{sname}</td>
            <td>{trades}</td>
            <td style="color:#00ff88">{w}</td>
            <td style="color:#ff4444">{l}</td>
            <td style="color:{wr_color};font-weight:bold">
                {wr:.0f}%
                <div style="background:#2a2a4a;border-radius:4px;height:8px;margin-top:4px">
                    <div style="background:{wr_color};width:{bar_width}%;height:8px;border-radius:4px"></div>
                </div>
            </td>
            <td style="color:#00ff88">{avg_win:+.1f}%</td>
            <td style="color:#ff4444">{avg_loss:.1f}%</td>
            <td style="color:{total_color};font-weight:bold">{total:+.2f}€</td>
        </tr>"""

    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎩 Albert Trading System</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#1a1a2e; color:#e0e0e0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }}

/* Header */
.header {{ background:#16213e; padding:20px 24px; border-bottom:2px solid #0f3460; }}
.header h1 {{ font-size:1.5em; margin-bottom:8px; }}
.header .subtitle {{ color:#888; font-size:0.9em; }}
.regime-badge {{ display:inline-block; padding:4px 12px; border-radius:12px; font-weight:bold; font-size:0.85em; }}

/* Tabs */
.tabs {{ display:flex; background:#16213e; border-bottom:2px solid #0f3460; position:sticky; top:0; z-index:100; }}
.tab {{ padding:16px 32px; cursor:pointer; font-size:1.1em; font-weight:600; color:#888; border-bottom:3px solid transparent; transition:all 0.2s; }}
.tab:hover {{ color:#e0e0e0; background:rgba(255,255,255,0.05); }}
.tab.active {{ color:#00ff88; border-bottom-color:#00ff88; }}
.tab-content {{ display:none; padding:24px; }}
.tab-content.active {{ display:block; }}

/* Cards */
.cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:16px; margin-bottom:24px; }}
.card {{ background:#16213e; border-radius:12px; padding:20px; text-align:center; }}
.card .label {{ color:#888; font-size:0.8em; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }}
.card .value {{ font-size:1.8em; font-weight:bold; }}
.card .sub {{ color:#888; font-size:0.85em; margin-top:4px; }}
.green {{ color:#00ff88; }}
.red {{ color:#ff4444; }}
.yellow {{ color:#ffaa00; }}

/* Tables */
.section {{ margin-bottom:32px; }}
.section h2 {{ font-size:1.2em; margin-bottom:16px; padding-bottom:8px; border-bottom:1px solid #2a2a4a; }}
table {{ width:100%; border-collapse:collapse; font-size:0.9em; }}
th {{ background:#0f3460; padding:12px; text-align:left; font-weight:600; font-size:0.85em; text-transform:uppercase; letter-spacing:0.5px; }}
td {{ padding:10px 12px; border-bottom:1px solid #2a2a4a; }}
tr:hover {{ background:rgba(255,255,255,0.03); }}
tr:nth-child(even) {{ background:rgba(255,255,255,0.02); }}

/* Badges */
.badge {{ display:inline-block; padding:2px 10px; border-radius:10px; font-size:0.8em; font-weight:bold; color:#fff; }}

/* Explanation boxes */
.explain {{ background:#16213e; border-left:4px solid #3498db; padding:16px; border-radius:0 8px 8px 0; margin-bottom:24px; font-size:0.9em; line-height:1.6; }}
.explain strong {{ color:#3498db; }}

/* Responsive */
@media (max-width: 768px) {{
    .cards {{ grid-template-columns:repeat(2, 1fr); }}
    .tab {{ padding:12px 16px; font-size:0.95em; }}
    table {{ font-size:0.8em; }}
    td, th {{ padding:8px 6px; }}
    .header {{ padding:16px; }}
}}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
    <h1>🎩 Albert Trading System</h1>
    <div class="subtitle">
        Stand: {now} &nbsp;|&nbsp; 
        VIX: <strong>{vix}</strong> &nbsp;
        <span class="regime-badge" style="background:{regime_color}">{regime_name}</span>
    </div>
</div>

<!-- Tab Navigation -->
<div class="tabs">
    <div class="tab active" onclick="switchTab('paper')">🧪 Paper Trades</div>
    <div class="tab" onclick="switchTab('real')">📈 Echtes Portfolio</div>
</div>

<!-- TAB: Paper Trades -->
<div id="tab-paper" class="tab-content active">
    
    <!-- Was bedeuten die Zahlen? -->
    <div class="explain">
        <strong>💡 So liest du das Dashboard:</strong><br>
        Albert verwaltet ein imaginäres Portfolio mit 1.000€ Startkapital. 
        Er kauft und verkauft Aktien nach 5 Strategien (PS1–PS5). 
        Jeder Trade hat einen <strong>Stop</strong> (Verlustgrenze) und ein <strong>Ziel</strong> (Gewinnziel). 
        <strong>Win-Rate</strong> = wie viel Prozent der Trades profitabel waren.
    </div>
    
    <!-- Fund Overview Cards -->
    <div class="cards">
        <div class="card">
            <div class="label">Startkapital</div>
            <div class="value">1.000€</div>
        </div>
        <div class="card">
            <div class="label">Aktueller Wert</div>
            <div class="value {'green' if perf_pct >= 0 else 'red'}">{total_value:.0f}€</div>
            <div class="sub {'green' if perf_pct >= 0 else 'red'}">{perf_pct:+.1f}%</div>
        </div>
        <div class="card">
            <div class="label">Bares Geld</div>
            <div class="value">{cash:.0f}€</div>
            <div class="sub">{cash/starting*100:.0f}% vom Fund</div>
        </div>
        <div class="card">
            <div class="label">Realisierter Gewinn</div>
            <div class="value {'green' if realized >= 0 else 'red'}">{realized:+.0f}€</div>
            <div class="sub">aus {total_closed} geschl. Trades</div>
        </div>
        <div class="card">
            <div class="label">Win-Rate</div>
            <div class="value {'green' if win_rate >= 50 else 'red'}">{win_rate:.0f}%</div>
            <div class="sub">{wins} ✅ / {losses} ❌</div>
        </div>
        <div class="card">
            <div class="label">Offene Positionen</div>
            <div class="value">{len(open_pos)}</div>
            <div class="sub">{invested:.0f}€ investiert</div>
        </div>
    </div>
    
    <!-- Geschlossene Trades -->
    <div class="section">
        <h2>💰 Abgeschlossene Trades — Was hat Albert gehandelt?</h2>
        <div class="explain">
            <strong>Buy-In</strong> = Einkaufspreis &nbsp;|&nbsp; 
            <strong>Exit</strong> = Verkaufspreis &nbsp;|&nbsp; 
            <strong>P&L</strong> = Gewinn oder Verlust &nbsp;|&nbsp;
            ✅ = Gewinn &nbsp;|&nbsp; ❌ = Verlust
        </div>
        <table>
            <tr>
                <th>#</th>
                <th>Aktie</th>
                <th>Strategie</th>
                <th>Buy-In</th>
                <th>Exit</th>
                <th>Stück</th>
                <th>Gewinn/Verlust</th>
                <th>P&L %</th>
                <th>Grund</th>
                <th>Datum</th>
            </tr>
            {closed_rows}
        </table>
        {f'<p style="color:#888;text-align:center;padding:20px">Noch keine geschlossenen Trades.</p>' if not closed_rows else ''}
    </div>
    
    <!-- Offene Positionen -->
    <div class="section">
        <h2>📊 Offene Positionen — Was hält Albert gerade?</h2>
        <div class="explain">
            <strong>Stop</strong> = Wenn der Kurs hierhin fällt, wird automatisch verkauft (Verlustbegrenzung)<br>
            <strong>Ziel</strong> = Wenn der Kurs hierhin steigt, wird Gewinn mitgenommen<br>
            <strong>Volumen</strong> = Wie viel Geld steckt in dieser Position
        </div>
        <table>
            <tr>
                <th>Aktie</th>
                <th>Strategie</th>
                <th>Einkauf</th>
                <th>Stück</th>
                <th>Stop</th>
                <th>Ziel</th>
                <th>Volumen</th>
            </tr>
            {open_rows}
        </table>
    </div>
    
    <!-- Strategie-Übersicht -->
    <div class="section">
        <h2>🧠 Strategie-Übersicht — Welche Strategie funktioniert?</h2>
        <div class="explain">
            Albert handelt nach 5 Strategien. Jede hat eine andere These warum bestimmte Aktien steigen sollten.<br>
            <strong>Win-Rate</strong> = Prozent der profitablen Trades. Über 50% = die Strategie funktioniert.
        </div>
        <table>
            <tr>
                <th>ID</th>
                <th>Strategie</th>
                <th>Trades</th>
                <th>✅</th>
                <th>❌</th>
                <th>Win-Rate</th>
                <th>⌀ Gewinn</th>
                <th>⌀ Verlust</th>
                <th>Gesamt</th>
            </tr>
            {strat_rows}
        </table>
    </div>
    
</div>

<!-- TAB: Echtes Portfolio -->
<div id="tab-real" class="tab-content">
    
    <div class="explain">
        <strong>💡 Victors echtes Portfolio.</strong> Diese Positionen sind mit echtem Geld in Trade Republic gekauft. 
        Albert überwacht sie und warnt bei Problemen.
    </div>
    
    <div class="section">
        <h2>📈 Aktive Positionen</h2>
        <div class="explain">
            <strong>Entry</strong> = Kaufpreis &nbsp;|&nbsp; 
            <strong>Stop</strong> = Automatischer Verkauf bei Verlust &nbsp;|&nbsp; 
            <strong>Ziel</strong> = Gewinnziel &nbsp;|&nbsp;
            <span style="color:#ff4444">⚠️ KEIN STOP</span> = Gefährlich! Ungeschützte Position.
        </div>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>Ziel</th>
                <th>Notiz</th>
            </tr>
            {real_rows}
        </table>
    </div>
    
    <div class="cards" style="margin-top:24px">
        <div class="card">
            <div class="label">Markt-Regime</div>
            <div class="value" style="color:{regime_color}">{regime_name}</div>
            <div class="sub">VIX: {vix}</div>
        </div>
        <div class="card">
            <div class="label">Positionen</div>
            <div class="value">{sum(1 for p in real.values() if p.get('status') != 'CLOSED')}</div>
            <div class="sub">aktiv</div>
        </div>
        <div class="card">
            <div class="label">Ohne Stop ⚠️</div>
            <div class="value red">{sum(1 for p in real.values() if not p.get('stop_eur') and p.get('status') != 'CLOSED')}</div>
            <div class="sub">ungeschützt</div>
        </div>
    </div>
</div>

<!-- JavaScript -->
<script>
function switchTab(tab) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    // Highlight correct tab
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(t => {{
        if ((tab === 'paper' && t.textContent.includes('Paper')) || 
            (tab === 'real' && t.textContent.includes('Echt'))) {{
            t.classList.add('active');
        }}
    }});
}}
</script>

</body>
</html>"""
    return html

def main():
    d = load_data()
    html = build_html(d)
    
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    
    # Also copy to root + public for Vercel
    (WS / 'index.html').write_text(html)
    pub = WS / 'public'
    pub.mkdir(exist_ok=True)
    (pub / 'index.html').write_text(html)
    
    size = len(html) / 1024
    print(f"✅ Dashboard generiert: {OUT} ({size:.1f} KB)")
    print(f"   + {WS / 'index.html'}")
    print(f"   + {pub / 'index.html'}")

if __name__ == '__main__':
    main()
