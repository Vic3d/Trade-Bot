// Vercel Serverless: Liest data/dashdata.json live aus GitHub
// KEIN hardcoded Daten mehr — kein Redeploy nötig bei Datenänderungen!
//
// Update-Flow:
//   positions-live.md geändert
//   → sync_positions.py laufen lassen
//   → generate_dashdata.py laufen lassen
//   → data/dashdata.json gepusht
//   → nächster Dashboard-Request zeigt frische Daten (max. ~60s GitHub-Cache)

const OWNER  = 'Vic3d';
const REPO   = 'Trade-Bot';
const FILE   = 'data/dashdata.json';
const BRANCH = 'master';

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store, no-cache');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const token = process.env.GITHUB_TOKEN;

  try {
    let data;

    if (token) {
      // Private repo: via GitHub API mit Token
      const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}?ref=${BRANCH}`;
      const r = await fetch(url, {
        headers: {
          'Authorization': `token ${token}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'TradeMind-Dashboard',
          'Cache-Control': 'no-cache',
        },
      });
      if (!r.ok) throw new Error(`GitHub API ${r.status}: ${await r.text()}`);
      const meta = await r.json();
      data = JSON.parse(Buffer.from(meta.content, 'base64').toString('utf-8'));
    } else {
      // Fallback: Public raw URL (funktioniert wenn Repo public ist)
      const url = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/${FILE}?t=${Date.now()}`;
      const r = await fetch(url, { headers: { 'Cache-Control': 'no-cache' } });
      if (!r.ok) throw new Error(`GitHub raw ${r.status} — GITHUB_TOKEN in Vercel env setzen!`);
      data = await r.json();
    }

    // Timestamp der letzten Daten mitsenden
    data._fetched = new Date().toISOString();
    res.end(JSON.stringify(data));

  } catch (err) {
    console.error('[dashdata]', err.message);
    res.status(502).json({
      error: 'Dashboard-Daten konnten nicht geladen werden',
      detail: err.message,
      hint: 'GITHUB_TOKEN in Vercel Environment Variables setzen (Settings → Environment Variables)',
    });
  }
};
