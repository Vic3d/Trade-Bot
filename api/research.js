// Vercel Serverless: Research-Daten pro Ticker + Queue-Management
// GET  /api/research?ticker=NOVO-B.CO  → gibt Research-JSON zurück
// POST /api/research                    → fügt Ticker zur Queue hinzu

const OWNER  = 'Vic3d';
const REPO   = 'Trade-Bot';
const BRANCH = 'master';

async function ghGet(token, path) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}?ref=${BRANCH}`;
  const r = await fetch(url, {
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'TradeMind-Dashboard',
      'Cache-Control': 'no-cache',
    },
  });
  if (r.status === 404) return { content: null, sha: null };
  if (!r.ok) throw new Error(`GitHub GET ${r.status}`);
  const d = await r.json();
  return {
    content: d.content ? JSON.parse(Buffer.from(d.content, 'base64').toString('utf-8')) : null,
    sha: d.sha,
    raw: d,
  };
}

async function ghPut(token, path, content, sha, message) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}`;
  const body = JSON.stringify({
    message,
    content: Buffer.from(JSON.stringify(content, null, 2)).toString('base64'),
    sha: sha || undefined,
    branch: BRANCH,
  });
  const r = await fetch(url, {
    method: 'PUT',
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'TradeMind-Dashboard',
      'Content-Type': 'application/json',
    },
    body,
  });
  if (!r.ok) throw new Error(`GitHub PUT ${r.status}: ${await r.text()}`);
  return await r.json();
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN fehlt' });

  // GET: Research-Daten für Ticker laden
  if (req.method === 'GET') {
    const ticker = (req.query.ticker || '').toUpperCase();
    if (!ticker) return res.status(400).json({ error: 'ticker required' });

    const safe = ticker.replace(/[^A-Z0-9]/g, '_');
    try {
      const { content } = await ghGet(token, `data/research/${safe}.json`);
      if (!content) return res.status(404).json({ error: 'Kein Research vorhanden', ticker });
      res.json(content);
    } catch (e) {
      res.status(502).json({ error: e.message });
    }
    return;
  }

  // POST: Ticker zur Queue hinzufügen (Deep Dive anfragen)
  if (req.method === 'POST') {
    let body = {};
    try {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      body = JSON.parse(Buffer.concat(chunks).toString());
    } catch {}

    const ticker = (body.ticker || '').toUpperCase();
    if (!ticker) return res.status(400).json({ error: 'ticker required' });

    try {
      // Queue laden oder neu anlegen
      const { content: queue, sha } = await ghGet(token, 'data/research-queue.json');
      const q = queue || [];

      // Prüfen ob bereits in Queue
      const existing = q.find(x => x.ticker === ticker && x.status === 'pending');
      if (existing) {
        return res.json({ queued: false, message: 'Bereits in Queue', ticker });
      }

      q.push({
        ticker,
        queued_at: new Date().toISOString(),
        status: 'pending',
        requested_from: 'dashboard',
      });

      await ghPut(token, 'data/research-queue.json', q, sha,
        `research: ${ticker} zur Queue hinzugefügt`);

      res.json({ queued: true, ticker, message: `${ticker} zur Deep-Dive-Queue hinzugefügt` });
    } catch (e) {
      res.status(502).json({ error: e.message });
    }
    return;
  }

  res.status(405).json({ error: 'Method not allowed' });
};
