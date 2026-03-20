// Vercel Serverless: Live-Preise + Macro (VIX, WTI, Nikkei, FX)
// EQNR: Gettex-Kurs via Onvista (Victor handelt auf TR/Gettex)

async function fetchEQNRGettex() {
  const r = await fetch('https://www.onvista.de/aktien/Equinor-ASA-Aktie-NO0010096985', {
    headers: { 'User-Agent': 'Mozilla/5.0' }
  });
  const html = await r.text();
  const idx = html.toLowerCase().indexOf('"name":"gettex"');
  if (idx < 0) return null;
  const chunk = html.slice(idx, idx + 800);
  const last = chunk.match(/"last":([0-9.]+)/)?.[1];
  const prev = chunk.match(/"previousLast":([0-9.]+)/)?.[1];
  if (!last) return null;
  const eur = parseFloat(last);
  const prevEur = prev ? parseFloat(prev) : null;
  const dayChange = prevEur ? Math.round((eur - prevEur) / prevEur * 10000) / 100 : null;
  return { raw: eur, currency: 'EUR', eur, prevEur, dayChange };
}

async function yahooFetch(ticker) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1d&range=2d`;
  const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  const data = await r.json();
  const result = data.chart.result[0];
  const meta = result.meta;
  // Use previous candle close as previousClose (most reliable)
  const closes = result.indicators.quote[0].close.filter(Boolean);
  const previousClose = closes.length >= 2 ? closes[closes.length - 2] : meta.chartPreviousClose;
  return {
    price: meta.regularMarketPrice,
    currency: meta.currency || 'USD',
    previousClose,
  };
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store');

  const stockTickers = [
    'NVDA','MSFT','PLTR','RIO.L','BAYN.DE',
    'OXY','FRO','DHT','HL','PAAS','MOS','TTE.PA',
    'HO.PA','GLEN.L','ASML.AS','NOVO-B.CO',
  ];
  const macroTickers = ['EURUSD=X','EURGBP=X','EURDKK=X','EURNOK=X','^VIX','CL=F','BZ=F','^N225','^GSPC','^IXIC','GC=F','HG=F'];

  const results = {};
  const errors = [];

  // Parallel fetch für Performance
  const allTickers = [...stockTickers, ...macroTickers];
  await Promise.all(allTickers.map(async t => {
    try {
      results[t] = await yahooFetch(t);
    } catch(e) {
      errors.push(t);
    }
  }));

  // FX Rates
  const eurusd = results['EURUSD=X']?.price || 1.09;
  const eurgbp = results['EURGBP=X']?.price || 0.86;
  const eurdkk = results['EURDKK=X']?.price || 7.46;
  const eurnok = results['EURNOK=X']?.price || 11.5;

  const toEur = (price, ccy) => {
    if (!price) return null;
    if (ccy === 'USD') return price / eurusd;
    if (ccy === 'NOK') return price / eurnok;
    if (ccy === 'GBp' || ccy === 'GBX') return (price / 100) / eurgbp;
    if (ccy === 'GBP') return price / eurgbp;
    if (ccy === 'DKK') return price / eurdkk;
    return price;
  };

  // Stock prices → EUR
  const prices = {};
  for (const t of stockTickers) {
    const d = results[t];
    if (!d) continue;
    const eur = Math.round(toEur(d.price, d.currency) * 100) / 100;
    const prevEur = d.previousClose ? Math.round(toEur(d.previousClose, d.currency) * 100) / 100 : null;
    const dayChange = (eur && prevEur) ? Math.round((eur - prevEur) / prevEur * 10000) / 100 : null;
    prices[t] = { raw: d.price, currency: d.currency, eur, prevEur, dayChange };
  }

  // EQNR Gettex (überschreibt Yahoo)
  try {
    const eqnr = await fetchEQNRGettex();
    if (eqnr) { prices['EQNR'] = eqnr; prices['EQNR.OL'] = eqnr; }
  } catch(e) { errors.push('EQNR_GETTEX'); }

  // Nikkei Tagesveränderung
  const nikkeiData = results['^N225'];
  let nikkeiChg = null;
  if (nikkeiData?.price && nikkeiData?.previousClose) {
    nikkeiChg = Math.round((nikkeiData.price - nikkeiData.previousClose) / nikkeiData.previousClose * 10000) / 100;
  }

  // WTI in USD
  const wtiUSD = results['CL=F']?.price || null;

  // Nikkei chg already calculated above
  const spxD  = results['^GSPC'];
  const ndxD  = results['^IXIC'];
  const goldD = results['GC=F'];
  const copD  = results['HG=F'];
  const brentD= results['BZ=F'];

  const dayChgPct = (d) => (d?.price && d?.previousClose)
    ? Math.round((d.price - d.previousClose) / d.previousClose * 10000) / 100
    : null;

  res.json({
    prices,
    macro: {
      vix:        results['^VIX']?.price    || null,
      wti:        wtiUSD,
      wti_chg:    dayChgPct(results['CL=F']),
      brent:      brentD?.price || null,
      brent_chg:  dayChgPct(brentD),
      nikkei:     nikkeiChg,
      spx:        spxD?.price || null,
      spx_chg:    dayChgPct(spxD),
      nasdaq:     ndxD?.price || null,
      nasdaq_chg: dayChgPct(ndxD),
      gold:       goldD?.price || null,
      gold_chg:   dayChgPct(goldD),
      copper:     copD?.price || null,
      copper_chg: dayChgPct(copD),
    },
    fx: {
      EURUSD: eurusd,
      EURGBP: eurgbp,
      EURDKK: eurdkk,
      EURNOK: eurnok,
    },
    errors,
    timestamp: new Date().toISOString(),
  });
};
