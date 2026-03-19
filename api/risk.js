// API: GET /api/risk — Portfolio Risk Dashboard
// Sprint 5 | TradeMind Bauplan

const { execSync } = require('child_process');

module.exports = (req, res) => {
  try {
    const result = execSync(`python3 -c "
import sys, json
sys.path.insert(0, '/data/.openclaw/workspace/scripts/execution')
from risk_manager import full_risk_report
report = full_risk_report()
print(json.dumps(report, default=str))
"`, { timeout: 10000 }).toString().trim();
    
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).send(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
