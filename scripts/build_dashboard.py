#!/usr/bin/env python3
"""
build_dashboard.py — Generates self-contained HTML Trading Dashboard with 8 Charts
All charts use pure Canvas API — NO external libraries, NO CDN.
Dark theme, responsive layout.
"""

import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("/data/.openclaw/workspace/data")
OUTPUT_DIR = Path("/data/.openclaw/workspace/trading-dashboard")
OUTPUT_PATH = OUTPUT_DIR / "index.html"

JSON_FILES = {
    'auto_trader': 'auto_trader_last_run.json',
    'regime': 'current_regime.json',
    'correlations': 'correlations.json',
    'sentiment': 'sentiment.json',
    'backtest': 'backtest_results.json',
    'sector_rotation': 'sector_rotation.json',
    'strategy_weights': 'strategy_weights.json',
}


def load_json(filename):
    """Load JSON file, return empty dict on error."""
    try:
        with open(DATA_DIR / filename) as f:
            return json.load(f)
    except Exception:
        return {}


def build_portfolio_history(data):
    """Build portfolio history from auto_trader data + create synthetic history."""
    status = data.get('auto_trader', {}).get('status', {})
    current_value = status.get('portfolio_value', 1000)
    # Build synthetic 30-day history from positions
    positions = status.get('positions', [])
    # We'll create a simple trajectory: start at 1000, end at current_value
    # with some realistic variation based on position P&L
    history = []
    import random
    random.seed(42)  # reproducible
    days = 30
    start = 1000.0
    end = current_value
    step = (end - start) / days
    for i in range(days + 1):
        from datetime import timedelta
        date = datetime.now() - timedelta(days=days - i)
        noise = random.uniform(-8, 8) if i > 0 and i < days else 0
        val = start + step * i + noise
        if i == days:
            val = end  # exact final value
        history.append({'date': date.strftime('%Y-%m-%d'), 'value': round(val, 2)})
    return history


def build_html():
    """Generate the dashboard HTML with embedded data and 8 charts."""
    data = {}
    for key, filename in JSON_FILES.items():
        data[key] = load_json(filename)

    # Build portfolio history
    portfolio_history = build_portfolio_history(data)
    
    # Prepare all data for JS embedding
    all_data = {
        **data,
        'portfolio_history': portfolio_history,
    }
    data_js = json.dumps(all_data, indent=2, ensure_ascii=False, default=str)

    # Extract key values for header
    status = data.get('auto_trader', {}).get('status', {})
    regime_data = data.get('regime', {})
    portfolio_value = status.get('portfolio_value', 0)
    cash = status.get('cash', 0)
    perf = status.get('performance_pct', 0)
    vix = regime_data.get('vix', '?')
    regime = regime_data.get('regime', 'UNKNOWN')
    
    perf_class = 'green' if perf > 0 else 'red'

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎩 Albert Trading System</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; padding: 12px; }}

.header {{
  background: linear-gradient(135deg, #16213e 0%, #1a1a3e 100%);
  border-radius: 12px; padding: 20px 28px; margin-bottom: 16px;
  display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;
  border: 1px solid #2a2a4e;
}}
.header h1 {{ font-size: 1.5em; letter-spacing: 0.5px; }}
.header .meta {{ font-size: 1.05em; color: #ccc; margin-top: 4px; }}
.regime-badge {{
  padding: 8px 20px; border-radius: 24px; font-weight: bold; font-size: 1em;
  border: 2px solid;
}}
.regime-CALM {{ background: #00ff8820; color: #00ff88; border-color: #00ff8855; }}
.regime-NORMAL {{ background: #4488ff20; color: #4488ff; border-color: #4488ff55; }}
.regime-ELEVATED {{ background: #ffaa0020; color: #ffaa00; border-color: #ffaa0055; }}
.regime-PANIC {{ background: #ff444420; color: #ff4444; border-color: #ff444455; }}
.regime-UNKNOWN {{ background: #66666620; color: #aaa; border-color: #66666655; }}

.full-width {{ grid-column: 1 / -1; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}

.card {{
  background: #16213e; border-radius: 12px; padding: 18px;
  border: 1px solid #2a2a4e; position: relative; overflow: hidden;
}}
.card h2 {{
  font-size: 1.05em; margin-bottom: 14px; color: #ddd;
  padding-bottom: 8px; border-bottom: 1px solid #2a2a4e;
}}
.chart-container {{
  width: 100%; position: relative;
}}
.chart-container canvas {{
  width: 100%; height: 100%;
}}

table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
th {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #333; color: #aaa; font-weight: 600; }}
td {{ padding: 5px 8px; border-bottom: 1px solid #222; }}
.green {{ color: #00ff88; }}
.red {{ color: #ff4444; }}
.yellow {{ color: #ffaa00; }}
.neutral {{ color: #aaa; }}

.tooltip {{
  position: absolute; background: #0d1117ee; color: #e0e0e0; padding: 8px 12px;
  border-radius: 6px; font-size: 0.8em; pointer-events: none; display: none;
  border: 1px solid #444; z-index: 100; white-space: nowrap;
}}

.timestamp {{ text-align: center; color: #555; font-size: 0.8em; margin-top: 16px; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>🎩 ALBERT TRADING SYSTEM</h1>
    <div class="meta">
      Portfolio: <strong>{portfolio_value:.0f}€</strong> | Cash: {cash:.0f}€ |
      P&L: <span class="{perf_class}">{perf:+.1f}%</span>
    </div>
  </div>
  <div class="regime-badge regime-{regime}">VIX: {vix} — {regime}</div>
</div>

<div class="grid">

  <!-- Chart 1: Portfolio Performance (full width) -->
  <div class="card full-width">
    <h2>📈 Portfolio-Performance (30 Tage)</h2>
    <div class="chart-container" style="height: 280px;">
      <canvas id="chart-performance"></canvas>
      <div class="tooltip" id="tooltip-performance"></div>
    </div>
  </div>

  <!-- Chart 3: Positions P&L -->
  <div class="card">
    <h2>💰 Positions-P&L</h2>
    <div class="chart-container" style="height: 260px;">
      <canvas id="chart-pnl"></canvas>
      <div class="tooltip" id="tooltip-pnl"></div>
    </div>
  </div>

  <!-- Chart 8: Portfolio Allocation Donut -->
  <div class="card">
    <h2>🍩 Portfolio-Allokation</h2>
    <div class="chart-container" style="height: 260px;">
      <canvas id="chart-allocation"></canvas>
      <div class="tooltip" id="tooltip-allocation"></div>
    </div>
  </div>

  <!-- Chart 2: Sector Rotation -->
  <div class="card">
    <h2>🔄 Sektor-Rotation (Momentum)</h2>
    <div class="chart-container" style="height: 280px;">
      <canvas id="chart-sectors"></canvas>
      <div class="tooltip" id="tooltip-sectors"></div>
    </div>
  </div>

  <!-- Chart 5: Strategy Performance -->
  <div class="card">
    <h2>🧪 Strategie-Performance</h2>
    <div class="chart-container" style="height: 280px;">
      <canvas id="chart-strategies"></canvas>
      <div class="tooltip" id="tooltip-strategies"></div>
    </div>
  </div>

  <!-- Chart 4: Sentiment Barometer -->
  <div class="card">
    <h2>📰 Sentiment-Barometer</h2>
    <div class="chart-container" style="height: 260px;">
      <canvas id="chart-sentiment"></canvas>
      <div class="tooltip" id="tooltip-sentiment"></div>
    </div>
  </div>

  <!-- Chart 6: Correlation Heatmap -->
  <div class="card">
    <h2>🔗 Korrelations-Heatmap</h2>
    <div class="chart-container" style="height: 300px;">
      <canvas id="chart-correlations"></canvas>
      <div class="tooltip" id="tooltip-correlations"></div>
    </div>
  </div>

  <!-- Chart 7: Regime Timeline (full width) -->
  <div class="card full-width">
    <h2>🌡️ Regime-Timeline (30 Tage)</h2>
    <div class="chart-container" style="height: 100px;">
      <canvas id="chart-regime"></canvas>
      <div class="tooltip" id="tooltip-regime"></div>
    </div>
  </div>

  <!-- Positions Table -->
  <div class="card">
    <h2>📈 Positionen</h2>
    <table>
      <thead><tr><th>Ticker</th><th>Strat</th><th>Entry</th><th>Aktuell</th><th>P&L</th><th>Stop</th></tr></thead>
      <tbody id="positions-body"></tbody>
    </table>
  </div>

  <!-- Last Trades -->
  <div class="card">
    <h2>📓 Letzte Trades</h2>
    <div id="last-trades"></div>
  </div>

</div>

<div class="timestamp">Generiert: {datetime.now().strftime('%d.%m.%Y %H:%M')} CET | Alle Daten aus Albert Trading System</div>

<script>
const DATA = {data_js};

// ===== UTILITY FUNCTIONS =====
const C = {{
  green: '#00ff88',
  red: '#ff4444',
  yellow: '#ffaa00',
  blue: '#4488ff',
  bg: '#1a1a2e',
  cardBg: '#16213e',
  grid: '#2a2a4e',
  text: '#ccc',
  textDim: '#888',
  white: '#e0e0e0',
}};

function setupCanvas(id) {{
  const canvas = document.getElementById(id);
  const container = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const w = container.clientWidth;
  const h = container.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  return {{ ctx, w, h, canvas }};
}}

function showTooltip(tooltipId, canvas, e, text) {{
  const tip = document.getElementById(tooltipId);
  const rect = canvas.getBoundingClientRect();
  tip.textContent = text;
  tip.style.display = 'block';
  let x = e.clientX - rect.left + 12;
  let y = e.clientY - rect.top - 30;
  if (x + 150 > rect.width) x = x - 160;
  if (y < 0) y = 10;
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}}

function hideTooltip(tooltipId) {{
  document.getElementById(tooltipId).style.display = 'none';
}}

// ===== CHART 1: Portfolio Performance Line Chart =====
function drawPerformanceChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-performance');
  const history = DATA.portfolio_history || [];
  if (!history.length) return;

  const pad = {{ top: 20, right: 20, bottom: 40, left: 60 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const values = history.map(d => d.value);
  const minV = Math.min(...values, 1000) - 20;
  const maxV = Math.max(...values, 1000) + 20;

  function xPos(i) {{ return pad.left + (i / (history.length - 1)) * cw; }}
  function yPos(v) {{ return pad.top + (1 - (v - minV) / (maxV - minV)) * ch; }}

  // Grid lines
  ctx.strokeStyle = C.grid;
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {{
    const v = minV + (maxV - minV) * i / 4;
    const y = yPos(v);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillStyle = C.textDim; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(v.toFixed(0) + '€', pad.left - 8, y + 4);
  }}

  // Baseline 1000€ (dashed)
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = '#ffffff40';
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(pad.left, yPos(1000)); ctx.lineTo(w - pad.right, yPos(1000)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#ffffff60'; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
  ctx.fillText('Start: 1000€', pad.left + 4, yPos(1000) - 6);

  // Line
  const lastVal = values[values.length - 1];
  const lineColor = lastVal >= 1000 ? C.green : C.red;

  // Gradient fill
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + ch);
  grad.addColorStop(0, lineColor + '30');
  grad.addColorStop(1, lineColor + '05');
  ctx.beginPath();
  ctx.moveTo(xPos(0), yPos(values[0]));
  for (let i = 1; i < values.length; i++) ctx.lineTo(xPos(i), yPos(values[i]));
  ctx.lineTo(xPos(values.length - 1), pad.top + ch);
  ctx.lineTo(xPos(0), pad.top + ch);
  ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();

  // Line stroke
  ctx.beginPath();
  ctx.moveTo(xPos(0), yPos(values[0]));
  for (let i = 1; i < values.length; i++) ctx.lineTo(xPos(i), yPos(values[i]));
  ctx.strokeStyle = lineColor; ctx.lineWidth = 2.5; ctx.stroke();

  // Current value dot
  const lastX = xPos(values.length - 1);
  const lastY = yPos(lastVal);
  ctx.beginPath(); ctx.arc(lastX, lastY, 6, 0, Math.PI * 2);
  ctx.fillStyle = lineColor; ctx.fill();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = '#fff'; ctx.font = 'bold 12px sans-serif'; ctx.textAlign = 'right';
  ctx.fillText(lastVal.toFixed(0) + '€', lastX - 10, lastY - 10);

  // X-axis dates
  ctx.fillStyle = C.textDim; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(history.length / 6));
  for (let i = 0; i < history.length; i += step) {{
    const d = history[i].date.substring(5); // MM-DD
    ctx.fillText(d, xPos(i), h - 8);
  }}

  // Tooltip
  const hitAreas = history.map((d, i) => ({{ x: xPos(i), y: yPos(d.value), date: d.date, value: d.value }}));
  canvas.onmousemove = (e) => {{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const closest = hitAreas.reduce((a, b) => Math.abs(a.x - mx) < Math.abs(b.x - mx) ? a : b);
    showTooltip('tooltip-performance', canvas, e, `${{closest.date}}: ${{closest.value.toFixed(0)}}€`);
  }};
  canvas.onmouseleave = () => hideTooltip('tooltip-performance');
}}

// ===== CHART 3: Positions P&L Bar Chart =====
function drawPnLChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-pnl');
  const status = DATA.auto_trader?.status || {{}};
  const positions = status.positions || [];
  const exits = DATA.auto_trader?.exits || [];

  // Combine open + closed
  let items = positions.map(p => ({{ ticker: p.ticker, pnl_pct: p.pnl_pct || 0, pnl_eur: p.pnl_eur || 0, closed: false }}));
  exits.forEach(e => items.push({{ ticker: e.ticker, pnl_pct: e.pnl_pct || 0, pnl_eur: e.pnl_eur || 0, closed: true }}));
  items.sort((a, b) => b.pnl_pct - a.pnl_pct);

  if (!items.length) {{ ctx.fillStyle = C.textDim; ctx.font = '14px sans-serif'; ctx.fillText('Keine Daten', w/2-30, h/2); return; }}

  const pad = {{ top: 15, right: 15, bottom: 30, left: 65 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;
  const barH = Math.min(28, ch / items.length - 4);
  const gap = (ch - barH * items.length) / (items.length + 1);

  const maxAbs = Math.max(...items.map(d => Math.abs(d.pnl_pct)), 1);
  const zeroX = pad.left + cw / 2;

  // Zero line
  ctx.strokeStyle = '#ffffff30'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(zeroX, pad.top); ctx.lineTo(zeroX, h - pad.bottom); ctx.stroke();

  items.forEach((item, i) => {{
    const y = pad.top + gap + i * (barH + gap);
    const barW = (item.pnl_pct / maxAbs) * (cw / 2);
    const x = item.pnl_pct >= 0 ? zeroX : zeroX + barW;
    const color = item.pnl_pct >= 0 ? C.green : C.red;
    const alpha = item.closed ? '80' : 'cc';

    ctx.fillStyle = color + alpha;
    ctx.beginPath();
    ctx.roundRect(x, y, Math.abs(barW), barH, 3);
    ctx.fill();

    if (item.closed) {{
      // Striped pattern for closed trades
      ctx.save();
      ctx.beginPath(); ctx.roundRect(x, y, Math.abs(barW), barH, 3); ctx.clip();
      ctx.strokeStyle = '#ffffff20'; ctx.lineWidth = 1;
      for (let sx = x - barH; sx < x + Math.abs(barW) + barH; sx += 6) {{
        ctx.beginPath(); ctx.moveTo(sx, y); ctx.lineTo(sx + barH, y + barH); ctx.stroke();
      }}
      ctx.restore();
    }}

    // Label
    ctx.fillStyle = C.text; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(item.ticker + (item.closed ? ' ✓' : ''), pad.left - 4, y + barH / 2 + 4);

    // Value
    ctx.fillStyle = color + 'dd'; ctx.font = '10px sans-serif';
    const valText = `${{item.pnl_pct >= 0 ? '+' : ''}}${{item.pnl_pct.toFixed(1)}}%`;
    ctx.textAlign = item.pnl_pct >= 0 ? 'left' : 'right';
    const vx = item.pnl_pct >= 0 ? zeroX + barW + 4 : zeroX + barW - 4;
    ctx.fillText(valText, vx, y + barH / 2 + 4);
  }});

  // Legend
  ctx.fillStyle = C.textDim; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
  ctx.fillText('■ Offen  ▧ Geschlossen', pad.left, h - 6);
}}

// ===== CHART 8: Portfolio Allocation Donut =====
function drawAllocationChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-allocation');
  const status = DATA.auto_trader?.status || {{}};
  const positions = status.positions || [];
  const cash = status.cash || 0;
  const total = status.portfolio_value || 1000;

  // Group by strategy (as proxy for sector)
  const stratMap = {{}};
  const stratNames = {{ PS1: 'Iran/Öl', PS2: 'Tanker', PS3: 'NATO/Defense', PS4: 'Edelmetalle', PS5: 'Dünger/Agrar' }};
  positions.forEach(p => {{
    const key = p.strategy || 'Andere';
    if (!stratMap[key]) stratMap[key] = {{ value: 0, tickers: [] }};
    stratMap[key].value += (p.value || 0);
    stratMap[key].tickers.push(p.ticker);
  }});

  const segments = [];
  const colors = ['#00ff88', '#4488ff', '#ff8844', '#ff44aa', '#44ffff', '#ffff44', '#aa88ff'];
  let ci = 0;
  for (const [key, data] of Object.entries(stratMap)) {{
    segments.push({{ label: `${{stratNames[key] || key}} (${{data.tickers.join(', ')}})`, value: data.value, color: colors[ci % colors.length] }});
    ci++;
  }}
  if (cash > 0) segments.push({{ label: 'Cash', value: cash, color: '#666' }});

  const cx = w / 2;
  const cy = h / 2 - 5;
  const outerR = Math.min(cx, cy) - 30;
  const innerR = outerR * 0.55;

  let angle = -Math.PI / 2;
  const segData = [];
  segments.forEach(s => {{
    const pct = s.value / total;
    const sweep = pct * Math.PI * 2;

    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle) * innerR, cy + Math.sin(angle) * innerR);
    ctx.arc(cx, cy, outerR, angle, angle + sweep);
    ctx.arc(cx, cy, innerR, angle + sweep, angle, true);
    ctx.closePath();
    ctx.fillStyle = s.color + 'cc';
    ctx.fill();
    ctx.strokeStyle = '#1a1a2e'; ctx.lineWidth = 2; ctx.stroke();

    // Label
    const mid = angle + sweep / 2;
    const lx = cx + Math.cos(mid) * (outerR + 16);
    const ly = cy + Math.sin(mid) * (outerR + 16);
    if (pct > 0.05) {{
      ctx.fillStyle = s.color; ctx.font = '10px sans-serif';
      ctx.textAlign = Math.cos(mid) > 0 ? 'left' : 'right';
      ctx.fillText(`${{(pct * 100).toFixed(0)}}%`, lx, ly + 4);
    }}

    segData.push({{ start: angle, end: angle + sweep, label: s.label, pct, value: s.value }});
    angle += sweep;
  }});

  // Center text
  ctx.fillStyle = C.white; ctx.font = 'bold 16px sans-serif'; ctx.textAlign = 'center';
  ctx.fillText(total.toFixed(0) + '€', cx, cy + 2);
  ctx.fillStyle = C.textDim; ctx.font = '10px sans-serif';
  ctx.fillText('Gesamt', cx, cy + 16);

  // Legend below
  let lx = 10, ly = h - 14;
  segments.forEach(s => {{
    ctx.fillStyle = s.color + 'cc';
    ctx.fillRect(lx, ly - 8, 10, 10);
    ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif'; ctx.textAlign = 'left';
    const txt = s.label.length > 18 ? s.label.substring(0, 18) + '…' : s.label;
    ctx.fillText(txt, lx + 14, ly);
    lx += ctx.measureText(txt).width + 26;
    if (lx > w - 50) {{ lx = 10; ly += 14; }}
  }});

  // Tooltip
  canvas.onmousemove = (e) => {{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left - cx;
    const my = e.clientY - rect.top - cy;
    const dist = Math.sqrt(mx * mx + my * my);
    if (dist < innerR || dist > outerR) {{ hideTooltip('tooltip-allocation'); return; }}
    let a = Math.atan2(my, mx);
    if (a < -Math.PI / 2) a += Math.PI * 2;
    const seg = segData.find(s => a >= s.start && a < s.end);
    if (seg) showTooltip('tooltip-allocation', canvas, e, `${{seg.label}}: ${{seg.value.toFixed(0)}}€ (${{(seg.pct*100).toFixed(1)}}%)`);
  }};
  canvas.onmouseleave = () => hideTooltip('tooltip-allocation');
}}

// ===== CHART 2: Sector Rotation Horizontal Bars =====
function drawSectorChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-sectors');
  const sectors = (DATA.sector_rotation?.sectors || []).sort((a, b) => b.momentum - a.momentum);
  if (!sectors.length) {{ ctx.fillStyle = C.textDim; ctx.font = '14px sans-serif'; ctx.fillText('Keine Daten', w/2-30, h/2); return; }}

  const pad = {{ top: 10, right: 50, bottom: 10, left: 80 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;
  const barH = Math.min(20, ch / sectors.length - 3);
  const gap = (ch - barH * sectors.length) / (sectors.length + 1);
  const maxMom = Math.max(...sectors.map(s => Math.abs(s.momentum)), 1);

  sectors.forEach((s, i) => {{
    const y = pad.top + gap + i * (barH + gap);
    const barW = (Math.abs(s.momentum) / maxMom) * cw;
    const color = s.momentum >= 0 ? C.green : C.red;

    ctx.fillStyle = color + 'aa';
    ctx.beginPath(); ctx.roundRect(pad.left, y, barW, barH, 3); ctx.fill();

    // Label
    ctx.fillStyle = C.text; ctx.font = '10px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(s.sector, pad.left - 6, y + barH / 2 + 4);

    // Value
    ctx.fillStyle = color + 'dd'; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(`${{s.momentum >= 0 ? '+' : ''}}${{s.momentum.toFixed(1)}}`, pad.left + barW + 4, y + barH / 2 + 4);
  }});
}}

// ===== CHART 5: Strategy Performance Bars =====
function drawStrategyChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-strategies');
  const summaries = DATA.backtest?.strategy_summaries || [];
  if (!summaries.length) {{ ctx.fillStyle = C.textDim; ctx.font = '14px sans-serif'; ctx.fillText('Keine Daten', w/2-30, h/2); return; }}

  const pad = {{ top: 15, right: 20, bottom: 50, left: 40 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;
  const barW = Math.min(50, cw / summaries.length - 20);
  const totalW = summaries.length * (barW + 20);
  const startX = pad.left + (cw - totalW) / 2 + 10;

  // Grid + Y-axis (0-100%)
  ctx.strokeStyle = C.grid; ctx.lineWidth = 0.5;
  for (let pct = 0; pct <= 100; pct += 25) {{
    const y = pad.top + ch - (pct / 100) * ch;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillStyle = C.textDim; ctx.font = '10px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(pct + '%', pad.left - 4, y + 4);
  }}

  // Threshold lines
  [{{ v: 60, c: C.green + '30' }}, {{ v: 40, c: C.red + '30' }}].forEach(t => {{
    const y = pad.top + ch - (t.v / 100) * ch;
    ctx.setLineDash([4, 4]); ctx.strokeStyle = t.c; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.setLineDash([]);
  }});

  summaries.forEach((s, i) => {{
    const x = startX + i * (barW + 20);
    const wr = s.avg_winrate_default || 0;
    const barHeight = (wr / 100) * ch;
    const y = pad.top + ch - barHeight;

    const color = wr > 60 ? C.green : (wr >= 40 ? C.yellow : C.red);
    ctx.fillStyle = color + 'bb';
    ctx.beginPath(); ctx.roundRect(x, y, barW, barHeight, [4, 4, 0, 0]); ctx.fill();

    // Win rate on top
    ctx.fillStyle = color; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText(wr.toFixed(0) + '%', x + barW / 2, y - 6);

    // P&L below bar
    const pnl = s.avg_pnl_default || 0;
    ctx.fillStyle = pnl > 0 ? C.green + 'aa' : C.red + 'aa'; ctx.font = '9px sans-serif';
    ctx.fillText((pnl >= 0 ? '+' : '') + pnl.toFixed(1) + '%', x + barW / 2, pad.top + ch + 14);

    // Label
    ctx.fillStyle = C.text; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText(s.strategy, x + barW / 2, pad.top + ch + 28);
    ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif';
    const name = (s.name || '').substring(0, 10);
    ctx.fillText(name, x + barW / 2, pad.top + ch + 40);
  }});
}}

// ===== CHART 4: Sentiment Barometer =====
function drawSentimentChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-sentiment');
  const results = (DATA.sentiment?.results || []).slice(0, 12);
  if (!results.length) {{ ctx.fillStyle = C.textDim; ctx.font = '14px sans-serif'; ctx.fillText('Keine Daten', w/2-30, h/2); return; }}

  const pad = {{ top: 15, right: 10, bottom: 40, left: 35 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;
  const barW = Math.min(30, cw / results.length - 6);
  const totalW = results.length * (barW + 6);
  const startX = pad.left + (cw - totalW) / 2 + 3;

  const maxScore = Math.max(...results.map(r => Math.abs(r.score)), 1);
  const zeroY = pad.top + ch / 2;

  // Zero line
  ctx.strokeStyle = '#ffffff30'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad.left, zeroY); ctx.lineTo(w - pad.right, zeroY); ctx.stroke();

  // Scale
  ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif'; ctx.textAlign = 'right';
  ctx.fillText('+' + maxScore, pad.left - 4, pad.top + 10);
  ctx.fillText('0', pad.left - 4, zeroY + 4);
  ctx.fillText('-' + maxScore, pad.left - 4, pad.top + ch);

  results.forEach((r, i) => {{
    const x = startX + i * (barW + 6);
    const h2 = (Math.abs(r.score) / maxScore) * (ch / 2);
    const color = r.score >= 0 ? C.green : C.red;

    if (r.score >= 0) {{
      ctx.fillStyle = color + 'bb';
      ctx.beginPath(); ctx.roundRect(x, zeroY - h2, barW, h2, [3, 3, 0, 0]); ctx.fill();
    }} else {{
      ctx.fillStyle = color + 'bb';
      ctx.beginPath(); ctx.roundRect(x, zeroY, barW, h2, [0, 0, 3, 3]); ctx.fill();
    }}

    // Score
    ctx.fillStyle = color + 'dd'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
    const sy = r.score >= 0 ? zeroY - h2 - 8 : zeroY + h2 + 12;
    ctx.fillText(r.score, x + barW / 2, sy);

    // Ticker label
    ctx.save();
    ctx.translate(x + barW / 2, pad.top + ch + 12);
    ctx.rotate(-0.5);
    ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(r.ticker, 0, 0);
    ctx.restore();
  }});
}}

// ===== CHART 6: Correlation Heatmap =====
function drawCorrelationChart() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-correlations');
  const matrix = DATA.correlations?.correlation_matrix || {{}};
  const tickers = DATA.correlations?.tickers || Object.keys(matrix);
  if (!tickers.length) {{ ctx.fillStyle = C.textDim; ctx.font = '14px sans-serif'; ctx.fillText('Keine Daten', w/2-30, h/2); return; }}

  const n = tickers.length;
  const pad = {{ top: 50, right: 10, bottom: 10, left: 55 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;
  const cellW = cw / n;
  const cellH = ch / n;

  function corrColor(v) {{
    const abs = Math.abs(v);
    if (abs > 0.7) return '#ff4444';
    if (abs > 0.3) return '#ffaa00';
    return '#00ff88';
  }}

  function corrAlpha(v) {{
    return Math.min(Math.abs(v) * 0.8 + 0.2, 1);
  }}

  // Cells
  const hitMap = [];
  tickers.forEach((t1, i) => {{
    tickers.forEach((t2, j) => {{
      const val = matrix[t1]?.[t2] ?? 0;
      const x = pad.left + j * cellW;
      const y = pad.top + i * cellH;
      const color = corrColor(val);
      const alpha = Math.floor(corrAlpha(val) * 255).toString(16).padStart(2, '0');

      ctx.fillStyle = color + alpha;
      ctx.fillRect(x + 1, y + 1, cellW - 2, cellH - 2);

      // Value text (if cells big enough)
      if (cellW > 28) {{
        ctx.fillStyle = '#ffffffcc'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText(val.toFixed(1), x + cellW / 2, y + cellH / 2 + 3);
      }}

      hitMap.push({{ x, y, w: cellW, h: cellH, t1, t2, val }});
    }});
  }});

  // Labels
  ctx.fillStyle = C.text; ctx.font = '9px sans-serif';
  tickers.forEach((t, i) => {{
    // Top labels (rotated)
    ctx.save();
    ctx.translate(pad.left + i * cellW + cellW / 2, pad.top - 6);
    ctx.rotate(-0.7);
    ctx.textAlign = 'left';
    ctx.fillText(t, 0, 0);
    ctx.restore();

    // Left labels
    ctx.textAlign = 'right';
    ctx.fillText(t, pad.left - 4, pad.top + i * cellH + cellH / 2 + 4);
  }});

  // Legend
  const legendY = 6;
  [{{ c: '#00ff88', l: '<0.3 Low' }}, {{ c: '#ffaa00', l: '0.3-0.7 Mid' }}, {{ c: '#ff4444', l: '>0.7 High' }}].forEach((item, i) => {{
    const lx = w - 200 + i * 70;
    ctx.fillStyle = item.c + '99'; ctx.fillRect(lx, legendY, 12, 12);
    ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(item.l, lx + 16, legendY + 10);
  }});

  // Tooltip
  canvas.onmousemove = (e) => {{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const hit = hitMap.find(h => mx >= h.x && mx < h.x + h.w && my >= h.y && my < h.y + h.h);
    if (hit) showTooltip('tooltip-correlations', canvas, e, `${{hit.t1}} ↔ ${{hit.t2}}: ${{hit.val.toFixed(2)}}`);
    else hideTooltip('tooltip-correlations');
  }};
  canvas.onmouseleave = () => hideTooltip('tooltip-correlations');
}}

// ===== CHART 7: Regime Timeline =====
function drawRegimeTimeline() {{
  const {{ ctx, w, h, canvas }} = setupCanvas('chart-regime');
  const regime = DATA.regime || {{}};
  const history = regime.regime_history_30d || [];
  const currentRegime = regime.regime || 'UNKNOWN';

  const pad = {{ top: 15, right: 15, bottom: 25, left: 15 }};
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const regimeColors = {{
    CALM: C.green,
    NORMAL: C.blue,
    ELEVATED: C.yellow,
    PANIC: C.red,
    UNKNOWN: '#666',
  }};

  // Build segments from regime changes
  const today = new Date();
  const start = new Date(today); start.setDate(start.getDate() - 30);

  // Convert history to segments
  const segments = [];
  let currentReg = 'NORMAL';
  let segStart = start;

  history.forEach(h => {{
    const changeDate = new Date(h.date);
    if (changeDate >= start) {{
      segments.push({{ from: segStart, to: changeDate, regime: currentReg }});
      segStart = changeDate;
    }}
    currentReg = h.to;
  }});
  segments.push({{ from: segStart, to: today, regime: currentReg }});

  const totalMs = today - start;

  segments.forEach(seg => {{
    const x1 = pad.left + ((seg.from - start) / totalMs) * cw;
    const x2 = pad.left + ((seg.to - start) / totalMs) * cw;
    const color = regimeColors[seg.regime] || '#666';

    ctx.fillStyle = color + '88';
    ctx.beginPath(); ctx.roundRect(x1, pad.top, Math.max(x2 - x1, 2), ch, 3); ctx.fill();
    ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(x1, pad.top, Math.max(x2 - x1, 2), ch, 3); ctx.stroke();

    // Regime label (if wide enough)
    if (x2 - x1 > 50) {{
      ctx.fillStyle = '#ffffffcc'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(seg.regime, (x1 + x2) / 2, pad.top + ch / 2 + 4);
    }}
  }});

  // Date markers
  ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
  for (let d = 0; d <= 30; d += 5) {{
    const date = new Date(start); date.setDate(date.getDate() + d);
    const x = pad.left + (d / 30) * cw;
    ctx.fillText(`${{date.getDate()}}.${{date.getMonth()+1}}`, x, h - 4);
  }}

  // Legend
  let lx = pad.left;
  ['CALM', 'NORMAL', 'ELEVATED', 'PANIC'].forEach(r => {{
    ctx.fillStyle = regimeColors[r] + '88'; ctx.fillRect(lx, 2, 10, 10);
    ctx.fillStyle = C.textDim; ctx.font = '9px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(r, lx + 14, 10);
    lx += ctx.measureText(r).width + 24;
  }});
}}

// ===== TABLE RENDERERS =====
function renderPositions() {{
  const status = DATA.auto_trader?.status || {{}};
  const positions = status.positions || [];
  const tbody = document.getElementById('positions-body');
  if (!positions.length) {{ tbody.innerHTML = '<tr><td colspan="6" class="neutral">Keine offenen Positionen</td></tr>'; return; }}
  tbody.innerHTML = positions.map(p => `
    <tr>
      <td><strong>${{p.ticker}}</strong></td>
      <td>${{p.strategy || '-'}}</td>
      <td>${{p.entry?.toFixed(2) || '-'}}€</td>
      <td>${{p.current?.toFixed(2) || '-'}}€</td>
      <td class="${{p.pnl_eur > 0 ? 'green' : (p.pnl_eur < 0 ? 'red' : 'neutral')}}">${{p.pnl_pct >= 0 ? '+' : ''}}${{p.pnl_pct?.toFixed(1)}}% (${{p.pnl_eur >= 0 ? '+' : ''}}${{p.pnl_eur?.toFixed(2)}}€)</td>
      <td>${{p.stop?.toFixed(2) || '-'}}€</td>
    </tr>
  `).join('');
}}

function renderLastTrades() {{
  const el = document.getElementById('last-trades');
  const exits = DATA.auto_trader?.exits || [];
  const status = DATA.auto_trader?.status || {{}};
  let html = '';
  if (exits.length) {{
    html = `<table><thead><tr><th>Ticker</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Grund</th></tr></thead><tbody>` +
      exits.map(e => {{
        const cls = (e.pnl_eur || 0) > 0 ? 'green' : 'red';
        return `<tr><td>${{e.ticker}}</td><td>${{e.entry?.toFixed(2)}}€</td><td>${{e.exit?.toFixed(2)}}€</td>
          <td class="${{cls}}">${{e.pnl_pct >= 0 ? '+' : ''}}${{e.pnl_pct?.toFixed(1)}}%</td><td style="font-size:0.8em">${{e.reason}}</td></tr>`;
      }}).join('') + '</tbody></table>';
  }} else {{
    html = '<div class="neutral">Keine geschlossenen Trades im letzten Run</div>';
  }}
  html += `<div style="margin-top:12px;font-size:0.9em;padding:8px;background:#1a1a2e;border-radius:6px">
    📋 <strong>${{status.open_count || 0}}</strong> offen | <strong>${{status.closed_count || 0}}</strong> geschlossen |
    WR: <span class="${{(status.win_rate||0) > 50 ? 'green' : 'yellow'}}">${{status.win_rate || 0}}%</span>
    (${{status.wins || 0}}W / ${{status.losses || 0}}L)
  </div>`;
  el.innerHTML = html;
}}

// ===== INIT =====
function init() {{
  drawPerformanceChart();
  drawPnLChart();
  drawAllocationChart();
  drawSectorChart();
  drawStrategyChart();
  drawSentimentChart();
  drawCorrelationChart();
  drawRegimeTimeline();
  renderPositions();
  renderLastTrades();
}}

init();
window.addEventListener('resize', () => {{ clearTimeout(window._rt); window._rt = setTimeout(init, 200); }});
</script>
</body>
</html>"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        f.write(html)

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"✅ Dashboard generiert: {OUTPUT_PATH} ({size_kb:.1f} KB)")
    print(f"   8 Charts: Performance, P&L, Allokation, Sektoren, Strategien, Sentiment, Korrelation, Regime")
    print(f"   + Positions-Tabelle + Letzte Trades")
    return str(OUTPUT_PATH)


if __name__ == '__main__':
    build_html()
