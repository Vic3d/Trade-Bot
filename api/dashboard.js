// TradeMind v2 Dashboard — Vercel Serverless Function
// Data is inlined at build time from trademind/dashboard/data.json
// Regenerate: python3 -m trademind dashboard generate && push

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=120');
  return res.status(200).send(`<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎩 TradeMind</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root { --bg: #0a0f1a; --card: #131b2e; --card-hover: #1a2540; --text: #e2e8f0; --muted: #64748b; --accent: #06b6d4; --accent2: #8b5cf6; --green: #10b981; --red: #ef4444; --amber: #f59e0b; --border: #1e293b; --gradient1: linear-gradient(135deg, #06b6d4 0%, #8b5cf6 100%); }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

/* HEADER */
.header { background: var(--card); padding: 1.25rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); }
.header-left { display: flex; align-items: center; gap: 1rem; }
.logo { font-size: 1.75rem; font-weight: 800; background: var(--gradient1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.logo-sub { color: var(--muted); font-size: 0.75rem; letter-spacing: 2px; text-transform: uppercase; }
.header-right { display: flex; gap: 1.5rem; align-items: center; }
.header-stat { text-align: center; }
.header-stat .val { font-size: 1.1rem; font-weight: 700; }
.header-stat .lbl { font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
.cb-indicator { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
.cb-ok { background: rgba(16,185,129,0.15); color: var(--green); }
.cb-blocked { background: rgba(239,68,68,0.15); color: var(--red); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }

/* NAV */
.nav { display: flex; gap: 0; background: var(--card); border-bottom: 1px solid var(--border); overflow-x: auto; }
.nav-item { padding: 0.85rem 1.5rem; cursor: pointer; color: var(--muted); font-size: 0.85rem; font-weight: 500; border-bottom: 2px solid transparent; transition: all 0.2s; white-space: nowrap; display: flex; align-items: center; gap: 6px; }
.nav-item:hover { color: var(--text); background: rgba(255,255,255,0.02); }
.nav-item.active { color: var(--accent); border-bottom-color: var(--accent); }
.nav-badge { background: var(--accent); color: #000; font-size: 0.65rem; padding: 1px 6px; border-radius: 10px; font-weight: 700; }

/* LAYOUT */
.content { padding: 1.5rem; max-width: 1400px; margin: 0 auto; }
.grid { display: grid; gap: 1rem; }
.g2 { grid-template-columns: 1fr 1fr; } .g3 { grid-template-columns: 1fr 1fr 1fr; } .g4 { grid-template-columns: 1fr 1fr 1fr 1fr; }

/* CARDS */
.card { background: var(--card); border-radius: 12px; padding: 1.25rem; border: 1px solid var(--border); transition: border-color 0.2s; }
.card:hover { border-color: rgba(6,182,212,0.3); }
.card-title { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 6px; }
.card-title .icon { font-size: 1rem; }

/* STATS */
.kpi { text-align: center; padding: 1rem 0.5rem; }
.kpi .number { font-size: 2.25rem; font-weight: 800; line-height: 1; }
.kpi .sublabel { color: var(--muted); font-size: 0.7rem; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }
.kpi .change { font-size: 0.8rem; margin-top: 2px; font-weight: 600; }
.green { color: var(--green); } .red { color: var(--red); } .amber { color: var(--amber); } .purple { color: var(--accent2); }

/* TABLE */
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th { color: var(--muted); text-align: left; padding: 0.6rem 0.75rem; font-weight: 500; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); }
td { padding: 0.6rem 0.75rem; border-bottom: 1px solid rgba(30,41,59,0.5); }
tr:hover td { background: rgba(6,182,212,0.03); }
.ticker-cell { font-weight: 700; color: var(--accent); }

/* BADGES */
.badge { display: inline-block; padding: 2px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 600; }
.b-green { background: rgba(16,185,129,0.15); color: var(--green); }
.b-red { background: rgba(239,68,68,0.15); color: var(--red); }
.b-amber { background: rgba(245,158,11,0.15); color: var(--amber); }
.b-purple { background: rgba(139,92,246,0.15); color: var(--accent2); }
.b-blue { background: rgba(6,182,212,0.15); color: var(--accent); }

/* CHART */
.chart-box { position: relative; height: 280px; }

/* PROGRESS BAR */
.prog-wrap { background: rgba(255,255,255,0.05); border-radius: 8px; height: 8px; overflow: hidden; margin: 4px 0; }
.prog-bar { height: 100%; border-radius: 8px; transition: width 0.8s ease; }

/* ALERT FEED */
.feed-item { padding: 0.6rem 0.75rem; border-left: 3px solid var(--accent); margin: 0.5rem 0; background: rgba(6,182,212,0.03); border-radius: 0 8px 8px 0; font-size: 0.82rem; }
.feed-item .ts { color: var(--muted); font-size: 0.7rem; }
.feed-item.loss { border-left-color: var(--red); background: rgba(239,68,68,0.03); }
.feed-item.win { border-left-color: var(--green); background: rgba(16,185,129,0.03); }

/* GRAVEYARD */
.grave { padding: 1rem; border: 1px solid var(--border); border-radius: 8px; margin: 0.5rem 0; opacity: 0.7; }
.grave:hover { opacity: 1; }
.grave .name { font-weight: 700; color: var(--red); }

/* EXPOSURE BAR */
.exp-row { display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: 0.82rem; }
.exp-label { width: 100px; color: var(--muted); }
.exp-bar-wrap { flex: 1; background: rgba(255,255,255,0.05); border-radius: 4px; height: 24px; position: relative; overflow: hidden; }
.exp-bar { height: 100%; border-radius: 4px; display: flex; align-items: center; padding: 0 8px; font-size: 0.7rem; font-weight: 600; transition: width 0.8s; }
.exp-limit { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--red); }
.exp-val { width: 60px; text-align: right; font-weight: 600; }

/* TABS */
.section { display: none; } .section.active { display: block; }

/* RESPONSIVE */
@media (max-width: 900px) { .g2,.g3,.g4 { grid-template-columns: 1fr; } .header { flex-direction: column; gap: 1rem; } .header-right { flex-wrap: wrap; justify-content: center; } }
@media (max-width: 600px) { .content { padding: 0.75rem; } .card { padding: 1rem; } .kpi .number { font-size: 1.5rem; } }
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="header-left">
    <div>
      <div class="logo">🎩 TradeMind</div>
      <div class="logo-sub">Autonomous Trading Intelligence</div>
    </div>
  </div>
  <div class="header-right">
    <div class="header-stat"><div class="val" id="h-pnl">—</div><div class="lbl">Gesamt P&L</div></div>
    <div class="header-stat"><div class="val" id="h-open">—</div><div class="lbl">Offene Pos.</div></div>
    <div class="header-stat"><div class="val" id="h-vix">—</div><div class="lbl">VIX</div></div>
    <div id="h-cb" class="cb-indicator cb-ok">● Trading OK</div>
  </div>
</div>

<!-- NAV -->
<div class="nav">
  <div class="nav-item active" onclick="tab('overview')">🏠 Übersicht</div>
  <div class="nav-item" onclick="tab('positions')">📊 Positionen <span class="nav-badge" id="nav-pos-count">0</span></div>
  <div class="nav-item" onclick="tab('risk')">⚡ Risk</div>
  <div class="nav-item" onclick="tab('performance')">📈 Performance</div>
  <div class="nav-item" onclick="tab('strategies')">🧬 Strategien</div>
  <div class="nav-item" onclick="tab('learning')">🧠 Learning</div>
  <div class="nav-item" onclick="tab('backtest')">🔬 Backtest</div>
</div>

<div class="content">

<!-- OVERVIEW -->
<div class="section active" id="sec-overview">
  <div class="grid g4" id="overview-kpis"></div>
  <div class="grid g2" style="margin-top:1rem">
    <div class="card"><div class="card-title"><span class="icon">📈</span> Equity Curve</div><div class="chart-box"><canvas id="ov-equity"></canvas></div></div>
    <div class="card"><div class="card-title"><span class="icon">📋</span> Letzte Aktivität</div><div id="ov-feed" style="max-height:280px;overflow-y:auto"></div></div>
  </div>
  <div class="grid g3" style="margin-top:1rem">
    <div class="card"><div class="card-title"><span class="icon">🥇</span> Beste Strategie</div><div id="ov-best"></div></div>
    <div class="card"><div class="card-title"><span class="icon">💀</span> Schlechteste Strategie</div><div id="ov-worst"></div></div>
    <div class="card"><div class="card-title"><span class="icon">⚠️</span> Top-Risiko</div><div id="ov-toprisk"></div></div>
  </div>
</div>

<!-- POSITIONS -->
<div class="section" id="sec-positions">
  <div class="card"><div class="card-title"><span class="icon">📊</span> Offene Positionen</div>
    <table><thead><tr><th>Ticker</th><th>Strategie</th><th>Theme</th><th>Entry</th><th>Aktuell</th><th>P&L</th><th>Stop</th><th>Risk</th><th>Tage</th></tr></thead><tbody id="pos-tbody"></tbody></table>
  </div>
</div>

<!-- RISK -->
<div class="section" id="sec-risk">
  <div class="grid g2">
    <div class="card">
      <div class="card-title"><span class="icon">🔌</span> Circuit Breaker</div>
      <div id="risk-cb"></div>
    </div>
    <div class="card">
      <div class="card-title"><span class="icon">💥</span> Stress Tests</div>
      <div id="risk-stress"></div>
    </div>
  </div>
  <div class="grid g2" style="margin-top:1rem">
    <div class="card"><div class="card-title"><span class="icon">🏭</span> Sektor-Exposure</div><div id="risk-sector"></div></div>
    <div class="card"><div class="card-title"><span class="icon">🌍</span> Region-Exposure</div><div id="risk-region"></div></div>
  </div>
  <div class="card" style="margin-top:1rem">
    <div class="card-title"><span class="icon">🔗</span> Korrelationsmatrix</div>
    <div class="chart-box"><canvas id="risk-corr-chart"></canvas></div>
  </div>
</div>

<!-- PERFORMANCE -->
<div class="section" id="sec-performance">
  <div class="grid g4" id="perf-kpis"></div>
  <div class="card" style="margin-top:1rem"><div class="card-title"><span class="icon">📈</span> Equity Curve</div><div class="chart-box"><canvas id="perf-equity"></canvas></div></div>
  <div class="grid g2" style="margin-top:1rem">
    <div class="card"><div class="card-title"><span class="icon">🥇</span> Top 5 Trades</div><div id="perf-top"></div></div>
    <div class="card"><div class="card-title"><span class="icon">💀</span> Worst 5 Trades</div><div id="perf-worst"></div></div>
  </div>
</div>

<!-- STRATEGIES -->
<div class="section" id="sec-strategies">
  <div class="card"><div class="card-title"><span class="icon">🧬</span> Aktive Strategien — Health Check</div>
    <table><thead><tr><th>Strategie</th><th>Trades</th><th>Win Rate</th><th>P&L</th><th>Sharpe</th><th>Profit Factor</th><th>p-value</th><th>Status</th></tr></thead><tbody id="strat-tbody"></tbody></table>
  </div>
  <div class="card" style="margin-top:1rem">
    <div class="card-title"><span class="icon">🪦</span> Strategie-Friedhof</div>
    <div id="strat-graveyard"></div>
  </div>
</div>

<!-- LEARNING -->
<div class="section" id="sec-learning">
  <div class="grid g3" id="learn-kpis"></div>
  <div class="grid g2" style="margin-top:1rem">
    <div class="card"><div class="card-title"><span class="icon">🎯</span> Setup-Performance</div><div id="learn-setup"></div></div>
    <div class="card"><div class="card-title"><span class="icon">🌍</span> Theme-Performance</div><div id="learn-theme"></div></div>
  </div>
  <div class="card" style="margin-top:1rem"><div class="card-title"><span class="icon">📝</span> Lektionen (neueste zuerst)</div><div id="learn-lessons"></div></div>
  <div class="card" style="margin-top:1rem"><div class="card-title"><span class="icon">🧠</span> Auto-Insights</div><div id="learn-insights"></div></div>
</div>

<!-- BACKTEST -->
<div class="section" id="sec-backtest">
  <div class="grid g2">
    <div class="card"><div class="card-title"><span class="icon">🚀</span> Momentum (Walk-Forward)</div><div id="bt-mom"></div></div>
    <div class="card"><div class="card-title"><span class="icon">🔄</span> Mean-Reversion (Walk-Forward)</div><div id="bt-mr"></div></div>
  </div>
  <div class="card" style="margin-top:1rem"><div class="card-title"><span class="icon">📊</span> Benchmark-Vergleich</div>
    <div class="chart-box"><canvas id="bt-chart"></canvas></div>
  </div>
</div>

</div>

<script>
let D={};
const D={
  "meta": {
    "generated_at": "2026-03-26T23:03:50.309237",
    "version": "1.0",
    "db_path": "/data/.openclaw/workspace/data/trading.db"
  },
  "portfolio": {
    "positions": [
      {
        "ticker": "NVDA",
        "strategy": "S3",
        "entry": 167.88,
        "current": 167.88,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 0.0,
        "target": 0.0,
        "days_held": 29,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "MSFT",
        "strategy": "S3",
        "entry": 351.85,
        "current": 351.85,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 338.0,
        "target": 0.0,
        "days_held": 29,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "PLTR",
        "strategy": "S3",
        "entry": 132.11,
        "current": 132.11,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 127.0,
        "target": 0.0,
        "days_held": 29,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "EQNR",
        "strategy": "S1",
        "entry": 27.04,
        "current": 27.04,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 30.0,
        "target": 0.0,
        "days_held": 29,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "BAYN.DE",
        "strategy": "S7",
        "entry": 39.95,
        "current": 39.95,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 38.0,
        "target": 0.0,
        "days_held": 22,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "RIO.L",
        "strategy": "S5",
        "entry": 76.92,
        "current": 76.92,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 73.0,
        "target": 0.0,
        "days_held": 22,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "TESTOK",
        "strategy": "PS1",
        "entry": 100.0,
        "current": 100.0,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 90.0,
        "target": 130.0,
        "days_held": 3,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "TTE.PA",
        "strategy": "PS1",
        "entry": 76.0,
        "current": 76.0,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 70.0,
        "target": 88.0,
        "days_held": 3,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "PSX",
        "strategy": "PT",
        "entry": 156.05,
        "current": 156.05,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 145.13,
        "target": 179.46,
        "days_held": 1,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "DINO",
        "strategy": "PM",
        "entry": 52.88,
        "current": 52.88,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 53.18,
        "target": 56.58,
        "days_held": 1,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "AG",
        "strategy": "PM",
        "entry": 17.33,
        "current": 17.33,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 17.33,
        "target": 25.0,
        "days_held": 1,
        "geo_theme": "",
        "setup_type": ""
      },
      {
        "ticker": "OXY",
        "strategy": "SA",
        "entry": 55.79,
        "current": 55.79,
        "pnl_eur": 0.0,
        "pnl_pct": 0.0,
        "stop": 52.21,
        "target": 70.11,
        "days_held": 0,
        "geo_theme": "iran_hormuz",
        "setup_type": "CREEPING"
      },
      {
        "ticker": "FRO",
        "strategy": "SA",
        "entry": 29.37,
        "current": 29.1,
        "pnl_eur": -96.93,
        "pnl_pct": -0.92,
        "stop": 26.59,
        "target": 40.49,
        "days_held": 0,
        "geo_theme": "iran_hormuz",
        "setup_type": "CREEPING"
      }
    ],
    "total_invested": 38056.99,
    "open_unrealized": -96.93,
    "closed_pnl": -2008.08,
    "total_pnl": -2105.01,
    "cash": 25000.0,
    "position_count": 13,
    "last_updated": "2026-03-26T23:03:50.019993"
  },
  "risk": {
    "circuit_breaker": {
      "trading_allowed": false,
      "triggered": [],
      "warnings": []
    },
    "exposure": {
      "total": 33056.99,
      "sector": {
        "Technology": {
          "pct": 2.0,
          "value": 651.84
        },
        "Energy": {
          "pct": 91.6,
          "value": 30288.28
        },
        "Healthcare": {
          "pct": 0.1,
          "value": 39.95
        },
        "Mining": {
          "pct": 6.3,
          "value": 2076.92
        }
      },
      "region": {
        "US": {
          "pct": 99.1,
          "value": 32761.08
        },
        "Europe": {
          "pct": 0.9,
          "value": 295.91
        }
      },
      "violations": [
        "Sektor Energy > 40% Limit (91.6%)",
        "Region US > 60% Limit (99.1%)",
        "Ticker OXY > 20% Limit (47.1%)",
        "Ticker FRO > 20% Limit (31.9%)"
      ]
    },
    "stress_tests": [
      {
        "name": "Öl -20% über Nacht",
        "total_loss": -6174.94,
        "severity": "critical",
        "description": "Saudi-Arabien/Russland Preiskrieg. Öl-Sektor kollabiert."
      },
      {
        "name": "VIX Spike auf 50",
        "total_loss": -3943.26,
        "severity": "critical",
        "description": "Panik-Verkäufe wie März 2020. Alle riskanten Assets crashen."
      },
      {
        "name": "Black Swan -10% alles",
        "total_loss": -3305.7,
        "severity": "critical",
        "description": "Unspezifischer Schock — alles fällt gleichzeitig 10%."
      }
    ],
    "correlation": {
      "tickers": [
        "NVDA",
        "MSFT",
        "PLTR",
        "BAYN.DE",
        "RIO.L",
        "TTE.PA",
        "AG",
        "PSX",
        "DINO",
        "OXY",
        "FRO"
      ],
      "matrix": [
        [
          1.0,
          0.365,
          0.282,
          0.175,
          0.374,
          -0.028,
          0.179,
          -0.041,
          -0.083,
          -0.255,
          0.19
        ],
        [
          0.365,
          1.0,
          0.619,
          -0.077,
          0.022,
          -0.096,
          -0.012,
          -0.109,
          0.068,
          -0.259,
          -0.002
        ],
        [
          0.282,
          0.619,
          1.0,
          -0.195,
          0.156,
          -0.085,
          0.09,
          0.158,
          0.096,
          -0.106,
          0.139
        ],
        [
          0.175,
          -0.077,
          -0.195,
          1.0,
          0.056,
          -0.04,
          -0.102,
          -0.23,
          0.068,
          -0.222,
          -0.0
        ],
        [
          0.374,
          0.022,
          0.156,
          0.056,
          1.0,
          -0.191,
          0.428,
          -0.036,
          -0.119,
          -0.256,
          0.274
        ],
        [
          -0.028,
          -0.096,
          -0.085,
          -0.04,
          -0.191,
          1.0,
          -0.26,
          0.219,
          0.107,
          0.328,
          0.165
        ],
        [
          0.179,
          -0.012,
          0.09,
          -0.102,
          0.428,
          -0.26,
          1.0,
          -0.076,
          -0.219,
          0.179,
          0.507
        ],
        [
          -0.041,
          -0.109,
          0.158,
          -0.23,
          -0.036,
          0.219,
          -0.076,
          1.0,
          0.647,
          0.23,
          0.044
        ],
        [
          -0.083,
          0.068,
          0.096,
          0.068,
          -0.119,
          0.107,
          -0.219,
          0.647,
          1.0,
          0.006,
          -0.19
        ],
        [
          -0.255,
          -0.259,
          -0.106,
          -0.222,
          -0.256,
          0.328,
          0.179,
          0.23,
          0.006,
          1.0,
          -0.048
        ],
        [
          0.19,
          -0.002,
          0.139,
          -0.0,
          0.274,
          0.165,
          0.507,
          0.044,
          -0.19,
          -0.048,
          1.0
        ]
      ]
    }
  },
  "performance": {
    "equity_curve": [
      {
        "date": "2026-03-11",
        "cumulative_pnl": -72.0,
        "pnl": -72.0
      },
      {
        "date": "2026-03-16",
        "cumulative_pnl": -37.0,
        "pnl": 35.0
      },
      {
        "date": "2026-03-18",
        "cumulative_pnl": -41.87,
        "pnl": -4.87
      },
      {
        "date": "2026-03-18",
        "cumulative_pnl": -47.81,
        "pnl": -5.94
      },
      {
        "date": "2026-03-18",
        "cumulative_pnl": -53.73,
        "pnl": -5.92
      },
      {
        "date": "2026-03-19",
        "cumulative_pnl": -56.73,
        "pnl": -3.0
      },
      {
        "date": "2026-03-20",
        "cumulative_pnl": -386.01,
        "pnl": -329.28
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -203.94,
        "pnl": 182.07
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -353.12,
        "pnl": -149.18
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -310.14,
        "pnl": 42.98
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -334.9,
        "pnl": -24.76
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -288.81,
        "pnl": 46.09
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -240.45,
        "pnl": 48.36
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -196.23,
        "pnl": 44.22
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -242.71,
        "pnl": -46.48
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -198.85,
        "pnl": 43.86
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -239.43,
        "pnl": -40.58
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -260.52,
        "pnl": -21.09
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -283.39,
        "pnl": -22.87
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -322.44,
        "pnl": -39.05
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -361.15,
        "pnl": -38.71
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -398.84,
        "pnl": -37.69
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -443.62,
        "pnl": -44.78
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -658.51,
        "pnl": -214.89
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -755.83,
        "pnl": -97.32
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -668.14,
        "pnl": 87.69
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -586.18,
        "pnl": 81.96
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -613.56,
        "pnl": -27.38
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -526.43,
        "pnl": 87.13
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -481.33,
        "pnl": 45.1
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -678.15,
        "pnl": -196.82
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -607.63,
        "pnl": 70.52
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -533.53,
        "pnl": 74.1
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -483.71,
        "pnl": 49.82
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -574.05,
        "pnl": -90.34
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -536.55,
        "pnl": 37.5
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -554.79,
        "pnl": -18.24
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -510.24,
        "pnl": 44.55
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -532.44,
        "pnl": -22.2
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -566.49,
        "pnl": -34.05
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -605.84,
        "pnl": -39.35
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -550.42,
        "pnl": 55.42
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -575.74,
        "pnl": -25.32
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -584.85,
        "pnl": -9.11
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -608.7,
        "pnl": -23.85
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -704.45,
        "pnl": -95.75
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -698.58,
        "pnl": 5.87
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -677.34,
        "pnl": 21.24
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -657.18,
        "pnl": 20.16
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -652.4,
        "pnl": 4.78
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -639.4,
        "pnl": 13.0
      },
      {
        "date": "2026-03-23",
        "cumulative_pnl": -641.25,
        "pnl": -1.85
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -296.17,
        "pnl": 345.08
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -335.07,
        "pnl": -38.9
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -405.61,
        "pnl": -70.54
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -550.91,
        "pnl": -145.3
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -506.88,
        "pnl": 44.03
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -458.86,
        "pnl": 48.02
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -413.0,
        "pnl": 45.86
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -368.97,
        "pnl": 44.03
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -435.93,
        "pnl": -66.96
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -382.07,
        "pnl": 53.86
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -434.65,
        "pnl": -52.58
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -474.94,
        "pnl": -40.29
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -432.48,
        "pnl": 42.46
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -420.17,
        "pnl": 12.31
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -609.77,
        "pnl": -189.6
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -621.94,
        "pnl": -12.17
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -624.1,
        "pnl": -2.16
      },
      {
        "date": "2026-03-24",
        "cumulative_pnl": -620.43,
        "pnl": 3.67
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -573.41,
        "pnl": 47.02
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -510.99,
        "pnl": 62.42
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -451.88,
        "pnl": 59.11
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -498.62,
        "pnl": -46.74
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -457.27,
        "pnl": 41.35
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -415.31,
        "pnl": 41.96
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -797.68,
        "pnl": -382.37
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -913.07,
        "pnl": -115.39
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -938.59,
        "pnl": -25.52
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -970.93,
        "pnl": -32.34
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1010.03,
        "pnl": -39.1
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -956.67,
        "pnl": 53.36
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1012.13,
        "pnl": -55.46
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1064.27,
        "pnl": -52.14
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1106.5,
        "pnl": -42.23
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1210.31,
        "pnl": -103.81
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1212.66,
        "pnl": -2.35
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1214.24,
        "pnl": -1.58
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1217.52,
        "pnl": -3.28
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1279.99,
        "pnl": -62.47
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1283.39,
        "pnl": -3.4
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1282.9,
        "pnl": 0.49
      },
      {
        "date": "2026-03-25",
        "cumulative_pnl": -1283.9,
        "pnl": -1.0
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -855.99,
        "pnl": 427.91
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -961.26,
        "pnl": -105.27
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -854.21,
        "pnl": 107.05
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -878.35,
        "pnl": -24.14
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1296.95,
        "pnl": -418.6
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1365.31,
        "pnl": -68.36
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1315.91,
        "pnl": 49.4
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1271.17,
        "pnl": 44.74
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1227.99,
        "pnl": 43.18
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1185.59,
        "pnl": 42.4
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1207.68,
        "pnl": -22.09
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1158.7,
        "pnl": 48.98
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1191.04,
        "pnl": -32.34
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1197.94,
        "pnl": -6.9
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1303.99,
        "pnl": -106.05
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1305.29,
        "pnl": -1.3
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1325.22,
        "pnl": -19.93
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1325.65,
        "pnl": -0.43
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1348.05,
        "pnl": -22.4
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1349.22,
        "pnl": -1.17
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1202.02,
        "pnl": 147.2
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1202.7,
        "pnl": -0.68
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1303.95,
        "pnl": -101.25
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1303.73,
        "pnl": 0.22
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1260.09,
        "pnl": 43.64
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1254.59,
        "pnl": 5.5
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1265.53,
        "pnl": -10.94
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1342.13,
        "pnl": -76.6
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1289.37,
        "pnl": 52.76
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1358.12,
        "pnl": -68.75
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1356.18,
        "pnl": 1.94
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1357.37,
        "pnl": -1.19
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1365.77,
        "pnl": -8.4
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1373.91,
        "pnl": -8.14
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1475.21,
        "pnl": -101.3
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1473.05,
        "pnl": 2.16
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1475.75,
        "pnl": -2.7
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1541.35,
        "pnl": -65.6
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1543.71,
        "pnl": -2.36
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1539.71,
        "pnl": 4.0
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1640.01,
        "pnl": -100.3
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1642.9,
        "pnl": -2.89
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1645.02,
        "pnl": -2.12
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1728.62,
        "pnl": -83.6
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1725.39,
        "pnl": 3.23
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1724.95,
        "pnl": 0.44
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1814.95,
        "pnl": -90.0
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1775.61,
        "pnl": 39.34
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1774.64,
        "pnl": 0.97
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1778.93,
        "pnl": -4.29
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1860.64,
        "pnl": -81.71
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1958.44,
        "pnl": -97.8
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1971.42,
        "pnl": -12.98
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1952.9,
        "pnl": 18.52
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1963.25,
        "pnl": -10.35
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1963.29,
        "pnl": -0.04
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1953.49,
        "pnl": 9.8
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1983.89,
        "pnl": -30.4
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1897.16,
        "pnl": 86.73
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1877.24,
        "pnl": 19.92
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1922.59,
        "pnl": -45.35
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1922.59,
        "pnl": 0.0
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1803.93,
        "pnl": 118.66
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1827.09,
        "pnl": -23.16
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1893.37,
        "pnl": -66.28
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1953.17,
        "pnl": -59.8
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1984.87,
        "pnl": -31.7
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -2027.28,
        "pnl": -42.41
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1946.47,
        "pnl": 80.81
      },
      {
        "date": "2026-03-26",
        "cumulative_pnl": -1996.08,
        "pnl": -49.61
      }
    ],
    "strategy_comparison": [
      {
        "strategy": "DT3-CTR",
        "trades": 4,
        "win_rate": 0.5,
        "total_pnl": 5.36,
        "sharpe": 8.015,
        "profit_factor": 3.866,
        "verdict": "Neutral"
      },
      {
        "strategy": "DT4-CTR",
        "trades": 2,
        "win_rate": 0.5,
        "total_pnl": 0.64,
        "sharpe": 2.217,
        "profit_factor": 1.492,
        "verdict": "Neutral"
      },
      {
        "strategy": "DT6-CTR",
        "trades": 1,
        "win_rate": 1.0,
        "total_pnl": 0.44,
        "sharpe": 0.0,
        "profit_factor": Infinity,
        "verdict": "Neutral"
      },
      {
        "strategy": "DT9",
        "trades": 2,
        "win_rate": 0.5,
        "total_pnl": -0.9,
        "sharpe": -0.062,
        "profit_factor": 0.989,
        "verdict": "Weak"
      },
      {
        "strategy": "DT9-CTR",
        "trades": 2,
        "win_rate": 0.5,
        "total_pnl": -1.39,
        "sharpe": -4.685,
        "profit_factor": 0.411,
        "verdict": "Weak"
      },
      {
        "strategy": "PS4",
        "trades": 2,
        "win_rate": 0.0,
        "total_pnl": -4.85,
        "sharpe": -47.34,
        "profit_factor": 0.0,
        "verdict": "Weak"
      },
      {
        "strategy": "DT1-CTR",
        "trades": 7,
        "win_rate": 0.286,
        "total_pnl": -9.96,
        "sharpe": -5.767,
        "profit_factor": 0.365,
        "verdict": "Weak"
      },
      {
        "strategy": "DT2-CTR",
        "trades": 3,
        "win_rate": 0.333,
        "total_pnl": -14.38,
        "sharpe": -12.633,
        "profit_factor": 0.131,
        "verdict": "Weak"
      },
      {
        "strategy": "PS3",
        "trades": 3,
        "win_rate": 0.0,
        "total_pnl": -16.73,
        "sharpe": -144.634,
        "profit_factor": 0.0,
        "verdict": "Weak"
      },
      {
        "strategy": "DT6",
        "trades": 2,
        "win_rate": 0.5,
        "total_pnl": -32.61,
        "sharpe": -7.011,
        "profit_factor": 0.231,
        "verdict": "Weak"
      },
      {
        "strategy": "S2",
        "trades": 2,
        "win_rate": 0.5,
        "total_pnl": -37.0,
        "sharpe": -3.882,
        "profit_factor": 0.486,
        "verdict": "Weak"
      },
      {
        "strategy": "PS1",
        "trades": 5,
        "win_rate": 0.6,
        "total_pnl": -66.87,
        "sharpe": -4.147,
        "profit_factor": 0.362,
        "verdict": "Weak"
      },
      {
        "strategy": "DT2",
        "trades": 4,
        "win_rate": 0.0,
        "total_pnl": -103.08,
        "sharpe": -14.463,
        "profit_factor": 0.0,
        "verdict": "Weak"
      },
      {
        "strategy": "DT1",
        "trades": 11,
        "win_rate": 0.364,
        "total_pnl": -243.59,
        "sharpe": -4.46,
        "profit_factor": 0.516,
        "verdict": "Weak"
      },
      {
        "strategy": "PS5",
        "trades": 2,
        "win_rate": 0.0,
        "total_pnl": -331.63,
        "sharpe": -11.386,
        "profit_factor": 0.0,
        "verdict": "Weak"
      },
      {
        "strategy": "DT3",
        "trades": 9,
        "win_rate": 0.111,
        "total_pnl": -414.64,
        "sharpe": -12.486,
        "profit_factor": 0.173,
        "verdict": "Weak"
      },
      {
        "strategy": "DT4",
        "trades": 102,
        "win_rate": 0.431,
        "total_pnl": -724.89,
        "sharpe": -1.102,
        "profit_factor": 0.803,
        "verdict": "Weak"
      }
    ],
    "best_trades": [
      {
        "ticker": "9988.HK",
        "strategy": "DT4",
        "pnl_eur": 427.91,
        "pnl_pct": 857.0,
        "exit_date": "2026-03-26"
      },
      {
        "ticker": "9988.HK",
        "strategy": "DT4",
        "pnl_eur": 345.08,
        "pnl_pct": 690.0,
        "exit_date": "2026-03-24"
      },
      {
        "ticker": "0700.HK",
        "strategy": "DT4",
        "pnl_eur": 182.07,
        "pnl_pct": 378.0,
        "exit_date": "2026-03-23"
      }
    ],
    "worst_trades": [
      {
        "ticker": "MOS",
        "strategy": "PS5",
        "pnl_eur": -329.28,
        "pnl_pct": -1324.0,
        "exit_date": "2026-03-20"
      },
      {
        "ticker": "KWEB",
        "strategy": "DT4",
        "pnl_eur": -382.37,
        "pnl_pct": -712.0,
        "exit_date": "2026-03-25"
      },
      {
        "ticker": "9988.HK",
        "strategy": "DT4",
        "pnl_eur": -418.6,
        "pnl_pct": -839.0,
        "exit_date": "2026-03-26"
      }
    ],
    "monthly_pnl": [
      {
        "month": "2026-03",
        "pnl": -1996.08
      }
    ],
    "total_closed_trades": 163,
    "total_closed_pnl": -1996.08
  },
  "learning": {
    "thesis_accuracy": 0.377,
    "setup_performance": [
      {
        "setup": "unknown",
        "trades": 167,
        "win_rate": 0.377,
        "avg_pnl": -12.02
      }
    ],
    "theme_performance": [
      {
        "theme": "untagged",
        "trades": 167,
        "win_rate": 0.377,
        "total_pnl": -2008.08
      }
    ],
    "vix_performance": [
      {
        "zone": "elevated (20-30)",
        "trades": 167,
        "win_rate": 0.377,
        "avg_pnl": -12.02
      }
    ],
    "lessons": [
      {
        "ticker": "OXY",
        "strategy": "PS1",
        "lesson": "Loss 0.0%. Thesis falsch oder Entry zu früh.",
        "date": "2026-03-25",
        "pnl": -1.0
      },
      {
        "ticker": "9988.HK",
        "strategy": "DT4",
        "lesson": "CRV 0.2:1 war zu niedrig — schlechtes Setup.",
        "date": "2026-03-25",
        "pnl": -1.58
      },
      {
        "ticker": "7203.T",
        "strategy": "DT4",
        "lesson": "Stop korrekt ausgelöst bei 18.11. Regel befolgt.",
        "date": "2026-03-25",
        "pnl": -3.28
      },
      {
        "ticker": "9984.T",
        "strategy": "DT4",
        "lesson": "Stop korrekt ausgelöst bei 20.67. Regel befolgt.",
        "date": "2026-03-25",
        "pnl": -62.47
      },
      {
        "ticker": "SAP.DE",
        "strategy": "DT4",
        "lesson": "Stop korrekt ausgelöst bei 146.90. Regel befolgt.",
        "date": "2026-03-25",
        "pnl": -3.4
      },
      {
        "ticker": "GOOGL",
        "strategy": "DT4",
        "lesson": "Win trotz schwachem CRV 1.8:1. Luck oder Thesis?",
        "date": "2026-03-25",
        "pnl": 0.49
      },
      {
        "ticker": "GLEN.L",
        "strategy": "PS5",
        "lesson": "CRV 1.4:1 war zu niedrig — schlechtes Setup.",
        "date": "2026-03-25",
        "pnl": -2.35
      },
      {
        "ticker": "FRO",
        "strategy": "PS1",
        "lesson": "Loss -5.1%. Thesis falsch oder Entry zu früh.",
        "date": "2026-03-25",
        "pnl": -103.81
      },
      {
        "ticker": "AMD",
        "strategy": "DT4",
        "lesson": "Stop korrekt ausgelöst bei 189.23. Regel befolgt.",
        "date": "2026-03-25",
        "pnl": -42.23
      },
      {
        "ticker": "AMD",
        "strategy": "DT4",
        "lesson": "Stop korrekt ausgelöst bei 187.61. Regel befolgt.",
        "date": "2026-03-25",
        "pnl": -52.14
      }
    ]
  },
  "backtest": {
    "tickers_used": [
      "AIR.PA",
      "TTE.PA"
    ],
    "momentum": {
      "aggregate": {
        "total_trades": 38,
        "win_rate": 0.632,
        "total_pnl": 7261.11,
        "sharpe": 10.249,
        "max_drawdown": -550.55,
        "profit_factor": 6.976
      },
      "oos_valid": true,
      "benchmark": {
        "spy_return": 0.3366,
        "dax_return": 0.372,
        "buy_hold_return": 794.69
      },
      "windows": [
        {
          "ticker": "TTE.PA",
          "train_start": "2024-11-28",
          "test_start": "2025-05-23",
          "trades": 1,
          "pnl": 326.51,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2024-12-30",
          "test_start": "2025-06-20",
          "trades": 1,
          "pnl": -40.32,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-01-28",
          "test_start": "2025-07-18",
          "trades": 1,
          "pnl": -15.28,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-02-25",
          "test_start": "2025-08-15",
          "trades": 1,
          "pnl": 4.64,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-03-25",
          "test_start": "2025-09-12",
          "trades": 1,
          "pnl": -167.42,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-04-24",
          "test_start": "2025-10-10",
          "trades": 1,
          "pnl": 106.42,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-05-23",
          "test_start": "2025-11-07",
          "trades": 1,
          "pnl": 484.47,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-06-20",
          "test_start": "2025-12-05",
          "trades": 1,
          "pnl": -47.9,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-07-18",
          "test_start": "2026-01-07",
          "trades": 1,
          "pnl": 574.92,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-08-15",
          "test_start": "2026-02-04",
          "trades": 1,
          "pnl": 1033.01,
          "wr": 1.0
        }
      ]
    },
    "mean_reversion": {
      "aggregate": {
        "total_trades": 31,
        "win_rate": 0.935,
        "total_pnl": 7796.52,
        "sharpe": 25.167,
        "max_drawdown": -147.37,
        "profit_factor": 53.196
      },
      "oos_valid": true,
      "benchmark": {
        "spy_return": 0.3366,
        "dax_return": 0.372,
        "buy_hold_return": 794.69
      },
      "windows": [
        {
          "ticker": "TTE.PA",
          "train_start": "2024-11-28",
          "test_start": "2025-05-23",
          "trades": 1,
          "pnl": 274.4,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2024-12-30",
          "test_start": "2025-06-20",
          "trades": 1,
          "pnl": 274.4,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-01-28",
          "test_start": "2025-07-18",
          "trades": 1,
          "pnl": 274.4,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-02-25",
          "test_start": "2025-08-15",
          "trades": 1,
          "pnl": 274.4,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-03-25",
          "test_start": "2025-09-12",
          "trades": 1,
          "pnl": 202.5,
          "wr": 1.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-04-24",
          "test_start": "2025-10-10",
          "trades": 0,
          "pnl": 0,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-05-23",
          "test_start": "2025-11-07",
          "trades": 0,
          "pnl": 0,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-06-20",
          "test_start": "2025-12-05",
          "trades": 0,
          "pnl": 0,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-07-18",
          "test_start": "2026-01-07",
          "trades": 0,
          "pnl": 0,
          "wr": 0.0
        },
        {
          "ticker": "TTE.PA",
          "train_start": "2025-08-15",
          "test_start": "2026-02-04",
          "trades": 0,
          "pnl": 0,
          "wr": 0.0
        }
      ]
    },
    "generated_at": "2026-03-26T23:03:50.308900"
  }
};render();function load(){}

function tab(t){
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(s=>s.classList.remove('active'));
  document.getElementById('sec-'+t).classList.add('active');
  event.target.closest('.nav-item').classList.add('active');
}

const fmt=v=>(v>=0?'+':'')+Math.round(v)+'€';
const pct=v=>(v>=0?'+':'')+v.toFixed(1)+'%';
const cls=v=>v>=0?'green':'red';

function render(){
  const p=D.positions||{}, r=D.risk||{}, perf=D.performance||{}, l=D.learning||{}, bt=D.backtest||{};
  const open=p.open||[];
  const totalPnl=perf.total_pnl||0;
  const openPnl=open.reduce((s,x)=>s+(x.pnl_eur||0),0);
  const closedN=perf.closed_trades||0;
  const wr=perf.win_rate||0;
  const cb=r.circuit_breaker||{};

  // Header
  document.getElementById('h-pnl').className='val '+(totalPnl>=0?'green':'red');
  document.getElementById('h-pnl').textContent=fmt(totalPnl);
  document.getElementById('h-open').textContent=open.length;
  document.getElementById('h-vix').textContent=(cb.details||{}).current_vix||'?';
  const hcb=document.getElementById('h-cb');
  if(cb.trading_allowed){hcb.className='cb-indicator cb-ok';hcb.innerHTML='● Trading OK'}
  else{hcb.className='cb-indicator cb-blocked';hcb.innerHTML='● GESPERRT: '+(cb.breakers_triggered||[]).join(', ')}
  document.getElementById('nav-pos-count').textContent=open.length;

  // Overview KPIs
  document.getElementById('overview-kpis').innerHTML=\`
    <div class="card kpi"><div class="number \${cls(totalPnl)}">\${fmt(totalPnl)}</div><div class="sublabel">Realisiert</div></div>
    <div class="card kpi"><div class="number \${cls(openPnl)}">\${fmt(openPnl)}</div><div class="sublabel">Unrealisiert</div></div>
    <div class="card kpi"><div class="number">\${closedN}</div><div class="sublabel">Geschlossene Trades</div></div>
    <div class="card kpi"><div class="number \${wr>45?'green':wr>35?'amber':'red'}">\${(wr*100).toFixed(0)}%</div><div class="sublabel">Win Rate</div></div>\`;

  // Equity curve (overview + performance)
  const ec=perf.equity_curve||[];
  if(ec.length>1){
    ['ov-equity','perf-equity'].forEach(id=>{
      const ctx=document.getElementById(id);
      if(!ctx)return;
      new Chart(ctx,{type:'line',data:{labels:ec.map(e=>e.date||''),datasets:[{
        data:ec.map(e=>e.cumulative_pnl||0),borderColor:'#06b6d4',backgroundColor:'rgba(6,182,212,0.08)',
        fill:true,tension:0.3,pointRadius:0,borderWidth:2}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
        scales:{x:{ticks:{color:'#64748b',maxTicksLimit:8,font:{size:10}},grid:{display:false}},
        y:{ticks:{color:'#64748b',callback:v=>v+'€'},grid:{color:'rgba(30,41,59,0.5)'}}}}});
    });
  }

  // Activity feed
  const trades=perf.recent_trades||ec.slice(-10).reverse();
  document.getElementById('ov-feed').innerHTML=trades.map(t=>{
    const c=t.pnl_eur>=0?'win':'loss';
    return \`<div class="feed-item \${c}"><div class="ts">\${t.date||''}</div><b>\${t.ticker||''}</b> \${t.strategy||''} — <span class="\${cls(t.pnl_eur||0)}">\${fmt(t.pnl_eur||0)}</span></div>\`;
  }).join('')||'<div style="color:var(--muted)">Keine Trades</div>';

  // Best/Worst strategy
  const strats=perf.strategies||[];
  const best=strats.reduce((a,b)=>(a.total_pnl||0)>(b.total_pnl||0)?a:b,{});
  const worst=strats.reduce((a,b)=>(a.total_pnl||0)<(b.total_pnl||0)?a:b,{});
  document.getElementById('ov-best').innerHTML=best.strategy?\`<div class="kpi"><div class="number green">\${best.strategy}</div><div class="sublabel">\${fmt(best.total_pnl||0)} | WR \${((best.win_rate||0)*100).toFixed(0)}% | Sharpe \${(best.sharpe||0).toFixed(2)}</div></div>\`:'—';
  document.getElementById('ov-worst').innerHTML=worst.strategy?\`<div class="kpi"><div class="number red">\${worst.strategy}</div><div class="sublabel">\${fmt(worst.total_pnl||0)} | WR \${((worst.win_rate||0)*100).toFixed(0)}% | Sharpe \${(worst.sharpe||0).toFixed(2)}</div></div>\`:'—';

  // Top risk
  const stress=r.stress_tests||[];
  const topStress=stress[0]||{};
  document.getElementById('ov-toprisk').innerHTML=\`<div class="kpi"><div class="number red">\${fmt(topStress.total_loss||0)}</div><div class="sublabel">\${topStress.name||'Kein Stress-Test'}</div></div>\`;

  // Positions
  document.getElementById('pos-tbody').innerHTML=open.map(pos=>\`<tr>
    <td class="ticker-cell">\${pos.ticker}</td><td><span class="badge b-blue">\${pos.strategy||''}</span></td>
    <td>\${pos.geo_theme||'—'}</td><td>\${(pos.entry_price||0).toFixed(2)}€</td>
    <td>\${(pos.current_price||pos.entry_price||0).toFixed(2)}€</td>
    <td class="\${cls(pos.pnl_eur||0)}"><b>\${fmt(pos.pnl_eur||0)}</b> (\${pct(pos.pnl_pct||0)})</td>
    <td>\${(pos.stop||0).toFixed(2)}€</td>
    <td>\${pos.risk_eur?Math.round(pos.risk_eur)+'€':'—'}</td>
    <td>\${pos.holding_days||0}d</td></tr>\`).join('');

  // Risk - Circuit Breaker
  const cbd=cb.details||{};
  document.getElementById('risk-cb').innerHTML=\`
    <div style="font-size:1.5rem;margin:1rem 0">\${cb.trading_allowed?'✅ Trading erlaubt':'🚨 TRADING GESPERRT'}</div>
    <div class="grid g2" style="gap:0.5rem">
      <div>Daily P&L: <b class="\${cls(cbd.daily_pnl||0)}">\${fmt(cbd.daily_pnl||0)}</b> / \${cb.limits?.daily_loss_limit||'-500'}€</div>
      <div>Weekly P&L: <b class="\${cls(cbd.weekly_pnl||0)}">\${fmt(cbd.weekly_pnl||0)}</b> / \${cb.limits?.weekly_loss_limit||'-1500'}€</div>
      <div>Consec Losses: <b>\${cbd.consecutive_losses||0}</b> / 5</div>
      <div>VIX: <b>\${cbd.current_vix||'?'}</b> / 45 (panic)</div>
    </div>\`;

  // Stress tests
  document.getElementById('risk-stress').innerHTML=stress.map(s=>{
    const sev=s.severity==='critical'?'red':s.severity==='high'?'amber':'green';
    const w=Math.min(Math.abs(s.total_loss||0)/7000*100,100);
    return \`<div style="margin:8px 0"><div style="display:flex;justify-content:space-between;font-size:0.82rem">
      <span>\${s.name}</span><span class="\${sev}" style="font-weight:700">\${fmt(s.total_loss||0)}</span></div>
      <div class="prog-wrap"><div class="prog-bar" style="width:\${w}%;background:var(--\${sev})"></div></div></div>\`;
  }).join('');

  // Exposure bars
  renderExposure('risk-sector', r.exposure?.by_sector||{}, 40);
  renderExposure('risk-region', r.exposure?.by_region||{}, 60);

  // Performance KPIs
  const sharpe=perf.sharpe||0;
  document.getElementById('perf-kpis').innerHTML=\`
    <div class="card kpi"><div class="number">\${closedN}</div><div class="sublabel">Trades</div></div>
    <div class="card kpi"><div class="number \${cls(totalPnl)}">\${fmt(totalPnl)}</div><div class="sublabel">P&L</div></div>
    <div class="card kpi"><div class="number \${sharpe>0?'green':'red'}">\${sharpe.toFixed(2)}</div><div class="sublabel">Sharpe Ratio</div></div>
    <div class="card kpi"><div class="number">\${(perf.profit_factor||0).toFixed(2)}</div><div class="sublabel">Profit Factor</div></div>\`;

  // Top/Worst trades
  const sorted=ec.slice().sort((a,b)=>(b.pnl_eur||0)-(a.pnl_eur||0));
  document.getElementById('perf-top').innerHTML=sorted.slice(0,5).map(t=>
    \`<div class="feed-item win"><b>\${t.ticker||''}</b> \${t.strategy||''} — <span class="green"><b>\${fmt(t.pnl_eur||0)}</b></span> (\${pct(t.pnl_pct||0)})</div>\`).join('');
  document.getElementById('perf-worst').innerHTML=sorted.slice(-5).reverse().map(t=>
    \`<div class="feed-item loss"><b>\${t.ticker||''}</b> \${t.strategy||''} — <span class="red"><b>\${fmt(t.pnl_eur||0)}</b></span> (\${pct(t.pnl_pct||0)})</div>\`).join('');

  // Strategies table
  document.getElementById('strat-tbody').innerHTML=strats.map(s=>{
    const v=s.verdict||'?';
    const bc=v==='KILL'?'b-red':v==='REVIEW'?'b-amber':v==='KEEP'?'b-green':'b-blue';
    return \`<tr><td class="ticker-cell">\${s.strategy}</td><td>\${s.trades}</td>
      <td>\${((s.win_rate||0)*100).toFixed(0)}%</td><td class="\${cls(s.total_pnl||0)}">\${fmt(s.total_pnl||0)}</td>
      <td>\${(s.sharpe||0).toFixed(2)}</td><td>\${(s.profit_factor||0).toFixed(2)}</td>
      <td>\${s.p_value!=null?s.p_value.toFixed(3):'—'}</td>
      <td><span class="badge \${bc}">\${v}</span></td></tr>\`;}).join('');

  // Graveyard
  const graveyard=D.graveyard||[
    {name:'DT3',reason:'11% WR, Sharpe -12.55, p=1.00',pnl:-415,trades:9,date:'2026-03-26'},
    {name:'DT4',reason:'43% WR, Sharpe -4.38, p=0.93',pnl:-725,trades:102,date:'2026-03-26'}
  ];
  document.getElementById('strat-graveyard').innerHTML=graveyard.map(g=>
    \`<div class="grave"><div class="name">🪦 \${g.name} <span style="color:var(--muted);font-weight:400">— beerdigt \${g.date}</span></div>
    <div style="margin-top:4px;font-size:0.82rem">\${g.reason}</div>
    <div style="margin-top:2px;font-size:0.82rem">P&L: <span class="red">\${fmt(g.pnl)}</span> | \${g.trades} Trades</div></div>\`).join('');

  // Learning
  const ta=l.thesis_accuracy||{};
  const rated=(ta.correct||0)+(ta.incorrect||0);
  const thPct=rated>0?(ta.correct/rated*100):0;
  document.getElementById('learn-kpis').innerHTML=\`
    <div class="card kpi"><div class="number \${thPct>50?'green':'amber'}">\${rated>0?thPct.toFixed(0)+'%':'—'}</div><div class="sublabel">These-Trefferquote</div></div>
    <div class="card kpi"><div class="number">\${l.total_trades||0}</div><div class="sublabel">SA Trades</div></div>
    <div class="card kpi"><div class="number \${cls(l.total_pnl||0)}">\${fmt(l.total_pnl||0)}</div><div class="sublabel">SA P&L</div></div>\`;

  renderBars('learn-setup', l.by_setup||{});
  renderBars('learn-theme', l.by_theme||{});

  document.getElementById('learn-lessons').innerHTML=(l.lessons||[]).slice(-10).reverse().map(le=>
    \`<div class="feed-item"><div class="ts">\${le.date} — \${le.ticker} (\${fmt(le.pnl||0)})</div>\${le.lesson}</div>\`
  ).join('')||'<div style="color:var(--muted)">Erste SA-Trades starten die Lektionen-Datenbank.</div>';

  document.getElementById('learn-insights').innerHTML=(l.meta_insights||[]).map(i=>
    \`<div style="padding:6px 0;font-size:0.85rem">\${i}</div>\`).join('')||'<div style="color:var(--muted)">Insights ab 5+ geschlossenen SA-Trades.</div>';

  // Backtest
  renderBT('bt-mom', bt.momentum||{});
  renderBT('bt-mr', bt.mean_reversion||{});

  // Benchmark chart
  const bmk=bt.benchmark||{};
  if(bmk.spy_return!=null){
    const momPnl=(bt.momentum?.aggregate?.total_pnl)||0;
    const mrPnl=(bt.mean_reversion?.aggregate?.total_pnl)||0;
    new Chart(document.getElementById('bt-chart'),{type:'bar',
      data:{labels:['Momentum','Mean-Rev','SPY B&H','DAX B&H'],
      datasets:[{data:[momPnl,mrPnl,bmk.spy_return*250||0,bmk.dax_return*250||0],
        backgroundColor:['#06b6d4','#8b5cf6','#64748b','#64748b'],borderRadius:6}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
        scales:{y:{ticks:{color:'#64748b',callback:v=>v+'€'},grid:{color:'rgba(30,41,59,0.5)'}},
        x:{ticks:{color:'#64748b'}}}}});
  }
}

function renderExposure(id, data, limit){
  const el=document.getElementById(id);
  const entries=Object.entries(data).sort((a,b)=>(b[1].pct||0)-(a[1].pct||0));
  const colors=['#06b6d4','#10b981','#f59e0b','#8b5cf6','#ef4444','#ec4899','#6366f1'];
  el.innerHTML=entries.map(([k,v],i)=>{
    const pctVal=v.pct||0;
    const over=pctVal>limit;
    return \`<div class="exp-row"><div class="exp-label">\${k}</div>
      <div class="exp-bar-wrap"><div class="exp-bar" style="width:\${Math.min(pctVal,100)}%;background:\${over?'var(--red)':colors[i%7]}">\${pctVal>8?pctVal.toFixed(0)+'%':''}</div>
      <div class="exp-limit" style="left:\${limit}%"></div></div>
      <div class="exp-val \${over?'red':''}">\${pctVal.toFixed(1)}%</div></div>\`;
  }).join('');
}

function renderBars(id, data){
  const el=document.getElementById(id);
  const entries=Object.entries(data);
  if(!entries.length){el.innerHTML='<div style="color:var(--muted)">Noch keine Daten</div>';return}
  el.innerHTML=entries.map(([k,v])=>{
    const pnl=v.pnl||0;
    return \`<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:0.82rem;border-bottom:1px solid var(--border)">
      <span>\${k}</span><span>\${v.trades||0} trades | <span class="\${cls(pnl)}">\${fmt(pnl)}</span></span></div>\`;
  }).join('');
}

function renderBT(id, data){
  const el=document.getElementById(id);
  const agg=data.aggregate||{};
  if(!agg.total_trades){el.innerHTML='<div style="color:var(--muted)">Kein Backtest</div>';return}
  const oos=data.out_of_sample_valid;
  el.innerHTML=\`
    <div class="grid g2" style="gap:8px;font-size:0.85rem;margin-bottom:1rem">
      <div>Trades: <b>\${agg.total_trades}</b></div><div>Win Rate: <b>\${((agg.win_rate||0)*100).toFixed(0)}%</b></div>
      <div>P&L: <b class="\${cls(agg.total_pnl||0)}">\${fmt(agg.total_pnl||0)}</b></div><div>Sharpe: <b>\${(agg.sharpe||0).toFixed(2)}</b></div>
      <div>Max DD: <b class="red">\${fmt(agg.max_drawdown||0)}</b></div><div>PF: <b>\${(agg.profit_factor||0).toFixed(2)}</b></div>
    </div>
    <span class="badge \${oos?'b-green':'b-red'}">Out-of-Sample: \${oos?'✅ Valide':'❌ Nicht valide'}</span>\`;
}

load();
</script>
</body>
</html>
`);
};
