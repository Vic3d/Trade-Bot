// Vercel Serverless: Liest data/scan-latest.json live aus GitHub
// Liefert die Ergebnisse des wöchentlichen Sektor-Scans ans Dashboard

const OWNER  = 'Vic3d';
const REPO   = 'Trade-Bot';
const FILE   = 'data/scan-latest.json';
const BRANCH = 'master';

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const token = process.env.GITHUB_TOKEN;

  try {
    let data;
    if (token) {
      const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}?ref=${BRANCH}`;
      const r = await fetch(url, {
        headers: {
          'Authorization': `token ${token}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'TradeMind-Dashboard',
          'Cache-Control': 'no-cache',
        },
      });
      if (!r.ok) throw new Error(`GitHub ${r.status}`);
      const meta = await r.json();
      data = JSON.parse(Buffer.from(meta.content, 'base64').toString('utf-8'));
    } else {
      const url = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/${FILE}?t=${Date.now()}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`raw.github ${r.status}`);
      data = await r.json();
    }
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: err.message, top: [], etf_rotation: [] });
  }
};
