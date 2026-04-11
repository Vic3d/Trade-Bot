#!/bin/bash
# TradeMind Watchdog — wird per Cron alle 5 Min ausgefuehrt
# Prueft ob Scheduler + API laufen, startet sie bei Bedarf neu
#
# Crontab: */5 * * * * /opt/trademind/deploy/watchdog-cron.sh >> /opt/trademind/data/watchdog.log 2>&1

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Scheduler pruefen
if ! systemctl is-active --quiet trademind-scheduler; then
    echo "[$TIMESTAMP] WARNUNG: Scheduler war gestoppt — starte neu..."
    systemctl restart trademind-scheduler
    sleep 2
    if systemctl is-active --quiet trademind-scheduler; then
        echo "[$TIMESTAMP] Scheduler erfolgreich neugestartet"
    else
        echo "[$TIMESTAMP] FEHLER: Scheduler konnte nicht gestartet werden!"
    fi
fi

# API pruefen
if ! systemctl is-active --quiet trademind-api; then
    echo "[$TIMESTAMP] WARNUNG: API war gestoppt — starte neu..."
    systemctl restart trademind-api
    sleep 2
    if systemctl is-active --quiet trademind-api; then
        echo "[$TIMESTAMP] API erfolgreich neugestartet"
    else
        echo "[$TIMESTAMP] FEHLER: API konnte nicht gestartet werden!"
    fi
fi

# Log-Rotation: watchdog.log auf 1000 Zeilen begrenzen
LOG="/opt/trademind/data/watchdog.log"
if [ -f "$LOG" ]; then
    LINES=$(wc -l < "$LOG")
    if [ "$LINES" -gt 1000 ]; then
        tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
fi
