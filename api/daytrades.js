// API: GET /api/daytrades — Day Trade Feed
const fs = require('fs');
const path = require('path');

function generateDayTradeSetups(dna, state, today) {
  const setups = [];

  // Setup 1: Öl-Momentum (basierend auf Strategie S1 Iran/Öl)
  setups.push({
    id: `DT-AUTO-${today}-1`,
    ticker: 'EQNR',
    trade_type: 'day_trade',
    direction: 'LONG',
    entry: null,
    setup_type: 'Momentum-Pullback',
    trigger: 'EMA20-Touch + Volumen > 1.5x Schnitt',
    stop_pct: 1.5,
    target_pct: 3.0,
    crv: 2.0,
    confidence: 65,
    thesis: 'Öl-Sektor-Momentum (Iran/Brent-Spread). EQNR pullback auf EMA20 = potenzieller Intraday-Long.',
    status: 'WATCHING',
    generated: new Date().toISOString(),
  });

  // Setup 2: Defensive Tech
  setups.push({
    id: `DT-AUTO-${today}-2`,
    ticker: 'PLTR',
    trade_type: 'day_trade',
    direction: 'LONG',
    entry: null,
    setup_type: 'Breakout-Retest',
    trigger: 'Break über Tageshoch + Retest + Hold',
    stop_pct: 1.8,
    target_pct: 3.5,
    crv: 1.9,
    confidence: 60,
    thesis: 'PLTR bullisch (VIX < 25, AI-Rotation aktiv). Breakout-Retest-Setup auf Intraday.',
    status: 'WATCHING',
    generated: new Date().toISOString(),
  });

  return setups;
}

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

  // Auto-generiere Day Trade Setups wenn keine vorhanden
  if (openDT.length === 0) {
    const today = new Date().toISOString().split('T')[0];
    const autoSetups = generateDayTradeSetups(dna, state, today);
    return res.status(200).json({
      open: autoSetups,
      strategies: dtStrategies,
      state: state,
      capital: 25000,
      pos_size: 5000,
      max_positions: 5,
      updated: dna.updated || null,
      auto_generated: true,
    });
  }

  res.status(200).json({
    open: openDT,
    strategies: dtStrategies,
    state: state,
    capital: 25000,
    pos_size: 5000,
    max_positions: 5,
    updated: dna.updated || null,
  });
};
