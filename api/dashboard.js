// TradeMind — Dashboard mit Sub-Navigationen
// Tab Real Portfolio: Übersicht | Bearbeiten | Eintragen
// Tab Paper Trades: Positionen | Strategien

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
   desc:'Solange der Iran-Konflikt die Straße von Hormuz bedroht, bleibt Öl teuer → Ölproduzenten profitieren.<br><br><strong>Kernthese:</strong> Iran + Houthi-Angriffe = Versicherungsprämie auf Öl. Jede Eskalation = bullisches Signal.<br><strong>Ausstieg wenn:</strong> Iran-Deal, Normalisierung der Tankerrouten, WTI dauerhaft unter 70$.'},
  {id:'PS2',color:'#e67e22',name:'Tanker-Lag-These',status:'🟢',conviction:'Mittel',tickers:['FRO','DHT'],
   desc:'Wenn Öl steigt, folgen Tanker-Aktien mit 2–4 Wochen Verzögerung. Wir kaufen Tanker BEVOR sie nachziehen.<br><br><strong>Kernthese:</strong> Steigende Ölpreise = mehr Tanker-Nachfrage + höhere Frachtraten → Aktien hinken nach.<br><strong>Ausstieg wenn:</strong> Öl fällt unter 70$ oder Frachtraten kollabieren.'},
  {id:'PS3',color:'#2ecc71',name:'NATO/EU-Rüstung',status:'🟡',conviction:'Mittel',tickers:['ASML.AS','HO.PA'],
   desc:'Europa erhöht Verteidigungsbudgets massiv → Rüstungs- und Dual-Use-Firmen bekommen Aufträge.<br><br><strong>Kernthese:</strong> 2% BIP-Ziel NATO → DE + FR + UK erhöhen Ausgaben. ASML (Chips für Guidance), Thales (Radar, Elektronik).<br><strong>Risiko:</strong> Ukraine-Waffenstillstand könnte Euphorie ausbremsen.'},
  {id:'PS4',color:'#f1c40f',name:'Edelmetalle/Miner',status:'🟡',conviction:'Mittel',tickers:['HL','PAAS'],
   desc:'Bei hoher Unsicherheit (VIX hoch, Geopolitik) fliehen Anleger in Gold/Silber → Minenproduzenten profitieren überproportional.<br><br><strong>Kernthese:</strong> Miner = gehebelte Wette auf Metallpreise. Bei Gold +20% → Miner oft +40–60%.<br><strong>Ausstieg wenn:</strong> VIX unter 18, Gold unter 2.500$.'},
  {id:'PS5',color:'#8b4513',name:'Dünger/Agrar-Superzyklus',status:'🟡',conviction:'Niedrig',tickers:['MOS','GLEN.L'],
   desc:'Russische Kali-Sanktionen + steigende Lebensmittelnachfrage → westliche Düngerproduzenten profitieren.<br><br><strong>Kernthese:</strong> Belarus + Russland = 40% des globalen Kali. Sanktionen = struktureller Engpass.<br><strong>Risiko:</strong> Sanktionslockerung, schlechte Ernte = weniger Nachfrage.'},
];

const HTML = () => {
const paperJSON = JSON.stringify(PAPER);
const stratJSON = JSON.stringify(STRATEGIES);
return `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeMind</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#7d8590;--green:#3fb950;--red:#f85149;--orange:#d29922;--accent:#7c3aed}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}

/* HEADER */
header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:200}
header h1{font-size:16px;font-weight:700}
.ts{font-size:11px;color:var(--muted);margin-left:auto}

/* MAIN TABS */
.main-nav{display:flex;background:var(--surface);border-bottom:1px solid var(--border)}
.main-nav button{flex:1;background:none;border:none;color:var(--muted);padding:13px;font-size:14px;font-weight:600;cursor:pointer;border-bottom:3px solid transparent;transition:color .15s}
.main-nav button.active{color:var(--text);border-bottom-color:var(--accent)}

/* SUB TABS */
.sub-nav{display:flex;background:var(--bg);border-bottom:1px solid var(--border);padding:0 20px;gap:4px}
.sub-nav button{background:none;border:none;color:var(--muted);padding:9px 14px;font-size:13px;cursor:pointer;border-bottom:2px solid transparent;transition:color .15s;white-space:nowrap}
.sub-nav button.active{color:var(--text);border-bottom-color:var(--accent)}

/* PANELS */
.main-panel{display:none}.main-panel.active{display:block}
.sub-panel{display:none;padding:16px 20px}.sub-panel.active{display:block}

/* MACRO */
.macro-strip{display:flex;gap:8px;overflow-x:auto;margin-bottom:20px;padding-bottom:2px}
.macro-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 14px;white-space:nowrap;min-width:80px}
.macro-key{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.macro-val{font-size:16px;font-weight:700;margin-top:2px}
.macro-sub{font-size:11px;margin-top:1px}

/* TABLE */
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}
td{padding:10px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.025)}
.ticker-name{font-weight:700;font-size:14px}
.ticker-sub{font-size:11px;color:var(--muted);margin-top:1px}
.stop-bar{height:3px;border-radius:2px;background:var(--border);margin-top:4px;max-width:80px}
.stop-fill{height:100%;border-radius:2px}

/* STATS */
.stat-row{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 16px;flex:1;min-width:110px}
.stat-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.stat-value{font-size:22px;font-weight:700;margin-top:4px}
.stat-sub{font-size:12px;margin-top:2px}

/* EDIT GRID */
.edit-row{display:grid;grid-template-columns:90px 1fr 1fr 1fr auto;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}
.edit-row:last-child{border-bottom:none}
.edit-ticker{font-weight:700;font-size:13px}
input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:7px 10px;border-radius:6px;font-size:13px;width:100%}
input:focus{outline:none;border-color:var(--accent)}
label{font-size:11px;color:var(--muted);display:block;margin-bottom:4px}

/* FORM */
.form-row{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.form-field{flex:1;min-width:90px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}

/* BUTTONS */
.btn{border:none;border-radius:6px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer}
.btn-primary{background:var(--accent);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-muted{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-sm{padding:5px 10px;font-size:12px}
.action-row{display:flex;gap:8px;margin-bottom:14px}
.action-row button{flex:1}

/* STRATEGY */
.strat-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden}
.strat-header{display:flex;align-items:center;gap:12px;padding:14px 16px;cursor:pointer;user-select:none}
.strat-header:hover{background:rgba(255,255,255,.025)}
.strat-badge{width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.strat-meta{font-size:12px;color:var(--muted);margin-top:2px}
.strat-chevron{font-size:12px;color:var(--muted);margin-left:auto;transition:transform .2s}
.strat-chevron.open{transform:rotate(180deg)}
.strat-body{display:none;padding:0 16px 16px 66px;font-size:13px;line-height:1.7}
.strat-body.open{display:block}
.tickers{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}

/* COLORS */
.green{color:var(--green)}.red{color:var(--red)}.orange{color:var(--orange)}.muted{color:var(--muted)}
.loading{text-align:center;padding:40px;color:var(--muted)}
.save-msg{font-size:12px;margin-left:8px}
</style>
</head>
<body>

<header>
  <span style="font-size:20px">🎩</span>
  <h1>TradeMind</h1>
  <button class="btn btn-muted" onclick="loadAll()" style="padding:6px 12px;font-size:12px">🔄</button>
  <span class="ts" id="ts">Lädt…</span>
</header>

<!-- HAUPT-TABS -->
<div class="main-nav">
  <button class="active" onclick="showMain('real',this)">📈 Real Portfolio</button>
  <button onclick="showMain('paper',this)">🧪 Paper Trades</button>
</div>

<!-- ═══ REAL PORTFOLIO ═══ -->
<div id="main-real" class="main-panel active">
  <div class="sub-nav">
    <button class="active" onclick="showSub('real','overview',this)">📊 Übersicht</button>
    <button onclick="showSub('real','edit',this)">✏️ Bearbeiten</button>
    <button onclick="showSub('real','log',this)">➕ Trade eintragen</button>
  </div>

  <!-- Übersicht -->
  <div id="real-overview" class="sub-panel active">
    <div class="macro-strip" id="macro-strip"><div class="loading">…</div></div>
    <div id="real-table"><div class="loading">Lädt…</div></div>
  </div>

  <!-- Bearbeiten -->
  <div id="real-edit" class="sub-panel">
    <p style="color:var(--muted);font-size:13px;margin-bottom:16px">Änderungen werden direkt in die Config gespeichert. Monitor übernimmt beim nächsten 15-Min-Run.</p>
    <div class="card" style="padding:0 16px">
      <div id="edit-table"><div class="loading">Lädt…</div></div>
    </div>
  </div>

  <!-- Trade eintragen -->
  <div id="real-log" class="sub-panel">
    <div class="card">
      <div style="font-weight:600;font-size:14px;margin-bottom:14px">Neuen Trade eintragen</div>
      <div class="action-row">
        <button id="btn-buy" class="btn btn-primary" onclick="setAction('BUY')">✅ KAUF</button>
        <button id="btn-sell" class="btn btn-muted" onclick="setAction('SELL')">🔴 VERKAUF</button>
      </div>
      <div class="form-row">
        <div class="form-field"><label>Ticker</label><input id="l-ticker" placeholder="z.B. EQNR"></div>
        <div class="form-field"><label>Preis (€)</label><input id="l-price" type="number" step="0.01" placeholder="0.00"></div>
        <div class="form-field"><label>Stop (€)</label><input id="l-stop" type="number" step="0.01" placeholder="0.00"></div>
        <div class="form-field"><label>Ziel (€)</label><input id="l-target" type="number" step="0.01" placeholder="0.00"></div>
      </div>
      <div class="form-row">
        <div class="form-field" style="flex:3"><label>Notiz</label><input id="l-notes" placeholder="z.B. EMA50-Rücklauf, CRV 5:1"></div>
      </div>
      <button class="btn btn-primary" onclick="logTrade()">💾 Speichern</button>
      <span id="log-status" class="save-msg"></span>
    </div>
  </div>
</div>

<!-- ═══ PAPER TRADES ═══ -->
<div id="main-paper" class="main-panel">
  <div class="sub-nav">
    <button class="active" onclick="showSub('paper','positions',this)">📋 Positionen</button>
    <button onclick="showSub('paper','strat',this)">🧠 Strategien</button>
  </div>

  <!-- Positionen -->
  <div id="paper-positions" class="sub-panel active">
    <div class="stat-row" id="paper-stats"></div>
    <div id="paper-table"><div class="loading">Lädt…</div></div>
  </div>

  <!-- Strategien -->
  <div id="paper-strat" class="sub-panel">
    <div id="strat-list"></div>
  </div>
</div>

<script>
const PAPER = ${paperJSON};
const STRATEGIES = ${stratJSON};
let cfg = null, prices = null, tradeAction = 'BUY';

function showMain(name, btn) {
  document.querySelectorAll('.main-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.main-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('main-'+name).classList.add('active');
  if(btn) btn.classList.add('active');
}

function showSub(main, sub, btn) {
  const panel = document.getElementById('main-'+main);
  panel.querySelectorAll('.sub-panel').forEach(p=>p.classList.remove('active'));
  panel.querySelectorAll('.sub-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(main+'-'+sub).classList.add('active');
  if(btn) btn.classList.add('active');
}

function pct(v,b){return b?(((v-b)/b)*100):null}
function pctHtml(v){
  if(v==null) return '<span class="muted">—</span>';
  const c=v>=0?'green':'red', s=v>=0?'▲ +':'▼ ';
  return \`<span class="\${c}">\${s}\${Math.abs(v).toFixed(1)}%</span>\`;
}
function getP(px,t){return px[t]||px[t+'.OL']||px[t+'.DE']||px[t+'.L']||null}

function stopCell(price, stop) {
  if(!stop) return '<span class="red" style="font-size:12px">⚠️ kein Stop</span>';
  const d=price?(price-stop)/price*100:null;
  const col=d!=null&&d<2?'var(--red)':d!=null&&d<5?'var(--orange)':'var(--green)';
  const bar=d!=null?Math.min(d*8,100):0;
  return \`<div><span style="color:\${col};font-weight:600">\${stop.toFixed(2)}€</span>
           <span class="muted" style="font-size:11px"> (\${d!=null?d.toFixed(1):'?'}% weg)</span></div>
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
    renderReal(cfg, prices);
    renderEdit(cfg);
    renderPaper(prices);
    renderStrat();
    document.getElementById('ts').textContent=new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
  } catch(e){
    document.getElementById('ts').textContent='⚠️ '+e.message;
  }
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

function renderReal(cfg, prices) {
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  const px=prices.prices||{};
  const rows=pos.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry_eur);
    return \`<tr>
      <td><div class="ticker-name">\${p.ticker}</div><div class="ticker-sub">\${p.name||''}</div></td>
      <td class="muted">\${p.entry_eur?.toFixed(2)??'—'}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(chg)}</td>
      <td>\${pctHtml(pnl)}</td>
      <td>\${stopCell(eur,p.stop_eur)}</td>
    </tr>\`;
  });
  document.getElementById('real-table').innerHTML=\`
    <table>
      <thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>Ges. P&amp;L</th><th>Stop</th></tr></thead>
      <tbody>\${rows.join('')||'<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">Keine offenen Positionen</td></tr>'}</tbody>
    </table>\`;
}

function renderEdit(cfg) {
  const pos=(cfg.positions||[]).filter(p=>p.status!=='CLOSED');
  if(!pos.length){document.getElementById('edit-table').innerHTML='<p class="muted" style="padding:16px 0">Keine Positionen</p>';return;}
  document.getElementById('edit-table').innerHTML=pos.map(p=>\`
    <div class="edit-row">
      <div class="edit-ticker">\${p.ticker}</div>
      <div><label>Entry €</label><input type="number" id="e-entry-\${p.ticker}" value="\${p.entry_eur||''}" step="0.01"></div>
      <div><label>Stop €</label><input type="number" id="e-stop-\${p.ticker}" value="\${p.stop_eur||''}" step="0.01"></div>
      <div><label>Ziel €</label><input type="number" id="e-target-\${p.ticker}" value="\${p.target_eur||''}" step="0.01"></div>
      <div style="padding-top:18px">
        <button class="btn btn-primary btn-sm" onclick="savePos('\${p.ticker}')">💾</button>
        <span id="e-status-\${p.ticker}" class="save-msg"></span>
      </div>
    </div>\`).join('');
}

function renderPaper(prices) {
  const px=prices.prices||{};
  let sumPnl=0,wins=0,cnt=0;
  const CASH=71, POS_CAPITAL=900;
  const rows=PAPER.map(p=>{
    const pr=getP(px,p.ticker),eur=pr?.eur??null,chg=pr?.dayChange??null;
    const pnl=pct(eur,p.entry);
    if(pnl!=null){cnt++;sumPnl+=pnl;if(pnl>0)wins++;}
    const s=STRATEGIES.find(s=>s.id===p.strategy);
    const badge=s?\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${p.strategy}</span>\`:'';
    return \`<tr>
      <td><div class="ticker-name">\${p.ticker}</div><div class="ticker-sub">\${p.name} \${badge}</div></td>
      <td class="muted">\${p.entry.toFixed(2)}€</td>
      <td>\${eur!=null?\`<strong>\${eur.toFixed(2)}€</strong>\`:'—'}</td>
      <td>\${pctHtml(chg)}</td>
      <td>\${pctHtml(pnl)}</td>
      <td class="muted" style="font-size:12px">\${p.stop||'—'}€ / \${p.target||'—'}€</td>
    </tr>\`;
  });
  const avg=cnt?sumPnl/cnt:0;
  const wr=cnt?(wins/cnt*100):0;
  const curVal=Math.round(POS_CAPITAL*(1+avg/100)+CASH);
  const diff=curVal-1000;
  document.getElementById('paper-stats').innerHTML=\`
    <div class="stat"><div class="stat-label">Startkapital</div><div class="stat-value">1.000€</div></div>
    <div class="stat"><div class="stat-label">Akt. Wert</div><div class="stat-value \${curVal>=1000?'green':'red'}">\${curVal}€</div><div class="stat-sub \${diff>=0?'green':'red'}">\${diff>=0?'+':''}\${diff}€</div></div>
    <div class="stat"><div class="stat-label">Ø P&amp;L</div><div class="stat-value \${avg>=0?'green':'red'}">\${avg>=0?'+':''}\${avg.toFixed(1)}%</div></div>
    <div class="stat"><div class="stat-label">Win-Rate</div><div class="stat-value">\${wr.toFixed(0)}%</div><div class="stat-sub muted">\${wins}/\${cnt}</div></div>
    <div class="stat"><div class="stat-label">Bares Geld</div><div class="stat-value">\${CASH}€</div><div class="stat-sub muted">7% vom Fund</div></div>
  \`;
  document.getElementById('paper-table').innerHTML=\`
    <table>
      <thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&amp;L</th><th>Stop / Ziel</th></tr></thead>
      <tbody>\${rows.join('')}</tbody>
    </table>\`;
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
        <div class="strat-chevron" id="chev-\${i}">▼</div>
      </div>
      <div class="strat-body" id="strat-body-\${i}">
        \${s.desc}
        <div class="tickers">\${s.tickers.map(t=>\`<span class="badge" style="background:\${s.color}22;color:\${s.color}">\${t}</span>\`).join('')}</div>
      </div>
    </div>\`).join('');
}

function toggleStrat(i) {
  document.getElementById('strat-body-'+i).classList.toggle('open');
  document.getElementById('chev-'+i).classList.toggle('open');
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
    if(d.status==='ok'){el.textContent='✅ gespeichert';el.style.color='var(--green)';setTimeout(()=>{el.textContent='';loadAll();},1200);}
    else{el.textContent='❌ '+d.error;el.style.color='var(--red)';}
  }catch(e){el.textContent='❌ '+e.message;el.style.color='var(--red)';}
}

function setAction(a) {
  tradeAction=a;
  document.getElementById('btn-buy').className='btn '+(a==='BUY'?'btn-primary':'btn-muted');
  document.getElementById('btn-sell').className='btn '+(a==='SELL'?'btn-danger':'btn-muted');
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
      el.textContent=\`✅ \${tradeAction==='BUY'?'Kauf':'Verkauf'} \${ticker} @ \${price}€\`;
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
};

module.exports = async function handler(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, no-cache');
  res.status(200).send(HTML());
};
