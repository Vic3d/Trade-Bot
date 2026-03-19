// API: POST /api/approve — Trade Proposal genehmigen/ablehnen
// Sprint 5 | TradeMind Bauplan

const { execSync } = require('child_process');
const fs = require('fs');

module.exports = (req, res) => {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'POST only' });
  }
  
  try {
    const { proposalId, action, reason } = req.body || {};
    
    if (!proposalId || !action) {
      return res.status(400).json({ error: 'proposalId and action required' });
    }
    
    if (!['approve', 'reject'].includes(action)) {
      return res.status(400).json({ error: 'action must be approve or reject' });
    }
    
    const result = execSync(`python3 -c "
import sys, json
sys.path.insert(0, '/data/.openclaw/workspace/scripts/execution')
sys.path.insert(0, '/data/.openclaw/workspace/scripts/core')
from trade_proposal import approve_proposal, reject_proposal

proposal_id = '${proposalId}'
action = '${action}'
reason = '${(reason || '').replace(/'/g, "\\'")}'

if action == 'approve':
    trade_id = approve_proposal(proposal_id)
    print(json.dumps({'status': 'approved', 'trade_id': trade_id}))
else:
    result = reject_proposal(proposal_id, reason)
    print(json.dumps({'status': 'rejected', 'success': result}))
"`, { timeout: 10000 }).toString().trim();
    
    res.setHeader('Content-Type', 'application/json');
    res.status(200).send(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
