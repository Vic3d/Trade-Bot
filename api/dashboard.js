// TradeMind v2 — Vollständiges Dashboard als Serverless Function
// Tabs: Portfolio (real) | Paper Trades | Stops bearbeiten | Trade Log | Strategien
// Kein CDN-Cache, immer aktuell

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
  {id:'PS1', color:'#3498db', name:'Iran/Öl-Geopolitik',    status:'🟢', desc:'Hormuz-Blockade → Öl teuer → OXY, TTE, NOVO'},
  {id:'PS2', color:'#e67e22', name:'Tanker-Lag-These',      status:'🟢', desc:'Öl steigt → Tanker 2-4W später → FRO, DHT'},
  {id:'PS3', color:'#2ecc71', name:'NATO/EU-Rüstung',       status:'🟡', desc:'Verteidigungsbudgets steigen → ASML, HO.PA'},
  {id:'PS4', color:'#f1c40f', name:'Edelmetalle/Miner',     status:'🟡', desc:'VIX hoch → Gold/Silber → HL, PAAS'},
  {id:'PS5', color:'#8b4513', name:'Dünger/Agrar-Superzyklus',status:'🟡',desc:'Russische Kali-Sanktionen → MOS, GLEN'},
  {id:'S1',  color:'#e74c3c', name:'Iran/Öl (Real)',        status:'🟢', desc:'EQNR, RIO.L'},
  {id:'S2',  color:'#9b59b6', name:'Rüstung (Real)',        status:'🟡', desc:'RHM.DE'},
  {id:'S3',  color:'#1abc9c', name:'KI-Halbleiter (Real)',  status:'🟢', desc:'NVDA, MSFT, PLTR'},
];

const HTML = (paperJson, strategiesJson) => `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeMind</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#7d8590;--green:#3fb950;--red:#f85149;--orange:#d29922;--blue:#58a6ff;--accent:#7c3aed}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:100}
header h1{font-size:16px;font-weight:700}
.ts{font-size:11px;color:var(--muted);margin-left:auto}
nav{display:flex;background:var(--surface);border-bottom:1px solid var(--border);overflow-x:auto}
nav button{background:none;border:none;color:var(--muted);padding:10px 18px;font-size:13px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
nav button.active{color:var(--text);border-bottom-color:var(--accent)}
.tab{display:none;padding:16px 20px}.tab.active{display:block}
.macro-strip{display:flex;gap:8px;overflow-x:auto;margin-bottom:16px}
.macro-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 14px;white-space:nowrap;min-width:80px}
.macro-key{font-size:10px;color:var(--muted);text-transform:uppercase}
.macro-val{font-size:15px;font-weight:700;margin-top:1px}
.macro-sub{font-size:11px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}
td{padding:10px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:hover td{background:rgba(255,255,255,.02)}
.ticker{font-weight:700;font-size:14px}
.badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}
.stop-bar{height:3px;border-radius:2px;background:var(--border);margin-top:3px}
.stop-fill{height:100%;border-radius:2px}
.btn{border:none;border-radius:6px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer}
.btn-primary{background:var(--accent);color:#fff}
.btn-muted{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-sm{padding:5px 10px;font-size:12px}
.form-row{display:flex;gap:8px;margin-bottom:10px;align-items:flex-end;flex-wrap:wrap}
label{font-size:12px;color:var(--muted);display:block;margin-bottom:3px}
input,select{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 10px;border-radius:6px;font-size:13px;width:100%}
input:focus,select:focus{outline:none;border-color:var(--accent)}
.field{flex:1;min-width:90px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:12px}
.stat-row{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.stat{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 14px;flex:1;min-width:100px}
.stat-label{font-size:11px;color:var(--muted);text-transform:uppercase}
.stat-value{font-size:20px;font-weight:700;margin-top:2px}
.strat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px;display:flex;align-items:center;gap:12px}
.strat-badge{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0}
.explain{background:rgba(88,166,255,.05);border:1px solid rgba(88,166,255,.2);border-radius:8px;padding:12px;margin-bottom:12px;font-size:13px;line-height:1.6}
.green{color:var(--green)}.red{color:var(--red)}.orange{color:var(--orange)}.muted{color:var(--muted)}
.loading{text-align:center;padding:40px;color:var(--muted)}
</style>
</head>
<body>
<header>
  <span style="font-size:20px">🎩</span>
  <h1>TradeMind</h1>
  <button class="btn btn-muted" onclick="loadAll()" style="padding:6px 14px;font-size:12px">🔄 Aktualisieren</button>
  <span class="ts" id="ts">Lädt...</span>
</header>
<nav>
  <button class="active" onclick="showTab('real',this)">📈 Real Portfolio</button>
  <button onclick="showTab('paper',this)">🧪 Paper Trades</button>
  <button onclick="showTab('edit',this)">✏️ Stops bearbeiten</button>
  <button onclick="showTab('log',this)">➕ Trade eintragen</button>
  <button onclick="showTab('strat',this)">🧠 Strategien</button>
</nav>

<div id="tab-real" class="tab active">
  <div class="macro-strip" id="macro-strip"></div>
  <div id="real-table"><div class="loading">Lädt...</div></div>
</div>

<div id="tab-paper" class="tab">
  <div class="stat-row" id="paper-stats"></div>
  <div id="paper-table"><div class="loading">Lädt...</div></div>
</div>

<div id="tab-edit" class="tab">
  <div class="card">
    <p style="color:var(--muted);font-size:13px;margin-bottom:14px">Änderungen direkt in Config → Monitor übernimmt beim nächsten 15-Min-Run.</p>
    <div id="edit-table"><div class="loading">Lädt...</div></div>
  </div>
</div>

<div id="tab-log" class="tab">
  <div class="card">
    <div style="font-weight:600;margin-bottom:14px">Trade eintragen</div>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button id="btn-buy" class="btn btn-primary btn-sm" onclick="setAction('BUY')" style="flex:1">KAUF</button>
      <button id="btn-sell" class="btn btn-muted btn-sm" onclick="setAction('SELL')" style="flex:1">VERKAUF</button>
    </div>
    <div class="form-row">
      <div class="field"><label>Ticker</label><input id="l-ticker" placeholder="z.B. EQNR"></div>
      <div class="field"><label>Preis (€)</label><input id="l-price" type="number" step="0.01"></div>
      <div class="field"><label>Stop (€)</label><input id="l-stop" type="number" step="0.01"></div>
      <div class="field"><label>Ziel (€)</label><input id="l-target" type="number" step="0.01"></div>
    </div>
    <div class="form-row">
      <div class="field" style="flex:3"><label>Notiz</label><input id="l-notes" placeholder="z.B. EMA50-Rücklauf, CRV 5:1"></div>
    </div>
    <button class="btn btn-primary" onclick="logTrade()">💾 Trade speichern</button>
    <span id="log-status" style="margin-left:10px;font-size:12px"></span>
  </div>
</div>

<div id="tab-strat" class="tab">
  <div id="strat-list"></div>
</div>

<script>
const PAPER = ${JSON.stringify(PAPER)};
const STRATEGIES = ${JSON.stringify(STRATEGIES)};
let cfg = null, prices = null, tradeAction = 'BUY';

function showTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  if(btn) btn.classList.add('active');
}

async function loadAll() {
  document.getElementById('ts').textContent = '⏳';
  try {
    [cfg, prices] = await Promise.all([
      fetch('/api/config').then(r=>r.json()),
      fetch('/api/prices').then(r=>r.json()),
    ]);
    renderMacro(prices);
    renderReal(cfg, prices);
    renderPaper(prices);
    renderEdit(cfg);
    renderStrat();
    document.getElementById('ts').textContent = 'Stand: '+new Date().toLocaleTimeString('de-DE');
  } catch(e) {
    document.getElementById('ts').textContent = '⚠️ '+e.message;
  }
}

function pct(val,base){return base?((val-base)/base*100):null}
function pctStr(v,cls=true){
  if(v==null)return'—';
  const c=cls?(v>=0?'green':'red'):'';
  return \`<span class="\${c}">\${v>=0?'▲ +':'▼ '}\${v.toFixed(1)}%</span>\`;
}
function stopCell(price, stop) {
  if(!stop) return '<span class="red">⚠️ KEIN STOP</span>';
  const d = price ? (price-stop)/price*100 : null;
  const col = d!=null&&d<2?'var(--red)':d!=null&&d<5?'var(--orange)':'var(--green)';
  const bar = d!=null?Math.min(d*8,100):0;
  return \`<span style="color:\${col}">\${stop.toFixed(2)}€ <small class="muted">(\${d!=null?d.toFixed(1):'?'}%)</small></span>
          <div class="stop-bar"><div class="stop-fill" style="width:\${bar}%;background:\${col}"></div></div>\`;
}

function renderMacro(p) {
  const m=p.macro||{}, f=p.fx||{};
  const vix=m.vix||0, nk=m.nikkei||0;
  const vc=vix>30?'var(--red)':vix>25?'var(--orange)':'var(--green)';
  document.getElementById('macro-strip').innerHTML = \`
    <div class="macro-item"><div class="macro-key">VIX</div><div class="macro-val" style="color:\${vc}">\${vix.toFixed(1)}</div><div class="macro-sub" style="color:\${vc}">\${vix>30?'🔴 Panik':vix>25?'🟠 Erhöht':'🟢 Normal'}</div></div>
    <div class="macro-item"><div class="macro-key">WTI</div><div class="macro-val">$\${(m.wti||0).toFixed(0)}</div><div class="macro-sub muted">Öl</div></div>
    <div class="macro-item"><div class="macro-key">Nikkei</div><div class="macro-val" style="color:\${nk<-3?'var(--red)':nk<0?'var(--orange)':'var(--green)'}">\${nk>=0?'+':''}\${nk.toFixed(1)}%</div><div class="macro-sub muted">225</div></div>
    <div class="macro-item"><div class="macro-key">EUR/USD</div><div class="macro-val">\${(f.EURUSD||0).toFixed(4)}</div><div class="macro-sub muted">FX</div></div>
  \`;
}

function renderReal(cfg, prices) {
  const pos = (cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px = prices.prices||{};
  const get = t => px[t]||px[t+'.OL']||px[t+'.DE']||px[t+'.L']||null;
  const rows = pos.map(p=>{
    const pr=get(p.ticker), eur=pr?.eur??null, chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry_eur);
    return \`<tr>
      <td><div class="ticker">\${p.ticker}</div><div class="muted" style="font-size:11px">\${p.name}</div></td>
      <td class="muted">\${p.entry_eur?.toFixed(2)??'—'}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctStr(chg)}</td>
      <td>\${pctStr(pnl)}</td>
      <td>\${stopCell(eur,p.stop_eur)}</td>
    </tr>\`;
  });
  document.getElementById('real-table').innerHTML=\`<table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&L</th><th>Stop</th></tr></thead><tbody>\${rows.join('')}</tbody></table>\`;
}

function renderPaper(prices) {
  const px = prices.prices||{};
  const get = t => px[t]||px[t+'.OL']||px[t+'.DE']||null;
  let totalPnl=0, wins=0, total=0;
  const rows = PAPER.map(p=>{
    const pr=get(p.ticker), eur=pr?.eur??null, chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry);
    if(pnl!=null){total++;if(pnl>0)wins++;}
    if(pnl!=null) totalPnl+=pnl;
    const sc=STRATEGIES.find(s=>s.id===p.strategy);
    const badge=sc?\`<span class="badge" style="background:\${sc.color}22;color:\${sc.color}">\${p.strategy}</span>\`:'';
    return \`<tr>
      <td><div class="ticker">\${p.ticker}</div><div class="muted" style="font-size:11px">\${p.name} \${badge}</div></td>
      <td class="muted">\${p.entry.toFixed(2)}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctStr(chg)}</td>
      <td>\${pctStr(pnl)}</td>
      <td>\${p.stop?p.stop+'€':'—'} / \${p.target?p.target+'€':'—'}</td>
    </tr>\`;
  });
  const avgPnl = total ? totalPnl/total : 0;
  const wr = total ? (wins/total*100).toFixed(0) : 0;
  document.getElementById('paper-stats').innerHTML=\`
    <div class="stat"><div class="stat-label">Ø P&L</div><div class="stat-value \${avgPnl>=0?'green':'red'}">\${avgPnl>=0?'+':''}\${avgPnl.toFixed(1)}%</div></div>
    <div class="stat"><div class="stat-label">Win-Rate</div><div class="stat-value">\${wr}%</div></div>
    <div class="stat"><div class="stat-label">Positionen</div><div class="stat-value">\${PAPER.length}</div></div>
  \`;
  document.getElementById('paper-table').innerHTML=\`<table><thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&L</th><th>Stop / Ziel</th></tr></thead><tbody>\${rows.join('')}</tbody></table>\`;
}

function renderEdit(cfg) {
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const rows=pos.map(p=>\`<tr>
    <td style="font-weight:700;padding:8px 10px">\${p.ticker}</td>
    <td style="padding:8px 5px"><input type="number" id="e-entry-\${p.ticker}" value="\${p.entry_eur||''}" step="0.01" style="width:90px"></td>
    <td style="padding:8px 5px"><input type="number" id="e-stop-\${p.ticker}" value="\${p.stop_eur||''}" step="0.01" style="width:90px"></td>
    <td style="padding:8px 5px"><input type="number" id="e-target-\${p.ticker}" value="\${p.target_eur||''}" step="0.01" style="width:90px"></td>
    <td style="padding:8px 5px">
      <button class="btn btn-primary btn-sm" onclick="savePos('\${p.ticker}')">💾</button>
      <span id="e-status-\${p.ticker}" style="font-size:11px;margin-left:6px"></span>
    </td>
  </tr>\`).join('');
  document.getElementById('edit-table').innerHTML=\`<table><thead><tr><th>Ticker</th><th>Entry €</th><th>Stop €</th><th>Ziel €</th><th></th></tr></thead><tbody>\${rows}</tbody></table>\`;
}

function renderStrat() {
  document.getElementById('strat-list').innerHTML = STRATEGIES.map(s=>\`
    <div class="strat-card">
      <div class="strat-badge" style="background:\${s.color}22;color:\${s.color}">\${s.id}</div>
      <div>
        <div style="font-weight:600">\${s.status} \${s.name}</div>
        <div class="muted" style="font-size:12px;margin-top:2px">\${s.desc}</div>
      </div>
    </div>\`).join('');
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
    if(d.status==='ok'){el.textContent='✅';el.style.color='var(--green)';setTimeout(()=>el.textContent='',3000);loadAll();}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

function setAction(a) {
  tradeAction=a;
  document.getElementById('btn-buy').className='btn btn-sm '+(a==='BUY'?'btn-primary':'btn-muted');
  document.getElementById('btn-sell').className='btn btn-sm '+(a==='SELL'?'btn-primary':'btn-muted');
  if(a==='SELL'){document.getElementById('btn-sell').style.background='var(--red)';}
}

async function logTrade() {
  const ticker=document.getElementById('l-ticker').value.toUpperCase();
  const price=parseFloat(document.getElementById('l-price').value);
  const stop=parseFloat(document.getElementById('l-stop').value)||null;
  const target=parseFloat(document.getElementById('l-target').value)||null;
  const notes=document.getElementById('l-notes').value;
  const el=document.getElementById('log-status');
  if(!ticker||!price){el.textContent='Ticker + Preis erforderlich!';el.style.color='var(--red)';return;}
  try {
    const r=await fetch('/api/trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,action:tradeAction,price_eur:price,stop_eur:stop,target_eur:target,notes})});
    const d=await r.json();
    if(d.status==='ok'){
      el.textContent=\`✅ \${tradeAction==='BUY'?'Kauf':'Verkauf'} \${ticker} @ \${price}€ gespeichert\`;
      el.style.color='var(--green)';
      ['l-ticker','l-price','l-stop','l-target','l-notes'].forEach(id=>document.getElementById(id).value='');
    }else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

loadAll();
setInterval(loadAll, 60000);
</script>
</body>
</html>`;

const PAPER_DATA = [
  {ticker:'ASML.AS',name:'ASML Holding',entry:1187.60,strategy:'PS3',stop:1100.0,target:1380.0},
  {ticker:'DHT',name:'DHT Holdings',entry:14.74,strategy:'PS2',stop:13.5,target:18.0},
  {ticker:'FRO',name:'Frontline',entry:26.40,strategy:'PS2',stop:24.0,target:33.0},
  {ticker:'GLEN.L',name:'Glencore',entry:6.07,strategy:'PS5',stop:5.5,target:7.5},
  {ticker:'HL',name:'Hecla Mining',entry:17.15,strategy:'PS4',stop:14.5,target:23.0},
  {ticker:'HO.PA',name:'Thales',entry:254.40,strategy:'PS3',stop:230.0,target:310.0},
  {ticker:'MOS',name:'Mosaic',entry:25.38,strategy:'PS5',stop:23.0,target:32.0},
  {ticker:'NOVO-B.CO',name:'Novo Nordisk',entry:32.32,strategy:'PS1',stop:29.0,target:42.0},
  {ticker:'OXY',name:'Occidental Petroleum',entry:50.63,strategy:'PS1',stop:46.0,target:64.0},
  {ticker:'PAAS',name:'Pan American Silver',entry:49.09,strategy:'PS4',stop:42.0,target:64.0},
  {ticker:'TTE.PA',name:'TotalEnergies',entry:74.48,strategy:'PS1',stop:68.0,target:92.0},
];

const STRATS = [
  {id:'PS1',color:'#3498db',name:'Iran/Öl-Geopolitik',status:'🟢',desc:'Hormuz-Blockade → Öl teuer → OXY, TTE, NOVO'},
  {id:'PS2',color:'#e67e22',name:'Tanker-Lag-These',status:'🟢',desc:'Öl steigt → Tanker 2-4W später → FRO, DHT'},
  {id:'PS3',color:'#2ecc71',name:'NATO/EU-Rüstung',status:'🟡',desc:'Verteidigungsbudgets steigen → ASML, HO.PA'},
  {id:'PS4',color:'#f1c40f',name:'Edelmetalle/Miner',status:'🟡',desc:'VIX hoch → Gold/Silber → HL, PAAS'},
  {id:'PS5',color:'#8b4513',name:'Dünger/Agrar-Superzyklus',status:'🟡',desc:'Russische Kali-Sanktionen → MOS, GLEN'},
  {id:'S1', color:'#e74c3c',name:'Iran/Öl (Real)',status:'🟢',desc:'EQNR.OL, RIO.L'},
  {id:'S2', color:'#9b59b6',name:'Rüstung (Real)',status:'🟡',desc:'RHM.DE'},
  {id:'S3', color:'#1abc9c',name:'KI-Halbleiter (Real)',status:'🟢',desc:'NVDA, MSFT, PLTR'},
];

module.exports = async function handler(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, no-cache');
  res.status(200).send(HTML(JSON.stringify(PAPER_DATA), JSON.stringify(STRATS)));
};
