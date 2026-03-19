// TradeMind Pro v2 — Vollständiges Trading Dashboard
// Tabs: Real | Paper | News | Watchlist | Kalender | Risiko | Signale | DNA | Macro
// Build: 2026-03-19 21:12 CET

const PAPER = [
  {ticker:'ASML.AS',  name:'ASML Holding',          entry:1187.60, strategy:'PS3', stop:1100.0, target:1380.0},
  {ticker:'DHT',      name:'DHT Holdings',           entry:14.74,   strategy:'PS2', stop:13.5,   target:18.0},
  {ticker:'FRO',      name:'Frontline',              entry:26.40,   strategy:'PS2', stop:24.0,   target:33.0},
  {ticker:'GLEN.L',   name:'Glencore',               entry:6.07,    strategy:'PS5', stop:5.5,    target:7.5},
  {ticker:'HL',       name:'Hecla Mining',           entry:17.15,   strategy:'PS4', stop:14.5,   target:23.0},
  {ticker:'HO.PA',    name:'Thales',                 entry:254.40,  strategy:'PS3', stop:230.0,  target:310.0},
  {ticker:'MOS',      name:'Mosaic',                 entry:25.38,   strategy:'PS5', stop:23.0,   target:32.0},
  {ticker:'NOVO-B.CO',name:'Novo Nordisk',           entry:32.32,   strategy:'PS1', stop:29.0,   target:42.0},
  {ticker:'OXY',      name:'Occidental Petroleum',   entry:50.63,   strategy:'PS1', stop:46.0,   target:64.0},
  {ticker:'PAAS',     name:'Pan American Silver',    entry:49.09,   strategy:'PS4', stop:42.0,   target:64.0},
  {ticker:'TTE.PA',   name:'TotalEnergies',          entry:74.48,   strategy:'PS1', stop:68.0,   target:92.0},
];

const STRATEGIES = [
  {id:'PS1',color:'#3498db',name:'Iran/Öl-Geopolitik',status:'🟢',conviction:'Hoch',tickers:['OXY','TTE.PA','NOVO-B.CO'],desc:'Hormuz-Bedrohung → Öl teuer → Ölproduzenten profitieren.<br><br><strong>Kernthese:</strong> Iran + Houthi = Ölpreis-Versicherungsprämie.<br><strong>Ausstieg:</strong> Iran-Deal oder WTI dauerhaft &lt; 70$.'},
  {id:'PS2',color:'#e67e22',name:'Tanker-Lag-These',status:'🟢',conviction:'Mittel',tickers:['FRO','DHT'],desc:'Öl steigt → Tanker folgen mit 2–4W Verzögerung.<br><br><strong>Kernthese:</strong> Steigende Ölpreise → höhere Frachtraten → Tanker-Aktien ziehen nach.<br><strong>Ausstieg:</strong> Öl &lt; 70$ oder Frachtraten kollabieren.'},
  {id:'PS3',color:'#2ecc71',name:'NATO/EU-Rüstung',status:'🟡',conviction:'Mittel',tickers:['ASML.AS','HO.PA'],desc:'Verteidigungsbudgets steigen → Rüstungs- und Dual-Use-Firmen gewinnen.<br><br><strong>Kernthese:</strong> 2%-BIP-Ziel NATO → ASML, Thales.<br><strong>Risiko:</strong> Ukraine-Waffenstillstand.'},
  {id:'PS4',color:'#f1c40f',name:'Edelmetalle/Miner',status:'🟡',conviction:'Mittel',tickers:['HL','PAAS'],desc:'VIX hoch + Geopolitik → Gold/Silber → Miner überproportional.<br><br><strong>Kernthese:</strong> Miner = gehebelte Metallwette. Gold +20% → Miner +40–60%.<br><strong>Ausstieg:</strong> VIX &lt; 18, Gold &lt; 2.500$.'},
  {id:'PS5',color:'#8b4513',name:'Dünger/Agrar-Superzyklus',status:'🟡',conviction:'Niedrig',tickers:['MOS','GLEN.L'],desc:'Russische Kali-Sanktionen → westliche Düngerproduzenten profitieren.<br><br><strong>Kernthese:</strong> Belarus+Russland = 40% globales Kali = struktureller Engpass.<br><strong>Risiko:</strong> Sanktionslockerung.'},
];

const EARNINGS = [
  {ticker:'MSFT',   name:'Microsoft',   date:'2026-04-29', type:'earnings'},
  {ticker:'NVDA',   name:'Nvidia',      date:'2026-05-28', type:'earnings'},
  {ticker:'PLTR',   name:'Palantir',    date:'2026-05-05', type:'earnings'},
  {ticker:'BAYN.DE',name:'Bayer',       date:'2026-05-06', type:'earnings'},
  {ticker:'EQNR',   name:'Equinor',     date:'2026-05-08', type:'earnings'},
  {ticker:'RIO.L',  name:'Rio Tinto',   date:'2026-07-30', type:'earnings'},
];

const MACRO_EVENTS = [
  {name:'US NFP',        date:'2026-04-03', desc:'Non-Farm Payrolls'},
  {name:'US CPI',        date:'2026-04-10', desc:'Inflationsdaten USA'},
  {name:'EZB Sitzung',   date:'2026-04-17', desc:'Zinsentscheidung Europa'},
  {name:'Fed FOMC',      date:'2026-04-29', desc:'Zinsentscheidung USA'},
  {name:'US NFP',        date:'2026-05-01', desc:'Non-Farm Payrolls'},
  {name:'Fed FOMC',      date:'2026-06-10', desc:'Zinsentscheidung USA'},
  {name:'EZB Sitzung',   date:'2026-06-05', desc:'Zinsentscheidung Europa'},
];

const SECTOR_MAP = {
  'NVDA':'KI/Tech','MSFT':'KI/Tech','PLTR':'KI/Tech','ASML.AS':'KI/Tech',
  'EQNR':'Energie','OXY':'Energie','TTE.PA':'Energie','FRO':'Energie','DHT':'Energie',
  'RIO.L':'Rohstoffe','GLEN.L':'Rohstoffe','MOS':'Rohstoffe',
  'HL':'Edelmetalle','PAAS':'Edelmetalle',
  'BAYN.DE':'Pharma','NOVO-B.CO':'Pharma',
  'HO.PA':'Rüstung',
};
const SECTOR_COLORS = {
  'KI/Tech':'#7c3aed','Energie':'#e67e22','Rohstoffe':'#8b4513',
  'Edelmetalle':'#f1c40f','Pharma':'#2ecc71','Rüstung':'#3498db',
};
const CORR_GROUPS = [
  {name:'KI/Halbleiter',color:'#7c3aed',tickers:['NVDA','MSFT','PLTR','ASML.AS']},
  {name:'Öl/Energie',   color:'#e67e22',tickers:['OXY','TTE.PA','EQNR']},
  {name:'Tanker',        color:'#3498db',tickers:['FRO','DHT']},
  {name:'Silber/Miner',  color:'#f1c40f',tickers:['HL','PAAS']},
  {name:'Agrar/Dünger',  color:'#2ecc71',tickers:['MOS','GLEN.L']},
];
const SECTOR_VOL = {'KI/Tech':0.028,'Energie':0.022,'Rohstoffe':0.020,'Edelmetalle':0.025,'Pharma':0.016,'Rüstung':0.018};
const TV_MAP = {
  'NVDA':'NASDAQ:NVDA','MSFT':'NASDAQ:MSFT','PLTR':'NYSE:PLTR',
  'EQNR':'OSL:EQNR','EQNR.OL':'OSL:EQNR','RIO.L':'LSE:RIO',
  'BAYN.DE':'XETR:BAYN','ASML.AS':'AMS:ASML','FRO':'NYSE:FRO',
  'DHT':'NYSE:DHT','OXY':'NYSE:OXY','PAAS':'NYSE:PAAS','HL':'NYSE:HL',
  'MOS':'NYSE:MOS','TTE.PA':'EURONEXT:TTE','HO.PA':'EURONEXT:HO',
  'GLEN.L':'LSE:GLEN','NOVO-B.CO':'CPH:NOVO B','AG':'NYSE:AG','RHM.DE':'XETR:RHM','BHP.L':'LSE:BHP',
};

const HTML = () => {
const pj=JSON.stringify(PAPER),sj=JSON.stringify(STRATEGIES),ej=JSON.stringify(EARNINGS);
const mej=JSON.stringify(MACRO_EVENTS),smj=JSON.stringify(SECTOR_MAP),scj=JSON.stringify(SECTOR_COLORS);
const cgj=JSON.stringify(CORR_GROUPS),svj=JSON.stringify(SECTOR_VOL),tvj=JSON.stringify(TV_MAP);
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
.cal-info{}
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
</header>

<div class="main-nav">
  <button class="active" onclick="showMain('real',this)">📈 Real</button>
  <button onclick="showMain('paper',this)">🧪 Paper</button>
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
      <div class="card-title">📐 Positionsgröße</div>
      <div class="form-row">
        <div class="ff"><label>Kontostand (€)</label><input id="ps-account" type="number" value="5000" oninput="calcSizing()"></div>
        <div class="ff"><label>Risiko %</label><input id="ps-risk" type="number" value="1" step="0.1" oninput="calcSizing()"></div>
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
</div>

<!-- PAPER TRADES -->
<div id="main-paper" class="main-panel">
  <div class="sub-nav">
    <button class="active" onclick="showSub('paper','positions',this)">📋 Positionen</button>
    <button onclick="showSub('paper','performance',this)">📊 Performance</button>
    <button onclick="showSub('paper','entry',this)">➕ Eintragen</button>
    <button onclick="showSub('paper','strat',this)">🧠 Strategien</button>
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
          <select id="pl-strat" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:6px;width:100%">
            <option value="PS1">PS1 — Iran/Öl</option><option value="PS2">PS2 — Tanker</option>
            <option value="PS3">PS3 — Rüstung</option><option value="PS4">PS4 — Edelmetalle</option>
            <option value="PS5">PS5 — Dünger</option>
          </select>
        </div>
        <div class="ff" style="flex:2"><label>Notiz</label><input id="pl-notes" placeholder="Begründung"></div>
      </div>
      <button class="btn btn-primary" onclick="logPaperTrade()">💾 Speichern</button>
      <span id="pl-status" class="save-msg"></span>
    </div>
  </div>
  <div id="paper-strat" class="sub-panel"><div id="strat-list"></div></div>
</div>

<!-- NEWS -->
<div id="main-news" class="main-panel">
  <div style="padding:12px 14px">
    <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap" id="news-filter"></div>
    <div id="news-list"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- WATCHLIST -->
<div id="main-watchlist" class="main-panel">
  <div style="padding:12px 14px">
    <div class="info-box">📌 Entry-Zone: <span class="green">grün</span> = Kurs unter Zone (gutes Entry), <span class="orange">orange</span> = in der Zone, <span class="red">rot</span> = darüber (verpasst).</div>
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
  </div>
  <div id="risk-exposure" class="sub-panel active">
    <div id="exposure-content"><div class="loading">Lädt…</div></div>
  </div>
  <div id="risk-corr" class="sub-panel">
    <div id="corr-content"><div class="loading">Lädt…</div></div>
  </div>
  <div id="risk-var" class="sub-panel">
    <div id="var-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- SIGNALS TAB -->
<div id="main-signals" class="main-panel">
  <div class="card"><div class="card-title">📡 Signal Engine — Aktive Lead-Lag Signale</div>
    <div id="signals-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- ANALYTICS/DNA TAB -->
<div id="main-analytics" class="main-panel">
  <div class="card"><div class="card-title">📊 Strategy DNA — Lernende Analyse</div>
    <div id="analytics-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- MACRO TAB -->
<div id="main-macro" class="main-panel">
  <div class="card"><div class="card-title">🌍 Macro Dashboard — 14 Indikatoren, 5 Jahre</div>
    <div id="macro-content"><div class="loading">Lädt…</div></div>
  </div>
</div>

<script>
const PAPER=${pj},STRATEGIES=${sj},EARNINGS=${ej},MACRO_EVENTS=${mej};
const SECTOR_MAP=${smj},SECTOR_COLORS=${scj},CORR_GROUPS=${cgj},SECTOR_VOL=${svj},TV_MAP=${tvj};
let cfg=null,prices=null,tradeAction='BUY',paperAction='BUY';
let newsLoaded=false,histLoaded=false,allNews=[],tradeHistory=[];

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
  panel.querySelectorAll('.sub-panel').forEach(p=>p.classList.remove('active'));
  panel.querySelectorAll('.sub-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(main+'-'+sub).classList.add('active');
  btn.classList.add('active');
}

// ── Helpers ──────────────────────────────────────────────
function pct(v,b){return b?((v-b)/b*100):null}
function pctHtml(v,bold=false){
  if(v==null)return'<span class="muted">—</span>';
  const c=v>=0?'green':'red',s=v>=0?'▲ +':'▼ ';
  return \`<span class="\${c}"\${bold?' style="font-weight:700"':''}>\${s}\${Math.abs(v).toFixed(1)}%</span>\`;
}
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
function tvLink(ticker){const tv=TV_MAP[ticker]||TV_MAP[ticker?.split('.')[0]];return tv?\`https://www.tradingview.com/chart/?symbol=\${tv}\`:'#';}

// ── Main Load ─────────────────────────────────────────────
async function loadAll(){
  document.getElementById('ts').textContent='⏳';
  try{
    [cfg,prices]=await Promise.all([
      fetch('/api/config').then(r=>r.json()),
      fetch('/api/prices').then(r=>r.json()),
    ]);
    renderMacro(prices);renderSummary(cfg,prices);renderReal(cfg,prices);
    renderEdit(cfg,prices);renderPaper(prices);renderStratPerf(prices);renderStrat();
    updateChecklist();
    document.getElementById('ts').textContent=new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
  }catch(e){document.getElementById('ts').textContent='⚠️ '+e.message;}
}

// ── Macro ─────────────────────────────────────────────────
function renderMacro(p){
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

// ── Portfolio Summary ─────────────────────────────────────
function renderSummary(cfg,prices){
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  let winning=0,danger=0,noStop=0,sumPnl=0,cnt=0;
  pos.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur??null;
    const pnl=pct(eur,p.entry_eur);
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)winning++;}
    if(!p.stop_eur)noStop++;
    else if(eur&&(eur-p.stop_eur)/eur*100<5)danger++;
  });
  const avg=cnt?sumPnl/cnt:0;
  document.getElementById('portfolio-summary').innerHTML=\`
    <div class="scard"><div class="scard-label">Positionen</div><div class="scard-val">\${pos.length}</div><div class="scard-sub muted">\${winning} im Plus</div></div>
    <div class="scard"><div class="scard-label">Ø P&amp;L</div><div class="scard-val \${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="scard" style="\${danger>0?'border-color:rgba(248,81,73,.4)':''}"><div class="scard-label">Stop &lt;5%</div><div class="scard-val \${danger>0?'orange':''}">\${danger}</div><div class="scard-sub \${danger>0?'red':'muted'}">Achtung</div></div>
    <div class="scard" style="\${noStop>0?'border-color:rgba(248,81,73,.4)':''}"><div class="scard-label">Kein Stop</div><div class="scard-val \${noStop>0?'red':''}">\${noStop}</div><div class="scard-sub muted">⚠️ Risiko</div></div>
  \`;
  const dangerPos=pos.filter(p=>{const eur=getP(px,p.ticker)?.eur;return p.stop_eur&&eur&&(eur-p.stop_eur)/eur*100<5;});
  document.getElementById('alert-box').innerHTML=dangerPos.length?\`<div class="alert-box">⚠️ <strong>Stop-Alarm:</strong> \${dangerPos.map(p=>{const d=getP(px,p.ticker)?.eur?((getP(px,p.ticker).eur-p.stop_eur)/getP(px,p.ticker).eur*100).toFixed(1):'?';return\`<strong>\${p.ticker}</strong> (\${d}% vom Stop)\`;}).join(' · ')}</div>\`:'';
}

// ── Real Portfolio Table ──────────────────────────────────
function renderReal(cfg,prices){
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  const rows=pos.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry_eur);
    const tv=tvLink(p.ticker);
    return \`<tr>
      <td><div class="ticker-name" onclick="window.open('\${tv}','_blank')" title="TradingView öffnen">\${p.ticker} ↗</div><div class="ticker-sub">\${p.name||''}</div></td>
      <td class="muted">\${p.entry_eur?.toFixed(2)??'—'}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(chg)}</td>
      <td>\${pctHtml(pnl,true)}</td>
      <td>\${stopCell(eur,p.stop_eur)}</td>
      <td>\${crvHtml(eur,p.stop_eur,p.target_eur)}</td>
    </tr>\`;
  });
  document.getElementById('real-table').innerHTML=\`<table><thead><tr><th>Position ↗TV</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&amp;L</th><th>Stop</th><th>CRV</th></tr></thead><tbody>\${rows.join('')||'<tr><td colspan="7" class="muted" style="text-align:center;padding:18px">Keine offenen Positionen</td></tr>'}</tbody></table>\`;
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
    return \`<tr><td class="muted" style="font-size:11px">\${date}</td><td>\${badge}</td><td><strong>\${t.ticker}</strong></td><td>\${t.price_eur?.toFixed(2)??'—'}€</td><td class="muted" style="font-size:12px">\${t.stop_eur?t.stop_eur+'€':'—'}</td><td class="muted" style="font-size:12px">\${t.target_eur?t.target_eur+'€':'—'}</td><td class="muted" style="font-size:11px;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">\${t.notes||''}</td></tr>\`;
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

// ── Paper Trades ──────────────────────────────────────────
function renderPaper(prices){
  const px=prices.prices||{};
  let sumPnl=0,wins=0,cnt=0;
  const CASH=71,PCAP=900;
  const posData=PAPER.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry);
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)wins++;}
    return{...p,eur,chg,pnl};
  });
  const avg=cnt?sumPnl/cnt:0,wr=cnt?(wins/cnt*100):0;
  const curVal=Math.round(PCAP*(1+avg/100)+CASH),diff=curVal-1000;
  document.getElementById('paper-stats').innerHTML=\`
    <div class="stat"><div class="stat-label">Startkapital</div><div class="stat-value">1.000€</div></div>
    <div class="stat"><div class="stat-label">Akt. Wert</div><div class="stat-value \${curVal>=1000?'green':'red'}">\${curVal}€</div><div class="stat-sub \${diff>=0?'green':'red'}">\${diff>=0?'+':''}\${diff}€</div></div>
    <div class="stat"><div class="stat-label">Ø P&amp;L</div><div class="stat-value \${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="stat"><div class="stat-label">Win-Rate</div><div class="stat-value">\${wr.toFixed(0)}%</div><div class="stat-sub muted">\${wins}/\${cnt}</div></div>
    <div class="stat"><div class="stat-label">Cash</div><div class="stat-value">\${CASH}€</div></div>
  \`;
  // Heatmap
  document.getElementById('paper-heatmap').innerHTML=\`<div class="heat-grid">\${posData.map(p=>{
    const v=p.pnl,tv=tvLink(p.ticker);
    const bg=v==null?'var(--surface)':v>=0?\`rgba(63,185,80,\${0.1+Math.min(Math.abs(v)*3,100)/300})\`:\`rgba(248,81,73,\${0.1+Math.min(Math.abs(v)*3,100)/300})\`;
    return\`<div class="heat-cell" style="background:\${bg}" onclick="window.open('\${tv}','_blank')" title="TradingView">
      <div class="heat-ticker">\${p.ticker.split('.')[0]}</div>
      <div class="heat-pnl" style="color:\${v==null?'var(--muted)':v>=0?'var(--green)':'var(--red)'}">\${v!=null?(v>=0?'+':'')+v.toFixed(1)+'%':'—'}</div>
    </div>\`;
  }).join('')}</div>\`;
  // Table
  document.getElementById('paper-table').innerHTML=\`<table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&amp;L</th><th>Stop/Ziel</th><th>CRV</th></tr></thead><tbody>\${posData.map(p=>{
    const s=STRATEGIES.find(s=>s.id===p.strategy);
    const badge=s?\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${p.strategy}</span>\`:'';
    return\`<tr><td><div class="ticker-name" onclick="window.open('\${tvLink(p.ticker)}','_blank')">\${p.ticker} ↗</div><div class="ticker-sub">\${p.name} \${badge}</div></td>
      <td class="muted">\${p.entry.toFixed(2)}€</td><td>\${p.eur!=null?\`<strong>\${p.eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(p.chg)}</td><td>\${pctHtml(p.pnl,true)}</td>
      <td class="muted" style="font-size:11px">\${p.stop||'—'}€/\${p.target||'—'}€</td>
      <td>\${crvHtml(p.eur,p.stop,p.target)}</td></tr>\`;
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
      <div style="flex:1"><div style="font-weight:600">\${s.status} \${s.name}</div><div class="strat-meta">Überzeugung: \${s.conviction} · \${s.tickers.join(', ')}</div></div>
      <div class="chev" id="chev-\${i}">▼</div>
    </div>
    <div class="strat-body" id="sbody-\${i}">\${s.desc}<div class="tickers-row">\${s.tickers.map(t=>\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${t}</span>\`).join('')}</div></div>
  </div>\`).join('');
}
function toggleStrat(i){document.getElementById('sbody-'+i).classList.toggle('open');document.getElementById('chev-'+i).classList.toggle('open');}

// ── News ──────────────────────────────────────────────────
let newsFilter='ALL';
async function loadNews(){
  if(newsLoaded)return;
  document.getElementById('news-list').innerHTML='<div class="loading">Lädt…</div>';
  try{
    const tickers=cfg?(cfg.positions||[]).filter(p=>p.status!=='CLOSED').map(p=>p.ticker).slice(0,5).join(','):'NVDA,EQNR,RIO';
    const d=await fetch(\`/api/news?tickers=\${tickers}\`).then(r=>r.json());
    allNews=d.news||[];renderNews('ALL');newsLoaded=true;
  }catch(e){document.getElementById('news-list').innerHTML=\`<div class="empty">⚠️ \${e.message}</div>\`;}
}
function renderNews(filter){
  newsFilter=filter;
  const tickers=['ALL','MACRO',...new Set(allNews.filter(n=>n.ticker!=='MACRO').map(n=>n.ticker))];
  document.getElementById('news-filter').innerHTML=tickers.map(t=>\`<button class="filter-btn \${t===filter?'active':''}" onclick="renderNews('\${t}')">\${t==='ALL'?'Alle':t==='MACRO'?'🌍 Makro':t}</button>\`).join('');
  const filtered=filter==='ALL'?allNews:allNews.filter(n=>n.ticker===filter);
  if(!filtered.length){document.getElementById('news-list').innerHTML='<div class="empty">Keine News</div>';return;}
  document.getElementById('news-list').innerHTML=filtered.map(n=>{
    const time=n.time?new Date(n.time).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'';
    const tc=n.ticker==='MACRO'?'#58a6ff':'#7c3aed';
    return\`<div class="news-item"><div class="news-title"><a href="\${n.url}" target="_blank" rel="noopener">\${n.title}</a></div>
      <div class="news-meta"><span class="badge" style="background:\${tc}22;color:\${tc}">\${n.ticker}</span><span>\${n.source||''}</span><span>\${time}</span></div></div>\`;
  }).join('');
}

// ── Watchlist ─────────────────────────────────────────────
function renderWatchlist(){
  const wl=cfg?.watchlist||[];
  if(!wl.length){document.getElementById('watchlist-content').innerHTML='<div class="empty">Keine Watchlist-Einträge in Config</div>';return;}
  const px=prices?.prices||{};
  document.getElementById('watchlist-content').innerHTML=wl.map(w=>{
    const pr=getP(px,w.ticker)??getP(px,w.ticker?.replace('.AS','')?.replace('.L','')?.replace('.DE',''));
    const eur=pr?.eur??null,chg=pr?.dayChange??null;
    let status='—',statusColor='var(--muted)',label='';
    if(eur!=null){
      if(eur<w.entryMin){status='🟢 Unter Zone';statusColor='var(--green)';label='Gutes Entry-Niveau';}
      else if(eur<=w.entryMax){status='🟡 In Zone';statusColor='var(--orange)';label='Entry-Zone aktiv!';}
      else{status='🔴 Über Zone';statusColor='var(--red)';label='Entry verpasst';}
    }
    const tv=tvLink(w.ticker);
    return\`<div class="wl-item">
      <div><div class="wl-ticker" onclick="window.open('\${tv}','_blank')" title="TradingView">\${w.ticker} ↗</div><div class="wl-zone muted">\${w.entryMin}€ – \${w.entryMax}€</div></div>
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

  // Earnings
  const upcoming=EARNINGS.filter(e=>e.date>=today).sort((a,b)=>a.date.localeCompare(b.date));
  document.getElementById('cal-earnings').innerHTML=upcoming.length?upcoming.map(e=>{
    const d=new Date(e.date),days=Math.ceil((d-now)/86400000);
    const col=days<7?'var(--red)':days<14?'var(--orange)':'var(--green)';
    const held=heldTickers.has(e.ticker)||heldTickers.has(e.ticker+'.OL');
    return\`<div class="cal-event" style="\${held?'border-color:var(--accent)':''}">
      <div class="cal-date" style="color:\${col}"><div class="cal-day">\${String(d.getDate()).padStart(2,'0')}</div><div class="cal-month">\${d.toLocaleString('de-DE',{month:'short'})}</div></div>
      <div class="cal-info"><div class="cal-name">\${held?'⭐ ':''}\${e.name} (\${e.ticker})</div><div class="cal-desc">Quartalszahlen\${e.est?' (ca.)':''}</div></div>
      <span class="days-badge" style="background:\${col}22;color:\${col};margin-left:auto">in \${days}T</span>
    </div>\`;
  }).join(''):'<div class="empty">Keine bevorstehenden Earnings</div>';

  // Makro
  const macro=MACRO_EVENTS.filter(e=>e.date>=today).sort((a,b)=>a.date.localeCompare(b.date));
  document.getElementById('cal-macro').innerHTML=macro.length?macro.map(e=>{
    const d=new Date(e.date),days=Math.ceil((d-now)/86400000);
    const col=days<7?'var(--red)':days<14?'var(--orange)':'var(--green)';
    return\`<div class="cal-event">
      <div class="cal-date" style="color:\${col}"><div class="cal-day">\${String(d.getDate()).padStart(2,'0')}</div><div class="cal-month">\${d.toLocaleString('de-DE',{month:'short'})}</div></div>
      <div class="cal-info"><div class="cal-name">\${e.name}</div><div class="cal-desc">\${e.desc}</div></div>
      <span class="days-badge" style="background:\${col}22;color:\${col};margin-left:auto">in \${days}T</span>
    </div>\`;
  }).join(''):'<div class="empty">Keine bevorstehenden Events</div>';
}

// ── Risiko ────────────────────────────────────────────────
function renderRisk(){
  const pos=(cfg?.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices?.prices||{};

  // Exposure
  const sectorCount={};
  pos.forEach(p=>{const s=SECTOR_MAP[p.ticker]||'Sonstige';sectorCount[s]=(sectorCount[s]||0)+1;});
  const total=pos.length||1;
  document.getElementById('exposure-content').innerHTML=\`
    <div style="margin-bottom:16px">\${Object.entries(sectorCount).sort((a,b)=>b[1]-a[1]).map(([s,c])=>{
      const col=SECTOR_COLORS[s]||'#7d8590',pct=Math.round(c/total*100);
      return\`<div class="exposure-row">
        <div class="exposure-label"><span>\${s}</span><span style="color:\${col};font-weight:600">\${c} Pos. (\${pct}%)</span></div>
        <div class="exposure-bar" style="width:\${pct}%;background:\${col}22;border:1px solid \${col}44"><div style="height:100%;width:\${pct}%;background:\${col};border-radius:4px"></div></div>
      </div>\`;
    }).join('')}</div>
    <div class="info-box">\${sectorCount['KI/Tech']>=3?\`⚠️ <strong>Klumpen-Risiko:</strong> \${sectorCount['KI/Tech']} KI/Tech-Positionen — hohe Korrelation bei Sektor-Crash.\`:'✅ Sektorverteilung ok'}</div>\`;

  // Korrelation
  document.getElementById('corr-content').innerHTML=CORR_GROUPS.map(g=>{
    const held=pos.filter(p=>g.tickers.includes(p.ticker)||g.tickers.includes(p.ticker.replace('.OL','').replace('.DE','').replace('.L',''))).map(p=>p.ticker);
    if(!held.length)return'';
    const warn=held.length>=2;
    return\`<div class="corr-group" style="\${warn?'border-color:'+g.color+'66':''}">
      <div class="corr-title"><span class="badge" style="background:\${g.color}22;color:\${g.color}">\${g.name}</span>
        \${warn?\`<span style="color:\${g.color};font-size:12px;margin-left:8px">⚠️ \${held.length}× im Portfolio</span>\`:''}</div>
      <div class="corr-held">\${warn?'Im Portfolio: <strong>'+held.join(', ')+'</strong> — bewegen sich oft gleichzeitig':'Im Portfolio: '+held.join(', ')}</div>
    </div>\`;
  }).filter(Boolean).join('')||'<div class="empty">Keine Korrelations-Warnungen</div>';

  // VaR (vereinfacht, ohne Positionsgrößen)
  const sectorVaR=Object.entries(sectorCount).map(([s,c])=>{
    const vol=(SECTOR_VOL[s]||0.02);
    return{sector:s,count:c,vol:vol,dailyVaR95:(vol*1.645*100).toFixed(1)+'%'};
  });
  document.getElementById('var-content').innerHTML=\`
    <div class="info-box" style="margin-bottom:12px">📊 <strong>Value at Risk (95%):</strong> Geschätzter Max-Tagesverlust pro Position — vereinfacht (keine Positionsgrößen hinterlegt). Für genauen EUR-VaR: Investitionsbeträge in Config eintragen.</div>
    <div class="var-box">
      <table><thead><tr><th>Sektor</th><th>Pos.</th><th>Tages-Volatilität</th><th>VaR 95%/Tag</th></tr></thead>
      <tbody>\${sectorVaR.map(v=>\`<tr>
        <td><span class="badge" style="background:\${SECTOR_COLORS[v.sector]||'#7d8590'}22;color:\${SECTOR_COLORS[v.sector]||'#7d8590'}">\${v.sector}</span></td>
        <td class="muted">\${v.count}</td>
        <td class="muted">\${(v.vol*100).toFixed(1)}%</td>
        <td><span class="red">\${v.dailyVaR95}</span></td>
      </tr>\`).join('')}</tbody></table>
    </div>\`;
}

// ── Position Sizing ───────────────────────────────────────
function calcSizing(){
  const lPrice=document.getElementById('l-price')?.value;
  const lStop=document.getElementById('l-stop')?.value;
  if(lPrice)document.getElementById('ps-entry').value=lPrice;
  if(lStop)document.getElementById('ps-stop').value=lStop;
  const account=parseFloat(document.getElementById('ps-account')?.value)||5000;
  const riskPct=parseFloat(document.getElementById('ps-risk')?.value)||1;
  const e=parseFloat(document.getElementById('ps-entry')?.value);
  const s=parseFloat(document.getElementById('ps-stop')?.value);
  const el=document.getElementById('sizing-result');
  if(!e||!s||e<=s){el.style.display='none';return;}
  const riskEur=account*riskPct/100,rps=e-s,shares=Math.floor(riskEur/rps);
  const invest=shares*e,maxLoss=shares*rps;
  el.style.display='block';
  el.innerHTML=\`
    <div class="sizing-row"><span class="sizing-label">Risiko-Budget</span><span class="sizing-val red">\${riskEur.toFixed(0)}€ (\${riskPct}%)</span></div>
    <div class="sizing-row"><span class="sizing-label">Stückzahl</span><span class="sizing-val">\${shares} Stück</span></div>
    <div class="sizing-row"><span class="sizing-label">Einsatz</span><span class="sizing-val">\${invest.toFixed(0)}€ (\${(invest/account*100).toFixed(1)}% vom Konto)</span></div>
    <div class="sizing-row"><span class="sizing-label">Max. Verlust</span><span class="sizing-val red">−\${maxLoss.toFixed(0)}€</span></div>
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

// ── UX: Dark/Light + Notifications ────────────────────────
let isDark=true;
function toggleTheme(){
  isDark=!isDark;
  document.body.classList.toggle('light',!isDark);
  document.getElementById('theme-btn').textContent=isDark?'🌙':'☀️';
  localStorage.setItem('theme',isDark?'dark':'light');
}
function requestNotifications(){
  if(!('Notification' in window)){alert('Browser unterstützt keine Notifications');return;}
  Notification.requestPermission().then(p=>{
    if(p==='granted'){
      new Notification('TradeMind 🎩',{body:'Stop-Alerts aktiviert! Du wirst benachrichtigt wenn ein Stop gefährdet ist.',icon:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🎩</text></svg>'});
      document.getElementById('notif-btn').textContent='🔔✅';
    }
  });
}

// Stop-Alert via Notification
function checkStopAlerts(){
  if(!cfg||!prices||Notification.permission!=='granted')return;
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  pos.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur;
    if(p.stop_eur&&eur&&(eur-p.stop_eur)/eur*100<2){
      new Notification(\`⚠️ Stop-Alarm: \${p.ticker}\`,{body:\`Kurs \${eur.toFixed(2)}€ — Stop \${p.stop_eur}€ nur \${((eur-p.stop_eur)/eur*100).toFixed(1)}% entfernt!\`});
    }
  });
}

// ── Neue Tabs: Signals, Analytics, Macro ──

async function loadSignals(){
  const el=document.getElementById('signals-content');
  
  // Lead-Lag Paare (statisch)
  const pairs=[
    {id:'NIKKEI_COPPER',lead:'Nikkei 225',lag:'Copper Futures',lag_hours:24,desc:'Japan-Import → Rohstoffnachfrage'},
    {id:'VIX_TECH',lead:'VIX',lag:'PLTR',lag_hours:24,desc:'Volatilität → Tech-Selloff'},
    {id:'BRENT_WTI_SPREAD_EQNR',lead:'Brent-WTI Spread',lag:'EQNR.OL',lag_hours:12,desc:'Lieferunterbrechung → Nordsee-Produzent'},
    {id:'INPEX_WTI',lead:'WTI',lag:'INPEX (1605.T)',lag_hours:5,desc:'Öl→Japan-Ölproduzent'},
    {id:'IRAN_BRENT',lead:'Iran Eskalation',lag:'Brent',lag_hours:6,desc:'Geopolitik→Ölpreis'},
  ];

  let html='';

  // 1. Live Signal-Feed laden
  try{
    const r=await fetch('/api/signals');
    if(r.ok){
      const data=await r.json();
      const stats=data.stats||{};
      const sigs=data.signals||[];
      
      // Stats-Bar
      html+='<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:16px">';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+stats.total+'</div><div style="color:#888;font-size:11px">Signale</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#2ecc71">'+stats.wins+'</div><div style="color:#888;font-size:11px">✅ Wins</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#e74c3c">'+stats.losses+'</div><div style="color:#888;font-size:11px">❌ Losses</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold;color:#f39c12">'+stats.pending+'</div><div style="color:#888;font-size:11px">⏳ Pending</div></div>';
      html+='<div class="card" style="padding:10px;text-align:center"><div style="font-size:22px;font-weight:bold">'+(stats.accuracy_pct!=null?stats.accuracy_pct+'%':'—')+'</div><div style="color:#888;font-size:11px">Accuracy</div></div>';
      html+='</div>';
      
      // Signal-History
      if(sigs.length){
        html+='<div class="card-title" style="margin-bottom:8px">📡 Signal-History (neueste zuerst)</div>';
        html+='<table><tr><th>Zeit</th><th>Lead → Lag</th><th>Signal</th><th>Lag (h)</th><th>Outcome</th><th>Δ%</th><th>Confidence</th></tr>';
        sigs.forEach(s=>{
          const oc=s.outcome||'PENDING';
          const ocColor=oc==='WIN'?'#2ecc71':(oc==='LOSS'?'#e74c3c':'#f39c12');
          const ocEmoji=oc==='WIN'?'✅':(oc==='LOSS'?'❌':'⏳');
          const time=(s.created_at||'').replace('T',' ').slice(0,16);
          const chg=s.actual_change_pct!=null?(s.actual_change_pct>0?'+':'')+s.actual_change_pct+'%':'—';
          html+='<tr>';
          html+='<td style="font-size:12px;white-space:nowrap">'+time+'</td>';
          html+='<td>'+s.lead_name+' → '+s.lag_name+'</td>';
          html+='<td style="font-weight:bold">'+s.signal_value+'</td>';
          html+='<td>'+s.lag_hours+'h</td>';
          html+='<td style="color:'+ocColor+'">'+ocEmoji+' '+oc+'</td>';
          html+='<td>'+chg+'</td>';
          html+='<td style="font-size:12px">'+s.confidence+'</td>';
          html+='</tr>';
        });
        html+='</table>';
        if(data.updated)html+='<p style="color:#555;font-size:11px;margin-top:6px">Letzte Aktualisierung: '+data.updated.replace('T',' ').slice(0,16)+' UTC</p>';
      } else {
        html+='<p style="color:#888;margin:12px 0">Noch keine Signale gefeuert. Tracker prüft alle 30 Min.</p>';
      }
    }
  }catch(e){
    html+='<p style="color:#888;margin-bottom:12px">Signal-Feed nicht erreichbar — zeige Lead-Lag Paare.</p>';
  }
  
  // 2. Lead-Lag Paare (immer anzeigen)
  html+='<div class="card-title" style="margin:16px 0 8px">🔗 Überwachte Lead-Lag Paare</div>';
  html+='<table><tr><th>Pair</th><th>Lead → Lag</th><th>Lag</th><th>Theorie</th></tr>';
  pairs.forEach(p=>{
    html+='<tr><td style="font-family:monospace;font-size:12px">'+p.id+'</td><td>'+p.lead+' → '+p.lag+'</td><td>'+p.lag_hours+'h</td><td style="font-size:12px">'+p.desc+'</td></tr>';
  });
  html+='</table>';
  html+='<p style="color:#f39c12;margin-top:8px;font-size:12px">⚠️ Min. 20 Samples + 60% Accuracy nötig bevor ein Signal handelbar wird.</p>';
  
  el.innerHTML=html;
}

async function loadAnalytics(){
  const el=document.getElementById('analytics-content');
  // Paper Trade Stats (aus PAPER Array berechnet)
  const closed=PAPER.filter(p=>p.status==='CLOSED');
  const open=PAPER.filter(p=>!p.status||p.status!=='CLOSED');
  
  let html='<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px">';
  html+='<div class="card" style="padding:12px;text-align:center"><div style="font-size:24px;font-weight:bold">'+PAPER.length+'</div><div style="color:#888">Paper Trades</div></div>';
  html+='<div class="card" style="padding:12px;text-align:center"><div style="font-size:24px;font-weight:bold">'+open.length+'</div><div style="color:#888">Offen</div></div>';
  html+='<div class="card" style="padding:12px;text-align:center"><div style="font-size:24px;font-weight:bold">'+STRATEGIES.length+'</div><div style="color:#888">Strategien</div></div>';
  html+='<div class="card" style="padding:12px;text-align:center"><div style="font-size:24px;font-weight:bold;color:#f39c12">⏳</div><div style="color:#888">Calibrating</div></div>';
  html+='</div>';
  
  // Strategy overview
  html+='<h3 style="margin:12px 0 8px">Paper-Strategien</h3><table><tr><th>Strategy</th><th>Status</th><th>Conviction</th><th>Ticker</th><th>Beschreibung</th></tr>';
  STRATEGIES.forEach(st=>{
    html+='<tr><td style="color:'+st.color+'"><strong>'+st.id+'</strong></td><td>'+st.status+'</td><td>'+st.conviction+'</td>';
    html+='<td>'+st.tickers.join(', ')+'</td><td style="font-size:12px">'+st.name+'</td></tr>';
  });
  html+='</table>';
  
  // Conviction Score System
  html+='<h3 style="margin:12px 0 8px">Conviction Score v2 — 8 Faktoren</h3>';
  html+='<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">';
  const factors=[
    {name:'Regime Alignment',weight:'20%',desc:'Passt Strategie zum aktuellen Regime?'},
    {name:'Technical Setup',weight:'20%',desc:'CRV, Trend, Pattern-Qualität'},
    {name:'Volume Confirm',weight:'10%',desc:'Volumen > 2× 20-SMA?'},
    {name:'News Momentum',weight:'10%',desc:'Sentiment-Trend letzte 48h'},
    {name:'Signal Confluence',weight:'15%',desc:'Mehrere Lead-Lag Signale?'},
    {name:'Backtest Perf',weight:'10%',desc:'Historische Win-Rate für Setup'},
    {name:'Correlation',weight:'5%',desc:'Portfolio-Diversifikation'},
    {name:'Sector Rotation',weight:'10%',desc:'Sektor-Momentum 20 Tage'},
  ];
  factors.forEach(f=>{
    html+='<div class="card" style="padding:8px;font-size:13px"><strong>'+f.name+'</strong> ('+f.weight+')<br><span style="color:#888">'+f.desc+'</span></div>';
  });
  html+='</div>';
  
  html+='<p style="color:#888;margin-top:12px">Self-Calibration aktiviert sich nach 50+ geschlossenen Trades. Aktuell: 3 geschlossen.</p>';
  el.innerHTML=html;
}

async function loadMacro(){
  const el=document.getElementById('macro-content');
  // Macro-Daten aus prices (bereits geladen via loadAll)
  if(!prices){el.innerHTML='<div class="loading">Warte auf Preisdaten…</div>';return;}
  
  const macroTickers=[
    {key:'^VIX',name:'VIX',unit:'',warn:25,crit:30},
    {key:'CL=F',name:'WTI Öl',unit:'$',warn:90,crit:100},
    {key:'BZ=F',name:'Brent',unit:'$',warn:100,crit:110},
    {key:'GC=F',name:'Gold',unit:'$'},
    {key:'^DJI',name:'Dow Jones',unit:''},
    {key:'^GSPC',name:'S&P 500',unit:''},
    {key:'^IXIC',name:'Nasdaq',unit:''},
    {key:'^N225',name:'Nikkei 225',unit:''},
    {key:'HG=F',name:'Kupfer',unit:'$'},
    {key:'EURUSD=X',name:'EUR/USD',unit:''},
  ];
  
  let html='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px">';
  macroTickers.forEach(m=>{
    const d=prices[m.key];
    if(!d)return;
    const price=d.price||d.regularMarketPrice||0;
    const chg=d.change_pct||0;
    const color=chg>0?'#2ecc71':(chg<0?'#e74c3c':'#888');
    let border='';
    if(m.crit&&price>=m.crit)border='border-left:3px solid #e74c3c';
    else if(m.warn&&price>=m.warn)border='border-left:3px solid #f39c12';
    html+='<div class="card" style="padding:12px;'+border+'">';
    html+='<div style="color:#888;font-size:11px">'+m.name+'</div>';
    html+='<div style="font-size:18px;font-weight:bold">'+m.unit+price.toFixed(2)+'</div>';
    html+='<div style="color:'+color+';font-size:12px">'+(chg>0?'+':'')+chg.toFixed(2)+'%</div>';
    html+='</div>';
  });
  html+='</div>';
  
  // Regime Info
  html+='<div class="card" style="padding:12px;margin-top:12px">';
  html+='<div class="card-title">Aktuelles Regime</div>';
  const vix=(prices['^VIX']||{}).price||0;
  let regime='NEUTRAL',rColor='#f39c12';
  if(vix<15){regime='BULL_CALM';rColor='#2ecc71';}
  else if(vix<20){regime='BULL_VOLATILE';rColor='#27ae60';}
  else if(vix<25){regime='NEUTRAL';rColor='#f39c12';}
  else if(vix<30){regime='CORRECTION';rColor='#e67e22';}
  else if(vix<35){regime='BEAR';rColor='#e74c3c';}
  else{regime='CRISIS';rColor='#c0392b';}
  html+='<div style="font-size:24px;font-weight:bold;color:'+rColor+'">'+regime+'</div>';
  html+='<div style="color:#888">VIX: '+vix.toFixed(1)+' | Position Factor: '+(vix<20?'1.2':(vix<25?'0.8':(vix<30?'0.6':'0.4')))+'</div>';
  html+='</div>';
  
  // Spread Info (wenn Daten da)
  const brent=(prices['BZ=F']||{}).price||0;
  const wti=(prices['CL=F']||{}).price||0;
  if(brent&&wti){
    const spread=(brent-wti).toFixed(2);
    const spreadColor=spread>10?'#e74c3c':(spread>5?'#f39c12':'#2ecc71');
    html+='<div class="card" style="padding:12px;margin-top:8px">';
    html+='<div style="color:#888;font-size:11px">Brent-WTI Spread</div>';
    html+='<div style="font-size:18px;font-weight:bold;color:'+spreadColor+'">$'+spread+'</div>';
    html+='<div style="color:#888;font-size:11px">>$10 = strukturelle Lieferunterbrechung</div>';
    html+='</div>';
  }
  
  el.innerHTML=html;
}

// Theme aus localStorage laden
if(localStorage.getItem('theme')==='light'){isDark=false;document.body.classList.add('light');document.getElementById('theme-btn').textContent='☀️';}

loadAll();
setInterval(()=>{loadAll();checkStopAlerts();},60000);
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
