#!/bin/bash
# Dashboard Healthcheck — kein AI nötig
RESP=$(curl -s --max-time 3 http://localhost:8080/api/prices 2>/dev/null)
if [ -z "$RESP" ]; then
    echo "Dashboard down — Neustart..."
    nohup python3 /data/.openclaw/workspace/scripts/dashboard_server.py > /tmp/tradevind-dashboard.log 2>&1 &
    echo "Neugestartet $(date)"
fi
