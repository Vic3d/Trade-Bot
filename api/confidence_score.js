// API: GET /api/confidence_score — Aktueller Konfidenz-Score
const fs   = require('fs');
const path = require('path');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');

  const p = path.join(process.cwd(), 'data', 'confidence_score.json');
  try {
    if (fs.existsSync(p)) {
      res.status(200).send(fs.readFileSync(p, 'utf8'));
    } else {
      res.status(200).json({ score: 0, label: '⚪ KEIN SIGNAL', action: 'Noch kein Score berechnet', factors: [], updated: null });
    }
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
};
