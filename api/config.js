// Vercel Serverless: liest trading_config.json aus GitHub Repo
// GET  /api/config  → gibt Positionen + Stops zurück
// POST /api/config  → updated Stop oder Entry einer Position

const OWNER = 'Vic3d';
const REPO  = 'Trade-Bot';
const FILE  = 'trading_config.json';
const BRANCH = 'master';

async function getFile(token) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}?ref=${BRANCH}`;
  const r = await fetch(url, {
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'TradeMind-Dashboard',
    },
  });
  if (!r.ok) throw new Error(`GitHub GET failed: ${r.status}`);
  const data = await r.json();
  const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
  return { content, sha: data.sha };
}

async function updateFile(token, content, sha, message) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`;
  const body = JSON.stringify({
    message,
    content: Buffer.from(JSON.stringify(content, null, 2)).toString('base64'),
    sha,
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
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`GitHub PUT failed: ${r.status} — ${err}`);
  }
  return await r.json();
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN nicht konfiguriert' });

  try {
    // GET — Config lesen
    if (req.method === 'GET') {
      const { content } = await getFile(token);
      const positions = Object.entries(content.positions || {}).map(([ticker, p]) => ({
        ticker,
        name:      p.name,
        entry_eur: p.entry_eur,
        stop_eur:  p.stop_eur || null,
        target_eur: p.target_eur || null,
        status:    p.status || 'OPEN',
        currency:  p.currency || 'EUR',
      }));
      const watchlist = Object.entries(content.watchlist || {}).map(([ticker, p]) => ({
        ticker,
        name: p.name,
        entry_eur: p.entry_eur || null,
        stop_eur:  p.stop_eur || null,
      }));
      return res.json({ positions, watchlist });
    }

    // POST — Stop / Entry updaten
    if (req.method === 'POST') {
      const { ticker, stop_eur, entry_eur, target_eur } = req.body || {};
      if (!ticker) return res.status(400).json({ error: 'ticker erforderlich' });

      const { content, sha } = await getFile(token);

      // Position oder Watchlist
      const section = content.positions?.[ticker] ? 'positions' : 
                      content.watchlist?.[ticker]  ? 'watchlist' : null;

      if (!section) return res.status(404).json({ error: `${ticker} nicht gefunden` });

      const old = { ...content[section][ticker] };

      if (stop_eur  !== undefined) content[section][ticker].stop_eur  = stop_eur  ? parseFloat(stop_eur)  : null;
      if (entry_eur !== undefined) content[section][ticker].entry_eur = parseFloat(entry_eur);
      if (target_eur !== undefined) content[section][ticker].target_eur = target_eur ? parseFloat(target_eur) : null;

      const changes = [];
      if (stop_eur  !== undefined) changes.push(`Stop ${old.stop_eur || '–'}→${stop_eur || '–'}€`);
      if (entry_eur !== undefined) changes.push(`Entry ${old.entry_eur}→${entry_eur}€`);
      if (target_eur !== undefined) changes.push(`Ziel →${target_eur}€`);

      const commitMsg = `Dashboard: ${ticker} — ${changes.join(', ')}`;
      await updateFile(token, content, sha, commitMsg);

      return res.json({ status: 'ok', ticker, changes, commitMsg });
    }

    return res.status(405).json({ error: 'Method not allowed' });

  } catch (e) {
    console.error(e);
    return res.status(500).json({ error: e.message });
  }
};
