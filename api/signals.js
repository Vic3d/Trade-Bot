// API: GET /api/signals — Signal Feed (aus data/signals.json)
// Liest committed signals.json — kein Python nötig

const fs = require('fs');
const path = require('path');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');
  
  const signalsPath = path.join(process.cwd(), 'data', 'signals.json');
  
  try {
    if (fs.existsSync(signalsPath)) {
      const data = fs.readFileSync(signalsPath, 'utf8');
      res.status(200).send(data);
    } else {
      res.status(200).json({
        signals: [],
        stats: { total: 0, wins: 0, losses: 0, pending: 0, accuracy_pct: null },
        updated: null
      });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
