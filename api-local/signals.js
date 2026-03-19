// API: GET /api/signals — Aktive Signale aus signals Tabelle
// Sprint 5 | TradeMind Bauplan

const { execSync } = require('child_process');

module.exports = (req, res) => {
  try {
    const result = execSync(`python3 -c "
import sqlite3, json
conn = sqlite3.connect('/data/.openclaw/workspace/data/trading.db')
conn.row_factory = sqlite3.Row
signals = conn.execute('''
  SELECT id, pair_id, lead_ticker, lag_ticker, signal_value,
         lead_price, lag_price_at_signal, lag_price_at_check, change_pct,
         outcome, regime_at_signal, vix_at_signal, accuracy_at_time,
         created_at, checked_at
  FROM signals ORDER BY created_at DESC LIMIT 50
''').fetchall()
print(json.dumps([dict(r) for r in signals]))
conn.close()
"`, { timeout: 10000 }).toString().trim();
    
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).send(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
