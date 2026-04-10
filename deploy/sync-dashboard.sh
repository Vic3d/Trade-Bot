#!/bin/bash
# sync-dashboard.sh — Synct Dashboard-Daten zum Vercel-Repo
# Wird via Cron alle 30 Min aufgerufen:
#   */30 * * * * /opt/trademind/deploy/sync-dashboard.sh >> /opt/trademind/data/sync.log 2>&1

set -e

TRADEMIND_HOME="/opt/trademind"
VENV="$TRADEMIND_HOME/venv/bin/python3.13"
DATA="$TRADEMIND_HOME/data"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TIMESTAMP] Dashboard sync gestartet..."

# 1. dashdata.json aus DB generieren
cd "$TRADEMIND_HOME"
$VENV -c "
import sqlite3, json
from pathlib import Path
from datetime import datetime, timezone

DB = Path('$DATA/trading.db')
OUT = Path('$DATA/dashdata.json')

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

# Offene Positionen
positions = [dict(r) for r in conn.execute('''
    SELECT ticker, strategy, entry_price, stop_price, target_price,
           conviction, entry_date, regime_at_entry, sector, style
    FROM paper_portfolio WHERE status=\"OPEN\"
    ORDER BY entry_date DESC
''').fetchall()]

# Performance
closed = conn.execute('''
    SELECT COUNT(*) as total,
           SUM(CASE WHEN pnl_eur > 0 THEN 1 ELSE 0 END) as wins,
           SUM(pnl_eur) as total_pnl
    FROM paper_portfolio WHERE status=\"CLOSED\"
''').fetchone()

# Regime
regime_row = conn.execute(
    'SELECT regime, vix FROM regime_history ORDER BY date DESC LIMIT 1'
).fetchone()

data = {
    'updated': datetime.now(timezone.utc).isoformat(),
    'positions': positions,
    'performance': {
        'total_trades': closed['total'] or 0,
        'wins': closed['wins'] or 0,
        'total_pnl': round(closed['total_pnl'] or 0, 2),
        'win_rate': round((closed['wins'] or 0) / max(closed['total'] or 1, 1) * 100, 1),
    },
    'regime': dict(regime_row) if regime_row else {'regime': 'UNKNOWN', 'vix': 0},
}

OUT.write_text(json.dumps(data, indent=2, default=str))
conn.close()
print(f'  dashdata.json geschrieben: {len(positions)} offene Positionen')
"

# 2. Git push zum Vercel-Repo (nur dashdata.json)
cd "$TRADEMIND_HOME"
if git diff --quiet data/dashdata.json 2>/dev/null; then
    echo "[$TIMESTAMP] Keine Änderungen — kein Push nötig."
else
    git add data/dashdata.json
    git commit -m "auto: dashboard sync $(date '+%H:%M')" --no-gpg-sign 2>/dev/null || true
    git push origin master 2>/dev/null && echo "[$TIMESTAMP] Push erfolgreich." || echo "[$TIMESTAMP] Push fehlgeschlagen."
fi

echo "[$TIMESTAMP] Dashboard sync fertig."
