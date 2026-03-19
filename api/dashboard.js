// Vercel Serverless: liefert TradeMind Dashboard HTML
// Kein CDN-Cache, immer aktuell
module.exports = async function handler(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, no-cache');
  res.status(200).send(`<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeMind v2</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --muted: #7d8590; --green: #3fb950;
  --red: #f85149; --orange: #d29922; --blue: #58a6ff; --accent: #7c3aed;
}
body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; }
header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 100; }
header h1 { font-size: 16px; font-weight: 700; }
.ts { font-size: 11px; color: var(--muted); margin-left: auto; }
nav { display: flex; background: var(--surface); border-bottom: 1px solid var(--border); overflow-x: auto; }
nav button { background: none; border: none; color: var(--muted); padding: 10px 18px; font-size: 13px; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
nav button.active { color: var(--text); border-bottom-color: var(--accent); }
.tab { display: none; padding: 16px 20px; }
.tab.active { display: block; }
.macro-strip { display: flex; gap: 8px; overflow-x: auto; margin-bottom: 16px; }
.macro-item { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; white-space: nowrap; min-width: 80px; }
.macro-key { font-size: 10px; color: var(--muted); text-transform: uppercase; }
.macro-val { font-size: 15px; font-weight: 700; margin-top: 1px; }
.macro-sub { font-size: 11px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tr:hover td { background: rgba(255,255,255,.02); }
.ticker { font-weight: 700; font-size: 14px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.badge-green { background: rgba(63,185,80,.15); color: var(--green); }
.badge-red { background: rgba(248,81,73,.15); color: var(--red); }
.badge-orange { background: rgba(210,153,34,.15); color: var(--orange); }
.stop-bar { height: 3px; border-radius: 2px; background: var(--border); margin-top: 3px; }
.stop-fill { height: 100%; border-radius: 2px; }
.btn { border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-refresh { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn-sm { padding: 5px 10px; font-size: 12px; }
.form-row { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; flex-wrap: wrap; }
label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 3px; }
input, select { background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 8px 10px; border-radius: 6px; font-size: 13px; width: 100%; }
input:focus, select:focus { outline: none; border-color: var(--accent); }
.field-group { flex: 1; min-width: 100px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 12px; }
.green { color: var(--green); } .red { color: var(--red); } .orange { color: var(--orange); } .muted { color: var(--muted); }
.loading { text-align: center; padding: 40px; color: var(--muted); }
.save-ok { color: var(--green); font-size: 12px; }
.save-err { color: var(--red); font-size: 12px; }
</style>
</head>
<body>

<header>
  <span style="font-size:20px">🎩</span>
  <h1>TradeMind v2</h1>
  <button class="btn btn-refresh" onclick="loadAll()" style="padding:6px 14px;font-size:12px">🔄 Aktualisieren</button>
  <span class="ts" id="ts">Lädt...</span>
</header>

<nav>
  <button class="active" onclick="showTab('portfolio',this)">📊 Portfolio</button>
  <button onclick="showTab('edit',this)">✏️ Stops bearbeiten</button>
  <button onclick="showTab('log',this)">📋 Trade Log</button>
</nav>

<!-- PORTFOLIO TAB -->
<div id="tab-portfolio" class="tab active">
  <div class="macro-strip" id="macro-strip"></div>
  <div id="portfolio-table"><div class="loading">Lädt...</div></div>
</div>

<!-- EDIT TAB -->
<div id="tab-edit" class="tab">
  <div class="card">
    <p style="color:var(--muted);font-size:13px;margin-bottom:16px">Änderungen werden direkt in die Config gespeichert. Monitor übernimmt beim nächsten Run (alle 15 Min).</p>
    <div id="edit-table"><div class="loading">Lädt...</div></div>
  </div>
</div>

<!-- TRADE LOG TAB -->
<div id="tab-log" class="tab">
  <div class="card" style="margin-bottom:16px">
    <div style="font-size:14px;font-weight:600;margin-bottom:14px">Trade eintragen</div>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button id="btn-buy" class="btn btn-primary btn-sm" onclick="setAction('BUY')" style="flex:1">KAUF</button>
      <button id="btn-sell" class="btn btn-sm" onclick="setAction('SELL')" style="flex:1;background:var(--surface);border:1px solid var(--border);color:var(--text)">VERKAUF</button>
    </div>
    <div class="form-row">
      <div class="field-group"><label>Ticker</label><input id="l-ticker" placeholder="z.B. EQNR"></div>
      <div class="field-group"><label>Preis (€)</label><input id="l-price" type="number" step="0.01" placeholder="0.00"></div>
      <div class="field-group"><label>Stop (€)</label><input id="l-stop" type="number" step="0.01" placeholder="0.00"></div>
    </div>
    <div class="form-row">
      <div class="field-group"><label>Ziel (€)</label><input id="l-target" type="number" step="0.01" placeholder="0.00"></div>
      <div class="field-group" style="flex:2"><label>Notiz</label><input id="l-notes" placeholder="z.B. EMA50-Rücklauf"></div>
    </div>
    <button class="btn btn-primary" onclick="logTrade()">Trade speichern</button>
    <span id="log-status" style="margin-left:10px;font-size:12px"></span>
  </div>
</div>

<script>
const API = '';
let cfg = null, prices = null, tradeAction = 'BUY';

function showTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (btn) btn.classList.add('active');
}

async function loadAll() {
  document.getElementById('ts').textContent = '⏳ Lädt...';
  try {
    [cfg, prices] = await Promise.all([
      fetch(\`\${API}/api/config\`).then(r => r.json()),
      fetch(\`\${API}/api/prices\`).then(r => r.json()),
    ]);
    renderMacro(prices);
    renderPortfolio(cfg, prices);
    renderEdit(cfg, prices);
    const now = new Date().toLocaleString('de-DE', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
    document.getElementById('ts').textContent = 'Stand: ' + now;
  } catch(e) {
    document.getElementById('ts').textContent = '⚠️ Fehler: ' + e.message;
  }
}

function renderMacro(p) {
  const m = p.macro || {};
  const f = p.fx || {};
  const vix = m.vix || 0;
  const vixColor = vix > 30 ? 'var(--red)' : vix > 25 ? 'var(--orange)' : 'var(--green)';
  const nk = m.nikkei || 0;
  const strip = document.getElementById('macro-strip');
  strip.innerHTML = \`
    <div class="macro-item"><div class="macro-key">VIX</div><div class="macro-val" style="color:\${vixColor}">\${vix.toFixed(1)}</div><div class="macro-sub muted">\${vix>30?'🔴 Panik':vix>25?'🟠 Erhöht':'🟢 Normal'}</div></div>
    <div class="macro-item"><div class="macro-key">WTI</div><div class="macro-val">$\${(m.wti||0).toFixed(0)}</div><div class="macro-sub muted">Öl</div></div>
    <div class="macro-item"><div class="macro-key">Nikkei</div><div class="macro-val" style="color:\${nk<-3?'var(--red)':nk<0?'var(--orange)':'var(--green)'}">\${nk>=0?'+':''}\${nk.toFixed(1)}%</div><div class="macro-sub muted">225</div></div>
    <div class="macro-item"><div class="macro-key">EUR/USD</div><div class="macro-val">\${(f.EURUSD||0).toFixed(4)}</div><div class="macro-sub muted">FX</div></div>
  \`;
}

function renderPortfolio(cfg, prices) {
  const pos = cfg.positions || [];
  const px = prices.prices || {};
  const getPrice = (ticker) => {
    return px[ticker] || px[ticker+'.OL'] || px[ticker+'.DE'] || px[ticker+'.L'] || null;
  };
  const rows = pos.filter(p => p.status !== 'CLOSED').map(p => {
    const pr = getPrice(p.ticker);
    const eur = pr?.eur ?? null;
    const chg = pr?.dayChange ?? null;
    const entry = p.entry_eur;
    const stop = p.stop_eur;
    const pnl = eur && entry ? (eur - entry) / entry * 100 : null;
    const stopDist = eur && stop ? (eur - stop) / eur * 100 : null;
    const pnlStr = pnl != null ? \`<span class="\${pnl>=0?'green':'red'}">\${pnl>=0?'📈':'📉'} \${pnl>=0?'+':''}\${pnl.toFixed(1)}%</span>\` : '—';
    const chgStr = chg != null ? \`<span class="\${chg>=0?'green':'red'}">\${chg>=0?'▲':'▼'} \${chg>=0?'+':''}\${chg.toFixed(1)}%</span>\` : '—';
    const prStr = eur != null ? \`<strong>\${eur.toFixed(2)}€</strong>\` : '—';
    let stopStr, stopBar = '';
    if (!stop) {
      stopStr = '<span class="red">⚠️ KEIN STOP</span>';
    } else {
      const dist = stopDist != null ? stopDist.toFixed(1) : '?';
      const barColor = stopDist != null && stopDist < 2 ? 'var(--red)' : stopDist != null && stopDist < 5 ? 'var(--orange)' : 'var(--green)';
      const barW = stopDist != null ? Math.min(stopDist * 8, 100) : 0;
      stopStr = \`<span style="color:\${barColor}">\${stop.toFixed(2)}€</span> <small class="muted">(\${dist}%)</small>\`;
      stopBar = \`<div class="stop-bar"><div class="stop-fill" style="width:\${barW}%;background:\${barColor}"></div></div>\`;
    }
    return \`<tr>
      <td><div class="ticker">\${p.ticker}</div><div class="muted" style="font-size:11px">\${p.name}</div></td>
      <td class="muted">\${entry?.toFixed(2) ?? '—'}€</td>
      <td>\${prStr}</td>
      <td>\${chgStr}</td>
      <td>\${pnlStr}</td>
      <td>\${stopStr}\${stopBar}</td>
    </tr>\`;
  });
  document.getElementById('portfolio-table').innerHTML = \`
    <table>
      <thead><tr><th>Position</th><th>Entry</th><th>Kurs</th><th>Heute</th><th>P&L</th><th>Stop</th></tr></thead>
      <tbody>\${rows.join('')}</tbody>
    </table>\`;
}

function renderEdit(cfg, prices) {
  const pos = cfg.positions || [];
  const rows = pos.filter(p => p.status !== 'CLOSED').map(p => \`
    <tr>
      <td style="font-weight:700;padding:8px 10px">\${p.ticker}</td>
      <td style="padding:8px 5px"><input type="number" id="e-entry-\${p.ticker}" value="\${p.entry_eur||''}" step="0.01" style="width:90px"></td>
      <td style="padding:8px 5px"><input type="number" id="e-stop-\${p.ticker}" value="\${p.stop_eur||''}" step="0.01" style="width:90px"></td>
      <td style="padding:8px 5px"><input type="number" id="e-target-\${p.ticker}" value="\${p.target_eur||''}" step="0.01" style="width:90px"></td>
      <td style="padding:8px 5px">
        <button class="btn btn-primary btn-sm" onclick="savePos('\${p.ticker}')">💾</button>
        <span id="e-status-\${p.ticker}" style="font-size:11px;margin-left:6px"></span>
      </td>
    </tr>\`).join('');
  document.getElementById('edit-table').innerHTML = \`
    <table>
      <thead><tr><th>Ticker</th><th>Entry €</th><th>Stop €</th><th>Ziel €</th><th></th></tr></thead>
      <tbody>\${rows}</tbody>
    </table>\`;
}

async function savePos(ticker) {
  const entry = document.getElementById(\`e-entry-\${ticker}\`)?.value;
  const stop  = document.getElementById(\`e-stop-\${ticker}\`)?.value;
  const target= document.getElementById(\`e-target-\${ticker}\`)?.value;
  const el = document.getElementById(\`e-status-\${ticker}\`);
  el.textContent = '⏳'; el.className = 'muted';
  try {
    const r = await fetch(\`\${API}/api/config\`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ ticker, entry_eur: entry, stop_eur: stop||null, target_eur: target||null }),
    });
    const d = await r.json();
    if (d.status === 'ok') { el.textContent = '✅'; el.className = 'save-ok'; setTimeout(()=>el.textContent='',3000); }
    else { el.textContent = '❌ ' + (d.error||'Fehler'); el.className = 'save-err'; }
  } catch(e) { el.textContent = '❌ ' + e.message; el.className = 'save-err'; }
}

function setAction(a) {
  tradeAction = a;
  document.getElementById('btn-buy').style.background = a==='BUY' ? 'var(--accent)' : 'var(--surface)';
  document.getElementById('btn-buy').style.color = a==='BUY' ? '#fff' : 'var(--text)';
  document.getElementById('btn-sell').style.background = a==='SELL' ? 'var(--red)' : 'var(--surface)';
  document.getElementById('btn-sell').style.color = a==='SELL' ? '#fff' : 'var(--text)';
  document.getElementById('btn-buy').style.border = a==='BUY' ? 'none' : '1px solid var(--border)';
  document.getElementById('btn-sell').style.border = a==='SELL' ? 'none' : '1px solid var(--border)';
}

async function logTrade() {
  const ticker = document.getElementById('l-ticker').value.toUpperCase();
  const price  = parseFloat(document.getElementById('l-price').value);
  const stop   = parseFloat(document.getElementById('l-stop').value)||null;
  const target = parseFloat(document.getElementById('l-target').value)||null;
  const notes  = document.getElementById('l-notes').value;
  const el = document.getElementById('log-status');
  if (!ticker || !price) { el.textContent = 'Ticker + Preis pflicht!'; el.className='save-err'; return; }
  try {
    const r = await fetch(\`\${API}/api/trade\`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ticker, action:tradeAction, price_eur:price, stop_eur:stop, target_eur:target, notes}),
    });
    const d = await r.json();
    if (d.status==='ok') {
      el.textContent = \`✅ \${tradeAction==='BUY'?'Kauf':'Verkauf'} \${ticker} @ \${price}€ gespeichert\`;
      el.className='save-ok';
      document.getElementById('l-ticker').value='';
      document.getElementById('l-price').value='';
      document.getElementById('l-stop').value='';
      document.getElementById('l-target').value='';
      document.getElementById('l-notes').value='';
    } else { el.textContent='❌ '+d.error; el.className='save-err'; }
  } catch(e) { el.textContent='❌ '+e.message; el.className='save-err'; }
}

// Auf Load und alle 60s
loadAll();
setInterval(loadAll, 60000);
</script>
</body>
</html>
`);
};
