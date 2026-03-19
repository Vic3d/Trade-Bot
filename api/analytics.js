// API: GET /api/analytics — Strategy DNA + Trade Stats
// Sprint 5 | TradeMind Bauplan

const { execSync } = require('child_process');

module.exports = (req, res) => {
  try {
    const result = execSync(`python3 -c "
import sys, json
sys.path.insert(0, '/data/.openclaw/workspace/scripts/intelligence')
sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
from strategy_dna import full_dna_report
from trade_journal import trade_stats
from calibration import run_calibration

report = full_dna_report()
stats = trade_stats()
calib = run_calibration()

output = {
  'dna': report,
  'stats': stats,
  'calibration': calib,
}
print(json.dumps(output, default=str))
"`, { timeout: 15000 }).toString().trim();
    
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).send(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
