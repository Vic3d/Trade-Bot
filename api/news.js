// Vercel Serverless: News-Feed für Portfolio-Ticker
// Quellen: Google News RSS (Hauptquelle, near-realtime) + Finnhub (US-Backup) + Bloomberg RSS
// KEIN CDN-Cache — immer frisch

const FINNHUB_KEY = process.env.FINNHUB_KEY || 'cttabspr01qhb1b3gee0cttabspr01qhb1b3geeg';

// Firmenname für Google News RSS (besser als Ticker-Symbol)
const COMPANY_NAMES = {
  'NVDA':    'Nvidia',
  'MSFT':    'Microsoft',
  'PLTR':    'Palantir',
  'BAYN.DE': 'Bayer',
  'RIO.L':   'Rio Tinto',
  'EQNR':    'Equinor',
  'OXY':     'Occidental Petroleum',
  'TTE.PA':  'TotalEnergies',
  'ASML.AS': 'ASML',
  'AG':      'First Majestic Silver',
  'A2QQ9R':  'Solar Energie ETF',
  'A3D42Y':  'Oil Services ETF',
  'A14WU5':  'Cyber Security ETF',
  'A2DWAW':  'Biotech ETF',
};

// Finnhub für US-Ticker (schneller als Google für NVDA/PLTR/MSFT)
const FINNHUB_MAP = {
  'NVDA':'NVDA','MSFT':'MSFT','PLTR':'PLTR','EQNR':'EQNR',
  'OXY':'OXY','AG':'AG','ASML.AS':'ASML',
};

async function googleNewsRSS(query, ticker = 'MACRO') {
  try {
    const enc = encodeURIComponent(query);
    const url = `https://news.google.com/rss/search?q=${enc}&hl=de&gl=DE&ceid=DE:de`;
    const r = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; TradeMind/2.0)' },
      signal: AbortSignal.timeout(6000),
    });
    if (!r.ok) return [];
    const xml = await r.text();
    const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, 4);
    return items.map(m => {
      const block = m[1];
      const title = block.match(/<title><!\[CDATA\[(.*?)\]\]><\/title>/)?.[1] ||
                    block.match(/<title>(.*?)<\/title>/)?.[1] || '';
      const link  = block.match(/<link>(.*?)<\/link>/)?.[1] ||
                    block.match(/<guid[^>]*>(.*?)<\/guid>/)?.[1] || '';
      const pub   = block.match(/<pubDate>(.*?)<\/pubDate>/)?.[1] || '';
      const src   = block.match(/<source[^>]*>(.*?)<\/source>/)?.[1] || 'Google News';
      return {
        title: title.trim(),
        url: link.trim(),
        source: src.trim(),
        time: pub ? new Date(pub).toISOString() : null,
        ticker,
      };
    }).filter(n => n.title && n.title.length > 5);
  } catch { return []; }
}

async function finnhubNews(symbol, ticker) {
  try {
    const to = new Date().toISOString().split('T')[0];
    const from = new Date(Date.now() - 2*24*60*60*1000).toISOString().split('T')[0];
    const url = `https://finnhub.io/api/v1/company-news?symbol=${symbol}&from=${from}&to=${to}&token=${FINNHUB_KEY}`;
    const r = await fetch(url, {
      headers: { 'User-Agent': 'TradeMind' },
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) return [];
    const items = await r.json();
    return (items || []).slice(0, 3).map(n => ({
      title: n.headline,
      url: n.url,
      source: n.source,
      time: n.datetime ? new Date(n.datetime * 1000).toISOString() : null,
      ticker,
    }));
  } catch { return []; }
}

async function bloombergRSS(feed) {
  // feed: 'markets' | 'energy' | 'technology'
  try {
    const url = `https://feeds.bloomberg.com/${feed}/news.rss`;
    const r = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0' },
      signal: AbortSignal.timeout(6000),
    });
    if (!r.ok) return [];
    const xml = await r.text();
    const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, 4);
    return items.map(m => {
      const block = m[1];
      const title = block.match(/<title>(.*?)<\/title>/)?.[1] || '';
      const link  = block.match(/<link>(.*?)<\/link>/)?.[1] ||
                    block.match(/<guid[^>]*>(.*?)<\/guid>/)?.[1] || '';
      const pub   = block.match(/<pubDate>(.*?)<\/pubDate>/)?.[1] || '';
      return {
        title: title.replace(/<!\[CDATA\[(.*?)\]\]>/g, '$1').trim(),
        url: link.trim(),
        source: 'Bloomberg',
        time: pub ? new Date(pub).toISOString() : null,
        ticker: 'MACRO',
      };
    }).filter(n => n.title && n.title.length > 5);
  } catch { return []; }
}

module.exports = async function handler(req, res) {
  // KEIN Cache — Trading braucht frische Daten
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');

  const requestedTickers = req.query.tickers
    ? req.query.tickers.split(',').slice(0, 6)
    : ['PLTR', 'EQNR', 'BAYN.DE', 'RIO.L', 'A3D42Y'];

  try {
    const promises = [];

    // Google News RSS für alle Portfolio-Ticker (primäre Quelle — near-realtime)
    for (const ticker of requestedTickers) {
      const name = COMPANY_NAMES[ticker] || ticker;
      promises.push(googleNewsRSS(`${name} Aktie`, ticker));
      // Für DE-Ticker auch auf Deutsch
      if (ticker.endsWith('.DE')) {
        promises.push(googleNewsRSS(`${name} Börse`, ticker));
      }
    }

    // Finnhub für US-Ticker zusätzlich
    for (const ticker of requestedTickers) {
      const fhSym = FINNHUB_MAP[ticker];
      if (fhSym) promises.push(finnhubNews(fhSym, ticker));
    }

    // Makro-News
    promises.push(googleNewsRSS('Ölpreis Iran Konflikt', 'MACRO'));
    promises.push(googleNewsRSS('DAX S&P500 Börse heute', 'MACRO'));
    promises.push(googleNewsRSS('Nvidia KI Chips', 'NVDA'));
    promises.push(bloombergRSS('markets'));
    promises.push(bloombergRSS('energy'));

    const results = await Promise.allSettled(promises);
    let allNews = results.flatMap(r => r.status === 'fulfilled' ? r.value : []);

    // Deduplizieren nach URL
    const seen = new Set();
    allNews = allNews.filter(n => {
      if (!n.url || seen.has(n.url)) return false;
      seen.add(n.url);
      return true;
    });

    // Nach Zeit sortieren — neueste zuerst
    allNews.sort((a, b) => {
      if (!a.time) return 1;
      if (!b.time) return -1;
      return new Date(b.time) - new Date(a.time);
    });

    // Nur Artikel der letzten 48h (kein veraltetes Zeug)
    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000);
    const fresh = allNews.filter(n => !n.time || new Date(n.time) > cutoff);

    res.json({
      news: fresh.slice(0, 30),
      total: fresh.length,
      timestamp: new Date().toISOString(),
      sources: ['Google News RSS', 'Finnhub', 'Bloomberg RSS'],
    });
  } catch(e) {
    res.status(500).json({ error: e.message, news: [], timestamp: new Date().toISOString() });
  }
};
