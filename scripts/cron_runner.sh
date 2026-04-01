#!/bin/bash
# cron_runner.sh — Führt Python-Scripts aus ohne AI-Agent
# Bei DISCORD_ALERT im Output: schreibt in Alert-Queue für nächsten Briefing-Run
# Bei PEACE_SIGNAL / CRITICAL: schreibt in CEO-Trigger-Queue
#
# Usage: ./cron_runner.sh <script.py> [args...]

SCRIPT="$1"
shift
WS="/data/.openclaw/workspace"
QUEUE="$WS/data/ceo_trigger_queue.json"
ALERT_LOG="$WS/data/script_alerts.log"

if [ ! -f "$SCRIPT" ]; then
    echo "Script nicht gefunden: $SCRIPT" >&2
    exit 1
fi

# Script ausführen, Output capturen
OUTPUT=$(python3 "$SCRIPT" "$@" 2>&1)
EXIT_CODE=$?

# Timestamp
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SCRIPT_NAME=$(basename "$SCRIPT" .py)

# Bei Fehler loggen
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$TS] ERROR $SCRIPT_NAME (exit $EXIT_CODE): ${OUTPUT:0:200}" >> "$ALERT_LOG"
    exit $EXIT_CODE
fi

# KEIN_SIGNAL = nichts tun
if echo "$OUTPUT" | grep -q "KEIN_SIGNAL"; then
    exit 0
fi

# DISCORD_ALERT oder PEACE_SIGNAL → in CEO-Queue schreiben
if echo "$OUTPUT" | grep -qE "DISCORD_ALERT|PEACE_SIGNAL|ENTRY_SIGNAL|WATCH_CLOSELY"; then
    # Alert-Text extrahieren
    ALERT_TEXT=$(echo "$OUTPUT" | grep -A5 "DISCORD_ALERT\|PEACE_SIGNAL\|ENTRY_SIGNAL\|WATCH_CLOSELY" | head -6)
    
    # Priorität bestimmen
    PRIORITY="ALERT"
    echo "$OUTPUT" | grep -q "PEACE_SIGNAL" && PRIORITY="CRITICAL"
    echo "$OUTPUT" | grep -q "ENTRY_SIGNAL" && PRIORITY="ALERT"
    
    # In Queue schreiben via Python (JSON-safe)
    python3 -c "
import sys
sys.path.insert(0, '$WS/scripts')
from ceo_queue import enqueue
enqueue(
    source='$SCRIPT_NAME',
    priority='$PRIORITY',
    headline='''${ALERT_TEXT:0:200}'''.replace(\"'\", \"\"),
    detail='Auto-detected from script output',
    thesis=''
)
print('Queued: $PRIORITY from $SCRIPT_NAME')
" 2>/dev/null
    
    # Auch in Log
    echo "[$TS] $PRIORITY $SCRIPT_NAME: ${ALERT_TEXT:0:200}" >> "$ALERT_LOG"
fi

exit 0
