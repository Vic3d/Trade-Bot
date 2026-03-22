// GET /api/trade-log — liest data/trade-log.json aus GitHub
const OWNER = 'Vic3d', REPO = 'Trade-Bot', BRANCH = 'master';

const { requireAuth } = require('../lib/auth');
module.exports = async function handler(req, res) {
  if (!requireAuth(req, res)) return;
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store');
  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN fehlt' });
  try {
    const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/data/trade-log.json?ref=${BRANCH}`, {
      headers: { 'Authorization': `token ${token}`, 'User-Agent': 'TradeMind', 'Accept': 'application/vnd.github.v3+json' }
    });
    if (!r.ok) return res.json({ trades: [] });
    const d = await r.json();
    const trades = JSON.parse(Buffer.from(d.content, 'base64').toString());
    return res.json({ trades });
  } catch(e) {
    return res.status(500).json({ error: e.message, trades: [] });
  }
};
