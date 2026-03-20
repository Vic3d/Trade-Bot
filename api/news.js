// Vercel Serverless: News-Feed für Portfolio-Ticker
// Quellen: Finnhub (Company News) + Google News RSS (Makro)

const FINNHUB_KEY = process.env.FINNHUB_KEY || 'cttabspr01qhb1b3gee0cttabspr01qhb1b3geeg';

// Mapping Config-Ticker → Finnhub-Symbol
const TICKER_MAP = {
  'NVDA':'NVDA','MSFT':'MSFT','PLTR':'PLTR','BAYN.DE':'BAYN',
  'RIO.L':'RIO','EQNR':'EQNR','OXY':'OXY','TTE.PA':'TTE',
  'FRO':'FRO','DHT':'DHT','HL':'HL','PAAS':'PAAS',
  'MOS':'MOS','HO.PA':'HO','ASML.AS':'ASML','NOVO-B.CO':'NVO',
};

async function finnhubNews(symbol) {
  const to = new Date().toISOString().split('T')[0];
  const from = new Date(Date.now() - 3*24*60*60*1000).toISOString().split('T')[0];
  const url = `https://finnhub.io/api/v1/company-news?symbol=${symbol}&from=${from}&to=${to}&token=${FINNHUB_KEY}`;
  const r = await fetch(url, { headers: { 'User-Agent': 'TradeMind' } });
  if (!r.ok) return [];
  const items = await r.json();
  return (items || []).slice(0, 3).map(n => ({
    title: n.headline,
    url: n.url,
    source: n.source,
    time: n.datetime ? new Date(n.datetime * 1000).toISOString() : null,
    ticker: symbol,
  }));
}

async function googleNewsRSS(query) {
  const enc = encodeURIComponent(query);
  const url = `https://news.google.com/rss/search?q=${enc}&hl=de&gl=DE&ceid=DE:de`;
  const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!r.ok) return [];
  const xml = await r.text();
  const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, 5);
  return items.map(m => {
    const block = m[1];
    const title = block.match(/<title><!\[CDATA\[(.*?)\]\]><\/title>/)?.[1] ||
                  block.match(/<title>(.*?)<\/title>/)?.[1] || '';
    const link  = block.match(/<link>(.*?)<\/link>/)?.[1] || '';
    const pub   = block.match(/<pubDate>(.*?)<\/pubDate>/)?.[1] || '';
    const src   = block.match(/<source[^>]*>(.*?)<\/source>/)?.[1] || 'Google News';
    return {
      title: title.trim(),
      url: link.trim(),
      source: src.trim(),
      time: pub ? new Date(pub).toISOString() : null,
      ticker: 'MACRO',
    };
  }).filter(n => n.title);
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'max-age=60, s-maxage=60'); // max 1 Min Cache

  const tickers = req.query.tickers
    ? req.query.tickers.split(',').slice(0, 5)
    : ['NVDA', 'EQNR', 'RIO'];

  try {
    const newsPromises = tickers
      .map(t => TICKER_MAP[t])
      .filter(Boolean)
      .map(sym => finnhubNews(sym));

    // Makro-News immer dabei
    newsPromises.push(googleNewsRSS('Ölpreis Aktien Börse'));
    newsPromises.push(googleNewsRSS('VIX Volatilität Markt'));

    const results = await Promise.allSettled(newsPromises);
    let allNews = results.flatMap(r => r.status === 'fulfilled' ? r.value : []);

    // Nach Zeit sortieren (neueste zuerst)
    allNews.sort((a, b) => {
      if (!a.time) return 1;
      if (!b.time) return -1;
      return new Date(b.time) - new Date(a.time);
    });

    // Deduplizieren nach URL
    const seen = new Set();
    allNews = allNews.filter(n => {
      if (!n.url || seen.has(n.url)) return false;
      seen.add(n.url); return true;
    });

    res.json({ news: allNews.slice(0, 20), timestamp: new Date().toISOString() });
  } catch(e) {
    res.status(500).json({ error: e.message, news: [] });
  }
};
