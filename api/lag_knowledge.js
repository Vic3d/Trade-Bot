// API: GET /api/lag_knowledge — Lead-Lag Wissensdatenbank
const fs   = require('fs');
const path = require('path');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');

  const p = path.join(process.cwd(), 'data', 'lag_knowledge.json');
  try {
    if (fs.existsSync(p)) {
      res.status(200).send(fs.readFileSync(p, 'utf8'));
    } else {
      res.status(200).json({ pairs: {} });
    }
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
};
