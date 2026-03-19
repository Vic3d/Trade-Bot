// Vercel Serverless: fetch live prices from Yahoo Finance
// EQNR: Gettex-Kurs via Onvista (Victor handelt auf TR/Gettex, nicht Oslo)

async function fetchEQNRGettex() {
  // Onvista liefert Gettex EUR-Kurs direkt
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

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  
  const tickers = [
    'NVDA','MSFT','PLTR','RIO.L','BAYN.DE',
    'OXY','FRO','DHT','HL','PAAS','MOS','TTE.PA',
    'HO.PA','GLEN.L','ASML.AS','NOVO-B.CO',
    'EURUSD=X','EURGBP=X','EURDKK=X','EURNOK=X',
    '^VIX'
  ];

  const results = {};
  const errors = [];

  for (const t of tickers) {
    try {
      const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(t)}?interval=1d&range=1d`;
      const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
      const data = await r.json();
      const meta = data.chart.result[0].meta;
      results[t] = {
        price: meta.regularMarketPrice,
        currency: meta.currency || 'USD',
        previousClose: meta.chartPreviousClose || meta.previousClose,
      };
    } catch (e) {
      errors.push(t);
    }
  }

  // Convert all to EUR
  const eurusd = results['EURUSD=X']?.price || 1.09;
  const eurgbp = results['EURGBP=X']?.price || 0.86;
  const eurdkk = results['EURDKK=X']?.price || 7.46;
  const eurnok = results['EURNOK=X']?.price || 11.5;

  const toEur = (price, ccy) => {
    if (ccy === 'USD') return price / eurusd;
    if (ccy === 'NOK') return price / eurnok;
    if (ccy === 'GBp' || ccy === 'GBX') return (price / 100) / eurgbp;
    if (ccy === 'GBP') return price / eurgbp;
    if (ccy === 'DKK') return price / eurdkk;
    return price; // EUR
  };

  const prices = {};
  for (const [t, d] of Object.entries(results)) {
    if (t.includes('=X') || t.startsWith('^')) continue;
    const eur = Math.round(toEur(d.price, d.currency) * 100) / 100;
    const prevEur = d.previousClose ? Math.round(toEur(d.previousClose, d.currency) * 100) / 100 : null;
    const dayChange = prevEur ? Math.round((eur - prevEur) / prevEur * 10000) / 100 : null;
    prices[t] = { raw: d.price, currency: d.currency, eur, prevEur, dayChange };
  }

  // EQNR: Gettex-Kurs (TR-Kurs) via Onvista — überschreibt Yahoo Oslo
  try {
    const eqnrGettex = await fetchEQNRGettex();
    if (eqnrGettex) {
      prices['EQNR'] = eqnrGettex;
      prices['EQNR.OL'] = eqnrGettex; // Alias damit config-Lookup funktioniert
    }
  } catch(e) { errors.push('EQNR_GETTEX'); }

  res.json({
    prices,
    vix: results['^VIX']?.price || null,
    fx: { eurusd, eurgbp, eurdkk, eurnok },
    errors,
    timestamp: new Date().toISOString(),
  });
}
