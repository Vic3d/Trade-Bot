// API: GET /api/daytrades — Day Trade Feed
const fs = require('fs');
const path = require('path');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');
  
  // Read dna.json and filter day_trade entries
  const dnaPath = path.join(process.cwd(), 'data', 'dna.json');
  const statePath = path.join(process.cwd(), 'memory', 'daytrader-state.json');
  
  let dna = { open_positions: [], strategies: [] };
  let state = { daily_pnl: 0, daily_trades: 0, last_date: null };
  
  try { if (fs.existsSync(dnaPath)) dna = JSON.parse(fs.readFileSync(dnaPath, 'utf8')); } catch(e) {}
  try { if (fs.existsSync(statePath)) state = JSON.parse(fs.readFileSync(statePath, 'utf8')); } catch(e) {}
  
  // Filter day trades from positions
  const openDT = (dna.open_positions || []).filter(p => p.trade_type === 'day_trade');
  const dtStrategies = (dna.strategies || []).filter(s => s.strategy && s.strategy.startsWith('DT'));
  
  res.status(200).json({
    open: openDT,
    strategies: dtStrategies,
    state: state,
    capital: 25000,
    pos_size: 5000,
    max_positions: 5,
    updated: dna.updated || null
  });
};
