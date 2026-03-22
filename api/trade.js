// Vercel Serverless: Trade eintragen
// POST /api/trade → schreibt in trade-log.json im GitHub Repo

const OWNER = 'Vic3d', REPO = 'Trade-Bot', BRANCH = 'master';
const TRADE_LOG = 'data/trade-log.json';

async function ghGet(token, path) {
  const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}?ref=${BRANCH}`, {
    headers: { 'Authorization': `token ${token}`, 'User-Agent': 'TradeMind', 'Accept': 'application/vnd.github.v3+json' }
  });
  if (r.status === 404) return { content: [], sha: null };
  const d = await r.json();
  return { content: JSON.parse(Buffer.from(d.content, 'base64').toString()), sha: d.sha };
}

async function ghPut(token, path, content, sha, message) {
  const body = { message, content: Buffer.from(JSON.stringify(content, null, 2)).toString('base64'), branch: BRANCH };
  if (sha) body.sha = sha;
  const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}`, {
    method: 'PUT',
    headers: { 'Authorization': `token ${token}`, 'User-Agent': 'TradeMind', 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`GitHub PUT ${path}: ${r.status}`);
}

const { requireAuth } = require('../lib/auth');
module.exports = async function handler(req, res) {
  if (req.method !== 'OPTIONS' && !requireAuth(req, res)) return;
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN nicht konfiguriert' });

  const { ticker, action, price_eur, stop_eur, target_eur, strategy, notes } = req.body || {};
  if (!ticker || !price_eur) return res.status(400).json({ error: 'ticker + price_eur erforderlich' });

  const entry = {
    ts: new Date().toISOString(),
    ticker: ticker.toUpperCase(),
    action: action || 'BUY',
    price_eur: parseFloat(price_eur),
    stop_eur: stop_eur ? parseFloat(stop_eur) : null,
    target_eur: target_eur ? parseFloat(target_eur) : null,
    strategy: strategy || '',
    notes: notes || '',
  };

  try {
    const { content: log, sha } = await ghGet(token, TRADE_LOG);
    log.push(entry);
    await ghPut(token, TRADE_LOG, log, sha, `Trade: ${entry.action} ${entry.ticker} @ ${entry.price_eur}€`);
    return res.json({ status: 'ok', entry });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
