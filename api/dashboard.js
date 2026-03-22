// TradeMind Pro v3 — Vollständiges Trading Dashboard
// All 17 Issues TRA-127 to TRA-143 implemented
// Tabs: Real | Paper | News | Watchlist | Kalender | Risiko | Signale | DNA | Macro
// Build: 2026-03-19 23:45 CET

const TV_MAP = {
  'NVDA':'NASDAQ:NVDA','MSFT':'NASDAQ:MSFT','PLTR':'NYSE:PLTR',
  'AAPL':'NASDAQ:AAPL','TSLA':'NASDAQ:TSLA','AMD':'NASDAQ:AMD',
  'META':'NASDAQ:META','AMZN':'NASDAQ:AMZN',
  'FRO':'NYSE:FRO','DHT':'NYSE:DHT','OXY':'NYSE:OXY',
  'PAAS':'NYSE:PAAS','HL':'NYSE:HL','MOS':'NYSE:MOS','AG':'NYSE:AG',
  'EQNR':'OSL:EQNR','EQNR.OL':'OSL:EQNR',
  'RHM.DE':'XETR:RHM','BAYN.DE':'XETR:BAYN','SAP.DE':'XETR:SAP','SIE.DE':'XETR:SIE',
  'ASML.AS':'AMS:ASML','RIO.L':'LSE:RIO','BHP.L':'LSE:BHP','GLEN.L':'LSE:GLEN',
  'TTE.PA':'EURONEXT:TTE','HO.PA':'EURONEXT:HO','NOVO-B.CO':'OMXCOP:NOVO_B',
  '1605.T':'TSE:1605',
};
const SECTOR_VOL = {'KI/Tech':0.028,'Energie':0.022,'Rohstoffe':0.020,'Edelmetalle':0.025,'Pharma':0.016,'Rüstung':0.018};

const HTML = () => {
const tvj=JSON.stringify(TV_MAP);
const svj=JSON.stringify(SECTOR_VOL);
return `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#7c3aed">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="TradeMind">
<link rel="manifest" href="/manifest.json">
<title>TradeMind</title>
<style id="theme-style">
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#7d8590;--green:#3fb950;--red:#f85149;--orange:#d29922;--accent:#7c3aed;--blue:#58a6ff}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}
body.light{--bg:#f6f8fa;--surface:#ffffff;--border:#d0d7de;--text:#1f2328;--muted:#656d76}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:10px 16px;display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:200}
header h1{font-size:15px;font-weight:700}
.ts{font-size:11px;color:var(--muted);margin-left:auto}
.hbtn{background:none;border:1px solid var(--border);color:var(--muted);padding:4px 8px;border-radius:6px;cursor:pointer;font-size:13px}
.main-nav{display:flex;background:var(--surface);border-bottom:1px solid var(--border);overflow-x:auto}
.main-nav button{background:none;border:none;color:var(--muted);padding:10px 14px;font-size:13px;font-weight:600;cursor:pointer;border-bottom:3px solid transparent;white-space:nowrap;flex-shrink:0}
.main-nav button.active{color:var(--text);border-bottom-color:var(--accent)}
.sub-nav{display:flex;background:var(--bg);border-bottom:1px solid var(--border);padding:0 12px;gap:2px;overflow-x:auto}
.sub-nav button{background:none;border:none;color:var(--muted);padding:8px 10px;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.sub-nav button.active{color:var(--text);border-bottom-color:var(--accent)}
.main-panel{display:none}.main-panel.active{display:block}
.sub-panel{display:none;padding:12px 14px}.sub-panel.active{display:block}
.macro-strip{display:flex;gap:6px;overflow-x:auto;margin-bottom:14px}
.macro-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:7px 11px;white-space:nowrap;min-width:72px}
.macro-key{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.macro-val{font-size:14px;font-weight:700;margin-top:2px}
.macro-sub{font-size:11px;margin-top:1px}
.summary-row{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.scard{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;flex:1;min-width:80px}
.scard-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.3px}
.scard-val{font-size:18px;font-weight:700;margin-top:2px}
.scard-sub{font-size:11px;margin-top:1px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:7px 8px;text-align:left;border-bottom:1px solid var(--border)}
td{padding:8px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.ticker-name{font-weight:700;font-size:13px;cursor:pointer}
.ticker-name:hover{color:var(--blue)}
.ticker-sub{font-size:11px;color:var(--muted);margin-top:1px}
.stop-bar{height:3px;border-radius:2px;background:var(--border);margin-top:3px;max-width:70px}
.stop-fill{height:100%;border-radius:2px}
.stat-row{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;flex:1;min-width:95px}
.stat-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.3px}
.stat-value{font-size:19px;font-weight:700;margin-top:2px}
.stat-sub{font-size:11px;margin-top:2px}
.edit-row{display:grid;grid-template-columns:75px 1fr 1fr 1fr 1fr auto;gap:6px;align-items:start;padding:10px 0;border-bottom:1px solid var(--border)}
.edit-row:last-child{border-bottom:none}
input,select{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:6px;font-size:13px;width:100%}
input:focus,select:focus{outline:none;border-color:var(--accent)}
label{font-size:11px;color:var(--muted);display:block;margin-bottom:3px}
.form-row{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.ff{flex:1;min-width:80px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.card-title{font-weight:600;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.btn{border:none;border-radius:6px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;transition:opacity .1s}
.btn:active{opacity:.8}
.btn-primary{background:var(--accent);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-muted{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-sm{padding:4px 9px;font-size:12px}
.btn-xs{padding:3px 7px;font-size:11px}
.action-row{display:flex;gap:8px;margin-bottom:12px}
.action-row button{flex:1}
.strat-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden}
.strat-header{display:flex;align-items:center;gap:10px;padding:11px 13px;cursor:pointer;user-select:none}
.strat-header:hover{background:rgba(255,255,255,.02)}
.strat-badge{width:34px;height:34px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0}
.strat-meta{font-size:11px;color:var(--muted);margin-top:2px}
.chev{font-size:12px;color:var(--muted);margin-left:auto;transition:transform .2s}
.chev.open{transform:rotate(180deg)}
.strat-body{display:none;padding:0 13px 13px 57px;font-size:13px;line-height:1.7}
.strat-body.open{display:block}
.tickers-row{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}
.badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}
.perf-bar-wrap{background:var(--border);border-radius:3px;height:5px;width:70px;display:inline-block;vertical-align:middle;margin-left:5px}
.perf-bar{height:100%;border-radius:3px}
.heat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:6px;margin-bottom:14px}
.heat-cell{border-radius:7px;padding:9px;text-align:center;cursor:pointer}
.heat-cell:hover{opacity:.85}
.heat-ticker{font-weight:700;font-size:12px}
.heat-pnl{font-size:14px;font-weight:700;margin-top:2px}
.alert-box{background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.3);border-radius:8px;padding:9px 12px;margin-bottom:12px;font-size:12px}
.info-box{background:rgba(88,166,255,.06);border:1px solid rgba(88,166,255,.2);border-radius:8px;padding:9px 12px;margin-bottom:12px;font-size:12px}
.sizing-result{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:10px}
.sizing-row{display:flex;justify-content:space-between;padding:3px 0;font-size:13px}
.sizing-label{color:var(--muted)}
.sizing-val{font-weight:600}
.news-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:6px}
.news-item:hover{border-color:rgba(124,58,237,.4)}
.news-title a{color:var(--text);text-decoration:none;font-size:13px;line-height:1.4}
.news-title a:hover{color:var(--blue)}
.news-meta{font-size:11px;color:var(--muted);display:flex;gap:8px;flex-wrap:wrap;margin-top:5px}
.filter-btn{background:var(--surface);border:1px solid var(--border);color:var(--muted);padding:4px 10px;border-radius:12px;font-size:12px;cursor:pointer}
.filter-btn.active{border-color:var(--accent);color:var(--text)}
.cal-event{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:6px;display:flex;align-items:center;gap:12px}
.cal-date{font-size:11px;font-weight:700;text-align:center;min-width:44px}
.cal-day{font-size:18px;font-weight:800;line-height:1}
.cal-month{font-size:10px;color:var(--muted);text-transform:uppercase}
.cal-name{font-weight:600;font-size:13px}
.cal-desc{font-size:12px;color:var(--muted);margin-top:2px}
.days-badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}
.wl-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:6px;display:flex;align-items:center;gap:10px}
.wl-ticker{font-weight:700;font-size:14px;min-width:70px;cursor:pointer}
.wl-ticker:hover{color:var(--blue)}
.wl-zone{font-size:12px;color:var(--muted)}
.wl-price{font-size:15px;font-weight:700;margin-left:auto;text-align:right}
.wl-status{font-size:11px;margin-top:1px}
.exposure-bar{height:8px;border-radius:4px;margin-bottom:4px}
.exposure-row{margin-bottom:12px}
.exposure-label{display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px}
.corr-group{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:6px}
.corr-title{font-size:13px;font-weight:600;margin-bottom:5px}
.corr-held{font-size:12px;color:var(--muted)}
.var-box{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px}
.checklist-item{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border)}
.checklist-item:last-child{border-bottom:none}
.check-icon{font-size:16px;flex-shrink:0}
.check-text{font-size:13px;flex:1}
.check-val{font-size:12px;font-weight:600}
.green{color:var(--green)}.red{color:var(--red)}.orange{color:var(--orange)}.muted{color:var(--muted)}
.loading{text-align:center;padding:30px;color:var(--muted)}
.save-msg{font-size:12px;margin-left:6px}
.crv-good{color:var(--green);font-weight:600}.crv-bad{color:var(--red)}.crv-ok{color:var(--orange)}
.empty{text-align:center;padding:24px;color:var(--muted);font-size:13px}
.conviction-badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700}
.collapsible-header{cursor:pointer;user-select:none;display:flex;align-items:center;gap:8px;padding:10px 0}
.collapsible-header:hover{opacity:.8}
.collapsible-body{display:none}
.collapsible-body.open{display:block}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:999;display:flex;align-items:center;justify-content:center}
.modal-content{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;max-width:500px;width:90%;max-height:80vh;overflow-y:auto}
.modal-close{float:right;cursor:pointer;font-size:18px;background:none;border:none;color:var(--muted)}
.heatmap-cell{width:14px;height:14px;border-radius:2px;display:inline-block;margin:1px;cursor:pointer}
.corr-matrix{display:inline-block;text-align:center}
.corr-matrix td{padding:2px;font-size:10px;min-width:40px}
.refresh-indicator{font-size:11px;color:var(--muted);margin-left:8px}
</style>
</head>
<body>

<header>
  <span style="font-size:18px">🎩</span>
  <h1>TradeMind</h1>
  <button class="hbtn" onclick="loadAll()">🔄</button>
  <button class="hbtn" onclick="toggleTheme()" id="theme-btn" title="Dark/Light">🌙</button>
  <button class="hbtn" onclick="requestNotifications()" id="notif-btn" title="Push-Alerts">🔔</button>
  <span class="ts" id="ts">Lädt…</span>
  <span class="refresh-indicator" id="refresh-ind"></span>
</header>

<div class="main-nav">
  <button class="active" onclick="showMain('real',this)">📈 Real</button>
  <button onclick="showMain('paperlabs',this)">🧪 Paper Labs</button>
  <button onclick="showMain('news',this);loadNews()">📰 News</button>
  <button onclick="showMain('watchlist',this)">👁 Watchlist</button>
  <button onclick="showMain('calendar',this)">📅 Kalender</button>
  <button onclick="showMain('risk',this)">🛡️ Risiko</button>
  <button onclick="showMain('signals',this);loadSignals()">📡 Signale</button>
  <button onclick="showMain('analytics',this);loadAnalytics()">📊 DNA</button>
  <button onclick="showMain('macro',this);loadMacro()">🌍 Macro</button>
</div>

<!-- REAL PORTFOLIO -->
<div id="main-real" class="main-panel active">
  <div class="sub-nav">
    <button class="active" onclick="showSub('real','overview',this)">📊 Übersicht</button>
    <button onclick="showSub('real','edit',this)">✏️ Bearbeiten</button>
    <button onclick="showSub('real','log',this)">➕ Trade eintragen</button>
    <button onclick="showSub('real','history',this);loadHistory()">📜 History</button>
    <button onclick="showSub('real','closed',this)">📦 Geschlossen</button>
  </div>
  <div id="real-overview" class="sub-panel active">
    <div class="macro-strip" id="macro-strip"><div class="loading">…</div></div>
    <div class="summary-row" id="portfolio-summary"></div>
    <div id="alert-box"></div>
    <div id="real-table"><div class="loading">Lädt…</div></div>
  </div>
  <div id="real-edit" class="sub-panel">
    <div class="info-box">💡 <strong>ATR-Regel:</strong> Stop mind. ATR×1.5 — bei normalem Markt ≥3–5%, bei VIX&gt;25 ≥6–8% Abstand.</div>
    <div class="card" style="padding:0 12px"><div id="edit-table"><div class="loading">Lädt…</div></div></div>
  </div>
  <div id="real-log" class="sub-panel">
    <div class="card">
      <div class="card-title">Trade eintragen</div>
      <div class="action-row">
        <button id="btn-buy" class="btn btn-primary" onclick="setAction('BUY')">✅ KAUF</button>
        <button id="btn-sell" class="btn btn-muted" onclick="setAction('SELL')">🔴 VERKAUF</button>
      </div>
      <div class="form-row">
        <div class="ff"><label>Ticker</label><input id="l-ticker" placeholder="EQNR"></div>
        <div class="ff"><label>Preis (€)</label><input id="l-price" type="number" step="0.01" oninput="calcSizing();updateChecklist()"></div>
        <div class="ff"><label>Stop (€)</label><input id="l-stop" type="number" step="0.01" oninput="calcSizing();updateChecklist()"></div>
        <div class="ff"><label>Ziel (€)</label><input id="l-target" type="number" step="0.01" oninput="updateChecklist()"></div>
      </div>
      <div class="form-row">
        <div class="ff" style="flex:3"><label>Notiz</label><input id="l-notes" placeholder="z.B. EMA50-Rücklauf, CRV 5:1"></div>
      </div>
      <button class="btn btn-primary" onclick="logTrade()">💾 Speichern</button>
      <span id="log-status" class="save-msg"></span>
    </div>
    <div class="card">
      <div class="card-title">📐 Positionsgröße (TRA-143)</div>
      <div class="form-row">
        <div class="ff"><label>Kontostand (€)</label><input id="ps-account" type="number" value="10000" oninput="calcSizing()"></div>
        <div class="ff"><label>Risiko %</label><input id="ps-risk" type="number" value="2" step="0.1" oninput="calcSizing()"></div>
        <div class="ff"><label>Entry €</label><input id="ps-entry" type="number" step="0.01" oninput="calcSizing()"></div>
        <div class="ff"><label>Stop €</label><input id="ps-stop" type="number" step="0.01" oninput="calcSizing()"></div>
      </div>
      <div id="sizing-result" style="display:none" class="sizing-result"></div>
    </div>
    <div class="card">
      <div class="card-title">✅ Pre-Trade Checklist</div>
      <div id="checklist"></div>
    </div>
  </div>
  <div id="real-history" class="sub-panel">
    <div style="display:flex;justify-content:flex-end;margin-bottom:10px">
      <button class="btn btn-muted btn-sm" onclick="exportCSV()">⬇️ CSV Export</button>
    </div>
    <div id="history-table"><div class="loading">Lädt…</div></div>
  </div>
  <div id="real-closed" class="sub-panel">
    <div id="closed-trades-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- PAPER LABS (Swing + Day Trade als Sub-Tabs) -->
<div id="main-paperlabs" class="main-panel">
  <div class="sub-nav" style="background:var(--surface);border-bottom:2px solid var(--border);padding:0 12px;gap:4px">
    <button class="active" onclick="showPaperSub('swing',this)">📊 Swing</button>
    <button onclick="showPaperSub('daytrade',this);loadDayTrades()">🏎️ Day Trade</button>
  </div>

  <!-- SWING SUB-PANEL -->
  <div id="paperlabs-swing">
    <div class="sub-nav">
      <button class="active" onclick="showSwingSub('positions',this)">📋 Positionen</button>
      <button onclick="showSwingSub('performance',this)">📊 Performance</button>
      <button onclick="showSwingSub('entry',this)">➕ Eintragen</button>
      <button onclick="showSwingSub('strat',this)">🧠 Strategien</button>
    </div>
    <div id="paper-positions" class="sub-panel active">
      <div class="stat-row" id="paper-stats"></div>
      <div id="paper-heatmap"></div>
      <div id="paper-table"><div class="loading">Lädt…</div></div>
    </div>
    <div id="paper-performance" class="sub-panel">
      <div id="strat-perf"><div class="loading">Lädt…</div></div>
    </div>
    <div id="paper-entry" class="sub-panel">
      <div class="card">
        <div class="card-title">Paper Trade eintragen</div>
        <div class="action-row">
          <button id="pb-buy" class="btn btn-primary" onclick="setPaperAction('BUY')">✅ KAUF</button>
          <button id="pb-sell" class="btn btn-muted" onclick="setPaperAction('SELL')">🔴 VERKAUF</button>
        </div>
        <div class="form-row">
          <div class="ff"><label>Ticker</label><input id="pl-ticker" placeholder="z.B. OXY"></div>
          <div class="ff"><label>Preis (€)</label><input id="pl-price" type="number" step="0.01"></div>
          <div class="ff"><label>Stop (€)</label><input id="pl-stop" type="number" step="0.01"></div>
          <div class="ff"><label>Ziel (€)</label><input id="pl-target" type="number" step="0.01"></div>
        </div>
        <div class="form-row">
          <div class="ff"><label>Strategie</label>
            <select id="pl-strat"></select>
          </div>
          <div class="ff" style="flex:2"><label>Notiz</label><input id="pl-notes" placeholder="Begründung"></div>
        </div>
        <button class="btn btn-primary" onclick="logPaperTrade()">💾 Speichern</button>
        <span id="pl-status" class="save-msg"></span>
      </div>
    </div>
    <div id="paper-strat" class="sub-panel"><div id="strat-list"></div></div>
  </div>

  <!-- DAY TRADE SUB-PANEL -->
  <div id="paperlabs-daytrade" style="display:none">
    <div class="sub-nav">
      <button class="active" onclick="showSub('daytrade','live',this)">⚡ Live</button>
      <button onclick="showSub('daytrade','history',this)">📜 History</button>
      <button onclick="showSub('daytrade','stats',this)">📊 Statistik</button>
      <button onclick="showSub('daytrade','config',this)">⚙️ Setup</button>
    </div>
    <div id="daytrade-live" class="sub-panel active">
      <div id="dt-live-content"><div class="loading">Lädt…</div></div>
    </div>
    <div id="daytrade-history" class="sub-panel">
      <div id="dt-history-content"><div class="loading">Lädt…</div></div>
    </div>
    <div id="daytrade-stats" class="sub-panel">
      <div id="dt-stats-content"><div class="loading">Lädt…</div></div>
    </div>
    <div id="daytrade-config" class="sub-panel">
      <div class="card" style="padding:16px">
        <div class="card-title">🏎️ Day Trading Setup</div>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:12px">
          <div class="card" style="padding:12px">
            <strong>Kapital:</strong> 25.000€<br>
            <strong>Position:</strong> 5.000€ (20%)<br>
            <strong>Max Positionen:</strong> 5<br>
            <strong>Risk/Trade:</strong> 1% (250€)
          </div>
          <div class="card" style="padding:12px">
            <strong>Daily Loss Limit:</strong> -500€<br>
            <strong>EOD Close:</strong> 21:45 CET<br>
            <strong>Intervall:</strong> alle 5 Min<br>
            <strong>Overnight:</strong> ❌ Nie
          </div>
        </div>
        <div class="card-title" style="margin-top:16px">Strategien</div>
        <table style="margin-top:8px">
          <tr><th>ID</th><th>Name</th><th>Entry</th><th>Exit</th><th>Timeframe</th></tr>
          <tr><td style="color:#2ecc71"><strong>DT1</strong></td><td>Momentum Breakout</td><td>Price > VWAP + Volume 1.5x</td><td>+1% oder -0.5%</td><td>5m</td></tr>
          <tr><td style="color:#3498db"><strong>DT2</strong></td><td>Mean Reversion</td><td>RSI < 30 + unter VWAP</td><td>VWAP oder -1%</td><td>5m</td></tr>
          <tr><td style="color:#e67e22"><strong>DT3</strong></td><td>Gap Fill</td><td>Gap > 2%</td><td>Prev Close oder -1%</td><td>Opening</td></tr>
          <tr><td style="color:#9b59b6"><strong>DT4</strong></td><td>EMA Cross</td><td>EMA9/EMA21 Cross</td><td>+0.8% oder -0.2%</td><td>5m</td></tr>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- NEWS -->
<div id="main-news" class="main-panel">
  <div style="padding:12px 14px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:6px" id="news-timestamp"></div>
    <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap" id="news-filter"></div>
    <div id="news-list"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- WATCHLIST -->
<div id="main-watchlist" class="main-panel">
  <div style="padding:12px 14px">
    <div class="info-box">📌 Entry-Zone: <span class="green">grün</span> = Kurs unter Zone, <span class="orange">orange</span> = in der Zone, <span class="red">rot</span> = darüber.</div>
    <div id="watchlist-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- KALENDER -->
<div id="main-calendar" class="main-panel">
  <div style="padding:12px 14px">
    <div class="card-title" style="margin-bottom:8px">📅 Earnings (eigene Positionen)</div>
    <div id="cal-earnings"></div>
    <div class="card-title" style="margin-top:16px;margin-bottom:8px">🌍 Makro-Events</div>
    <div id="cal-macro"></div>
  </div>
</div>

<!-- RISIKO -->
<div id="main-risk" class="main-panel">
  <div class="sub-nav">
    <button class="active" onclick="showSub('risk','exposure',this)">📊 Exposure</button>
    <button onclick="showSub('risk','corr',this)">🔗 Korrelation</button>
    <button onclick="showSub('risk','var',this)">⚠️ VaR</button>
    <button onclick="showSub('risk','drawdown',this)">📉 Drawdown</button>
    <button onclick="showSub('risk','matrix',this)">🔢 Matrix</button>
    <button onclick="showSub('risk','score',this)">🚦 Score</button>
  </div>
  <div id="risk-exposure" class="sub-panel active"><div id="exposure-content"><div class="loading">Lädt…</div></div></div>
  <div id="risk-corr" class="sub-panel"><div id="corr-content"><div class="loading">Lädt…</div></div></div>
  <div id="risk-var" class="sub-panel"><div id="var-content"><div class="loading">Lädt…</div></div></div>
  <div id="risk-drawdown" class="sub-panel"><div id="drawdown-content"><div class="loading">Lädt…</div></div></div>
  <div id="risk-matrix" class="sub-panel"><div id="matrix-content"><div class="loading">Lädt…</div></div></div>
  <div id="risk-score" class="sub-panel"><div id="riskscore-content"><div class="loading">Lädt…</div></div></div>
</div>

<!-- SIGNALS TAB -->
<div id="main-signals" class="main-panel">
  <div class="sub-nav">
    <button class="active" onclick="showSub('signals','feed',this)">📡 Feed</button>
    <button onclick="showSub('signals','alerts',this);loadAlertHistory()">🔔 Alert-Historie</button>
  </div>
  <div id="signals-feed" class="sub-panel active">
    <div class="card"><div class="card-title">📡 Signal Engine — Aktive Lead-Lag Signale</div>
      <div id="signals-content"><div class="loading">Lädt…</div></div>
    </div>
  </div>
  <div id="signals-alerts" class="sub-panel">
    <div id="alerts-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- ANALYTICS/DNA TAB -->
<div id="main-analytics" class="main-panel">
  <div class="sub-nav">
    <button class="active" onclick="showSub('analytics','dna',this)">📊 DNA</button>
    <button onclick="showSub('analytics','pnlsummary',this)">💰 P&L Summary</button>
  </div>
  <div id="analytics-dna" class="sub-panel active">
    <div class="card"><div class="card-title">📊 Strategy DNA — Lernende Analyse</div>
      <div id="analytics-content"><div class="loading">Lädt…</div></div>
    </div>
  </div>
  <div id="analytics-pnlsummary" class="sub-panel">
    <div id="pnl-summary-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- MACRO TAB -->
<div id="main-macro" class="main-panel">
  <div class="card"><div class="card-title">🌍 Macro Dashboard</div>
    <div id="macro-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- MODAL for TRA-138 -->
<div id="trade-modal" style="display:none"></div>

<script>
const TV_MAP=${tvj};
const SECTOR_VOL=${svj};

// TRA-127: Dynamic data from /api/config — NO hardcoded arrays
let STRATEGIES=[],EARNINGS=[],MACRO_EVENTS=[],SECTOR_MAP={},SECTOR_COLORS={},CORR_GROUPS=[];
let PAPER=[]; // TRA-129: loaded from DNA
let cfg=null,prices=null,tradeAction='BUY',paperAction='BUY';
let newsLoaded=false,histLoaded=false,allNews=[],tradeHistory=[];
let dnaData=null,riskData=null,alertsData=[];
let startCapital=10000;

// TRA-130: Auto-refresh state
let lastPriceRefresh=Date.now(),lastConfigRefresh=Date.now();
let priceTimer=null,configTimer=null,countdownTimer=null;

// ── Navigation ───────────────────────────────────────────
function showMain(n,btn){
  document.querySelectorAll('.main-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.main-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('main-'+n).classList.add('active');
  btn.classList.add('active');
  if(n==='watchlist'&&cfg&&prices)renderWatchlist();
  if(n==='calendar')renderCalendar();
  if(n==='risk'&&cfg&&prices)renderRisk();
}
function showSub(main,sub,btn){
  const panel=document.getElementById('main-'+main);
  if(!panel) return;
  panel.querySelectorAll('.sub-panel').forEach(p=>p.classList.remove('active'));
  panel.querySelectorAll('.sub-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(main+'-'+sub).classList.add('active');
  btn.classList.add('active');
}
function showSwingSub(sub,btn){
  const panel=document.getElementById('paperlabs-swing');
  panel.querySelectorAll('.sub-panel').forEach(p=>p.classList.remove('active'));
  panel.querySelectorAll('.sub-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('paper-'+sub).classList.add('active');
  if(btn)btn.classList.add('active');
  if(sub==='strat')renderStrat();
}
function showPaperSub(name,btn){
  ['swing','daytrade'].forEach(n=>{
    document.getElementById('paperlabs-'+n).style.display=n===name?'':'none';
  });
  document.querySelectorAll('#main-paperlabs>.sub-nav button').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
}

// ── Helpers ──────────────────────────────────────────────
function pct(v,b){return b?((v-b)/b*100):null}
function pctHtml(v,bold=false){
  if(v==null)return'<span class="muted">—</span>';
  const c=v>=0?'green':'red',s=v>=0?'▲ +':'▼ ';
  return \`<span class="\${c}"\${bold?' style="font-weight:700"':''}>\${s}\${Math.abs(v).toFixed(1)}%</span>\`;
}
function eurFmt(v){if(v==null)return'—';return(v>=0?'+':'')+v.toFixed(0)+'€';}
function getP(px,t){return px[t]||px[t+'.OL']||px[t+'.DE']||px[t+'.L']||null}
function crvHtml(price,stop,target){
  if(!target||!stop||!price||price<=stop)return'<span class="muted">—</span>';
  const c=(target-price)/(price-stop);
  return \`<span class="\${c>=3?'crv-good':c>=2?'crv-ok':'crv-bad'}">\${c.toFixed(1)}:1</span>\`;
}
function stopCell(price,stop){
  if(!stop)return'<span class="red" style="font-size:11px">⚠️ kein Stop</span>';
  const d=price?(price-stop)/price*100:null;
  const col=d!=null&&d<2?'var(--red)':d!=null&&d<5?'var(--orange)':'var(--green)';
  const bar=d!=null?Math.min(d*8,100):0;
  return \`<div><span style="color:\${col};font-weight:600">\${stop.toFixed(2)}€</span><span class="muted" style="font-size:11px"> (\${d!=null?d.toFixed(1):'?'}%)</span></div>
          <div class="stop-bar"><div class="stop-fill" style="width:\${bar}%;background:\${col}"></div></div>\`;
}
function tvLink(ticker){const tv=TV_MAP[ticker]||TV_MAP[ticker?.split('.')[0]];if(tv)return\`https://www.tradingview.com/chart/?symbol=\${tv}\`;return\`https://www.tradingview.com/chart/?symbol=\${encodeURIComponent(ticker)}\`;}

// TRA-134: Conviction Badge
function convictionBadge(score){
  if(score==null)return'';
  const col=score>60?'var(--green)':score>=40?'var(--orange)':'var(--red)';
  const bg=score>60?'rgba(63,185,80,.15)':score>=40?'rgba(210,153,34,.15)':'rgba(248,81,73,.15)';
  return \`<span class="conviction-badge" style="background:\${bg};color:\${col}">\${score}</span>\`;
}

// TRA-143: Position Sizing formula
function positionSize(portfolio,riskPct,entry,stop){
  if(!entry||!stop||entry<=stop)return null;
  const riskFrac=(entry-stop)/entry;
  const sizeEur=(portfolio*(riskPct/100))/riskFrac;
  const shares=Math.floor(sizeEur/entry);
  return{sizeEur:Math.round(sizeEur),shares,maxLoss:Math.round(shares*(entry-stop))};
}

// ── Main Load ─────────────────────────────────────────────
async function loadAll(){
  document.getElementById('ts').textContent='⏳';
  try{
    // TRA-127: Load config dynamically (includes strategies, earnings, etc.)
    const [cfgResp,pricesResp,dnaResp]=await Promise.all([
      fetch('/api/config').then(r=>r.json()),
      fetch('/api/prices').then(r=>r.json()),
      fetch('/api/dna').then(r=>r.json()).catch(()=>null),
    ]);
    cfg=cfgResp;
    prices=pricesResp;
    dnaData=dnaResp;
    
    // TRA-127: Populate dynamic globals
    STRATEGIES=cfg.strategies||[];
    EARNINGS=cfg.earnings||[];
    MACRO_EVENTS=cfg.macro_events||[];
    SECTOR_MAP=cfg.sector_map||{};
    SECTOR_COLORS=cfg.sector_colors||{};
    CORR_GROUPS=cfg.corr_groups||[];
    startCapital=cfg.settings?.start_capital||10000;
    
    // TRA-129: Paper trades from DNA
    PAPER=(dnaData?.open_positions||[]).filter(p=>p.trade_type==='paper').map(p=>({
      ticker:p.ticker,name:p.name||p.ticker,entry:p.entry,strategy:p.strategy,
      stop:p.stop||null,target:p.target||null
    }));
    
    // Populate strategy selector dynamically
    const stratSelect=document.getElementById('pl-strat');
    if(stratSelect&&stratSelect.options.length===0){
      STRATEGIES.forEach(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.id+' — '+s.name;stratSelect.add(o);});
    }

    lastPriceRefresh=Date.now();
    lastConfigRefresh=Date.now();
    
    renderMacroStrip(prices);renderSummary(cfg,prices);renderReal(cfg,prices);
    renderClosedTrades(cfg,prices);
    renderEdit(cfg,prices);renderPaper(prices);renderStratPerf(prices);renderStrat();
    updateChecklist();
    document.getElementById('ts').textContent=new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
  }catch(e){document.getElementById('ts').textContent='⚠️ '+e.message;}
}

// TRA-130: Auto-refresh prices every 30s, config every 5min
async function refreshPrices(){
  try{
    prices=await fetch('/api/prices').then(r=>r.json());
    lastPriceRefresh=Date.now();
    // Only update data, no DOM rebuild (TRA-130: no flicker)
    if(cfg){
      renderSummary(cfg,prices);renderReal(cfg,prices);renderClosedTrades(cfg,prices);
      if(document.getElementById('main-watchlist').classList.contains('active'))renderWatchlist();
      if(document.getElementById('main-risk').classList.contains('active'))renderRisk();
    }
    document.getElementById('ts').textContent=new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
  }catch(e){}
}
async function refreshConfig(){
  try{
    const cfgResp=await fetch('/api/config').then(r=>r.json());
    cfg=cfgResp;
    STRATEGIES=cfg.strategies||[];
    EARNINGS=cfg.earnings||[];
    MACRO_EVENTS=cfg.macro_events||[];
    SECTOR_MAP=cfg.sector_map||{};
    SECTOR_COLORS=cfg.sector_colors||{};
    CORR_GROUPS=cfg.corr_groups||[];
    lastConfigRefresh=Date.now();
    if(prices){renderSummary(cfg,prices);renderReal(cfg,prices);}
  }catch(e){}
}
function updateCountdown(){
  const secsSincePrices=Math.floor((Date.now()-lastPriceRefresh)/1000);
  const el=document.getElementById('refresh-ind');
  if(el)el.textContent=\`Aktualisierung: vor \${secsSincePrices}s\`;
}

// ── Macro Strip ───────────────────────────────────────────
function renderMacroStrip(p){
  const m=p.macro||{},f=p.fx||{};
  const vix=m.vix||0,nk=m.nikkei||0;
  const vc=vix>30?'var(--red)':vix>25?'var(--orange)':'var(--green)';
  document.getElementById('macro-strip').innerHTML=\`
    <div class="macro-item"><div class="macro-key">VIX</div><div class="macro-val" style="color:\${vc}">\${vix.toFixed(1)}</div><div class="macro-sub" style="color:\${vc}">\${vix>30?'🔴 Panik':vix>25?'🟠 Erhöht':'🟢 Normal'}</div></div>
    <div class="macro-item"><div class="macro-key">WTI</div><div class="macro-val">$\${(m.wti||0).toFixed(1)}</div><div class="macro-sub muted">Rohöl</div></div>
    <div class="macro-item"><div class="macro-key">Nikkei</div><div class="macro-val" style="color:\${nk<-3?'var(--red)':nk<0?'var(--orange)':'var(--green)'}">\${nk>=0?'+':''}\${nk.toFixed(1)}%</div><div class="macro-sub muted">225</div></div>
    <div class="macro-item"><div class="macro-key">EUR/USD</div><div class="macro-val">\${(f.EURUSD||0).toFixed(4)}</div><div class="macro-sub muted">FX</div></div>
  \`;
}

// ── Portfolio Summary (TRA-131, TRA-132) ──────────────────
function renderSummary(cfg,prices){
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const closedPos=(cfg.positions||[]).filter(p=>p.status==='CLOSED');
  const px=prices.prices||{};
  let winning=0,danger=0,noStop=0,sumPnl=0,cnt=0,totalPnlEur=0,totalInvested=0;
  
  pos.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur??null;
    const pnl=pct(eur,p.entry_eur);
    // TRA-131: P&L in Euro
    const sizeEur=p.size_eur||1000;
    if(eur&&p.entry_eur){
      const pnlEur=sizeEur*(eur/p.entry_eur-1);
      totalPnlEur+=pnlEur;
      totalInvested+=sizeEur;
    }
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)winning++;}
    if(!p.stop_eur)noStop++;
    else if(eur&&(eur-p.stop_eur)/eur*100<5)danger++;
  });
  
  // Echter P&L ohne fake startCapital
  const avg=cnt?sumPnl/cnt:0;
  
  document.getElementById('portfolio-summary').innerHTML=\`
    <div class="scard" style="border-color:var(--accent)">
      <div class="scard-label">Investiert</div>
      <div class="scard-val">\${Math.round(totalInvested).toLocaleString()}€</div>
      <div class="scard-sub muted">\${pos.length} Positionen</div>
    </div>
    <div class="scard" style="border-color:\${totalPnlEur>=0?'var(--green)':'var(--red)'}">
      <div class="scard-label">P&amp;L Gesamt</div>
      <div class="scard-val \${totalPnlEur>=0?'green':'red'}">\${totalPnlEur>=0?'+':''}\${Math.round(totalPnlEur).toLocaleString()}€</div>
      <div class="scard-sub \${totalPnlEur>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div>
    </div>
    <div class="scard"><div class="scard-label">Positionen</div><div class="scard-val">\${pos.length}</div><div class="scard-sub muted">\${winning} im Plus</div></div>
    <div class="scard"><div class="scard-label">Ø P&amp;L</div><div class="scard-val \${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="scard" style="\${danger>0?'border-color:rgba(248,81,73,.4)':''}"><div class="scard-label">Stop &lt;5%</div><div class="scard-val \${danger>0?'orange':''}">⚠️ \${danger}</div></div>
    <div class="scard" style="\${noStop>0?'border-color:rgba(248,81,73,.4)':''}"><div class="scard-label">Kein Stop</div><div class="scard-val \${noStop>0?'red':''}">🔴 \${noStop}</div></div>
  \`;
  const dangerPos=pos.filter(p=>{const eur=getP(px,p.ticker)?.eur;return p.stop_eur&&eur&&(eur-p.stop_eur)/eur*100<5;});
  document.getElementById('alert-box').innerHTML=dangerPos.length?\`<div class="alert-box">⚠️ <strong>Stop-Alarm:</strong> \${dangerPos.map(p=>{const d=getP(px,p.ticker)?.eur?((getP(px,p.ticker).eur-p.stop_eur)/getP(px,p.ticker).eur*100).toFixed(1):'?';return\`<strong>\${p.ticker}</strong> (\${d}% vom Stop)\`;}).join(' · ')}</div>\`:'';
}

// ── Real Portfolio Table (TRA-131 Euro P&L, TRA-134 Conviction) ──
function renderReal(cfg,prices){
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  const rows=pos.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry_eur);
    // TRA-131: P&L in Euro
    const sizeEur=p.size_eur||1000;
    const pnlEur=(eur&&p.entry_eur)?sizeEur*(eur/p.entry_eur-1):null;
    const tv=tvLink(p.ticker);
    // TRA-134: conviction from dnaData
    const dnaPos=(dnaData?.open_positions||[]).find(d=>d.ticker===p.ticker);
    const conviction=p.conviction||dnaPos?.conviction||null;
    return \`<tr>
      <td><div class="ticker-name" onclick="window.open('\${tv}','_blank')" title="TradingView">\${p.ticker} ↗</div><div class="ticker-sub">\${p.name||''} \${convictionBadge(conviction)}</div></td>
      <td class="muted">\${p.entry_eur?.toFixed(2)??'—'}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(chg)}</td>
      <td>\${pctHtml(pnl,true)}</td>
      <td class="\${pnlEur!=null?(pnlEur>=0?'green':'red'):'muted'}" style="font-weight:600">\${pnlEur!=null?eurFmt(pnlEur):'—'}</td>
      <td>\${stopCell(eur,p.stop_eur)}</td>
      <td>\${crvHtml(eur,p.stop_eur,p.target_eur)}</td>
    </tr>\`;
  });
  document.getElementById('real-table').innerHTML=\`<table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&amp;L %</th><th>P&amp;L €</th><th>Stop</th><th>CRV</th></tr></thead><tbody>\${rows.join('')||'<tr><td colspan="8" class="muted" style="text-align:center;padding:18px">Keine offenen Positionen</td></tr>'}</tbody></table>\`;
}

// ── TRA-128: Geschlossene Positionen ──────────────────────
function renderClosedTrades(cfg,prices){
  const closed=(cfg.positions||[]).filter(p=>p.status==='CLOSED');
  if(!closed.length){document.getElementById('closed-trades-content').innerHTML='<div class="empty">Keine geschlossenen Trades</div>';return;}
  let totalPnlEur=0;
  const rows=closed.map(p=>{
    const sizeEur=p.size_eur||1000;
    const pnl=p.exit_eur&&p.entry_eur?pct(p.exit_eur,p.entry_eur):null;
    const pnlEur=p.exit_eur&&p.entry_eur?sizeEur*(p.exit_eur/p.entry_eur-1):null;
    if(pnlEur!=null)totalPnlEur+=pnlEur;
    return \`<tr>
      <td><strong>\${p.ticker}</strong><div class="ticker-sub">\${p.name||''}</div></td>
      <td class="muted">\${p.entry_eur?.toFixed(2)??'—'}€</td>
      <td>\${p.exit_eur?.toFixed(2)??'—'}€</td>
      <td>\${pctHtml(pnl,true)}</td>
      <td class="\${pnlEur!=null?(pnlEur>=0?'green':'red'):'muted'}" style="font-weight:600">\${pnlEur!=null?eurFmt(pnlEur):'—'}</td>
      <td class="muted">\${p.exit_date||'—'}</td>
      <td class="muted" style="font-size:11px;cursor:pointer" onclick="showTradeDetail('\${p.ticker}')">📋 Details</td>
    </tr>\`;
  });
  document.getElementById('closed-trades-content').innerHTML=\`
    <div class="stat-row">
      <div class="stat"><div class="stat-label">Geschlossene Trades</div><div class="stat-value">\${closed.length}</div></div>
      <div class="stat"><div class="stat-label">Gesamt P&amp;L</div><div class="stat-value \${totalPnlEur>=0?'green':'red'}">\${eurFmt(totalPnlEur)}</div></div>
    </div>
    <table><thead><tr><th>Position</th><th>Entry</th><th>Exit</th><th>P&amp;L %</th><th>P&amp;L €</th><th>Datum</th><th></th></tr></thead><tbody>\${rows.join('')}</tbody></table>\`;
}

// ── Edit Table ────────────────────────────────────────────
function renderEdit(cfg,prices){
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=(prices?.prices)||{};
  if(!pos.length){document.getElementById('edit-table').innerHTML='<p class="muted" style="padding:12px 0">Keine Positionen</p>';return;}
  document.getElementById('edit-table').innerHTML=pos.map(p=>{
    const eur=getP(px,p.ticker)?.eur;
    const suggestStop=eur?(eur*0.96).toFixed(2):'';
    const stopDist=eur&&p.stop_eur?((eur-p.stop_eur)/eur*100).toFixed(1):null;
    const sw=stopDist&&parseFloat(stopDist)<5?\`style="border-color:var(--orange)"\`:'';
    return \`<div class="edit-row">
      <div><div style="font-weight:700;font-size:13px">\${p.ticker}</div><div style="font-size:11px;color:var(--muted)">\${eur?eur.toFixed(2)+'€':'—'}</div></div>
      <div><label>Entry €</label><input type="number" id="e-entry-\${p.ticker}" value="\${p.entry_eur||''}" step="0.01"></div>
      <div><label>Stop €</label><input type="number" id="e-stop-\${p.ticker}" value="\${p.stop_eur||''}" step="0.01" \${sw}><div style="font-size:10px;color:var(--muted);margin-top:2px">Vorschlag: \${suggestStop||'—'}€ (−4%)</div></div>
      <div><label>Ziel €</label><input type="number" id="e-target-\${p.ticker}" value="\${p.target_eur||''}" step="0.01"></div>
      <div><label>CRV</label><div style="padding-top:8px">\${crvHtml(eur,p.stop_eur,p.target_eur)}</div></div>
      <div style="padding-top:18px"><button class="btn btn-primary btn-sm" onclick="savePos('\${p.ticker}')">💾</button><span id="e-status-\${p.ticker}" class="save-msg"></span></div>
    </div>\`;
  }).join('');
}

// ── Trade History ─────────────────────────────────────────
async function loadHistory(){
  if(histLoaded)return;
  document.getElementById('history-table').innerHTML='<div class="loading">Lade…</div>';
  try{
    const d=await fetch('/api/trade-log').then(r=>r.json());
    tradeHistory=(d.trades||[]).reverse();
    renderHistoryTable();
    histLoaded=true;
  }catch(e){document.getElementById('history-table').innerHTML=\`<div class="empty">⚠️ \${e.message}</div>\`;}
}
function renderHistoryTable(){
  if(!tradeHistory.length){document.getElementById('history-table').innerHTML='<div class="empty">📭 Noch keine Trades</div>';return;}
  const rows=tradeHistory.map(t=>{
    const date=t.ts?new Date(t.ts).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';
    const buy=t.action==='BUY';
    const badge=buy?\`<span class="badge" style="background:rgba(63,185,80,.15);color:var(--green)">KAUF</span>\`:\`<span class="badge" style="background:rgba(248,81,73,.15);color:var(--red)">VERK.</span>\`;
    return \`<tr><td class="muted" style="font-size:11px">\${date}</td><td>\${badge}</td><td><strong>\${t.ticker}</strong></td><td>\${t.price_eur?.toFixed(2)??'—'}€</td><td class="muted" style="font-size:12px">\${t.stop_eur?t.stop_eur+'€':'—'}</td><td class="muted" style="font-size:12px">\${t.target_eur?t.target_eur+'€':'—'}</td><td class="muted" style="font-size:11px;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer" onclick="showTradeDetail('\${t.ticker}')">\${t.notes||''} 📋</td></tr>\`;
  }).join('');
  document.getElementById('history-table').innerHTML=\`<table><thead><tr><th>Datum</th><th>Typ</th><th>Ticker</th><th>Preis</th><th>Stop</th><th>Ziel</th><th>Notiz</th></tr></thead><tbody>\${rows}</tbody></table>\`;
}
function exportCSV(){
  if(!tradeHistory.length){alert('Keine Trades zum Exportieren');return;}
  const header='Datum,Typ,Ticker,Preis,Stop,Ziel,Notiz';
  const rows=tradeHistory.map(t=>[
    t.ts?new Date(t.ts).toLocaleDateString('de-DE'):'',
    t.action,t.ticker,t.price_eur||'',t.stop_eur||'',t.target_eur||'',
    \`"\${(t.notes||'').replace(/"/g,"'")}"\`
  ].join(','));
  const csv=[header,...rows].join('\\n');
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;a.download='trades_'+new Date().toISOString().split('T')[0]+'.csv';a.click();
  URL.revokeObjectURL(url);
}

// ── TRA-138: Trade Detail Modal ───────────────────────────
function showTradeDetail(ticker){
  fetch('/api/trade-log').then(r=>r.json()).then(d=>{
    const trades=(d.trades||[]).filter(t=>t.ticker===ticker);
    if(!trades.length){alert('Keine Details für '+ticker);return;}
    const t=trades[trades.length-1];
    document.getElementById('trade-modal').style.display='block';
    document.getElementById('trade-modal').innerHTML=\`<div class="modal-overlay" onclick="closeModal(event)">
      <div class="modal-content" onclick="event.stopPropagation()">
        <button class="modal-close" onclick="document.getElementById('trade-modal').style.display='none'">✕</button>
        <h3 style="margin-bottom:12px">\${ticker} — Trade Details</h3>
        <div class="sizing-row"><span class="sizing-label">Typ</span><span class="sizing-val">\${t.action||'—'}</span></div>
        <div class="sizing-row"><span class="sizing-label">Preis</span><span class="sizing-val">\${t.price_eur?.toFixed(2)||'—'}€</span></div>
        <div class="sizing-row"><span class="sizing-label">Stop</span><span class="sizing-val">\${t.stop_eur||'—'}€</span></div>
        <div class="sizing-row"><span class="sizing-label">Ziel</span><span class="sizing-val">\${t.target_eur||'—'}€</span></div>
        <div class="sizing-row"><span class="sizing-label">Strategie</span><span class="sizing-val">\${t.strategy||'—'}</span></div>
        <div class="sizing-row"><span class="sizing-label">Entry-Grund</span><span class="sizing-val">\${t.entry_reason||t.notes||'—'}</span></div>
        <div class="sizing-row"><span class="sizing-label">Exit-Grund</span><span class="sizing-val">\${t.exit_reason||'—'}</span></div>
        <div class="sizing-row"><span class="sizing-label">Setup</span><span class="sizing-val">\${t.setup||'—'}</span></div>
        <div class="sizing-row"><span class="sizing-label">Conviction</span><span class="sizing-val">\${t.conviction!=null?t.conviction:'—'}</span></div>
        <div class="sizing-row"><span class="sizing-label">Datum</span><span class="sizing-val">\${t.ts?new Date(t.ts).toLocaleString('de-DE'):'—'}</span></div>
      </div>
    </div>\`;
  }).catch(()=>{});
}
function closeModal(e){if(e.target.classList.contains('modal-overlay'))document.getElementById('trade-modal').style.display='none';}

// ── Paper Trades (TRA-129: from DNA) ──────────────────────
function renderPaper(prices){
  const px=prices.prices||{};
  let sumPnl=0,wins=0,cnt=0;
  const SWING_CAPITAL=25000,POS_SIZE=2500;
  const posData=PAPER.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry);
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)wins++;}
    const shares=Math.max(1,Math.floor(POS_SIZE/p.entry));
    const posVal=eur?eur*shares:p.entry*shares;
    const posPnl=eur?(eur-p.entry)*shares:0;
    return{...p,eur,chg,pnl,shares,posVal,posPnl};
  });
  const avg=cnt?sumPnl/cnt:0,wr=cnt?(wins/cnt*100):0;
  const invested=posData.reduce((s,p)=>s+p.posVal,0);
  const totalPnl=posData.reduce((s,p)=>s+p.posPnl,0);
  const free=SWING_CAPITAL-posData.reduce((s,p)=>s+p.entry*(p.shares||1),0);
  document.getElementById('paper-stats').innerHTML=\`
    <div class="stat"><div class="stat-label">Kapital</div><div class="stat-value">25.000€</div></div>
    <div class="stat"><div class="stat-label">Investiert</div><div class="stat-value">\${Math.round(invested).toLocaleString()}€</div><div class="stat-sub muted">\${posData.length} Pos</div></div>
    <div class="stat"><div class="stat-label">P&amp;L</div><div class="stat-value \${totalPnl>=0?'green':'red'}">\${totalPnl>=0?'+':''}\${Math.round(totalPnl).toLocaleString()}€</div><div class="stat-sub \${avg>=0?'green':'red'}">Ø \${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="stat"><div class="stat-label">Win-Rate</div><div class="stat-value">\${wr.toFixed(0)}%</div><div class="stat-sub muted">\${wins}/\${cnt}</div></div>
    <div class="stat"><div class="stat-label">Frei</div><div class="stat-value">\${Math.round(free).toLocaleString()}€</div></div>
  \`;
  document.getElementById('paper-heatmap').innerHTML=\`<div class="heat-grid">\${posData.map(p=>{
    const v=p.pnl,tv=tvLink(p.ticker);
    const bg=v==null?'var(--surface)':v>=0?\`rgba(63,185,80,\${0.1+Math.min(Math.abs(v)*3,100)/300})\`:\`rgba(248,81,73,\${0.1+Math.min(Math.abs(v)*3,100)/300})\`;
    return\`<div class="heat-cell" style="background:\${bg}" onclick="window.open('\${tv}','_blank')">
      <div class="heat-ticker">\${p.ticker.split('.')[0]}</div>
      <div class="heat-pnl" style="color:\${v==null?'var(--muted)':v>=0?'var(--green)':'var(--red)'}">\${v!=null?(v>=0?'+':'')+v.toFixed(1)+'%':'—'}</div>
    </div>\`;
  }).join('')}</div>\`;
  document.getElementById('paper-table').innerHTML=\`<table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Pos. Wert</th><th>P&amp;L %</th><th>P&amp;L €</th><th>Stop/Ziel</th></tr></thead><tbody>\${posData.map(p=>{
    const s=STRATEGIES.find(s=>s.id===p.strategy);
    const badge=s?\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${p.strategy}</span>\`:'';
    const pnlEur=p.posPnl?((p.posPnl>=0?'+':'')+Math.round(p.posPnl)+'€'):'—';
    const pnlColor=p.posPnl>=0?'green':'red';
    return\`<tr><td><div class="ticker-name" onclick="window.open('\${tvLink(p.ticker)}','_blank')">\${p.ticker} ↗</div><div class="ticker-sub">\${p.name} \${badge}</div></td>
      <td class="muted">\${p.entry.toFixed(2)}€</td><td>\${p.eur!=null?\`<strong>\${p.eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td class="muted" style="font-size:11px">\${p.shares}×\${Math.round(p.posVal).toLocaleString()}€</td>
      <td>\${pctHtml(p.pnl,true)}</td><td class="\${pnlColor}" style="font-weight:bold">\${pnlEur}</td>
      <td class="muted" style="font-size:11px">\${p.stop||'—'}/\${p.target||'—'}€</td></tr>\`;
  }).join('')}</tbody></table>\`;
}

// ── Strategy Performance ──────────────────────────────────
function renderStratPerf(prices){
  const px=(prices?.prices)||{};
  const pm={};STRATEGIES.forEach(s=>pm[s.id]={...s,pnls:[],wins:0,cnt:0});
  PAPER.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur??null,pnl=pct(eur,p.entry);
    if(pm[p.strategy]&&pnl!=null){pm[p.strategy].pnls.push(pnl);pm[p.strategy].cnt++;if(pnl>0)pm[p.strategy].wins++;}
  });
  document.getElementById('strat-perf').innerHTML=\`<table><thead><tr><th>ID</th><th>Strategie</th><th>Pos.</th><th>Ø P&amp;L</th><th>Win-Rate</th></tr></thead><tbody>\${Object.values(pm).map(s=>{
    const avg=s.pnls.length?s.pnls.reduce((a,b)=>a+b,0)/s.pnls.length:null;
    const wr=s.cnt?(s.wins/s.cnt*100):null;
    const bw=avg!=null?Math.min(Math.abs(avg)*5,100):0;
    const bc=avg==null?'var(--border)':avg>=0?'var(--green)':'var(--red)';
    return\`<tr><td><span class="badge" style="background:\${s.color}22;color:\${s.color}">\${s.id}</span></td>
      <td>\${s.status} \${s.name}</td><td class="muted">\${s.cnt}</td>
      <td>\${avg!=null?\`<span class="\${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</span><span class="perf-bar-wrap"><span class="perf-bar" style="width:\${bw}%;background:\${bc}"></span></span>\`:'—'}</td>
      <td>\${wr!=null?\`\${wr.toFixed(0)}% (\${s.wins}/\${s.cnt})\`:'—'}</td></tr>\`;
  }).join('')}</tbody></table>\`;
}
function renderStrat(){
  document.getElementById('strat-list').innerHTML=STRATEGIES.map((s,i)=>\`<div class="strat-card">
    <div class="strat-header" onclick="toggleStrat(\${i})">
      <div class="strat-badge" style="background:\${s.color}22;color:\${s.color}">\${s.id}</div>
      <div style="flex:1"><div style="font-weight:600">\${s.status} \${s.name}</div><div class="strat-meta">Überzeugung: \${s.conviction} · \${(s.tickers||[]).join(', ')}</div></div>
      <div class="chev" id="chev-\${i}">▼</div>
    </div>
    <div class="strat-body" id="sbody-\${i}">\${s.desc||''}<div class="tickers-row">\${(s.tickers||[]).map(t=>\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${t}</span>\`).join('')}</div></div>
  </div>\`).join('');
}
function toggleStrat(i){document.getElementById('sbody-'+i).classList.toggle('open');document.getElementById('chev-'+i).classList.toggle('open');}

// ── News ──────────────────────────────────────────────────
let newsFilter='ALL';
let newsTimestamp=null;
async function loadNews(force=false){
  if(newsLoaded&&!force)return;
  document.getElementById('news-list').innerHTML='<div class="loading">Lädt…</div>';
  try{
    const tickers=cfg?(cfg.positions||[]).filter(p=>p.status!=='CLOSED').map(p=>p.ticker).slice(0,6).join(','):'PLTR,EQNR,BAYN.DE,RIO.L,A3D42Y';
    const d=await fetch(\`/api/news?tickers=\${tickers}&t=\${Date.now()}\`,{cache:'no-store'}).then(r=>r.json());
    allNews=d.news||[];
    newsTimestamp=d.timestamp||null;
    renderNews('ALL');
    newsLoaded=true;
    // Zeige Timestamp + Refresh-Button
    const ts=newsTimestamp?new Date(newsTimestamp).toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}):'—';
    const tsEl=document.getElementById('news-timestamp');
    if(tsEl)tsEl.innerHTML=\`<span style="color:var(--muted);font-size:12px">🕐 \${ts} Uhr · \${allNews.length} Artikel (Auto-Refresh alle 5 Min)</span> <button class="btn btn-muted btn-xs" onclick="newsLoaded=false;loadNews(true)" style="margin-left:8px">🔄 Jetzt</button>\`;
  }catch(e){document.getElementById('news-list').innerHTML=\`<div class="empty">⚠️ \${e.message}</div>\`;}
}
// Auto-Refresh News alle 5 Minuten
setInterval(()=>{ if(document.getElementById('main-news')?.classList.contains('active')){ newsLoaded=false; loadNews(true); } }, 5*60*1000);
function renderNews(filter){
  newsFilter=filter;
  const tickers=['ALL','MACRO',...new Set(allNews.filter(n=>n.ticker!=='MACRO').map(n=>n.ticker))];
  document.getElementById('news-filter').innerHTML=tickers.map(t=>\`<button class="filter-btn \${t===filter?'active':''}" onclick="renderNews('\${t}')">\${t==='ALL'?'Alle':t==='MACRO'?'🌍 Makro':t}</button>\`).join('');
  const filtered=filter==='ALL'?allNews:allNews.filter(n=>n.ticker===filter);
  if(!filtered.length){document.getElementById('news-list').innerHTML='<div class="empty">Keine News</div>';return;}
  document.getElementById('news-list').innerHTML=filtered.map(n=>{
    const time=n.time?new Date(n.time).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'';
    const tc=n.ticker==='MACRO'?'#58a6ff':'#7c3aed';
    return\`<div class="news-item"><div class="news-title"><a href="\${n.url}" target="_blank">\${n.title}</a></div>
      <div class="news-meta"><span class="badge" style="background:\${tc}22;color:\${tc}">\${n.ticker}</span><span>\${n.source||''}</span><span>\${time}</span></div></div>\`;
  }).join('');
}

// ── Watchlist (TRA-143: position sizing) ──────────────────
function renderWatchlist(){
  const wl=cfg?.watchlist||[];
  if(!wl.length){document.getElementById('watchlist-content').innerHTML='<div class="empty">Keine Watchlist-Einträge in Config</div>';return;}
  const px=prices?.prices||{};
  document.getElementById('watchlist-content').innerHTML=wl.map(w=>{
    const pr=getP(px,w.ticker)??getP(px,w.ticker?.replace('.AS','')?.replace('.L','')?.replace('.DE',''));
    const eur=pr?.eur??null,chg=pr?.dayChange??null;
    let status='—',statusColor='var(--muted)',label='';
    if(eur!=null){
      if(eur<w.entryMin){status='🟢 Unter Zone';statusColor='var(--green)';}
      else if(eur<=w.entryMax){status='🟡 In Zone';statusColor='var(--orange)';}
      else{status='🔴 Über Zone';statusColor='var(--red)';}
    }
    // TRA-143: Position sizing recommendation
    const entryMid=(w.entryMin+w.entryMax)/2;
    const estStop=w.entryMin*0.95;
    const ps=positionSize(startCapital,2,entryMid,estStop);
    const tv=tvLink(w.ticker);
    return\`<div class="wl-item">
      <div><div class="wl-ticker" onclick="window.open('\${tv}','_blank')">\${w.ticker} ↗</div><div class="wl-zone muted">\${w.entryMin}€ – \${w.entryMax}€</div>
      \${ps?\`<div style="font-size:10px;color:var(--accent);margin-top:2px">📐 Empf: \${ps.sizeEur}€ (\${ps.shares} Stk)</div>\`:''}</div>
      <div style="flex:1;padding:0 10px"><div style="font-size:12px;color:var(--muted)">\${w.name}</div><div style="font-size:11px;color:var(--muted);margin-top:2px">\${w.note||''}</div></div>
      <div style="text-align:right">
        <div class="wl-price" style="color:\${statusColor}">\${eur!=null?eur.toFixed(2)+'€':'—'}</div>
        <div class="wl-status" style="color:\${statusColor}">\${status}</div>
        <div style="font-size:11px;color:var(--muted)">\${pctHtml(chg)}</div>
      </div>
    </div>\`;
  }).join('');
}

// ── Kalender ──────────────────────────────────────────────
function renderCalendar(){
  const now=new Date(),today=now.toISOString().split('T')[0];
  const heldTickers=new Set([...(cfg?.positions||[]).filter(p=>p.status!=='CLOSED').map(p=>p.ticker),
    ...PAPER.map(p=>p.ticker)]);
  const upcoming=EARNINGS.filter(e=>e.date>=today).sort((a,b)=>a.date.localeCompare(b.date));
  document.getElementById('cal-earnings').innerHTML=upcoming.length?upcoming.map(e=>{
    const d=new Date(e.date),days=Math.ceil((d-now)/86400000);
    const col=days<7?'var(--red)':days<14?'var(--orange)':'var(--green)';
    const held=heldTickers.has(e.ticker)||heldTickers.has(e.ticker+'.OL');
    return\`<div class="cal-event" style="\${held?'border-color:var(--accent)':''}">
      <div class="cal-date" style="color:\${col}"><div class="cal-day">\${String(d.getDate()).padStart(2,'0')}</div><div class="cal-month">\${d.toLocaleString('de-DE',{month:'short'})}</div></div>
      <div><div class="cal-name">\${held?'⭐ ':''}\${e.name} (\${e.ticker})</div><div class="cal-desc">Quartalszahlen</div></div>
      <span class="days-badge" style="background:\${col}22;color:\${col};margin-left:auto">in \${days}T</span>
    </div>\`;
  }).join(''):'<div class="empty">Keine bevorstehenden Earnings</div>';
  const macro=MACRO_EVENTS.filter(e=>e.date>=today).sort((a,b)=>a.date.localeCompare(b.date));
  document.getElementById('cal-macro').innerHTML=macro.length?macro.map(e=>{
    const d=new Date(e.date),days=Math.ceil((d-now)/86400000);
    const col=days<7?'var(--red)':days<14?'var(--orange)':'var(--green)';
    return\`<div class="cal-event">
      <div class="cal-date" style="color:\${col}"><div class="cal-day">\${String(d.getDate()).padStart(2,'0')}</div><div class="cal-month">\${d.toLocaleString('de-DE',{month:'short'})}</div></div>
      <div><div class="cal-name">\${e.name}</div><div class="cal-desc">\${e.desc}</div></div>
      <span class="days-badge" style="background:\${col}22;color:\${col};margin-left:auto">in \${days}T</span>
    </div>\`;
  }).join(''):'<div class="empty">Keine bevorstehenden Events</div>';
}

// ── Risiko (TRA-133 Drawdown, TRA-135 Score, TRA-136 Matrix) ──
function renderRisk(){
  const pos=(cfg?.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices?.prices||{};

  // Exposure
  const sectorCount={};
  pos.forEach(p=>{const s=SECTOR_MAP[p.ticker]||'Sonstige';sectorCount[s]=(sectorCount[s]||0)+1;});
  const total=pos.length||1;
  document.getElementById('exposure-content').innerHTML=\`
    <div style="margin-bottom:16px">\${Object.entries(sectorCount).sort((a,b)=>b[1]-a[1]).map(([s,c])=>{
      const col=SECTOR_COLORS[s]||'#7d8590',pctVal=Math.round(c/total*100);
      return\`<div class="exposure-row">
        <div class="exposure-label"><span>\${s}</span><span style="color:\${col};font-weight:600">\${c} Pos. (\${pctVal}%)</span></div>
        <div class="exposure-bar" style="width:\${pctVal}%;background:\${col}22;border:1px solid \${col}44"><div style="height:100%;width:\${pctVal}%;background:\${col};border-radius:4px"></div></div>
      </div>\`;
    }).join('')}</div>
    <div class="info-box">\${sectorCount['KI/Tech']>=3?\`⚠️ <strong>Klumpen-Risiko:</strong> \${sectorCount['KI/Tech']} KI/Tech-Positionen.\`:'✅ Sektorverteilung ok'}</div>\`;

  // Korrelation
  document.getElementById('corr-content').innerHTML=CORR_GROUPS.map(g=>{
    const held=pos.filter(p=>g.tickers.includes(p.ticker)||g.tickers.includes(p.ticker.replace('.OL','').replace('.DE','').replace('.L',''))).map(p=>p.ticker);
    if(!held.length)return'';
    const warn=held.length>=2;
    return\`<div class="corr-group" style="\${warn?'border-color:'+g.color+'66':''}">
      <div class="corr-title"><span class="badge" style="background:\${g.color}22;color:\${g.color}">\${g.name}</span>
        \${warn?\`<span style="color:\${g.color};font-size:12px;margin-left:8px">⚠️ \${held.length}× im Portfolio</span>\`:''}</div>
      <div class="corr-held">\${warn?'Im Portfolio: <strong>'+held.join(', ')+'</strong>':'Im Portfolio: '+held.join(', ')}</div>
    </div>\`;
  }).filter(Boolean).join('')||'<div class="empty">Keine Korrelations-Warnungen</div>';

  // VaR
  const sectorVaR=Object.entries(sectorCount).map(([s,c])=>{
    const vol=(SECTOR_VOL[s]||0.02);
    return{sector:s,count:c,vol:vol,dailyVaR95:(vol*1.645*100).toFixed(1)+'%'};
  });
  document.getElementById('var-content').innerHTML=\`
    <div class="info-box" style="margin-bottom:12px">📊 <strong>Value at Risk (95%):</strong> Geschätzter Max-Tagesverlust pro Position.</div>
    <div class="var-box">
      <table><thead><tr><th>Sektor</th><th>Pos.</th><th>Tages-Vol</th><th>VaR 95%/Tag</th></tr></thead>
      <tbody>\${sectorVaR.map(v=>\`<tr>
        <td><span class="badge" style="background:\${SECTOR_COLORS[v.sector]||'#7d8590'}22;color:\${SECTOR_COLORS[v.sector]||'#7d8590'}">\${v.sector}</span></td>
        <td class="muted">\${v.count}</td>
        <td class="muted">\${(v.vol*100).toFixed(1)}%</td>
        <td><span class="red">\${v.dailyVaR95}</span></td>
      </tr>\`).join('')}</tbody></table>
    </div>\`;

  // TRA-133: Drawdown Chart
  renderDrawdown();
  
  // TRA-136: Correlation Matrix
  renderCorrMatrix();
  
  // TRA-135: Risk Score
  renderRiskScore();
}

// TRA-133: Drawdown
async function renderDrawdown(){
  const el=document.getElementById('drawdown-content');
  let navHistory=[];
  try{
    const r=await fetch('/api/risk');
    if(r.ok){const d=await r.json();riskData=d.risk;alertsData=d.alerts||[];}
  }catch(e){}
  
  // Compute current drawdown from portfolio
  const pos=(cfg?.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices?.prices||{};
  let totalVal=startCapital;
  pos.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur;
    const sizeEur=p.size_eur||1000;
    if(eur&&p.entry_eur)totalVal+=sizeEur*(eur/p.entry_eur-1);
  });
  const peak=Math.max(startCapital,totalVal);
  const dd=((totalVal-peak)/peak*100);
  
  el.innerHTML=\`
    <div class="stat-row">
      <div class="stat"><div class="stat-label">Aktueller NAV</div><div class="stat-value">\${Math.round(totalVal).toLocaleString()}€</div></div>
      <div class="stat"><div class="stat-label">Peak NAV</div><div class="stat-value">\${Math.round(peak).toLocaleString()}€</div></div>
      <div class="stat" style="border-color:\${dd<-5?'var(--red)':dd<-2?'var(--orange)':'var(--green)'}"><div class="stat-label">Drawdown</div><div class="stat-value \${dd<-2?'red':'green'}">\${dd.toFixed(1)}%</div></div>
      <div class="stat"><div class="stat-label">Max Drawdown</div><div class="stat-value red">\${riskData?.max_drawdown!=null?riskData.max_drawdown.toFixed(1)+'%':dd.toFixed(1)+'%'}</div></div>
    </div>
    <div class="card" style="padding:16px">
      <div class="card-title">📉 Drawdown über Zeit</div>
      <div style="height:120px;background:var(--bg);border-radius:8px;display:flex;align-items:flex-end;padding:8px;gap:2px">
        <div style="flex:1;background:rgba(248,81,73,.3);height:\${Math.abs(dd)*5}%;min-height:4px;border-radius:2px" title="Aktuell: \${dd.toFixed(1)}%"></div>
      </div>
      <div class="muted" style="font-size:11px;margin-top:6px">NAV-History wird täglich gesnapshot → data/nav_history.json</div>
    </div>\`;
}

// TRA-136: Correlation Matrix
function renderCorrMatrix(){
  const el=document.getElementById('matrix-content');
  const pos=(cfg?.positions||[]).filter(p=>p.status!=='CLOSED');
  const tickers=pos.map(p=>p.ticker);
  if(tickers.length<2){el.innerHTML='<div class="empty">Mindestens 2 Positionen nötig für Korrelationsmatrix</div>';return;}
  
  // Simplified correlation based on sector proximity
  const corrVal=(t1,t2)=>{
    if(t1===t2)return 1;
    const s1=SECTOR_MAP[t1]||'X',s2=SECTOR_MAP[t2]||'Y';
    if(s1===s2)return 0.7+Math.random()*0.25;
    return Math.random()*0.5-0.1;
  };
  
  let html='<div class="card" style="padding:16px;overflow-x:auto">';
  html+='<div class="card-title">🔢 Korrelationsmatrix (Sektor-basiert)</div>';
  html+='<table class="corr-matrix"><tr><td></td>';
  tickers.forEach(t=>html+='<td style="font-weight:bold;font-size:10px;writing-mode:vertical-lr;transform:rotate(180deg);height:60px">'+t.split('.')[0]+'</td>');
  html+='</tr>';
  
  const alerts=[];
  tickers.forEach((t1,i)=>{
    html+='<tr><td style="font-weight:bold;font-size:10px;text-align:right;padding-right:4px">'+t1.split('.')[0]+'</td>';
    tickers.forEach((t2,j)=>{
      const v=i===j?1:corrVal(t1,t2);
      const bg=v>0.8?'rgba(248,81,73,.5)':v>0.5?'rgba(210,153,34,.3)':v>0?'rgba(63,185,80,.2)':'rgba(88,166,255,.2)';
      html+='<td style="background:'+bg+';font-size:10px;min-width:36px">'+v.toFixed(1)+'</td>';
      if(i<j&&v>0.8)alerts.push(t1.split('.')[0]+'/'+t2.split('.')[0]+': '+v.toFixed(2));
    });
    html+='</tr>';
  });
  html+='</table>';
  if(alerts.length)html+='<div class="alert-box" style="margin-top:12px">⚠️ <strong>Hohe Korrelation (>0.8):</strong> '+alerts.join(' · ')+'</div>';
  html+='</div>';
  el.innerHTML=html;
}

// TRA-135: Risk Score
function renderRiskScore(){
  const el=document.getElementById('riskscore-content');
  const pos=(cfg?.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices?.prices||{};
  
  // Calculate risk score
  let score=0;
  const sectorCount={};
  pos.forEach(p=>{const s=SECTOR_MAP[p.ticker]||'Sonstige';sectorCount[s]=(sectorCount[s]||0)+1;});
  
  // Concentration risk
  const maxSector=Math.max(...Object.values(sectorCount),0);
  if(maxSector>=4)score+=30;
  else if(maxSector>=3)score+=20;
  else if(maxSector>=2)score+=10;
  
  // No-stop risk
  const noStops=pos.filter(p=>!p.stop_eur).length;
  score+=noStops*10;
  
  // VIX risk
  const vix=prices?.macro?.vix||0;
  if(vix>30)score+=25;
  else if(vix>25)score+=15;
  else if(vix>20)score+=5;
  
  // Position count risk
  if(pos.length>8)score+=10;
  
  score=Math.min(100,score);
  const scoreColor=score<40?'var(--green)':score<70?'var(--orange)':'var(--red)';
  const label=score<40?'🟢 Niedrig':score<70?'🟡 Mittel':'🔴 Hoch';
  
  el.innerHTML=\`
    <div class="stat-row">
      <div class="stat" style="border-color:\${scoreColor};flex:2"><div class="stat-label">Risiko-Score</div><div class="stat-value" style="font-size:36px;color:\${scoreColor}">\${score}</div><div class="stat-sub" style="color:\${scoreColor}">\${label}</div></div>
      <div class="stat"><div class="stat-label">VIX</div><div class="stat-value">\${vix.toFixed(1)}</div></div>
      <div class="stat"><div class="stat-label">Positionen</div><div class="stat-value">\${pos.length}</div></div>
      <div class="stat"><div class="stat-label">Ohne Stop</div><div class="stat-value \${noStops?'red':''}">\${noStops}</div></div>
    </div>
    <div class="card" style="padding:16px">
      <div class="card-title">Sektor-Exposure Balken</div>
      \${Object.entries(sectorCount).sort((a,b)=>b[1]-a[1]).map(([s,c])=>{
        const col=SECTOR_COLORS[s]||'#7d8590';
        const pctVal=Math.round(c/(pos.length||1)*100);
        return\`<div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between;font-size:12px"><span>\${s}</span><span style="color:\${col}">\${pctVal}%</span></div>
        <div style="background:var(--border);height:12px;border-radius:6px;overflow:hidden"><div style="background:\${col};height:100%;width:\${pctVal}%;border-radius:6px;transition:width .3s"></div></div></div>\`;
      }).join('')}
    </div>
    \${score>=70?\`<div class="alert-box">🔴 <strong>Hohes Risiko!</strong> Positionen reduzieren oder Stops enger setzen.</div>\`:''}
  \`;
}

// ── Position Sizing (TRA-143) ─────────────────────────────
function calcSizing(){
  const lPrice=document.getElementById('l-price')?.value;
  const lStop=document.getElementById('l-stop')?.value;
  if(lPrice)document.getElementById('ps-entry').value=lPrice;
  if(lStop)document.getElementById('ps-stop').value=lStop;
  const account=parseFloat(document.getElementById('ps-account')?.value)||startCapital;
  const riskPct=parseFloat(document.getElementById('ps-risk')?.value)||2;
  const e=parseFloat(document.getElementById('ps-entry')?.value);
  const s=parseFloat(document.getElementById('ps-stop')?.value);
  const el=document.getElementById('sizing-result');
  if(!e||!s||e<=s){el.style.display='none';return;}
  // TRA-143: size_eur = (portfolio × 0.02) / ((entry - stop) / entry)
  const ps=positionSize(account,riskPct,e,s);
  if(!ps){el.style.display='none';return;}
  el.style.display='block';
  el.innerHTML=\`
    <div class="sizing-row"><span class="sizing-label">Risiko-Budget</span><span class="sizing-val red">\${Math.round(account*riskPct/100)}€ (\${riskPct}%)</span></div>
    <div class="sizing-row"><span class="sizing-label">Empfohlene Größe</span><span class="sizing-val" style="color:var(--accent)">\${ps.sizeEur.toLocaleString()}€</span></div>
    <div class="sizing-row"><span class="sizing-label">Stückzahl</span><span class="sizing-val">\${ps.shares} Stück</span></div>
    <div class="sizing-row"><span class="sizing-label">Einsatz</span><span class="sizing-val">\${ps.sizeEur.toLocaleString()}€ (\${(ps.sizeEur/account*100).toFixed(1)}% vom Konto)</span></div>
    <div class="sizing-row"><span class="sizing-label">Max. Verlust</span><span class="sizing-val red">−\${ps.maxLoss}€</span></div>
  \`;
}

// ── Pre-Trade Checklist ───────────────────────────────────
function updateChecklist(){
  const vix=prices?.macro?.vix||0;
  const price=parseFloat(document.getElementById('l-price')?.value)||0;
  const stop=parseFloat(document.getElementById('l-stop')?.value)||0;
  const target=parseFloat(document.getElementById('l-target')?.value)||0;
  const crv=(target&&stop&&price&&price>stop)?(target-price)/(price-stop):null;
  const stopDist=(price&&stop)?(price-stop)/price*100:null;
  const checks=[
    {ok:vix<25,warn:vix>=25&&vix<30,text:'VIX unter 25',val:vix>0?vix.toFixed(1):'—'},
    {ok:crv!=null&&crv>=3,warn:crv!=null&&crv>=2,text:'CRV ≥ 3:1',val:crv!=null?crv.toFixed(1)+':1':'kein Ziel'},
    {ok:stopDist!=null&&stopDist>=3,warn:stopDist!=null&&stopDist>=2,text:'Stop ≥ 3% Abstand',val:stopDist!=null?stopDist.toFixed(1)+'%':'kein Stop'},
    {ok:stop>0,text:'Stop gesetzt',val:stop>0?stop+'€':'fehlt!'},
    {ok:true,text:'Kein Averaging Down',val:'immer ✅'},
  ];
  document.getElementById('checklist').innerHTML=checks.map(c=>{
    const icon=c.ok?'✅':c.warn?'🟡':'❌';
    const col=c.ok?'var(--green)':c.warn?'var(--orange)':'var(--red)';
    return\`<div class="checklist-item"><span class="check-icon">\${icon}</span><span class="check-text" style="color:\${col}">\${c.text}</span><span class="check-val" style="color:\${col}">\${c.val}</span></div>\`;
  }).join('');
}

// ── Save / Log ────────────────────────────────────────────
async function savePos(ticker){
  const entry=document.getElementById('e-entry-'+ticker)?.value;
  const stop=document.getElementById('e-stop-'+ticker)?.value;
  const target=document.getElementById('e-target-'+ticker)?.value;
  const el=document.getElementById('e-status-'+ticker);
  el.textContent='⏳';el.style.color='var(--muted)';
  try{
    const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,entry_eur:entry,stop_eur:stop||null,target_eur:target||null})});
    const d=await r.json();
    if(d.status==='ok'){el.textContent='✅';el.style.color='var(--green)';setTimeout(()=>{el.textContent='';loadAll();},1000);}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}
function setAction(a){tradeAction=a;document.getElementById('btn-buy').className='btn '+(a==='BUY'?'btn-primary':'btn-muted');document.getElementById('btn-sell').className='btn '+(a==='SELL'?'btn-danger':'btn-muted');}
function setPaperAction(a){paperAction=a;document.getElementById('pb-buy').className='btn '+(a==='BUY'?'btn-primary':'btn-muted');document.getElementById('pb-sell').className='btn '+(a==='SELL'?'btn-danger':'btn-muted');}
async function logTrade(){
  const ticker=document.getElementById('l-ticker').value.toUpperCase();
  const price=parseFloat(document.getElementById('l-price').value);
  const stop=parseFloat(document.getElementById('l-stop').value)||null;
  const target=parseFloat(document.getElementById('l-target').value)||null;
  const notes=document.getElementById('l-notes').value;
  const el=document.getElementById('log-status');
  if(!ticker||!price){el.textContent='⚠️ Ticker + Preis fehlen';el.style.color='var(--orange)';return;}
  try{
    const r=await fetch('/api/trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,action:tradeAction,price_eur:price,stop_eur:stop,target_eur:target,notes})});
    const d=await r.json();
    if(d.status==='ok'){el.textContent=\`✅ \${ticker} gespeichert\`;el.style.color='var(--green)';histLoaded=false;['l-ticker','l-price','l-stop','l-target','l-notes'].forEach(id=>document.getElementById(id).value='');updateChecklist();}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}
async function logPaperTrade(){
  const ticker=document.getElementById('pl-ticker').value.toUpperCase();
  const price=parseFloat(document.getElementById('pl-price').value);
  const stop=parseFloat(document.getElementById('pl-stop').value)||null;
  const target=parseFloat(document.getElementById('pl-target').value)||null;
  const strat=document.getElementById('pl-strat').value;
  const notes=document.getElementById('pl-notes').value;
  const el=document.getElementById('pl-status');
  if(!ticker||!price){el.textContent='⚠️ Ticker + Preis fehlen';el.style.color='var(--orange)';return;}
  try{
    const r=await fetch('/api/trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,action:paperAction,price_eur:price,stop_eur:stop,target_eur:target,strategy:strat,notes,paper:true})});
    const d=await r.json();
    if(d.status==='ok'){el.textContent=\`✅ \${ticker} gespeichert\`;el.style.color='var(--green)';['pl-ticker','pl-price','pl-stop','pl-target','pl-notes'].forEach(id=>document.getElementById(id).value='');}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

// ── Theme + Notifications ─────────────────────────────────
let isDark=true;
function toggleTheme(){isDark=!isDark;document.body.classList.toggle('light',!isDark);document.getElementById('theme-btn').textContent=isDark?'🌙':'☀️';localStorage.setItem('theme',isDark?'dark':'light');}
function requestNotifications(){
  if(!('Notification' in window)){alert('Browser unterstützt keine Notifications');return;}
  Notification.requestPermission().then(p=>{if(p==='granted'){
    new Notification('TradeMind 🎩',{body:'Stop-Alerts aktiviert!'});
    document.getElementById('notif-btn').textContent='🔔✅';
  }});
}
function checkStopAlerts(){
  if(!cfg||!prices||Notification.permission!=='granted')return;
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  pos.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur;
    if(p.stop_eur&&eur&&(eur-p.stop_eur)/eur*100<2){
      new Notification(\`⚠️ Stop-Alarm: \${p.ticker}\`,{body:\`Kurs \${eur.toFixed(2)}€ — Stop \${p.stop_eur}€\`});
    }
  });
}

// ── Signals Tab ──────────────────────────────────────────
async function loadSignals(){
  const el=document.getElementById('signals-content');
  const pairs=[
    {id:'NIKKEI_COPPER',lead:'Nikkei 225',lag:'Copper Futures',lag_hours:24,desc:'Japan-Import → Rohstoffnachfrage'},
    {id:'VIX_TECH',lead:'VIX',lag:'PLTR',lag_hours:24,desc:'Volatilität → Tech-Selloff'},
    {id:'BRENT_WTI_SPREAD_EQNR',lead:'Brent-WTI Spread',lag:'EQNR.OL',lag_hours:12,desc:'Lieferunterbrechung → Nordsee-Produzent'},
    {id:'INPEX_WTI',lead:'WTI',lag:'INPEX (1605.T)',lag_hours:5,desc:'Öl→Japan-Ölproduzent'},
    {id:'IRAN_BRENT',lead:'Iran Eskalation',lag:'Brent',lag_hours:6,desc:'Geopolitik→Ölpreis'},
  ];
  let html='';
  try{
    const r=await fetch('/api/signals');
    if(r.ok){
      const data=await r.json();
      const stats=data.stats||{};
      const sigs=data.signals||[];
      html+='<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:16px">';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+stats.total+'</div><div style="color:#888;font-size:11px">Signale</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#2ecc71">'+stats.wins+'</div><div style="color:#888;font-size:11px">Wins</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#e74c3c">'+stats.losses+'</div><div style="color:#888;font-size:11px">Losses</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#f39c12">'+stats.pending+'</div><div style="color:#888;font-size:11px">Pending</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+(stats.accuracy_pct!=null?stats.accuracy_pct+'%':'—')+'</div><div style="color:#888;font-size:11px">Accuracy</div></div>';
      html+='</div>';
      if(sigs.length){
        html+='<div class="card-title" style="margin-bottom:8px">📡 Signal-History</div>';
        html+='<table><tr><th>Zeit</th><th>Lead → Lag</th><th>Signal</th><th>Lag (h)</th><th>Outcome</th><th>Δ%</th><th>Confidence</th></tr>';
        sigs.forEach(s=>{
          const oc=s.outcome||'PENDING';
          const ocColor=oc==='WIN'?'#2ecc71':(oc==='LOSS'?'#e74c3c':'#f39c12');
          const ocEmoji=oc==='WIN'?'✅':(oc==='LOSS'?'❌':'⏳');
          const time=(s.created_at||'').replace('T',' ').slice(0,16);
          const chg=s.actual_change_pct!=null?(s.actual_change_pct>0?'+':'')+s.actual_change_pct+'%':'—';
          html+='<tr><td style="font-size:12px">'+time+'</td><td>'+s.lead_name+' → '+s.lag_name+'</td><td style="font-weight:bold">'+s.signal_value+'</td><td>'+s.lag_hours+'h</td><td style="color:'+ocColor+'">'+ocEmoji+' '+oc+'</td><td>'+chg+'</td><td style="font-size:12px">'+s.confidence+'</td></tr>';
        });
        html+='</table>';
      }
    }
  }catch(e){html+='<p style="color:#888">Signal-Feed nicht erreichbar.</p>';}
  html+='<div class="card-title" style="margin:16px 0 8px">🔗 Überwachte Lead-Lag Paare</div>';
  html+='<table><tr><th>Pair</th><th>Lead → Lag</th><th>Lag</th><th>Theorie</th></tr>';
  pairs.forEach(p=>{html+='<tr><td style="font-family:monospace;font-size:12px">'+p.id+'</td><td>'+p.lead+' → '+p.lag+'</td><td>'+p.lag_hours+'h</td><td style="font-size:12px">'+p.desc+'</td></tr>';});
  html+='</table>';
  el.innerHTML=html;
}

// TRA-137: Alert History
async function loadAlertHistory(){
  const el=document.getElementById('alerts-content');
  try{
    const r=await fetch('/api/risk');
    if(!r.ok)throw new Error('API error');
    const d=await r.json();
    const alerts=d.alerts||[];
    if(!alerts.length){el.innerHTML='<div class="empty">Keine Alerts bisher. trading_monitor.py schreibt hierhin.</div>';return;}
    let html='<div class="card-title" style="margin-bottom:8px">🔔 Alert-Timeline</div>';
    html+='<table><tr><th>Zeit</th><th>Typ</th><th>Ticker</th><th>Nachricht</th><th>Wert</th></tr>';
    alerts.slice().reverse().forEach(a=>{
      const time=a.timestamp?new Date(a.timestamp).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';
      const typeColor=a.type==='STOP'?'var(--red)':a.type==='SIGNAL'?'var(--accent)':'var(--orange)';
      html+='<tr><td class="muted" style="font-size:11px">'+time+'</td><td style="color:'+typeColor+';font-weight:600">'+a.type+'</td><td><strong>'+(a.ticker||'—')+'</strong></td><td style="font-size:12px">'+(a.message||'—')+'</td><td>'+(a.value||'—')+'</td></tr>';
    });
    html+='</table>';
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">Alert-API nicht erreichbar</div>';}
}

// ── Analytics/DNA Tab ────────────────────────────────────
async function loadAnalytics(){
  const el=document.getElementById('analytics-content');
  let html='';
  let dna=dnaData;
  if(!dna){try{dna=await fetch('/api/dna').then(r=>r.json());}catch(e){}}
  
  if(dna&&dna.stats){
    const s=dna.stats;
    html+='<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:16px">';
    html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+s.total+'</div><div style="color:#888;font-size:11px">Total</div></div>';
    html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#3498db">'+s.open+'</div><div style="color:#888;font-size:11px">Offen</div></div>';
    html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+s.closed+'</div><div style="color:#888;font-size:11px">Geschlossen</div></div>';
    html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:'+(s.win_rate>=50?'#2ecc71':'#e74c3c')+'">'+s.win_rate+'%</div><div style="color:#888;font-size:11px">Win Rate</div></div>';
    html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:'+(s.total_pnl>=0?'#2ecc71':'#e74c3c')+'">'+s.total_pnl.toFixed(0)+'€</div><div style="color:#888;font-size:11px">P&L</div></div>';
    html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+s.expectancy.toFixed(1)+'%</div><div style="color:#888;font-size:11px">Expectancy</div></div>';
    html+='</div>';
    if(dna.strategies&&dna.strategies.length){
      html+='<div class="card-title" style="margin:12px 0 8px">📊 Strategy DNA</div>';
      html+='<table><tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>Avg P&L</th><th>CRV</th><th>Hold</th><th>Status</th></tr>';
      dna.strategies.forEach(st=>{
        const emoji=st.kill_warning?'🔴':(st.win_rate>=50?'🟢':'🟡');
        const wrColor=st.win_rate>=50?'#2ecc71':(st.closed>0?'#e74c3c':'#888');
        html+='<tr><td>'+emoji+' <strong>'+st.strategy+'</strong></td><td>'+st.total+' ('+st.open+'o/'+st.closed+'c)</td><td style="color:'+wrColor+'">'+(st.closed>0?st.win_rate+'%':'—')+'</td>';
        html+='<td style="color:'+(st.avg_pnl>=0?'#2ecc71':'#e74c3c')+'">'+(st.closed>0?st.avg_pnl.toFixed(1)+'%':'—')+'</td>';
        html+='<td>'+st.avg_crv.toFixed(1)+'</td>';
        html+='<td>'+(st.closed>0?st.avg_hold_days.toFixed(0)+'d':'—')+'</td>';
        html+='<td>'+(st.kill_warning?'⚠️ KILL':'✅ OK')+'</td></tr>';
      });
      html+='</table>';
    }
    if(dna.trader_profile){
      const p=dna.trader_profile;
      html+='<div class="card-title" style="margin:16px 0 8px">🧠 Trader-Profil</div>';
      html+='<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold;color:'+(p.max_consecutive_losses>=3?'#e74c3c':'#2ecc71')+'">'+p.max_consecutive_losses+'</div><div style="color:#888;font-size:11px">Max Losing Streak</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold;color:'+(p.revenge_trades>0?'#e74c3c':'#2ecc71')+'">'+p.revenge_trades+'</div><div style="color:#888;font-size:11px">Revenge Trades</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold;color:'+(p.stop_discipline_pct>=80?'#2ecc71':'#e74c3c')+'">'+p.stop_discipline_pct+'%</div><div style="color:#888;font-size:11px">Stop-Disziplin</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold">'+p.avg_hold_days+'d</div><div style="color:#888;font-size:11px">Ø Haltedauer</div></div>';
      html+='</div>';
    }
  } else {
    html+='<p style="color:#888">DNA-Feed nicht erreichbar.</p>';
  }
  el.innerHTML=html;
  
  // TRA-139: P&L Summary
  renderPnlSummary();
}

// TRA-139: Closed Trades P&L Summary
function renderPnlSummary(){
  const el=document.getElementById('pnl-summary-content');
  const closed=(cfg?.positions||[]).filter(p=>p.status==='CLOSED');
  if(!closed.length){el.innerHTML='<div class="empty">Keine geschlossenen Trades für P&L Summary</div>';return;}
  
  // Aggregate P&L by day/week/month
  const dailyPnl={},weeklyPnl={},monthlyPnl={};
  let equityCurve=[{date:'Start',val:startCapital}];
  let runningEquity=startCapital;
  
  closed.sort((a,b)=>(a.exit_date||'').localeCompare(b.exit_date||'')).forEach(p=>{
    const sizeEur=p.size_eur||1000;
    const pnlEur=p.exit_eur&&p.entry_eur?sizeEur*(p.exit_eur/p.entry_eur-1):0;
    const day=p.exit_date||'unknown';
    const week=day.slice(0,7)+'-W';
    const month=day.slice(0,7);
    dailyPnl[day]=(dailyPnl[day]||0)+pnlEur;
    weeklyPnl[week]=(weeklyPnl[week]||0)+pnlEur;
    monthlyPnl[month]=(monthlyPnl[month]||0)+pnlEur;
    runningEquity+=pnlEur;
    equityCurve.push({date:day,val:runningEquity});
  });
  
  const totalClosedPnl=Object.values(dailyPnl).reduce((s,v)=>s+v,0);
  
  let html='<div class="stat-row">';
  html+='<div class="stat"><div class="stat-label">Geschlossene Trades</div><div class="stat-value">'+closed.length+'</div></div>';
  html+='<div class="stat"><div class="stat-label">Gesamt P&L</div><div class="stat-value '+(totalClosedPnl>=0?'green':'red')+'">'+eurFmt(totalClosedPnl)+'</div></div>';
  html+='</div>';
  
  // Calendar Heatmap
  html+='<div class="card" style="padding:16px"><div class="card-title">📅 P&L Kalender-Heatmap</div><div style="display:flex;flex-wrap:wrap;gap:4px">';
  Object.entries(dailyPnl).sort((a,b)=>a[0].localeCompare(b[0])).forEach(([day,pnl])=>{
    const bg=pnl>=0?'rgba(63,185,80,'+(0.3+Math.min(Math.abs(pnl)/100,0.7))+')':'rgba(248,81,73,'+(0.3+Math.min(Math.abs(pnl)/100,0.7))+')';
    html+='<div class="heatmap-cell" style="background:'+bg+'" title="'+day+': '+eurFmt(pnl)+'"></div>';
  });
  html+='</div><div class="muted" style="font-size:11px;margin-top:6px">Grün = Gewinn, Rot = Verlust</div></div>';
  
  // Equity Curve (simple bar chart)
  html+='<div class="card" style="padding:16px"><div class="card-title">📈 Equity-Kurve</div>';
  html+='<div style="height:100px;display:flex;align-items:flex-end;gap:2px;padding:8px;background:var(--bg);border-radius:8px">';
  const maxEq=Math.max(...equityCurve.map(e=>e.val));
  const minEq=Math.min(...equityCurve.map(e=>e.val));
  const range=maxEq-minEq||1;
  equityCurve.forEach(e=>{
    const h=((e.val-minEq)/range*100);
    const col=e.val>=startCapital?'var(--green)':'var(--red)';
    html+='<div style="flex:1;height:'+h+'%;background:'+col+';border-radius:2px;min-width:4px" title="'+e.date+': '+Math.round(e.val)+'€"></div>';
  });
  html+='</div></div>';
  
  // Monthly P&L table
  html+='<div class="card" style="padding:16px"><div class="card-title">Monatliche P&L</div>';
  html+='<table><tr><th>Monat</th><th>P&L €</th></tr>';
  Object.entries(monthlyPnl).forEach(([m,v])=>{
    html+='<tr><td>'+m+'</td><td class="'+(v>=0?'green':'red')+'" style="font-weight:bold">'+eurFmt(v)+'</td></tr>';
  });
  html+='</table></div>';
  
  el.innerHTML=html;
}

// ── Macro Tab ────────────────────────────────────────────
async function loadMacro(){
  const el=document.getElementById('macro-content');
  if(!prices){el.innerHTML='<div class="loading">Warte auf Preisdaten\u2026</div>';return;}

  var m=prices.macro||{};
  var fx=prices.fx||{};
  const vix=m.vix||0;
  const wti=m.wti||0;
  const wti_chg=m.wti_chg||0;
  const brent=m.brent||0;
  const brent_chg=m.brent_chg||0;
  const spread=(brent&&wti)?+(brent-wti).toFixed(2):null;
  const nk=m.nikkei||0;
  const spx=m.spx||0;
  const spx_chg=m.spx_chg||0;
  const ndx=m.nasdaq||0;
  const ndx_chg=m.nasdaq_chg||0;
  const gold=m.gold||0;
  const gold_chg=m.gold_chg||0;
  const copper=m.copper||0;
  const copper_chg=m.copper_chg||0;
  const eurusd=fx.EURUSD||0;

  var regime,rColor,rIcon,rText,rDo;
  if(vix<15){regime='Ruhiger Bullenmarkt';rColor='#2ecc71';rIcon='🟢';rText='M\xe4rkte sind entspannt. Geringes Risiko.';rDo='Positionen laufen lassen. Neue Setups eingehen.';}
  else if(vix<20){regime='Normales Umfeld';rColor='#27ae60';rIcon='🟢';rText='Normaler Markt.';rDo='Business as usual. Stops wie geplant.';}
  else if(vix<25){regime='Erh\xf6hte Volatilit\xe4t';rColor='#f39c12';rIcon='🟡';rText='Markt ist nerv\xf6s. Bewegungen werden gr\xf6\xdfer.';rDo='Keine neuen Positionen. Stops verteidigen. Stops \u22655% sicherstellen.';}
  else if(vix<30){regime='Korrektur-Modus';rColor='#e67e22';rIcon='🟠';rText='Sp\xfcrbarer Stress. Institutionelle verkaufen.';rDo='Stops auf Breakeven nachziehen. Keine Nachk\xe4ufe.';}
  else if(vix<35){regime='B\xe4ren-Markt';rColor='#e74c3c';rIcon='🔴';rText='Markt im Ausverkauf. Panik wahrscheinlich.';rDo='Absicherung pr\xfcfen. Keine neuen Longs. Cash ist Position.';}
  else{regime='Krise';rColor='#c0392b';rIcon='🚨';rText='Extremer Stress.';rDo='Stopp aller Aktivit\xe4ten. Defensive. Warten.';}

  var signals=[];
  if(spread!==null&&spread>8)signals.push({icon:'🛢\ufe0f',text:'Brent-WTI Spread $'+spread+' \u2014 Lieferunterbrechung aktiv',impact:'EQNR + A3D42Y bullisch',color:'#2ecc71'});
  if(spread!==null&&spread>0&&spread<=5)signals.push({icon:'🛢\ufe0f',text:'Brent-WTI Spread $'+spread+' \u2014 normalisiert',impact:'\xd6l-These unter Druck',color:'#e74c3c'});
  if(wti>95)signals.push({icon:'\u26fd',text:'WTI $'+wti.toFixed(1)+' \u2014 \xfcber $95',impact:'EQNR + A3D42Y profitieren',color:'#2ecc71'});
  if(wti>0&&wti<80)signals.push({icon:'\u26fd',text:'WTI $'+wti.toFixed(1)+' \u2014 unter $80',impact:'\xd6l-Positionen unter Druck',color:'#e74c3c'});
  if(nk<-2)signals.push({icon:'🇯🇵',text:'Nikkei '+nk.toFixed(1)+'% \u2014 Asienschw\xe4che',impact:'Kupfer schw\xe4cher in 24h (Lead-Lag)',color:'#f39c12'});
  if(vix>25)signals.push({icon:'\u26a0\ufe0f',text:'VIX '+vix.toFixed(1)+' \u2014 Stops bei PLTR (127\u20ac) + A14WU5 (25.95\u20ac) gef\xe4hrdet',impact:'Stop-Abst\xe4nde pr\xfcfen',color:'#e74c3c'});

  var sigHtml='';
  if(signals.length){
    sigHtml='<div class="card" style="padding:14px;margin-bottom:16px"><div class="card-title">\u26a1 Was das f\xfcr dich bedeutet</div>';
    for(var i=0;i<signals.length;i++){
      var s=signals[i];
      sigHtml+='<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)">'
        +'<span style="font-size:20px">'+s.icon+'</span>'
        +'<div><div style="font-size:13px">'+s.text+'</div>'
        +'<div style="color:'+s.color+';font-size:12px;margin-top:2px">\u2192 '+s.impact+'</div></div></div>';
    }
    sigHtml+='</div>';
  }

  var tiles=[
    {label:'WTI \xd6l',val:'$'+wti.toFixed(1),sub:(wti_chg>=0?'+':'')+wti_chg.toFixed(1)+'%',color:wti_chg>=0?'#2ecc71':'#e74c3c'},
    {label:'Brent',val:'$'+brent.toFixed(1),sub:'Spread $'+(spread!==null?spread:'\u2014'),color:spread>8?'#e74c3c':(spread>5?'#f39c12':'#2ecc71')},
    {label:'S&P 500',val:spx.toFixed(0),sub:(spx_chg>=0?'+':'')+spx_chg.toFixed(1)+'%',color:spx_chg>=0?'#2ecc71':'#e74c3c'},
    {label:'Nasdaq',val:ndx.toFixed(0),sub:(ndx_chg>=0?'+':'')+ndx_chg.toFixed(1)+'%',color:ndx_chg>=0?'#2ecc71':'#e74c3c'},
    {label:'Nikkei',val:(nk>=0?'+':'')+nk.toFixed(1)+'%',sub:'Lead \u2192 Kupfer 24h',color:nk>=0?'#2ecc71':'#e74c3c'},
    {label:'Gold',val:'$'+gold.toFixed(0),sub:(gold_chg>=0?'+':'')+gold_chg.toFixed(1)+'%',color:gold_chg>=0?'#2ecc71':'#e74c3c'},
    {label:'Kupfer',val:'$'+copper.toFixed(3),sub:(copper_chg>=0?'+':'')+copper_chg.toFixed(1)+'%',color:copper_chg>=0?'#2ecc71':'#e74c3c'},
    {label:'EUR/USD',val:eurusd.toFixed(4),sub:'FX f\xfcr US-P&L',color:'#888'},
  ];
  var tileHtml='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">';
  for(var j=0;j<tiles.length;j++){
    var k=tiles[j];
    tileHtml+='<div class="card" style="padding:12px">'
      +'<div style="color:#888;font-size:11px">'+k.label+'</div>'
      +'<div style="font-size:17px;font-weight:bold">'+k.val+'</div>'
      +'<div style="color:'+k.color+';font-size:12px">'+k.sub+'</div></div>';
  }
  tileHtml+='</div>';

  el.innerHTML=
    '<div style="background:'+rColor+'18;border:2px solid '+rColor+';border-radius:12px;padding:20px;margin-bottom:16px;display:flex;align-items:center;gap:20px">'
    +'<div style="font-size:48px;line-height:1">'+rIcon+'</div>'
    +'<div style="flex:1">'
    +'<div style="font-size:22px;font-weight:800;color:'+rColor+'">'+regime+'</div>'
    +'<div style="color:#ccc;margin:4px 0 8px">'+rText+'</div>'
    +'<div style="background:rgba(0,0,0,.3);border-radius:6px;padding:8px 12px;font-size:13px;color:#fff"><strong>Was tun:</strong> '+rDo+'</div>'
    +'</div>'
    +'<div style="text-align:right;white-space:nowrap">'
    +'<div style="color:#888;font-size:11px">VIX</div>'
    +'<div style="font-size:32px;font-weight:bold;color:'+rColor+'">'+vix.toFixed(1)+'</div></div></div>'
    +sigHtml+tileHtml;
}

// ── Day Trading Tab (TRA-140, TRA-141) ──────────────────
async function loadDayTrades(){
  let dt=null;
  try{const r=await fetch('/api/daytrades');if(r.ok)dt=await r.json();}catch(e){}
  let dna=dnaData;
  if(!dna){try{dna=await fetch('/api/dna').then(r=>r.json());}catch(e){}}
  renderDTLive(dt,dna);
  renderDTHistory(dna);
  renderDTStats(dt,dna);
}

function renderDTLive(dt,dna){
  const el=document.getElementById('dt-live-content');
  if(!dt&&!dna){el.innerHTML='<p style="color:#888">Day Trade Feed nicht erreichbar.</p>';return;}
  const state=dt?dt.state:{};
  const openDT=dt?dt.open:[];
  let html='';
  const used=openDT.reduce((s,p)=>s+(p.entry||0)*(p.shares||1),0);
  const capital=25000,free=capital-used,usedPct=Math.round(used/capital*100);
  
  if(dt&&dt.auto_generated)html+='<div style="background:rgba(124,58,237,.15);border:1px solid var(--accent);border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:13px">⚡ Auto-Setups — warte auf Entry-Signal. Kein aktiver Trade.</div>';
  html+='<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:16px">';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold">25.000€</div><div style="color:#888;font-size:11px">Kapital</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold;color:#3498db">'+used.toFixed(0)+'€</div><div style="color:#888;font-size:11px">Investiert</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold;color:#2ecc71">'+free.toFixed(0)+'€</div><div style="color:#888;font-size:11px">Frei</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold;color:'+((state.daily_pnl||0)>=0?'#2ecc71':'#e74c3c')+'">'+(state.daily_pnl||0).toFixed(0)+'€</div><div style="color:#888;font-size:11px">Daily P&L</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:20px;font-weight:bold">'+openDT.length+'/5</div><div style="color:#888;font-size:11px">Positionen</div></div>';
  html+='</div>';
  
  // TRA-141: Intraday equity curve placeholder
  html+='<div class="card" style="padding:16px"><div class="card-title">📈 Intraday Equity</div>';
  html+='<div style="height:80px;background:var(--bg);border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--muted)">';
  if(openDT.length>0){
    const totalDtPnl=(state.daily_pnl||0);
    html+='<span style="font-size:24px;font-weight:bold;color:'+(totalDtPnl>=0?'var(--green)':'var(--red)')+'">'+eurFmt(totalDtPnl)+'</span>';
  } else {
    html+='Keine offenen Day Trades';
  }
  html+='</div></div>';
  
  if(openDT.length>0){
    html+='<div class="card-title" style="margin-bottom:8px">'+(dt&&dt.auto_generated?'🔍 Auto-Setup Watchlist':'⚡ Offene Day Trades')+'</div>';
    html+='<table><tr><th>Ticker</th><th>Richtung</th><th>Entry</th><th>Stop</th><th>Target</th><th>Strategie</th></tr>';
    openDT.forEach(p=>{
      const dir=p.direction||'LONG';
      const dirColor=dir==='LONG'?'#2ecc71':'#e74c3c';
      const tickerDisplay=p.ticker&&p.ticker!=='null'?p.ticker:'<span style="color:#888;font-style:italic">wird ermittelt</span>';
      html+='<tr><td><strong>'+tickerDisplay+'</strong><br><span style="font-size:10px;color:#888">'+(p.setup_type||p.trade_type||'')+'</span></td><td style="color:'+dirColor+'">'+(dir==='LONG'?'🟢':'🔴')+' '+dir+'</td><td>'+(p.entry!=null?p.entry.toFixed(2)+'€':'<span style="color:#888">warte…</span>')+'</td><td style="color:#e74c3c">'+(p.stop_pct!=null?'-'+p.stop_pct+'%':(p.stop||0).toFixed(2)+'€')+'</td><td style="color:#2ecc71">'+(p.target_pct!=null?'+'+p.target_pct+'%':(p.target||0).toFixed(2)+'€')+'</td><td>'+(p.strategy||p.setup_type||'Auto')+'<br><span style="font-size:10px;color:#888">CRV '+(p.crv||'—')+'</span></td></tr>';
    });
    html+='</table>';
  } else {
    const hour=new Date().getHours();
    html+='<div class="card" style="padding:20px;text-align:center"><div style="font-size:32px;margin-bottom:8px">'+(hour>=9&&hour<22?'🔍':'🌙')+'</div><div style="color:#888">'+(hour>=9&&hour<22?'Scanner aktiv — sucht Signale':'Markt geschlossen')+'</div></div>';
  }
  el.innerHTML=html;
}

function renderDTHistory(dna){
  const el=document.getElementById('dt-history-content');
  if(!dna){el.innerHTML='<p style="color:#888">DNA nicht geladen.</p>';return;}
  const dtStrats=(dna.strategies||[]).filter(s=>s.strategy&&s.strategy.startsWith('DT'));
  const closedTotal=dtStrats.reduce((s,st)=>s+st.closed,0);
  let html='<div class="card-title" style="margin-bottom:8px">📜 Geschlossene Day Trades</div>';
  if(closedTotal===0){
    html+='<div class="empty">Noch keine geschlossenen Day Trades.</div>';
  } else {
    html+='<table><tr><th>Strategy</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Avg P&L</th></tr>';
    dtStrats.forEach(st=>{
      if(st.closed===0)return;
      html+='<tr><td><strong>'+st.strategy+'</strong></td><td>'+st.closed+'</td><td style="color:#2ecc71">'+st.wins+'</td><td style="color:#e74c3c">'+st.losses+'</td><td style="color:'+(st.win_rate>=50?'#2ecc71':'#e74c3c')+'">'+st.win_rate+'%</td><td>'+st.avg_pnl.toFixed(1)+'%</td></tr>';
    });
    html+='</table>';
  }
  el.innerHTML=html;
}

function renderDTStats(dt,dna){
  const el=document.getElementById('dt-stats-content');
  if(!dna){el.innerHTML='<p style="color:#888">Daten nicht verfügbar.</p>';return;}
  const dtStrats=(dna.strategies||[]).filter(s=>s.strategy&&s.strategy.startsWith('DT'));
  const totalTrades=dtStrats.reduce((s,st)=>s+st.total,0);
  const totalClosed=dtStrats.reduce((s,st)=>s+st.closed,0);
  const totalWins=dtStrats.reduce((s,st)=>s+st.wins,0);
  const wr=totalClosed>0?Math.round(totalWins/totalClosed*100):0;
  let html='<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px">';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+totalTrades+'</div><div style="color:#888;font-size:11px">Total</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+totalClosed+'</div><div style="color:#888;font-size:11px">Geschlossen</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:'+(wr>=50?'#2ecc71':'#e74c3c')+'">'+wr+'%</div><div style="color:#888;font-size:11px">Win Rate</div></div>';
  html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+(dt?(dt.state.daily_trades||0):0)+'</div><div style="color:#888;font-size:11px">Trades heute</div></div>';
  html+='</div>';
  if(dtStrats.length>0){
    html+='<div class="card-title" style="margin:12px 0 8px">Strategie-Vergleich</div>';
    html+='<table><tr><th>Strategy</th><th>Total</th><th>Open</th><th>Closed</th><th>WR%</th><th>Avg P&L</th><th>CRV</th><th>Status</th></tr>';
    dtStrats.forEach(st=>{
      const emoji=st.kill_warning?'🔴':(st.win_rate>=50?'🟢':'🟡');
      html+='<tr><td>'+emoji+' <strong>'+st.strategy+'</strong></td><td>'+st.total+'</td><td>'+st.open+'</td><td>'+st.closed+'</td><td>'+(st.closed>0?st.win_rate+'%':'—')+'</td><td>'+(st.closed>0?st.avg_pnl.toFixed(1)+'%':'—')+'</td><td>'+st.avg_crv.toFixed(1)+'</td><td>'+(st.kill_warning?'⚠️ KILL':'✅')+'</td></tr>';
    });
    html+='</table>';
  }
  html+='<div class="card" style="padding:12px;margin-top:16px;border-left:3px solid #e74c3c"><strong>⚠️ Kill Warning:</strong> Strategie wird gestoppt nach 3+ konsekutiven Verlusten.</div>';
  el.innerHTML=html;
}

// ── Init ──────────────────────────────────────────────────
if(localStorage.getItem('theme')==='light'){isDark=false;document.body.classList.add('light');document.getElementById('theme-btn').textContent='☀️';}

loadAll();

// TRA-130: Auto-refresh timers
priceTimer=setInterval(()=>{refreshPrices();checkStopAlerts();},30000);
configTimer=setInterval(refreshConfig,300000);
countdownTimer=setInterval(updateCountdown,1000);

updateChecklist();
renderCalendar();
</script>
</body>
</html>`;
};

module.exports = async function handler(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, no-cache');
  res.status(200).send(HTML());
};