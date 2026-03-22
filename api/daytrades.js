// API: GET /api/daytrades — Day Trade Feed
// Liest echte DT1–DT9 Strategien aus data/strategies.json + offene Trades aus data/dna.json
const fs = require('fs');
const path = require('path');

const STRATEGY_META = {
  DT1: { setup_type: 'Momentum-Breakout',         trigger: 'Break über Widerstand + Volumen > 1.5x', stop_pct: 1.5, target_pct: 3.0, crv: 2.0 },
  DT2: { setup_type: 'Mean-Reversion Oversold',    trigger: 'RSI < 30 + Tageskerze Hammer',           stop_pct: 1.2, target_pct: 2.5, crv: 2.1 },
  DT3: { setup_type: 'Gap-Fill',                   trigger: 'Gap-Up/Down > 1% vorbörslich + Retest',  stop_pct: 1.0, target_pct: 2.0, crv: 2.0 },
  DT4: { setup_type: 'News-Catalyst',              trigger: 'CRITICAL/IMPORTANT News-Alert + Kurs bewegt sich', stop_pct: 2.0, target_pct: 4.0, crv: 2.0 },
  DT5: { setup_type: 'VWAP-Bounce',               trigger: 'Kurs unter VWAP + Bounce mit Volumen',   stop_pct: 1.2, target_pct: 2.4, crv: 2.0 },
  DT6: { setup_type: 'Triple RSI Mean Reversion',  trigger: 'RSI(2)<10 + RSI(5)<25 + RSI(14)<40',    stop_pct: 1.5, target_pct: 3.0, crv: 2.0 },
  DT7: { setup_type: 'Internal Bar Strength (IBS)', trigger: 'IBS < 0.2 (Close nahe Low)',            stop_pct: 1.0, target_pct: 2.5, crv: 2.5 },
  DT8: { setup_type: 'BB Squeeze Breakout',        trigger: 'Bollinger Bands < 1% Breite + Break',    stop_pct: 1.5, target_pct: 4.5, crv: 3.0 },
  DT9: { setup_type: 'Sektor-Momentum',            trigger: 'Stärkster Sektor heute + Top-Aktie',     stop_pct: 1.5, target_pct: 3.0, crv: 2.0 },
};

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Access-Control-Allow-Origin', '*');

  const dnaPath      = path.join(process.cwd(), 'data', 'dna.json');
  const stratPath    = path.join(process.cwd(), 'data', 'strategies.json');
  const statePath    = path.join(process.cwd(), 'memory', 'daytrader-state.json');

  let dna      = { open_positions: [], strategies: [] };
  let allStrats = {};
  let state    = { daily_pnl: 0, daily_trades: 0, last_date: null };

  try { if (fs.existsSync(dnaPath))   dna       = JSON.parse(fs.readFileSync(dnaPath,   'utf8')); } catch(e) {}
  try { if (fs.existsSync(stratPath)) allStrats = JSON.parse(fs.readFileSync(stratPath, 'utf8')); } catch(e) {}
  try { if (fs.existsSync(statePath)) state     = JSON.parse(fs.readFileSync(statePath, 'utf8')); } catch(e) {}

  // Offene Day Trades aus DNA
  const openDT = (dna.open_positions || []).filter(p => p.trade_type === 'day_trade');

  // DT1–DT9 aus strategies.json aufbauen
  const dtStrategies = Object.entries(allStrats)
    .filter(([id]) => id.startsWith('DT'))
    .map(([id, s]) => {
      const meta = STRATEGY_META[id] || {};
      return {
        id,
        name:         s.name || id,
        thesis:       s.thesis || '',
        setup_type:   meta.setup_type  || '',
        trigger:      meta.trigger     || '',
        stop_pct:     meta.stop_pct    || 1.5,
        target_pct:   meta.target_pct  || 3.0,
        crv:          meta.crv         || 2.0,
        conviction:   s.genesis?.conviction_current || 3,
        status:       s.status || 'active',
        win_rate:     s.performance?.win_rate || 0,
        total_trades: s.performance?.total_trades || 0,
        wins:         s.performance?.wins || 0,
        losses:       s.performance?.losses || 0,
      };
    })
    .sort((a, b) => a.id.localeCompare(b.id));

  // Wenn keine offenen Trades: Auto-Setups aus echten DT-Strategien generieren
  let open = openDT;
  let auto_generated = false;
  if (openDT.length === 0 && dtStrategies.length > 0) {
    const today = new Date().toISOString().split('T')[0];
    // Nur aktive Strategien mit Conviction >= 2
    open = dtStrategies
      .filter(s => s.status === 'active' && s.conviction >= 2)
      .map((s, i) => ({
        id:         `DT-AUTO-${today}-${s.id}`,
        ticker:     null,
        strategy:   s.id,
        trade_type: 'day_trade',
        direction:  'LONG',
        entry:      null,
        setup_type: s.setup_type,
        trigger:    s.trigger,
        stop_pct:   s.stop_pct,
        target_pct: s.target_pct,
        crv:        s.crv,
        confidence: Math.round(40 + s.conviction * 10 + s.win_rate * 10),
        thesis:     s.thesis,
        status:     'WATCHING',
        generated:  new Date().toISOString(),
      }));
    auto_generated = true;
  }

  res.status(200).json({
    open,
    strategies:    dtStrategies,
    state,
    capital:       25000,
    pos_size:      5000,
    max_positions: 5,
    updated:       dna.updated || null,
    auto_generated,
  });
};
