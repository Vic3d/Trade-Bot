// api/data.js — Combined Data Router
// Ersetzt: daytrades.js, dna.js, news.js, prices.js, risk.js, signals.js, trade-log.js
// Route via: /api/data?_route=<name>  (intern via vercel.json rewrite)
// Alte URLs bleiben identisch — kein Dashboard-Code muss geändert werden

const fs   = require('fs');
const path = require('path');
const { requireAuth } = require('../lib/auth');

// ─── Helper ────────────────────────────────────────────────────────────────────
const readJSON = (rel, def = {}) => {
  try {
    const p = path.join(process.cwd(), rel);
    return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : def;
  } catch { return def; }
};

// ─── Handler: daytrades ────────────────────────────────────────────────────────
const STRATEGY_META = {
  DT1:{setup_type:'Momentum-Breakout',trigger:'Break über Widerstand + Volumen > 1.5x',stop_pct:1.5,target_pct:3.0,crv:2.0,watch:'Scanner ermittelt täglich'},
  DT2:{setup_type:'Mean-Reversion Oversold',trigger:'RSI < 30 + Tageskerze Hammer',stop_pct:1.2,target_pct:2.5,crv:2.1,watch:'Scanner ermittelt täglich'},
  DT3:{setup_type:'Gap-Fill',trigger:'Gap-Up/Down > 1% vorbörslich + Retest',stop_pct:1.0,target_pct:2.0,crv:2.0,watch:'Scanner ermittelt täglich'},
  DT4:{setup_type:'News-Catalyst',trigger:'CRITICAL News-Alert + Kurs bewegt sich',stop_pct:2.0,target_pct:4.0,crv:2.0,watch:'EQNR / PLTR / A3D42Y'},
  DT5:{setup_type:'VWAP-Bounce',trigger:'Kurs unter VWAP + Bounce mit Volumen',stop_pct:1.2,target_pct:2.4,crv:2.0,watch:'Scanner ermittelt täglich'},
  DT6:{setup_type:'Triple RSI Mean Reversion',trigger:'RSI(2)<10 + RSI(5)<25 + RSI(14)<40',stop_pct:1.5,target_pct:3.0,crv:2.0,watch:'Scanner ermittelt täglich'},
  DT7:{setup_type:'Internal Bar Strength (IBS)',trigger:'IBS < 0.2 (Close nahe Tagestief)',stop_pct:1.0,target_pct:2.5,crv:2.5,watch:'Scanner ermittelt täglich'},
  DT8:{setup_type:'BB Squeeze Breakout',trigger:'Bollinger Bands < 1% Breite + Break',stop_pct:1.5,target_pct:4.5,crv:3.0,watch:'Scanner ermittelt täglich'},
  DT9:{setup_type:'Sektor-Momentum',trigger:'Stärkster Sektor + Top-Aktie',stop_pct:1.5,target_pct:3.0,crv:2.0,watch:'Stärkster Sektor des Tages'},
};
function handleDaytrades(req, res) {
  const dna       = readJSON('data/dna.json', { open_positions: [], strategies: [] });
  const allStrats = readJSON('data/strategies.json', {});
  const state     = readJSON('memory/daytrader-state.json', { daily_pnl:0, daily_trades:0, last_date:null });
  const openDT    = (dna.open_positions || []).filter(p => p.trade_type === 'day_trade');
  const dtStrategies = Object.entries(allStrats)
    .filter(([id]) => id.startsWith('DT'))
    .map(([id, s]) => {
      const meta = STRATEGY_META[id] || {};
      return { id, name:s.name||id, thesis:s.thesis||'', setup_type:meta.setup_type||'',
               trigger:meta.trigger||'', stop_pct:meta.stop_pct||1.5, target_pct:meta.target_pct||3.0,
               crv:meta.crv||2.0, conviction:s.genesis?.conviction_current||3, status:s.status||'active',
               win_rate:s.performance?.win_rate||0, total_trades:s.performance?.total_trades||0,
               wins:s.performance?.wins||0, losses:s.performance?.losses||0 };
    }).sort((a,b) => a.id.localeCompare(b.id));
  res.json({ open:openDT, strategies:dtStrategies, state, capital:25000, pos_size:5000, max_positions:5, updated:dna.updated||null, auto_generated:false });
}

// ─── Handler: dna ─────────────────────────────────────────────────────────────
function handleDna(req, res) {
  const p = path.join(process.cwd(), 'data/dna.json');
  if (fs.existsSync(p)) res.status(200).send(fs.readFileSync(p,'utf8'));
  else res.json({ stats:{}, strategies:[], trader_profile:{}, updated:null });
}

// ─── Handler: risk ────────────────────────────────────────────────────────────
function handleRisk(req, res) {
  const risk    = readJSON('data/risk.json', { overall_score:0, sector_exposure:{}, correlation_warnings:[] });
  const corr    = readJSON('data/correlations.json', {});
  const alerts  = readJSON('data/alerts.json', []);
  res.json({ risk, correlations:corr, alerts:(Array.isArray(alerts)?alerts:[]).slice(-50), updated:risk.updated||null });
}

// ─── Handler: signals ─────────────────────────────────────────────────────────
const SIG_FILES = {
  signals:    'data/signals.json',
  confidence: 'data/confidence_score.json',
  lag:        'data/lag_knowledge.json',
};
const SIG_DEF = {
  signals:    { signals:[], stats:{total:0,wins:0,losses:0,pending:0,accuracy_pct:null}, updated:null },
  confidence: { score:0, label:'⚪ KEIN SIGNAL', action:'Noch kein Score berechnet', factors:[], updated:null },
  lag:        { pairs:{} },
};
function handleSignals(req, res) {
  const subtype = req.query.type || req.query.subtype || 'signals';
  const file = SIG_FILES[subtype] || SIG_FILES.signals;
  const def  = SIG_DEF[subtype]  || SIG_DEF.signals;
  const p = path.join(process.cwd(), file);
  if (fs.existsSync(p)) res.status(200).send(fs.readFileSync(p,'utf8'));
  else res.json(def);
}

// ─── Handler: tradelog ────────────────────────────────────────────────────────
const OWNER='Vic3d', REPO='Trade-Bot', BRANCH='master';
async function handleTradelog(req, res) {
  if (!requireAuth(req, res)) return;
  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error:'GITHUB_TOKEN fehlt' });
  try {
    const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/data/trade-log.json?ref=${BRANCH}`,
      { headers:{ 'Authorization':`token ${token}`, 'User-Agent':'TradeMind', 'Accept':'application/vnd.github.v3+json' } });
    if (!r.ok) return res.json({ trades:[] });
    const d = await r.json();
    return res.json({ trades: JSON.parse(Buffer.from(d.content,'base64').toString()) });
  } catch(e) { return res.status(500).json({ error:e.message, trades:[] }); }
}

// ─── Handler: news ────────────────────────────────────────────────────────────
const FINNHUB_KEY = process.env.FINNHUB_KEY || 'cttabspr01qhb1b3gee0cttabspr01qhb1b3geeg';
const COMPANY_NAMES = { 'NVDA':'Nvidia','MSFT':'Microsoft','PLTR':'Palantir','BAYN.DE':'Bayer','RIO.L':'Rio Tinto','EQNR':'Equinor','OXY':'Occidental Petroleum','TTE.PA':'TotalEnergies','ASML.AS':'ASML','AG':'First Majestic Silver','A2QQ9R':'Solar Energie ETF','A3D42Y':'Oil Services ETF','A14WU5':'Cyber Security ETF','A2DWAW':'Biotech ETF' };
const FINNHUB_MAP  = { 'NVDA':'NVDA','MSFT':'MSFT','PLTR':'PLTR','EQNR':'EQNR','OXY':'OXY','AG':'AG','ASML.AS':'ASML' };
async function googleNewsRSS(query, ticker='MACRO') {
  try {
    const url=`https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=de&gl=DE&ceid=DE:de`;
    const r=await fetch(url,{headers:{'User-Agent':'Mozilla/5.0'},signal:AbortSignal.timeout(6000)});
    if (!r.ok) return [];
    const xml=await r.text();
    return [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0,4).map(m=>{
      const b=m[1];
      const title=(b.match(/<title><!\[CDATA\[(.*?)\]\]><\/title>/)?.[1]||b.match(/<title>(.*?)<\/title>/)?.[1]||'').trim();
      const url2=(b.match(/<link>(.*?)<\/link>/)?.[1]||b.match(/<guid[^>]*>(.*?)<\/guid>/)?.[1]||'').trim();
      const pub=b.match(/<pubDate>(.*?)<\/pubDate>/)?.[1]||'';
      const src=(b.match(/<source[^>]*>(.*?)<\/source>/)?.[1]||'Google News').trim();
      return {title,url:url2,source:src,time:pub?new Date(pub).toISOString():null,ticker};
    }).filter(n=>n.title&&n.title.length>5);
  } catch { return []; }
}
async function finnhubNews(symbol,ticker) {
  try {
    const to=new Date().toISOString().split('T')[0];
    const from=new Date(Date.now()-2*86400000).toISOString().split('T')[0];
    const r=await fetch(`https://finnhub.io/api/v1/company-news?symbol=${symbol}&from=${from}&to=${to}&token=${FINNHUB_KEY}`,{signal:AbortSignal.timeout(5000)});
    if (!r.ok) return [];
    return ((await r.json())||[]).slice(0,3).map(n=>({title:n.headline,url:n.url,source:n.source,time:n.datetime?new Date(n.datetime*1000).toISOString():null,ticker}));
  } catch { return []; }
}
async function bloombergRSS(feed) {
  try {
    const r=await fetch(`https://feeds.bloomberg.com/${feed}/news.rss`,{headers:{'User-Agent':'Mozilla/5.0'},signal:AbortSignal.timeout(6000)});
    if (!r.ok) return [];
    const xml=await r.text();
    return [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0,4).map(m=>{
      const b=m[1];
      const title=(b.match(/<title>(.*?)<\/title>/)?.[1]||'').replace(/<!\[CDATA\[(.*?)\]\]>/g,'$1').trim();
      const url2=(b.match(/<link>(.*?)<\/link>/)?.[1]||'').trim();
      const pub=b.match(/<pubDate>(.*?)<\/pubDate>/)?.[1]||'';
      return {title,url:url2,source:'Bloomberg',time:pub?new Date(pub).toISOString():null,ticker:'MACRO'};
    }).filter(n=>n.title&&n.title.length>5);
  } catch { return []; }
}
async function handleNews(req, res) {
  res.setHeader('Cache-Control','no-store,no-cache,must-revalidate');
  res.setHeader('Pragma','no-cache');
  const tickers=(req.query.tickers?req.query.tickers.split(',').slice(0,6):['PLTR','EQNR','BAYN.DE','RIO.L','A3D42Y']);
  try {
    const promises=[];
    for (const t of tickers) { const name=COMPANY_NAMES[t]||t; promises.push(googleNewsRSS(`${name} Aktie`,t)); if(t.endsWith('.DE'))promises.push(googleNewsRSS(`${name} Börse`,t)); }
    for (const t of tickers) { const s=FINNHUB_MAP[t]; if(s)promises.push(finnhubNews(s,t)); }
    promises.push(googleNewsRSS('Ölpreis Iran Konflikt','MACRO'),googleNewsRSS('DAX S&P500 Börse heute','MACRO'),googleNewsRSS('Nvidia KI Chips','NVDA'),bloombergRSS('markets'),bloombergRSS('energy'));
    let all=(await Promise.allSettled(promises)).flatMap(r=>r.status==='fulfilled'?r.value:[]);
    const seen=new Set();
    all=all.filter(n=>{if(!n.url||seen.has(n.url))return false;seen.add(n.url);return true;});
    all.sort((a,b)=>!a.time?1:!b.time?-1:new Date(b.time)-new Date(a.time));
    const cutoff=new Date(Date.now()-48*3600000);
    const fresh=all.filter(n=>!n.time||new Date(n.time)>cutoff);
    res.json({news:fresh.slice(0,30),total:fresh.length,timestamp:new Date().toISOString(),sources:['Google News RSS','Finnhub','Bloomberg RSS']});
  } catch(e) { res.status(500).json({error:e.message,news:[],timestamp:new Date().toISOString()}); }
}

// ─── Handler: prices ─────────────────────────────────────────────────────────
async function yahooFetch(ticker) {
  const r=await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1d&range=2d`,{headers:{'User-Agent':'Mozilla/5.0'}});
  const d=await r.json(); const result=d.chart.result[0]; const meta=result.meta;
  const closes=result.indicators.quote[0].close.filter(Boolean);
  const previousClose=closes.length>=2?closes[closes.length-2]:meta.chartPreviousClose;
  return {price:meta.regularMarketPrice,currency:meta.currency||'USD',previousClose};
}
async function fetchEQNRGettex() {
  const r=await fetch('https://www.onvista.de/aktien/Equinor-ASA-Aktie-NO0010096985',{headers:{'User-Agent':'Mozilla/5.0'}});
  const html=await r.text(); const idx=html.toLowerCase().indexOf('"name":"gettex"');
  if(idx<0)return null; const chunk=html.slice(idx,idx+800);
  const last=chunk.match(/"last":([0-9.]+)/)?.[1]; const prev=chunk.match(/"previousLast":([0-9.]+)/)?.[1];
  if(!last)return null; const eur=parseFloat(last); const prevEur=prev?parseFloat(prev):null;
  return {raw:eur,currency:'EUR',eur,prevEur,dayChange:prevEur?Math.round((eur-prevEur)/prevEur*10000)/100:null};
}
async function handlePrices(req, res) {
  const stocks=['NVDA','MSFT','PLTR','RIO.L','BAYN.DE','OXY','FRO','DHT','HL','PAAS','MOS','TTE.PA','HO.PA','GLEN.L','ASML.AS','NOVO-B.CO'];
  const macros=['EURUSD=X','EURGBP=X','EURDKK=X','EURNOK=X','^VIX','CL=F','BZ=F','^N225','^GSPC','^IXIC','GC=F','HG=F'];
  const results={}; const errors=[];
  await Promise.all([...stocks,...macros].map(async t=>{try{results[t]=await yahooFetch(t);}catch{errors.push(t);}}));
  const eurusd=results['EURUSD=X']?.price||1.09,eurgbp=results['EURGBP=X']?.price||0.86,eurdkk=results['EURDKK=X']?.price||7.46,eurnok=results['EURNOK=X']?.price||11.5;
  const toEur=(p,c)=>{if(!p)return null;if(c==='USD')return p/eurusd;if(c==='NOK')return p/eurnok;if(c==='GBp'||c==='GBX')return(p/100)/eurgbp;if(c==='GBP')return p/eurgbp;if(c==='DKK')return p/eurdkk;return p;};
  const prices={};
  for(const t of stocks){const d=results[t];if(!d)continue;const eur=Math.round(toEur(d.price,d.currency)*100)/100;const prevEur=d.previousClose?Math.round(toEur(d.previousClose,d.currency)*100)/100:null;const dayChange=(eur&&prevEur)?Math.round((eur-prevEur)/prevEur*10000)/100:null;prices[t]={raw:d.price,currency:d.currency,eur,prevEur,dayChange};}
  try{const eqnr=await fetchEQNRGettex();if(eqnr){prices['EQNR']=eqnr;prices['EQNR.OL']=eqnr;}}catch{errors.push('EQNR_GETTEX');}
  const dayChg=d=>(d?.price&&d?.previousClose)?Math.round((d.price-d.previousClose)/d.previousClose*10000)/100:null;
  res.json({prices,macro:{vix:results['^VIX']?.price||null,wti:results['CL=F']?.price||null,wti_chg:dayChg(results['CL=F']),brent:results['BZ=F']?.price||null,brent_chg:dayChg(results['BZ=F']),nikkei:dayChg(results['^N225']),spx:results['^GSPC']?.price||null,spx_chg:dayChg(results['^GSPC']),nasdaq:results['^IXIC']?.price||null,nasdaq_chg:dayChg(results['^IXIC']),gold:results['GC=F']?.price||null,gold_chg:dayChg(results['GC=F']),copper:results['HG=F']?.price||null,copper_chg:dayChg(results['HG=F'])},fx:{EURUSD:eurusd,EURGBP:eurgbp,EURDKK:eurdkk,EURNOK:eurnok},errors,timestamp:new Date().toISOString()});
}

// ─── Main Router ──────────────────────────────────────────────────────────────
module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'OPTIONS') return res.status(200).end();

  const route = req.query._route || '';

  switch (route) {
    case 'daytrades':  return handleDaytrades(req, res);
    case 'dna':        return handleDna(req, res);
    case 'risk':       return handleRisk(req, res);
    case 'signals':    return handleSignals(req, res);
    case 'tradelog':   return handleTradelog(req, res);
    case 'news':       return handleNews(req, res);
    case 'prices':     return handlePrices(req, res);
    default:
      return res.status(400).json({ error: 'Unknown route. Use ?_route=daytrades|dna|risk|signals|tradelog|news|prices' });
  }
};
