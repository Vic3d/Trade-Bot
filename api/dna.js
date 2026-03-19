// API: GET /api/dna — Strategy DNA Feed (aus data/dna.json)
const fs = require('fs');
const path = require('path');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');
  
  const dnaPath = path.join(process.cwd(), 'data', 'dna.json');
  
  try {
    if (fs.existsSync(dnaPath)) {
      res.status(200).send(fs.readFileSync(dnaPath, 'utf8'));
    } else {
      res.status(200).json({ stats: {}, strategies: [], trader_profile: {}, updated: null });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
