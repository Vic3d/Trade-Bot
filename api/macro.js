// API: GET /api/macro — Macro Dashboard (VIX, Yields, DXY, etc.)
// Sprint 5 | TradeMind Bauplan

const { execSync } = require('child_process');

module.exports = (req, res) => {
  try {
    const days = parseInt(req.query.days) || 30;
    const result = execSync(`python3 -c "
import sqlite3, json
conn = sqlite3.connect('/data/.openclaw/workspace/data/trading.db')
conn.row_factory = sqlite3.Row

indicators = ['VIX', 'WTI', 'BRENT', 'DXY', 'GOLD', 'US10Y', 'US2Y', 'COPPER', 'EURUSD', 'SP500', 'NASDAQ', 'BRENT_WTI_SPREAD', 'YIELD_SPREAD_2Y10Y']

result = {}
for ind in indicators:
    rows = conn.execute('''
        SELECT date, value, change_pct FROM macro_daily 
        WHERE indicator=? ORDER BY date DESC LIMIT ${days}
    ''', (ind,)).fetchall()
    if rows:
        result[ind] = {
            'current': rows[0]['value'],
            'prev': rows[1]['value'] if len(rows) > 1 else None,
            'change_pct': rows[0]['change_pct'],
            'history': [{'date': r['date'], 'value': r['value']} for r in rows]
        }

print(json.dumps(result, default=str))
conn.close()
"`, { timeout: 10000 }).toString().trim();
    
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).send(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
};
