// API: GET /api/risk — Risk Score + Sektor-Exposure + Korrelation
// Liest data/risk.json + data/correlations.json + trading_config.json
const fs = require('fs');
const path = require('path');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');
  
  const riskPath = path.join(process.cwd(), 'data', 'risk.json');
  const corrPath = path.join(process.cwd(), 'data', 'correlations.json');
  const alertsPath = path.join(process.cwd(), 'data', 'alerts.json');
  
  let risk = { overall_score: 0, sector_exposure: {}, correlation_warnings: [] };
  let correlations = {};
  let alerts = [];
  
  try { if (fs.existsSync(riskPath)) risk = JSON.parse(fs.readFileSync(riskPath, 'utf8')); } catch(e) {}
  try { if (fs.existsSync(corrPath)) correlations = JSON.parse(fs.readFileSync(corrPath, 'utf8')); } catch(e) {}
  try { if (fs.existsSync(alertsPath)) alerts = JSON.parse(fs.readFileSync(alertsPath, 'utf8')); } catch(e) {}
  
  res.status(200).json({
    risk,
    correlations,
    alerts: alerts.slice(-50), // letzte 50 Alerts
    updated: risk.updated || null
  });
};
