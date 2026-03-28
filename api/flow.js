// Vercel Serverless: reads memory/flow-scanner-data.json from GitHub Repo
// GET /api/flow → returns latest PIFS scan result

const OWNER  = 'Vic3d';
const REPO   = 'Trade-Bot';
const FILE   = 'memory/flow-scanner-data.json';
const BRANCH = 'master';

async function getFlowData(token) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}?ref=${BRANCH}`;
  const r = await fetch(url, {
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'TradeMind-Dashboard',
    },
  });
  if (!r.ok) {
    if (r.status === 404) return null;  // file not yet created
    throw new Error(`GitHub GET failed: ${r.status}`);
  }
  const data = await r.json();
  return JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN not configured' });

  try {
    const data = await getFlowData(token);
    if (!data) {
      // Return empty placeholder if scan hasn't run yet
      return res.status(200).json({
        timestamp: null,
        overall_direction: 'NEUTRAL',
        overall_emoji: '⚪',
        overall_score: 0,
        total_net_flow: 0,
        sectors: {},
        top_signals: [],
        congressional_tickers: [],
        auto_trades_created: [],
        _empty: true,
      });
    }
    return res.status(200).json(data);
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
