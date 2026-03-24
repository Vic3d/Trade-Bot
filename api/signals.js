// API: GET /api/signals — Signal Feed + Flow Intelligence Data
// ?type=signals (default) → data/signals.json
// ?type=confidence        → data/confidence_score.json
// ?type=lag               → data/lag_knowledge.json

const fs   = require('fs');
const path = require('path');

const FILES = {
  signals:    'data/signals.json',
  confidence: 'data/confidence_score.json',
  lag:        'data/lag_knowledge.json',
};

const DEFAULTS = {
  signals:    { signals: [], stats: { total: 0, wins: 0, losses: 0, pending: 0, accuracy_pct: null }, updated: null },
  confidence: { score: 0, label: '⚪ KEIN SIGNAL', action: 'Noch kein Score berechnet', factors: [], updated: null },
  lag:        { pairs: {} },
};

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');

  const type = (req.query?.type || req.url?.split('type=')[1]?.split('&')[0] || 'signals');
  const file = FILES[type] || FILES.signals;
  const def  = DEFAULTS[type] || DEFAULTS.signals;

  try {
    const p = path.join(process.cwd(), file);
    if (fs.existsSync(p)) {
      res.status(200).send(fs.readFileSync(p, 'utf8'));
    } else {
      res.status(200).json(def);
    }
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
};
