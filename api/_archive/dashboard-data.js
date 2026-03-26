// Vercel Serverless: serves dashboard data.json from GitHub repo
// GET /api/dashboard-data → returns latest data.json

const OWNER = 'Vic3d';
const REPO  = 'Trade-Bot';
const FILE  = 'trademind/dashboard/data.json';
const BRANCH = 'master';

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
  
  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    return res.status(500).json({ error: 'GITHUB_TOKEN not set' });
  }
  
  try {
    const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}?ref=${BRANCH}`;
    const r = await fetch(url, {
      headers: {
        'Authorization': `token ${token}`,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'TradeMind-Dashboard',
      },
    });
    
    if (!r.ok) {
      return res.status(r.status).json({ error: `GitHub: ${r.status}` });
    }
    
    const data = await r.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    
    res.setHeader('Content-Type', 'application/json');
    return res.status(200).json(content);
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
