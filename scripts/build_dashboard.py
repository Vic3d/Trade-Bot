#!/usr/bin/env python3
"""Build Trading Dashboard v2 — Tabs (Echt + Paper), klar & verständlich."""

import sqlite3, json, urllib.request, time
from pathlib import Path
from datetime import datetime

WS = Path('/data/.openclaw/workspace')
DATA = WS / 'data'
OUT = WS / 'trading-dashboard' / 'index.html'

def yahoo_price(ticker):
    """Fetch current price from Yahoo Finance."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.load(r)
        meta = d['chart']['result'][0]['meta']
        return meta['regularMarketPrice'], meta.get('currency', 'USD')
    except:
        return None, None

def get_live_prices():
    """Fetch all live prices and FX rates."""
    prices = {}
    # FX rates
    for fx in ['EURUSD=X', 'EURNOK=X', 'EURGBP=X', 'EURDKK=X']:
        p, _ = yahoo_price(fx)
        prices[fx] = p or 1.0
        time.sleep(0.2)
    
    # All portfolio tickers
    tickers = ['NVDA', 'MSFT', 'PLTR', 'EQNR.OL', 'RIO.L', 'BAYN.DE',
               'OXY', 'FRO', 'DHT', 'HL', 'PAAS', 'MOS', 'TTE.PA',
               'HO.PA', 'GLEN.L', 'ASML.AS', 'NOVO-B.CO', 'HAG.DE']
    for t in tickers:
        p, ccy = yahoo_price(t)
        if p:
            # Convert to EUR
            if ccy == 'USD':
                prices[t] = p / prices['EURUSD=X']
            elif ccy == 'NOK':
                prices[t] = p / prices['EURNOK=X']
            elif ccy in ('GBp', 'GBX'):
                prices[t] = (p / 100) / prices['EURGBP=X']
            elif ccy == 'GBP':
                prices[t] = p / prices['EURGBP=X']
            elif ccy == 'DKK':
                prices[t] = p / prices['EURDKK=X']
            else:
                prices[t] = p
        time.sleep(0.2)
    return prices

def load_data():
    d = {}
    # Real portfolio
    d['real'] = json.loads((WS / 'trading_config.json').read_text()).get('positions', {})
    
    # Live prices
    print("📡 Hole Live-Kurse von Yahoo Finance...")
    d['prices'] = get_live_prices()
    print(f"   {len(d['prices'])} Kurse geladen")
    
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

    # Strategies from Single Source of Truth
    strategies_path = DATA / 'strategies.json'
    if strategies_path.exists():
        all_strats = json.loads(strategies_path.read_text())
        d['strategies'] = {k: v for k, v in all_strats.items() if k != 'emerging_themes'}
        d['emerging_themes_def'] = all_strats.get('emerging_themes', {})
    else:
        d['strategies'] = {}
        d['emerging_themes_def'] = {}
    
    db.close()
    return d

def build_strategy_deep_dive(strategies):
    """Build the Strategy Deep Dive HTML section with collapsible dropdown cards."""
    if not strategies:
        return '<p style="color:#888;text-align:center;padding:20px">Keine Strategie-Daten verfügbar (strategies.json fehlt?).</p>'

    health_emoji = {
        'green': '🟢', 'green_hot': '🔥', 'yellow': '🟡', 'red': '🔴',
    }
    health_color = {
        'green': '#00ff88', 'green_hot': '#00ffcc', 'yellow': '#ffaa00', 'red': '#ff4444',
    }
    type_badge = {
        'paper': '<span style="background:#3498db;color:#fff;padding:2px 8px;border-radius:8px;font-size:0.8em">📄 PAPER</span>',
        'real': '<span style="background:#e74c3c;color:#fff;padding:2px 8px;border-radius:8px;font-size:0.8em">💰 REAL</span>',
    }

    cards = ""
    for strat_id, strat in sorted(strategies.items()):
        name = strat.get('name', strat_id)
        stype = strat.get('type', 'paper')
        health = strat.get('health', 'yellow')
        status = strat.get('status', 'active')
        thesis = strat.get('thesis', '')
        sector = strat.get('sector', '')
        kill_trigger = strat.get('kill_trigger', '')
        entry_trigger = strat.get('entry_trigger', '')
        learning_q = strat.get('learning_question', '')
        tickers = strat.get('tickers', [])
        watchlist_tickers = strat.get('watchlist_tickers', [])
        horizon = strat.get('horizon_weeks', '?')
        genesis = strat.get('genesis', {})

        h_emoji = health_emoji.get(health, '⚪')
        h_color = health_color.get(health, '#888')
        type_b = type_badge.get(stype, '')

        ticker_badges = " ".join(
            f'<span style="background:#1a3a5c;color:#7ec8e3;padding:2px 8px;border-radius:6px;font-size:0.8em;margin:2px;display:inline-block">{t}</span>'
            for t in tickers
        ) if tickers else ''
        watchlist_badges = " ".join(
            f'<span style="background:#2a1a3c;color:#c8a0e3;padding:2px 8px;border-radius:6px;font-size:0.8em;margin:2px;display:inline-block">👁 {t}</span>'
            for t in watchlist_tickers
        ) if watchlist_tickers else ''
        all_badges = (ticker_badges + " " + watchlist_badges).strip() or '<span style="color:#888">–</span>'

        status_str = {"active": "✅ Aktiv", "watchlist": "👁 Watchlist", "closed": "❌ Geschlossen"}.get(status, status)

        # Genesis detail section (inside dropdown)
        genesis_detail = ""
        if genesis:
            trigger = genesis.get('trigger', '')
            chain = genesis.get('logical_chain', '')
            conviction = genesis.get('conviction_at_start', 0)
            created = genesis.get('created', '')
            sources = genesis.get('sources', [])
            steps = genesis.get('analysis_steps', [])
            counters = genesis.get('counter_arguments_checked', [])

            steps_html = "".join(f"<li>{s}</li>" for s in steps) if steps else ""
            counters_html = "".join(f"<li style='color:#ffaa00'>{c}</li>" for c in counters) if counters else ""
            sources_str = ", ".join(sources) if sources else "–"
            conviction_stars = "⭐" * conviction + "☆" * (5 - conviction)

            genesis_detail = f"""
                <div style="background:#0d1b2a;border-radius:8px;padding:14px;margin-top:12px;font-size:0.88em">
                    <div style="color:#aaa;margin-bottom:8px">
                        📅 Erstellt: {created} &nbsp;|&nbsp; Überzeugung: {conviction_stars} ({conviction}/5)
                        &nbsp;|&nbsp; Quellen: {sources_str}
                    </div>
                    <div style="margin-bottom:8px">
                        <strong style="color:#3498db">⚡ Auslöser:</strong> {trigger}
                    </div>
                    {f'<div style="margin-bottom:8px"><strong style="color:#2ecc71">🔗 Logik-Kette:</strong><br>{chain}</div>' if chain else ''}
                    {f'<div style="margin-bottom:8px"><strong style="color:#e0e0e0">🔍 Analyse-Schritte:</strong><ul style="margin:6px 0 0 20px;color:#ccc">{steps_html}</ul></div>' if steps_html else ''}
                    {f'<div><strong style="color:#ffaa00">⚠️ Gegenargumente geprüft:</strong><ul style="margin:6px 0 0 20px">{counters_html}</ul></div>' if counters_html else ''}
                </div>"""

        # Build collapsible card using div + JS toggle (all closed by default)
        cards += f"""
        <div class="strat-card" style="border-left:4px solid {h_color}">
            <div class="strat-header" onclick="this.parentElement.classList.toggle('open')">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                    <div style="display:flex;align-items:center;gap:10px">
                        <span style="font-size:1.2em;font-weight:bold">{h_emoji} {strat_id}: {name}</span>
                        {type_b}
                    </div>
                    <div style="display:flex;align-items:center;gap:12px">
                        <span style="color:#888;font-size:0.85em">{status_str} &nbsp;|&nbsp; {sector} &nbsp;|&nbsp; {horizon}W</span>
                        <span class="dropdown-arrow" style="color:#888;font-size:1.2em">▼</span>
                    </div>
                </div>
                <div style="margin-top:8px;font-style:italic;color:#8ab4d0;font-size:0.9em">
                    📌 {thesis}
                </div>
                <div style="margin-top:6px">{all_badges}</div>
            </div>
            <div class="strat-body">
                <div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:0.88em">
                    <div>
                        <strong style="color:#2ecc71">🟢 Entry-Trigger:</strong><br>
                        <span style="color:#ccc">{entry_trigger or '–'}</span>
                    </div>
                    <div>
                        <strong style="color:#ff4444">🔴 Kill-Switch:</strong><br>
                        <span style="color:#ccc">{kill_trigger or '–'}</span>
                    </div>
                </div>
                {f'<div style="margin-top:12px;font-size:0.88em"><strong style="color:#f1c40f">🎓 Lernfrage:</strong><br><span style="color:#ccc;font-style:italic">{learning_q}</span></div>' if learning_q else ''}
                {genesis_detail}
            </div>
        </div>"""

    return cards


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
    prices = d.get('prices', {})
    strategies = d.get('strategies', {})
    
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
    
    # Build real portfolio rows with live prices
    real_rows = ""
    real_total_entry = 0
    real_total_current = 0
    for ticker, pos in real.items():
        if pos.get('status') == 'CLOSED':
            continue
        name = pos.get('name', ticker)
        entry = pos.get('entry_eur', 0)
        stop = pos.get('stop_eur')
        targets = pos.get('targets_eur', [])
        target_str = f"{targets[0]}€" if targets else "—"
        notes = pos.get('notes', '')
        stop_str = f"{stop}€" if stop else '<span style="color:#ff4444;font-weight:bold">⚠️ KEIN STOP</span>'
        stop_class = '' if stop else 'style="background:rgba(255,68,68,0.1)"'
        
        # Live price lookup
        yahoo_t = pos.get('yahoo', ticker)
        current = prices.get(yahoo_t, prices.get(ticker, None))
        if current and entry:
            pnl_pct = ((current - entry) / entry) * 100
            pnl_color = '#00ff88' if pnl_pct >= 0 else '#ff4444'
            pnl_icon = '📈' if pnl_pct >= 0 else '📉'
            price_str = f"{current:.2f}€"
            pnl_str = f'<span style="color:{pnl_color};font-weight:bold">{pnl_icon} {pnl_pct:+.1f}%</span>'
            real_total_entry += entry
            real_total_current += current
        else:
            price_str = "—"
            pnl_str = "—"
            real_total_entry += entry or 0
            real_total_current += entry or 0
        
        real_rows += f"""<tr {stop_class}>
            <td><strong>{ticker}</strong></td>
            <td>{name}</td>
            <td>{entry}€</td>
            <td data-ticker="{yahoo_t}" data-field="price"><strong>{price_str}</strong></td>
            <td data-ticker="{yahoo_t}" data-field="pnl" data-entry="{entry}">{pnl_str}</td>
            <td>{stop_str}</td>
            <td>{target_str}</td>
            <td style="font-size:0.85em;color:#888">{notes[:40]}</td>
        </tr>"""
    
    real_total_pnl_pct = ((real_total_current - real_total_entry) / real_total_entry * 100) if real_total_entry else 0
    
    # Build open paper positions rows
    open_rows = ""
    paper_total_entry = 0
    paper_total_current = 0
    for p in open_pos:
        s = p.get('strategy', '?')
        badge_color = strat_colors.get(s, '#888')
        sname = strat_names.get(s, s)
        entry = p.get('entry_price', 0)
        shares = p.get('shares', 0)
        stop = p.get('stop_price', 0)
        target = p.get('target_price', 0)
        vol = entry * shares
        ticker = p['ticker']
        
        # Live price
        current = prices.get(ticker, None)
        if current and entry:
            pnl_pct = ((current - entry) / entry) * 100
            pnl_color = '#00ff88' if pnl_pct >= 0 else '#ff4444'
            pnl_icon = '📈' if pnl_pct >= 0 else '📉'
            price_str = f"{current:.2f}€"
            pnl_str = f'<span style="color:{pnl_color};font-weight:bold">{pnl_icon} {pnl_pct:+.1f}%</span>'
            paper_total_entry += entry * shares
            paper_total_current += current * shares
        else:
            price_str = "—"
            pnl_str = "—"
            paper_total_entry += vol
            paper_total_current += vol
        
        open_rows += f"""<tr>
            <td><strong>{ticker}</strong></td>
            <td><span class="badge" style="background:{badge_color}">{s}</span> {sname}</td>
            <td>{entry:.2f}€</td>
            <td data-ticker="{ticker}" data-field="price">{price_str}</td>
            <td data-ticker="{ticker}" data-field="pnl" data-entry="{entry}">{pnl_str}</td>
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

/* Strategy Dropdowns */
.strat-card {{ background:#16213e; border-radius:12px; margin-bottom:12px; overflow:hidden; transition:box-shadow 0.2s; }}
.strat-card:hover {{ background:#1a2744; }}
.strat-header {{ padding:16px 20px; cursor:pointer; user-select:none; }}
.strat-header:hover {{ background:rgba(255,255,255,0.03); }}
.strat-body {{ display:none; padding:0 20px 20px 20px; border-top:1px solid #2a2a4a; }}
.strat-card.open .strat-body {{ display:block; }}
.strat-card.open {{ box-shadow:0 4px 16px rgba(0,0,0,0.3); }}
.strat-card .dropdown-arrow {{ transition:transform 0.2s; display:inline-block; }}
.strat-card.open .dropdown-arrow {{ transform:rotate(180deg); }}

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
<div class="header" style="display:flex;justify-content:space-between;align-items:center">
    <div>
        <h1 style="margin:0">🎩 Albert Trading System</h1>
        <div class="subtitle">
            Stand: {now} &nbsp;|&nbsp; 
            VIX: <strong>{vix}</strong> &nbsp;
            <span class="regime-badge" style="background:{regime_color}">{regime_name}</span>
        </div>
    </div>
    <button id="refreshBtn" onclick="refreshPrices()" style="background:#0f3460;color:#fff;border:1px solid #1a4a8a;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:1em">🔄 Aktualisieren</button>
</div>

<!-- Tab Navigation -->
<div class="tabs">
    <div class="tab active" onclick="switchTab('paper')">🧪 Paper Trades</div>
    <div class="tab" onclick="switchTab('real')">📈 Echtes Portfolio</div>
    <div class="tab" onclick="switchTab('strategies')">🧠 Strategien</div>
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
    
    <!-- Sind die Kurse echt? -->
    <div class="explain" style="border-left-color:#ffaa00">
        <strong>⚠️ Sind die Gewinne echt?</strong><br>
        Die Kurse sind <strong>echte Marktpreise</strong> von Yahoo Finance zum Zeitpunkt des Kaufs/Verkaufs. 
        ABER: In der Realität wären die Gewinne <strong>etwas niedriger</strong> (ca. 2-5%), weil:<br>
        • <strong>Spread</strong> — Unterschied zwischen Kauf- und Verkaufskurs (0,05-0,3%)<br>
        • <strong>Slippage</strong> — Man bekommt nie genau den angezeigten Preis<br>
        • <strong>Timing</strong> — Man kann nicht perfekt am Tageshoch verkaufen<br>
        • <strong>Gebühren</strong> — 3€ pro Trade bei Trade Republic (bereits eingerechnet)
    </div>
    
    <!-- Strategie-Erklärungen -->
    <div class="explain" style="border-left-color:#2ecc71">
        <strong>🧠 Die 5 Strategien erklärt:</strong><br><br>
        <span class="badge" style="background:#3498db">PS1</span> <strong>Iran/Öl-Geopolitik</strong><br>
        Solange der Iran-Konflikt die Straße von Hormuz bedroht, bleibt Öl teuer → Ölproduzenten (OXY, TotalEnergies) profitieren.<br><br>
        
        <span class="badge" style="background:#e67e22">PS2</span> <strong>Tanker-Lag-These</strong><br>
        Wenn Öl steigt, steigen Tankerschiffe 2-4 Wochen SPÄTER. Wir kaufen Tanker-Aktien (FRO, DHT) bevor sie nachziehen.<br><br>
        
        <span class="badge" style="background:#2ecc71">PS3</span> <strong>NATO/EU-Rüstung</strong><br>
        Europa erhöht Verteidigungsbudgets massiv → Rüstungsfirmen (Kratos, Hensoldt, Huntington Ingalls) bekommen mehr Aufträge.<br><br>
        
        <span class="badge" style="background:#f1c40f;color:#000">PS4</span> <strong>Edelmetalle/Miner</strong><br>
        Bei hoher Unsicherheit (VIX hoch) fliehen Anleger in Gold/Silber → Minenunternehmen (Hecla, Pan American Silver) profitieren.<br><br>
        
        <span class="badge" style="background:#8b4513">PS5</span> <strong>Dünger/Agrar-Superzyklus</strong><br>
        Russische Kali-Sanktionen + steigende Lebensmittelnachfrage → westliche Düngerproduzenten (Mosaic) profitieren.
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
                <th>Kurs</th>
                <th>P&L</th>
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

<!-- TAB: Strategien Deep Dive -->
<div id="tab-strategies" class="tab-content">

    <div class="explain">
        <strong>🧠 Strategy Deep Dive — Warum existiert jede Strategie?</strong><br>
        Hier siehst du die vollständige Begründung hinter jeder Strategie: Auslöser, Logik-Kette,
        geprüfte Gegenargumente, Entry- und Kill-Trigger. <strong>Single Source of Truth: data/strategies.json</strong>
    </div>

    <!-- Paper Strategies -->
    <div class="section">
        <h2>📄 Paper-Strategien (PS1–PS5)</h2>
        {build_strategy_deep_dive({k: v for k, v in strategies.items() if k.startswith('PS')})}
    </div>

    <!-- Real Strategies -->
    <div class="section">
        <h2>💰 Real-Strategien (S1–S7)</h2>
        {build_strategy_deep_dive({k: v for k, v in strategies.items() if k.startswith('S')})}
    </div>

</div>

<!-- TAB: Echtes Portfolio -->
<div id="tab-real" class="tab-content">
    
    <div class="explain">
        <strong>💡 Victors echtes Portfolio.</strong> Diese Positionen sind mit echtem Geld in Trade Republic gekauft. 
        Kurse sind live von Yahoo Finance. Albert überwacht und warnt bei Problemen.
    </div>
    
    <!-- Real Portfolio Cards -->
    <div class="cards">
        <div class="card">
            <div class="label">Positionen</div>
            <div class="value">{sum(1 for p in real.values() if p.get('status') != 'CLOSED')}</div>
            <div class="sub">aktiv</div>
        </div>
        <div class="card">
            <div class="label">Gesamt-Trend</div>
            <div class="value {'green' if real_total_pnl_pct >= 0 else 'red'}">{real_total_pnl_pct:+.1f}%</div>
            <div class="sub">seit Kauf (Durchschnitt)</div>
        </div>
        <div class="card">
            <div class="label">Markt-Regime</div>
            <div class="value" style="color:{regime_color}">{regime_name}</div>
            <div class="sub">VIX: {vix}</div>
        </div>
        <div class="card">
            <div class="label">Ohne Stop ⚠️</div>
            <div class="value red">{sum(1 for p in real.values() if not p.get('stop_eur') and p.get('status') != 'CLOSED')}</div>
            <div class="sub">ungeschützt</div>
        </div>
    </div>
    
    <div class="section">
        <h2>📈 Aktive Positionen (Live-Kurse)</h2>
        <div class="explain">
            <strong>Entry</strong> = Kaufpreis &nbsp;|&nbsp; 
            <strong>Aktuell</strong> = Jetziger Kurs (Yahoo Finance) &nbsp;|&nbsp;
            <strong>P&L</strong> = Gewinn/Verlust seit Kauf &nbsp;|&nbsp;
            <strong>Stop</strong> = Automatischer Verkauf bei Verlust &nbsp;|&nbsp;
            <span style="color:#ff4444">⚠️ KEIN STOP</span> = Gefährlich!
        </div>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th>Entry</th>
                <th>Aktuell</th>
                <th>Gewinn/Verlust</th>
                <th>Stop</th>
                <th>Ziel</th>
                <th>Notiz</th>
            </tr>
            {real_rows}
        </table>
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
            (tab === 'real' && t.textContent.includes('Echt')) ||
            (tab === 'strategies' && t.textContent.includes('Strateg'))) {{
            t.classList.add('active');
        }}
    }});
}}

async function refreshPrices() {{
    const btn = document.getElementById('refreshBtn');
    btn.textContent = '⏳ Laden…';
    btn.disabled = true;
    try {{
        const r = await fetch('/api/prices');
        const data = await r.json();
        if (!data.prices) throw new Error('No prices');
        
        // Update all price cells with data-ticker attribute
        document.querySelectorAll('[data-ticker]').forEach(el => {{
            const ticker = el.dataset.ticker;
            const field = el.dataset.field;
            const p = data.prices[ticker];
            if (!p) return;
            
            if (field === 'price') {{
                el.textContent = p.eur.toFixed(2) + '€';
            }} else if (field === 'pnl') {{
                const entry = parseFloat(el.dataset.entry);
                if (entry) {{
                    const pnl = ((p.eur - entry) / entry * 100);
                    el.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(1) + '%';
                    el.style.color = pnl >= 0 ? '#00ff88' : '#ff4444';
                }}
            }}
        }});
        
        // Update VIX
        if (data.vix) {{
            const vixEl = document.querySelector('.subtitle strong');
            if (vixEl) vixEl.textContent = data.vix.toFixed(2);
        }}
        
        // Update timestamp
        const sub = document.querySelector('.subtitle');
        if (sub) {{
            const now = new Date().toLocaleString('de-DE');
            sub.innerHTML = sub.innerHTML.replace(/Stand:.*?&nbsp;/, 'Stand: ' + now + ' &nbsp;');
        }}
        
        btn.textContent = '✅ Aktuell!';
        setTimeout(() => {{ btn.textContent = '🔄 Aktualisieren'; }}, 2000);
    }} catch(e) {{
        btn.textContent = '❌ Fehler';
        console.error(e);
        setTimeout(() => {{ btn.textContent = '🔄 Aktualisieren'; }}, 3000);
    }}
    btn.disabled = false;
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
