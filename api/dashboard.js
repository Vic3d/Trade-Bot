// TradeMind — Professional Trading Dashboard
// Real Portfolio: Übersicht (CRV, Portfolio-Summary, Alert) | Bearbeiten (ATR-Hint) | Trade eintragen (Positionsgröße) | Trade History
// Paper Trades: Positionen (Equity Chart, Heatmap) | Performance (Strategie-Breakdown) | Eintragen | Strategien

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
  {id:'PS1',color:'#3498db',name:'Iran/Öl-Geopolitik',status:'🟢',conviction:'Hoch',tickers:['OXY','TTE.PA','NOVO-B.CO'],
   desc:'Solange der Iran-Konflikt die Straße von Hormuz bedroht, bleibt Öl teuer → Ölproduzenten profitieren.<br><br><strong>Kernthese:</strong> Iran + Houthi-Angriffe = Versicherungsprämie auf Öl.<br><strong>Ausstieg wenn:</strong> Iran-Deal, WTI dauerhaft unter 70$.'},
  {id:'PS2',color:'#e67e22',name:'Tanker-Lag-These',status:'🟢',conviction:'Mittel',tickers:['FRO','DHT'],
   desc:'Wenn Öl steigt, folgen Tanker-Aktien mit 2–4 Wochen Verzögerung.<br><br><strong>Kernthese:</strong> Steigende Ölpreise = höhere Frachtraten → Tanker-Aktien hinken nach.<br><strong>Ausstieg wenn:</strong> Öl fällt unter 70$ oder Frachtraten kollabieren.'},
  {id:'PS3',color:'#2ecc71',name:'NATO/EU-Rüstung',status:'🟡',conviction:'Mittel',tickers:['ASML.AS','HO.PA'],
   desc:'Europa erhöht Verteidigungsbudgets → Rüstungs- und Dual-Use-Firmen gewinnen.<br><br><strong>Kernthese:</strong> 2%-BIP-Ziel NATO → ASML (Chips), Thales (Radar, Elektronik).<br><strong>Risiko:</strong> Ukraine-Waffenstillstand.'},
  {id:'PS4',color:'#f1c40f',name:'Edelmetalle/Miner',status:'🟡',conviction:'Mittel',tickers:['HL','PAAS'],
   desc:'Bei VIX hoch + Geopolitik fliehen Anleger in Gold/Silber → Miner profitieren überproportional.<br><br><strong>Kernthese:</strong> Miner = gehebelte Wette auf Metallpreise. Gold +20% → Miner oft +40–60%.<br><strong>Ausstieg wenn:</strong> VIX unter 18, Gold unter 2.500$.'},
  {id:'PS5',color:'#8b4513',name:'Dünger/Agrar-Superzyklus',status:'🟡',conviction:'Niedrig',tickers:['MOS','GLEN.L'],
   desc:'Russische Kali-Sanktionen + steigende Lebensmittelnachfrage → westliche Düngerproduzenten profitieren.<br><br><strong>Kernthese:</strong> Belarus + Russland = 40% des globalen Kali = struktureller Engpass.<br><strong>Risiko:</strong> Sanktionslockerung.'},
];

const HTML = () => {
const pj = JSON.stringify(PAPER);
const sj = JSON.stringify(STRATEGIES);
return `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeMind</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#7d8590;--green:#3fb950;--red:#f85149;--orange:#d29922;--accent:#7c3aed;--blue:#58a6ff}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:200}
header h1{font-size:16px;font-weight:700}
.ts{font-size:11px;color:var(--muted);margin-left:auto}
.main-nav{display:flex;background:var(--surface);border-bottom:1px solid var(--border)}
.main-nav button{flex:1;background:none;border:none;color:var(--muted);padding:13px;font-size:14px;font-weight:600;cursor:pointer;border-bottom:3px solid transparent}
.main-nav button.active{color:var(--text);border-bottom-color:var(--accent)}
.sub-nav{display:flex;background:var(--bg);border-bottom:1px solid var(--border);padding:0 16px;gap:2px;overflow-x:auto}
.sub-nav button{background:none;border:none;color:var(--muted);padding:9px 12px;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.sub-nav button.active{color:var(--text);border-bottom-color:var(--accent)}
.main-panel{display:none}.main-panel.active{display:block}
.sub-panel{display:none;padding:14px 16px}.sub-panel.active{display:block}
.macro-strip{display:flex;gap:8px;overflow-x:auto;margin-bottom:16px}
.macro-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;white-space:nowrap;min-width:75px}
.macro-key{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.macro-val{font-size:15px;font-weight:700;margin-top:2px}
.macro-sub{font-size:11px;margin-top:1px}
.summary-row{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.scard{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 14px;flex:1;min-width:90px}
.scard-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.scard-val{font-size:20px;font-weight:700;margin-top:3px}
.scard-sub{font-size:11px;margin-top:1px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:7px 8px;text-align:left;border-bottom:1px solid var(--border)}
td{padding:9px 8px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.ticker-name{font-weight:700;font-size:13px}
.ticker-sub{font-size:11px;color:var(--muted);margin-top:1px}
.stop-bar{height:3px;border-radius:2px;background:var(--border);margin-top:3px;max-width:70px}
.stop-fill{height:100%;border-radius:2px}
.stat-row{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 14px;flex:1;min-width:100px}
.stat-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.stat-value{font-size:20px;font-weight:700;margin-top:3px}
.stat-sub{font-size:11px;margin-top:2px}
.edit-row{display:grid;grid-template-columns:80px 1fr 1fr 1fr 1fr auto;gap:6px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}
.edit-row:last-child{border-bottom:none}
input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 8px;border-radius:6px;font-size:13px;width:100%}
input:focus{outline:none;border-color:var(--accent)}
label{font-size:11px;color:var(--muted);display:block;margin-bottom:3px}
.form-row{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.ff{flex:1;min-width:80px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:12px}
.card-title{font-weight:600;font-size:13px;margin-bottom:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-size:11px}
.btn{border:none;border-radius:6px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer}
.btn-primary{background:var(--accent);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-muted{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-sm{padding:4px 10px;font-size:12px}
.action-row{display:flex;gap:8px;margin-bottom:12px}
.action-row button{flex:1}
.strat-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden}
.strat-header{display:flex;align-items:center;gap:12px;padding:12px 14px;cursor:pointer;user-select:none}
.strat-header:hover{background:rgba(255,255,255,.02)}
.strat-badge{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0}
.strat-meta{font-size:12px;color:var(--muted);margin-top:2px}
.chev{font-size:12px;color:var(--muted);margin-left:auto;transition:transform .2s}
.chev.open{transform:rotate(180deg)}
.strat-body{display:none;padding:0 14px 14px 62px;font-size:13px;line-height:1.7}
.strat-body.open{display:block}
.tickers-row{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.perf-bar-wrap{background:var(--border);border-radius:3px;height:6px;width:80px;display:inline-block;vertical-align:middle;margin-left:6px}
.perf-bar{height:100%;border-radius:3px}
.heat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;margin-bottom:16px}
.heat-cell{border-radius:8px;padding:10px;text-align:center}
.heat-ticker{font-weight:700;font-size:12px}
.heat-pnl{font-size:16px;font-weight:700;margin-top:2px}
.alert-box{background:rgba(124,58,237,.08);border:1px solid rgba(124,58,237,.3);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:12px}
.alert-box b{color:var(--accent)}
.sizing-result{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;margin-top:12px}
.sizing-row{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}
.sizing-label{color:var(--muted)}
.sizing-val{font-weight:600}
.green{color:var(--green)}.red{color:var(--red)}.orange{color:var(--orange)}.muted{color:var(--muted)}
.loading{text-align:center;padding:30px;color:var(--muted)}
.save-msg{font-size:12px;margin-left:6px}
.history-empty{text-align:center;padding:30px;color:var(--muted);font-size:13px}
.crv-good{color:var(--green);font-weight:600}
.crv-bad{color:var(--red)}
.crv-ok{color:var(--orange)}
.news-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.news-item:hover{border-color:var(--accent)}
.news-title{font-size:13px;font-weight:500;line-height:1.4;margin-bottom:6px}
.news-title a{color:var(--text);text-decoration:none}
.news-title a:hover{color:var(--blue)}
.news-meta{font-size:11px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap}
.news-badge{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600}
.filter-btn{background:var(--surface);border:1px solid var(--border);color:var(--muted);padding:4px 10px;border-radius:12px;font-size:12px;cursor:pointer}
.filter-btn.active{border-color:var(--accent);color:var(--text)}
</style>
</head>
<body>

<header>
  <span style="font-size:20px">🎩</span>
  <h1>TradeMind</h1>
  <button class="btn btn-muted" onclick="loadAll()" style="padding:5px 12px;font-size:12px">🔄</button>
  <span class="ts" id="ts">Lädt…</span>
</header>

<div class="main-nav">
  <button class="active" onclick="showMain('real',this)">📈 Real Portfolio</button>
  <button onclick="showMain('paper',this)">🧪 Paper Trades</button>
  <button onclick="showMain('news',this);loadNews()">📰 News</button>
</div>

<!-- ═══ REAL PORTFOLIO ═══ -->
<div id="main-real" class="main-panel active">
  <div class="sub-nav">
    <button class="active" onclick="showSub('real','overview',this)">📊 Übersicht</button>
    <button onclick="showSub('real','edit',this)">✏️ Bearbeiten</button>
    <button onclick="showSub('real','log',this)">➕ Trade eintragen</button>
    <button onclick="showSub('real','history',this);loadHistory()">📜 Trade History</button>
  </div>

  <div id="real-overview" class="sub-panel active">
    <div class="macro-strip" id="macro-strip"><div class="loading">…</div></div>
    <div class="summary-row" id="portfolio-summary"></div>
    <div id="alert-box"></div>
    <div id="real-table"><div class="loading">Lädt…</div></div>
  </div>

  <div id="real-edit" class="sub-panel">
    <div class="alert-box" style="margin-bottom:14px">
      <b>💡 ATR-Regel:</b> Stop-Abstand mindestens <strong>ATR × 1.5</strong>. Faustregel: bei normalem Markt mind. 3–5%, bei VIX &gt; 25 mind. 6–8% Abstand.
    </div>
    <div class="card" style="padding:0 14px">
      <div id="edit-table"><div class="loading">Lädt…</div></div>
    </div>
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
        <div class="ff"><label>Preis (€)</label><input id="l-price" type="number" step="0.01" placeholder="0.00" oninput="calcSizing()"></div>
        <div class="ff"><label>Stop (€)</label><input id="l-stop" type="number" step="0.01" placeholder="0.00" oninput="calcSizing()"></div>
        <div class="ff"><label>Ziel (€)</label><input id="l-target" type="number" step="0.01" placeholder="0.00"></div>
      </div>
      <div class="form-row">
        <div class="ff" style="flex:3"><label>Notiz</label><input id="l-notes" placeholder="z.B. EMA50-Rücklauf, CRV 5:1"></div>
      </div>
      <button class="btn btn-primary" onclick="logTrade()">💾 Speichern</button>
      <span id="log-status" class="save-msg"></span>
    </div>

    <div class="card">
      <div class="card-title">📐 Positionsgröße berechnen</div>
      <div class="form-row">
        <div class="ff"><label>Kontostand (€)</label><input id="ps-account" type="number" value="5000" oninput="calcSizing()"></div>
        <div class="ff"><label>Risiko %</label><input id="ps-risk" type="number" value="1" step="0.1" min="0.1" max="10" oninput="calcSizing()"></div>
        <div class="ff"><label>Entry (€) ↑ auto</label><input id="ps-entry" type="number" step="0.01" placeholder="aus oben" oninput="calcSizing()"></div>
        <div class="ff"><label>Stop (€) ↑ auto</label><input id="ps-stop" type="number" step="0.01" placeholder="aus oben" oninput="calcSizing()"></div>
      </div>
      <div class="sizing-result" id="sizing-result" style="display:none"></div>
    </div>
  </div>

  <div id="real-history" class="sub-panel">
    <div id="history-table"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- ═══ NEWS ═══ -->
<div id="main-news" class="main-panel">
  <div style="padding:14px 16px">
    <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap" id="news-filter"></div>
    <div id="news-list"><div class="loading">Lädt…</div></div>
  </div>
</div>

<!-- ═══ PAPER TRADES ═══ -->
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
            <option value="PS1">PS1 — Iran/Öl</option>
            <option value="PS2">PS2 — Tanker-Lag</option>
            <option value="PS3">PS3 — NATO/Rüstung</option>
            <option value="PS4">PS4 — Edelmetalle</option>
            <option value="PS5">PS5 — Dünger/Agrar</option>
          </select>
        </div>
        <div class="ff" style="flex:2"><label>Notiz</label><input id="pl-notes" placeholder="Begründung"></div>
      </div>
      <button class="btn btn-primary" onclick="logPaperTrade()">💾 Speichern</button>
      <span id="pl-status" class="save-msg"></span>
    </div>
  </div>

  <div id="paper-strat" class="sub-panel">
    <div id="strat-list"></div>
  </div>
</div>

<script>
const PAPER = ${pj};
const STRATEGIES = ${sj};
let cfg = null, prices = null, tradeAction = 'BUY', paperAction = 'BUY';
let historyLoaded = false;

function showMain(n, btn) {
  document.querySelectorAll('.main-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.main-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('main-'+n).classList.add('active');
  btn.classList.add('active');
}
function showSub(main, sub, btn) {
  const panel = document.getElementById('main-'+main);
  panel.querySelectorAll('.sub-panel').forEach(p=>p.classList.remove('active'));
  panel.querySelectorAll('.sub-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(main+'-'+sub).classList.add('active');
  btn.classList.add('active');
}

function pct(v,b){return b?((v-b)/b*100):null}
function pctHtml(v,bold=false){
  if(v==null)return'<span class="muted">—</span>';
  const c=v>=0?'green':'red',s=v>=0?'▲ +':'▼ ';
  return \`<span class="\${c}" \${bold?'style="font-weight:700"':''}>\${s}\${Math.abs(v).toFixed(1)}%</span>\`;
}
function getP(px,t){return px[t]||px[t+'.OL']||px[t+'.DE']||px[t+'.L']||null}

function crvHtml(price, stop, target) {
  if(!target||!stop||!price||price<=stop) return '<span class="muted">—</span>';
  const crv = (target-price)/(price-stop);
  const cls = crv>=3?'crv-good':crv>=2?'crv-ok':'crv-bad';
  return \`<span class="\${cls}">\${crv.toFixed(1)}:1</span>\`;
}

function stopCell(price, stop) {
  if(!stop) return '<span class="red" style="font-size:11px">⚠️ kein Stop</span>';
  const d=price?(price-stop)/price*100:null;
  const col=d!=null&&d<2?'var(--red)':d!=null&&d<5?'var(--orange)':'var(--green)';
  const bar=d!=null?Math.min(d*8,100):0;
  return \`<div><span style="color:\${col};font-weight:600">\${stop.toFixed(2)}€</span>
           <span class="muted" style="font-size:11px"> (\${d!=null?d.toFixed(1):'?'}%)</span></div>
          <div class="stop-bar"><div class="stop-fill" style="width:\${bar}%;background:\${col}"></div></div>\`;
}

async function loadAll() {
  document.getElementById('ts').textContent='⏳';
  try {
    [cfg, prices] = await Promise.all([
      fetch('/api/config').then(r=>r.json()),
      fetch('/api/prices').then(r=>r.json()),
    ]);
    renderMacro(prices);
    renderSummary(cfg, prices);
    renderReal(cfg, prices);
    renderEdit(cfg, prices);
    renderPaper(prices);
    renderStratPerf(prices);
    renderStrat();
    document.getElementById('ts').textContent=new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
  } catch(e){ document.getElementById('ts').textContent='⚠️ '+e.message; }
}

function renderMacro(p) {
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

function renderSummary(cfg, prices) {
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  let winning=0,danger=0,noStop=0,sumPnl=0,cnt=0;
  pos.forEach(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null;
    const pnl=pct(eur,p.entry_eur);
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)winning++;}
    if(!p.stop_eur) noStop++;
    else if(eur&&(eur-p.stop_eur)/eur*100<5) danger++;
  });
  const avg=cnt?sumPnl/cnt:0;
  document.getElementById('portfolio-summary').innerHTML=\`
    <div class="scard"><div class="scard-label">Positionen</div><div class="scard-val">\${pos.length}</div><div class="scard-sub muted">\${winning} im Plus</div></div>
    <div class="scard"><div class="scard-label">Ø P&amp;L</div><div class="scard-val \${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="scard" style="border-color:\${danger>0?'rgba(248,81,73,.4)':'var(--border)'}"><div class="scard-label">Stop &lt; 5%</div><div class="scard-val \${danger>0?'orange':''}">\${danger}</div><div class="scard-sub \${danger>0?'red muted':'muted'}">Gefahr</div></div>
    <div class="scard" style="border-color:\${noStop>0?'rgba(248,81,73,.4)':'var(--border)'}"><div class="scard-label">Kein Stop</div><div class="scard-val \${noStop>0?'red':''}">\${noStop}</div><div class="scard-sub muted">⚠️ Risiko</div></div>
  \`;

  // Alert box: Stops in Danger
  const dangerPos = pos.filter(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null;
    return p.stop_eur&&eur&&(eur-p.stop_eur)/eur*100<5;
  });
  const alertEl = document.getElementById('alert-box');
  if(dangerPos.length>0){
    alertEl.innerHTML=\`<div class="alert-box">⚠️ <b>Stop-Alarm:</b> \${dangerPos.map(p=>{
      const eur=getP(px,p.ticker)?.eur;
      const d=eur?((eur-p.stop_eur)/eur*100).toFixed(1):'?';
      return \`<strong>\${p.ticker}</strong> (\${d}% vom Stop)\`;
    }).join(' · ')}</div>\`;
  } else { alertEl.innerHTML=''; }
}

function renderReal(cfg, prices) {
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  const rows=pos.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry_eur);
    const crv=crvHtml(eur, p.stop_eur, p.target_eur);
    return \`<tr>
      <td><div class="ticker-name">\${p.ticker}</div><div class="ticker-sub">\${p.name||''}</div></td>
      <td class="muted">\${p.entry_eur?.toFixed(2)??'—'}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(chg)}</td>
      <td>\${pctHtml(pnl,true)}</td>
      <td>\${stopCell(eur,p.stop_eur)}</td>
      <td>\${crv}</td>
    </tr>\`;
  });
  document.getElementById('real-table').innerHTML=\`
    <table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&amp;L</th><th>Stop</th><th>CRV</th></tr></thead>
    <tbody>\${rows.join('')||'<tr><td colspan="7" class="muted" style="text-align:center;padding:20px">Keine offenen Positionen</td></tr>'}</tbody></table>\`;
}

function renderEdit(cfg, prices) {
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=(prices?.prices)||{};
  if(!pos.length){document.getElementById('edit-table').innerHTML='<p class="muted" style="padding:14px 0">Keine Positionen</p>';return;}
  document.getElementById('edit-table').innerHTML=pos.map(p=>{
    const eur=getP(px,p.ticker)?.eur;
    // ATR Hinweis: Faustregel ~4% vom Kurs
    const suggestStop = eur ? (eur*0.96).toFixed(2) : '';
    const stopDist = eur&&p.stop_eur ? ((eur-p.stop_eur)/eur*100).toFixed(1) : null;
    const stopWarn = stopDist && parseFloat(stopDist) < 5 ? \`style="border-color:var(--orange)"\` : '';
    const atrHint = eur ? \`<div style="font-size:10px;color:var(--muted);margin-top:3px">Vorschlag: \${suggestStop}€ (−4%)</div>\` : '';
    return \`<div class="edit-row">
      <div><div style="font-weight:700;font-size:13px">\${p.ticker}</div><div style="font-size:11px;color:var(--muted)">\${eur?eur.toFixed(2)+'€':'—'}</div></div>
      <div><label>Entry €</label><input type="number" id="e-entry-\${p.ticker}" value="\${p.entry_eur||''}" step="0.01"></div>
      <div><label>Stop €</label><input type="number" id="e-stop-\${p.ticker}" value="\${p.stop_eur||''}" step="0.01" \${stopWarn}>\${atrHint}</div>
      <div><label>Ziel €</label><input type="number" id="e-target-\${p.ticker}" value="\${p.target_eur||''}" step="0.01"></div>
      <div><label>CRV</label><div style="padding-top:8px;font-size:13px">\${crvHtml(eur,p.stop_eur,p.target_eur)}</div></div>
      <div style="padding-top:18px">
        <button class="btn btn-primary btn-sm" onclick="savePos('\${p.ticker}')">💾</button>
        <span id="e-status-\${p.ticker}" class="save-msg"></span>
      </div>
    </div>\`;
  }).join('');
}

async function loadHistory() {
  if(historyLoaded) return;
  document.getElementById('history-table').innerHTML='<div class="loading">Lade…</div>';
  try {
    const d = await fetch('/api/trade-log').then(r=>r.json());
    const trades = (d.trades||[]).reverse();
    if(!trades.length){
      document.getElementById('history-table').innerHTML='<div class="history-empty">📭 Noch keine Trades gespeichert</div>';
      return;
    }
    const rows=trades.map(t=>{
      const date = t.ts ? new Date(t.ts).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
      const isBuy = t.action==='BUY';
      const badge = isBuy
        ? \`<span class="badge" style="background:rgba(63,185,80,.15);color:var(--green)">KAUF</span>\`
        : \`<span class="badge" style="background:rgba(248,81,73,.15);color:var(--red)">VERKAUF</span>\`;
      return \`<tr>
        <td class="muted" style="font-size:12px">\${date}</td>
        <td>\${badge}</td>
        <td><strong>\${t.ticker}</strong></td>
        <td>\${t.price_eur?.toFixed(2)??'—'}€</td>
        <td class="muted" style="font-size:12px">\${t.stop_eur?t.stop_eur+'€':'—'}</td>
        <td class="muted" style="font-size:12px">\${t.target_eur?t.target_eur+'€':'—'}</td>
        <td class="muted" style="font-size:11px;max-width:150px;overflow:hidden;text-overflow:ellipsis">\${t.notes||''}</td>
      </tr>\`;
    }).join('');
    document.getElementById('history-table').innerHTML=\`
      <table><thead><tr><th>Datum</th><th>Typ</th><th>Ticker</th><th>Preis</th><th>Stop</th><th>Ziel</th><th>Notiz</th></tr></thead>
      <tbody>\${rows}</tbody></table>\`;
    historyLoaded = true;
  } catch(e){
    document.getElementById('history-table').innerHTML=\`<div class="history-empty">⚠️ Fehler: \${e.message}</div>\`;
  }
}

function renderPaper(prices) {
  const px=prices.prices||{};
  let sumPnl=0,wins=0,cnt=0;
  const CASH=71, PCAP=900;
  const posData = PAPER.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry);
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)wins++;}
    return {...p,eur,chg,pnl};
  });
  const avg=cnt?sumPnl/cnt:0;
  const wr=cnt?(wins/cnt*100):0;
  const curVal=Math.round(PCAP*(1+avg/100)+CASH);
  const diff=curVal-1000;

  document.getElementById('paper-stats').innerHTML=\`
    <div class="stat"><div class="stat-label">Startkapital</div><div class="stat-value">1.000€</div></div>
    <div class="stat"><div class="stat-label">Akt. Wert</div><div class="stat-value \${curVal>=1000?'green':'red'}">\${curVal}€</div><div class="stat-sub \${diff>=0?'green':'red'}">\${diff>=0?'+':''}\${diff}€</div></div>
    <div class="stat"><div class="stat-label">Ø P&amp;L</div><div class="stat-value \${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="stat"><div class="stat-label">Win-Rate</div><div class="stat-value">\${wr.toFixed(0)}%</div><div class="stat-sub muted">\${wins}/\${cnt}</div></div>
    <div class="stat"><div class="stat-label">Bares Geld</div><div class="stat-value">\${CASH}€</div></div>
  \`;

  // Heatmap
  const heatCells=posData.map(p=>{
    const v=p.pnl;
    const intensity=Math.min(Math.abs(v||0)*3,100);
    const bg=v==null?'rgba(30,30,30,1)':v>=0?\`rgba(63,185,80,\${0.1+intensity/300})\`:\`rgba(248,81,73,\${0.1+intensity/300})\`;
    return \`<div class="heat-cell" style="background:\${bg}">
      <div class="heat-ticker">\${p.ticker.split('.')[0]}</div>
      <div class="heat-pnl" style="color:\${v==null?'var(--muted)':v>=0?'var(--green)':'var(--red)'}">\${v!=null?(v>=0?'+':'')+v.toFixed(1)+'%':'—'}</div>
    </div>\`;
  }).join('');
  document.getElementById('paper-heatmap').innerHTML=\`<div class="heat-grid">\${heatCells}</div>\`;

  // Table
  const rows=posData.map(p=>{
    const s=STRATEGIES.find(s=>s.id===p.strategy);
    const badge=s?\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${p.strategy}</span>\`:'';
    return \`<tr>
      <td><div class="ticker-name">\${p.ticker}</div><div class="ticker-sub">\${p.name} \${badge}</div></td>
      <td class="muted">\${p.entry.toFixed(2)}€</td>
      <td>\${p.eur!=null?\`<strong>\${p.eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(p.chg)}</td>
      <td>\${pctHtml(p.pnl,true)}</td>
      <td class="muted" style="font-size:12px">\${p.stop||'—'}€ / \${p.target||'—'}€</td>
      <td>\${crvHtml(p.eur,p.stop,p.target)}</td>
    </tr>\`;
  }).join('');
  document.getElementById('paper-table').innerHTML=\`
    <table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&amp;L</th><th>Stop/Ziel</th><th>CRV</th></tr></thead>
    <tbody>\${rows}</tbody></table>\`;
}

function renderStratPerf(prices) {
  const px=(prices?.prices)||{};
  const perfMap={};
  STRATEGIES.forEach(s=>perfMap[s.id]={id:s.id,name:s.name,color:s.color,status:s.status,pnls:[],wins:0,cnt:0});
  PAPER.forEach(p=>{
    const eur=getP(px,p.ticker)?.eur??null;
    const pnl=pct(eur,p.entry);
    if(perfMap[p.strategy]){
      if(pnl!=null){perfMap[p.strategy].pnls.push(pnl);perfMap[p.strategy].cnt++;if(pnl>0)perfMap[p.strategy].wins++;}
    }
  });
  const rows=Object.values(perfMap).map(s=>{
    const avg=s.pnls.length?s.pnls.reduce((a,b)=>a+b,0)/s.pnls.length:null;
    const wr=s.cnt?(s.wins/s.cnt*100):null;
    const barW=avg!=null?Math.min(Math.abs(avg)*5,100):0;
    const barColor=avg==null?'var(--border)':avg>=0?'var(--green)':'var(--red)';
    return \`<tr>
      <td><span class="badge" style="background:\${s.color}22;color:\${s.color}">\${s.id}</span></td>
      <td>\${s.status} \${s.name}</td>
      <td class="muted">\${s.cnt}</td>
      <td>
        \${avg!=null?\`<span class="\${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</span>\`:'—'}
        <div class="perf-bar-wrap"><div class="perf-bar" style="width:\${barW}%;background:\${barColor}"></div></div>
      </td>
      <td>\${wr!=null?\`\${wr.toFixed(0)}% (\${s.wins}/\${s.cnt})\`:'—'}</td>
    </tr>\`;
  }).join('');
  document.getElementById('strat-perf').innerHTML=\`
    <table><thead><tr><th>ID</th><th>Strategie</th><th>Pos.</th><th>Ø P&amp;L</th><th>Win-Rate</th></tr></thead>
    <tbody>\${rows}</tbody></table>\`;
}

function renderStrat() {
  document.getElementById('strat-list').innerHTML=STRATEGIES.map((s,i)=>\`
    <div class="strat-card">
      <div class="strat-header" onclick="toggleStrat(\${i})">
        <div class="strat-badge" style="background:\${s.color}22;color:\${s.color}">\${s.id}</div>
        <div style="flex:1">
          <div style="font-weight:600">\${s.status} \${s.name}</div>
          <div class="strat-meta">Überzeugung: \${s.conviction} · \${s.tickers.join(', ')}</div>
        </div>
        <div class="chev" id="chev-\${i}">▼</div>
      </div>
      <div class="strat-body" id="sbody-\${i}">
        \${s.desc}
        <div class="tickers-row">\${s.tickers.map(t=>\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${t}</span>\`).join('')}</div>
      </div>
    </div>\`).join('');
}

function toggleStrat(i){document.getElementById('sbody-'+i).classList.toggle('open');document.getElementById('chev-'+i).classList.toggle('open');}

function calcSizing() {
  const entry=parseFloat(document.getElementById('l-price')?.value||document.getElementById('ps-entry')?.value);
  const stop=parseFloat(document.getElementById('l-stop')?.value||document.getElementById('ps-stop')?.value);
  // Sync entry/stop to calculator fields
  if(document.getElementById('l-price').value) document.getElementById('ps-entry').value=document.getElementById('l-price').value;
  if(document.getElementById('l-stop').value) document.getElementById('ps-stop').value=document.getElementById('l-stop').value;
  const account=parseFloat(document.getElementById('ps-account')?.value)||5000;
  const riskPct=parseFloat(document.getElementById('ps-risk')?.value)||1;
  const e=parseFloat(document.getElementById('ps-entry')?.value);
  const s=parseFloat(document.getElementById('ps-stop')?.value);
  const el=document.getElementById('sizing-result');
  if(!e||!s||e<=s){el.style.display='none';return;}
  const riskEur=account*riskPct/100;
  const riskPerShare=e-s;
  const shares=Math.floor(riskEur/riskPerShare);
  const invest=shares*e;
  const maxLoss=shares*riskPerShare;
  const pctOfAccount=(invest/account*100).toFixed(1);
  el.style.display='block';
  el.innerHTML=\`
    <div class="sizing-row"><span class="sizing-label">Max. Risiko</span><span class="sizing-val red">\${riskEur.toFixed(0)}€ (\${riskPct}%)</span></div>
    <div class="sizing-row"><span class="sizing-label">Stückzahl</span><span class="sizing-val">\${shares} Stück</span></div>
    <div class="sizing-row"><span class="sizing-label">Einsatz</span><span class="sizing-val">\${invest.toFixed(0)}€ (\${pctOfAccount}% vom Konto)</span></div>
    <div class="sizing-row"><span class="sizing-label">Risiko per Share</span><span class="sizing-val">\${riskPerShare.toFixed(2)}€</span></div>
    <div class="sizing-row"><span class="sizing-label">Max. Verlust</span><span class="sizing-val red">−\${maxLoss.toFixed(0)}€</span></div>
  \`;
}

async function savePos(ticker) {
  const entry=document.getElementById('e-entry-'+ticker)?.value;
  const stop=document.getElementById('e-stop-'+ticker)?.value;
  const target=document.getElementById('e-target-'+ticker)?.value;
  const el=document.getElementById('e-status-'+ticker);
  el.textContent='⏳';el.style.color='var(--muted)';
  try {
    const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,entry_eur:entry,stop_eur:stop||null,target_eur:target||null})});
    const d=await r.json();
    if(d.status==='ok'){el.textContent='✅';el.style.color='var(--green)';setTimeout(()=>{el.textContent='';loadAll();},1000);}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

function setAction(a) {
  tradeAction=a;
  document.getElementById('btn-buy').className='btn '+(a==='BUY'?'btn-primary':'btn-muted');
  document.getElementById('btn-sell').className='btn '+(a==='SELL'?'btn-danger':'btn-muted');
}
function setPaperAction(a) {
  paperAction=a;
  document.getElementById('pb-buy').className='btn '+(a==='BUY'?'btn-primary':'btn-muted');
  document.getElementById('pb-sell').className='btn '+(a==='SELL'?'btn-danger':'btn-muted');
}

async function logTrade() {
  const ticker=document.getElementById('l-ticker').value.toUpperCase();
  const price=parseFloat(document.getElementById('l-price').value);
  const stop=parseFloat(document.getElementById('l-stop').value)||null;
  const target=parseFloat(document.getElementById('l-target').value)||null;
  const notes=document.getElementById('l-notes').value;
  const el=document.getElementById('log-status');
  if(!ticker||!price){el.textContent='⚠️ Ticker + Preis fehlen';el.style.color='var(--orange)';return;}
  try {
    const r=await fetch('/api/trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,action:tradeAction,price_eur:price,stop_eur:stop,target_eur:target,notes})});
    const d=await r.json();
    if(d.status==='ok'){
      el.textContent=\`✅ \${ticker} gespeichert\`;el.style.color='var(--green)';
      historyLoaded=false;
      ['l-ticker','l-price','l-stop','l-target','l-notes'].forEach(id=>document.getElementById(id).value='');
    }else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

async function logPaperTrade() {
  const ticker=document.getElementById('pl-ticker').value.toUpperCase();
  const price=parseFloat(document.getElementById('pl-price').value);
  const stop=parseFloat(document.getElementById('pl-stop').value)||null;
  const target=parseFloat(document.getElementById('pl-target').value)||null;
  const strat=document.getElementById('pl-strat').value;
  const notes=document.getElementById('pl-notes').value;
  const el=document.getElementById('pl-status');
  if(!ticker||!price){el.textContent='⚠️ Ticker + Preis fehlen';el.style.color='var(--orange)';return;}
  try {
    const r=await fetch('/api/trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,action:paperAction,price_eur:price,stop_eur:stop,target_eur:target,strategy:strat,notes,paper:true})});
    const d=await r.json();
    if(d.status==='ok'){el.textContent=\`✅ \${ticker} gespeichert\`;el.style.color='var(--green)';['pl-ticker','pl-price','pl-stop','pl-target','pl-notes'].forEach(id=>document.getElementById(id).value='');}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

let newsLoaded = false;
let allNews = [];
let newsFilter = 'ALL';

async function loadNews() {
  if(newsLoaded) return;
  document.getElementById('news-list').innerHTML='<div class="loading">Lädt News…</div>';
  try {
    // Tickers aus Config holen
    const tickers = cfg ? (cfg.positions||[]).filter(p=>p.status!=='CLOSED').map(p=>p.ticker).slice(0,5).join(',') : 'NVDA,EQNR,RIO';
    const d = await fetch(\`/api/news?tickers=\${tickers}\`).then(r=>r.json());
    allNews = d.news || [];
    renderNews('ALL');
    newsLoaded = true;
  } catch(e) {
    document.getElementById('news-list').innerHTML=\`<div class="history-empty">⚠️ \${e.message}</div>\`;
  }
}

function renderNews(filter) {
  newsFilter = filter;
  // Filter-Buttons
  const tickers = ['ALL', 'MACRO', ...new Set(allNews.filter(n=>n.ticker!=='MACRO').map(n=>n.ticker))];
  document.getElementById('news-filter').innerHTML = tickers.map(t=>
    \`<button class="filter-btn \${t===filter?'active':''}" onclick="renderNews('\${t}')">\${t==='ALL'?'Alle':t==='MACRO'?'🌍 Makro':t}</button>\`
  ).join('');

  const filtered = filter==='ALL' ? allNews : allNews.filter(n=>n.ticker===filter);
  if(!filtered.length){
    document.getElementById('news-list').innerHTML='<div class="history-empty">Keine News gefunden</div>';
    return;
  }
  document.getElementById('news-list').innerHTML = filtered.map(n => {
    const time = n.time ? new Date(n.time).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
    const tickerColor = n.ticker==='MACRO' ? '#58a6ff' : '#7c3aed';
    const badge = \`<span class="news-badge" style="background:\${tickerColor}22;color:\${tickerColor}">\${n.ticker}</span>\`;
    return \`<div class="news-item">
      <div class="news-title"><a href="\${n.url}" target="_blank" rel="noopener">\${n.title}</a></div>
      <div class="news-meta">\${badge}<span>\${n.source||''}</span><span>\${time}</span></div>
    </div>\`;
  }).join('');
}

loadAll();
setInterval(loadAll, 60000);
</script>
</body>
</html>`;
};

module.exports = async function handler(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, no-cache');
  res.status(200).send(HTML());
};
