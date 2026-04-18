#!/usr/bin/env bash
# K10 — Externer Heartbeat-Watchdog (Phase 23)
# Installiert Cron-Job der alle 5min heartbeat_monitor.py aufruft.
#
# Idempotent: ersetzt vorhandenen Eintrag, fügt neue Zeile hinzu falls fehlt.
#
# Aufruf (auf Server, als root):
#   bash /opt/trademind/deploy/install-heartbeat-cron.sh
set -euo pipefail

CRON_LINE='*/5 * * * * /opt/trademind/venv/bin/python3 /opt/trademind/scripts/heartbeat_monitor.py >> /opt/trademind/data/heartbeat_monitor.log 2>&1'
SUDOERS_LINE='trademind ALL=(root) NOPASSWD: /bin/systemctl restart trademind-scheduler'
SUDOERS_FILE='/etc/sudoers.d/trademind-scheduler-restart'

# 1) Cron-Job für root installieren (heartbeat_monitor läuft als root, weil restart sudo braucht)
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'heartbeat_monitor.py' > "$TMP" || true
echo "$CRON_LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "✅ Cron-Job installiert:"
crontab -l | grep heartbeat_monitor || true

# 2) Sudoers-Regel für trademind-User (falls Heartbeat unter trademind läuft)
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
    chmod 0440 "$SUDOERS_FILE"
    visudo -c -f "$SUDOERS_FILE" && echo "✅ Sudoers-Regel installiert: $SUDOERS_FILE"
else
    echo "ℹ️  Sudoers-Regel existiert bereits: $SUDOERS_FILE"
fi

# 3) Test-Run (ohne --test, soll OK zurückgeben wenn scheduler läuft)
echo ""
echo "── Test-Run heartbeat_monitor.py ──"
/opt/trademind/venv/bin/python3 /opt/trademind/scripts/heartbeat_monitor.py || echo "(non-zero exit ok wenn scheduler down)"

echo ""
echo "✅ K10 Heartbeat-Watchdog aktiv (alle 5min, max 1 Alert/h)"
