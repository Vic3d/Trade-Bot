// API: GET /api/regime — Aktuelles Regime + Historie
// Sprint 5 | TradeMind Bauplan

const { execSync } = require('child_process');

module.exports = (req, res) => {
  try {
    const result = execSync(`python3 -c "
import sqlite3, json
conn = sqlite3.connect('/data/.openclaw/workspace/data/trading.db')
conn.row_factory = sqlite3.Row

# Aktuelles Regime
current = conn.execute('SELECT * FROM regime_history ORDER BY date DESC LIMIT 1').fetchone()

# Letzte 30 Tage
history = conn.execute('SELECT date, regime, vix, wti, gold FROM regime_history ORDER BY date DESC LIMIT 30').fetchall()

# Regime-Verteilung (letztes Jahr)
distribution = conn.execute('''
  SELECT regime, COUNT(*) as days, AVG(vix) as avg_vix
  FROM regime_history WHERE date > date(\"now\", \"-365 days\")
  GROUP BY regime ORDER BY days DESC
''').fetchall()

result = {
  'current': dict(current) if current else None,
  'history': [dict(r) for r in history],
  'distribution': [dict(r) for r in distribution],
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
