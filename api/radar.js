// Vercel Serverless: Radar-Tab als eigenständige Seite
// GET /api/radar → vollständige HTML-Seite mit Scan + Deep Dive

module.exports = async function handler(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');

  const HTML = `<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📡 TradeMind Radar</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0e17;--card:#111827;--border:#1e293b;
  --text:#e2e8f0;--dim:#64748b;
  --cyan:#06b6d4;--green:#10b981;--red:#ef4444;--amber:#f59e0b;--purple:#a78bfa;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
a{color:var(--cyan);text-decoration:none}
.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.cyan{color:var(--cyan)}.dim{color:var(--dim)}

/* Topbar */
.topbar{background:#0f172a;border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{font-size:1.15rem;font-weight:700;display:flex;align-items:center;gap:10px}
.back-btn{background:none;border:1px solid var(--border);color:var(--dim);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.8rem}
.back-btn:hover{border-color:var(--cyan);color:var(--cyan)}

/* Layout */
.content{padding:16px;max-width:1200px;margin:0 auto}

/* KPI Grid */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:20px}
.kpi{text-align:center;padding:14px 10px;background:var(--card);border:1px solid var(--border);border-radius:10px}
.kpi .num{font-size:1.5rem;font-weight:700;line-height:1.2}
.kpi .label{font-size:.68rem;color:var(--dim);margin-top:4px;text-transform:uppercase;letter-spacing:.5px}

/* Radar Cards */
.radar-card{
  background:var(--card);border:1px solid var(--border);
  border-left:4px solid var(--border);border-radius:12px;
  padding:18px;margin-bottom:10px;
  display:grid;grid-template-columns:1fr auto;gap:16px;align-items:center;
  transition:border-color .15s,box-shadow .15s;cursor:default
}
.radar-card:hover{border-color:rgba(6,182,212,.4);box-shadow:0 0 0 1px rgba(6,182,212,.15)}
.radar-card.sc-high{border-left-color:var(--green)}
.radar-card.sc-mid{border-left-color:var(--amber)}
.radar-card.sc-low{border-left-color:var(--border)}

.rc-left{display:flex;flex-direction:column;gap:8px}
.rc-ticker{font-size:1.1rem;font-weight:700}
.rc-ticker a{color:var(--cyan)}
.rc-badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{font-size:.62rem;padding:2px 9px;border-radius:12px;font-weight:600}
.b-sector{background:rgba(6,182,212,.1);color:var(--cyan)}
.b-green{background:rgba(16,185,129,.15);color:var(--green)}
.b-red{background:rgba(239,68,68,.15);color:var(--red)}
.b-amber{background:rgba(245,158,11,.15);color:var(--amber)}
.b-gray{background:rgba(100,116,139,.15);color:var(--dim)}

.rc-metrics{display:flex;gap:20px;flex-wrap:wrap}
.metric .v{font-size:.9rem;font-weight:700;display:block}
.metric .l{font-size:.65rem;color:var(--dim);margin-top:1px}

.rc-signal{font-size:.72rem;color:var(--dim);border-top:1px solid rgba(30,41,59,.5);padding-top:7px;font-style:italic}

.rc-right{display:flex;flex-direction:column;align-items:flex-end;gap:12px;min-width:120px}
.score-wrap{text-align:center}
.score-num{font-size:2.2rem;font-weight:700;line-height:1}
.score-label{font-size:.6rem;color:var(--dim);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
.score-bar{height:5px;border-radius:3px;width:80px;background:var(--border);margin-top:6px}
.score-fill{height:5px;border-radius:3px}

.btn-dd{
  background:linear-gradient(135deg,#0e7490,#06b6d4);
  color:#fff;border:none;padding:9px 16px;border-radius:8px;
  cursor:pointer;font-size:.78rem;font-weight:600;
  white-space:nowrap;letter-spacing:.3px;transition:filter .15s
}
.btn-dd:hover{filter:brightness(1.12)}

/* ETF Grid */
.etf-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-top:6px}
.etf-card{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px}
.etf-ticker{font-size:.82rem;font-weight:700;color:var(--dim)}
.etf-chg{font-size:1.15rem;font-weight:700;line-height:1.2;margin-top:2px}
.etf-rsi{font-size:.68rem;color:var(--dim);margin-top:3px}

/* Section headers */
.section-header{display:flex;align-items:center;justify-content:space-between;margin:24px 0 12px}
.section-header h2{font-size:.82rem;text-transform:uppercase;letter-spacing:.8px;color:var(--dim)}
.section-header span{font-size:.72rem;color:var(--dim)}

/* Spinner */
.spinner{display:inline-block;width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--cyan);border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-state{text-align:center;padding:60px;color:var(--dim)}

/* ── Modal ────────────────────────────────────────────── */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:1000;display:none;align-items:center;justify-content:center;padding:16px}
.modal-bg.open{display:flex}
.modal{
  background:var(--card);border:1px solid var(--border);border-radius:16px;
  width:100%;max-width:680px;max-height:88vh;overflow-y:auto;
  display:flex;flex-direction:column
}
.modal-header{
  padding:18px 20px 14px;border-bottom:1px solid var(--border);
  display:flex;align-items:flex-start;justify-content:space-between;
  position:sticky;top:0;background:var(--card);z-index:2;border-radius:16px 16px 0 0
}
.modal-title{font-size:1.1rem;font-weight:700}
.modal-subtitle{font-size:.75rem;color:var(--dim);margin-top:3px}
.modal-close{background:none;border:1px solid var(--border);color:var(--dim);width:30px;height:30px;border-radius:6px;cursor:pointer;font-size:1rem;flex-shrink:0}
.modal-close:hover{border-color:var(--red);color:var(--red)}
.modal-body{padding:20px}

/* Modal KPI row */
.dd-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;margin-bottom:16px}
.dd-kpi{text-align:center;padding:10px 6px;background:var(--bg);border:1px solid var(--border);border-radius:8px}
.dd-kpi .v{font-size:1.2rem;font-weight:700}
.dd-kpi .l{font-size:.62rem;color:var(--dim);margin-top:2px}

/* 52W Range bar */
.range-bar{margin:14px 0}
.range-labels{display:flex;justify-content:space-between;font-size:.65rem;color:var(--dim);margin-bottom:4px}
.range-track{height:6px;background:var(--border);border-radius:3px;position:relative}
.range-dot{position:absolute;width:12px;height:12px;background:var(--cyan);border:2px solid var(--card);border-radius:50%;top:-3px;transform:translateX(-50%)}
.range-current{text-align:center;font-size:.68rem;color:var(--dim);margin-top:5px}

/* Setup visual */
.setup-row{display:flex;align-items:stretch;gap:0;margin:14px 0;font-size:.78rem;font-weight:600}
.setup-stop{background:rgba(239,68,68,.12);color:var(--red);border:1px solid rgba(239,68,68,.3);padding:8px 12px;border-radius:8px 0 0 8px;text-align:center}
.setup-entry{background:rgba(6,182,212,.12);color:var(--cyan);border:1px solid rgba(6,182,212,.3);padding:8px 14px;text-align:center;border-left:none;border-right:none}
.setup-target{background:rgba(16,185,129,.12);color:var(--green);border:1px solid rgba(16,185,129,.3);padding:8px 12px;border-radius:0 8px 8px 0;text-align:center}
.setup-label{font-size:.6rem;opacity:.7;display:block;font-weight:400;margin-top:2px}

/* Signal pills */
.signal-pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.sig-pill{padding:4px 11px;border-radius:16px;font-size:.75rem;font-weight:500}
.sp-ok{background:rgba(16,185,129,.12);color:var(--green)}
.sp-warn{background:rgba(245,158,11,.12);color:var(--amber)}
.sp-bad{background:rgba(239,68,68,.12);color:var(--red)}

/* DD sections */
.dd-section{padding:14px 0;border-top:1px solid rgba(30,41,59,.5)}
.dd-section:first-child{border-top:none;padding-top:0}
.dd-section h4{font-size:.7rem;text-transform:uppercase;letter-spacing:.8px;color:var(--dim);margin-bottom:10px}

/* News items */
.news-item{padding:7px 0;border-bottom:1px solid rgba(30,41,59,.3)}
.news-item:last-child{border-bottom:none}
.news-time{font-size:.67rem;color:var(--dim)}
.news-title{font-size:.82rem;margin-top:2px}

/* History */
.hist-item{padding:5px 0;border-bottom:1px solid rgba(30,41,59,.25);font-size:.78rem}
.hist-item:last-child{border-bottom:none}

/* Request button */
.btn-request{background:rgba(6,182,212,.12);border:1px solid rgba(6,182,212,.3);color:var(--cyan);padding:10px 20px;border-radius:8px;cursor:pointer;font-size:.85rem;font-weight:600;margin-top:14px}
.btn-request:hover{background:rgba(6,182,212,.2)}

@media(max-width:600px){
  .radar-card{grid-template-columns:1fr}
  .rc-right{flex-direction:row;align-items:center;justify-content:space-between;min-width:auto}
  .score-bar{width:60px}
}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">📡 TradeMind Radar</div>
  <button class="back-btn" onclick="window.location='/api/dashboard'">← Dashboard</button>
</div>

<div class="content">

  <!-- KPIs -->
  <div class="kpi-grid" id="kpis">
    <div class="kpi"><div class="num cyan">—</div><div class="label">Gescannte Ticker</div></div>
  </div>

  <!-- Top Setups -->
  <div class="section-header">
    <h2>🏆 Top Setups diese Woche</h2>
    <span id="scan-ts"></span>
  </div>
  <div id="scan-cards">
    <div class="loading-state"><div class="spinner"></div><br>Lade Scan-Daten...</div>
  </div>

  <!-- ETF Sektor-Rotation -->
  <div class="section-header">
    <h2>📊 Sektor-Rotation</h2>
    <span style="font-size:.7rem;color:var(--dim)">ETF Performance</span>
  </div>
  <div class="etf-grid" id="etf-grid"></div>

</div>

<!-- Deep Dive Modal -->
<div class="modal-bg" id="ddModal">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title" id="dd-title">🔬 Deep Dive</div>
        <div class="modal-subtitle" id="dd-subtitle"></div>
      </div>
      <button class="modal-close" onclick="closeDD()">✕</button>
    </div>
    <div class="modal-body" id="dd-body">
      <div class="loading-state"><div class="spinner"></div></div>
    </div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const cls=v=>v>=0?'green':'red';

// ── Scan laden ────────────────────────────────────────────────────────────────
async function loadScan(){
  try{
    const r=await fetch('/api/scan');
    const S=await r.json();
    if(S.error&&!(S.top||[]).length) throw new Error(S.error);
    renderScan(S);
  }catch(e){
    $('scan-cards').innerHTML='<div class="loading-state red">Fehler: '+esc(e.message)+'<br><small>Sonntags-Cron noch nicht gelaufen?</small></div>';
  }
}

function renderScan(S){
  const top=S.top||[], etfs=S.etf_rotation||[];

  // KPIs
  $('kpis').innerHTML=[
    {v:S.fetched||0,  l:'Gescannte Ticker', c:'cyan'},
    {v:S.setups_found||0, l:'Setups gefunden', c:(S.setups_found||0)>20?'green':'amber'},
    {v:top.length,    l:'Top Kandidaten',   c:''},
    {v:S.regime||'?', l:'Regime',           c:''},
    {v:S.vix||'?',   l:'VIX',              c:''},
    {v:'$'+(S.wti||'?'), l:'WTI',          c:''},
  ].map(k=>\`<div class="kpi"><div class="num \${k.c}">\${esc(String(k.v))}</div><div class="label">\${k.l}</div></div>\`).join('');

  // Timestamp
  if(S._generated) $('scan-ts').textContent='Stand: '+new Date(S._generated).toLocaleString('de-DE',{timeZone:'Europe/Berlin'});

  // Cards
  if(!top.length){
    $('scan-cards').innerHTML='<div class="loading-state"><div style="font-size:2.5rem;margin-bottom:10px">📭</div><strong>Noch kein Scan</strong><br><span>Läuft automatisch jeden Sonntag 08:00</span></div>';
  } else {
    $('scan-cards').innerHTML=top.map(c=>{
      const sc=c.score||0, rsi=c.rsi||50, chg=c.chg||0, fromH=c.from_high||0;
      const scCol=sc>=60?'var(--green)':sc>=40?'var(--amber)':'var(--dim)';
      const scClass=sc>=60?'sc-high':sc>=40?'sc-mid':'sc-low';
      const rsiCls=rsi<35?'b-green':rsi>70?'b-red':'b-amber';
      const rsiLbl=rsi<35?\`↓ RSI \${rsi.toFixed(0)} — Kaufzone\`:rsi>70?\`↑ RSI \${rsi.toFixed(0)} — Überkauft\`:\`RSI \${rsi.toFixed(0)}\`;
      const chgH=\`<span class="\${chg>=0?'green':'red'}">\${chg>=0?'+':''}\${chg.toFixed(1)}%</span>\`;
      const fromHH=\`<span class="\${fromH>-10?'amber':'red'}">\${fromH.toFixed(1)}%</span>\`;
      const sector=(c.sector||'').replace(/_/g,' ');
      return \`
      <div class="radar-card \${scClass}">
        <div class="rc-left">
          <div class="rc-ticker">
            <a href="https://finance.yahoo.com/chart/\${encodeURIComponent(c.ticker)}" target="_blank">\${esc(c.ticker)} ↗</a>
          </div>
          <div class="rc-badges">
            <span class="badge b-sector">\${esc(sector)}</span>
            <span class="badge \${rsiCls}">\${rsiLbl}</span>
            \${fromH<-30?'<span class="badge b-red">'+fromH.toFixed(0)+'% Korrektur</span>':fromH>-5?'<span class="badge b-green">Nahe High</span>':''}
          </div>
          <div class="rc-metrics">
            <div class="metric"><span class="v">\${c.price} \${esc(c.currency||'')}</span><span class="l">Kurs \${chgH}</span></div>
            <div class="metric"><span class="v">\${fromHH}</span><span class="l">vs 52W-High</span></div>
            <div class="metric"><span class="v \${c.crv>=3?'green':c.crv>=2?'amber':'red'}">\${c.crv}:1</span><span class="l">CRV</span></div>
            <div class="metric"><span class="v" style="font-family:monospace;font-size:.82rem">~\${c.entry} → \${c.stop}</span><span class="l">Entry → Stop</span></div>
          </div>
          <div class="rc-signal">→ \${esc((c.reason||'').slice(0,130))}</div>
        </div>
        <div class="rc-right">
          <div class="score-wrap">
            <div class="score-num" style="color:\${scCol}">\${sc}</div>
            <div class="score-label">Score</div>
            <div class="score-bar"><div class="score-fill" style="width:\${sc}%;background:\${scCol}"></div></div>
          </div>
          <button class="btn-dd" onclick="openDD('\${esc(c.ticker)}')">🔬 Deep Dive</button>
        </div>
      </div>\`;
    }).join('');
  }

  // ETF-Grid
  const sorted=[...etfs].sort((a,b)=>(b.chg_pct||0)-(a.chg_pct||0));
  $('etf-grid').innerHTML=sorted.map(e=>{
    const chg=e.chg_pct||0, rsi=e.rsi||50;
    const bg=chg>=0?'rgba(16,185,129,.07)':'rgba(239,68,68,.07)';
    const bc=chg>=0?'rgba(16,185,129,.2)':'rgba(239,68,68,.2)';
    const cc=chg>=0?'var(--green)':'var(--red)';
    const sig=rsi>70?'🔴 Überkauft':rsi<35?'🟢 Überverkauft':'⚪ Neutral';
    return \`<div class="etf-card" style="background:\${bg};border-color:\${bc}">
      <div class="etf-ticker">\${esc(e.ticker||'')}</div>
      <div class="etf-chg" style="color:\${cc}">\${chg>=0?'+':''}\${chg.toFixed(1)}%</div>
      <div class="etf-rsi">RSI \${rsi.toFixed(0)} — \${sig}</div>
    </div>\`;
  }).join('');
}

// ── Deep Dive Modal ───────────────────────────────────────────────────────────
function closeDD(){$('ddModal').classList.remove('open');}
$('ddModal').addEventListener('click',e=>{if(e.target===$('ddModal'))closeDD();});

async function openDD(ticker){
  $('dd-title').textContent='🔬 '+ticker;
  $('dd-subtitle').textContent='';
  $('dd-body').innerHTML='<div class="loading-state"><div class="spinner"></div><br>Lade Research...</div>';
  $('ddModal').classList.add('open');
  try{
    const r=await fetch('/api/research?ticker='+encodeURIComponent(ticker));
    if(r.status===404){ $('dd-body').innerHTML=renderDDEmpty(ticker); return; }
    const d=await r.json();
    if(d.error){ $('dd-body').innerHTML=renderDDEmpty(ticker); return; }
    $('dd-subtitle').textContent=(d.market?.currency||'')+'  ·  '+new Date(d._generated).toLocaleDateString('de-DE');
    $('dd-body').innerHTML=renderDD(d);
  }catch(e){
    $('dd-body').innerHTML='<div style="color:var(--red);padding:20px">Fehler: '+esc(e.message)+'</div>';
  }
}

async function requestDD(ticker){
  const btn=$('dd-req-btn');
  if(btn){btn.textContent='⏳ Wird angefordert…';btn.disabled=true;}
  try{
    const r=await fetch('/api/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker})});
    const d=await r.json();
    $('dd-body').innerHTML=d.queued
      ?'<div style="text-align:center;padding:30px"><div style="font-size:2rem;margin-bottom:10px">✅</div><strong>'+esc(ticker)+' in Queue!</strong><br><span class="dim" style="font-size:.82rem">Albert analysiert in ~5 Minuten. Dann hier nochmal öffnen.</span></div>'
      :'<div style="color:var(--amber);padding:20px">'+esc(d.message||d.error||'?')+'</div>';
  }catch(e){
    $('dd-body').innerHTML='<div style="color:var(--red);padding:20px">'+esc(e.message)+'</div>';
  }
}

function renderDDEmpty(ticker){
  return \`<div style="text-align:center;padding:30px">
    <div style="font-size:2.5rem;margin-bottom:12px">🔍</div>
    <strong>Noch kein Research für \${esc(ticker)}</strong>
    <br><span class="dim" style="font-size:.82rem">Albert analysiert Technicals, News und Setup</span>
    <br><button class="btn-request" id="dd-req-btn" onclick="requestDD('\${esc(ticker)}')">🔬 Deep Dive anfordern</button>
  </div>\`;
}

function renderDD(d){
  const m=d.market||{}, s=d.setup||{}, t=d.technicals||{}, news=d.news||[], history=d.history||[];
  const chg=m.chg_pct||0, rsi=m.rsi||50, fromH=m.from_high||0, fromL=m.from_low||0;
  const chgC=chg>=0?'green':'red', rsiC=rsi<35?'green':rsi>70?'red':'amber';
  let html='';

  // KPI-Zeile
  html+=\`<div class="dd-kpis">
    <div class="dd-kpi"><div class="v">\${(m.price||0).toFixed(2)} \${esc(m.currency||'')}</div><div class="l">Kurs</div></div>
    <div class="dd-kpi"><div class="v \${chgC}">\${chg>=0?'+':''}\${chg.toFixed(1)}%</div><div class="l">Heute</div></div>
    <div class="dd-kpi"><div class="v \${rsiC}">\${rsi.toFixed(0)}</div><div class="l">RSI 14</div></div>
    <div class="dd-kpi"><div class="v \${fromH>-10?'amber':'red'}">\${fromH.toFixed(1)}%</div><div class="l">vs High</div></div>
    <div class="dd-kpi"><div class="v \${s.crv>=3?'green':s.crv>=2?'amber':'red'}">\${(s.crv||0).toFixed(1)}:1</div><div class="l">CRV</div></div>
    <div class="dd-kpi"><div class="v">\${(m.vol_ratio||0).toFixed(1)}x</div><div class="l">Vol/Ø</div></div>
  </div>\`;

  // 52W-Range
  const pos52=Math.max(3,Math.min(97, fromL/(fromL-fromH+.001)*100));
  html+=\`<div class="range-bar">
    <div class="range-labels"><span>52W-Low: \${(m.w52_low||0).toFixed(2)}</span><span>52W-High: \${(m.w52_high||0).toFixed(2)}</span></div>
    <div class="range-track"><div class="range-dot" style="left:\${pos52}%"></div></div>
    <div class="range-current">Aktuell \${(m.price||0).toFixed(2)} — \${fromL.toFixed(1)}% über 52W-Low</div>
  </div>\`;

  // Setup
  html+=\`<div class="dd-section">
    <h4>🎯 Setup</h4>
    <div class="setup-row">
      <div class="setup-stop"><span class="setup-label">Stop</span>\${s.stop||'?'}</div>
      <div class="setup-entry"><span class="setup-label">Entry</span>~\${s.entry||'?'}</div>
      <div class="setup-target"><span class="setup-label">Ziel</span>\${s.target||'?'}</div>
    </div>
    <div style="font-size:.75rem;color:var(--dim)">
      Risiko: <strong class="red">\${s.risk_pct||'?'}%</strong> &nbsp;·&nbsp;
      Reward: <strong class="green">\${s.reward_pct||'?'}%</strong> &nbsp;·&nbsp;
      \${esc(m.currency||'')}
    </div>
  </div>\`;

  // Technische Signale
  html+=\`<div class="dd-section"><h4>⚡ Technische Signale</h4>
    <div class="signal-pills">\`;
  (t.verdicts||[]).forEach(v=>{
    const cls=v.startsWith('🟢')||v.startsWith('✅')?'sp-ok':v.startsWith('🔴')||v.startsWith('❌')?'sp-bad':'sp-warn';
    html+=\`<span class="sig-pill \${cls}">\${esc(v)}</span>\`;
  });
  html+=\`</div>
    <div style="font-size:.7rem;color:var(--dim);margin-top:10px">
      MA20: \${(m.ma20||0).toFixed(2)} &nbsp;·&nbsp; MA50: \${(m.ma50||0).toFixed(2)} &nbsp;·&nbsp; MA200: \${(m.ma200||0).toFixed(2)}
    </div>
  </div>\`;

  // News
  if(news.length){
    html+=\`<div class="dd-section"><h4>📰 News (7 Tage)</h4>\`;
    html+=news.slice(0,6).map(n=>{
      const dt=n.datetime?new Date(n.datetime*1000).toLocaleDateString('de-DE'):'';
      return \`<div class="news-item">
        <div class="news-time">\${dt}\${n.source?' · '+esc(n.source):''}</div>
        <div class="news-title">\${n.url?'<a href="'+esc(n.url)+'" target="_blank">'+esc(n.headline)+' ↗</a>':esc(n.headline)}</div>
      </div>\`;
    }).join('');
    html+=\`</div>\`;
  }

  // History
  if(history.length>1){
    html+=\`<div class="dd-section"><h4>📋 Research-Historie</h4>\`;
    html+=[...history].reverse().slice(0,5).map(h=>{
      const dt=h.date?new Date(h.date).toLocaleString('de-DE',{timeZone:'Europe/Berlin'}):'';
      return \`<div class="hist-item"><span class="dim" style="font-size:.68rem">\${dt}</span><br>\${esc(h.summary||h.action||'')}</div>\`;
    }).join('');
    html+=\`</div>\`;
  }

  html+=\`<div style="font-size:.65rem;color:var(--dim);text-align:right;padding-top:10px">Analysiert: \${d._generated?new Date(d._generated).toLocaleString('de-DE',{timeZone:'Europe/Berlin'}):'?'}</div>\`;
  return html;
}

loadScan();
</script>
</body>
</html>`;

  res.end(HTML);
};
