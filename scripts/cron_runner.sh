#!/bin/bash
# cron_runner.sh — Führt Python-Scripts aus, schreibt Alerts in pending_alerts.txt
# KEIN AI nötig. Läuft über system crontab.
#
# Usage: ./cron_runner.sh <script.py> [args...]

SCRIPT="$1"
shift
WS="/data/.openclaw/workspace"
ALERTS_FILE="$WS/data/pending_alerts.txt"
LOG="$WS/data/script_alerts.log"

if [ ! -f "$SCRIPT" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ERROR: $SCRIPT nicht gefunden" >> "$LOG"
    exit 1
fi

OUTPUT=$(python3 "$SCRIPT" "$@" 2>&1)
EXIT_CODE=$?
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
NAME=$(basename "$SCRIPT" .py)

if [ $EXIT_CODE -ne 0 ]; then
    echo "[$TS] ERROR $NAME (exit $EXIT_CODE): ${OUTPUT:0:200}" >> "$LOG"
    exit $EXIT_CODE
fi

# KEIN_SIGNAL = fertig
echo "$OUTPUT" | grep -q "KEIN_SIGNAL" && exit 0

# Alert gefunden → in pending_alerts.txt schreiben (Haiku Dispatcher liest das)
if echo "$OUTPUT" | grep -qE "DISCORD_ALERT|PEACE_SIGNAL|ENTRY_SIGNAL|STOP_HIT|WATCH_CLOSELY"; then
    ALERT_LINE=$(echo "$OUTPUT" | grep -A3 "DISCORD_ALERT\|PEACE_SIGNAL\|ENTRY_SIGNAL\|STOP_HIT\|WATCH_CLOSELY" | head -4)
    
    # Priorität
    PRIO="ALERT"
    echo "$OUTPUT" | grep -qE "PEACE_SIGNAL|DISCORD_ALERT:PEACE|DISCORD_ALERT:ESCALATION|STOP_HIT" && PRIO="CRITICAL"
    
    # In pending_alerts.txt anhängen (thread-safe via lockfile)
    {
        flock -w 5 200
        echo "[$TS] [$PRIO] [$NAME] $ALERT_LINE" >> "$ALERTS_FILE"
    } 200>"$ALERTS_FILE.lock"
    
    # Auch in CEO Queue
    python3 -c "
import sys; sys.path.insert(0, '$WS/scripts')
try:
    from ceo_queue import enqueue
    enqueue('$NAME', '$PRIO', '''$(echo "$ALERT_LINE" | head -1 | tr -d "'" | cut -c1-200)''')
except: pass
" 2>/dev/null
    
    echo "[$TS] $PRIO $NAME: ${ALERT_LINE:0:200}" >> "$LOG"
fi

exit 0
